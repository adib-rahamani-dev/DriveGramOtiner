from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow():
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Keep SQLite mock tests and PostgreSQL equally explicit about UTC."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


class Control(Base):
    __tablename__ = "control"
    id: Mapped[int] = mapped_column(primary_key=True)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    baseline_scope: Mapped[str | None] = mapped_column(String(256))
    last_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    scan_error: Mapped[str | None] = mapped_column(Text)
    telegram_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    telegram_error: Mapped[str | None] = mapped_column(Text)
    telegram_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    worker_heartbeat: Mapped[datetime | None] = mapped_column(UTCDateTime())
    worker_disk_free: Mapped[int | None] = mapped_column(BigInteger)
    worker_disk_total: Mapped[int | None] = mapped_column(BigInteger)
    private_chat_id: Mapped[str | None] = mapped_column(String(64))
    pair_hash: Mapped[str | None] = mapped_column(String(64))
    pair_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    pair_poll_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    telegram_update_offset: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    refresh_encrypted: Mapped[str] = mapped_column(Text)
    generation: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("drive_file_id", "version_key", name="uq_drive_version"),
        CheckConstraint("status IN ('discovered','queued','downloading','uploading','completed','failed','canceled')",
                        name="ck_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    drive_file_id: Mapped[str] = mapped_column(String(256))
    version_key: Mapped[str] = mapped_column(String(256))
    source_scope: Mapped[str] = mapped_column(String(256))
    original_name: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(256))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    md5_checksum: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="discovered", index=True)
    bytes_downloaded: Mapped[int] = mapped_column(BigInteger, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    claim_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    telegram_file_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
