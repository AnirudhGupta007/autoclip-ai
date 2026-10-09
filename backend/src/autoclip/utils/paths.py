"""Filesystem <-> public-URL helpers for generated media.

Clips used to be stored with whatever path string produced them — relative
("outputs/<vid>/...") from the pipeline, absolute ("/app/outputs/...") from
the reprocess path — and URLs were built with `"/" + path`, which turned the
absolute form into the broken "//app/outputs/...". Everything now goes
through `public_url()`, which maps any path under OUTPUT_DIR / UPLOAD_DIR to
the authorised file route ("/api/files/outputs/...", "/api/files/uploads/...",
see routers/files.py) regardless of how it was stored. There are no public
static mounts any more: every media URL is ownership-checked.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from autoclip.config import OUTPUT_DIR, UPLOAD_DIR


def video_output_dir(video_id: str) -> Path:
    return Path(OUTPUT_DIR) / video_id


def clip_dir(video_id: str, clip_id: str) -> Path:
    return video_output_dir(video_id) / "clips" / clip_id


def resolve_path(path: Optional[str]) -> Optional[Path]:
    """Absolute filesystem path for a stored media path (relative or absolute)."""
    if not path:
        return None
    p = Path(path)
    if p.is_absolute():
        return p
    parts = p.parts
    # Legacy rows: "outputs/<vid>/..." relative to the app's cwd.
    if parts and parts[0] == "outputs":
        return Path(OUTPUT_DIR).joinpath(*parts[1:])
    if parts and parts[0] == "uploads":
        return Path(UPLOAD_DIR).joinpath(*parts[1:])
    return (Path.cwd() / p)


def public_url(path: Optional[str]) -> Optional[str]:
    """Browser URL for a stored media path, or None if it isn't servable."""
    p = resolve_path(path)
    if p is None:
        return None
    for root, mount in ((Path(OUTPUT_DIR), "/api/files/outputs"), (Path(UPLOAD_DIR), "/api/files/uploads")):
        try:
            rel = p.resolve().relative_to(root.resolve())
            return f"{mount}/{rel.as_posix()}"
        except ValueError:
            continue
    return None
