#!/usr/bin/env bash
# Build the Windows release folder on Linux (or Git Bash): dist/windows/MXL Capybara Editor V2/
# repack.py only rewrites the PyInstaller archive, so no Windows tools or Wine are needed to build.
# Env: BASE_DIR=<folder with the base exe and _internal/>, PYTHON310=<python 3.10>.
set -euo pipefail
source "$(dirname "$0")/common.sh"
find_base
find_python310
OUT="$ROOT/dist/windows/$APP_TITLE"
rm -rf "$OUT"
mkdir -p "$OUT/lang"
cp -r "$BASE_DIR/_internal" "$OUT/_internal"
cp "$ROOT"/lang/*.json "$OUT/lang/"
cp "$ROOT"/src/*.json "$OUT/_internal/"          # data files read next to the modules (dirname(__file__))
"$PY310" "$ROOT/src/repack.py" "$BASE_EXE" "$OUT/$APP_TITLE.exe" --icon="$ROOT/src/capybara.ico"
if command -v zip >/dev/null 2>&1; then
    ZIP="$ROOT/dist/windows/MXL-Capybara-Editor-V2-windows.zip"
    rm -f "$ZIP"
    (cd "$ROOT/dist/windows" && zip -q -r "$ZIP" "$APP_TITLE")
    echo "zip: $ZIP"
fi
echo "built: $OUT"
