"""Transcript-first segments for talk content (podcasts, interviews, talks).

The chunk vision pass was built for films, where a moment is a visual beat:
it returns 3-17s fragments. On a podcast the unit people clip is a whole
story, rant or piece of advice (30-90s), so a 6s fragment stretched to a
clip length starts early or stops before the payoff.

This module cuts the word-timed transcript into 30-90s segments on sentence
and topic boundaries and returns them as ordinary `Moment`s, so embedding,
hybrid retrieval, re-rank and the diversity filter work unchanged:

  1. sentences()        — utterances merged up to terminal punctuation
  2. segment windows    — one cheap text-only LLM call per ~10 min of
                          sentences (OPENROUTER_MODEL_SEGMENT) returns
                          [first, last] sentence ids + a one-line summary +
                          the payoff sentence; the last segment of a window
                          is re-read at the start of the next window
  3. normalise_spans()  — contiguous, every span within [min, max] seconds
                          (merge short, split long at the biggest pause)
  4. pause_spans()      — no-LLM fallback for a window whose call fails
  5. build_segments()   — Moments (style_tags=["segment"], payoff time),
                          vision descriptions of overlapping moments kept as
                          "On screen:" context

Pure functions except `_llm_window`, so the boundary logic unit-tests cleanly.
"""
from __future__ import annotations
import logging
import re
from typing import Callable, Optional, Sequence

from pydantic import BaseModel, Field

from autoclip.config import (
    SEGMENT_MIN_SECONDS, SEGMENT_MAX_SECONDS, SEGMENT_WINDOW_SECONDS, SEGMENT_MODE,
    SEGMENT_STATIC_FRAC,
)
from autoclip.pipeline.state import Moment

logger = logging.getLogger(__name__)

SEGMENT_TAG = "segment"
LABEL = "lite_segment"
SENTENCE_MAX_SECONDS = 25.0      # an unpunctuated run is cut at the next utterance after this
_TERMINAL = re.compile(r"[.?!…][\"'”’)\]]*$")


def is_segment(m) -> bool:
    return SEGMENT_TAG in (getattr(m, "style_tags", None) or [])


def use_segments(media_kind: str, static_flags: Sequence[bool] = (), mode: Optional[str] = None) -> bool:
    """Whether a video's moment map should be transcript segments.
    auto: audio always; video when >= SEGMENT_STATIC_FRAC of chunks were static shots."""
    mode = (mode or SEGMENT_MODE or "auto").lower()
    if mode == "segments":
        return True
    if mode == "moments":
        return False
    if (media_kind or "video") == "audio":
        return True
    flags = list(static_flags)
    return bool(flags) and sum(1 for f in flags if f) / len(flags) >= SEGMENT_STATIC_FRAC


# ─── sentences ───────────────────────────────────────────────

def sentences(transcript_data: dict) -> list[dict]:
    """[{start, end, text}] — consecutive utterances merged until one ends a
    sentence (or the run passes SENTENCE_MAX_SECONDS). Utterances carry the
    transcript's real phrase timings; word times inside them are interpolated."""
    utts = sorted((transcript_data or {}).get("utterances") or [], key=lambda u: u.get("start", 0))
    if not utts:  # fall back to words, cut at terminal punctuation
        utts = [{"text": w["text"], "start": w["start"], "end": w["end"]}
                for w in (transcript_data or {}).get("words") or []]
    out: list[dict] = []
    cur: Optional[dict] = None
    for u in utts:
        text = str(u.get("text") or "").strip()
        if not text:
            continue
        s, e = float(u["start"]), float(u["end"])
        if cur is None:
            cur = {"start": s, "end": e, "text": text}
        else:
            cur["end"] = max(cur["end"], e)
            cur["text"] += " " + text
        if _TERMINAL.search(text) or cur["end"] - cur["start"] >= SENTENCE_MAX_SECONDS:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


# ─── span arithmetic (spans are inclusive sentence-index pairs) ─

def _dur(sents: Sequence[dict], a: int, b: int) -> float:
    return sents[b]["end"] - sents[a]["start"]


def _gap_after(sents: Sequence[dict], j: int) -> float:
    return sents[j + 1]["start"] - sents[j]["end"] if j + 1 < len(sents) else 0.0


