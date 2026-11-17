"""Item records: the bit layout shared by .d2s, .stash and .shared files (docs/SAVE_FORMAT.md, section 6).

An item is 'JM' followed by a bit stream (LSB first) that is padded to a whole byte. Its length is not stored:
the only way to find the end of an item is to decode it, which needs the stat widths of itemstatcost.bin.
The items socketed into an item follow it directly as complete items of their own (location 6); they are not
counted in the list's item count.
"""
from dataclasses import dataclass, field
from typing import Optional

from .bits import BitReader, BitWriter, FormatError
from .tables import STAT_GROUPS, STAT_DEFENSE, STAT_DURABILITY, STAT_MAX_DURABILITY

# header flags (bit numbers of the 32-bit flags field)
FLAG_IDENTIFIED = 4
FLAG_SOCKETED = 11
FLAG_NEW = 13           # vanilla "picked up since the last save"; set on freshly cubed items in the samples
FLAG_EAR = 16           # vanilla player ear: different layout, never seen in Median XL samples -> refused
FLAG_STARTER = 17
FLAG_SIMPLE = 21        # compact item: nothing after the socketed-count bit
FLAG_ETHEREAL = 22
FLAG_ALWAYS = 23        # set on every item of every sample
FLAG_PERSONALIZED = 24
FLAG_RUNEWORD = 26
FLAG_NAMES = {FLAG_IDENTIFIED: 'identified', FLAG_SOCKETED: 'socketed', FLAG_NEW: 'new', FLAG_EAR: 'ear',
              FLAG_STARTER: 'starter', FLAG_SIMPLE: 'simple', FLAG_ETHEREAL: 'ethereal', FLAG_ALWAYS: 'always',
              FLAG_PERSONALIZED: 'personalized', FLAG_RUNEWORD: 'runeword'}

QUALITY = {1: 'low', 2: 'normal', 3: 'superior', 4: 'magic', 5: 'set', 6: 'rare', 7: 'unique', 8: 'crafted',
           9: 'honorific'}
LOCATION = {0: 'stored', 1: 'equipped', 2: 'belt', 4: 'cursor', 6: 'socketed'}
PANEL = {0: 'none', 1: 'inventory', 4: 'cube', 5: 'stash'}

SET_UNIQUE_ID_BITS = 15     # vanilla: 12
AFFIX_BITS = 11
RUNEWORD_BITS = 16          # vanilla: 12 + 4 unknown; read here as one 16-bit field
TOME_CODES = ('tbk ', 'ibk ')


@dataclass
class Stat:
    id: int
    param: Optional[int]    # None when the stat has no parameter
    raw: int                # stored bits; value = raw - save_add
    value: int


