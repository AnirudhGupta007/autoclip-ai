"""Go-live hardening: the one-at-a-time analysis queue (with positions), the
site-wide daily analysis-minutes cap, and /api/health/ready.

Reuses the app + temp DB set up by test_auth_isolation (same process). The
pipeline is replaced by a stub that waits on an Event — no ffmpeg, no LLM.
"""
from __future__ import annotations

import threading
import time

import httpx
import pytest

from test_auth_isolation import (  # noqa: F401
    PASSWORD, SessionLocal, Video, _client, _make_video, _signup, agent_tools,
)

from autoclip import config
from autoclip.services import health, rate_limit, storage
from autoclip.utils import analysis_jobs as AJ


# ─── analysis queue ─────────────────────────────────────────────

class GatedPipeline:
    """Stand-in for _run_pipeline: each video runs until its gate opens."""

    def __init__(self):
        self.gates: dict[str, threading.Event] = {}
        self.started: list[str] = []
        self.fail: set[str] = set()

    def __call__(self, video_id: str) -> None:
        self.started.append(video_id)
        self.gates.setdefault(video_id, threading.Event()).wait(10)
        if video_id in self.fail:
            raise RuntimeError("pipeline blew up")
        db = SessionLocal()
        try:
            db.get(Video, video_id).status = AJ.ANALYZED
            db.commit()
        finally:
            db.close()

    def release(self, video_id: str) -> None:
        self.gates.setdefault(video_id, threading.Event()).set()


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def gated(monkeypatch):
    g = GatedPipeline()
    monkeypatch.setattr(AJ, "_run_pipeline", g)
    monkeypatch.setattr(AJ, "MAX_CONCURRENCY", 1)
    yield g
    for vid in list(g.gates) + g.started:
        g.release(vid)
    _wait(lambda: not AJ._queue)


def test_queue_runs_one_at_a_time_and_reports_position(gated):
    _, me = _signup()
    vids = [_make_video(me["id"], analyzed=False)[0] for _ in range(3)]
    for v in vids:
        assert AJ.start_analysis(v)["result"] == "started"
    assert _wait(lambda: gated.started == vids[:1])
    assert AJ.queue_position(vids[0]) == 0
    states = [AJ.video_state(v) for v in vids]
    assert [s["status"] for s in states] == [AJ.ANALYZING] * 3
    assert [s["queue_position"] for s in states] == [None, 1, 2]
    assert states[1]["stage"] == "queued"
    time.sleep(0.2)
    assert gated.started == vids[:1]                     # still only one running

    gated.release(vids[0])
    assert _wait(lambda: gated.started == vids[:2])
    assert _wait(lambda: AJ.video_state(vids[2])["queue_position"] == 1)
    assert AJ.video_state(vids[1])["queue_position"] is None
    assert AJ.video_state(vids[0])["status"] == AJ.ANALYZED

    gated.release(vids[1])
    gated.release(vids[2])
    assert _wait(lambda: all(AJ.video_state(v)["status"] == AJ.ANALYZED for v in vids))
    assert not AJ._queue


def test_queued_position_reaches_the_chat_and_events(gated, monkeypatch):
    events = []
    monkeypatch.setattr(AJ.pipeline_events, "publish_analysis",
                        lambda vid, typ, data: events.append((vid, typ, dict(data))))
    _, other = _signup()
    blocker, _ = _make_video(other["id"], analyzed=False)
    AJ.start_analysis(blocker)
    assert _wait(lambda: gated.started == [blocker])

    c, me = _signup()
    vid, _ = _make_video(me["id"], analyzed=False)
    r = c.post("/api/chat/message", json={"message": "3 funny clips", "video_id": vid})
    body = r.json()
    assert r.status_code == 200 and body["pending_request"] is True
    assert body["analysis"]["queue_position"] == 1
    assert "#1 in line" in body["response"]
    # asking again while queued: same position, nothing charged twice
    r = c.post("/api/chat/message", json={"message": "3 funny clips", "video_id": vid})
    assert r.json()["analysis"]["queue_position"] == 1 and "#1 in line" in r.json()["response"]
    assert r.json()["queries_remaining"] == 1
    assert c.get(f"/api/chat/analysis/{vid}").json()["queue_position"] == 1
    mine = [e for e in events if e[0] == vid]
    assert mine[0][1] == "analysis_started" and mine[0][2]["queue_position"] == 1
    assert any(t == "analysis_progress" and d.get("stage") == "queued" and d["queue_position"] == 1
               for _, t, d in mine)

    gated.release(blocker)
    assert _wait(lambda: gated.started == [blocker, vid])
    assert c.get(f"/api/chat/analysis/{vid}").json()["queue_position"] is None
    assert any(t == "analysis_progress" and d.get("queue_position") is None
               for v, t, d in events if v == vid)


