#!/usr/bin/env bash
# Build the native Linux AppImage: dist/linux/MXL_Capybara_Editor_V2-x86_64.AppImage
#
# The AppImage holds a standalone CPython 3.10 (python-build-standalone: static Tcl/Tk and X11, glibc >= 2.17),
# Pillow + ttkbootstrap, the collector's modules taken from the base exe as 3.10 bytecode (extract_host.py), the
# editor's modules from src/, the language files and the Linux launcher. No Wine is involved, and nothing is
# installed on the system: everything stays in dist/ and .cache/ of this repository.
#
# Usage: packaging/build_appimage.sh [--appdir-only]
# Env:   BASE_DIR=<folder with the base exe>   PYTHON_DIR=<unpacked standalone python 3.10 to bundle>
#        PY_URL=<python-build-standalone tarball>   APPIMAGETOOL=<appimagetool binary>
set -euo pipefail
source "$(dirname "$0")/common.sh"
PY_URL="${PY_URL:-https://github.com/astral-sh/python-build-standalone/releases/download/20261009/cpython-3.10.22%2B20261009-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz}"
TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
PILLOW="pillow==10.4.0"          # the version in the Windows exe
TTKBOOTSTRAP="ttkbootstrap==2.2.7"
CACHE="$ROOT/.cache"
APPDIR="$ROOT/dist/linux/AppDir"
LOG="$ROOT/dist/linux/build.log"

find_base
rm -rf "$APPDIR"
mkdir -p "$APPDIR/opt/capybara/lang" "$CACHE"
: > "$LOG"

# 1. Python 3.10 to bundle
if [ -n "${PYTHON_DIR:-}" ]; then
    cp -rL "$PYTHON_DIR" "$APPDIR/opt/python"
else
    if [ ! -f "$CACHE/python310.tar.gz" ]; then
        echo "downloading Python 3.10"
        curl -fsSL -o "$CACHE/python310.tar.gz" "$PY_URL"
    fi
    tar -xzf "$CACHE/python310.tar.gz" -C "$APPDIR/opt"          # unpacks to opt/python
fi
PY="$APPDIR/opt/python/bin/python3.10"
rm -f "$APPDIR/opt/python/lib/python3.10/EXTERNALLY-MANAGED"
"$PY" -I -m pip install -q --no-warn-script-location --disable-pip-version-check "$PILLOW" "$TTKBOOTSTRAP" >>"$LOG" 2>&1 \
    || { tail -20 "$LOG"; exit 1; }

# 2. the application: host modules (bytecode), editor modules (source), languages, launcher
"$PY" -I "$ROOT/packaging/extract_host.py" "$BASE_EXE" "$APPDIR/opt/capybara" >>"$LOG"
cp "$ROOT"/src/mxl_*.py "$ROOT/packaging/linux/capybara_editor.py" "$APPDIR/opt/capybara/"
cp "$BASE_DIR"/_internal/lang/*.json "$APPDIR/opt/capybara/lang/" 2>/dev/null || true
cp "$ROOT"/lang/*.json "$APPDIR/opt/capybara/lang/"              # superset of the collector's files
"$PY" -I -m compileall -q "$APPDIR/opt/capybara" >>"$LOG"

# 3. slim the interpreter
PL="$APPDIR/opt/python/lib/python3.10"
for d in test idlelib ensurepip lib2to3 turtledemo tkinter/test unittest/test distutils/tests \
         site-packages/pip site-packages/setuptools; do
    rm -rf "${PL:?}/$d"
done
rm -rf "$APPDIR/opt/python/include" "$APPDIR/opt/python/share"
find "$APPDIR/opt/python" \( -name '*.a' -o -name 'config-3.10-*' \) -prune -exec rm -rf {} +

# 4. AppImage metadata
cp "$ROOT/packaging/linux/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp "$ROOT/packaging/linux/capybara-editor-v2.desktop" "$APPDIR/"
"$PY" -I "$ROOT/packaging/linux/write_icon.py" "$ROOT/src" "$APPDIR/capybara-editor-v2.png"
ln -sf capybara-editor-v2.png "$APPDIR/.DirIcon"
echo "AppDir ready: $APPDIR ($(du -sh "$APPDIR" | cut -f1))"
if [ "${1:-}" = "--appdir-only" ]; then exit 0; fi

# 5. pack
TOOL="${APPIMAGETOOL:-$(command -v appimagetool || true)}"
if [ -z "$TOOL" ]; then
    TOOL="$CACHE/appimagetool-x86_64.AppImage"
    if [ ! -x "$TOOL" ]; then
        echo "downloading appimagetool"
        curl -fsSL -o "$TOOL" "$TOOL_URL"
        chmod +x "$TOOL"
    fi
fi
OUT="$ROOT/dist/linux/MXL_Capybara_Editor_V2-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT" >>"$LOG" 2>&1 || { tail -20 "$LOG"; exit 1; }
echo "built: $OUT ($(du -h "$OUT" | cut -f1))"
