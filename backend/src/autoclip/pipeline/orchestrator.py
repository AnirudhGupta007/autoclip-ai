"""Pipeline orchestrator — runs all 5 stages and yields SSE events."""
import json
import asyncio
from pathlib import Path
from autoclip.config import UPLOAD_DIR, OUTPUT_DIR
from autoclip.database import SessionLocal
from autoclip.models import Video, Clip, generate_id
from autoclip.utils.ffmpeg import extract_audio, get_video_info
from autoclip.services.transcription import transcribe_audio
from autoclip.services.scene_detector import detect_scenes
from autoclip.services.analysis import chunk_transcript, score_chunk
from autoclip.services.video_processor import cut_clip
from autoclip.services.caption_engine import generate_captions
from autoclip.services.thumbnail_gen import generate_thumbnail


def _sse_event(event: str, data: dict) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _progress(stage: int, stage_name: str, progress: int, message: str) -> str:
    return _sse_event("progress", {
        "stage": stage,
        "stage_name": stage_name,
        "progress": progress,
        "message": message,
    })


async def run_pipeline(video_id: str):
    """
    Generator that runs all 5 pipeline stages and yields SSE event strings.
    """
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            yield _sse_event("error", {"message": "Video not found"})
            return

        video.status = "processing"
        db.commit()

        video_path = video.file_path
        video_dir = OUTPUT_DIR / video_id
        video_dir.mkdir(parents=True, exist_ok=True)

        # ============ STAGE 1: Transcription ============
        yield _progress(1, "Transcription", 0, "Extracting audio...")

        audio_path = str(video_dir / "audio.wav")
        await asyncio.to_thread(extract_audio, video_path, audio_path)
        yield _progress(1, "Transcription", 30, "Transcribing with AssemblyAI...")

        transcript_data = await asyncio.to_thread(transcribe_audio, audio_path)
        words = transcript_data["words"]
        utterances = transcript_data["utterances"]

        # Save transcript
        transcript_file = video_dir / "transcript.json"
        with open(transcript_file, "w") as f:
            json.dump(transcript_data, f, indent=2)

        yield _progress(1, "Transcription", 100, f"Transcribed {len(words)} words")

        # ============ STAGE 2: Scene Analysis ============
        yield _progress(2, "Scene Analysis", 0, "Detecting scenes...")

        scenes = await asyncio.to_thread(detect_scenes, video_path)
        scene_file = video_dir / "scenes.json"
        with open(scene_file, "w") as f:
            json.dump(scenes, f, indent=2)

        yield _progress(2, "Scene Analysis", 100, f"Found {len(scenes)} scenes")

        # ============ STAGE 3: LLM Chunking ============
        yield _progress(3, "AI Chunking", 0, "Identifying viral segments...")

        # Use utterances if available, else create from transcript
        if not utterances:
            utterances = [{"speaker": "A", "text": transcript_data["text"], "start": 0, "end": 9999}]

        chunks = await asyncio.to_thread(chunk_transcript, transcript_data["text"], utterances)

        yield _progress(3, "AI Chunking", 100, f"Found {len(chunks)} potential clips")

        # ============ STAGE 4: Engagement Scoring ============
        yield _progress(4, "Scoring", 0, "Scoring clips for engagement...")

        scored_chunks = []
        for i, chunk in enumerate(chunks):
            # Build chunk text from utterances
            start_line = chunk["start_line"]
            end_line = chunk["end_line"]
            chunk_utterances = utterances[start_line:end_line + 1]
            chunk_text = " ".join(u["text"] for u in chunk_utterances)

            chunk_start = chunk_utterances[0]["start"] if chunk_utterances else 0
            chunk_end = chunk_utterances[-1]["end"] if chunk_utterances else 0

            scores = await asyncio.to_thread(score_chunk, chunk_text, chunk["title"])

            scored_chunks.append({
                **chunk,
                "text": chunk_text,
                "start_time": chunk_start,
                "end_time": chunk_end,
                "scores": scores,
                "overall_score": scores.get("overall", 5.0),
            })

            progress = int((i + 1) / len(chunks) * 100)
            yield _progress(4, "Scoring", progress, f"Scored {i + 1}/{len(chunks)} clips")

        # Sort by score, take top clips
        scored_chunks.sort(key=lambda c: c["overall_score"], reverse=True)
        top_chunks = scored_chunks[:6]  # Max 6 clips

        # Refine timestamps using word-level data
        for chunk in top_chunks:
            chunk_words = [
                w for w in words
                if w["start"] >= chunk["start_time"] - 0.5
                and w["end"] <= chunk["end_time"] + 0.5
            ]
            if chunk_words:
                chunk["start_time"] = chunk_words[0]["start"]
                chunk["end_time"] = chunk_words[-1]["end"]

        yield _progress(4, "Scoring", 100, f"Selected top {len(top_chunks)} clips")

        # ============ STAGE 5: Production ============
        yield _progress(5, "Production", 0, "Producing clips...")

        created_clips = []
        for i, chunk in enumerate(top_chunks):
            clip_id = generate_id()
            clip_dir = video_dir / "clips" / clip_id
            clip_dir.mkdir(parents=True, exist_ok=True)

            # Cut video segment
            raw_path = str(clip_dir / "raw.mp4")
            await asyncio.to_thread(
                cut_clip, video_path, raw_path,
                chunk["start_time"], chunk["end_time"]
            )

            # Generate captions
            ass_path = str(clip_dir / "captions.ass")
            await asyncio.to_thread(
                generate_captions,
                words, chunk["start_time"], chunk["end_time"],
                "bold_pop", ass_path
            )

            # Burn captions onto video
            final_path = str(clip_dir / "final.mp4")
            try:
                from autoclip.utils.ffmpeg import burn_captions
                await asyncio.to_thread(burn_captions, raw_path, ass_path, final_path)
            except Exception:
                # If caption burning fails, use raw clip
                import shutil
                shutil.copy2(raw_path, final_path)

            # Generate thumbnail
            thumb_path = str(clip_dir / "thumbnail.jpg")
            try:
                await asyncio.to_thread(
                    generate_thumbnail, final_path, thumb_path, chunk["title"]
                )
            except Exception:
                thumb_path = None

            # Save to database
            duration = chunk["end_time"] - chunk["start_time"]
            clip = Clip(
                id=clip_id,
                video_id=video_id,
                title=chunk["title"],
                start_time=chunk["start_time"],
                end_time=chunk["end_time"],
                duration=round(duration, 2),
                file_path=final_path,
                thumbnail_path=thumb_path,
                transcript=chunk.get("text", ""),
                scores=chunk["scores"],
                overall_score=chunk["overall_score"],
                caption_style="bold_pop",
                caption_file=ass_path,
            )
            db.add(clip)
            created_clips.append(clip_id)

            progress = int((i + 1) / len(top_chunks) * 100)
            yield _progress(5, "Production", progress,
                          f"Produced clip {i + 1}/{len(top_chunks)}: {chunk['title']}")

        db.commit()

        # Update video status
        video.status = "completed"
        db.commit()

        yield _sse_event("complete", {
            "video_id": video_id,
            "clips_count": len(created_clips),
            "clip_ids": created_clips,
        })

    except Exception as e:
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.status = "failed"
            db.commit()
        yield _sse_event("error", {"message": str(e)})

    finally:
        db.close()
