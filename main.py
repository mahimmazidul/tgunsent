"""Target-user message logger. Repository owner: mahimmazidul (github.com/mahimmazidul)."""
import asyncio
import os

from dotenv import load_dotenv
from pyrogram import Client, enums, raw
from pyrogram.errors import FloodWait, RPCError

load_dotenv()
try:
    API_ID = int(os.environ["API_ID"])
    API_HASH = os.environ["API_HASH"].strip()
    TARGET_USER_ID = int(os.environ["TARGET_USER_ID"])
    LOG_CHAT_ID = int(os.environ["LOG_CHAT_ID"])
    if not API_HASH or API_ID <= 0 or TARGET_USER_ID <= 0:
        raise ValueError("Invalid configuration")
except (KeyError, ValueError):
    raise SystemExit("Set valid API_ID, API_HASH, TARGET_USER_ID and LOG_CHAT_ID in .env")

# One worker preserves update order, including while a forward is in progress.
app = Client("username", api_id=API_ID, api_hash=API_HASH, workers=1, sleep_threshold=0)
cache = {}  # (channel id or None, message id) -> original text and log message id


def key_for(message):
    # Non-channel message IDs share the account's namespace; channel IDs do not.
    channel = message.chat.id if message.chat.type in (
        enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL
    ) else None
    return channel, message.id


def target_message(message):
    return (message.chat and message.chat.id != LOG_CHAT_ID and message.from_user
            and message.from_user.id == TARGET_USER_ID and not message.service)


def text_of(message):
    return str(message.text or message.caption or "[No text or caption]")


async def attempt(operation, *args, **kwargs):
    # Respect Telegram's wait; do not retry indefinitely or try to evade limits.
    for attempt_number in range(2):
        try:
            return await operation(*args, **kwargs)
        except FloodWait as error:
            if attempt_number:
                print("Telegram requested another wait; operation skipped.")
                return None
            await asyncio.sleep(error.value)
        except RPCError:
            return None  # Includes permission errors and unavailable messages.
        except Exception as error:
            print(f"Operation failed: {type(error).__name__}")
            return None


# Case 1: forward a newly received target-user message.
@app.on_message()
async def on_new(client, message):
    if not target_message(message):
        return
    key = key_for(message)
    if key in cache:
        return
    cache[key] = {"original": text_of(message), "log_id": None, "deleted": False}
    forwarded = await attempt(client.forward_messages, LOG_CHAT_ID, message.chat.id, message.id)
    if forwarded:
        cache[key]["log_id"] = forwarded.id


# Case 2: send the edited text, with the initially observed original if available.
@app.on_edited_message()
async def on_edit(client, message):
    if not target_message(message):
        return
    entry = cache.get(key_for(message))
    original = entry["original"] if entry else "[Not cached]"
    content = (f"[EDITED] Chat {message.chat.id}, message {message.id}\n"
               f"Original:\n{original}\n\nNew:\n{text_of(message)}")
    # Split long edits rather than silently truncating either version.
    while content:
        chunk, content = content[:3500], content[3500:]
        await attempt(client.send_message, LOG_CHAT_ID, chunk,
                      parse_mode=enums.ParseMode.DISABLED, disable_web_page_preview=True)


# Case 3: try to edit the forwarded copy if Telegram allows it; never send a new message.
@app.on_raw_update(group=1)
async def on_delete(client, update, users, chats):
    if isinstance(update, raw.types.UpdateDeleteChannelMessages):
        channel = int(f"-100{update.channel_id}")
    elif isinstance(update, raw.types.UpdateDeleteMessages):
        channel = None
    else:
        return
    for message_id in update.messages:
        entry = cache.get((channel, message_id))
        if not entry or entry["deleted"]:
            continue
        entry["deleted"] = True
        if entry["log_id"]:
            # Forwarded messages normally cannot be edited; this is best effort only.
            await attempt(client.edit_message_text, LOG_CHAT_ID, entry["log_id"],
                          "[DELETED]\n" + entry["original"][:4000],
                          parse_mode=enums.ParseMode.DISABLED)


if __name__ == "__main__":
    print("Starting target-user logger. Sign in when prompted.")
    app.run()
