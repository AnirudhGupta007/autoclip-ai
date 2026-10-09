"""Pure scoring functions for the movie eval. No I/O, no globals.

Conventions
-----------
* A *span* is ``(start, end)`` in seconds, ``end > start``.
* **Overlap match** (the one rule everything uses): span ``c`` matches span
  ``g`` iff ``overlap(c, g) >= 0.5 * min(len(c), len(g))``. Using the shorter
  span means a 15 s clip sitting fully inside a 60 s labelled scene counts, and
  so does a 60 s clip that fully contains a 20 s labelled beat — but a clip
  that only grazes the edge of a scene does not.
* **One-to-one** metrics (recall/precision@k, coverage) use a greedy matching:
  all matching (pred, gt) pairs sorted by tIoU (desc), then by pred rank, then
  gt index; each pred and each gt is used at most once. This stops one long
  clip from "recalling" three adjacent labels, and stops four near-duplicate
  clips from all counting as precise.
* **Ranking** metrics (hit@k, MRR) are many-to-one: a pred is relevant iff it
  matches *any* relevant span.
* Functions return ``None`` when the metric is undefined (e.g. precision with
  zero predictions, length adherence when no length was asked) so aggregates
  can skip them instead of silently counting them as 0 or 1.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

Span = tuple[float, float]

MATCH_FRAC = 0.5


# --------------------------------------------------------------------------- spans
def span_len(a: Span) -> float:
    return max(0.0, float(a[1]) - float(a[0]))


def overlap(a: Span, b: Span) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def matches(c: Span, g: Span, frac: float = MATCH_FRAC) -> bool:
    """c matches g iff overlap >= frac * min(len(c), len(g)) (and overlap > 0)."""
    ov = overlap(c, g)
    if ov <= 0:
        return False
    return ov >= frac * min(span_len(c), span_len(g)) - 1e-9


def tiou(a: Span, b: Span) -> float:
    ov = overlap(a, b)
    union = span_len(a) + span_len(b) - ov
    return ov / union if union > 0 else 0.0


def greedy_match(preds: Sequence[Span], gts: Sequence[Span],
                 frac: float = MATCH_FRAC) -> list[tuple[int, int, float]]:
    """One-to-one greedy matching. Returns [(pred_idx, gt_idx, tiou)] sorted by pred_idx."""
    cands = []
    for i, p in enumerate(preds):
        for j, g in enumerate(gts):
            if matches(p, g, frac):
                cands.append((-tiou(p, g), i, j))
    cands.sort()
    used_p: set[int] = set()
    used_g: set[int] = set()
    out = []
    for neg_t, i, j in cands:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        out.append((i, j, -neg_t))
    return sorted(out)


# ------------------------------------------------------------ set retrieval @ k
def _topk(preds: Sequence[Span], k: Optional[int]) -> Sequence[Span]:
    return preds if k is None else preds[:k]


def recall_at_k(preds: Sequence[Span], gts: Sequence[Span], k: Optional[int] = None) -> Optional[float]:
    """Fraction of ground-truth spans matched (one-to-one) by the top-k preds."""
    if not gts:
        return None
    return len(greedy_match(_topk(preds, k), gts)) / len(gts)


def precision_at_k(preds: Sequence[Span], gts: Sequence[Span], k: Optional[int] = None) -> Optional[float]:
    """Fraction of the top-k preds that are matched (one-to-one) to some ground truth.
    Denominator is the number of preds actually available (<= k)."""
    top = _topk(preds, k)
    if not top:
        return None
    return len(greedy_match(top, gts)) / len(top)


# ---------------------------------------------------------------- ranking metrics
def relevance(preds: Sequence[Span], relevant: Sequence[Span]) -> list[bool]:
    """For each pred (in rank order): does it match any relevant span?"""
    return [any(matches(p, g) for g in relevant) for p in preds]


def hit_at_k(preds: Sequence[Span], relevant: Sequence[Span], k: int) -> Optional[float]:
    """1.0 if any of the top-k preds matches any relevant span. None if no preds."""
    if not preds:
        return 0.0 if relevant else None
    return 1.0 if any(relevance(preds[:k], relevant)) else 0.0


def mrr(preds: Sequence[Span], relevant: Sequence[Span]) -> float:
    """Reciprocal rank of the first pred that matches any relevant span (0 if none)."""
    for r, ok in enumerate(relevance(preds, relevant), 1):
        if ok:
            return 1.0 / r
    return 0.0


def best_truth_rank(preds: Sequence[Span], truth_ranked: Sequence[Span]) -> Optional[int]:
    """Best (lowest) 1-based rank in the human's ranked truth list that any pred matches."""
    for r, g in enumerate(truth_ranked, 1):
        if any(matches(p, g) for p in preds):
            return r
    return None


