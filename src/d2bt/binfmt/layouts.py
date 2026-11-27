"""Layout loading.  Layouts live in layouts/<version>/<table>.json:

{ "table", "version", "record_size", "verified", "source", "fields": [
    {"name", "type", "offset", "size", "bit", "link", "ftype", ...}, ...] }

ftype is the D2 txt-compiler field type (Fog D2C_TxtFieldTypes):
 1 ascii  2 dword  3 word  4 byte  5 byte(one char)  6 ubyte  7 ascii  8 dword  9 raw 4cc code
 10 4cc code key  11 code->dword idx  12 code key (byte)  13 code->byte idx  14 code key (word)
 15 code->word idx  16 ascii key  17 name key (word)  18 name key (dword)  19 name->dword idx
 20 name->word idx  21 name->byte idx  22 tbl key->word  23/24 custom  25 calc->dword  26 bit
"""
import json
import os

LAYOUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layouts')

# Detection order: when several versions have the same record size the first wins.
VERSION_ORDER = ['113c', '114d', '113d', '112a', '111b', '110', '109d', '108', '107', 'mxl']

_cache = {}


def versions():
    if not os.path.isdir(LAYOUT_DIR):
        return []
    have = [v for v in os.listdir(LAYOUT_DIR) if os.path.isdir(os.path.join(LAYOUT_DIR, v))]
    return [v for v in VERSION_ORDER if v in have] + sorted(v for v in have
                                                            if v not in VERSION_ORDER)


def tables(version):
    d = os.path.join(LAYOUT_DIR, version)
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json'))


def load(version, table):
    key = (version, table.lower())
    if key not in _cache:
        p = os.path.join(LAYOUT_DIR, version, table.lower() + '.json')
        if os.path.exists(p):
            with open(p, encoding='utf-8') as fh:
                _cache[key] = json.load(fh)
        else:
            _cache[key] = None
    return _cache[key]


def candidates(table, record_size):
    """Versions whose layout for `table` has this record size."""
    out = []
    for v in versions():
        lay = load(v, table)
        if lay and lay.get('record_size') == record_size:
            out.append(v)
    return out
