"""Small readers for the extracted game tables (<user dir>/data/*.bin and *.tbl) the save format depends on.

A compiled table (.bin) is `u32 row count` followed by `count` rows of equal size. Only the columns the save
format needs are read; their offsets are those of Median XL Sigma 2.14.x (taken from the host application's
reader and checked on the samples - see docs/SAVE_FORMAT.md, "Game tables the format depends on").

What the save format needs from the tables:
  itemstatcost.bin  width of every stat: in item stat lists (save bits / save add / save param bits) and in
                    the character stats section (CSvBits / CSvParam)
  weapons/armor/misc.bin   per item code: table (weapon / armor / misc), item type, "stackable" (quantity field)
  itemtypes.bin     type hierarchy: defense / durability fields exist only for types under 'armo' / 'weap'
  skills.bin        which skills belong to a class, in row order = order of the bytes of the skills section
Names (optional, for dumps): string.tbl / patchstring.tbl / expansionstring.tbl, monstats.bin, skilldesc.bin.
"""
import os
import struct
from dataclasses import dataclass

from .bits import FormatError

# Stats saved together with the next ones under ONE 9-bit id (vanilla "save group": min/max damage pairs).
# The id of the first is written, then (param, value) of each member in turn.
STAT_GROUPS = {17: (18,), 48: (49,), 50: (51,), 52: (53,), 54: (55, 56), 57: (58, 59)}

STAT_DEFENSE, STAT_DURABILITY, STAT_MAX_DURABILITY = 31, 72, 73


@dataclass(frozen=True)
class StatDef:
    id: int
    save_bits: int        # width of the value in an item stat list (0: the stat is never saved on items)
    save_add: int         # stored value = real value + save_add
    save_param: int       # width of the parameter in an item stat list (0: none)
    csv_bits: int         # width of the value in the character stats section (0: not a character stat)
    csv_param: int        # width of the parameter in the character stats section


@dataclass(frozen=True)
class ItemBase:
    code: str             # 4 characters, space padded, as stored in the save
    table: str            # 'weapons' / 'armor' / 'misc'
    type: int             # row of itemtypes.bin
    type2: int
    stackable: bool       # has the 9-bit quantity field
    width: int
    height: int
    name_index: int       # string index


def _rows(folder, name):
    with open(os.path.join(folder, name + '.bin'), 'rb') as f:
        d = f.read()
    n = struct.unpack_from('<I', d)[0]
    if not n:
        return []
    size = (len(d) - 4) // n
    return [d[4 + i * size:4 + (i + 1) * size] for i in range(n)]


def load_tbl(path):
    """{index: text} of a Diablo II string table (.tbl).
    Header (21 bytes): u16 crc, u16 index count, u32 hash table size, u8 version, u32 data start,
    u32 max tries, u32 file size; then `index count` u16 (hash slot of string i); then `hash table size`
    entries of 17 bytes: u8 used, u16 index, u32 hash, u32 key offset, u32 text offset, u16 text length."""
    with open(path, 'rb') as f:
        b = f.read()
    _crc, count, hsize, _ver, _start, _tries, _size = struct.unpack_from('<HHIBIII', b, 0)
    slots = struct.unpack_from(f'<{count}H', b, 21)
    base = 21 + 2 * count
    out = {}
    for i, slot in enumerate(slots):
        used, _idx, _hash, _koff, soff, slen = struct.unpack_from('<BHIIIH', b, base + 17 * slot)
        if used:
            raw = b[soff:soff + slen].split(b'\0')[0]
            try:
                out[i] = raw.decode('utf-8')
            except UnicodeDecodeError:
                out[i] = raw.decode('latin1')
    return out


def _strip_colors(text):
    out, i = [], 0
    while i < len(text):
        if text[i] == '\xff' and i + 2 < len(text) + 1 and text[i + 1:i + 2] == 'c':
            i += 3
            continue
        out.append(text[i])
        i += 1
    return ''.join(out)


