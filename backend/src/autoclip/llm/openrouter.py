"""OpenRouter — the single text/vision/audio LLM gateway for this app.

Every LLM call in autoclip (deep-agent orchestration, subagents, clip
scoring, titles, chat replies, vision-based chunk analysis, audio
transcription) goes through OpenRouter's OpenAI-compatible chat-completions
API. The only exception is embeddings — OpenRouter has no embeddings
endpoint at all, so `services/embeddings.py` uses a local fastembed (ONNX, no torch)
model instead (see that file's docstring).

OpenRouter has no native video-file-upload or dedicated-ASR endpoint, so
`pipeline/agents/chunk_analyzer.py` (frame-sampled vision calls) and
`services/transcription.py` (audio-part chat-completion calls) both route
through the vision/audio-capable models configured here rather than a
separate provider SDK.
"""
from __future__ import annotations
import logging
from functools import lru_cache

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


def get_vision_model(temperature: float = 0.4) -> ChatOpenAI:
    return get_chat_model(model=OPENROUTER_MODEL_VISION, temperature=temperature)


def get_audio_model(temperature: float = 0.0) -> ChatOpenAI:
    return get_chat_model(model=OPENROUTER_MODEL_AUDIO, temperature=temperature)


__all__ = ["get_chat_model", "get_vision_model", "get_audio_model"]
