"""Moment selection: hybrid candidates -> one LLM re-rank -> diversity.

Why (eval, reports/eval/*/20261007*): analysis found 83-91% of the human
moments, but for category requests ("funny", "most tense moment", "best
quote") the human top-3 sat at median rank ~#45 of pure vector search over
description+dialogue embeddings — an abstract request embeds close to
moments that literally *say* "joke"/"tense", not ones that are funny/tense.

  1. hybrid_candidates — union of vector top-N (cosine vs the stored moment
     embeddings), category-tag matches (moment_tagger categories, falling
     back to the vision style_tags), and keyword hits in description /
     dialogue / why — up to 50 candidates, cheap, no LLM. (Measured on the
     two eval videos: a 30-candidate pool contained >=1 human top-3 moment
     for 9/12 queries, 50 for 12/12; 50 compact rows are ~6k prompt tokens.)
  2. rerank — ONE structured-output call (OPENROUTER_MODEL_RERANK) that reads
     the user's request and every candidate and returns ranked ids + reasons.
  3. conflicts / diverse windows — callers never return two clips that
     overlap >30% (of the shorter) or whose centres are within 20s.
Pure functions except `rerank` (and `embed_query`), so they unit-test cleanly.
"""
from __future__ import annotations
import logging
import math
import re
from typing import Optional, Sequence

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_OVERLAP_FRAC = 0.30
MIN_CENTRE_GAP_S = 20.0
N_VECTOR, N_TAG, N_KEYWORD, N_CANDIDATES = 25, 25, 10, 50

CATEGORY_WORDS: dict[str, list[str]] = {
    "funny": ["funny", "funniest", "hilarious", "humor", "humour", "humorous", "joke", "jokes",
              "comedy", "comedic", "comic", "laugh", "laughs", "lol", "witty", "absurd", "punchline"],
    "action": ["action", "fight", "fights", "chase", "shootout", "explosion", "stunt", "crash",
               "shot at", "shoot", "shooting", "gun", "gunfire", "gunfight", "car chase"],
    "tense": ["tense", "tension", "suspense", "suspenseful", "thrilling", "scary", "danger",
              "dangerous", "threat", "standoff", "shot at", "gun", "nerve-wracking"],
    "emotional": ["emotional", "sad", "touching", "heartfelt", "moving", "tears", "crying",
                  "vulnerable", "heartbreaking"],
    "romantic": ["romantic", "romance", "love", "flirt", "flirting", "kiss"],
    "insightful": ["insightful", "insight", "smart", "wise", "wisdom", "lesson", "takeaway",
                   "thought-provoking", "explains", "explanation", "big idea"],
    "quotable": ["quote", "quotes", "quotable", "one-liner", "one liner", "one-liners", "line",
                 "catchphrase", "soundbite", "zinger", "comeback"],
    "heated": ["heated", "rant", "angry", "anger", "fiery", "furious", "outburst", "passionate",
               "argument", "argues", "roast", "roasts", "fired up"],
    "story": ["story", "stories", "anecdote", "narrative", "tale"],
    "hot_take": ["hot take", "hot takes", "controversial", "contrarian", "unpopular opinion", "spicy",
                 "bold claim", "provocative", "opinion", "opinions"],
    "advice": ["advice", "tip", "tips", "how to", "how-to", "actionable", "recommendation",
               "recommendations", "guidance", "practical"],
}
# Vision-model style_tags -> categories, for moments the tagger hasn't seen.
STYLE_TAG_MAP = {"funny": "funny", "emotional": "emotional", "story": "story",
                 "story_beat": "story", "quote": "quotable", "hot_take": "hot_take",
                 "controversial": "hot_take", "educational": "insightful"}

_STOP = set("""a an the and or of to in on at for with from by about into this that these those it its is are
was were be been being i me my you your he him his she her they them their we our us give get gets got make want need
please can could would some any one two three four five six all most more best great good really very just
clip clips moment moments scene scenes part bit video movie film talk show seconds second sec secs s long
short where when who what which how there here something someone somebody tiktok reels shorts youtube
vertical square format x 9 16 1 under over each analyze analyse find podcast episode guest host""".split())


def _norm(s: str) -> str:
    return " " + re.sub(r"[^a-z0-9' -]+", " ", (s or "").lower()) + " "


