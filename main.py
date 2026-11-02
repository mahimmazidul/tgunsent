#!/usr/bin/env python3

import asyncio
import json
import os
import signal

from dotenv import load_dotenv
from pyrogram import Client, enums, raw, utils

load_dotenv()

API_ID = int(os.getenv("API_ID") or 0)
API_HASH = (os.getenv("API_HASH") or "").strip()
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID") or 0)


def parse_targets():
    """
    TARGET_USERS=123:Alice,456:Bob   -> {123: "Alice", 456: "Bob"}
    TARGET_USER_ID=123 (legacy)     -> {123: "123"}

    The nickname is what appears in front of every log line, so several users can
    share one log chat without confusion.
    """
    targets = {}
    for item in (os.getenv("TARGET_USERS") or "").split(","):
        item = item.strip()
        if not item:
            continue
        user_id, _, nick = item.partition(":")
        try:
            uid = int(user_id.strip())
        except ValueError:
            print(f"[config] ignoring TARGET_USERS entry {item!r}: id is not a number")
            continue
        targets[uid] = nick.strip() or str(uid)
    if not targets:
        legacy = int(os.getenv("TARGET_USER_ID") or 0)
        if legacy:
            targets[legacy] = (os.getenv("TARGET_NICKNAME") or "").strip() or str(legacy)
    return targets


TARGETS = parse_targets()
TARGET_USER_ID = next(iter(TARGETS), 0)  # kept for the startup banner

