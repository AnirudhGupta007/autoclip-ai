from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class VideoOut(BaseModel):
    id: str
    filename: str
    duration: Optional[float] = None
    resolution: Optional[str] = None
    status: str
    created_at: datetime
    clips_count: int = 0

    model_config = {"from_attributes": True}


class ClipOut(BaseModel):
    id: str
    video_id: str
    title: Optional[str] = None
    start_time: float
    end_time: float
    duration: float
    file_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    transcript: Optional[str] = None
    scores: Optional[dict] = None
    overall_score: Optional[float] = None
    caption_style: str = "bold_pop"
    music_id: Optional[str] = None
    music_volume: float = 0.3
    exports: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClipUpdate(BaseModel):
    title: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    caption_style: Optional[str] = None
    music_id: Optional[str] = None
    music_url: Optional[str] = None
    music_volume: Optional[float] = None


class ExportRequest(BaseModel):
    format: str = "9:16"


class PipelineStatus(BaseModel):
    video_id: str
    status: str
    current_stage: Optional[int] = None
    stage_name: Optional[str] = None
    progress: int = 0
    message: str = ""
