#!/bin/bash
echo "======================================================================="
echo "              CHATTERBOX TTS STUDIO - CONSOLE LOGS                     "
echo "======================================================================="
echo "[SYSTEM] Starting Python environment..."
echo "[SYSTEM] Realtime console output enabled (PYTHONUNBUFFERED=1)"
echo

# Ensure we are in the script's directory
cd "$(dirname "$0")"

if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
fi

# Set unbuffered python output
export PYTHONUNBUFFERED=1

# Launch Python main application
exec python3 main.py
