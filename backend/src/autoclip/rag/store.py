"""LlamaIndex vector store for moment retrieval.

Additive, not a repointing of the existing `moments` table: `MomentRecord`
(models.py) and routers/search.py's raw pgvector column already have a
schema shape that predates this RAG package. Rather than migrate that
table to LlamaIndex's node schema (node_id/text/metadata_/embedding), we
let LlamaIndex manage its own table — `llamaindex_moment_nodes` — in the
same Postgres instance, populated by a dual-write from
`services/moment_store.persist_moments()`. Nothing that already reads
`MomentRecord`/`moments` (eval.py, the Clip/Video models) is touched.

On sqlite (local dev without Postgres), PGVectorStore isn't usable, so we
fall back to LlamaIndex's in-memory SimpleVectorStore — RAG search still
works locally, it just isn't persisted across restarts.
"""
from __future__ import annotations
import logging
from urllib.parse import urlparse
from functools import lru_cache

from autoclip.config import DATABASE_URL, EMBEDDING_DIM

logger = logging.getLogger(__name__)

TABLE_NAME = "moment_nodes"  # LlamaIndex prefixes this with "data_" internally


def _parse_postgres_dsn(url: str) -> dict:
    """Parse a SQLAlchemy-style postgres DSN into PGVectorStore.from_params kwargs."""
    # Normalize e.g. postgresql+psycopg2://user:pass@host:port/db -> postgresql://...
    normalized = url.replace("postgresql+psycopg2", "postgresql")
    parsed = urlparse(normalized)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "database": (parsed.path or "/autoclip").lstrip("/"),
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


@lru_cache(maxsize=1)
def get_vector_store():
    """Return a LlamaIndex vector store — PGVectorStore on Postgres, in-memory otherwise."""
    if DATABASE_URL.startswith("postgres"):
        try:
            from llama_index.vector_stores.postgres import PGVectorStore
            params = _parse_postgres_dsn(DATABASE_URL)
            store = PGVectorStore.from_params(
                **params,
                table_name=TABLE_NAME,
                embed_dim=EMBEDDING_DIM,
            )
            logger.info("RAG vector store: PGVectorStore table=%s", TABLE_NAME)
            return store
        except Exception as e:
            logger.warning("PGVectorStore unavailable (%s) — falling back to in-memory store", e)

    from llama_index.core.vector_stores import SimpleVectorStore
    logger.info("RAG vector store: in-memory SimpleVectorStore (no Postgres)")
    return SimpleVectorStore()
