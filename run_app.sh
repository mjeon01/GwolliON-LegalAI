#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -f resources/law-index.json ]; then
  .venv/bin/python scripts/build_law_index.py
fi
exec .venv/bin/python -m uvicorn mvp.app:app --host 127.0.0.1 --port "${GWOLLION_PORT:-8020}"
