import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from autoclip.config import DATABASE_URL
from autoclip.database import Base

# pgvector when Postgres is available, JSON column otherwise — same model file works
# locally (sqlite) and on the deployed instance.
if DATABASE_URL.startswith("postgres"):
    try:
        from pgvector.sqlalchemy import Vector  # type: ignore
        from autoclip.services.embeddings import EMBEDDING_DIM
        _EmbeddingColumn = Vector(EMBEDDING_DIM)
    except Exception:
        _EmbeddingColumn = JSON
else:
    _EmbeddingColumn = JSON


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


class MomentRecord(Base):
    """A multimodal moment surfaced by chunk_analyzer + global_fusion.

    Stored separately from Clip because moments are the analysis primitive —
    a single video can yield many moments, and the user later picks/produces
    a subset of them as Clips. Embeddings power semantic moment search.
    """
    __tablename__ = "moments"

    id = Column(String, primary_key=True, default=generate_id)
    video_id = Column(String, ForeignKey("videos.id"), nullable=False, index=True)
    start = Column(Float, nullable=False)
    end = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    transcript = Column(Text, nullable=True)
    style_tags = Column(JSON, default=list)
    visual_energy = Column(Float, default=0.0)
    audio_energy = Column(Float, default=0.0)
    text_hook_strength = Column(Float, default=0.0)
    convergence_score = Column(Float, default=0.0)
    modalities_active = Column(Integer, default=0)
    embedding = Column(_EmbeddingColumn, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
