# AutoClip AI — System Architecture

## Overview

AutoClip AI is a **conversational AI video clipping system** that uses a multimodal LangGraph pipeline to analyze long-form videos and generate short-form viral clips. Users interact through a chat interface — no complex UI, just natural language.

```
"Give me 4 funny TikTok clips under 30 seconds"
    → Multimodal Analysis (Vision + Audio + Text)
    → Cross-Modal Fusion
    → Clip Generation
    → "Here are your 4 clips"
```

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Orchestration** | LangGraph (StateGraph) | Stateful graph with conditional routing, subgraphs, checkpointing |
| **LLM** | Google Gemini 2.0 Flash | Multimodal (vision + text), large context window, structured output |
| **Transcription** | AssemblyAI | Word-level timestamps + speaker diarization |
| **Audio Analysis** | librosa | RMS, spectral centroid, onset detection, tempo, ZCR |
| **Scene Detection** | PySceneDetect | Content-based scene boundary detection |
| **Video Processing** | FFmpeg | Cutting, captioning, reframing, thumbnail generation |
| **API** | FastAPI | Async, SSE support, auto OpenAPI docs |
| **Database** | SQLAlchemy + SQLite | Lightweight persistence (swap to Postgres for production) |
| **Frontend** | React + Vite + Tailwind | Minimal chat UI |
| **Package Management** | uv + pyproject.toml | Modern Python packaging |

## Pipeline Architecture

### Main Graph (with Checkpointing)

```
START
  │
  ├── [analysis_complete?]
  │     │
  │     ├── NO → transcription → scene_detection → analysis_subgraph
  │     │         │
  │     │         └── [moments found?]
  │     │               ├── YES → generation_subgraph → END
  │     │               └── NO  → END (no interesting content)
  │     │
  │     └── YES → generation_subgraph → END (skip analysis, reuse cached state)
  │
  └── END
```

**Key LangGraph features:**
- `MemorySaver` checkpointing persists state across chat turns
- Conditional entry: `route_analysis_check()` skips analysis for regeneration requests
- Thread-based config: `{"configurable": {"thread_id": video_id}}`

### Analysis Subgraph (Parallel Fan-Out via Send API)

```
classifier_node
  │
  ├── [video_type == podcast?]
  │     │
  │     ├── YES → Send("audio_agent") ─┐
  │     │         Send("text_agent")  ─┼→ fusion → END
  │     │                              │
  │     └── NO  → Send("visual_agent")─┤
  │               Send("audio_agent") ─┤
  │               Send("text_agent")  ─┘
  │
  └── fusion (fan-in: waits for all agents) → END
```

**Parallel dispatch via Send API:** The classifier returns a list of `Send()` objects, dispatching agents concurrently rather than sequentially. LangGraph runs all dispatched agents in parallel and waits for all to complete before executing the fusion fan-in node.

**Conditional fan-out:** Podcast videos skip visual analysis (minimal visual change) — the classifier simply omits `Send("visual_agent")` from the dispatch list.

**State reducers:** Each agent writes to its own state field using `Annotated[list[T], operator.add]`, preventing overwrites during concurrent execution.

### Generation Subgraph

```
clip_selector → production → END
                    │
                    └── ToolNode(PRODUCTION_TOOLS)
                         ├── tool_cut_clip
                         ├── tool_generate_captions
                         ├── tool_burn_captions
                         ├── tool_reframe_video
                         └── tool_generate_thumbnail
```

**ToolNode integration:** FFmpeg operations are registered as LangChain tools, making them available to the production node through LangGraph's `ToolNode` pattern.

## Multimodal Agent Design

### Visual Agent (Two-Pass Strategy)

```
Pass 1 (Coarse): Sample every 2-5s → Gemini Vision batch analysis
                                      │
                                      ├── Identify high-energy regions
                                      │
Pass 2 (Dense):  Re-sample high-energy regions at 0.5-1s intervals
                                      │
                                      └── Merge → Visual Timeline
```

- Sampling rate adapts to video type (presentation = 2s, podcast = 5s)
- Batches of 10 frames sent to Gemini Vision
- Outputs: energy, emotion, emotion_confidence, scene_type, has_text_on_screen
- Two-pass avoids wasting API calls on boring sections

### Audio Agent (Feature Extraction)

Extracts 8 features per 2-second window using librosa:

| Feature | What It Detects |
|---|---|
| RMS Energy | Volume — loud = exciting |
| RMS dB | Decibel level for silence detection |
| Spectral Centroid | Brightness — high = excitement |
| Spectral Rolloff | Frequency distribution |
| Zero Crossing Rate | Noisiness — high = applause, laughter |
| Onset Strength | Transient events — emphasis, claps |
| Local Tempo | Rhythmic patterns |
| Speech Pace | Words per minute from transcript alignment |

**Event classification logic:**
```
silence:  low energy + no words
music:    moderate energy + no words + low ZCR (tonal)
laughter: high onset + few words + high ZCR (noisy)
applause: high onset + no words + very high ZCR
speech:   has words
```

### Text Agent (Semantic Segmentation)

Three-stage analysis:

1. **Regex pre-scan:** Fast pattern matching for hook indicators
   - Curiosity gaps: "you won't believe", "the truth is"
   - Hot takes: "unpopular opinion", "everyone is wrong"
   - Story openers: "so there I was", "let me tell you"

2. **LLM segmentation:** Gemini analyzes full transcript with few-shot examples
   - Classifies: hot_take, story, quote, educational, controversial, emotional, funny
   - Scores hook strength 0.0-1.0

3. **Narrative arc detection:** Post-processing that identifies setup → conflict → resolution patterns and boosts climax segments

## Temporal Fusion

The fusion node aligns three timelines to find **convergence windows** — moments where multiple modalities spike simultaneously.

```
Visual:  [----low----][HIGH 2:30-2:45][--low--][MED 4:10-4:20]
Audio:   [----low----][HIGH 2:28-2:42][--low--][----low------]
Text:    [setup......][HOOK 2:29-2:46][transition][story 4:00-4:30]
                          ↑
                   ALL THREE ALIGN = HIGH CONFIDENCE VIRAL MOMENT
```

**Convergence scoring:**
```python
convergence = visual * 0.3 + audio * 0.3 + text * 0.4
if 3 modalities active: convergence *= 1.3  # 30% bonus
if 2 modalities active: convergence *= 1.15 # 15% bonus
```

**Why this works:** A moment that's visually energetic AND has rising audio energy AND contains a hook phrase is far more likely to engage than any single signal alone.

## Chat Interface

The intent router parses natural language into structured actions:

| User Says | Intent | Params |
|---|---|---|
| "4 funny tiktoks under 30s" | generate_clips | count=4, style=funny, frame=9:16, length=30 |
| "make clip 2 longer" | modify_clip | clip_index=2, action=lengthen |
| "change clip 1 to square" | modify_clip | clip_index=1, new_frame=1:1 |
| "download all" | export | clip_index=all |
| "what moments did you find?" | ask_question | — |

**Analysis caching:** Video is analyzed once. Subsequent requests (different styles, lengths, formats) reuse the cached moment map and go straight to clip generation.

## State Schema

```python
class PipelineState(TypedDict):
    # Video
    video_id: str
    video_path: str
    video_type: Annotated[str, _replace]

    # Analysis (parallel-safe with operator.add reducer)
    visual_timeline: Annotated[list[VisualSignal], operator.add]
    audio_timeline: Annotated[list[AudioSignal], operator.add]
    text_segments: Annotated[list[TextSegment], operator.add]
    scene_boundaries: Annotated[list[float], operator.add]

    # Fusion
    moment_map: Annotated[list[Moment], _replace]
    transcript_data: Annotated[dict, _replace]

    # User request
    clip_configs: list[ClipConfig]

    # Output
    clips: Annotated[list[ProducedClip], _replace]

    # Control flow
    analysis_complete: Annotated[bool, _replace]
    needs_reanalysis: bool
    error: Optional[str]
```

## Project Structure

```
backend/
├── pyproject.toml              # uv-compatible package config
├── src/autoclip/
│   ├── main.py                 # FastAPI entry point
│   ├── config.py               # Environment + constants
│   ├── database.py             # SQLAlchemy setup
│   ├── models.py               # Video + Clip ORM models
│   ├── schemas.py              # Pydantic request/response
│   ├── pipeline/
│   │   ├── state.py            # Typed state + Pydantic models
│   │   ├── graph.py            # LangGraph pipeline definition
│   │   ├── chat.py             # Intent parsing + response gen
│   │   ├── tools.py            # LangChain tool definitions
│   │   └── agents/
│   │       ├── classifier.py   # Video type classification
│   │       ├── visual_agent.py # Two-pass frame analysis
│   │       ├── audio_agent.py  # librosa feature extraction
│   │       ├── text_agent.py   # Semantic segmentation
│   │       ├── fusion.py       # Cross-modal convergence
│   │       ├── clip_selector.py# Preference-based selection
│   │       └── production.py   # FFmpeg clip production
│   ├── routers/
│   │   ├── chat.py             # Chat endpoint (primary)
│   │   ├── videos.py           # Upload/manage videos
│   │   ├── clips.py            # Clip CRUD
│   │   └── pipeline.py         # Legacy SSE pipeline
│   ├── services/               # Transcription, captions, etc.
│   └── utils/                  # FFmpeg, subtitle helpers
├── tests/
│   ├── test_state.py
│   ├── test_fusion.py
│   ├── test_graph.py
│   ├── test_chat.py
│   └── test_e2e.py
frontend/
├── src/
│   ├── pages/Chat.jsx          # Primary chat interface
│   ├── components/             # Clip cards, upload zone, etc.
│   └── services/api.js         # Axios HTTP client
```

## Scaling Considerations

| Current | Production |
|---|---|
| SQLite | PostgreSQL + connection pooling |
| MemorySaver | PostgresSaver for persistent checkpoints |
| In-memory analysis cache | Redis |
| Sequential processing | Celery workers for parallel FFmpeg |
| Local file storage | S3/GCS |
| SSE for progress | WebSocket for bidirectional |
