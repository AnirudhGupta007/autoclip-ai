# Deploying AutoClip on AWS

This documents what actually runs in production: **one EC2 instance running
the Docker Compose stack**, HTTPS via a Let's Encrypt IP certificate, no SSH,
and CI/CD through GitHub OIDC + SSM Run Command. Option B (ECS Fargate) is
sketched at the bottom for when one box isn't enough.

> **Cost reality:** the single highest-leverage decision is instance size and
> whether it runs 24/7. The live demo runs a `t3a.small` always-on for
> ~$15/month (instance + 30GB gp3 + public IPv4). Stopping it when idle cuts
> that to just EBS + the Elastic IP.

---

## Option A — one EC2 instance (current production)

### What runs where

| Piece | Where |
|---|---|
| FastAPI backend, Postgres+pgvector, Redis, nginx frontend | Docker Compose on one EC2 instance, app at `/opt/autoclip` |
| Source videos + produced clips | Docker named volumes on the instance's EBS disk |
| Secrets (`OPENROUTER_API_KEY`, `POSTGRES_PASSWORD`) | `/opt/autoclip/.env` on the host (not in git) |
| TLS certificates | `/opt/autoclip/certs`, issued/renewed by acme.sh on the host |

### Current production setup

| Setting | Value |
|---|---|
| Region | `ap-south-1` (Mumbai) |
| Instance | `t3a.small` (2 vCPU / 2GB), CPU credits **standard**, Ubuntu 24.04 |
| Disk | 30GB gp3 + 4GB swapfile |
| Address | Elastic IP `15.206.112.113` |
| Security group | inbound **80, 443 only** — port 22 closed |
| Instance profile | `autoclip-ec2-ssm` (`AmazonSSMManagedInstanceCore`) — all admin goes through SSM |
| Quota | `DAILY_QUERY_LIMIT=2`, `DAILY_GLOBAL_QUERY_LIMIT=100` in `.env` |
| Limits | 300 MB / 60 min uploads (audio or video) for everyone, 3 active uploads and 1.5 GB per user (section 7) |

2GB RAM + 4GB swap is tight but works for uploads of up to an hour, one
analysis at a time. Postgres + Redis + the Python app + nginx idle around
1–1.5GB; ffmpeg pushes it into swap. For longer videos use a `t3.large`
(8GB) and more disk.

| Instance | vCPU / RAM | Use |
|---|---|---|
| `t3a.small` | 2 / 2GB | Public demo with short videos (current). Needs swap. |
| `t3.medium` | 2 / 4GB | Comfortable for short/medium videos. |
| `t3.large` | 2 / 8GB | Long-form videos. Enable T3 Unlimited for long encodes. |

### 1. Launch the instance

- AMI: Ubuntu 24.04 LTS (x86_64), type `t3a.small`, 30GB gp3
- Security group inbound: `80`, `443` (port 80 must stay open — ACME
  challenges and the HTTP→HTTPS redirect use it)
- IAM instance profile with `AmazonSSMManagedInstanceCore` so you can manage
  it with SSM Session Manager / Run Command instead of SSH
- Allocate and associate an Elastic IP

### 2. Provision the box (via SSM Session Manager)

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile \
  && sudo mkswap /swapfile && sudo swapon /swapfile \
  && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# CI expects the checkout at /opt/autoclip, and the directory name also fixes
# the compose project name (container autoclip-frontend-1, used by the cert reload)
sudo git clone https://github.com/AnirudhGupta007/autoclip-ai.git /opt/autoclip
cd /opt/autoclip
sudo cp .env.example .env
sudo nano .env
#   OPENROUTER_API_KEY=sk-or-v1-...
#   POSTGRES_PASSWORD=<long random>   # set BEFORE first boot — the pgdata volume keeps the first one
#   DAILY_QUERY_LIMIT=2
#   DAILY_GLOBAL_QUERY_LIMIT=100
#   ADMIN_EMAILS=you@example.com      # then sign up with it right away (section 9)
```

Then set up HTTPS (next section) and start with the prod overlay:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

**Always include the prod overlay.** Plain `docker compose up` (or `make up`)
uses `nginx.conf`, which serves HTTP only on :80 — the site loses HTTPS.

### 3. HTTPS without a domain (Let's Encrypt IP certificate)

The prod overlay (`docker-compose.prod.yml`) publishes 443, mounts
`frontend/nginx.prod.conf`, `./certs` and `./acme-www`. Port 80 serves only
ACME challenges and a redirect.

Certificates are Let's Encrypt **IP address** certs (`shortlived` profile,
~6.5-day lifetime), issued and renewed on the host by acme.sh (run as root):

```bash
cd /opt/autoclip
mkdir -p certs acme-www
# bootstrap: nginx needs *a* cert to start, so begin with a throwaway self-signed one
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=<ip>" \
  -keyout certs/key.pem -out certs/fullchain.pem
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d frontend

