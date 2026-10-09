"""Video upload, list, and delete endpoints."""
import logging
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from autoclip.auth import settings as auth_settings
from autoclip.auth.deps import current_user, get_owned_video, require_not_demo
from autoclip.database import get_db
from autoclip.models import User, Video, generate_id
from autoclip.schemas import VideoOut
from autoclip.config import UPLOAD_DIR, MAX_UPLOAD_SIZE, OUTPUT_DIR
from autoclip.utils.ffmpeg import get_video_info

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["videos"], dependencies=[Depends(current_user)])


def _video_out(v: Video, clips_count: int) -> VideoOut:
    from autoclip.utils.paths import public_url
    return VideoOut(id=v.id, filename=v.filename, duration=v.duration, resolution=v.resolution,
                    status=v.status, created_at=v.created_at, clips_count=clips_count,
                    source_url=public_url(v.file_path))


@router.post("/upload", response_model=VideoOut)
async def upload_video(file: UploadFile = File(...), db: Session = Depends(get_db),
                       user: User = Depends(require_not_demo)):
    """Upload a video file (non-admins: at most MAX_VIDEOS_PER_USER stored
    videos, each at most MAX_VIDEO_MINUTES_DEMO long)."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        raise HTTPException(400, f"Unsupported format: {ext}")

    if not user.is_admin:
        owned = db.query(Video).filter(Video.user_id == user.id).count()
        if owned >= auth_settings.MAX_VIDEOS_PER_USER:
            raise HTTPException(409, (f"You can keep up to {auth_settings.MAX_VIDEOS_PER_USER} videos. "
                                      "Delete one in your Library to upload another."))

    video_id = generate_id()
    video_dir = UPLOAD_DIR / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    file_path = video_dir / f"source{ext}"

    # Save uploaded file
    size = 0
    with open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                f.close()
                shutil.rmtree(video_dir)
                raise HTTPException(413, "File too large (max 500MB)")
            f.write(chunk)

    # Get video metadata
    try:
        info = get_video_info(str(file_path))
    except Exception:
        info = {"duration": None, "resolution": None}

    max_minutes = auth_settings.MAX_VIDEO_MINUTES_DEMO
    if not user.is_admin and max_minutes > 0:
        duration = info.get("duration")
        if duration is None or duration > max_minutes * 60:
            shutil.rmtree(video_dir, ignore_errors=True)
            raise HTTPException(413, (f"Videos can be at most {max_minutes} minutes long on this account."
                                      if duration else "Couldn't read this video's duration."))

    video = Video(
        id=video_id,
        filename=file.filename,
        file_path=str(file_path),
        duration=info.get("duration"),
        resolution=info.get("resolution"),
        status="uploaded",
        user_id=user.id,
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    return _video_out(video, 0)


@router.get("", response_model=list[VideoOut])
def list_videos(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """List the current user's videos (status normalised like the chat API)."""
    from autoclip.utils import analysis_jobs
    videos = (db.query(Video).filter(Video.user_id == user.id)
              .order_by(Video.created_at.desc()).all())
    out = []
    for v in videos:
        item = _video_out(v, len(v.clips))
        item.status = analysis_jobs.video_state(v.id).get("status", v.status)
        out.append(item)
    return out


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Get video details."""
    video = get_owned_video(db, user, video_id)
    return _video_out(video, len(video.clips))


@router.delete("/{video_id}")
def delete_video(video_id: str, db: Session = Depends(get_db), user: User = Depends(require_not_demo)):
    """Delete a video, its clips, moments and RAG vectors, then its files.

    DB rows go first (one transaction) and files only after the commit: the
    old order removed the files and then failed on the moments FK, leaving a
    DB row pointing at nothing.
    """
    from autoclip.models import Clip
    from autoclip.services.moment_store import delete_moments
    from autoclip.utils import analysis_jobs

    video = get_owned_video(db, user, video_id)
    if analysis_jobs.is_running(video_id):
        raise HTTPException(409, "This video is still being analysed — try again when it finishes.")

    try:
        delete_moments(db, video_id)  # moments table + data_moment_nodes vectors
        db.query(Clip).filter(Clip.video_id == video_id).delete(synchronize_session=False)
        db.delete(video)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("delete_video failed for %s", video_id)
        raise HTTPException(500, "Could not delete the video. Nothing was removed.")

    for d in (UPLOAD_DIR / video_id, OUTPUT_DIR / video_id):
        shutil.rmtree(d, ignore_errors=True)
    return {"message": "Video deleted"}
