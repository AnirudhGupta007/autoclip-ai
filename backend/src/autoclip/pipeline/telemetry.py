"""Lightweight in-process telemetry for OpenRouter calls.

Tracks per-model-label token usage so it can be reported via /api/telemetry
and the benchmark script (backend/scripts/benchmark.py). LangSmith handles
distributed tracing separately; this is just for fast local roll-ups.

`model_label` is a caller-chosen tag (e.g. "vision", "audio", "lite",
"orchestrator") rather than the literal OpenRouter model string, so the
dashboard stays meaningful even when OPENROUTER_MODEL* env vars change.
"""
from __future__ import annotations
import logging
import threading
from dataclasses import dataclass

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


def _extract_usage(message) -> tuple[int, int, int]:
    """Pull (prompt_tokens, cached_tokens, output_tokens) off a LangChain AIMessage.

    LangChain standardizes usage onto `AIMessage.usage_metadata` as
    {input_tokens, output_tokens, total_tokens, input_token_details: {cache_read}}.
    OpenRouter/OpenAI-compatible responses populate this via langchain-openai.
    """
    if message is None:
        return 0, 0, 0
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return 0, 0, 0
    prompt = usage.get("input_tokens", 0) or 0
    output = usage.get("output_tokens", 0) or 0
    details = usage.get("input_token_details") or {}
    cached = details.get("cache_read", 0) or 0
    return prompt, cached, output


def record_openrouter_call(message, model_label: str) -> None:
    """Record token usage from a LangChain AIMessage returned by an OpenRouter call."""
    prompt, cached, output = _extract_usage(message)
    with _lock:
        c = _by_model.setdefault(model_label, CounterSnapshot())
        c.calls += 1
        c.prompt_tokens += prompt
        c.cached_tokens += cached
        c.output_tokens += output
    logger.info(
        "openrouter_call model=%s prompt=%d cached=%d output=%d (cache_hit=%.1f%%)",
        model_label, prompt, cached, output, (cached / prompt * 100) if prompt else 0.0,
    )


def snapshot() -> dict[str, CounterSnapshot]:
    with _lock:
        return {m: CounterSnapshot(**c.__dict__) for m, c in _by_model.items()}


def reset() -> None:
    with _lock:
        _by_model.clear()
