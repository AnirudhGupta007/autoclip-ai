"""OpenRouter audio-transcription with short, retried, validated segments.

OpenRouter has no dedicated ASR/Whisper endpoint, so each audio segment is
sent as an `input_audio` chat-completion content part to an audio-capable
model (OPENROUTER_MODEL_AUDIO) with a strict JSON schema asking for a
phrase-level transcript with clip-relative timestamps.

Why the segments are short (TRANSCRIBE_SEGMENT_SECONDS, default 180s, hard
cap 240s): a live run on a 98-min film with 600s segments lost ~90% of the
dialogue — 8/10 segments hit the output-token cap (Gemini falls into
repeated-line loops on long audio) and 1 returned invalid JSON, all
swallowed silently. Every segment now goes through:

  1. strict json_schema response_format + adequate max_tokens (8192)
  2. tolerant JSON repair (fences / prose / truncated tail)
  3. degeneracy checks — repetition loops, implausible words/sec,
     timestamps that don't span the clip — which trigger a retry
  4. up to TRANSCRIBE_ATTEMPTS attempts, then a recursive split into
     halves (down to 45s) before giving up and salvaging what parsed
  5. timestamps clamped to the segment, offset by the segment's real
     (ffprobe'd) start, never by `index * nominal_length`

A coverage check compares the transcript's time span against the
non-silent duration of the audio (ffmpeg silencedetect) and logs a warning
below TRANSCRIBE_MIN_COVERAGE. Music/SFX also count as "non-silent", so on
films the ratio is a lower bound — failed/empty segments are reported
separately and are the stronger signal.

Precision note: a chat model only *estimates* phrase start/end; per-word
times are interpolated evenly across each phrase. Good enough for
scene/word-boundary snapping, not frame-accurate like forced alignment.
"""
from __future__ import annotations
import base64
import logging
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from autoclip.config import (
    TRANSCRIBE_SEGMENT_SECONDS as _SEGMENT_ENV,
    TRANSCRIBE_SEGMENT_HARD_MAX,
    TRANSCRIBE_PARALLELISM,
    TRANSCRIBE_MAX_TOKENS,
    TRANSCRIBE_ATTEMPTS,
    TRANSCRIBE_MIN_COVERAGE,
    TRANSCRIBE_TIMESTAMP_FORMAT,
)
from autoclip.llm.openrouter import get_audio_model, extract_json, message_text, finish_reason
from autoclip.pipeline import telemetry

logger = logging.getLogger(__name__)

_SEGMENT_DEFAULT = 180.0   # live-validated: 95.5% word recall on a 98-min film
if _SEGMENT_ENV > TRANSCRIBE_SEGMENT_HARD_MAX:
    # Typically a stale .env from the old 600s default — use the validated
    # default rather than an untested in-between value.
    logger.warning(
        "TRANSCRIBE_SEGMENT_SECONDS=%.0f exceeds the %.0fs hard cap (long segments overflow the "
        "output cap / loop) — using %.0fs. Set TRANSCRIBE_SEGMENT_SECONDS=180 in .env.",
        _SEGMENT_ENV, TRANSCRIBE_SEGMENT_HARD_MAX, _SEGMENT_DEFAULT,
    )
    _SEGMENT_ENV = _SEGMENT_DEFAULT
TRANSCRIBE_SEGMENT_SECONDS = max(30.0, _SEGMENT_ENV)
# Audio up to this length is sent in one call (avoids a tiny trailing segment).
SINGLE_SHOT_MAX = TRANSCRIBE_SEGMENT_SECONDS * 1.25
MIN_SPLIT_SECONDS = 45.0
MAX_SPLIT_DEPTH = 2
MAX_WORDS_PER_SECOND = 5.0      # fast speech is ~3.5 w/s; above this the model is looping/hallucinating
TELEMETRY_LABEL = "audio"
COVERAGE_BIN_S = 20

# Timestamp format the model writes. Gemini's audio docs reference MM:SS;
# "seconds" asks for plain floats. Both are parsed by _to_seconds.
TIMESTAMP_FORMAT = TRANSCRIBE_TIMESTAMP_FORMAT
_MMSS = TIMESTAMP_FORMAT != "seconds"

