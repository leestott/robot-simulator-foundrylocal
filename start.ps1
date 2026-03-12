# start.ps1 – Launch the Robot Simulator (Windows PowerShell)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[start] Virtual environment not found. Run .\setup.ps1 first."
    exit 1
}

# Parse arguments – default to web mode
$Mode = "web"
$ExtraArgs = @()

foreach ($arg in $args) {
    if ($arg -eq "--cli") {
        $Mode = "cli"
    } else {
        $ExtraArgs += $arg
    }
}

# Use -u for unbuffered output so logs appear in real time
if ($Mode -eq "web") {
    Write-Host "[start] Starting Robot Simulator (Web UI) ..."
    Write-Host "[start] Open http://localhost:8080 in your browser"
    Write-Host ""
    & $VenvPython -u -m src --web @ExtraArgs
} else {
    Write-Host "[start] Starting Robot Simulator (CLI) ..."
    Write-Host ""
    & $VenvPython -u -m src @ExtraArgs
}
