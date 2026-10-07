"""One-use private-chat pairing without exposing Telegram credentials."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = depends_on = None


def upgrade():
    op.add_column("control", sa.Column("private_chat_id", sa.String(64)))
    op.add_column("control", sa.Column("pair_hash", sa.String(64)))
    op.add_column("control", sa.Column("pair_expires_at", sa.DateTime(timezone=True)))
    op.add_column("control", sa.Column("pair_poll_until", sa.DateTime(timezone=True)))
    op.add_column("control", sa.Column("telegram_update_offset", sa.BigInteger(), nullable=False, server_default="0"))


def downgrade():
    for field in ("telegram_update_offset", "pair_poll_until", "pair_expires_at", "pair_hash", "private_chat_id"):
        op.drop_column("control", field)
