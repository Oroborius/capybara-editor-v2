#!/usr/bin/env bash
# Headless regression suite of MXL Capybara Editor V2 (details: tests/README.md).
#
#   tools/run_tests.sh [--quick] [-k SUBSTRING]... [--list] [--keep] [--timeout SECONDS]
#
#   --quick   data + engine tests only (no window, no X server)
#   -k TEXT   only tests whose id contains TEXT (file::name[variant]); may be given several times
#   --list    print the test ids
#   --keep    keep the session folder (copies of the fixtures, output of every test process)
#
# Fixtures (the user's game data: never committed, always COPIED, never written):
#   MXL_TEST_USER_DIR   user folder with the extracted game tables     (default /tmp/opencode/fakehome)
#   MXL_TEST_SAVE_DIR   folder with sample saves (*.d2s + *.stash)     (default /tmp/opencode/fakesaves)
#   MXL_TEST_SAVE_DIR2  optional second sample (honorific item)        (default /tmp/claude-1000/honorific-sample)
#   MXL_TEST_SAVE_DIR3  optional third sample: test-druid, checked against in-game stat screen screenshots
#                       (default .cache/samples/owlie of this checkout, else of the main checkout)
#   MXL_TEST_TMP        where the session folder is made               (default: system temp folder)
# Build inputs, only used when dist/linux/AppDir does not exist yet (see packaging/build_appimage.sh):
#   BASE_DIR, PYTHON_DIR
# The application always runs on an X server of its own (xvfb-run), never on the real display, and with
# MXL_USER_DIR / MXL_SAVE_DIR pointing at the copies.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPDIR="$ROOT/dist/linux/AppDir"
PY="$APPDIR/opt/python/bin/python3.10"

# the base exe (build + packaging tests): BASE_DIR, else what packaging/fetch_base.sh downloaded into .cache/,
# else - in a git worktree, which has no .cache/ of its own - the main checkout's
if [ -z "${BASE_DIR:-}" ]; then
    BASE_DIR="$(ls -d "$ROOT"/.cache/base/*/ 2>/dev/null | head -1 || true)"
fi
if [ -z "${BASE_DIR:-}" ]; then
    MAIN="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
    if [ -n "$MAIN" ]; then
        BASE_DIR="$(ls -d "$(dirname "$MAIN")"/.cache/base/*/ 2>/dev/null | head -1 || true)"
    fi
fi
BASE_DIR="${BASE_DIR%/}"

if [ ! -x "$PY" ] || [ ! -f "$APPDIR/opt/capybara/mxl_gui.pyc" ]; then
    echo "building the application folder (packaging/build_appimage.sh --appdir-only)"
    if [ -n "$BASE_DIR" ]; then
        BASE_DIR="$BASE_DIR" "$ROOT/packaging/build_appimage.sh" --appdir-only
    else
        "$ROOT/packaging/build_appimage.sh" --appdir-only
    fi
fi
# the tests always run the modules of src/ as they are now
cp "$ROOT"/src/mxl_*.py "$ROOT"/src/*.json "$ROOT/packaging/linux/capybara_editor.py" "$APPDIR/opt/capybara/"
cp "$ROOT"/lang/*.json "$APPDIR/opt/capybara/lang/"
rm -rf "$APPDIR/opt/capybara/__pycache__"

export CAPY_APPDIR="$APPDIR"
export CAPY_REPO="$ROOT"
export CAPY_BASE_DIR="$BASE_DIR"
export CAPY_SRC_USER="${MXL_TEST_USER_DIR:-/tmp/opencode/fakehome}"
export CAPY_SRC_SAVES="${MXL_TEST_SAVE_DIR:-/tmp/opencode/fakesaves}"
export CAPY_SRC_SAVES2="${MXL_TEST_SAVE_DIR2:-/tmp/claude-1000/honorific-sample}"
if [ -z "${MXL_TEST_SAVE_DIR3:-}" ]; then
    MXL_TEST_SAVE_DIR3="$ROOT/.cache/samples/owlie"
    if [ ! -d "$MXL_TEST_SAVE_DIR3" ]; then
        MAIN="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
        [ -n "$MAIN" ] && [ -d "$(dirname "$MAIN")/.cache/samples/owlie" ] && MXL_TEST_SAVE_DIR3="$(dirname "$MAIN")/.cache/samples/owlie"
    fi
fi
export CAPY_SRC_SAVES3="$MXL_TEST_SAVE_DIR3"
# nothing of the caller's session reaches the application
unset MXL_USER_DIR MXL_SAVE_DIR MXL_EXIT_AFTER MXL_THEME MXL_UI_SCALE || true

quick=0
for a in "$@"; do
    case "$a" in --quick|--list|-h|--help) quick=1 ;; esac
done
if [ "$quick" = 1 ]; then
    exec env -u DISPLAY -u WAYLAND_DISPLAY "$PY" -B "$ROOT/tests/run.py" "$@"
fi
command -v xvfb-run >/dev/null 2>&1 || { echo "xvfb-run not found: only 'tools/run_tests.sh --quick' can run" >&2; exit 2; }
exec env -u DISPLAY WAYLAND_DISPLAY=fake xvfb-run -a -s "-screen 0 1280x720x24" "$PY" -B "$ROOT/tests/run.py" "$@"
