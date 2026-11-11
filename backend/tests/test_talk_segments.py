"""Transcript-first talk segments: sentence building, segment boundaries,
strict tags + the share cap, sentence-snapped clip windows and the
SEGMENT_MODE switch. Every LLM call is mocked.

    docker run ... python -m pytest tests/test_talk_segments.py -q
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="autoclip-segtest-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("OUTPUT_DIR", str(_TMP / "outputs"))
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-used")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from autoclip.pipeline.state import Moment  # noqa: E402
from autoclip.services import talk_segments as T  # noqa: E402
from autoclip.services import moment_tagger as MT  # noqa: E402
from autoclip.rag import selection as S  # noqa: E402


def _transcript(n: int = 120, step: float = 5.0, gaps: dict | None = None) -> dict:
    """n one-sentence utterances, each `step` s long; each sentence is split
    into two utterances (the first without punctuation) to test merging.
    gaps = {sentence index: extra pause before it}."""
    utts, t = [], 0.0
    for i in range(n):
        t += (gaps or {}).get(i, 0.0)
        half = step / 2
        utts.append({"speaker": "A", "text": f"s{i} part one", "start": t, "end": t + half})
        utts.append({"speaker": "A", "text": f"part two of s{i}.", "start": t + half, "end": t + step})
        t += step
    words = [{"text": w, "start": u["start"], "end": u["end"]} for u in utts for w in u["text"].split()]
    return {"utterances": utts, "words": words, "duration": t}


def _moment(start, end, **kw) -> Moment:
    base = dict(visual_energy=0.0, audio_energy=0.0, text_hook_strength=0.0, convergence_score=0.5,
                modalities_active=1, style_tags=[], description="", transcript="")
    base.update(kw)
    return Moment(start=start, end=end, **base)


# ─── sentences ──────────────────────────────────────────────
def test_sentences_merge_utterances_up_to_punctuation():
    sents = T.sentences(_transcript(4))
    assert len(sents) == 4
    assert sents[1] == {"start": 5.0, "end": 10.0, "text": "s1 part one part two of s1."}


def test_sentences_cap_unpunctuated_runs():
    utts = [{"text": f"no stop {i}", "start": i * 5.0, "end": i * 5.0 + 5} for i in range(20)]
    sents = T.sentences({"utterances": utts})
    assert all(s["end"] - s["start"] <= T.SENTENCE_MAX_SECONDS for s in sents)
    assert len(sents) == 4   # 100 s cut every 25 s


# ─── boundaries ─────────────────────────────────────────────
def _check_spans(spans, sents, lo=0, hi=None):
    hi = len(sents) - 1 if hi is None else hi
    assert spans[0][0] == lo and spans[-1][1] == hi
    for (a, b), (c, _) in zip(spans, spans[1:]):
        assert c == b + 1, "spans must be contiguous"


def test_normalise_merges_short_and_splits_long():
    sents = T.sentences(_transcript(60))           # 300 s of 5 s sentences
    # model: a 10 s segment, then one 280 s segment
    spans = T.normalise_spans([0, 2], sents, 0, 59)
    _check_spans(spans, sents)
    for a, b in spans:
        assert T.SEGMENT_MIN_SECONDS <= T._dur(sents, a, b) <= T.SEGMENT_MAX_SECONDS


def test_normalise_ignores_bad_ids():
    sents = T.sentences(_transcript(30))
    spans = T.normalise_spans([-4, 0, 12, 12, 999], sents, 0, 29)
    assert spans == [(0, 11), (12, 29)]


def test_long_span_splits_at_the_biggest_pause():
    sents = T.sentences(_transcript(30, gaps={13: 3.0}))   # a 3 s pause before sentence 13
    spans = T.normalise_spans([], sents, 0, 29)             # one 153 s span
    assert (0, 12) in spans


def test_pause_fallback_respects_bounds():
    sents = T.sentences(_transcript(100, gaps={14: 4.0, 30: 4.0}))
    spans = T.pause_spans(sents, 0, 99)
    _check_spans(spans, sents)
    assert spans[0] == (0, 13)                      # cut at the pause, not at a fixed length
    assert all(T._dur(sents, a, b) <= T.SEGMENT_MAX_SECONDS for a, b in spans)


def test_segment_spans_uses_model_and_rereads_window_tail():
    sents = T.sentences(_transcript(240))           # 1200 s -> two+ windows of 600 s
    calls = []

    def fake(sents_, lo, hi):
        calls.append((lo, hi))
        # a segment every 12 sentences (60 s), payoff on the 10th
        return [{"first": f, "summary": f"topic {f}", "payoff": f + 9, "score": 0.6}
                for f in range(lo, hi + 1, 12)]

    out = T.segment_spans(sents, fake, window_s=600)
    spans = [(o["a"], o["b"]) for o in out]
    _check_spans(spans, sents)
    assert calls[1][0] in [a for a, _ in spans]     # window 2 starts on a span start
    assert calls[1][0] <= calls[0][1], "the last span of window 1 is re-read"
    assert all(T.SEGMENT_MIN_SECONDS <= T._dur(sents, a, b) <= T.SEGMENT_MAX_SECONDS for a, b in spans)
    assert all(o["a"] <= o["payoff"] <= o["b"] for o in out)
    assert out[0]["summary"] == "topic 0" and out[0]["payoff"] == 9


def test_segment_spans_falls_back_when_the_call_fails():
    sents = T.sentences(_transcript(60))

    def boom(*a):
        raise RuntimeError("upstream 500")
    out = T.segment_spans(sents, boom)
    _check_spans([(o["a"], o["b"]) for o in out], sents)
    assert all(o["payoff"] == o["b"] for o in out)


def test_build_segments_moments_and_vision_context():
    tr = _transcript(36)                            # 180 s
    vision = [_moment(70, 76, description="host laughs, slaps the desk", visual_energy=0.8)]

    def fake(sents, lo, hi):
        return [{"first": 0, "summary": "intro", "payoff": 5, "score": 0.4},
                {"first": 12, "summary": "the accountant story", "payoff": 22, "score": 0.9},
                {"first": 24, "summary": "advice", "payoff": 35, "score": 0.5}]
    segs = T.build_segments(tr, vision, call=fake)
    assert [(m.start, m.end) for m in segs] == [(0, 60), (60, 120), (120, 180)]
    s = segs[1]
    assert T.is_segment(s) and s.payoff == 115.0 and s.convergence_score == 0.9
    assert s.description.startswith("the accountant story") and "slaps the desk" in s.description
    assert s.visual_energy == 0.8 and "s12 part one" in s.transcript and "of s23." in s.transcript
    assert "On screen" not in segs[0].description


# ─── strict tags ────────────────────────────────────────────
def test_parse_strict_caps_two_and_drops_weak_and_unknown():
    obj = {"items": [{"i": 1, "tags": [{"c": "hot_take", "s": 3}, {"c": "funny", "s": 2},
                                       {"c": "story", "s": 3}]},
                     {"i": 2, "tags": [{"c": "insightful", "s": 1}, {"c": "vibes", "s": 3}]},
                     {"i": 2, "tags": [{"c": "funny", "s": 3}]}]}      # duplicate id ignored
    got = MT.parse_strict(obj, 2)
    assert got[0][0] == [("hot_take", 3), ("funny", 2)]
    assert got[1][0] == []


def test_cap_tags_keeps_the_strongest_quarter():
    tags = [[("insightful", 2)] for _ in range(12)] + [[("hot_take", 3), ("insightful", 3)]] * 4
    capped = MT.cap_tags(tags, 0.25)              # 16 segments -> at most 4 per tag
    n = lambda c: sum(c in x for x in capped)     # noqa: E731
    assert n("insightful") == 4 and n("hot_take") == 4
    # strength 3 beats 2, and listed-first beats listed-second at equal strength
    assert all("insightful" in x for x in capped[12:]) and not any("insightful" in x for x in capped[:12])


def test_tag_segments_distribution_respects_the_cap(monkeypatch):
    segs = [_moment(i * 60, i * 60 + 60, description=f"seg {i}", transcript="talk") for i in range(20)]

    def fake_invoke(model, schema, prompt, label):
        n = prompt.count("SUMMARY:")
        # an inflated model: everything insightful, half hot takes, 3 tags each
        return {"items": [{"i": k, "tags": [{"c": "insightful", "s": 2}, {"c": "hot_take", "s": 2 + k % 2},
                                            {"c": "funny", "s": 2}], "why": "w"} for k in range(1, n + 1)]}
    monkeypatch.setattr(MT, "invoke_json", fake_invoke)
    monkeypatch.setattr(MT, "get_chat_model", lambda *a, **k: None)
    dist = MT.tag_segments(segs, max_share=0.25)
    assert max(dist.values()) <= 5 and set(dist) == {"insightful", "hot_take"}   # funny was 3rd -> dropped
    assert all(len(m.categories) <= 2 and m.why for m in segs)


# ─── clip windows ───────────────────────────────────────────
def _seg(start, end, payoff=None):
    return _moment(start, end, style_tags=[T.SEGMENT_TAG], payoff=payoff)


def test_fit_segment_shorter_ask_ends_on_the_payoff():
    sents = T.sentences(_transcript(40))
    seg = _seg(60, 150, payoff=120)               # 90 s segment, payoff sentence ends at 120 s
    s, e = T.fit_segment(seg, 30, sents, tol=3)
    assert (s, e) == (90, 120)
    assert any(x["start"] == s for x in sents) and any(x["end"] == e for x in sents)


def test_fit_segment_longer_ask_adds_adjacent_sentences():
    sents = T.sentences(_transcript(40))
    seg = _seg(60, 90, payoff=85)
    s, e = T.fit_segment(seg, 60, sents, tol=6)
    assert e - s == pytest.approx(60, abs=6) and s <= 60 and e >= 90
    assert any(x["start"] == s for x in sents) and any(x["end"] == e for x in sents)


def test_fit_segment_respects_the_safe_range():
    sents = T.sentences(_transcript(40))
    s, e = T.fit_segment(_seg(150, 180, payoff=175), 60, sents, tol=6, hi=190)
    assert e <= 190 and e - s == pytest.approx(60, abs=6)


def test_clip_selector_fit_window_snaps_segments_to_sentences():
    from autoclip.pipeline.agents import clip_selector as CS
    tr = _transcript(40)
    sents = T.sentences(tr)
    s, e = CS._fit_window(_seg(60, 150, payoff=120), 30, tr, [])
    assert (s, e) == (90, 120)
    # a vision moment is still centred (old behaviour)
    s, e = CS._fit_window(_moment(100, 106), 30, tr, [])
    assert abs((s + e) / 2 - 103) < 3
    assert any(x["start"] == 90 for x in sents)


def test_rerank_prompt_reads_the_whole_segment():
    long_text = "word " * 200 + "THE PAYOFF LINE."
    seg = _seg(0, 80)
    seg.transcript, seg.description = long_text, "a story about an accountant"
    p = S.rerank_prompt("the best story", "story", [seg], 1, [long_text])
    assert "THE PAYOFF LINE." in p and "ABOUT: a story about an accountant" in p
    p = S.rerank_prompt("the best story", "story", [_moment(0, 5, transcript=long_text)], 1)
    assert "THE PAYOFF LINE." not in p     # vision moments keep the 400-char window


# ─── mode switch ────────────────────────────────────────────
def test_use_segments_modes():
    assert T.use_segments("audio", [], mode="auto")
    assert not T.use_segments("video", [], mode="auto")
    assert T.use_segments("video", [True, True, True, False], mode="auto")
    assert not T.use_segments("video", [True, False, False, False], mode="auto")
    assert T.use_segments("video", [], mode="segments")
    assert not T.use_segments("audio", [True], mode="moments")


def test_audio_routes_to_the_segmenter_and_video_fans_out(monkeypatch):
    from autoclip.pipeline import graph as G
    from autoclip.pipeline.state import ChunkPlan
    plan = ChunkPlan(index=0, start=0, end=120, video_path="x", transcript_window={})
    monkeypatch.setattr(T, "SEGMENT_MODE", "auto")
    assert G.route_after_planner({"media_kind": "audio", "chunk_plans": [plan], "video_id": "v"}) == "talk_segmenter"
    sends = G.route_after_planner({"media_kind": "video", "chunk_plans": [plan], "video_id": "v"})
    assert isinstance(sends, list) and len(sends) == 1
    monkeypatch.setattr(T, "SEGMENT_MODE", "moments")
    assert isinstance(G.route_after_planner({"media_kind": "audio", "chunk_plans": [plan], "video_id": "v"}), list)


def test_global_fusion_switches_on_static_chunks(monkeypatch):
    from autoclip.pipeline.agents import global_fusion as GF
    import autoclip.services.embeddings as E
    import autoclip.utils.video_profile as VP
    monkeypatch.setattr(T, "SEGMENT_MODE", "auto")
    monkeypatch.setattr(E, "embed_moments", lambda ms: None)
    monkeypatch.setattr(VP, "credits_start", lambda *a, **k: None)
    monkeypatch.setattr(GF.events, "publish_moments", lambda *a: None)
    monkeypatch.setattr(MT, "tag_segments", lambda segs: {})
    monkeypatch.setattr(MT, "tag_moments", lambda ms: 0)
    monkeypatch.setattr(T, "_llm_window", lambda *a: None)       # pause fallback, no network
    tr = _transcript(36)
    raw = [_moment(70, 76, description="laughs"), _moment(130, 134, description="points")]
    state = {"video_id": "", "video_path": "", "media_kind": "video", "transcript_data": tr,
             "moment_map_raw": list(raw)}
    out = GF.global_fusion_node({**state, "chunk_static": [True, True]})["moment_map"]
    assert out and all(T.is_segment(m) for m in out)
    assert all(m.end - m.start >= T.SEGMENT_MIN_SECONDS for m in out)
    assert any("laughs" in m.description for m in out)
    out = GF.global_fusion_node({**state, "chunk_static": [False, False]})["moment_map"]
    assert out and not any(T.is_segment(m) for m in out)
