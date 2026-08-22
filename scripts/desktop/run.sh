#!/bin/bash
set -e

# Resolve project root (parent of scripts/desktop/)
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "======================================================================="
echo "              CHATTERBOX TTS STUDIO - CONSOLE LOGS                     "
echo "======================================================================="
echo "[SYSTEM] Starting Python environment..."
echo "[SYSTEM] Realtime console output enabled (PYTHONUNBUFFERED=1)"
echo

if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
fi

export PYTHONUNBUFFERED=1
export PYTHONPATH="src:${PYTHONPATH}"

PYTHON_BIN="python3"
if [ -f "venv/bin/python" ]; then
    PYTHON_BIN="venv/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
fi

exec "$PYTHON_BIN" main.py
