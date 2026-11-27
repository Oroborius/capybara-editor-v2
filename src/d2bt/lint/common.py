"""Shared bits of the mod checks: the Issue record and a light txt table reader.

No Tk here: the GUI panel and the Build & Play pre-deploy step both use these.
"""
import os
from dataclasses import dataclass, field

from ..binfmt.txt2bin import parse_txt

ERROR, WARNING, INFO = 'error', 'warning', 'info'
SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass
class Issue:
    """One finding.

    severity  'error' (the game breaks / saves get corrupted), 'warning' (works, but probably not what you
              meant, or existing characters change), 'info'
    table     table name without .txt ('' = whole mod)
    row       0-based data row as the game sees it (Expansion rows dropped), or None
    line      1-based line in the .txt file (1 = header), or None; the editor's row number is line - 1
    column    column header, or ''
    message   plain English
    fix       suggestion, or ''
    rule      short id ('broken-link', 'missing-string', 'save-bits' ...)
    affects   for save checks: what a save must reference to be hit (see saves.affected_by)
    """
    severity: str
    table: str
    message: str
    row: int = None
    line: int = None
    column: str = ''
    fix: str = ''
    rule: str = ''
    affects: tuple = field(default=(), repr=False)

    def where(self):
        s = self.table + '.txt' if self.table else ''
        if self.line:
            s += f' line {self.line}'
        if self.column:
            s += f' [{self.column}]'
        return s

    def __str__(self):
        s = f'{self.severity.upper():7} {self.where()}: {self.message}'
        if self.fix:
            s += f'  Fix: {self.fix}'
        return s


def sort_issues(issues):
    return sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.table, i.line or 0))


def blocking(issues):
    """Issues that should stop a deploy (errors)."""
    return [i for i in issues if i.severity == ERROR]


def summary(issues):
    n = {ERROR: 0, WARNING: 0, INFO: 0}
    for i in issues:
        n[i.severity] = n.get(i.severity, 0) + 1
    return f'{n[ERROR]} error(s), {n[WARNING]} warning(s), {n[INFO]} note(s)'


def dec(b):
    return b.decode('latin-1') if isinstance(b, (bytes, bytearray)) else (b or '')


class Table:
    """A txt table: header, rows (Expansion rows dropped like the game) and the file line of each row."""

    def __init__(self, name, path):
        self.name = name
        self.path = path
        with open(path, 'rb') as fh:
            data = fh.read()
        self.header, rows = parse_txt(data)
        self.rows = rows
        self.hdr = [dec(h) for h in self.header]
        self._col = {}
        for i, h in enumerate(self.hdr):
            self._col.setdefault(h.strip().lower(), i)
        # file line (1-based) of each kept row
        lines = data.split(b'\n')
        if lines and lines[-1] in (b'', b'\r'):
            lines.pop()
        self.lines = [n + 1 for n, ln in enumerate(lines[1:], 1)
                      if ln.rstrip(b'\r').split(b'\t')[0] != b'Expansion']

    def line(self, row):
        return self.lines[row] if row is not None and 0 <= row < len(self.lines) else None

    def ci(self, name):
        return self._col.get(name.lower())

    def has(self, name):
        return name.lower() in self._col

    def cell(self, row, col):
        i = self.ci(col) if isinstance(col, str) else col
        if i is None or row >= len(self.rows):
            return ''
        r = self.rows[row]
        return dec(r[i]).strip() if i < len(r) else ''

    def col(self, name):
        i = self.ci(name)
        if i is None:
            return None
        return [dec(r[i]).strip() if i < len(r) else '' for r in self.rows]

    def num(self, row, col, default=0):
        s = self.cell(row, col)
        try:
            return int(s)
        except ValueError:
            return default

    def __len__(self):
        return len(self.rows)


class TxtDir:
    """Lazy table access to a txt folder (case-insensitive names)."""

    def __init__(self, path):
        self.path = path
        self._files = {}
        if path and os.path.isdir(path):
            for fn in os.listdir(path):
                if fn.lower().endswith('.txt'):
                    self._files[fn[:-4].lower()] = os.path.join(path, fn)
        self._t = {}

    def has(self, name):
        return name.lower() in self._files

    def __getitem__(self, name):
        name = name.lower()
        if name not in self._t:
            p = self._files.get(name)
            self._t[name] = Table(name, p) if p else None
        return self._t[name]

    def names(self):
        return sorted(self._files)

    def is_median(self):
        """Median XL / D2Sigma data: its extension tables are present."""
        return any(self.has(t) for t in ('skills2', 'uniqueitems2', 'requirements', 'npcstores'))
