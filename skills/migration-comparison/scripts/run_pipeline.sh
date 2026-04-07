#!/usr/bin/env bash
# Usage: ./run_pipeline.sh <script.py> [args...]
#
# Sets up a virtual environment with required dependencies,
# then runs the specified Python script.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
REQUIREMENTS="${SCRIPT_DIR}/requirements.txt"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  if command -v uv &>/dev/null; then
    uv venv "$VENV_DIR"
    uv pip install --python "$VENV_DIR/bin/python" -r "$REQUIREMENTS"
  else
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS"
  fi
fi

exec "$VENV_DIR/bin/python" "$@"
