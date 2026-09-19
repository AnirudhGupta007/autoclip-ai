"""Chunk analyzer — frame-sampled vision call per video chunk, via OpenRouter.

OpenRouter has no native video-file-upload API (unlike Google's Gemini File
API), so instead of uploading the raw chunk video we sample ~1 frame every
FRAME_SAMPLE_INTERVAL_S seconds, base64-encode each as JPEG, and send them
as a sequence of `image_url` (data URI) content parts in one chat-completion
call to a vision-capable model (OPENROUTER_MODEL_VISION), alongside the
chunk's transcript window. This approximates native video understanding —
visual_energy/audio_energy judgments rely more heavily on the transcript
signal than a true video model would, which is a known precision tradeoff
(see README).

This still runs one call per chunk under LangGraph's Send-API fan-out —
the parallel time-chunked architecture is unchanged, only the transport
for that per-chunk call moved from Gemini's File API to OpenRouter.
"""
from __future__ import annotations
import base64
import logging
import subprocess
from pathlib import Path
from typing import Optional

from autoclip.llm.openrouter import get_vision_model
from autoclip.pipeline.state import (
    PipelineState, Moment, ChunkAnalysis, ChunkPlan,
)
from autoclip.pipeline import telemetry

logger = logging.getLogger(__name__)

FRAME_SAMPLE_INTERVAL_S = 2.5
MAX_SAMPLED_FRAMES = 24  # cap payload size on long chunks


# ─── System prompt (identical curation rules to the previous version) ───

SYSTEM_PROMPT = """You are a video clip-curation expert. Given a sequence of \
sampled frames from a short video chunk (2 minutes max, frames spaced a few \
seconds apart) and its transcript, identify up to 5 moments inside the chunk \
that would make great viral short-form clips.

A great moment has at least one of:
  • a strong verbal hook (hot take, surprising claim, story beat, punchline, tight quote)
  • visual energy (gestures, reactions, scene change, B-roll cut, on-screen text)
  • audio energy (laughter, applause, pitch swing, dramatic pause + payoff) — infer this \
    from the transcript's punctuation/phrasing and any visible reactions in frames, since \
    you cannot hear the audio directly.

Rules:
  1. Timestamps MUST be in seconds, relative to the start of the FULL video — \
     the chunk metadata tells you the chunk's start offset; add it to your \
     within-chunk timestamps.
  2. Each moment is 5-30 seconds. No clip-length-zero moments.
  3. Quality over quantity. Return 0-5 moments. Empty is acceptable.
  4. convergence_score > 0.7 ONLY when 2+ modalities co-fire — be strict, \
     this drives downstream ranking.
  5. transcript must be verbatim from the supplied transcript window, not paraphrased.
"""


# ─── Helpers ─────────────────────────────────────────────────

def _slice_transcript(transcript_data: dict, start: float, end: float) -> str:
    """Extract the transcript text overlapping [start, end] from word-level data."""
    words = transcript_data.get("words", []) or []
    in_window = [w for w in words if w["start"] < end and w["end"] > start]
    if in_window:
        return " ".join(w["text"] for w in in_window).strip()
    full_text = transcript_data.get("text", "") or ""
    return full_text[:2000]


def _cut_chunk(video_path: str, start: float, end: float, out_path: str) -> str:
    """Cut a chunk from the source video using stream-copy (fast)."""
    if start <= 0 and (end >= 1e9 or end <= 0):
        return video_path
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start), "-to", str(end),
        "-i", video_path,
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _sample_frames(video_path: str, out_dir: str, interval: float, max_frames: int) -> list[str]:
    """Sample frames at `interval` seconds via ffmpeg fps filter, return sorted paths."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    fps = 1.0 / interval
    pattern = str(Path(out_dir) / "f_%04d.jpg")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "4",
        pattern,
    ]
    subprocess.run(cmd, check=True)
    frames = sorted(Path(out_dir).glob("f_*.jpg"))[:max_frames]
    return [str(p) for p in frames]


def _frame_to_data_uri(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _convergence_modalities(m) -> int:
    """How many modalities are 'active' (energy > 0.4) for this moment."""
    return sum(1 for v in (m.visual_energy, m.audio_energy, m.text_hook_strength) if v > 0.4)


# ─── Core: analyze one chunk ─────────────────────────────────

def analyze_chunk(plan: ChunkPlan, video_id: Optional[str] = None) -> list[Moment]:
    """Run one chunk through frame-sampled OpenRouter vision analysis and return Moment[]."""
    chunk_path = _cut_chunk(
        plan.video_path, plan.start, plan.end,
        out_path=str(Path("outputs") / "chunks" / f"{Path(plan.video_path).stem}_{plan.index}.mp4"),
    )

    frames_dir = str(Path("outputs") / "chunks" / f"{Path(plan.video_path).stem}_{plan.index}_frames")
    try:
        frame_paths = _sample_frames(chunk_path, frames_dir, FRAME_SAMPLE_INTERVAL_S, MAX_SAMPLED_FRAMES)
    except subprocess.CalledProcessError as e:
        logger.warning("frame sampling failed for chunk %s: %s", plan.index, e)
        frame_paths = []

    transcript_window_text = _slice_transcript(plan.transcript_window, plan.start, plan.end)
    user_text = (
        f"CHUNK METADATA:\n"
        f"  chunk_index = {plan.index}\n"
        f"  chunk_start_seconds = {plan.start:.2f}\n"
        f"  chunk_end_seconds = {plan.end:.2f}\n"
        f"  sampled_frames = {len(frame_paths)} (spaced ~{FRAME_SAMPLE_INTERVAL_S:.1f}s apart)\n\n"
        f"TRANSCRIPT WINDOW (verbatim, word-level):\n{transcript_window_text}\n\n"
        f"Return up to 5 viral-clip moments per the system rules. "
        f"All timestamps must be in seconds relative to the FULL video."
    )

    content: list[dict] = [{"type": "text", "text": user_text}]
    for fp in frame_paths:
        content.append({"type": "image_url", "image_url": {"url": _frame_to_data_uri(fp)}})

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    model = get_vision_model().with_structured_output(ChunkAnalysis, include_raw=True)

    try:
        response = model.invoke(messages)
        parsed: Optional[ChunkAnalysis] = response.get("parsed") if isinstance(response, dict) else None
        raw = response.get("raw") if isinstance(response, dict) else None
        telemetry.record_openrouter_call(raw, model_label="vision")
    except Exception as e:
        logger.warning("chunk_analyzer: OpenRouter call failed for chunk %s: %s", plan.index, e)
        parsed = None

    if parsed is None:
        logger.warning("chunk_analyzer: parsed=None for chunk %s", plan.index)
        return []

    moments: list[Moment] = []
    for m in parsed.moments:
        if m.end <= m.start or (m.end - m.start) < 2.0:
            continue
        moments.append(Moment(
            start=round(float(m.start), 2),
            end=round(float(m.end), 2),
            visual_energy=float(m.visual_energy),
            audio_energy=float(m.audio_energy),
            text_hook_strength=float(m.text_hook_strength),
            convergence_score=float(m.convergence_score),
            modalities_active=_convergence_modalities(m),
            style_tags=list(m.style_tags),
            description=(m.description or "")[:200],
            transcript=(m.transcript or "")[:1000],
        ))

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
    moments = analyze_chunk(plan, video_id=video_id)
    return {"moment_map_raw": moments}
