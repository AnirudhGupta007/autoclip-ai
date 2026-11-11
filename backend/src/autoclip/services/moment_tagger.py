"""Text-only tagging pass over analysed moments.

The vision model's `style_tags` (hot_take/story/quote/...) were designed for
talking-head content and miss what people actually ask for ("an action
scene", "the most tense moment", "something romantic"). Rather than
re-running the expensive vision analysis, one cheap lite-model pass reads
each moment's description + own-window dialogue and adds:

  * categories — 0-3 of CATEGORIES
  * why        — one short "why it works as a clip" line

It runs at the end of analysis (global_fusion) and can be backfilled for
already-analysed videos with scripts/backfill_moment_tags.py. Batched
(BATCH moments per call, a few calls in parallel); a failed batch leaves
those moments untagged rather than failing the analysis.
"""
from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from autoclip.llm.openrouter import get_chat_model, invoke_json

logger = logging.getLogger(__name__)

CATEGORIES = ["funny", "action", "tense", "emotional", "romantic",
              "insightful", "quotable", "heated", "story",
              "hot_take", "advice"]   # last two: podcasts / interviews
BATCH = 20
WORKERS = 4
LABEL = "lite_tagging"

_DEFS = """funny      - humour: a joke, punchline, absurd situation, comic timing, audience laughter
action     - physical action: fight, chase, shooting, crash, stunt, explosion
tense      - suspense or threat: danger, standoff, gun drawn, confrontation, high stakes
emotional  - sadness, vulnerability, tears, a heartfelt confession or plea
romantic   - flirting, attraction, love, intimacy
insightful - a clear, smart idea, argument or explanation worth sharing
quotable   - a punchy line that works out of context (one-liner, soundbite)
heated     - anger, a rant, passionate condemnation, a fiery outburst, crowd roaring
story      - a self-contained anecdote or narrative beat with setup and payoff
hot_take   - a bold, contrarian or controversial opinion stated with conviction
advice     - concrete, actionable advice or a how-to tip the listener could apply"""


class _Tag(BaseModel):
    i: int = Field(description="the moment's number from the list")
    categories: list[str] = Field(default_factory=list, description="0-3 categories")
    why: str = Field(default="", description="<= 15 words: why it works (or not) as a short clip")


class _TagBatch(BaseModel):
    items: list[_Tag] = Field(default_factory=list)


def _prompt(batch: list) -> str:
    lines = []
    for n, m in enumerate(batch, 1):
        said = (m.transcript or "").strip().replace("\n", " ")[:400]
        lines.append(f"[{n}] SEEN: {(m.description or '').strip()[:240]}\n    SAID: {said or '(no dialogue)'}")
    return f"""You label moments from a video for a short-form clip search engine.

Categories (use ONLY these names):
{_DEFS}

For each numbered moment give 0-3 categories that clearly apply, based on what
is seen and said — do not guess from a single word (a person saying "joke" is
not automatically funny). Then a short "why" line (<= 15 words) saying why it
would or would not work as a standalone clip.

Moments:
{chr(10).join(lines)}

Return JSON: {{"items": [{{"i": 1, "categories": ["funny"], "why": "..."}}, ...]}} with one item per moment."""


def parse_tags(obj, n: int) -> dict[int, tuple[list[str], str]]:
    """{0-based index: (categories, why)} from a model reply; unknown categories dropped."""
    items = obj.get("items") if isinstance(obj, dict) else obj
    out: dict[int, tuple[list[str], str]] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("i")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= i < n or i in out:
            continue
        cats = []
        for c in it.get("categories") or []:
            c = str(c).strip().lower()
            if c in CATEGORIES and c not in cats:
                cats.append(c)
        why = str(it.get("why") or "").strip()[:160] or "(tagged)"
        out[i] = (cats[:3], why)
    return out


def _tag_batch(batch: list) -> int:
    obj = invoke_json(get_chat_model(lite=True, temperature=0.0, max_tokens=4096),
                      _TagBatch, _prompt(batch), LABEL)
    tags = parse_tags(obj, len(batch))
    for i, (cats, why) in tags.items():
        batch[i].categories = cats
        batch[i].why = why
    return len(tags)


def tag_moments(moments: Iterable, force: bool = False) -> int:
    """Set .categories/.why on moments (anything with description/transcript
    attributes). Skips already-tagged ones unless `force`. Returns #tagged."""
    todo = [m for m in moments if force or not (getattr(m, "why", "") or "")]
    if not todo:
        return 0
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        done = sum(pool.map(_tag_batch, batches))
    logger.info("moment_tagger: tagged %d/%d moments in %d batch(es)", done, len(todo), len(batches))
    return done


# ─── strict tagging for talk segments ───────────────────────
# Segments are 30-90s of conversation, so the loose pass above tags nearly
# everything "insightful" and a third "hot_take" (measured on the Blocks
# podcast), and tag retrieval can't tell them apart. The strict pass asks
# for at most 2 categories with a strength, defines each one narrowly, and
# cap_tags() then keeps any one category on at most SEGMENT_TAG_MAX_SHARE of
# the video's segments (the strongest ones).
SEGMENT_BATCH = 10
MAX_SEGMENT_TAGS = 2
LABEL_STRICT = "lite_tagging_strict"

