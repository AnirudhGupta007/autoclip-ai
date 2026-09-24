# Deploying AutoClip on AWS

Two paths. **Option A (single EC2 + S3)** is what this guide recommends for a
portfolio project — it's the current `docker-compose.yml` on one box, so it
needs almost no code changes. **Option B (ECS Fargate)** is sketched at the
bottom for when one box isn't enough.

> **Cost reality:** a new AWS account gets up to **$200** in credits (not $300 —
> that's Google Cloud). An always-on `c7i.xlarge` burns that in ~6 weeks. The
> single highest-leverage decision in this document is **stopping the instance
> when nobody is looking at it** — that turns ~$72/month into ~$14/month.

---

## Option A — one EC2 instance + S3

### What you get

| Piece | Where it runs |
|---|---|
| FastAPI backend, Postgres+pgvector, Redis, nginx frontend | Docker Compose on one EC2 instance |
| Source videos + produced clips | S3 (durable, survives instance termination) |
| Secrets (`OPENROUTER_API_KEY`) | SSM Parameter Store |

### Sizing

| Instance | vCPU / RAM | ~$/mo (on-demand, us-east-1) | Notes |
|---|---|---|---|
| `t3.medium` | 2 / 4GB | ~$30 | Floor. Tight once ffmpeg runs. |
| **`t3.large`** | 2 / 8GB | **~$60** | **Recommended.** Enable T3 Unlimited for long encodes. |
| `c7i.large` | 2 / 4GB | ~$62 | Sustained CPU, no burst throttling. Better for 3hr films. |

Postgres + Redis + Python (LlamaIndex) + nginx idle at roughly 1.5–2GB before
ffmpeg starts, which is why 4GB is the floor and 8GB is comfortable.

Storage: **100GB gp3** (~$8/mo). A 3-hour source plus its chunk files can use
tens of GB during analysis.

### 1. Launch the instance

- AMI: Ubuntu 24.04 LTS (x86_64)
- Type: `t3.large`
- Storage: 100GB gp3
- Security group inbound: `22` (your IP only), `80`, `443`
- IAM instance role: attach the policy in step 3 (so no AWS keys live on the box)

### 2. Create the S3 bucket

```bash
aws s3 mb s3://autoclip-media-<your-suffix> --region us-east-1

# Block public access; serve clips via presigned URLs or CloudFront instead.
aws s3api put-public-access-block \
  --bucket autoclip-media-<your-suffix> \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Clips are re-creatable — expire raw intermediates to control cost.
aws s3api put-bucket-lifecycle-configuration \
  --bucket autoclip-media-<your-suffix> \
  --lifecycle-configuration '{"Rules":[{"ID":"expire-raw","Status":"Enabled","Filter":{"Prefix":"raw/"},"Expiration":{"Days":7}}]}'
```

### 3. IAM policy for the instance role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::autoclip-media-<your-suffix>/*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::autoclip-media-<your-suffix>"
    },
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParameter"],
      "Resource": "arn:aws:ssm:us-east-1:<account-id>:parameter/autoclip/*"
    }
  ]
}
```

Store the key once, encrypted:

```bash
aws ssm put-parameter --name /autoclip/openrouter_api_key \
  --value "sk-or-v1-..." --type SecureString
```

### 4. Provision the box

```bash
ssh ubuntu@<elastic-ip>

sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git awscli
sudo usermod -aG docker ubuntu && newgrp docker

git clone https://github.com/AnirudhGupta007/autoclip-ai.git
cd autoclip-ai

cp .env.example .env
# Pull the secret at boot rather than pasting it into .env by hand:
echo "OPENROUTER_API_KEY=$(aws ssm get-parameter --name /autoclip/openrouter_api_key \
  --with-decryption --query Parameter.Value --output text)" >> .env

docker compose up -d --build
```

Browse to `http://<elastic-ip>`. First build takes several minutes.

### 5. HTTPS (optional but do it before sharing the link)

```bash
sudo apt-get install -y certbot
sudo certbot certonly --standalone -d clips.yourdomain.com
```

Then mount the certs into the frontend container and add a `listen 443 ssl;`
server block to `frontend/nginx.conf`. Without a domain, use the raw IP over
HTTP and accept the browser warning.

### 6. Start/stop scripts — the part that saves the credits

```bash
# save as ~/autoclip-up.sh on your laptop
aws ec2 start-instances --instance-ids i-XXXX
aws ec2 wait instance-running --instance-ids i-XXXX
aws ec2 describe-instances --instance-ids i-XXXX \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
```

```bash
# ~/autoclip-down.sh
aws ec2 stop-instances --instance-ids i-XXXX
```

Stopped instances cost nothing for compute. You still pay for the EBS volume
(~$8/mo) and the public IPv4 address (~$3.60/mo, now billed even while
attached). Budget **~$14/month** if you only start it for demos.

Set a billing alarm regardless:

```bash
aws cloudwatch put-metric-alarm --alarm-name autoclip-spend \
  --namespace AWS/Billing --metric-name EstimatedCharges \
  --statistic Maximum --period 21600 --threshold 25 \
  --comparison-operator GreaterThanThreshold --evaluation-periods 1
```

---

## Code changes needed before this is production-shaped

Option A runs today on one box because local disk is still valid there. These
three are still worth doing, and the first two are **required** for a 3-hour
video regardless of where it runs:

1. **Background analysis jobs.** `ingest_and_analyze_video` currently runs
   synchronously inside the chat request. A 3-hour film takes 15–45 minutes;
   nginx cuts `/api/` off at 600s and an ALB defaults to 60s. Move the run to a
   worker and report progress over the SSE channel that already exists.
2. **Raise the upload ceiling / ingest by path.** `MAX_UPLOAD_SIZE` is 500MB
   (`backend/src/autoclip/config.py`); a 3-hour film is 2–8GB. Either raise it
   and use presigned S3 multipart upload, or add a "ingest from path" endpoint
   for files already on the box.
3. **Write outputs to S3.** Clips currently land on local disk and are served
   from a static mount. Fine on one box, fatal across containers.

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
while it runs.

**Gotchas that bite everyone:**

- **ALB idle timeout is 60s by default.** Your SSE progress stream dies silently
  at exactly 60 seconds until you raise it (max 4000s).
- **Fargate ephemeral storage defaults to 20GB.** A 3-hour film plus 90 chunk
  files blows past it — set 200GB or stream chunks from S3.
- **pgvector on RDS** needs Postgres 15.2+ and `CREATE EXTENSION vector;` run
  once against the instance.
- **No GPU required.** All inference is remote via OpenRouter; workers only need
  CPU for ffmpeg. That is what keeps this cheap.

## HTTPS without a domain (Let's Encrypt IP certificate)

The public server runs with the production overlay, which serves HTTPS on
443 and uses port 80 only for ACME challenges and a redirect:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Certificates are Let's Encrypt **IP address** certs (`shortlived` profile,
~6.5-day lifetime), issued and renewed on the host by acme.sh:

```bash
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
When a domain is added later, re-issue for the domain the same way.
