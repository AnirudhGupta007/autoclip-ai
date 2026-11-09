"""Background video analysis — an in-process worker for a one-box deploy.

Analysis of a feature film takes ~20 minutes (98-min film: 18.6 min), far
longer than any HTTP request may stay open (browser 300s, nginx 600s). So
`start_analysis()` returns immediately and runs the analysis-only LangGraph
graph on a daemon thread:

  • Video.status (DB) is the durable state: uploaded → analyzing → analyzed
    (or failed). Legacy values "completed"/"processing" are normalised.
  • Progress (stage, %, chunks, ETA, heartbeat) lives in Redis
    (`analysis:progress:<video_id>`, in-memory fallback) and is pushed to the
    browser as SSE events on the existing `pipeline:<video_id>` channel.
  • A per-video lock + the live-thread registry make a second analyze request
    a no-op ("already_running") instead of a duplicate run. A heartbeat lets
    us tell a live job from one orphaned by a process restart (reported as
    failed/"interrupted", so the next request simply restarts it).
  • A FIFO queue caps concurrent analyses (ANALYSIS_MAX_CONCURRENCY, 1 on
    the t3a.small). Waiting jobs report `queue_position` (1 = next) in
    video_state() and in `analysis_progress` events (stage "queued").
  • A site-wide daily budget of analysed minutes (rate_limit,
    DAILY_ANALYSIS_MINUTES_LIMIT) is charged when a job starts and refunded
    if it fails; admins are exempt.

Quota: the request that starts an analysis is charged once; the router then
grants a one-shot "follow-up credit" so the automatic re-send of that same
request after `analysis_done` is free (see routers/chat.py). On failure the
unit is refunded via the `on_fail` callback.

Single-process assumption: with several uvicorn workers the thread registry
is per worker; the DB status + Redis heartbeat still prevent duplicates as
long as the heartbeat is fresh.
"""
from __future__ import annotations
import json
import logging
import math
import os
import threading
import time
from typing import Callable, Optional

from autoclip.services import events as pipeline_events
from autoclip.utils.paths import video_output_dir

logger = logging.getLogger(__name__)

UPLOADED, ANALYZING, ANALYZED, FAILED = "uploaded", "analyzing", "analyzed", "failed"
_LEGACY = {"completed": ANALYZED, "processing": ANALYZING}

HEARTBEAT_SECONDS = 15
STALE_AFTER_SECONDS = 120
PROGRESS_TTL = 7 * 24 * 3600
CREDIT_TTL = 24 * 3600
MAX_CONCURRENCY = max(1, int(os.getenv("ANALYSIS_MAX_CONCURRENCY", "1")))

_jobs: dict[str, threading.Thread] = {}
_jobs_lock = threading.Lock()
# Jobs that are running or waiting, in arrival order: the first
# MAX_CONCURRENCY run, the rest wait. RLock-backed, so helpers can nest.
_queue: list[str] = []
_queue_cv = threading.Condition()
_mem_progress: dict[str, dict] = {}
_mem_credits: dict[str, float] = {}


# ─── progress store ─────────────────────────────────────────────

def _pkey(video_id: str) -> str:
    return f"analysis:progress:{video_id}"


def get_progress(video_id: str) -> Optional[dict]:
    r = pipeline_events.get_redis()
    if r is not None:
        try:
            raw = r.get(_pkey(video_id))
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return _mem_progress.get(video_id)


def _set_progress(video_id: str, **fields) -> dict:
    cur = dict(get_progress(video_id) or {})
    cur.update(fields)
    cur["heartbeat_at"] = time.time()
    _mem_progress[video_id] = cur
    r = pipeline_events.get_redis()
    if r is not None:
        try:
            r.set(_pkey(video_id), json.dumps(cur), ex=PROGRESS_TTL)
        except Exception:
            pass
    return cur


def estimate_seconds(duration: Optional[float]) -> int:
    """Wall-clock estimate: measured ~0.19x realtime on a 98-min film, plus
    fixed overhead for short videos."""
    return int(45 + 0.2 * float(duration or 0.0))


