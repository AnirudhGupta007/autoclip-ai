"""FastAPI application entry point."""
import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from autoclip.database import init_db
from autoclip.auth import settings as auth_settings
from autoclip.auth.deps import require_admin
from autoclip.auth.origin import OriginCheckMiddleware
from autoclip.routers import videos, clips, music, files
from autoclip.routers.account import router as account_router
from autoclip.routers.auth import router as auth_router
from autoclip.routers.chat import router as chat_router
from autoclip.routers.conversations import router as conversations_router
from autoclip.routers.search import router as search_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    cleanup = None
    if auth_settings.CLEANUP_ENABLED:
        # Nightly storage cleanup (services/storage.py); a Redis key makes it
        # run once a day however many workers start this loop.
        from autoclip.services.storage import cleanup_loop
        cleanup = asyncio.create_task(cleanup_loop(), name="storage-cleanup")
    try:
        yield
    finally:
        if cleanup is not None:
            cleanup.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup


app = FastAPI(
    title="AutoClip AI",
    description="Conversational AI-powered video clipping with multimodal analysis",
    version="2.0.0",
    lifespan=lifespan,
)

# Explicit allow-list — never "*" with credentials (cookies).
app.add_middleware(
    CORSMiddleware,
    allow_origins=auth_settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.add_middleware(OriginCheckMiddleware)

# Auth (the only public API besides /api/health)
app.include_router(auth_router)

# Chat interface (primary)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(account_router)

# REST endpoints — all require a session and are scoped to the caller's data
app.include_router(videos.router)
app.include_router(clips.router)
app.include_router(music.router)
app.include_router(search_router)
# Media: ownership-checked replacement for the old public /uploads, /outputs mounts
app.include_router(files.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "AutoClip AI", "version": "2.0.0"}


@app.get("/api/telemetry", dependencies=[Depends(require_admin)])
def telemetry():
    """Lightweight rollup of OpenRouter calls + cache hit rate, per model_label (admins only)."""
    from autoclip.pipeline import telemetry as t
    return {
        model: {
            "calls": s.calls,
            "prompt_tokens": s.prompt_tokens,
            "cached_tokens": s.cached_tokens,
            "output_tokens": s.output_tokens,
            "cache_hit_rate": round(s.cache_hit_rate, 4),
        }
        for model, s in t.snapshot().items()
    }
