"""Extract the host application's modules (MXL Item Collector) from a PyInstaller exe as sourceless .pyc files.

Usage: extract_host.py base.exe out_dir

base.exe is the original `MXL Item Collector.exe` or a released `MXL Capybara Editor.exe` (both hold the collector's
modules in their PYZ archive). Every top-level module that is not part of the standard library, not a third-party
package and not one of the editor's own modules in src/ is written to out_dir/<name>.pyc. The bytecode is copied as
it is (never unmarshalled), so this runs with any Python 3; the result needs the exe's own Python (3.10) to import."""
import os, struct, sys, zlib, marshal
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
sys.path.insert(0, SRC)
import carch

THIRD_PARTY = {'PIL', 'numpy', 'psutil', 'yaml', 'ttkbootstrap', 'jinja2', 'markupsafe', 'cffi', 'pycparser',
               'pyparsing', 'packaging', 'setuptools', 'pkg_resources', 'pyreadline3', 'readline', '_distutils_hack',
               'typing_extensions'}
# standard library of Python 3.10, removed from later versions (sys.stdlib_module_names of the running Python)
OLD_STDLIB = set('aifc asynchat asyncore audioop binhex cgi cgitb chunk crypt distutils formatter imghdr imp lib2to3 '
                 'mailcap msilib nis nntplib ossaudiodev parser pipes smtpd sndhdr spwd sunau symbol telnetlib uu '
                 'xdrlib'.split())


def host_modules(exe):
    """{name: raw marshalled code} of the collector's modules, and the 4-byte pyc magic of the exe's Python."""
    d, start, ents, info = carch.read(exe)
    z = [e for e in ents if e['typ'] == 'z'][0]['data']
    magic = z[4:8]
    toc = marshal.loads(z[struct.unpack('!i', z[8:12])[0]:])
    packages = {n.split('.')[0] for n, _ in toc if '.' in n}
    ours = {f[:-3] for f in os.listdir(SRC) if f.endswith('.py')}
    out = {}
    for name, (typ, off, ln) in toc:
        if '.' in name or name in packages or name in THIRD_PARTY or name in OLD_STDLIB or name in sys.stdlib_module_names or name in ours:
            continue
        if name.startswith(('_', 'pyi')):
            continue
        out[name] = zlib.decompress(z[off:off + ln])
    if 'mxl_gui' not in out:                 # original exe: the GUI is the entry script, not a PYZ module
        script = [e for e in ents if e['typ'] == 's' and e['name'] == 'mxl_gui'][0]
        out['mxl_gui'] = zlib.decompress(script['data']) if script['cflag'] else script['data']
    return out, magic


if __name__ == '__main__':
    exe, dst = sys.argv[1], sys.argv[2]
    mods, magic = host_modules(exe)
    os.makedirs(dst, exist_ok=True)
    for name, code in mods.items():
        with open(os.path.join(dst, name + '.pyc'), 'wb') as f:
            f.write(magic + b'\0' * 12 + code)      # flags 0, mtime 0, size 0: sourceless, never checked
    print(len(mods), 'host modules written in', dst + ':', ' '.join(sorted(mods)))
