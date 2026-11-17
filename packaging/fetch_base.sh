#!/usr/bin/env bash
# Download the base release (exe + _internal/) that both builds start from, into .cache/base/.
# The base holds MXL Item Collector's modules and Windows runtime; it is not part of this repository.
# Override: BASE_URL=<zip url> BASE_SHA256=<hash, or empty to skip the check> packaging/fetch_base.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE_URL="${BASE_URL:-https://github.com/Nugwa628/capybara-heroeditor/releases/download/v1.2/MXL-Capybara-Editor-v1.2.zip}"
BASE_SHA256="${BASE_SHA256-d487789bbdb5eb9ba769d438fa17a29ca9e3eb834275d1e86deaa2014089c4b2}"
DEST="$ROOT/.cache/base"
if ls "$DEST"/*/*.exe >/dev/null 2>&1; then echo "base already in $DEST"; exit 0; fi
mkdir -p "$DEST"
echo "downloading $BASE_URL"
curl -fsSL -o "$DEST/base.zip" "$BASE_URL"
if [ -n "$BASE_SHA256" ]; then echo "$BASE_SHA256  $DEST/base.zip" | sha256sum -c - >/dev/null; fi
unzip -q -o "$DEST/base.zip" -d "$DEST"
rm "$DEST/base.zip"
echo "base ready: $(ls -d "$DEST"/*/)"
