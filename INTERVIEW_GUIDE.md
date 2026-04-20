# AutoClip AI — Interview Guide (Explained Simply)

> A beginner-friendly walkthrough of the project, written the way you'd explain it to a classmate who has never seen the code before. Use this to prep for your interview.

---

## 1. What is this project? (The simplest answer)

Imagine a YouTuber who records a **1-hour podcast**. To grow, they need to post **short 30-second clips on TikTok, Instagram Reels, and YouTube Shorts**. But finding the "best" moments, cutting them, adding captions, and resizing the video from wide (16:9) to tall (9:16) takes hours.

**AutoClip AI does it for them in minutes — just by chatting.**

You upload a long video, type something like:
> *"Give me 4 funny TikTok clips under 30 seconds"*

and the AI sends back 4 ready-to-post short videos with captions burned in.

---

## 2. The Problem Statement (Why this project exists)

**The pain:**
1. Long videos are hard to re-use → creators lose reach
2. Manually finding viral moments takes hours
3. Existing tools (Opus Clip, Vidyo.ai) only read the **transcript** — they can't see if the audience is laughing or if the speaker is making dramatic gestures
4. Those tools also have **complicated editing timelines** that beginners hate

**The idea:**
- Make an AI that **sees, hears, AND reads** the video (like a human would)
- Replace the complicated UI with a simple **chat box**

That's AutoClip AI in one sentence.

---

## 3. The Big Idea — Multimodal Analysis

"Multimodal" just means **using more than one type of data**. Here we use three:

| Modality | What it looks at | Example signal |
|---|---|---|
| **Visual** | Video frames (images) | Speaker waves hands, face shows surprise |
| **Audio** | Sound wave | Audience laughs, volume suddenly spikes |
| **Text** | Transcript (words spoken) | Speaker says *"the truth is nobody tells you..."* |

**Why this matters:** A text-only tool reading *"and that's when everything changed"* doesn't know if it was whispered (boring) or shouted with the crowd cheering (viral). By combining all three, we catch moments where **multiple signals agree** — and those are the real viral moments.

We call this **convergence**. When the video is visually exciting + audio is loud + the words have a "hook" → that's probably gold.

---

## 4. How It Works — Step by Step (like a recipe)

Here's what happens from the moment you upload a video to getting clips back:

### Step 1: Upload the video
User drags a video into the chat. It saves to disk. Done.

### Step 2: Get the words (Transcription)
We send the audio to **AssemblyAI** (a speech-to-text service). It gives us:
- The full transcript
- The exact timestamp of every single word
- Who is speaking (if multiple people)

We need word-level timestamps later so clips never cut in the middle of a word.

### Step 3: Find scene boundaries
We use **PySceneDetect** to find where the camera angle changes (shot boundaries). If we need to cut a clip, snapping to these boundaries makes the cuts look natural.

### Step 4: Classify the video type
Is it a talking head? A presentation? A podcast? We send 3 sample frames to **Google Gemini** and ask it to pick a category. This matters because:
- For a **podcast**, there's nothing to see → skip visual analysis (save API cost)
- For a **presentation**, slides change fast → sample frames more often

### Step 5: Run THREE agents in parallel
This is the coolest part. At the same time:

**A) Visual Agent** — Looks at the frames
- Samples frames every few seconds
- Sends them to Gemini Vision
- Gemini returns: *"energy = 0.8, emotion = excited, scene = talking_head, has_text = false"*
- Uses a clever **two-pass trick** — sample cheaply first, then zoom in on interesting parts

**B) Audio Agent** — Listens to the sound
- Uses a Python library called **librosa** (free, runs locally)
- Measures 8 things per 2-second window: volume, brightness, noisiness, onset events (sudden sounds like claps), tempo, speech pace
- Classifies each moment as: *speech*, *laughter*, *applause*, *silence*, or *music*

**C) Text Agent** — Reads the transcript
- First, super-fast regex pre-scan for known hook patterns like *"you won't believe"*, *"the truth is"*, *"unpopular opinion"*
- Then sends transcript to Gemini to classify every segment: is it a *hot_take*, *story*, *quote*, *funny*, *emotional*, *educational*, or nothing?
- Rates each segment's "hook strength" from 0.0 to 1.0

All three run **at the same time** (parallel), not one after the other. This saves huge amounts of time.

### Step 6: Fusion — combine the three signals
Now we have three timelines. The **fusion node** slides a 5-second window across the whole video. For every 5-second window it asks:
- Is visual energy high? ✅
- Is audio energy high? ✅
- Does this contain a strong text hook? ✅

