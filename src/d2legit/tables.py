"""Stock LoD 1.14d Excel tables read from the game's MPQs (patch_d2 > d2exp > d2data), no loose or mod files.

The server's legit check uses the stock tables, so the editor does the same whatever mod folder is selected.
Adapted from the D2-Development-Kit legit/data.py (MIT, see LICENSE)."""
import os
import tempfile

from . import bin2txt
from .table import Table

NAMES = (
    'armor', 'weapons', 'misc', 'itemtypes', 'itemstatcost', 'skills', 'playerclass',
    'charstats', 'skilldesc', 'experience', 'magicprefix', 'magicsuffix', 'automagic',
    'rareprefix', 'raresuffix', 'uniqueitems', 'setitems', 'sets', 'runes',
    'properties', 'cubemain', 'qualityitems', 'lowqualityitems', 'gems',
)
ARCHIVES = ('patch_d2.mpq', 'd2exp.mpq', 'd2data.mpq')
EXCEL = 'data\\global\\excel\\'


class MissingTables(Exception):
    pass


def _open(path):
    try:
        from mxl_profile_mpq import ProfileMPQ
        return ProfileMPQ(path)
    except ImportError:
        from mpq import MPQ
        return MPQ(path)


def _parse_txt(raw):
    lines = raw.decode('latin-1').replace('\r\n', '\n').split('\n')
    while lines and not lines[-1]:
        lines.pop()
    rows = [[c.strip('"') for c in ln.split('\t')] for ln in lines]
    return rows[0], rows[1:]


def read_tables(game):
    """-> {name: Table} for the stock tables of the Diablo II folder `game`."""
    files = {n.lower(): os.path.join(game, n) for n in os.listdir(game)}
    archives = []
    for name in ARCHIVES:
        if name in files:
            try:
                archives.append(_open(files[name]))
            except Exception:
                pass
    if not archives:
        raise MissingTables('no Diablo II MPQ archives found in ' + str(game))
    raw = {}
    for name in NAMES:
        for arc in archives:                              # first archive holding either form wins
            txt, binary = (arc.read(f'{EXCEL}{name}.{ext}') for ext in ('txt', 'bin'))
            if txt or binary:
                raw[name] = (txt, binary)
                break
        else:
            raise MissingTables(f'{name} is missing from the game archives')
    # the converter resolves names (property codes ...) from the txt/bin files of one folder
    with tempfile.TemporaryDirectory(prefix='d2legit-') as tmp:
        for name, (txt, binary) in raw.items():
            for ext, data in (('txt', txt), ('bin', binary)):
                if data:
                    with open(os.path.join(tmp, f'{name}.{ext}'), 'wb') as fh:
                        fh.write(data)
        ctx = bin2txt.Context(bin_dir=tmp, version='114d')
        out = {}
        for name, (txt, binary) in raw.items():
            if txt:
                headers, rows = _parse_txt(txt)
            else:
                headers, rows = bin2txt.convert(binary, name, '114d', ctx)
            out[name] = Table(headers, rows)
    return out
