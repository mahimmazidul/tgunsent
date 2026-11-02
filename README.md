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

## Which library to use

`requirements.txt` installs **kurigram** — an actively maintained fork of
Pyrogram. It ships the same `pyrogram` package and API, so `main.py` runs
unchanged; it just keeps the MTProto layer current.

| Library | API | State (Nov 2026) | MTProto layer | This script |
| --- | --- | --- | --- | --- |
| **kurigram 2.2.26** | Pyrogram | active — commits Oct 2026, PyPI Sep 2026 | **229** | works as-is |
| Telethon 1.45.0 | Telethon | most active — moved to [Codeberg](https://codeberg.org/Lonami/Telethon), layer 232 on master | 229+ | needs a port |
| pyrofork 2.3.69 | Pyrogram | archived mid-2026, frozen | 220 | works as-is |
| hydrogram | Pyrogram | repo active, PyPI stale (0.2.0, 2024) | 158 | untested |
| pyrogram 2.0.106 | Pyrogram | abandoned since Apr 2023 | 158 | works as-is |

Read that table carefully: **"archived on GitHub" does not mean dead.**
Telethon's GitHub repo is archived only because development moved to Codeberg —
it committed MTProto Layer 232 days ago and released 1.45.0 last month. Library
code does not rot the moment it stops being updated; what actually ages is the
MTProto layer, and old layers keep working for a long time.

Practical advice:

- **Want zero changes?** Stay on kurigram (`pip install kurigram tgcrypto`). All
  four cases are tested against it.
- **Want the most durable option?** Telethon — biggest project, newest layers,
  releases every few weeks. Its `TelegramClient(...)` takes `device_model`,
  `system_version`, `app_version`, `lang_code` and `system_lang_code` directly,
  and `lang_pack` is one attribute assignment (`client._init_request.lang_pack =
  "tdesktop"`), so the fingerprint above ports over cleanly. The handlers would
  need rewriting (`events.NewMessage`, `events.MessageEdited`,
  `events.MessageDeleted`, `events.Raw`), which is a single-file job.
- **Install exactly one of them.** `kurigram`, `pyrofork` and `pyrogram` all
  install a package named `pyrogram` and silently overwrite each other. Telethon
  can coexist, but do not run both against the same session.
- If a supply chain matters to you, pin with a hash: `pip install
  kurigram==2.2.26 --hash=sha256:...` (see `pip download`).

A static review of pyrofork 2.3.69 found no backdoor: the only outbound socket is
`asyncio.open_connection` in the TCP transport, aimed at Telegram DC addresses
(or your own proxy); no `os.environ` reads, no `eval`/`exec`/`subprocess`/`pickle`,
no HTTP client, no bundled binaries. The same lineage applies to kurigram, which
is a smaller diff on top of Pyrogram — treat it as evidence, not a guarantee.

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
