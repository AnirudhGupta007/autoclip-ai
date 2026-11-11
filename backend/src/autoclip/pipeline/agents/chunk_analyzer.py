"""Chunk analyzer — one OpenRouter vision call per video chunk.

Two input modes (VISION_INPUT_MODE):

  frames (default) — VISION_MAX_FRAMES JPEGs sampled *evenly across the
      whole chunk* (spacing = chunk_len / N, frame i at (i+0.5)·spacing),
      each preceded by a text label with its chunk-relative time, sent as
      `image_url` data-URI parts. The model cannot hear audio in this mode;
      audio_energy is inferred from the transcript and visible reactions.
  video — the chunk re-encoded small (VISION_VIDEO_HEIGHT, H.264+AAC) and
      sent as one native `video_url` data-URI part. Live-verified on
      OpenRouter with google/gemini-2.5-flash-lite: the model sees ~1 fps
      (258 tokens/frame regardless of resolution) and also hears the audio
      track (~25 tokens/s), so a 120s chunk costs ~34k input tokens vs ~6k
      for 24 frames. If a video call fails outright, the chunk falls back
      to frames mode once.

Podcast savings: an audio upload (ChunkPlan.media_kind="audio", an
audiogram) gets NO frames and a transcript-only prompt. In frames mode a
cheap static-shot check groups the sampled frames by pixel difference; if
they show <= VISION_STATIC_FRAMES distinct looks (fixed podcast camera, or a
few angles) only one frame per look is sent (padded to that many).

Robustness (live-run fixes): retries (CHUNK_ANALYZE_ATTEMPTS) with
tolerant JSON repair; per-moment validation so one bad field doesn't
discard the whole chunk; failures logged and counted in telemetry. The
model returns times relative to the chunk; absolute times are detected
and converted; every moment is clamped to [chunk_start, chunk_end] or
discarded if it mostly lies outside. The transcript window holds ONLY the
words inside this chunk (never a whole-video fallback).

Scratch files live in OUTPUT_DIR/{video_id}/chunks/chunk_NNN/, are cleared
before use and deleted after analysis (uploads are all named source.*, so
the old outputs/chunks/source_{i}.* paths collided across videos).

Runs once per chunk under LangGraph's Send-API fan-out.
"""
from __future__ import annotations
import base64
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from autoclip.config import (
    OUTPUT_DIR,
    VISION_INPUT_MODE,
    VISION_MAX_FRAMES,
    VISION_FRAME_WIDTH,
    VISION_VIDEO_HEIGHT,
    VISION_MAX_TOKENS,
    CHUNK_ANALYZE_ATTEMPTS,
    VISION_FFMPEG_CONCURRENCY,
    VISION_STATIC_CHECK,
    VISION_STATIC_FRAMES,
    VISION_STATIC_DIFF,
)
from autoclip.llm.openrouter import get_vision_model, extract_json, message_text, finish_reason
from autoclip.pipeline.state import PipelineState, Moment, ChunkPlan
from autoclip.pipeline import telemetry

logger = logging.getLogger(__name__)

TELEMETRY_LABEL = "vision"
MAX_MOMENTS = 5
MIN_MOMENT_S = 3.0
MAX_TRANSCRIPT_CHARS = 6000
STYLE_TAGS = ["hot_take", "story", "quote", "educational",
              "controversial", "emotional", "funny", "story_beat"]
# LangGraph fans every chunk out at once (thread pool of ~cpu+4); the LLM
# calls are cheap to overlap but each ffmpeg decode is ~100 MB RSS, so frame
# sampling / video re-encoding is bounded separately.
_FFMPEG_SLOTS = threading.BoundedSemaphore(max(1, VISION_FFMPEG_CONCURRENCY))
# Back-compat names (older scripts import these).
MAX_SAMPLED_FRAMES = VISION_MAX_FRAMES


# ─── Prompt + schema ─────────────────────────────────────────

_SYSTEM_COMMON = """You are a video clip-curation expert. Identify up to 5 moments \
inside this video chunk that would make great viral short-form clips.

A great moment has at least one of:
  • a strong verbal hook (hot take, surprising claim, story beat, punchline, tight quote)
  • visual energy (gestures, reactions, action, scene change, on-screen text)
  • audio energy (laughter, applause, shouting, pitch swing, dramatic pause + payoff)

Rules:
  1. Timestamps are SECONDS FROM THE START OF THIS CHUNK (0 = first instant of \
the chunk, never more than the chunk length). Do not add any offset.
  2. Each moment is 5-30 seconds and lies entirely inside the chunk.
  3. Quality over quantity. Return 0-5 moments. Empty is acceptable.
  4. convergence_score > 0.7 ONLY when 2+ modalities co-fire — be strict, \
this drives downstream ranking.
  5. transcript must be copied verbatim from the supplied transcript lines for \
that time range ("" if none) — never invent dialogue.
  6. description says concretely what is seen/heard (who, what action), <200 chars.
"""