acme.sh --set-default-ca --server letsencrypt
acme.sh --issue -d <ip> -w "$PWD/acme-www" --cert-profile shortlived --days 3
acme.sh --install-cert -d <ip> \
  --key-file "$PWD/certs/key.pem" --fullchain-file "$PWD/certs/fullchain.pem" \
  --reloadcmd "docker exec autoclip-frontend-1 nginx -s reload"
```

acme.sh's cron renews every 3 days and reloads nginx in place (no downtime).

> The reload command hard-codes the container name `autoclip-frontend-1`,
> which only holds when the checkout directory is named `autoclip`. If you
> clone elsewhere, adjust it — otherwise renewal succeeds but nginx keeps the
> old cert until it expires, silently.

When a domain is added later, re-issue for the domain the same way.

### 4. CI/CD (GitHub Actions → SSM)

`.github/workflows/deploy.yml`:

1. **On every push and PR:** frontend `npm ci && npm run build`; backend
   `python -m compileall`.
2. **On push to `master`** (after both pass): assume an AWS role via GitHub
   OIDC, send an SSM Run Command (`AWS-RunShellScript`) to the instance that
   runs, in `/opt/autoclip`:
   `git fetch && git reset --hard <sha>` →
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`,
   wait for it, then `curl` `https://<ip>/api/health/ready` as a smoke test.
   Deploys are serialized (concurrency group) and pinned to the tested SHA.

One-time AWS setup:

- IAM OIDC identity provider for `token.actions.githubusercontent.com`.
- Role `autoclip-github-deploy`, trusted for this repo's `master` branch,
  allowed `ssm:SendCommand` on the instance + `AWS-RunShellScript`, and
  `ssm:GetCommandInvocation`.
- Repo secret **`AWS_DEPLOY_ROLE_ARN`** = that role's ARN.
- `AWS_REGION`, `INSTANCE_ID` and `SITE_URL` are hard-coded in the
  workflow's `env:` — update them if the instance changes.

The smoke test hits `/api/health/ready`, which answers 503 until Postgres,
Redis, free disk (>= `READY_MIN_FREE_DISK_GB`), ffmpeg and the OpenRouter key
all check out. The OpenRouter balance is cached 5 minutes; a slow or failing
OpenRouter API reads as "unknown" and doesn't fail the check, only a missing
key or a balance at/below `READY_MIN_OPENROUTER_USD` does. The response
never includes the balance. `/api/health` stays the cheap liveness probe for
the Docker healthcheck. There is still no automatic rollback.

### 5. Manual deploy / admin

Through SSM Session Manager (or Run Command):

```bash
cd /opt/autoclip && sudo git pull \
  && sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
sudo docker compose logs -f backend
```

### 6. Nightly database backups to S3

`backend/scripts/backup_db.sh` runs on the **host**: `pg_dump` from the
postgres container → gzip → `aws s3 cp` to `s3://$BACKUP_S3_BUCKET/autoclip/db/`
(region `ap-south-1`). It keeps the newest 7 dumps locally in
`~/autoclip-backups` and refuses to upload a suspiciously small dump. Media
files are not backed up (sources expire after 7 days anyway).

Not set up yet. One-time setup, done by the owner (none of this exists today):

1. Create a private bucket in `ap-south-1` (block all public access, SSE-S3).
   Add a lifecycle rule to expire `autoclip/db/` objects after e.g. 30 days.
