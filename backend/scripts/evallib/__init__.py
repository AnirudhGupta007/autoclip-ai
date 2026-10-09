"""Evaluation library for AutoClip AI movie-level evals.

- metrics: pure scoring functions (no I/O) — unit-tested in backend/tests/test_evallib.py
- probe:   ffprobe/ffmpeg helpers (host ffmpeg or `docker exec` into the backend)
- client:  thin urllib client for the AutoClip HTTP API + OpenRouter credits
- report:  markdown / csv rendering
"""
