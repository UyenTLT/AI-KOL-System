@echo off
REM Double-click this to type lines and hear them spoken. No browser involved.
REM
REM The browser on this machine reaches the local pages and then fails to render them, so the
REM web studio is not a usable path here. This is the same features from a terminal window.
setlocal
cd /d "%~dp0"

echo.
echo   Voice Studio - terminal edition
echo   -------------------------------
echo   Type a line and press Enter to hear it.
echo.
echo     voice              switch speaker
echo     speed 1.2          change pace
echo     scenario ^<brief^>   she writes the script herself
echo     quit               exit
echo.
echo   Every clip is also saved to:  %~dp0renders\
echo.

if not exist ".venv\Scripts\python.exe" (
  echo   [!] .venv not found - run this from the project folder.
  pause
  exit /b 1
)

.venv\Scripts\python.exe tools\studio\say.py
echo.
pause
