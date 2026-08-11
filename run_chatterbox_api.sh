#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ -z "$VIRTUAL_ENV" ] && [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

export PYTHONUNBUFFERED=1
export HF_HUB_CACHE="$PWD/models"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export PYTHONPATH="src:${PYTHONPATH}"

exec python3 -m uvicorn api_app:app --host 127.0.0.1 --port 8000
