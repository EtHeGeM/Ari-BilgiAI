#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

# Optional: load env vars from .env (if present)
if [[ -f "$ROOT_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Creating venv: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

echo "Installing deps: chatbot/requirements.txt"
"$VENV_DIR/bin/pip" install -q -r chatbot/requirements.txt

echo "Starting API on http://$HOST:$PORT/"
exec "$VENV_DIR/bin/uvicorn" chatbot.api_server:app --host "$HOST" --port "$PORT"

