"""Readiness checks for GET /api/health/ready (deploy smoke test, uptime monitor).

/api/health stays the cheap liveness probe (Docker healthcheck). /ready
answers 200 only when the app can actually serve a request:

  db          SELECT 1
  redis       PING (skipped when REDIS_URL is unset — local dev)
  disk        free space >= READY_MIN_FREE_DISK_GB (below MIN_FREE_DISK_GB
              uploads are paused but the app still works, so that's only
              reported, not a failure)
  ffmpeg      ffmpeg + ffprobe on PATH
  openrouter  key set; balance from /credits, cached READY_OPENROUTER_CACHE_SECONDS.
              A slow or failing OpenRouter is "unknown", never a failure —
              only a key that is missing or known to be out of credit
              (<= READY_MIN_OPENROUTER_USD) fails readiness.

The response never includes the balance itself (the endpoint is public).
"""
from __future__ import annotations
import logging
import os
import shutil
import threading
import time

from autoclip import config
from autoclip.auth import settings

logger = logging.getLogger(__name__)

READY_MIN_FREE_DISK_GB = float(os.getenv("READY_MIN_FREE_DISK_GB", "1"))
READY_MIN_OPENROUTER_USD = float(os.getenv("READY_MIN_OPENROUTER_USD", "0"))
READY_OPENROUTER_CACHE_SECONDS = int(os.getenv("READY_OPENROUTER_CACHE_SECONDS", "300"))
READY_OPENROUTER_TIMEOUT = float(os.getenv("READY_OPENROUTER_TIMEOUT", "3"))
GB = 1024 ** 3

_balance_cache: dict = {"at": 0.0, "value": None}   # value: float, or None = unknown
_balance_lock = threading.Lock()


def check_db() -> dict:
    from sqlalchemy import text
    from autoclip.database import engine
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


def check_redis() -> dict:
    url = os.getenv("REDIS_URL", "")
    if not url:
        return {"ok": True, "skipped": True}
    import redis
    client = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    try:
        client.ping()
    finally:
        client.close()
    return {"ok": True}


def check_disk() -> dict:
    from autoclip.services.storage import free_disk_bytes
    free = free_disk_bytes()
    return {"ok": free >= READY_MIN_FREE_DISK_GB * GB, "free_gb": round(free / GB, 1),
            "uploads_paused": settings.MIN_FREE_DISK_GB > 0 and free < settings.MIN_FREE_DISK_GB * GB}


def check_ffmpeg() -> dict:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    return {"ok": not missing, **({"missing": missing} if missing else {})}


def _fetch_balance() -> float | None:
    """USD left on the OpenRouter account, or None when it can't be told."""
    import httpx
    try:
        r = httpx.get(f"{config.OPENROUTER_BASE_URL.rstrip('/')}/credits",
                      headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                      timeout=READY_OPENROUTER_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json().get("data") or {}
        return float(data["total_credits"]) - float(data["total_usage"])
    except Exception as e:  # timeouts, DNS, odd JSON: unknown, not down
        logger.info("openrouter balance check failed: %s", e)
        return None


def openrouter_balance(now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    with _balance_lock:
        if now - _balance_cache["at"] < READY_OPENROUTER_CACHE_SECONDS:
            return _balance_cache["value"]
    value = _fetch_balance()
    with _balance_lock:
        _balance_cache.update(at=now, value=value)
    return value


def check_openrouter() -> dict:
    if not config.OPENROUTER_API_KEY:
        return {"ok": False, "error": "OPENROUTER_API_KEY is not set"}
    balance = openrouter_balance()
    if balance is None:
        return {"ok": True, "balance": "unknown"}
    if balance <= READY_MIN_OPENROUTER_USD:
        return {"ok": False, "balance": "exhausted"}
    return {"ok": True, "balance": "ok"}


CHECKS = ("db", "redis", "disk", "ffmpeg", "openrouter")
CHECK_TIMEOUT = 5.0   # per check; a hung dependency is a failure, not a hung probe


def run_check(name: str) -> dict:
    try:
        return globals()[f"check_{name}"]()
    except Exception as e:
        logger.warning("readiness check %s failed: %s", name, e)
        return {"ok": False, "error": type(e).__name__}


async def readiness() -> tuple[bool, dict]:
    """All checks concurrently, each bounded by CHECK_TIMEOUT."""
    import asyncio

    async def one(name: str) -> dict:
        try:
            return await asyncio.wait_for(asyncio.to_thread(run_check, name), CHECK_TIMEOUT)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "timeout"}

    results = dict(zip(CHECKS, await asyncio.gather(*(one(n) for n in CHECKS))))
    return all(r.get("ok") for r in results.values()), results
