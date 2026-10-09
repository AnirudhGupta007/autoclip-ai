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

# Chat quota backstop per client IP (catches one person with many accounts).
# 0 disables. Per-user limit is config.DAILY_QUERY_LIMIT.
IP_DAILY_QUERY_LIMIT = _int("IP_DAILY_QUERY_LIMIT", 20)

# Upload caps for non-admin users.
MAX_VIDEOS_PER_USER = _int("MAX_VIDEOS_PER_USER", 5)
MAX_VIDEO_MINUTES_DEMO = _int("MAX_VIDEO_MINUTES_DEMO", 60)

# Media files: when served behind our nginx, answer with X-Accel-Redirect to
# an `internal` location instead of streaming bytes through Python.
FILES_ACCEL_REDIRECT = os.getenv("FILES_ACCEL_REDIRECT", "0").strip().lower() in {"1", "true", "yes"}
FILES_ACCEL_PREFIX = os.getenv("FILES_ACCEL_PREFIX", "/_protected").rstrip("/")
