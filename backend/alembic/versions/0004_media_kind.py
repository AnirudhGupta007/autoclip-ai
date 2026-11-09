"""Video.media_kind: "video" | "audio" (audio uploads become audiograms).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10

Existing rows are videos, so the server default back-fills them.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("videos")}
    if "media_kind" not in cols:
        op.add_column("videos", sa.Column("media_kind", sa.String(), nullable=False,
                                          server_default="video"))


def downgrade() -> None:
    with op.batch_alter_table("videos") as batch:
        batch.drop_column("media_kind")
