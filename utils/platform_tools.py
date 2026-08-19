"""Small cross-platform helpers shared by desktop, API, and demos."""

import os
import subprocess
import sys
from pathlib import Path

import torch


def select_device(preference="auto"):
    """Return the requested available accelerator, or the best fallback."""
    if preference == "cpu":
        return "cpu"
    if preference in ("auto", "cuda") and torch.cuda.is_available():
        return "cuda"
    if preference in ("auto", "cuda", "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def clear_accelerator_cache():
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    elif torch.backends.mps.is_available():
        torch.mps.empty_cache()


def open_folder(path):
    """Open a directory with the operating system's file manager."""
    folder = str(Path(path))
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])


def primary_shortcut():
    """Return Tk's primary modifier and its user-facing label."""
    return ("Command", "⌘") if sys.platform == "darwin" else ("Control", "Ctrl")