def _eta(progress: dict, duration: Optional[float]) -> int:
    if progress.get("stage") == "queued":
        return estimate_seconds(duration)   # own run only; the wait shows as queue_position
    started = progress.get("started_at") or time.time()
    elapsed = max(0.0, time.time() - started)
    pct = float(progress.get("progress") or 0)
    if pct >= 25:
        return int(elapsed * (100 - pct) / pct)
    return int(max(10.0, estimate_seconds(duration) - elapsed))


# ─── follow-up credit (one logical request = one quota unit) ────

def _ckey(ip: str, video_id: str) -> str:
    return f"analysis:credit:{video_id}:{ip}"


def grant_followup_credit(ip: str, video_id: str) -> None:
    r = pipeline_events.get_redis()
    if r is not None:
        try:
            r.set(_ckey(ip, video_id), "1", ex=CREDIT_TTL)
            return
        except Exception:
            pass
    _mem_credits[_ckey(ip, video_id)] = time.time() + CREDIT_TTL


def consume_followup_credit(ip: str, video_id: str) -> bool:
    key = _ckey(ip, video_id)
    r = pipeline_events.get_redis()
    if r is not None:
        try:
            return bool(r.delete(key))
        except Exception:
            pass
    exp = _mem_credits.pop(key, None)
    return bool(exp and exp > time.time())


def revoke_followup_credit(ip: str, video_id: str) -> None:
    consume_followup_credit(ip, video_id)


# ─── queue ──────────────────────────────────────────────────────

def queue_position(video_id: str) -> Optional[int]:
    """1 = next in line, 0 = running, None = not in this worker's queue."""
    with _queue_cv:
        if video_id not in _queue:
            return None
        i = _queue.index(video_id)
    return 0 if i < MAX_CONCURRENCY else i - MAX_CONCURRENCY + 1


def _wait_for_slot(video_id: str, duration: Optional[float]) -> None:
    with _queue_cv:
        if video_id not in _queue:
            _queue.append(video_id)
    last = None
    while True:
        pos = queue_position(video_id)
        if not pos:
            return
        if pos != last:   # tell the browser where it stands ("#2 in line")
            _progress_event(video_id, duration, stage="queued", progress=0, queue_position=pos)
            last = pos
        with _queue_cv:
            if queue_position(video_id):
                _queue_cv.wait(timeout=HEARTBEAT_SECONDS)


def _leave_queue(video_id: str) -> None:
    with _queue_cv:
        if video_id in _queue:
            _queue.remove(video_id)
        _queue_cv.notify_all()


# ─── state ──────────────────────────────────────────────────────

def _job_alive(video_id: str) -> bool:
    t = _jobs.get(video_id)
    return bool(t and t.is_alive())


def video_state(video_id: str) -> dict:
    """Normalised analysis state for a video (DB + live job + progress)."""
    from autoclip.database import SessionLocal
    from autoclip.models import Video, MomentRecord, Clip

    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return {"exists": False, "video_id": video_id}
        moment_count = db.query(MomentRecord).filter(MomentRecord.video_id == video_id).count()
        clip_count = db.query(Clip).filter(Clip.video_id == video_id).count()
        raw = _LEGACY.get(video.status or UPLOADED, video.status or UPLOADED)
        duration = video.duration
        archived = bool(video.archived)
    finally:
        db.close()

    progress = get_progress(video_id) or {}
    status = raw
    error = None
    if _job_alive(video_id):
        status = ANALYZING
    elif raw == ANALYZING:
        fresh = time.time() - float(progress.get("heartbeat_at") or 0) < STALE_AFTER_SECONDS
        if not fresh:
            # Orphaned by a restart (or another worker died) — not running.
            status = ANALYZED if moment_count > 0 and progress.get("status") == ANALYZED else FAILED
            error = "Analysis was interrupted."
    elif moment_count > 0:
        status = ANALYZED
    elif raw == FAILED:
        error = progress.get("error") or "Analysis failed."

    out = {
        "exists": True,
        "video_id": video_id,
        "status": status,
        "duration": duration,
        "moment_count": moment_count,
        "clip_count": clip_count,
        "progress": 100 if status == ANALYZED else int(progress.get("progress") or 0),
        "stage": progress.get("stage") if status == ANALYZING else None,
        "chunks_done": progress.get("chunks_done"),
        "chunks_total": progress.get("chunks_total"),
        "eta_seconds": _eta(progress, duration) if status == ANALYZING else None,
        "queue_position": _queued_at(video_id, progress) if status == ANALYZING else None,
        "error": error,
        "archived": archived,
    }
    return out


