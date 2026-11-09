"""Auth + per-user data isolation.

Runs the real FastAPI app on a temp SQLite DB (migrated with Alembic), with
the LLM orchestrator and the embedding call stubbed out — no network, no
OpenRouter spend.

    cd backend && uv run --with pytest --with argon2-cffi --with alembic pytest tests/test_auth_isolation.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="autoclip-authtest-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "UPLOAD_DIR": str(_TMP / "uploads"),
    "OUTPUT_DIR": str(_TMP / "outputs"),
    "OPENROUTER_API_KEY": "test-key-not-used",
    "EMBEDDING_DIM": "8",
    "REDIS_URL": "",
    "LANGGRAPH_PG_URL": "",
    "LANGSMITH_TRACING": "false",
    "DAILY_QUERY_LIMIT": "2",
    "DAILY_GLOBAL_QUERY_LIMIT": "0",
    "IP_DAILY_QUERY_LIMIT": "1000",
    "DEMO_DAILY_QUERY_LIMIT": "3",
    "SIGNUP_LIMIT_PER_IP_PER_DAY": "1000",
    "LOGIN_LIMIT_PER_15_MIN": "1000",
    "ADMIN_EMAILS": "boss@example.com",
    "COOKIE_SECURE": "0",
    "ALLOWED_ORIGINS": "http://localhost:5173",
    "MAX_VIDEOS_PER_USER": "2",
    "MAX_VIDEO_MINUTES_DEMO": "60",
    "MIN_FREE_DISK_GB": "0",        # tests/test_storage.py turns the disk guard on itself
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from autoclip.database import SessionLocal, init_db  # noqa: E402

init_db()  # runs the Alembic migrations (0001 + 0002) on the temp DB

from autoclip import main as app_main  # noqa: E402
from autoclip.agent import tools as agent_tools  # noqa: E402
from autoclip.auth import settings as auth_settings  # noqa: E402
from autoclip.auth.security import UNUSABLE_PASSWORD  # noqa: E402
from autoclip.config import OUTPUT_DIR, UPLOAD_DIR  # noqa: E402
from autoclip.models import Clip, MomentRecord, User, Video  # noqa: E402
from autoclip.pipeline.state import Moment  # noqa: E402
from autoclip.rag import embedding as rag_embedding  # noqa: E402
from autoclip.routers import chat as chat_router  # noqa: E402
from autoclip.routers import videos as videos_router  # noqa: E402
from autoclip.services.moment_store import persist_moments  # noqa: E402

PASSWORD = "correct horse battery"
app = app_main.app

# ─── stubs ──────────────────────────────────────────────────────

rag_embedding.embed_text = lambda text: [1.0] + [0.0] * 7  # no OpenRouter


class FakeOrchestrator:
    """Stands in for the deep agent. A message "TOOL <name> <json-args>" calls
    that tool with the run's config (as LangGraph's ToolNode would); anything
    else just echoes. Records the configs it saw."""

    def __init__(self):
        self.configs = []

    def invoke(self, inp, config):
        self.configs.append(config)
        text = inp["messages"][-1].content.split("\n", 1)[-1]
        reply = "ok"
        if text.startswith("TOOL "):
            _, name, args = text.split(" ", 2)
            tool = {t.name: t for t in agent_tools.ALL_TOOLS}[name]
            reply = json.dumps(tool.invoke(json.loads(args), config=config), default=str)
        return {"messages": [inp["messages"][-1], AIMessage(content=reply)]}


fake_orchestrator = FakeOrchestrator()
chat_router.orchestrator = fake_orchestrator


# ─── helpers ────────────────────────────────────────────────────

def _client() -> TestClient:
    return TestClient(app)


def _signup(email: str | None = None) -> tuple[TestClient, dict]:
    c = _client()
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = c.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return c, r.json()


def _make_video(user_id: int, analyzed: bool = True) -> tuple[str, str]:
    """A video + one clip + moments + files on disk, owned by user_id."""
    vid = uuid.uuid4().hex[:12]
    cid = uuid.uuid4().hex[:12]
    src = Path(UPLOAD_DIR) / vid / "source.mp4"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"fake-video")
    cdir = Path(OUTPUT_DIR) / vid / "clips" / cid
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "clip.mp4").write_bytes(b"fake-clip")
    (cdir / "thumb.jpg").write_bytes(b"fake-thumb")
    db = SessionLocal()
    try:
        db.add(Video(id=vid, filename="a.mp4", file_path=str(src), duration=60.0,
                     status="analyzed" if analyzed else "uploaded", user_id=user_id))
        db.add(Clip(id=cid, video_id=vid, title="Clip", start_time=1, end_time=11, duration=10,
                    file_path=str(cdir / "clip.mp4"), thumbnail_path=str(cdir / "thumb.jpg"),
                    overall_score=7.0))
        db.commit()
        if analyzed:
            persist_moments(db, vid, [Moment(
                start=1, end=11, visual_energy=0.5, audio_energy=0.5, text_hook_strength=0.5,
                convergence_score=0.8, modalities_active=3, style_tags=["funny"],
                description=f"moment of {vid}", transcript="hello", embedding=[1.0] + [0.0] * 7)])
    finally:
        db.close()
    return vid, cid


@pytest.fixture(scope="module")
def two_users():
    a, a_me = _signup()
    b, b_me = _signup()
    a_vid, a_cid = _make_video(a_me["id"])
    b_vid, b_cid = _make_video(b_me["id"])
    return dict(a=a, b=b, a_me=a_me, b_me=b_me, a_vid=a_vid, a_cid=a_cid, b_vid=b_vid, b_cid=b_cid)


# ─── unauthenticated sweep ──────────────────────────────────────

PUBLIC = {"/api/health"}


def _api_routes(routes) -> list[APIRoute]:
    """All APIRoutes, flattening FastAPI >= 0.14x's lazily-included routers."""
    out = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        elif hasattr(r, "original_router"):   # fastapi.routing._IncludedRouter
            out.extend(_api_routes(r.original_router.routes))
    return out


