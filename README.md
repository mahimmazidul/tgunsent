# tgunsent

A small Pyrogram user client that forwards messages from one configured Telegram user to a private log chat, reports edits, and attempts to label forwarded messages when deletion notices arrive.

## Setup

1. Obtain `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org/apps). Create a private log chat and obtain its numeric chat ID; use a chat only you can access.
2. Copy `.env.example` to `.env` and set the API credentials, `TARGET_USER_ID`, and `LOG_CHAT_ID`. IDs are numeric; group IDs are typically negative.
3. Run on a seedbox without root:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env
screen -S tgunsent
python main.py
```

Sign in interactively the first time. Detach from screen with Ctrl+A, D; reattach with `screen -r tgunsent`.

## Important limitations

- The client captures messages it sees while running; it cannot recover content it never observed. It watches accessible chats, not Secret Chats.
- The message cache is in memory and is lost on restart. Pyrogram saves authentication separately in `username.session` (a SQLite-backed session file). Protect both that file and `.env`; neither belongs in Git.
- Telegram generally does not allow editing forwarded messages, so the `[DELETED]` label usually cannot be added. The forwarded copy remains if it was successfully delivered. Deletion notifications may be missing and do not say who deleted the message.
- Protected content or insufficient permissions can prevent forwarding. Telegram rate limits are respected; delivery is not guaranteed. Pyrogram is no longer actively maintained, and no client can guarantee an account won't be restricted.
- Use only where you have permission to retain the messages. Do not share your API credentials, session file or GitHub tokens.

## Owner

Repository: [mahimmazidul/tgunsent](https://github.com/mahimmazidul/tgunsent).