_SYSTEM_FRAMES = _SYSTEM_COMMON + """
Input: still frames sampled evenly across the chunk, each labelled with its \
time (seconds from chunk start), plus the chunk's transcript lines. You cannot \
hear the audio — infer audio energy from the transcript and visible reactions. \
Use the frame labels to place moments in time.
"""

_SYSTEM_VIDEO = _SYSTEM_COMMON + """
Input: the chunk itself as a video WITH its audio track, plus a machine \
transcript of the chunk (may have gaps). Use what you see and hear; the video's \
own timeline (starting at 0) is the time base.
"""

_SYSTEM_AUDIO = _SYSTEM_COMMON + """
Input: an AUDIO-ONLY episode (podcast/talk) — there is nothing to see, only \
the transcript lines of this chunk. Judge moments by what is said: hooks, \
stories, strong opinions, jokes, quotable lines, clear advice. Set \
visual_energy to 0; infer audio energy from the words (laughter, emphasis). \
description says who is talking and about what, <200 chars.
"""

_NUM01 = {"type": "number", "minimum": 0, "maximum": 1}
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "chunk_moments",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "moments": {
                    "type": "array",
                    "maxItems": MAX_MOMENTS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "number", "description": "seconds from chunk start"},
                            "end": {"type": "number", "description": "seconds from chunk start"},
                            "description": {"type": "string"},
                            "transcript": {"type": "string"},
                            "style_tags": {"type": "array", "items": {"type": "string", "enum": STYLE_TAGS}},
                            "visual_energy": _NUM01,
                            "audio_energy": _NUM01,
                            "text_hook_strength": _NUM01,
                            "convergence_score": _NUM01,
                        },
                        "required": ["start", "end", "description", "transcript", "style_tags",
                                     "visual_energy", "audio_energy", "text_hook_strength",
                                     "convergence_score"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["moments"],
            "additionalProperties": False,
        },
    },
}


# ─── Helpers ─────────────────────────────────────────────────

def _slice_transcript(transcript_data: dict, start: float, end: float) -> str:
    """Transcript lines inside [start, end], labelled with chunk-relative times.

    Only this window's words — if the window has none, an explicit
    "no dialogue" note (the old whole-transcript fallback fed every
    silent chunk the film's ending).
    """
    transcript_data = transcript_data or {}
    utts = [u for u in (transcript_data.get("utterances") or [])
            if u.get("start", 0) < end and u.get("end", 0) > start and (u.get("text") or "").strip()]
    if utts:
        lines = [f"[{max(0.0, u['start'] - start):5.1f}s] {u['text'].strip()}" for u in utts]
    else:
        words = [w for w in (transcript_data.get("words") or [])
                 if w.get("start", 0) < end and w.get("end", 0) > start]
        lines = []
        if words:   # group words into ~5s lines
            cur, cur_t = [], None
            for w in words:
                if cur_t is None or w["start"] - cur_t > 5:
                    if cur:
                        lines.append(f"[{max(0.0, cur_t - start):5.1f}s] {' '.join(cur)}")
                    cur, cur_t = [], w["start"]
                cur.append(w["text"])
            if cur:
                lines.append(f"[{max(0.0, cur_t - start):5.1f}s] {' '.join(cur)}")
    text = "\n".join(lines).strip()
    if not text:
        return "(no dialogue transcribed in this window)"
    return text[:MAX_TRANSCRIPT_CHARS]


def _work_dir(plan: ChunkPlan, video_id: Optional[str]) -> Path:
    """Per-video, per-chunk scratch dir, emptied before use."""
    vid = video_id or Path(plan.video_path).resolve().parent.name or Path(plan.video_path).stem
    d = Path(OUTPUT_DIR) / vid / "chunks" / f"chunk_{plan.index:03d}"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _frame_times(chunk_len: float, n: int) -> list[float]:
    """n chunk-relative timestamps spread evenly across the whole chunk."""
    n = max(1, min(n, int(chunk_len) or 1))
    spacing = chunk_len / n
    return [round((i + 0.5) * spacing, 2) for i in range(n)]