def pause_spans(sents: Sequence[dict], lo: int, hi: int,
                min_s: float = SEGMENT_MIN_SECONDS, max_s: float = SEGMENT_MAX_SECONDS) -> list[tuple[int, int]]:
    """No-LLM fallback: greedy spans over sentences lo..hi, each cut after the
    sentence with the longest following pause among ends that keep the span
    within [min_s, max_s] (ties -> closest to the middle of the range)."""
    spans: list[tuple[int, int]] = []
    i = lo
    mid = (min_s + max_s) / 2
    while i <= hi:
        if _dur(sents, i, hi) <= max_s:
            spans.append((i, hi))
            break
        ends = [j for j in range(i, hi + 1) if min_s <= _dur(sents, i, j) <= max_s]
        if not ends:  # one very long sentence, or nothing reaches min before max
            j = i
            while j < hi and _dur(sents, i, j + 1) <= max_s:
                j += 1
        else:
            j = max(ends, key=lambda k: (round(_gap_after(sents, k), 1), -abs(_dur(sents, i, k) - mid)))
        spans.append((i, j))
        i = j + 1
    return spans


def _split_long(sents, a: int, b: int, min_s: float, max_s: float) -> list[tuple[int, int]]:
    if _dur(sents, a, b) <= max_s or a == b:
        return [(a, b)]
    cuts = [j for j in range(a, b) if _dur(sents, a, j) >= min_s and _dur(sents, j + 1, b) >= min_s]
    if not cuts:
        cuts = list(range(a, b))
    target = sents[a]["start"] + _dur(sents, a, b) / 2
    j = max(cuts, key=lambda k: (round(_gap_after(sents, k), 1), -abs(sents[k]["end"] - target)))
    return _split_long(sents, a, j, min_s, max_s) + _split_long(sents, j + 1, b, min_s, max_s)


def normalise_spans(starts: Sequence[int], sents: Sequence[dict], lo: int, hi: int,
                    min_s: float = SEGMENT_MIN_SECONDS,
                    max_s: float = SEGMENT_MAX_SECONDS) -> list[tuple[int, int]]:
    """Contiguous spans covering lo..hi from the model's segment start ids:
    out-of-range/duplicate ids dropped, spans shorter than min_s merged into
    the shorter neighbour, then spans longer than max_s split at the biggest
    pause (so a too-short piece next to a too-long one gets re-cut)."""
    cut = sorted({int(s) for s in starts if lo < int(s) <= hi})
    bounds = [lo] + cut + [hi + 1]
    spans = [(bounds[k], bounds[k + 1] - 1) for k in range(len(bounds) - 1)]

    changed = True
    while changed and len(spans) > 1:
        changed = False
        for k, (a, b) in enumerate(spans):
            if _dur(sents, a, b) >= min_s:
                continue
            left = (spans[k - 1][0], b) if k > 0 else None
            right = (a, spans[k + 1][1]) if k + 1 < len(spans) else None
            opts = [(o, side) for o, side in ((left, -1), (right, 1)) if o]
            (na, nb), side = min(opts, key=lambda x: _dur(sents, *x[0]))
            if side == -1:
                spans[k - 1:k + 1] = [(na, nb)]
            else:
                spans[k:k + 2] = [(na, nb)]
            changed = True
            break

    out: list[tuple[int, int]] = []
    for a, b in spans:
        out.extend(_split_long(sents, a, b, min_s, max_s))
    return out


# ─── LLM segmentation ────────────────────────────────────────

class _Seg(BaseModel):
    first: int = Field(description="id of the segment's first sentence")
    last: int = Field(description="id of the segment's last sentence")
    summary: str = Field(default="", description="one line, <= 20 words")
    payoff: int = Field(default=-1, description="id of the sentence that lands the point")
    score: float = Field(default=0.5, description="0-1: strength as a standalone clip")


class _SegResult(BaseModel):
    segments: list[_Seg] = Field(default_factory=list)


def _fmt(t: float) -> str:
    t = int(max(0, t))
    return f"{t // 60}:{t % 60:02d}"


