"""Chat router — conversational interface for the video clipping pipeline."""
import json
import asyncio
from dataclasses import asdict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models import Video, Clip, generate_id
from app.pipeline.chat import parse_user_intent, intent_to_clip_configs, generate_chat_response
from app.pipeline.graph import analysis_pipeline, generation_pipeline
from app.pipeline.state import PipelineState, ClipConfig

router = APIRouter(prefix="/api/chat", tags=["chat"])

# In-memory store for analysis state per video (in production, use Redis)
_analysis_cache: dict[str, dict] = {}


class ChatMessage(BaseModel):
    message: str
    video_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    intent: str
    clips: Optional[list[dict]] = None
    moment_count: Optional[int] = None
    is_processing: bool = False


def _clip_to_dict(clip) -> dict:
    """Convert a ProducedClip or Clip model to dict."""
    if hasattr(clip, "__dict__"):
        d = {}
        for k in ["id", "title", "start_time", "end_time", "duration",
                   "file_path", "thumbnail_path", "transcript", "scores",
                   "overall_score", "frame", "style_tags"]:
            d[k] = getattr(clip, k, None)
        # Convert file paths to URLs
        if d.get("file_path"):
            d["file_url"] = "/" + d["file_path"].replace("\\", "/")
        if d.get("thumbnail_path"):
            d["thumbnail_url"] = "/" + d["thumbnail_path"].replace("\\", "/")
        return d
    return clip


