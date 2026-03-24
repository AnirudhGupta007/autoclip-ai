# AutoClip AI

**Conversational AI video clipping with multimodal LangGraph pipeline.**

Upload a long-form video, tell the AI what you want in plain English, and get short-form viral clips back — optimized for TikTok, Instagram Reels, and YouTube Shorts.

```
You:  "Give me 4 funny TikTok clips under 30 seconds"
AI:   Analyzing video with 3 parallel agents...
      Found 4 clips:
      [1] "The Database Was a Spreadsheet" — 28s — 9:16 — score 8.9/10
      [2] "Nobody Told the CEO" — 24s — 9:16 — score 8.4/10
      ...

You:  "Make clip 2 longer and give me clip 1 in square format"
AI:   Done. Updated clip 2 to 42s. Exported clip 1 in 1:1.
```

No complex UI. No manual editing timeline. Just chat.

---

## How It Works

### Multimodal Analysis Pipeline

The system doesn't just read the transcript — it **sees**, **hears**, and **reads** the video simultaneously using three parallel agents:

```
Video Input
    │
    ▼
┌────────────────┐
│ Classifier     │ ← Gemini Vision: "what type of video is this?"
│ (conditional)  │   → talking_head / presentation / podcast / mixed
└───────┬────────┘
        │
        ▼ routes to appropriate agents
┌──────────────────────────────────────────┐
│         PARALLEL ANALYSIS                 │
│                                           │
│  Visual Agent     Audio Agent    Text     │
│  (Gemini Vision)  (librosa)     Agent    │
│                                 (Gemini)  │
│  Frames → energy  RMS, onset   Hooks,    │
│  emotion, scenes  pace, events  stories   │
└──────────┬────────────┬──────────┬───────┘
           └────────────┼──────────┘
                        ▼
              ┌──────────────────┐
              │  TEMPORAL FUSION  │
              │                   │
              │  Aligns 3 timelines
              │  finds moments where
              │  2+ modalities spike
              │  together            │
              └─────────┬────────┘
                        ▼
              ┌──────────────────┐
              │  CLIP SELECTOR   │ ← filtered by user preferences
              │  + PRODUCTION    │   (style, length, count, format)
              └──────────────────┘
```

### Why Multimodal Beats Text-Only

A text-only system would miss:
- The speaker slamming the table (visual energy)
- The audience gasping (audio onset detection)
- A dramatic pause before the punchline (audio silence → speech)
- The speaker's facial expression changing (visual emotion)

When visual energy, audio excitement, and a text hook all converge on the same timestamp — that's a high-confidence viral moment.

---

## Tech Stack

| Component | Technology |
|---|---|
| **Pipeline Orchestration** | [LangGraph](https://github.com/langchain-ai/langgraph) — StateGraph with subgraphs, conditional routing, checkpointing |
| **LLM / Vision** | Google Gemini 2.0 Flash — multimodal analysis (frames + text) |
| **Transcription** | AssemblyAI — word-level timestamps + speaker diarization |
| **Audio Analysis** | librosa — RMS, spectral centroid, onset detection, tempo, ZCR |
| **Scene Detection** | PySceneDetect — content-based scene boundaries |
| **Video Processing** | FFmpeg — cutting, captioning (ASS format), reframing, thumbnails |
| **API** | FastAPI — async endpoints, SSE streaming |
| **Frontend** | React + Vite + Tailwind — minimal chat interface |
| **Database** | SQLAlchemy + SQLite |
| **Packaging** | `uv` + `pyproject.toml` — modern Python packaging |

### LangGraph Features Used

- **StateGraph** with typed state + annotated reducers (`operator.add`)
- **Subgraphs** — analysis and generation as compiled sub-pipelines
- **Conditional edges** — video-type routing, analysis skip, early termination
- **ToolNode** — FFmpeg operations as LangChain tools
- **MemorySaver checkpointing** — state persists across chat turns
- **Pydantic structured output** — type-safe LLM responses

---

## Project Structure

```
autoclip-ai/
├── architecture.md                    # Detailed system design doc
├── backend/
│   ├── pyproject.toml                 # uv-compatible dependencies
│   ├── src/autoclip/
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── config.py                  # Environment variables
│   │   ├── database.py               # SQLAlchemy setup
│   │   ├── models.py                 # Video + Clip ORM models
│   │   ├── pipeline/
│   │   │   ├── state.py              # Typed state + Pydantic models
│   │   │   ├── graph.py              # LangGraph pipeline definition
│   │   │   ├── chat.py               # Intent parsing + response gen
│   │   │   ├── tools.py              # LangChain tool definitions
│   │   │   └── agents/
│   │   │       ├── classifier.py     # Video type classification
│   │   │       ├── visual_agent.py   # Two-pass frame analysis
│   │   │       ├── audio_agent.py    # 8-feature audio extraction
│   │   │       ├── text_agent.py     # Hook detection + arc analysis
│   │   │       ├── fusion.py         # Cross-modal convergence
│   │   │       ├── clip_selector.py  # User-preference filtering
│   │   │       └── production.py     # FFmpeg clip production
│   │   ├── routers/                   # FastAPI endpoints
│   │   ├── services/                  # Transcription, captions, etc.
│   │   └── utils/                     # FFmpeg, subtitle helpers
│   └── tests/
│       ├── test_state.py
│       ├── test_fusion.py
│       ├── test_graph.py
│       ├── test_chat.py
│       └── test_e2e.py               # End-to-end pipeline tests
└── frontend/
    └── src/
        ├── pages/Chat.jsx             # Chat interface
        ├── components/                # UI components
        └── services/api.js            # API client
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- FFmpeg installed and on PATH
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### API Keys

You'll need:
- [Google Gemini API key](https://ai.google.dev/)
- [AssemblyAI API key](https://www.assemblyai.com/)

### Setup

```bash
# Clone
git clone https://github.com/AnirudhGupta007/autoclip-ai.git
cd autoclip-ai

# Backend
cd backend
cp ../.env.example .env        # Add your API keys
uv sync                        # or: pip install -e ".[dev]"
uv run uvicorn autoclip.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` — upload a video and start chatting.

### Run Tests

```bash
cd backend
uv run pytest tests/ -v        # 69 tests, no API keys needed
```

---

## Pipeline Deep Dive

See **[architecture.md](architecture.md)** for the full system design, including:

- Main graph with conditional entry (analysis vs regeneration)
- Analysis subgraph with fan-out/fan-in agent pattern
- Two-pass visual sampling strategy
- Audio feature extraction (8 librosa features)
- Text hook detection with regex pre-scan + LLM + narrative arc detection
- Temporal fusion convergence algorithm
- State schema with annotated reducers

---

## User Controls

Everything is controlled through natural language:

| What You Say | What Happens |
|---|---|
| "4 funny TikToks under 30s" | 4 clips, funny style, 9:16, ≤30s each |
| "3 educational clips for YouTube" | 3 clips, educational, 16:9 |
| "make clip 2 longer" | Extends clip 2 by ~15s |
| "change clip 1 to square" | Re-exports clip 1 in 1:1 |
| "find me something dramatic" | Filters moment map for dramatic content |
| "what moments did you find?" | Shows top moments with convergence scores |
| "download all" | Download links for all clips |

The video is analyzed **once**. Follow-up requests reuse the cached moment map — fast regeneration without re-analyzing.

---

## License

MIT