_TS_RULE = (
    "start and end timestamps as \"MM:SS\" strings (e.g. \"01:23\") measured from the start of THIS audio clip"
    if _MMSS else
    "start and end times in seconds measured from the start of THIS audio clip, as plain numbers (e.g. 83.5)"
)
SYSTEM_PROMPT = (
    "You are a verbatim audio transcriber. Transcribe every spoken line in the "
    "supplied audio, in order, in the language it is spoken (do not translate). "
    "Ignore music, lyrics and sound effects. Each phrase is a short span "
    f"(roughly 3-12 words) with {_TS_RULE}. "
    "Write each phrase exactly once per time it is actually spoken — never "
    "repeat earlier lines to fill silence. If there is no speech, return an "
    "empty list."
)

_TS_SCHEMA = ({"type": "string", "description": "MM:SS from clip start"} if _MMSS
              else {"type": "number", "description": "seconds from clip start"})
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "transcript",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "phrases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": _TS_SCHEMA,
                            "end": _TS_SCHEMA,
                            "text": {"type": "string", "description": "verbatim words"},
                        },
                        "required": ["start", "end", "text"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["phrases"],
            "additionalProperties": False,
        },
    },
}


def _fmt_ts(sec: float) -> str:
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}" if _MMSS else f"{sec:.1f}"


# ─── ffmpeg helpers ──────────────────────────────────────────

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


def _encode_wav(input_path: str, output_path: str, start: float = 0.0,
                duration: Optional[float] = None) -> str:
    """Re-encode (a slice of) the input to 16kHz mono WAV."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", input_path]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", output_path]
    subprocess.run(cmd, check=True)
    return output_path


def _split_into_segments(input_path: str, work_dir: str, segment_seconds: float) -> list[tuple[str, float, float]]:
    """Split into WAV segments. Returns (path, offset, duration) with offsets
    accumulated from each segment's real duration."""
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

    out: list[tuple[str, float, float]] = []
    offset = 0.0
    for p in sorted(Path(work_dir).glob("seg_*.wav")):
        dur = _ffprobe_duration(str(p)) or segment_seconds
        out.append((str(p), offset, dur))
        offset += dur
    return out


def _nonsilent_intervals(path: str, noise_db: int = -35, min_silence: float = 0.6) -> list[tuple[float, float]]:
    """Non-silent [start, end] intervals via ffmpeg silencedetect (speech proxy)."""
    total = _ffprobe_duration(path)
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
           "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    silences: list[list[float]] = []
    for line in res.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            silences.append([max(0.0, float(m.group(1))), total])
            continue
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and silences:
            silences[-1][1] = float(m.group(1))
    out, cur = [], 0.0
    for s, e in silences:
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if total > cur:
        out.append((cur, total))
    return [(s, e) for s, e in out if e - s > 0.05]


