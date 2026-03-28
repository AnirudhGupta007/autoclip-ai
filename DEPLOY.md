# AutoClip AI — Deployment Guide

## Architecture

```
GitHub push → GitHub Actions (test → SSH deploy)
                    ↓
EC2 t2.micro (Ubuntu 24.04, 20GB, free tier)
  └─ Docker Compose
       ├─ nginx (:80)    → serves React build + proxies /api
       ├─ backend (:8000) → FastAPI + FFmpeg + uvicorn
       └─ postgres (:5432) → persistent data volume
```

**Cost: $0/month** (free tier for 12 months)

---

## Step-by-Step Deployment

### Step 1: AWS CLI Setup (on your local machine)

```bash
# Install AWS CLI
winget install Amazon.AWSCLI
# Restart terminal, then:
aws configure
# Enter: Access Key ID, Secret Key, region: us-east-1, output: json
```

Get your access key from: AWS Console → IAM → Users → Create user → Security credentials → Create access key

### Step 2: Create SSH Key Pair

```bash
aws ec2 create-key-pair \
  --key-name autoclip-key \
  --query 'KeyMaterial' \
  --output text > ~/.ssh/autoclip-key.pem

chmod 400 ~/.ssh/autoclip-key.pem
```

### Step 3: Create Security Group

```bash
aws ec2 create-security-group \
  --group-name autoclip-sg \
  --description "AutoClip AI"

aws ec2 authorize-security-group-ingress --group-name autoclip-sg --protocol tcp --port 22 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-name autoclip-sg --protocol tcp --port 80 --cidr 0.0.0.0/0
```

### Step 4: Launch EC2 Instance

```bash
# Find latest Ubuntu 24.04 AMI
AMI_ID=$(aws ec2 describe-images \
  --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
  --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
  --output text)

echo "Using AMI: $AMI_ID"

# Launch t2.micro (free tier)
aws ec2 run-instances \
  --image-id $AMI_ID \
  --instance-type t2.micro \
  --key-name autoclip-key \
  --security-groups autoclip-sg \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=autoclip-ai}]' \
  --count 1

# Wait 30 seconds, then get your public IP
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=autoclip-ai" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text
```

### Step 5: SSH into EC2 and Install Docker

```bash
ssh -i ~/.ssh/autoclip-key.pem ubuntu@<YOUR_EC2_IP>

# On the EC2 instance:
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu

# Add 2GB swap (prevents OOM crashes on t2.micro's 1GB RAM)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Log out and back in for docker group
exit
ssh -i ~/.ssh/autoclip-key.pem ubuntu@<YOUR_EC2_IP>

# Verify
docker --version
```

### Step 6: Clone and Configure

```bash
cd /home/ubuntu
git clone https://github.com/AnirudhGupta007/autoclip-ai.git
cd autoclip-ai

# Create production .env
nano .env
```

Add to .env:
```
GEMINI_API_KEY=your_key
ASSEMBLYAI_API_KEY=your_key
PEXELS_API_KEY=your_key
POSTGRES_PASSWORD=pick_a_strong_password
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your_key
LANGSMITH_PROJECT=Autoclip
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

### Step 7: Deploy

```bash
docker compose up -d --build
# Takes 5-10 minutes first time

# Verify
docker compose ps        # All 3 containers should be "Up"
curl http://localhost/api/health  # Should return {"status":"ok"}
```

Open `http://<YOUR_EC2_IP>` in browser.

### Step 8: Set Up CI/CD (GitHub Actions)

Go to your GitHub repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|--------|-------|
| `EC2_HOST` | Your EC2 public IP |
| `EC2_SSH_KEY` | Contents of `~/.ssh/autoclip-key.pem` |

Now every push to `main` auto-deploys.

---

## Day-to-Day Commands

```bash
# SSH into server
ssh -i ~/.ssh/autoclip-key.pem ubuntu@<EC2_IP>

# View logs
docker compose logs -f backend

# Restart after manual changes
docker compose up -d --build

# Check database
docker compose exec postgres psql -U autoclip -d autoclip

# Stop instance (save money)
aws ec2 stop-instances --instance-ids <INSTANCE_ID>

# Start instance (before interview)
aws ec2 start-instances --instance-ids <INSTANCE_ID>

# Get new IP after start
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=autoclip-ai" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
```

## Cost

| When stopped | $0/month (disk only, covered by free tier) |
|---|---|
| When running | $0/month (free tier: 750 hrs/month) |
| After free tier (12 months) | ~$10/month |
| **$100 credits** | **Lasts years if you stop when not using** |
