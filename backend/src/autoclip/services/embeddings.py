"""Gemini embeddings + pgvector helpers (Phase 2.5).

Embeds moment transcripts at fusion time and pushes them to a pgvector
column on the moments table. Powers semantic moment search across videos.
"""
from __future__ import annotations
import os
import logging
from typing import Iterable, Optional
from google import genai
from autoclip.config import GEMINI_API_KEY
from autoclip.pipeline.state import Moment

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = int(os.getenv("GEMINI_EMBEDDING_DIM", "768"))


def _client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


def embed_text(text: str) -> Optional[list[float]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        resp = _client().models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
        )
        emb = resp.embeddings[0]
        return list(getattr(emb, "values", emb))
    except Exception as e:
        logger.warning("embed_text failed: %s", e)
        return None


def embed_moments(moments: Iterable[Moment]) -> None:
    """Mutate each Moment to set .embedding when missing."""
    for m in moments:
        if m.embedding is not None:
            continue
        text = (m.transcript or m.description or "").strip()
        if not text:
            continue
        m.embedding = embed_text(text)


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
        dup = False
        for k in kept:
            if k.embedding and _cosine(m.embedding, k.embedding) >= threshold:
                dup = True
                break
        if not dup:
            kept.append(m)
    return kept
