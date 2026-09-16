"""Live cost/latency benchmark — run this once you have real API access.

Not run in the sandbox this rewrite was built in (no internet access there).
Uploads a sample video, drives one chat turn through the real running
backend's HTTP API, times each phase, reads /api/telemetry for per-model
token usage, and appends a timestamped entry to BENCHMARKS.md — so the
README's cost/latency numbers come from an actual run, not a guess.

Usage:
    python backend/scripts/benchmark.py --video path/to/sample.mp4 \\
        --base-url http://localhost:8000 \\
        --message "give me 3 funny clips under 20 seconds"
"""
from __future__ import annotations
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="Path to a sample video file")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--message", default="give me 3 funny clips under 20 seconds")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "BENCHMARKS.md"))
    args = ap.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=600.0)

    health = client.get("/api/health")
    health.raise_for_status()
    print("health:", health.json())

    t0 = time.time()
    with open(args.video, "rb") as f:
        upload = client.post("/api/videos/upload", files={"file": f})
    upload.raise_for_status()
    video = upload.json()
    video_id = video["id"]
    t_upload = time.time() - t0
    print(f"uploaded video_id={video_id} in {t_upload:.1f}s")

    t1 = time.time()
    chat = client.post("/api/chat/message", json={"message": args.message, "video_id": video_id})
    chat.raise_for_status()
    chat_data = chat.json()
    t_chat = time.time() - t1
    print(f"chat turn completed in {t_chat:.1f}s")
    print("response:", chat_data.get("response"))
    print("clips:", len(chat_data.get("clips") or []))

    telemetry = client.get("/api/telemetry")
    telemetry.raise_for_status()
    telemetry_data = telemetry.json()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "video": args.video,
        "message": args.message,
        "upload_seconds": round(t_upload, 2),
        "chat_turn_seconds": round(t_chat, 2),
        "clips_produced": len(chat_data.get("clips") or []),
        "telemetry": telemetry_data,
    }

    out_path = Path(args.out)
    header = "# AutoClip AI — Live Benchmarks\n\nAppended by `backend/scripts/benchmark.py`. Each entry is one real run against a real backend + OpenRouter account.\n\n"
    block = (
        f"## {entry['timestamp']}\n\n"
        f"- video: `{entry['video']}`\n"
        f"- message: `{entry['message']}`\n"
        f"- upload: {entry['upload_seconds']}s\n"
        f"- chat turn (analysis + selection + production): {entry['chat_turn_seconds']}s\n"
        f"- clips produced: {entry['clips_produced']}\n"
        f"- telemetry:\n\n```json\n{json.dumps(entry['telemetry'], indent=2)}\n```\n\n"
    )

    if not out_path.exists():
        out_path.write_text(header + block)
    else:
        with open(out_path, "a") as f:
            f.write(block)

    print(f"\nAppended benchmark entry to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
