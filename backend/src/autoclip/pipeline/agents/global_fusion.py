"""Global fusion — dedupes moments across chunk-overlap regions.

Chunks overlap by ~10s, so the same real moment may appear at the end of
chunk N and the start of chunk N+1. This node consolidates duplicates by:
  0. Dropping moments inside the detected end credits
  1. Greedy temporal merge (overlap > 50% of the shorter window)
  2. Each moment's transcript is re-sliced from the real word-level
     transcript for its own [start, end] (model-quoted text can be wrong)
  3. Optional embedding dedupe on description + own-window dialogue, only
     between moments whose centres are within FUSION_DEDUPE_WINDOW_SECONDS
     (live: whole-film dedupe on bad shared transcripts collapsed 229 → 52)
  4. A text-only tagging pass adds categories + a "why" line per moment
The merged result is the canonical `moment_map` for clip selection.
"""
from __future__ import annotations
import logging
from autoclip.config import FUSION_DEDUPE_THRESHOLD, FUSION_DEDUPE_WINDOW_SECONDS
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


def _window_text(words: list[dict], start: float, end: float) -> str:
    return " ".join(w["text"] for w in words if w["start"] < end and w["end"] > start).strip()


def _attach_own_transcripts(moments: list[Moment], transcript_data: dict) -> None:
    """Replace each moment's transcript with the real words in its window.

    Keeps the model's text only when the transcript has nothing there (e.g.
    in video mode the model may have heard dialogue transcription missed).
    """
    words = (transcript_data or {}).get("words") or []
    if not words:
        return
    for m in moments:
        own = _window_text(words, m.start, m.end)
        if own:
            m.transcript = own[:1000]


def global_fusion_node(state: PipelineState) -> dict:
    raw = list(state.get("moment_map_raw") or [])
    if not raw:
        return {"moment_map": [], "analysis_complete": True}

    from autoclip.utils.video_profile import credits_start
    credits = credits_start(state.get("video_id", ""), state.get("video_path", ""))
    if credits:
        before = len(raw)
        raw = [m for m in raw if m.start < credits]
        if len(raw) != before:
            logger.info("global_fusion: dropped %d moment(s) inside the end credits (>= %.0fs)",
                        before - len(raw), credits)
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

    n_temporal = len(merged)
    _attach_own_transcripts(merged, state.get("transcript_data") or {})

    # Embedding dedupe (Phase 2.5) — temporally local only.
    try:
        from autoclip.services.embeddings import embed_moments, cosine_sim_dedupe
        embed_moments(merged)
        merged = cosine_sim_dedupe(
            merged, threshold=FUSION_DEDUPE_THRESHOLD, max_gap_s=FUSION_DEDUPE_WINDOW_SECONDS,
        )
    except Exception as e:
        logger.warning("embedding dedupe skipped (non-fatal): %s", e)

    # Text-only category tags + "why it works" (cheap lite-model pass) —
    # feeds hybrid retrieval and the re-ranker (rag/selection.py).
    try:
        from autoclip.services.moment_tagger import tag_moments
        tag_moments(merged)
    except Exception as e:
        logger.warning("moment tagging skipped (non-fatal): %s", e)

    merged.sort(key=lambda m: m.convergence_score, reverse=True)
    logger.info("global_fusion: %d raw → %d after temporal merge → %d after embedding dedupe "
                "(threshold=%.2f, window=%.0fs)", len(raw), n_temporal, len(merged),
                FUSION_DEDUPE_THRESHOLD, FUSION_DEDUPE_WINDOW_SECONDS)

    video_id = state.get("video_id")
    if video_id:
        events.publish_moments(video_id, merged)

    return {"moment_map": merged, "analysis_complete": True}
