"""Shared clip-update/reprocess logic — used by both the `PUT /api/clips/{id}`
HTTP route and the deep agent's `modify_clip` tool, so the two code paths
never drift apart."""
from __future__ import annotations
import json
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from autoclip.config import OUTPUT_DIR
from autoclip.models import Clip, Video
from autoclip.schemas import ClipUpdate
from autoclip.services.video_processor import cut_clip
from autoclip.services.caption_engine import generate_captions
from autoclip.utils.ffmpeg import burn_captions


async def apply_clip_update(db: Session, clip: Clip, video: Video | None, update: ClipUpdate) -> Clip:
    """Apply a ClipUpdate to `clip`, re-cutting/re-captioning on disk if the
    change requires it (trim or caption style). Commits the DB session."""
    needs_reprocess = False

    if update.title is not None:
        clip.title = update.title

    if update.caption_style is not None and update.caption_style != clip.caption_style:
        clip.caption_style = update.caption_style
        needs_reprocess = True

    if update.start_time is not None or update.end_time is not None:
        if update.start_time is not None:
            clip.start_time = update.start_time
        if update.end_time is not None:
            clip.end_time = update.end_time
        clip.duration = round(clip.end_time - clip.start_time, 2)
        needs_reprocess = True

    if update.music_id is not None:
        clip.music_id = update.music_id
    if update.music_url is not None:
        clip.music_url = update.music_url
    if update.music_volume is not None:
        clip.music_volume = update.music_volume

    if needs_reprocess and video:
        import asyncio
        clip_dir = OUTPUT_DIR / clip.video_id / "clips" / clip.id
        raw_path = str(clip_dir / "raw.mp4")
        await asyncio.to_thread(cut_clip, video.file_path, raw_path, clip.start_time, clip.end_time)

        transcript_file = OUTPUT_DIR / clip.video_id / "transcript.json"
        words = []
        if transcript_file.exists():
            with open(transcript_file) as f:
                words = json.load(f).get("words", [])

        if words:
            ass_path = str(clip_dir / "captions.ass")
            await asyncio.to_thread(generate_captions, words, clip.start_time, clip.end_time,
                                     clip.caption_style, ass_path)
            clip.caption_file = ass_path

            final_path = str(clip_dir / "final.mp4")
            try:
                await asyncio.to_thread(burn_captions, raw_path, ass_path, final_path)
            except Exception:
                shutil.copy2(raw_path, final_path)
            clip.file_path = final_path

    db.commit()
    db.refresh(clip)
    return clip
