<#
.SYNOPSIS
    Chatterbox TTS Studio - PowerShell Server Launcher (Windows)
#>

$ProjectRoot = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $ProjectRoot

# Activate Virtual Environment
$PythonBin = "python"
if (Test-Path "$ProjectRoot\.venv\Scripts\python.exe") {
    $PythonBin = "$ProjectRoot\.venv\Scripts\python.exe"
} elseif (Test-Path "$ProjectRoot\venv\Scripts\python.exe") {
    $PythonBin = "$ProjectRoot\venv\Scripts\python.exe"
}

# Configure environment
if (-not $env:CHATTERBOX_API_DATA_DIR) {
    if ($env:LOCALAPPDATA) {
        $env:CHATTERBOX_API_DATA_DIR = "$env:LOCALAPPDATA\Chatterbox\data"
    } else {
        $env:CHATTERBOX_API_DATA_DIR = "$ProjectRoot\tmp\api"
    }
}
if (-not (Test-Path $env:CHATTERBOX_API_DATA_DIR)) {
    New-Item -ItemType Directory -Path $env:CHATTERBOX_API_DATA_DIR -Force | Out-Null
}

$env:PYTHONUNBUFFERED = "1"
$env:HF_HUB_CACHE = "$ProjectRoot\models"
if (-not $env:HF_HUB_OFFLINE) { $env:HF_HUB_OFFLINE = "1" }
$env:PYTHONPATH = "$ProjectRoot\src;$env:PYTHONPATH"

# Run tests
if ($args[0] -eq "--test" -or $args[0] -eq "test") {
    Write-Host "=======================================================================" -ForegroundColor Cyan
    Write-Host "       CHATTERBOX TTS -- CHAY KIEM THU TICH HOP (UNIT TESTS)           " -ForegroundColor Cyan
    Write-Host "=======================================================================" -ForegroundColor Cyan
    $env:CHATTERBOX_IN_PROCESS = "1"
    & $PythonBin -m unittest discover -v tests/
    exit $LASTEXITCODE
}

$HostAddr = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$Port = if ($env:PORT) { $env:PORT } else { "8000" }

Write-Host "=======================================================================" -ForegroundColor Magenta
Write-Host "       CHATTERBOX TTS STUDIO -- WEB GUI & REST API SERVER (POWERSHELL)  " -ForegroundColor Magenta
Write-Host "=======================================================================" -ForegroundColor Magenta
Write-Host "  * Web GUI Studio:     http://$HostAddr`:$Port/" -ForegroundColor Green
Write-Host "  * REST API v1 Base:   http://$HostAddr`:$Port/api/v1/" -ForegroundColor Green
Write-Host "  * API Swagger Docs:   http://$HostAddr`:$Port/docs" -ForegroundColor Green
Write-Host "  * Du lieu:            $env:CHATTERBOX_API_DATA_DIR" -ForegroundColor DarkGray
Write-Host "=======================================================================" -ForegroundColor Magenta

& $PythonBin -m uvicorn api_app:app --host $HostAddr --port $Port
