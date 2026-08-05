@echo off
title Chatterbox TTS Studio - Realtime Logs Console
echo =======================================================================
echo               CHATTERBOX TTS STUDIO - CONSOLE LOGS                     
echo =======================================================================
echo [SYSTEM] Starting Python environment...
echo [SYSTEM] Realtime console output enabled (PYTHONUNBUFFERED=1)
echo.

cd /d "%~dp0"
set PYTHONUNBUFFERED=1

python main.py

echo.
echo =======================================================================
echo [SYSTEM] Ung dung Chatterbox TTS Studio da dong.
echo Nhan phim bat ky de thoat cua so CMD...
pause > nul
