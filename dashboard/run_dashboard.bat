@echo off
REM ---------------------------------------------------------------------------
REM Launch the GB carbon intensity dashboard.
REM
REM Double-click this file, or run it from a terminal. It calls the pypsa-gb
REM environment interpreter directly, so it works without activating conda (the
REM PowerShell conda hook is blocked by execution policy on this machine).
REM
REM If the environment lives elsewhere, edit the PY path below.
REM ---------------------------------------------------------------------------
set "PY=C:\Users\user\miniforge3\envs\pypsa-gb\python.exe"

REM Repository root is one level up from this dashboard/ folder.
cd /d "%~dp0.."

if not exist "%PY%" (
  echo Could not find the Python interpreter at:
  echo   %PY%
  echo Edit the PY path in run_dashboard.bat, or run:
  echo   conda activate pypsa-gb ^&^& streamlit run dashboard\app.py
  pause
  exit /b 1
)

echo Starting the dashboard. It will open in your browser at http://localhost:8501
echo Press Ctrl+C in this window to stop it.
"%PY%" -m streamlit run dashboard\app.py
pause