_STRICT_DEFS = """funny      - the audience or the other speaker would actually laugh: a joke or bit
             that lands. Friendly banter or a light tone is NOT enough.
story      - someone narrates something that happened (a specific time, place or
             person) with a setup and an ending. General discussion is NOT a story.
hot_take   - a contrarian or provocative opinion that many listeners would push back
             on, stated with conviction. An ordinary opinion or preference is NOT one.
advice     - concrete advice the listener could act on ("do X", "never Y").
insightful - a non-obvious idea or explanation a listener would learn something
             from. Ordinary chat, opinions and anecdotes are NOT insightful.
quotable   - contains one short line that works as a soundbite out of context.
heated     - anger, a rant, a raised-voice argument or passionate condemnation.
emotional  - sadness, vulnerability, a heartfelt confession.
tense      - real threat, conflict or suspense.
romantic   - flirting, love, attraction.
action     - physical action on screen (fight, chase, stunt)."""


class _StrictTag(BaseModel):
    c: str = Field(description="category name")
    s: int = Field(default=2, description="2 = clearly present, 3 = the defining feature")


class _StrictItem(BaseModel):
    i: int
    tags: list[_StrictTag] = Field(default_factory=list, description="0-2 tags")
    why: str = Field(default="", description="<= 15 words")


class _StrictBatch(BaseModel):
    items: list[_StrictItem] = Field(default_factory=list)


def _strict_prompt(batch: list) -> str:
    lines = []
    for n, m in enumerate(batch, 1):
        said = (m.transcript or "").strip().replace("\n", " ")[:1500]
        lines.append(f"[{n}] SUMMARY: {(m.description or '').strip()[:300]}\n    SAID: {said or '(no dialogue)'}")
    return f"""You label 30-90 second segments of a podcast, interview or talk for a
clip search engine. Labels must be selective: they are only useful if they
separate segments. Most segments get 0 or 1 tag; a tag that fits most of the
conversation fits none of it.

Categories (use ONLY these names, and only when clearly present in SAID):
{_STRICT_DEFS}

For each segment give at most {MAX_SEGMENT_TAGS} tags, strongest first, each with a strength:
2 = clearly present, 3 = it is what the segment is about. If in doubt, leave it out.
Then a short "why" line (<= 15 words): why it would or would not work as a clip.

Segments:
{chr(10).join(lines)}

Return JSON: {{"items": [{{"i": 1, "tags": [{{"c": "story", "s": 3}}], "why": "..."}}, ...]}} with one item per segment."""


def parse_strict(obj, n: int) -> dict[int, tuple[list[tuple[str, int]], str]]:
    """{0-based index: ([(category, strength)], why)} — unknown names and
    strengths < 2 dropped, at most MAX_SEGMENT_TAGS per segment."""
    items = obj.get("items") if isinstance(obj, dict) else obj
    out: dict[int, tuple[list[tuple[str, int]], str]] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            i = int(it.get("i")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= i < n or i in out:
            continue
        tags: list[tuple[str, int]] = []
        for t in it.get("tags") or []:
            if isinstance(t, dict):
                c, s = str(t.get("c") or t.get("category") or "").strip().lower(), t.get("s", 2)
            else:
                c, s = str(t).strip().lower(), 2
            try:
                s = int(s)
            except (TypeError, ValueError):
                s = 2
            if c in CATEGORIES and s >= 2 and c not in [x for x, _ in tags]:
                tags.append((c, min(s, 3)))
        out[i] = (tags[:MAX_SEGMENT_TAGS], str(it.get("why") or "").strip()[:160] or "(tagged)")
    return out


def cap_tags(tags: list[list[tuple[str, int]]], max_share: float) -> list[list[str]]:
    """Keep each category on at most max(1, floor(max_share * n)) segments:
    the ones where it is strongest (strength, then listed first), earliest
    segment on ties. Returns plain category lists in the original order."""
    n = len(tags)
    cap = max(1, int(max_share * n))
    keep: set[tuple[int, str]] = set()
    for c in {c for ts in tags for c, _ in ts}:
        holders = [(-s, pos, i) for i, ts in enumerate(tags) for pos, (cc, s) in enumerate(ts) if cc == c]
        for _, _, i in sorted(holders)[:cap]:
            keep.add((i, c))
    return [[c for c, _ in ts if (i, c) in keep] for i, ts in enumerate(tags)]


def tag_segments(segments: list, max_share: Optional[float] = None) -> dict[str, int]:
    """Strict tags on talk segments (all of them, in place). Returns the tag
    distribution {category: count} after the cap."""
    from autoclip.config import OPENROUTER_MODEL_SEGMENT, SEGMENT_TAG_MAX_SHARE
    share = SEGMENT_TAG_MAX_SHARE if max_share is None else max_share
    if not segments:
        return {}
    raw: list[list[tuple[str, int]]] = [[] for _ in segments]
    whys = ["" for _ in segments]
    starts = list(range(0, len(segments), SEGMENT_BATCH))

    def run(k: int) -> None:
        batch = segments[k:k + SEGMENT_BATCH]
        obj = invoke_json(get_chat_model(OPENROUTER_MODEL_SEGMENT, temperature=0.0, max_tokens=4096),
                          _StrictBatch, _strict_prompt(batch), LABEL_STRICT)
        for i, (tags, why) in parse_strict(obj, len(batch)).items():
            raw[k + i], whys[k + i] = tags, why

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(run, starts))
    capped = cap_tags(raw, share)
    dist: dict[str, int] = {}
    for m, cats, why in zip(segments, capped, whys):
        m.categories = cats
        m.why = why or "(untagged)"
        for c in cats:
            dist[c] = dist.get(c, 0) + 1
    logger.info("moment_tagger: strict tags on %d segments: %s", len(segments), dist)
    return dist
