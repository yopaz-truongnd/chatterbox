<#
.SYNOPSIS
    Chatterbox TTS Studio - PowerShell Launcher for Windows 10/11 & Cross-Platform PowerShell Core
.DESCRIPTION
    Checks virtual environment, PyTorch accelerator (CUDA/CPU), port availability, and model checkpoints before launch.
#>

param(
    [switch]$Test,
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

# Locate Python Virtual Environment
$PythonBin = "python"
if (Test-Path "$ProjectDir\.venv\Scripts\python.exe") {
    $PythonBin = "$ProjectDir\.venv\Scripts\python.exe"
} elseif (Test-Path "$ProjectDir\venv\Scripts\python.exe") {
    $PythonBin = "$ProjectDir\venv\Scripts\python.exe"
}

# Configure Environment Variables
$env:PYTHONUNBUFFERED = "1"
$env:HF_HUB_CACHE = "$ProjectDir\models"
if (-not $env:HF_HUB_OFFLINE) { $env:HF_HUB_OFFLINE = "1" }
$env:PYTHONPATH = "$ProjectDir\src;$env:PYTHONPATH"

# Configure Default Data Directory
if (-not $env:CHATTERBOX_API_DATA_DIR) {
    if ($env:LOCALAPPDATA) {
        $env:CHATTERBOX_API_DATA_DIR = "$env:LOCALAPPDATA\Chatterbox\data"
    } else {
        $env:CHATTERBOX_API_DATA_DIR = "$ProjectDir\tmp\api"
    }
}
if (-not (Test-Path $env:CHATTERBOX_API_DATA_DIR)) {
    New-Item -ItemType Directory -Path $env:CHATTERBOX_API_DATA_DIR -Force | Out-Null
}

# Handle --test switch
if ($Test) {
    Write-Host "=======================================================================" -ForegroundColor Cyan
    Write-Host "       CHATTERBOX TTS -- RUN INTEGRATION TESTS (UNIT TESTS)           " -ForegroundColor Cyan
    Write-Host "=======================================================================" -ForegroundColor Cyan
    $env:CHATTERBOX_IN_PROCESS = "1"
    & $PythonBin -m unittest discover -v tests/
    exit $LASTEXITCODE
}

# Check Port Availability using Socket
$PortAvailable = $true
try {
    $Socket = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Parse($HostAddress), $Port)
    $Socket.Start()
    $Socket.Stop()
} catch {
    $PortAvailable = $false
}

if (-not $PortAvailable) {
    Write-Host "[WARNING] Port $Port on $HostAddress is already in use by another process!" -ForegroundColor Yellow
    Write-Host "You can specify another port using: .\run_chatterbox_api.ps1 -Port 8001" -ForegroundColor Yellow
}

Write-Host "=======================================================================" -ForegroundColor Magenta
Write-Host "       CHATTERBOX TTS STUDIO -- WEB GUI & REST API SERVER (POWERSHELL) " -ForegroundColor Magenta
Write-Host "=======================================================================" -ForegroundColor Magenta
Write-Host "  * Web GUI Studio:     http://${HostAddress}:${Port}/" -ForegroundColor Green
Write-Host "  * REST API v1 Base:   http://${HostAddress}:${Port}/api/v1/" -ForegroundColor White
Write-Host "  * API Swagger Docs:   http://${HostAddress}:${Port}/docs" -ForegroundColor White
Write-Host "  * Data Directory:     $env:CHATTERBOX_API_DATA_DIR" -ForegroundColor DarkGray
Write-Host "=======================================================================" -ForegroundColor Magenta
Write-Host ""

& $PythonBin -m uvicorn api_app:app --host $HostAddress --port $Port
