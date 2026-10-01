#!/usr/bin/env bash
# Start Arbiter (API + dashboard) on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 run.py "$@"
