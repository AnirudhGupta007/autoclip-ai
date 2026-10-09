"""Unit tests for backend/scripts/evallib — hand-computed cases.

Run:  uv run --no-project --with pytest pytest backend/tests/test_evallib.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evallib import metrics as M  # noqa: E402
from evallib import report as R  # noqa: E402
from evallib import score as S  # noqa: E402
from evallib.client import looks_like_analysis_started  # noqa: E402
from evallib.runs import build_message, load_gt, match_query  # noqa: E402

approx = pytest.approx


# ------------------------------------------------------------------ overlap rule
def test_overlap_and_tiou():
    assert M.overlap((0, 10), (5, 20)) == 5
    assert M.overlap((0, 10), (10, 20)) == 0
    assert M.tiou((0, 10), (5, 15)) == approx(5 / 15)
    assert M.tiou((0, 10), (0, 10)) == 1.0


def test_match_uses_shorter_span():
    # 15s clip fully inside a 60s scene: overlap 15 >= 0.5*15
    assert M.matches((110, 125), (100, 160))
    # exactly half of the shorter span is enough
    assert M.matches((0, 30), (15, 75))       # overlap 15 = 0.5*30
    assert not M.matches((0, 30), (15.1, 75))  # overlap 14.9
    # baseline clip d: 610-640 vs labelled 628-672 → overlap 12 < 15
    assert not M.matches((610, 640), (628, 672))
    # baseline clip a1: 87.5-117.5 vs 100-150 → overlap 17.5 >= 15
    assert M.matches((87.5, 117.5), (100, 150))
    # touching spans never match
    assert not M.matches((0, 10), (10, 20))


def test_greedy_match_is_one_to_one_and_prefers_tiou():
    gts = [(0, 10), (10, 20)]
    # one long pred overlapping both gts can only take one of them
    assert len(M.greedy_match([(0, 20)], gts)) == 1
    # two preds, both match gt0; the better-tIoU one wins, the other is unmatched
    out = M.greedy_match([(0, 12), (1, 10)], [(0, 10)])
    assert out == [(1, 0, approx(0.9))]


def test_recall_precision_at_k():
    gts = [(0, 10), (100, 110), (200, 210), (300, 310)]
    preds = [(0, 10), (50, 60), (100, 110), (100, 108), (900, 910)]
    assert M.recall_at_k(preds, gts, 1) == 0.25
    assert M.precision_at_k(preds, gts, 1) == 1.0
    assert M.recall_at_k(preds, gts, 3) == 0.5
    assert M.precision_at_k(preds, gts, 3) == approx(2 / 3)
    # (100,108) duplicates an already-matched gt → no extra credit
    assert M.recall_at_k(preds, gts, None) == 0.5
    assert M.precision_at_k(preds, gts, None) == approx(2 / 5)
    # k larger than the list uses what's there
    assert M.precision_at_k(preds[:2], gts, 10) == 0.5
    assert M.precision_at_k([], gts, 10) is None
    assert M.recall_at_k(preds, [], 10) is None


# ----------------------------------------------------------------- ranking metrics
def test_hit_mrr_truth_rank():
    truth = [(100, 150), (200, 250), (300, 350)]
    preds = [(0, 30), (205, 235), (110, 140)]
    assert M.hit_at_k(preds, truth, 1) == 0.0
    assert M.hit_at_k(preds, truth, 3) == 1.0
    assert M.mrr(preds, truth) == 0.5
    assert M.best_truth_rank(preds, truth) == 1  # third pred hits truth #1
    assert M.best_truth_rank(preds[:2], truth) == 2
    assert M.mrr([(0, 30)], truth) == 0.0
    assert M.hit_at_k([], truth, 3) == 0.0   # produced nothing = miss
    assert M.best_truth_rank([], truth) is None


def test_tag_precision():
    moments = [{"start": 100, "end": 150, "tags": ["funny"]},
               {"start": 200, "end": 260, "tags": ["romantic", "emotional"]},
               {"start": 300, "end": 340, "tags": ["action", "shot_at"]}]
    clips = [(90, 120), (210, 240), (500, 530), (305, 335)]
    assert M.tag_hits(clips, moments, ["funny"]) == [True, False, False, False]
    assert M.tag_precision(clips, moments, ["funny"]) == 0.25
    assert M.tag_precision(clips, moments, ["emotional", "romantic"]) == 0.25
    assert M.tag_precision(clips, moments, ["shot_at"]) == 0.25
    assert M.tag_precision([], moments, ["funny"]) is None


# ------------------------------------------------------------------- format checks
def test_length_adherence():
    assert M.length_ok(33.0, 30, 0.10) is True
    assert M.length_ok(33.1, 30, 0.10) is False
    assert M.length_ok(22.83, 20, 0.10) is False   # baseline 1:1 clip
    assert M.length_ok(22.83, 20, 0.25) is True
    assert M.length_ok(27.0, 30, 0.10) is True
    assert M.length_ok(30.0, None, 0.10) is None
    assert M.rate([True, False, None, True]) == approx(2 / 3)
    assert M.rate([None]) is None


def test_aspect_adherence():
    assert M.aspect_ok(1080, 1920, "9:16") is True
    assert M.aspect_ok(1080, 1080, "1:1") is True
    assert M.aspect_ok(1280, 720, "16:9") is True
    assert M.aspect_ok(1080, 1920, "16:9") is False
    assert M.aspect_ok(1080, 1350, "4:5") is True
    assert M.aspect_ok(1080, 1900, "9:16") is True    # 1.0% off
    assert M.aspect_ok(1080, 1800, "9:16") is False   # 6.7% off
    assert M.aspect_ok(1080, 1920, None) is None


def test_duplicates():
    spans = [(0, 30), (5, 35), (100, 130), (0, 30), (200, 230)]
    assert M.duplicate_flags(spans) == [False, True, False, True, False]
    assert M.duplicate_rate(spans) == 0.4
    assert M.duplicate_rate([]) is None


# --------------------------------------------------------------- temporal coverage
def test_coverage_by_tenth():
    film_end = 1000
    gts = [(10, 50), (150, 190), (160, 180), (950, 990)]
    preds = [(15, 45), (155, 185), (5000, 5010)]
    bins = M.coverage_by_tenth(preds, gts, film_end)
    assert len(bins) == 10
    assert (bins[0]["n_gt"], bins[0]["n_hit"], bins[0]["recall"]) == (1, 1, 1.0)
    # two gts in tenth 2 but only one pred → one-to-one gives 1/2
    assert (bins[1]["n_gt"], bins[1]["n_hit"], bins[1]["recall"]) == (2, 1, 0.5)
    assert bins[5]["recall"] is None
    assert (bins[9]["n_gt"], bins[9]["n_hit"]) == (1, 0)
    # the pred past film_end is clamped into the last bucket
    assert bins[9]["n_pred"] == 1
    assert sum(b["n_hit"] for b in bins) / len(gts) == M.recall_at_k(preds, gts)


def test_within_chunk_offsets_and_histogram():
    # stride = 120 - 10 = 110
    offs = M.within_chunk_offsets([5, 115, 230, 330], 120, 10)
    assert offs == approx([5, 5, 10, 0])
    # with explicit chunk indices the offset can sit in the overlap tail
    offs2 = M.within_chunk_offsets([115, 225], 120, 10, chunk_index=[0, 1])
    assert offs2 == approx([115, 115])
    h = M.within_chunk_histogram([5, 25, 61, 119, 70], 120, 20)
    assert h["counts"] == [1, 1, 0, 2, 0, 1]
    assert h["frac_second_half"] == approx(3 / 5)
    assert M.within_chunk_histogram([], 120, 20)["frac_second_half"] is None


def test_last_analysed_credits_gaps():
    spans = [(0, 30), (400, 420), (5590, 5620), (5700, 5710)]
    assert M.last_analysed_fraction(spans, 5600) == approx(5710 / 5600)
    assert M.credits_violations(spans, 5600) == [3]
    assert M.coverage_gaps(spans, 1000, 300) == [(30, 400), (420, 1000)]
    assert M.coverage_gaps([(0, 1000)], 1000, 300) == []
    assert M.last_analysed_fraction([], 5600) is None


def test_transcript_minute_coverage():
    words = [0.5, 59.9, 60.0, 61, 5401.46, 5545.0, 5700]  # last one is in the credits
    tc = M.transcript_minute_coverage(words, 5600)
    assert tc["minutes"] == 94
    assert tc["covered_minutes"] == [0, 1, 90, 92]
    assert tc["fraction"] == approx(4 / 94)


# --------------------------------------------------------------- glue / reporting
def test_bar():
    assert R.bar(0) == "░" * 10
    assert R.bar(1) == "█" * 10
    assert R.bar(0.5) == "█████░░░░░"
    assert len(R.bar(0.37)) == 10
    assert R.bar(None) == "·" * 10


def test_analysis_started_heuristic():
    assert looks_like_analysis_started({"response": "I've started analysing your video — check back in a few minutes."})
    assert looks_like_analysis_started({"response": "Analysis is now running in the background.", "clips": None})
    assert looks_like_analysis_started({"response": "ok", "status": "analyzing"})
    assert not looks_like_analysis_started({"response": "I've analyzed the video and produced 4 clips",
                                            "clips": [{"id": "x"}]})
    assert not looks_like_analysis_started({"response": "Here is your clip."})


GT_PATH = ROOT / "eval" / "movies" / "wild_target.json"


@pytest.mark.skipif(not GT_PATH.is_file(), reason="ground truth not present")
def test_ground_truth_file_and_query_matching():
    gt = load_gt(GT_PATH)
    assert len(gt["moments"]) == 35 and len(gt["queries"]) == 6
    assert all(1 <= m["grade"] <= 3 for m in gt["moments"])
    assert all(m["end"] <= gt["film_end"] for m in gt["moments"])
    for q in gt["queries"]:
        # every truth moment carries at least one of the query's tags
        ids = {m["id"]: m for m in gt["moments"]}
        assert all(set(q["tags"]) & set(ids[t]["tags"]) for t in q["truth"]), q["id"]
    assert match_query("Give me an action scene, 45 seconds, 16:9", gt["queries"])["id"] == "q_action"
    assert match_query("show me the funniest bit", gt["queries"])["id"] == "q_funny"
    assert match_query("best one-liner please", gt["queries"])["id"] == "q_one_liner"
    assert build_message({"prompt": "the funniest moment", "count": 1, "length": 30, "frame": "9:16"}) == \
        "Give me the funniest moment, 30 seconds, 9:16"


def test_score_run_end_to_end():
    gt = {"film_end": 1000, "chunking": {"chunk_s": 120, "overlap_s": 10},
          "moments": [{"id": "m1", "start": 100, "end": 150, "tags": ["funny"], "note": "a"},
                      {"id": "m2", "start": 300, "end": 360, "tags": ["action"], "note": "b"},
                      {"id": "m3", "start": 600, "end": 640, "tags": ["funny"], "note": "c"}],
          "queries": [{"id": "q1", "prompt": "funny", "count": 2, "length": 30, "frame": "9:16",
                       "tags": ["funny"], "truth": ["m3", "m1"]},
                      {"id": "q2", "prompt": "action", "count": 1, "length": 20, "frame": "1:1",
                       "tags": ["action"], "truth": ["m2"]}]}
    run = {"clips": {
        "a": {"id": "a", "start": 290, "end": 320, "delivered_len_s": 30.5, "delivered_res": "1080x1920"},
        "b": {"id": "b", "start": 110, "end": 140, "delivered_len_s": 34.0, "delivered_res": "1080x1920"},
        "c": {"id": "c", "start": 800, "end": 820, "delivered_len_s": 20.0, "delivered_res": "1080x1920"}},
        "moments": [{"start": 105, "end": 115, "convergence_score": 0.9},
                    {"start": 900, "end": 910, "convergence_score": 0.5}],
        "transcript": {"word_starts": [10.0, 130.0]}}
    queries = [{"query_id": "q1", "clip_ids": ["a", "b"], "returned_ids": ["a", "b"], "elapsed_s": 10},
               {"query_id": "q2", "clip_ids": ["c"], "returned_ids": ["a", "b", "c"], "elapsed_s": 5}]
    sc = S.score_run(gt, run, queries, probes={})
    q1, q2 = sc["per_query"]
    # q1: clip a (290-320) overlaps m2 by 20s >= 15 → matches a human moment, but m2 is
    # action and not in q1's truth; clip b hits m1 (truth #2)
    assert (q1["hit_at_1"], q1["hit_at_3"], q1["mrr"], q1["best_truth_rank"]) == (0.0, 1.0, 0.5, 2)
    assert q1["tag_precision"] == 0.5
    assert q1["length_adherence_10"] == 0.5     # 30.5 ok, 34.0 not
    assert q2["n_stale_returned"] == 2
    assert q2["aspect_adherence"] == 0.0         # asked 1:1, got 9:16
    s = sc["summary"]
    assert s["hit_at_3"] == 0.5 and s["mrr"] == 0.25
    assert s["tag_precision"] == approx(1 / 3)   # 1 of 3 clips
    assert s["clip_precision"] == approx(2 / 3)   # a→m2, b→m1, c→none
    an = S.score_analysis(gt, run)
    assert an["moment_recall_all"] == approx(1 / 3)
    assert an["moment_precision_10"] == 0.5
    assert an["transcript_coverage"] == approx(2 / 17)
    # a self-diff never regresses; a drop beyond the threshold does
    head = S.headline([sc], an, run)
    rows, reg = S.diff(head, head, 0.05)
    assert not reg
    worse = dict(head, hit_at_3=head["hit_at_3"] - 0.1)
    assert S.diff(worse, head, 0.05)[1] is True
    md = R.render_md({"gt": {"title": "T", "license_note": "x", "n_moments": 3, "n_queries": 2, "film_end": 1000,
                             "duration": 1100, "chunk_s": 120},
                      "meta": {"generated_utc": "now", "mode": "test", "runs": 1},
                      "headline": head, "summary_extra": s, "analysis": an,
                      "runs": [{"run": 1, **sc}], "gt_queries": {q["id"]: q for q in gt["queries"]},
                      "gt_moments": {m["id"]: m for m in gt["moments"]}})
    assert "## Scoreboard" in md and "Per clip" in md
    json.dumps(sc)  # report must be serialisable
