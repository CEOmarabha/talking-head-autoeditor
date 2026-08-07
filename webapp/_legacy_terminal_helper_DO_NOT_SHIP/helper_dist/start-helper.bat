@echo off
title AutoEditor Helper
cd /d "%~dp0"
cls
echo ======================================================
echo    AutoEditor Helper
echo ======================================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo This needs Python. Opening the download page...
  start https://www.python.org/downloads/
  echo Install Python ^(tick "Add to PATH"^), then double-click Start Helper again.
  pause & exit /b
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  where winget >nul 2>nul
  if not errorlevel 1 (
    echo Installing FFmpeg ^(one time^)...
    winget install --id Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements
  ) else (
    echo This needs FFmpeg. Opening the download page...
    start https://www.gyan.dev/ffmpeg/builds/
    echo Install FFmpeg, then double-click Start Helper again.
    pause & exit /b
  )
)
echo Getting ready ^(first time takes a minute^)...
python -m pip install --user -q -r requirements.txt
echo.
python friend_helper.py
pause
