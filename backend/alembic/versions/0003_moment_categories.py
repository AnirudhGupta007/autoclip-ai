"""Moment categories + "why it works" line (text-only tagging pass).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09

Nullable columns: NULL means "not tagged yet" — scripts/backfill_moment_tags.py
fills them for videos analysed before this revision.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("moments")}
    if "categories" not in cols:
        op.add_column("moments", sa.Column("categories", sa.JSON(), nullable=True))
    if "why" not in cols:
        op.add_column("moments", sa.Column("why", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("moments", "why")
    op.drop_column("moments", "categories")
