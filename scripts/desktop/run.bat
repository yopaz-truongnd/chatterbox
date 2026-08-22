@echo off
setlocal enabledelayedexpansion
title Chatterbox TTS Studio (Desktop GUI)

set "PROJECT_ROOT=%~dp0..\.."
cd /d "%PROJECT_ROOT%"

set "PYTHON_BIN=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_BIN=venv\Scripts\python.exe"
)

set "PYTHONUNBUFFERED=1"
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"

echo =======================================================================
echo               CHATTERBOX TTS STUDIO - CONSOLE LOGS
echo =======================================================================
echo [SYSTEM] Khoi chay moi truong Python...
echo [SYSTEM] Console output real-time (PYTHONUNBUFFERED=1)
echo.

"%PYTHON_BIN%" main.py
if errorlevel 1 pause
