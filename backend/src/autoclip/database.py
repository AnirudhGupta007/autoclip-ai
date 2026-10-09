import logging
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from autoclip.config import DATABASE_URL

logger = logging.getLogger(__name__)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# backend/ in the repo, /app in the container (holds alembic.ini + alembic/)
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(revision: str = "head") -> None:
    """`alembic upgrade head`, programmatically (same as the container entrypoint)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.attributes["configure_logging"] = False
    command.upgrade(cfg, revision)


def init_db():
    """Bring the schema up to date. Migrations are the source of truth
    (backend/alembic); create_all is only a fallback for checkouts without
    the alembic directory."""
    if os.getenv("AUTOCLIP_SKIP_MIGRATIONS", "").strip() in {"1", "true"}:
        return
    if (BACKEND_ROOT / "alembic").is_dir():
        run_migrations()
    else:
        logger.warning("alembic/ not found next to the app — falling back to create_all()")
        import autoclip.models  # noqa: F401  (register tables)
        Base.metadata.create_all(bind=engine)
