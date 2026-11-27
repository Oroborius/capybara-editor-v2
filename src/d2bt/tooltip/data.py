"""Table and string access for the tooltip builders (no Tk).

GameData wraps what the Excel Editor already has: an explain.Ctx (live grid rows first, else the txt files
beside the opened file) or just a txt folder, plus the string tables (.tbl beside the txt, or a StringSet).
Rows are read lazily: Table keeps the raw str rows and a lower-case header index, so a 1000-row skills.txt
costs nothing until a cell is asked for."""
import os
import re

from ..binfmt import explain as X

_NUM = re.compile(r'^\s*-?\d+')


def to_int(s, default=0):
    if isinstance(s, int):
        return s
    m = _NUM.match(str(s or ''))
    return int(m.group(0)) if m else default


def fix_text(s):
    """Colour codes as 'ÿcN' (the .tbl may hold the UTF-8 bytes of 'ÿ' read as latin-1: 'Ã¿')."""
    return s.replace('Ã¿c', 'ÿc').replace('\xffc', 'ÿc') if s else s


class Table:
    def __init__(self, hdr, rows):
        self.hdr = list(hdr)
        self.rows = rows
        self.idx = {}
        for i, h in enumerate(self.hdr):
            self.idx.setdefault(h.lower(), i)
        self._key = {}

    def __len__(self):
        return len(self.rows)

    def has(self, col):
        return col.lower() in self.idx

    def get(self, r, col, default=''):
        i = self.idx.get(col.lower())
        if i is None or not 0 <= r < len(self.rows):
            return default
        row = self.rows[r]
        v = row[i] if i < len(row) else ''
        return default if v is None else str(v)

    def row(self, r):
        """{column: text} of row r ({} when out of range)."""
        if not 0 <= r < len(self.rows):
            return {}
        row = self.rows[r]
        return {h: ('' if i >= len(row) or row[i] is None else str(row[i])) for i, h in enumerate(self.hdr)}

    def find(self, key, col=None):
        """Row index of key in col (default: the first column), case-insensitive; -1 when absent."""
        ci = self.idx.get((col or self.hdr[0] if self.hdr else '').lower(), 0)
        cache = self._key.get(ci)
        if cache is None:
            cache = {}
            for r, row in enumerate(self.rows):
                k = str(row[ci] if ci < len(row) and row[ci] is not None else '').strip().lower()
                if k and k not in cache:
                    cache[k] = r
            self._key[ci] = cache
        return cache.get(str(key or '').strip().lower(), -1)


class GameData:
    """tables: an explain.Ctx, a txt folder path, or a GameData; strings: a tbl.StringSet or None
    (then the .tbl files beside the txt are read)."""

    def __init__(self, tables, strings=None):
        if isinstance(tables, GameData):
            self.ctx = tables.ctx
            strings = strings if strings is not None else tables.strings
        elif isinstance(tables, X.Ctx):
            self.ctx = tables
        else:
            self.ctx = X.Ctx(str(tables or ''))
        self._tables = {}
        self.strings = strings if strings is not None else self._load_strings()
        self._keys = None

    def _load_strings(self):
        from ..binfmt.tbl import StringSet
        try:
            from ..binfmt.bin2txt import load_strings
            ss = load_strings(self.ctx.txt_dir)
            if not ss.tables:
                ss = self.ctx.project._listing_strings()
            return ss
        except Exception:
            return StringSet()

    @property
    def version(self):
        return self.ctx.version

    def invalidate(self, table=None):
        if table is None:
            self._tables.clear()
        else:
            self._tables.pop(table.lower(), None)

    def table(self, name):
        name = name.lower()
        t = self._tables.get(name)
        if t is None:
            got = None
            try:
                got = self.ctx.rows(name)
            except Exception:
                got = None
            t = Table(*got) if got else Table([], [])
            self._tables[name] = t
        return t

    # ---- strings
    def text(self, key):
        """In-game text of a string key ('' for none / 'dummy')."""
        if key is None:
            return ''
        key = str(key)
        if not key.strip() or key.strip().lower() == 'dummy':
            return ''
        try:
            v = self.strings.text_by_key(key) if self.strings else None
        except Exception:
            v = None
        if v is None and key.strip().isdigit():
            v = self.text_id(int(key))
        return fix_text(v) if v is not None else ''

    def text_id(self, idx):
        """Text of a string id (string.tbl 0.., patch 10000.., expansion 20000..)."""
        try:
            v = self.strings.text(idx) if self.strings else None
        except Exception:
            v = None
        return fix_text(v) if v else ''

    def has_strings(self):
        return bool(self.strings)
