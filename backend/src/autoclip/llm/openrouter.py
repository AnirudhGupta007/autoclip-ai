"""OpenRouter — the single text/vision/audio LLM gateway for this app.

Every LLM call in autoclip (deep-agent orchestration, subagents, clip
scoring, titles, chat replies, vision-based chunk analysis, audio
transcription) goes through OpenRouter's OpenAI-compatible chat-completions
API. Embeddings also go through OpenRouter (its /embeddings API) — see
`services/embeddings.py`.

Chunk analysis (`pipeline/agents/chunk_analyzer.py`, sampled frames or a
native `video_url` part) and transcription (`services/transcription.py`,
`input_audio` parts) both use
the vision/audio-capable models configured here — there's no separate
provider SDK.
"""
from __future__ import annotations
import json
import logging
import re
from functools import lru_cache
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from autoclip.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    OPENROUTER_MODEL_LITE,
    OPENROUTER_MODEL_VISION,
    OPENROUTER_MODEL_AUDIO,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def get_chat_model(
    model: str | None = None, *, lite: bool = False, temperature: float = 0.4, max_tokens: int = 4096,
) -> ChatOpenAI:
    """Return a cached ChatOpenAI instance pointed at OpenRouter.

    `model` overrides the default entirely (used for the vision/audio call
    sites, which pass OPENROUTER_MODEL_VISION/OPENROUTER_MODEL_AUDIO
    explicitly). `lite=True` selects OPENROUTER_MODEL_LITE for
    cheap/fast classification-shaped tasks (scoring, titles, chat replies)
    when `model` isn't given.

    `max_tokens` defaults to a real cap (4096) rather than leaving it unset:
    live-tested and confirmed some models (e.g. Claude via OpenRouter) default
    to max_tokens=64000 when the client doesn't specify one, which both
    costs far more than these structured/short responses need and can
    outright fail on a low-credit account ("requested up to 64000 tokens,
    but can only afford X").
    """
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY is not set — LLM calls will fail")
    resolved = model or (OPENROUTER_MODEL_LITE if lite else OPENROUTER_MODEL)
    return ChatOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY or "missing",
        model=resolved,
        temperature=temperature,
        max_tokens=max_tokens,
        default_headers={
            "HTTP-Referer": "https://github.com/AnirudhGupta007/autoclip-ai",
            "X-Title": "AutoClip AI",
        },
    )


def get_vision_model(temperature: float = 0.4, max_tokens: int = 4096) -> ChatOpenAI:
    return get_chat_model(model=OPENROUTER_MODEL_VISION, temperature=temperature, max_tokens=max_tokens)


def get_audio_model(temperature: float = 0.0, max_tokens: int = 8192) -> ChatOpenAI:
    return get_chat_model(model=OPENROUTER_MODEL_AUDIO, temperature=temperature, max_tokens=max_tokens)


# ─── Tolerant JSON extraction ────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def message_text(message: Any) -> str:
    """Flatten a LangChain AIMessage's content (str or list of parts) to text."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") in (None, "text"):
                parts.append(str(p.get("text", "")))
        return "".join(parts)
    return str(content or "")


def finish_reason(message: Any) -> Optional[str]:
    meta = getattr(message, "response_metadata", None) or {}
    return meta.get("finish_reason")


def _close_truncated(s: str) -> str:
    """Best-effort closing of a JSON document cut off mid-stream.

    Walks the text tracking string/bracket state, truncates back to the last
    point where a complete array element / object member ended, then appends
    the closers still open. Good enough for `{"items":[{...},{...},{..`-style
    truncation, which is the common failure (max_tokens hit mid-list).
    """
    stack: list[str] = []
    in_str = esc = False
    last_safe = -1          # index just after the last complete value inside a container
    safe_stack: list[str] = []
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            last_safe, safe_stack = i + 1, list(stack)
            if not stack:
                return s[: i + 1]
    if last_safe < 0:
        return s
    return s[:last_safe] + "".join(reversed(safe_stack))


def extract_json(text: str) -> Optional[Any]:
    """Parse JSON from model output, tolerating fences, prose and truncation.

    Returns the parsed object or None. Order: strict parse → strip code
    fences → outermost {...}/[...] slice → repair a truncated tail.
    """
    if not text:
        return None
    s = text.strip()
    s = _FENCE_RE.sub("", s).strip()
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    starts = [i for i in (s.find("{"), s.find("[")) if i >= 0]
    if not starts:
        return None
    s = s[min(starts):]
    end = max(s.rfind("}"), s.rfind("]"))
    if end > 0:
        try:
            return json.loads(s[: end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    # Trailing commas are a frequent model slip.
    cleaned = re.sub(r",\s*([}\]])", r"\1", s)
    for candidate in (cleaned, _close_truncated(cleaned)):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def invoke_json(model: ChatOpenAI, schema, prompt: str, label: str) -> Optional[Any]:
    """One structured-output call that degrades gracefully.

    Tries LangChain structured output (`schema` is a Pydantic model); if the
    model/provider ignores the schema or the parse fails, falls back to
    tolerant JSON extraction from the raw text. Returns a plain dict/list
    (or None) — callers validate the shape themselves, so a router model
    that answers in prose-wrapped JSON still works.
    """
    from autoclip.pipeline import telemetry
    raw = None
    try:
        resp = model.with_structured_output(schema, include_raw=True).invoke(prompt)
        raw = resp.get("raw")
        if raw is not None:
            telemetry.record_openrouter_call(raw, model_label=label)
        parsed = resp.get("parsed")
        if parsed is not None:
            return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
    except Exception as e:
        logger.warning("%s: structured call failed (%s) — retrying as plain JSON", label, str(e)[:200])
    text = message_text(raw) if raw is not None else ""
    if not text:
        try:
            raw = model.invoke(prompt + "\n\nReply with JSON only.")
            telemetry.record_openrouter_call(raw, model_label=label)
            text = message_text(raw)
        except Exception as e:
            telemetry.record_failure(label, str(e))
            return None
    out = extract_json(text)
    if out is None:
        telemetry.record_failure(label, "unparseable output")
    return out


__all__ = [
    "get_chat_model", "get_vision_model", "get_audio_model",
    "extract_json", "message_text", "finish_reason", "invoke_json",
]
