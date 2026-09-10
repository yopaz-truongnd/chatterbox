#!/usr/bin/env python3
"""Root CLI entrypoint for Chatterbox Voice Director."""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.voice_cli import main

if __name__ == "__main__":
    sys.exit(main())