def _sample_frames(video_path: str, chunk_start: float, times: list[float], out_dir: Path,
                   width: int = VISION_FRAME_WIDTH) -> list[tuple[float, str]]:
    """Grab one JPEG per timestamp straight from the source (accurate input
    seek per frame). Returns [(relative_time, path)] that exist.

    One short ffmpeg process per frame, sequentially: a single process with
    N `-i` inputs opens N decoders at once — measured 1.3 GB peak RSS for
    24 inputs of a 720p AV1 film vs ~110 MB per sequential call, at about
    the same wall time (~5s/chunk).
    """
    outs = []
    for i, t in enumerate(times):
        p = out_dir / f"f_{i:03d}.jpg"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{chunk_start + t:.3f}", "-i", video_path,
               "-map", "0:v:0", "-frames:v", "1",
               "-vf", f"scale='min({width},iw)':-2", "-q:v", "4", str(p)]
        try:
            subprocess.run(cmd, check=True, timeout=60)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.debug("frame @%.1fs failed: %s", chunk_start + t, e)
            continue
        outs.append((t, p))
    if not outs and times:
        raise subprocess.CalledProcessError(1, "ffmpeg", "no frames could be extracted")
    return [(t, str(p)) for t, p in outs if p.exists() and p.stat().st_size > 0]


def _frame_signature(path: str):
    """32x18 greyscale thumbnail as float32 (None if unreadable)."""
    try:
        import cv2
        import numpy as np
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return cv2.resize(img, (32, 18), interpolation=cv2.INTER_AREA).astype(np.float32)
    except Exception:
        return None


def static_keep(sigs: list, max_looks: int = VISION_STATIC_FRAMES,
                threshold: float = VISION_STATIC_DIFF) -> Optional[list[int]]:
    """Indices of the frames to send if the chunk is a static shot, else None.

    Greedy grouping: a frame starts a new "look" unless its mean abs
    difference to an existing look's first frame is < threshold. More than
    `max_looks` looks -> not static (send everything). Otherwise keep each
    look's first frame, padded with evenly spaced frames up to `max_looks`.
    """
    n = len(sigs)
    if n <= max_looks or max_looks < 1:
        return None
    looks: list[int] = []
    for i, s in enumerate(sigs):
        if s is None:
            return None
        if any(float(abs(s - sigs[j]).mean()) < threshold for j in looks):
            continue
        looks.append(i)
        if len(looks) > max_looks:
            return None
    keep = set(looks)
    for k in range(max_looks):
        if len(keep) >= max_looks:
            break
        keep.add(min(n - 1, int((k + 0.5) * n / max_looks)))
    return sorted(keep)


