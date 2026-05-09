"""Lightweight in-process telemetry for Gemini calls.

Tracks prompt-cache hit rate so it can be reported in eval runs and the
README dashboard (Phase 5 deliverable). LangSmith handles distributed
tracing separately; this is just for fast local roll-ups.
"""
from __future__ import annotations
import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CounterSnapshot:
    calls: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        return (self.cached_tokens / self.prompt_tokens) if self.prompt_tokens else 0.0


_lock = threading.Lock()
_by_model: dict[str, CounterSnapshot] = {}


def record_gemini_call(response, model: str) -> None:
    """Pull usage_metadata off a google-genai response and roll it up."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return
    prompt = getattr(meta, "prompt_token_count", 0) or 0
    cached = getattr(meta, "cached_content_token_count", 0) or 0
    output = (
        getattr(meta, "candidates_token_count", 0)
        or getattr(meta, "output_token_count", 0)
        or 0
    )
    with _lock:
        c = _by_model.setdefault(model, CounterSnapshot())
        c.calls += 1
        c.prompt_tokens += prompt
        c.cached_tokens += cached
        c.output_tokens += output
    logger.info(
        "gemini_call model=%s prompt=%d cached=%d output=%d (cache_hit=%.1f%%)",
        model, prompt, cached, output, (cached / prompt * 100) if prompt else 0.0,
    )


def snapshot() -> dict[str, CounterSnapshot]:
    with _lock:
        return {m: CounterSnapshot(**c.__dict__) for m, c in _by_model.items()}


def reset() -> None:
    with _lock:
        _by_model.clear()
