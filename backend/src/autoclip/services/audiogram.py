"""Audio upload -> audiogram mp4.

Audio-only podcasts are turned into a video at upload so everything
downstream (transcription, chunking, fusion, rendering, thumbnails) runs
unchanged. Two steps, split for speed:

  1. Upload (`make_audiogram`, one ffmpeg pass): a static 720x720 title
     card — black background, the episode title in platinum — at 1 fps,
     muxed with the audio. The audio is stream-copied when it is already
     AAC/MP3 (m4a/aac/mp3 uploads) and only re-encoded otherwise.
  2. Clip render (`waveform_filter`, used by utils/ffmpeg.render_clip):
     the animated gold `showwaves` waveform is drawn at the output
     resolution, so clips come out as captioned audiograms.

Why not animate the whole episode at upload: measured on a 58-min episode
at 2 CPUs (the t3a.small), a full-length animated pass took 517s / 143MB
(the backend sits behind nginx's 600s proxy timeout) and the native AAC
encoder alone took 307s; card + stream copy is ~25s / ~60MB.

Layout: the title sits inside the centre 405x405 square, which survives
both a centred 9:16 crop (405 wide) and a 16:9 crop (405 tall) in
production.py (no faces -> centred crop). The original audio file is
deleted afterwards.
"""
from __future__ import annotations
import json
import logging
import subprocess
import textwrap
from pathlib import Path

from autoclip.utils.paths import video_output_dir

logger = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"}
COPY_CODECS = {"aac", "mp3"}   # playable inside mp4 as-is
SIZE = 720
GOLD, PLATINUM = "#D4AF7A", "0xF5F3EF"   # showwaves misreads 0x colours (came out purple)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TITLE_CHARS, TITLE_LINES = 20, 2


def title_lines(filename: str) -> str:
    """Episode title from the upload's filename, wrapped to fit the safe square."""
    stem = Path(filename or "").stem.replace("_", " ").replace("-", " ").strip() or "Podcast"
    lines = textwrap.wrap(" ".join(stem.split()), TITLE_CHARS)
    if len(lines) > TITLE_LINES:
        lines = lines[:TITLE_LINES]
        lines[-1] = lines[-1][: TITLE_CHARS - 1].rstrip() + "…"
    return "\n".join(lines)


def audio_codec(path: str) -> str:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=codec_name", "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True)
    return (out.stdout or "").strip().lower()


def audiogram_cmd(audio_path: str, out_path: str, title_file: str, duration: float,
                  copy_audio: bool) -> list[str]:
    text = (f"drawtext=fontfile={FONT}:textfile={title_file}:expansion=none:fontcolor={PLATINUM}"
            f":fontsize=24:line_spacing=8:x=(w-text_w)/2:y=200,format=yuv420p")
    audio = ["-c:a", "copy"] if copy_audio else ["-c:a", "aac", "-b:a", "96k", "-ac", "1"]
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s={SIZE}x{SIZE}:r=1",
        "-i", audio_path,
        "-t", f"{duration:.3f}", "-vf", text,
        "-map", "0:v", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "30", "-g", "2",
        *audio, "-movflags", "+faststart", out_path,
    ]


def waveform_filter(width: int, height: int, fps: int = 30) -> str:
    """filter_complex fragment: [0:a] -> gold waveform [wave], width x height/6."""
    h = max(32, (height // 6) // 2 * 2)
    return (f"[0:a]aformat=channel_layouts=mono,showwaves=s={width}x{h}:mode=cline:rate={fps}"
            f":colors={GOLD}:scale=cbrt:draw=full,format=yuva420p[wave]")


def seed_profile(video_id: str, duration: float) -> None:
    """Pre-write the per-video profile (utils/video_profile.py) for an
    audiogram: the black card would otherwise read as letterbox bars and as
    end credits. media_kind tells production to draw the waveform."""
    d = video_output_dir(video_id)
    d.mkdir(parents=True, exist_ok=True)
    from autoclip.utils.video_profile import PROFILE_VERSION
    (d / "profile.json").write_text(json.dumps({
        "version": PROFILE_VERSION, "width": SIZE, "height": SIZE, "duration": duration,
        "letterbox": None, "credits_start": None, "media_kind": "audio",
    }, indent=2))


def make_audiogram(audio_path: str, out_path: str, filename: str, video_id: str,
                   duration: float, timeout: int = 900) -> str:
    """Write the title-card audiogram for `audio_path` to `out_path`; deletes
    the audio file on success. Raises RuntimeError if ffmpeg fails."""
    title_file = Path(out_path).with_name("title.txt")
    title_file.write_text(title_lines(filename))
    copy_audio = audio_codec(audio_path) in COPY_CODECS
    try:
        res = subprocess.run(audiogram_cmd(audio_path, out_path, str(title_file), duration, copy_audio),
                             capture_output=True, text=True, timeout=timeout)
    finally:
        title_file.unlink(missing_ok=True)
    if res.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(f"audiogram encode failed: {(res.stderr or '')[-400:]}")
    Path(audio_path).unlink(missing_ok=True)
    logger.info("audiogram %s: %s -> %s (audio %s)", video_id, Path(audio_path).name,
                Path(out_path).name, "copied" if copy_audio else "re-encoded")
    return out_path
