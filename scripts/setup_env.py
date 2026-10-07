"""Generate local secrets without printing them, optionally import the supplied bot token."""
import argparse
import os
import re
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

parser = argparse.ArgumentParser()
parser.add_argument("--attachment", type=Path, help="Read TELEGRAM_BOT_TOKEN from the supplied brief, silently")
args = parser.parse_args()
path = Path(".env")
if path.exists():
    raise SystemExit(".env already exists; preserved. Edit it locally.")
values = {}
if args.attachment:
    match = re.search(r"TELEGRAM_BOT_TOKEN:\s*([0-9]+:[A-Za-z0-9_-]+)", args.attachment.read_text(encoding="utf-8-sig"))
    if match:
        values["TELEGRAM_BOT_TOKEN"] = match.group(1)
password = secrets.token_urlsafe(32)
values.update({"POSTGRES_PASSWORD": password,
               "DATABASE_URL": f"postgresql+psycopg://drivegram:{password}@db:5432/drivegram",
               "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(), "SESSION_SECRET": secrets.token_urlsafe(48),
               "ADMIN_PASSWORD": secrets.token_urlsafe(24), "COOKIE_SECURE": "false"})
lines = []
for line in Path(".env.example").read_text(encoding="utf-8").splitlines():
    key = line.split("=", 1)[0]
    lines.append(f"{key}={values[key]}" if key in values else line)
with path.open("x", encoding="utf-8", newline="\n") as output:
    output.write("\n".join(lines) + "\n")
if os.name != "nt":
    path.chmod(0o600)
print("Created .env with generated secrets. Read ADMIN_PASSWORD locally; do not paste it into chat/logs.")
