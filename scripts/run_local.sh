#!/usr/bin/env bash
# Run the API locally with hot-reload.

set -euo pipefail

export CONQUEST_DEV_LOGIN="${CONQUEST_DEV_LOGIN:-1}"
export CONQUEST_JWT_SECRET="${CONQUEST_JWT_SECRET:-dev-secret-change-me-please-use-a-real-one}"

exec poetry run uvicorn conquest.main:app --reload --host 0.0.0.0 --port 8000
