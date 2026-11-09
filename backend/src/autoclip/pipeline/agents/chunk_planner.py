"""Chunk planner — splits a video into overlapping windows for parallel analysis.

This is the entry point of the chunk-parallel architecture (V2_PLAN §5).
It produces a list of ChunkPlan objects; the graph then fans out to
chunk_analyzer via LangGraph's Send API, one Send per chunk.
"""
from __future__ import annotations
import math
import os
import logging
from autoclip.pipeline.state import PipelineState, ChunkPlan
from autoclip.utils.ffmpeg import get_video_info

logger = logging.getLogger(__name__)

CHUNK_LENGTH = float(os.getenv("CHUNK_LENGTH_SECONDS", "120"))   # 2 min
CHUNK_OVERLAP = float(os.getenv("CHUNK_OVERLAP_SECONDS", "10"))   # 10 s overlap
MAX_CHUNKS = int(os.getenv("CHUNK_MAX", "60"))                    # cost/safety bound (~110 min at 2-min chunks)


def _window(transcript_data: dict, start: float, end: float) -> dict:
    """Only the words/utterances overlapping [start, end] — each chunk (and
    each LangGraph Send payload) carries its own slice, never the whole film."""
    def inside(x: dict) -> bool:
        return x.get("start", 0) < end and x.get("end", 0) > start
    return {
        "words": [w for w in transcript_data.get("words") or [] if inside(w)],
        "utterances": [u for u in transcript_data.get("utterances") or [] if inside(u)],
        "duration": transcript_data.get("duration"),
    }


def chunk_planner_node(state: PipelineState) -> dict:
    """Plan chunks based on the source video's duration."""
    video_path = state["video_path"]
    transcript_data = state.get("transcript_data", {}) or {}

    duration = float(transcript_data.get("duration") or 0.0)
    if duration <= 0:
        info = get_video_info(video_path)
        duration = float(info.get("duration", 0.0))
    duration = max(duration, 1.0)

    # Don't spend vision calls on the end credits (utils/video_profile.py
    # detects them from keyframe luma); global_fusion also drops any moment
    # that still lands there.
    from autoclip.utils.video_profile import credits_start
    credits = credits_start(state.get("video_id", ""), video_path)
    if credits and 60.0 < credits < duration:
        logger.info("chunk_planner: end credits from %.0fs — analysing [0, %.0f] of %.0fs",
                    credits, credits, duration)
        duration = credits

    chunk_len, overlap = CHUNK_LENGTH, min(CHUNK_OVERLAP, CHUNK_LENGTH / 2)
    step = max(1.0, chunk_len - overlap)
    needed = 1 if duration <= chunk_len else math.ceil((duration - overlap) / step)
    if needed > MAX_CHUNKS:
        # Never silently truncate: stretch chunks so MAX_CHUNKS covers the
        # whole video (frames are spread evenly, so longer chunks just mean
        # sparser frames; in video mode, more tokens per call).
        step = (duration - overlap) / MAX_CHUNKS
        chunk_len = step + overlap
        logger.warning(
            "chunk_planner: %.0fs video needs %d chunks of %.0fs but CHUNK_MAX=%d — "
            "stretching chunks to %.0fs (raise CHUNK_MAX to keep %.0fs chunks)",
            duration, needed, CHUNK_LENGTH, MAX_CHUNKS, chunk_len, CHUNK_LENGTH,
        )

    plans: list[ChunkPlan] = []
    t = 0.0
    idx = 0
    while t < duration and idx < MAX_CHUNKS:
        end = min(t + chunk_len, duration)
        if idx == MAX_CHUNKS - 1:
            end = duration   # float slop must never leave a tail uncovered
        s_r, e_r = round(t, 3), round(end, 3)
        plans.append(ChunkPlan(
            index=idx,
            start=s_r,
            end=e_r,
            video_path=video_path,
            transcript_window=_window(transcript_data, s_r, e_r),
        ))
        if end >= duration:
            break
        t += step
        idx += 1

    if plans and plans[-1].end < duration - 0.5:
        logger.error("chunk_planner: plans end at %.1fs but video is %.1fs", plans[-1].end, duration)
    logger.info("chunk_planner: duration=%.1fs → %d chunks of ≤%.0fs", duration, len(plans), chunk_len)
    return {"chunk_plans": plans, "video_duration": duration}