# ─── daily analysis-minutes cap ─────────────────────────────────

def _video_of_minutes(user_id: int, minutes: float) -> str:
    vid, _ = _make_video(user_id, analyzed=False)
    db = SessionLocal()
    try:
        db.get(Video, vid).duration = minutes * 60
        db.commit()
    finally:
        db.close()
    return vid


def test_analysis_minutes_cap(gated, monkeypatch):
    used = rate_limit.analysis_minutes_used()
    monkeypatch.setattr(config, "DAILY_ANALYSIS_MINUTES_LIMIT", used + 2)
    c, me = _signup()
    first = _video_of_minutes(me["id"], 1.5)          # charged 2 minutes
    assert AJ.start_analysis(first)["result"] == "started"
    assert rate_limit.analysis_minutes_used() == used + 2

    second = _video_of_minutes(me["id"], 0.5)
    r = c.post("/api/chat/message", json={"message": "clips", "video_id": second})
    assert r.status_code == 429 and "tomorrow" in r.json()["detail"]
    assert c.get("/api/chat/quota").json()["remaining"] == 2      # the query was refunded
    assert AJ.video_state(second)["status"] == AJ.UPLOADED
    cfg = {"configurable": {"user_id": me["id"]}}
    assert agent_tools.ingest_and_analyze_video.invoke({"video_id": second}, config=cfg)["status"] == "daily_cap"
    # admins are exempt
    assert AJ.start_analysis(second, cap_exempt=True)["result"] == "started"
    assert rate_limit.analysis_minutes_used() == used + 2


def test_failed_analysis_refunds_minutes(gated, monkeypatch):
    used = rate_limit.analysis_minutes_used()
    monkeypatch.setattr(config, "DAILY_ANALYSIS_MINUTES_LIMIT", used + 100)
    _, me = _signup()
    vid = _video_of_minutes(me["id"], 3)
    gated.fail.add(vid)
    assert AJ.start_analysis(vid)["result"] == "started"
    assert rate_limit.analysis_minutes_used() == used + 3
    gated.release(vid)
    assert _wait(lambda: AJ.video_state(vid)["status"] == AJ.FAILED)
    assert _wait(lambda: rate_limit.analysis_minutes_used() == used)


def test_daily_analysis_count_cap(gated, monkeypatch):
    from autoclip.auth import settings as auth_settings
    used = rate_limit.analyses_used()
    monkeypatch.setattr(auth_settings, "DAILY_ANALYSIS_LIMIT", used + 2)
    monkeypatch.setattr(config, "DAILY_ANALYSIS_MINUTES_LIMIT", 0)
    _, a = _signup()
    c, b = _signup()
    first, second = _video_of_minutes(a["id"], 1), _video_of_minutes(b["id"], 1)
    for v in (first, second):
        gated.release(v)                               # let them finish; only the charge matters
        assert AJ.start_analysis(v)["result"] == "started"
    assert rate_limit.analyses_used() == used + 2

    third = _video_of_minutes(b["id"], 1)              # a third, from either user, is refused
    r = c.post("/api/chat/message", json={"message": "clips", "video_id": third})
    assert r.status_code == 429 and "tomorrow" in r.json()["detail"]
    assert AJ.video_state(third)["status"] == AJ.UPLOADED
    assert rate_limit.analyses_used() == used + 2
    gated.release(third)
    assert AJ.start_analysis(third, cap_exempt=True)["result"] == "started"   # admins exempt
    assert _wait(lambda: AJ.video_state(third)["status"] == AJ.ANALYZED)


def test_failed_analysis_refunds_the_daily_slot(gated, monkeypatch):
    from autoclip.auth import settings as auth_settings
    used = rate_limit.analyses_used()
    monkeypatch.setattr(auth_settings, "DAILY_ANALYSIS_LIMIT", used + 5)
    _, me = _signup()
    vid = _video_of_minutes(me["id"], 1)
    gated.fail.add(vid)
    assert AJ.start_analysis(vid)["result"] == "started"
    assert rate_limit.analyses_used() == used + 1
    gated.release(vid)
    assert _wait(lambda: rate_limit.analyses_used() == used)


