# tgunsent

Minimal Pyrogram userbot that watches **one or more** users (`TARGET_USERS`) and logs
their activity into `LOG_CHAT_ID`: new text (`[NEW]`), edits (`[EDITED]` with
before/after), photos/videos/documents (re-sent with a `[NEW - photo]` caption)
and deletions — the original log message is edited to
`[DELETED] <last known content>`.

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
# detach: Ctrl+A then D — reattach later with: screen -r system
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

## Finding `LOG_CHAT_ID` and `TARGET_USER_ID`

Set `DEBUG=1` in `.env` and run the bot. It prints one line per event, with the
ids you need, and stays quiet about everything else:

```
[dbg] message chat=123456789 (ChatType.PRIVATE) from=123456789 id=40074
[dbg] cached new text id=40074 as basic:40074 -> log message 1
[dbg] delete update UpdateDeleteMessages chat=- ids=[40074]
[dbg] delete matched basic:40074 -> editing log message 1
```

- `chat=` is the id for `LOG_CHAT_ID` (the chat that receives logs).
- `from=` is the id for `TARGET_USER_ID` (the user being watched).
- `skip …` lines say *why* something was ignored: inside the log chat, or a
  sender that is not the target.

Only delete updates are reported on the raw channel — `UpdateNewMessage`,
`UpdateUserStatus` and friends carry no message list and are skipped silently,
which is why they look like `ids=[]` if anything prints them at all.

## What can be a log chat

Anything your account can post to:

| Log chat | `LOG_CHAT_ID` looks like | Notes |
| --- | --- | --- |
| **Saved Messages** | your own user id, `123456789` | Simplest and most private. |
| Private group / supergroup | `-100…` (supergroup) or `-123456789` | You must be a member; mute is fine. |
| Channel | `-100…` | You need admin/post rights. |
| Chat with a bot | the bot's user id | Works; handy for archiving. |

Not usable: Secret Chats (they never deliver update events) and channels where
you have no posting rights. If posting fails you will see
`[log] send failed: CHAT_WRITE_FORBIDDEN` in the console.

**Only this one user is mirrored.** Messages you send from the bot's own account
are never logged, and edits/deletes only count when they come from
`TARGET_USER_ID`.

## Updating the running bot

`git pull` only changes files on disk — the running process keeps using the code
it loaded at start. Stop, pull, start:

```bash
cd /path/to/tgunsent                    # wherever you cloned it

# 1. stop it (this sends [STOPPED] to the log chat, then disconnects)
tmux kill-session -t system

# 2. pull the new code
git pull

# 3. only if requirements.txt changed
source .venv/bin/activate && pip install -r requirements.txt

# 4. start it again
tmux new -d -s system 'cd /path/to/tgunsent && .venv/bin/python main.py'
tmux ls                                  # confirm it is running
```

Check the update landed before restarting:

```bash
git log --oneline -3
git rev-parse --short HEAD               # compare with the commit you expected
```

If `git pull` refuses because you edited `main.py` locally, either keep your edits
(`git stash && git pull && git stash pop`) or throw them away
(`git checkout -- main.py && git pull`). `.env`, `cache.json` and
`userbot.session` are gitignored, so a pull never touches your secrets, cache or
login.

Watching it after a restart:

```bash
tmux attach -t system                    # Ctrl+B then D to detach again
```

## Files

| File | Purpose |
| --- | --- |
| `main.py` | The whole bot (flat functions, one handler per case). |
| `requirements.txt` | Pyrofork + tgcrypto + python-dotenv (see the swap note inside). |
| `.env` | Secrets; never commit it. |
| `cache.json` | Message cache, written after every change. |
| `userbot.session` | Pyrogram's SQLite login session; keep it private. |

## Self-destructing and protected media

**No library can forward or re-send them — that is server-side, not a Pyrogram
limitation.** Once-view media (`ttl_seconds`) is handed out with a short-lived
file reference; forwarding it, downloading it or re-sending its `file_id` is
refused by Telegram. Chats with "restrict saving content" (`has_protected_content`)
block forwarding the same way.

What this bot does instead:

| Situation | Log chat gets |
| --- | --- |
| once-view photo/video | the event, its caption, and `(self-destructing 5s, not re-sendable)` |
| normal photo/video/document | the actual media, re-sent by `file_id` |
| `file_id` refused (`FILE_REFERENCE_EXPIRED`) | retried automatically with `copy_message`, which refetches the message and mints a fresh file reference |
| protected chat / message already gone | `[NEW - photo]` + `(protected content)` / `(not re-sent)` |

