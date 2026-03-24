import subprocess
import json
from pathlib import Path


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


def cut_video(input_path: str, output_path: str, start: float, end: float) -> str:
    """Cut a segment from video with precise re-encoding."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", str(start),
        "-to", str(end),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        output_path
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


def reframe_video(
    input_path: str, output_path: str,
    target_w: int, target_h: int,
    crop_x: int = -1
) -> str:
    """Reframe video to target aspect ratio with optional crop offset."""
    info = get_video_info(input_path)
    src_w, src_h = info["width"], info["height"]

    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if abs(target_ratio - src_ratio) < 0.01:
        vf = f"scale={target_w}:{target_h}"
    elif target_ratio < src_ratio:
        crop_h = src_h
        crop_w = int(src_h * target_ratio)
        if crop_x < 0:
            crop_x = (src_w - crop_w) // 2
        crop_x = max(0, min(crop_x, src_w - crop_w))
        vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,scale={target_w}:{target_h}"
    else:
        crop_w = src_w
        crop_h = int(src_w / target_ratio)
        crop_y = (src_h - crop_h) // 2
        vf = f"crop={crop_w}:{crop_h}:0:{crop_y},scale={target_w}:{target_h}"

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
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
