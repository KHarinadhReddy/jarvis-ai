@echo off
REM J.A.R.V.I.S. Backend - one-click start
REM Runs the FastAPI backend on http://0.0.0.0:8000
REM Pair with: jarvis-os/android/setup_tunnel.bat (adb reverse)

cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv not found. Run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ============================================
echo   J.A.R.V.I.S. Backend starting on :8000
echo   Health: http://127.0.0.1:8000/v1/health
echo ============================================

call .venv\Scripts\activate.bat
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
