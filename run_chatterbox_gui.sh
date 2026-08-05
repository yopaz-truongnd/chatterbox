#!/bin/bash
echo "======================================================================="
echo "              CHATTERBOX TTS STUDIO - CONSOLE LOGS                     "
echo "======================================================================="
echo "[SYSTEM] Starting Python environment on Linux..."
echo "[SYSTEM] Realtime console output enabled (PYTHONUNBUFFERED=1)"
echo

# Ensure we are in the script's directory
cd "$(dirname "$0")"

# Set unbuffered python output
export PYTHONUNBUFFERED=1

# Launch Python main application
python3 main.py

echo
echo "======================================================================="
echo "[SYSTEM] Application closed."
