"""Embeddings via OpenRouter's OpenAI-compatible /embeddings API + cosine helpers.

Default model is open-source BGE-M3 (`baai/bge-m3`, 1024-dim). Call sites
(moment_store.py, routers/search.py, the rag/ package) only see
`embed_text` / `embed_moments` returning `list[float]`, so the model can be
swapped via EMBEDDING_MODEL_NAME/EMBEDDING_DIM without touching them.
"""
from __future__ import annotations
import logging
from functools import lru_cache
from typing import Iterable, Optional

from openai import OpenAI

from autoclip.config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, EMBEDDING_MODEL_NAME, EMBEDDING_DIM,
)
from autoclip.pipeline.state import Moment

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = EMBEDDING_MODEL_NAME  # kept for backward-compat imports (models.py)
_BATCH_SIZE = 64


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY or "missing")


def embed_texts(texts: list[str]) -> list[Optional[list[float]]]:
    """Embed many texts in batched API calls; empty inputs map to None."""
    out: list[Optional[list[float]]] = [None] * len(texts)
    idx = [i for i, t in enumerate(texts) if (t or "").strip()]
    for start in range(0, len(idx), _BATCH_SIZE):
        chunk = idx[start:start + _BATCH_SIZE]
        try:
            resp = _client().embeddings.create(
                model=EMBEDDING_MODEL_NAME,
                input=[texts[i].strip() for i in chunk],
            )
        except Exception as e:
            logger.warning("embedding batch failed: %s", e)
            continue
        for i, item in zip(chunk, sorted(resp.data, key=lambda d: d.index)):
            vec = [float(x) for x in item.embedding]
            if len(vec) != EMBEDDING_DIM:
                logger.warning("embedding dim %d != EMBEDDING_DIM %d — check config",
                               len(vec), EMBEDDING_DIM)
            out[i] = vec
    return out


def embed_text(text: str) -> Optional[list[float]]:
    return embed_texts([text])[0]


def embed_moments(moments: Iterable[Moment]) -> None:
    """Set .embedding on every moment that lacks one, in one batched call."""
    todo = [m for m in moments if m.embedding is None and (m.transcript or m.description or "").strip()]
    vecs = embed_texts([(m.transcript or m.description) for m in todo])
    for m, v in zip(todo, vecs):
        m.embedding = v


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return s / (na * nb) if na and nb else 0.0


def cosine_sim_dedupe(moments: list[Moment], threshold: float = 0.92) -> list[Moment]:
    """Drop moments whose embedding nearly matches an earlier kept moment."""
    kept: list[Moment] = []
    for m in moments:
        if m.embedding is None:
            kept.append(m)
            continue
        if not any(k.embedding and _cosine(m.embedding, k.embedding) >= threshold for k in kept):
            kept.append(m)
    return kept
