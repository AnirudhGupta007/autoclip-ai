"""Pipeline processing endpoint with SSE progress streaming."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from autoclip.database import get_db
from autoclip.models import Video
from autoclip.schemas import PipelineStatus
from autoclip.pipeline.orchestrator import run_pipeline

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/process/{video_id}")
async def process_video(video_id: str, db: Session = Depends(get_db)):
    """
    Start processing a video through the AI clipping pipeline.
    Returns an SSE stream with progress updates.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")

    if video.status == "processing":
        raise HTTPException(409, "Video is already being processed")

    if video.status == "completed":
        raise HTTPException(409, "Video has already been processed")

    async def event_generator():
        async for event in run_pipeline(video_id):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status/{video_id}", response_model=PipelineStatus)
def get_status(video_id: str, db: Session = Depends(get_db)):
    """Get the current processing status of a video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")

    return PipelineStatus(
        video_id=video.id,
        status=video.status,
        message=f"Status: {video.status}",
    )
