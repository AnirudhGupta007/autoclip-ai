"""Chat history: conversations are per user (404 across users, also inside
agent tools), the demo account is read-only, and chat turns are stored.

Reuses the app + temp DB set up by test_auth_isolation (same process). The
orchestrator is the FakeOrchestrator stub — no OpenRouter calls.
"""
from __future__ import annotations

import json

import pytest

from test_auth_isolation import (  # noqa: F401
    SessionLocal, _client, _make_video, _signup, agent_tools, chat_router, fake_orchestrator,
)

from autoclip.models import Conversation, Message
from autoclip.services import conversations as C
from autoclip.utils.text import truncate_words


@pytest.fixture()
def pair():
    a, a_me = _signup()
    b, b_me = _signup()
    a_vid, a_cid = _make_video(a_me["id"])
    r = a.post("/api/conversations", json={"video_id": a_vid})
    assert r.status_code == 201, r.text
    return dict(a=a, b=b, a_me=a_me, b_me=b_me, a_vid=a_vid, a_cid=a_cid, conv=r.json())


def test_create_and_list(pair):
    a, conv = pair["a"], pair["conv"]
    assert set(conv) == {"id", "title", "video_id", "updated_at"}
    assert conv["video_id"] == pair["a_vid"] and conv["title"] == ""
    assert conv["updated_at"].endswith("Z")
    # POST without a body works too (the UI creates one before the first message)
    r = a.post("/api/conversations")
    assert r.status_code == 201 and r.json()["video_id"] is None
    ids = [c["id"] for c in a.get("/api/conversations").json()]
    assert ids[0] == r.json()["id"] and conv["id"] in ids   # newest updated_at first
    assert a.get(f"/api/conversations/{conv['id']}/messages").json() == []


def test_cannot_attach_someone_elses_video(pair):
    r = pair["b"].post("/api/conversations", json={"video_id": pair["a_vid"]})
    assert r.status_code == 404


def test_isolation_between_users(pair):
    b, cid = pair["b"], pair["conv"]["id"]
    assert cid not in {c["id"] for c in b.get("/api/conversations").json()}
    assert b.get(f"/api/conversations/{cid}/messages").status_code == 404
    assert b.patch(f"/api/conversations/{cid}", json={"title": "pwned"}).status_code == 404
    assert b.delete(f"/api/conversations/{cid}").status_code == 404
    r = b.post("/api/chat/message", json={"message": "hi", "conversation_id": cid})
    assert r.status_code == 404
    # untouched for the owner
    a = pair["a"]
    conv = next(c for c in a.get("/api/conversations").json() if c["id"] == cid)
    assert conv["title"] == ""
    assert a.get(f"/api/conversations/{cid}/messages").json() == []


def test_rename_and_delete(pair):
    a, cid = pair["a"], pair["conv"]["id"]
    r = a.patch(f"/api/conversations/{cid}", json={"title": "  My   podcast clips "})
    assert r.status_code == 200 and r.json()["title"] == "My podcast clips"
    assert a.patch(f"/api/conversations/{cid}", json={"title": "   "}).status_code == 422
    a.post("/api/chat/message", json={"message": "hi", "conversation_id": cid})
    assert a.delete(f"/api/conversations/{cid}").status_code == 204
    assert a.get(f"/api/conversations/{cid}/messages").status_code == 404
    db = SessionLocal()
    try:
        assert db.query(Message).filter(Message.conversation_id == cid).count() == 0
    finally:
        db.close()


