import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, Text, ForeignKey, DateTime, JSON, Boolean, false
from sqlalchemy.orm import relationship
from autoclip.config import DATABASE_URL
from autoclip.database import Base

# pgvector when Postgres is available, JSON column otherwise — same model file works
# locally (sqlite) and on the deployed instance.
if DATABASE_URL.startswith("postgres"):
    try:
        from pgvector.sqlalchemy import Vector  # type: ignore
        from autoclip.config import EMBEDDING_DIM
        _EmbeddingColumn = Vector(EMBEDDING_DIM)
    except Exception:
        _EmbeddingColumn = JSON
else:
    _EmbeddingColumn = JSON


def generate_id():
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    """Naive UTC — the existing columns are TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(320), nullable=False, unique=True, index=True)  # stored lower-cased
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    is_demo = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)

    videos = relationship("Video", back_populates="owner")


class AuthSession(Base):
    """A login session. Only sha256(token) is stored — a DB leak doesn't
    hand out live cookies."""
    __tablename__ = "sessions"

    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)

    user = relationship("User")


class Video(Base):
    __tablename__ = "videos"

    id = Column(String, primary_key=True, default=generate_id)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    duration = Column(Float, nullable=True)
    resolution = Column(String, nullable=True)
    # uploaded -> analyzing -> analyzed | failed  (background job: utils/analysis_jobs.py;
    # legacy rows may still say "completed"/"processing" — normalised there)
    status = Column(String, default="uploaded")
    # "video" | "audio" — audio uploads are stored as an audiogram mp4
    # (services/audiogram.py) and analysed from the transcript only.
    media_kind = Column(String, nullable=False, default="video", server_default="video")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Owner. Nullable only at the DB level (migration 0002 back-fills legacy
    # rows); every code path that creates a Video sets it.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    owner = relationship("User", back_populates="videos")
    clips = relationship("Clip", back_populates="video", cascade="all, delete-orphan")


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String, primary_key=True, default=generate_id)
    video_id = Column(String, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
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
    # ondelete only affects freshly created schemas; existing DBs rely on the
    # explicit delete in routers/videos.delete_video.
    video_id = Column(String, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
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
    categories = Column(JSON, nullable=True)   # moment_tagger.CATEGORIES (None = not tagged yet)
    why = Column(Text, nullable=True)          # one-line "why it works"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Conversation(Base):
    """One chat in the Studio sidebar. Its LangGraph thread is
    `u:{user_id}:c:{id}` (routers/chat.chat_thread_id)."""
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=generate_id)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # SET NULL: deleting a video keeps the conversation (and its messages).
    video_id = Column(String, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(200), nullable=False, default="", server_default="")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(16), nullable=False)        # "user" | "assistant"
    content = Column(Text, nullable=False, default="")
    clips_json = Column(JSON, nullable=True)          # clip dicts as the chat API returned them
    pending = Column(Boolean, nullable=False, default=False, server_default=false())
    created_at = Column(DateTime, default=utcnow)