def test_cap_zero_disables(monkeypatch):
    monkeypatch.setattr(config, "DAILY_ANALYSIS_MINUTES_LIMIT", 0)
    ok, charge = rate_limit.try_consume_analysis_minutes(10_000)
    assert ok and charge.keys == []


# ─── /api/health/ready ──────────────────────────────────────────

@pytest.fixture()
def ready(monkeypatch):
    """Healthy defaults; OpenRouter never contacted for real."""
    calls = []

    def fake_balance():
        calls.append(1)
        return 12.5

    monkeypatch.setattr(health, "_fetch_balance", fake_balance)
    monkeypatch.setitem(health._balance_cache, "at", 0.0)
    monkeypatch.setattr(storage, "free_disk_bytes", lambda: 20 * storage.GB)
    monkeypatch.delenv("REDIS_URL", raising=False)
    return calls


def _ready():
    r = _client().get("/api/health/ready")
    return r.status_code, r.json()


def test_ready_ok_and_balance_cached(ready):
    code, body = _ready()
    assert code == 200 and body["status"] == "ready", body
    assert set(body["checks"]) == {"db", "redis", "disk", "ffmpeg", "openrouter"}
    assert body["checks"]["openrouter"] == {"ok": True, "balance": "ok"}
    assert "12.5" not in str(body)                       # public: no dollar figure
    _ready()
    assert len(ready) == 1                               # second call served from the 5-min cache


def test_ready_fails_without_ffmpeg(ready, monkeypatch):
    monkeypatch.setattr(health.shutil, "which", lambda name: None)
    code, body = _ready()
    assert code == 503 and body["status"] == "not_ready"
    assert body["checks"]["ffmpeg"] == {"ok": False, "missing": ["ffmpeg", "ffprobe"]}


def test_ready_fails_when_db_down(ready, monkeypatch):
    def down():
        raise ConnectionError("db gone")
    monkeypatch.setattr(health, "check_db", down)
    code, body = _ready()
    assert code == 503 and body["checks"]["db"] == {"ok": False, "error": "ConnectionError"}


def test_ready_fails_when_redis_unreachable(ready, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    code, body = _ready()
    assert code == 503 and body["checks"]["redis"]["ok"] is False


def test_ready_times_out_a_hung_check(ready, monkeypatch):
    monkeypatch.setattr(health, "CHECK_TIMEOUT", 0.2)
    monkeypatch.setattr(health, "check_db", lambda: time.sleep(1) or {"ok": True})
    code, body = _ready()
    assert code == 503 and body["checks"]["db"] == {"ok": False, "error": "timeout"}


def test_ready_disk(ready, monkeypatch):
    from autoclip.auth import settings as auth_settings
    monkeypatch.setattr(auth_settings, "MIN_FREE_DISK_GB", 5.0)
    monkeypatch.setattr(storage, "free_disk_bytes", lambda: 3 * storage.GB)
    code, body = _ready()                                # uploads paused, app still serves
    assert code == 200 and body["checks"]["disk"]["uploads_paused"] is True
    monkeypatch.setattr(storage, "free_disk_bytes", lambda: storage.GB // 2)
    code, body = _ready()
    assert code == 503 and body["checks"]["disk"]["ok"] is False


def test_ready_slow_openrouter_is_not_a_failure(ready, monkeypatch):
    monkeypatch.undo()                                   # use the real _fetch_balance …
    monkeypatch.setitem(health._balance_cache, "at", 0.0)
    monkeypatch.setattr(storage, "free_disk_bytes", lambda: 20 * storage.GB)
    monkeypatch.delenv("REDIS_URL", raising=False)

    def slow(*a, **k):                                   # … with a network that times out
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "get", slow)
    code, body = _ready()
    assert code == 200 and body["checks"]["openrouter"] == {"ok": True, "balance": "unknown"}

    monkeypatch.setitem(health._balance_cache, "at", 0.0)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(500, json={}))
    assert _ready()[0] == 200


def test_ready_fails_on_exhausted_or_missing_key(ready, monkeypatch):
    monkeypatch.setattr(health, "_fetch_balance", lambda: 0.0)
    code, body = _ready()
    assert code == 503 and body["checks"]["openrouter"] == {"ok": False, "balance": "exhausted"}
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    code, body = _ready()
    assert code == 503 and "not set" in body["checks"]["openrouter"]["error"]
