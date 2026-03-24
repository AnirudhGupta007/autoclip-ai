"""Visual analysis agent — extracts timeline of visual signals from video frames.

Uses a two-pass sampling strategy:
    1. Coarse pass: sample every N seconds, detect high-energy regions
    2. Dense pass: re-sample high-energy regions at higher frequency

Sends frame batches to Gemini Vision for structured analysis:
    - Facial emotion detection
    - Scene type classification
    - Visual energy scoring
    - Text/slide detection (OCR indicator)
"""
import json
import time
import math
from pathlib import Path
from google import genai
from autoclip.config import GEMINI_API_KEY, GEMINI_RPM_DELAY
from autoclip.utils.ffmpeg import extract_frame, get_video_info
from autoclip.pipeline.state import PipelineState, VisualSignal, FrameAnalysis


# Sampling configuration per video type
SAMPLING_CONFIG = {
    "talking_head": {"coarse_interval": 3.0, "dense_interval": 1.0, "energy_threshold": 0.6},
    "presentation":  {"coarse_interval": 2.0, "dense_interval": 0.5, "energy_threshold": 0.5},
    "podcast":       {"coarse_interval": 5.0, "dense_interval": 2.0, "energy_threshold": 0.7},
    "mixed":         {"coarse_interval": 2.5, "dense_interval": 1.0, "energy_threshold": 0.55},
}

BATCH_SIZE = 10  # Max frames per Gemini Vision call
MODEL = "gemini-2.0-flash"


def _extract_frames_at_timestamps(
    video_path: str, timestamps: list[float], output_dir: Path
) -> list[tuple[float, str]]:
    """Extract frames at given timestamps. Returns list of (timestamp, file_path)."""
    results = []
    for t in timestamps:
        fp = str(output_dir / f"frame_{int(t * 100):08d}.jpg")
        try:
            extract_frame(video_path, t, fp)
            results.append((t, fp))
        except Exception:
            continue
    return results


def _build_vision_prompt(frame_count: int, timestamps: list[float]) -> str:
    """Build the structured analysis prompt for Gemini Vision."""
    return (
        f"Analyze these {frame_count} video frames sampled at timestamps {timestamps}.\n\n"
        "For EACH frame, evaluate:\n"
        "1. energy (0.0-1.0): How visually dynamic? Consider gestures, movement, "
        "facial expressiveness, scene complexity. 0=static/boring, 1=highly dynamic.\n"
        "2. emotion: The dominant emotion shown (neutral/happy/surprised/angry/sad/excited)\n"
        "3. emotion_confidence (0.0-1.0): How clear is the emotion?\n"
        "4. description: What's happening visually (max 15 words)\n"
        "5. has_text_on_screen: Is there text, slides, titles, or graphics visible?\n"
        "6. scene_type: One of (talking_head, presentation, broll, audience)\n\n"
        "Return ONLY a JSON array with one object per frame, in order.\n"
        "Each object must have keys: energy, emotion, emotion_confidence, "
        "description, has_text_on_screen, scene_type"
    )


def _analyze_frame_batch(
    client: genai.Client,
    frame_paths: list[str],
    timestamps: list[float],
) -> list[dict]:
    """Send a batch of frames to Gemini Vision for analysis.

    Uses multimodal input: text prompt + image parts.
    Returns parsed JSON array of frame analyses.
    """
    prompt = _build_vision_prompt(len(frame_paths), timestamps)
    contents = [prompt]

    # Add each frame as an image part
    for fp in frame_paths:
        with open(fp, "rb") as f:
            image_data = f.read()
        contents.append(
            genai.types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
        )

    response = client.models.generate_content(model=MODEL, contents=contents)
    text = response.text.strip()

    # Extract JSON from markdown code blocks if present
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    return json.loads(text.strip())


def _coarse_pass(
    video_path: str, video_id: str, duration: float, interval: float
) -> tuple[list[VisualSignal], list[tuple[float, float]]]:
    """First pass: sample at regular intervals, identify high-energy regions.

    Returns:
        signals: List of VisualSignal from coarse analysis
        high_energy_regions: List of (start, end) tuples for dense re-sampling
    """
    frame_dir = Path(f"outputs/{video_id}/frames/coarse")
    frame_dir.mkdir(parents=True, exist_ok=True)

    # Generate timestamps
    timestamps = []
    t = 1.0
    while t < duration - 1:
        timestamps.append(round(t, 2))
        t += interval

    if not timestamps:
        return [], []

    # Extract all frames
    frame_data = _extract_frames_at_timestamps(video_path, timestamps, frame_dir)
    if not frame_data:
        return [], []

    # Analyze in batches
    client = genai.Client(api_key=GEMINI_API_KEY)
    signals = []

    for i in range(0, len(frame_data), BATCH_SIZE):
        batch = frame_data[i:i + BATCH_SIZE]
        batch_times = [t for t, _ in batch]
        batch_paths = [p for _, p in batch]

        try:
            results = _analyze_frame_batch(client, batch_paths, batch_times)
            for j, result in enumerate(results):
                if j < len(batch_times):
                    signals.append(VisualSignal(
                        timestamp=batch_times[j],
                        energy=float(result.get("energy", 0.5)),
                        emotion=result.get("emotion", "neutral"),
                        emotion_confidence=float(result.get("emotion_confidence", 0.5)),
                        description=result.get("description", ""),
                        has_text_on_screen=bool(result.get("has_text_on_screen", False)),
                        scene_type=result.get("scene_type", "talking_head"),
                    ))
        except Exception as e:
            print(f"Visual coarse batch {i} failed: {e}")

        time.sleep(GEMINI_RPM_DELAY)

    # Identify high-energy regions for dense pass
    high_energy_regions = _find_high_energy_regions(signals, interval)

    return signals, high_energy_regions


