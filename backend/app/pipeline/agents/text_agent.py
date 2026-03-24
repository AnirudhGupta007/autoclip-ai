"""Text analysis agent — analyzes transcript for hooks, stories, and semantic segments."""
import json
import time
from google import genai
from app.config import GEMINI_API_KEY, GEMINI_RPM_DELAY
from app.pipeline.state import PipelineState, TextSegment


def run_text_agent(state: PipelineState) -> dict:
    """
    Analyze transcript using Gemini to identify semantic segments,
    hooks, and content types. Produces a list of text segments.
    """
    transcript_data = state.get("transcript_data", {})
    utterances = transcript_data.get("utterances", [])
    full_text = transcript_data.get("text", "")

    if not utterances and full_text:
        utterances = [{"speaker": "A", "text": full_text, "start": 0, "end": 9999}]

    if not utterances:
        return {"text_segments": []}

    # Build numbered transcript for LLM
    numbered_lines = []
    for i, utt in enumerate(utterances):
        speaker = utt.get("speaker", "?")
        numbered_lines.append(f"[{i}] ({utt['start']:.1f}s-{utt['end']:.1f}s) Speaker {speaker}: {utt['text']}")

    transcript_block = "\n".join(numbered_lines)

    prompt = f"""You are a content strategist analyzing a video transcript.
Identify ALL meaningful segments (not just viral ones). For each segment, classify it.

Transcript:
{transcript_block}

For each segment, return:
- "start_line": starting line number [N]
- "end_line": ending line number [N]
- "hook_type": one of (hot_take, story, quote, educational, controversial, emotional, funny, none)
- "hook_strength": 0.0 to 1.0 — how strong is the hook?
- "topic": brief topic label (3-5 words)
- "is_complete": does this segment form a complete thought? (true/false)

Return ONLY a valid JSON array. Identify 5-15 segments covering most of the transcript.
Segments can overlap slightly if a moment fits multiple categories.

JSON:"""

    client = genai.Client(api_key=GEMINI_API_KEY)
    time.sleep(GEMINI_RPM_DELAY)
    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    text = response.text.strip()

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        segments_raw = json.loads(text.strip())
    except json.JSONDecodeError:
        return {"text_segments": []}

    # Convert line numbers to timestamps
    text_segments = []
    max_line = len(utterances) - 1

    for seg in segments_raw:
        start_line = max(0, min(int(seg.get("start_line", 0)), max_line))
        end_line = max(start_line, min(int(seg.get("end_line", 0)), max_line))

        start_time = utterances[start_line]["start"]
        end_time = utterances[end_line]["end"]
        segment_text = " ".join(u["text"] for u in utterances[start_line:end_line + 1])

        text_segment = TextSegment(
            start=start_time,
            end=end_time,
            text=segment_text,
            hook_type=seg.get("hook_type", "none"),
            hook_strength=float(seg.get("hook_strength", 0.0)),
            topic=seg.get("topic", ""),
            is_complete=bool(seg.get("is_complete", True)),
        )
        text_segments.append(text_segment)

    return {"text_segments": text_segments}