def segment_prompt(sents: Sequence[dict], lo: int, hi: int,
                   min_s: float = SEGMENT_MIN_SECONDS, max_s: float = SEGMENT_MAX_SECONDS) -> str:
    rows = "\n".join(f"[{i}] {_fmt(sents[i]['start'])} {sents[i]['text'][:300]}" for i in range(lo, hi + 1))
    return f"""Split this transcript excerpt (a podcast, interview or talk) into consecutive
segments that would each work as a standalone short clip.

Rules:
- A segment is one complete unit: a story told start to finish, one argument
  or opinion with its reasoning, one piece of advice, one joke or bit with its
  laugh, one question with its full answer.
- Start a new segment where the topic, story or question changes. Never cut
  in the middle of a story or before its punchline/conclusion.
- Each segment should last about {min_s:.0f}-{max_s:.0f} seconds (times are shown as m:ss).
- Segments are consecutive and cover every sentence from [{lo}] to [{hi}].
  The excerpt may stop mid-topic; end the last segment at [{hi}] anyway.
- summary: one plain line (<= 20 words) saying what happens, no hype.
- payoff: the id of the sentence where the point lands (the punchline, the
  conclusion, the key line). Usually near the end of the segment.
- score: 0-1, how well it works as a standalone clip (most are 0.3-0.7).

Sentences ([id] m:ss text):
{rows}

Return JSON: {{"segments": [{{"first": {lo}, "last": 12, "summary": "...", "payoff": 11, "score": 0.6}}, ...]}}"""


def parse_segments(obj, lo: int, hi: int) -> list[dict]:
    """[{first, summary, payoff, score}] sorted by first, ids clamped/validated."""
    items = obj.get("segments") if isinstance(obj, dict) else obj
    out: dict[int, dict] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            first = int(it.get("first"))
        except (TypeError, ValueError):
            continue
        if not lo <= first <= hi or first in out:
            continue
        try:
            payoff = int(it.get("payoff"))
        except (TypeError, ValueError):
            payoff = -1
        try:
            score = min(1.0, max(0.0, float(it.get("score", 0.5))))
        except (TypeError, ValueError):
            score = 0.5
        out[first] = {"first": first, "summary": str(it.get("summary") or "").strip()[:200],
                      "payoff": payoff, "score": score}
    return [out[k] for k in sorted(out)]


def _llm_window(sents: Sequence[dict], lo: int, hi: int) -> Optional[list[dict]]:
    from autoclip.config import OPENROUTER_MODEL_SEGMENT
    from autoclip.llm.openrouter import get_chat_model, invoke_json
    model = get_chat_model(OPENROUTER_MODEL_SEGMENT, temperature=0.0, max_tokens=4096)
    obj = invoke_json(model, _SegResult, segment_prompt(sents, lo, hi), LABEL)
    segs = parse_segments(obj, lo, hi)
    return segs or None


def segment_spans(sents: Sequence[dict],
                  call: Optional[Callable[[Sequence[dict], int, int], Optional[list[dict]]]] = None,
                  window_s: float = SEGMENT_WINDOW_SECONDS) -> list[dict]:
    """[{a, b, summary, payoff, score}] over all sentences, windows processed
    in order. `call(sents, lo, hi)` returns parse_segments-shaped items or
    None (-> pause_spans fallback for that window)."""
    call = call or _llm_window
    out: list[dict] = []
    n = len(sents)
    lo = 0
    while lo < n:
        hi = lo
        while hi + 1 < n and sents[hi + 1]["end"] - sents[lo]["start"] <= window_s:
            hi += 1
        last_window = hi == n - 1
        try:
            items = call(sents, lo, hi)
        except Exception as e:  # never fail the analysis on one window
            logger.warning("talk_segments: window [%d-%d] call failed: %s", lo, hi, e)
            items = None
        meta = {it["first"]: it for it in items or []}
        if items:
            spans = normalise_spans([it["first"] for it in items], sents, lo, hi)
        else:
            logger.info("talk_segments: window [%d-%d] using the pause fallback", lo, hi)
            spans = pause_spans(sents, lo, hi)
        # The window may stop mid-story: re-read its last span next time.
        if not last_window and len(spans) > 1:
            spans = spans[:-1]
        for a, b in spans:
            # summary/payoff from the model item whose start falls in this span
            it = next((meta[k] for k in sorted(meta) if a <= k <= b), None) if items else None
            payoff = it["payoff"] if it and a <= it["payoff"] <= b else b
            out.append({"a": a, "b": b, "summary": (it or {}).get("summary", ""),
                        "payoff": payoff, "score": (it or {}).get("score", 0.5)})
        lo = spans[-1][1] + 1
    return out


