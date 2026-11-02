"""
Single-file Pyrogram userbot that watches ONE target user (TARGET_USER_ID) and
re-publishes what they do into LOG_CHAT_ID as log messages that THIS account
owns, so those log messages can always be edited later.
"""


import json
import os

from dotenv import load_dotenv
from pyrogram import Client, enums


load_dotenv()

API_ID = int(os.getenv("API_ID") or 0)
API_HASH = (os.getenv("API_HASH") or "").strip()
TARGET_USER_ID = int(os.getenv("TARGET_USER_ID") or 0)
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID") or 0)


CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")


# Realistic Telegram Desktop headers. Default Pyrogram headers are fingerprinted.
CLIENT_HEADERS = {
    "app_version": "9.3.3",
    "device_model": "Linux Desktop",
    "system_version": "Ubuntu 22.04",
    "lang_code": "en",
    "system_lang_code": "en-US",
}
try:
    app = Client("userbot", api_id=API_ID, api_hash=API_HASH, **CLIENT_HEADERS)
except TypeError:
    # Pyrogram 2.0.106 has no system_lang_code parameter; all other headers apply.
    CLIENT_HEADERS.pop("system_lang_code", None)
    app = Client("userbot", api_id=API_ID, api_hash=API_HASH, **CLIENT_HEADERS)


# Primary cache: "<namespace>:<message_id>" -> entry dict.
# cache.json is only a mirror; this dict is what the bot reads from.
cache = {}


# --------------------------------------------------------------------------- #
# cache.json helpers (stdlib json only)
# --------------------------------------------------------------------------- #
def load_cache():
    """Read cache.json once on startup."""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            cache.update(data)
    except FileNotFoundError:
        pass
    except Exception as error:
        print(f"[cache] could not read {CACHE_FILE}: {error}")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def cache_key(chat, message_id):
    """
    Key layout:
      channels / supergroups -> "<chat_id>:<message_id>"  (ids are namespaced per
        chat, and UpdateDeleteChannelMessages tells us the channel id)
      private chats / basic groups -> "basic:<message_id>", because
        UpdateDeleteMessages arrives WITHOUT a peer, so the bare id is all we
        ever get back for those.
    """
    if chat is not None and chat.type in (enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL):
        return f"{chat.id}:{message_id}"
    return f"basic:{message_id}"


def is_target(message):
    """True only for a real, non-service message authored by TARGET_USER_ID."""
    return bool(
        message.chat
        and message.chat.id != LOG_CHAT_ID  # never log our own log chat
        and message.from_user
        and message.from_user.id == TARGET_USER_ID
        and not message.service
    )


def content_of(message):
    """Plain text view of a message, used for the cache and the [DELETED] body."""
    return message.text or message.caption or "media"


async def send_log(text):
    """Send one fresh log message. Never raises."""
    try:
        return await app.send_message(
            LOG_CHAT_ID, text[:4096], disable_web_page_preview=True
        )
    except Exception as error:
        print(f"[log] send failed: {error}")
        return None


# --------------------------------------------------------------------------- #
# CASE 1: new text message from the target
# --------------------------------------------------------------------------- #
async def log_new_text(message, key):
    text = content_of(message)
    sent = await send_log(f"[NEW] {text}")
    if sent is None:
        return
    # We store OUR log message id, not the original one: that is the message we
    # are allowed to edit later when CASE 4 fires.
    cache[key] = {
        "log_chat": LOG_CHAT_ID,
        "log_id": sent.id,
        "kind": "text",
        "text": text,
        "deleted": False,
    }


# --------------------------------------------------------------------------- #
# on_message -> CASE 1
# --------------------------------------------------------------------------- #
@app.on_message()
async def on_new_message(client, message):
    """CASE 1: new text message from the target user."""
    try:
        if not is_target(message):
            return
        await log_new_text(message, cache_key(message.chat, message.id))
    except Exception as error:
        print(f"[case 1] skipped: {error}")


if __name__ == "__main__":
    print("WARNING: automating a user account can get it restricted or banned by "
          "Telegram. Use only on an account you can afford to lose.")
    load_cache()
    print(f"Loaded {len(cache)} cached message(s) from {CACHE_FILE}")
    app.run()
