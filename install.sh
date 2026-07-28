#!/usr/bin/env bash
# One-time setup. Safe to re-run: every step is idempotent.
set -euo pipefail

BLUE=$'\033[1;34m'; GREEN=$'\033[1;32m'; YELL=$'\033[1;33m'; RESET=$'\033[0m'
step() { echo "${BLUE}==>${RESET} $*"; }
ok()   { echo "${GREEN} ok${RESET} $*"; }
warn() { echo "${YELL} !!${RESET} $*"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${AUTOEDITOR_HOME:-$HOME/.autoeditor}"

step "Checking system dependencies"
if ! command -v ffmpeg >/dev/null; then
  warn "ffmpeg not found"
  if [[ "$(uname)" == "Darwin" ]]; then
    command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
    brew install ffmpeg
  else
    sudo apt-get update && sudo apt-get install -y ffmpeg
  fi
fi
ok "ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3)"

PY="$(command -v python3.12 || command -v python3.11 || command -v python3)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' \
  || { echo "Python 3.10+ required (found $($PY -V))"; exit 1; }
ok "python $($PY -V | cut -d' ' -f2)"

step "Creating virtualenv at $ROOT/.venv"
[[ -d "$ROOT/.venv" ]] || "$PY" -m venv "$ROOT/.venv"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r "$ROOT/requirements.txt"
ok "python packages installed"

step "Preparing data directory: $DATA"
mkdir -p "$DATA/broll_cache" "$DATA/sfx"
ok "cache + sfx directories ready"

step "Warming the speech model (one-time ~150MB download)"
python - <<'PY'
from faster_whisper import WhisperModel
WhisperModel("small", device="cpu", compute_type="int8")
print("   speech model cached")
PY
ok "transcription ready"

step "Optional: animated diagram renderer (Remotion, needs Node 18+)"
if command -v node >/dev/null && command -v npm >/dev/null; then
  if [[ ! -d "$DATA/remotion-viz/node_modules" ]]; then
    mkdir -p "$DATA/remotion-viz"
    cp -R "$ROOT/templates/remotion-viz/." "$DATA/remotion-viz/"
    (cd "$DATA/remotion-viz" && npm install --silent) && ok "diagram renderer installed"
  else
    ok "diagram renderer already installed"
  fi
else
  warn "Node not found, animated diagrams will be skipped (everything else works)"
fi

step "Config files"
[[ -f "$ROOT/.env" ]] || { cp "$ROOT/.env.example" "$ROOT/.env"; ok "created .env (add your keys)"; }
[[ -f "$ROOT/brand.yaml" ]] && ok "brand.yaml present"

cat <<EOF

${GREEN}Setup complete.${RESET}

  1. Add at least one API key to  ${ROOT}/.env
       DEEPSEEK_API_KEY=xxx  (the creative brain, about 1c per video)
       PEXELS_API_KEY=xxx    (free stock b-roll)
  2. Set your colours and font in  ${ROOT}/brand.yaml
  3. If RAW sync needs correction, calibrate and certify that recording:
       make calibrate VIDEO=/path/to/raw.mov
       make certify VIDEO=/path/to/raw.mov OFFSET=0
  4. Edit a video:
       make edit VIDEO=/path/to/raw.mov

  No keys at all? It still runs, you get a cut, captioned, loudness-normalised,
  fully verified video, just with fewer creative flourishes.
EOF
