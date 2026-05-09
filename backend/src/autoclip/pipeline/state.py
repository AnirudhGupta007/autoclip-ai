"""LangGraph pipeline state — chunk-parallel multimodal analysis."""
from typing import TypedDict, Optional, Annotated, Literal
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
import operator


# ─── Pydantic structured-output models ────────────────────────

class GeminiMoment(BaseModel):
    """A single high-engagement moment, returned by Gemini per chunk."""
    start: float = Field(description="Start time in seconds (relative to the full video)")
    end: float = Field(description="End time in seconds (relative to the full video)")
    description: str = Field(max_length=200, description="What happens in this moment")
    transcript: str = Field(max_length=1000, description="Verbatim transcript of speech in this window")
    style_tags: list[
        Literal[
            "hot_take", "story", "quote", "educational",
            "controversial", "emotional", "funny", "story_beat",
        ]
    ] = Field(default_factory=list, description="What kind of moment this is — 1-3 tags")
    visual_energy: float = Field(ge=0.0, le=1.0, description="Visual dynamism")
    audio_energy: float = Field(ge=0.0, le=1.0, description="Audio dynamism (laughter, applause, vocal pitch swings)")
    text_hook_strength: float = Field(ge=0.0, le=1.0, description="How strong this is as a verbal hook")
    convergence_score: float = Field(
        ge=0.0, le=1.0,
        description="Overall multimodal engagement — only set high (>0.7) when 2+ modalities co-fire",
    )


class ChunkAnalysis(BaseModel):
    """Gemini's structured response for one video chunk."""
    moments: list[GeminiMoment] = Field(
        default_factory=list,
        description="At most 5 moments per chunk — quality over quantity",
    )


class EngagementScores(BaseModel):
    """Per-clip engagement scoring."""
    hook: int = Field(ge=1, le=10)
    emotion: int = Field(ge=1, le=10)
    shareability: int = Field(ge=1, le=10)
    retention: int = Field(ge=1, le=10)
    controversy: int = Field(ge=1, le=10)
    novelty: int = Field(ge=1, le=10)


# ─── Internal dataclasses ────────────────────────────────────

@dataclass
class Moment:
    """A multimodal moment — output of chunk analysis + global fusion."""
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
    embedding: Optional[list[float]] = None  # populated in Phase 2.5


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


@dataclass
class ChunkPlan:
    """A planned chunk window — input to chunk_analyzer."""
    index: int
    start: float
    end: float
    video_path: str
    transcript_window: dict


# ─── LangGraph state ─────────────────────────────────────────

def _replace(existing, new):
    """Reducer that overwrites the old value."""
    return new


class PipelineState(TypedDict, total=False):
    """State that flows through the pipeline graph.

    Annotated reducers let parallel chunk workers append to `moment_map_raw`
    without conflicts. The post-fan-in `global_fusion` node consolidates them
    into the deduped `moment_map`.
    """
    # Video info
    video_id: str
    video_path: str
    video_duration: Annotated[float, _replace]
    video_type: Annotated[str, _replace]

    # Chunk planning
    chunk_plans: Annotated[list[ChunkPlan], _replace]

    # Per-chunk outputs — fan-in via operator.add reducer
    moment_map_raw: Annotated[list[Moment], operator.add]

    # Global fusion output
    moment_map: Annotated[list[Moment], _replace]

    # Transcript (whole video)
    transcript_data: Annotated[dict, _replace]

    # Scene cut timestamps (used by clip_selector for boundary snap)
    scene_boundaries: Annotated[list[float], _replace]

    # User request
    clip_configs: list[ClipConfig]

    # Produced clips
    clips: Annotated[list[ProducedClip], _replace]

    # Control flow
    needs_reanalysis: bool
    analysis_complete: Annotated[bool, _replace]
    error: Optional[str]