If 2 or 3 of the three say yes → **this is a convergence moment**. We give it a bonus score (30% bonus if all 3, 15% if 2 out of 3).

The output is a **ranked list of "moments"** — the best potential clips, sorted from most viral to least.

### Step 7: Clip Selector — pick the best moments
Now the user's preferences kick in. If they said *"funny clips"*, we filter the moments for funny tags. If they said *"30 seconds"*, we expand/shrink moments around their center to hit 30s.

Each selected clip gets:
- A **title** (generated by Gemini)
- **Engagement scores** on 6 dimensions: Hook, Emotion, Shareability, Retention, Controversy, Novelty (each 1-10)
- An **overall score** (weighted average)

### Step 8: Production — cut and polish the clip
For each clip we:
1. Cut the segment out of the original video (**FFmpeg**)
2. Generate animated captions in ASS format (karaoke-style highlighting)
3. Burn the captions onto the video
4. Reframe from 16:9 (wide) to 9:16 (tall) using **OpenCV face detection** — this finds where the speaker's face is so we don't crop them out
5. Generate a thumbnail image

Done. The clip is ready to download.

### Step 9: Send everything back to the chat
The user sees a list of clips, each with a preview, title, score, and download button.

---

## 5. Follow-up Magic — The Reason for LangGraph

Here's a scenario:
- User: *"Give me 4 clips"* → system analyzes video (takes a few minutes)
- User: *"Make clip 2 longer"* → ???

Do we re-analyze the whole video? **NO — that would take forever.**

We use **LangGraph's checkpointing**. After Step 6, the pipeline **saves the state** (tagged with the video ID). When the user says "make clip 2 longer", we:
1. Skip Steps 2-6 entirely
2. Jump straight to Step 7 (clip selector) using the cached moments
3. Re-run production on just that one clip

This takes seconds instead of minutes. **This is the superpower of using LangGraph.**

---

## 6. Tech Stack — What We Used and Why

| Tool | What it does | Why we picked it |
|---|---|---|
| **LangGraph** | Orchestrates the AI pipeline | Supports parallel agents, checkpointing, and conditional branching out of the box |
| **Google Gemini 2.0 Flash** | The AI brain (vision + text) | One model handles both images and text. ~10x cheaper than GPT-4V |
| **AssemblyAI** | Speech-to-text | Gives word-level timestamps + speaker diarization in one API call |
| **librosa** | Audio analysis | Free, runs locally, no API cost |
| **PySceneDetect** | Scene boundary detection | Best open-source tool for this |
| **FFmpeg** | Video cutting/resizing/captioning | Industry standard |
| **OpenCV** | Face detection for auto-reframe | Ships with Haar cascades for face detection |
| **FastAPI** | Backend framework | Async-native, auto-generates API docs |
| **React + Vite + Tailwind** | Frontend | Vite = super fast reload, Tailwind = no writing CSS |
| **SQLAlchemy + SQLite/Postgres** | Database | SQLite for local dev, Postgres for production |
| **Docker + Nginx** | Deployment | Containers for easy deploy, Nginx as reverse proxy |
| **GitHub Actions** | CI/CD | Auto-deploys to EC2 on every push |
| **AWS EC2 (t3.micro)** | Hosting | Free tier for 12 months |

---

## 7. Problems I Faced and How I Fixed Them

**⚠️ These are the most important stories for the interview. They prove you actually built this.**

### Problem 1: Three agents writing to the same state at the same time
**What went wrong:** When agents ran in parallel, their outputs were overwriting each other — the last one to finish won, and the other two disappeared.

**How I fixed it:** LangGraph has a feature called **reducers**. By declaring state fields with `Annotated[list[VisualSignal], operator.add]`, writes get **appended** instead of overwritten. Problem solved.

### Problem 2: Gemini Vision API was too expensive
**What went wrong:** Dense frame sampling on a 1-hour video = 7,200+ API calls. That's expensive and hits rate limits.

**How I fixed it:** A **two-pass sampling strategy**. First pass samples every few seconds to find "hot regions." Second pass only zooms in on those hot regions. 80-90% fewer API calls.

### Problem 3: Clips were cutting mid-word
**What went wrong:** Clips would start like *"...and then I realized..."* — the first word was half-missing.

**How I fixed it:** Using AssemblyAI's word-level timestamps, I **snap clip start/end to the nearest word boundary** (within 0.5s). I also snap to PySceneDetect boundaries within 2s for cinematic-feeling cuts.

