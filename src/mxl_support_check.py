"""The one definition of a genuine Capybara Editor V2 support zip ("Make a support zip for help..."), shared by the
editor (it checks its own zip before sending) and the receiving side (the upload address and LadderBot run the same
function before they accept or forward anything). Standard library only; reads the zip in memory, extracts nothing.

    validate(zip_bytes, filename, version) -> (ok, reason)
"""
import io
import json
import re
import zipfile

MAX_UPLOAD = 26 * 1024 * 1024                 # bytes of the request body / the zip file
MAX_ENTRIES = 2000
MAX_TOTAL = 250 * 1024 * 1024                 # uncompressed, all entries
MAX_RATIO = 100                               # uncompressed / compressed, per entry (zip bomb guard)
MAX_SETTINGS = 64 * 1024
LOG_HEAD = 64 * 1024

FILENAME = re.compile(r'^Capybara-support-(\d{8}-\d{6})\.zip$')
VERSION = re.compile(r'^v2\.0-\d{4}-\d{2}-\d{2}(-\d{1,3})?$')
SAVE_EXT = ('.d2s', '.d2x', '.sss', '.shared', '.stash', '.d2i')
_NAME = r'[^/\\\x00-\x1f]{1,200}'
ALLOWED = (
    re.compile(r'^README\.txt$'),
    re.compile(r'^settings\.json$'),
    re.compile(r'^log/capybara\.log(\.[1-3])?$'),
    re.compile(r'^saves/' + _NAME + r'$'),                         # extension checked below
    re.compile(r'^saves/backups/' + _NAME + r'\.bak-\d{8}-\d{6}$'),
)
D2S_MAGIC = b'\x55\xaa\x55\xaa'


def _bad_name(name):
    return (not name or name.startswith('/') or '\\' in name or '..' in name.split('/') or ':' in name
            or name.endswith('/'))


def validate(zip_bytes, filename, version):
    """(True, '') for a genuine CapyV2 support zip, else (False, why)."""
    if not isinstance(zip_bytes, (bytes, bytearray)) or not zip_bytes:
        return False, 'no file'
    if len(zip_bytes) > MAX_UPLOAD:
        return False, 'too big'
    m = FILENAME.match(filename or '')
    if not m:
        return False, 'not a support zip name'
    stamp = m.group(1)
    if not VERSION.match(version or ''):
        return False, 'unknown editor version'
    try:
        z = zipfile.ZipFile(io.BytesIO(bytes(zip_bytes)))
        infos = z.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        return False, 'not a zip'
    if not infos or len(infos) > MAX_ENTRIES:
        return False, 'entry count'
    total, names = 0, set()
    for i in infos:
        n = i.filename
        if _bad_name(n) or n in names:
            return False, f'bad entry name: {n[:80]!r}'
        names.add(n)
        if i.flag_bits & 0x1:
            return False, 'encrypted entry'
        if (i.external_attr >> 16) & 0o170000 not in (0, 0o100000):     # only plain files (no symlinks, devices)
            return False, f'not a plain file: {n[:80]!r}'
        if not any(p.match(n) for p in ALLOWED):
            return False, f'unexpected entry: {n[:80]!r}'
        if n.startswith('saves/') and not n.startswith('saves/backups/') and not n.lower().endswith(SAVE_EXT):
            return False, f'unexpected save file: {n[:80]!r}'
        if i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            return False, 'compression method'
        total += i.file_size
        if total > MAX_TOTAL:
            return False, 'too big unpacked'
        if i.file_size > 1024 and i.file_size > MAX_RATIO * max(1, i.compress_size):
            return False, f'compression ratio: {n[:80]!r}'
    if 'README.txt' not in names or 'log/capybara.log' not in names:
        return False, 'README.txt or log/capybara.log missing'
    try:
        first = z.read('README.txt')[:200].decode('utf-8', 'replace').splitlines()[0]
    except Exception:
        return False, 'README.txt unreadable'
    if first != f'MXL Capybara Editor support zip, {stamp}':
        return False, 'README stamp does not match the file name'
    try:
        with z.open('log/capybara.log') as f:
            head = f.read(LOG_HEAD)
    except Exception:
        return False, 'log unreadable'
    if b'build v2.0-' not in head:
        return False, 'not a Capybara Editor V2 log'
    if 'settings.json' in names:
        info = z.getinfo('settings.json')
        if info.file_size > MAX_SETTINGS:
            return False, 'settings.json too big'
        try:
            if not isinstance(json.loads(z.read('settings.json').decode('utf-8')), dict):
                return False, 'settings.json is not an object'
        except Exception:
            return False, 'settings.json is not JSON'
    for n in names:
        base = n.lower()
        if base.endswith('.d2s') or (n.startswith('saves/backups/') and '.d2s.bak-' in base):
            with z.open(n) as f:
                if f.read(4) != D2S_MAGIC:
                    return False, f'not a character file: {n[:80]!r}'
    return True, ''
