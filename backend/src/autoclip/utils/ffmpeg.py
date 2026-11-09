import re
import subprocess
import json
from pathlib import Path
from typing import Optional


def get_video_info(file_path: str) -> dict:
    """Get video duration, resolution, and codec info using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)

    video_stream = next(
        (s for s in data.get("streams", []) if s["codec_type"] == "video"), None
    )

    info = {
        "duration": float(data["format"].get("duration", 0)),
        "resolution": None,
        "width": 0,
        "height": 0,
    }
    if video_stream:
        w = int(video_stream.get("width", 0))
        h = int(video_stream.get("height", 0))
        info["resolution"] = f"{w}x{h}"
        info["width"] = w
        info["height"] = h

    return info


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio as WAV for transcription."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def _nearest_keyframe(input_path: str, target: float) -> float:
    """Find the nearest keyframe at or before `target` (seconds)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_frames", "-show_entries", "frame=pkt_pts_time",
        "-read_intervals", f"{max(0.0, target - 5):.3f}%{target + 5:.3f}",
        "-of", "csv=p=0",
        input_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    # ffprobe sometimes emits non-numeric noise lines even at -v error (e.g.
    # "H.264 User Data Unregistered SEI message" for certain streams) —
    # live-tested and confirmed this crashes clip production if every line
    # is assumed to be a parseable timestamp. Skip lines that aren't floats.
    candidates = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            candidates.append(float(line))
        except ValueError:
            continue
    before = [t for t in candidates if t <= target]
    return max(before) if before else target


def cut_video(input_path: str, output_path: str, start: float, end: float) -> str:
    """Cut a segment using ffmpeg stream-copy (-c copy) — ~20x faster than re-encoding.

    Snaps `start` to the nearest preceding keyframe so the output is decodable
    from frame 0. Falls back to re-encoding if the keyframe distance > 2s
    (cut would drift too far from the requested start).
    """
    snapped = _nearest_keyframe(input_path, start)
    drift = start - snapped

    if drift <= 2.0:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(snapped),
            "-to", str(end),
            "-i", input_path,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            return output_path

    # Fallback: precise re-encode
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", input_path,
        "-ss", str(start),
        "-to", str(end),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def burn_captions(input_path: str, ass_path: str, output_path: str) -> str:
    """Burn ASS subtitles onto video."""
    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"ass='{ass_escaped}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def aspect_crop(
    region: tuple[int, int, int, int], target_w: int, target_h: int,
    center_x: Optional[float] = None,
) -> tuple[int, int, int, int]:
    """Largest target-aspect window (w, h, x, y) inside `region` (w, h, x, y).

    `center_x` (source-pixel coordinates) positions the window horizontally
    when the region is wider than the target — e.g. on a detected face.
    """
    rw, rh, rx, ry = region
    target_ratio = target_w / target_h
    if abs(rw / rh - target_ratio) < 0.01:
        return _even(rw), _even(rh), rx, ry
    if target_ratio < rw / rh:
        cw, ch = _even(int(rh * target_ratio)), _even(rh)
        cx = rx + (rw - cw) // 2 if center_x is None else int(center_x - cw / 2)
        cx = max(rx, min(cx, rx + rw - cw))
        return cw, ch, cx, ry
    cw, ch = _even(rw), _even(int(rw / target_ratio))
    cy = ry + (rh - ch) // 2
    return cw, ch, rx, cy


def _even(v: int) -> int:
    v = int(v)
    return v - (v % 2)


