import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from autoclip.database import Base


def generate_id():
    return uuid.uuid4().hex[:12]


class Video(Base):
    __tablename__ = "videos"

    id = Column(String, primary_key=True, default=generate_id)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    duration = Column(Float, nullable=True)
    resolution = Column(String, nullable=True)
    status = Column(String, default="uploaded")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    clips = relationship("Clip", back_populates="video", cascade="all, delete-orphan")


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String, primary_key=True, default=generate_id)
    video_id = Column(String, ForeignKey("videos.id"), nullable=False)
    title = Column(String, nullable=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    file_path = Column(String, nullable=True)
    thumbnail_path = Column(String, nullable=True)
    transcript = Column(Text, nullable=True)
    scores = Column(JSON, nullable=True)
    overall_score = Column(Float, nullable=True)
    caption_style = Column(String, default="bold_pop")
    caption_file = Column(String, nullable=True)
    music_id = Column(String, nullable=True)
    music_url = Column(String, nullable=True)
    music_volume = Column(Float, default=0.3)
    exports = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    video = relationship("Video", back_populates="clips")
