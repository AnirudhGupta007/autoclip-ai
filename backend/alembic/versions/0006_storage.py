"""Storage rules: Video.archived, User.last_active_at.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10

last_active_at is back-filled with the migration time, so the 60-day
inactive-account rule starts counting from the upgrade, not from sign-up.
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    videos = {c["name"] for c in sa.inspect(bind).get_columns("videos")}
    if "archived" not in videos:
        op.add_column("videos", sa.Column("archived", sa.Boolean(), nullable=False,
                                          server_default=sa.false()))
    users = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "last_active_at" not in users:
        op.add_column("users", sa.Column("last_active_at", sa.DateTime(), nullable=True))
    bind.execute(sa.text("UPDATE users SET last_active_at = :now WHERE last_active_at IS NULL"),
                 {"now": datetime.now(timezone.utc).replace(tzinfo=None)})


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_active_at")
    with op.batch_alter_table("videos") as batch:
        batch.drop_column("archived")
