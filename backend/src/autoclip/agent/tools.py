"""Tools the deep-agent orchestrator can call.

Each tool is a thin wrapper around existing, already-working code — the
LangGraph Send-API chunk-analysis subgraph, the ffmpeg production pipeline,
the RAG retriever, and the DB models. No media-processing logic is
duplicated here; the tools just give the agent a way to invoke it.

Authorisation: tool arguments come from the LLM, so ids in them are never
trusted. The chat router passes the signed-in user's id in the run's
RunnableConfig (`configurable.user_id`, inherited by deepagents subagents)
and in a ContextVar backstop; every tool resolves the user from those and
answers "not found" for videos/clips that user doesn't own.
"""
from __future__ import annotations
import contextvars
import json
import logging
import threading
import time
from typing import Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from autoclip.database import SessionLocal
from autoclip.models import Video, Clip, MomentRecord
from autoclip.pipeline.graph import generation_only
from autoclip.pipeline.state import PipelineState, ClipConfig, Moment
from autoclip.rag import selection as S
from autoclip.services.clip_reprocess import apply_clip_update, ClipUpdateError
from autoclip.schemas import ClipUpdate
from autoclip.utils import analysis_jobs
from autoclip.utils.paths import public_url, video_output_dir

logger = logging.getLogger(__name__)

# ─── "clips touched in THIS chat turn" ─────────────────────────
# The chat router used to scrape every ToolMessage in the (checkpointed)
# thread, so turn N returned the clips of turns 1..N. Tools now report the
# clip ids they create/modify to a per-turn collector. A ContextVar carries
# it into tool calls (LangGraph copies context into its worker threads, also
# for subagents); a time-stamped per-video log is the fallback if the
# context ever doesn't propagate.
_turn_collector: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar(
    "autoclip_turn_clips", default=None)
_recent: list[tuple[float, str, str]] = []   # (ts, video_id, clip_id)
_recent_lock = threading.Lock()


# ─── who is this turn for? ──────────────────────────────────────
_current_user: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "autoclip_current_user", default=None)


# The user's raw chat message for this turn — the clip re-ranker judges
# candidates against it, not only against the agent's (often terse) query.
_current_request: contextvars.ContextVar[str] = contextvars.ContextVar(
    "autoclip_current_request", default="")


def set_current_request(text: str) -> contextvars.Token:
    return _current_request.set((text or "")[:1000])


def reset_current_request(token: contextvars.Token) -> None:
    _current_request.reset(token)


def set_current_user(user_id: int) -> contextvars.Token:
    return _current_user.set(int(user_id))


def reset_current_user(token: contextvars.Token) -> None:
    _current_user.reset(token)


def _user_id(config: Optional[RunnableConfig]) -> Optional[int]:
    """The authenticated user for this tool call, or None (= deny).

    Both sources must agree when both are present; a mismatch means
    something is badly wrong, so refuse rather than guess."""
    cfg_uid = None
    if isinstance(config, dict):
        cfg_uid = (config.get("configurable") or {}).get("user_id")
    ctx_uid = _current_user.get()
    if cfg_uid is not None and ctx_uid is not None and int(cfg_uid) != int(ctx_uid):
        logger.error("agent tool: user mismatch config=%s context=%s", cfg_uid, ctx_uid)
        return None
    uid = cfg_uid if cfg_uid is not None else ctx_uid
    if uid is None:
        return None
    if isinstance(config, dict) and not _thread_belongs_to(int(uid), config):
        return None
    return int(uid)


def _thread_belongs_to(user_id: int, config: dict) -> bool:
    """The run's chat thread must be this user's: `u:{uid}:...`, and for a
    conversation thread `u:{uid}:c:{cid}` the conversation must be theirs
    (the router already checked; this catches a forged or stale config)."""
    configurable = config.get("configurable") or {}
    thread = str(configurable.get("thread_id") or "")
    if not thread.startswith("u:"):
        return True   # no chat thread (direct tool use, tests, scripts)
    parts = thread.split(":")
    if len(parts) < 3 or parts[1] != str(user_id):
        logger.error("agent tool: thread %s does not belong to user %s", thread, user_id)
        return False
    if parts[2] == "c":
        cid = ":".join(parts[3:])
        if configurable.get("conversation_id") not in (None, cid):
            return False
        from autoclip.services.conversations import user_owns_conversation
        if not user_owns_conversation(user_id, cid):
            logger.error("agent tool: conversation %s is not user %s's", cid, user_id)
            return False
    return True


def _owns_video(user_id: Optional[int], video_id: str) -> bool:
    if user_id is None or not video_id:
        return False
    db: Session = SessionLocal()
    try:
        return db.query(Video.id).filter(Video.id == str(video_id), Video.user_id == user_id).first() is not None
    finally:
        db.close()


