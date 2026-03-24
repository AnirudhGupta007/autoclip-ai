"""LangGraph tool definitions — callable tools for agent nodes.

These are registered as LangChain tools so agents can invoke them
via function calling. Used in ToolNode for the production subgraph.
"""
from langchain_core.tools import tool
from autoclip.utils.ffmpeg import (
    extract_frame, extract_audio, cut_video, burn_captions,
    reframe_video, get_video_info, add_music,
)
from autoclip.services.scene_detector import detect_scenes
from autoclip.services.caption_engine import generate_captions
from autoclip.services.video_processor import detect_face_position
from autoclip.services.thumbnail_gen import generate_thumbnail


@tool
def tool_extract_frames(video_path: str, timestamps: list[float], output_dir: str) -> list[str]:
    """Extract frames from video at specified timestamps.
    Returns list of file paths for extracted frame images."""
    import os
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for t in timestamps:
        out = os.path.join(output_dir, f"frame_{int(t * 10):06d}.jpg")
        try:
            extract_frame(video_path, t, out)
            paths.append(out)
        except Exception:
            pass
    return paths


@tool
def tool_extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video as WAV file for analysis.
    Returns path to the extracted audio file."""
    return extract_audio(video_path, output_path)


@tool
def tool_get_video_info(video_path: str) -> dict:
    """Get video metadata: duration, resolution, width, height.
    Returns dict with video information."""
    return get_video_info(video_path)


@tool
def tool_detect_scenes(video_path: str, threshold: float = 27.0) -> list[dict]:
    """Detect scene boundaries in video using content detection.
    Returns list of scenes with start/end timestamps."""
    return detect_scenes(video_path, threshold)


@tool
def tool_cut_clip(video_path: str, output_path: str, start: float, end: float) -> str:
    """Cut a segment from source video between start and end timestamps.
    Returns path to the cut clip."""
    return cut_video(video_path, output_path, start, end)


@tool
def tool_generate_captions(
    words_json: str, clip_start: float, clip_end: float,
    style: str, output_path: str
) -> str:
    """Generate animated ASS captions for a clip segment.
    words_json is a JSON string of word timestamps.
    Returns path to the generated ASS file."""
    import json
    words = json.loads(words_json)
    return generate_captions(words, clip_start, clip_end, style, output_path)


@tool
def tool_burn_captions(video_path: str, ass_path: str, output_path: str) -> str:
    """Burn ASS subtitle file onto video (hardcoded captions).
    Returns path to the captioned video."""
    return burn_captions(video_path, ass_path, output_path)


@tool
def tool_reframe_video(
    video_path: str, output_path: str,
    target_width: int, target_height: int
) -> str:
    """Reframe video to target aspect ratio with smart cropping.
    Uses face detection for portrait crops.
    Returns path to the reframed video."""
    crop_x = -1
    target_ratio = target_width / target_height
    if target_ratio < 1:  # portrait
        crop_x = detect_face_position(video_path)
    return reframe_video(video_path, output_path, target_width, target_height, crop_x)


@tool
def tool_generate_thumbnail(video_path: str, output_path: str, title: str) -> str:
    """Generate a thumbnail image from video with title overlay.
    Returns path to the generated thumbnail."""
    return generate_thumbnail(video_path, output_path, title)


# All tools available to the production agent
PRODUCTION_TOOLS = [
    tool_cut_clip,
    tool_generate_captions,
    tool_burn_captions,
    tool_reframe_video,
    tool_generate_thumbnail,
]

# All tools available for video analysis
ANALYSIS_TOOLS = [
    tool_extract_frames,
    tool_extract_audio,
    tool_get_video_info,
    tool_detect_scenes,
]
