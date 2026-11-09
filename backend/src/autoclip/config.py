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
# Clip-selection re-rank (rag/selection.py): one structured-output call per
# request ranking ~30 hybrid candidates. Defaults to the orchestrator model.
OPENROUTER_MODEL_RERANK = os.getenv("OPENROUTER_MODEL_RERANK", "") or OPENROUTER_MODEL
# Scoring / titles — open-source, cheap, supports structured output.
OPENROUTER_MODEL_LITE = os.getenv("OPENROUTER_MODEL_LITE", "qwen/qwen3-30b-a3b-instruct-2507")
# Chunk analysis — cheapest Gemini with image+video input.
OPENROUTER_MODEL_VISION = os.getenv("OPENROUTER_MODEL_VISION", "google/gemini-2.5-flash-lite")
# Transcription — cheapest Gemini with audio input. Any OpenRouter model
# with "audio" in input_modalities works (e.g. google/gemini-3.5-flash-lite).
OPENROUTER_MODEL_AUDIO = os.getenv("OPENROUTER_MODEL_AUDIO", "google/gemini-2.5-flash-lite")

# Embeddings via OpenRouter's /embeddings API — open-source BGE-M3.
# EMBEDDING_DIM must match the model's output (sizes the pgvector columns).
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "baai/bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

# ─── Analysis-stage tuning ────────────────────────────────────
# Transcription (services/transcription.py). Long segments overflow the
# output cap / make Gemini loop, so segments are short and capped.
TRANSCRIBE_SEGMENT_SECONDS = float(os.getenv("TRANSCRIBE_SEGMENT_SECONDS", "180"))
TRANSCRIBE_SEGMENT_HARD_MAX = 240.0   # values above this fall back to 180 (live: 600s segments failed 9/10; 360s single calls stopped early)
TRANSCRIBE_PARALLELISM = int(os.getenv("TRANSCRIBE_PARALLELISM", "4"))
TRANSCRIBE_MAX_TOKENS = int(os.getenv("TRANSCRIBE_MAX_TOKENS", "8192"))
TRANSCRIBE_ATTEMPTS = int(os.getenv("TRANSCRIBE_ATTEMPTS", "3"))
TRANSCRIBE_MIN_COVERAGE = float(os.getenv("TRANSCRIBE_MIN_COVERAGE", "0.8"))
# Timestamp format requested from the audio model: "mmss" (MM:SS strings) or "seconds".
TRANSCRIBE_TIMESTAMP_FORMAT = os.getenv("TRANSCRIBE_TIMESTAMP_FORMAT", "mmss").strip().lower()

# Chunk vision analysis (pipeline/agents/chunk_analyzer.py).
#   frames — N JPEG frames sampled evenly across the chunk (image_url parts)
#   video  — the chunk re-encoded small and sent as a native `video_url`
#            part (model also hears the audio track; ~5x the input tokens)
VISION_INPUT_MODE = os.getenv("VISION_INPUT_MODE", "frames").strip().lower()
VISION_MAX_FRAMES = int(os.getenv("VISION_MAX_FRAMES", "24"))
VISION_FRAME_WIDTH = int(os.getenv("VISION_FRAME_WIDTH", "768"))
VISION_VIDEO_HEIGHT = int(os.getenv("VISION_VIDEO_HEIGHT", "360"))
VISION_MAX_TOKENS = int(os.getenv("VISION_MAX_TOKENS", "4096"))
CHUNK_ANALYZE_ATTEMPTS = int(os.getenv("CHUNK_ANALYZE_ATTEMPTS", "2"))
# Max concurrent ffmpeg frame-sampling/encode jobs across chunks (~100 MB RSS each).
VISION_FFMPEG_CONCURRENCY = int(os.getenv("VISION_FFMPEG_CONCURRENCY", "2"))

# Global fusion embedding dedupe (pipeline/agents/global_fusion.py).
FUSION_DEDUPE_THRESHOLD = float(os.getenv("FUSION_DEDUPE_THRESHOLD", "0.92"))
FUSION_DEDUPE_WINDOW_SECONDS = float(os.getenv("FUSION_DEDUPE_WINDOW_SECONDS", "180"))

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

# Upload cap in MB (frontend nginx client_max_body_size must be >= this).
MAX_UPLOAD_SIZE = int(float(os.getenv("MAX_UPLOAD_SIZE_MB", "500")) * 1024 * 1024)

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
