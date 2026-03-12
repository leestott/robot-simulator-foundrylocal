@echo off
REM setup.bat – Create .venv, activate it, and install dependencies (Windows cmd)
setlocal

cd /d "%~dp0"

set VENV_DIR=.venv

if not exist "%VENV_DIR%" (
    echo [setup] Creating virtual environment in %VENV_DIR% ...
    python -m venv %VENV_DIR%
) else (
    echo [setup] Virtual environment already exists at %VENV_DIR%
)

echo [setup] Activating virtual environment ...
call %VENV_DIR%\Scripts\activate.bat

echo [setup] Installing dependencies ...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo =============================================
echo   Setup complete!
echo   The venv is active in this session.
echo.
echo   To reactivate later, run:
echo     .venv\Scripts\activate.bat
echo.
echo   Start the app:
echo     python -m src.app
echo =============================================