@dataclass
class Item:
    flags: int = 0
    version: int = 0
    location: int = 0
    equipped: int = 0
    x: int = 0
    y: int = 0
    panel: int = 0
    code: str = ''
    socketed_count: int = 0
    # ---- extended part (absent on simple items)
    id: Optional[int] = None
    ilvl: Optional[int] = None
    quality: Optional[int] = None
    image: Optional[int] = None             # 3 bits, when the "multiple pictures" bit is set
    auto_affix: Optional[int] = None        # 11 bits, when the "class specific / automagic" bit is set
    subquality: Optional[int] = None        # low / superior: 3 bits
    prefix: Optional[int] = None            # magic: 11 bits
    suffix: Optional[int] = None            # magic: 11 bits
    set_unique_id: Optional[int] = None     # set / unique: 15 bits
    rare_names: Optional[tuple] = None      # rare / crafted / honorific: 8 + 8 bits
    rare_affixes: Optional[list] = None     # rare / crafted: 6 x (1 bit present + 11 bits); None = absent slot
    runeword_id: Optional[int] = None       # 16 bits, flag 26
    personalized_name: Optional[str] = None  # 7-bit characters, 0-terminated, flag 24
    tome_bits: Optional[int] = None         # 5 bits, codes 'tbk ' / 'ibk ' only
    realm_bit: Optional[int] = None         # 1 bit, 0 in every sample (vanilla: "realm data follows")
    defense_raw: Optional[int] = None       # armor: stat 31 width; value = raw - save_add
    max_durability: Optional[int] = None    # armor / weapons: stat 73 width
    durability: Optional[int] = None        # only when max_durability != 0: stat 72 width
    quantity: Optional[int] = None          # stackable bases: 9 bits
    sockets: Optional[int] = None           # 4 bits, flag 11
    set_mask: Optional[int] = None          # set items: 5 bits, one extra stat list per bit
    stats: list = field(default_factory=list)
    set_stats: dict = field(default_factory=dict)      # {bit number 0..4: [Stat]}
    runeword_stats: Optional[list] = None
    padding: int = 0                        # value of the bits that fill the last byte (0 in every sample)
    # ---- bookkeeping (not stored)
    offset: int = -1                        # byte offset of 'JM' in the parsed buffer
    size: int = 0                           # bytes, 'JM' included, socketed items excluded
    socketed: list = field(default_factory=list)

    def flag(self, bit):
        return bool(self.flags >> bit & 1)

    @property
    def simple(self):
        return self.flag(FLAG_SIMPLE)

    @property
    def quality_name(self):
        return QUALITY.get(self.quality, 'simple' if self.quality is None else f'quality {self.quality}')

    def flag_names(self):
        return [FLAG_NAMES.get(b, f'bit{b}') for b in range(32) if self.flags >> b & 1]

    def total_size(self):
        return self.size + sum(s.size for s in self.socketed)

    # ------------------------------------------------------------------ writer
    def to_bytes(self, tables):
        """The item's own bytes ('JM' + bit stream), without its socketed items."""
        w = BitWriter()
        w.write(32, self.flags)
        w.write(10, self.version)
        w.write(3, self.location)
        w.write(4, self.equipped)
        w.write(4, self.x)
        w.write(4, self.y)
        w.write(3, self.panel)
        if len(self.code) != 4:
            raise FormatError(f'item code {self.code!r}: 4 characters expected')
        for ch in self.code:
            w.write(8, ord(ch))
        if self.simple:
            w.write(1, self.socketed_count)
            w.write_padding(self.padding)
            return b'JM' + w.to_bytes()
        w.write(3, self.socketed_count)
        w.write(32, self.id)
        w.write(7, self.ilvl)
        w.write(4, self.quality)
        for value, bits in ((self.image, 3), (self.auto_affix, AFFIX_BITS)):
            w.write(1, value is not None)
            if value is not None:
                w.write(bits, value)
        q = QUALITY.get(self.quality)
        if q in ('low', 'superior'):
            w.write(3, self.subquality)
        elif q == 'magic':
            w.write(AFFIX_BITS, self.prefix)
            w.write(AFFIX_BITS, self.suffix)
        elif q in ('set', 'unique'):
            w.write(SET_UNIQUE_ID_BITS, self.set_unique_id)
        elif q in ('rare', 'crafted', 'honorific'):
            w.write(8, self.rare_names[0])
            w.write(8, self.rare_names[1])
            if q != 'honorific':
                for a in self.rare_affixes:
                    w.write(1, a is not None)
                    if a is not None:
                        w.write(AFFIX_BITS, a)
        if self.flag(FLAG_RUNEWORD):
            w.write(RUNEWORD_BITS, self.runeword_id)
        if self.flag(FLAG_PERSONALIZED):
            for ch in self.personalized_name:
                w.write(7, ord(ch))
            w.write(7, 0)
        if self.code in TOME_CODES:
            w.write(5, self.tome_bits)
        w.write(1, self.realm_bit)
        kind = tables.body_kind(self.code)
        if kind == 'armor':
            w.write(tables.stats[STAT_DEFENSE].save_bits, self.defense_raw)
        if kind in ('armor', 'weapons'):
            w.write(tables.stats[STAT_MAX_DURABILITY].save_bits, self.max_durability)
            if self.max_durability != tables.stats[STAT_MAX_DURABILITY].save_add:
                w.write(tables.stats[STAT_DURABILITY].save_bits, self.durability)
        if tables.base(self.code).stackable:
            w.write(9, self.quantity)
        if self.flag(FLAG_SOCKETED):
            w.write(4, self.sockets)
        if q == 'set':
            w.write(5, self.set_mask)
        _write_stats(w, self.stats, tables)
        if q == 'set':
            for bit in range(5):
                if self.set_mask >> bit & 1:
                    _write_stats(w, self.set_stats[bit], tables)
        if self.flag(FLAG_RUNEWORD):
            _write_stats(w, self.runeword_stats, tables)
        w.write_padding(self.padding)
        return b'JM' + w.to_bytes()

    def to_bytes_with_socketed(self, tables):
        return self.to_bytes(tables) + b''.join(s.to_bytes(tables) for s in self.socketed)

    def as_dict(self, tables=None):
        d = {k: v for k, v in self.__dict__.items()
             if v is not None and k not in ('stats', 'set_stats', 'runeword_stats', 'socketed')}
        d['flag_names'] = self.flag_names()
        d['quality_name'] = self.quality_name
        if tables is not None:
            d['name'] = tables.base_name(self.code)
        d['stats'] = [s.__dict__ for s in self.stats]
        if self.set_stats:
            d['set_stats'] = {str(k): [s.__dict__ for s in v] for k, v in self.set_stats.items()}
        if self.runeword_stats is not None:
            d['runeword_stats'] = [s.__dict__ for s in self.runeword_stats]
        d['socketed'] = [s.as_dict(tables) for s in self.socketed]
        return d


