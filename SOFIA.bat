@echo off
REM Double-click to open Sofia's text-to-speech window. One box, one button, no browser.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  if not exist ".venv\Scripts\python.exe" (
    echo   [!] .venv not found - run this from the project folder.
    pause
    exit /b 1
  )
  .venv\Scripts\python.exe tools\studio\sofia_app.py
  exit /b
)
REM pythonw so no console window tags along behind the app.
start "" ".venv\Scripts\pythonw.exe" "tools\studio\sofia_app.py"
