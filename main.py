"""
Single-file Pyrogram userbot that watches ONE target user (TARGET_USER_ID) and
re-publishes what they do into LOG_CHAT_ID as log messages that THIS account
owns, so those log messages can always be edited later.
"""


import json
import os

from dotenv import load_dotenv
from pyrogram import Client


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


if __name__ == "__main__":
    print("WARNING: automating a user account can get it restricted or banned by "
          "Telegram. Use only on an account you can afford to lose.")
    load_cache()
    print(f"Loaded {len(cache)} cached message(s) from {CACHE_FILE}")
    app.run()
