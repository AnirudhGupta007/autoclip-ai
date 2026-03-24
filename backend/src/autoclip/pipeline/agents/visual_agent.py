"""Visual analysis agent — extracts timeline of visual signals from video frames."""
import json
import time
from pathlib import Path
from google import genai
from autoclip.config import GEMINI_API_KEY, GEMINI_RPM_DELAY
from autoclip.utils.ffmpeg import extract_frame, get_video_info
from autoclip.pipeline.state import PipelineState, VisualSignal


def _analyze_frame_batch(client, frame_paths: list[str], timestamps: list[float]) -> list[dict]:
    """Send a batch of frames to Gemini Vision for analysis."""
    contents = [
        "Analyze each frame from a video. For each frame, return:\n"
        "- energy (0.0-1.0): How visually dynamic/interesting is this frame?\n"
        "- emotion: What emotion is the speaker/subject showing? "
        "(neutral, happy, surprised, angry, sad, excited)\n"
        "- emotion_confidence (0.0-1.0): How confident are you?\n"
        "- description: Brief description of what's happening (max 15 words)\n"
        "- has_text_on_screen: Is there text/slides/titles visible? (true/false)\n"
        "- scene_type: One of (talking_head, presentation, broll, audience)\n\n"
        f"There are {len(frame_paths)} frames at timestamps: {timestamps}\n\n"
        "Return ONLY a JSON array with one object per frame, in order."
    ]

    for fp in frame_paths:
        with open(fp, "rb") as f:
            image_data = f.read()
        contents.append(genai.types.Part.from_bytes(data=image_data, mime_type="image/jpeg"))

    response = client.models.generate_content(model="gemini-2.0-flash", contents=contents)
    text = response.text.strip()

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    return json.loads(text.strip())


def run_visual_agent(state: PipelineState) -> dict:
    """
    Extract frames at regular intervals and analyze them with Gemini Vision.
    Produces a timeline of visual signals.
    """
    video_path = state["video_path"]
    video_id = state["video_id"]
    video_type = state.get("video_type", "mixed")

    frame_dir = Path(f"outputs/{video_id}/frames")
    frame_dir.mkdir(parents=True, exist_ok=True)

    # Get video duration
    info = get_video_info(video_path)
    duration = info["duration"]

    # Determine sampling rate based on video type
    # Podcast: less visual change, sample less frequently
    # Mixed/presentation: more visual variety, sample more
    if video_type == "podcast":
        interval = 4.0  # every 4 seconds
    elif video_type == "presentation":
        interval = 2.0  # every 2 seconds (catch slide changes)
    else:
        interval = 3.0  # default every 3 seconds

    # Extract frames
    timestamps = []
    frame_paths = []
    t = 1.0
    while t < duration - 1:
        fp = str(frame_dir / f"frame_{int(t * 10):06d}.jpg")
        try:
            extract_frame(video_path, t, fp)
            timestamps.append(round(t, 2))
            frame_paths.append(fp)
        except Exception:
            pass
        t += interval

    if not frame_paths:
        return {"visual_timeline": []}

    # Process in batches of 10 frames (Gemini context limit friendly)
    client = genai.Client(api_key=GEMINI_API_KEY)
    batch_size = 10
    visual_timeline = []

    for i in range(0, len(frame_paths), batch_size):
        batch_frames = frame_paths[i:i + batch_size]
        batch_times = timestamps[i:i + batch_size]

        try:
            results = _analyze_frame_batch(client, batch_frames, batch_times)

            for j, result in enumerate(results):
                if j < len(batch_times):
                    signal = VisualSignal(
                        timestamp=batch_times[j],
                        energy=float(result.get("energy", 0.5)),
                        emotion=result.get("emotion", "neutral"),
                        emotion_confidence=float(result.get("emotion_confidence", 0.5)),
                        description=result.get("description", ""),
                        has_text_on_screen=bool(result.get("has_text_on_screen", False)),
                        scene_type=result.get("scene_type", "talking_head"),
                    )
                    visual_timeline.append(signal)
        except Exception as e:
            # If a batch fails, skip it rather than crash the pipeline
            print(f"Visual batch {i} failed: {e}")

        time.sleep(GEMINI_RPM_DELAY)

    return {"visual_timeline": visual_timeline}
