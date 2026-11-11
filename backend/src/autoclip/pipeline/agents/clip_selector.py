"""Clip selector node — picks moments for a clip request, fits windows, scores.

Selection (see rag/selection.py): hybrid candidates over the credits-free
moment map (vector + category tags + keywords) -> one LLM re-rank against
the user's own request (OPENROUTER_MODEL_RERANK) -> diversity pass (no two
clips overlapping >30% or with centres within 20s, also vs clips produced in
earlier turns). `ClipConfig.query` is the agent's search phrase; the user's
raw message travels in state["user_request"]. Explicit timestamps bypass it.
"""
from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from autoclip.llm.openrouter import get_chat_model
from autoclip.models import generate_id
from autoclip.pipeline import telemetry
from autoclip.pipeline.state import PipelineState, ClipConfig, ProducedClip, Moment, EngagementScores
from autoclip.rag import selection as S
from autoclip.services.talk_segments import is_segment, sentences, fit_segment
from autoclip.utils.text import truncate_words

logger = logging.getLogger(__name__)

LENGTH_TOLERANCE = 0.10   # final clip length stays within +-10% of the request
MIN_CLIP_SECONDS = 5
MAX_CLIP_SECONDS = 180
SCENE_SNAP_SECONDS = 1.5


def _in_range(m: Moment, lo: float, hi: float) -> bool:
    """Moment's centre lies inside the allowed (credits-free) window."""
    c = (m.start + m.end) / 2
    return lo <= c <= hi


def _effective_query(config: ClipConfig) -> str:
    query = config.query.strip() if config.query else ""
    if not query and config.style and config.style != "any":
        query = f"{config.style} moment"
    return query or "the most engaging, high-energy moment"


def _rank_moments(moment_map: list[Moment], query: str, request: str, want: int,
                  lo: float, hi: float, words: Optional[list[dict]] = None,
                  length: float = 30.0) -> list[tuple[Moment, str]]:
    """Hybrid candidates (vector + category tags + keywords) over the
    credits-free moments, then one LLM re-rank against the user's request.
    Returns (moment, reason) best-first: re-ranked ones, then the rest of the
    candidate pool in hybrid order (fallback material for the diversity pass)."""
    pool = [m for m in moment_map if _in_range(m, lo, hi)]
    if not pool:
        return []
    idx = S.hybrid_candidates(pool, f"{request} {query}".strip(), S.embed_query(query))
    cands = [pool[i] for i in idx]
    dialogue = None
    if words:  # judge the clip that would actually be cut, not a 3-8s fragment
        half = max(5.0, float(length)) / 2
        dialogue = []
        for m in cands:
            if is_segment(m):  # a talk segment: its whole text (payoff included)
                dialogue.append(m.transcript or "")
                continue
            c = (m.start + m.end) / 2
            dialogue.append(" ".join(w["text"] for w in words
                                     if w["end"] > c - half and w["start"] < c + half))
    ranked = S.rerank(request, query, cands, want, dialogue)
    return [(cands[i], why) for i, why in S.order_after_rerank(len(cands), ranked)]


def _word_at(words: list[dict], t: float) -> Optional[dict]:
    for w in words:
        if w["start"] < t < w["end"]:
            return w
        if w["start"] >= t:
            break
    return None


def _nearest(points: list[float], t: float, max_dist: float) -> Optional[float]:
    best = None
    for p in points:
        d = abs(p - t)
        if d <= max_dist and (best is None or d < abs(best - t)):
            best = p
    return best


