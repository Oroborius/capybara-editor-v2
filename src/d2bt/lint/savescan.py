"""Read-only save scanner: what each character / stash file references in the game tables.

Format: docs of the MXL Capybara Editor V2 (SAVE_FORMAT.md) - .d2s header, 'gf' stat stream, 'if' skills,
'JM' item lists (bit streams, LSB first), corpses, 'jf' mercenary; Median .stash / _sharedstash.shared =
u32 version, u32 page, then 'STASH' + u32 page + item list per page.  Vanilla 1.10-1.14 .d2s is read the same
way with 12-bit set/unique ids and 30 class skills.

Never writes anything; callers should scan a COPY of the save folder (copy_saves).
"""
import os
import shutil
import struct
from dataclasses import dataclass, field

from .common import TxtDir

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
    """The widths a save needs, from an (unmodified) txt folder."""

    def __init__(self, txt_dir, median=None):
        td = TxtDir(txt_dir)
        self.median = td.is_median() if median is None else median
        isc = td['itemstatcost']
        self.stats = {}
        for r in range(len(isc)):
            self.stats[r] = (isc.num(r, 'save bits'), isc.num(r, 'save add'), isc.num(r, 'save param bits'),
                             isc.num(r, 'csvbits'), isc.num(r, 'csvparam'))
        it = td['itemtypes']
        codes = it.col('code')
        self._parents = {}
        for r, c in enumerate(codes):
            if c and c not in self._parents:
                self._parents[c] = [x for x in (it.cell(r, 'equiv1'), it.cell(r, 'equiv2')) if x]
        self.bases = {}
        for t in ('weapons', 'armor', 'misc'):
            tab = td[t]
            if tab is None:
                continue
            for r in range(len(tab)):
                code = (tab.cell(r, 'code') + '    ')[:4]
                if code.strip() and code not in self.bases:
                    self.bases[code] = (t, self.kind(t, tab.cell(r, 'type'), tab.cell(r, 'type2')),
                                        bool(tab.num(r, 'stackable')))
        pc = td['playerclass'].col('code') if td['playerclass'] else ['ama', 'sor', 'nec', 'pal', 'bar',
                                                                       'dru', 'ass']
        sk = td['skills'].col('charclass')
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


def parse_d2s(path, tab):
    """Read an expansion v96 save using the scanner's item and stat readers."""
    with open(path, 'rb') as fh:
        data = fh.read()
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
        item.runeword = packed
    if flags >> 24 & 1:
        while br.read(7):
            pass
    if code in TOME_CODES:
        br.read(5)
    kind = base[1]
    if br.read(1) and not tab.median:
        # Realm data has the same width before armor, weapon and misc fields.
        br.read(96)
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
    if pos + 4 > len(buf) or buf[pos:pos + 2] != b'JM':
        raise SaveError(f"'JM' expected at byte {pos}")
    n = struct.unpack_from('<H', buf, pos + 2)[0]
    pos += 4
    for _ in range(n):
        pos = _item_with_sockets(buf, pos, tab, u, items)
    return pos


def _item_with_sockets(buf, pos, tab, u, items):
    pos, flags, count = _item(buf, pos, tab, u, items)
    for _ in range(count if flags >> 11 & 1 else 0):
        children = items[-1].children if items is not None else None
        pos, _, _ = _item(buf, pos, tab, u, children)
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
        if p + 4 > len(b):
            raise SaveError('truncated corpse count')
        nc = struct.unpack_from('<H', b, p + 2)[0]
        p += 4
        for _ in range(nc):
            p = _item_list(b, p + 12, tab, u, items)
    if b[p:p + 2] == b'jf':
        p += 2
        if b[p:p + 2] == b'JM':
            p = _item_list(b, p, tab, u, items)
    if b[p:p + 2] == b'kf':
        if b[p + 2:p + 3] == b'\x01':
            p = _item_with_sockets(b, p + 3, tab, u, items)
        elif b[p + 2:p + 3] == b'\x00':
            p += 3
        else:
            raise SaveError('invalid iron golem marker')
    if character is not None and p != len(b):
        raise SaveError(f'unexpected data after item sections at byte {p}')
    return u


def scan_stash(path, tab):
    u = Usage(path, name=os.path.basename(path))
    b = open(path, 'rb').read()
    p = 8
    while p < len(b):
        if b[p:p + 5] != b'STASH':
            raise SaveError(f"'STASH' expected at byte {p}")
        p = _item_list(b, p + 9, tab, u)
    return u


def scan_dir(save_dir, txt_dir, median=None):
    """-> [Usage] for every save in save_dir, parsed with the tables of txt_dir (use the UNMODIFIED data the
    saves were written with).  A file that does not parse gets Usage.error set."""
    tab = SaveTables(txt_dir, median)
    out = []
    for fn in sorted(os.listdir(save_dir)):
        p = os.path.join(save_dir, fn)
        low = fn.lower()
        if not os.path.isfile(p) or not low.endswith(('.d2s', '.stash', '.shared')):
            continue
        try:
            out.append(scan_d2s(p, tab) if low.endswith('.d2s') else scan_stash(p, tab))
        except (SaveError, IndexError, struct.error) as e:
            out.append(Usage(p, name=fn, error=str(e)))
    return out


def copy_saves(src_dir, dst_dir):
    """Copy the save files (.d2s / .stash / .shared, nothing else) so they can be scanned without touching the
    originals.  -> number of files copied."""
    os.makedirs(dst_dir, exist_ok=True)
    n = 0
    for fn in os.listdir(src_dir):
        p = os.path.join(src_dir, fn)
        if os.path.isfile(p) and fn.lower().endswith(('.d2s', '.stash', '.shared')):
            shutil.copy2(p, os.path.join(dst_dir, fn))
            n += 1
    return n
