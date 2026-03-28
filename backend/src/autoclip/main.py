"""FastAPI application entry point."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from autoclip.database import init_db
from autoclip.config import UPLOAD_DIR, OUTPUT_DIR
from autoclip.routers import videos, clips, music
from autoclip.routers.chat import router as chat_router

app = FastAPI(
    title="AutoClip AI",
    description="Conversational AI-powered video clipping with multimodal analysis",
    version="2.0.0",
)

cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chat interface (primary)
app.include_router(chat_router)

# REST endpoints
app.include_router(videos.router)
app.include_router(clips.router)
app.include_router(music.router)

# Serve uploaded and output files
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "AutoClip AI", "version": "2.0.0"}
