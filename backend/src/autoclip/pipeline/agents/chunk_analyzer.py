"""Chunk analyzer — single Gemini 2.5 Flash multimodal call per video chunk.

Replaces the v1 visual_agent + audio_agent + text_agent + fusion stack
(~975 lines of hand-rolled signal extraction) with one native call: Gemini
takes the chunk's raw video+audio + the chunk's transcript window, and
returns structured `GeminiMoment[]` directly.

This is the "let the model do the hard work" inversion from V2_PLAN §2.
"""
import os
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types as genai_types

from autoclip.config import GEMINI_API_KEY, GEMINI_MODEL_MULTIMODAL
from autoclip.pipeline.state import (
    PipelineState, Moment, ChunkAnalysis, ChunkPlan,
)
from autoclip.pipeline import telemetry

logger = logging.getLogger(__name__)


# ─── System prompt (cacheable across chunks) ─────────────────

SYSTEM_PROMPT = """You are a video clip-curation expert. Given a short video chunk \
(2 minutes max) and its transcript, identify up to 5 moments inside the chunk that \
would make great viral short-form clips.

A great moment has at least one of:
  • a strong verbal hook (hot take, surprising claim, story beat, punchline, tight quote)
  • visual energy (gestures, reactions, scene change, B-roll cut, on-screen text)
  • audio energy (laughter, applause, pitch swing, dramatic pause + payoff)

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


def _upload_and_wait(client: genai.Client, path: str, max_wait: float = 90.0):
    """Upload a video file to Gemini and poll until ACTIVE."""
    f = client.files.upload(file=path)
    deadline = time.time() + max_wait
    while getattr(f.state, "name", str(f.state)) == "PROCESSING":
        if time.time() > deadline:
            raise TimeoutError(f"Gemini file upload stuck PROCESSING for {path}")
        time.sleep(1.5)
        f = client.files.get(name=f.name)
    state = getattr(f.state, "name", str(f.state))
    if state != "ACTIVE":
        raise RuntimeError(f"Gemini file upload failed ({state}) for {path}")
    return f


def _convergence_modalities(m) -> int:
    """How many modalities are 'active' (energy > 0.4) for this moment."""
    return sum(1 for v in (m.visual_energy, m.audio_energy, m.text_hook_strength) if v > 0.4)


# ─── Core: analyze one chunk ─────────────────────────────────

def analyze_chunk(plan: ChunkPlan, video_id: Optional[str] = None) -> list[Moment]:
    """Run one chunk through Gemini 2.5 Flash multimodal and return Moment[]."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    # 1. Cut chunk (stream-copy, ~instant) — or pass full video if chunk == video
    chunk_path = _cut_chunk(
        plan.video_path, plan.start, plan.end,
        out_path=str(Path("outputs") / "chunks" / f"{Path(plan.video_path).stem}_{plan.index}.mp4"),
    )

    # 2. Upload to Gemini File API
    uploaded = _upload_and_wait(client, chunk_path)

    # 3. Build prompt (transcript window + chunk metadata)
    transcript_window_text = _slice_transcript(plan.transcript_window, plan.start, plan.end)
    user_prompt = (
        f"CHUNK METADATA:\n"
        f"  chunk_index = {plan.index}\n"
        f"  chunk_start_seconds = {plan.start:.2f}\n"
        f"  chunk_end_seconds = {plan.end:.2f}\n\n"
        f"TRANSCRIPT WINDOW (verbatim, word-level):\n{transcript_window_text}\n\n"
        f"Return up to 5 viral-clip moments per the system rules. "
        f"All timestamps must be in seconds relative to the FULL video."
    )

    # 4. Single Gemini call with Pydantic structured output
    config = genai_types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=ChunkAnalysis,
        temperature=0.4,
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL_MULTIMODAL,
        contents=[uploaded, user_prompt],
        config=config,
    )

    # 5. Cache-hit metric (Phase 5)
    telemetry.record_gemini_call(response, model=GEMINI_MODEL_MULTIMODAL)

    parsed: Optional[ChunkAnalysis] = getattr(response, "parsed", None)
    if parsed is None:
        logger.warning("chunk_analyzer: parsed=None for chunk %s; raw=%r",
                       plan.index, getattr(response, "text", "")[:300])
        return []

    # 6. Map → internal Moment dataclass
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
            description=m.description,
            transcript=m.transcript,
        ))

    # 7. Publish incremental progress to Redis (Phase 3)
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
