-- Runs once on first container start (Docker initdb hook).
-- Subsequent restarts skip this file because pgdata already exists.

CREATE EXTENSION IF NOT EXISTS vector;
