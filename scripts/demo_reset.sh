#!/usr/bin/env bash
# Reseed the demo data on a running server (keeps the debate cache, so re-running the demo is free).
set -euo pipefail
curl -s -X POST "${ARBITER_URL:-http://localhost:8000}/api/demo/reset" -H 'Content-Type: application/json' -d '{}'
echo
