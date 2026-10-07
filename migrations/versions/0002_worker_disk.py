"""Report transfer storage from the persistent worker to a remote panel."""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade():
    op.add_column("control", sa.Column("worker_disk_free", sa.BigInteger()))
    op.add_column("control", sa.Column("worker_disk_total", sa.BigInteger()))


def downgrade():
    op.drop_column("control", "worker_disk_total")
    op.drop_column("control", "worker_disk_free")
