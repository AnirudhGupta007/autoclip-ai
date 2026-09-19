"""Clip selector node — RAG-driven moment selection + OpenRouter scoring/titles.

Replaces the old fixed 5-value style-enum keyword filter with real semantic
retrieval (autoclip.rag.retriever) over the moment map: `ClipConfig.query`
(freeform user text, e.g. "roasts a competitor") drives retrieval directly;
when empty, `ClipConfig.style` is used as the query so old-style requests
("funny clips") still resolve to something reasonable without RAG-specific
phrasing.
"""
from __future__ import annotations
from autoclip.llm.openrouter import get_chat_model
from autoclip.models import generate_id
from autoclip.pipeline import telemetry
from autoclip.pipeline.state import PipelineState, ClipConfig, ProducedClip, Moment, EngagementScores
from autoclip.rag.retriever import retrieve_moments


def _select_moment(
    video_id: str,
    moment_map: list[Moment],
    config: ClipConfig,
    used_ranges: list[tuple],
) -> Moment | None:
    """RAG-retrieve the best unused moment matching the user's request."""
    query = config.query.strip() if config.query else ""
    if not query and config.style and config.style != "any":
        query = f"{config.style} moment"
    if not query:
        query = "the most engaging, high-energy moment"

    candidates = retrieve_moments(
        video_id=video_id, query=query, k=10,
        min_convergence=0.0, exclude_ranges=tuple(used_ranges),
    )
    if candidates:
        return candidates[0]

    # Fallback: retrieval found nothing usable (e.g. empty index) — take the
    # highest-convergence unused moment from the in-state map directly.
    for moment in sorted(moment_map, key=lambda m: m.convergence_score, reverse=True):
        overlap = any(moment.start < e and moment.end > s for s, e in used_ranges)
        if not overlap:
            return moment
    return None


def _expand_moment_to_length(
    moment: Moment,
    target_length: int,
    transcript_data: dict,
    scene_boundaries: list[float],
) -> tuple[float, float]:
    """Expand or trim a moment to match the target clip length."""
    center = (moment.start + moment.end) / 2
    half_len = target_length / 2

    clip_start = max(0, center - half_len)
    clip_end = clip_start + target_length

    for boundary in scene_boundaries:
        if abs(clip_start - boundary) < 2.0:
            clip_start = boundary
            clip_end = clip_start + target_length
        if abs(clip_end - boundary) < 2.0:
            clip_end = boundary
            clip_start = max(0, clip_end - target_length)

    # Snap to word boundaries, but only keep the snap if it doesn't gut the
    # clip: with sparse/approximate word timings the nearest words can sit far
    # inside the window and collapse a 15s request down to ~4s.
    words = transcript_data.get("words", [])
    if words:
        snapped_start, snapped_end = clip_start, clip_end
        for w in words:
            if w["start"] >= clip_start - 0.5:
                snapped_start = w["start"]
                break
        for w in reversed(words):
            if w["end"] <= clip_end + 0.5:
                snapped_end = w["end"]
                break
        if snapped_end - snapped_start >= 0.8 * target_length:
            clip_start, clip_end = snapped_start, snapped_end

    return round(clip_start, 3), round(clip_end, 3)


_SCORE_WEIGHTS = {
    "hook": 0.20, "emotion": 0.20, "shareability": 0.15,
    "retention": 0.20, "controversy": 0.10, "novelty": 0.15,
}


def _score_clip(moment: Moment, transcript: str) -> dict:
    """Get engagement scores for a clip via OpenRouter structured output."""
    prompt = f"""Rate this video clip on 6 dimensions (each 1-10). Be critical.

Content description: {moment.description}
Style tags: {', '.join(moment.style_tags)}
Cross-modal convergence: {moment.convergence_score:.2f}
Visual energy: {moment.visual_energy:.2f}
Audio energy: {moment.audio_energy:.2f}

Transcript: {transcript[:1000]}

Dimensions:
1. Hook Strength — Does the opening grab attention?
2. Emotional Impact — Does it make viewers feel something?
3. Shareability — Would people repost this?
4. Retention — Will viewers watch until the end?
5. Controversy — Does it spark discussion?
6. Novelty — Is it fresh and surprising?"""

    model = get_chat_model(lite=True).with_structured_output(EngagementScores, include_raw=True)
    try:
        response = model.invoke(prompt)
        parsed: EngagementScores = response["parsed"]
        telemetry.record_openrouter_call(response["raw"], model_label="lite_scoring")
        scores = parsed.model_dump()
    except Exception:
        scores = {"hook": 5, "emotion": 5, "shareability": 5, "retention": 5, "controversy": 5, "novelty": 5}

    overall = sum(scores.get(k, 5) * w for k, w in _SCORE_WEIGHTS.items())
    scores["overall"] = round(overall, 2)
    return scores


def _generate_title(moment: Moment, transcript: str) -> str:
    """Generate a catchy title for the clip via OpenRouter."""
    prompt = f"""Generate a catchy, short title (max 50 chars) for this video clip.
The title should be engaging and describe the key moment.

Content: {moment.description}
Transcript excerpt: {transcript[:300]}

Return ONLY the title text, nothing else."""

    model = get_chat_model(lite=True)
    try:
        response = model.invoke(prompt)
        telemetry.record_openrouter_call(response, model_label="lite_title")
        return response.content.strip().strip('"')[:50]
    except Exception:
        return (moment.description or "Untitled clip")[:50]


def run_clip_selector(state: PipelineState) -> dict:
    """
    Select moments from moment_map based on user clip configs (via RAG
    retrieval), score and title each clip (via OpenRouter).
    """
    moment_map = state.get("moment_map", [])
    clip_configs = state.get("clip_configs", [])
    transcript_data = state.get("transcript_data", {})
    scene_boundaries = state.get("scene_boundaries", [])
    video_id = state["video_id"]

    if not moment_map:
        return {"clips": [], "error": "No interesting moments found in the video."}

    if not clip_configs:
        clip_configs = [ClipConfig() for _ in range(4)]

    clips = []
    # Seed with ranges already claimed by clips produced in earlier turns —
    # otherwise a second select_and_produce_clips call happily returns a
    # duplicate of the same moment (live-confirmed: two identical clips).
    used_ranges = [tuple(r) for r in state.get("used_ranges", [])]

    for config in clip_configs:
        if config.moment is not None:
            nearest = min(moment_map, key=lambda m: abs(m.start - config.moment))
            moment = nearest
        else:
            moment = _select_moment(video_id, moment_map, config, used_ranges)

        if moment is None:
            continue

        clip_start, clip_end = _expand_moment_to_length(
            moment, config.length, transcript_data, scene_boundaries
        )

        used_ranges.append((clip_start, clip_end))

        words = transcript_data.get("words", [])
        clip_words = [w for w in words if w["start"] >= clip_start - 0.1 and w["end"] <= clip_end + 0.1]
        clip_transcript = " ".join(w["text"] for w in clip_words)

        scores = _score_clip(moment, clip_transcript)
        title = _generate_title(moment, clip_transcript)

        clip = ProducedClip(
            id=generate_id(),
            title=title,
            start_time=clip_start,
            end_time=clip_end,
            duration=round(clip_end - clip_start, 2),
            file_path="",
            thumbnail_path=None,
            transcript=clip_transcript,
            scores=scores,
            overall_score=scores.get("overall", 5.0),
            frame=config.frame,
            style_tags=moment.style_tags,
        )
        clips.append(clip)

    clips.sort(key=lambda c: c.overall_score, reverse=True)

    return {"clips": clips}
