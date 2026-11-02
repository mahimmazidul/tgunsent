#!/usr/bin/env python3

import json
import os

from dotenv import load_dotenv
from pyrogram import Client, enums, raw, utils

load_dotenv()

API_ID = int(os.getenv("API_ID") or 0)
API_HASH = (os.getenv("API_HASH") or "").strip()
TARGET_USER_ID = int(os.getenv("TARGET_USER_ID") or 0)
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID") or 0)

# DEBUG=1 prints every update the account receives, including chat ids, which is
# how you discover TARGET_USER_ID and LOG_CHAT_ID. Off by default.
DEBUG = (os.getenv("DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")

# One single, self-consistent Telegram Desktop identity. Telegram compares these
# strings with lang_pack during login, so they must describe one real client.
FINGERPRINT = {
    "device_model": "Desktop",
    "system_version": "Windows 10",
    "app_version": "5.12.3 x64",
    "lang_code": "en",
    "system_lang_code": "en-US",
    "lang_pack": "tdesktop",
}

try:
    # Pyrofork (and future Pyrogram builds) accept lang_pack and system_lang_code.
    app = Client("userbot", api_id=API_ID, api_hash=API_HASH, **FINGERPRINT)
except TypeError:
    # Stock Pyrogram 2.0.106 does not: those two fields get patched in below.
    options = {k: v for k, v in FINGERPRINT.items()
               if k not in ("lang_pack", "system_lang_code")}
    app = Client("userbot", api_id=API_ID, api_hash=API_HASH, **options)


def patch_init_connection():
    """
    Stock Pyrogram hardcodes lang_pack="" and system_lang_code=lang_code in
    pyrogram/session/session.py, and Pyrofork lowercases everything it is given
    ("en-US" becomes "en-us"). Rewriting the payload keeps the exact strings.
    """
    try:
        original = raw.functions.InitConnection

        def init_connection(**kwargs):
            kwargs["lang_pack"] = FINGERPRINT["lang_pack"]
            kwargs["system_lang_code"] = FINGERPRINT["system_lang_code"]
            return original(**kwargs)

        raw.functions.InitConnection = init_connection
    except Exception as error:
        print(f"[fingerprint] lang_pack patch skipped: {error}")


patch_init_connection()

# Primary cache: "<namespace>:<message_id>" -> entry dict.
# cache.json is only a mirror; this dict is what the bot reads from.
cache = {}

# kurigram deprecates disable_web_page_preview in favour of link_preview_options;
# stock Pyrogram only knows the old flag. Pick whichever this install supports.
try:
    from pyrogram.types import LinkPreviewOptions

    LINK_PREVIEW = {"link_preview_options": LinkPreviewOptions(is_disabled=True)}
except Exception:
    LINK_PREVIEW = {"disable_web_page_preview": True}

# Media kinds we can re-send straight from a file_id, mapped to the client method.
MEDIA_METHODS = {
    "photo": "send_photo",
    "video": "send_video",
    "document": "send_document",
    "animation": "send_animation",
    "audio": "send_audio",
    "voice": "send_voice",
}


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


def save_cache():
    """Write cache.json after every mutation (atomic, so a crash cannot truncate)."""
    try:
        tmp = f"{CACHE_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, ensure_ascii=False)
        os.replace(tmp, CACHE_FILE)
    except Exception as error:
        print(f"[cache] could not write {CACHE_FILE}: {error}")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def dbg(text):
    """Print diagnostics only when DEBUG=1."""
    if DEBUG:
        print(f"[dbg] {text}")


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


def media_kind_of(message):
    """Return 'photo' / 'video' / 'document' / ... or None."""
    for kind in MEDIA_METHODS:
        if getattr(message, kind, None):
            return kind
    return None


def content_of(message):
    """Plain text view of a message, used for the cache and the [DELETED] body."""
    return message.text or message.caption or "media"


async def send_log(text):
    """Send one fresh log message. Never raises."""
    try:
        return await app.send_message(LOG_CHAT_ID, text[:4096], **LINK_PREVIEW)
    except Exception as error:
        print(f"[log] send failed: {error}")
        return None


async def send_media_log(kind, file_id, caption):
    """Re-send media we own, straight from its file_id (works for protected content)."""
    try:
        return await getattr(app, MEDIA_METHODS[kind])(
            LOG_CHAT_ID, file_id, caption=caption[:1024]
        )
    except Exception as error:
        print(f"[log] {kind} re-send failed: {error}")
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
    dbg(f"cached new text id={message.id} as {key} -> log message {sent.id}")
    cache[key] = {
        "log_chat": LOG_CHAT_ID,
        "log_id": sent.id,
        "kind": "text",
        "text": text,
        "deleted": False,
    }
    save_cache()


# --------------------------------------------------------------------------- #
# CASE 3: new media message from the target (photo / video / document / ...)
# --------------------------------------------------------------------------- #
async def log_new_media(message, key, kind):
    caption = f"[NEW - {kind}]"
    if message.caption:
        caption = f"{caption}\n{message.caption}"
    sent = await send_media_log(kind, getattr(message, kind).file_id, caption)
    if sent is None:
        # Media could not be re-sent: still leave a trace in the log chat.
        caption = f"[NEW - {kind}] (not re-sent)"
        sent = await send_log(caption)
        if sent is None:
            return
    cache[key] = {
        "log_chat": LOG_CHAT_ID,
        "log_id": sent.id,
        "kind": kind,  # media log messages can only be edited as a caption
        "text": content_of(message),
        "deleted": False,
    }
    save_cache()


# --------------------------------------------------------------------------- #
# on_message -> CASE 1 and CASE 3
# --------------------------------------------------------------------------- #
@app.on_message()
async def on_new_message(client, message):
    """CASE 1 (text) and CASE 3 (media) for the target user."""
    try:
        sender = message.from_user.id if message.from_user else "channel/anonymous"
        dbg(f"message chat={message.chat.id} ({message.chat.type}) "
            f"from={sender} id={message.id}")
        if message.chat and message.chat.id == LOG_CHAT_ID:
            dbg(f"skip id={message.id}: it is inside the log chat")
            return
        if not is_target(message):
            dbg(f"skip id={message.id}: sender is not TARGET_USER_ID")
            return
        key = cache_key(message.chat, message.id)
        kind = media_kind_of(message)
        if kind:
            await log_new_media(message, key, kind)  # CASE 3
        else:
            await log_new_text(message, key)  # CASE 1
    except Exception as error:
        print(f"[case 1/3] skipped: {error}")


# --------------------------------------------------------------------------- #
# CASE 2: the target edits a message
# --------------------------------------------------------------------------- #
@app.on_edited_message()
async def on_edited_message(client, message):
    """CASE 2: a brand new log message, never an edit of the previous log."""
    try:
        sender = message.from_user.id if message.from_user else "channel/anonymous"
        dbg(f"edited chat={message.chat.id} from={sender} id={message.id}")
        if not is_target(message):
            return
        key = cache_key(message.chat, message.id)
        entry = cache.get(key)
        before = entry["text"] if entry else "(not in cache)"
        after = content_of(message)
        sent = await send_log(f"[EDITED]\nBefore: {before}\nAfter: {after}")
        if sent is None:
            return
        if entry is None:
            cache[key] = {
                "log_chat": LOG_CHAT_ID,
                "log_id": sent.id,
                "kind": "text",
                "text": after,
                "deleted": False,
            }
        else:
            # Keep the cache current so a later delete shows the real text.
            entry["text"] = after
        save_cache()
    except Exception as error:
        print(f"[case 2] skipped: {error}")


# --------------------------------------------------------------------------- #
# CASE 4: deletion -> edit the cached log message, prefix it with [DELETED]
# --------------------------------------------------------------------------- #
async def mark_deleted(key):
    """Edit the log message we own so the deletion shows up in place."""
    entry = cache.get(key)
    if not entry or entry.get("deleted"):
        return
    entry["deleted"] = True
    was = entry.get("text") or "media"
    dbg(f"delete matched {key} -> editing log message {entry.get('log_id')}")
    try:
        if entry.get("kind") == "text":
            await app.edit_message_text(
                entry["log_chat"], entry["log_id"], f"[DELETED]\nContent was: {was}"[:4096]
            )
        else:
            # A media log message only accepts caption edits.
            await app.edit_message_caption(
                entry["log_chat"], entry["log_id"], f"[DELETED] Content was: {was}"[:1024]
            )
    except Exception as error:
        # Too old / not editable / no permission: fall back to a fresh message.
        print(f"[case 4] edit failed ({error}), sending a new message")
        await send_log(f"[DELETED]\nContent was: {was}")
    save_cache()


@app.on_raw_update(group=1)
async def on_raw_update(client, update, users, chats):
    """CASE 4: Telegram never names the deleter; we only match ids from our cache."""
    try:
        if not isinstance(update, (raw.types.UpdateDeleteMessages,
                                  raw.types.UpdateDeleteChannelMessages)):
            return

        ids = list(getattr(update, "messages", []) or [])
        dbg(f"delete update {type(update).__name__} "
            f"chat={getattr(update, 'channel_id', '-')} ids={ids}")
        if isinstance(update, raw.types.UpdateDeleteChannelMessages):
            prefix = f"-100{update.channel_id}"
            matched = {mid: f"{prefix}:{mid}" for mid in ids if f"{prefix}:{mid}" in cache}
        elif isinstance(update, raw.types.UpdateDeleteMessages):
            # No peer information at all: match on the message id alone. We only
            # watch one user, so if the id is in our cache it is theirs.
            wanted = set(ids)
            matched = {}
            for cached_key in list(cache.keys()):
                try:
                    mid = int(cached_key.rsplit(":", 1)[1])
                except (IndexError, ValueError):
                    continue
                if mid in wanted:
                    matched[mid] = cached_key
        else:
            return

        for key in matched.values():
            await mark_deleted(key)
        for mid in ids:
            if mid not in matched:
                dbg(f"delete id={mid} has no cache entry")
                await send_log(f"[DELETED] Message ID: {mid} — no cached content")
    except Exception as error:
        print(f"[case 4] skipped: {error}")


# --------------------------------------------------------------------------- #
# startup
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    if not (API_ID and API_HASH and TARGET_USER_ID and LOG_CHAT_ID):
        raise SystemExit(
            "Fill API_ID, API_HASH, TARGET_USER_ID and LOG_CHAT_ID in .env first."
        )
    print("WARNING: automating a user account can get it restricted or banned by "
          "Telegram. Use only on an account you can afford to lose.")
    load_cache()
    print(f"Loaded {len(cache)} cached message(s) from {CACHE_FILE}")
    print(f"Tracking user {TARGET_USER_ID} -> log chat {LOG_CHAT_ID}")
    if DEBUG:
        print("DEBUG is on: every message prints chat=<id> from=<user id>. Send "
              "something in the group you want to log to, then copy chat=<id> "
              "into LOG_CHAT_ID.")
    app.run()
