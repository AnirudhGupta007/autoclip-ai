"""LangGraph pipeline graph — chunk-parallel multimodal analysis.

V2 Architecture:
    transcription → scene_detection → chunk_planner
        ──Send API fan-out──▶ chunk_analyzer (×N parallel) ──fan-in──▶ global_fusion
        ──▶ generation subgraph (clip_selector → production)

Key LangGraph primitives used:
    • Send API for parallel fan-out over time chunks (NOT modalities) — V2's central flex
    • Compiled subgraphs (analysis + generation) reused as nodes
    • Annotated state reducers (`operator.add`) for safe parallel writes
    • Conditional entry edge for "skip analysis when regenerating clips"
    • Postgres checkpointer (env-toggle) for resumable runs and chat threads
"""
from __future__ import annotations
import os
import json
import logging
from pathlib import Path

from langgraph.graph import StateGraph, END, START
from langgraph.types import Send
from langgraph.checkpoint.memory import MemorySaver

from autoclip.pipeline.state import PipelineState, ChunkPlan
from autoclip.pipeline.agents.chunk_planner import chunk_planner_node
from autoclip.pipeline.agents.chunk_analyzer import chunk_analyzer_node
from autoclip.pipeline.agents.global_fusion import global_fusion_node
from autoclip.pipeline.agents.clip_selector import run_clip_selector
from autoclip.pipeline.agents.production import run_production
from autoclip.utils.ffmpeg import extract_audio
from autoclip.services.transcription import transcribe_audio
from autoclip.services.scene_detector import detect_scene_boundaries

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PRE-CHUNK NODES (run once per video)
# ═══════════════════════════════════════════════════════════════

def transcription_node(state: PipelineState) -> dict:
    """Extract audio and transcribe with Groq Whisper Turbo."""
    video_id = state["video_id"]
    output_dir = Path(f"outputs/{video_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_path = str(output_dir / "audio.wav")
    extract_audio(state["video_path"], audio_path)
    transcript_data = transcribe_audio(audio_path)

    with open(output_dir / "transcript.json", "w") as f:
        json.dump(transcript_data, f, indent=2)

    return {"transcript_data": transcript_data}


def scene_detection_node(state: PipelineState) -> dict:
    """Detect scene cuts via ffmpeg scene filter."""
    boundaries = detect_scene_boundaries(state["video_path"])
    return {"scene_boundaries": boundaries}


def selector_node(state: PipelineState) -> dict:
    return run_clip_selector(state)


def production_node(state: PipelineState) -> dict:
    return run_production(state)


# ═══════════════════════════════════════════════════════════════
# SEND-API FAN-OUT
# ═══════════════════════════════════════════════════════════════

def route_to_chunks(state: PipelineState) -> list[Send]:
    """Fan out one Send per chunk — true parallel time-chunked analysis.

    Each chunk_analyzer worker writes to `moment_map_raw` via the
    operator.add reducer; LangGraph waits for all dispatched workers to
    finish before invoking global_fusion.
    """
    plans: list[ChunkPlan] = state.get("chunk_plans") or []
    if not plans:
        return []
    # Send each chunk in its own single-element list, plus the shared video_id
    # so chunk_analyzer can publish per-chunk events.
    return [
        Send("chunk_analyzer", {
            "chunk_plans": [plan],
            "video_id": state["video_id"],
        })
        for plan in plans
    ]


def route_after_fusion(state: PipelineState) -> str:
    return "has_moments" if state.get("moment_map") else "no_moments"


def route_analysis_check(state: PipelineState) -> str:
    return "skip_to_selection" if state.get("analysis_complete") else "needs_analysis"


# ═══════════════════════════════════════════════════════════════
# SUBGRAPHS
# ═══════════════════════════════════════════════════════════════

def build_analysis_subgraph() -> StateGraph:
    """chunk_planner → Send API fan-out (chunk_analyzer ×N) → global_fusion → END."""
    g = StateGraph(PipelineState)
    g.add_node("chunk_planner", chunk_planner_node)
    g.add_node("chunk_analyzer", chunk_analyzer_node)
    g.add_node("global_fusion", global_fusion_node)

    g.set_entry_point("chunk_planner")
    g.add_conditional_edges("chunk_planner", route_to_chunks, ["chunk_analyzer"])
    g.add_edge("chunk_analyzer", "global_fusion")
    g.add_edge("global_fusion", END)
    return g


def build_generation_subgraph() -> StateGraph:
    """clip_selector → production → END."""
    g = StateGraph(PipelineState)
    g.add_node("clip_selector", selector_node)
    g.add_node("production", production_node)
    g.set_entry_point("clip_selector")
    g.add_edge("clip_selector", "production")
    g.add_edge("production", END)
    return g


# ═══════════════════════════════════════════════════════════════
# MAIN GRAPH
# ═══════════════════════════════════════════════════════════════

def build_pipeline_graph() -> StateGraph:
    g = StateGraph(PipelineState)

    g.add_node("transcription", transcription_node)
    g.add_node("scene_detection", scene_detection_node)
    g.add_node("analysis", build_analysis_subgraph().compile())
    g.add_node("generation", build_generation_subgraph().compile())

    g.add_conditional_edges(
        START, route_analysis_check,
        {"needs_analysis": "transcription", "skip_to_selection": "generation"},
    )
    g.add_edge("transcription", "scene_detection")
    g.add_edge("scene_detection", "analysis")
    g.add_conditional_edges(
        "analysis", route_after_fusion,
        {"has_moments": "generation", "no_moments": END},
    )
    g.add_edge("generation", END)
    return g


# ═══════════════════════════════════════════════════════════════
# CHECKPOINTER (env-toggle: Postgres in prod, MemorySaver in dev)
# ═══════════════════════════════════════════════════════════════

def _build_checkpointer():
    """Use PostgresSaver when LANGGRAPH_PG_URL is set, else MemorySaver."""
    pg_url = os.getenv("LANGGRAPH_PG_URL", "")
    if not pg_url:
        return MemorySaver()
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        saver = PostgresSaver.from_conn_string(pg_url)
        try:
            saver.setup()
        except Exception as e:
            logger.warning("PostgresSaver.setup() raised (often safe to ignore): %s", e)
        logger.info("LangGraph using PostgresSaver")
        return saver
    except Exception as e:
        logger.warning("PostgresSaver unavailable (%s) — falling back to MemorySaver", e)
        return MemorySaver()


checkpointer = _build_checkpointer()
pipeline = build_pipeline_graph().compile(checkpointer=checkpointer)
generation_only = build_generation_subgraph().compile()


__all__ = [
    "pipeline",
    "generation_only",
    "build_pipeline_graph",
    "build_analysis_subgraph",
    "build_generation_subgraph",
    "route_to_chunks",
    "route_after_fusion",
    "route_analysis_check",
    "checkpointer",
]
