@echo off
REM start.bat – Launch the Robot Simulator (Windows cmd)
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [start] Virtual environment not found. Run setup.bat first.
    exit /b 1
)

set VENV_PYTHON=%~dp0.venv\Scripts\python.exe

REM Default to web mode unless --cli is passed
set MODE=web
set EXTRA_ARGS=

:parse
if "%~1"=="" goto run
if "%~1"=="--cli" (
    set MODE=cli
    shift
    goto parse
)
set EXTRA_ARGS=%EXTRA_ARGS% %1
shift
goto parse

:run
if "%MODE%"=="web" (
    echo [start] Starting Robot Simulator (Web UI) ...
    echo [start] Open http://localhost:8080 in your browser
    echo.
    "%VENV_PYTHON%" -u -m src --web %EXTRA_ARGS%
) else (
    echo [start] Starting Robot Simulator (CLI) ...
    echo.
    "%VENV_PYTHON%" -u -m src %EXTRA_ARGS%
)
