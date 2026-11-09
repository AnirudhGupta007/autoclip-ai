from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from typing import Optional
from datetime import datetime

from autoclip.config import CAPTION_STYLES

MAX_CLIP_SECONDS = 180.0


class VideoOut(BaseModel):
    id: str
    filename: str
    duration: Optional[float] = None
    resolution: Optional[str] = None
    status: str
    created_at: datetime
    clips_count: int = 0
    source_url: Optional[str] = None  # ownership-checked /api/files/... URL
    media_kind: str = "video"         # "video" | "audio" (stored as an audiogram mp4)

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

    @computed_field
    @property
    def file_url(self) -> Optional[str]:
        from autoclip.utils.paths import public_url
        return public_url(self.file_path)

    @computed_field
    @property
    def thumbnail_url(self) -> Optional[str]:
        from autoclip.utils.paths import public_url
        return public_url(self.thumbnail_path)


class ClipUpdate(BaseModel):
    """Clip edit. Field-level checks here; checks that need the source video
    (end <= duration) and the clip's current values (end > start after
    merging a one-sided trim) run in services/clip_reprocess.validate_window."""
    title: Optional[str] = Field(default=None, max_length=200)
    start_time: Optional[float] = Field(default=None, ge=0)
    end_time: Optional[float] = Field(default=None, gt=0)
    caption_style: Optional[str] = None
    music_id: Optional[str] = None
    music_url: Optional[str] = None
    music_volume: Optional[float] = Field(default=None, ge=0, le=1)

    @field_validator("caption_style")
    @classmethod
    def _known_style(cls, v):
        if v is not None and v not in CAPTION_STYLES:
            raise ValueError(f"caption_style must be one of {CAPTION_STYLES}")
        return v

    @model_validator(mode="after")
    def _window(self):
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be greater than start_time")
            if self.end_time - self.start_time > MAX_CLIP_SECONDS:
                raise ValueError(f"clips can be at most {int(MAX_CLIP_SECONDS)} seconds long")
        return self


class ExportRequest(BaseModel):
    format: str = "9:16"


class PipelineStatus(BaseModel):
    video_id: str
    status: str
    current_stage: Optional[int] = None
    stage_name: Optional[str] = None
    progress: int = 0
    message: str = ""
