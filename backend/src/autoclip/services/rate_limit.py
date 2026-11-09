"""Rate limits and daily chat quotas (Redis fixed-window counters).

Two kinds of limit live here:

  • `hit(name, subject, limit, window)` — generic fixed-window limiter used
    for signup (per IP / day) and login (per IP+email / 15 min).
  • The chat quota. Every chat message runs the agent, and every agent run
    spends OpenRouter credits, so each *user* gets DAILY_QUERY_LIMIT runs per
    UTC day (admins: unlimited; the shared demo account: one shared
    DEMO_DAILY_QUERY_LIMIT pool). A per-IP backstop (IP_DAILY_QUERY_LIMIT)
    catches one person with many accounts, and DAILY_GLOBAL_QUERY_LIMIT caps
    the whole site.

Counters live in Redis (shared across workers/replicas, survive restarts).
If Redis is unavailable, an in-process dict keeps the limits working on a
single worker rather than failing open.
"""
from __future__ import annotations

import ipaddress
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request

from autoclip.auth import settings as auth_settings
from autoclip import config
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


def _incr(key: str, amount: int = 1, ttl: int = _KEY_TTL_SECONDS) -> int:
    client = _get_sync()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incrby(key, amount)
            pipe.expire(key, ttl)
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


# ─── generic fixed-window limiter ───────────────────────────────

def hit(name: str, subject: str, limit: int, window_seconds: int) -> bool:
    """Count one attempt; False once `limit` attempts happened in the current
    window. limit <= 0 disables the check."""
    if limit <= 0:
        return True
    bucket = int(time.time() // window_seconds)
    key = f"rl:{name}:{bucket}:{subject}"
    return _incr(key, 1, ttl=window_seconds + 60) <= limit


# ─── chat quota ─────────────────────────────────────────────────

def chat_limit(user) -> Optional[int]:
    """Daily agent-run limit for this user; None = unlimited (admin)."""
    if user.is_admin:
        return None
    if user.is_demo:
        return auth_settings.DEMO_DAILY_QUERY_LIMIT
    return DAILY_QUERY_LIMIT


def _user_key(user) -> str:
    subject = "demo" if user.is_demo else f"u{user.id}"
    return f"quota:chat:{_today()}:{subject}"


def _ip_key(ip: str) -> str:
    return f"quota:chat:{_today()}:ip:{ip}"


def _global_key() -> str:
    return f"quota:chat:{_today()}:__global__"


@dataclass
class Charge:
    """Counters incremented by one try_consume(), so refund() undoes exactly those."""
    keys: list = field(default_factory=list)   # key names, or (key, amount)


def used(user) -> int:
    """Agent runs charged to this user today (admins are never charged)."""
    return _get(_user_key(user))


def remaining(user) -> Optional[int]:
    limit = chat_limit(user)
    if limit is None:
        return None
    return max(0, limit - _get(_user_key(user)))


def try_consume(user, ip: str) -> tuple[bool, Optional[int], str, Charge]:
    """Reserve one agent run. Returns (allowed, remaining_after, reason, charge);
    reason is "user", "ip" or "global" when refused."""
    charge = Charge()
    limit = chat_limit(user)
    if limit is None:
        return True, None, "", charge

    key = _user_key(user)
    used = _incr(key)
    if used > limit:
        _incr(key, -1)  # don't let blocked attempts pile up
        return False, 0, "user", charge
    charge.keys.append(key)

    checks = []
    if auth_settings.IP_DAILY_QUERY_LIMIT > 0:
        checks.append((_ip_key(ip), auth_settings.IP_DAILY_QUERY_LIMIT, "ip"))
    if DAILY_GLOBAL_QUERY_LIMIT > 0:
        checks.append((_global_key(), DAILY_GLOBAL_QUERY_LIMIT, "global"))
    for k, lim, reason in checks:
        if _incr(k) > lim:
            _incr(k, -1)
            refund(charge)
            return False, max(0, limit - used + 1), reason, Charge()
        charge.keys.append(k)

    return True, max(0, limit - used), "", charge


# ─── analysis minutes (site-wide) ───────────────────────────────

def _analysis_key() -> str:
    return f"quota:analysis_min:{_today()}"


def analysis_minutes_used() -> int:
    return _get(_analysis_key())


def try_consume_analysis_minutes(minutes: int) -> tuple[bool, Charge]:
    """Reserve `minutes` of today's site-wide analysis budget
    (DAILY_ANALYSIS_MINUTES_LIMIT, 0 = unlimited). Refund with refund()."""
    limit = config.DAILY_ANALYSIS_MINUTES_LIMIT
    charge = Charge()
    if limit <= 0 or minutes <= 0:
        return True, charge
    key = _analysis_key()
    if _incr(key, minutes) > limit:
        _incr(key, -minutes)
        return False, charge
    charge.keys.append((key, minutes))
    return True, charge


def refund(charge: Optional[Charge]) -> None:
    """Give the run back when it failed on our side (e.g. provider error)."""
    if not charge:
        return
    for k in charge.keys:
        key, amount = k if isinstance(k, tuple) else (k, 1)
        _incr(key, -amount)
    charge.keys = []