# ---------------------------------------------------------------------- stat lists

def _read_stats(br, tables):
    """A stat list: repeated [9-bit id][param][value], ended by id 0x1FF. Stats of a save group (STAT_GROUPS)
    follow their first member without an id of their own."""
    out = []
    while True:
        sid = br.read(9)
        if sid == 0x1FF:
            return out
        for x in (sid,) + STAT_GROUPS.get(sid, ()):
            sd = tables.stats.get(x)
            if sd is None or not sd.save_bits:
                raise FormatError(f'stat {x} cannot be stored on an item (unknown id or no save width)')
            param = br.read(sd.save_param) if sd.save_param else None
            raw = br.read(sd.save_bits)
            out.append(Stat(x, param, raw, raw - sd.save_add))


def _write_stats(w, stats, tables):
    i = 0
    while i < len(stats):
        sid = stats[i].id
        w.write(9, sid)
        for x in (sid,) + STAT_GROUPS.get(sid, ()):
            if i >= len(stats) or stats[i].id != x:
                raise FormatError(f'stat {x} expected in the save group of stat {sid}')
            sd = tables.stats[x]
            if sd.save_param:
                w.write(sd.save_param, stats[i].param or 0)
            w.write(sd.save_bits, stats[i].raw)
            i += 1
    w.write(9, 0x1FF)


# ---------------------------------------------------------------------- reader

def parse_item(buf, pos, tables):
    """One item at byte `pos` of `buf` (must be 'JM'). Returns the Item (offset / size filled)."""
    if buf[pos:pos + 2] != b'JM':
        raise FormatError(f"'JM' expected at byte {pos}")
    br = BitReader(buf, pos + 2)
    it = Item(offset=pos)
    try:
        _parse_body(it, br, tables)
    except FormatError as e:
        raise FormatError(f'item {it.code!r} at byte {pos}: {e}') from None
    it.size = 2 + br.bytes_used()
    return it


