#!/usr/bin/env bash
# Setup-and-run launcher for ytwrangler.
# First run: creates the venv and installs requirements.
# Later runs: just launches the app. Uses the script's own folder (no cd).
set -e
DIR="$(dirname "${BASH_SOURCE[0]}")"
VENV="$DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "First run — creating virtual environment..."
    python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

if [ ! -f "$VENV/.deps-installed" ]; then
    echo "Installing dependencies (one time)..."
    pip install -q -r "$DIR/requirements.txt"
    touch "$VENV/.deps-installed"
fi

python "$DIR/main.py" "$@"
