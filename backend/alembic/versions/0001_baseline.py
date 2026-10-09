"""Baseline: videos, clips, moments as they existed before auth.

Revision ID: 0001
Revises:
Create Date: 2026-10-08

Existing databases already have these tables (created by the old
`Base.metadata.create_all()`): either `alembic stamp 0001` them, or just run
`upgrade` — each table is only created if it's missing, so this revision is
a no-op on a pre-Alembic database.
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _embedding_type():
    if op.get_bind().dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector
        return Vector(int(os.getenv("EMBEDDING_DIM", "1024")))
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    if "videos" not in existing:
        op.create_table(
            "videos",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("file_path", sa.String(), nullable=False),
            sa.Column("duration", sa.Float(), nullable=True),
            sa.Column("resolution", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if "clips" not in existing:
        op.create_table(
            "clips",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("video_id", sa.String(), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("start_time", sa.Float(), nullable=False),
            sa.Column("end_time", sa.Float(), nullable=False),
            sa.Column("duration", sa.Float(), nullable=False),
            sa.Column("file_path", sa.String(), nullable=True),
            sa.Column("thumbnail_path", sa.String(), nullable=True),
            sa.Column("transcript", sa.Text(), nullable=True),
            sa.Column("scores", sa.JSON(), nullable=True),
            sa.Column("overall_score", sa.Float(), nullable=True),
            sa.Column("caption_style", sa.String(), nullable=True),
            sa.Column("caption_file", sa.String(), nullable=True),
            sa.Column("music_id", sa.String(), nullable=True),
            sa.Column("music_url", sa.String(), nullable=True),
            sa.Column("music_volume", sa.Float(), nullable=True),
            sa.Column("exports", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
    if "moments" not in existing:
        op.create_table(
            "moments",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("video_id", sa.String(), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
            sa.Column("start", sa.Float(), nullable=False),
            sa.Column("end", sa.Float(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("transcript", sa.Text(), nullable=True),
            sa.Column("style_tags", sa.JSON(), nullable=True),
            sa.Column("visual_energy", sa.Float(), nullable=True),
            sa.Column("audio_energy", sa.Float(), nullable=True),
            sa.Column("text_hook_strength", sa.Float(), nullable=True),
            sa.Column("convergence_score", sa.Float(), nullable=True),
            sa.Column("modalities_active", sa.Integer(), nullable=True),
            sa.Column("embedding", _embedding_type(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_moments_video_id", "moments", ["video_id"])


def downgrade() -> None:
    op.drop_table("moments")
    op.drop_table("clips")
    op.drop_table("videos")
