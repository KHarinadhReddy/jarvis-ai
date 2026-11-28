@echo off
REM J.A.R.V.I.S. One-click start: backend + ADB tunnel
REM Usage: run this while the emulator is running, then launch the app.

echo ============================================
echo   J.A.R.V.I.S. START SCRIPT
echo ============================================

REM --- Step 1: ADB reverse tunnel ---
echo [1/3] Setting up ADB reverse tunnel (tcp:8000 -> tcp:8000)...
call "%~dp0\android\setup_tunnel.bat" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Tunnel setup failed. Is the emulator running?
    echo         Start emulator: emulator -avd Medium_Phone
    pause
    exit /b 1
)
echo [OK] Tunnel active.

REM --- Step 2: Start backend in background ---
echo [2/3] Starting backend on port 8000...
cd /d "%~dp0\backend"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

start "" cmd /c "call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

REM --- Step 3: wait for backend health ---
echo [3/3] Waiting for backend health check (this takes ~5-10s)...
timeout /t 6 /nobreak >nul

echo.
echo ============================================
echo   J.A.R.V.I.S. stack started.
echo   Backend: http://127.0.0.1:8000/v1/health
echo   Tunnel: adb reverse tcp:8000 tcp:8000  (active)
echo ============================================
echo.
echo Next steps:
echo   1. Keep this window open (backend runs in child window) or check the backend window.
echo   2. Launch the app: adb shell am start -n ai.jarvis.mobile/.MainActivity
echo   3. In app: Settings > Backend link > Test link
echo.
pause
