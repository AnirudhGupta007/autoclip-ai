"""Video processing: cutting clips and auto-reframing."""
import cv2
import numpy as np
from pathlib import Path
from app.utils.ffmpeg import cut_video, reframe_video, get_video_info
from app.config import EXPORT_FORMATS


face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


def detect_face_position(video_path: str, sample_count: int = 5) -> int:
    """
    Detect dominant face x-position by sampling frames.
    Returns crop x-offset for portrait reframe, or -1 if no face found.
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames == 0:
        cap.release()
        return -1

    face_positions = []
    sample_indices = np.linspace(0, total_frames - 1, sample_count, dtype=int)

    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        if len(faces) > 0:
            # Take the largest face
            areas = [w * h for (x, y, w, h) in faces]
            largest = faces[np.argmax(areas)]
            fx, _, fw, _ = largest
            face_center_x = fx + fw // 2
            face_positions.append(face_center_x)

    cap.release()

    if not face_positions:
        return -1

    avg_x = int(np.mean(face_positions))
    info = get_video_info(video_path)
    src_w, src_h = info["width"], info["height"]
    target_ratio = 9 / 16
    crop_w = int(src_h * target_ratio)
    crop_x = avg_x - crop_w // 2
    crop_x = max(0, min(crop_x, src_w - crop_w))

    return crop_x


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

    crop_x = -1
    if format_key == "9:16":
        crop_x = detect_face_position(clip_path)

    return reframe_video(
        clip_path, output_path,
        fmt["width"], fmt["height"],
        crop_x=crop_x
    )
