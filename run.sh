#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import fastapi, aiosqlite, pydantic_settings, piper" >/dev/null 2>&1; then
  echo "Instalando dependencias..."
  pip install -q -r requirements.txt
fi

PROVIDER=$(python -c "from app.config import get_settings; print(get_settings().ai_provider)")
OPENCODE_URL=$(python -c "from app.config import get_settings; print(get_settings().opencode_base_url)")

OPENCODE_PID=""
cleanup() {
  if [ -n "$OPENCODE_PID" ]; then
    kill "$OPENCODE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [ "$PROVIDER" = "opencode" ] && ! curl -sf -m 3 "$OPENCODE_URL/global/health" >/dev/null 2>&1; then
  OPENCODE_PORT=$(python -c "from urllib.parse import urlparse; from app.config import get_settings; print(urlparse(get_settings().opencode_base_url).port or 4097)")
  echo "Iniciando opencode serve na porta $OPENCODE_PORT..."
  opencode serve --port "$OPENCODE_PORT" --hostname 127.0.0.1 \
    > /tmp/opencode-serve.log 2>&1 &
  OPENCODE_PID=$!

  for _ in $(seq 1 40); do
    if curl -sf -m 2 "$OPENCODE_URL/global/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done

  if ! curl -sf -m 3 "$OPENCODE_URL/global/health" >/dev/null 2>&1; then
    echo "Falha ao iniciar opencode. Veja /tmp/opencode-serve.log" >&2
    exit 1
  fi
fi

HOST=$(python -c "from app.config import get_settings; print(get_settings().host)")
PORT=$(python -c "from app.config import get_settings; print(get_settings().port)")

echo "Bot disponivel em http://$HOST:$PORT (webhook: /webhook/evolution)"
uvicorn app.main:app --host "$HOST" --port "$PORT"
