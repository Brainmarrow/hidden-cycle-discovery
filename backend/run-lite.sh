#!/usr/bin/env bash
# Hidden Cycle Discovery — Lite Local Runner (macOS/Linux, no Docker)
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate

if [ ! -f venv/.lite_installed ]; then
  echo "Installing dependencies (~500MB, first run takes a few minutes)..."
  pip install --upgrade pip
  pip install -r requirements-lite.txt
  touch venv/.lite_installed
else
  echo "Dependencies already installed, skipping."
fi

echo ""
echo "Starting engine on http://127.0.0.1:8741 ..."
echo "Data stored in: \$HOME/.hidden-cycle-discovery"
echo "API docs at:    http://127.0.0.1:8741/docs"
echo "Press Ctrl+C to stop."
echo ""

export DESKTOP_MODE=1
export HCD_PORT=8741
export DEBUG=true
python desktop_main.py