def _fit_window(
    moment: Moment,
    target_length: float,
    transcript_data: dict,
    scene_boundaries: list[float],
    lo: float = 0.0,
    hi: float = float("inf"),
) -> tuple[float, float]:
    """Centre a `target_length` window on the moment, then nudge its edges so
    they don't cut mid-word and land on nearby scene cuts — but only while
    the length stays within +-10% of the request and inside [lo, hi].
    (The old version let snapping stretch a 15s request to 16.4s and a 30s
    one to 33.6s, and never clamped to the video's end.)"""
    target = float(max(MIN_CLIP_SECONDS, min(target_length, MAX_CLIP_SECONDS)))
    if hi - lo < target:
        target = max(1.0, hi - lo)
    tol = max(0.5, LENGTH_TOLERANCE * target)

    def ok(s: float, e: float) -> bool:
        return s >= lo and e <= hi and abs((e - s) - target) <= tol

    if is_segment(moment):
        # Talk segment: cut on sentence starts/ends — a sub-window ending on
        # the payoff when the ask is shorter, adjacent sentences when longer.
        win = fit_segment(moment, target, sentences(transcript_data), tol, lo, hi)
        if win and ok(*win):
            return round(win[0], 3), round(win[1], 3)
        # no sentence-aligned fit: a window ending on the payoff, word-snapped below
        if moment.payoff:
            moment = Moment(**{**moment.__dict__, "start": moment.payoff - target / 2,
                               "end": moment.payoff - target / 2 + 0.001})

    center = (moment.start + moment.end) / 2
    start = min(max(center - target / 2, lo), hi - target)
    end = start + target

    words = sorted(transcript_data.get("words", []) or [], key=lambda w: w["start"])
    if words:
        ws, we = _word_at(words, start), _word_at(words, end)
        ns = ws["start"] if ws else start
        ne = we["end"] if we else end
        if ok(ns, ne):
            start, end = ns, ne
        elif ok(ns, end):
            start = ns
        elif ok(start, ne):
            end = ne

    scenes = sorted(scene_boundaries or [])
    if scenes:
        b = _nearest(scenes, start, SCENE_SNAP_SECONDS)
        if b is not None and ok(b, end) and not (words and _word_at(words, b)):
            start = b
        b = _nearest(scenes, end, SCENE_SNAP_SECONDS)
        if b is not None and ok(start, b) and not (words and _word_at(words, b)):
            end = b

    if not ok(start, end):  # safety net — never return an out-of-spec window
        start = min(max(center - target / 2, lo), hi - target)
        end = start + target
    return round(max(lo, start), 3), round(min(hi, end), 3)


# Back-compat alias (older callers/tests).
def _expand_moment_to_length(moment, target_length, transcript_data, scene_boundaries):
    return _fit_window(moment, target_length, transcript_data, scene_boundaries)


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


TITLE_MAX_CHARS = 50   # thumbnails draw the title on one line


def _clean_title(raw: str) -> str:
    """One line, no wrapping quotes, cut at a word boundary. A hard [:50]
    slice used to leave titles like "... for Lower Ta"."""
    line = next((ln for ln in (raw or "").splitlines() if ln.strip()), "")
    line = line.strip().strip('"\'“”‘’*').strip()
    if line.lower().startswith("title:"):
        line = line[6:].strip()
    return truncate_words(line, TITLE_MAX_CHARS)


def _generate_title(moment: Moment, transcript: str) -> str:
    """Generate a catchy title for the clip via OpenRouter."""
    prompt = f"""Write a catchy title for this short video clip.
Keep it short: at most 7 words and under 45 characters. A complete phrase,
not a sentence cut off. Engaging, and about the key moment.

Content: {moment.description}
Transcript excerpt: {transcript[:300]}

Return ONLY the title text, nothing else."""

    model = get_chat_model(lite=True)
    try:
        response = model.invoke(prompt)
        telemetry.record_openrouter_call(response, model_label="lite_title")
        return _clean_title(response.content) or _clean_title(moment.description) or "Untitled clip"
    except Exception:
        return _clean_title(moment.description) or "Untitled clip"


def _score_and_title(moment: Moment, transcript: str) -> tuple[dict, str]:
    return _score_clip(moment, transcript), _generate_title(moment, transcript)


