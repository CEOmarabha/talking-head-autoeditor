#!/usr/bin/env bash
# Assemble the friend Helper download from repo sources -> helper.zip
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
cp -r "$ROOT/autoeditor" "$STAGE/"
cp -r "$ROOT/profiles" "$STAGE/"
cp "$ROOT/brand.yaml" "$STAGE/"
mkdir -p "$STAGE/webapp/render_worker"
cp "$ROOT/webapp/__init__.py" "$STAGE/webapp/"
cp "$ROOT/webapp/render_worker_compat.py" "$STAGE/webapp/"
cp "$ROOT/webapp/render_worker/"*.py "$STAGE/webapp/render_worker/"
cp "$ROOT/webapp/render_worker/requirements.txt" "$STAGE/"
cp "$ROOT/webapp/helper_dist/friend_helper.py" "$STAGE/"
cp "$ROOT/webapp/helper_dist/start-helper.command" "$STAGE/"
cp "$ROOT/webapp/helper_dist/start-helper.bat" "$STAGE/"
cp "$ROOT/webapp/helper_dist/READ-ME-FIRST.txt" "$STAGE/"
chmod +x "$STAGE/start-helper.command"
OUT="$ROOT/webapp/helper.zip"
rm -f "$OUT"
( cd "$STAGE" && zip -qr "$OUT" . -x '*.pyc' -x '*__pycache__*' )
rm -rf "$STAGE"
echo "built $OUT"
