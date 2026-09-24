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

# ─── OpenRouter — the only model provider in this app ─────────
# Every model call — orchestration, subagents, scoring, titles, chunk
# vision analysis, audio transcription AND embeddings — goes through
# OpenRouter. Defaults are cheap Gemini models + cheap open-source models.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Deep-agent orchestrator + subagents — needs reliable tool-calling.
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
# Scoring / titles — open-source, cheap, supports structured output.
OPENROUTER_MODEL_LITE = os.getenv("OPENROUTER_MODEL_LITE", "qwen/qwen3-30b-a3b-instruct-2507")
# Chunk analysis — cheapest Gemini with image+video input.
OPENROUTER_MODEL_VISION = os.getenv("OPENROUTER_MODEL_VISION", "google/gemini-2.5-flash-lite")
# Transcription — cheapest Gemini with audio input.
OPENROUTER_MODEL_AUDIO = os.getenv("OPENROUTER_MODEL_AUDIO", "google/gemini-2.5-flash-lite")

# Embeddings via OpenRouter's /embeddings API — open-source BGE-M3.
# EMBEDDING_DIM must match the model's output (sizes the pgvector columns).
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "baai/bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

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

# Public-demo quota: agent runs per visitor IP per UTC day (see services/rate_limit.py).
# DAILY_GLOBAL_QUERY_LIMIT caps the whole site; 0 disables the global cap.
DAILY_QUERY_LIMIT = int(os.getenv("DAILY_QUERY_LIMIT", "2"))
DAILY_GLOBAL_QUERY_LIMIT = int(os.getenv("DAILY_GLOBAL_QUERY_LIMIT", "0"))

CAPTION_STYLES = ["bold_pop", "minimal_clean", "karaoke_sweep", "bounce_in", "glow"]

EXPORT_FORMATS = {
    "9:16": {"width": 1080, "height": 1920, "label": "TikTok/Reels"},
    "1:1": {"width": 1080, "height": 1080, "label": "Twitter/Instagram"},
    "16:9": {"width": 1920, "height": 1080, "label": "YouTube"},
}
