@echo off
setlocal enabledelayedexpansion
title Chatterbox TTS Studio - API & Web Server

cd /d "%~dp0"

:: Check for virtual environment
set "PYTHON_BIN=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_BIN=venv\Scripts\python.exe"
)

:: Configure default portable data directory
if not defined CHATTERBOX_API_DATA_DIR (
    if defined LOCALAPPDATA (
        set "CHATTERBOX_API_DATA_DIR=%LOCALAPPDATA%\Chatterbox\data"
    ) else (
        set "CHATTERBOX_API_DATA_DIR=%~dp0tmp\api"
    )
)
if not exist "%CHATTERBOX_API_DATA_DIR%" mkdir "%CHATTERBOX_API_DATA_DIR%"

set "PYTHONUNBUFFERED=1"
set "HF_HUB_CACHE=%~dp0models"
if not defined HF_HUB_OFFLINE set "HF_HUB_OFFLINE=1"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

:: Support --test flag
if "%~1"=="--test" (
    echo =======================================================================
    echo        CHATTERBOX TTS - CHAY KIEM THU TICH HOP (UNIT TESTS)
    echo =======================================================================
    set "CHATTERBOX_IN_PROCESS=1"
    "%PYTHON_BIN%" -m unittest discover -v tests/
    goto :eof
)
if "%~1"=="test" (
    echo =======================================================================
    echo        CHATTERBOX TTS - CHAY KIEM THU TICH HOP (UNIT TESTS)
    echo =======================================================================
    set "CHATTERBOX_IN_PROCESS=1"
    "%PYTHON_BIN%" -m unittest discover -v tests/
    goto :eof
)

if not defined HOST set "HOST=127.0.0.1"
if not defined PORT set "PORT=8000"

echo =======================================================================
echo        CHATTERBOX TTS STUDIO - WEB GUI & REST API SERVER (WINDOWS)
echo =======================================================================
echo   * Web GUI Studio:     http://%HOST%:%PORT%/
echo   * REST API v1 Base:   http://%HOST%:%PORT%/api/v1/
echo   * API Swagger Docs:   http://%HOST%:%PORT%/docs
echo   * ReDoc Manual:       http://%HOST%:%PORT%/redoc
echo   * Du lieu:            %CHATTERBOX_API_DATA_DIR%
echo =======================================================================
echo.

"%PYTHON_BIN%" -m uvicorn api_app:app --host "%HOST%" --port "%PORT%"
pause
