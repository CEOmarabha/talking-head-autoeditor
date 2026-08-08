#!/usr/bin/env bash
# Publish the website Worker only.
#
# NOTE: the friend Helper is a SIGNED desktop installer (.exe / .dmg) built
# by .github/workflows/helper-release.yml and uploaded to R2 under
# dist/helper/<target>/. It is NOT built or uploaded here. The old
# Python/terminal helper.zip path was removed on purpose — friends must
# never receive a Python source tree or run a terminal.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/webapp/worker"
echo "Publishing the website..."
npx wrangler deploy
echo
echo "Done. Website is live."
echo "Helper installers are published by the signed release workflow, not"
echo "by this script."