@router.post("/message", response_model=ChatResponse)
async def chat_message(msg: ChatMessage, db: Session = Depends(get_db)):
    """
    Process a chat message and return a response.
    This is the main interface — users send natural language, get clips back.
    """
    video_id = msg.video_id
    message = msg.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Check if we have a video
    video = None
    if video_id:
        video = db.query(Video).filter(Video.id == video_id).first()

    has_video = video is not None
    has_analysis = video_id in _analysis_cache and _analysis_cache[video_id].get("analysis_complete")
    has_clips = video_id in _analysis_cache and bool(_analysis_cache[video_id].get("clips"))

    # Parse intent
    intent_result = await asyncio.to_thread(
        parse_user_intent, message, has_video, has_analysis, has_clips
    )
    intent = intent_result.get("intent", "ask_question")
    params = intent_result.get("params", {})

    # Handle greeting
    if intent == "greeting":
        response_text = generate_chat_response(intent, params)
        return ChatResponse(response=response_text, intent=intent)

    # Handle generate_clips
    if intent == "generate_clips":
        if not video:
            return ChatResponse(
                response="Please upload a video first, then tell me what clips you want!",
                intent=intent,
            )

        clip_configs = intent_to_clip_configs(params)

        # Check if analysis exists
        if has_analysis:
            # Reuse existing analysis, just generate new clips
            cached = _analysis_cache[video_id]
            state = {
                **cached,
                "clip_configs": clip_configs,
            }
            result = await asyncio.to_thread(generation_pipeline.invoke, state)
        else:
            # Run full analysis + generation
            state: PipelineState = {
                "video_id": video_id,
                "video_path": video.file_path,
                "clip_configs": clip_configs,
                "analysis_complete": False,
                "needs_reanalysis": False,
            }

            # Update video status
            video.status = "processing"
            db.commit()

            try:
                result = await asyncio.to_thread(analysis_pipeline.invoke, state)
            except Exception as e:
                video.status = "failed"
                db.commit()
                return ChatResponse(
                    response=f"Analysis failed: {str(e)}. Please try again.",
                    intent=intent,
                )

            video.status = "completed"
            db.commit()

        # Cache analysis results
        _analysis_cache[video_id] = {
            "video_id": video_id,
            "video_path": video.file_path,
            "video_type": result.get("video_type", "mixed"),
            "visual_timeline": result.get("visual_timeline", []),
            "audio_timeline": result.get("audio_timeline", []),
            "text_segments": result.get("text_segments", []),
            "moment_map": result.get("moment_map", []),
            "scene_boundaries": result.get("scene_boundaries", []),
            "transcript_data": result.get("transcript_data", {}),
            "analysis_complete": True,
            "clips": result.get("clips", []),
        }

        clips = result.get("clips", [])

        # Save clips to database
        for clip in clips:
            db_clip = Clip(
                id=clip.id,
                video_id=video_id,
                title=clip.title,
                start_time=clip.start_time,
                end_time=clip.end_time,
                duration=clip.duration,
                file_path=clip.file_path,
                thumbnail_path=clip.thumbnail_path,
                transcript=clip.transcript,
                scores=clip.scores,
                overall_score=clip.overall_score,
                caption_style="bold_pop",
            )
            db.add(db_clip)
        db.commit()

        clip_dicts = [_clip_to_dict(c) for c in clips]
        response_text = generate_chat_response(intent, params, clips=clips)
        moment_count = len(result.get("moment_map", []))

        return ChatResponse(
            response=response_text,
            intent=intent,
            clips=clip_dicts,
            moment_count=moment_count,
        )

    # Handle modify_clip
    if intent == "modify_clip":
        if not has_clips:
            return ChatResponse(
                response="Generate some clips first! Tell me what you want, like '4 funny TikTok clips'.",
                intent=intent,
            )

        cached = _analysis_cache[video_id]
        clips = cached.get("clips", [])
        clip_index = params.get("clip_index", 1) - 1
        action = params.get("action", "")

        if clip_index < 0 or clip_index >= len(clips):
            return ChatResponse(
                response=f"I only have {len(clips)} clips. Pick a number between 1 and {len(clips)}.",
                intent=intent,
            )

        # Create modified config
        old_clip = clips[clip_index]
        new_config = ClipConfig(
            moment=old_clip.start_time if action != "different_moment" else None,
            length=params.get("new_length", int(old_clip.duration)),
            style="any",
            frame=params.get("new_frame", old_clip.frame),
        )

        if action == "shorten":
            new_config.length = max(15, int(old_clip.duration - 15))
        elif action == "lengthen":
            new_config.length = min(90, int(old_clip.duration + 15))

        # Re-generate just this clip
        gen_state = {
            **cached,
            "clip_configs": [new_config],
        }
        result = await asyncio.to_thread(generation_pipeline.invoke, gen_state)

        new_clips = result.get("clips", [])
        if new_clips:
            clips[clip_index] = new_clips[0]
            cached["clips"] = clips

            # Update in database
            db_clip = db.query(Clip).filter(Clip.id == old_clip.id).first()
            if db_clip:
                db.delete(db_clip)
            new_c = new_clips[0]
            db_clip = Clip(
                id=new_c.id,
                video_id=video_id,
                title=new_c.title,
                start_time=new_c.start_time,
                end_time=new_c.end_time,
                duration=new_c.duration,
                file_path=new_c.file_path,
                thumbnail_path=new_c.thumbnail_path,
                transcript=new_c.transcript,
                scores=new_c.scores,
                overall_score=new_c.overall_score,
                caption_style="bold_pop",
            )
            db.add(db_clip)
            db.commit()

        clip_dicts = [_clip_to_dict(c) for c in clips]
        response_text = generate_chat_response(intent, params, clips=clips)

        return ChatResponse(
            response=response_text,
            intent=intent,
            clips=clip_dicts,
        )

    # Handle ask_question
    if intent == "ask_question":
        moment_map = []
        if video_id and video_id in _analysis_cache:
            moment_map = _analysis_cache[video_id].get("moment_map", [])

        response_text = generate_chat_response(intent, params, moment_map=moment_map)
        return ChatResponse(response=response_text, intent=intent)

    # Handle export
    if intent == "export":
        clips = []
        if video_id and video_id in _analysis_cache:
            clips = _analysis_cache[video_id].get("clips", [])

        clip_dicts = [_clip_to_dict(c) for c in clips]
        response_text = generate_chat_response(intent, params, clips=clips)

        return ChatResponse(
            response=response_text,
            intent=intent,
            clips=clip_dicts,
        )

    # Fallback
    response_text = generate_chat_response(intent, params)
    return ChatResponse(response=response_text, intent=intent)


@router.get("/analysis/{video_id}")
async def get_analysis_status(video_id: str):
    """Check if analysis is cached for a video."""
    cached = _analysis_cache.get(video_id)
    if not cached:
        return {"analyzed": False, "moment_count": 0}

    return {
        "analyzed": cached.get("analysis_complete", False),
        "video_type": cached.get("video_type", "unknown"),
        "moment_count": len(cached.get("moment_map", [])),
        "clips_count": len(cached.get("clips", [])),
    }
