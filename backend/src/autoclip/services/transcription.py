"""Groq Whisper Turbo transcription — 216x realtime, word-level timestamps."""
from groq import Groq
from autoclip.config import GROQ_API_KEY, GROQ_TRANSCRIPTION_MODEL


def transcribe_audio(audio_path: str) -> dict:
    """
    Transcribe audio with Groq's whisper-large-v3-turbo.

    Same return shape as the previous AssemblyAI impl so callers don't change:
    { text, words[{text,start,end,confidence,speaker}], utterances[], duration }

    Groq has no native diarization (speaker is None) and a 25 MB file limit;
    Phase 2's chunk_planner handles long videos by splitting upstream.
    """
    client = Groq(api_key=GROQ_API_KEY)

    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=f,
            model=GROQ_TRANSCRIPTION_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )

    def _g(obj, key):
        return obj[key] if isinstance(obj, dict) else getattr(obj, key, None)

    raw_words = getattr(result, "words", None) or []
    words = [
        {
            "text": _g(w, "word") or _g(w, "text") or "",
            "start": float(_g(w, "start") or 0.0),
            "end": float(_g(w, "end") or 0.0),
            "confidence": None,
            "speaker": None,
        }
        for w in raw_words
    ]

    raw_segments = getattr(result, "segments", None) or []
    utterances = [
        {
            "speaker": "A",
            "text": (_g(s, "text") or "").strip(),
            "start": float(_g(s, "start") or 0.0),
            "end": float(_g(s, "end") or 0.0),
        }
        for s in raw_segments
    ]

    duration = float(getattr(result, "duration", 0.0) or 0.0)
    if not duration and words:
        duration = words[-1]["end"]

    return {
        "text": getattr(result, "text", "") or "",
        "words": words,
        "utterances": utterances,
        "duration": duration,
    }
