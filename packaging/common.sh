# Shared by the build scripts: locate the base folder (exe + _internal/) and a Python 3.10.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_TITLE="MXL Capybara Editor V2"

find_base() {            # sets BASE_DIR and BASE_EXE; BASE_DIR=<folder> overrides the downloaded base
    if [ -z "${BASE_DIR:-}" ]; then
        "$ROOT/packaging/fetch_base.sh"
        BASE_DIR="$(ls -d "$ROOT"/.cache/base/*/ | head -1)"
    fi
    BASE_DIR="${BASE_DIR%/}"
    BASE_EXE="$(ls "$BASE_DIR"/*.exe | head -1)"
    [ -d "$BASE_DIR/_internal" ] || { echo "no _internal/ in $BASE_DIR" >&2; exit 1; }
}

find_python310() {       # sets PY310; PYTHON310=<interpreter> overrides
    local c
    for c in "${PYTHON310:-}" python3.10 "$HOME/.local/bin/python3.10"; do
        if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 && \
           [ "$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])')" = "3.10" ]; then
            PY310="$(command -v "$c")"; return
        fi
    done
    if command -v uv >/dev/null 2>&1; then
        uv python install -q 3.10 && PY310="$(uv python find 3.10)" && return
    fi
    echo "Python 3.10 not found: run 'uv python install 3.10' (user-level, no system packages) or set PYTHON310=" >&2
    exit 1
}