# ------------------------------------------------------------------- tag precision
def tag_hits(clips: Sequence[Span], moments: Sequence[dict], asked_tags: Iterable[str]) -> list[bool]:
    """Per clip: does it match any human moment carrying one of the asked tags?
    ``moments`` items need ``start``, ``end``, ``tags``."""
    asked = set(asked_tags)
    pool = [(m["start"], m["end"]) for m in moments if asked & set(m.get("tags", []))]
    return [any(matches(c, g) for g in pool) for c in clips]


def tag_precision(clips: Sequence[Span], moments: Sequence[dict], asked_tags: Iterable[str]) -> Optional[float]:
    hits = tag_hits(clips, moments, asked_tags)
    return sum(hits) / len(hits) if hits else None


# ------------------------------------------------------------------ format checks
def length_ok(delivered_s: Optional[float], asked_s: Optional[float], tol: float) -> Optional[bool]:
    """|delivered - asked| <= tol * asked. None if nothing was asked or nothing measured."""
    if asked_s is None or delivered_s is None or asked_s <= 0:
        return None
    return abs(delivered_s - asked_s) <= tol * asked_s + 1e-9


FRAMES = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0, "4:5": 4 / 5, "4:3": 4 / 3}


def parse_frame(frame: str) -> Optional[float]:
    if not frame:
        return None
    if frame in FRAMES:
        return FRAMES[frame]
    try:
        a, b = frame.split(":")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return None


def aspect_ok(width: Optional[int], height: Optional[int], frame: Optional[str], tol: float = 0.02) -> Optional[bool]:
    """Delivered w/h within ``tol`` (relative) of the asked frame. None if not asked/measured."""
    target = parse_frame(frame) if frame else None
    if target is None or not width or not height:
        return None
    return abs((width / height) - target) / target <= tol


def rate(flags: Iterable[Optional[bool]]) -> Optional[float]:
    """Mean of the non-None booleans; None if there are none."""
    vals = [bool(f) for f in flags if f is not None]
    return sum(vals) / len(vals) if vals else None


