"""Gemini LLM integration for chunking and engagement scoring."""
import json
import time
from google import genai
from autoclip.config import GEMINI_API_KEY, GEMINI_RPM_DELAY

_client = None
MODEL = "gemini-2.0-flash"


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def chunk_transcript(transcript_text: str, utterances: list[dict]) -> list[dict]:
    """
    Use Gemini to identify viral-worthy segments from transcript.
    Returns list of chunks with title, start/end line numbers.
    """
    numbered_lines = []
    for i, utt in enumerate(utterances):
        speaker = utt.get("speaker", "?")
        numbered_lines.append(f"[{i}] Speaker {speaker}: {utt['text']}")

    transcript_block = "\n".join(numbered_lines)

    prompt = f"""You are a viral content expert. Analyze this transcript and identify 3-6 segments
that would make compelling short-form video clips (30-90 seconds each).

Look for:
- Surprising statements or hot takes
- Emotional moments (funny, shocking, inspiring)
- Clear standalone stories or anecdotes
- Quotable one-liners or wisdom
- Dramatic tension or conflict
- Educational "did you know" moments

Transcript:
{transcript_block}

Return ONLY valid JSON array. Each item must have:
- "title": catchy clip title (max 60 chars)
- "start_line": starting line number
- "end_line": ending line number
- "hook": why this segment is engaging (1 sentence)

Example: [{{"title": "The moment everything changed", "start_line": 5, "end_line": 12, "hook": "Unexpected plot twist that hooks viewers"}}]

JSON:"""

    response = _get_client().models.generate_content(model=MODEL, contents=prompt)
    text = response.text.strip()

    # Extract JSON from response
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    chunks = json.loads(text.strip())

    # Validate and clamp line numbers
    max_line = len(utterances) - 1
    validated = []
    for chunk in chunks:
        start = max(0, min(int(chunk["start_line"]), max_line))
        end = max(start, min(int(chunk["end_line"]), max_line))
        validated.append({
            "title": chunk["title"][:60],
            "start_line": start,
            "end_line": end,
            "hook": chunk.get("hook", ""),
        })

    return validated


def score_chunk(chunk_text: str, title: str) -> dict:
    """
    Score a transcript chunk on 6 engagement dimensions using Gemini.
    Returns scores dict with overall score.
    """
    prompt = f"""Rate this video clip transcript on 6 dimensions (each 1-10).
Be critical — only truly exceptional content gets 9-10.

Clip title: {title}
Transcript: {chunk_text}

Dimensions:
1. Hook Strength — Does the opening grab attention in first 3 seconds?
2. Emotional Impact — Does it make viewers feel something strong?
3. Shareability — Would people tag friends or repost this?
4. Retention — Does it keep viewers watching until the end?
5. Controversy/Debate — Does it spark discussion in comments?
6. Novelty — Is the insight/story fresh and surprising?

Return ONLY valid JSON:
{{"hook": N, "emotion": N, "shareability": N, "retention": N, "controversy": N, "novelty": N}}

JSON:"""

    time.sleep(GEMINI_RPM_DELAY)
    response = _get_client().models.generate_content(model=MODEL, contents=prompt)
    text = response.text.strip()

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    scores = json.loads(text.strip())

    weights = {
        "hook": 0.20, "emotion": 0.20, "shareability": 0.15,
        "retention": 0.20, "controversy": 0.10, "novelty": 0.15
    }
    overall = sum(scores.get(k, 5) * w for k, w in weights.items())
    scores["overall"] = round(overall, 2)

    return scores
