"""Clip selector node — picks moments based on user preferences and produces clips."""
import json
import time
from pathlib import Path
from google import genai
from app.config import GEMINI_API_KEY, GEMINI_RPM_DELAY
from app.models import generate_id
from app.pipeline.state import PipelineState, ClipConfig, ProducedClip, Moment


def _select_moments(
    moment_map: list[Moment],
    config: ClipConfig,
    used_ranges: list[tuple],
) -> Moment | None:
    """Select the best unused moment matching config criteria."""
    target_length = config.length

    for moment in moment_map:
        moment_duration = moment.end - moment.start

        # Skip if already used (avoid duplicate clips)
        overlap = False
        for used_start, used_end in used_ranges:
            if moment.start < used_end and moment.end > used_start:
                overlap = True
                break
        if overlap:
            continue

        # Filter by style if specified
        if config.style != "any":
            # Map user-friendly styles to hook types
            style_map = {
                "funny": ["funny", "story"],
                "dramatic": ["emotional", "controversial", "hot_take"],
                "educational": ["educational", "quote"],
                "motivational": ["emotional", "story", "quote"],
                "controversial": ["controversial", "hot_take"],
            }
            allowed_types = style_map.get(config.style, [])
            if allowed_types and not any(tag in allowed_types for tag in moment.style_tags):
                # Relax filter: if no exact match, still consider high-scoring moments
                if moment.convergence_score < 0.7:
                    continue

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

    # Snap to scene boundaries if close (within 2 seconds)
    for boundary in scene_boundaries:
        if abs(clip_start - boundary) < 2.0:
            clip_start = boundary
            clip_end = clip_start + target_length
        if abs(clip_end - boundary) < 2.0:
            clip_end = boundary
            clip_start = max(0, clip_end - target_length)

    # Snap to word boundaries
    words = transcript_data.get("words", [])
    if words:
        # Find nearest word start for clip_start
        for w in words:
            if w["start"] >= clip_start - 0.5:
                clip_start = w["start"]
                break

        # Find nearest word end for clip_end
        for w in reversed(words):
            if w["end"] <= clip_end + 0.5:
                clip_end = w["end"]
                break

    return round(clip_start, 3), round(clip_end, 3)


def _score_clip_with_gemini(moment: Moment, transcript: str) -> dict:
    """Get engagement scores for a clip using Gemini."""
    client = genai.Client(api_key=GEMINI_API_KEY)

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
6. Novelty — Is it fresh and surprising?

Return ONLY valid JSON:
{{"hook": N, "emotion": N, "shareability": N, "retention": N, "controversy": N, "novelty": N}}

JSON:"""

    time.sleep(GEMINI_RPM_DELAY)
    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    text = response.text.strip()

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        scores = json.loads(text.strip())
    except json.JSONDecodeError:
        scores = {"hook": 5, "emotion": 5, "shareability": 5, "retention": 5, "controversy": 5, "novelty": 5}

    weights = {
        "hook": 0.20, "emotion": 0.20, "shareability": 0.15,
        "retention": 0.20, "controversy": 0.10, "novelty": 0.15
    }
    overall = sum(scores.get(k, 5) * w for k, w in weights.items())
    scores["overall"] = round(overall, 2)

    return scores


def _generate_title(moment: Moment, transcript: str) -> str:
    """Generate a catchy title for the clip."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""Generate a catchy, short title (max 50 chars) for this video clip.
The title should be engaging and describe the key moment.

Content: {moment.description}
Transcript excerpt: {transcript[:300]}

Return ONLY the title text, nothing else."""

    time.sleep(GEMINI_RPM_DELAY)
    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    return response.text.strip().strip('"')[:50]


def run_clip_selector(state: PipelineState) -> dict:
    """
    Select moments from moment_map based on user clip configs.
    Score and title each clip.
    """
    moment_map = state.get("moment_map", [])
    clip_configs = state.get("clip_configs", [])
    transcript_data = state.get("transcript_data", {})
    scene_boundaries = state.get("scene_boundaries", [])
    video_id = state["video_id"]

    if not moment_map:
        return {"clips": [], "error": "No interesting moments found in the video."}

    if not clip_configs:
        # Default: 4 clips, 30s, any style, 9:16
        clip_configs = [ClipConfig() for _ in range(4)]

    clips = []
    used_ranges = []

    for config in clip_configs:
        if config.moment is not None:
            # User pinned a specific timestamp — find nearest moment
            nearest = min(moment_map, key=lambda m: abs(m.start - config.moment))
            moment = nearest
        else:
            moment = _select_moments(moment_map, config, used_ranges)

        if moment is None:
            continue

        # Expand/trim to target length
        clip_start, clip_end = _expand_moment_to_length(
            moment, config.length, transcript_data, scene_boundaries
        )

        used_ranges.append((clip_start, clip_end))

        # Get transcript for this clip
        words = transcript_data.get("words", [])
        clip_words = [w for w in words if w["start"] >= clip_start - 0.1 and w["end"] <= clip_end + 0.1]
        clip_transcript = " ".join(w["text"] for w in clip_words)

        # Score the clip
        scores = _score_clip_with_gemini(moment, clip_transcript)

        # Generate title
        title = _generate_title(moment, clip_transcript)

        clip = ProducedClip(
            id=generate_id(),
            title=title,
            start_time=clip_start,
            end_time=clip_end,
            duration=round(clip_end - clip_start, 2),
            file_path="",  # filled by production
            thumbnail_path=None,
            transcript=clip_transcript,
            scores=scores,
            overall_score=scores.get("overall", 5.0),
            frame=config.frame,
            style_tags=moment.style_tags,
        )
        clips.append(clip)

    # Sort by overall score
    clips.sort(key=lambda c: c.overall_score, reverse=True)

    return {"clips": clips}
