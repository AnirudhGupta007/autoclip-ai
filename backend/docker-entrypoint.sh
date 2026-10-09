#!/bin/sh
# Apply database migrations, then start the API.
# Pre-Alembic databases: 0001 only creates missing tables, so `upgrade head`
# is safe on them too (DEPLOY.md documents `alembic stamp 0001` as well).
set -e
cd /app
alembic upgrade head
exec "$@"
