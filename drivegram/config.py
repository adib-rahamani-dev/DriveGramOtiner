from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr = SecretStr("postgresql+psycopg://drivegram:change-me@db:5432/drivegram")
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_api_id: str = ""
    telegram_api_hash: SecretStr = SecretStr("")
    telegram_channel_id: str = ""
    telegram_chat_id: str = ""
    telegram_bot_api_url: str = "http://bot-api:8081"
    telegram_api_mode: Literal["local", "cloud"] = "local"
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_drive_folder_id: str = ""
    google_redirect_uri: str = "http://localhost:8000/oauth/callback"
    token_encryption_key: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("")
    admin_password_hash: SecretStr = SecretStr("")
    poll_interval_seconds: int = Field(60, ge=10)
    max_file_size_mb: int = Field(500, ge=1, le=2000)
    max_concurrent_transfers: int = Field(1, ge=1, le=8)
    max_attempts: int = Field(5, ge=1, le=20)
    retry_base_seconds: int = Field(30, ge=1)
    download_timeout_seconds: int = Field(1800, ge=1)
    upload_timeout_seconds: int = Field(3600, ge=1)
    lease_seconds: int = Field(120, ge=30)
    disk_reserve_mb: int = Field(512, ge=0)
    temp_dir: Path = Path("/transfers")
    worker_heartbeat_path: Path = Path("/tmp/drivegram-worker-heartbeat")
    public_base_url: str = "http://localhost:8000"
    cookie_secure: bool = True
    remote_worker: bool = False
    database_no_pool: bool = False

    @model_validator(mode="after")
    def trusted_endpoints(self):
        from urllib.parse import urlparse
        url = urlparse(self.telegram_bot_api_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Invalid Local Bot API address")
        if self.telegram_api_mode == "cloud":
            if self.telegram_bot_api_url.rstrip("/") != "https://api.telegram.org":
                raise ValueError("Cloud mode requires the official HTTPS Telegram endpoint")
        elif url.hostname == "api.telegram.org":
            raise ValueError("Transfers require a Local Bot API server")
        return self

    @property
    def google_configured(self):
        return bool(self.google_client_id and self.google_client_secret.get_secret_value()
                    and self.google_drive_folder_id and self.token_encryption_key.get_secret_value())

    @property
    def telegram_configured(self):
        return bool(self.telegram_bot_token.get_secret_value() and self.telegram_target_id
                    and (self.telegram_api_mode == "cloud" or
                         (self.telegram_api_id and self.telegram_api_hash.get_secret_value())))

    @property
    def max_file_size_bytes(self):
        configured = self.max_file_size_mb * 1024 * 1024
        return min(configured, 50_000_000) if self.telegram_api_mode == "cloud" else configured

    @property
    def telegram_target_id(self):
        return self.telegram_chat_id or self.telegram_channel_id


@lru_cache
def get_settings():
    return Settings()
