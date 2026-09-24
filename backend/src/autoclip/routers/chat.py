"""Chat router — conversational interface for the video clipping pipeline.

Delegates to the deep-agent orchestrator (autoclip.agent.orchestrator)
instead of the old fixed-intent parser. State that used to live in an
in-process `_analysis_cache` dict (a real bug under multiple workers/
replicas) now lives in the DB (Video/Clip/MomentRecord) and the LangGraph
Postgres checkpointer — both already durable, shared, multi-worker-safe.
"""
from __future__ import annotations
import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional
from sse_starlette.sse import EventSourceResponse
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from autoclip.services import events as pipeline_events
from autoclip.database import SessionLocal
from autoclip.models import Video
from autoclip.agent.orchestrator import orchestrator
from autoclip.config import DAILY_QUERY_LIMIT
from autoclip.services import rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    message: str
    video_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    intent: str = "agent"
    clips: Optional[list[dict]] = None
    moment_count: Optional[int] = None
    is_processing: bool = False
    queries_remaining: Optional[int] = None


def _extract_clips_from_run(result: dict) -> list[dict]:
    """Pull clip lists out of any tool-call results in the agent run's
    message history (select_and_produce_clips / modify_clip results)."""
    clips: list[dict] = []
    for msg in result.get("messages", []):
        if isinstance(msg, ToolMessage) and msg.name in ("select_and_produce_clips", "modify_clip"):
            try:
                content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(content, list):
                clips.extend(content)
            elif isinstance(content, dict) and isinstance(content.get("clips"), list):
                clips.extend(content["clips"])          # select_and_produce_clips result
            elif isinstance(content, dict) and "id" in content:
                clips.append(content)                    # modify_clip result
    return clips


def _final_text(result: dict) -> str:
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return "I couldn't come up with a reply — try rephrasing your request."


@router.get("/quota")
async def chat_quota(request: Request):
    """How many agent runs this visitor has left today."""
    return {
        "limit": DAILY_QUERY_LIMIT,
        "remaining": rate_limit.remaining(rate_limit.client_ip(request)),
        "resets_in_seconds": rate_limit.seconds_until_reset(),
    }


@router.post("/message", response_model=ChatResponse)
async def chat_message(msg: ChatMessage, request: Request, response: Response):
    """Process a chat message via the deep-agent orchestrator and return a
    response. Each call spends one of the visitor's daily queries."""
    video_id = msg.video_id
    message = msg.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if video_id:
        db = SessionLocal()
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                return ChatResponse(response="I don't see a video with that ID — try uploading one first.")
        finally:
            db.close()

    # Only charge the quota once the request is valid and about to hit the models
    ip = rate_limit.client_ip(request)
    allowed, left, reason = rate_limit.try_consume(ip)
    if not allowed:
        hours = max(1, round(rate_limit.seconds_until_reset() / 3600))
        detail = (
            f"You've used your {DAILY_QUERY_LIMIT} free queries for today. They reset in about {hours}h."
            if reason == "user"
            else "The demo has hit its daily limit. Please try again tomorrow."
        )
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(rate_limit.seconds_until_reset()), "X-Queries-Remaining": "0"},
        )
    response.headers["X-Queries-Remaining"] = str(left)

    run_config = {"configurable": {"thread_id": video_id or "no-video"}}
    context_message = (
        f"[current video_id: {video_id}]\n{message}" if video_id
        else f"[no video uploaded yet]\n{message}"
    )

    try:
        result = await asyncio.to_thread(
            orchestrator.invoke,
            {"messages": [HumanMessage(content=context_message)]},
            run_config,
        )
    except Exception as e:
        logger.exception("orchestrator run failed")
        rate_limit.refund(ip)  # our failure, not the visitor's — don't charge them
        return ChatResponse(
            response=f"Something went wrong: {e}. Try again.",
            queries_remaining=rate_limit.remaining(ip),
        )

    clips = _extract_clips_from_run(result)
    response_text = _final_text(result)

    moment_count = None
    if video_id:
        from autoclip.agent.tools import get_video_status
        status = get_video_status.invoke({"video_id": video_id})
        moment_count = status.get("moment_count") if status.get("exists") else None

    return ChatResponse(
        response=response_text,
        clips=clips or None,
        moment_count=moment_count,
        queries_remaining=left,
    )


@router.get("/stream/{video_id}")
async def stream_pipeline_events(video_id: str, request: Request):
    """SSE stream of live pipeline events for a video — unchanged from
    before: chunk_analyzer/global_fusion/production publish events via
    Redis pub/sub, the frontend listens while a chat turn is in flight."""
    async def gen():
        yield {"event": "open", "data": json.dumps({"video_id": video_id})}
        try:
            async for evt in pipeline_events.subscribe(video_id):
                if await request.is_disconnected():
                    return
                yield {"event": evt.get("type", "message"), "data": json.dumps(evt.get("data", {}))}
                if evt.get("type") == "done":
                    return
        except asyncio.CancelledError:
            return

    return EventSourceResponse(gen())


@router.get("/analysis/{video_id}")
async def get_analysis_status(video_id: str):
    """Check analysis/clip state for a video — now reads the DB directly
    (get_video_status tool logic) instead of an in-process cache."""
    from autoclip.agent.tools import get_video_status
    status = get_video_status.invoke({"video_id": video_id})
    if not status.get("exists"):
        return {"analyzed": False, "moment_count": 0}
    return {
        "analyzed": status.get("has_analysis", False),
        "duration": status.get("duration", 0.0),
        "moment_count": status.get("moment_count", 0),
        "clips_count": status.get("clip_count", 0),
    }
