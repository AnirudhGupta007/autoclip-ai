# AutoClip AI — Project Progress

## What This Project Is
A conversational AI video clipping tool. Users upload a long video, chat with it in natural language, and get short viral clips generated through multimodal AI analysis (visual + audio + text fusion).

**Stack:** FastAPI + LangGraph + Gemini 2.0 Flash + React + Vite + Tailwind + PostgreSQL + Docker + Nginx

---

## What's Been Done

### 1. Codebase Cleanup (Completed)
- **Removed legacy pipeline flow** (Flow 1: Dashboard → Process → Results via SSE)
- Kept only **Chat flow** (Flow 2: upload in chat → LangGraph pipeline → clips in chat)
- Deleted files:
  - `backend/src/autoclip/pipeline/orchestrator.py` — old SSE pipeline
  - `backend/src/autoclip/pipeline/tools.py` — unused ToolNode definitions
  - `backend/src/autoclip/routers/pipeline.py` — legacy SSE endpoint
  - `backend/src/autoclip/services/analysis.py` — old chunking logic
  - `frontend/src/pages/Home.jsx, Dashboard.jsx, Process.jsx, Results.jsx`
  - `frontend/src/components/Sidebar.jsx, DropZone.jsx, ClipGrid.jsx, CaptionStyler.jsx, FormatPicker.jsx, MusicSelector.jsx, ProgressTracker.jsx, ScoreRadar.jsx, VideoPreview.jsx`
  - `frontend/src/hooks/useSSE.js`

### 2. Bug Fixes (Completed)
- **Critical:** `generation_pipeline` → `generation_only` in `routers/chat.py:226` (was crashing modify-clip)
- Removed unused imports: `EventSourceResponse`, `asdict`, `ANALYSIS_TOOLS`, `ToolNode`
- Removed disconnected `ffmpeg_tools` ToolNode from generation subgraph
- Fixed `Chat.jsx` to use `sendChatMessage()` instead of direct `api.post()`
- Removed `react-query` wrapper from `main.jsx` (was unused after page deletions)

### 3. Frontend Redesign (Completed)
Extracted Chat.jsx (380 lines) into proper components:

| Component | Purpose |
|-----------|---------|
| `HeroSection.jsx` | Animated landing page with gradient glow, feature pills, upload zone |
| `UploadZone.jsx` | Enhanced drag-drop using `react-dropzone`, floating icon animation |
| `VideoBar.jsx` | Sticky bar showing video name, duration, resolution after upload |
| `ProcessingIndicator.jsx` | 4-step animated progress: Analyzing → Extracting → Scoring → Generating |
| `ChatMessage.jsx` | Message bubble with purple left border for bot messages |
| `ClipCard.jsx` | Expandable card with ScoreRing, score breakdown bars, transcript preview |
| `ScoreRing.jsx` | SVG circular score badge (animated stroke, color-coded) |
| `SuggestedPrompts.jsx` | Quick-action chips: "4 funny TikToks", "Best highlights", etc. |

Chat.jsx is now ~150 lines (orchestrator pattern).

### 4. Deployment Setup (Completed)
- **Docker:** `backend/Dockerfile` (multi-stage: uv build → Python 3.11 + FFmpeg runtime)
- **Docker:** `frontend/Dockerfile` (multi-stage: Node build → nginx serve)
- **Docker Compose:** `docker-compose.yml` (3 containers: backend + postgres + nginx)
- **Nginx:** `frontend/nginx.conf` (reverse proxy for /api, /uploads, /outputs)
- **CI/CD:** `.github/workflows/deploy.yml` (GitHub Actions: test → SSH deploy to EC2)
- **Database:** Made `database.py` compatible with both SQLite and PostgreSQL
- **CORS:** Made configurable via `CORS_ORIGINS` env var (was hardcoded to localhost)
- **Config:** Made `config.py` Docker-aware for .env file loading

### 5. AWS Deployment (Completed - LIVE)
- **Instance:** EC2 t3.micro, Ubuntu 24.04, 20GB gp3 disk, us-east-1
- **Instance ID:** `i-02383ba41e2d0079d`
- **Public IP:** `35.173.49.231` (NOTE: changes if instance is stopped/started)
- **URL:** http://35.173.49.231
- **SSH Key:** `~/.ssh/autoclip-key.pem` (you need to recreate this if machine is wiped)
- **Security Group:** `autoclip-sg` (ports 22, 80 open)
- **Key Pair Name:** `autoclip-key` (stored in AWS, can be used with new .pem)
- **Swap:** 2GB swap file configured (prevents OOM on 1GB RAM)
- All 3 Docker containers running: nginx (frontend), backend (FastAPI), postgres

---

## AWS Account Details
- **Account ID:** 947947704799
- **IAM User:** autoclip-admin
- **Region:** us-east-1
- **Instance type:** t3.micro (free tier eligible)

---

