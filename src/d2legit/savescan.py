"""Save reader for the legit validator (from the dev kit lint/savescan.py, trimmed). MIT, see LICENSE."""
import os
import shutil
import struct
from dataclasses import dataclass, field

from .items import to_int

STAT_GROUPS = {17: (18,), 48: (49,), 50: (51,), 52: (53,), 54: (55, 56), 57: (58, 59)}
STAT_DEFENSE, STAT_DURABILITY, STAT_MAX_DURABILITY = 31, 72, 73
TOME_CODES = ('tbk ', 'ibk ')
SAVE_EXT = ('.d2s', '.stash', '.shared', '.sss', '.d2x')


class SaveError(Exception):
    pass


class UnknownStatError(SaveError):
    """the save carries a stat id that vanilla 1.14d's ItemStatCost.txt does not define (or cannot be saved)"""
    def __init__(self, stat: int):
        super().__init__(f'stat {stat} does not exist in vanilla 1.14d')
        self.stat = stat


class Bits:
    def __init__(self, data, start):
        self.d, self.start, self.pos = data, start, 0
        self.n = (len(data) - start) * 8

    def read(self, n):
        if self.pos + n > self.n:
            raise SaveError('read past the end of the file')
        b = self.start + (self.pos >> 3)
        sh = self.pos & 7
        v = (int.from_bytes(self.d[b:b + ((sh + n + 7) >> 3)], 'little') >> sh) & ((1 << n) - 1)
        self.pos += n
        return v

    def end_byte(self):
        return self.start + (self.pos + 7) // 8


class SaveTables:
    """The widths a save needs, from the stock txt tables (td.table(name) -> Table)."""

    def __init__(self, td, median=False):
        self.median = median
        isc = td.table('itemstatcost')
        self.stats = {}
        for r in range(len(isc)):
            g = lambda c, r=r: to_int(isc.get(r, c))
            self.stats[r] = (g('save bits'), g('save add'), g('save param bits'), g('csvbits'), g('csvparam'))
        it = td.table('itemtypes')
        self._parents = {}
        for r in range(len(it)):
            c = it.get(r, 'code').strip()
            if c and c not in self._parents:
                self._parents[c] = [x for x in (it.get(r, 'equiv1').strip(), it.get(r, 'equiv2').strip()) if x]
        self.bases = {}
        for t in ('weapons', 'armor', 'misc'):
            tab = td.table(t)
            for r in range(len(tab)):
                code = (tab.get(r, 'code').strip() + '    ')[:4]
                if code.strip() and code not in self.bases:
                    self.bases[code] = (t, self.kind(t, tab.get(r, 'type').strip(), tab.get(r, 'type2').strip()),
                                        bool(to_int(tab.get(r, 'stackable'))))
        pc = td.table('playerclass')
        pc = [pc.get(r, 'code').strip() for r in range(len(pc))] or ['ama', 'sor', 'nec', 'pal', 'bar', 'dru', 'ass']
        sk = td.table('skills')
        sk = [sk.get(r, 'charclass').strip() for r in range(len(sk))]
        self.class_skills = [sum(1 for c in sk if c == code) for code in pc]
        self.class_codes = pc

    def ancestors(self, t):
        seen, todo = set(), [t]
        while todo:
            x = todo.pop()
            if x and x not in seen:
                seen.add(x)
                todo.extend(self._parents.get(x, ()))
        return seen

    def kind(self, table, t1, t2):
        anc = self.ancestors(t1) | self.ancestors(t2)
        if table == 'armor' and 'armo' in anc:
            return 'armor'
        if table == 'weapons' and 'weap' in anc:
            return 'weapons'
        return 'misc'


@dataclass
class Usage:
    """What one save file references."""
    path: str
    name: str = ''
    cls: int = None
    stats: set = field(default_factory=set)          # itemstatcost rows (items + character)
    codes: set = field(default_factory=set)          # item codes (4 chars, space padded)
    rows: dict = field(default_factory=dict)         # table -> set of row indices
    runewords: set = field(default_factory=set)      # runeword ids (Median: string index of the name key)
    merc: int = None                                 # hireling Id
    skills: set = field(default_factory=set)         # skill ids in hotkeys / mouse buttons
    items: int = 0
    error: str = ''

    def add(self, table, idx):
        self.rows.setdefault(table, set()).add(idx)


