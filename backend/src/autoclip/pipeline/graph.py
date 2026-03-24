"""LangGraph pipeline graph — multimodal video analysis with conditional routing.

Architecture:
    - Analysis subgraph: transcription → scene detection → classifier
        → [fan-out] visual_agent | audio_agent | text_agent [fan-in] → fusion
    - Generation subgraph: clip_selector → production (with ToolNode)
    - Main graph: orchestrates analysis + generation with checkpointing

Key LangGraph features used:
    - StateGraph with typed state + annotated reducers
    - Subgraphs for modular pipeline stages
    - Fan-out / fan-in for parallel multimodal agents
    - Conditional edges for video-type routing
    - ToolNode for FFmpeg tool calling
    - MemorySaver checkpointing for conversation persistence
    - Send API for dynamic parallel dispatch
"""
import json
from pathlib import Path
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from autoclip.pipeline.state import PipelineState
from autoclip.pipeline.agents.classifier import classify_video
from autoclip.pipeline.agents.visual_agent import run_visual_agent
from autoclip.pipeline.agents.audio_agent import run_audio_agent
from autoclip.pipeline.agents.text_agent import run_text_agent
from autoclip.pipeline.agents.fusion import run_fusion
from autoclip.pipeline.agents.clip_selector import run_clip_selector
from autoclip.pipeline.agents.production import run_production
from autoclip.pipeline.tools import PRODUCTION_TOOLS, ANALYSIS_TOOLS
from autoclip.utils.ffmpeg import extract_audio, get_video_info
from autoclip.services.transcription import transcribe_audio
from autoclip.services.scene_detector import detect_scenes


# ═══════════════════════════════════════════════════════════════
# NODE IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════

