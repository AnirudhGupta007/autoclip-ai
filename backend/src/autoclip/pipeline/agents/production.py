"""Production node — cuts, captions, reframes, and exports clips."""
import shutil
from pathlib import Path
from autoclip.config import OUTPUT_DIR, EXPORT_FORMATS
from autoclip.utils.ffmpeg import cut_video, burn_captions, reframe_video, extract_frame
from autoclip.services.caption_engine import generate_captions
from autoclip.services.video_processor import detect_face_position
from autoclip.services.thumbnail_gen import generate_thumbnail
from autoclip.pipeline.state import PipelineState, ProducedClip


def run_production(state: PipelineState) -> dict:
    """
    Produce all clips: cut video, generate captions, burn them,
    reframe to target aspect ratio, and generate thumbnails.
    """
    video_path = state["video_path"]
    video_id = state["video_id"]
    clips = state.get("clips", [])
    transcript_data = state.get("transcript_data", {})
    words = transcript_data.get("words", [])

    produced_clips = []

    for clip in clips:
        clip_dir = Path(f"outputs/{video_id}/clips/{clip.id}")
        clip_dir.mkdir(parents=True, exist_ok=True)

        # 1. Cut raw segment
        raw_path = str(clip_dir / "raw.mp4")
        try:
            cut_video(video_path, raw_path, clip.start_time, clip.end_time)
        except Exception as e:
            print(f"Failed to cut clip {clip.id}: {e}")
            continue

        # 2. Generate captions
        ass_path = str(clip_dir / "captions.ass")
        try:
            generate_captions(
                words, clip.start_time, clip.end_time,
                "bold_pop", ass_path
            )
        except Exception:
            ass_path = None

        # 3. Burn captions onto video
        captioned_path = str(clip_dir / "captioned.mp4")
        if ass_path:
            try:
                burn_captions(raw_path, ass_path, captioned_path)
            except Exception:
                shutil.copy2(raw_path, captioned_path)
        else:
            shutil.copy2(raw_path, captioned_path)

        # 4. Reframe to target aspect ratio
        final_path = str(clip_dir / "final.mp4")
        fmt = EXPORT_FORMATS.get(clip.frame)
        if fmt and clip.frame != "16:9":
            try:
                crop_x = -1
                if clip.frame == "9:16":
                    crop_x = detect_face_position(captioned_path)
                reframe_video(
                    captioned_path, final_path,
                    fmt["width"], fmt["height"],
                    crop_x=crop_x
                )
            except Exception:
                shutil.copy2(captioned_path, final_path)
        else:
            shutil.copy2(captioned_path, final_path)

        # 5. Generate thumbnail
        thumb_path = str(clip_dir / "thumbnail.jpg")
        try:
            generate_thumbnail(final_path, thumb_path, clip.title)
        except Exception:
            thumb_path = None

        # Update clip with file paths
        produced_clip = ProducedClip(
            id=clip.id,
            title=clip.title,
            start_time=clip.start_time,
            end_time=clip.end_time,
            duration=clip.duration,
            file_path=final_path,
            thumbnail_path=thumb_path,
            transcript=clip.transcript,
            scores=clip.scores,
            overall_score=clip.overall_score,
            frame=clip.frame,
            style_tags=clip.style_tags,
        )
        produced_clips.append(produced_clip)

    return {"clips": produced_clips}
