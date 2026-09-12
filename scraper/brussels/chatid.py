"""Print the chat_id(s) the Brussels bot can see.

api.telegram.org is unreachable from the dev sandbox, so this runs as an
optional step in the probe workflow. It prints only chat titles and ids —
never the token.

Prerequisite: the bot must already be an administrator of the channel, and
at least one message must have been posted there.
"""

import os
import sys

from curl_cffi import requests


def main() -> None:
    token = os.environ.get("TELEGRAM_BRUSSELS_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BRUSSELS_BOT_TOKEN not set — skipping chat_id lookup")
        return

    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=20
        )
        data = resp.json()
    except Exception as e:
        print(f"getUpdates failed: {e}")
        sys.exit(0)

    if not data.get("ok"):
        # Never echo the response verbatim — it can quote the request URL.
        print(f"Telegram rejected getUpdates (error_code={data.get('error_code')})")
        sys.exit(0)

    chats = {}
    for update in data.get("result", []):
        for key in ("message", "channel_post", "edited_channel_post",
                    "my_chat_member", "chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if chat:
                name = chat.get("title") or chat.get("username") or "(private chat)"
                chats[chat.get("id")] = (name, chat.get("type", "?"))

    if not chats:
        print("No chats seen. An admin must ADD the bot to the channel (a "
              "t.me invite link will not do — bots cannot join by invite), "
              "then post a message there, then re-run this workflow.")
        return

    print("Chats visible to this bot — use the id as TELEGRAM_BRUSSELS_CHAT_ID:")
    for chat_id, (name, chat_type) in chats.items():
        note = "  <-- a channel, this is probably the one" if chat_type in (
            "channel", "supergroup") else ""
        print(f"  [{chat_type}] {name}: {chat_id}{note}")


if __name__ == "__main__":
    main()
