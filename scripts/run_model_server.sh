#!/bin/sh
# Run the clause model server on this Mac (Apple GPU via MPS) for the booth demo.
#   sh scripts/run_model_server.sh           # serves http://127.0.0.1:7860, key required
# Then, in another terminal, expose it:  ngrok http 7860 --url=<your-static-domain>.ngrok-free.app
# Vercel: GWOLLION_CLAUSE_MODEL_URL=https://<your-static-domain>.ngrok-free.app
#         GWOLLION_CLAUSE_MODEL_KEY=<contents of var/model-server.key>
set -eu
cd "$(dirname "$0")/.."
KEY_FILE=var/model-server.key
if [ ! -s "$KEY_FILE" ]; then
  mkdir -p var
  (umask 077; .venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))" > "$KEY_FILE")
  echo "새 API 키를 만들었습니다: $KEY_FILE (Vercel GWOLLION_CLAUSE_MODEL_KEY에 넣으세요)"
fi
export API_KEY="$(cat "$KEY_FILE")" REQUIRE_API_KEY=1 MODEL_DIR="${MODEL_DIR:-$PWD/var/ml/clause/v2}"
export PYTHONPATH="$PWD/backend" PORT="${PORT:-7860}" HF_HUB_OFFLINE=1
exec .venv/bin/python model_server/app.py
