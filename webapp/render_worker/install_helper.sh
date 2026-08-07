#!/usr/bin/env bash
# One-time installer for the AutoEditor Helper (macOS / Linux).
# A friend runs this once; afterwards they just launch the helper.
set -e
echo "Installing the AutoEditor Helper..."

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg is required. Install it first:"
  echo "  macOS:  brew install ffmpeg"
  echo "  Linux:  sudo apt install ffmpeg"
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required (python.org/downloads)."
  exit 1
fi

DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # repo root
python3 -m pip install --user -r "$DIR/webapp/render_worker/requirements.txt"

echo
echo "Done. Start the helper any time with:"
echo "  python3 $DIR/webapp/render_worker/friend_helper.py"