def _parse_body(it, br, tables):
    it.flags = br.read(32)
    if it.flag(FLAG_EAR):
        raise FormatError('ear item (flag 16): layout not implemented, no sample')
    it.version = br.read(10)
    it.location = br.read(3)
    it.equipped = br.read(4)
    it.x = br.read(4)
    it.y = br.read(4)
    it.panel = br.read(3)
    it.code = ''.join(chr(br.read(8)) for _ in range(4))
    base = tables.base(it.code)
    if it.simple:
        it.socketed_count = br.read(1)
        it.padding = br.read_padding()
        return
    it.socketed_count = br.read(3)
    it.id = br.read(32)
    it.ilvl = br.read(7)
    it.quality = br.read(4)
    if br.read(1):
        it.image = br.read(3)
    if br.read(1):
        it.auto_affix = br.read(AFFIX_BITS)
    q = QUALITY.get(it.quality)
    if q in ('low', 'superior'):
        it.subquality = br.read(3)
    elif q == 'magic':
        it.prefix = br.read(AFFIX_BITS)
        it.suffix = br.read(AFFIX_BITS)
    elif q in ('set', 'unique'):
        it.set_unique_id = br.read(SET_UNIQUE_ID_BITS)
    elif q in ('rare', 'crafted', 'honorific'):
        it.rare_names = (br.read(8), br.read(8))
        if q != 'honorific':
            it.rare_affixes = [br.read(AFFIX_BITS) if br.read(1) else None for _ in range(6)]
    elif q != 'normal':
        raise FormatError(f'unknown quality {it.quality}')
    if it.flag(FLAG_RUNEWORD):
        it.runeword_id = br.read(RUNEWORD_BITS)
    if it.flag(FLAG_PERSONALIZED):
        chars = []
        while True:
            c = br.read(7)
            if not c:
                break
            chars.append(chr(c))
        it.personalized_name = ''.join(chars)
    if it.code in TOME_CODES:
        it.tome_bits = br.read(5)
    it.realm_bit = br.read(1)
    kind = tables.body_kind(it.code)
    if kind == 'armor':
        it.defense_raw = br.read(tables.stats[STAT_DEFENSE].save_bits)
    if kind in ('armor', 'weapons'):
        md = tables.stats[STAT_MAX_DURABILITY]
        it.max_durability = br.read(md.save_bits)
        if it.max_durability != md.save_add:
            it.durability = br.read(tables.stats[STAT_DURABILITY].save_bits)
    if base.stackable:
        it.quantity = br.read(9)
    if it.flag(FLAG_SOCKETED):
        it.sockets = br.read(4)
    if q == 'set':
        it.set_mask = br.read(5)
    it.stats = _read_stats(br, tables)
    if q == 'set':
        for bit in range(5):
            if it.set_mask >> bit & 1:
                it.set_stats[bit] = _read_stats(br, tables)
    if it.flag(FLAG_RUNEWORD):
        it.runeword_stats = _read_stats(br, tables)
    it.padding = br.read_padding()


def parse_item_list(buf, pos, count, tables):
    """`count` items from byte `pos`, each followed by its socketed items. Returns (items, next byte)."""
    items = []
    for _ in range(count):
        it = parse_item(buf, pos, tables)
        pos += it.size
        n = it.socketed_count if it.flag(FLAG_SOCKETED) else 0
        for _k in range(n):
            sub = parse_item(buf, pos, tables)
            pos += sub.size
            it.socketed.append(sub)
        items.append(it)
    return items, pos


def build_item_list(items, tables):
    """'JM' + u16 count + the items with their socketed items."""
    return b'JM' + len(items).to_bytes(2, 'little') + b''.join(i.to_bytes_with_socketed(tables) for i in items)


def split_raw(buf, pos, end):
    """Without tables an item cannot be delimited exactly. Best effort for display only: cut at every 'JM'
    between pos and end ('JM' can also occur inside an item's bits, so the result may be wrong)."""
    cuts = []
    p = buf.find(b'JM', pos, end)
    while p >= 0:
        cuts.append(p)
        p = buf.find(b'JM', p + 2, end)
    return [buf[a:b] for a, b in zip(cuts, cuts[1:] + [end])]
