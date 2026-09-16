import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env — check Docker path first, then project root
for _env in [Path("/app/.env"), BASE_DIR.parent / ".env", BASE_DIR.parent.parent / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# ─── OpenRouter — the only LLM provider in this app ───────────
# Every text/vision/audio LLM call (deep-agent orchestration, subagents,
# clip scoring, titles, chat replies, chunk-vision analysis, audio
# transcription) goes through OpenRouter's OpenAI-compatible API.
# Embeddings are the one exception — OpenRouter has no embeddings endpoint,
# see services/embeddings.py.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Deep-agent orchestrator + subagents — needs solid tool-calling/reasoning.
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")
# Classification-shaped tasks: scoring, titles, chat replies — fast + cheap.
OPENROUTER_MODEL_LITE = os.getenv("OPENROUTER_MODEL_LITE", "openai/gpt-4o-mini")
# Frame-sampled chunk analysis (OpenRouter has no native video upload —
# see pipeline/agents/chunk_analyzer.py for the frame-sampling approach).
OPENROUTER_MODEL_VISION = os.getenv("OPENROUTER_MODEL_VISION", "google/gemini-2.5-flash")
# Audio-part transcription (OpenRouter has no dedicated ASR endpoint —
# see services/transcription.py for the audio-content-part approach).
OPENROUTER_MODEL_AUDIO = os.getenv("OPENROUTER_MODEL_AUDIO", "google/gemini-2.5-flash")

# Local embedding model (fastembed (ONNX, no torch)) — see services/embeddings.py.
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-en-v1.5")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

# LangSmith auto-instruments LangChain/LangGraph when these are set in env;
# loading them here just makes the wiring explicit.
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "Autoclip")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'autoclip.db'}")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(BASE_DIR / "outputs")))

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB

CAPTION_STYLES = ["bold_pop", "minimal_clean", "karaoke_sweep", "bounce_in", "glow"]

EXPORT_FORMATS = {
    "9:16": {"width": 1080, "height": 1920, "label": "TikTok/Reels"},
    "1:1": {"width": 1080, "height": 1080, "label": "Twitter/Instagram"},
    "16:9": {"width": 1920, "height": 1080, "label": "YouTube"},
}
