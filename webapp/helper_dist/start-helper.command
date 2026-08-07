#!/bin/bash
# AutoEditor Helper — double-click to run. No typing needed.
cd "$(dirname "$0")"
clear
echo "======================================================"
echo "   AutoEditor Helper"
echo "======================================================"
echo
# 1) Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "This needs Python. Opening the download page..."
  open "https://www.python.org/downloads/"
  echo "Install Python, then double-click this Start Helper file again."
  read -p "Press Return to close."; exit 0
fi
# 2) FFmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing FFmpeg (one time)..."; brew install ffmpeg
  else
    echo "This needs FFmpeg. The easiest way is Homebrew:"
    echo "  1) Open https://brew.sh and paste their install line, OR"
    echo "  2) ask the yellow Help button on the website."
    open "https://brew.sh"
    read -p "Press Return to close."; exit 0
  fi
fi
# 3) Python deps (quietly)
echo "Getting ready (first time takes a minute)..."
python3 -m pip install --user -q -r requirements.txt 2>/dev/null
echo
# 4) Run
python3 friend_helper.py
read -p "Helper stopped. Press Return to close."
