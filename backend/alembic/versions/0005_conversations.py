"""Chat history: conversations + messages (per user).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10

A conversation's LangGraph thread is `u:{user_id}:c:{conversation_id}`.
Older checkpointer threads (`u:{uid}:v:{vid}`) are left as they are — no
conversation points at them, so they're simply never read again.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("video_id", sa.String(), sa.ForeignKey("videos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("clips_json", sa.JSON(), nullable=True),
        # True on the "analysing, I'll pick this up" reply: the frontend
        # re-sends the same prompt after analysis_done, which must not be
        # stored a second time.
        sa.Column("pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_updated", table_name="conversations")
    op.drop_table("conversations")
