#!/usr/bin/env bash
# Nightly Postgres backup: pg_dump -> gzip -> S3. Runs on the EC2 host (not
# in the backend image), from the repo checkout, e.g. via cron:
#
#   15 2 * * * BACKUP_S3_BUCKET=my-bucket /opt/autoclip/backend/scripts/backup_db.sh >> /var/log/autoclip-backup.log 2>&1
#
# Needs: docker compose (the postgres service running), gzip, and the AWS
# CLI with credentials that may s3:PutObject into the bucket (on EC2: the
# instance role). Nothing here creates AWS resources — see DEPLOY.md.
#
# Env:
#   BACKUP_S3_BUCKET   required, bucket name (no s3:// prefix)
#   BACKUP_S3_PREFIX   key prefix, default "autoclip/db"
#   AWS_REGION         default ap-south-1
#   BACKUP_DIR         local copies, default ~/autoclip-backups
#   BACKUP_KEEP_LOCAL  local dumps to keep, default 7
#   COMPOSE_FILES      default "-f docker-compose.yml -f docker-compose.prod.yml"
set -euo pipefail

: "${BACKUP_S3_BUCKET:?set BACKUP_S3_BUCKET to the bucket name}"
PREFIX="${BACKUP_S3_PREFIX:-autoclip/db}"
REGION="${AWS_REGION:-ap-south-1}"
DIR="${BACKUP_DIR:-$HOME/autoclip-backups}"
KEEP="${BACKUP_KEEP_LOCAL:-7}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"

cd "$(dirname "$0")/../.."          # repo root (where the compose files live)
mkdir -p "$DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$DIR/autoclip-$STAMP.sql.gz"

# Custom-format dumps can't be streamed through gzip usefully; plain SQL can,
# and restores with `gunzip -c file | psql`. --clean/--if-exists make the
# restore idempotent on an existing database.
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T postgres \
  pg_dump -U autoclip -d autoclip --clean --if-exists --no-owner \
  | gzip -9 > "$FILE.part"
mv "$FILE.part" "$FILE"

# A dump of an empty/broken DB is a few hundred bytes — refuse to upload it.
SIZE=$(stat -c %s "$FILE")
if [ "$SIZE" -lt 1024 ]; then
  echo "backup_db: $FILE is only $SIZE bytes, not uploading" >&2
  exit 1
fi

aws s3 cp "$FILE" "s3://$BACKUP_S3_BUCKET/$PREFIX/$(basename "$FILE")" \
  --region "$REGION" --only-show-errors
echo "backup_db: uploaded $(basename "$FILE") ($SIZE bytes) to s3://$BACKUP_S3_BUCKET/$PREFIX/"

# Keep the newest $KEEP local copies.
ls -1t "$DIR"/autoclip-*.sql.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
