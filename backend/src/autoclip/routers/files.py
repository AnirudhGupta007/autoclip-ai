"""Authorised media access — replaces the old public /uploads and /outputs mounts.

GET /api/files/{kind}/{video_id}/...   kind = uploads | outputs

Every media file lives under UPLOAD_DIR/<video_id>/ or OUTPUT_DIR/<video_id>/,
so the first path segment is the owning video: we check the caller owns it
(404 otherwise), then either
  • answer with `X-Accel-Redirect: /_protected/<kind>/<path>` so nginx streams
    the file itself from a read-only, `internal` location (Range requests /
    seeking work, Python never touches the bytes) — FILES_ACCEL_REDIRECT=1, or
  • stream it with FileResponse (dev without nginx).
"""
from __future__ import annotations
import mimetypes
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from autoclip.auth import settings
from autoclip.auth.deps import current_user, get_owned_video
from autoclip.config import OUTPUT_DIR, UPLOAD_DIR
from autoclip.database import get_db
from autoclip.models import User

router = APIRouter(prefix="/api/files", tags=["files"], dependencies=[Depends(current_user)])

ROOTS = {"uploads": Path(UPLOAD_DIR), "outputs": Path(OUTPUT_DIR)}


def _locate(path: Path) -> Optional[tuple[str, str]]:
    """(kind, relative posix path) for a file under one of the media roots."""
    rp = path.resolve()
    for kind, root in ROOTS.items():
        try:
            return kind, rp.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return None


def send_media(path: Path, filename: Optional[str] = None, media_type: Optional[str] = None) -> Response:
    """Serve an (already authorised) media file — via nginx when configured."""
    media_type = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    loc = _locate(path)
    if settings.FILES_ACCEL_REDIRECT and loc:
        kind, rel = loc
        headers = {
            "X-Accel-Redirect": f"{settings.FILES_ACCEL_PREFIX}/{kind}/{quote(rel)}",
            "Cache-Control": "private, max-age=3600",
        }
        if filename:
            headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        return Response(status_code=200, headers=headers, media_type=media_type)
    resp = FileResponse(str(path), filename=filename, media_type=media_type)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@router.get("/{kind}/{file_path:path}")
def get_file(kind: str, file_path: str, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    root = ROOTS.get(kind)
    parts = [p for p in file_path.split("/") if p]
    if root is None or len(parts) < 2 or any(p in (".", "..") for p in parts):
        raise HTTPException(404, "File not found")
    video = get_owned_video(db, user, parts[0])
    base = (root / video.id).resolve()
    target = (root / Path(*parts)).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(404, "File not found")
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return send_media(target)
