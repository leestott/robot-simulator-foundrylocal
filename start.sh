#!/usr/bin/env bash
# start.sh – Launch the Robot Simulator (Linux / macOS)
set -e
cd "$(dirname "$0")"

VENV_PYTHON=".venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[start] Virtual environment not found. Run setup.sh first."
    exit 1
fi

# Default to web mode unless --cli is passed
MODE="web"
EXTRA_ARGS=""

for arg in "$@"; do
    if [ "$arg" = "--cli" ]; then
        MODE="cli"
    else
        EXTRA_ARGS="$EXTRA_ARGS $arg"
    fi
done

if [ "$MODE" = "web" ]; then
    echo "[start] Starting Robot Simulator (Web UI) ..."
    echo "[start] Open http://localhost:8080 in your browser"
    echo
    "$VENV_PYTHON" -u -m src --web $EXTRA_ARGS
else
    echo "[start] Starting Robot Simulator (CLI) ..."
    echo
    "$VENV_PYTHON" -u -m src $EXTRA_ARGS
fi
