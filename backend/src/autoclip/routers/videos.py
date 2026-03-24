"""Video upload, list, and delete endpoints."""
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from autoclip.database import get_db
from autoclip.models import Video, generate_id
from autoclip.schemas import VideoOut
from autoclip.config import UPLOAD_DIR, MAX_UPLOAD_SIZE, OUTPUT_DIR
from autoclip.utils.ffmpeg import get_video_info

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post("/upload", response_model=VideoOut)
async def upload_video(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a video file."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        raise HTTPException(400, f"Unsupported format: {ext}")

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

    video = Video(
        id=video_id,
        filename=file.filename,
        file_path=str(file_path),
        duration=info.get("duration"),
        resolution=info.get("resolution"),
        status="uploaded",
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    return VideoOut(
        id=video.id,
        filename=video.filename,
        duration=video.duration,
        resolution=video.resolution,
        status=video.status,
        created_at=video.created_at,
        clips_count=0,
    )


@router.get("", response_model=list[VideoOut])
def list_videos(db: Session = Depends(get_db)):
    """List all uploaded videos."""
    videos = db.query(Video).order_by(Video.created_at.desc()).all()
    result = []
    for v in videos:
        result.append(VideoOut(
            id=v.id,
            filename=v.filename,
            duration=v.duration,
            resolution=v.resolution,
            status=v.status,
            created_at=v.created_at,
            clips_count=len(v.clips),
        ))
    return result


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: str, db: Session = Depends(get_db)):
    """Get video details."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")
    return VideoOut(
        id=video.id,
        filename=video.filename,
        duration=video.duration,
        resolution=video.resolution,
        status=video.status,
        created_at=video.created_at,
        clips_count=len(video.clips),
    )


@router.delete("/{video_id}")
def delete_video(video_id: str, db: Session = Depends(get_db)):
    """Delete video and all associated clips."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")

    # Delete files
    upload_dir = UPLOAD_DIR / video_id
    output_dir = OUTPUT_DIR / video_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)

    db.delete(video)
    db.commit()
    return {"message": "Video deleted"}
