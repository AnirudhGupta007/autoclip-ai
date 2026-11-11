"""Talk segments: MomentRecord.payoff.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12

Podcast/talk videos store 30-90s transcript segments as moments
(services/talk_segments.py). `payoff` is the end time of the sentence where
the segment's point lands; a clip shorter than the segment ends on it.
Nullable: vision moments and every existing row leave it empty.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("moments")}
    if "payoff" not in cols:
        op.add_column("moments", sa.Column("payoff", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("moments") as batch:
        batch.drop_column("payoff")