2. Give the instance role `autoclip-ec2-ssm` an inline policy allowing
   `s3:PutObject` on `arn:aws:s3:::<bucket>/autoclip/db/*` only.
3. On the box: `sudo apt-get install -y awscli` (or the v2 installer), then
   a root crontab entry:

```bash
15 2 * * * BACKUP_S3_BUCKET=<bucket> /opt/autoclip/backend/scripts/backup_db.sh >> /var/log/autoclip-backup.log 2>&1
```

Run it once by hand first and check the object appears. To restore:

```bash
aws s3 cp s3://<bucket>/autoclip/db/autoclip-<stamp>.sql.gz . --region ap-south-1
gunzip -c autoclip-<stamp>.sql.gz | sudo docker compose exec -T postgres psql -U autoclip -d autoclip
```

The dump uses `--clean --if-exists`, so it replaces the existing tables.

### 7. Storage rules and disk

The 30 GB disk has ~17 GB free and isn't being resized, so uploads have
limits and files expire (all env keys, see README "Configuration"):

| Rule | Default | Key |
|---|---|---|
| Active uploads per user | 3 | `MAX_VIDEOS_PER_USER` |
| Storage per user (sources + clips) | 1.5 GB | `STORAGE_QUOTA_MB` |
| Uploads paused when free disk is below | 5 GB | `MIN_FREE_DISK_GB` |
| Source file deleted (video then "archived") | 7 days after upload | `SOURCE_RETENTION_DAYS` |
| Rendered clips deleted | 30 days after rendering | `CLIP_RETENTION_DAYS` |
| Inactive account: all files deleted, account kept | 60 days | `INACTIVE_ACCOUNT_DAYS` |

The cleanup runs inside the backend: an asyncio loop started in the app's
lifespan wakes every 15 minutes and runs once per UTC day from
`CLEANUP_HOUR_UTC` (03:00), guarded by a Redis `SET NX` key so only one
worker runs it. Admin and demo accounts are exempt, so the public demo's
source never expires. `CLEANUP_ENABLED=0` turns it off.

Analysis runs one job at a time (`ANALYSIS_MAX_CONCURRENCY=1`); others wait
in line and the chat shows their position. `DAILY_ANALYSIS_MINUTES_LIMIT`
(default 240) caps the minutes of media non-admins can have analysed per UTC
day, site-wide.

### 8. Stop / start to save credits

```bash
aws ec2 stop-instances  --region ap-south-1 --instance-ids i-XXXX
aws ec2 start-instances --region ap-south-1 --instance-ids i-XXXX
```

A stopped instance costs nothing for compute; you still pay for EBS and the
Elastic IP. **When shutting down for good, release the Elastic IP** — an
unattached EIP keeps billing.

Set a billing alarm regardless (billing metrics live in `us-east-1`):

```bash
aws cloudwatch put-metric-alarm --region us-east-1 --alarm-name autoclip-spend \
  --namespace AWS/Billing --metric-name EstimatedCharges \
  --dimensions Name=Currency,Value=USD \
  --statistic Maximum --period 21600 --threshold 25 \
  --comparison-operator GreaterThanThreshold --evaluation-periods 1
```

### 9. Accounts, migrations and the demo

The schema is managed by Alembic (`backend/alembic/`). The backend
container's entrypoint runs `alembic upgrade head` before uvicorn, and the
app runs it again on startup (a no-op when current).

**First deploy of the auth release onto the existing prod database** (tables
created by the old `create_all()`, no `alembic_version` yet):

