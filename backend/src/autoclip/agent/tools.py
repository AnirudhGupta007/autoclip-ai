"""Tools the deep-agent orchestrator can call.

Each tool is a thin wrapper around existing, already-working code — the
LangGraph Send-API chunk-analysis subgraph, the ffmpeg production pipeline,
the RAG retriever, and the DB models. No media-processing logic is
duplicated here; the tools just give the agent a way to invoke it.
"""
from __future__ import annotations
import logging
from typing import Optional

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from autoclip.database import SessionLocal
from autoclip.models import Video, Clip, MomentRecord, generate_id
from autoclip.pipeline.graph import pipeline, generation_only
from autoclip.pipeline.state import PipelineState, ClipConfig
from autoclip.rag.retriever import retrieve_moments
from autoclip.services.moment_store import persist_moments
from autoclip.services.clip_reprocess import apply_clip_update
from autoclip.schemas import ClipUpdate

logger = logging.getLogger(__name__)


def _clip_to_dict(clip) -> dict:
    if hasattr(clip, "__dict__"):
        d = {}
        for k in ["id", "title", "start_time", "end_time", "duration",
                   "file_path", "thumbnail_path", "transcript", "scores",
                   "overall_score", "frame", "style_tags"]:
            d[k] = getattr(clip, k, None)
        if d.get("file_path"):
            d["file_url"] = "/" + d["file_path"].replace("\\", "/")
        if d.get("thumbnail_path"):
            d["thumbnail_url"] = "/" + d["thumbnail_path"].replace("\\", "/")
        return d
    return clip


@tool
def get_video_status(video_id: str) -> dict:
    """Look up a video's DB state: whether it exists, is analyzed (has moments),
    and has produced clips. Call this first when you don't already know the
    video's state — this replaces guessing from conversation history."""
    db: Session = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return {"exists": False}
        moment_count = db.query(MomentRecord).filter(MomentRecord.video_id == video_id).count()
        clips = db.query(Clip).filter(Clip.video_id == video_id).all()
        return {
            "exists": True,
            "status": video.status,
            "duration": video.duration,
            "has_analysis": moment_count > 0,
            "moment_count": moment_count,
            "clip_count": len(clips),
            "clips": [_clip_to_dict(c) for c in clips],
        }
    finally:
        db.close()


@tool
def ingest_and_analyze_video(video_id: str) -> str:
    """Run full analysis on a video: transcription, scene detection, and
    parallel per-chunk multimodal moment analysis. Call this before trying
    to select/produce clips for a video that has no analysis yet
    (check with get_video_status first). This can take a while for long
    videos — it runs the whole chunk-parallel pipeline synchronously."""
    db: Session = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return f"No video found with id {video_id}."

        state: PipelineState = {
            "video_id": video_id,
            "video_path": video.file_path,
            "clip_configs": [],
            "analysis_complete": False,
            "needs_reanalysis": False,
            "chunk_plans": [],
            "moment_map_raw": [],
            "scene_boundaries": [],
        }
        video.status = "processing"
        db.commit()

        try:
            result = pipeline.invoke(state, {"configurable": {"thread_id": video_id}})
        except Exception as e:
            video.status = "failed"
            db.commit()
            return f"Analysis failed: {e}"

        video.status = "completed"
        db.commit()

        moments = result.get("moment_map", [])
        persist_moments(db, video_id, moments)
        return f"Analysis complete: found {len(moments)} candidate moments in the video."
    finally:
        db.close()


@tool
def search_moments(video_id: str, query: str, k: int = 10) -> list[dict]:
    """Semantically search a video's analyzed moments for ones matching a
    freeform description (e.g. "roasts a competitor", "emotional story
    about failure"). Returns candidate moments with timestamps and scores.
    Use this to ground clip selection in what's actually in the video
    before calling select_and_produce_clips, or to answer questions like
    "what funny moments are in this video?" without producing clips."""
    moments = retrieve_moments(video_id=video_id, query=query, k=k)
    return [
        {
            "start": m.start, "end": m.end, "description": m.description,
            "transcript": m.transcript, "style_tags": m.style_tags,
            "convergence_score": m.convergence_score,
        }
        for m in moments
    ]