File references expire, and once-view media uses single-use ones. That is what
`FILE_REFERENCE_EXPIRED` means. The fallback is `copy_message()`, which is
`get_messages()` + `message.copy()`: it fetches the message again for a valid
reference and re-sends it as **our own** message — no "forwarded from" header, and
still fully editable, so it is not a forward.

So you still get *who sent what, when, with which caption* — you just never get a
copy of the file, because Telegram will not give it to you. If the deletion event
arrives later, the log message becomes
`[DELETED] media (self-destructing 5s, not re-sendable)`.

**Secret Chats are not supported at all.** They are end-to-end encrypted with a
separate protocol, and Pyrogram never sees their messages, so nothing can be
logged from them.

## Keeping it running, and what happens on a disconnect

**"Offline" does not mean disconnected.** Online status is only a flag; API calls
work regardless, so the bot posts to the log chat whether you appear online or
offline. A running bot with `offline` status is the normal, intended state.

If the connection does drop, three layers handle it:

1. **Auto-reconnect.** The session restarts itself on a null packet or transport
   error; short flood waits are slept off automatically.
2. **Gap recovery (kurigram only).** kurigram stores the update state in
   `userbot.session` and calls `recover_gaps()` when the dispatcher starts, which
   pulls `updates.GetDifference` and replays what arrived while you were down — so
   messages sent during an outage still get logged once it reconnects. Stock
   Pyrogram 2.0.106 has no such code, and pyrofork stores the state but never
   reads it back. This is the strongest practical reason to stay on kurigram.
3. **Hard limits.** Telegram only keeps differences for a limited window. If the
   bot was down long enough, the stored `pts` expires
   (`PersistentTimestampOutdated`) and the gap is dropped — those messages are
   gone. Nothing can fix that retroactively.

### Knowing when it stopped

`NOTIFY_ON_STOP=1` (default) posts one line to the log chat when the bot shuts
down **gracefully**:

```
[STOPPED] forwarding stopped (SIGTERM)
```

`SIGINT` is Ctrl+C, `SIGTERM` is `systemctl stop` / `kill`, `SIGHUP` is
`tmux kill-session` or a dying terminal. The message is sent *before* the client
disconnects, so it works while the account is offline.

What it cannot do, and no code can:

- **A dead process cannot send anything.** `kill -9`, an OOM kill, a seedbox
  reboot or a power cut leave no notice — the notice is the last thing the
  process does, and those paths skip it.
- If the network is already gone at shutdown time, the send fails silently.

For those cases use systemd's `Restart=always` (above) plus `NOTIFY_ON_START=1`:
a `[STARTED]` line with no `[STOPPED]` before it means the previous run died hard.
That pair is the only reliable way to spot a silent death.

### screen or tmux?

Both survive SSH drops; **tmux** is the better choice (actively maintained, real
scrollback, panes, scriptable):

```bash
tmux new -d -s system 'python main.py'   # start detached
tmux ls                                   # is it running?
tmux attach -t system                   # look at it (Ctrl+B then D to detach)
```

The `screen` equivalent, if that is all the box has:

```bash
screen -dmS system python main.py
screen -r system
```

Neither restarts a crashed process. For that, use `systemd --user`, which is more
reliable than either multiplexer:

```ini
# ~/.config/systemd/user/tgunsent.service
[Unit]
Description=tgunsent
[Service]
WorkingDirectory=%h/tgunsent
ExecStart=%h/tgunsent/.venv/bin/python main.py
Restart=always
RestartSec=10
[Install]
WantedBy=default.target
```
```bash
systemctl --user enable --now tgunsent
loginctl enable-linger "$USER"     # keep it running after you log out
```

With gap recovery, a crash plus restart is cheap: the bot catches up on what it
missed. Two rules: **never run two copies against the same `userbot.session`**
(check `tmux ls` / `pgrep -f main.py` first), and if a restart keeps failing,
`AuthKeyDuplicated` means the session file was copied across IPs — delete it and
log in again.

## Why reactions do not show up as edits

Reacting to a message makes Telegram send an **edit update** for that message —
the reaction counters changed. The bot filters those out in two ways:

1. **Text unchanged → ignored.** For anything it logged, the new text is compared
   with the cached text; identical means it was a reaction, a pin, a view counter
   or similar, not an edit.
2. **Never logged → ignored by default.** There is no "before" to show, and a
   reaction is the most likely cause. Set `LOG_UNCACHED_EDITS=1` to log these
   anyway (they appear as `Before: (not in cache)`).

Genuine edits are unaffected, including caption edits on media.

## When it dies: `AuthKeyNotFound` / "session revoked"

```
pyrogram.session.session.AuthKeyNotFound: Auth key not found in the system.
```

