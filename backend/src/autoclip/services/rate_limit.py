"""Daily query quota for the public demo.

Every chat message runs the agent, and every agent run spends OpenRouter
credits — so each visitor (by client IP) gets DAILY_QUERY_LIMIT messages per
UTC day. An optional DAILY_GLOBAL_QUERY_LIMIT caps the whole site, as a
backstop against IP rotation.

Counters live in Redis (shared across workers/replicas, survive restarts).
If Redis is unavailable, an in-process dict keeps the limit working on a
single worker rather than failing open.
"""
from __future__ import annotations

import ipaddress
import logging
import threading
from datetime import datetime, timedelta, timezone

from fastapi import Request

from autoclip.config import DAILY_GLOBAL_QUERY_LIMIT, DAILY_QUERY_LIMIT
from autoclip.services.events import _get_sync

logger = logging.getLogger(__name__)

_KEY_TTL_SECONDS = 2 * 24 * 3600  # outlives the day it counts, then cleans itself up
_local_counts: dict[str, int] = {}
_local_lock = threading.Lock()


def client_ip(request: Request) -> str:
    """Real visitor IP. X-Real-IP is only trusted when the request came
    through our own nginx (a private/loopback peer) — a client hitting the
    backend directly could otherwise spoof it to reset their quota."""
    peer = request.client.host if request.client else "unknown"
    try:
        trusted_proxy = ipaddress.ip_address(peer).is_private or ipaddress.ip_address(peer).is_loopback
    except ValueError:
        trusted_proxy = False
    if trusted_proxy:
        forwarded = request.headers.get("x-real-ip")
        if forwarded:
            return forwarded.strip()
    return peer


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def seconds_until_reset() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds())


def _keys(ip: str) -> tuple[str, str]:
    day = _today()
    return f"quota:chat:{day}:{ip}", f"quota:chat:{day}:__global__"


def _incr(key: str, amount: int = 1) -> int:
    client = _get_sync()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incrby(key, amount)
            pipe.expire(key, _KEY_TTL_SECONDS)
            return int(pipe.execute()[0])
        except Exception:
            logger.warning("rate limit: redis unavailable, using in-process counter", exc_info=True)
    with _local_lock:
        _local_counts[key] = _local_counts.get(key, 0) + amount
        return _local_counts[key]


def _get(key: str) -> int:
    client = _get_sync()
    if client is not None:
        try:
            return int(client.get(key) or 0)
        except Exception:
            pass
    with _local_lock:
        return _local_counts.get(key, 0)


def remaining(ip: str) -> int:
    user_key, _ = _keys(ip)
    return max(0, DAILY_QUERY_LIMIT - _get(user_key))


def try_consume(ip: str) -> tuple[bool, int, str]:
    """Reserve one query. Returns (allowed, remaining_after, reason)."""
    user_key, global_key = _keys(ip)

    used = _incr(user_key)
    if used > DAILY_QUERY_LIMIT:
        _incr(user_key, -1)  # don't let blocked attempts pile up
        return False, 0, "user"

    if DAILY_GLOBAL_QUERY_LIMIT > 0:
        if _incr(global_key) > DAILY_GLOBAL_QUERY_LIMIT:
            _incr(global_key, -1)
            _incr(user_key, -1)
            return False, max(0, DAILY_QUERY_LIMIT - used + 1), "global"

    return True, max(0, DAILY_QUERY_LIMIT - used), ""


def refund(ip: str) -> None:
    """Give the query back when the run failed on our side (e.g. provider error)."""
    user_key, global_key = _keys(ip)
    _incr(user_key, -1)
    if DAILY_GLOBAL_QUERY_LIMIT > 0:
        _incr(global_key, -1)