def _queued_at(video_id: str, progress: dict) -> Optional[int]:
    """Position in line while waiting (None once running)."""
    pos = queue_position(video_id) if _job_alive(video_id) else progress.get("queue_position")
    return pos or None


# ─── job control ────────────────────────────────────────────────

def start_analysis(video_id: str, on_fail: Optional[Callable[[], None]] = None,
                   force: bool = False, cap_exempt: bool = False) -> dict:
    """Start analysing `video_id` in the background unless it is already
    running (or already analysed and not `force`). Never blocks on the work.

    Returns {"result": started|already_running|already_analyzed|not_found|
             archived|daily_cap, "state": video_state(...)}. "archived": the
    source file is gone (services/storage.py), so there is nothing to
    analyse. "daily_cap": today's site-wide analysis minutes are used up
    (not checked when `cap_exempt`, i.e. for admins).
    """
    from autoclip.database import SessionLocal
    from autoclip.models import Video

    with _jobs_lock:
        state = video_state(video_id)
        if not state.get("exists"):
            return {"result": "not_found", "state": state}
        if state["status"] == ANALYZING:
            return {"result": "already_running", "state": state}
        if state["status"] == ANALYZED and not force:
            return {"result": "already_analyzed", "state": state}
        if state.get("archived"):
            return {"result": "archived", "state": state}

        minutes_charge = None
        if not cap_exempt:
            from autoclip.services import rate_limit
            minutes = max(1, math.ceil(float(state.get("duration") or 0) / 60))
            ok, minutes_charge = rate_limit.try_consume_analysis_minutes(minutes)
            if not ok:
                return {"result": "daily_cap", "state": state}

        db = SessionLocal()
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            video.status = ANALYZING
            db.commit()
            duration = video.duration
        finally:
            db.close()

        eta = estimate_seconds(duration)
        with _queue_cv:   # join the line now, so the position is right at once
            _queue.append(video_id)
        _set_progress(video_id, status=ANALYZING, stage="queued", progress=0,
                      chunks_done=0, chunks_total=None, started_at=time.time(),
                      error=None, eta_seconds=eta, queue_position=queue_position(video_id) or None)
        t = threading.Thread(target=_run, args=(video_id, on_fail, minutes_charge), daemon=True,
                             name=f"analysis-{video_id}")
        _jobs[video_id] = t
        t.start()

    pipeline_events.publish_analysis(video_id, "analysis_started",
                                     {"eta_seconds": eta, "duration": duration,
                                      "queue_position": queue_position(video_id) or None})
    return {"result": "started", "state": video_state(video_id)}


def _progress_event(video_id: str, duration: Optional[float], **fields) -> None:
    p = _set_progress(video_id, **fields)
    pipeline_events.publish_analysis(video_id, "analysis_progress", {
        "stage": p.get("stage"),
        "progress": p.get("progress", 0),
        "chunks_done": p.get("chunks_done"),
        "chunks_total": p.get("chunks_total"),
        "eta_seconds": _eta(p, duration),
        "queue_position": p.get("queue_position") or None,
    })


def _run(video_id: str, on_fail: Optional[Callable[[], None]], minutes_charge=None) -> None:
    from autoclip.database import SessionLocal
    from autoclip.models import Video

    stop = threading.Event()

    def heartbeat():
        while not stop.wait(HEARTBEAT_SECONDS):
            _set_progress(video_id)

    hb = threading.Thread(target=heartbeat, daemon=True, name=f"analysis-hb-{video_id}")
    hb.start()
    try:
        duration = _duration_of(video_id)
        _wait_for_slot(video_id, duration)
        # Out of the line: the clock (ETA) starts now, and the browser drops "#N in line".
        _progress_event(video_id, duration, stage="starting", progress=1,
                        queue_position=None, started_at=time.time())
        _run_pipeline(video_id)
    except Exception:
        logger.exception("analysis job failed for video=%s", video_id)
        from autoclip.services import rate_limit
        rate_limit.refund(minutes_charge)   # our failure: the minutes go back
        db = SessionLocal()
        try:
            v = db.query(Video).filter(Video.id == video_id).first()
            if v:
                v.status = FAILED
                db.commit()
        finally:
            db.close()
        _set_progress(video_id, status=FAILED, stage="failed",
                      error="Analysis failed. Please try again.")
        pipeline_events.publish_analysis(video_id, "analysis_failed", {
            "message": "Analysis failed on our side — you were not charged. Try again.",
        })
        if on_fail:
            try:
                on_fail()
            except Exception:
                logger.warning("analysis on_fail callback raised", exc_info=True)
    finally:
        stop.set()
        _leave_queue(video_id)
        with _jobs_lock:
            if _jobs.get(video_id) is threading.current_thread():
                _jobs.pop(video_id, None)


