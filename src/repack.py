"""Rebuild a PyInstaller (6.x, onedir) exe: same bootloader, same CArchive entries, PYZ with extra modules,
entry script replaced. Usage: repack.py in.exe out.exe [--identity] [--icon=capybara.ico]
in.exe is the original MXL Item Collector.exe, or a released MXL Capybara Editor.exe. Run it with Python 3.10, the exe's own version: the modules are
compiled here and stored as 3.10 bytecode."""
import os, struct, zlib, marshal, sys
HERE = os.path.dirname(os.path.abspath(__file__))          # carch.py and the editor's modules (src/)
sys.path.insert(0, HERE)
import carch

# packages packed into the exe from outside src/: {name: folder}. tools/mxlsave is the independent save-format
# library (one copy of the source: the command line tool there, the package `mxlsave` in both builds)
PACKAGES = {'mxlsave': os.path.join(os.path.dirname(HERE), 'tools', 'mxlsave')}

def package_modules(name, folder):
    """{dotted name: code} of a flat package folder: 'pkg' (its __init__) and 'pkg.<module>' for every other .py."""
    out = {}
    for f in sorted(os.listdir(folder)):
        if f.endswith('.py'):
            mod = name if f == '__init__.py' else f'{name}.{f[:-3]}'
            out[mod] = compile(open(os.path.join(folder, f), encoding='utf-8').read(), f'{name}/{f}', 'exec')
    if name not in out:
        sys.exit(f'{folder}: no __init__.py')
    return out

def build_pyz(z, extra):
    toff = struct.unpack('!i', z[8:12])[0]
    toc = marshal.loads(z[toff:])
    blobs = []
    for name, (typ, off, ln) in toc:
        if name in extra:
            continue
        blobs.append((name, typ, z[off:off + ln]))
    for name, code in extra.items():
        # PYZ type codes: 0 module, 1 package (the importer gives it a __path__, so its submodules are found)
        blobs.append((name, 1 if name in PACKAGES else 0, zlib.compress(marshal.dumps(code), 9)))
    out = bytearray(z[:8]) + b'\0\0\0\0'
    newtoc = []
    for name, typ, data in blobs:
        newtoc.append((name, (typ, len(out), len(data))))
        out += data
    struct.pack_into('!i', out, 8, len(out))
    out += marshal.dumps(newtoc)
    return bytes(out)

def build_exe(d, start, ents, info, replace):
    pkg = bytearray()
    toc = bytearray()
    for e in ents:
        data = replace.get(e['name'], None)
        if data is None:
            data, ulen, cflag = e['data'], e['ulen'], e['cflag']
        else:
            data, ulen, cflag = data
        off = len(pkg)
        pkg += data
        name = e['name'].encode() + b'\0'
        elen = 18 + len(name)
        pad = (16 - elen % 16) % 16
        toc += struct.pack('!IIIIBc', elen + pad, off, len(data), ulen, cflag, e['typ'].encode()) + name + b'\0' * pad
    tocoff = len(pkg)
    pkg += toc
    pyver, pylib = info
    pkglen = len(pkg) + 88
    pkg += struct.pack('!8sIIii64s', carch.COOKIE, pkglen, tocoff, len(toc), pyver, pylib)
    return d[:start] + bytes(pkg)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    d, start, ents, info = carch.read(src)
    if '--identity' in sys.argv:
        out = build_exe(d, start, ents, info, {})
        print('identical:', out == d, len(out), len(d))
        sys.exit()
    if sys.version_info[:2] != (3, 10):
        sys.exit(f'run repack.py with Python 3.10 (this is {sys.version.split()[0]}): the exe cannot load other bytecode')
    plugin = HERE
    extra = {}
    # every editor module of src/ (mxl_*.py); a new module needs no entry here
    for mod in sorted(f[:-3] for f in os.listdir(plugin) if f.startswith('mxl_') and f.endswith('.py')):
        extra[mod] = compile(open(f'{plugin}/{mod}.py', encoding='utf-8').read(), f'{mod}.py', 'exec')
    for name, folder in PACKAGES.items():
        extra.update(package_modules(name, folder))
    script = [e for e in ents if e['typ'] == 's' and e['name'] == 'mxl_gui'][0]
    z = [e for e in ents if e['typ'] == 'z'][0]
    zd = z['data']
    if 'mxl_gui' not in dict(marshal.loads(zd[struct.unpack('!i', zd[8:12])[0]:])):
        extra['mxl_gui'] = marshal.loads(zlib.decompress(script['data']))  # original GUI, now importable
    # else: in.exe is an already repacked editor exe (its entry script is the launcher, the GUI is in the PYZ)
    pyz = build_pyz(z['data'], extra)
    launcher = compile("import mxl_boot\nmxl_boot.launch()\n", 'mxl_gui.py', 'exec')
    ld = marshal.dumps(launcher)
    replace = {'PYZ.pyz': (pyz, len(pyz), 0), 'mxl_gui': (zlib.compress(ld, 9), len(ld), 1)}
    out = build_exe(d, start, ents, info, replace)
    ico = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--icon=')), None)
    if ico:                                    # exe file icon: new resource section, overlay (archive) kept as is
        import rsrc
        out = rsrc.replace_icons(out, open(ico, 'rb').read(), start)
    open(dst, 'wb').write(out)
    print('written', dst, len(out))
    # ttkbootstrap's own window icon (set as the default of every window when the app starts): the capybara too
    icons = os.path.join(os.path.dirname(os.path.abspath(dst)), '_internal', 'ttkbootstrap', 'assets', 'app_icons')
    if os.path.isdir(icons):
        import base64, mxl_app_icon
        open(os.path.join(icons, 'ttkbootstrap.ico'), 'wb').write(base64.b64decode(mxl_app_icon.ICO_FILE))
        open(os.path.join(icons, 'ttkbootstrap.png'), 'wb').write(base64.b64decode(mxl_app_icon.ICONS[0]))
        print('capybara icons written in', icons)
