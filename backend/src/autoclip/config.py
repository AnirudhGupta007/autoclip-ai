import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'autoclip.db'}")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(BASE_DIR / "outputs")))

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB

GEMINI_RPM_DELAY = 4  # seconds between Gemini calls (free tier = 15 RPM)

CAPTION_STYLES = ["bold_pop", "minimal_clean", "karaoke_sweep", "bounce_in", "glow"]

EXPORT_FORMATS = {
    "9:16": {"width": 1080, "height": 1920, "label": "TikTok/Reels"},
    "1:1": {"width": 1080, "height": 1080, "label": "Twitter/Instagram"},
    "16:9": {"width": 1920, "height": 1080, "label": "YouTube"},
}
