"""Unit tests for moment selection: diversity filter, re-rank/tag parsing,
hybrid candidates, and the eval's ASS caption check. No network.

    cd backend && uv run --with pytest pytest tests/test_selection.py -q
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="autoclip-seltest-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("OUTPUT_DIR", str(_TMP / "outputs"))
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-used")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from autoclip.rag import selection as S  # noqa: E402
from evallib import probe as P  # noqa: E402


@dataclass
class M:
    start: float
    end: float
    description: str = ""
    transcript: str = ""
    style_tags: list = field(default_factory=list)
    categories: list = field(default_factory=list)
    why: str = ""
    convergence_score: float = 0.5
    embedding: list | None = None


# ─── diversity ──────────────────────────────────────────────
def test_conflicts_overlap_rule():
    assert S.conflicts((0, 30), (0, 30))                 # identical
    assert S.conflicts((0, 30), (20, 50))                # 10/30 = 33% > 30%
    assert not S.conflicts((0, 30), (25, 55))            # 5/30 = 17%, centres 25s apart
    assert not S.conflicts((0, 30), (100, 130))


def test_conflicts_centre_gap_rule():
    # no overlap at all, but centres 15s apart (short clips) -> too close
    assert S.conflicts((0, 10), (10, 20))                 # touching, centres 10s apart
    assert S.conflicts((0, 10), (15, 25))                 # centres 5 vs 20 -> 15s < 20s
    assert not S.conflicts((0, 10), (25, 35))             # centres 25s apart


def test_pick_diverse_keeps_order_and_skips_conflicts():
    windows = [(100, 130), (105, 135), (300, 330), (310, 340), (600, 630)]
    assert S.pick_diverse(windows, 3) == [0, 2, 4]
    assert S.pick_diverse(windows, 2) == [0, 2]
    # earlier clips (previous turns) block too
    assert S.pick_diverse(windows, 3, taken=[(98, 128)]) == [2, 4]


# ─── re-rank parsing ────────────────────────────────────────
def test_parse_rerank_shapes():
    obj = {"ranked": [{"id": 3, "reason": "big laugh"}, {"id": "1", "reason": "ok"}]}
    assert S.parse_rerank(obj, 5) == [(2, "big laugh"), (0, "ok")]
    assert S.parse_rerank([2, 4], 5) == [(1, ""), (3, "")]
    assert S.parse_rerank({"ids": ["#2", "[5]"]}, 5) == [(1, ""), (4, "")]


def test_parse_rerank_drops_bad_ids():
    obj = {"ranked": [{"id": 0}, {"id": 9}, {"id": 2}, {"id": 2}, {"id": "x"}, {"reason": "no id"}, "7"]}
    assert S.parse_rerank(obj, 3) == [(1, "")]
    assert S.parse_rerank(None, 3) == []
    assert S.parse_rerank({"something": 1}, 3) == []


def test_order_after_rerank_appends_rest():
    assert S.order_after_rerank(4, [(2, "a")]) == [(2, "a"), (0, ""), (1, ""), (3, "")]


# ─── hybrid candidates ──────────────────────────────────────
def test_query_categories_and_keywords():
    assert S.query_categories("Give me an action scene, 45 seconds, 16:9") == ["action"]
    assert S.query_categories("The best one-liner, 15 seconds") == ["quotable"]
    assert set(S.query_categories("A clip where someone gets shot at")) == {"action", "tense"}
    assert S.query_categories("An emotional or romantic moment") == ["emotional", "romantic"]
    assert S.keywords("A moment about enshittification and Big Tech") == ["enshittification", "big", "tech"]


def test_hybrid_candidates_unions_tag_keyword_vector():
    ms = [
        M(0, 10, "a man says joke", embedding=[1, 0]),            # vector-closest
        M(100, 110, "car chase", categories=["action"], why="x", embedding=[0, 1]),
        M(200, 210, "talks about pricing", embedding=[0, 1]),
        M(300, 310, "quiet", embedding=[0, 1], convergence_score=0.9),
    ]
    idx = S.hybrid_candidates(ms, "an action scene about pricing", query_vec=[1, 0], limit=3)
    assert idx[:3] == [0, 1, 2]  # interleaved: vector #1, tag #1, keyword #1
    # style_tags are the fallback only for untagged moments
    assert S.moment_categories(M(0, 1, style_tags=["quote", "hot_take"])) == {"quotable", "heated"}
    assert S.moment_categories(M(0, 1, style_tags=["quote"], categories=[], why="tagged")) == set()


def test_rerank_prompt_lists_every_candidate():
    ms = [M(65, 80, "a", "said a"), M(3700, 3720, "b")]
    p = S.rerank_prompt("give me something funny", "funny", ms, 1)
    assert "[1] 1:05-1:20" in p and "[2] 1:01:40-1:02:00" in p
    assert 'User\'s request: "give me something funny"' in p


# ─── tagger parsing ─────────────────────────────────────────
def test_parse_tags():
    from autoclip.services.moment_tagger import parse_tags
    obj = {"items": [{"i": 1, "categories": ["Funny", "bogus", "funny", "tense"], "why": "great punchline"},
                     {"i": 3, "categories": [], "why": ""}, {"i": 9, "categories": ["action"]}]}
    out = parse_tags(obj, 3)
    assert out[0] == (["funny", "tense"], "great punchline")
    assert out[2] == ([], "(tagged)")
    assert 1 not in out and 8 not in out


# ─── eval caption check ─────────────────────────────────────
def test_parse_ass_events():
    ass = ("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
           "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,hello\n"
           "Dialogue: 0,0:00:29.00,0:00:31.00,Default,,0,0,0,,edge\n"
           "Dialogue: 0,0:00:40.00,0:00:41.00,Default,,0,0,0,,after\n")
    assert P.parse_ass_events(ass, 30.0) == 2
    assert P.parse_ass_events("", 30.0) == 0
    assert P.captions_from_ass(True, 2) == (True, "ass_events")
    assert P.captions_from_ass(True, 0) == (False, "ass_empty")
    assert P.captions_from_ass(False, None) == (None, None)