# DEBUG=1 prints every update the account receives, including chat ids, which is
# how you discover TARGET_USER_ID and LOG_CHAT_ID. Off by default.
DEBUG = (os.getenv("DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")

# A delete update carries no sender. If the id is not in our cache we cannot know
# whose message it was, so by default nothing is written (otherwise your own
# deletions get reported as if they were the target's). Set to 1 to log
# "[DELETED] Message ID: N - no cached content" for those anyway.
LOG_UNKNOWN_DELETES = (os.getenv("LOG_UNKNOWN_DELETES") or "").strip().lower() in (
    "1", "true", "yes", "on")

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

# Announce lifecycle events in the log chat. A stopped process cannot send
# anything, so only graceful stops can be reported (Ctrl+C, SIGTERM from
# systemctl stop, SIGHUP from tmux kill-session). SIGKILL and power loss cannot.
NOTIFY_ON_STOP = (os.getenv("NOTIFY_ON_STOP") or "1").strip().lower() in (
    "1", "true", "yes", "on")
NOTIFY_ON_START = (os.getenv("NOTIFY_ON_START") or "0").strip().lower() in (
    "1", "true", "yes", "on")

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


def target_of(message):
    """Nickname of the watched user who sent this message, or None."""
    if (not message.chat
            or message.chat.id == LOG_CHAT_ID  # never log our own log chat
            or not message.from_user
            or message.service):
        return None
    return TARGETS.get(message.from_user.id)


def media_kind_of(message):
    """Return 'photo' / 'video' / 'document' / ... or None."""
    for kind in MEDIA_METHODS:
        if getattr(message, kind, None):
            return kind
    return None


def media_limits(message):
    """
    Describe what Telegram will refuse for this media, or None if it is ordinary.

    ttl_seconds marks "view once" / self-destructing media: the file reference is
    short lived, so it can neither be forwarded nor re-sent by file_id.
    has_protected_content ("restrict saving content") blocks forwarding too; a
    file_id re-send may still be refused, in which case we keep a placeholder.
    """
    ttl = getattr(message, "ttl_seconds", None)
    for kind in MEDIA_METHODS:
        media = getattr(message, kind, None)
        if media is not None and getattr(media, "ttl_seconds", None):
            ttl = getattr(media, "ttl_seconds")
            break
    if ttl:
        return f"self-destructing {ttl}s, not re-sendable"
    if getattr(message, "has_protected_content", False):
        return "protected content"
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


async def copy_media_log(chat_id, message_id, caption):
    """
    Server-side copy: get_messages() then message.copy(). This refetches the
    message, which mints a fresh file_reference, so it works when a plain
    file_id re-send fails with FILE_REFERENCE_EXPIRED. It is not a forward: the
    result is a normal message of ours with no "forwarded from" header.
    """
    try:
        return await app.copy_message(
            LOG_CHAT_ID, chat_id, message_id, caption=caption[:1024]
        )
    except Exception as error:
        print(f"[log] copy fallback failed: {error}")
        return None


# --------------------------------------------------------------------------- #
# CASE 1: new text message from the target
# --------------------------------------------------------------------------- #
async def log_new_text(message, key, who):
    text = content_of(message)
    sent = await send_log(f"[NEW] {who}: {text}")
    if sent is None:
        return
    # We store OUR log message id, not the original one: that is the message we
    # are allowed to edit later when CASE 4 fires.
    dbg(f"cached new text id={message.id} as {key} -> log message {sent.id}")
    cache[key] = {
        "log_chat": LOG_CHAT_ID,
        "log_id": sent.id,
        "kind": "text",
        "user": who,
        "text": text,
        "deleted": False,
    }
    save_cache()


# --------------------------------------------------------------------------- #
# CASE 3: new media message from the target (photo / video / document / ...)
# --------------------------------------------------------------------------- #
async def log_new_media(message, key, kind, who):
    limit = media_limits(message)
    caption = f"[NEW - {kind}] {who}"
    if message.caption:
        caption = f"{caption}\n{message.caption}"

    note = None
    if limit and limit.startswith("self-destructing"):
        # Telegram never hands this file over again, so do not even try to send
        # it: log the event, the caption and why the file is missing.
        dbg(f"id={message.id} is once-view media ({limit})")
        note = limit
        sent = await send_log(f"{caption}\n({note})")
    else:
        sent = await send_media_log(kind, getattr(message, kind).file_id, caption)
        if sent is None:
            # Most common cause: a stale file_reference (expired, or single-use
            # for once-view media). copy_message refetches and retries.
            dbg(f"id={message.id} file_id re-send refused, trying copy")
            sent = await copy_media_log(message.chat.id, message.id, caption)
        if sent is None:
            # Protected content or the message is gone: keep a trace anyway.
            note = limit or "not re-sent"
            dbg(f"id={message.id} media not re-sent ({note})")
            sent = await send_log(f"{caption}\n({note})")

    if sent is None:
        return

    cache[key] = {
        "log_chat": LOG_CHAT_ID,
        "log_id": sent.id,
        "kind": kind,  # media log messages can only be edited as a caption
        "user": who,
        "text": f"media ({note})" if note else content_of(message),
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
        who = target_of(message)
        if who is None:
            dbg(f"skip id={message.id}: {sender} is not a watched user")
            return
        dbg(f"watched user {sender} -> nickname {who!r}")
        key = cache_key(message.chat, message.id)
        kind = media_kind_of(message)
        if kind:
            await log_new_media(message, key, kind, who)  # CASE 3
        else:
            await log_new_text(message, key, who)  # CASE 1
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
        who = target_of(message)
        if who is None:
            return
        key = cache_key(message.chat, message.id)
        entry = cache.get(key)
        before = entry["text"] if entry else "(not in cache)"
        after = content_of(message)
        sent = await send_log(f"[EDITED] {who}\nBefore: {before}\nAfter: {after}")
        if sent is None:
            return
        if entry is None:
            cache[key] = {
                "log_chat": LOG_CHAT_ID,
                "log_id": sent.id,
                "kind": "text",
                "user": who,
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
    who = entry.get("user")
    label = f"{who}: {was}" if who else was
    dbg(f"delete matched {key} ({who}) -> editing log message {entry.get('log_id')}")
    try:
        if entry.get("kind") == "text":
            await app.edit_message_text(
                entry["log_chat"], entry["log_id"], f"[DELETED] {label}"[:4096]
            )
        else:
            # A media log message only accepts caption edits.
            await app.edit_message_caption(
                entry["log_chat"], entry["log_id"], f"[DELETED] {label}"[:1024]
            )
    except Exception as error:
        # Too old / not editable / no permission: fall back to a fresh message.
        print(f"[case 4] edit failed ({error}), sending a new message")
        await send_log(f"[DELETED] {label}")
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

        unknown = [mid for mid in ids if mid not in matched]
        if unknown:
            shown = ", ".join(str(mid) for mid in unknown[:20])
            dbg(f"delete: {len(ids)} id(s), {len(matched)} matched, "
                f"{len(unknown)} not cached ({shown}) -> ignored, sender unknown")
        else:
            dbg(f"delete: {len(ids)} id(s), all {len(matched)} matched in cache")

        if unknown and LOG_UNKNOWN_DELETES:
            for mid in unknown:
                await send_log(f"[DELETED] Message ID: {mid} — no cached content")
    except Exception as error:
        print(f"[case 4] skipped: {error}")


# --------------------------------------------------------------------------- #
# lifecycle notice: "[STOPPED] forwarding stopped" on a graceful shutdown
# --------------------------------------------------------------------------- #
async def serve():
    """
    Start the client, wait for a stop signal, announce it while still connected,
    then stop. A hard kill cannot reach this code, so nothing is sent then.
    """
    await app.start()

    if NOTIFY_ON_START:
        await send_log("[STARTED] forwarding resumed")

    stop = asyncio.Event()
    fired = {"name": "shutdown"}

    def on_signal(signum, _frame=None):
        fired["name"] = signal.Signals(signum).name
        stop.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            loop.add_signal_handler(sig, on_signal, sig)
        except (NotImplementedError, RuntimeError) as error:
            print(f"[lifecycle] cannot hook {sig!r}: {error}")

    try:
        await stop.wait()
    finally:
        if NOTIFY_ON_STOP:
            # Sent before the client goes away; skipped if the network is gone.
            await send_log(f"[STOPPED] forwarding stopped ({fired['name']})")
        await app.stop()


# --------------------------------------------------------------------------- #
# startup
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    if not (API_ID and API_HASH and TARGETS and LOG_CHAT_ID):
        raise SystemExit(
            "Fill API_ID, API_HASH, TARGET_USERS (or TARGET_USER_ID) and "
            "LOG_CHAT_ID in .env first."
        )
    print("WARNING: automating a user account can get it restricted or banned by "
          "Telegram. Use only on an account you can afford to lose.")
    load_cache()
    print(f"Loaded {len(cache)} cached message(s) from {CACHE_FILE}")
    watched = ", ".join(f"{nick} ({uid})" for uid, nick in TARGETS.items())
    print(f"Tracking {len(TARGETS)} user(s): {watched}")
    print(f"Log chat: {LOG_CHAT_ID}")
    if DEBUG:
        print("DEBUG is on: every message prints chat=<id> from=<user id>. Send "
              "something in the group you want to log to, then copy chat=<id> "
              "into LOG_CHAT_ID.")
    app.loop.run_until_complete(serve())
