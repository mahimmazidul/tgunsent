# tgunsent

Minimal Pyrogram userbot that watches **one** user (`TARGET_USER_ID`) and logs
their activity into `LOG_CHAT_ID`: new text (`[NEW]`), edits (`[EDITED]` with
before/after), photos/videos/documents (re-sent with a `[NEW - photo]` caption)
and deletions (`[DELETED]` edited onto the log message we own).

Nothing is ever forwarded — every log message is re-sent by this account, so it
can always be edited later. Content is cached in `cache.json` (stdlib `json`),
which survives restarts and lets a bare delete update be resolved backwards.

## Run on a seedbox (no root)

```bash
cp .env.example .env && nano .env     # fill API_ID, API_HASH, TARGET_USER_ID, LOG_CHAT_ID
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
screen -S userbot
python main.py                        # first run: phone, login code, 2FA password
# detach: Ctrl+A then D — reattach later with: screen -r userbot
```

## Files

| File | Purpose |
| --- | --- |
| `main.py` | The whole bot (flat functions, one handler per case). |
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
