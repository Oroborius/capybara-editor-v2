#!/usr/bin/env bash
# Rebuild Tk with Xft (FreeType + fontconfig: antialiased, hinted TrueType text) for the AppImage.
#
# The standalone CPython bundled in the AppImage has a Tk built without Xft: it can only draw X core bitmap fonts.
# Its _tkinter loads Tk as a separate shared library (lib/libtcl9tk9.0.so) that reaches Tcl through the stubs table,
# so the library alone can be replaced by a build of the SAME Tk version from the official sources.
#
# Usage: packaging/build_tk_xft.sh <tk patch level, e.g. 9.0.4> <output folder>
# Output: <out>/libtcl9tk9.0.so (RUNPATH $ORIGIN) + <out>/libXft.so.2, libXrender.so.1 copied from this machine.
# Needs: cc, make, and the headers of X11, Xft, fontconfig and FreeType. Nothing is installed: sources and the build
# tree stay in .cache/.
set -euo pipefail
source "$(dirname "$0")/common.sh"
VER="${1:?tk patch level}"
OUT="$(realpath -m "${2:?output folder}")"
case "$VER" in      # official source releases, https://prdownloads.sourceforge.net/tcl/<name>
    9.0.4) TCL_SHA=d0aed49230bc02a65c1e0229e65f34590a4b037ec40d546f32573b467f7551ea
           TK_SHA=d7a146d2917eb8b5cc95276dbf0e3d03c7464d2b19c1675357857c989301dbb4 ;;
    *) echo "tk-xft: no pinned sources for Tk $VER (add its checksums to packaging/build_tk_xft.sh)" >&2; exit 2 ;;
esac
SRC_URL="${TCLTK_SRC_URL:-https://prdownloads.sourceforge.net/tcl}"
CACHE="$ROOT/.cache"
SRC="$CACHE/src"
BUILD="$CACHE/build-tk-xft-$VER"
LIB=libtcl9tk9.0.so
LOG="$CACHE/tk-xft-$VER.log"
COMPAT="$ROOT/packaging/linux/glibc_compat.h"
# the flags are part of the result: a change here rebuilds
STAMP="tk $VER; $(cksum < "${BASH_SOURCE[0]}"); $(cksum < "$COMPAT")"

if [ -f "$OUT/$LIB" ] && [ "$(cat "$OUT/.stamp" 2>/dev/null)" = "$STAMP" ]; then
    echo "tk-xft: Tk $VER with Xft already built ($OUT)"
    exit 0
fi

for tool in cc make; do
    command -v "$tool" >/dev/null || { echo "tk-xft: '$tool' not found (or build with MXL_NO_XFT=1)" >&2; exit 1; }
done
mkdir -p "$SRC"
printf '#include <X11/Xft/Xft.h>\n#include <fontconfig/fontconfig.h>\nint main(void){return 0;}\n' > "$CACHE/xftprobe.c"
if ! cc $(pkg-config --cflags xft 2>/dev/null || echo -I/usr/include/freetype2) -fsyntax-only "$CACHE/xftprobe.c" 2>/dev/null; then
    echo "tk-xft: development headers of libXft / fontconfig / FreeType / X11 not found" >&2
    echo "        (Debian/Ubuntu: libxft-dev; Fedora: libXft-devel; Arch: libxft), or build with MXL_NO_XFT=1" >&2
    exit 1
fi
rm -f "$CACHE/xftprobe.c"

fetch() {            # fetch <file> <sha256>
    if [ ! -f "$SRC/$1" ]; then
        echo "tk-xft: downloading $1"
        curl -fsSL -o "$SRC/$1.part" "$SRC_URL/$1"
        mv "$SRC/$1.part" "$SRC/$1"
    fi
    echo "$2  $SRC/$1" | sha256sum -c --quiet - || { echo "tk-xft: checksum mismatch: $SRC/$1" >&2; exit 1; }
}
fetch "tcl$VER-src.tar.gz" "$TCL_SHA"
fetch "tk$VER-src.tar.gz" "$TK_SHA"

echo "tk-xft: building Tk $VER with Xft (about a minute; log: $LOG)"
rm -rf "$BUILD"
mkdir -p "$BUILD"
tar -xzf "$SRC/tcl$VER-src.tar.gz" -C "$BUILD"
tar -xzf "$SRC/tk$VER-src.tar.gz" -C "$BUILD"
JOBS="$(nproc 2>/dev/null || echo 2)"
# gnu11 + glibc_compat.h: no dependency on a recent glibc (see the header)
export CFLAGS="-O2 -std=gnu11 -include $COMPAT"
(
    # Tcl: only its headers, tclConfig.sh and the stubs archive are used (Tk calls the bundled libtcl9.0.so via stubs)
    cd "$BUILD/tcl$VER/unix"
    ./configure --prefix=/usr --disable-zipfs
    make -j"$JOBS" binaries
    # Tk: scripts stay on disk (lib/tk9.0 of the bundled Python, same version), no screensaver / printing libraries
    cd "$BUILD/tk$VER/unix"
    ./configure --prefix=/usr --with-tcl="$BUILD/tcl$VER/unix" --enable-xft --disable-zipfs --disable-xss \
                --disable-libcups --disable-rpath
    grep -q -e '-DHAVE_XFT=1' Makefile
    make -j"$JOBS" "LDFLAGS=-Wl,--as-needed -Wl,-soname,$LIB -Wl,-rpath,'\$\$ORIGIN'" "$LIB"
) >"$LOG" 2>&1 || { tail -25 "$LOG" >&2; echo "tk-xft: build failed (log: $LOG); MXL_NO_XFT=1 builds without it" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT"
cp "$BUILD/tk$VER/unix/$LIB" "$OUT/$LIB"
strip --strip-unneeded "$OUT/$LIB" 2>/dev/null || true
# Bundled next to it: what a desktop does not always have. Left to the host, as AppImages do (the "excludelist"):
# glibc, libX11 / libxcb, and libfontconfig + libfreetype (they must match the host's font configuration).
for dep in libXft.so.2 libXrender.so.1; do
    path="$(ldd "$OUT/$LIB" | awk -v d="$dep" '$1 == d { print $3 }')"
    [ -f "$path" ] || { echo "tk-xft: $dep not found on this machine" >&2; exit 1; }
    cp -L "$path" "$OUT/$dep"
    chmod 644 "$OUT/$dep"
done
need="$( (objdump -T "$OUT/$LIB" "$OUT"/lib*.so.* | grep -o 'GLIBC_[0-9.]*' | sort -Vu | tail -1) || true)"
echo "$STAMP" > "$OUT/.stamp"
rm -rf "$BUILD"
echo "tk-xft: done, $(du -sh "$OUT" | cut -f1) in $OUT (needs glibc >= ${need#GLIBC_})"
