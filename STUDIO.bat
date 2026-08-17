@echo off
REM Double-click to open the studio control panel: voices, speech, video, scenarios.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "tools\studio\control_panel.py"
) else (
  if not exist ".venv\Scripts\python.exe" (
    echo   [!] .venv not found - run this from the project folder.
    pause
    exit /b 1
  )
  .venv\Scripts\python.exe tools\studio\control_panel.py
)
