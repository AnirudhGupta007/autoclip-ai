"""Podcast / 1-hour scope: audio upload -> audiogram, static-shot frame
reduction, transcript-only chunks for audio, the length cap for everyone,
and the credits guard. No network.

Reuses the app + temp DB set up by test_auth_isolation (same process).
The audiogram tests need a real ffmpeg and are skipped without one — run
them inside the backend image:

    cd backend && uv run --with pytest --with argon2-cffi --with alembic pytest tests/test_podcast.py -q
    docker run --rm -v "$PWD/backend:/w" -w /w --entrypoint sh autoclip-ai-backend -c \\
        "/usr/local/bin/pip install -q --target /tmp/pt pytest &&
         PYTHONPATH=/tmp/pt:/w/src python -m pytest tests -q -p no:cacheprovider"
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from test_auth_isolation import PASSWORD, SessionLocal, Video, _client, _signup, videos_router  # noqa: F401

from autoclip.auth import settings as auth_settings
from autoclip.config import OUTPUT_DIR
from autoclip.pipeline.agents import chunk_analyzer as CA
from autoclip.pipeline.state import ChunkPlan
from autoclip.services import audiogram as AG
from autoclip.utils import video_profile as VP

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _admin():
    c = _client()
    c.post("/api/auth/login", json={"email": "boss@example.com", "password": PASSWORD})
    if c.get("/api/auth/me").status_code != 200:
        c, _ = _signup("boss@example.com")
    return c


def _probe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
                          "-show_streams", path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _tone(path: Path, seconds: int = 4) -> bytes:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-ac", "1", str(path)], check=True)
    return path.read_bytes()


# ─── audio upload -> audiogram ──────────────────────────────────

def test_title_lines_wrap_and_truncate():
    assert AG.title_lines("my_show-ep_12.mp3") == "my show ep 12"
    t = AG.title_lines("a very long podcast episode title that keeps going and going.mp3")
    assert t.count("\n") == AG.TITLE_LINES - 1 and t.endswith("…")
    assert all(len(line) <= AG.TITLE_CHARS for line in t.split("\n"))


@needs_ffmpeg
def test_make_audiogram_is_a_video_with_the_audio(tmp_path):
    src = tmp_path / "ep.wav"
    _tone(src, 3)
    out = AG.make_audiogram(str(src), str(tmp_path / "source.mp4"), "Ep: 100% 'quotes'.wav", "vid", 3.0)
    info = _probe(out)
    kinds = {s["codec_type"]: s for s in info["streams"]}
    assert kinds["video"]["width"] == AG.SIZE and kinds["video"]["height"] == AG.SIZE
    assert kinds["audio"]["codec_name"] == "aac"  # wav is re-encoded, aac/mp3 are copied
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.5
    assert not src.exists() and not (tmp_path / "title.txt").exists()


@needs_ffmpeg
def test_audiogram_copies_mp3_audio(tmp_path):
    src = tmp_path / "ep.mp3"
    _tone(src, 2)
    out = AG.make_audiogram(str(src), str(tmp_path / "source.mp4"), "ep.mp3", "vid", 2.0)
    assert {s["codec_type"]: s["codec_name"] for s in _probe(out)["streams"]}["audio"] == "mp3"


@needs_ffmpeg
def test_audiogram_clip_render_draws_waveform(tmp_path):
    from autoclip.utils.ffmpeg import aspect_crop, render_clip
    src = tmp_path / "ep.wav"
    _tone(src, 4)
    card = AG.make_audiogram(str(src), str(tmp_path / "source.mp4"), "ep.wav", "vid", 4.0)
    crop = aspect_crop((AG.SIZE, AG.SIZE, 0, 0), 1080, 1920, None)
    out = render_clip(card, str(tmp_path / "clip.mp4"), 0.5, 3.0, crop=crop, scale=(1080, 1920),
                      waveform=True)
    info = _probe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920) and v["r_frame_rate"] == "30/1"
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert abs(float(info["format"]["duration"]) - 2.5) < 0.3
    # the waveform band in the middle is lit (gold), the card's top-left is black
    frame = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", out, "-frames:v", "1",
                    str(frame)], check=True)
    import cv2
    img = cv2.imread(str(frame))
    assert img[900:1020].mean() > img[:200, :200].mean() + 1


@needs_ffmpeg
def test_audio_upload_becomes_audiogram(tmp_path):
    c, _ = _signup()
    data = _tone(tmp_path / "tone.mp3")
    r = c.post("/api/videos/upload", files={"file": ("My Podcast.mp3", data, "audio/mpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["media_kind"] == "audio" and body["resolution"] == f"{AG.SIZE}x{AG.SIZE}"
    assert abs(body["duration"] - 4.0) < 0.5
    db = SessionLocal()
    try:
        v = db.query(Video).filter(Video.id == body["id"]).one()
        assert v.media_kind == "audio" and v.file_path.endswith("/source.mp4")
        folder = Path(v.file_path).parent
    finally:
        db.close()
    assert sorted(p.name for p in folder.iterdir()) == ["source.mp4"]  # original audio removed
    # profile pre-seeded: no letterbox crop to the waveform, no "credits"
    prof = VP.get_profile(body["id"], str(folder / "source.mp4"))
    assert prof["letterbox"] is None and prof["credits_start"] is None
    assert prof["media_kind"] == "audio"


def test_audio_upload_failure_cleans_up(monkeypatch):
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": 30.0, "resolution": None})

    def boom(*a, **k):
        raise RuntimeError("encode failed")

    monkeypatch.setattr(videos_router, "make_audiogram", boom)
    c, _ = _signup()
    r = c.post("/api/videos/upload", files={"file": ("x.m4a", b"junk", "audio/mp4")})
    assert r.status_code == 422
    assert c.get("/api/videos").json() == []


def test_unsupported_format_rejected():
    c, _ = _signup()
    r = c.post("/api/videos/upload", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400


# ─── 60-minute cap for everyone ─────────────────────────────────

def test_length_cap_applies_to_admins(monkeypatch):
    cap = auth_settings.MAX_VIDEO_MINUTES_DEMO * 60
    admin = _admin()
    up = lambda: admin.post("/api/videos/upload",  # noqa: E731
                            files={"file": ("long.mp4", b"x", "video/mp4")})
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": cap + 1.0, "resolution": "x"})
    r = up()
    assert r.status_code == 413 and "60 minutes" in r.json()["detail"]
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": cap - 1.0, "resolution": "x"})
    assert up().status_code == 200
    # flag off -> admins uncapped again (non-admins stay capped)
    monkeypatch.setattr(auth_settings, "VIDEO_MINUTES_CAP_ADMINS", False)
    monkeypatch.setattr(videos_router, "get_video_info", lambda p: {"duration": cap * 2.0, "resolution": "x"})
    assert up().status_code == 200
    c, _ = _signup()
    assert c.post("/api/videos/upload", files={"file": ("l.mp4", b"x", "video/mp4")}).status_code == 413


def test_upload_size_message_uses_the_config(monkeypatch):
    monkeypatch.setattr(videos_router, "MAX_UPLOAD_SIZE", 10)
    monkeypatch.setattr(videos_router, "MAX_UPLOAD_SIZE_MB", 0.00001)
    c, _ = _signup()
    r = c.post("/api/videos/upload", files={"file": ("big.mp4", b"x" * 100, "video/mp4")})
    assert r.status_code == 413 and "500MB" not in r.json()["detail"]


# ─── static-shot frame reduction ────────────────────────────────

def _sig(v: float) -> np.ndarray:
    return np.full((18, 32), v, dtype=np.float32)


def test_static_keep_single_shot_sends_four():
    rng = np.random.default_rng(0)
    sigs = [_sig(100) + rng.normal(0, 2, (18, 32)).astype(np.float32) for _ in range(24)]
    keep = CA.static_keep(sigs, max_looks=4, threshold=12)
    assert keep is not None and len(keep) == 4 and keep == sorted(keep)


def test_static_keep_two_angles_keeps_both():
    sigs = [_sig(40 if (i // 3) % 2 else 200) for i in range(24)]  # cut every 3 frames
    keep = CA.static_keep(sigs, max_looks=4, threshold=12)
    assert keep is not None and len(keep) == 4
    assert {0, 3} <= set(keep)  # first frame of each angle


def test_static_keep_moving_footage_sends_all():
    sigs = [_sig(i * 10) for i in range(24)]
    assert CA.static_keep(sigs, max_looks=4, threshold=12) is None
    assert CA.static_keep(sigs[:4], max_looks=4, threshold=12) is None  # too few to reduce
    assert CA.static_keep([_sig(1)] * 23 + [None], max_looks=4, threshold=12) is None


def _plan(kind: str = "video") -> ChunkPlan:
    words = [{"text": "hello", "start": 1.0, "end": 1.5}, {"text": "world", "start": 1.6, "end": 2.0}]
    return ChunkPlan(index=0, start=0.0, end=120.0, video_path="/nonexistent.mp4",
                     transcript_window={"words": words, "utterances": []}, media_kind=kind)


def _fake_frames(values):
    import cv2

    def sample(video_path, chunk_start, times, out_dir, width=768):
        outs = []
        for i, t in enumerate(times):
            p = Path(out_dir) / f"f_{i:03d}.jpg"
            cv2.imwrite(str(p), np.full((90, 160), values(i), dtype=np.uint8))
            outs.append((t, str(p)))
        return outs
    return sample


def _images(messages) -> int:
    return sum(1 for part in messages[1]["content"] if part.get("type") == "image_url")


def test_build_messages_static_shot_sends_fewer_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(CA, "VISION_STATIC_CHECK", True)
    monkeypatch.setattr(CA, "_sample_frames", _fake_frames(lambda i: 120))
    msgs, mode = CA._build_messages(_plan(), "frames", tmp_path)
    assert mode == "frames" and _images(msgs) == CA.VISION_STATIC_FRAMES < CA.VISION_MAX_FRAMES
    # check off -> the full set
    monkeypatch.setattr(CA, "VISION_STATIC_CHECK", False)
    msgs, _ = CA._build_messages(_plan(), "frames", tmp_path)
    assert _images(msgs) == CA.VISION_MAX_FRAMES


def test_build_messages_moving_footage_sends_all(tmp_path, monkeypatch):
    monkeypatch.setattr(CA, "VISION_STATIC_CHECK", True)
    monkeypatch.setattr(CA, "_sample_frames", _fake_frames(lambda i: (i * 37) % 256))
    msgs, _ = CA._build_messages(_plan(), "frames", tmp_path)
    assert _images(msgs) == CA.VISION_MAX_FRAMES


def test_audio_chunk_is_transcript_only(tmp_path, monkeypatch):
    def no_ffmpeg(*a, **k):
        raise AssertionError("audio chunks must not sample frames")
    monkeypatch.setattr(CA, "_sample_frames", no_ffmpeg)
    monkeypatch.setattr(CA, "_encode_chunk_video", no_ffmpeg)
    seen = {}

    def fake_call(messages, attempt):
        seen["messages"] = messages
        return {"moments": [{"start": 1, "end": 10, "description": "host greets", "transcript": "hello world",
                             "style_tags": [], "visual_energy": 0, "audio_energy": 0.5,
                             "text_hook_strength": 0.6, "convergence_score": 0.5}]}, None
    monkeypatch.setattr(CA, "_call", fake_call)
    moments = CA.analyze_chunk(_plan("audio"), video_id=None, mode="video")
    assert len(moments) == 1
    msgs = seen["messages"]
    assert _images(msgs) == 0 and msgs[0]["content"] == CA._SYSTEM_AUDIO
    assert not any(p.get("type") == "video_url" for p in msgs[1]["content"])


# ─── credits guard ──────────────────────────────────────────────

def test_no_credits_detection_for_short_or_audio(monkeypatch):
    called = []
    monkeypatch.setattr(VP, "scan_keyframe_luma", lambda p, s: called.append(s) or [])
    assert VP.detect_credits_start("x.mp4", 69 * 60) is None and called == []
    VP.detect_credits_start("x.mp4", 98 * 60)
    assert called  # feature-length: still probed
    monkeypatch.setattr(VP, "get_profile", lambda vid, path: {"credits_start": 3000.0})
    assert VP.credits_start("v", "x.mp4", "audio") is None
    assert VP.credits_start("v", "x.mp4", "video") == 3000.0
