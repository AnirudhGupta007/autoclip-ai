"""Temporal fusion node — aligns visual, audio, and text timelines to find convergence."""
import json
import time
from google import genai
from app.config import GEMINI_API_KEY, GEMINI_RPM_DELAY
from app.pipeline.state import (
    PipelineState, Moment, VisualSignal, AudioSignal, TextSegment
)


def _find_convergence_windows(
    visual: list[VisualSignal],
    audio: list[AudioSignal],
    text: list[TextSegment],
    window_size: float = 5.0,
) -> list[dict]:
    """
    Find time windows where 2+ modalities show high engagement.
    Uses a sliding window approach.
    """
    if not visual and not audio and not text:
        return []

    # Determine video duration from available signals
    max_time = 0
    if visual:
        max_time = max(max_time, max(v.timestamp for v in visual))
    if audio:
        max_time = max(max_time, max(a.timestamp for a in audio))
    if text:
        max_time = max(max_time, max(t.end for t in text))

    windows = []
    t = 0.0
    step = 2.0  # slide by 2 seconds

    while t < max_time:
        w_end = t + window_size

        # Visual score for this window
        v_signals = [v for v in visual if t <= v.timestamp < w_end]
        v_score = max((v.energy for v in v_signals), default=0.0)
        v_has_emotion = any(v.emotion not in ("neutral",) and v.emotion_confidence > 0.6 for v in v_signals)
        if v_has_emotion:
            v_score = min(1.0, v_score + 0.2)

        # Audio score for this window
        a_signals = [a for a in audio if t <= a.timestamp < w_end]
        a_score = max((a.energy for a in a_signals), default=0.0)
        a_has_event = any(a.event_type in ("laughter", "applause") for a in a_signals)
        a_high_pace = any(a.speech_pace > 180 for a in a_signals)  # fast speech
        if a_has_event:
            a_score = min(1.0, a_score + 0.3)
        if a_high_pace:
            a_score = min(1.0, a_score + 0.15)

        # Text score for this window
        t_segments = [s for s in text if s.start < w_end and s.end > t]
        t_score = max((s.hook_strength for s in t_segments), default=0.0)

        # Count modalities that are "active" (score > threshold)
        threshold = 0.4
        active_count = sum([
            1 if v_score > threshold else 0,
            1 if a_score > threshold else 0,
            1 if t_score > threshold else 0,
        ])

        # Convergence score: weighted combination + bonus for multi-modal agreement
        convergence = (v_score * 0.3 + a_score * 0.3 + t_score * 0.4)
        if active_count >= 3:
            convergence = min(1.0, convergence * 1.3)  # 30% bonus for triple convergence
        elif active_count >= 2:
            convergence = min(1.0, convergence * 1.15)  # 15% bonus for double

        # Collect style tags from text segments
        style_tags = list(set(
            s.hook_type for s in t_segments
            if s.hook_type != "none" and s.hook_strength > 0.3
        ))

        # Get transcript for this window
        transcript = " ".join(s.text for s in t_segments) if t_segments else ""

        # Description from visual
        descriptions = [v.description for v in v_signals if v.description]
        desc = descriptions[0] if descriptions else "No visual description"

        if convergence > 0.3:  # Only keep somewhat interesting windows
            windows.append({
                "start": round(t, 2),
                "end": round(w_end, 2),
                "visual_energy": round(v_score, 3),
                "audio_energy": round(a_score, 3),
                "text_hook_strength": round(t_score, 3),
                "convergence_score": round(convergence, 3),
                "active_modalities": active_count,
                "style_tags": style_tags,
                "description": desc,
                "transcript": transcript[:500],
            })

        t += step

    # Sort by convergence score
    windows.sort(key=lambda w: w["convergence_score"], reverse=True)
    return windows


def _merge_overlapping_windows(windows: list[dict], max_gap: float = 3.0) -> list[dict]:
    """Merge overlapping or adjacent high-scoring windows."""
    if not windows:
        return []

    # Sort by start time
    sorted_windows = sorted(windows, key=lambda w: w["start"])
    merged = [sorted_windows[0]]

    for w in sorted_windows[1:]:
        prev = merged[-1]
        if w["start"] <= prev["end"] + max_gap:
            # Merge: extend end, take max scores
            prev["end"] = max(prev["end"], w["end"])
            prev["visual_energy"] = max(prev["visual_energy"], w["visual_energy"])
            prev["audio_energy"] = max(prev["audio_energy"], w["audio_energy"])
            prev["text_hook_strength"] = max(prev["text_hook_strength"], w["text_hook_strength"])
            prev["convergence_score"] = max(prev["convergence_score"], w["convergence_score"])
            prev["active_modalities"] = max(prev["active_modalities"], w["active_modalities"])
            prev["style_tags"] = list(set(prev["style_tags"] + w["style_tags"]))
            if len(w["transcript"]) > len(prev["transcript"]):
                prev["transcript"] = w["transcript"]
        else:
            merged.append(w)

    return merged


def run_fusion(state: PipelineState) -> dict:
    """
    Align 3 modality timelines and find convergence windows.
    Produces a ranked moment map.
    """
    visual = state.get("visual_timeline", [])
    audio = state.get("audio_timeline", [])
    text = state.get("text_segments", [])

    # Find convergence windows
    windows = _find_convergence_windows(visual, audio, text)

    # Take top windows and merge overlapping ones
    top_windows = windows[:30]  # consider top 30
    merged = _merge_overlapping_windows(top_windows)

    # Re-sort merged windows by score
    merged.sort(key=lambda w: w["convergence_score"], reverse=True)

    # Convert to Moment objects
    moment_map = []
    for w in merged:
        moment = Moment(
            start=w["start"],
            end=w["end"],
            visual_energy=w["visual_energy"],
            audio_energy=w["audio_energy"],
            text_hook_strength=w["text_hook_strength"],
            convergence_score=w["convergence_score"],
            style_tags=w["style_tags"],
            description=w["description"],
            transcript=w["transcript"],
        )
        moment_map.append(moment)

    return {"moment_map": moment_map, "analysis_complete": True}