def query_categories(text: str) -> list[str]:
    """Categories a request asks for, by whole-word/phrase match ("action scene" -> action)."""
    t = _norm(text)
    return [c for c, words in CATEGORY_WORDS.items()
            if any(f" {w} " in t for w in words)]


def keywords(text: str) -> list[str]:
    """Content words of a request (stopwords, category words and numbers removed)."""
    cat_words = {w for ws in CATEGORY_WORDS.values() for w in ws if " " not in w}
    out = []
    for w in re.findall(r"[a-z0-9']+", (text or "").lower()):
        w = w.strip("'")
        if len(w) < 3 or w.isdigit() or w in _STOP or w in cat_words or w in out:
            continue
        out.append(w)
    return out


def moment_categories(m) -> set[str]:
    cats = set(getattr(m, "categories", None) or [])
    if cats or (getattr(m, "why", "") or ""):
        return cats
    return {STYLE_TAG_MAP[t] for t in (getattr(m, "style_tags", None) or []) if t in STYLE_TAG_MAP}


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if a is None or b is None or len(a) == 0 or len(a) != len(b):
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0


def hybrid_candidates(moments: Sequence, query: str, query_vec: Optional[Sequence[float]] = None,
                      limit: int = N_CANDIDATES) -> list[int]:
    """Indices into `moments`: interleaved vector / tag / keyword top lists, deduped."""
    if not moments:
        return []
    conv = lambda i: float(getattr(moments[i], "convergence_score", 0.0) or 0.0)  # noqa: E731
    idx = range(len(moments))

    vec: list[int] = []
    if query_vec is not None:
        scored = [(_cosine(query_vec, getattr(moments[i], "embedding", None)), i) for i in idx]
        vec = [i for s, i in sorted(scored, key=lambda x: (-x[0], x[1])) if s > 0][:N_VECTOR]

    cats = set(query_categories(query))
    tag: list[int] = []
    if cats:
        hits = [(len(cats & moment_categories(moments[i])), i) for i in idx]
        tag = [i for n, i in sorted(hits, key=lambda x: (-x[0], -conv(x[1]), x[1])) if n > 0][:N_TAG]

    kws = keywords(query)
    kw: list[int] = []
    if kws:
        def kscore(i):
            m = moments[i]
            text = _norm(" ".join([getattr(m, "description", "") or "", getattr(m, "transcript", "") or "",
                                   getattr(m, "why", "") or ""]))
            return sum(1 for k in kws if f" {k}" in text)
        hits = [(kscore(i), i) for i in idx]
        kw = [i for n, i in sorted(hits, key=lambda x: (-x[0], -conv(x[1]), x[1])) if n > 0][:N_KEYWORD]

    by_conv = sorted(idx, key=lambda i: (-conv(i), i))  # fallback when the request has no signal
    out: list[int] = []
    for group in zip_longest_lists([vec, tag, kw]) + by_conv:
        if group not in out:
            out.append(group)
        if len(out) >= limit:
            break
    return out


def zip_longest_lists(lists: list[list[int]]) -> list[int]:
    out = []
    for k in range(max((len(x) for x in lists), default=0)):
        for x in lists:
            if k < len(x):
                out.append(x[k])
    return out


# ─── re-rank ────────────────────────────────────────────────

class RerankItem(BaseModel):
    id: int = Field(description="candidate number")
    reason: str = Field(default="", description="<= 15 words")


class RerankResult(BaseModel):
    ranked: list[RerankItem] = Field(default_factory=list, description="best match first")


