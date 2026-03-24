"""LangGraph pipeline state definitions with Pydantic structured output."""
from typing import TypedDict, Optional, Annotated, Literal
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
import operator


# ─── Pydantic models for Gemini structured output ─────────────

class FrameAnalysis(BaseModel):
    """Structured output from Gemini Vision for a single frame."""
    energy: float = Field(ge=0.0, le=1.0, description="Visual dynamism 0-1")
    emotion: Literal["neutral", "happy", "surprised", "angry", "sad", "excited"] = "neutral"
    emotion_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    description: str = Field(max_length=100, default="")
    has_text_on_screen: bool = False
    scene_type: Literal["talking_head", "presentation", "broll", "audience"] = "talking_head"


class TranscriptSegment(BaseModel):
    """Structured output from Gemini for a transcript segment."""
    start_line: int
    end_line: int
    hook_type: Literal["hot_take", "story", "quote", "educational", "controversial", "emotional", "funny", "none"]
    hook_strength: float = Field(ge=0.0, le=1.0)
    topic: str = Field(max_length=50)
    is_complete: bool = True


class EngagementScores(BaseModel):
    """Structured output for clip engagement scoring."""
    hook: int = Field(ge=1, le=10)
    emotion: int = Field(ge=1, le=10)
    shareability: int = Field(ge=1, le=10)
    retention: int = Field(ge=1, le=10)
    controversy: int = Field(ge=1, le=10)
    novelty: int = Field(ge=1, le=10)


# ─── Signal dataclasses ──────────────────────────────────────

@dataclass
class VisualSignal:
    """A visual event detected in a video frame."""
    timestamp: float
    energy: float
    emotion: str
    emotion_confidence: float
    description: str
    has_text_on_screen: bool = False
    scene_type: str = "talking_head"


@dataclass
class AudioSignal:
    """An audio event detected in the audio track."""
    timestamp: float
    energy: float
    speech_pace: float
    event_type: str  # speech, laughter, applause, silence, music
    pitch_change: float
    rms_db: float = 0.0
    spectral_centroid: float = 0.0
    tempo_local: float = 0.0


@dataclass
class TextSegment:
    """A semantic text segment from transcript analysis."""
    start: float
    end: float
    text: str
    hook_type: str
    hook_strength: float
    topic: str
    is_complete: bool


@dataclass
class Moment:
    """A fused multimodal moment — the core output of analysis."""
    start: float
    end: float
    visual_energy: float
    audio_energy: float
    text_hook_strength: float
    convergence_score: float
    modalities_active: int
    style_tags: list[str]
    description: str
    transcript: str


@dataclass
class ClipConfig:
    """User-specified clip configuration."""
    moment: Optional[float] = None
    length: int = 30
    style: str = "any"
    frame: str = "9:16"
    caption_style: str = "bold_pop"


@dataclass
class ProducedClip:
    """A produced clip ready for download."""
    id: str
    title: str
    start_time: float
    end_time: float
    duration: float
    file_path: str
    thumbnail_path: Optional[str]
    transcript: str
    scores: dict
    overall_score: float
    frame: str
    style_tags: list[str]


# ─── LangGraph State ─────────────────────────────────────────
# Using Annotated with operator.add for list accumulation across nodes

def _replace(existing, new):
    """Reducer that replaces the old value with the new value."""
    return new


class PipelineState(TypedDict, total=False):
    """LangGraph state that flows through the pipeline graph.

    Uses annotated reducers so parallel nodes can independently
    append to list fields without overwriting each other.
    """
    # Video info
    video_id: str
    video_path: str
    video_type: Annotated[str, _replace]

    # Analysis outputs — use add reducer for parallel agent writes
    visual_timeline: Annotated[list[VisualSignal], operator.add]
    audio_timeline: Annotated[list[AudioSignal], operator.add]
    text_segments: Annotated[list[TextSegment], operator.add]
    scene_boundaries: Annotated[list[float], operator.add]

    # Fusion output
    moment_map: Annotated[list[Moment], _replace]

    # Transcript (shared across agents)
    transcript_data: Annotated[dict, _replace]

    # User request
    clip_configs: list[ClipConfig]

    # Produced clips
    clips: Annotated[list[ProducedClip], _replace]

    # Control flow
    needs_reanalysis: bool
    analysis_complete: Annotated[bool, _replace]
    error: Optional[str]
