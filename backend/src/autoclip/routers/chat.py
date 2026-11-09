"""Chat router — conversational interface for the video clipping pipeline.

Delegates to the deep-agent orchestrator (autoclip.agent.orchestrator).
Durable state lives in the DB (Video/Clip/MomentRecord), Redis (analysis
progress, quota) and the LangGraph Postgres checkpointer (chat threads).

Async analysis contract
-----------------------
All endpoints require a signed-in user; another user's video_id is a 404.

POST /api/chat/message {message, video_id?, conversation_id?}
  • With conversation_id (the caller's, else 404): the agent thread is
    `u:{uid}:c:{cid}` and the prompt + reply are stored in that
    conversation (services/conversations.py). Without it: thread per video.
  • Video not analysed yet (uploaded/failed): starts the background analysis
    job, charges ONE quota unit, and returns immediately with
    `is_processing=true, pending_request=true, analysis={status, progress,
    eta_seconds, ...}`. No agent run happens. The frontend keeps the message
    and re-sends it after the `analysis_done` SSE event; that follow-up is
    free (one logical request = one unit).
  • Video analysing: same shape, nothing charged, nothing started twice.
  • Video analysed (or no video): normal agent turn; `clips` contains only
    the clips created/modified in THIS turn.
GET /api/chat/stream/{video_id}  SSE: `status` snapshot on connect, then the
  events listed in services/events.py (analysis_progress, analysis_done, ...).
GET /api/chat/analysis/{video_id}  polling fallback (same fields as `analysis`).
"""
from __future__ import annotations
import json
import asyncio
import logging
import re
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from typing import Optional
from sse_starlette.sse import EventSourceResponse
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from sqlalchemy.orm import Session

from autoclip.services import events as pipeline_events
from autoclip.agent.orchestrator import orchestrator
from autoclip.agent import tools as agent_tools
from autoclip.auth.deps import current_user, get_owned_video
from autoclip.database import get_db
from autoclip.models import User
from autoclip.services import conversations, rate_limit
from autoclip.services.conversations import get_owned_conversation
from autoclip.utils import analysis_jobs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(current_user)])

GENERIC_ERROR = "Something went wrong on our side and your query wasn't charged. Please try again."


class ChatMessage(BaseModel):
    message: str = Field(max_length=2000)
    video_id: Optional[str] = None
    # Chat history (routers/conversations.py). Optional: without it the
    # thread is per user + video, as before.
    conversation_id: Optional[str] = Field(default=None, max_length=64)
    # Legacy per-tab id from older frontends. Ignored: threads are now scoped
    # to the authenticated user (see chat_thread_id).
    client_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    intent: str = "agent"
    clips: Optional[list[dict]] = None
    moment_count: Optional[int] = None
    is_processing: bool = False
    pending_request: bool = False
    analysis: Optional[dict] = None
    queries_remaining: Optional[int] = None


def chat_thread_id(user_id: int, video_id: Optional[str], conversation_id: Optional[str] = None) -> str:
    """The ONE place a LangGraph chat thread id is built.

    Scoped to the authenticated user (and conversation, or video for callers
    without one), so visitors never share a thread and a thread can't collide
    with any other user's — or with the analysis pipeline's own ids. Old
    `u:{uid}:v:{vid}` checkpoints stay in Postgres, unread once a
    conversation is used.
    """
    if conversation_id:
        return f"u:{int(user_id)}:c:{conversation_id}"
    return f"u:{int(user_id)}:v:{video_id}" if video_id else f"u:{int(user_id)}:novideo"


def _credit_subject(user: User) -> str:
    """Owner of the analysis follow-up credit (was the client IP pre-auth)."""
    return f"u{user.id}"


def _tool_clips_after_last_human(result: dict) -> list[dict]:
    """Fallback: clip dicts from top-level tool results of THIS turn only."""
    messages = result.get("messages", [])
    last_human = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    clips: list[dict] = []
    for msg in messages[last_human + 1:]:
        if isinstance(msg, ToolMessage) and msg.name in ("select_and_produce_clips", "modify_clip"):
            try:
                content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(content, dict) and isinstance(content.get("clips"), list):
                clips.extend(content["clips"])
            elif isinstance(content, dict) and "id" in content:
                clips.append(content)
    return clips


def _final_text(result: dict) -> str:
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return "I couldn't come up with a reply — try rephrasing your request."


def _fmt_eta(seconds: Optional[int]) -> str:
    if not seconds:
        return "a few minutes"
    m = round(seconds / 60)
    return "under a minute" if m < 1 else f"about {m} min"


