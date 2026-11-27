"""Table wrapper used by the validator (from the dev kit tooltip/data.py). MIT, see LICENSE."""

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


