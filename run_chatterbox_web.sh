#!/bin/bash
echo "======================================================================="
echo "              CHATTERBOX TTS STUDIO - WEB INTERFACE (LOCALHOST)         "
echo "======================================================================="
echo "[SYSTEM] Starting Web Server on http://127.0.0.1:7860..."
echo "[SYSTEM] Realtime console output enabled (PYTHONUNBUFFERED=1)"
echo

# Ensure we are in the script's directory
cd "$(dirname "$0")"

# Activate venv if exists and not yet activated
if [ -z "$VIRTUAL_ENV" ] && [ -f "venv/bin/activate" ]; then
    echo "[SYSTEM] Activating virtual environment (venv)..."
    source venv/bin/activate
fi

# Set unbuffered python output & pythonpath
export PYTHONUNBUFFERED=1
export PYTHONPATH="src:$PYTHONPATH"

# Launch Python web application
python3 web_app.py

echo
echo "======================================================================="
echo "[SYSTEM] Web server stopped."
