"""Text analysis agent — analyzes transcript for hooks, stories, and semantic segments.

Uses a two-stage approach:
    1. Topic segmentation: Break transcript into coherent topic blocks
       using sentence-level analysis of content shifts.
    2. Hook detection: For each topic segment, classify the hook type
       and strength using Gemini with few-shot examples.

The agent also detects:
    - Narrative arc patterns (setup → conflict → resolution)
    - Curiosity gaps ("you won't believe...", "the truth is...")
    - Quotable one-liners
    - Question-answer patterns
"""
import json
import time
import re
from google import genai
from autoclip.config import GEMINI_API_KEY, GEMINI_RPM_DELAY
from autoclip.pipeline.state import PipelineState, TextSegment


MODEL = "gemini-2.0-flash"

# Patterns that indicate strong hooks (regex-based pre-filter)
HOOK_PATTERNS = {
    "curiosity_gap": [
        r"you won't believe",
        r"here's the thing",
        r"the truth is",
        r"nobody talks about",
        r"what most people don't",
        r"the secret is",
        r"i'm going to tell you",
    ],
    "hot_take": [
        r"i think .+ is wrong",
        r"unpopular opinion",
        r"everyone is wrong about",
        r"stop doing",
        r"this is why .+ fail",
    ],
    "story_opener": [
        r"so (there i was|one day|last)",
        r"let me tell you",
        r"true story",
        r"i remember when",
        r"the moment (i|we|they)",
    ],
    "educational": [
        r"here's how",
        r"the (first|second|third) thing",
        r"step (one|two|three|\d)",
        r"the (key|trick|hack) is",
        r"did you know",
    ],
}


def _pre_scan_hooks(text: str) -> dict[str, float]:
    """Pre-scan text for hook patterns using regex.

    Returns a dict of detected hook types with confidence scores.
    This acts as a fast pre-filter before the LLM analysis.
    """
    text_lower = text.lower()
    detected = {}

    for hook_type, patterns in HOOK_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                detected[hook_type] = max(detected.get(hook_type, 0), 0.6)
                break

    return detected


def _build_segmentation_prompt(transcript_block: str) -> str:
    """Build the LLM prompt for transcript segmentation and hook detection."""
    return f"""You are a content strategist analyzing a video transcript for viral clip potential.

TASK: Identify ALL meaningful segments (5-15 segments). For each:
1. Mark the start and end line numbers
2. Classify the hook type
3. Rate hook strength (0.0-1.0)
4. Label the topic
5. Check if it forms a complete thought

HOOK TYPES (choose one per segment):
- hot_take: Controversial opinion, bold claim, challenges conventional wisdom
- story: Personal anecdote, narrative arc with setup+payoff
- quote: Memorable one-liner, quotable wisdom
- educational: How-to, explanation, teaching moment
- controversial: Debate-worthy, polarizing, provocative
- emotional: Vulnerability, inspiration, strong feeling
- funny: Humor, joke, unexpected twist
- none: Transition, filler, setup without payoff

HOOK STRENGTH GUIDE:
- 0.9-1.0: Would stop someone scrolling. Viral-grade hook.
- 0.7-0.8: Strong engagement. People would watch to the end.
- 0.5-0.6: Decent content. Worth including as a clip.
- 0.3-0.4: Mildly interesting. Filler territory.
- 0.0-0.2: No hook value.

FEW-SHOT EXAMPLES:
- "Nobody talks about the fact that 90% of startups fail because of this one thing" → hot_take, 0.9
- "So there I was, 3am, the server is on fire, and my CEO calls me..." → story, 0.85
- "The three things I wish I knew at 20" → educational, 0.75
- "And that's when I realized I'd been doing it wrong my entire career" → emotional, 0.8

Transcript:
{transcript_block}

Return ONLY a valid JSON array. Each item:
{{"start_line": N, "end_line": N, "hook_type": "...", "hook_strength": 0.X, "topic": "...", "is_complete": true/false}}

JSON:"""


