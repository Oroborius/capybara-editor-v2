"""Layout loading.  Layouts live in layouts/<version>/<table>.json:

{ "table", "version", "record_size", "verified", "source", "fields": [
    {"name", "type", "offset", "size", "bit", "link", "ftype", ...}, ...] }

ftype is the D2 txt-compiler field type (Fog D2C_TxtFieldTypes):
 1 ascii  2 dword  3 word  4 byte  5 byte(one char)  6 ubyte  7 ascii  8 dword  9 raw 4cc code
 10 4cc code key  11 code->dword idx  12 code key (byte)  13 code->byte idx  14 code key (word)
 15 code->word idx  16 ascii key  17 name key (word)  18 name key (dword)  19 name->dword idx
 20 name->word idx  21 name->byte idx  22 tbl key->word  23/24 custom  25 calc->dword  26 bit
"""

from .layout_data import LAYOUTS

_cache = {}


def versions():
    return ['114d']


def tables(version):
    return sorted(LAYOUTS) if version == '114d' else []


def load(version, table):
    return LAYOUTS.get(table.lower()) if version == '114d' else None


def candidates(table, record_size):
    """Versions whose layout for `table` has this record size."""
    out = []
    for v in versions():
        lay = load(v, table)
        if lay and lay.get('record_size') == record_size:
            out.append(v)
    return out
