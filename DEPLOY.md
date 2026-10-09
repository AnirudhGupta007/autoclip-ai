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

2GB RAM + 4GB swap is tight but works for short demo videos. Postgres + Redis
+ the Python app + nginx idle around 1–1.5GB; ffmpeg pushes it into swap.
For long (1–3 hour) videos use a `t3.large` (8GB) and ~100GB of disk — a
3-hour source plus its chunk files can use tens of GB during analysis.

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
#   ADMIN_EMAILS=you@example.com      # then sign up with it right away (section 7)
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
   wait for it, then `curl` `https://<ip>/api/health` as a smoke test.
   Deploys are serialized (concurrency group) and pinned to the tested SHA.

One-time AWS setup:

- IAM OIDC identity provider for `token.actions.githubusercontent.com`.
- Role `autoclip-github-deploy`, trusted for this repo's `master` branch,
  allowed `ssm:SendCommand` on the instance + `AWS-RunShellScript`, and
  `ssm:GetCommandInvocation`.
- Repo secret **`AWS_DEPLOY_ROLE_ARN`** = that role's ARN.
- `AWS_REGION`, `INSTANCE_ID` and `SITE_URL` are hard-coded in the
  workflow's `env:` — update them if the instance changes.

Caveat: the smoke test hits `/api/health`, which returns a static response
without touching Postgres/Redis/OpenRouter, and there is no rollback.

### 5. Manual deploy / admin

Through SSM Session Manager (or Run Command):

```bash
cd /opt/autoclip && sudo git pull \
  && sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
sudo docker compose logs -f backend
```

### 6. Stop / start to save credits

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

### 7. Accounts, migrations and the demo

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

**Bootstrap the admin:** open `/signup` and sign up with the first
`ADMIN_EMAILS` address — that claims the passwordless owner account the
migration created, with all existing videos. Do this right after deploying:
there is no email verification, so until then anyone who knows the address
could claim it.

**Demo account** ("Try demo" on `/login`, and `/demo`): give it one or more
already-analysed videos — they move from their current owner to the demo:

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
worth doing, and the first two are **required** for a 3-hour video:

1. **Background analysis jobs.** `ingest_and_analyze_video` runs
   synchronously inside the chat request. A 3-hour film takes 15–45 minutes;
   the frontend gives up at 300s, nginx cuts `/api/` off at 600s, and an ALB
   defaults to 60s. Move the run to a worker and report progress over the SSE
   channel that already exists.
2. **Raise the upload ceiling / ingest by path.** `MAX_UPLOAD_SIZE` is 500MB
   (`backend/src/autoclip/config.py`); a 3-hour film is 2–8GB. Either raise it
   and use presigned S3 multipart upload, or add an "ingest from path"
   endpoint for files already on the box.
3. **Write outputs to S3.** Clips land on local disk and are served from a
   static mount. Fine on one box, fatal across containers.
4. ~~**Access control.**~~ Done — accounts + per-user scoping (section 7).

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