## API Keys Needed (store in .env, DO NOT commit)
You need to regenerate ALL of these (they were exposed in chat):
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey
- `ASSEMBLYAI_API_KEY` — https://www.assemblyai.com/dashboard
- `PEXELS_API_KEY` — https://www.pexels.com/api/
- `LANGSMITH_API_KEY` — https://smith.langchain.com
- `POSTGRES_PASSWORD` — any strong password

---

## How to Reconnect After Machine Wipe

### 1. Install tools
```bash
winget install Amazon.AWSCLI
winget install GitHub.cli
```

### 2. Configure AWS CLI
```bash
aws configure
# Enter your access key, secret key, region: us-east-1, format: json
```

### 3. Recreate SSH key (the .pem file was on your old machine)
You CANNOT download the old key again. You have two options:

**Option A: Create a new key pair and replace on instance**
```bash
# Create new key pair
aws ec2 create-key-pair --key-name autoclip-key-v2 --query 'KeyMaterial' --output text --region us-east-1 > ~/.ssh/autoclip-key-v2.pem
chmod 400 ~/.ssh/autoclip-key-v2.pem

# You'll need to use EC2 Instance Connect (browser-based SSH) to update the authorized_keys
# Go to: AWS Console → EC2 → select instance → Connect → EC2 Instance Connect → Connect
# Then run:
# echo "YOUR_NEW_PUBLIC_KEY" >> ~/.ssh/authorized_keys
```

**Option B: Use EC2 Instance Connect (no SSH key needed)**
```bash
# Install the plugin
pip install ec2instanceconnectcli

# Connect directly
aws ec2-instance-connect ssh --instance-id i-02383ba41e2d0079d --region us-east-1
```

**Option C: AWS Console browser SSH**
Go to AWS Console → EC2 → Instances → select `autoclip-ai` → Connect → EC2 Instance Connect → Connect

### 4. Clone repo and continue
```bash
git clone https://github.com/AnirudhGupta007/autoclip-ai.git
cd autoclip-ai
```

---

## How to Manage the EC2 Instance

### Stop (save money, $0 when stopped)
```bash
aws ec2 stop-instances --instance-ids i-02383ba41e2d0079d --region us-east-1
```

### Start (before interview/demo)
```bash
aws ec2 start-instances --instance-ids i-02383ba41e2d0079d --region us-east-1
# Wait 30 seconds, then get the NEW public IP:
aws ec2 describe-instances --instance-ids i-02383ba41e2d0079d --query 'Reservations[0].Instances[0].PublicIpAddress' --output text --region us-east-1
```

### SSH into server
```bash
ssh -i ~/.ssh/autoclip-key.pem ubuntu@<EC2_IP>
```

### Redeploy after code changes
```bash
# On EC2:
cd /home/ubuntu/autoclip-ai
git pull origin master
docker compose up -d --build
docker image prune -f
```

### View logs
```bash
docker compose logs -f backend    # backend logs
docker compose logs -f frontend   # nginx logs
docker compose logs -f postgres   # database logs
```

### Check database
```bash
docker compose exec postgres psql -U autoclip -d autoclip
# \dt to list tables
# SELECT * FROM videos;
```

---

## Server .env File Location
On EC2: `/home/ubuntu/autoclip-ai/.env`

Contents needed:
```
GEMINI_API_KEY=<your_key>
ASSEMBLYAI_API_KEY=<your_key>
PEXELS_API_KEY=<your_key>
POSTGRES_PASSWORD=<strong_password>
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=<your_key>
LANGSMITH_PROJECT=Autoclip
```

---

## What's Left To Do

### High Priority
- [ ] Rotate ALL API keys (exposed in chat history)
- [ ] Test full end-to-end flow: upload video → ask for clips → download clips
- [ ] Set up GitHub Actions secrets (EC2_HOST, EC2_SSH_KEY) for auto-deploy

### Future Features
- [ ] User authentication (sessions, JWT)
- [ ] Save clip summaries for future editing
- [ ] Auto-delete source videos after processing (save disk space)
- [ ] Custom domain with SSL (HTTPS)
- [ ] Auto-stop EC2 when idle (Lambda scheduler)

---

## Architecture

```
GitHub push → GitHub Actions (test → SSH deploy)
                    ↓
EC2 t3.micro (Ubuntu 24.04, 20GB)
  └─ Docker Compose
       ├─ nginx (:80)     → serves React dist + proxies /api
       ├─ backend (:8000)  → FastAPI + FFmpeg + LangGraph
       └─ postgres (:5432) → persistent data volume

Pipeline: Upload → Transcription (AssemblyAI) → Scene Detection
  → Parallel Agents: Visual (Gemini Vision) | Audio (librosa) | Text (Gemini)
  → Temporal Fusion → Clip Selection + Scoring → FFmpeg Production → Download
```

## Cost
- Free tier: $0/month for 12 months
- After free tier: ~$10/month
- When stopped: $0 (disk only, covered by free tier)