### Problem 4: Re-running the whole pipeline on every chat message
**What went wrong:** When user said *"make clip 2 longer"*, the whole analysis was re-running — minutes of wasted time.

**How I fixed it:** LangGraph's **MemorySaver checkpointing** + a conditional edge at the start of the graph that checks `analysis_complete`. If analysis is cached, skip straight to generation. Seconds instead of minutes.

### Problem 5: Auto-reframe was cropping speakers out of the frame
**What went wrong:** When converting 16:9 → 9:16, the default center-crop lost speakers standing on the side.

**How I fixed it:** Used **OpenCV's Haar cascade face detector** to sample 5 frames, find the dominant face x-position, and crop around the face instead of the center.

### Problem 6: t3.micro EC2 crashed during video processing
**What went wrong:** 1 GB RAM is too little when FFmpeg + librosa run at the same time. The instance kept hitting Out-of-Memory.

**How I fixed it:** Added a **2 GB swap file** to the Ubuntu server. Cheap and effective.

### Problem 7: The frontend chat page was 380 lines of spaghetti
**What went wrong:** Everything lived in one file — unreadable and untestable.

**How I fixed it:** Refactored into **8 focused components**: HeroSection, UploadZone, VideoBar, ChatMessage, ClipCard, ScoreRing, ProcessingIndicator, SuggestedPrompts. Chat.jsx dropped to ~150 lines and is now a pure orchestrator.

### Problem 8: "Double counting" of modalities
**What went wrong:** Loud screen-share moments were scoring high on both visual energy and audio energy → fake viral moments.

**How I fixed it:** The convergence bonus only kicks in when 2+ **distinct** modalities each pass an activity threshold (>0.4). No more fake convergence.

---

## 8. Jargon Dictionary (memorize these)

Don't get caught out by technical terms. Here's plain-English for each:

| Term | Plain-English meaning |
|---|---|
| **Multimodal** | Using more than one type of data (image + sound + text) |
| **Pipeline** | A series of steps where the output of one feeds the next |
| **Agent** | A small program that does one focused job (look, listen, or read) |
| **Parallel** | Running at the same time instead of one after the other |
| **Fan-out / Fan-in** | One step splitting into many (fan-out) and many merging back to one (fan-in) |
| **Subgraph** | A mini-pipeline that plugs into a bigger one |
| **Checkpointing** | Saving state so you can resume later without restarting |
| **State** | The shared data that flows through the pipeline |
| **Reducer** | A rule for how to combine updates to the same state field |
| **Convergence** | When multiple signals agree at the same moment |
| **Hook** | The attention-grabbing opening of a clip |
| **Transcription** | Converting speech → text |
| **Diarization** | Figuring out *who* is speaking *when* |
| **librosa features** | Numbers extracted from sound (energy, brightness, etc.) |
| **Onset** | The start of a sudden sound event (a clap, a drum hit) |
| **Reframing** | Resizing a video from one aspect ratio to another (16:9 → 9:16) |
| **ASS format** | A subtitle format that supports animations |
| **Haar cascade** | A fast, classic algorithm for detecting faces |
| **Pydantic** | A Python library for validating data types |
| **TypedDict** | A Python dictionary with a declared structure |
| **FastAPI** | A modern Python web framework |
| **SSE / WebSocket** | Ways to stream data from server to browser |
| **Docker** | A way to package your app with all its dependencies so it runs the same everywhere |
| **Nginx** | A web server that sits in front and routes requests |
| **CI/CD** | Automatically testing and deploying your code on every push |
| **EC2** | An AWS virtual server |

---

## 9. 90-Second Interview Answer ("Walk me through your project")

Practice saying this out loud:

> "AutoClip AI is a chat-based video clipping tool. The user uploads a long video and types something like *'give me 4 funny TikTok clips under 30 seconds'*.
>
> My backend parses that message with Gemini to figure out the user's intent, then runs a LangGraph pipeline. The pipeline first transcribes the audio with AssemblyAI to get word-level timestamps, then runs PySceneDetect to find shot boundaries, then classifies the video type.
>
> The key part is the next step — it fans out to three agents that run **in parallel**: a Visual Agent that samples frames and sends them to Gemini Vision, an Audio Agent that uses librosa to extract 8 sound features per second, and a Text Agent that looks for hooks and story patterns in the transcript.
>
> All three write to their own piece of shared state using LangGraph reducers, so they don't overwrite each other. A fusion step then slides a window across the three timelines and finds **convergence moments** — spots where visual energy, audio energy, and text hooks all peak together. These are the most likely viral clips.
>
> A clip selector picks the best moments matching the user's request, and a production step uses FFmpeg to cut the video, burn animated captions on with ASS format, and reframe 16:9 to 9:16 using OpenCV face detection so speakers stay centered.
>
> The whole pipeline state is checkpointed by video ID, so follow-up requests like *'make clip 2 longer'* skip the analysis and complete in seconds instead of minutes.
>
> The frontend is a minimal React chat. Everything is Dockerized and deployed on an AWS EC2 with GitHub Actions for auto-deploy."

