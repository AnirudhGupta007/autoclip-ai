"""LangGraph pipeline graph — multimodal video analysis with conditional routing."""
import asyncio
import json
from pathlib import Path
from langgraph.graph import StateGraph, END

from autoclip.pipeline.state import PipelineState
from autoclip.pipeline.agents.classifier import classify_video
from autoclip.pipeline.agents.visual_agent import run_visual_agent
from autoclip.pipeline.agents.audio_agent import run_audio_agent
from autoclip.pipeline.agents.text_agent import run_text_agent
from autoclip.pipeline.agents.fusion import run_fusion
from autoclip.pipeline.agents.clip_selector import run_clip_selector
from autoclip.pipeline.agents.production import run_production
from autoclip.utils.ffmpeg import extract_audio
from autoclip.services.transcription import transcribe_audio
from autoclip.services.scene_detector import detect_scenes


# ─── Node wrappers ────────────────────────────────────────────

def transcription_node(state: PipelineState) -> dict:
    """Extract audio and transcribe with AssemblyAI."""
    video_path = state["video_path"]
    video_id = state["video_id"]

    output_dir = Path(f"outputs/{video_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_path = str(output_dir / "audio.wav")
    extract_audio(video_path, audio_path)

    transcript_data = transcribe_audio(audio_path)

    # Save transcript
    with open(output_dir / "transcript.json", "w") as f:
        json.dump(transcript_data, f, indent=2)

    return {"transcript_data": transcript_data}


def scene_detection_node(state: PipelineState) -> dict:
    """Detect scene boundaries."""
    video_path = state["video_path"]
    scenes = detect_scenes(video_path)
    boundaries = [s["start"] for s in scenes] + ([scenes[-1]["end"]] if scenes else [])
    return {"scene_boundaries": boundaries}


def classifier_node(state: PipelineState) -> dict:
    """Classify video type."""
    return classify_video(state)


def visual_node(state: PipelineState) -> dict:
    """Run visual analysis agent."""
    return run_visual_agent(state)


def audio_node(state: PipelineState) -> dict:
    """Run audio analysis agent."""
    return run_audio_agent(state)


def text_node(state: PipelineState) -> dict:
    """Run text analysis agent."""
    return run_text_agent(state)


def fusion_node(state: PipelineState) -> dict:
    """Run temporal fusion."""
    return run_fusion(state)


def selector_node(state: PipelineState) -> dict:
    """Run clip selector."""
    return run_clip_selector(state)


def production_node(state: PipelineState) -> dict:
    """Run clip production."""
    return run_production(state)


# ─── Conditional routing ──────────────────────────────────────

def should_skip_visual(state: PipelineState) -> str:
    """Skip visual agent for podcast-type videos (minimal visual change)."""
    video_type = state.get("video_type", "mixed")
    if video_type == "podcast":
        return "skip_visual"
    return "run_visual"


def check_analysis_done(state: PipelineState) -> str:
    """Check if we should proceed to fusion or if analysis already exists."""
    if state.get("analysis_complete"):
        return "already_analyzed"
    return "needs_analysis"


def after_fusion(state: PipelineState) -> str:
    """After fusion, check if we have moments or need to retry."""
    moment_map = state.get("moment_map", [])
    if not moment_map:
        return "no_moments"
    return "has_moments"


# ─── Build the graph ──────────────────────────────────────────

def build_analysis_graph() -> StateGraph:
    """
    Build the full analysis pipeline graph.

    Flow:
    transcription → scene_detection → classifier
        → [conditional] visual_agent (parallel with audio + text)
        → fusion → clip_selector → production
    """
    graph = StateGraph(PipelineState)

    # Add all nodes
    graph.add_node("transcription", transcription_node)
    graph.add_node("scene_detection", scene_detection_node)
    graph.add_node("classifier", classifier_node)
    graph.add_node("visual_agent", visual_node)
    graph.add_node("audio_agent", audio_node)
    graph.add_node("text_agent", text_node)
    graph.add_node("fusion", fusion_node)
    graph.add_node("clip_selector", selector_node)
    graph.add_node("production", production_node)

    # Entry: start with transcription
    graph.set_entry_point("transcription")

    # Transcription → scene detection
    graph.add_edge("transcription", "scene_detection")

    # Scene detection → classifier
    graph.add_edge("scene_detection", "classifier")

    # Classifier → conditional routing for visual agent
    graph.add_conditional_edges(
        "classifier",
        should_skip_visual,
        {
            "run_visual": "visual_agent",
            "skip_visual": "audio_agent",
        }
    )

    # Visual, Audio, Text agents → fusion
    # Visual agent runs, then audio and text run in sequence after
    # (LangGraph doesn't natively parallelize nodes, but we keep them as separate nodes
    #  for clear graph visualization and independent state updates)
    graph.add_edge("visual_agent", "audio_agent")
    graph.add_edge("audio_agent", "text_agent")
    graph.add_edge("text_agent", "fusion")

    # Fusion → conditional check
    graph.add_conditional_edges(
        "fusion",
        after_fusion,
        {
            "has_moments": "clip_selector",
            "no_moments": END,
        }
    )

    # Clip selector → production
    graph.add_edge("clip_selector", "production")

    # Production → END
    graph.add_edge("production", END)

    return graph


def build_generation_graph() -> StateGraph:
    """
    Build a lighter graph for re-generating clips from existing analysis.
    Skips analysis, goes straight to clip selection + production.
    """
    graph = StateGraph(PipelineState)

    graph.add_node("clip_selector", selector_node)
    graph.add_node("production", production_node)

    graph.set_entry_point("clip_selector")
    graph.add_edge("clip_selector", "production")
    graph.add_edge("production", END)

    return graph


# Compile graphs
analysis_pipeline = build_analysis_graph().compile()
generation_pipeline = build_generation_graph().compile()