def mean(xs: Iterable[Optional[float]]) -> Optional[float]:
    vals = [float(x) for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else None


def duplicate_flags(spans: Sequence[Span]) -> list[bool]:
    """Per span: does it match (overlap rule) any *earlier* span?"""
    return [any(matches(s, spans[j]) for j in range(i)) for i, s in enumerate(spans)]


def duplicate_rate(spans: Sequence[Span]) -> Optional[float]:
    if not spans:
        return None
    return sum(duplicate_flags(spans)) / len(spans)


# --------------------------------------------------------------- temporal coverage
def _mid(s: Span) -> float:
    return (s[0] + s[1]) / 2


def coverage_by_tenth(preds: Sequence[Span], gts: Sequence[Span], film_end: float,
                      bins: int = 10) -> list[dict]:
    """Recall per 1/``bins`` of the film. Ground truth is bucketed by midpoint;
    hits come from the global one-to-one matching (so totals equal recall@all).
    ``n_pred`` counts predictions whose midpoint falls in the bucket (preds past
    film_end are clamped into the last bucket)."""
    matched_g = {j for _, j, _ in greedy_match(preds, gts)}
    width = film_end / bins
    out = []
    for b in range(bins):
        lo, hi = b * width, (b + 1) * width
        idx = [j for j, g in enumerate(gts) if (lo <= _mid(g) < hi) or (b == bins - 1 and _mid(g) >= hi)]
        n_pred = sum(1 for p in preds if (lo <= _mid(p) < hi) or (b == bins - 1 and _mid(p) >= hi))
        hit = sum(1 for j in idx if j in matched_g)
        out.append({"bin": b, "lo": lo, "hi": hi, "n_gt": len(idx), "n_hit": hit,
                    "recall": (hit / len(idx)) if idx else None, "n_pred": n_pred})
    return out


def within_chunk_offsets(starts: Sequence[float], chunk_s: float = 120.0, overlap_s: float = 10.0,
                         chunk_index: Optional[Sequence[int]] = None) -> list[float]:
    """Offset of each moment start from the start of its analysis chunk.
    Chunks begin every ``chunk_s - overlap_s`` seconds. If the chunk a moment came
    from is unknown it is inferred as floor(start / stride)."""
    stride = chunk_s - overlap_s
    out = []
    for i, s in enumerate(starts):
        idx = chunk_index[i] if chunk_index is not None else int(math.floor(s / stride))
        out.append(s - idx * stride)
    return out


def within_chunk_histogram(offsets: Sequence[float], chunk_s: float = 120.0, bin_s: float = 20.0) -> dict:
    """Histogram of within-chunk offsets. A healthy analyser is roughly flat; a
    pile-up in the first bins means the tail of each chunk is not being seen."""
    nb = int(math.ceil(chunk_s / bin_s))
    counts = [0] * nb
    for o in offsets:
        counts[min(nb - 1, max(0, int(o // bin_s)))] += 1
    n = len(offsets)
    second_half = sum(1 for o in offsets if o >= chunk_s / 2)
    return {"bin_s": bin_s, "edges": [i * bin_s for i in range(nb + 1)], "counts": counts, "n": n,
            "frac_second_half": (second_half / n) if n else None}


def last_analysed_fraction(spans: Sequence[Span], film_end: float) -> Optional[float]:
    """max(end) / film_end. >1 means the analyser reached into the credits."""
    if not spans or film_end <= 0:
        return None
    return max(s[1] for s in spans) / film_end


def coverage_gaps(spans: Sequence[Span], film_end: float, min_gap: float = 300.0) -> list[Span]:
    """Stretches of [0, film_end) longer than ``min_gap`` seconds with no span in them."""
    gaps, cursor = [], 0.0
    for s, e in sorted(spans):
        if s - cursor >= min_gap:
            gaps.append((cursor, min(s, film_end)))
        cursor = max(cursor, e)
        if cursor >= film_end:
            break
    if film_end - cursor >= min_gap:
        gaps.append((cursor, film_end))
    return gaps


def credits_violations(spans: Sequence[Span], film_end: float) -> list[int]:
    """Indices of spans that start after the film proper has ended."""
    return [i for i, s in enumerate(spans) if s[0] > film_end]


def transcript_minute_coverage(word_times: Sequence[float], film_end: float) -> dict:
    """Fraction of film minutes [0, film_end) containing at least one transcript
    word (by word start time)."""
    n_min = max(1, int(math.ceil(film_end / 60.0)))
    covered = sorted({int(t // 60) for t in word_times if 0 <= t < film_end})
    return {"minutes": n_min, "covered": len(covered), "fraction": len(covered) / n_min,
            "covered_minutes": covered}


def gt_spans(moments: Sequence[dict]) -> list[Span]:
    return [(float(m["start"]), float(m["end"])) for m in moments]
