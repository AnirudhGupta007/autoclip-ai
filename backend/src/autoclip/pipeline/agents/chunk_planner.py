"""Chunk planner — splits a video into overlapping windows for parallel analysis.

This is the entry point of the chunk-parallel architecture (V2_PLAN §5).
It produces a list of ChunkPlan objects; the graph then fans out to
chunk_analyzer via LangGraph's Send API, one Send per chunk.
"""
from __future__ import annotations
import os
import logging
from autoclip.pipeline.state import PipelineState, ChunkPlan
from autoclip.utils.ffmpeg import get_video_info

logger = logging.getLogger(__name__)

CHUNK_LENGTH = float(os.getenv("CHUNK_LENGTH_SECONDS", "120"))   # 2 min
CHUNK_OVERLAP = float(os.getenv("CHUNK_OVERLAP_SECONDS", "10"))   # 10 s overlap
MAX_CHUNKS = int(os.getenv("CHUNK_MAX", "60"))                    # safety bound


def chunk_planner_node(state: PipelineState) -> dict:
    """Plan chunks based on the source video's duration."""
    video_path = state["video_path"]
    transcript_data = state.get("transcript_data", {}) or {}

    duration = float(transcript_data.get("duration") or 0.0)
    if duration <= 0:
        info = get_video_info(video_path)
        duration = float(info.get("duration", 0.0))
    duration = max(duration, 1.0)

    plans: list[ChunkPlan] = []
    step = max(1.0, CHUNK_LENGTH - CHUNK_OVERLAP)
    t = 0.0
    idx = 0
    while t < duration and idx < MAX_CHUNKS:
        end = min(t + CHUNK_LENGTH, duration)
        plans.append(ChunkPlan(
            index=idx,
            start=round(t, 3),
            end=round(end, 3),
            video_path=video_path,
            transcript_window=transcript_data,
        ))
        if end >= duration:
            break
        t += step
        idx += 1

    logger.info("chunk_planner: duration=%.1fs → %d chunks", duration, len(plans))
    return {"chunk_plans": plans, "video_duration": duration}