def _is_admin(user_id: Optional[int]) -> bool:
    from autoclip.models import User
    db: Session = SessionLocal()
    try:
        return bool(user_id is not None and db.query(User.id).filter(
            User.id == user_id, User.is_admin.is_(True)).first())
    finally:
        db.close()


def _archived_message() -> str:
    from autoclip.services.storage import ARCHIVED_MESSAGE
    return ARCHIVED_MESSAGE


def begin_turn() -> tuple[list, contextvars.Token]:
    bucket: list = []
    return bucket, _turn_collector.set(bucket)


def end_turn(token: contextvars.Token) -> None:
    _turn_collector.reset(token)


def _record_clip(video_id: str, clip_id: str) -> None:
    bucket = _turn_collector.get()
    if bucket is not None and clip_id not in bucket:
        bucket.append(clip_id)
    now = time.time()
    with _recent_lock:
        _recent.append((now, video_id, clip_id))
        del _recent[: max(0, len(_recent) - 500)]


def clips_recorded_since(video_id: str, since: float) -> list[str]:
    with _recent_lock:
        out = [c for t, v, c in _recent if t >= since and v == video_id]
    return list(dict.fromkeys(out))


def clip_to_dict(clip) -> dict:
    d = {}
    for k in ["id", "title", "start_time", "end_time", "duration",
              "file_path", "thumbnail_path", "transcript", "scores",
              "overall_score", "frame", "style_tags", "caption_style"]:
        d[k] = getattr(clip, k, None)
    if not d.get("frame") and d.get("file_path"):
        # Clip rows don't store the aspect; read it from the rendered file.
        from autoclip.services.clip_reprocess import infer_frame
        from autoclip.utils.paths import resolve_path
        d["frame"] = infer_frame(resolve_path(d["file_path"]))
    d["file_url"] = public_url(d.get("file_path"))
    d["thumbnail_url"] = public_url(d.get("thumbnail_path"))
    return d


_clip_to_dict = clip_to_dict  # back-compat name


def clips_by_ids(clip_ids: list[str], user_id: Optional[int] = None) -> list[dict]:
    """Clip dicts in the given order; with user_id, only that user's clips."""
    if not clip_ids:
        return []
    db: Session = SessionLocal()
    try:
        q = db.query(Clip).filter(Clip.id.in_(clip_ids))
        if user_id is not None:
            q = q.join(Video, Clip.video_id == Video.id).filter(Video.user_id == user_id)
        rows = {c.id: c for c in q.all()}
        return [clip_to_dict(rows[i]) for i in clip_ids if i in rows]
    finally:
        db.close()


@tool
def get_video_status(video_id: str, config: RunnableConfig = None) -> dict:
    """Look up a video's state: exists, status (uploaded / analyzing /
    analyzed / failed), analysis progress, moment count, and its most recent
    clips. Call this first when you don't already know the video's state."""
    if not _owns_video(_user_id(config), video_id):
        return {"exists": False}
    state = analysis_jobs.video_state(video_id)
    if not state.get("exists"):
        return {"exists": False}
    db: Session = SessionLocal()
    try:
        clips = (db.query(Clip).filter(Clip.video_id == video_id)
                 .order_by(Clip.created_at.desc()).limit(20).all())
        clip_dicts = [clip_to_dict(c) for c in clips]
    finally:
        db.close()
    return {
        **state,
        "has_analysis": state["status"] == analysis_jobs.ANALYZED and state["moment_count"] > 0,
        "clips": clip_dicts,
    }


@tool
def ingest_and_analyze_video(video_id: str, config: RunnableConfig = None) -> dict:
    """START analysis of a video (transcription, scene detection, parallel
    per-chunk multimodal moment analysis) as a BACKGROUND job and return
    immediately. Long videos take many minutes (~12 min per hour of video).
    Returns {"status": "started" | "already_running" | "already_analyzed" |
    "not_found" | "archived" | "daily_cap", "eta_minutes", "message"}. While it runs you cannot produce
    clips — tell the user analysis is running and roughly how long it takes;
    the app notifies them and resumes their request when it finishes."""
    uid = _user_id(config)
    if not _owns_video(uid, video_id):
        return {"status": "not_found", "eta_minutes": 0, "message": f"No video found with id {video_id}."}
    res = analysis_jobs.start_analysis(video_id, cap_exempt=_is_admin(uid))
    state = res["state"]
    eta_s = state.get("eta_seconds") or analysis_jobs.estimate_seconds(state.get("duration"))
    eta_min = max(1, round(eta_s / 60))
    msgs = {
        "started": (f"Analysis queued — #{state['queue_position']} in line, then about {eta_min} min."
                    if state.get("queue_position") else
                    f"Analysis started in the background (about {eta_min} min)."),
        "already_running": f"Analysis is already running ({state.get('progress', 0)}% done, about {eta_min} min left).",
        "already_analyzed": f"This video is already analyzed ({state.get('moment_count', 0)} moments).",
        "not_found": f"No video found with id {video_id}.",
        "archived": _archived_message(),
        "daily_cap": "The site has used today's analysis minutes. Please try again tomorrow.",
    }
    return {"status": res["result"], "eta_minutes": eta_min, "message": msgs[res["result"]]}


