"""Video processing: cutting clips and auto-reframing."""
from __future__ import annotations
from typing import Optional

import cv2
import numpy as np
from autoclip.utils.ffmpeg import cut_video, reframe_video, get_video_info
from autoclip.config import EXPORT_FORMATS


face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


def face_center_x(
    video_path: str,
    start: float = 0.0,
    end: Optional[float] = None,
    sample_count: int = 15,
    region: Optional[dict] = None,
) -> Optional[float]:
    """Robust horizontal face centre (source-pixel x) over [start, end].

    Samples `sample_count` frames evenly across the window, takes the largest
    plausible face in each (restricted to the letterbox `region` if given),
    and returns the MEDIAN centre. One static crop centred on the median
    keeps the subject in frame for the whole clip without the jitter a
    per-frame track would add; outliers (a single false positive, a passer-by)
    can't drag it the way the old 5-sample mean could. None if no faces.
    """
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            return None
        if end is None or end <= start:
            end = total / fps
        times = np.linspace(start + 0.2, max(start + 0.3, end - 0.2), sample_count)
        centres: list[float] = []
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            ox, oy = 0, 0
            if region:
                ox, oy = region["x"], region["y"]
                frame = frame[oy:oy + region["h"], ox:ox + region["w"]]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            min_side = max(24, int(gray.shape[0] * 0.08))
            faces = face_cascade.detectMultiScale(gray, 1.2, 6, minSize=(min_side, min_side))
            if len(faces) == 0:
                continue
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            centres.append(ox + fx + fw / 2.0)
        if not centres:
            return None
        # Require faces in a reasonable share of samples, else it's noise.
        if len(centres) < max(2, sample_count // 5):
            return None
        return float(np.median(centres))
    finally:
        cap.release()


def detect_face_position(video_path: str, sample_count: int = 9) -> int:
    """Legacy API: crop x-offset for a 9:16 crop of `video_path`, or -1."""
    cx = face_center_x(video_path, sample_count=sample_count)
    if cx is None:
        return -1
    info = get_video_info(video_path)
    src_w, src_h = info["width"], info["height"]
    crop_w = int(src_h * 9 / 16)
    return int(max(0, min(cx - crop_w // 2, src_w - crop_w)))


def cut_clip(
    video_path: str, output_path: str,
    start: float, end: float
) -> str:
    """Cut a clip from the source video."""
    return cut_video(video_path, output_path, start, end)


def export_clip(
    clip_path: str, output_path: str,
    format_key: str
) -> str:
    """Export clip in specified format with auto-reframe."""
    fmt = EXPORT_FORMATS.get(format_key)
    if not fmt:
        raise ValueError(f"Unknown format: {format_key}")

    center = None
    if format_key == "9:16":
        center = face_center_x(clip_path, sample_count=9)

    return reframe_video(
        clip_path, output_path,
        fmt["width"], fmt["height"],
        face_center_x=center,
    )
