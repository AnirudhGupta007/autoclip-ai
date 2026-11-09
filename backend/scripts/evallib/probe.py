"""ffprobe / ffmpeg helpers for inspecting delivered clips.

ffmpeg is not required on the host: if it is missing, every command runs via
``docker exec <container>`` against the file inside the backend container
(clips live under /app/outputs there). Paths are always *container* paths in
docker mode and *host* paths in local mode; :func:`resolve_clip_path` maps
the API's ``outputs/<vid>/clips/<id>/final.mp4`` to the right one.

Everything here is best effort: a probe that fails returns ``None`` fields
rather than raising, so a missing file never kills a report.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_CONTAINER = "autoclip-ai-backend-1"
CONTAINER_ROOT = "/app"


@dataclass
class Runner:
    """Runs ffmpeg/ffprobe either locally or inside the backend container."""
    container: Optional[str] = None  # None → local
    local_root: Optional[Path] = None  # host dir that maps to /app (local mode)

    @classmethod
    def auto(cls, container: str = DEFAULT_CONTAINER, local_root: Optional[Path] = None,
             prefer_local: bool = True) -> "Runner":
        if prefer_local and shutil.which("ffprobe") and shutil.which("ffmpeg") and local_root:
            return cls(container=None, local_root=local_root)
        if shutil.which("docker"):
            try:
                r = subprocess.run(["docker", "exec", container, "which", "ffprobe"],
                                   capture_output=True, text=True, timeout=20)
                if r.returncode == 0:
                    return cls(container=container)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if shutil.which("ffprobe"):
            return cls(container=None, local_root=local_root)
        raise RuntimeError("no ffprobe on the host and the backend container is not reachable")

    def run(self, argv: list[str], timeout: float = 120, binary: bool = False):
        cmd = (["docker", "exec", self.container] + argv) if self.container else argv
        return subprocess.run(cmd, capture_output=True, text=not binary, timeout=timeout)

    def exists(self, path: str) -> bool:
        if self.container:
            return self.run(["test", "-f", path], timeout=20).returncode == 0
        return Path(path).is_file()


def resolve_clip_path(runner: Runner, file_path: str) -> str:
    """'outputs/<vid>/clips/<id>/final.mp4' (API form) → absolute path for the runner."""
    rel = file_path.lstrip("/")
    if rel.startswith("app/"):
        rel = rel[len("app/"):]
    if runner.container:
        return f"{CONTAINER_ROOT}/{rel}"
    root = runner.local_root or Path(".")
    return str(root / rel)


@dataclass
class ClipProbe:
    path: str
    exists: bool = False
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    has_audio: Optional[bool] = None
    black_bar_frac: Optional[float] = None   # fraction of frame area cropdetect calls black
    has_ass: Optional[bool] = None           # captions.ass next to the clip
    caption_diff: Optional[float] = None     # mean |final - reframed| in the bottom third (0-255)
    ass_events: Optional[int] = None         # Dialogue events of captions.ass inside the clip
    captions_visible: Optional[bool] = None
    caption_evidence: Optional[str] = None   # how captions_visible was decided
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        return d


def ffprobe(runner: Runner, path: str) -> dict:
    r = runner.run(["ffprobe", "-v", "error", "-show_entries",
                    "format=duration:stream=codec_type,width,height", "-of", "json", path], timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return json.loads(r.stdout)


def cropdetect_black_fraction(runner: Runner, path: str, width: int, height: int,
                              duration: float, samples: int = 3) -> Optional[float]:
    """Run cropdetect on a few short windows; report 1 - (crop area / frame area)
    using the *largest* crop seen (so a dark scene doesn't look letterboxed)."""
    best = 0
    for k in range(samples):
        t = max(0.0, duration * (k + 1) / (samples + 1) - 1)
        r = runner.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{t:.2f}", "-i", path, "-t", "2",
                        "-vf", "cropdetect=24:2:0", "-an", "-f", "null", "-"], timeout=120)
        for m in re.finditer(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr or ""):
            w, h = int(m.group(1)), int(m.group(2))
            best = max(best, w * h)
    if best == 0:
        return None
    return max(0.0, 1.0 - best / float(width * height))


