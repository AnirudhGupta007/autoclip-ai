"""Minimal stdlib HTTP client for the AutoClip API, the OpenRouter credits
endpoint, and a read-only postgres fallback for moments.

Written defensively: the backend is being refactored (analysis moving to a
background task), so responses are parsed with ``.get`` everywhere and
unknown shapes degrade to "no data" instead of crashing.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional


class QuotaExceeded(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


def _req(url: str, method: str = "GET", body: Any = None, headers: Optional[dict] = None,
         timeout: float = 60) -> tuple[int, dict, Any]:
    data = None
    hdrs = dict(headers or {})
    if body is not None and not isinstance(body, (bytes, bytearray)):
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = body
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status, rh = r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw, status, rh = e.read(), e.code, dict(e.headers or {})
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = raw.decode(errors="replace")
    return status, rh, payload


# --------------------------------------------------------------------- OpenRouter
def read_env_key(env_path: Path, name: str = "OPENROUTER_API_KEY") -> Optional[str]:
    if os.environ.get(name):
        return os.environ[name]
    if not env_path.is_file():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


class Credits:
    """Reads cumulative OpenRouter usage; deltas between reads = spend.
    The endpoint lags by a few seconds, so callers should settle() before the
    final read."""

    URL = "https://openrouter.ai/api/v1/credits"

    def __init__(self, key: Optional[str]):
        self.key = key

    def usage(self) -> Optional[float]:
        if not self.key:
            return None
        try:
            status, _, p = _req(self.URL, headers={"Authorization": f"Bearer {self.key}"}, timeout=20)
            if status == 200 and isinstance(p, dict):
                return float(p["data"]["total_usage"])
        except (OSError, KeyError, TypeError, ValueError):
            pass
        return None


# ------------------------------------------------------------------------ AutoClip
ANALYSIS_STARTED_RE = re.compile(
    r"(analy[sz](is|ing)\b.{0,40}\b(start|started|running|in progress|underway|kicked off|queued|begun|began))"
    r"|((start|started|kicked off|began|queued)\b.{0,30}\banaly[sz])"
    r"|(still analy[sz]ing)|(check back)|(come back (in|when))", re.I | re.S)


def looks_like_analysis_started(resp: dict) -> bool:
    """Heuristic: did the chat turn kick off (background) analysis instead of
    producing clips? Accepts explicit flags if the API grows them."""
    if not isinstance(resp, dict):
        return False
    for k in ("analysis_started", "analysis_in_progress", "is_processing", "processing"):
        if resp.get(k) is True:
            return True
    if str(resp.get("status", "")).lower() in {"analyzing", "analysis_started", "processing", "queued"}:
        return True
    if resp.get("clips"):
        return False
    return bool(ANALYSIS_STARTED_RE.search(str(resp.get("response", ""))))


class AutoClip:
    """API client. The backend requires a signed-in session: pass
    email/password (or set EVAL_EMAIL / EVAL_PASSWORD) and the client logs in
    once and replays the session cookie on every call. The cookie is handled
    by hand rather than with http.cookiejar because a `Secure` cookie
    (COOKIE_SECURE=1) must still be sent to a plain-http backend URL such as
    http://127.0.0.1:8000 on the server itself."""

    def __init__(self, base: str, log: Callable[[str], None] = print,
                 email: Optional[str] = None, password: Optional[str] = None):
        self.base = base.rstrip("/")
        self.log = log
        self.email = email or os.environ.get("EVAL_EMAIL")
        self.password = password or os.environ.get("EVAL_PASSWORD")
        self.cookies: dict[str, str] = {}
        self._logged_in = False

    def url(self, path: str) -> str:
        return self.base + path

    # ------------------------------------------------------------ session
    def _remember_cookies(self, headers: dict) -> None:
        raw = [v for k, v in headers.items() if k.lower() == "set-cookie"]
        for line in raw:
            for part in re.split(r",(?=\s*[^;,=\s]+=)", line):  # tolerate folded headers
                name, _, rest = part.strip().partition("=")
                value = rest.split(";", 1)[0]
                if name.endswith("session"):
                    if value and "max-age=0" not in part.lower():
                        self.cookies[name] = value
                    else:
                        self.cookies.pop(name, None)

    def _req(self, path: str, method: str = "GET", body: Any = None, headers: Optional[dict] = None,
             timeout: float = 60) -> tuple[int, dict, Any]:
        if not self._logged_in and self.email and not path.startswith("/api/auth/"):
            self.login()
        hdrs = dict(headers or {})
        if self.cookies:
            hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        status, rh, payload = _req(self.url(path), method, body, hdrs, timeout=timeout)
        self._remember_cookies(rh)
        if status == 401 and not path.startswith("/api/auth/"):
            raise ApiError(f"HTTP 401 from {path}: the API needs a login — pass --email/--password "
                           f"or set EVAL_EMAIL/EVAL_PASSWORD.")
        return status, rh, payload

    def login(self) -> dict:
        if not (self.email and self.password):
            raise ApiError("login needs an email and password (EVAL_EMAIL / EVAL_PASSWORD)")
        self._logged_in = True  # set first: _req() must not recurse into login()
        s, _, p = self._req("/api/auth/login", "POST", {"email": self.email, "password": self.password},
                            timeout=30)
        if s != 200 or not isinstance(p, dict):
            self._logged_in = False
            detail = p.get("detail") if isinstance(p, dict) else p
            raise ApiError(f"login failed: HTTP {s}: {detail!r}")
        self.log(f"  logged in as {p.get('email')}{' (admin)' if p.get('is_admin') else ''}")
        return p

    def health(self) -> bool:
        for p in ("/health", "/api/health", "/"):
            try:
                s, _, _ = _req(self.url(p), timeout=10)  # public, no session needed
                if s < 500:
                    return True
            except OSError:
                continue
        return False

    def quota(self) -> Optional[dict]:
        s, _, p = self._req("/api/chat/quota", timeout=15)
        return p if s == 200 and isinstance(p, dict) else None

    def video(self, video_id: str) -> Optional[dict]:
        s, _, p = self._req(f"/api/videos/{video_id}", timeout=15)
        return p if s == 200 and isinstance(p, dict) else None

    def analysis(self, video_id: str) -> dict:
        s, _, p = self._req(f"/api/chat/analysis/{video_id}", timeout=30)
        return p if s == 200 and isinstance(p, dict) else {}

    def clips(self, video_id: str) -> list[dict]:
        s, _, p = self._req("/api/clips?" + urllib.parse.urlencode({"video_id": video_id}), timeout=30)
        return p if s == 200 and isinstance(p, list) else []

    def moments_endpoint(self, video_id: str) -> Optional[list[dict]]:
        """Try plausible moments endpoints; None if the API has none."""
        for path in (f"/api/videos/{video_id}/moments", f"/api/moments?video_id={video_id}",
                     f"/api/chat/moments/{video_id}"):
            try:
                s, _, p = self._req(path, timeout=30)
            except OSError:
                continue
            if s == 200:
                if isinstance(p, dict):
                    p = p.get("moments")
                if isinstance(p, list):
                    return p
        return None

    def upload(self, path: Path, timeout: float = 3600) -> dict:
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        body = head + path.read_bytes() + tail
        s, _, p = self._req("/api/videos/upload", "POST", body,
                       {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=timeout)
        if s != 200 or not isinstance(p, dict) or "id" not in p:
            raise ApiError(f"upload failed: HTTP {s}: {str(p)[:300]}")
        return p

    def chat(self, video_id: str, message: str, timeout: float = 7200) -> tuple[int, dict, dict]:
        s, h, p = self._req("/api/chat/message", "POST",
                       {"message": message, "video_id": video_id}, timeout=timeout)
        if s == 429:
            detail = p.get("detail") if isinstance(p, dict) else p
            raise QuotaExceeded(
                f"HTTP 429 from /api/chat/message: {detail!r}. The backend meters chat turns per user per day "
                f"(DAILY_QUERY_LIMIT, default 2; ADMIN_EMAILS accounts are unlimited — log in as one). This eval sends one turn per query per run, plus one "
                f"re-send per query if analysis runs in the background. Set DAILY_QUERY_LIMIT=50 (or higher) "
                f"in .env and recreate the backend (docker compose up -d backend), or wait for the reset "
                f"(Retry-After: {next((v for k, v in h.items() if k.lower() == 'retry-after'), '?')}s).")
        if s != 200 or not isinstance(p, dict):
            raise ApiError(f"chat failed: HTTP {s}: {str(p)[:300]}")
        return s, h, p

    def wait_for_analysis(self, video_id: str, timeout_s: float = 3 * 3600, poll_s: float = 15) -> dict:
        """Poll GET /api/chat/analysis/{id} until analysed. Tolerant of several
        status shapes: {analyzed: bool}, {status: 'done'|'completed'|'failed'},
        {progress: 0-100}."""
        t0 = time.time()
        last = None
        prev_count = None
        while time.time() - t0 < timeout_s:
            st = self.analysis(video_id)
            status = str(st.get("status", "")).lower()
            if status in {"failed", "error"}:
                raise ApiError(f"analysis failed: {st}")
            count = st.get("moment_count") or 0
            done = st.get("analyzed") is True or status in {"done", "completed", "analyzed", "ready"}
            busy = status in {"analyzing", "running", "processing", "queued", "pending"} or \
                st.get("in_progress") is True or st.get("is_processing") is True
            # Without an explicit status, "analyzed" may just mean "has ≥1 moment"
            # (moments can land chunk by chunk) — so also require a stable count.
            stable = bool(status) or (prev_count is not None and count == prev_count)
            if done and count > 0 and not busy and stable:
                return st
            prev_count = count
            msg = f"analysis: {json.dumps(st)[:160]}"
            if msg != last:
                self.log(f"  … {msg} ({time.time() - t0:.0f}s)")
                last = msg
            time.sleep(poll_s)
        raise ApiError(f"analysis did not finish within {timeout_s:.0f}s")


# ------------------------------------------------------------------ postgres fallback
PG_CONTAINER = "autoclip-ai-postgres-1"


def moments_from_postgres(video_id: str, container: str = PG_CONTAINER, user: str = "autoclip",
                          db: str = "autoclip") -> Optional[list[dict]]:
    """Read moments straight from the `moments` table (read-only SELECT)."""
    if not re.fullmatch(r"[0-9a-zA-Z_-]+", video_id):
        raise ValueError("bad video id")
    sql = ("SELECT coalesce(json_agg(t ORDER BY t.start), '[]'::json) FROM ("
           "SELECT start, \"end\", convergence_score, style_tags, description, "
           "visual_energy, audio_energy, text_hook_strength, modalities_active "
           f"FROM moments WHERE video_id = '{video_id}') t")
    try:
        r = subprocess.run(["docker", "exec", container, "psql", "-U", user, "-d", db, "-At", "-c", sql],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.strip() or "[]")
    except json.JSONDecodeError:
        return None


def transcript_from_container(video_id: str, container: str = "autoclip-ai-backend-1") -> Optional[dict]:
    """Word *timings only* (no text) from /app/outputs/<vid>/transcript.json."""
    code = ("import json,sys;d=json.load(open(sys.argv[1]));"
            "print(json.dumps({'duration':d.get('duration'),"
            "'word_starts':[w.get('start') for w in d.get('words',[]) if w.get('start') is not None]}))")
    try:
        r = subprocess.run(["docker", "exec", container, "python3", "-c", code,
                            f"/app/outputs/{video_id}/transcript.json"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
