"""Clip CRUD, export, and download endpoints."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from autoclip.auth.deps import current_user, get_owned_clip, get_owned_video
from autoclip.database import get_db
from autoclip.models import Clip, User, Video
from autoclip.schemas import ClipOut, ClipUpdate, ExportRequest
from autoclip.config import OUTPUT_DIR, EXPORT_FORMATS
from autoclip.services.video_processor import export_clip
from autoclip.services.clip_reprocess import apply_clip_update, ClipUpdateError
from autoclip.utils.paths import public_url, resolve_path
from autoclip.routers.files import send_media

router = APIRouter(prefix="/api/clips", tags=["clips"], dependencies=[Depends(current_user)])


@router.get("", response_model=list[ClipOut])
def list_clips(video_id: str = None, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    """List the current user's clips, optionally filtered by video_id."""
    query = db.query(Clip).join(Video, Clip.video_id == Video.id).filter(Video.user_id == user.id)
    if video_id:
        get_owned_video(db, user, video_id)
        query = query.filter(Clip.video_id == video_id)
    clips = query.order_by(Clip.overall_score.desc()).all()
    return [ClipOut.model_validate(c) for c in clips]


@router.get("/{clip_id}", response_model=ClipOut)
def get_clip(clip_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Get clip details with scores."""
    clip = get_owned_clip(db, user, clip_id)
    return ClipOut.model_validate(clip)


@router.put("/{clip_id}", response_model=ClipOut)
async def update_clip(clip_id: str, update: ClipUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Update clip properties (trim, caption style, music)."""
    clip = get_owned_clip(db, user, clip_id)

    video = db.query(Video).filter(Video.id == clip.video_id).first()
    try:
        clip = await apply_clip_update(db, clip, video, update)
    except ClipUpdateError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    return ClipOut.model_validate(clip)


@router.post("/{clip_id}/export")
async def export_clip_format(clip_id: str, req: ExportRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Export clip in specified format (9:16, 1:1, 16:9)."""
    clip = get_owned_clip(db, user, clip_id)

    if req.format not in EXPORT_FORMATS:
        raise HTTPException(400, f"Invalid format. Choose from: {list(EXPORT_FORMATS.keys())}")

    src = resolve_path(clip.file_path)
    if not src or not src.exists():
        raise HTTPException(400, "Clip file not found")

    clip_dir = OUTPUT_DIR / clip.video_id / "clips" / clip.id / "exports"
    clip_dir.mkdir(parents=True, exist_ok=True)

    format_slug = req.format.replace(":", "x")
    output_path = str(clip_dir / f"{format_slug}.mp4")

    await asyncio.to_thread(export_clip, str(src), output_path, req.format)

    # Save export path (new dict so SQLAlchemy sees the JSON column change)
    clip.exports = {**(clip.exports or {}), req.format: output_path}
    db.commit()

    return {"format": req.format, "url": public_url(output_path),
            "download_url": f"/api/clips/{clip.id}/download/{req.format}", "message": "Export complete"}


@router.get("/{clip_id}/download/{format}")
def download_clip(clip_id: str, format: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Download an exported clip file."""
    clip = get_owned_clip(db, user, clip_id)

    # Check for exported format
    exports = clip.exports or {}
    file_path = exports.get(format)

    if not file_path:
        # Fall back to original clip
        if format == "original" and clip.file_path:
            file_path = clip.file_path
        else:
            raise HTTPException(404, f"Export for format '{format}' not found. Export it first.")

    resolved = resolve_path(file_path)
    if not resolved or not resolved.exists():
        raise HTTPException(404, "File not found on disk")
    filename = f"{clip.title or clip.id}_{format.replace(':', 'x')}.mp4"
    return send_media(resolved, filename=filename, media_type="video/mp4")
