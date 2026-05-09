"""Global fusion — dedupes moments across chunk-overlap regions.

Chunks overlap by ~10s, so the same real moment may appear at the end of
chunk N and the start of chunk N+1. This node consolidates duplicates by:
  1. Greedy temporal merge (overlap > 50% of the shorter window)
  2. Optional cosine-similarity dedupe via embeddings (Phase 2.5)
The merged result is the canonical `moment_map` for clip selection.
"""
from __future__ import annotations
import logging
from autoclip.pipeline.state import PipelineState, Moment
from autoclip.services import events

logger = logging.getLogger(__name__)


def _temporal_overlap_frac(a: Moment, b: Moment) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    if inter <= 0:
        return 0.0
    shorter = min(a.end - a.start, b.end - b.start)
    return inter / shorter if shorter > 0 else 0.0


def _merge(a: Moment, b: Moment) -> Moment:
    """Pick the higher-convergence moment, widen its window to cover both."""
    keeper, other = (a, b) if a.convergence_score >= b.convergence_score else (b, a)
    return Moment(
        start=min(a.start, b.start),
        end=max(a.end, b.end),
        visual_energy=max(a.visual_energy, b.visual_energy),
        audio_energy=max(a.audio_energy, b.audio_energy),
        text_hook_strength=max(a.text_hook_strength, b.text_hook_strength),
        convergence_score=max(a.convergence_score, b.convergence_score),
        modalities_active=max(a.modalities_active, b.modalities_active),
        style_tags=list({*a.style_tags, *b.style_tags}),
        description=keeper.description,
        transcript=keeper.transcript if len(keeper.transcript) >= len(other.transcript) else other.transcript,
        embedding=keeper.embedding,
    )


def global_fusion_node(state: PipelineState) -> dict:
    raw = list(state.get("moment_map_raw") or [])
    if not raw:
        return {"moment_map": [], "analysis_complete": True}

    raw.sort(key=lambda m: (m.start, -m.convergence_score))

    merged: list[Moment] = []
    for m in raw:
        absorbed = False
        for i, kept in enumerate(merged):
            if _temporal_overlap_frac(m, kept) >= 0.5:
                merged[i] = _merge(kept, m)
                absorbed = True
                break
        if not absorbed:
            merged.append(m)

    # Optional embedding-based dedupe (Phase 2.5)
    try:
        from autoclip.services.embeddings import embed_moments, cosine_sim_dedupe
        embed_moments(merged)
        merged = cosine_sim_dedupe(merged, threshold=0.92)
    except Exception as e:
        logger.debug("embedding dedupe skipped (non-fatal): %s", e)

    merged.sort(key=lambda m: m.convergence_score, reverse=True)
    logger.info("global_fusion: %d raw → %d merged", len(raw), len(merged))

    video_id = state.get("video_id")
    if video_id:
        events.publish_moments(video_id, merged)

    return {"moment_map": merged, "analysis_complete": True}
