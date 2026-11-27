#!/usr/bin/env python3
"""Lists what the editor's modules import that the built Windows folder does not contain.

The Windows exe is the collector's PyInstaller build with our modules added (src/repack.py): it only holds the
standard-library and third-party modules the COLLECTOR used. A module of src/ importing anything else works on
Linux (full Python) and fails in the exe with ImportError. Run after packaging/build_windows.sh, with Python 3.10:

    python3.10 tools/check_windows_imports.py ["dist/windows/MXL Capybara Editor V2"]

Prints one line per missing module with the files importing it; exit status 1 when something is missing."""
import ast
import glob
import marshal
import os
import struct
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
import carch

# built into python310.dll on Windows (no file of their own)
WIN_BUILTIN = set('''_abc _ast _bisect _blake2 _codecs _codecs_cn _codecs_hk _codecs_iso2022 _codecs_jp _codecs_kr
_codecs_tw _collections _contextvars _csv _datetime _functools _heapq _imp _io _json _locale _lsprof _md5
_multibytecodec _opcode _operator _pickle _random _sha1 _sha256 _sha3 _sha512 _signal _sre _stat _statistics
_string _struct _symtable _thread _tracemalloc _warnings _weakref _winapi _xxsubinterpreters array atexit audioop
binascii builtins cmath errno faulthandler gc itertools marshal math mmap msvcrt nt sys time winreg xxsubtype
zlib'''.split())


def available(folder):
    exe = next(f for f in glob.glob(os.path.join(folder, '*.exe')))
    _d, _start, ents, _info = carch.read(exe)
    z = [e for e in ents if e['typ'] == 'z'][0]['data']
    have = set(dict(marshal.loads(z[struct.unpack('!i', z[8:12])[0]:])))
    have |= {e['name'] for e in ents}
    internal = os.path.join(folder, '_internal')
    with zipfile.ZipFile(os.path.join(internal, 'base_library.zip')) as zf:
        for n in zf.namelist():
            have.add(n.rsplit('.', 1)[0].replace('/', '.').replace('.__init__', ''))
    for f in os.listdir(internal):
        if f.endswith('.pyd'):
            have.add(f.split('.')[0])
    # source packages shipped as folders in _internal (on sys.path at run time, e.g. d2bt): their modules count
    for root, _dirs, files in os.walk(internal):
        rel = os.path.relpath(root, internal)
        if rel == '.' or not os.path.isfile(os.path.join(root, '__init__.py')):
            continue
        pkg = rel.replace(os.sep, '.')
        have.add(pkg)
        have |= {f'{pkg}.{f[:-3]}' for f in files if f.endswith('.py') and f != '__init__.py'}
    return have | WIN_BUILTIN


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'dist', 'windows', 'MXL Capybara Editor V2')
    have = available(folder)
    missing = {}
    for path in sorted(glob.glob(os.path.join(ROOT, 'src', 'mxl_*.py'))):
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
                if node.module in have:           # "from package import submodule": the submodule must exist too
                    pkg = any(h.startswith(node.module + '.') for h in have)
                    names += [f'{node.module}.{a.name}' for a in node.names
                              if pkg and a.name[:1].isupper() and node.module == 'PIL']
            for m in names:
                if m not in have:
                    missing.setdefault(m, set()).add(f'{os.path.basename(path)}:{node.lineno}')
    for m, where in sorted(missing.items()):
        print(f'{m}: {", ".join(sorted(where))}')
    print(f'{len(missing)} missing module(s) in {folder}')
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