class Tables:
    """The game tables of one extracted data folder."""

    def __init__(self, folder):
        self.folder = folder
        self.stats = {}
        for r in _rows(folder, 'itemstatcost'):
            sid = struct.unpack_from('<H', r, 0)[0]
            self.stats[sid] = StatDef(sid, r[25], struct.unpack_from('<i', r, 28)[0],
                                      struct.unpack_from('<i', r, 36)[0], r[10], r[11])
        self.bases = {}
        for table in ('weapons', 'armor', 'misc'):
            for r in _rows(folder, table):
                code = r[128:132].decode('latin1')
                if code in self.bases:
                    continue
                t1, t2 = struct.unpack_from('<hh', r, 286)
                self.bases[code] = ItemBase(code, table, t1, t2, bool(r[306]), r[271] or 1, r[272] or 1,
                                            struct.unpack_from('<H', r, 244)[0])
        # itemtypes.bin: code (4 bytes), then the two parent types (i16, i16)
        self.item_types = [(r[:4].decode('latin1').strip('\0 '), struct.unpack_from('<hh', r, 4))
                           for r in _rows(folder, 'itemtypes')]
        self._type_index = {}
        for i, (code, _parents) in enumerate(self.item_types):
            self._type_index.setdefault(code, i)
        self._ancestors = {}
        self._skills = _rows(folder, 'skills')
        self._strings = None
        self._monstats = None
        self._skilldesc = None

    # ------------------------------------------------------------------ locating the data folder
    @classmethod
    def find(cls, folder=None):
        """Tables of `folder`, else of $MXLSAVE_DATA, $MXL_USER_DIR/data, or the editor's / collector's user
        folder. Returns None when no folder with itemstatcost.bin is found."""
        cands = [folder, os.environ.get('MXLSAVE_DATA')]
        if os.environ.get('MXL_USER_DIR'):
            cands.append(os.path.join(os.environ['MXL_USER_DIR'], 'data'))
        bases = [os.environ.get('LOCALAPPDATA'), os.environ.get('XDG_DATA_HOME'),
                 os.path.join(os.path.expanduser('~'), '.local', 'share')]
        for b in bases:
            for name in ('MXL Capybara Editor', 'MXL Item Collector'):
                if b:
                    cands.append(os.path.join(b, name, 'data'))
        for c in cands:
            if c and os.path.isfile(os.path.join(c, 'itemstatcost.bin')):
                return cls(c)
        return None

    # ------------------------------------------------------------------ what the item layout depends on
    def base(self, code):
        b = self.bases.get(code)
        if b is None:
            raise FormatError(f'item code {code!r} is not in weapons/armor/misc.bin')
        return b

    def type_ancestors(self, t):
        if t not in self._ancestors:
            seen, todo = set(), [t]
            while todo:
                x = todo.pop()
                if x <= 0 or x in seen or x >= len(self.item_types):
                    continue
                seen.add(x)
                todo.extend(self.item_types[x][1])
            self._ancestors[t] = frozenset(seen)
        return self._ancestors[t]

    def body_kind(self, code):
        """'armor': defense + durability fields; 'weapons': durability fields; 'misc': neither.
        The game reads these fields by item TYPE (under 'armo' / 'weap'), not by table: a weapons.bin row whose
        type is not under 'weap' (Staff of Herding, code 'wd02') has no durability field."""
        b = self.base(code)
        anc = self.type_ancestors(b.type) | self.type_ancestors(b.type2)
        if b.table == 'armor' and self._type_index.get('armo') in anc:
            return 'armor'
        if b.table == 'weapons' and self._type_index.get('weap') in anc:
            return 'weapons'
        return 'misc'

    def class_skills(self, cls):
        """Skill ids of a class in skills.bin row order: the order of the bytes of the skills section."""
        return [i for i, r in enumerate(self._skills) if struct.unpack_from('<I', r, 12)[0] == cls]

    # ------------------------------------------------------------------ names (dumps only)
    def string(self, index):
        if self._strings is None:
            self._strings = {}
            for name, base in (('string', 0), ('patchstring', 10000), ('expansionstring', 20000)):
                try:
                    for i, v in load_tbl(os.path.join(self.folder, name + '.tbl')).items():
                        self._strings[base + i] = v
                except (OSError, struct.error):
                    pass
        return _strip_colors(self._strings.get(index, '')).strip()

    def base_name(self, code):
        b = self.bases.get(code)
        return self.string(b.name_index).split('\n')[-1] if b else ''

    def monster_name(self, mid):
        if self._monstats is None:
            try:
                self._monstats = _rows(self.folder, 'monstats')
            except OSError:
                self._monstats = []
        if 0 <= mid < len(self._monstats):
            return self.string(struct.unpack_from('<H', self._monstats[mid], 6)[0])
        return ''

    def skill_name(self, sid):
        if self._skilldesc is None:
            try:
                self._skilldesc = _rows(self.folder, 'skilldesc')
            except OSError:
                self._skilldesc = []
        if 0 <= sid < len(self._skills):
            sd = struct.unpack_from('<H', self._skills[sid], 404)[0]
            if 0 < sd < len(self._skilldesc):
                return self.string(struct.unpack_from('<H', self._skilldesc[sd], 8)[0])
        return ''