```bash
cd /opt/autoclip && sudo git pull
# 1. set ADMIN_EMAILS in .env (first entry becomes the owner of existing videos)
# 2. back up, then mark the pre-auth schema as revision 0001
sudo docker compose exec postgres pg_dump -U autoclip autoclip > ~/autoclip-pre-auth.sql
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm --entrypoint "" backend alembic stamp 0001
# 3. deploy: the entrypoint applies 0002 (users, sessions, videos.user_id; existing
#    videos are assigned to the first ADMIN_EMAILS address, or owner@local)
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

(`stamp` is belt-and-braces: 0001 only creates tables that are missing, so a
plain `upgrade head` on the old schema is also safe.)

Later migrations apply on their own at deploy: 0003 moment categories, 0004
`videos.media_kind`, 0005 chat history (`conversations`, `messages`), 0006
storage (`videos.archived`, `users.last_active_at`, back-filled with the
upgrade time so the 60-day inactivity clock starts then). Chats made before
0005 lived in LangGraph threads named `u:{uid}:v:{vid}`; they stay in
Postgres but no longer show, since history now comes from `conversations`.

**Bootstrap the admin:** open `/signup` and sign up with the first
`ADMIN_EMAILS` address — that claims the passwordless owner account the
migration created, with all existing videos. Do this right after deploying:
there is no email verification, so until then anyone who knows the address
could claim it.

**Demo account** ("Try demo" on `/login`, and `/demo`): give it one or more
already-analysed videos — they move from their current owner to the demo:

> The Doctorow talk is 61.2 minutes, over the 60-minute cap that now applies
> to admins too. To upload it as the admin, set `VIDEO_MINUTES_CAP_ADMINS=0`
> in `.env` and restart the backend, upload, then set it back to `1`. Or
> trim the file under 60 minutes first.

```bash
sudo docker compose exec backend python scripts/seed_demo.py --video-id <id> [--video-id <id2>]
```

Demo visitors can watch the clips and chat (shared `DEMO_DAILY_QUERY_LIMIT`
pool), but can't upload or delete.

**Media files** are no longer public. `/api/files/{uploads|outputs}/…`
checks ownership and answers with `X-Accel-Redirect: /_protected/…`; nginx
serves the bytes from the `uploads`/`outputs` volumes, which compose mounts
read-only into the frontend container (`FILES_ACCEL_REDIRECT=1`). Without
nginx (local `make dev`) the backend streams the file itself.

**Eval runs** need a login now: `EVAL_EMAIL=you@example.com EVAL_PASSWORD=… \
python backend/scripts/eval_movie.py …` (an admin account skips the quota).

---

## Code changes needed before this is production-shaped

Option A runs on one box because local disk is fine there. These are still
worth doing before going past one box or past an hour of video:

1. ~~**Background analysis jobs.**~~ Done in-process: analysis runs on a
   background thread with SSE progress and a one-at-a-time queue
   (`utils/analysis_jobs.py`). Across several containers it would need a real
   worker + queue.
2. **Raise the upload ceiling / ingest by path.** `MAX_UPLOAD_SIZE_MB` is 300
   (`backend/src/autoclip/config.py`), sized for an hour of video. Longer
   files need presigned S3 multipart upload, or an "ingest from path"
   endpoint for files already on the box.
3. **Write outputs to S3.** Clips land on local disk and are served from a
   static mount. Fine on one box, fatal across containers.
4. ~~**Access control.**~~ Done — accounts + per-user scoping (section 9).

---

## Option B — ECS Fargate (when one box isn't enough)

```
Browser ──presigned PUT──▶ S3 ◀── CloudFront (serves clips)
   │
   └─▶ ALB (idle timeout 4000s — required for SSE)
          ├─▶ ECS api task     (2 vCPU / 4GB, always on)   ──▶ SQS
          └─▶ ECS worker task  (4–8 vCPU, scale 0→N on queue depth,
                                ephemeral storage 200GB)
                    │
              RDS Postgres (pgvector) · ElastiCache Redis · Secrets Manager
```

Baseline ~$110–130/month, but workers scale to zero so you pay for ffmpeg only
while it runs. Requires code changes 1–3 above.

**Gotchas that bite everyone:**

- **ALB idle timeout is 60s by default.** Your SSE progress stream dies
  silently at exactly 60 seconds until you raise it (max 4000s).
- **Fargate ephemeral storage defaults to 20GB.** A 3-hour film plus 90 chunk
  files blows past it — set 200GB or stream chunks from S3.
- **pgvector on RDS** needs Postgres 15.2+ and `CREATE EXTENSION vector;` run
  once against the instance.
- **No GPU required.** All inference is remote via OpenRouter; workers only
  need CPU for ffmpeg. That is what keeps this cheap.