def _fmt_t(s: float) -> str:
    s = int(max(0, s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def rerank_prompt(request: str, query: str, cands: Sequence, want: int,
                  dialogue: Optional[Sequence[str]] = None) -> str:
    """`dialogue[i]` (optional) replaces candidate i's own-window transcript —
    callers pass the dialogue of the whole clip window that would be cut
    around the moment, since moments are often 3-8s fragments of a scene."""
    rows = []
    for n, m in enumerate(cands, 1):
        cats = ", ".join(sorted(moment_categories(m))) or "-"
        said = dialogue[n - 1] if dialogue is not None else (getattr(m, "transcript", "") or "")
        said = said.replace("\n", " ").strip()[:400]
        why = (getattr(m, "why", "") or "").strip()
        rows.append(f"[{n}] {_fmt_t(m.start)}-{_fmt_t(m.end)} | tags: {cats}\n"
                    f"    SEEN: {(m.description or '').strip()[:220]}\n"
                    f"    SAID: {said or '(no dialogue)'}" + (f"\n    WHY: {why}" if why else ""))
    ask = request.strip() if request and request.strip() else query
    extra = f'\nSearch phrase chosen by the assistant: "{query}"' if query and query != ask else ""
    k = min(len(cands), max(want + 4, 6))
    return f"""You pick moments from a video for short-form clips.

User's request: "{ask}"{extra}

Candidates (time = the analysed moment; SEEN = what is on screen there; SAID =
dialogue of the clip that would be cut around it; tags may be wrong):
{chr(10).join(rows)}

Rank the {k} candidates that best satisfy the request, best first. Judge the
actual content: a "funny" clip must actually be funny, a "tense" one must
carry real threat or suspense, a "quote" must be a strong line on its own.
Prefer moments that work standalone. Give each a short reason.
Return JSON: {{"ranked": [{{"id": 3, "reason": "..."}}, ...]}}"""


def parse_rerank(obj, n: int) -> list[tuple[int, str]]:
    """[(0-based candidate index, reason)] in rank order; tolerant of shape
    ({"ranked": [...]}, a bare list, ids as ints or numeric strings);
    unknown/out-of-range/duplicate ids dropped."""
    items = obj.get("ranked", obj.get("ids")) if isinstance(obj, dict) else obj
    out: list[tuple[int, str]] = []
    seen: set[int] = set()
    for it in items or []:
        if isinstance(it, dict):
            raw, reason = it.get("id", it.get("i")), str(it.get("reason") or "")
        else:
            raw, reason = it, ""
        try:
            i = int(str(raw).strip().strip("[]#")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < n and i not in seen:
            seen.add(i)
            out.append((i, reason.strip()[:200]))
    return out


def rerank(request: str, query: str, cands: Sequence, want: int,
           dialogue: Optional[Sequence[str]] = None) -> list[tuple[int, str]]:
    """Ranked [(index into cands, reason)]; empty list if the call fails
    (callers then keep the hybrid order)."""
    if not cands:
        return []
    from autoclip.config import OPENROUTER_MODEL_RERANK
    from autoclip.llm.openrouter import get_chat_model, invoke_json
    model = get_chat_model(OPENROUTER_MODEL_RERANK, temperature=0.0, max_tokens=4096)
    obj = invoke_json(model, RerankResult, rerank_prompt(request, query, cands, want, dialogue), "rerank")
    ranked = parse_rerank(obj, len(cands))
    if not ranked:
        logger.warning("rerank returned nothing usable for %r — keeping hybrid order", query)
    return ranked


def order_after_rerank(n: int, ranked: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Re-ranked ids first, then the remaining candidates in hybrid order."""
    got = {i for i, _ in ranked}
    return list(ranked) + [(i, "") for i in range(n) if i not in got]


# ─── diversity ──────────────────────────────────────────────

def conflicts(a: tuple[float, float], b: tuple[float, float],
              max_overlap: float = MAX_OVERLAP_FRAC, min_gap: float = MIN_CENTRE_GAP_S) -> bool:
    """True if two clip windows overlap > max_overlap of the shorter one, or
    their centres are within min_gap seconds."""
    (s1, e1), (s2, e2) = a, b
    inter = max(0.0, min(e1, e2) - max(s1, s2))
    shorter = max(1e-9, min(e1 - s1, e2 - s2))
    if inter / shorter > max_overlap:
        return True
    return abs((s1 + e1) / 2 - (s2 + e2) / 2) < min_gap


def pick_diverse(windows: Sequence[tuple[float, float]], want: int,
                 taken: Sequence[tuple[float, float]] = ()) -> list[int]:
    """Greedy, in order: indices of up to `want` windows that conflict with
    neither each other nor anything in `taken`."""
    chosen: list[int] = []
    busy = list(taken)
    for i, w in enumerate(windows):
        if len(chosen) >= want:
            break
        if any(conflicts(w, t) for t in busy):
            continue
        chosen.append(i)
        busy.append(w)
    return chosen


def embed_query(text: str) -> Optional[list[float]]:
    try:
        from autoclip.services.embeddings import embed_text
        return embed_text(text)
    except Exception as e:
        logger.warning("query embedding failed: %s", e)
        return None