def reframe_video(
    input_path: str, output_path: str,
    target_w: int, target_h: int,
    crop_x: int = -1,
    src_crop: Optional[dict] = None,
    face_center_x: Optional[float] = None,
) -> str:
    """Reframe video to target aspect ratio.

    `src_crop` ({w,h,x,y}) removes a detected letterbox first; the aspect
    crop is then taken inside that region, centred on `face_center_x`
    (source pixels) if given. `crop_x` is the legacy explicit offset.
    """
    info = get_video_info(input_path)
    src_w, src_h = info["width"], info["height"]
    region = (src_w, src_h, 0, 0)
    if src_crop:
        region = (src_crop["w"], src_crop["h"], src_crop["x"], src_crop["y"])
    center = face_center_x
    if center is None and crop_x >= 0:
        center = crop_x + int(region[1] * target_w / target_h) / 2
    cw, ch, cx, cy = aspect_crop(region, target_w, target_h, center)
    vf = f"crop={cw}:{ch}:{cx}:{cy},scale={target_w}:{target_h},setsar=1"

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def probe_duration(path: str) -> float:
    """Container duration of a media file in seconds (0.0 if unknown)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


_CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def detect_letterbox(path: str, duration: float, width: int, height: int,
                     samples: int = 6, sample_seconds: float = 2.0) -> Optional[dict]:
    """Detect black bars with ffmpeg cropdetect at a few points in the video.

    Returns {w,h,x,y} of the picture area, or None when there are no
    meaningful bars. Uses the UNION of the per-sample boxes so a single dark
    scene can't make us over-crop real picture.
    """
    if not (duration and width and height):
        return None
    boxes = []
    for i in range(samples):
        t = duration * (0.08 + 0.84 * i / max(1, samples - 1))
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{t:.2f}", "-i", path,
            "-t", str(sample_seconds), "-vf", "cropdetect=limit=24:round=2:reset=0",
            "-an", "-f", "null", "-",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        found = _CROP_RE.findall(res.stderr or "")
        if found:
            w, h, x, y = map(int, found[-1])
            if w > 0 and h > 0:
                boxes.append((x, y, x + w, y + h))
    if not boxes:
        return None
    x1 = min(b[0] for b in boxes); y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes); y2 = max(b[3] for b in boxes)
    w, h = x2 - x1, y2 - y1
    # Snap near-full dimensions to the full frame (cropdetect is +-2px noisy).
    if w >= width * 0.97:
        x1, w = 0, width
    if h >= height * 0.97:
        y1, h = 0, height
    if w * h >= width * height * 0.93:
        return None  # bars too thin to matter
    return {"w": _even(w), "h": _even(h), "x": x1, "y": y1}


def scan_keyframe_luma(path: str, start: float) -> list[tuple[float, float]]:
    """(timestamp, mean luma 0-255) for every keyframe from `start` to EOF.

    Keyframe-only decoding (-skip_frame nokey) makes this ~1s for the last
    15 minutes of a feature film.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-skip_frame", "nokey",
        "-ss", f"{max(0.0, start):.2f}", "-i", path,
        "-vf", "scale=96:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
        "-vsync", "0", "-an", "-f", "null", "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    out: list[tuple[float, float]] = []
    pts = None
    for line in (res.stderr or "").splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            pts = float(m.group(1))
            continue
        m = re.search(r"YAVG=([0-9.]+)", line)
        if m and pts is not None:
            out.append((round(start + pts, 2), float(m.group(1))))
            pts = None
    return out


def render_clip(
    input_path: str, output_path: str, start: float, end: float,
    crop: Optional[tuple[int, int, int, int]] = None,
    scale: Optional[tuple[int, int]] = None,
    ass_path: Optional[str] = None,
    waveform: bool = False,
) -> str:
    """Cut + crop + scale + burn captions in ONE frame-accurate encode.

    Replaces cut(-c copy, keyframe-snapped) -> reframe -> burn: the stream-copy
    cut started at the previous keyframe (clips ran up to ~2s long) and every
    extra step re-encoded the video again.

    `waveform` (audio uploads, needs `scale`): the source is a static title
    card (services/audiogram.py); an animated gold waveform of the clip's
    audio is drawn across the middle of the output, under the captions.
    """
    filters = []
    if crop:
        cw, ch, cx, cy = crop
        filters.append(f"crop={cw}:{ch}:{cx}:{cy}")
    if scale:
        filters.append(f"scale={scale[0]}:{scale[1]}")
    filters.append("setsar=1")
    ass = None
    if ass_path:
        ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        ass = f"ass='{ass_escaped}'"
    if waveform and scale:
        from autoclip.services.audiogram import waveform_filter
        graph = (f"[0:v]{','.join(filters)},fps=30[bg];{waveform_filter(scale[0], scale[1])};"
                 f"[bg][wave]overlay=0:(main_h-overlay_h)/2:shortest=1" + (f",{ass}" if ass else "") + "[v]")
        video_args = ["-filter_complex", graph, "-map", "[v]", "-map", "0:a:0"]
    else:
        if ass:
            filters.append(ass)
        video_args = ["-vf", ",".join(filters)]
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{max(0.0, start):.3f}", "-i", input_path,
        "-t", f"{max(0.1, end - start):.3f}",
        *video_args,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {(res.stderr or '')[-500:]}")
    return output_path


def add_music(
    video_path: str, music_path: str, output_path: str,
    music_volume: float = 0.3
) -> str:
    """Mix background music into video."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        f"[1:a]volume={music_volume}[bg];[0:a][bg]amix=inputs=2:duration=first[out]",
        "-map", "0:v", "-map", "[out]",
        "-c:v", "copy", "-c:a", "aac",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def extract_frame(video_path: str, timestamp: float, output_path: str) -> str:
    """Extract a single frame as image."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path