@tool
def select_and_produce_clips(
    video_id: str,
    count: int = 4,
    length_seconds: int = 30,
    query: str = "",
    frame: str = "9:16",
) -> list[dict]:
    """Select the best matching moments (via RAG retrieval on `query`) and
    produce finished clips: cut, captioned, reframed, thumbnailed. Requires
    the video to already be analyzed (call ingest_and_analyze_video first
    if get_video_status shows has_analysis=false). `query` is freeform text
    describing what kind of clips the user wants (e.g. "funny", "where he
    argues about pricing") — it drives semantic retrieval, not just a fixed
    style enum. `frame` is one of "9:16" (TikTok/Reels), "1:1" (square),
    "16:9" (YouTube)."""
    db: Session = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return []

        moment_count = db.query(MomentRecord).filter(MomentRecord.video_id == video_id).count()
        if moment_count == 0:
            return []

        moments_rows = db.query(MomentRecord).filter(MomentRecord.video_id == video_id).all()
        from autoclip.pipeline.state import Moment
        moment_map = [
            Moment(
                start=r.start, end=r.end, visual_energy=r.visual_energy,
                audio_energy=r.audio_energy, text_hook_strength=r.text_hook_strength,
                convergence_score=r.convergence_score, modalities_active=r.modalities_active,
                style_tags=list(r.style_tags or []), description=r.description or "",
                transcript=r.transcript or "",
            )
            for r in moments_rows
        ]

        import json
        from pathlib import Path
        from autoclip.config import OUTPUT_DIR
        transcript_path = Path(OUTPUT_DIR) / video_id / "transcript.json"
        transcript_data = {}
        if transcript_path.exists():
            transcript_data = json.loads(transcript_path.read_text())

        clip_configs = [
            ClipConfig(length=length_seconds, query=query, frame=frame)
            for _ in range(max(1, min(count, 10)))
        ]

        state: PipelineState = {
            "video_id": video_id,
            "video_path": video.file_path,
            "moment_map": moment_map,
            "transcript_data": transcript_data,
            "scene_boundaries": [],
            "clip_configs": clip_configs,
        }
        result = generation_only.invoke(state)
        clips = result.get("clips", [])

        for c in clips:
            db.add(Clip(
                id=c.id, video_id=video_id, title=c.title,
                start_time=c.start_time, end_time=c.end_time, duration=c.duration,
                file_path=c.file_path, thumbnail_path=c.thumbnail_path,
                transcript=c.transcript, scores=c.scores, overall_score=c.overall_score,
                caption_style="bold_pop",
            ))
        db.commit()

        return [_clip_to_dict(c) for c in clips]
    finally:
        db.close()


@tool
def modify_clip(clip_id: str, new_start_time: Optional[float] = None,
                 new_end_time: Optional[float] = None,
                 new_caption_style: Optional[str] = None) -> dict:
    """Trim or re-style an already-produced clip in place (re-cuts and
    re-captions on disk). Use for requests like "make clip 2 longer" —
    translate that into new_start_time/new_end_time yourself based on the
    clip's current start_time/end_time from get_video_status."""
    import asyncio
    db: Session = SessionLocal()
    try:
        clip = db.query(Clip).filter(Clip.id == clip_id).first()
        if not clip:
            return {"error": f"No clip found with id {clip_id}"}
        video = db.query(Video).filter(Video.id == clip.video_id).first()
        update = ClipUpdate(start_time=new_start_time, end_time=new_end_time,
                             caption_style=new_caption_style)
        updated = asyncio.run(apply_clip_update(db, clip, video, update))
        return _clip_to_dict(updated)
    finally:
        db.close()


ALL_TOOLS = [
    get_video_status,
    ingest_and_analyze_video,
    search_moments,
    select_and_produce_clips,
    modify_clip,
]
