@echo off
REM J.A.R.V.I.S. Android - ADB reverse tunnel
REM Makes the Windows backend reachable from the emulator via http://127.0.0.1:8000
REM Run this after every emulator restart.

set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"

if not exist "%ADB%" (
    echo ERROR: adb.exe not found at %ADB%
    echo Install Android SDK platform-tools or fix the path.
    pause
    exit /b 1
)

echo ============================================
echo   J.A.R.V.I.S. Tunnel: tcp:8000 -> tcp:8000
echo ============================================

"%ADB%" reverse tcp:8000 tcp:8000
if errorlevel 1 (
    echo.
    echo ERROR: adb reverse failed. Is the emulator running?
    echo   Start it: emulator -avd Medium_Phone
    pause
    exit /b 1
)

echo.
echo Tunnel active. The app can now reach the backend at http://127.0.0.1:8000
echo Keep this window open while testing, or run the command again after restarting the emulator.
pause
