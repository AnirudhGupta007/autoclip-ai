"""Auth / multi-user settings, read straight from the environment.

Kept out of config.py on purpose (that module is shared with the pipeline);
everything here is read once at import time.
"""
from __future__ import annotations
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# Cookie. `__Host-` cookies MUST be Secure, so plain-HTTP dev uses a
# different (non-prefixed) name instead of a cookie the browser would drop.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes"}
COOKIE_NAME = "__Host-session" if COOKIE_SECURE else "autoclip_session"
SESSION_DAYS = _int("SESSION_DAYS", 30)
# Sliding expiry: only extend (one DB write) when the session is this old.
SESSION_REFRESH_SECONDS = 6 * 3600

PASSWORD_MIN_LENGTH = 10

# Admins: exempt from chat quota and upload caps. Lower-cased.
ADMIN_EMAILS = [e.lower() for e in _list("ADMIN_EMAILS")]

# Explicit CORS allow-list (never "*" — cookies are credentials). Falls back
# to the legacy CORS_ORIGINS var, minus any wildcard.
ALLOWED_ORIGINS = [
    o.rstrip("/") for o in (_list("ALLOWED_ORIGINS") or _list("CORS_ORIGINS",
                            "http://localhost:5173,http://127.0.0.1:5173"))
    if o != "*"
]

# Brute-force / abuse limits (services/rate_limit.py fixed windows).
SIGNUP_LIMIT_PER_IP_PER_DAY = _int("SIGNUP_LIMIT_PER_IP_PER_DAY", 5)
LOGIN_LIMIT_PER_15_MIN = _int("LOGIN_LIMIT_PER_15_MIN", 10)
DEMO_LOGIN_LIMIT_PER_IP_PER_DAY = _int("DEMO_LOGIN_LIMIT_PER_IP_PER_DAY", 30)

# Shared demo account ("Try demo"): view + chat, no upload/delete.
DEMO_ENABLED = os.getenv("DEMO_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@autoclip.local").strip().lower()
DEMO_DAILY_QUERY_LIMIT = _int("DEMO_DAILY_QUERY_LIMIT", 10)   # shared by every demo visitor

# New analyses started per UTC day, all non-admin users combined — analysis
# is the expensive step, so this caps the daily OpenRouter spend. 0 disables
# (docker-compose sets 2).
DAILY_ANALYSIS_LIMIT = _int("DAILY_ANALYSIS_LIMIT", 0)

# Chat quota backstop per client IP (catches one person with many accounts).
# 0 disables. Per-user limit is config.DAILY_QUERY_LIMIT.
IP_DAILY_QUERY_LIMIT = _int("IP_DAILY_QUERY_LIMIT", 20)

# Upload caps. MAX_VIDEOS_PER_USER counts active (not archived) uploads and
# is for non-admins only; the length cap applies to admins too unless
# VIDEO_MINUTES_CAP_ADMINS=0 (podcast/1-hour scope — longer analyses are
# what cost money).
MAX_VIDEOS_PER_USER = _int("MAX_VIDEOS_PER_USER", 3)
MAX_VIDEO_MINUTES_DEMO = _int("MAX_VIDEO_MINUTES_DEMO", 60)
VIDEO_MINUTES_CAP_ADMINS = os.getenv("VIDEO_MINUTES_CAP_ADMINS", "1").strip().lower() in {"1", "true", "yes"}

# Media files: when served behind our nginx, answer with X-Accel-Redirect to
# an `internal` location instead of streaming bytes through Python.
FILES_ACCEL_REDIRECT = os.getenv("FILES_ACCEL_REDIRECT", "0").strip().lower() in {"1", "true", "yes"}
FILES_ACCEL_PREFIX = os.getenv("FILES_ACCEL_PREFIX", "/_protected").rstrip("/")

# ─── Storage + retention (services/storage.py) ─────────────────
# Per-user quota over sources + clips on disk (non-admins). Uploads are
# refused for everyone while the disk has less than MIN_FREE_DISK_GB free.
STORAGE_QUOTA_MB = _int("STORAGE_QUOTA_MB", 1536)
STORAGE_QUOTA_BYTES = STORAGE_QUOTA_MB * 1024 * 1024
MIN_FREE_DISK_GB = _float("MIN_FREE_DISK_GB", 5.0)
# Nightly cleanup. 0 disables a rule. Admin and demo accounts are exempt
# (the owner's eval videos, the public demo's source).
SOURCE_RETENTION_DAYS = _int("SOURCE_RETENTION_DAYS", 7)     # source deleted -> video "archived"
CLIP_RETENTION_DAYS = _int("CLIP_RETENTION_DAYS", 30)        # rendered clips (files + rows)
INACTIVE_ACCOUNT_DAYS = _int("INACTIVE_ACCOUNT_DAYS", 60)    # all files deleted, account kept
CLEANUP_ENABLED = os.getenv("CLEANUP_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
CLEANUP_HOUR_UTC = _int("CLEANUP_HOUR_UTC", 3)               # runs once a day from this hour
CLEANUP_CHECK_SECONDS = _int("CLEANUP_CHECK_SECONDS", 900)   # how often the loop wakes up
