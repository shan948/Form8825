#!/usr/bin/env bash
# One-command demo: build the UI and serve UI + API on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"
(cd frontend && npm install --no-audit --no-fund && npm run build)
exec python -m uvicorn backend.app.main:app --port 8000
