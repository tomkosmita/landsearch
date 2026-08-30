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
        for key in ("message", "channel_post", "edited_channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if chat:
                chats[chat.get("id")] = chat.get("title") or chat.get("username") or "(private)"

    if not chats:
        print("No chats seen. Add the bot to the channel as an admin, post a "
              "message there, then re-run this workflow.")
        return

    print("Chats visible to this bot — use the id as TELEGRAM_BRUSSELS_CHAT_ID:")
    for chat_id, title in chats.items():
        print(f"  {title}: {chat_id}")


if __name__ == "__main__":
    main()
