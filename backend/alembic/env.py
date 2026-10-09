"""Alembic environment for AutoClip.

Only the app's own tables are managed here. Two families of tables in the
same database belong to libraries and are ignored by autogenerate:
  • LangGraph's PostgresSaver tables (checkpoints, checkpoint_*)
  • LlamaIndex's PGVectorStore tables (data_*)
render_as_batch=True so ALTERs also work on SQLite (local dev / tests).
"""
from __future__ import annotations
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from autoclip.config import DATABASE_URL
from autoclip.database import Base
import autoclip.models  # noqa: F401  (registers the tables on Base.metadata)

config = context.config
if config.config_file_name and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name and (name.startswith("checkpoint") or name.startswith("data_")):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True,
        render_as_batch=True, include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
        with engine.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata,
        render_as_batch=True, include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
