# tgunsent

Minimal Pyrogram userbot that watches **one** user (`TARGET_USER_ID`) and logs
their activity into `LOG_CHAT_ID`: new text (`[NEW]`), edits (`[EDITED]` with
before/after), photos/videos/documents (re-sent with a `[NEW - photo]` caption)
and deletions (`[DELETED]` edited onto the log message we own).

Nothing is ever forwarded — every log message is re-sent by this account, so it
can always be edited later. Content is cached in `cache.json` (stdlib `json`),
which survives restarts and lets a bare delete update be resolved backwards.

## Where to get `API_ID` and `API_HASH`

These come from your **own Telegram account**, not from @BotFather:

1. Open <https://my.telegram.org> and log in with the phone number of the
   account that will run the bot (the login code arrives in the Telegram app).
2. Click **API development tools**.
3. Fill the form with anything sensible — *App title* `tgunsent`, *Short name*
   `tgunsent`, *Platform* **Desktop** — and press **Create application**.
4. Copy two values into `.env`:
   - **App api_id** → a number, e.g. `1234567` → `API_ID`
   - **App api_hash** → 32 hex characters → `API_HASH`

Notes:

- The hash is a secret, exactly like a password. Never commit it, screenshot it
  or paste it in an issue; if it leaks, delete the app on that page and make a
  new one.
- Ids are bound to the account that created them, and a new pair can only be
  created a few times per account. Do not use someone else's pair — Telegram
  may restrict both accounts.
- `TARGET_USER_ID` is the numeric id of the watched user (get it via
  @userinfobot or any "my id" bot). `LOG_CHAT_ID` is the numeric id of your log
  chat/channel and usually starts with `-100`.

## Run on a seedbox (no root)

```bash
cp .env.example .env && nano .env     # fill API_ID, API_HASH, TARGET_USER_ID, LOG_CHAT_ID
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
screen -S userbot
python main.py                        # first run: phone, login code, 2FA password
# detach: Ctrl+A then D — reattach later with: screen -r userbot
```

## Client fingerprint

Telegram compares `device_model`, `system_version`, `app_version`, `lang_code`
and `lang_pack` during the login handshake, so those values have to describe one
real client. Stock Pyrogram sends `device_model="CPython 3.13.x"`,
`app_version="Pyrogram 2.0.106"`, `lang_pack=""` and
`system_lang_code = lang_code` — a fingerprint no official app produces.

`FINGERPRINT` in `main.py` holds one consistent Telegram Desktop identity
(`Desktop` / `Windows 10` / `5.12.3 x64` / `en` / `en-US` / `tdesktop`) and is
passed straight to `Client()`. `patch_init_connection()` then rewrites
`lang_pack` and `system_lang_code` on the outgoing `InitConnection` so the exact
strings go out, because stock Pyrogram hardcodes those two fields and Pyrofork
lowercases them (`en-US` → `en-us`). Both paths are tested.

If you want generated, randomised official-client fingerprints for every field,
that is what [opentele2](https://github.com/thedemons/opentele) does — but it is
Telethon-based, so it cannot be mixed into this script.

## Pyrofork vs Pyrogram

`requirements.txt` installs **Pyrofork** (`pyrofork==2.3.69`), a maintained fork
of Pyrogram. It installs the same `pyrogram` package, so `main.py` needs no
changes; it just adds `lang_pack` / `system_lang_code` as real `Client`
arguments, plus topics, stories, quote replies and an optional Mongo session
store. Notes:

- **Do not install both libraries in one venv** — each ships a package named
  `pyrogram` and they will overwrite each other.
- Requires **Python >= 3.10**; use `tgcrypto-pyrofork` for the AES speedup.
- Extra transitive dependency `pymediainfo-pyrofork` (pure Python, used only for
  media groups / paid media).
- The upstream GitHub repo was **archived in mid-2026** and the last PyPI release
  is 2.3.69 (Dec 2025), so treat it as frozen rather than actively developed.
- Pin and verify if you care about supply chain:
  `pyrofork==2.3.69 --hash=sha256:13f7a7fbfa5ede230df6b6df10fcc2c6b33b4c3d75bf2088a7d32f41621df8e4`
  (the wheel published on PyPI).

A static review of that wheel found no backdoor: the only outbound socket is
`asyncio.open_connection` in `connection/transport/tcp/tcp.py`, aimed at
Telegram DC addresses (or your own proxy); there are no reads of `os.environ` or
`~`, no `eval`/`exec`/`subprocess`/`pickle`, no HTTP client, no bundled
binaries, and the crypto/session/storage modules differ from upstream Pyrogram
only by licence headers and ordinary features. That is evidence, not a
guarantee — read the source if your threat model demands it.

## Files

| File | Purpose |
| --- | --- |
| `main.py` | The whole bot (flat functions, one handler per case). |
| `requirements.txt` | Pyrofork + tgcrypto + python-dotenv (see the swap note inside). |
| `.env` | Secrets; never commit it. |
| `cache.json` | Message cache, written after every change. |
| `userbot.session` | Pyrogram's SQLite login session; keep it private. |

## Notes

- Telegram does not say *who* deleted a message. The bot only watches one user,
  so a cached id is enough to attribute it.
- Delete notices may arrive without any peer information (private chats); those
  ids are matched on their own, channel ids are namespaced per chat.
- Protected / no-forward content still works, because media is re-sent from its
  `file_id` instead of being forwarded.
- If a deletion notice matches nothing in the cache, the log gets
  `[DELETED] Message ID: <id> — no cached content`.
- All handler exceptions are swallowed and printed; permission errors never
  crash the bot.
- Automating a user account can get it restricted or banned. Use an account you
  can afford to lose, and only log chats you are allowed to keep.
