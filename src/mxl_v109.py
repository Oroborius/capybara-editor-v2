"""Pre-1.10 character saves (header version 92, written by 1.09; vanilla folder profiles only, never Median XL).

What differs from a version 96 save (the 1.14d game reads both; its reader takes the save version as an argument):
- 'gf' stats: a 16-bit mask of the stats present (bit i = stat i, ids 0..15 only), then one u32 per set bit in id
  order (life / mana / stamina in 1/256 points as in 96), instead of the 9-bit id + CSvBits bit field.
- Item records: same header layout, but every width / offset comes from the itemstatcost columns "1.09-Save Bits"
  (u8 at row +0x1A) and "1.09-Save Add" (i32 at +0x20) of the selected game folder: defense, max durability,
  socket count and every stat value; current durability is 8 bits. Stat ids 83-87 / 179-180 (one per class),
  107-109 / 181-187 (single skills), 126, 188-193, 195-213 carry packed old forms, and 92, 94, 95, ... are the old
  "fast" twins of 93 / 96 / 99 / 102 / 105. The reader below turns them into the 1.10 ids the tooltips know, like
  the game's own reader (d2-114d-codex specs/items/bitstream-legacy.md section 4).
- A set item's 12-bit index is a sets.txt row there (not setitems): set_item_row turns it into the setitems row of
  that set whose base code is the item's (the first in table order, as the game's reader does).

The editor reads these saves and writes the character values back in the 92 layout; the item records are kept
byte for byte (no 1.09 item writer): item edits are refused (mxl_char)."""
import struct

VERSION = 92

# stored id of the old "fast" twins (the width stays the read id's)
_FAST_TWIN = {92: 93, 94: 93, 95: 96, 97: 96, 98: 99, 100: 99, 101: 102, 103: 102, 104: 105, 106: 105}
_CLASS_SKILL_LAYER = {83: 0, 84: 3, 85: 2, 86: 1, 87: 4, 179: 5, 180: 6}
_SINGLE_SKILL = (107, 108, 109) + tuple(range(181, 188))
_GROUPS = {17: (18,), 48: (49,), 50: (51,), 52: (53,), 54: (55, 56), 57: (58, 59)}


def is_old(raw):
    """True for a d2s whose header version is 92 (1.09)."""
    return len(raw) >= 8 and struct.unpack_from('<I', raw, 4)[0] == VERSION


# ------------------------------------------------------------------ 'gf' section
def read_stats(b, gf):
    """[[sid, None, value], ...] and the offset after the section ('if' expected there)."""
    mask = struct.unpack_from('<H', b, gf + 2)[0]
    p, out = gf + 4, []
    for sid in range(16):
        if mask >> sid & 1:
            out.append([sid, None, struct.unpack_from('<I', b, p)[0]])
            p += 4
    return out, p


def build_stats(stats):
    """Bytes after 'gf': mask + u32 values. Raises ValueError for a stat the layout cannot hold."""
    mask, vals = 0, b''
    for sid, _p, v in sorted(stats, key=lambda st: st[0]):
        if not 0 <= sid < 16 or not 0 <= v < 1 << 32 or mask >> sid & 1:
            raise ValueError(f'stat {sid} = {v}')
        mask |= 1 << sid
        vals += struct.pack('<I', v)
    return struct.pack('<H', mask) + vals


# ------------------------------------------------------------------ item records
def _widths(data):
    """{stat: (1.09 save bits, 1.09 save add)} from the game folder's itemstatcost rows (cached on data)."""
    w = getattr(data, '_v109_widths', None)
    if w is None:
        w = {}
        for r in data._rows('itemstatcost'):
            w[struct.unpack_from('<H', r, 0)[0]] = (r[0x1A], struct.unpack_from('<i', r, 0x20)[0])
        data._v109_widths = w
    return w


