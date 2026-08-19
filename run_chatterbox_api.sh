#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
fi

# Cấu hình thư mục tạm trong dự án cho API
mkdir -p "$PWD/tmp/api"
export CHATTERBOX_API_DATA_DIR="${CHATTERBOX_API_DATA_DIR:-$PWD/tmp/api}"
export PYTHONUNBUFFERED=1
export HF_HUB_CACHE="$PWD/models"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export PYTHONPATH="src:${PYTHONPATH}"

PYTHON_BIN="python3"
if [ -f "venv/bin/python" ]; then
    PYTHON_BIN="venv/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "======================================================================="
echo "       CHATTERBOX TTS STUDIO — WEB GUI & REST API SERVER              "
echo "======================================================================="
echo "  🎨 Web GUI Studio:     http://${HOST}:${PORT}/"
echo "  🔌 REST API v1 Base:   http://${HOST}:${PORT}/api/v1/"
echo "  📖 API Swagger Docs:   http://${HOST}:${PORT}/docs"
echo "  📑 ReDoc Manual:       http://${HOST}:${PORT}/redoc"
echo "======================================================================="
echo

exec "$PYTHON_BIN" -m uvicorn api_app:app --host "$HOST" --port "$PORT"
