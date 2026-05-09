"""Lightweight scene detection via ffmpeg's `select='gt(scene,X)'` filter.

Replaces PySceneDetect (10x faster, no Python deps). Used by clip_selector
to snap clip boundaries to scene cuts.
"""
from __future__ import annotations
import os
import re
import subprocess
import logging

logger = logging.getLogger(__name__)

SCENE_THRESHOLD = float(os.getenv("SCENE_THRESHOLD", "0.3"))


def detect_scenes(video_path: str) -> list[dict]:
    """Return [{'start': t, 'end': t}] for each scene boundary."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", video_path,
        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        logger.warning("ffmpeg not found — scene detection disabled")
        return []
    timestamps = sorted({
        round(float(t), 2)
        for t in re.findall(r"pts_time:([0-9.]+)", result.stderr or "")
    })
    if not timestamps:
        return []
    scenes: list[dict] = []
    for i, t in enumerate(timestamps):
        end = timestamps[i + 1] if i + 1 < len(timestamps) else t + 5.0
        scenes.append({"start": t, "end": end})
    return scenes


def detect_scene_boundaries(video_path: str) -> list[float]:
    return [s["start"] for s in detect_scenes(video_path)]