class Data109:
    """The game data as the item parser sees it for a version 92 record: itemstatcost widths / offsets from the
    1.09 columns (defense, durability, sockets), current durability 8 bits, and the old stat-list reader."""
    v109 = True

    def __init__(self, data):
        self._data = data
        w = _widths(data)
        isc = dict(data.isc)
        for sid in (31, 72, 73, 194):
            if sid in isc and sid in w:
                isc[sid] = dict(isc[sid], bits=w[sid][0], add=w[sid][1])
        if 72 in isc:
            isc[72] = dict(isc[72], bits=8)
        self.isc = isc

    def __getattr__(self, name):
        return getattr(self._data, name)

    def read_stats(self, br):
        return read_item_stats(br, self._data)


def set_item_row(data, set_row, code):
    """The setitems row of a 1.09 set item: the first row (table order = the set's member list) of sets row
    `set_row` whose item code is `code`, from the selected game folder's tables. No match (the game refuses such
    an item): `set_row` unchanged, so the item still reads."""
    try:
        for i, r in enumerate(unwrap(data).set_items):
            if r.get('set_id') == set_row and r.get('code') == code:
                return i
    except Exception as e:
        print('1.09 set item:', e)
    return set_row


def unwrap(data):
    return getattr(data, '_data', data)


def _entry(data, sid, param, value, pos):
    c = data.isc.get(sid, {})
    return {'id': sid, 'param': param, 'value': value, 'pos': pos, 'desc': c.get('desc', ''),
            'bits': c.get('bits', 0), 'add': c.get('add', 0)}


def read_item_stats(br, data):
    """One stat list of a version 92 item record, as the 1.14d reader does it: ends at 0x1FF, or (without a
    failure) at an id with no itemstatcost row. Entries use the 1.10 ids / layers."""
    w = _widths(data)
    out = []
    prev = None
    while True:
        pos = br.pos
        sid = br.read(9)
        if sid == 0x1FF or sid not in w:
            break
        if sid == 0 and prev == 0:
            break
        prev = sid

        def isc(s):
            bits, add = w.get(s, (0, 0))
            return br.read(bits) - add
        if sid in _GROUPS:
            out.append(_entry(data, sid, None, isc(sid), pos))
            for s in _GROUPS[sid]:
                out.append(_entry(data, s, None, isc(s), pos))
        elif sid in _CLASS_SKILL_LAYER:
            out.append(_entry(data, 83, _CLASS_SKILL_LAYER[sid], br.read(3), pos))
        elif sid in _SINGLE_SKILL:
            v = br.read(14)
            skill, level = v & 0x1FF, v >> 9
            top = (1 << data.isc.get(107, {}).get('bits', 3)) - 1
            if 0 < level <= top:
                out.append(_entry(data, 107, skill, level, pos))
        elif sid == 126:
            out.append(_entry(data, 126, 1, br.read(4), pos))
        elif 188 <= sid <= 193:
            v = br.read(10)
            n = v & 0x1F
            out.append(_entry(data, 188, n % 3 + 8 * (n // 3), min(v >> 5, 7), pos))
        elif 195 <= sid <= 203:
            v = br.read(21)
            base = 195 + (sid - 195) // 3 * 3
            out.append(_entry(data, base, 64 * (v & 0x1FF) + (v >> 9 & 0x1F), v >> 14, pos))
        elif 204 <= sid <= 213:
            v = br.read(30)
            out.append(_entry(data, 204, ((v & 0x1FF) << 6) + (v >> 9 & 0x1F), (v >> 14 & 0xFF) + 256 * (v >> 22),
                              pos))
        else:
            out.append(_entry(data, _FAST_TWIN.get(sid, sid), None, isc(sid), pos))
    lay = {st['param']: st['value'] for st in out if st['id'] == 83}
    x = lay.get(0, 0)
    if x > 0 and all(lay.get(k) == x for k in (1, 2, 3, 4)):
        out = [st for st in out if st['id'] != 83] + [_entry(data, 127, None, x, out[0]['pos'])]
    return out