def _duration_of(video_id: str) -> Optional[float]:
    from autoclip.database import SessionLocal
    from autoclip.models import Video
    db = SessionLocal()
    try:
        v = db.query(Video).filter(Video.id == video_id).first()
        return v.duration if v else None
    finally:
        db.close()


def _run_pipeline(video_id: str) -> None:
    from autoclip.database import SessionLocal
    from autoclip.models import Video
    from autoclip.pipeline.graph import analysis_only
    from autoclip.services.moment_store import persist_moments
    from autoclip.utils.video_profile import get_profile

    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise RuntimeError("video disappeared")
        video_path, duration = video.file_path, video.duration
        media_kind = video.media_kind or "video"
    finally:
        db.close()

    _progress_event(video_id, duration, stage="transcribing", progress=3)
    state = {
        "video_id": video_id,
        "video_path": video_path,
        "media_kind": media_kind,
        "clip_configs": [],
        "analysis_complete": False,
        "needs_reanalysis": False,
        "chunk_plans": [],
        "moment_map_raw": [],
        "scene_boundaries": [],
    }
    chunks_total = 0
    chunks_done = 0
    moments = None
    out_dir = video_output_dir(video_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    for _ns, update in analysis_only.stream(state, stream_mode="updates", subgraphs=True):
        if not isinstance(update, dict):
            continue
        for node, data in update.items():
            data = data or {}
            if node == "transcription":
                _progress_event(video_id, duration, stage="detecting scenes", progress=15)
            elif node == "scene_detection":
                try:
                    (out_dir / "scenes.json").write_text(json.dumps(data.get("scene_boundaries") or []))
                except OSError:
                    pass
                _progress_event(video_id, duration, stage="planning chunks", progress=18)
            elif node == "chunk_planner":
                chunks_total = len(data.get("chunk_plans") or [])
                _progress_event(video_id, duration, stage="analysing chunks", progress=20,
                                chunks_done=0, chunks_total=chunks_total)
            elif node == "chunk_analyzer":
                chunks_done += 1
                pct = 20 + int(72 * chunks_done / max(1, chunks_total))
                _progress_event(video_id, duration, stage="analysing chunks", progress=min(pct, 92),
                                chunks_done=chunks_done, chunks_total=chunks_total)
            elif node == "global_fusion":
                moments = data.get("moment_map")
                _progress_event(video_id, duration, stage="ranking moments", progress=94)
            elif node == "analysis" and moments is None:
                moments = data.get("moment_map")

    moments = moments or []
    _progress_event(video_id, duration, stage="indexing", progress=96)
    db = SessionLocal()
    try:
        persist_moments(db, video_id, moments)  # replaces old rows + vector nodes
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.status = ANALYZED
            db.commit()
    finally:
        db.close()

    try:  # letterbox + credits, cached for production
        get_profile(video_id, video_path)
    except Exception as e:
        logger.warning("profile computation failed for %s: %s", video_id, e)

    _set_progress(video_id, status=ANALYZED, stage="done", progress=100,
                  moment_count=len(moments), finished_at=time.time())
    pipeline_events.publish_analysis(video_id, "analysis_done", {"moment_count": len(moments)})
    logger.info("analysis done for video=%s: %d moments", video_id, len(moments))


def is_running(video_id: str) -> bool:
    return _job_alive(video_id) or video_state(video_id).get("status") == ANALYZING