def _analysing_text(state: dict) -> str:
    return (f"Still analysing your video — {state.get('progress', 0)}% done, "
            f"{_fmt_eta(state.get('eta_seconds'))} left. I'll pick up your request "
            "automatically as soon as it's ready.")


def _started_text(state: dict) -> str:
    return (f"First I need to watch the whole video — analysis started, "
            f"{_fmt_eta(state.get('eta_seconds'))}. You'll see progress here, and I'll "
            "make your clips automatically when it's done.")


def _public_analysis(state: dict) -> dict:
    keys = ("status", "progress", "stage", "eta_seconds", "chunks_done", "chunks_total",
            "moment_count", "duration", "error")
    return {k: state.get(k) for k in keys}


@router.get("/quota")
async def chat_quota(user: User = Depends(current_user)):
    """How many agent runs this user has left today (limit null = unlimited)."""
    return {
        "limit": rate_limit.chat_limit(user),
        "remaining": rate_limit.remaining(user),
        "resets_in_seconds": rate_limit.seconds_until_reset(),
    }


def _quota_exceeded(reason: str, user: User) -> HTTPException:
    hours = max(1, round(rate_limit.seconds_until_reset() / 3600))
    if reason == "user" and user.is_demo:
        detail = (f"The demo account has used today's shared queries. They reset in about {hours}h "
                  "— or sign up for your own daily queries.")
    elif reason == "user":
        detail = (f"You've used your {rate_limit.chat_limit(user)} free queries for today. "
                  f"They reset in about {hours}h.")
    elif reason == "ip":
        detail = "This network has used its daily queries. Please try again tomorrow."
    else:
        detail = "The demo has hit its daily limit. Please try again tomorrow."
    return HTTPException(
        status_code=429, detail=detail,
        headers={"Retry-After": str(rate_limit.seconds_until_reset()), "X-Queries-Remaining": "0"},
    )


def _remaining_header(response: Response, left: Optional[int]) -> None:
    if left is not None:
        response.headers["X-Queries-Remaining"] = str(left)