def test_every_api_route_requires_login():
    c = _client()
    checked = 0
    for route in _api_routes(app.routes):
        if not route.path.startswith("/api"):
            continue
        if route.path in PUBLIC or route.path.startswith("/api/auth/"):
            continue
        path = route.path
        for p in route.param_convertors:
            path = path.replace("{" + p + "}", "x").replace("{" + p + ":path}", "x/y")
        for method in route.methods - {"HEAD", "OPTIONS"}:
            r = c.request(method, path, json={})
            assert r.status_code == 401, (method, route.path, r.status_code, r.text)
            checked += 1
    assert checked >= 15
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_old_public_mounts_are_gone(two_users):
    c = _client()
    vid = two_users["a_vid"]
    for url in (f"/uploads/{vid}/source.mp4", f"/outputs/{vid}/clips/{two_users['a_cid']}/clip.mp4"):
        r = c.get(url)
        assert r.status_code == 404
        assert r.content != b"fake-video"


# ─── signup / login / logout ────────────────────────────────────

def test_signup_validation_and_duplicates():
    c = _client()
    assert c.post("/api/auth/signup", json={"email": "x@example.com", "password": "short"}).status_code == 422
    assert c.post("/api/auth/signup", json={"email": "not-an-email", "password": PASSWORD}).status_code == 422
    email = f"Dup-{uuid.uuid4().hex[:6]}@Example.com"
    assert c.post("/api/auth/signup", json={"email": email, "password": PASSWORD}).status_code == 201
    r = _client().post("/api/auth/signup", json={"email": email.lower(), "password": PASSWORD})
    assert r.status_code == 409
    r = _client().post("/api/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert r.status_code == 200 and r.json()["email"] == email.lower()


def test_login_errors_are_generic():
    _, me = _signup()
    c = _client()
    wrong = c.post("/api/auth/login", json={"email": me["email"], "password": "wrong password!"})
    unknown = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_session_cookie_attributes():
    c = _client()
    r = c.post("/api/auth/signup", json={"email": f"ck-{uuid.uuid4().hex[:6]}@example.com",
                                         "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert auth_settings.COOKIE_NAME in r.headers["set-cookie"]


def test_session_token_stored_hashed():
    c, me = _signup()
    token = c.cookies.get(auth_settings.COOKIE_NAME)
    from autoclip.models import AuthSession
    db = SessionLocal()
    try:
        rows = db.query(AuthSession).filter(AuthSession.user_id == me["id"]).all()
    finally:
        db.close()
    assert rows and all(r.token_hash != token and len(r.token_hash) == 64 for r in rows)


def test_logout_invalidates_session():
    c, _ = _signup()
    token = c.cookies.get(auth_settings.COOKIE_NAME)
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    replay = _client()
    replay.cookies.set(auth_settings.COOKIE_NAME, token)
    assert replay.get("/api/auth/me").status_code == 401
    assert replay.get("/api/videos").status_code == 401


def test_login_rate_limit(monkeypatch):
    monkeypatch.setattr(auth_settings, "LOGIN_LIMIT_PER_15_MIN", 3)
    c = _client()
    email = f"rl-{uuid.uuid4().hex[:6]}@example.com"
    codes = [c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code
             for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_signup_rate_limit(monkeypatch):
    monkeypatch.setattr(auth_settings, "SIGNUP_LIMIT_PER_IP_PER_DAY", 0)  # 0 = disabled
    _signup()
    from autoclip.services import rate_limit
    monkeypatch.setattr(rate_limit, "hit", lambda *a, **k: False)
    r = _client().post("/api/auth/signup", json={"email": "z@example.com", "password": PASSWORD})
    assert r.status_code == 429


def test_admin_email_gets_admin_and_unlimited_quota():
    c, me = _signup("boss@example.com")
    assert me["is_admin"] is True
    q = c.get("/api/chat/quota").json()
    assert q["limit"] is None and q["remaining"] is None
    for _ in range(4):
        assert c.post("/api/chat/message", json={"message": "hi"}).status_code == 200


def test_origin_check_blocks_cross_site_writes():
    c, _ = _signup()
    r = c.post("/api/chat/message", json={"message": "hi"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert c.get("/api/auth/me").status_code == 200   # session survived
    r = c.post("/api/chat/message", json={"message": "hi"}, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    r = c.post("/api/chat/message", json={"message": "hi"}, headers={"Origin": "http://testserver"})
    assert r.status_code in (200, 429)  # same-origin passes the check


def test_cors_never_wildcard_with_credentials():
    r = _client().options("/api/videos", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") in (None, "")
    r = _client().options("/api/videos", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ─── isolation: B must not see A's data ─────────────────────────

def test_lists_are_scoped(two_users):
    a, b = two_users["a"], two_users["b"]
    a_ids = {v["id"] for v in a.get("/api/videos").json()}
    b_ids = {v["id"] for v in b.get("/api/videos").json()}
    assert two_users["a_vid"] in a_ids and two_users["a_vid"] not in b_ids
    assert two_users["b_vid"] in b_ids and two_users["b_vid"] not in a_ids
    b_clips = {c["id"] for c in b.get("/api/clips").json()}
    assert two_users["a_cid"] not in b_clips and two_users["b_cid"] in b_clips


def test_cross_user_access_is_404(two_users):
    b = two_users["b"]
    vid, cid = two_users["a_vid"], two_users["a_cid"]
    checks = [
        ("GET", f"/api/videos/{vid}", None),
        ("DELETE", f"/api/videos/{vid}", None),
        ("GET", f"/api/clips?video_id={vid}", None),
        ("GET", f"/api/clips/{cid}", None),
        ("PUT", f"/api/clips/{cid}", {"title": "pwned"}),
        ("POST", f"/api/clips/{cid}/export", {"format": "9:16"}),
        ("GET", f"/api/clips/{cid}/download/original", None),
        ("GET", f"/api/files/uploads/{vid}/source.mp4", None),
        ("GET", f"/api/files/outputs/{vid}/clips/{cid}/clip.mp4", None),
        ("GET", f"/api/chat/stream/{vid}", None),
        ("GET", f"/api/chat/analysis/{vid}", None),
        ("POST", "/api/chat/message", {"message": "make clips", "video_id": vid}),
        ("POST", "/api/search", {"query": "funny", "video_id": vid}),
    ]
    for method, url, body in checks:
        r = b.request(method, url, json=body)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
    # A's data is untouched and still reachable by A
    a = two_users["a"]
    assert a.get(f"/api/videos/{vid}").status_code == 200
    assert a.get(f"/api/clips/{cid}").json()["title"] == "Clip"


def test_owner_can_fetch_files_via_authorised_urls(two_users):
    a = two_users["a"]
    clip = a.get(f"/api/clips/{two_users['a_cid']}").json()
    assert clip["file_url"].startswith(f"/api/files/outputs/{two_users['a_vid']}/")
    assert clip["thumbnail_url"].startswith("/api/files/outputs/")
    assert a.get(clip["file_url"]).content == b"fake-clip"
    assert a.get(clip["thumbnail_url"]).content == b"fake-thumb"
    video = a.get(f"/api/videos/{two_users['a_vid']}").json()
    assert video["source_url"] == f"/api/files/uploads/{two_users['a_vid']}/source.mp4"
    r = a.get(video["source_url"])
    assert r.status_code == 200 and r.content == b"fake-video"
    assert "private" in r.headers["cache-control"]
    r = a.get(f"/api/clips/{two_users['a_cid']}/download/original")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]


def test_file_route_rejects_traversal_and_bad_kinds(two_users):
    a = two_users["a"]
    vid, b_vid = two_users["a_vid"], two_users["b_vid"]
    for url in (f"/api/files/uploads/{vid}/..%2F{b_vid}%2Fsource.mp4",
                f"/api/files/uploads/{vid}/%2E%2E/{b_vid}/source.mp4",
                f"/api/files/etc/{vid}/source.mp4",
                f"/api/files/uploads/{vid}"):
        r = a.get(url)
        assert r.status_code == 404, (url, r.status_code)


def test_x_accel_redirect_mode(two_users, monkeypatch):
    monkeypatch.setattr(auth_settings, "FILES_ACCEL_REDIRECT", True)
    a = two_users["a"]
    r = a.get(f"/api/files/uploads/{two_users['a_vid']}/source.mp4")
    assert r.status_code == 200
    assert r.headers["x-accel-redirect"] == f"/_protected/uploads/{two_users['a_vid']}/source.mp4"
    assert r.content == b""
    assert two_users["b"].get(f"/api/files/uploads/{two_users['a_vid']}/source.mp4").status_code == 404


def test_search_is_scoped_to_own_videos(two_users):
    a, b = two_users["a"], two_users["b"]
    hits = b.post("/api/search", json={"query": "funny", "limit": 50}).json()
    assert hits, "B should find their own moments"
    assert {h["video_id"] for h in hits} == {two_users["b_vid"]}
    hits = a.post("/api/search", json={"query": "funny", "video_id": two_users["a_vid"]}).json()
    assert {h["video_id"] for h in hits} == {two_users["a_vid"]}
    _, me = _signup()
    c = _client()
    c.post("/api/auth/login", json={"email": me["email"], "password": PASSWORD})
    assert c.post("/api/search", json={"query": "funny"}).json() == []


# ─── agent tools never trust LLM-supplied ids ───────────────────

def test_agent_tools_check_ownership(two_users):
    a_vid, a_cid = two_users["a_vid"], two_users["a_cid"]
    b_cfg = {"configurable": {"user_id": two_users["b_me"]["id"]}}
    a_cfg = {"configurable": {"user_id": two_users["a_me"]["id"]}}
    t = agent_tools
    assert t.get_video_status.invoke({"video_id": a_vid}, config=b_cfg) == {"exists": False}
    assert t.ingest_and_analyze_video.invoke({"video_id": a_vid}, config=b_cfg)["status"] == "not_found"
    assert t.search_moments.invoke({"video_id": a_vid, "query": "funny"}, config=b_cfg) == []
    assert t.select_and_produce_clips.invoke({"video_id": a_vid}, config=b_cfg)["status"] == "video_not_found"
    assert "error" in t.modify_clip.invoke({"clip_id": a_cid, "new_caption_style": "glow"}, config=b_cfg)
    # the owner gets real answers
    st = t.get_video_status.invoke({"video_id": a_vid}, config=a_cfg)
    assert st["exists"] is True and st["clips"][0]["id"] == a_cid
    assert t.search_moments.invoke({"video_id": a_vid, "query": "funny"}, config=a_cfg)
    # no user at all -> deny
    assert t.get_video_status.invoke({"video_id": a_vid}) == {"exists": False}


def test_agent_tools_contextvar_backstop(two_users):
    a_vid = two_users["a_vid"]
    tok = agent_tools.set_current_user(two_users["b_me"]["id"])
    try:
        assert agent_tools.get_video_status.invoke({"video_id": a_vid}) == {"exists": False}
        # config says A but the turn belongs to B -> mismatch -> deny
        a_cfg = {"configurable": {"user_id": two_users["a_me"]["id"]}}
        assert agent_tools.get_video_status.invoke({"video_id": a_vid}, config=a_cfg) == {"exists": False}
    finally:
        agent_tools.reset_current_user(tok)
    tok = agent_tools.set_current_user(two_users["a_me"]["id"])
    try:
        assert agent_tools.get_video_status.invoke({"video_id": a_vid})["exists"] is True
    finally:
        agent_tools.reset_current_user(tok)


def test_chat_passes_user_to_agent_and_scopes_thread(two_users):
    b = two_users["b"]
    b_id = two_users["b_me"]["id"]
    payload = json.dumps({"video_id": two_users["a_vid"]})
    r = b.post("/api/chat/message", json={"message": f"TOOL get_video_status {payload}",
                                          "video_id": two_users["b_vid"]})
    assert r.status_code == 200, r.text
    assert json.loads(r.json()["response"]) == {"exists": False}
    cfg = fake_orchestrator.configs[-1]["configurable"]
    assert cfg["user_id"] == b_id
    assert cfg["thread_id"] == f"u:{b_id}:v:{two_users['b_vid']}"
    assert chat_router.chat_thread_id(b_id, None) == f"u:{b_id}:novideo"


def test_clips_by_ids_filters_by_owner(two_users):
    out = agent_tools.clips_by_ids([two_users["a_cid"], two_users["b_cid"]], two_users["b_me"]["id"])
    assert [c["id"] for c in out] == [two_users["b_cid"]]


# ─── quotas ─────────────────────────────────────────────────────

def test_quota_is_per_user():
    a, _ = _signup()
    b, _ = _signup()
    assert a.get("/api/chat/quota").json()["remaining"] == 2
    assert a.post("/api/chat/message", json={"message": "hi"}).status_code == 200
    assert a.post("/api/chat/message", json={"message": "hi"}).status_code == 200
    r = a.post("/api/chat/message", json={"message": "hi"})
    assert r.status_code == 429 and r.headers["x-queries-remaining"] == "0"
    assert a.get("/api/chat/quota").json()["remaining"] == 0
    # same IP, different user: own quota
    assert b.get("/api/chat/quota").json()["remaining"] == 2
    assert b.post("/api/chat/message", json={"message": "hi"}).status_code == 200


def test_ip_backstop(monkeypatch):
    from autoclip.services import rate_limit
    monkeypatch.setattr(auth_settings, "IP_DAILY_QUERY_LIMIT", 1)
    ip = "10.66.66.66"
    monkeypatch.setattr(rate_limit, "client_ip", lambda request: ip)
    a, _ = _signup()
    b, _ = _signup()
    assert a.post("/api/chat/message", json={"message": "hi"}).status_code == 200
    r = b.post("/api/chat/message", json={"message": "hi"})
    assert r.status_code == 429
    assert b.get("/api/chat/quota").json()["remaining"] == 2  # B's own quota refunded


def test_failed_agent_run_is_refunded(monkeypatch):
    c, _ = _signup()

    class Boom:
        def invoke(self, *a, **k):
            raise RuntimeError("provider down")

    monkeypatch.setattr(chat_router, "orchestrator", Boom())
    r = c.post("/api/chat/message", json={"message": "hi"})
    assert r.status_code == 200 and r.json()["queries_remaining"] == 2


# ─── upload caps & demo account ─────────────────────────────────

def _upload(c: TestClient, name="clip.mp4"):
    return c.post("/api/videos/upload", files={"file": (name, b"not-really-a-video", "video/mp4")})


def test_upload_caps(monkeypatch):
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": 30.0, "resolution": "640x360"})
    c, me = _signup()
    r = _upload(c)
    assert r.status_code == 200, r.text
    assert r.json()["source_url"].startswith("/api/files/uploads/")
    db = SessionLocal()
    try:
        assert db.query(Video).filter(Video.id == r.json()["id"]).one().user_id == me["id"]
    finally:
        db.close()
    assert _upload(c).status_code == 200
    r = _upload(c)
    assert r.status_code == 409  # MAX_VIDEOS_PER_USER=2 in this test env
    # too long for a non-admin
    c2, _ = _signup()
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": 2 * 3600.0, "resolution": "x"})
    r = _upload(c2)
    assert r.status_code == 413
    assert c2.get("/api/videos").json() == []
    # admins: no count cap, but the length cap applies to them too
    # (VIDEO_MINUTES_CAP_ADMINS defaults on; tests/test_podcast.py covers it)
    admin = _client()
    admin.post("/api/auth/login", json={"email": "boss@example.com", "password": PASSWORD})
    if admin.get("/api/auth/me").status_code != 200:
        admin, _ = _signup("boss@example.com")
    assert _upload(admin).status_code == 413
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": 30.0, "resolution": "x"})
    for _ in range(3):
        assert _upload(admin).status_code == 200


def test_owner_can_delete_but_not_others():
    a, me = _signup()
    vid, _ = _make_video(me["id"])
    b, _ = _signup()
    assert b.delete(f"/api/videos/{vid}").status_code == 404
    assert a.delete(f"/api/videos/{vid}").status_code == 200
    assert a.get(f"/api/videos/{vid}").status_code == 404
    assert not (Path(UPLOAD_DIR) / vid).exists()


@pytest.fixture(scope="module")
def demo():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == auth_settings.DEMO_EMAIL).first()
        if user is None:
            user = User(email=auth_settings.DEMO_EMAIL, password_hash=UNUSABLE_PASSWORD, is_demo=True)
            db.add(user)
            db.commit()
        uid = user.id
    finally:
        db.close()
    vid, cid = _make_video(uid)
    return dict(id=uid, vid=vid, cid=cid)


def test_demo_account(demo, monkeypatch):
    c = _client()
    r = c.post("/api/auth/demo")
    assert r.status_code == 200 and r.json()["is_demo"] is True
    assert {v["id"] for v in c.get("/api/videos").json()} == {demo["vid"]}
    assert c.get(f"/api/files/uploads/{demo['vid']}/source.mp4").status_code == 200
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": 30.0, "resolution": "x"})
    assert _upload(c).status_code == 403
    assert c.delete(f"/api/videos/{demo['vid']}").status_code == 403
    # cannot log in with a password, cannot be signed up for
    assert _client().post("/api/auth/login", json={"email": auth_settings.DEMO_EMAIL,
                                                   "password": PASSWORD}).status_code == 401
    assert _client().post("/api/auth/signup", json={"email": auth_settings.DEMO_EMAIL,
                                                    "password": PASSWORD}).status_code == 400
    # shared, small chat quota across all demo visitors
    other = _client()
    other.post("/api/auth/demo")
    codes = [x.post("/api/chat/message", json={"message": "hi"}).status_code
             for x in (c, other, c, other)]
    assert codes == [200, 200, 200, 429]
    # demo visitors still can't reach regular users' data
    a, me = _signup()
    vid, _ = _make_video(me["id"])
    assert c.get(f"/api/videos/{vid}").status_code == 404


def test_legacy_owner_claim_via_admin_signup(monkeypatch):
    """Migration 0002 may create a passwordless owner for ADMIN_EMAILS[0];
    signing up with that email claims it. Other existing emails can't be."""
    db = SessionLocal()
    try:
        db.add(User(email="legacy@example.com", password_hash=UNUSABLE_PASSWORD))
        db.commit()
    finally:
        db.close()
    r = _client().post("/api/auth/signup", json={"email": "legacy@example.com", "password": PASSWORD})
    assert r.status_code == 409   # not an admin email -> no claim
    assert _client().post("/api/auth/login", json={"email": "legacy@example.com",
                                                   "password": PASSWORD}).status_code == 401
    monkeypatch.setattr(auth_settings, "ADMIN_EMAILS", ["legacy@example.com"])
    c = _client()
    r = c.post("/api/auth/signup", json={"email": "legacy@example.com", "password": PASSWORD})
    assert r.status_code == 201 and r.json()["is_admin"] is True
    # once claimed it has a real password: a second claim is refused
    r = _client().post("/api/auth/signup", json={"email": "legacy@example.com", "password": PASSWORD + "x"})
    assert r.status_code == 409


# ─── migrations ─────────────────────────────────────────────────

def test_migration_0002_assigns_existing_videos_to_legacy_owner(tmp_path):
    """Run 0001, insert a pre-auth video, then 0002: the video gets an owner."""
    db_url = f"sqlite:///{tmp_path / 'm.db'}"
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": db_url, "ADMIN_EMAILS": "Owner@Example.com,second@example.com"}
    run = lambda *args: subprocess.run([sys.executable, "-m", "alembic", *args], cwd=backend, env=env,
                                       capture_output=True, text=True, check=True)
    run("upgrade", "0001")
    import sqlalchemy as sa
    eng = sa.create_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sa.text("INSERT INTO videos (id, filename, file_path, status) "
                             "VALUES ('legacyvid', 'old.mp4', '/x', 'completed')"))
    run("upgrade", "head")
    with eng.begin() as conn:
        owner = conn.execute(sa.text("SELECT id, email, is_admin, password_hash FROM users")).one()
        uid = conn.execute(sa.text("SELECT user_id FROM videos WHERE id='legacyvid'")).scalar()
    assert owner.email == "owner@example.com" and owner.is_admin and owner.password_hash == "!"
    assert uid == owner.id
    run("downgrade", "0001")
    run("upgrade", "head")
