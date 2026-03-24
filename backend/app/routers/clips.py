"""Clip CRUD, export, and download endpoints."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Clip, Video
from app.schemas import ClipOut, ClipUpdate, ExportRequest
from app.config import OUTPUT_DIR, EXPORT_FORMATS
from app.services.video_processor import export_clip
from app.services.caption_engine import generate_captions
from app.utils.ffmpeg import burn_captions

router = APIRouter(prefix="/api/clips", tags=["clips"])


@router.get("", response_model=list[ClipOut])
def list_clips(video_id: str = None, db: Session = Depends(get_db)):
    """List clips, optionally filtered by video_id."""
    query = db.query(Clip)
    if video_id:
        query = query.filter(Clip.video_id == video_id)
    clips = query.order_by(Clip.overall_score.desc()).all()
    return [ClipOut.model_validate(c) for c in clips]


@router.get("/{clip_id}", response_model=ClipOut)
def get_clip(clip_id: str, db: Session = Depends(get_db)):
    """Get clip details with scores."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")
    return ClipOut.model_validate(clip)


@router.put("/{clip_id}", response_model=ClipOut)
async def update_clip(clip_id: str, update: ClipUpdate, db: Session = Depends(get_db)):
    """Update clip properties (trim, caption style, music)."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")

    video = db.query(Video).filter(Video.id == clip.video_id).first()
    needs_reprocess = False

    if update.title is not None:
        clip.title = update.title

    if update.caption_style is not None and update.caption_style != clip.caption_style:
        clip.caption_style = update.caption_style
        needs_reprocess = True

    if update.start_time is not None or update.end_time is not None:
        if update.start_time is not None:
            clip.start_time = update.start_time
        if update.end_time is not None:
            clip.end_time = update.end_time
        clip.duration = round(clip.end_time - clip.start_time, 2)
        needs_reprocess = True

    if update.music_id is not None:
        clip.music_id = update.music_id
    if update.music_url is not None:
        clip.music_url = update.music_url
    if update.music_volume is not None:
        clip.music_volume = update.music_volume

    if needs_reprocess and video:
        clip_dir = OUTPUT_DIR / clip.video_id / "clips" / clip.id

        # Re-cut from source
        from app.services.video_processor import cut_clip
        raw_path = str(clip_dir / "raw.mp4")
        await asyncio.to_thread(
            cut_clip, video.file_path, raw_path,
            clip.start_time, clip.end_time
        )

        # Re-generate captions with new style
        import json
        transcript_file = OUTPUT_DIR / clip.video_id / "transcript.json"
        words = []
        if transcript_file.exists():
            with open(transcript_file) as f:
                transcript_data = json.load(f)
                words = transcript_data.get("words", [])

        if words:
            ass_path = str(clip_dir / "captions.ass")
            await asyncio.to_thread(
                generate_captions, words,
                clip.start_time, clip.end_time,
                clip.caption_style, ass_path
            )
            clip.caption_file = ass_path

            final_path = str(clip_dir / "final.mp4")
            try:
                await asyncio.to_thread(burn_captions, raw_path, ass_path, final_path)
            except Exception:
                import shutil
                shutil.copy2(raw_path, final_path)
            clip.file_path = final_path

    db.commit()
    db.refresh(clip)
    return ClipOut.model_validate(clip)


@router.post("/{clip_id}/export")
async def export_clip_format(clip_id: str, req: ExportRequest, db: Session = Depends(get_db)):
    """Export clip in specified format (9:16, 1:1, 16:9)."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")

    if req.format not in EXPORT_FORMATS:
        raise HTTPException(400, f"Invalid format. Choose from: {list(EXPORT_FORMATS.keys())}")

    if not clip.file_path or not Path(clip.file_path).exists():
        raise HTTPException(400, "Clip file not found")

    clip_dir = OUTPUT_DIR / clip.video_id / "clips" / clip.id / "exports"
    clip_dir.mkdir(parents=True, exist_ok=True)

    format_slug = req.format.replace(":", "x")
    output_path = str(clip_dir / f"{format_slug}.mp4")

    await asyncio.to_thread(export_clip, clip.file_path, output_path, req.format)

    # Save export path
    exports = clip.exports or {}
    exports[req.format] = output_path
    clip.exports = exports
    db.commit()

    return {"format": req.format, "path": output_path, "message": "Export complete"}


@router.get("/{clip_id}/download/{format}")
def download_clip(clip_id: str, format: str, db: Session = Depends(get_db)):
    """Download an exported clip file."""
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip:
        raise HTTPException(404, "Clip not found")

    # Check for exported format
    exports = clip.exports or {}
    file_path = exports.get(format)

    if not file_path:
        # Fall back to original clip
        if format == "original" and clip.file_path:
            file_path = clip.file_path
        else:
            raise HTTPException(404, f"Export for format '{format}' not found. Export it first.")

    if not Path(file_path).exists():
        raise HTTPException(404, "File not found on disk")

    filename = f"{clip.title or clip.id}_{format.replace(':', 'x')}.mp4"
    return FileResponse(file_path, filename=filename, media_type="video/mp4")
