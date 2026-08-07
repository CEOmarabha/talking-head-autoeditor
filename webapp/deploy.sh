#!/usr/bin/env bash
# One command to publish everything. Run from anywhere.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
bash "$ROOT/webapp/build_helper_zip.sh"
cd "$ROOT/webapp/worker"
echo "Publishing the website..."
npx wrangler deploy
echo "Uploading the Helper download..."
npx wrangler r2 object put autoeditor-media/dist/helper.zip \
  --file "$ROOT/webapp/helper.zip" --content-type application/zip
echo
echo "Done. Site + Helper download are live."
