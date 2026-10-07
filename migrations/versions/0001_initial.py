"""Durable queue, encrypted credentials, control and login throttling.

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    op.create_table("control", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("auto_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("baseline_scope", sa.String(256)), sa.Column("last_scan_at", sa.DateTime(timezone=True)),
        sa.Column("scan_error", sa.Text()), sa.Column("telegram_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("telegram_checked_at", sa.DateTime(timezone=True)), sa.Column("telegram_error", sa.Text()),
        sa.Column("telegram_retry_at", sa.DateTime(timezone=True)), sa.Column("worker_heartbeat", sa.DateTime(timezone=True)))
    op.execute(sa.text("INSERT INTO control (id, auto_sync, telegram_ok) VALUES (1, false, false)"))
    op.create_table("oauth_tokens", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("refresh_encrypted", sa.Text(), nullable=False), sa.Column("generation", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("login_attempts", sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False), sa.Column("window_start", sa.DateTime(timezone=True), nullable=False))
    op.create_table("jobs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("drive_file_id", sa.String(256), nullable=False),
        sa.Column("version_key", sa.String(256), nullable=False), sa.Column("source_scope", sa.String(256), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False), sa.Column("mime_type", sa.String(256), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("md5_checksum", sa.String(32)),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("bytes_downloaded", sa.BigInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("claim_token", sa.String(36)), sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False), sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(64)), sa.Column("error_message", sa.Text()),
        sa.Column("telegram_message_id", sa.BigInteger()), sa.Column("telegram_chat_id", sa.String(64)),
        sa.Column("telegram_file_id", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("drive_file_id", "version_key", name="uq_drive_version"),
        sa.CheckConstraint("status IN ('discovered','queued','downloading','uploading','completed','failed','canceled')", name="ck_status"))
    for field in ("status", "next_attempt_at", "lease_until"):
        op.create_index(f"ix_jobs_{field}", "jobs", [field])


def downgrade():
    for table in ("jobs", "login_attempts", "oauth_tokens", "control"):
        op.drop_table(table)
