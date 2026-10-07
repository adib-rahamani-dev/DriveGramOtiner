import hashlib
import hmac
import logging
import re
import unicodedata
from pathlib import PurePath

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet


def cipher(settings):
    return Fernet(settings.token_encryption_key.get_secret_value().encode())


def safe_filename(name):
    name = unicodedata.normalize("NFC", name)
    name = "".join("_" if c in '<>:"/\\|?*' or not c.isprintable() else c for c in name).strip(" .")
    suffix = PurePath(name).suffix
    if len(suffix.encode("utf-8")) > 20:
        suffix = ""
    stem = name[:-len(suffix)] if suffix else name
    if stem.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
        stem = "file_" + stem
    stem = stem.encode("utf-8")[:200 - len(suffix.encode("utf-8"))].decode("utf-8", errors="ignore").strip(" .")
    return (stem or "media") + suffix


def admin_hash(settings):
    value = settings.admin_password_hash.get_secret_value()
    if value:
        return value
    password = settings.admin_password.get_secret_value()
    if len(password) < 12:
        raise ValueError("ADMIN_PASSWORD must have at least 12 characters")
    return PasswordHasher().hash(password)


def check_password(username, password, settings, password_hash):
    try:
        valid = PasswordHasher().verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        valid = False
    return valid and hmac.compare_digest(username.encode(), settings.admin_username.encode())


def auth_fingerprint(settings, password_hash):
    # A password/configuration change invalidates existing sessions across restarts.
    stable = settings.admin_password_hash.get_secret_value() or settings.admin_password.get_secret_value()
    return hmac.new(settings.session_secret.get_secret_value().encode(),
                    (settings.admin_username + stable).encode(), hashlib.sha256).hexdigest()


class RedactingFormatter(logging.Formatter):
    def __init__(self, settings):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.secrets = [s for s in (
            settings.telegram_bot_token.get_secret_value(), settings.telegram_api_hash.get_secret_value(),
            settings.google_client_secret.get_secret_value(), settings.admin_password.get_secret_value(),
            settings.token_encryption_key.get_secret_value(), settings.session_secret.get_secret_value(),
            settings.database_url.get_secret_value(),
            settings.telegram_http_proxy.get_secret_value(),
        ) if s]

    def format(self, record):
        message = super().format(record)
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"bot\d+:[\w-]+", "bot[REDACTED]", message)
        message = re.sub(r"(?i)(access_token|refresh_token|code|client_secret)=([^\s&]+)",
                         r"\1=[REDACTED]", message)
        return message


def configure_logging(settings):
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(settings))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ("httpx", "httpcore", "sqlalchemy.engine", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
