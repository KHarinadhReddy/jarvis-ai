@echo off
REM J.A.R.V.I.S. Android - one-click APK build + install + launch
REM Requires: Android Studio JDK (JAVA_HOME), Android SDK adb/emulator.

set "JAVA_HOME=C:\Program Files\Android\Android Studio\jbr"
set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
set "APK=C:\Users\RAMULUREDDY\Music\jarvis_openrouter_voice_ai\jarvis-os\android\app\build\outputs\apk\debug\app-debug.apk"

echo ============================================
echo   J.A.R.V.I.S. APK UPDATE
echo ============================================

echo [1/3] Building debug APK...
cd /d "C:\Users\RAMULUREDDY\Music\jarvis_openrouter_voice_ai\jarvis-os\android"
call "%JAVA_HOME%\bin\gradlew.bat" :app:assembleDebug --no-daemon --console=plain

if errorlevel 1 (
    echo [ERROR] Build failed. See gradle output above.
    pause
    exit /b 1
)

echo [2/3] Installing APK...
if not exist "%APK%" (
    echo [ERROR] APK not found at %APK%
    pause
    exit /b 1
)
"%ADB%" install -r "%APK%"

if errorlevel 1 (
    echo [ERROR] Install failed.
    pause
    exit /b 1
)

echo [3/3] Launching app...
"%ADB%" shell am start --display 0 -n ai.jarvis.mobile/.MainActivity

echo.
echo ============================================
echo   J.A.R.V.I.S. APK updated and launched.
echo ============================================
pause