---

## 10. Common Interview Questions + Simple Answers

**Q: Why LangGraph and not plain Python or LangChain?**
A: LangGraph gives three things I needed that would be painful to build from scratch: (1) parallel agent execution with Send API, (2) state reducers so parallel writes don't conflict, and (3) checkpointing so chat conversations remember prior state.

**Q: Why Gemini and not OpenAI GPT-4V?**
A: Gemini 2.0 Flash is about 10x cheaper than GPT-4V for vision tasks, handles both images and text in the same model, and has good Pydantic structured output support.

**Q: How do you deal with hallucinations in the AI outputs?**
A: Three layers of defense: (1) Pydantic schemas validate every LLM response, (2) the final scoring math is deterministic — convergence is calculated, not asked to an LLM, (3) if JSON parsing fails, I fall back to safe defaults instead of crashing.

**Q: Why not Whisper instead of AssemblyAI?**
A: AssemblyAI gives speaker diarization in one API call. With Whisper I'd need a separate model (pyannote) — more code, more failure points. For a hobby/portfolio scale it's worth the cost.

**Q: What would you do to scale this to 10,000 videos/day?**
A: Three changes: (1) swap `MemorySaver` for `PostgresSaver` so checkpoints survive restarts, (2) move the in-memory analysis cache to Redis, (3) use Celery worker pool to run FFmpeg clip production in parallel instead of sequentially.

**Q: What's the weakest part of your code?**
A: Right now `MemorySaver` keeps state in RAM — if the server restarts, analysis is lost. That's a trivial fix (swap to `PostgresSaver`), but I left it because for a demo it's fine. I'd also improve the error handling — I catch bare exceptions in a few places where I should validate with Pydantic and retry.

**Q: Why chat instead of a timeline UI?**
A: Timeline UIs like Opus Clip have a learning curve. Chat has zero learning curve — everyone knows how to type. The trade-off is fine-grained control, but for the 80% case (*"give me 4 TikTok clips"*) chat is faster.

**Q: How does the "two-pass" visual sampling work?**
A: First pass samples every 2-5 seconds (coarse) and tags each frame's energy level. We find regions with high energy, then the second pass re-samples only those regions at 0.5-1s intervals. This skips 80-90% of boring footage — huge API cost savings.

**Q: How do you make sure clips don't cut mid-word?**
A: AssemblyAI gives me the exact start/end timestamp of every word. When I pick clip boundaries, I snap to the nearest word boundary within 0.5 seconds. I also snap to PySceneDetect shot boundaries within 2 seconds for smoother cuts.

**Q: What would you build next?**
A: A feedback loop. Right now my convergence weights (0.3 visual, 0.3 audio, 0.4 text) are hardcoded. I'd add thumbs up/down on clips and slowly tune the weights per user — personalized viral detection.

---

## 11. Quick Confidence Tips for the Interview

1. **Don't memorize — understand.** If you understand *why* each piece exists, you can handle any follow-up.
2. **Use simple words first, add jargon second.** Say *"three AIs running at the same time"* before you say *"fan-out parallel agents via Send API"*.
3. **When in doubt, use analogies.** Parallel agents = three people reading the same book, one watching the movie, one listening to the audiobook. Fusion = comparing notes at the end.
4. **Be honest about weaknesses.** Saying *"I used in-memory state which won't scale, but swapping to PostgresSaver is a one-line change"* sounds 10x better than pretending there are no issues.
5. **Lead with the insight.** Your main selling point is *multimodal convergence beats text-only clipping*. Say that first, then explain how.

---

## 12. The One-Liner Summary

> **"AutoClip AI is a chat-based video clipping tool that uses three parallel AI agents — vision, audio, and text — to find moments where all three signals peak at the same time. Those are the viral clips. I built it with LangGraph, Gemini, FastAPI, and React, deployed on AWS with Docker."**

That's it. Good luck! 🚀