def _union_len(intervals: list[tuple[float, float]]) -> float:
    total, cur_s, cur_e = 0.0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def _intersect_len(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """Length of (union of a) ∩ (union of b); both lists are small enough for O(n·m)."""
    a = _merge(a)
    b = _merge(b)
    total, j = 0.0, 0
    for s, e in a:
        while j < len(b) and b[j][1] <= s:
            j += 1
        k = j
        while k < len(b) and b[k][0] < e:
            total += max(0.0, min(e, b[k][1]) - max(s, b[k][0]))
            k += 1
    return total


def _merge(iv: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


# ─── Response validation ─────────────────────────────────────

def _to_seconds(v) -> Optional[float]:
    """Accept 83.5, "83.5", "1:23.5", "01:01:23" → seconds."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        v = v.strip().rstrip("s")
        try:
            if ":" in v:
                secs = 0.0
                for part in v.split(":"):
                    secs = secs * 60 + float(part)
                return secs
            return float(v)
        except ValueError:
            return None
    return None


def _norm(t: str) -> str:
    return " ".join(re.findall(r"\w+", t.lower()))


_MAX_PHRASE_WORDS = 60   # prompt asks for 3-12; anything this long is a run-on/loop


def _squash_tokens(text: str, max_run: int = 4) -> str:
    """Collapse in-phrase token loops ("la la la la la ..." / "no no no ...")."""
    toks = text.split()
    out: list[str] = []
    for t in toks:
        if len(out) >= max_run and all(_norm(o) == _norm(t) for o in out[-max_run:]):
            continue
        out.append(t)
    return " ".join(out)


def _clean_phrases(raw, clip_dur: float) -> list[dict]:
    """Validate/clamp raw phrase dicts to [0, clip_dur]; drop junk; sort."""
    if isinstance(raw, dict):
        raw = raw.get("phrases") or raw.get("segments") or []
    if not isinstance(raw, list):
        return []
    out = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        text = _squash_tokens(str(p.get("text") or "").strip())
        s, e = _to_seconds(p.get("start")), _to_seconds(p.get("end"))
        if not text or s is None or len(text.split()) > _MAX_PHRASE_WORDS:
            continue
        if e is None or e <= s:
            e = s + max(0.6, 0.35 * len(text.split()))
        if s > clip_dur + 2.0:          # beyond the clip — hallucinated time
            continue
        s, e = max(0.0, s), min(e, clip_dur)
        if e <= s:
            e = min(clip_dur, s + 0.5)
        out.append({"text": text, "start": round(s, 3), "end": round(e, 3)})
    out.sort(key=lambda p: p["start"])
    return out


def _loop_start(phrases: list[dict]) -> Optional[int]:
    """Index where a repetition loop starts (≥4 consecutive near-identical
    phrases, or a 1-3 phrase cycle repeating ≥4 times), else None."""
    norms = [_norm(p["text"]) for p in phrases]
    n = len(norms)
    for period in (1, 2, 3):
        for i in range(n - period * 4 + 1):
            block = norms[i:i + period]
            if not any(block):
                continue
            if all(norms[i + k * period:i + (k + 1) * period] == block for k in range(1, 4)):
                return i
    return None


def _degeneracy(phrases: list[dict], clip_dur: float,
                voiced: Optional[list[tuple[float, float]]] = None) -> Optional[str]:
    """Return a reason string if the transcript looks like a model failure."""
    if not phrases:
        return None
    if _loop_start(phrases) is not None:
        return "repetition_loop"
    n_words = sum(len(p["text"].split()) for p in phrases)
    if clip_dur > 20 and n_words / clip_dur > MAX_WORDS_PER_SECOND:
        return f"implausible_rate({n_words / clip_dur:.1f} w/s)"
    norms = [_norm(p["text"]) for p in phrases if len(p["text"].split()) >= 3]
    if len(norms) >= 12:
        top, cnt = Counter(norms).most_common(1)[0]
        if cnt / len(norms) > 0.25:
            return f"repeated_line({cnt}x)"
    # Timestamps squeezed into a sliver of a long clip (e.g. MM.SS floats).
    if clip_dur >= 90 and len(phrases) >= 10 and phrases[-1]["end"] < 0.2 * clip_dur:
        return "timestamps_compressed"
    # Model quietly stopped part-way (live-seen on 360s clips: transcript ended
    # at 170s with dialogue continuing). Judged against non-silent audio after
    # the last phrase; music can trigger it too, which only costs a retry/split.
    if voiced:
        last_end = max(p["end"] for p in phrases)
        tail = _intersect_len(voiced, [(last_end + 5.0, clip_dur)])
        if tail > max(30.0, 0.3 * clip_dur):
            return f"stopped_early(last={last_end:.0f}s, {tail:.0f}s voiced after)"
    return None


def _span(phrases: list[dict]) -> float:
    """Seconds of clip covered by phrases (used to pick the best salvage)."""
    return _union_len([(p["start"], p["end"] + 1.0) for p in phrases])


def _salvage(phrases: list[dict]) -> list[dict]:
    """Keep the pre-loop prefix and drop consecutive duplicates."""
    i = _loop_start(phrases)
    if i is not None:
        phrases = phrases[: i + 1]
    out: list[dict] = []
    for p in phrases:
        if out and _norm(out[-1]["text"]) == _norm(p["text"]):
            continue
        out.append(p)
    return out


# ─── Model call ──────────────────────────────────────────────

def _call_model(audio_b64: str, clip_dur: float, attempt: int,
                voiced: Optional[list[tuple[float, float]]] = None) -> tuple[list[dict], Optional[str]]:
    """One transcription call. Returns (phrases relative to clip, problem|None)."""
    model = get_audio_model(
        temperature=0.0 if attempt == 0 else 0.2 * attempt,
        max_tokens=TRANSCRIBE_MAX_TOKENS,
    )
    # response_format goes via extra_body so LangChain doesn't treat it as a
    # structured-output request — that path raises on finish_reason=length
    # and throws away the (repairable) partial JSON.
    extra = {"response_format": RESPONSE_FORMAT}
    if attempt > 0:
        extra["frequency_penalty"] = 0.3   # nudges a looping model off repeated lines
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    f"This audio clip is {_fmt_ts(clip_dur)} long; every timestamp must be "
                    f"between {_fmt_ts(0)} and {_fmt_ts(clip_dur)}. Transcribe it."
                )},
                {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
            ],
        },
    ]
    try:
        msg = model.invoke(messages, extra_body=extra)
    except Exception as e:
        return [], f"request_error: {str(e)[:300]}"
    telemetry.record_openrouter_call(msg, model_label=TELEMETRY_LABEL)

    data = extract_json(message_text(msg))
    if data is None:
        return [], "invalid_json"
    phrases = _clean_phrases(data, clip_dur)
    if finish_reason(msg) == "length":
        return phrases, "truncated(max_tokens)"
    problem = _degeneracy(phrases, clip_dur, voiced)
    return phrases, problem


def _transcribe_file(path: str, clip_dur: float, depth: int = 0) -> tuple[list[dict], bool]:
    """Transcribe one WAV with retries, then split-in-half fallback.

    Returns (phrases relative to this file, ok). ok=False means the result
    is a best-effort salvage after every attempt failed.
    """
    with open(path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")

    try:
        voiced = _nonsilent_intervals(path)
    except Exception:
        voiced = None

    best: list[dict] = []
    problem: Optional[str] = None
    for attempt in range(max(1, TRANSCRIBE_ATTEMPTS)):
        phrases, problem = _call_model(audio_b64, clip_dur, attempt, voiced)
        if problem is None:
            return phrases, True
        salvaged = _salvage(phrases)
        if _span(salvaged) > _span(best):
            best = salvaged
        if attempt + 1 < TRANSCRIBE_ATTEMPTS:
            telemetry.record_retry(TELEMETRY_LABEL, f"{Path(path).name} attempt {attempt + 1}: {problem}")

    if depth < MAX_SPLIT_DEPTH and clip_dur >= 2 * MIN_SPLIT_SECONDS:
        half = clip_dur / 2.0
        logger.warning("transcribe: %s failed %d attempts (%s) — splitting into 2×%.0fs",
                       Path(path).name, TRANSCRIBE_ATTEMPTS, problem, half)
        merged: list[dict] = []
        all_ok = True
        work = Path(path).with_suffix("")
        for k, (start, dur) in enumerate(((0.0, half), (half, clip_dur - half))):
            sub = f"{work}_h{depth}{k}.wav"
            try:
                _encode_wav(path, sub, start=start, duration=dur)
                sub_phrases, ok = _transcribe_file(sub, _ffprobe_duration(sub) or dur, depth + 1)
            finally:
                Path(sub).unlink(missing_ok=True)
            all_ok &= ok
            merged.extend({**p, "start": p["start"] + start, "end": p["end"] + start} for p in sub_phrases)
        return merged, all_ok

    telemetry.record_failure(TELEMETRY_LABEL, f"{Path(path).name}: {problem} — salvaged {len(best)} phrases")
    return best, False


# ─── Assembly ────────────────────────────────────────────────

def _words_from_phrase(text: str, start: float, end: float) -> list[dict]:
    """Approximate per-word timestamps by evenly splitting a phrase's window."""
    tokens = text.split()
    if not tokens:
        return []
    step = max(end - start, 0.01) / len(tokens)
    return [{"text": tok, "start": round(start + i * step, 3), "end": round(start + (i + 1) * step, 3),
             "confidence": None, "speaker": None} for i, tok in enumerate(tokens)]


def _transcribe_segment(path: str, offset_seconds: float, clip_dur: Optional[float] = None) -> dict:
    clip_dur = clip_dur or _ffprobe_duration(path)
    try:
        phrases, ok = _transcribe_file(path, clip_dur)
    except Exception as e:     # ffmpeg/IO — never kill the whole transcript for one segment
        telemetry.record_failure(TELEMETRY_LABEL, f"segment@{offset_seconds:.0f}s: {e}")
        phrases, ok = [], False
    words: list[dict] = []
    utterances: list[dict] = []
    for p in phrases:
        s, e = p["start"] + offset_seconds, p["end"] + offset_seconds
        words.extend(_words_from_phrase(p["text"], s, e))
        utterances.append({"speaker": "A", "text": p["text"], "start": round(s, 3), "end": round(e, 3)})
    return {
        "text": " ".join(p["text"] for p in phrases).strip(),
        "words": words, "utterances": utterances,
        "duration": clip_dur, "offset": offset_seconds, "ok": ok,
    }


def _coverage(audio_path: str, utterances: list[dict], segments: list[dict]) -> dict:
    """Transcript time-coverage of non-silent audio + failed/empty segment report."""
    try:
        voiced = _nonsilent_intervals(audio_path)
    except Exception as e:
        logger.debug("silencedetect failed: %s", e)
        voiced = []
    voiced_len = _union_len(voiced)
    # Pad phrases slightly: model timestamps are estimates and pauses inside lines are voiced.
    covered = [(u["start"] - 1.0, u["end"] + 1.0) for u in utterances]
    time_ratio = (_intersect_len(covered, voiced) / voiced_len) if voiced_len > 0 else 1.0
    # Primary metric: of the COVERAGE_BIN_S windows that are mostly non-silent,
    # what fraction contain at least one transcribed phrase. Robust to pauses
    # between lines; a dead model leaves whole bins empty.
    total = max([s["offset"] + s["duration"] for s in segments] + [0.0])
    voiced_bins = covered_bins = 0
    starts = sorted(u["start"] for u in utterances)
    t = 0.0
    while t < total:
        b_end = min(t + COVERAGE_BIN_S, total)
        if b_end - t >= 5 and _intersect_len(voiced, [(t, b_end)]) > 0.5 * (b_end - t):
            voiced_bins += 1
            if any(t - 1 <= st < b_end + 1 for st in starts):
                covered_bins += 1
        t = b_end
    ratio = covered_bins / voiced_bins if voiced_bins else 1.0
    failed = [round(s["offset"], 1) for s in segments if not s.get("ok", True)]
    empty = [round(s["offset"], 1) for s in segments
             if not s["utterances"] and _intersect_len(voiced, [(s["offset"], s["offset"] + s["duration"])])
             > 0.3 * s["duration"]]
    return {"ratio": round(ratio, 3), "voiced_bins": voiced_bins, "bin_seconds": COVERAGE_BIN_S,
            "time_ratio": round(time_ratio, 3), "nonsilent_seconds": round(voiced_len, 1),
            "failed_segment_offsets": failed, "empty_voiced_segment_offsets": empty,
            "segments": len(segments)}


def transcribe_audio(audio_path: str) -> dict:
    """Transcribe audio of any length, splitting and parallelizing if needed.

    Returns the shape callers already consume —
      { text, words[{text,start,end,confidence,speaker}], utterances[], duration }
    — plus a `coverage` diagnostics dict.
    """
    duration = _ffprobe_duration(audio_path)
    logger.info("transcribe_audio: %.1fs source", duration)

    work_dir = tempfile.mkdtemp(prefix="atc_tx_")
    try:
        if 0 < duration <= SINGLE_SHOT_MAX:
            wav_path = str(Path(work_dir) / "audio.wav")
            try:
                _encode_wav(audio_path, wav_path)
            except subprocess.CalledProcessError:
                wav_path = audio_path
            segments = [(wav_path, 0.0, _ffprobe_duration(wav_path) or duration)]
        else:
            segments = _split_into_segments(audio_path, work_dir, TRANSCRIBE_SEGMENT_SECONDS)
        logger.info("transcribe_audio: %d segment(s) x ≤%.0fs (parallel=%d)",
                    len(segments), TRANSCRIBE_SEGMENT_SECONDS, TRANSCRIBE_PARALLELISM)

        with ThreadPoolExecutor(max_workers=max(1, TRANSCRIBE_PARALLELISM)) as ex:
            results = list(ex.map(lambda s: _transcribe_segment(*s), segments))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    results.sort(key=lambda r: r["offset"])
    merged_words: list[dict] = []
    merged_utts: list[dict] = []
    for r in results:
        merged_words.extend(r["words"])
        merged_utts.extend(r["utterances"])

    coverage = _coverage(audio_path, merged_utts, results)
    level = logging.WARNING if (
        coverage["ratio"] < TRANSCRIBE_MIN_COVERAGE
        or coverage["failed_segment_offsets"] or coverage["empty_voiced_segment_offsets"]
    ) else logging.INFO
    logger.log(
        level,
        "transcribe_audio: coverage=%.0f%% of %d non-silent %ds windows contain transcript (min %.0f%%; "
        "music/SFX count as non-silent, so this is a lower bound; phrase-time coverage %.0f%%); "
        "%d/%d segments failed %s; voiced-but-empty segments %s",
        coverage["ratio"] * 100, coverage["voiced_bins"], COVERAGE_BIN_S, TRANSCRIBE_MIN_COVERAGE * 100,
        coverage["time_ratio"] * 100,
        len(coverage["failed_segment_offsets"]), len(results), coverage["failed_segment_offsets"],
        coverage["empty_voiced_segment_offsets"],
    )

    return {
        "text": " ".join(r["text"] for r in results if r["text"]).strip(),
        "words": merged_words,
        "utterances": merged_utts,
        "duration": duration or (merged_words[-1]["end"] if merged_words else 0.0),
        "coverage": coverage,
    }
