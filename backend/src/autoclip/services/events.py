"""Redis pub/sub for live pipeline events.

Publishers (chunk_analyzer, global_fusion) call publish_*() to fire events
into the `pipeline:{video_id}` channel. The SSE endpoint subscribes to
that channel and pipes events to the frontend, so users see moments and
clips appear live as the pipeline runs.

If REDIS_URL is unset (local dev without Redis), publish_* is a no-op
and SSE simply returns no incremental events.
"""
from __future__ import annotations
import os
import json
import logging
import asyncio
from dataclasses import asdict, is_dataclass
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")

_sync_client = None
_async_client = None


def _get_sync():
    global _sync_client
    if not REDIS_URL:
        return None
    if _sync_client is None:
        import redis  # local import keeps optional dep optional
        _sync_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _sync_client


def _get_async():
    global _async_client
    if not REDIS_URL:
        return None
    if _async_client is None:
        import redis.asyncio as aredis
        _async_client = aredis.from_url(REDIS_URL, decode_responses=True)
    return _async_client


def _channel(video_id: str) -> str:
    return f"pipeline:{video_id}"


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


def publish(video_id: str, event_type: str, payload: dict | list) -> None:
    """Fire-and-forget publish. Silently no-ops if Redis isn't configured."""
    client = _get_sync()
    if client is None:
        return
    try:
        msg = json.dumps({"type": event_type, "data": _to_jsonable(payload)})
        client.publish(_channel(video_id), msg)
    except Exception as e:
        logger.debug("publish failed (non-fatal): %s", e)


def publish_chunk_done(video_id: str, chunk_index: int, moments: list) -> None:
    publish(video_id, "chunk_done", {
        "chunk_index": chunk_index,
        "moment_count": len(moments),
        "moments": moments,
    })


def publish_moments(video_id: str, moments: list) -> None:
    publish(video_id, "moments", {"moments": moments})


def publish_clip_ready(video_id: str, clip) -> None:
    publish(video_id, "clip_ready", {"clip": clip})


def publish_done(video_id: str, summary: dict) -> None:
    publish(video_id, "done", summary)


async def subscribe(video_id: str, stop_event: Optional[asyncio.Event] = None) -> AsyncIterator[dict]:
    """Async generator yielding decoded events from `pipeline:{video_id}`.

    If REDIS_URL isn't set, yields nothing (SSE just keeps the connection alive
    until the request finishes — frontend falls back to the JSON response).
    """
    client = _get_async()
    if client is None:
        return
    pubsub = client.pubsub()
    await pubsub.subscribe(_channel(video_id))
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                continue
            data = msg.get("data")
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                logger.warning("subscribe: dropping non-json msg: %r", data[:200])
    finally:
        try:
            await pubsub.unsubscribe(_channel(video_id))
            await pubsub.close()
        except Exception:
            pass