def _gray_frame(runner: Runner, path: str, t: float, w: int = 96, h: int = 160) -> Optional[bytes]:
    r = runner.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                    "-vf", f"scale={w}:{h}", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
                   timeout=60, binary=True)
    if r.returncode != 0 or len(r.stdout) != w * h:
        return None
    return r.stdout


def bottom_third_diff(runner: Runner, final: str, reference: str, duration: float,
                      samples: int = 4, w: int = 96, h: int = 160) -> Optional[float]:
    """Mean absolute pixel difference between the final clip and the pre-caption
    render (reframed.mp4) in the bottom third. Burned-in captions show up as a
    clear difference there; identical renders give ~0."""
    diffs = []
    for k in range(samples):
        t = duration * (k + 1) / (samples + 1)
        a, b = _gray_frame(runner, final, t, w, h), _gray_frame(runner, reference, t, w, h)
        if a is None or b is None:
            continue
        start = (2 * h // 3) * w
        diffs.append(sum(abs(x - y) for x, y in zip(a[start:], b[start:])) / (len(a) - start))
    return sum(diffs) / len(diffs) if diffs else None


_ASS_TIME = re.compile(r"^Dialogue:\s*[^,]*,(\d+):(\d+):(\d+(?:\.\d+)?),(\d+):(\d+):(\d+(?:\.\d+)?),")


def parse_ass_events(text: str, duration: float) -> int:
    """Number of ASS Dialogue events that are on screen inside [0, duration]."""
    n = 0
    for line in (text or "").splitlines():
        m = _ASS_TIME.match(line.strip())
        if not m:
            continue
        h1, m1, s1, h2, m2, s2 = m.groups()
        a = int(h1) * 3600 + int(m1) * 60 + float(s1)
        b = int(h2) * 3600 + int(m2) * 60 + float(s2)
        if b > a and a < duration and b > 0:
            n += 1
    return n


def ass_events_in_range(runner: Runner, ass_path: str, duration: float) -> Optional[int]:
    if runner.container:
        r = runner.run(["cat", ass_path], timeout=20)
        if r.returncode != 0:
            return None
        text = r.stdout
    else:
        try:
            text = Path(ass_path).read_text(errors="replace")
        except OSError:
            return None
    return parse_ass_events(text, duration)


def captions_from_ass(has_ass: Optional[bool], events: Optional[int]) -> tuple[Optional[bool], Optional[str]]:
    """Single-pass renders burn captions.ass straight into final.mp4, and
    production deletes the .ass when it had to render without captions — so
    an .ass with events in range means captions were burned in. No .ass is
    *unknown* (no speech in the window, or caption generation failed)."""
    if has_ass and events:
        return True, "ass_events"
    if has_ass and events == 0:
        return False, "ass_empty"
    return None, None


def probe_clip(runner: Runner, path: str, deep: bool = True, caption_threshold: float = 2.0) -> ClipProbe:
    p = ClipProbe(path=path)
    try:
        p.exists = runner.exists(path)
        if not p.exists:
            p.errors.append("missing")
            return p
        info = ffprobe(runner, path)
        p.duration = float(info.get("format", {}).get("duration") or 0) or None
        streams = info.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        p.width, p.height = v.get("width"), v.get("height")
        p.has_audio = any(s.get("codec_type") == "audio" for s in streams)
        clip_dir = path.rsplit("/", 1)[0]
        ass = f"{clip_dir}/captions.ass"
        p.has_ass = runner.exists(ass)
        if p.has_ass and p.duration:
            p.ass_events = ass_events_in_range(runner, ass, p.duration)
        if deep and p.width and p.height and p.duration:
            p.black_bar_frac = cropdetect_black_fraction(runner, path, p.width, p.height, p.duration)
            ref = f"{clip_dir}/reframed.mp4"
            if runner.exists(ref):  # legacy two-pass renders: pixel diff vs the uncaptioned file
                p.caption_diff = bottom_third_diff(runner, path, ref, p.duration)
                if p.caption_diff is not None:
                    p.captions_visible = p.caption_diff >= caption_threshold
                    p.caption_evidence = "pixel_diff_vs_reframed"
        if p.captions_visible is None:
            p.captions_visible, p.caption_evidence = captions_from_ass(p.has_ass, p.ass_events)
    except (RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        p.errors.append(str(e)[:200])
    return p
