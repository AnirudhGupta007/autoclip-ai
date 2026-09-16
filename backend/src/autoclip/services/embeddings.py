"""Local embeddings + pgvector helpers.

OpenRouter has no embeddings endpoint at all (it's chat-completions only),
so this is the one call site in the app that does NOT go through
OpenRouter. Instead it uses a local ONNX embedding model via `fastembed` —
no API key, no network call at inference time, runs in-process.

fastembed, not sentence-transformers, deliberately: sentence-transformers
pulls the full PyTorch + transformers stack (multi-GB, incl. CUDA wheels by
default), which is unnecessary weight for a single small embedding model.
fastembed runs the same class of model (BAAI/bge-small-en-v1.5, 384-dim)
on ONNX Runtime instead — no torch, a fraction of the install footprint.
This keeps the pgvector column format (list[float]) and every call site
(moment_store.py, routers/search.py, the rag/ package) unaware that
embeddings moved local.
"""
from __future__ import annotations
import logging
import threading
from typing import Iterable, Optional

from autoclip.config import EMBEDDING_MODEL_NAME, EMBEDDING_DIM
from autoclip.pipeline.state import Moment

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = EMBEDDING_MODEL_NAME  # kept for backward-compat imports (models.py)

_model_lock = threading.Lock()
_model = None


def _get_model():
    """Lazily load the fastembed ONNX model as a module-level singleton."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding
            logger.info("Loading local embedding model %s", EMBEDDING_MODEL_NAME)
            _model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
    return _model


def embed_text(text: str) -> Optional[list[float]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        (vec,) = _get_model().embed([text])
        return [float(x) for x in vec]
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