Telegram invalidated this session's key. Nothing recovers from it — the auth key
is dead server-side, and retrying just loops. It happens when:

- the session is terminated from **Settings → Devices** (by you, or someone with
  access to the account),
- the same `userbot.session` is copied to another server/IP and used from both,
- the account was deactivated or restricted.

Recovery:

```bash
tmux kill-session -t system
rm -f userbot.session userbot.session-journal
tmux new -d -s system 'cd /path/to/tgunsent && .venv/bin/python main.py'
tmux attach -t system         # enter phone, login code, 2FA password
```

Never copy `userbot.session` between machines — each machine logs in once and
keeps its own file. Then check Settings → Devices: if you did not terminate that
session, someone else did, and you should change your 2FA password.

### Getting a notice when the key is revoked

A dead auth key means the user session **cannot send anything at all** — every
RPC, including `SendMessage`, is rejected. So the log-chat notice needs a
different identity:

```env
BOT_TOKEN=123456:ABC-DEF...      # from @BotFather
```

Add that bot to `LOG_CHAT_ID` as a member (admin for a channel), and fatal
notices arrive through it even when the user session is revoked:

```
[FATAL] userbot session is invalid (auth key revoked). Forwarding has stopped - log in again on the server.
[STOPPED] forwarding stopped (connection lost)
```

Order of attempts: user session first, bot identity only if that fails — so no
extra round-trip in normal operation. `BOT_TOKEN` is optional and stays an empty
no-op if unset. With it configured, a revoked key becomes visible in the log chat
instead of only in a tmux window nobody is watching.

The bot handles both failure shapes itself:

- **At startup**, a revoked key prints the three lines above instead of a
  traceback and exits with code 1.
- **Mid-run**, a dead session triggers `on_disconnect`, which posts
  `[STOPPED] forwarding stopped (connection lost)` if it still can and exits with
  code 1, so `systemd Restart=always` or a supervisor restarts it. Without that
  the process would stay alive doing nothing — the worst failure mode.

## Health watchdog

Every `WATCHDOG_INTERVAL` seconds (default 60) the bot sends a cheap
`updates.GetState` probe:

- **Probe answers** → nothing happens, counter reset.
- **`WATCHDOG_MISSES` probes fail in a row** (default 3) → the session is
  considered dead, `[STOPPED] forwarding stopped (connection lost)` is posted if
  possible, and the process exits 1 so a supervisor restarts it.
- **An auth error** (`AuthKeyNotFound`, `SessionRevoked`, …) → exits at once.

This exists because a revoked auth key makes every RPC time out silently. Without
the probe the process stays alive, keeps retrying forever and logs nothing — you
saw exactly that: `[10] Retrying "updates.GetState" … Request timed out`.

A single blip is harmless: Pyrogram reconnects on its own and the counter resets.
The `on_disconnect` handler deliberately does **not** exit, because
`Session.restart()` fires it on every reconnect.

## Duplicate deliveries (and why logs never double up now)

Telegram re-sends updates it thinks you missed — after a reconnect, and through
kurigram's gap recovery. The same message id can therefore reach the handler two
or three times. Telegram message ids are unique per chat, so the bot treats a
cached id as "already logged" and skips it:

```
[dbg] skip id=42766: already logged as basic:42766 (duplicate update)
```

Because `cache.json` holds those ids, duplicates are also suppressed across
restarts. The same rule keeps duplicate edit updates from producing a second
`[EDITED]` block. A send that *fails* is not cached, so a later retry still works.

If you still see duplicates in the log chat, it is not re-delivery — it is almost
always **two processes on one session file**:

```bash
pgrep -af main.py          # must show exactly one pid
tmux ls                    # plus any leftover session
```

Each process has its own cache, so they cannot dedupe each other. The startup
banner now prints `Started as pid <n>` so you can compare.

## Notes

- Telegram does not say *who* deleted a message. The bot only watches one user,
  so a cached id is enough to attribute it.
- Delete notices may arrive without any peer information (private chats); those
  ids are matched on their own, channel ids are namespaced per chat.
- Protected / no-forward content still works, because media is re-sent from its
  `file_id` instead of being forwarded.
- **Deletes are only reported when the id is in the cache.** A delete update
  carries no sender, so an id we never saw could be anyone's — including yours.
  Those are ignored by default (not even a "no cached content" line, which used
  to look like your own deletions were being logged). Set
  `LOG_UNKNOWN_DELETES=1` to report them as
  `[DELETED] Message ID: <id> — no cached content`.
- All handler exceptions are swallowed and printed; permission errors never
  crash the bot.
- Automating a user account can get it restricted or banned. Use an account you
  can afford to lose, and only log chats you are allowed to keep.
