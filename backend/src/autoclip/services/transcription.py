"""OpenRouter audio-transcription with audio chunking for long videos.

OpenRouter has no dedicated ASR/Whisper endpoint — there is no
`/audio/transcriptions` route the way Groq/OpenAI expose one. Instead this
sends each audio segment as an `input_audio` chat-completion content part
(the OpenAI-compatible audio-input shape) to an audio-capable model
(OPENROUTER_MODEL_AUDIO, default google/gemini-2.5-flash via OpenRouter)
and asks for a structured phrase-level transcript with timestamps.

Known precision tradeoff vs. the old Groq Whisper approach: Whisper gives
true forced-alignment word-level timestamps. A chat-completion model can
only *estimate* phrase-level start/end times from the audio, so per-word
timestamps here are approximated by evenly distributing each phrase's
words across its estimated [start, end] window. This is good enough for
scene/word-boundary snapping in clip_selector, but is not frame-accurate
the way Whisper's word timestamps were — flagged here and in the README.

We still split long audio into ~10-min segments and transcribe them in
parallel (same shape/tunables as before), since a single OpenRouter
chat-completion call has payload-size and latency limits similar to any
other provider.
"""
from __future__ import annotations
import os
import base64
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from pydantic import BaseModel, Field

from autoclip.llm.openrouter import get_audio_model

logger = logging.getLogger(__name__)

TRANSCRIBE_SEGMENT_SECONDS = float(os.getenv("TRANSCRIBE_SEGMENT_SECONDS", "600"))   # 10 min
TRANSCRIBE_SINGLE_SHOT_MAX = float(os.getenv("TRANSCRIBE_SINGLE_SHOT_MAX", "780"))   # 13 min
TRANSCRIBE_PARALLELISM = int(os.getenv("TRANSCRIBE_PARALLELISM", "4"))

SYSTEM_PROMPT = (
    "You are a verbatim audio transcriber. Listen to the supplied audio and "
    "return every spoken phrase in order, each with an estimated start and "
    "end time in seconds relative to the start of THIS audio clip. Do not "
    "summarize or paraphrase — transcribe exactly what is said. Break the "
    "transcript into short phrases (roughly 3-10 words) so timestamps stay "
    "precise."
)


class _Phrase(BaseModel):
    text: str = Field(description="Verbatim phrase text")
    start: float = Field(description="Start time in seconds, relative to this audio clip")
    end: float = Field(description="End time in seconds, relative to this audio clip")


class _TranscriptResult(BaseModel):
    phrases: list[_Phrase] = Field(default_factory=list)


# ─── Helpers ─────────────────────────────────────────────────

def _ffprobe_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _encode_wav(input_path: str, output_path: str) -> str:
    """Re-encode to 16kHz mono WAV — the most broadly-supported input_audio format."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", input_path,
        "-vn", "-ac", "1", "-ar", "16000",
        output_path,
    ]
    subprocess.run(cmd, check=True)
    return output_path


def _split_into_segments(input_path: str, work_dir: str, segment_seconds: float) -> list[tuple[str, float]]:
    pattern = str(Path(work_dir) / "seg_%04d.wav")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", input_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-f", "segment",
        "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1",
        pattern,
    ]
    subprocess.run(cmd, check=True)

    segs = sorted(Path(work_dir).glob("seg_*.wav"))
    return [(str(p), i * segment_seconds) for i, p in enumerate(segs)]


def _words_from_phrase(phrase: _Phrase) -> list[dict]:
    """Approximate per-word timestamps by evenly splitting a phrase's window."""
    tokens = phrase.text.split()
    if not tokens:
        return []
    span = max(phrase.end - phrase.start, 0.01)
    step = span / len(tokens)
    words = []
    for i, tok in enumerate(tokens):
        w_start = phrase.start + i * step
        w_end = phrase.start + (i + 1) * step
        words.append({"text": tok, "start": round(w_start, 3), "end": round(w_end, 3),
                       "confidence": None, "speaker": None})
    return words


# ─── Single-segment transcription ───────────────────────────

def _transcribe_segment(path: str, offset_seconds: float) -> dict:
    """Transcribe one audio file via OpenRouter and offset all timestamps."""
    with open(path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")

    model = get_audio_model().with_structured_output(_TranscriptResult)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Transcribe this audio."},
                {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
            ],
        },
    ]

    try:
        result: _TranscriptResult = model.invoke(messages)
    except Exception as e:
        logger.warning("transcribe segment failed (offset=%.0fs): %s", offset_seconds, e)
        result = _TranscriptResult()

    words: list[dict] = []
    utterances: list[dict] = []
    for p in result.phrases:
        p_offset = _Phrase(text=p.text, start=p.start + offset_seconds, end=p.end + offset_seconds)
        words.extend(_words_from_phrase(p_offset))
        utterances.append({"speaker": "A", "text": p.text.strip(),
                            "start": p_offset.start, "end": p_offset.end})

    text = " ".join(p.text.strip() for p in result.phrases if p.text).strip()
    duration = _ffprobe_duration(path)

    return {"text": text, "words": words, "utterances": utterances,
            "duration": duration, "offset": offset_seconds}


# ─── Public entry ────────────────────────────────────────────

def transcribe_audio(audio_path: str) -> dict:
    """Transcribe audio of any length, splitting and parallelizing if needed.

    Returns the same shape callers already consume:
      { text, words[{text,start,end,confidence,speaker}], utterances[], duration }
    """
    duration = _ffprobe_duration(audio_path)
    logger.info("transcribe_audio: %.1fs source", duration)

    if duration > 0 and duration <= TRANSCRIBE_SINGLE_SHOT_MAX:
        with tempfile.TemporaryDirectory(prefix="atc_tx_") as tmp:
            wav_path = str(Path(tmp) / "audio.wav")
            try:
                _encode_wav(audio_path, wav_path)
                result = _transcribe_segment(wav_path, offset_seconds=0.0)
            except subprocess.CalledProcessError:
                result = _transcribe_segment(audio_path, offset_seconds=0.0)
        result["duration"] = result["duration"] or duration
        result.pop("offset", None)
        return result

    work_dir = tempfile.mkdtemp(prefix="atc_tx_")
    try:
        segments = _split_into_segments(audio_path, work_dir, TRANSCRIBE_SEGMENT_SECONDS)
        logger.info(
            "transcribe_audio: %d segments x %.0fs (parallel=%d)",
            len(segments), TRANSCRIBE_SEGMENT_SECONDS, TRANSCRIBE_PARALLELISM,
        )

        with ThreadPoolExecutor(max_workers=max(1, TRANSCRIBE_PARALLELISM)) as ex:
            results = list(ex.map(lambda s: _transcribe_segment(*s), segments))

        results.sort(key=lambda r: r.get("offset", 0.0))
        merged_text = " ".join((r["text"] or "").strip() for r in results if r["text"]).strip()
        merged_words: list[dict] = []
        merged_utts: list[dict] = []
        for r in results:
            merged_words.extend(r["words"])
            merged_utts.extend(r["utterances"])

        return {
            "text": merged_text,
            "words": merged_words,
            "utterances": merged_utts,
            "duration": duration or (merged_words[-1]["end"] if merged_words else 0.0),
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