def _find_high_energy_regions(
    signals: list[VisualSignal],
    interval: float,
    energy_threshold: float = 0.6,
    merge_gap: float = 5.0,
) -> list[tuple[float, float]]:
    """Find contiguous regions where visual energy exceeds threshold.

    Merges nearby regions to avoid fragmenting interesting sections.
    """
    if not signals:
        return []

    # Find signals above threshold
    high_signals = [s for s in signals if s.energy > energy_threshold]
    if not high_signals:
        # If nothing above threshold, take top 20% by energy
        sorted_signals = sorted(signals, key=lambda s: s.energy, reverse=True)
        top_count = max(1, len(sorted_signals) // 5)
        high_signals = sorted_signals[:top_count]

    # Sort by timestamp
    high_signals.sort(key=lambda s: s.timestamp)

    # Build regions with padding
    pad = interval * 1.5
    regions = []
    for s in high_signals:
        start = max(0, s.timestamp - pad)
        end = s.timestamp + pad
        regions.append((start, end))

    # Merge overlapping/adjacent regions
    if not regions:
        return []

    merged = [regions[0]]
    for start, end in regions[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + merge_gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    return merged


def _dense_pass(
    video_path: str,
    video_id: str,
    regions: list[tuple[float, float]],
    interval: float,
) -> list[VisualSignal]:
    """Second pass: densely sample high-energy regions for fine-grained analysis.

    Only runs on regions identified by the coarse pass.
    """
    if not regions:
        return []

    frame_dir = Path(f"outputs/{video_id}/frames/dense")
    frame_dir.mkdir(parents=True, exist_ok=True)

    # Generate dense timestamps within each region
    timestamps = []
    for start, end in regions:
        t = start
        while t < end:
            timestamps.append(round(t, 2))
            t += interval

    if not timestamps:
        return []

    # Deduplicate and sort
    timestamps = sorted(set(timestamps))

    # Extract frames
    frame_data = _extract_frames_at_timestamps(video_path, timestamps, frame_dir)
    if not frame_data:
        return []

    # Analyze in batches
    client = genai.Client(api_key=GEMINI_API_KEY)
    signals = []

    for i in range(0, len(frame_data), BATCH_SIZE):
        batch = frame_data[i:i + BATCH_SIZE]
        batch_times = [t for t, _ in batch]
        batch_paths = [p for _, p in batch]

        try:
            results = _analyze_frame_batch(client, batch_paths, batch_times)
            for j, result in enumerate(results):
                if j < len(batch_times):
                    signals.append(VisualSignal(
                        timestamp=batch_times[j],
                        energy=float(result.get("energy", 0.5)),
                        emotion=result.get("emotion", "neutral"),
                        emotion_confidence=float(result.get("emotion_confidence", 0.5)),
                        description=result.get("description", ""),
                        has_text_on_screen=bool(result.get("has_text_on_screen", False)),
                        scene_type=result.get("scene_type", "talking_head"),
                    ))
        except Exception as e:
            print(f"Visual dense batch {i} failed: {e}")

        time.sleep(GEMINI_RPM_DELAY)

    return signals


def _merge_signals(
    coarse: list[VisualSignal], dense: list[VisualSignal]
) -> list[VisualSignal]:
    """Merge coarse and dense signals, preferring dense where overlap exists.

    Dense signals are higher resolution in high-energy regions,
    so they take priority over coarse signals at the same timestamps.
    """
    # Build a set of dense timestamps (with tolerance)
    dense_times = {round(s.timestamp, 1) for s in dense}

    # Keep coarse signals that don't overlap with dense
    merged = [s for s in coarse if round(s.timestamp, 1) not in dense_times]
    merged.extend(dense)

    # Sort by timestamp
    merged.sort(key=lambda s: s.timestamp)
    return merged


def run_visual_agent(state: PipelineState) -> dict:
    """Run the two-pass visual analysis pipeline.

    Pass 1 (Coarse): Sample every N seconds across entire video.
    Pass 2 (Dense): Re-sample high-energy regions at higher frequency.
    Merge results into a unified visual timeline.
    """
    video_path = state["video_path"]
    video_id = state["video_id"]
    video_type = state.get("video_type", "mixed")

    # Get video duration
    info = get_video_info(video_path)
    duration = info["duration"]

    # Get sampling config for this video type
    config = SAMPLING_CONFIG.get(video_type, SAMPLING_CONFIG["mixed"])
    coarse_interval = config["coarse_interval"]
    dense_interval = config["dense_interval"]
    energy_threshold = config["energy_threshold"]

    # Pass 1: Coarse sampling
    coarse_signals, high_energy_regions = _coarse_pass(
        video_path, video_id, duration, coarse_interval
    )

    # Pass 2: Dense sampling of high-energy regions only
    dense_signals = _dense_pass(
        video_path, video_id, high_energy_regions, dense_interval
    )

    # Merge both passes
    timeline = _merge_signals(coarse_signals, dense_signals)

    return {"visual_timeline": timeline}