def _detect_narrative_arcs(segments: list[TextSegment]) -> list[TextSegment]:
    """Post-process segments to detect narrative arc patterns.

    Boosts hook strength for segments that are part of a
    setup → conflict → resolution pattern, since these
    create natural clip boundaries with complete stories.
    """
    if len(segments) < 3:
        return segments

    for i in range(len(segments) - 2):
        curr = segments[i]
        next1 = segments[i + 1]
        next2 = segments[i + 2]

        # Look for story + emotional + resolution pattern
        is_arc = (
            curr.hook_type in ("story", "educational") and
            next1.hook_type in ("emotional", "controversial", "hot_take") and
            next2.hook_type in ("story", "quote", "emotional", "funny")
        )

        if is_arc:
            # Boost the climax segment
            next1.hook_strength = min(1.0, next1.hook_strength + 0.1)

    return segments


def _refine_timestamps(
    segments: list[TextSegment],
    utterances: list[dict],
    words: list[dict],
) -> list[TextSegment]:
    """Refine segment timestamps to snap to word boundaries.

    Ensures clips don't start mid-word or mid-sentence.
    """
    for seg in segments:
        # Snap start to nearest word start
        for w in words:
            if w["start"] >= seg.start - 0.3:
                seg.start = w["start"]
                break

        # Snap end to nearest word end
        for w in reversed(words):
            if w["end"] <= seg.end + 0.3:
                seg.end = w["end"]
                break

    return segments


def run_text_agent(state: PipelineState) -> dict:
    """Analyze transcript to identify hooks, stories, and semantic segments.

    Pipeline:
        1. Build numbered transcript from utterances
        2. Pre-scan for hook patterns (regex fast path)
        3. LLM segmentation and hook classification
        4. Detect narrative arcs (multi-segment patterns)
        5. Refine timestamps to word boundaries
    """
    transcript_data = state.get("transcript_data", {})
    utterances = transcript_data.get("utterances", [])
    words = transcript_data.get("words", [])
    full_text = transcript_data.get("text", "")

    if not utterances and full_text:
        utterances = [{"speaker": "A", "text": full_text, "start": 0, "end": 9999}]

    if not utterances:
        return {"text_segments": []}

    # ─── Step 1: Build numbered transcript ────────────────────
    numbered_lines = []
    for i, utt in enumerate(utterances):
        speaker = utt.get("speaker", "?")
        numbered_lines.append(
            f"[{i}] ({utt['start']:.1f}s-{utt['end']:.1f}s) Speaker {speaker}: {utt['text']}"
        )
    transcript_block = "\n".join(numbered_lines)

    # ─── Step 2: Pre-scan for hook patterns ───────────────────
    prescan_hooks = {}
    for utt in utterances:
        hooks = _pre_scan_hooks(utt["text"])
        for hook_type, confidence in hooks.items():
            prescan_hooks[utt["start"]] = (hook_type, confidence)

    # ─── Step 3: LLM segmentation ────────────────────────────
    prompt = _build_segmentation_prompt(transcript_block)
    client = genai.Client(api_key=GEMINI_API_KEY)

    time.sleep(GEMINI_RPM_DELAY)
    response = client.models.generate_content(model=MODEL, contents=prompt)
    text = response.text.strip()

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        segments_raw = json.loads(text.strip())
    except json.JSONDecodeError:
        return {"text_segments": []}

    # ─── Step 4: Convert to TextSegment objects ───────────────
    max_line = len(utterances) - 1
    text_segments = []

    for seg in segments_raw:
        start_line = max(0, min(int(seg.get("start_line", 0)), max_line))
        end_line = max(start_line, min(int(seg.get("end_line", 0)), max_line))

        start_time = utterances[start_line]["start"]
        end_time = utterances[end_line]["end"]
        segment_text = " ".join(u["text"] for u in utterances[start_line:end_line + 1])

        hook_type = seg.get("hook_type", "none")
        hook_strength = float(seg.get("hook_strength", 0.0))

        # Boost hook strength if regex pre-scan also detected a hook
        for ts, (ptype, pconf) in prescan_hooks.items():
            if start_time <= ts <= end_time:
                hook_strength = min(1.0, hook_strength + 0.05)
                break

        text_segments.append(TextSegment(
            start=start_time,
            end=end_time,
            text=segment_text,
            hook_type=hook_type,
            hook_strength=hook_strength,
            topic=seg.get("topic", ""),
            is_complete=bool(seg.get("is_complete", True)),
        ))

    # ─── Step 5: Post-processing ──────────────────────────────
    text_segments = _detect_narrative_arcs(text_segments)
    text_segments = _refine_timestamps(text_segments, utterances, words)

    return {"text_segments": text_segments}