def test_messages_are_persisted_with_title_and_thread(pair):
    a, cid, vid = pair["a"], pair["conv"]["id"], pair["a_vid"]
    prompt = "Give me three funny thirty second clips about libertarians and lower taxes please"
    r = a.post("/api/chat/message", json={"message": prompt, "video_id": vid, "conversation_id": cid})
    assert r.status_code == 200, r.text
    cfg = fake_orchestrator.configs[-1]["configurable"]
    assert cfg["thread_id"] == f"u:{pair['a_me']['id']}:c:{cid}"
    assert cfg["conversation_id"] == cid

    msgs = a.get(f"/api/conversations/{cid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == prompt and msgs[1]["content"] == r.json()["response"]
    assert set(msgs[0]) == {"id", "role", "content", "clips", "created_at"}

    conv = next(c for c in a.get("/api/conversations").json() if c["id"] == cid)
    assert conv["title"] == truncate_words(prompt, C.TITLE_MAX)
    assert len(conv["title"]) <= C.TITLE_MAX and not conv["title"].rstrip("…").endswith(" ")
    assert prompt.startswith(conv["title"].rstrip("…"))      # cut at a word boundary
    assert conv["updated_at"] >= pair["conv"]["updated_at"]

    # the second prompt doesn't change the title
    a.post("/api/chat/message", json={"message": "and one more", "video_id": vid, "conversation_id": cid})
    msgs = a.get(f"/api/conversations/{cid}/messages").json()
    assert len(msgs) == 4
    assert next(c for c in a.get("/api/conversations").json() if c["id"] == cid)["title"] == conv["title"]


def test_clips_are_stored_and_rehydrated(pair):
    """An assistant reply's clips come back in the chat-API clip shape."""
    a, cid, vid, clip_id = pair["a"], pair["conv"]["id"], pair["a_vid"], pair["a_cid"]
    C.record_turn(pair["a_me"]["id"], cid, "make a clip", "Here you go",
                  clips=[agent_tools.clips_by_ids([clip_id])[0]], video_id=vid)
    msgs = a.get(f"/api/conversations/{cid}/messages").json()
    clip = msgs[-1]["clips"][0]
    assert clip["id"] == clip_id and clip["file_url"].startswith("/api/files/outputs/")
    for k in ("title", "thumbnail_url", "duration", "frame", "start_time", "end_time",
              "overall_score", "scores", "style_tags", "transcript"):
        assert k in clip
    # a clip deleted later keeps its record but loses the media URLs
    from autoclip.models import Clip
    db = SessionLocal()
    try:
        db.query(Clip).filter(Clip.id == clip_id).delete()
        db.commit()
    finally:
        db.close()
    clip = a.get(f"/api/conversations/{cid}/messages").json()[-1]["clips"][0]
    assert clip["id"] == clip_id and clip["file_url"] is None and clip["thumbnail_url"] is None


def test_pending_resend_is_not_stored_twice(pair):
    uid, cid = pair["a_me"]["id"], pair["conv"]["id"]
    C.record_turn(uid, cid, "3 funny clips", "Analysing…", pending=True)
    C.record_turn(uid, cid, "3 funny clips", "Here are your clips")
    msgs = pair["a"].get(f"/api/conversations/{cid}/messages").json()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "3 funny clips"), ("assistant", "Analysing…"), ("assistant", "Here are your clips")]


def test_unanalysed_video_turn_is_stored_as_pending(pair, monkeypatch):
    from autoclip.utils import analysis_jobs
    a, me = pair["a"], pair["a_me"]
    vid, _ = _make_video(me["id"], analyzed=False)
    monkeypatch.setattr(analysis_jobs, "_run_pipeline", lambda video_id: None)
    cid = a.post("/api/conversations", json={"video_id": vid}).json()["id"]
    r = a.post("/api/chat/message", json={"message": "clips please", "video_id": vid, "conversation_id": cid})
    assert r.status_code == 200 and r.json()["pending_request"] is True
    db = SessionLocal()
    try:
        rows = db.query(Message).filter(Message.conversation_id == cid).order_by(Message.id).all()
        assert [(m.role, m.pending) for m in rows] == [("user", False), ("assistant", True)]
    finally:
        db.close()


