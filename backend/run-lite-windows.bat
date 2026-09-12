@echo off
REM ============================================================
REM  Hidden Cycle Discovery — Lite Local Runner (Windows, no Docker)
REM  For low-RAM machines. Uses SQLite + fakeredis + eager tasks.
REM  Skips PyTorch (AI Models module) to keep install ~500MB, not ~5GB.
REM ============================================================
setlocal

echo.
echo === Hidden Cycle Discovery - Lite Setup ===
echo.

REM 1. Create venv if it doesn't exist yet
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM 2. Activate it
call venv\Scripts\activate.bat

REM 3. Install lite dependencies (first run only — skips if already installed)
if not exist venv\.lite_installed (
    echo Installing dependencies (~500MB, first run takes a few minutes)...
    pip install --upgrade pip
    pip install -r requirements-lite.txt
    echo done > venv\.lite_installed
) else (
    echo Dependencies already installed, skipping.
)

REM 4. Run the engine
echo.
echo Starting engine on http://127.0.0.1:8741 ...
echo Data stored in: %USERPROFILE%\.hidden-cycle-discovery
echo API docs at:    http://127.0.0.1:8741/docs
echo Press Ctrl+C to stop.
echo.

set DESKTOP_MODE=1
set HCD_PORT=8741
set DEBUG=true
python desktop_main.py

pause