def run_clip_selector(state: PipelineState) -> dict:
    """
    Select moments from moment_map based on user clip configs (via RAG
    retrieval), fit each to the requested length inside the credits-free
    window, then score and title them (via OpenRouter, in parallel).

    No clip_configs -> no clips. (It used to invent 4 default clips, which
    made the analysis-only path render throwaway clips.)
    """
    moment_map = state.get("moment_map", [])
    clip_configs = state.get("clip_configs", []) or []
    transcript_data = state.get("transcript_data", {}) or {}
    scene_boundaries = state.get("scene_boundaries", []) or []
    video_id = state["video_id"]

    if not clip_configs:
        return {"clips": []}
    if not moment_map:
        return {"clips": [], "error": "No interesting moments found in the video."}

    lo, hi = 0.0, float("inf")
    rng = state.get("safe_range")
    if rng:
        lo, hi = float(rng[0]), float(rng[1])
    elif state.get("video_path"):
        try:
            from autoclip.utils.video_profile import safe_range
            lo, hi = safe_range(video_id, state["video_path"], state.get("video_duration") or 0.0,
                                transcript_data.get("words", []))
        except Exception as e:
            logger.warning("safe_range failed for %s (using whole video): %s", video_id, e)

    # Seed with ranges already claimed by clips produced in earlier turns —
    # otherwise a second select_and_produce_clips call happily returns a
    # duplicate of the same moment (live-confirmed: two identical clips).
    used_ranges = [tuple(r) for r in state.get("used_ranges", [])]
    words = transcript_data.get("words", []) or []

    picked: list[tuple[ClipConfig, Moment, float, float, str]] = []

    def take(config: ClipConfig, moment: Moment, clip_start: float, clip_end: float) -> None:
        used_ranges.append((clip_start, clip_end))
        clip_words = [w for w in words if w["end"] > clip_start and w["start"] < clip_end]
        picked.append((config, moment, clip_start, clip_end, " ".join(w["text"] for w in clip_words)))

    # Explicit timestamps ("clip at 12:30") bypass retrieval.
    for config in [c for c in clip_configs if c.moment is not None]:
        in_range = [m for m in moment_map if _in_range(m, lo, hi)] or moment_map
        moment = min(in_range, key=lambda m: abs(m.start - config.moment))
        anchor = moment
        if is_segment(moment):  # the asked-for time, not the segment's payoff
            anchor = Moment(**{**moment.__dict__, "start": float(config.moment),
                               "end": float(config.moment), "style_tags": []})
        take(config, moment, *_fit_window(anchor, config.length, transcript_data, scene_boundaries, lo, hi))

    # Retrieval: one ranking per distinct query, then a diversity pass — no two
    # clips (in this request or produced earlier) overlap >30% or sit within 20s.
    request = (state.get("user_request") or "").strip()
    groups: dict[str, list[ClipConfig]] = {}
    for config in clip_configs:
        if config.moment is None:
            groups.setdefault(_effective_query(config), []).append(config)
    for query, configs in groups.items():
        ranked = _rank_moments(moment_map, query, request, len(configs), lo, hi,
                               words, configs[0].length)
        if not ranked:  # nothing in range at all
            continue
        for config in configs:
            for moment, _why in ranked:
                window = _fit_window(moment, config.length, transcript_data, scene_boundaries, lo, hi)
                if not any(S.conflicts(window, u) for u in used_ranges):
                    take(config, moment, *window)
                    break

    with ThreadPoolExecutor(max_workers=4) as pool:
        meta = list(pool.map(lambda p: _score_and_title(p[1], p[4] or p[1].transcript), picked))

    clips = []
    for (config, moment, clip_start, clip_end, clip_transcript), (scores, title) in zip(picked, meta):
        clips.append(ProducedClip(
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
            caption_style=config.caption_style or "bold_pop",
        ))

    # Rank order (the re-ranker's judgement of fit to the request) is kept —
    # re-sorting by the generic engagement score used to bury the best match.
    return {"clips": clips}
