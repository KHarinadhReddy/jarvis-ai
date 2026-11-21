@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment .venv...
  py -m venv .venv
)

echo Installing dependencies (local set, includes mic support)...
".venv\Scripts\python.exe" -m pip install -r requirements-local.txt

echo Starting JARVIS AI...
".venv\Scripts\python.exe" -m streamlit run jarvis_exact.py --server.port 8502

pause