@tool
def search_moments(video_id: str, query: str, k: int = 10, config: RunnableConfig = None) -> list[dict]:
    """Semantically search a video's analyzed moments for ones matching a
    freeform description (e.g. "roasts a competitor", "emotional story
    about failure"). Returns candidate moments with timestamps and scores.
    Use this to answer questions like "what funny moments are in this
    video?" without producing clips. It does NOT produce anything: if the
    user asked for a clip, a moment or a scene ("a moment about X", "a clip
    where ..."), call select_and_produce_clips instead (it retrieves and
    re-ranks on its own) — never stop at search results and ask whether to
    make the clip."""
    if not _owns_video(_user_id(config), video_id):
        return []
    db: Session = SessionLocal()
    try:
        moments = [_row_to_moment(r) for r in
                   db.query(MomentRecord).filter(MomentRecord.video_id == video_id).all()]
    finally:
        db.close()
    k = max(1, min(int(k or 10), 30))
    idx = S.hybrid_candidates(moments, query, S.embed_query(query), limit=k)
    return [
        {
            "start": m.start, "end": m.end, "description": m.description,
            "transcript": (m.transcript or "")[:400], "categories": m.categories,
            "why": m.why, "convergence_score": m.convergence_score,
        }
        for m in (moments[i] for i in idx)
    ]


_FRAMES = {"9:16", "1:1", "16:9"}


def _row_to_moment(r: MomentRecord) -> Moment:
    emb = getattr(r, "embedding", None)
    return Moment(
        start=r.start, end=r.end, visual_energy=r.visual_energy or 0.0,
        audio_energy=r.audio_energy or 0.0, text_hook_strength=r.text_hook_strength or 0.0,
        convergence_score=r.convergence_score or 0.0, modalities_active=r.modalities_active or 0,
        style_tags=list(r.style_tags or []), description=r.description or "",
        transcript=r.transcript or "",
        embedding=[float(x) for x in emb] if emb is not None else None,
        categories=list(getattr(r, "categories", None) or []), why=getattr(r, "why", None) or "",
    )


def _load_json(path, default):
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


