"""Video classifier node — determines video type for conditional routing."""
import base64
from pathlib import Path
from google import genai
from app.config import GEMINI_API_KEY
from app.utils.ffmpeg import extract_frame
from app.pipeline.state import PipelineState


def classify_video(state: PipelineState) -> dict:
    """
    Sample a few frames and classify the video type.
    Routes to appropriate agents based on content type.
    """
    video_path = state["video_path"]
    video_id = state["video_id"]
    output_dir = Path(f"outputs/{video_id}/classify")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sample 3 frames: beginning, middle, end
    transcript_data = state.get("transcript_data", {})
    duration = transcript_data.get("duration", 60)
    sample_times = [5, duration * 0.5, max(duration - 5, 10)]

    frame_paths = []
    for i, t in enumerate(sample_times):
        fp = str(output_dir / f"classify_{i}.jpg")
        try:
            extract_frame(video_path, t, fp)
            frame_paths.append(fp)
        except Exception:
            continue

    if not frame_paths:
        return {"video_type": "mixed"}

    # Send frames to Gemini Vision
    client = genai.Client(api_key=GEMINI_API_KEY)
    contents = [
        "Classify this video into exactly ONE category based on these sample frames:\n"
        "- talking_head: A person speaking to camera, interview, or conversation\n"
        "- presentation: Slides, screen share, whiteboard, lecture\n"
        "- podcast: Multiple speakers, studio setup, minimal visual changes\n"
        "- mixed: Combination of styles, b-roll heavy, documentary\n\n"
        "Return ONLY the category name, nothing else."
    ]

    for fp in frame_paths:
        with open(fp, "rb") as f:
            image_data = f.read()
        contents.append(genai.types.Part.from_bytes(data=image_data, mime_type="image/jpeg"))

    response = client.models.generate_content(model="gemini-2.0-flash", contents=contents)
    video_type = response.text.strip().lower().replace(" ", "_")

    valid_types = {"talking_head", "presentation", "podcast", "mixed"}
    if video_type not in valid_types:
        video_type = "mixed"

    return {"video_type": video_type}
