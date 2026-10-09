"""Per-video facts computed once and cached next to the outputs.

`outputs/<video_id>/profile.json` holds:
  • letterbox — the picture area inside black bars (ffmpeg cropdetect), so
    vertical/square reframes crop real picture instead of ~25% black.
  • credits_start — where the end credits begin (see below), so clip
    selection never lands on a scrolling cast list.

Credits heuristic (deliberately simple, documented):
  1. Visual (primary, transcript-independent): decode only keyframes from the
     last 20% of the video (max 15 min) and read their mean luma. End credits
     are white text on black, so the frames are dark. `credits_start` is the
     earliest dark keyframe t such that >= 80% of keyframes in [t, end] are
     dark and the dark tail lasts >= 20s (a fade-out to black is not credits).
  2. Speech (secondary, only when the transcript looks healthy — word timings
     span >= 50% of the video at >= 6 words/min): nothing after the last
     spoken word + 30s, nothing before the first spoken word - 30s.
`safe_range()` combines both into the [lo, hi] window clips must sit in.
"""
from __future__ import annotations
import json
import logging
import threading
from pathlib import Path
from typing import Optional

from autoclip.utils.ffmpeg import get_video_info, detect_letterbox, scan_keyframe_luma
from autoclip.utils.paths import video_output_dir

logger = logging.getLogger(__name__)

PROFILE_VERSION = 1
DARK_LUMA = 36.0           # mean luma (0-255) below which a keyframe counts as dark
DARK_TAIL_FRACTION = 0.8   # share of tail keyframes that must be dark
MIN_CREDITS_SECONDS = 20.0
SPEECH_MARGIN = 30.0

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(video_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(video_id, threading.Lock())


def _profile_path(video_id: str) -> Path:
    return video_output_dir(video_id) / "profile.json"


def detect_credits_start(video_path: str, duration: float) -> Optional[float]:
    if duration < 60:
        return None
    window = min(duration * 0.2, 900.0)
    samples = scan_keyframe_luma(video_path, duration - window)
    if len(samples) < 4:
        return None
    dark_count = 0
    best: Optional[float] = None
    bright_run_start: Optional[float] = None
    # Walk backwards from the end; any suffix that is mostly dark is a candidate.
    # Stop at the first sustained (>15s) bright stretch — that is the film.
    for i in range(len(samples) - 1, -1, -1):
        t, luma = samples[i]
        if luma < DARK_LUMA:
            dark_count += 1
            bright_run_start = None
        else:
            if bright_run_start is None:
                bright_run_start = t
            elif bright_run_start - t > 15.0:
                break
        n = len(samples) - i
        if luma < DARK_LUMA and dark_count / n >= DARK_TAIL_FRACTION:
            best = t
    if best is None or duration - best < MIN_CREDITS_SECONDS:
        return None
    return round(best, 2)


def get_profile(video_id: str, video_path: str) -> dict:
    """Load (or compute once and cache) the per-video profile."""
    path = _profile_path(video_id)
    with _lock_for(video_id):
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if data.get("version") == PROFILE_VERSION:
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        info = get_video_info(video_path)
        duration, w, h = info.get("duration", 0.0), info.get("width", 0), info.get("height", 0)
        letterbox = None
        credits = None
        try:
            letterbox = detect_letterbox(video_path, duration, w, h)
        except Exception as e:  # never block production on a probe
            logger.warning("letterbox detection failed for %s: %s", video_id, e)
        try:
            credits = detect_credits_start(video_path, duration)
        except Exception as e:
            logger.warning("credits detection failed for %s: %s", video_id, e)
        data = {
            "version": PROFILE_VERSION, "width": w, "height": h, "duration": duration,
            "letterbox": letterbox, "credits_start": credits,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
        except OSError as e:
            logger.warning("could not cache profile for %s: %s", video_id, e)
        logger.info("video profile %s: letterbox=%s credits_start=%s", video_id, letterbox, credits)
        return data


def _speech_bounds(words: list[dict], duration: float) -> tuple[Optional[float], Optional[float]]:
    if not words or duration <= 0:
        return None, None
    first, last = words[0]["start"], words[-1]["end"]
    span = last - first
    if span < 0.5 * duration or len(words) / max(span / 60.0, 1e-6) < 6:
        return None, None  # transcript too sparse/partial to trust
    return first, last


def safe_range(video_id: str, video_path: str, duration: float,
               words: Optional[list[dict]] = None) -> tuple[float, float]:
    """[lo, hi] window clips may come from: excludes end credits and the
    speech-free head/tail (when the transcript is trustworthy)."""
    profile = get_profile(video_id, video_path)
    duration = float(duration or profile.get("duration") or 0.0)
    lo, hi = 0.0, duration
    credits = profile.get("credits_start")
    if credits:
        hi = min(hi, float(credits))
    first, last = _speech_bounds(words or [], duration)
    if last is not None:
        hi = min(hi, last + SPEECH_MARGIN)
    if first is not None:
        lo = max(lo, first - SPEECH_MARGIN)
    if hi - lo < 10:  # heuristics disagree badly — fall back to the whole video
        return 0.0, duration
    return lo, hi