@tool
def select_and_produce_clips(
    video_id: str,
    count: int = 1,
    length_seconds: int = 30,
    query: str = "",
    frame: str = "9:16",
    caption_style: str = "bold_pop",
    config: RunnableConfig = None,
) -> dict:
    """Select the best matching moments (via RAG retrieval on `query`) and
    produce finished clips: cut, captioned, reframed, thumbnailed. Clips are
    kept within +-10% of `length_seconds` (5-180s) and never taken from the
    end credits.

    Returns {"status": ..., "clips_produced": int, "clips": [...], "message": str}.
    status is one of: "ok" (clips were produced and written to disk),
    "video_not_found", "analyzing" (analysis still running — wait),
    "not_analyzed" (call ingest_and_analyze_video first),
    "archived" (the source file was deleted by the storage rules — old
    clips still play, new ones need a re-upload),
    "no_match" (analyzed, but nothing matched the query). Only "ok" with
    clips_produced > 0 means clips actually exist — report `message` to the
    user verbatim for any other status. `count` is how many clips the
    user asked for — "a clip", "the most X", "the best X" mean 1; always pass
    it explicitly. `query` is freeform text
    describing what kind of clips the user wants (e.g. "funny", "where he
    argues about pricing") — it drives semantic retrieval, not just a fixed
    style enum. `frame` is one of "9:16" (TikTok/Reels), "1:1" (square),
    "16:9" (YouTube). `caption_style` is one of bold_pop, minimal_clean,
    karaoke_sweep, bounce_in, glow."""
    from autoclip.config import CAPTION_STYLES

    if not _owns_video(_user_id(config), video_id):
        state_info = {"exists": False}
    else:
        state_info = analysis_jobs.video_state(video_id)
    if not state_info.get("exists"):
        return {"status": "video_not_found", "clips_produced": 0, "clips": [],
                "message": f"No video found with id {video_id}. Nothing was produced."}
    if state_info["status"] == analysis_jobs.ANALYZING:
        return {"status": "analyzing", "clips_produced": 0, "clips": [],
                "message": (f"The video is still being analyzed ({state_info.get('progress', 0)}%). "
                            "NO clips were produced yet — they can be made once analysis finishes.")}

    db: Session = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        moments_rows = db.query(MomentRecord).filter(MomentRecord.video_id == video_id).all()
        moment_count = len(moments_rows)
        if moment_count == 0:
            return {"status": "not_analyzed", "clips_produced": 0, "clips": [],
                    "message": ("This video has no analyzed moments yet, so NO clips were "
                                "produced. Call ingest_and_analyze_video first, then retry.")}

        if video.archived:
            from autoclip.services.storage import ARCHIVED_MESSAGE
            return {"status": "archived", "clips_produced": 0, "clips": [],
                    "message": ARCHIVED_MESSAGE + " NO clips were produced."}

        moment_map = [_row_to_moment(r) for r in moments_rows]

        out_dir = video_output_dir(video_id)
        transcript_data = _load_json(out_dir / "transcript.json", {})
        scene_boundaries = _load_json(out_dir / "scenes.json", [])

        frame = frame if frame in _FRAMES else "9:16"
        caption_style = caption_style if caption_style in CAPTION_STYLES else "bold_pop"
        length = int(max(5, min(int(length_seconds or 30), 180)))
        clip_configs = [
            ClipConfig(length=length, query=query, frame=frame, caption_style=caption_style)
            for _ in range(max(1, min(int(count or 1), 6)))
        ]

        safe = None
        try:
            from autoclip.utils.video_profile import safe_range
            safe = safe_range(video_id, video.file_path, video.duration or 0.0,
                              transcript_data.get("words", []))
        except Exception as e:
            logger.warning("safe_range failed for %s: %s", video_id, e)

        state: PipelineState = {
            "video_id": video_id,
            "video_path": video.file_path,
            "video_duration": video.duration or 0.0,
            "moment_map": moment_map,
            "transcript_data": transcript_data,
            "scene_boundaries": scene_boundaries,
            "clip_configs": clip_configs,
            "user_request": _current_request.get(),
            "used_ranges": [
                (c.start_time, c.end_time)
                for c in db.query(Clip).filter(Clip.video_id == video_id).all()
            ],
        }
        if safe:
            state["safe_range"] = safe
        result = generation_only.invoke(state)
        clips = result.get("clips", [])

        for c in clips:
            db.add(Clip(
                id=c.id, video_id=video_id, title=c.title,
                start_time=c.start_time, end_time=c.end_time, duration=c.duration,
                file_path=c.file_path, thumbnail_path=c.thumbnail_path,
                transcript=c.transcript, scores=c.scores, overall_score=c.overall_score,
                caption_style=c.caption_style,
                caption_file=str(out_dir / "clips" / c.id / "captions.ass")
                if (out_dir / "clips" / c.id / "captions.ass").exists() else None,
            ))
        db.commit()
        for c in clips:
            _record_clip(video_id, c.id)

        produced = [clip_to_dict(c) for c in clips]
        if not produced:
            return {"status": "no_match", "clips_produced": 0, "clips": [],
                    "message": (f"Analysis found {moment_count} moments, but none matched "
                                f"{query!r} well enough to clip. NO clips were produced.")}
        return {"status": "ok", "clips_produced": len(produced), "clips": produced,
                "message": f"Produced {len(produced)} clip(s)."}
    finally:
        db.close()


@tool
def modify_clip(clip_id: str, new_start_time: Optional[float] = None,
                 new_end_time: Optional[float] = None,
                 new_caption_style: Optional[str] = None,
                 config: RunnableConfig = None) -> dict:
    """Trim or re-style an already-produced clip in place (re-renders it with
    the same framing). Use for requests like "make clip 2 longer" —
    translate that into new_start_time/new_end_time yourself based on the
    clip's current start_time/end_time from get_video_status. Max clip
    length is 180s; times must lie within the video."""
    import asyncio
    uid = _user_id(config)
    db: Session = SessionLocal()
    try:
        clip = None
        if uid is not None:
            clip = (db.query(Clip).join(Video, Clip.video_id == Video.id)
                    .filter(Clip.id == str(clip_id), Video.user_id == uid).first())
        if not clip:
            return {"error": f"No clip found with id {clip_id}"}
        video = db.query(Video).filter(Video.id == clip.video_id).first()
        try:
            update = ClipUpdate(start_time=new_start_time, end_time=new_end_time,
                                caption_style=new_caption_style)
            updated = asyncio.run(apply_clip_update(db, clip, video, update))
        except (ClipUpdateError, ValueError) as e:
            db.rollback()
            return {"error": f"Clip not changed: {e}"}
        _record_clip(updated.video_id, updated.id)
        return clip_to_dict(updated)
    finally:
        db.close()


ALL_TOOLS = [
    get_video_status,
    ingest_and_analyze_video,
    search_moments,
    select_and_produce_clips,
    modify_clip,
]
