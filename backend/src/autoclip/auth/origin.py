"""CSRF backstop: reject state-changing requests from foreign Origins.

SameSite=Lax already keeps the session cookie off cross-site POSTs; this
also blocks them explicitly. Requests without an Origin header (curl, the
eval client, same-origin GETs) pass — browsers always send Origin on
cross-origin POST/PUT/PATCH/DELETE.
"""
from __future__ import annotations
import json
from urllib.parse import urlsplit

from autoclip.auth import settings

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _hostname(netloc: str) -> str:
    return (urlsplit(f"//{netloc}").hostname or "").lower()


class OriginCheckMiddleware:
    def __init__(self, app, allowed_origins: list[str] | None = None):
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in (allowed_origins or settings.ALLOWED_ORIGINS)}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in UNSAFE:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            origin = headers.get("origin")
            if origin and not self._ok(origin, headers.get("host", "")):
                body = json.dumps({"detail": "Cross-origin request blocked"}).encode()
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)

    def _ok(self, origin: str, host: str) -> bool:
        origin = origin.rstrip("/").lower()
        if origin in self.allowed:
            return True
        if origin == "null":
            return False
        # Same-origin. nginx forwards Host without the port, so compare hostnames.
        return bool(host) and urlsplit(origin).hostname == _hostname(host)
