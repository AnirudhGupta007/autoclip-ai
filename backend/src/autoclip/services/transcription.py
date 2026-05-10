"""Groq Whisper Turbo transcription with audio chunking for long videos.

Groq's API caps audio uploads at 25 MB. WAV at 16 kHz mono PCM hits that
around 13 min, so for 2+ hr podcasts we must split the audio first.
This module re-encodes to Opus (small) and splits into ~10-min segments,
then transcribes them in parallel and merges with absolute timestamp offsets.
"""
from __future__ import annotations
import os
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from groq import Groq
from autoclip.config import GROQ_API_KEY, GROQ_TRANSCRIPTION_MODEL

logger = logging.getLogger(__name__)

# Tunables — env-overridable so we can dial in per-deployment.
TRANSCRIBE_SEGMENT_SECONDS = float(os.getenv("TRANSCRIBE_SEGMENT_SECONDS", "600"))   # 10 min
TRANSCRIBE_SINGLE_SHOT_MAX = float(os.getenv("TRANSCRIBE_SINGLE_SHOT_MAX", "780"))   # 13 min
TRANSCRIBE_PARALLELISM = int(os.getenv("TRANSCRIBE_PARALLELISM", "4"))


# ─── Helpers ─────────────────────────────────────────────────

def _g(obj, key):
    return obj[key] if isinstance(obj, dict) else getattr(obj, key, None)


def _ffprobe_duration(path: str) -> float:
    """Return audio/video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _encode_opus(input_path: str, output_path: str) -> str:
    """Re-encode audio to Opus mono — ~10x smaller than WAV at usable quality."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", input_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libopus", "-b:a", "32k",
        output_path,
    ]
    subprocess.run(cmd, check=True)
    return output_path


def _split_into_segments(input_path: str, work_dir: str, segment_seconds: float) -> list[tuple[str, float]]:
    """Re-encode + split the audio into Opus segments. Returns [(path, start_offset_s), ...]."""
    pattern = str(Path(work_dir) / "seg_%04d.opus")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", input_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libopus", "-b:a", "32k",
        "-f", "segment",
        "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1",
        pattern,
    ]
    subprocess.run(cmd, check=True)

    segs = sorted(Path(work_dir).glob("seg_*.opus"))
    out: list[tuple[str, float]] = []
    for i, p in enumerate(segs):
        out.append((str(p), i * segment_seconds))
    return out


# ─── Single-segment transcription ───────────────────────────

def _transcribe_segment(path: str, offset_seconds: float) -> dict:
    """Transcribe one audio file via Groq and offset all timestamps by `offset_seconds`."""
    client = Groq(api_key=GROQ_API_KEY)
    with open(path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=f,
            model=GROQ_TRANSCRIPTION_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )

    raw_words = getattr(result, "words", None) or []
    words = [
        {
            "text": _g(w, "word") or _g(w, "text") or "",
            "start": float(_g(w, "start") or 0.0) + offset_seconds,
            "end": float(_g(w, "end") or 0.0) + offset_seconds,
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
            "start": float(_g(s, "start") or 0.0) + offset_seconds,
            "end": float(_g(s, "end") or 0.0) + offset_seconds,
        }
        for s in raw_segments
    ]

    duration = float(getattr(result, "duration", 0.0) or 0.0)

    return {
        "text": getattr(result, "text", "") or "",
        "words": words,
        "utterances": utterances,
        "duration": duration,
        "offset": offset_seconds,
    }


# ─── Public entry ────────────────────────────────────────────

def transcribe_audio(audio_path: str) -> dict:
    """Transcribe audio of any length, splitting and parallelizing if needed.

    Returns the same shape callers already consume:
      { text, words[{text,start,end,confidence,speaker}], utterances[], duration }
    """
    duration = _ffprobe_duration(audio_path)
    logger.info("transcribe_audio: %.1fs source", duration)

    # Short enough to send in one shot — but still re-encode to Opus to keep
    # us under 25 MB on long-but-under-13min recordings.
    if duration > 0 and duration <= TRANSCRIBE_SINGLE_SHOT_MAX:
        with tempfile.TemporaryDirectory(prefix="atc_tx_") as tmp:
            opus_path = str(Path(tmp) / "audio.opus")
            try:
                _encode_opus(audio_path, opus_path)
                result = _transcribe_segment(opus_path, offset_seconds=0.0)
            except subprocess.CalledProcessError:
                # If ffmpeg/Opus isn't available, fall back to the original file
                result = _transcribe_segment(audio_path, offset_seconds=0.0)
        result["duration"] = result["duration"] or duration
        result.pop("offset", None)
        return result

    # Long-form: split + parallel
    work_dir = tempfile.mkdtemp(prefix="atc_tx_")
    try:
        segments = _split_into_segments(audio_path, work_dir, TRANSCRIBE_SEGMENT_SECONDS)
        logger.info(
            "transcribe_audio: %d segments × %.0fs (parallel=%d)",
            len(segments), TRANSCRIBE_SEGMENT_SECONDS, TRANSCRIBE_PARALLELISM,
        )

        with ThreadPoolExecutor(max_workers=max(1, TRANSCRIBE_PARALLELISM)) as ex:
            results = list(ex.map(lambda s: _transcribe_segment(*s), segments))

        # Merge in segment order
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
