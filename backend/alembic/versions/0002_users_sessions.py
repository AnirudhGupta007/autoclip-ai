"""Users, login sessions, and video ownership.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08

Existing videos are assigned to a legacy owner: the first ADMIN_EMAILS entry
(created as an admin without a usable password — sign up with that email to
claim it), or a placeholder "owner@local" account if ADMIN_EMAILS is unset.
"""
import os
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UNUSABLE_PASSWORD = "!"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    with op.batch_alter_table("videos") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_videos_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_videos_user_id", ["user_id"])

    # ── back-fill: existing videos belong to a legacy owner ──
    bind = op.get_bind()
    orphans = bind.execute(sa.text("SELECT count(*) FROM videos WHERE user_id IS NULL")).scalar() or 0
    if not orphans:
        return
    admins = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
    email = admins[0] if admins else "owner@local"
    users = sa.table("users", sa.column("id", sa.Integer), sa.column("email", sa.String),
                     sa.column("password_hash", sa.String), sa.column("is_admin", sa.Boolean),
                     sa.column("is_demo", sa.Boolean), sa.column("created_at", sa.DateTime))
    owner_id = bind.execute(sa.select(users.c.id).where(users.c.email == email)).scalar()
    if owner_id is None:
        bind.execute(users.insert().values(
            email=email, password_hash=UNUSABLE_PASSWORD, is_admin=bool(admins), is_demo=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        owner_id = bind.execute(sa.select(users.c.id).where(users.c.email == email)).scalar()
    bind.execute(sa.text("UPDATE videos SET user_id = :uid WHERE user_id IS NULL"), {"uid": owner_id})


def downgrade() -> None:
    with op.batch_alter_table("videos") as batch:
        batch.drop_index("ix_videos_user_id")
        batch.drop_constraint("fk_videos_user_id_users", type_="foreignkey")
        batch.drop_column("user_id")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