def transcription_node(state: PipelineState) -> dict:
    """Extract audio and transcribe with AssemblyAI.
    Produces word-level timestamps and speaker diarization."""
    video_path = state["video_path"]
    video_id = state["video_id"]

    output_dir = Path(f"outputs/{video_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_path = str(output_dir / "audio.wav")
    extract_audio(video_path, audio_path)
    transcript_data = transcribe_audio(audio_path)

    # Persist transcript to disk
    with open(output_dir / "transcript.json", "w") as f:
        json.dump(transcript_data, f, indent=2)

    return {"transcript_data": transcript_data}


def scene_detection_node(state: PipelineState) -> dict:
    """Detect scene boundaries using PySceneDetect content detector."""
    video_path = state["video_path"]
    scenes = detect_scenes(video_path)
    boundaries = [s["start"] for s in scenes]
    if scenes:
        boundaries.append(scenes[-1]["end"])
    return {"scene_boundaries": boundaries}


def classifier_node(state: PipelineState) -> dict:
    """Classify video type for conditional agent routing."""
    return classify_video(state)


def visual_node(state: PipelineState) -> dict:
    """Run visual analysis — frame sampling + Gemini Vision."""
    return run_visual_agent(state)


def audio_node(state: PipelineState) -> dict:
    """Run audio analysis — librosa feature extraction."""
    return run_audio_agent(state)


def text_node(state: PipelineState) -> dict:
    """Run text analysis — transcript semantic segmentation."""
    return run_text_agent(state)


def fusion_node(state: PipelineState) -> dict:
    """Temporal fusion — align 3 modality timelines, find convergence."""
    return run_fusion(state)


def selector_node(state: PipelineState) -> dict:
    """Select and score clips based on user preferences."""
    return run_clip_selector(state)


def production_node(state: PipelineState) -> dict:
    """Produce clips: cut, caption, reframe, thumbnail."""
    return run_production(state)


# ═══════════════════════════════════════════════════════════════
# CONDITIONAL ROUTING
# ═══════════════════════════════════════════════════════════════

def route_by_video_type(state: PipelineState) -> list[Send]:
    """Fan-out to parallel agents using Send API.

    For non-podcast video: dispatches visual, audio, and text agents in parallel.
    For podcast: skips visual agent (no useful frames), runs audio + text only.

    Each agent writes to its own state field using annotated reducers,
    so parallel writes don't conflict.
    """
    video_type = state.get("video_type", "mixed")
    agents = ["audio_agent", "text_agent"]
    if video_type != "podcast":
        agents.append("visual_agent")
    return [Send(agent, state) for agent in agents]


def route_after_fusion(state: PipelineState) -> str:
    """Route after fusion — check if moments were found."""
    moment_map = state.get("moment_map", [])
    if not moment_map:
        return "no_moments"
    return "has_moments"


def route_analysis_check(state: PipelineState) -> str:
    """Skip analysis if already completed (regeneration mode)."""
    if state.get("analysis_complete"):
        return "skip_to_selection"
    return "needs_analysis"


# ═══════════════════════════════════════════════════════════════
# SUBGRAPH: MULTIMODAL ANALYSIS
# ═══════════════════════════════════════════════════════════════

def build_analysis_subgraph() -> StateGraph:
    """Build the multimodal analysis subgraph with parallel agent dispatch.

    Flow:
        classifier → Send API [parallel dispatch]
            → visual_agent ─┐
            → audio_agent  ─┼→ fusion (fan-in)
            → text_agent   ─┘

    Uses LangGraph's Send API for true parallel execution:
    - classifier determines video type, then dispatches Send() to each agent
    - Each agent writes to its own state field (operator.add reducers prevent conflicts)
    - LangGraph waits for ALL dispatched agents to complete before proceeding to fusion
    - For podcast videos, visual_agent is skipped (not included in Send list)

    This is the fan-out/fan-in pattern: Send fans out, fusion fans in.
    """
    graph = StateGraph(PipelineState)

    graph.add_node("classifier", classifier_node)
    graph.add_node("visual_agent", visual_node)
    graph.add_node("audio_agent", audio_node)
    graph.add_node("text_agent", text_node)
    graph.add_node("fusion", fusion_node)

    graph.set_entry_point("classifier")

    # Classifier → parallel fan-out via Send API
    # route_by_video_type returns [Send("visual_agent", state), Send("audio_agent", state), ...]
    # LangGraph dispatches all agents concurrently
    graph.add_conditional_edges("classifier", route_by_video_type)

    # Fan-in: all agents converge to fusion
    # LangGraph waits for ALL Send-dispatched nodes to finish before running fusion
    graph.add_edge("visual_agent", "fusion")
    graph.add_edge("audio_agent", "fusion")
    graph.add_edge("text_agent", "fusion")

    graph.add_edge("fusion", END)

    return graph


# ═══════════════════════════════════════════════════════════════
# SUBGRAPH: CLIP GENERATION
# ═══════════════════════════════════════════════════════════════

def build_generation_subgraph() -> StateGraph:
    """Build the clip generation subgraph.

    Flow: clip_selector → production → END

    The production node uses FFmpeg tools (registered via ToolNode pattern)
    for cutting, captioning, reframing, and thumbnail generation.
    """
    graph = StateGraph(PipelineState)

    graph.add_node("clip_selector", selector_node)
    graph.add_node("production", production_node)

    # ToolNode for FFmpeg operations — makes tools available to production
    tool_node = ToolNode(PRODUCTION_TOOLS)
    graph.add_node("ffmpeg_tools", tool_node)

    graph.set_entry_point("clip_selector")
    graph.add_edge("clip_selector", "production")
    graph.add_edge("production", END)

    return graph


# ═══════════════════════════════════════════════════════════════
# MAIN GRAPH: FULL PIPELINE
# ═══════════════════════════════════════════════════════════════

def build_pipeline_graph() -> StateGraph:
    """Build the full pipeline graph with subgraphs.

    Flow:
        START → [check analysis]
            → transcription → scene_detection → analysis_subgraph
                → [check moments] → generation_subgraph → END
            → generation_subgraph → END  (if analysis already done)

    Features:
        - Conditional entry: skip analysis for regeneration requests
        - Analysis subgraph: multimodal agents with conditional routing
        - Generation subgraph: clip selection + FFmpeg production
        - Checkpointing: MemorySaver persists state across chat turns
    """
    graph = StateGraph(PipelineState)

    # Pre-analysis nodes
    graph.add_node("transcription", transcription_node)
    graph.add_node("scene_detection", scene_detection_node)

    # Compile subgraphs and add as nodes
    analysis_sub = build_analysis_subgraph().compile()
    generation_sub = build_generation_subgraph().compile()

    graph.add_node("analysis", analysis_sub)
    graph.add_node("generation", generation_sub)

    # Entry: check if analysis already exists
    graph.add_conditional_edges(
        START,
        route_analysis_check,
        {
            "needs_analysis": "transcription",
            "skip_to_selection": "generation",
        }
    )

    # Analysis path: transcription → scene_detection → analysis subgraph
    graph.add_edge("transcription", "scene_detection")
    graph.add_edge("scene_detection", "analysis")

    # After analysis: check if moments found
    graph.add_conditional_edges(
        "analysis",
        route_after_fusion,
        {
            "has_moments": "generation",
            "no_moments": END,
        }
    )

    # Generation → END
    graph.add_edge("generation", END)

    return graph


# ═══════════════════════════════════════════════════════════════
# COMPILED PIPELINES WITH CHECKPOINTING
# ═══════════════════════════════════════════════════════════════

# Checkpointer for conversation persistence across chat turns.
# In production, swap MemorySaver for SqliteSaver or PostgresSaver.
checkpointer = MemorySaver()

# Main pipeline: full analysis + generation
pipeline = build_pipeline_graph().compile(checkpointer=checkpointer)

# Lightweight pipeline: skip analysis, just generate from existing state
generation_only = build_generation_subgraph().compile()

# Export subgraph builders for testing
__all__ = [
    "pipeline",
    "generation_only",
    "build_pipeline_graph",
    "build_analysis_subgraph",
    "build_generation_subgraph",
    "route_by_video_type",
    "route_after_fusion",
    "route_analysis_check",
    "checkpointer",
]