def _encode_chunk_video(video_path: str, start: float, duration: float, out_path: Path,
                        height: int = VISION_VIDEO_HEIGHT) -> str:
    """Re-encode [start, start+duration] small (H.264 + mono AAC) for video_url input."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", video_path, "-t", f"{duration:.3f}",
        "-vf", f"scale=-2:'min({height},ih)',fps=2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "48k", "-ac", "1",
        "-movflags", "+faststart", str(out_path),
    ]
    subprocess.run(cmd, check=True, timeout=600)
    return str(out_path)


def _data_uri(path: str, mime: str) -> str:
    with open(path, "rb") as f:
        return f"data:{mime};base64,{base64.b64encode(f.read()).decode('ascii')}"


def _f01(v) -> float:
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _num(v) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            if ":" in v:
                secs = 0.0
                for part in v.strip().split(":"):
                    secs = secs * 60 + float(part)
                return secs
            return float(v.strip().rstrip("s"))
        except ValueError:
            return None
    return None


def _coerce_moments(data, chunk_start: float, chunk_end: float, chunk_idx) -> Optional[list[Moment]]:
    """Validate raw moment dicts → absolute-time Moment[] clamped to the chunk.

    Returns None if the payload has no usable `moments` list (→ retry).
    """
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict) and isinstance(data.get("moments"), list):
        raw = data["moments"]
    else:
        return None
    chunk_len = chunk_end - chunk_start

    items = []
    for m in raw[: MAX_MOMENTS * 2]:
        if not isinstance(m, dict):
            continue
        s, e = _num(m.get("start")), _num(m.get("end"))
        if s is None or e is None or e <= s:
            continue
        items.append((s, e, m))
    if not items:
        return []

    # The prompt asks for chunk-relative times; models sometimes return
    # absolute ones anyway. If everything sits inside the absolute window and
    # something lies beyond the chunk length, treat the response as absolute.
    absolute = (
        chunk_start > MIN_MOMENT_S
        and all(chunk_start - 5 <= s <= chunk_end + 5 for s, _, _ in items)
        and any(s > chunk_len + 5 for s, _, _ in items)
    )
    if absolute:
        logger.info("chunk_analyzer: chunk %s returned absolute timestamps — converting", chunk_idx)

    moments: list[Moment] = []
    dropped = 0
    for s, e, m in items:
        if absolute:
            s, e = s - chunk_start, e - chunk_start
        cs, ce = max(0.0, s), min(chunk_len, e)
        # Discard if mostly outside the chunk or too short after clamping.
        if ce - cs < MIN_MOMENT_S or (ce - cs) < 0.5 * (e - s):
            dropped += 1
            continue
        tags = [t for t in (m.get("style_tags") or []) if t in STYLE_TAGS][:3]
        vis, aud, txt = _f01(m.get("visual_energy")), _f01(m.get("audio_energy")), _f01(m.get("text_hook_strength"))
        moments.append(Moment(
            start=round(chunk_start + cs, 2),
            end=round(chunk_start + ce, 2),
            visual_energy=vis,
            audio_energy=aud,
            text_hook_strength=txt,
            convergence_score=_f01(m.get("convergence_score")),
            modalities_active=sum(1 for v in (vis, aud, txt) if v > 0.4),
            style_tags=tags,
            description=str(m.get("description") or "")[:200],
            transcript=str(m.get("transcript") or "")[:1000],
        ))
    if dropped:
        logger.info("chunk_analyzer: chunk %s dropped %d moment(s) outside [%.1f, %.1f]",
                    chunk_idx, dropped, chunk_start, chunk_end)
    moments.sort(key=lambda x: -x.convergence_score)
    return moments[:MAX_MOMENTS]


def _build_messages(plan: ChunkPlan, mode: str, work: Path,
                   info: Optional[dict] = None) -> tuple[list[dict], str]:
    """Build the chat messages for one chunk. Returns (messages, effective_mode).
    `info["static"]` is set to whether the sampled frames are a static shot
    (computed even when VISION_STATIC_CHECK is off; talk_segments reads it)."""
    chunk_len = plan.end - plan.start
    transcript_text = _slice_transcript(plan.transcript_window, plan.start, plan.end)
    header = (
        f"CHUNK: index={plan.index}, length={chunk_len:.1f}s "
        f"(covers {plan.start:.1f}s-{plan.end:.1f}s of the full video, for reference only — "
        f"answer in seconds from chunk start, 0-{chunk_len:.0f}).\n\n"
        f"TRANSCRIPT LINES ([seconds from chunk start] text):\n{transcript_text}\n"
    )
    content: list[dict] = []

    if mode == "video":
        try:
            with _FFMPEG_SLOTS:
                clip = _encode_chunk_video(plan.video_path, plan.start, chunk_len, work / "chunk.mp4")
            content = [
                {"type": "text", "text": header + "\nThe chunk video (with audio) follows."},
                {"type": "video_url", "video_url": {"url": _data_uri(clip, "video/mp4")}},
            ]
            system = _SYSTEM_VIDEO
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            logger.warning("chunk_analyzer: video encode failed for chunk %s (%s) — using frames", plan.index, e)
            mode = "frames"

    if mode == "audio":
        content = [{"type": "text", "text": header + "\nAudio-only episode: no frames, judge by the transcript."}]
        system = _SYSTEM_AUDIO

    if mode not in ("video", "audio"):
        times = _frame_times(chunk_len, VISION_MAX_FRAMES)
        try:
            with _FFMPEG_SLOTS:
                frames = _sample_frames(plan.video_path, plan.start, times, work)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("chunk_analyzer: frame sampling failed for chunk %s: %s", plan.index, e)
            frames = []
        spacing = chunk_len / max(1, len(times))
        note = f"spaced ~{spacing:.1f}s apart across the whole chunk."
        keep = static_keep([_frame_signature(fp) for _, fp in frames]) if frames else None
        if info is not None:
            info["static"] = keep is not None
        if VISION_STATIC_CHECK and frames:
            if keep is not None:
                logger.info("chunk_analyzer: chunk %s is a static shot — sending %d of %d frames",
                            plan.index, len(keep), len(frames))
                frames = [frames[i] for i in keep]
                note = "from a static shot (near-identical frames were dropped)."
        content = [{"type": "text", "text": header + f"\n{len(frames)} frames follow, {note}"}]
        for t, fp in frames:
            content.append({"type": "text", "text": f"frame @ {t:.1f}s"})
            content.append({"type": "image_url", "image_url": {"url": _data_uri(fp, "image/jpeg")}})
        system = _SYSTEM_FRAMES
        mode = "frames"

    content.append({"type": "text", "text": "Return up to 5 viral-clip moments as JSON per the rules."})
    return [{"role": "system", "content": system}, {"role": "user", "content": content}], mode


def _call(messages: list[dict], attempt: int):
    """One vision call. Returns (parsed_json|None, problem|None)."""
    model = get_vision_model(temperature=0.4 if attempt == 0 else 0.2, max_tokens=VISION_MAX_TOKENS)
    try:
        # response_format via extra_body: LangChain's structured-output path
        # raises on finish_reason=length and discards repairable JSON.
        msg = model.invoke(messages, extra_body={"response_format": RESPONSE_FORMAT})
    except Exception as e:
        return None, f"request_error: {str(e)[:300]}"
    telemetry.record_openrouter_call(msg, model_label=TELEMETRY_LABEL)
    data = extract_json(message_text(msg))
    if data is None:
        fr = finish_reason(msg)
        return None, f"invalid_json(finish_reason={fr})"
    return data, None


# ─── Core: analyze one chunk ─────────────────────────────────

def analyze_chunk(plan: ChunkPlan, video_id: Optional[str] = None,
                  mode: Optional[str] = None, info: Optional[dict] = None) -> list[Moment]:
    """Run one chunk through OpenRouter vision analysis and return Moment[]."""
    mode = (mode or VISION_INPUT_MODE or "frames").lower()
    if plan.media_kind == "audio":
        mode = "audio"
    elif mode not in ("frames", "video"):
        logger.warning("VISION_INPUT_MODE=%r unknown — using frames", mode)
        mode = "frames"

    work = _work_dir(plan, video_id)
    moments: Optional[list[Moment]] = None
    try:
        messages, eff_mode = _build_messages(plan, mode, work, info)
        problem = None
        attempts = max(1, CHUNK_ANALYZE_ATTEMPTS)
        for attempt in range(attempts):
            data, problem = _call(messages, attempt)
            if data is not None:
                moments = _coerce_moments(data, plan.start, plan.end, plan.index)
                if moments is None:
                    problem = "no_moments_list"
            if moments is not None:
                break
            if attempt + 1 < attempts:
                telemetry.record_retry(TELEMETRY_LABEL, f"chunk {plan.index} attempt {attempt + 1}: {problem}")

        if moments is None and eff_mode == "video":
            # Video part rejected/garbled — one last try with frames.
            logger.warning("chunk_analyzer: video mode failed for chunk %s (%s) — retrying with frames",
                           plan.index, problem)
            messages, _ = _build_messages(plan, "frames", work)
            data, problem = _call(messages, 0)
            if data is not None:
                moments = _coerce_moments(data, plan.start, plan.end, plan.index)

        if moments is None:
            telemetry.record_failure(TELEMETRY_LABEL, f"chunk {plan.index} [{plan.start:.0f}-{plan.end:.0f}s]: {problem}")
            moments = []
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:   # drop outputs/{video_id}/chunks once the last chunk is done
            work.parent.rmdir()
        except OSError:
            pass   # other chunks still running (dir not empty) or already gone

    if video_id:
        try:
            from autoclip.services.events import publish_chunk_done
            publish_chunk_done(video_id, plan.index, moments)
        except Exception as e:
            logger.debug("publish_chunk_done failed (non-fatal): %s", e)

    return moments


# ─── LangGraph node entry ────────────────────────────────────

def chunk_analyzer_node(state: PipelineState) -> dict:
    """LangGraph node: analyze a single chunk dispatched via Send API.

    The Send API places the ChunkPlan into state under `chunk_plans=[plan]`
    (a single-element list) — see route_to_chunks() in graph.py.
    """
    plans = state.get("chunk_plans", [])
    if not plans:
        return {"moment_map_raw": []}
    plan = plans[0]
    video_id = state.get("video_id")
    info: dict = {}
    moments = analyze_chunk(plan, video_id=video_id, info=info)
    return {"moment_map_raw": moments, "chunk_static": [bool(info.get("static"))]}
