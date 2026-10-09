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
from autoclip.pipeline import telemetry

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
            telemetry.record_failure("embedding", str(e))
            continue
        usage = getattr(resp, "usage", None)
        telemetry.record_usage("embedding", prompt=getattr(usage, "prompt_tokens", 0) or 0)
        for i, item in zip(chunk, sorted(resp.data, key=lambda d: d.index)):
            vec = [float(x) for x in item.embedding]
            if len(vec) != EMBEDDING_DIM:
                logger.warning("embedding dim %d != EMBEDDING_DIM %d — check config",
                               len(vec), EMBEDDING_DIM)
            out[i] = vec
    return out


def embed_text(text: str) -> Optional[list[float]]:
    return embed_texts([text])[0]


def moment_embed_text(m: Moment) -> str:
    """What a moment's embedding represents: what is seen + what is said in
    its own window. (Transcript-only embeddings collapsed distinct scenes
    when transcripts were wrong/shared — live: 229 → 52 moments.)"""
    desc = (m.description or "").strip()
    said = (m.transcript or "").strip()
    return f"{desc}\nDialogue: {said}" if desc and said else (desc or said)


def embed_moments(moments: Iterable[Moment]) -> None:
    """Set .embedding on every moment that lacks one, in one batched call."""
    todo = [m for m in moments if m.embedding is None and moment_embed_text(m)]
    vecs = embed_texts([moment_embed_text(m) for m in todo])
    for m, v in zip(todo, vecs):
        m.embedding = v


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return s / (na * nb) if na and nb else 0.0


def cosine_sim_dedupe(moments: list[Moment], threshold: float = 0.92,
                      max_gap_s: Optional[float] = None) -> list[Moment]:
    """Drop moments whose embedding nearly matches an already-kept moment.

    Moments are considered in descending convergence_score so the stronger
    of a duplicate pair survives. With `max_gap_s`, only moments whose
    centres are within that many seconds can be duplicates — a near-identical
    description 40 minutes later is a different scene, not a duplicate.
    """
    def centre(m: Moment) -> float:
        return (m.start + m.end) / 2.0

    kept: list[Moment] = []
    for m in sorted(moments, key=lambda x: -x.convergence_score):
        if m.embedding is None:
            kept.append(m)
            continue
        dup = any(
            k.embedding
            and (max_gap_s is None or abs(centre(k) - centre(m)) <= max_gap_s)
            and _cosine(m.embedding, k.embedding) >= threshold
            for k in kept
        )
        if not dup:
            kept.append(m)
    return kept
