#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -d frontend/node_modules ]; then
  npm --prefix frontend ci
fi
npm --prefix frontend run build
if [ ! -f resources/law-index.json ]; then
  .venv/bin/python scripts/build_law_index.py
fi
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port "${GWOLLION_PORT:-8020}"
