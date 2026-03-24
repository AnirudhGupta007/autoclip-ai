"""Thumbnail generation from video clips."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app.utils.ffmpeg import extract_frame


def generate_thumbnail(
    video_path: str,
    output_path: str,
    title: str = "",
    timestamp: float = None,
) -> str:
    """
    Generate a thumbnail from a video clip.
    Extracts a frame and optionally overlays title text.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Extract frame at 1/3 of the way through (usually more interesting than first frame)
    if timestamp is None:
        from app.utils.ffmpeg import get_video_info
        info = get_video_info(video_path)
        timestamp = info["duration"] / 3

    frame_path = output_path.replace(".jpg", "_frame.jpg")
    extract_frame(video_path, timestamp, frame_path)

    img = Image.open(frame_path)

    if title:
        draw = ImageDraw.Draw(img)
        w, h = img.size

        # Try to use a nice font, fall back to default
        font_size = max(24, h // 15)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

        # Draw text with shadow at bottom
        text_y = h - font_size - 40
        # Shadow
        draw.text((22, text_y + 2), title, fill="black", font=font)
        # Main text
        draw.text((20, text_y), title, fill="white", font=font)

    img.save(output_path, "JPEG", quality=85)

    # Clean up temp frame
    frame_file = Path(frame_path)
    if frame_file.exists() and frame_path != output_path:
        frame_file.unlink()

    return output_path
