@echo off
REM Double-click this, type a line, get a lip-synced mp4 in renders\ and opened for you.
REM
REM Same pipeline the avatar uses live, rendered to a file instead of streamed to a browser.
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist "LiveTalking\.venv\Scripts\python.exe" (
  echo   [!] LiveTalking venv not found.
  pause
  exit /b 1
)

echo.
echo   Talking video for Sofia
echo   -----------------------
echo   Type what she should say, then press Enter. Blank line to quit.
echo   Renders take roughly one second per three seconds of speech.
echo.

:loop
set "LINE="
set /p "LINE=say> "
if "!LINE!"=="" goto :done

REM %TIME% contains colons and spaces, neither of which belong in a filename.
set "STAMP=%TIME::=%"
set "STAMP=!STAMP: =0!"
set "STAMP=!STAMP:.=!"
set "OUT=renders\talk-!STAMP!.mp4"

echo   rendering...
LiveTalking\.venv\Scripts\python.exe tools\livetalking\render_video.py sofia-vargas ^
  --text "!LINE!" --avatar-id sofia-vargas_v2 --out "!OUT!"

if exist "!OUT!" (
  echo   opening !OUT!
  start "" "!OUT!"
) else (
  echo   [!] render failed - see the messages above.
)
echo.
goto :loop

:done
echo.
echo   Clips are in %~dp0renders\
pause