@dataclass
class ParsedItem:
    code: str
    flags: int = 0
    seed: int | None = None  # the saved item GUID; the transient server unit id is not in the d2s
    ilvl: int = 1
    quality: int = 2
    quality_id: int | None = None
    automagic: int = 0
    affixes: list = field(default_factory=list)
    rare_name: tuple = ()
    runeword: int | None = None
    defense: int | None = None
    sockets: int = 0
    children: list = field(default_factory=list)
    stats: list = field(default_factory=list)
    set_stats: dict = field(default_factory=dict)
    runeword_stats: list = field(default_factory=list)


@dataclass
class ParsedCharacter:
    name: str = ''
    cls: int = 0
    level: int = 0
    stats: dict = field(default_factory=dict)
    skills: tuple = ()
    quests: tuple = ()
    items: list = field(default_factory=list)


def parse_d2s(data, tab, path=''):
    """Read an expansion v96 save (bytes) using the scanner's item and stat readers."""
    if len(data) < 0x2ff or data[:8] != b'\x55\xaa\x55\xaa\x60\x00\x00\x00' or not data[36] & 32:
        raise SaveError('expected a LoD v96 character save')
    if data[0x14f:0x153] != b'Woo!':
        raise SaveError('missing quest header')
    character = ParsedCharacter(level=data[43], quests=tuple(
        struct.unpack_from('<48H', data, 0x159 + 96 * diff) for diff in range(3)))
    _scan_d2s(path, data, tab, character)
    return character


def _stats(br, tab, u, values=None):
    while True:
        sid = br.read(9)
        if sid == 0x1FF:
            return
        for x in (sid,) + STAT_GROUPS.get(sid, ()):
            sd = tab.stats.get(x)
            if not sd or not sd[0]:
                raise UnknownStatError(x)
            u.stats.add(x)
            layer = br.read(sd[2]) if sd[2] else 0
            value = br.read(sd[0]) - sd[1]
            if values is not None:
                values.append((x, layer, value))


def _item(buf, pos, tab, u, items=None):
    if buf[pos:pos + 2] != b'JM':
        raise SaveError(f"'JM' expected at byte {pos}")
    br = Bits(buf, pos + 2)
    flags = br.read(32)
    if flags >> 16 & 1:
        if items is None:
            raise SaveError('ear items are not supported')
        br.read(10 + 3 + 4 + 4 + 4 + 3 + 3 + 7)
        while br.read(7):
            pass
        return br.end_byte(), flags, 0
    br.read(10 + 3 + 4 + 4 + 4 + 3)
    code = ''.join(chr(br.read(8)) for _ in range(4))
    item = ParsedItem(code.strip(), flags)
    if items is not None:
        items.append(item)
    u.codes.add(code)
    u.items += 1
    base = tab.bases.get(code)
    if base is None:
        raise SaveError(f'item code {code!r} is not in weapons/armor/misc')
    if flags >> 21 & 1:                # simple
        br.read(1 if tab.median else 3)
        return br.end_byte(), flags, 0
    nsock = br.read(3)
    item.seed = br.read(32)
    item.ilvl = br.read(7)
    q = item.quality = br.read(4)
    if br.read(1):
        br.read(3)
    if br.read(1):
        item.automagic = br.read(11)
        u.add('automagic', item.automagic)

    def affix(table, width):
        idx = br.read(width)
        u.add(table, idx)
        return idx

    if q == 1:
        item.quality_id = affix('lowqualityitems', 3)
    elif q == 3:
        item.quality_id = affix('qualityitems', 3)
    elif q == 4:
        item.affixes = [(table, affix(table, 11)) for table in ('magicprefix', 'magicsuffix')]
    elif q in (5, 7):
        item.quality_id = affix('setitems' if q == 5 else 'uniqueitems', 15 if tab.median else 12)
    elif q in (6, 8, 9):
        item.rare_name = (affix('rareprefix', 8), affix('raresuffix', 8))
        if q != 9:
            for k in range(6):
                if br.read(1):
                    table = 'magicprefix' if k % 2 == 0 else 'magicsuffix'
                    item.affixes.append((table, affix(table, 11)))
    elif q != 2:
        raise SaveError(f'unknown item quality {q}')
    if flags >> 26 & 1:
        packed = br.read(16)
        u.runewords.add(packed)
        item.runeword = packed & 0xfff
    if flags >> 24 & 1:
        while br.read(7):
            pass
    if code in TOME_CODES:
        br.read(5)
    kind = base[1]
    if br.read(1) and not tab.median:
        # v96 stores 96 bits of realm data for misc items. Weapons and
        # armor carry only the three-bit realm field before durability.
        br.read(96 if kind == 'misc' else 3)
    if kind == 'armor':
        bits, add = tab.stats[STAT_DEFENSE][:2]
        item.defense = br.read(bits) - add
    if kind in ('armor', 'weapons'):
        bits, add = tab.stats[STAT_MAX_DURABILITY][:2]
        if br.read(bits) != add:
            br.read(tab.stats[STAT_DURABILITY][0])
    if base[2]:
        br.read(9)
    if flags >> 11 & 1:
        item.sockets = br.read(4)
    mask = br.read(5) if q == 5 else 0
    _stats(br, tab, u, item.stats)
    for b in range(5):
        if mask >> b & 1:
            _stats(br, tab, u, item.set_stats.setdefault(b, []))
    if flags >> 26 & 1:
        _stats(br, tab, u, item.runeword_stats)
    return br.end_byte(), flags, nsock


