"""LangGraph pipeline state definitions."""
from typing import TypedDict, Optional
from dataclasses import dataclass, field


@dataclass
class VisualSignal:
    """A visual event detected in a video frame."""
    timestamp: float
    energy: float           # 0-1, how visually dynamic
    emotion: str            # neutral, happy, surprised, angry, sad
    emotion_confidence: float
    description: str        # what's happening visually
    has_text_on_screen: bool = False
    scene_type: str = "talking_head"  # talking_head, presentation, broll, audience


@dataclass
class AudioSignal:
    """An audio event detected in the audio track."""
    timestamp: float
    energy: float           # 0-1, volume/amplitude
    speech_pace: float      # words per minute estimate
    event_type: str         # speech, laughter, applause, silence, music
    pitch_change: float     # 0-1, how much pitch changed vs baseline


@dataclass
class TextSegment:
    """A semantic text segment from transcript analysis."""
    start: float
    end: float
    text: str
    hook_type: str          # hot_take, story, quote, educational, controversial, emotional, none
    hook_strength: float    # 0-1
    topic: str              # brief topic label
    is_complete: bool       # does it form a complete thought?


@dataclass
class Moment:
    """A fused multimodal moment — the core output of analysis."""
    start: float
    end: float
    visual_energy: float
    audio_energy: float
    text_hook_strength: float
    convergence_score: float    # how many modalities agree this is interesting
    style_tags: list[str]       # funny, dramatic, educational, motivational, controversial
    description: str
    transcript: str


@dataclass
class ClipConfig:
    """User-specified clip configuration."""
    moment: Optional[float] = None  # None = auto-select
    length: int = 30                # seconds
    style: str = "any"              # funny, dramatic, educational, motivational, controversial, any
    frame: str = "9:16"             # 9:16, 1:1, 16:9
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


class PipelineState(TypedDict, total=False):
    """LangGraph state that flows through the pipeline."""
    # Video info
    video_id: str
    video_path: str
    video_type: str  # talking_head, presentation, podcast, mixed

    # Analysis outputs (computed once, reused)
    visual_timeline: list[VisualSignal]
    audio_timeline: list[AudioSignal]
    text_segments: list[TextSegment]
    moment_map: list[Moment]
    scene_boundaries: list[float]
    transcript_data: dict  # raw transcript from AssemblyAI

    # User request
    clip_configs: list[ClipConfig]

    # Produced clips
    clips: list[ProducedClip]

    # Control flow
    needs_reanalysis: bool
    analysis_complete: bool
    error: Optional[str]

    # SSE progress reporting
    progress_callback: Optional[object]
