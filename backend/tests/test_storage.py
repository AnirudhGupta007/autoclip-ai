"""Storage rules: upload quota + disk guard, the retention cleanup (with an
injected clock), /api/me/usage, DELETE /api/me, and the archived state.

Reuses the app + temp DB set up by test_auth_isolation (same process).
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from test_auth_isolation import (  # noqa: F401
    PASSWORD, UNUSABLE_PASSWORD, SessionLocal, User, Video, _client, _make_video, _signup,
    _upload, agent_tools, auth_settings, videos_router,
)

from autoclip.config import OUTPUT_DIR, UPLOAD_DIR
from autoclip.models import AuthSession, Clip, Conversation, Message, MomentRecord, utcnow
from autoclip.services import storage

DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
def _fake_probe(monkeypatch):
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": 30.0, "resolution": "640x360"})
    monkeypatch.setattr(auth_settings, "MAX_VIDEOS_PER_USER", 50)


def _set(model, pk, **fields):
    db = SessionLocal()
    try:
        row = db.get(model, pk)
        for k, v in fields.items():
            setattr(row, k, v)
        db.commit()
    finally:
        db.close()


def _get(model, pk):
    db = SessionLocal()
    try:
        return db.get(model, pk)
    finally:
        db.close()


def _demo_id() -> int:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == auth_settings.DEMO_EMAIL).first()
        if u is None:
            u = User(email=auth_settings.DEMO_EMAIL, password_hash=UNUSABLE_PASSWORD, is_demo=True)
            db.add(u)
            db.commit()
        return u.id
    finally:
        db.close()


# ─── upload guards ──────────────────────────────────────────────

def test_quota_rejects_upload_over_the_limit(monkeypatch):
    c, me = _signup()
    payload = len(b"not-really-a-video")
    monkeypatch.setattr(auth_settings, "STORAGE_QUOTA_BYTES", payload + 5)
    assert _upload(c).status_code == 200
    r = _upload(c)
    assert r.status_code == 413 and "quota" in r.json()["detail"]
    assert len(c.get("/api/videos").json()) == 1          # nothing half-stored
    dirs = [p for p in Path(UPLOAD_DIR).iterdir() if p.is_dir()]
    db = SessionLocal()
    try:
        known = {v.id for v in db.query(Video).all()}
    finally:
        db.close()
    assert all(d.name in known for d in dirs)


def test_quota_does_not_apply_to_admins(monkeypatch):
    monkeypatch.setattr(auth_settings, "STORAGE_QUOTA_BYTES", 1)
    admin = _client()
    if admin.post("/api/auth/login", json={"email": "boss@example.com", "password": PASSWORD}).status_code != 200:
        admin, _ = _signup("boss@example.com")
    assert _upload(admin).status_code == 200


def test_disk_guard_refuses_everyone(monkeypatch):
    monkeypatch.setattr(auth_settings, "MIN_FREE_DISK_GB", 5.0)
    monkeypatch.setattr(storage, "free_disk_bytes", lambda: 4 * storage.GB)
    c, _ = _signup()
    r = _upload(c)
    assert r.status_code == 507 and "disk" in r.json()["detail"]
    assert c.get("/api/videos").json() == []
    monkeypatch.setattr(storage, "free_disk_bytes", lambda: 6 * storage.GB)
    assert _upload(c).status_code == 200


def test_archived_uploads_free_a_slot(monkeypatch):
    monkeypatch.setattr(auth_settings, "MAX_VIDEOS_PER_USER", 1)
    c, _ = _signup()
    vid = _upload(c).json()["id"]
    r = _upload(c)
    assert r.status_code == 409 and "active uploads" in r.json()["detail"]
    _set(Video, vid, archived=True)
    assert _upload(c).status_code == 200


# ─── expiry fields ──────────────────────────────────────────────

def test_usage_and_video_fields():
    c, me = _signup()
    vid, cid = _make_video(me["id"])
    u = c.get("/api/me/usage").json()
    assert u["queries_limit"] == 2 and u["queries_used"] == 0
    assert u["storage_quota_bytes"] == auth_settings.STORAGE_QUOTA_BYTES
    item = u["items"][0]
    assert set(item) == {"video_id", "title", "media_kind", "size_bytes", "source_expires_at",
                         "clips_expire_at", "archived"}
    assert item["video_id"] == vid and item["media_kind"] == "video" and item["archived"] is False
    assert item["size_bytes"] == len(b"fake-video") + len(b"fake-clip") + len(b"fake-thumb")
    assert u["storage_bytes"] == item["size_bytes"]
    assert item["source_expires_at"].endswith("Z") and item["clips_expire_at"].endswith("Z")
    v = _get(Video, vid)
    assert item["source_expires_at"].startswith((v.created_at.replace(tzinfo=None) + 7 * DAY).strftime("%Y-%m-%dT%H:%M"))
    c.post("/api/chat/message", json={"message": "hi"})
    assert c.get("/api/me/usage").json()["queries_used"] == 1
    # same optional fields on /api/videos; google_linked on /auth/me
    lv = c.get("/api/videos").json()[0]
    assert lv["source_expires_at"] == item["source_expires_at"] and lv["clips_expire_at"] == item["clips_expire_at"]
    assert lv["archived"] is False and lv["media_kind"] == "video"
    assert c.get("/api/auth/me").json()["google_linked"] is False
    # archived: no source expiry, no source URL
    _set(Video, vid, archived=True)
    lv = c.get("/api/videos").json()[0]
    assert lv["archived"] is True and lv["source_expires_at"] is None and lv["source_url"] is None


def test_admin_usage_is_unlimited():
    admin = _client()
    if admin.post("/api/auth/login", json={"email": "boss@example.com", "password": PASSWORD}).status_code != 200:
        admin, _ = _signup("boss@example.com")
    u = admin.get("/api/me/usage").json()
    assert u["queries_limit"] is None and u["storage_quota_bytes"] is None


# ─── the cleanup job ────────────────────────────────────────────

def test_cleanup_archives_sources_and_expires_clips():
    c, me = _signup()
    vid, old_cid = _make_video(me["id"])
    _, demo_cid = _make_video(_demo_id())
    demo_vid = _get(Clip, demo_cid).video_id
    # a second, newer clip on the same video
    new_cid = "n" + old_cid[1:]
    new_dir = Path(OUTPUT_DIR) / vid / "clips" / new_cid
    new_dir.mkdir(parents=True)
    (new_dir / "clip.mp4").write_bytes(b"new")
    db = SessionLocal()
    try:
        db.add(Clip(id=new_cid, video_id=vid, title="New", start_time=1, end_time=5, duration=4,
                    file_path=str(new_dir / "clip.mp4"), created_at=utcnow() + 20 * DAY))
        db.commit()
    finally:
        db.close()

    now = utcnow()
    storage.run_cleanup(now + 6 * DAY)                            # day 6: nothing of ours yet
    assert _get(Video, vid).archived is False and (Path(UPLOAD_DIR) / vid / "source.mp4").exists()

    out = storage.run_cleanup(now + 8 * DAY)                      # day 8: source goes
    assert out["sources_archived"] >= 1
    assert _get(Video, vid).archived is True
    assert not (Path(UPLOAD_DIR) / vid).exists()
    assert _get(Clip, old_cid) is not None and (Path(OUTPUT_DIR) / vid / "clips" / old_cid).exists()
    assert c.get(f"/api/clips/{old_cid}").status_code == 200     # old clips still play

    storage.run_cleanup(now + 31 * DAY)                           # day 31: first clip goes
    assert _get(Clip, old_cid) is None
    assert not (Path(OUTPUT_DIR) / vid / "clips" / old_cid).exists()
    assert _get(Clip, new_cid) is not None and new_dir.exists()  # made on day 20
    db = SessionLocal()
    try:   # transcript-derived moments stay with the archived video
        assert db.query(MomentRecord).filter(MomentRecord.video_id == vid).count() == 1
    finally:
        db.close()

    # the demo account is exempt from every rule
    assert _get(Video, demo_vid).archived is False and _get(Clip, demo_cid) is not None
    assert (Path(UPLOAD_DIR) / demo_vid / "source.mp4").exists()


def test_cleanup_purges_inactive_accounts():
    c, me = _signup()
    vid, cid = _make_video(me["id"])
    conv = c.post("/api/conversations", json={"video_id": vid}).json()["id"]
    active, active_me = _signup()
    a_vid, _ = _make_video(active_me["id"])
    now = utcnow()
    _set(User, me["id"], last_active_at=now - 61 * DAY)
    _set(User, active_me["id"], last_active_at=now - 59 * DAY)
    _set(Video, vid, created_at=now)          # keep the per-item rules out of it
    _set(Video, a_vid, created_at=now)

    out = storage.run_cleanup(now)
    assert out["inactive_accounts"] >= 1
    assert not (Path(UPLOAD_DIR) / vid).exists() and not (Path(OUTPUT_DIR) / vid).exists()
    assert _get(Video, vid).archived is True and _get(Clip, cid) is None
    assert _get(User, me["id"]) is not None and _get(Conversation, conv) is not None   # account kept
    assert (Path(UPLOAD_DIR) / a_vid / "source.mp4").exists()                         # 59 days: untouched
    # a second run finds nothing left to delete for that account
    assert storage.run_cleanup(now)["inactive_accounts"] == 0


def test_requests_refresh_last_active():
    c, me = _signup()
    _set(User, me["id"], last_active_at=utcnow() - 90 * DAY)
    assert c.get("/api/auth/me").status_code == 200
    assert utcnow() - _get(User, me["id"]).last_active_at < timedelta(minutes=1)


def test_cleanup_tick_runs_once_a_day(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "run_cleanup", lambda now=None: calls.append(1) or {})
    monkeypatch.setattr(auth_settings, "CLEANUP_HOUR_UTC", 3)
    day = utcnow().replace(year=2031, month=1, day=1)
    assert asyncio.run(storage.cleanup_tick(day.replace(hour=2))) is None      # before 03:00
    assert asyncio.run(storage.cleanup_tick(day.replace(hour=3))) == {}
    assert asyncio.run(storage.cleanup_tick(day.replace(hour=9))) is None      # already ran today
    assert asyncio.run(storage.cleanup_tick((day + DAY).replace(hour=4))) == {}
    assert len(calls) == 2


def test_cleanup_failure_releases_the_day(monkeypatch):
    def boom(now=None):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(storage, "run_cleanup", boom)
    day = utcnow().replace(year=2032, month=1, day=1, hour=12)
    assert asyncio.run(storage.cleanup_tick(day)) is None
    monkeypatch.setattr(storage, "run_cleanup", lambda now=None: {"ok": 1})
    assert asyncio.run(storage.cleanup_tick(day)) == {"ok": 1}


# ─── archived videos ────────────────────────────────────────────

def test_archived_video_refuses_new_clips(monkeypatch):
    c, me = _signup()
    vid, cid = _make_video(me["id"])
    _set(Video, vid, archived=True)
    cfg = {"configurable": {"user_id": me["id"]}}
    res = agent_tools.select_and_produce_clips.invoke({"video_id": vid}, config=cfg)
    assert res["status"] == "archived" and "re-upload" in res["message"]
    res = agent_tools.modify_clip.invoke({"clip_id": cid, "new_caption_style": "glow"}, config=cfg)
    assert "re-upload" in res["error"]
    r = c.put(f"/api/clips/{cid}", json={"start_time": 2, "end_time": 9})
    assert r.status_code == 422 and "re-upload" in r.json()["detail"]
    assert c.put(f"/api/clips/{cid}", json={"title": "renamed"}).status_code == 200   # no re-render needed
    # not analysed + archived: no analysis, no charge
    vid2, _ = _make_video(me["id"], analyzed=False)
    _set(Video, vid2, archived=True)
    r = c.post("/api/chat/message", json={"message": "clips", "video_id": vid2})
    assert r.status_code == 200 and "re-upload" in r.json()["response"]
    assert r.json()["queries_remaining"] == 2
    assert agent_tools.ingest_and_analyze_video.invoke({"video_id": vid2}, config=cfg)["status"] == "archived"


# ─── DELETE /api/me ─────────────────────────────────────────────

def test_delete_me_removes_everything():
    c, me = _signup()
    vid, cid = _make_video(me["id"])
    conv = c.post("/api/conversations", json={"video_id": vid}).json()["id"]
    c.post("/api/chat/message", json={"message": "hi", "video_id": vid, "conversation_id": conv})
    other, other_me = _signup()
    o_vid, _ = _make_video(other_me["id"])

    r = c.delete("/api/me")
    assert r.status_code == 204
    assert "max-age=0" in r.headers.get("set-cookie", "").lower() or 'expires=' in r.headers.get("set-cookie", "").lower()
    assert c.get("/api/auth/me").status_code == 401
    db = SessionLocal()
    try:
        assert db.get(User, me["id"]) is None
        assert db.query(Video).filter(Video.user_id == me["id"]).count() == 0
        assert db.get(Clip, cid) is None
        assert db.query(MomentRecord).filter(MomentRecord.video_id == vid).count() == 0
        assert db.get(Conversation, conv) is None
        assert db.query(Message).filter(Message.conversation_id == conv).count() == 0
        assert db.query(AuthSession).filter(AuthSession.user_id == me["id"]).count() == 0
    finally:
        db.close()
    assert not (Path(UPLOAD_DIR) / vid).exists() and not (Path(OUTPUT_DIR) / vid).exists()
    # someone else's data is untouched; the email can sign up again
    assert other.get(f"/api/videos/{o_vid}").status_code == 200
    assert _client().post("/api/auth/signup", json={"email": me["email"], "password": PASSWORD}).status_code == 201


def test_delete_me_is_403_for_demo():
    _demo_id()
    c = _client()
    assert c.post("/api/auth/demo").status_code == 200
    assert c.delete("/api/me").status_code == 403
    assert c.get("/api/auth/me").status_code == 200