@router.post("/message", response_model=ChatResponse)
async def chat_message(msg: ChatMessage, request: Request, response: Response,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Process a chat message. Never blocks on video analysis (see module doc)."""
    video_id = msg.video_id
    message = msg.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    ip = rate_limit.client_ip(request)
    credit_subject = _credit_subject(user)
    conv_id = msg.conversation_id or None
    if conv_id:
        get_owned_conversation(db, user, conv_id)  # 404 for anyone else's conversation

    async def _reply(resp: ChatResponse) -> ChatResponse:
        """Store the turn in the conversation (if any), then answer."""
        if conv_id:
            await asyncio.to_thread(conversations.record_turn, user.id, conv_id, message, resp.response,
                                    resp.clips, video_id=video_id, pending=resp.pending_request)
        return resp

    # ── Gate: the video must be analysed before the agent can do anything ──
    if video_id:
        get_owned_video(db, user, video_id)  # 404 for anyone else's video
        db.close()  # don't hold a pooled connection through a long agent run
        state = await asyncio.to_thread(analysis_jobs.video_state, video_id)
        if not state.get("exists"):
            raise HTTPException(404, "Video not found")

        if state["status"] == analysis_jobs.ANALYZING:
            return await _reply(ChatResponse(
                response=_analysing_text(state),
                is_processing=True, pending_request=True,
                analysis=_public_analysis(state),
                queries_remaining=rate_limit.remaining(user),
            ))

        if state["status"] != analysis_jobs.ANALYZED:
            allowed, left, reason, charge = rate_limit.try_consume(user, ip)
            if not allowed:
                raise _quota_exceeded(reason, user)

            def _on_fail(charge=charge, subj=credit_subject, vid=video_id):
                rate_limit.refund(charge)
                analysis_jobs.revoke_followup_credit(subj, vid)

            res = await asyncio.to_thread(analysis_jobs.start_analysis, video_id, _on_fail)
            if res["result"] == "archived":
                rate_limit.refund(charge)
                from autoclip.services.storage import ARCHIVED_MESSAGE
                return await _reply(ChatResponse(response=ARCHIVED_MESSAGE,
                                                 queries_remaining=rate_limit.remaining(user)))
            if res["result"] == "started":
                analysis_jobs.grant_followup_credit(credit_subject, video_id)
            else:
                rate_limit.refund(charge)
                left = rate_limit.remaining(user)
            st = res["state"]
            _remaining_header(response, left)
            if res["result"] == "already_analyzed":
                pass  # raced with a job that just finished — fall through to the agent
            else:
                return await _reply(ChatResponse(
                    response=_started_text(st),
                    is_processing=True, pending_request=True,
                    analysis=_public_analysis(st), queries_remaining=left,
                ))

    # ── Agent turn ──
    db.close()
    charge = None
    free = bool(video_id) and analysis_jobs.consume_followup_credit(credit_subject, video_id)
    if free:
        left = rate_limit.remaining(user)
    else:
        allowed, left, reason, charge = rate_limit.try_consume(user, ip)
        if not allowed:
            raise _quota_exceeded(reason, user)
    _remaining_header(response, left)

    # user_id travels two ways so every tool can check ownership without
    # trusting LLM-supplied ids: RunnableConfig (inherited by subagents) and
    # a ContextVar backstop set inside the worker thread below.
    run_config = {"configurable": {"thread_id": chat_thread_id(user.id, video_id, conv_id),
                                   "user_id": user.id, "conversation_id": conv_id}}
    context_message = (
        f"[current video_id: {video_id}]\n{message}" if video_id
        else f"[no video uploaded yet]\n{message}"
    )

    def _run_turn():
        bucket, token = agent_tools.begin_turn()
        user_token = agent_tools.set_current_user(user.id)
        request_token = agent_tools.set_current_request(message)
        try:
            result = orchestrator.invoke(
                {"messages": [HumanMessage(content=context_message)]}, run_config,
            )
        finally:
            agent_tools.reset_current_request(request_token)
            agent_tools.reset_current_user(user_token)
            agent_tools.end_turn(token)
        return result, bucket

    started = time.time()
    try:
        result, turn_clip_ids = await asyncio.to_thread(_run_turn)
    except Exception:
        logger.exception("orchestrator run failed (video=%s)", video_id)
        if free:
            analysis_jobs.grant_followup_credit(credit_subject, video_id)  # give the free pass back
        else:
            rate_limit.refund(charge)  # our failure, not the visitor's — don't charge them
        return await _reply(ChatResponse(response=GENERIC_ERROR, queries_remaining=rate_limit.remaining(user)))

    # Clips created/modified in THIS turn only (not the thread's history).
    clip_ids = list(turn_clip_ids)
    if not clip_ids and video_id:
        clip_ids = agent_tools.clips_recorded_since(video_id, started)
    clips = await asyncio.to_thread(agent_tools.clips_by_ids, clip_ids, user.id)
    if not clips:
        clips = _tool_clips_after_last_human(result)
    response_text = _final_text(result)

    moment_count = None
    analysis = None
    is_processing = False
    if video_id:
        st = await asyncio.to_thread(analysis_jobs.video_state, video_id)
        moment_count = st.get("moment_count") if st.get("exists") else None
        if st.get("status") == analysis_jobs.ANALYZING:
            # The agent itself kicked off a (re-)analysis this turn.
            analysis, is_processing = _public_analysis(st), True

    return await _reply(ChatResponse(
        response=response_text,
        clips=clips or None,
        moment_count=moment_count,
        is_processing=is_processing,
        analysis=analysis,
        queries_remaining=left,
    ))


@router.get("/stream/{video_id}")
async def stream_pipeline_events(video_id: str, request: Request, conversation_id: Optional[str] = None,
                                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    """SSE stream of live pipeline events for a video (Redis pub/sub).

    Sends a `status` snapshot first so a client that connects late (or
    reconnects) knows where analysis stands. Never closes itself on an event —
    the client closes it when it's done listening. `conversation_id` is
    accepted and ignored (events are per video)."""
    get_owned_video(db, user, video_id)
    db.close()  # the stream can stay open for an hour

    async def gen():
        try:
            state = await asyncio.to_thread(analysis_jobs.video_state, video_id)
            yield {"event": "status", "data": json.dumps(_public_analysis(state))}
            async for evt in pipeline_events.subscribe(video_id):
                if await request.is_disconnected():
                    return
                yield {"event": evt.get("type", "message"), "data": json.dumps(evt.get("data", {}))}
        except asyncio.CancelledError:
            return

    return EventSourceResponse(gen(), ping=15)


@router.get("/analysis/{video_id}")
async def get_analysis_status(video_id: str, user: User = Depends(current_user),
                              db: Session = Depends(get_db)):
    """Analysis/clip state for a video — polling fallback for the SSE stream."""
    get_owned_video(db, user, video_id)
    state = await asyncio.to_thread(analysis_jobs.video_state, video_id)
    if not state.get("exists"):
        return {"analyzed": False, "status": "not_found", "moment_count": 0}
    return {
        "analyzed": state["status"] == analysis_jobs.ANALYZED,
        "clips_count": state.get("clip_count", 0),
        **_public_analysis(state),
    }