# ─── Moments ────────────────────────────────────────────────

def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def build_segments(transcript_data: dict, context: Sequence[Moment] = (),
                   call=None) -> list[Moment]:
    """Transcript segments as Moments. `context` = the vision pass's moments
    (video only): their descriptions are kept on the overlapping segment."""
    sents = sentences(transcript_data)
    if not sents:
        return []
    out: list[Moment] = []
    for sp in segment_spans(sents, call):
        a, b = sp["a"], sp["b"]
        start, end = sents[a]["start"], sents[b]["end"]
        text = " ".join(s["text"] for s in sents[a:b + 1])
        seen = sorted(((_overlap(start, end, m.start, m.end), m) for m in context
                       if _overlap(start, end, m.start, m.end) > 0), key=lambda x: -x[0])
        vis = [m for _, m in seen]
        desc = sp["summary"] or text[:160]
        if vis:
            desc += "\nOn screen: " + " | ".join((m.description or "").strip()[:160] for m in vis[:2])
        out.append(Moment(
            start=round(start, 3), end=round(end, 3),
            visual_energy=max((m.visual_energy for m in vis), default=0.0),
            audio_energy=max((m.audio_energy for m in vis), default=0.0),
            text_hook_strength=max((m.text_hook_strength for m in vis), default=sp["score"]),
            convergence_score=round(float(sp["score"]), 3),
            modalities_active=2 if vis else 1,
            style_tags=[SEGMENT_TAG],
            description=desc[:600],
            transcript=text[:4000],
            payoff=round(sents[sp["payoff"]]["end"], 3),
        ))
    lens = [m.end - m.start for m in out]
    logger.info("talk_segments: %d sentences -> %d segments (mean %.0fs, min %.0fs, max %.0fs)",
                len(sents), len(out), sum(lens) / len(lens), min(lens), max(lens))
    return out


# ─── clip windows on sentence boundaries ─────────────────────

def fit_segment(seg, target: float, sents: Sequence[dict], tol: float,
                lo: float = 0.0, hi: float = float("inf")) -> Optional[tuple[float, float]]:
    """A clip window of ~target seconds (+-tol) on sentence boundaries for a
    segment. Shorter request: the best sentence span inside the segment that
    contains the payoff, preferring one that ends on it. Longer request: the
    segment plus adjacent sentences (before first, it is the setup). None if no
    sentence-aligned window fits; the caller then falls back to word snapping."""
    idx = [i for i, s in enumerate(sents) if s["end"] > seg.start + 0.5 and s["start"] < seg.end - 0.5]
    if not idx:
        return None
    a, b = idx[0], idx[-1]
    payoff_t = getattr(seg, "payoff", None) or sents[b]["end"]
    p = min(range(a, b + 1), key=lambda i: abs(sents[i]["end"] - payoff_t))

    def ok(i: int, j: int) -> bool:
        return (sents[i]["start"] >= lo and sents[j]["end"] <= hi
                and abs(_dur(sents, i, j) - target) <= tol)

    if _dur(sents, a, b) > target + tol:
        best = None
        for j in range(p, b + 1):           # end on the payoff, else just after it
            for i in range(a, j + 1):
                if i <= p and ok(i, j):
                    key = (j - p, abs(_dur(sents, i, j) - target))
                    if best is None or key < best[0]:
                        best = (key, i, j)
            if best and best[0][0] == j - p:
                break
        return (sents[best[1]]["start"], sents[best[2]]["end"]) if best else None

    i, j = a, b
    while not ok(i, j):
        grow = []
        if i > 0 and sents[i - 1]["start"] >= lo:
            grow.append((i - 1, j))
        if j + 1 < len(sents) and sents[j + 1]["end"] <= hi:
            grow.append((i, j + 1))
        grow = [g for g in grow if _dur(sents, *g) <= target + tol]
        if not grow:
            return None
        i, j = min(grow, key=lambda g: (abs(_dur(sents, *g) - target), g[0] == i))
    return sents[i]["start"], sents[j]["end"]
