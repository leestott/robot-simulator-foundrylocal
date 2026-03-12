# setup.ps1 – Create .venv, activate it, and install dependencies (Windows PowerShell)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$VenvDir = ".venv"

if (-not (Test-Path $VenvDir)) {
    Write-Host "[setup] Creating virtual environment in $VenvDir ..."
    python -m venv $VenvDir
} else {
    Write-Host "[setup] Virtual environment already exists at $VenvDir"
}

Write-Host "[setup] Activating virtual environment ..."
& "$VenvDir\Scripts\Activate.ps1"

Write-Host "[setup] Installing dependencies ..."
python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host ""
Write-Host "============================================="
Write-Host "  Setup complete!"
Write-Host "  The venv is active in this session."
Write-Host ""
Write-Host "  To reactivate later, run:"
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "  Start the app:"
Write-Host "    python -m src.app"
Write-Host "============================================="