def test_agent_tools_refuse_a_foreign_conversation_thread(pair):
    """Tools re-check the thread in the run config, not just the user id."""
    a_id, b_id = pair["a_me"]["id"], pair["b_me"]["id"]
    vid, cid = pair["a_vid"], pair["conv"]["id"]
    ok = {"configurable": {"user_id": a_id, "thread_id": f"u:{a_id}:c:{cid}", "conversation_id": cid}}
    assert agent_tools.get_video_status.invoke({"video_id": vid}, config=ok)["exists"] is True
    forged = [
        {"configurable": {"user_id": a_id, "thread_id": f"u:{b_id}:c:{cid}"}},       # someone else's thread
        {"configurable": {"user_id": a_id, "thread_id": f"u:{a_id}:c:nope"}},        # unknown conversation
        {"configurable": {"user_id": a_id, "thread_id": f"u:{a_id}:c:{cid}", "conversation_id": "x"}},
    ]
    for cfg in forged:
        assert agent_tools.get_video_status.invoke({"video_id": vid}, config=cfg) == {"exists": False}
    # B's own conversation thread can't reach A's video either
    b_conv = pair["b"].post("/api/conversations").json()["id"]
    b_cfg = {"configurable": {"user_id": b_id, "thread_id": f"u:{b_id}:c:{b_conv}"}}
    assert agent_tools.get_video_status.invoke({"video_id": vid}, config=b_cfg) == {"exists": False}


def test_chat_through_foreign_conversation_runs_no_agent(pair):
    n = len(fake_orchestrator.configs)
    payload = json.dumps({"video_id": pair["a_vid"]})
    r = pair["b"].post("/api/chat/message", json={"message": f"TOOL get_video_status {payload}",
                                                  "conversation_id": pair["conv"]["id"]})
    assert r.status_code == 404
    assert len(fake_orchestrator.configs) == n


def test_demo_is_read_only_for_history():
    from test_auth_isolation import User, auth_settings, UNUSABLE_PASSWORD  # noqa: F401
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == auth_settings.DEMO_EMAIL).first() is None:
            db.add(User(email=auth_settings.DEMO_EMAIL, password_hash=UNUSABLE_PASSWORD, is_demo=True))
            db.commit()
    finally:
        db.close()
    c = _client()
    assert c.post("/api/auth/demo").status_code == 200
    assert c.get("/api/conversations").json() == []
    assert c.post("/api/conversations").status_code == 403
    # even an id that exists (someone else's) is 403 for rename/delete
    owner, _ = _signup()
    cid = owner.post("/api/conversations").json()["id"]
    assert c.patch(f"/api/conversations/{cid}", json={"title": "x"}).status_code == 403
    assert c.delete(f"/api/conversations/{cid}").status_code == 403
    assert c.get(f"/api/conversations/{cid}/messages").status_code == 404
    db = SessionLocal()
    try:
        assert db.get(Conversation, cid) is not None
    finally:
        db.close()


def test_deleting_a_video_keeps_its_conversations(pair):
    a, cid, vid = pair["a"], pair["conv"]["id"], pair["a_vid"]
    a.post("/api/chat/message", json={"message": "hi", "video_id": vid, "conversation_id": cid})
    assert a.delete(f"/api/videos/{vid}").status_code == 200
    conv = next(c for c in a.get("/api/conversations").json() if c["id"] == cid)
    assert conv["video_id"] is None
    assert len(a.get(f"/api/conversations/{cid}/messages").json()) == 2


def test_truncate_words():
    assert truncate_words("short title", 60) == "short title"
    t = truncate_words("Libertarians Would Vote for Mussolini for Lower Taxes Every Time", 50)
    assert t == "Libertarians Would Vote for Mussolini for Lower…"
    assert len(t) <= 50
    assert truncate_words("a" * 80, 10) == "a" * 9 + "…"
    assert truncate_words("  spaced \n out  ", 60) == "spaced out"
    assert truncate_words("Hello, world, again", 14) == "Hello, world…"
