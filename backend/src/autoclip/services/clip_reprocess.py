"""Shared clip-update/reprocess logic — used by both the `PUT /api/clips/{id}`
HTTP route and the deep agent's `modify_clip` tool, so the two code paths
never drift apart.

A trim or caption-style change re-renders through the same
`render_clip_assets()` production uses, so the edited clip keeps its
letterbox crop, 9:16/1:1 reframe and captions (the old path re-cut the raw
16:9 source and silently dropped the reframe, and skipped re-rendering
entirely when the transcript had no words). The output gets a fresh file
name so browsers don't replay a cached copy, and exports rendered from the
old version are deleted.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from autoclip.models import Clip, Video
from autoclip.schemas import ClipUpdate, MAX_CLIP_SECONDS
from autoclip.utils.ffmpeg import get_video_info
from autoclip.utils.paths import resolve_path, video_output_dir

logger = logging.getLogger(__name__)

MIN_CLIP_SECONDS = 1.0


class ClipUpdateError(ValueError):
    """Invalid edit (bad window etc.) — routers map this to HTTP 422."""


def validate_window(start: float, end: float, video_duration: Optional[float]) -> None:
    if start < 0:
        raise ClipUpdateError("start_time must be >= 0")
    if end <= start:
        raise ClipUpdateError("end_time must be greater than start_time")
    if video_duration and end > float(video_duration) + 0.05:
        raise ClipUpdateError(f"end_time must be <= the video duration ({float(video_duration):.2f}s)")
    if end - start > MAX_CLIP_SECONDS:
        raise ClipUpdateError(f"clips can be at most {int(MAX_CLIP_SECONDS)} seconds long")
    if end - start < MIN_CLIP_SECONDS:
        raise ClipUpdateError(f"clips must be at least {MIN_CLIP_SECONDS:g} second long")


def infer_frame(path: Optional[Path]) -> str:
    """Clip rows don't store their aspect; read it back from the rendered file."""
    if not path or not path.exists():
        return "9:16"
    try:
        info = get_video_info(str(path))
        w, h = info.get("width") or 0, info.get("height") or 0
    except Exception:
        return "9:16"
    if not w or not h:
        return "9:16"
    ratio = w / h
    if ratio < 0.8:
        return "9:16"
    if ratio < 1.25:
        return "1:1"
    return "16:9"


def _load_words(video_id: str) -> list[dict]:
    transcript_file = video_output_dir(video_id) / "transcript.json"
    if not transcript_file.exists():
        return []
    try:
        return json.loads(transcript_file.read_text()).get("words", []) or []
    except (OSError, json.JSONDecodeError):
        return []


def _drop_exports(clip: Clip) -> None:
    for p in (clip.exports or {}).values():
        rp = resolve_path(p)
        try:
            if rp and rp.exists():
                rp.unlink()
        except OSError:
            pass
    clip.exports = {}


async def apply_clip_update(db: Session, clip: Clip, video: Video | None, update: ClipUpdate) -> Clip:
    """Apply a ClipUpdate to `clip`, re-rendering on disk if the change
    requires it (trim or caption style). Commits the DB session.

    Raises ClipUpdateError for invalid edits (nothing is changed then)."""
    new_start = clip.start_time if update.start_time is None else float(update.start_time)
    new_end = clip.end_time if update.end_time is None else float(update.end_time)
    trim = (update.start_time is not None or update.end_time is not None) and (
        abs(new_start - clip.start_time) > 1e-3 or abs(new_end - clip.end_time) > 1e-3
    )
    restyle = update.caption_style is not None and update.caption_style != clip.caption_style
    if trim:
        validate_window(new_start, new_end, video.duration if video else None)
    if (trim or restyle) and not video:
        raise ClipUpdateError("The source video for this clip no longer exists.")

    if update.title is not None:
        clip.title = update.title
    if update.music_id is not None:
        clip.music_id = update.music_id
    if update.music_url is not None:
        clip.music_url = update.music_url
    if update.music_volume is not None:
        clip.music_volume = update.music_volume

    if trim or restyle:
        from autoclip.pipeline.agents.production import render_clip_assets

        style = update.caption_style or clip.caption_style or "bold_pop"
        old_file = resolve_path(clip.file_path)
        frame = await asyncio.to_thread(infer_frame, old_file)
        out = await asyncio.to_thread(
            render_clip_assets,
            video_id=clip.video_id, video_path=video.file_path, clip_id=clip.id,
            start=new_start, end=new_end, frame=frame, caption_style=style,
            words=_load_words(clip.video_id), title=clip.title or "",
            output_name=f"final_{int(time.time() * 1000)}.mp4",
        )
        if old_file and old_file.exists() and str(old_file) != out["file_path"]:
            try:
                old_file.unlink()
            except OSError:
                pass
        clip.start_time = out["start"]
        clip.end_time = out["end"]
        clip.duration = out["duration"]
        clip.file_path = out["file_path"]
        clip.thumbnail_path = out["thumbnail_path"]
        clip.caption_file = out["caption_file"]
        clip.caption_style = style
        _drop_exports(clip)

    db.commit()
    db.refresh(clip)
    return clip
