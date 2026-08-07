# Legacy terminal Helper — DO NOT SHIP TO FRIENDS

These files (friend_helper.py, start-helper.command/.bat, build_helper_zip.sh,
install_helper.sh) are the OLD Python/terminal Helper. They require Python,
FFmpeg, and a terminal, which violates the "one signed installer, no dev
tools" bar. They are kept only for reference/history and are excluded from
deploy.sh. The real friend Helper is the signed Electron installer built by
.github/workflows/helper-release.yml.
