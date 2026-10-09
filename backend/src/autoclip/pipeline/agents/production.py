"""Production node — renders each selected clip in a single ffmpeg pass.

Per clip:
  1. Per-video profile (cached): letterbox box + credits window.
  2. Crop window: inside the letterbox (no black bars), at the target aspect,
     centred on the MEDIAN face position over the clip (9:16 and 1:1).
  3. Captions: ASS sized to the output resolution, in the clip's
     caption_style — or none at all when nobody speaks in the window.
  4. One frame-accurate encode: seek -> crop -> scale -> burn captions.
  5. Clip.duration is read back from the rendered file (ffprobe).

`render_clip_assets()` is shared with services/clip_reprocess.py so a trim or
caption-style change re-renders exactly like the original production did.
"""
from __future__ import annotations
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Optional

from autoclip.config import EXPORT_FORMATS, CAPTION_STYLES
from autoclip.utils.ffmpeg import render_clip, aspect_crop, probe_duration
from autoclip.utils.paths import clip_dir as clip_dir_for
from autoclip.utils.video_profile import get_profile
from autoclip.services.caption_engine import generate_captions
from autoclip.services.video_processor import face_center_x
from autoclip.services.thumbnail_gen import generate_thumbnail
from autoclip.services import events as pipeline_events
from autoclip.pipeline.state import PipelineState, ProducedClip

logger = logging.getLogger(__name__)

PRODUCTION_WORKERS = int(os.getenv("PRODUCTION_WORKERS", "2"))


def render_clip_assets(
    *,
    video_id: str,
    video_path: str,
    clip_id: str,
    start: float,
    end: float,
    frame: str = "9:16",
    caption_style: str = "bold_pop",
    words: Optional[list[dict]] = None,
    title: str = "",
    output_name: str = "final.mp4",
) -> dict:
    """Render final.mp4 (+captions, thumbnail) for one clip.

    Returns {file_path, thumbnail_path, caption_file, start, end, duration}
    with absolute paths. `end` is clamped to the source duration.
    """
    profile = get_profile(video_id, video_path)
    src_w, src_h = int(profile.get("width") or 0), int(profile.get("height") or 0)
    src_dur = float(profile.get("duration") or 0.0)
    if src_dur > 0:
        end = min(end, src_dur)
    start = max(0.0, start)
    if end - start < 0.5:
        raise ValueError(f"clip window too short: {start:.2f}-{end:.2f}")

    out_dir = clip_dir_for(video_id, clip_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    fmt = EXPORT_FORMATS.get(frame) or EXPORT_FORMATS["9:16"]
    out_w, out_h = fmt["width"], fmt["height"]
    crop = None
    scale = None
    if src_w and src_h:
        source_ratio = src_w / src_h
        if frame == "16:9" and abs(source_ratio - 16 / 9) < 0.02:
            scale = None if (src_w, src_h) == (out_w, out_h) else (out_w, out_h)
        else:
            lb = profile.get("letterbox") if frame != "16:9" else None
            region = (lb["w"], lb["h"], lb["x"], lb["y"]) if lb else (src_w, src_h, 0, 0)
            center = None
            if frame in ("9:16", "1:1"):
                try:
                    center = face_center_x(video_path, start, end, region=lb)
                except Exception as e:
                    logger.debug("face detection failed for clip %s: %s", clip_id, e)
            crop = aspect_crop(region, out_w, out_h, center)
            scale = (out_w, out_h)
    final_w, final_h = scale or (src_w or out_w, src_h or out_h)

    style = caption_style if caption_style in CAPTION_STYLES else "bold_pop"
    ass_path: Optional[str] = None
    try:
        ass_path = generate_captions(
            words or [], start, end, style,
            str(out_dir / "captions.ass"), play_res=(final_w, final_h),
        )
    except Exception as e:
        logger.warning("caption generation failed for clip %s: %s", clip_id, e)
        ass_path = None
    if ass_path is None:
        stale = out_dir / "captions.ass"
        if stale.exists():
            stale.unlink()

    final_path = str(out_dir / output_name)
    tmp_path = str(out_dir / f"{Path(output_name).stem}.tmp.mp4")
    try:
        render_clip(video_path, tmp_path, start, end, crop=crop, scale=scale, ass_path=ass_path)
    except Exception:
        if not ass_path:
            raise
        logger.warning("render with captions failed for %s — retrying without", clip_id)
        ass_path = None
        render_clip(video_path, tmp_path, start, end, crop=crop, scale=scale)
    os.replace(tmp_path, final_path)
    for leftover in ("raw.mp4", "reframed.mp4"):
        try:
            (out_dir / leftover).unlink()
        except FileNotFoundError:
            pass

    thumb_path: Optional[str] = str(out_dir / "thumbnail.jpg")
    try:
        generate_thumbnail(final_path, thumb_path, title)
    except Exception:
        thumb_path = None

    duration = probe_duration(final_path) or (end - start)
    return {
        "file_path": final_path,
        "thumbnail_path": thumb_path,
        "caption_file": ass_path,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(duration, 2),
    }


def _produce_one(video_id: str, video_path: str, words: list[dict], clip: ProducedClip) -> Optional[ProducedClip]:
    try:
        out = render_clip_assets(
            video_id=video_id, video_path=video_path, clip_id=clip.id,
            start=clip.start_time, end=clip.end_time, frame=clip.frame,
            caption_style=clip.caption_style, words=words, title=clip.title,
        )
    except Exception as e:
        logger.warning("Failed to produce clip %s: %s", clip.id, e)
        return None
    produced = replace(
        clip,
        start_time=out["start"], end_time=out["end"], duration=out["duration"],
        file_path=out["file_path"], thumbnail_path=out["thumbnail_path"],
    )
    try:
        from autoclip.utils.paths import public_url
        payload = asdict(produced)
        payload["file_url"] = public_url(produced.file_path)
        payload["thumbnail_url"] = public_url(produced.thumbnail_path)
        pipeline_events.publish_clip_ready(video_id, payload)
    except Exception:
        pass
    return produced


def run_production(state: PipelineState) -> dict:
    """Render every selected clip (a couple in parallel) and publish events."""
    video_path = state["video_path"]
    video_id = state["video_id"]
    clips = state.get("clips", [])
    words = (state.get("transcript_data") or {}).get("words", []) or []

    if not clips:
        return {"clips": []}

    with ThreadPoolExecutor(max_workers=max(1, PRODUCTION_WORKERS)) as pool:
        results = list(pool.map(lambda c: _produce_one(video_id, video_path, words, c), clips))
    produced_clips = [c for c in results if c is not None]

    # Not "done": that name used to close the SSE stream mid-conversation.
    pipeline_events.publish(video_id, "clips_done", {"clip_count": len(produced_clips)})
    return {"clips": produced_clips}
