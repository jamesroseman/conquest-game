#!/usr/bin/env bash
# Start the Firestore emulator on localhost:8080.
# Tests and local dev point at it via FIRESTORE_EMULATOR_HOST.

set -euo pipefail

if ! command -v gcloud >/dev/null; then
  echo "gcloud is required (install: https://cloud.google.com/sdk/docs/install)"
  exit 1
fi

PORT="${FIRESTORE_EMULATOR_PORT:-8080}"
echo "Starting Firestore emulator on :${PORT}..."
exec gcloud emulators firestore start --host-port="localhost:${PORT}"