def _item_list(buf, pos, tab, u, items=None):
    if buf[pos:pos + 2] != b'JM':
        raise SaveError(f"'JM' expected at byte {pos}")
    n = struct.unpack_from('<H', buf, pos + 2)[0]
    pos += 4
    for _ in range(n):
        pos, flags, nsock = _item(buf, pos, tab, u, items)
        for _k in range(nsock if flags >> 11 & 1 else 0):
            children = items[-1].children if items is not None else None
            pos, _f, _n = _item(buf, pos, tab, u, children)
    return pos


def scan_d2s(path, tab):
    with open(path, 'rb') as fh:
        return _scan_d2s(path, fh.read(), tab)


def _scan_d2s(path, b, tab, character=None):
    u = Usage(path)
    items = character.items if character is not None else None
    if b[:4] != b'\x55\xaa\x55\xaa':
        raise SaveError('not a character file')
    u.name = b[0x14:0x24].split(b'\0')[0].decode('latin-1')
    u.cls = b[0x28]
    if character is not None:
        character.name, character.cls = u.name, u.cls
    for o in list(range(0x38, 0x78, 4)) + [0x78, 0x7C, 0x80, 0x84]:
        v = struct.unpack_from('<I', b, o)[0]
        if v != 0xFFFF and v != 0xFFFFFFFF:
            u.skills.add(v & 0x7FFF)
    if struct.unpack_from('<I', b, 0xB3)[0]:
        u.merc = struct.unpack_from('<H', b, 0xB9)[0]
    p = 0x2FD
    if b[p:p + 2] != b'gf':
        raise SaveError("'gf' expected at 0x2FD")
    br = Bits(b, p + 2)
    while True:
        sid = br.read(9)
        if sid == 0x1FF:
            break
        sd = tab.stats.get(sid)
        if not sd or not sd[3]:
            raise SaveError(f'character stat {sid} has no width')
        u.stats.add(sid)
        param = br.read(sd[4]) if sd[4] else None
        value = br.read(sd[3])
        if character is not None:
            character.stats[sid] = value
        if sid == 88 and param is not None and param < 0x2000:
            u.add('monstats', param)
    p = br.end_byte()
    if b[p:p + 2] != b'if':
        raise SaveError("'if' expected after the stats")
    n = tab.class_skills[u.cls] if u.cls < len(tab.class_skills) else 30
    if character is not None:
        character.skills = tuple(b[p + 2:p + 2 + n])
    p += 2 + n
    p = _item_list(b, p, tab, u, items)
    if b[p:p + 2] == b'JM':                   # corpses
        nc = struct.unpack_from('<H', b, p + 2)[0]
        p += 4
        for _ in range(nc):
            p = _item_list(b, p + 12, tab, u, items)
    if b[p:p + 2] == b'jf':
        p += 2
        if b[p:p + 2] == b'JM':
            p = _item_list(b, p, tab, u, items)
    if character is not None and b[p:p + 3] == b'kf\x01':
        _item(b, p + 3, tab, u, items)
    return u


def parse_items(buf, tab):
    """Parse a run of item blobs (an item followed by its socketed items, repeated) -> [ParsedItem]."""
    items, u, pos = [], Usage(''), 0
    while pos < len(buf):
        pos, flags, nsock = _item(buf, pos, tab, u, items)
        for _ in range(nsock if flags >> 11 & 1 else 0):
            pos, _f, _n = _item(buf, pos, tab, u, items[-1].children)
    return items
