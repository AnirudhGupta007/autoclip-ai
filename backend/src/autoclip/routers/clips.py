"""Clip CRUD, export, and download endpoints."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from autoclip.database import get_db
from autoclip.models import Clip, Video
from autoclip.schemas import ClipOut, ClipUpdate, ExportRequest
from autoclip.config import OUTPUT_DIR, EXPORT_FORMATS
from autoclip.services.video_processor import export_clip
from autoclip.services.clip_reprocess import apply_clip_update

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
    clip = await apply_clip_update(db, clip, video, update)
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
