#!/usr/bin/env bash
# setup.sh – Create .venv, activate it, and install dependencies (Linux/macOS)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "[setup] Creating virtual environment in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
else
    echo "[setup] Virtual environment already exists at $VENV_DIR"
fi

echo "[setup] Activating virtual environment ..."
source "$VENV_DIR/bin/activate"

echo "[setup] Installing dependencies ..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "============================================="
echo "  Setup complete!"
echo "  To activate the venv in your shell, run:"
echo "    source $VENV_DIR/bin/activate"
echo ""
echo "  Then start the app:"
echo "    python -m src.app"
echo "============================================="
