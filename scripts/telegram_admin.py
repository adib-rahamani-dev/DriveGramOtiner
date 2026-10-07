"""Explicit Telegram setup operations; never prints token-bearing URLs or server error bodies."""
import argparse

import httpx

from drivegram.config import get_settings
from drivegram.telegram import Telegram

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["cloud-logout", "channel-id", "check"])
args = parser.parse_args()
settings = get_settings()
token = settings.telegram_bot_token.get_secret_value()
if not token:
    raise SystemExit("Configure TELEGRAM_BOT_TOKEN in .env first.")
try:
    if args.action == "check":
        api = Telegram(settings)
        try:
            me = api.check()
            print("Bot username and channel posting permissions verified:", me["username"])
        finally:
            api.close()
    else:
        # Cloud logout is invoked explicitly, never during normal worker startup.
        base = "https://api.telegram.org" if args.action == "cloud-logout" else settings.telegram_bot_api_url
        method = "logOut" if args.action == "cloud-logout" else "getUpdates"
        with httpx.Client(timeout=30) as client:
            response = client.post(base.rstrip("/") + "/bot" + token + "/" + method,
                                   json={} if method == "logOut" else {"timeout": 0, "allowed_updates": ["channel_post", "my_chat_member"]})
            data = response.json()
        if not data.get("ok"):
            raise ValueError()
        if method == "logOut":
            print("Cloud logout succeeded. You can now use the Local Bot API.")
        else:
            ids = set()
            for update in data["result"]:
                for key in ("channel_post", "my_chat_member"):
                    chat = update.get(key, {}).get("chat", {})
                    if chat.get("type") == "channel":
                        ids.add(chat["id"])
            print("Channel IDs:", ", ".join(map(str, sorted(ids))) if ids else "No channel updates. Post a message in the channel, then retry.")
except Exception:
    raise SystemExit("Telegram setup request failed. Check network, API migration, bot token and permissions; credentials were not logged.") from None
