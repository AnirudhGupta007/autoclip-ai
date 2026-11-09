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
from typing import Iterable

from pydantic import BaseModel, Field

from autoclip.llm.openrouter import get_chat_model, invoke_json

logger = logging.getLogger(__name__)

CATEGORIES = ["funny", "action", "tense", "emotional", "romantic",
              "insightful", "quotable", "heated", "story"]
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
story      - a self-contained anecdote or narrative beat with setup and payoff"""


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
