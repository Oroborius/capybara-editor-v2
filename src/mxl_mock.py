"""Mock Mode engine: analyzer and generator of Diablo II "mock pi" / "funky pi" PvP characters (vanilla LoD
1.10-1.14d, d2s version 96). No GUI here (see mxl_mock_gui.py); everything is testable without a window.

Knowledge: docs/review/mock-pi.md (sections 2, 3, 6, 8, 9) and the user's own rules in
docs/review/mock-pi-user-notes.md (authoritative). The band / mana rule follows our research script
docs/review/mock-pi-data/bands.py: mana = (base + sum(+mana) + 20 Sigon's full-set bonus) x (100 + sum(mana%)) / 100,
item Energy not counted, the inactive weapon pair left out, charms only from the inventory.

Parts:
- a vanilla item codec (encode_item / decode_item) that writes stat lines in the given order without merging
  (the creator's encoder merges and sorts lines, which mock items must not do);
- model_from_character(ch) + analyze(model): computed values with good / warn / bad checks;
- PRESETS, plan(...) (integer solvers for mana, life, regen, damage; aura source plan) and generate(...) -> bytes;
- write_new(raw, folder, name): a NEW .d2s with a non-colliding name (exclusive create, never overwrites).
"""
import math
import os
import random
import struct
import time
from fractions import Fraction

ROLL = 8388607                      # 2^23 - 1: the signed 32-bit fixed-point (8 fraction bits) roll point
PVP = Fraction(17, 100)             # PvP damage penalty
DMG_CAP_PVP = Fraction(ROLL) * PVP / 2      # (8388607 * PvP penalty) / 2 = 713031.6 (after 50% DR)
SET_BONUS = 20                      # Sigon's Complete Steel full-set bonus: +20 mana (sets.txt)
SIGON_SET_IDS = tuple(range(35, 41))
INT_MIN = -(1 << 31)
FILE_LIMIT = 8192

# aura skill ids; the highest id on an item is that item's active source
PRAYER, HOLY_FIRE, THORNS, HOLY_FREEZE, HOLY_SHOCK, MEDITATION = 99, 102, 103, 114, 118, 120
CONVICTION, SALVATION, SANCTUARY, BARBS, OAK = 123, 125, 119, 296, 298
AURA_NAMES = {PRAYER: 'Prayer', HOLY_FIRE: 'Holy Fire', THORNS: 'Thorns', HOLY_FREEZE: 'Holy Freeze',
              HOLY_SHOCK: 'Holy Shock', MEDITATION: 'Meditation', CONVICTION: 'Conviction', SALVATION: 'Salvation',
              SANCTUARY: 'Sanctuary', BARBS: 'Barbs Aura', OAK: 'Oak Sage Aura', 98: 'Might', 100: 'Resist Fire',
              101: 'Defiance', 104: 'Cleansing', 105: 'Resist Cold', 108: 'Blessed Aim', 109: 'Concentration',
              110: 'Resist Lightning', 113: 'Vigor', 115: 'Fanaticism', 122: 'Redemption', 124: 'Resist All'}
# stacking auras: all levels add up and ONE aura launches (S6, doc 8.4); the others launch one source per item
STACKING = {THORNS, MEDITATION, BARBS, OAK}

SMITE, STUN, DELIRIUM, BATTLE_ORDERS = 97, 139, 350, 149
NV_JUST_HIT, NV_HOLY_SHIELD = 86, 101    # NV states of clone-99 (stat 98)
DOPPLEZON = 63                      # NV state Dopplezon: item stat 98 (state), param 63, value 1 (reference clone-05)
SOR_FIRST_SKILL = 36                # Sorceress class skills 36..65 (30 bytes of the 'if' section)
TELEKINESIS, WARMTH, ENERGY_SHIELD = 43, 37, 58
CLASS_FIRST_SKILL = (6, 36, 66, 96, 126, 221, 251)
CLASSES = ('Amazon', 'Sorceress', 'Necromancer', 'Paladin', 'Barbarian', 'Druid', 'Assassin')
CHARMS = ('cm1 ', 'cm2 ', 'cm3 ')
# shield base damage used by Smite (armor.txt mindam / maxdam; vanilla 1.10-1.14d)
SHIELD_DMG = {'buc ': (1, 3), 'sml ': (2, 3), 'lrg ': (2, 4), 'kit ': (2, 5), 'tow ': (1, 5), 'gts ': (2, 6),
              'bsh ': (3, 6), 'spk ': (5, 9), 'xuc ': (8, 12), 'xml ': (7, 14), 'xrg ': (11, 15), 'xit ': (15, 24),
              'xow ': (10, 17), 'xts ': (12, 16), 'xsh ': (14, 20), 'xpk ': (18, 35), 'pa1 ': (2, 6), 'pa2 ': (2, 8),
              'pa3 ': (3, 9), 'pa4 ': (4, 10), 'pa5 ': (4, 12), 'uuc ': (16, 30), 'uml ': (17, 29), 'urg ': (14, 32),
              'uit ': (12, 34), 'uow ': (18, 28), 'uts ': (11, 35), 'ush ': (24, 38), 'upk ': (26, 40),
              'pa6 ': (12, 16), 'pa7 ': (15, 20), 'pa8 ': (18, 24), 'pa9 ': (20, 28), 'paa ': (24, 32),
              'pab ': (22, 70), 'pac ': (35, 58), 'pad ': (10, 82), 'pae ': (46, 46), 'paf ': (5, 87)}
# user (2026-11-20): the smite cap is 8388607 before any penalty / reduction; one point over rolls over and deals 1
# (as bad as no damage), so the analyzer scores > 8388607 BAD. The in-game rounding is unverified (Equilibrium's
# README 713029.5 PvP is ~113 PvM under our formula), so the generator aims SMITE_SLACK under the cap.
SMITE_SLACK = 100
SMITE_TARGET = ROLL - SMITE_SLACK

# vanilla 1.10-1.14d item save widths (ItemStatCost: save bits, save add, save param bits) of the stats the
# generator writes; the decoder takes the profile's own table (any stat)
VANILLA_ISC = {0: (8, 32, 0), 1: (7, 32, 0), 2: (7, 32, 0), 3: (7, 32, 0), 7: (9, 32, 0), 9: (8, 32, 0),
               21: (6, 0, 0), 22: (7, 0, 0), 27: (8, 0, 0), 34: (6, 0, 0), 36: (8, 0, 0), 39: (8, 50, 0),
               41: (8, 50, 0), 43: (8, 50, 0), 45: (8, 50, 0), 74: (6, 30, 0), 76: (6, 10, 0), 77: (6, 10, 0), 93: (7, 20, 0),
               97: (6, 0, 9), 98: (1, 0, 8), 99: (7, 20, 0), 107: (3, 0, 9), 111: (9, 20, 0), 114: (6, 0, 0),
               135: (7, 0, 0), 136: (7, 0, 0), 142: (7, 0, 0), 144: (7, 0, 0), 148: (7, 0, 0), 151: (5, 0, 9),
               194: (4, 0, 0), 195: (7, 0, 16), 198: (7, 0, 16), 220: (6, 0, 0), 230: (6, 0, 0), 231: (6, 0, 0),
               232: (6, 0, 0), 233: (6, 0, 0), 234: (6, 0, 0), 235: (6, 0, 0), 236: (6, 0, 0),
               288: (22, 0, 0), 289: (22, 0, 0), 290: (22, 0, 0), 329: (9, 50, 0),
               330: (9, 50, 0), 331: (9, 50, 0),
               # the clones' other categories (vanilla ItemStatCost widths, read from the 1.14d tables)
               35: (6, 0, 0), 40: (5, 0, 0), 42: (5, 0, 0), 44: (5, 0, 0), 67: (7, 30, 0), 68: (7, 30, 0),
               96: (7, 20, 0), 99: (7, 20, 0), 105: (7, 20, 0), 109: (9, 0, 0), 115: (1, 0, 0), 116: (7, 0, 0),
               141: (7, 0, 0), 143: (7, 0, 0), 145: (7, 0, 0), 146: (7, 0, 0), 149: (7, 0, 0), 153: (1, 0, 0),
               238: (5, 0, 0), 333: (8, 0, 0), 334: (8, 0, 0), 335: (8, 0, 0), 338: (7, 0, 0), 339: (7, 0, 0),
               340: (7, 0, 0)}
LINE_CAP = 30                       # user: at most 30 lines per stat list (magic, each set list, runeword list)
GROUPS = {17: (18,), 48: (49,), 50: (51,), 52: (53,), 54: (55, 56), 57: (58, 59)}   # written as one line
PER_LEVEL = {216, 217, 220, 221, 222, 223, 224, 230, 231, 232, 233, 234, 235, 236, 238}   # value x clvl / 8


def line_max(sid):
    bits, add, _ = VANILLA_ISC[sid]
    return (1 << bits) - 1 - add


def line_min(sid):
    return -VANILLA_ISC[sid][1]


def line_bits(sid):
    bits, _, par = VANILLA_ISC[sid]
    return 9 + par + bits


# ============================================================================================ bit I/O
class BitWriter:
    def __init__(self):
        self.v = 0
        self.n = 0

    def write(self, n, x):
        if n <= 0:
            return
        if not 0 <= x < (1 << n):
            raise ValueError(f'{x} does not fit in {n} bits')
        self.v |= x << self.n
        self.n += n

    def align(self, pad=0):
        k = (-self.n) % 8
        self.write(k, pad & ((1 << k) - 1))

    def bytes(self):
        return self.v.to_bytes((self.n + 7) // 8, 'little')


class BitReader:
    def __init__(self, b, pos=0):
        self.v = int.from_bytes(b, 'little')
        self.pos = pos
        self.n = len(b) * 8

    def read(self, n):
        if self.pos + n > self.n:
            raise ValueError('read past the end')
        r = (self.v >> self.pos) & ((1 << n) - 1)
        self.pos += n
        return r

    def align(self):
        k = (-self.pos) % 8
        return self.read(k) if k else 0


# ============================================================================================ item codec
FLAG_IDENTIFIED, FLAG_SOCKETED, FLAG_EAR = 0x10, 0x800, 0x10000
FLAG_SIMPLE, FLAG_ETHEREAL, FLAG_PERSONALIZED, FLAG_RUNEWORD = 0x200000, 0x400000, 0x1000000, 0x4000000
FLAG_ALWAYS = 0x800000              # set on every item of the samples
ITEM_VERSION = 100                  # the reference mocks' item version field (10 bits)


class CodecError(Exception):
    pass


def isc_from_data(data):
    """Width lookup (save bits, save add, save param bits) from the editor's tables (data.isc)."""
    def get(sid):
        c = data.isc[sid]
        return c['bits'], c['add'], c['param'] or 0
    return get


def base_from_data(data):
    """Item kind lookup: code -> (kind 'armor' / 'weapons' / 'misc', stackable)."""
    def get(code):
        b = data.base(code)
        return b.kind, b.stack_max is not None
    return get


def _vanilla_isc(sid):
    return VANILLA_ISC[sid]


_KIND = {'ghm ': 'armor', 'gth ': 'armor', 'hgl ': 'armor', 'hbt ': 'armor', 'hbl ': 'armor', 'tow ': 'armor',
         'amu ': 'misc', 'rin ': 'misc', 'jew ': 'misc', 'cm1 ': 'misc', 'cm2 ': 'misc', 'cm3 ': 'misc',
         'crs ': 'weapons'}


def _vanilla_base(code):
    return _KIND[code], False


def _read_list(br, isc):
    out = []
    while True:
        sid = br.read(9)
        if sid == 0x1FF:
            return out
        for k in (sid,) + GROUPS.get(sid, ()):
            bits, add, par = isc(k)
            if not bits:
                raise CodecError(f'stat {k} has no save width')
            p = br.read(par) if par else None
            out.append((k, p, br.read(bits) - add))


def _write_list(bw, lines, isc):
    i = 0
    while i < len(lines):
        sid = lines[i][0]
        group = (sid,) + GROUPS.get(sid, ())
        bw.write(9, sid)
        for k in group:
            if i >= len(lines) or lines[i][0] != k:
                raise CodecError(f'stat group {group}: {k} missing')
            _, p, v = lines[i]
            bits, add, par = isc(k)
            if par:
                bw.write(par, p or 0)
            raw = v + add
            if not 0 <= raw < (1 << bits):
                raise CodecError(f'stat {k}: {v} cannot be stored ({-add} to {(1 << bits) - 1 - add})')
            bw.write(bits, raw)
            i += 1
    bw.write(9, 0x1FF)


def decode_item(b, isc, base, pos=0):
    """One item (no socketed children) from b[pos:] ('JM' first): (record, end offset). The record keeps every
    field (and the padding bits) so encode_item gives the same bytes."""
    if b[pos:pos + 2] != b'JM':
        raise CodecError(f'no JM at {pos}')
    br = BitReader(b[pos + 2:])
    r = dict(flags=br.read(32), version=br.read(10), location=br.read(3), equipped=br.read(4), x=br.read(4),
             y=br.read(4), panel=br.read(3))
    f = r['flags']
    if f & FLAG_EAR:
        r['ear_class'], r['ear_level'] = br.read(3), br.read(7)
        nm = []
        while True:
            c = br.read(7)
            nm.append(c)
            if not c:
                break
        r['ear_name'] = nm
        r['pad'] = br.align()
        return r, pos + 2 + br.pos // 8
    r['code'] = code = ''.join(chr(br.read(8)) for _ in range(4))
    if f & FLAG_SIMPLE:
        r['socketed_count'] = br.read(1)
        r['pad'] = br.align()
        return r, pos + 2 + br.pos // 8
    r['socketed_count'] = br.read(3)
    r['id'], r['ilvl'], r['quality'] = br.read(32), br.read(7), br.read(4)
    r['image'] = br.read(3) if br.read(1) else None
    r['auto_affix'] = br.read(11) if br.read(1) else None
    q = r['quality']
    if q in (1, 3):
        r['subquality'] = br.read(3)
    elif q == 4:
        r['prefix'], r['suffix'] = br.read(11), br.read(11)
    elif q in (5, 7):
        r['set_unique_id'] = br.read(12)
    elif q in (6, 8):
        r['rare_names'] = (br.read(8), br.read(8))
        r['rare_affixes'] = [br.read(11) if br.read(1) else None for _ in range(6)]
    if f & FLAG_RUNEWORD:
        r['runeword_id'] = br.read(16)
    if f & FLAG_PERSONALIZED:
        nm = []
        while True:
            c = br.read(7)
            nm.append(c)
            if not c:
                break
        r['personalized'] = nm
    if code in ('tbk ', 'ibk '):
        r['tome_bits'] = br.read(5)
    r['realm_bit'] = br.read(1)
    kind, stack = base(code)
    if kind == 'armor':
        r['defense_raw'] = br.read(11)
    if kind in ('armor', 'weapons'):
        r['max_durability'] = br.read(8)
        if r['max_durability']:
            r['durability'] = br.read(9)
    if stack:
        r['quantity'] = br.read(9)
    if f & FLAG_SOCKETED:
        r['sockets'] = br.read(4)
    mask = br.read(5) if q == 5 else 0
    r['set_mask'] = mask
    r['lists'] = [_read_list(br, isc)]
    r['set_lists'] = [_read_list(br, isc) if mask >> i & 1 else None for i in range(5)]
    if f & FLAG_RUNEWORD:
        r['rw_list'] = _read_list(br, isc)
    r['pad'] = br.align()
    return r, pos + 2 + br.pos // 8


def encode_item(r, isc=_vanilla_isc, base=_vanilla_base):
    """Bytes ('JM' + bits) of one item record (the decode_item layout); lines are written in the given order."""
    bw = BitWriter()
    f = r['flags']
    for n, k in ((32, 'flags'), (10, 'version'), (3, 'location'), (4, 'equipped'), (4, 'x'), (4, 'y'),
                 (3, 'panel')):
        bw.write(n, r.get(k, 0))
    if f & FLAG_EAR:
        bw.write(3, r['ear_class'])
        bw.write(7, r['ear_level'])
        for c in r['ear_name']:
            bw.write(7, c)
        bw.align(r.get('pad', 0))
        return b'JM' + bw.bytes()
    code = r['code']
    for ch in code:
        bw.write(8, ord(ch))
    if f & FLAG_SIMPLE:
        bw.write(1, r.get('socketed_count', 0))
        bw.align(r.get('pad', 0))
        return b'JM' + bw.bytes()
    bw.write(3, r.get('socketed_count', 0))
    bw.write(32, r['id'])
    bw.write(7, r['ilvl'])
    q = r['quality']
    bw.write(4, q)
    for key, n in (('image', 3), ('auto_affix', 11)):
        if r.get(key) is None:
            bw.write(1, 0)
        else:
            bw.write(1, 1)
            bw.write(n, r[key])
    if q in (1, 3):
        bw.write(3, r.get('subquality', 0))
    elif q == 4:
        bw.write(11, r['prefix'])
        bw.write(11, r['suffix'])
    elif q in (5, 7):
        bw.write(12, r['set_unique_id'])
    elif q in (6, 8):
        bw.write(8, r['rare_names'][0])
        bw.write(8, r['rare_names'][1])
        for a in r['rare_affixes']:
            if a is None:
                bw.write(1, 0)
            else:
                bw.write(1, 1)
                bw.write(11, a)
    if f & FLAG_RUNEWORD:
        bw.write(16, r.get('runeword_id', 0xFFFF))
    if f & FLAG_PERSONALIZED:
        for c in r['personalized']:
            bw.write(7, c)
    if code in ('tbk ', 'ibk '):
        bw.write(5, r.get('tome_bits', 0))
    bw.write(1, r.get('realm_bit', 0))
    kind, stack = base(code)
    if kind == 'armor':
        bw.write(11, r.get('defense_raw', 10))
    if kind in ('armor', 'weapons'):
        bw.write(8, r.get('max_durability', 0))
        if r.get('max_durability'):
            bw.write(9, r.get('durability', 0))
    if stack:
        bw.write(9, r.get('quantity', 1))
    if f & FLAG_SOCKETED:
        bw.write(4, r.get('sockets', 0))
    mask = r.get('set_mask', 0) if q == 5 else 0
    if q == 5:
        bw.write(5, mask)
    lists = r.get('lists') or [[]]
    _write_list(bw, lists[0], isc)
    sl = r.get('set_lists') or [None] * 5
    for i in range(5):
        if mask >> i & 1:
            _write_list(bw, sl[i] or [], isc)
    if f & FLAG_RUNEWORD:
        _write_list(bw, r.get('rw_list') or [], isc)
    bw.align(r.get('pad', 0))
    return b'JM' + bw.bytes()


def decode_blob(blob, isc, base):
    """A top-level item with its socketed children (an Entry.blob of mxl_char): [records]."""
    out, pos = [], 0
    rec, pos = decode_item(blob, isc, base, pos)
    out.append(rec)
    for _ in range(rec.get('socketed_count', 0) if not rec['flags'] & FLAG_SIMPLE else 0):
        ch, pos = decode_item(blob, isc, base, pos)
        out.append(ch)
    if pos != len(blob):
        raise CodecError(f'{len(blob) - pos} bytes left after the item')
    return out


# ============================================================================================ analyzer
class Unit:
    """One aura 'source' holder: a top-level item (its own + set lists), a socketed jewel or a charm."""
    __slots__ = ('kind', 'name', 'lists', 'side')

    def __init__(self, kind, name, lists, side=None):
        self.kind, self.name, self.lists, self.side = kind, name, lists, side

    def lines(self):
        for L in self.lists:
            yield from L

    def auras(self):
        return {p for L in self.lists for sid, p, v in L if sid == 151 and v > 0}

    def source(self):
        a = self.auras()
        return max(a) if a else None


def _side_of_body(body):
    """Weapon side of an equipped body slot: 'A' (4/5, the first pair), 'B' (11/12), None (both)."""
    return 'A' if body in (4, 5) else 'B' if body in (11, 12) else None


def model_from_character(ch, size=None):
    """Neutral model of a mxl_char.Character (any class): header values, character stats, skills, units."""
    head = bytes(ch.head)
    st = {sid: v for sid, p, v in ch.stats}
    cls = head[0x28]
    skills = bytes(ch.skills[2:])
    first = CLASS_FIRST_SKILL[cls] if cls < 7 else 0
    sk = {first + i: lv for i, lv in enumerate(skills) if lv}
    units = []

    def lists_of(it):
        L = [[(s['id'], s.get('param'), s['value']) for s in it.get('stats', [])]]
        for i in range(5):
            if it.get(f'set_stats_{i}') is not None:
                L.append([(s['id'], s.get('param'), s['value']) for s in it[f'set_stats_{i}']])
        if it.get('stats_runeword') is not None:
            L.append([(s['id'], s.get('param'), s['value']) for s in it['stats_runeword']])
        return L

    set_ids = {'A': set(), 'B': set(), None: set()}
    shields = {}
    excess = 0
    for e in ch.items:
        it = e.it
        code = it.get('code', '')
        if it.get('location') == 1:
            side = _side_of_body(it.get('equipped'))
            nm = f"{code.strip()}@{it.get('equipped')}"
            units.append(Unit('gear', nm, lists_of(it), side))
            if it.get('quality') in (5, 'set'):
                set_ids[side].add(it.get('set_unique_id'))
            if it.get('equipped') in (4, 5, 11, 12) and code in SHIELD_DMG:
                shields[side] = code
            kids = it.get('socketed') or []
            field = it.get('sockets') or 0
            if code in ('rin ', 'amu '):
                field = 0                            # the game clamps the field to the base's sockets (none here)
            elif code in SOCKET_FIELD:
                field = min(field, SOCKET_FIELD[code])
            cap = field + sum(s['value'] for s in it.get('stats', []) if s['id'] == 194)
            excess += max(0, len(kids) - cap)
            for j, s in enumerate(kids[:cap]):          # the game drops children beyond the socket count
                units.append(Unit('jewel', f'{nm}/{j}', lists_of(s), side))
        elif it.get('location') == 0 and it.get('panel') == 1 and code in CHARMS:
            units.append(Unit('charm', f"{code.strip()}@{it.get('x')},{it.get('y')}", lists_of(it)))
    return dict(name=ch.name, cls=cls, level=st.get(12, 0), active_weapon=struct.unpack_from('<I', head, 0x10)[0],
                base_str=st.get(0, 0), base_ene=st.get(1, 0), base_vit=st.get(3, 0),
                base_mana_raw=st.get(9, 0), base_life_raw=st.get(7, 0), stat_points=st.get(4, 0), skills=sk,
                units=units, set_ids=set_ids,
                shields=shields, size=size if size is not None else len(ch.raw), excess_jewels=excess)


def wrap32(x):
    return ((x + (1 << 31)) % (1 << 32)) - (1 << 31)


def band_info(mana, tk):
    """Mana (Fraction) and hard Telekinesis level -> band facts (doc 2.2 / 8.1)."""
    q = max(32 - tk, 1)
    width = (1 << 19) * q
    m = math.floor(mana * 256)                      # current mana in 1/256 units
    cap = wrap32((m // q) * 16)                     # pct(m, 16, q) = (m / q) x 16 in signed 32-bit
    k = math.floor(mana / width)
    good = k % 2 == 0
    funky = cap == INT_MIN
    top = (k + 1) * width - 1 if good else None
    return dict(q=q, ratio=Fraction(16, q), width=width, band=k, good=good, funky=funky,
                stable=funky and q % 2 == 0, offscreen=Fraction(cap, 256), to_roll=(top - mana) if good else None,
                exact=Fraction(mana) == int(mana))


def regen_cap(mana):
    """Highest mana regen % before the per-frame regen rolls over: floor((8388607 / mana) x 3000 - 100)."""
    return math.floor(Fraction(ROLL) * 3000 / Fraction(mana) - 100) if mana > 0 else 10 ** 9


def warmth_pct(lvl):
    return 30 + 12 * (lvl - 1) if lvl > 0 else 0


def meditation_pct(lvl):
    return 300 + 25 * (lvl - 1) if lvl > 0 else 0


def oak_pct(lvl):
    return 30 + 5 * (lvl - 1) if lvl > 0 else 0


def thorns_pct(lvl):
    return 250 + 40 * (lvl - 1) if lvl > 0 else 0


def barbs_pct(lvl):
    return 50 + 10 * (lvl - 1) if lvl > 0 else 0


def prayer_heal(lvl):
    """Life healed per source every 2 s (doc 2.5, lvl >= 28)."""
    return (lvl - 28) * 3 + 41 if lvl >= 28 else 2 * lvl


def prayer_drain(lvl):
    return (lvl - 28) * 0.376 + 6 if lvl >= 28 else 1


def holy_freeze_dmg(lvl, top=False):
    """Cold damage per source (PvM, before mastery; doc 2.5: (lvl - 28) x 5 + 67 .. 68); top: the maximum."""
    return (lvl - 28) * 5 + (68 if top else 67) if lvl >= 28 else 5 + lvl


def active_units(model, side=None):
    """Units that count on a weapon side ('A' / 'B'; default: the side the header says is in use)."""
    if side is None:
        side = 'B' if model['active_weapon'] else 'A'
    return [u for u in model['units'] if u.side in (None, side)], side


def totals(model, side=None):
    units, side = active_units(model, side)
    T, N = {}, {}
    aura_lv, sources, ctc, nonclass, names = {}, {}, [], {}, {}
    nlists, longest = 0, 0
    for u in units:
        nlists += len(u.lists)
        longest = max([longest] + [len(L) for L in u.lists])
        for sid, p, v in u.lines():
            T[sid] = T.get(sid, 0) + v
            N[sid] = N.get(sid, 0) + 1
            if sid == 151:
                aura_lv[p] = aura_lv.get(p, 0) + v
            elif sid in (195, 198, 201) and p is not None:
                ctc.append((sid, p >> 6, p & 63, v))
            elif sid in (97, 107) and p is not None:
                nonclass[p] = nonclass.get(p, 0) + v
        s = u.source()
        if s is not None:
            sources.setdefault(s, {}).setdefault(u.kind, 0)
            sources[s][u.kind] += 1
            names.setdefault(s, []).append(u.name)
    return dict(units=units, side=side, T=T, N=N, aura_lv=aura_lv, sources=sources, ctc=ctc, nonclass=nonclass,
                lists=nlists, longest=longest, source_units=names)


# in game, before the duel (the clones' "how to use": shift-click the 1023 attributes into Energy, cast BO + ES)
MANA_PER_ENERGY = (Fraction(3, 2), 2, 2, Fraction(3, 2), 1, 2, Fraction(7, 4))   # charstats ManaPerMagic / 4


def bo_pct(model, t):
    """Battle Orders max life / mana %: 35 + 3 per level after the first; the clones2 top-band manas fit an
    effective level of at most 99 (clone-45, clone-67, clone-52: two 63 lines -> 99, not 126)."""
    lv = min(99, t['nonclass'].get(BATTLE_ORDERS, 0) + (model['skills'].get(BATTLE_ORDERS, 0)))
    return 35 + 3 * (lv - 1) if lv else 0


def pct_fp(v, pct):
    """The game's percent step on a 1/256 fixed-point value: v + (v // 100) x pct (the hundredth is truncated
    first). Measured in 1.14d: generated MockHigh 1572480 (the exact product said 1572500.1), FunkyXXX 1048560
    (said 1048576); clone-63 and the other v // 100-exact funkies stay at 1048576."""
    return v + (v // 100) * pct


def mana_of(model, t, bo=False, energy=False):
    full = all(i in (model['set_ids'][None] | model['set_ids'][t['side']]) for i in SIGON_SET_IDS)
    v = model['base_mana_raw']
    if energy and model['cls'] < 7:
        v += int(model.get('stat_points', 0) * Fraction(MANA_PER_ENERGY[model['cls']]) * 256)
    v += 256 * (t['T'].get(9, 0) + (SET_BONUS if full else 0))
    return Fraction(pct_fp(v, t['T'].get(77, 0) + (bo_pct(model, t) if bo else 0)), 256), full


def life_of(model, t, bo=False):
    T = t['T']
    oak = t['aura_lv'].get(OAK, 0)
    vit_life = {0: 3, 1: 2, 2: 2, 3: 3, 4: 4, 5: 2, 6: 3}.get(model['cls'], 2)
    v = model['base_life_raw'] + 256 * (T.get(7, 0) + vit_life * T.get(3, 0))
    return Fraction(pct_fp(v, T.get(76, 0) + oak_pct(oak) + (bo_pct(model, t) if bo else 0)), 256)


def solve_fp(target, pct, exact):
    """Smallest fixed-point X with pct_fp(X, pct) == 256 x target (exact) or floor(pct_fp / 256) == target."""
    T = 256 * Fraction(target)
    if T.denominator != 1:
        return None
    T = int(T)
    m = 100 + pct
    if m <= 0:
        return None
    q0 = T // m
    for q in (q0 - 1, q0, q0 + 1):                      # pct_fp(100 q + r) = q m + r, 0 <= r < 100
        if q < 0:
            continue
        r = max(0, T - q * m)
        if r > 99:
            continue
        v = q * m + r
        if v == T or (not exact and T <= v < T + 256):
            return 100 * q + r
    return None


def smite_of(model, t):
    """Smite damage (PvM min, max) with the equipped shield: (shield + flat) x (100 + 15 x slvl + str%) / 100."""
    T, lvl = t['T'], model['level']
    shield = model['shields'].get(t['side']) or model['shields'].get(None)
    smin, smax = SHIELD_DMG.get(shield, (0, 0))
    # effective level at most 99, like BO (bo_pct): clone-45' two Smite 63 lines give a capped 8382830, not 8462500
    slvl = min(99, t['nonclass'].get(SMITE, 0) + (model['skills'].get(SMITE, 0)))
    strength = model['base_str'] + T.get(0, 0) + T.get(220, 0) * lvl // 8
    mult = 100 + 15 * slvl + strength
    lo = (smin + T.get(111, 0) + T.get(21, 0)) * mult // 100
    hi = (smax + T.get(111, 0) + T.get(22, 0)) * mult // 100
    return dict(shield=shield, slvl=slvl, strength=strength, mult=mult, min=lo, max=hi)


GOOD, WARN, BAD, INFO = 'good', 'warn', 'bad', 'info'


def analyze(model, side=None, bo=False, energy=False):
    """Computed values and colour-coded checks of a character model: dict(values, checks=[(key, label, text,
    status)]). Covers mana band / funky, TK ratio, off-screen, regen vs roll-over, life, smite vs cap, aura
    sources and levels, Prayer heal / drain vs regen, stun vs stability, lists and file size. bo / energy: the
    in-game values after casting Battle Orders / spending the unspent attribute points on Energy."""
    t = totals(model, side)
    T = t['T']
    tk = model['skills'].get(TELEKINESIS, 0) if model['cls'] == 1 else 0
    mana, full = mana_of(model, t, bo, energy)
    b = band_info(mana, tk)
    warmth = warmth_pct(model['skills'].get(WARMTH, 0) if model['cls'] == 1 else 0)
    med = t['aura_lv'].get(MEDITATION, 0)
    regen = T.get(27, 0) + warmth + (meditation_pct(med) if med and MEDITATION in t['sources'] else 0)
    cap = regen_cap(mana)
    life = life_of(model, t, bo)
    sm = smite_of(model, t)
    pvp = Fraction(sm['max']) * PVP / 2
    prayer_lv = t['aura_lv'].get(PRAYER, 0)
    prayer_src = sum(t['sources'].get(PRAYER, {}).values())
    heal_s = prayer_heal(prayer_lv) * prayer_src / 2 if prayer_src else 0
    drain_s = prayer_drain(prayer_lv) * prayer_src / 2 if prayer_src else 0
    regen_s = float(mana) / 120 * (100 + regen) / 100
    stun = [(k, lv, c) for k, sk, lv, c in t['ctc'] if sk == STUN and k in (195, 198)]
    deli = [(k, lv, c) for k, sk, lv, c in t['ctc'] if sk == DELIRIUM and k in (195, 198)]
    stun_total = sum(c for _, _, c in stun)
    hf_lv = t['aura_lv'].get(HOLY_FREEZE, 0)
    hf_src = sum(t['sources'].get(HOLY_FREEZE, {}).values())
    hf_dmg = holy_freeze_dmg(hf_lv) * (100 + T.get(331, 0)) / 100 if hf_lv else 0
    hf_top = holy_freeze_dmg(hf_lv, True) * (100 + T.get(331, 0)) / 100 if hf_lv else 0
    v = dict(mana=mana, full_set=full, tk=tk, band=b, regen=regen, regen_cap=cap, warmth=warmth, meditation=med,
             life=life, smite=sm, smite_pvp=pvp, prayer_level=prayer_lv, prayer_sources=prayer_src,
             prayer_heal_s=heal_s, prayer_drain_s=drain_s, regen_s=regen_s, stun=stun, stun_total=stun_total,
             delirium=deli, aura_levels={AURA_NAMES.get(k, str(k)): x for k, x in t['aura_lv'].items()},
             sources={AURA_NAMES.get(k, str(k)): dict(x) for k, x in t['sources'].items()},
             hf_per_source=hf_dmg, hf_sources=hf_src, lists=t['lists'], size=model['size'], side=t['side'],
             dtm=T.get(114, 0), dr=T.get(34, 0), dr_pct=T.get(36, 0), units=len(t['units']))
    C = []

    def add(key, label, text, status):
        C.append((key, label, text, status))

    if b['funky']:
        how = 'stable, q even' if b['stable'] else 'UNSTABLE, q odd'
        add('mana', 'Mana', f"{_num(mana)}  FUNKY zero (k={b['band']}, {how})", GOOD if b['stable'] else WARN)
    elif b['good']:
        add('mana', 'Mana', f"{_num(mana)}  good band {b['band']} ({b['band'] * b['width']}-"
            f"{(b['band'] + 1) * b['width'] - 1}), {_num(b['to_roll'])} below the roll", GOOD)
    else:
        add('mana', 'Mana', f"{_num(mana)}  BAD band {b['band']} (negative capacity: shield gives damage)", BAD)
    add('tk', 'Telekinesis', f"TK {tk} -> q {b['q']}, ratio {float(b['ratio']):.4g}, band width {b['width']}"
        + ('' if model['cls'] == 1 else ' (TK / ES need a Sorceress)'), INFO if model['cls'] == 1 else WARN)
    add('offscreen', 'Off-screen mana', _num(b['offscreen']), GOOD if b['offscreen'] > 0 or b['funky'] else BAD)
    add('setbonus', 'Sigon full set (+20 mana)', 'yes' if full else 'no', INFO)
    bp, pts = bo_pct(model, t), model.get('stat_points', 0)
    v.update(bo_pct=bp, stat_points=pts, mana_nobo=mana_of(model, t)[0])
    if (bp and not bo) or (pts and not energy):
        m2, _ = mana_of(model, t, True, True)
        b2 = band_info(m2, tk)
        st2 = 'funky' if b2['funky'] else f"good band {b2['band']}" if b2['good'] else f"BAD band {b2['band']}"
        add('ingame', 'After BO + Energy', f'{_num(m2)} ({st2}) with BO +{bp}% and {pts} attribute(s) in Energy '
            '(the clones: "cast BO, shift-click the attributes into Energy")', INFO)
    if bo and bp:
        m0, _ = mana_of(model, t)
        add('mana_nobo', 'Mana without BO', f'{_num(m0)} (the mana above counts BO +{bp}%)', INFO)
    st = GOOD if regen <= cap else BAD
    if st == GOOD and cap - regen > max(300, cap // 20):
        st = WARN
    add('regen', 'Mana regen', f"{regen}% of cap {cap}% (Warmth {warmth}%, Meditation lvl {med}"
        f"{', ' + str(sum(t['sources'].get(MEDITATION, {}).values())) + ' source(s)' if med else ''})"
        + ('  ROLL-OVER' if regen > cap else ''), st)
    add('life', 'Life', _num(life), BAD if life >= ROLL else WARN if life > 7900000 else GOOD)
    st = BAD if sm['max'] > ROLL else WARN if sm['max'] < ROLL * 0.95 else GOOD
    add('damage', 'Smite damage', f"PvM {sm['min']}-{sm['max']} (lvl {sm['slvl']}, str {sm['strength']}, "
        f"shield {(sm['shield'] or '-').strip()}); PvP after DR {float(pvp):.0f} / cap {float(DMG_CAP_PVP):.0f}",
        st if sm['slvl'] else INFO)
    for aid, kinds in sorted(t['sources'].items()):
        n = sum(kinds.values())
        lv = t['aura_lv'].get(aid, 0)
        name = AURA_NAMES.get(aid, str(aid))
        kt = ', '.join(f'{k} {c}' for k, c in sorted(kinds.items()))
        note = ' (stacking: one aura)' if aid in STACKING else ''
        status = INFO
        if aid == PRAYER:
            status = GOOD if set(kinds) == {'charm'} else WARN
        elif aid in (THORNS, MEDITATION):
            status = GOOD if n == 1 else WARN
        elif aid in (HOLY_FREEZE,):
            status = GOOD if 3 <= n <= 7 else INFO
        add(f'aura_{aid}', f'{name} sources', f'{n} ({kt}), level {lv}{note}', status)
    passive = {k: x for k, x in t['aura_lv'].items() if k not in t['sources']}
    if passive:
        add('aura_passive', 'Passive aura levels', ', '.join(f'{AURA_NAMES.get(k, k)} {x}' for k, x in
                                                             sorted(passive.items())), INFO)
    if hf_lv:
        add('hf', 'Holy Freeze per source', f'{hf_dmg:.0f}-{hf_top:.0f} PvM x {hf_src} source(s); PvP max '
            f'{hf_top * 0.17:.0f} of cap {ROLL * 0.17:.0f}',
            BAD if hf_top > ROLL else GOOD)      # user: aura damage caps like smite (x 0.17 PvP, no DR%)
    if prayer_src:
        add('prayer', 'Prayer per second', f'heal {heal_s:.0f}, drain {drain_s:.0f} vs regen {regen_s:.0f} mana/s',
            GOOD if drain_s < regen_s else WARN)
    if stun:
        txt = ', '.join(f"{'att' if k == 195 else 'hit'} {c}% L{lv}" for k, lv, c in stun[:6])
        txt += f', ... ({len(stun)} lines)' if len(stun) > 6 else ''
        # never 100% on a line (lag); more than 10/10 only for funky / sStun builds (a mock author)
        add('stun', 'Stun', f'{txt} (total {stun_total}%)',
            BAD if max(c for _, _, c in stun) >= 100 else GOOD if stun_total <= 20 or b['funky'] else WARN)
    else:
        add('stun', 'Stun', 'none (most stable)', GOOD)
    if deli:
        lv = {x[1] for x in deli}
        add('delirium', 'Delirium attack reset', ', '.join(f"{'att' if k == 195 else 'hit'} {c}% L{l}"
                                                            for k, l, c in deli),
            GOOD if len(deli) >= 2 and len(lv) >= 2 else WARN)
    dz = sum(1 for u in t['units'] for sid, p, x in u.lines() if sid == 98 and p == DOPPLEZON and x)
    v['dopplezon'] = dz
    add('dopplezon', 'NV state Dopplezon (state 63)', f'{dz} line(s)' if dz else 'missing (needed with the '
        'Delirium attack reset)', GOOD if dz else WARN)
    ex = model.get('excess_jewels', 0)
    v['excess_jewels'] = ex
    if ex:
        add('sockets', 'Socketed jewels', f'{ex} jewel(s) beyond the socket count (save field + item_numsockets): '
            'the game drops them, their stats are not counted', BAD)
    add('lists', 'Stat lists', str(t['lists']), GOOD if t['lists'] <= 198 else WARN)
    v['longest'] = t['longest']
    add('lines', 'Lines per list', f"at most {t['longest']} of {LINE_CAP}",
        GOOD if t['longest'] <= LINE_CAP else BAD)       # user: more than 30 lines in one list crash on hover
    add('size', 'File size', f"{model['size']} bytes", GOOD if model['size'] < FILE_LIMIT else BAD)
    return dict(values=v, checks=C)


def _num(x):
    x = Fraction(x)
    if x.denominator == 1:
        return str(x.numerator)
    return f'{float(x):.2f}'


def sides(model):
    """The weapon sides that differ ('A', 'B'), the active one first."""
    have = {u.side for u in model['units'] if u.side}
    act = 'B' if model['active_weapon'] else 'A'
    return [act] + [s for s in ('A', 'B') if s != act and s in have]


# ============================================================================================ generator
# Presets (doc 9.2 + the user's notes). mana: the target; exact: funky (the product must hit it exactly).
# the user's clone-99: speeds IAS / FCR -121, FRW -164, stun 90% at level 63, NV states Just Hit + Holy Shield
_FUNKY = dict(ias=-121, frw=-164, fcr=-121, stun_lvl=63, holy_shield=True, just_hit=True, barbs=0)   # barbs: 1 / 7 funkies
PRESETS = {
    # TK31 mocks (clones2: clone-02 A / clone-80 B / Prototype B high, clone-70 / clone-90 B mid, clone-12 /
    # Beginner B low): 7 Holy Freeze sources capped by cold mastery, Thorns + Barbs return, resist by level
    'mock_high': dict(label='Mock High', role='mock', tk=31, mana=1572500, hf_sources=7, hf_level=3100,
                      thorns=4278, res_cold=3528, res_fire=3339,
                      note='TK31 top of good band 2 (1048576-1572863): 7 capped Holy Freeze, Thorns 4278 + Barbs '
                           '3100, cold / fire resist by level, max absorb'),
    'mock_mid': dict(label='Mock Mid', role='mock', tk=31, mana=1310719, hf_sources=7, hf_level=3100, thorns=4278,
                     res_cold=3528, res_fire=3528, note='TK31 "1.31" mana (off-screen 4194288), 7 capped Holy Freeze'),
    'mock_low': dict(label='Mock Low', role='mock', tk=31, mana=1211974, hf_sources=7, hf_level=3100, thorns=4278,
                     res_cold=4158, res_fire=4158, note='TK31 low mana 1.21M, 7 capped Holy Freeze, more resist'),
    # P/T (clone-76, clone-104, clone-87): no holy aura, no stun, high return, all three res/lvl
    'prayer_thorner': dict(label='Prayer/Thorner', role='pt', tk=31, mana=1572863, hf_sources=0, hf_level=0,
                           thorns=4278, barbs=3100, stun=0, res_cold=3780, res_fire=3780, res_light=3780,
                           target_def=762, itd=True,
                           note='P/T: 1572863 (the PT mana: no enemy aura), Thorns 4278 + Barbs 3100 (capped '
                                'return), no holy aura, no stun, max absorb'),
    'aura_killer': dict(label='Aura Killer', role='ak', tk=31, mana=1211974, hf_sources=28, hf_level=3100,
                        hf_target=8320000, thorns=3981, barbs=0, res_cold=4725, res_fire=4725, res_light=4725,
                        target_def=762, pierce=45390, note='reference clone-05 layout: 28 Holy Freeze sources on '
                                                        'gear jewels at ~8.32M per source, all 40 charms Prayer'),
    # funkies: the user's clone-99 (speeds -121 / -164, FHR -36, stun 90 L63, Delirium, curse res, NV
    # states Just Hit + Holy Shield) on the tested aura plan
    'funky': dict(label='Funky (TK30)', role='funky', tk=30, mana=1048576, exact=True, hf_sources=7, hf_level=3100,
                  thorns=3981, stun=100, **_FUNKY, note='perfect funky: exactly 1048576.000 at TK30 (q even: stable)'),
    'funky28': dict(label='Funky TK28', role='funky', tk=28, mana=2097152, exact=True, hf_sources=7, hf_level=3100,
                    thorns=3981, stun=100, **_FUNKY, note='funky zero 2097152 at TK28 (q 4, stable)'),
    'funky26': dict(label='Funky TK26', role='funky', tk=26, mana=3145728, exact=True, hf_sources=7, hf_level=3100,
                    thorns=3981, stun=100, **_FUNKY, note='funky zero 3145728 at TK26 (q 6, stable)'),
    'funky24': dict(label='Funky TK24', role='funky', tk=24, mana=4194304, exact=True, hf_sources=7, hf_level=3100,
                    thorns=3981, stun=100, **_FUNKY, weapon=True, note='funky zero 4194304 at TK24 (q 8); needs a socketed '
                                                             'weapon (198 lists) for the exact product'),
    'balance_switch': dict(label='Balance switch', role='mock', tk=31, mana=1572500, mana_b=1211974, hf_sources=7,
                           hf_level=3100, thorns=4278, switch='balance', res_cold=3528,
                           note='side A High 1.5725M (stun shield), weapon switch to side B Low 1.21M (no stun)'),
    # clones2 (README): clone-104 / clone-87 "mid mana" P/T 1377236 (TK31): 40 Prayer charms, Thorns
    # 4278 + Barbs 4154 (ours 3100: the room left at 31 per line), no holy aura, no stun
    'pt_mid': dict(label='P/T Mid', role='pt', tk=31, mana=1377236, hf_sources=0, hf_level=0, thorns=4278,
                   barbs=3100, stun=0, res_cold=2898, res_fire=2898, res_light=2898, target_def=762, itd=True,
                   note='clone-104 mid-mana Prayer/Thorner: 1377236, Thorns 4278 + Barbs 3100, no holy aura, '
                        'no stun'),
    # clone-45 / clone-09 / clone-32 hosts: high mana, Host position (DTM 500, no stun), Thorns + Barbs
    'host': dict(label='Host', role='host', tk=31, mana=1572500, position='Host', hf_sources=7, hf_level=3100,
                 thorns=4278, barbs=3100, res_cold=5166, res_fire=5166, cbf=True,
                 note='Host (clone-45 / clone-09 / clone-32): high mana, no stun, 7 capped Holy Freeze, '
                      'Thorns 4278 + Barbs 3100, resist by level (no absorb by time)'),
}
PRESET_ORDER = ('mock_high', 'mock_mid', 'mock_low', 'prayer_thorner', 'aura_killer', 'funky', 'funky28',
                'funky26', 'funky24', 'balance_switch', 'pt_mid', 'host')
# user (2026-11-20): TK31 mocks sit between 1.21M and 1.57M; the mana is picked by the enemy's aura: high aura ->
# low mana, low aura -> high mana (to push the enemy's mana to the zero), no aura (a PT, not PTA) -> 1572863
ENEMY_AURA_MANA = {'none': 1572863, 'low': 1572500, 'mid': 1310719, 'high': 1211974}
TK31_RANGE = (1210000, 1572863)
# reference clone-05 / clone-41: Holy Freeze ~8.31-8.32M PvM per source (never at the roll point itself)
HF_SOURCE_TARGET = 8320000
# clones2 7-source mocks: 8384065 (clone-90) .. 8389231 per source (cold mastery 43k-82k); the generator aims just
# under the roll (over 8388607 PvM = BAD, the analyzer's rule)
HF_MOCK_TARGET = 8384000
POSITIONS = {'Host': dict(dtm=500, stun=0), 'HPJ': dict(dtm=420, stun=11), 'LPJ': dict(dtm=330, stun=11)}
# level 127: every well-described clones2 mock (per-level stats give 127/8 per point)
# the generator fills the file with target-neutral bulk lines up to FILE_LIMIT - 1 - SIZE_MARGIN bytes
SIZE_MARGIN = 200
DEFAULTS = dict(cls=1, level=127, position='LPJ', life=7300000, damage=Fraction(SMITE_TARGET) * PVP / 2,
                size_budget=FILE_LIMIT - 1 - SIZE_MARGIN,
                # every category the proven clones carry (docs/review/mock-pi-data/clone-profile.txt, CLONE_PROFILE):
                # the clone median unless a preset says otherwise
                barbs=3100, hf_cap=True, hf_target=HF_MOCK_TARGET, thorns_lvl=0,
                ias=107, frw=107, fhr=-36, fcr=0, nv_ias=97, nv_frw=97,      # IAS 93, FRW 96, FHR 99, FCR 105, 68, 67
                curse_res=511, target_def=381, dodge=127, ow=127, cb=127, ds=0, itd=False, cbf=False,
                dr=63, dr_pct=255, mdr=0, abs_pct=127, abs_flat=0, abs_lvl=True, abs_time=True, replenish=True,
                res_cold=0, res_fire=0, res_light=0, res_flat=0, pierce=0,
                stun_lvl=1, holy_shield=False, just_hit=False)

# item skeleton: (role, body, code, Sigon's set item id, socketed with 7 jewels)
GEAR = (('helm', 1, 'ghm ', 36, True), ('armor', 3, 'gth ', 37, True), ('shield', 5, 'tow ', 40, True),
        ('amulet', 2, 'amu ', 35, True), ('ring1', 6, 'rin ', 38, True), ('ring2', 7, 'rin ', 39, True),
        ('gloves', 10, 'hgl ', 35, False), ('boots', 9, 'hbt ', 38, False), ('belt', 8, 'hbl ', 39, False))
WEAPON = ('weapon', 4, 'crs ', 36, True)
SOCKET_FIELD = {'ghm ': 2, 'gth ': 3, 'tow ': 3, 'crs ': 6}
# the game only keeps as many socketed children as the item has sockets: the save field PLUS item_numsockets (194)
# lines. Every reference mock writes 194 = 8 on the first list of each socketed item (amulet / rings: field 0-1);
# without it the 7 jewels of the amulet / rings (and 4-5 of helm / armor / shield) were lost in game.
SOCKET_STAT = 8
# user (2026-11-20): D2 supports up to 7 sockets without crashing on weapons, shields, body armor, helms, rings and
# amulets (not boots / belts / gloves). The game clamps the save's socket field to the base item's sockets (rings /
# amulets: 0; in game a field of 7 lost the jewels: max mana 438311 instead of 1048576), so the field keeps the base
# count and stat 194 adds the rest up to 7 in total (the clones' "194 = 7 - field")
MAX_SOCKETS = 7
JEWELS = 7
CHARM_COUNT = 40
# size tricks of the reference clones (docs/review/mock-pi-data/editor-tricks.txt): socketed jewels are NORMAL
# quality (q2: no 3-bit sub-quality; clone-09, clone-32, Cold, clone-23, clone-52, Prototype) and every
# jewel / charm has no picture field ("no img": 1 flag bit instead of 4; clone-32's 40 charms, clone-83's
# jewel; our rings / amulets already load in game without it). Charms stay superior (no sample has a q2 charm).
JEWEL_QUALITY = 2
CHARM_QUALITY = 3
# target-neutral bulk lines of the clones, written into the room left under the size budget (charms first, then
# jewels, then gear; one line per stat per list): replenish life 33 (the field max: clone-99 / README "replenish
# and DR on almost everything"), then absorb by time 4194303 (cold, fire, lightning: clone-28, Cold, Assault,
# clone-52, TryToKill*), never on a Host (doc S4: abs-by-time does not work as host): a Host gets resist by
# level instead (fire, lightning, cold 63: clone-45 82/82/54 lines, clone-32, clone-64; doc S4 "hosts 66k resist").
# Life, mana, regen, smite, aura and mastery stats stay off: they would move a target.
BULK_REPLENISH = (74, 33)
BULK_ABS_TIME = ((288, 4194303), (289, 4194303), (290, 4194303))
BULK_HOST_RES = ((230, 63), (231, 63), (232, 63))
DELIRIUM_CHANCE = 127               # chance % of both Delirium lines (attack reset)
AURA_LINE_MAX = 31


class PlanError(Exception):
    """A target the plan cannot reach; key: the form field it belongs to (None: the whole form)."""

    def __init__(self, msg='', key=None):
        super().__init__(msg)
        self.key = key


class Slot:
    """One stat list of a unit."""
    __slots__ = ('unit', 'idx', 'lines')

    def __init__(self, unit, idx):
        self.unit, self.idx, self.lines = unit, idx, []

    def has(self, sid, param=None):
        return any(s == sid and p == param for s, p, _ in self.lines)

    def count(self):
        """Lines in the saved list: a socketed gear item's first list also carries the item_numsockets line."""
        return len(self.lines) + (1 if self.idx == 0 and self.unit.socketed else 0)

    def room(self):
        return LINE_CAP - self.count()

    def ok(self, sid, param=None):
        return self.room() > 0 and not self.has(sid, param)

    def add(self, sid, value, param=None):
        self.lines.append((sid, param, value))


class PUnit:
    """A unit of the plan: a gear item, a jewel or a charm, with its role for the aura plan."""

    def __init__(self, kind, name, nlists, role='cover', body=None, code=None, set_id=None, parent=None, side=None):
        self.kind, self.name, self.role = kind, name, role
        self.body, self.code, self.set_id, self.parent, self.side = body, code, set_id, parent, side
        self.slots = [Slot(self, i) for i in range(nlists)]
        self.socketed = False


# ---------------------------------------------------------------------------------- integer solvers
def solve_mana(target, exact, max_lines, base_lo=4096, base_hi_raw=(1 << 21) - 1, extra_pct=0):
    """Mana = pct_fp(B + 256 (F + 20), P) / 256 with base B in 1/256 steps (<= 8191.996), F = sum of +mana lines
    (<= 223 each), P = sum of mana% lines (<= 53 each), at most max_lines lines of each. exact: the product hits
    the target exactly with an integer base (funky); else floor(mana) == target. Fewest bits, then the base
    nearest 8190. Returns dict(base_raw, flat, pct, mana) or None."""
    best = None
    tgt = Fraction(target)
    for P in range(0, 53 * max_lines + 1):
        X = solve_fp(tgt, P + extra_pct, exact)            # extra: the Battle Orders %
        if X is None or exact and X % 256:
            continue
        rest = X - 256 * SET_BONUS                          # B_raw + 256 F
        F = max(0, -(-(rest - base_hi_raw) // 256))
        B = rest - 256 * F
        if B < 256 * base_lo:
            continue
        if exact and B % 256:
            continue
        if F > 223 * max_lines:
            continue
        cost = 17 * -(-F // 223) + 15 * -(-P // 53)
        key = (cost, abs(B - 8190 * 256))
        if best is None or key < best[0]:
            best = (key, dict(base_raw=B, flat=F, pct=P, mana=Fraction(pct_fp(X, P + extra_pct), 256)))
    return best[1] if best else None


def solve_regen(mana, warmth_lvl):
    """Single Meditation source as high as possible + one regen% remainder line: total = the roll-over cap."""
    cap = regen_cap(mana)
    w = warmth_pct(warmth_lvl)
    room = cap - w
    if room < 300:
        r = max(0, min(255, room))
        return dict(cap=cap, med=0, pct=r, total=w + r)
    med = (room - 275) // 25
    r = room - meditation_pct(med)
    while r > 255:
        med += 1
        r = room - meditation_pct(med)
    return dict(cap=cap, med=med, pct=r, total=w + meditation_pct(med) + r)


def solve_life(target, base_raw, oak_min, oak_max, max_lines, extra_pct=0):
    """Life = (base + sum(+life lines <= 479)) x (100 + Oak Sage %) / 100 <= target, fewest bits, nearest."""
    best = None
    base = Fraction(base_raw, 256)
    for L in range(oak_min, oak_max + 1):
        pct = 100 + oak_pct(L) + extra_pct
        x = math.floor(Fraction(target) * 100 / pct - base)
        if x < 0:
            continue
        a = -(-x // 479)
        if a > max_lines:
            continue
        life = Fraction(pct_fp(base_raw + 256 * x, pct - 100), 256)       # the game's percent step
        cost = 18 * a + 23 * max(0, -(-L // AURA_LINE_MAX) - oak_min)
        key = (cost + float(target - life) / 2000, cost)
        if best is None or key < best[0]:
            best = (key, dict(oak=L, flat=x, life=life))
    return best[1] if best else None


def solve_smite(target_pvm, level, shield, max_lines, base_str=1023, slvl=63, mode='efficient'):
    """Max Smite damage = (shield max + sum(+damage lines <= 491)) x (100 + 15 slvl + str%) / 100 <= target,
    str = base + floor(sum(str/lvl lines <= 63) x clvl / 8). Smallest gap, then fewest bits."""
    smin, smax = SHIELD_DMG[shield]
    cands = []
    for S in range(0, 63 * max_lines + 1):
        mult = 100 + 15 * slvl + base_str + S * level // 8
        D = ((target_pvm + 1) * 100 - 1) // mult - smax
        if D < 0:
            break
        m = -(-D // 491)
        if m > max_lines:
            continue
        hi = (smax + D) * mult // 100
        cost = 15 * -(-S // 63) + 18 * m
        cands.append((target_pvm - hi, cost, S, D, hi, mult))
    if not cands:
        return None
    if mode == 'max':
        # the largest max under the target, then fewest bits; +min damage closes the shield's min-max spread
        gap, cost, S, D, hi, mult = min(cands, key=lambda c: (c[0], c[1]))
        lo_add = smax - smin
        return dict(str_points=S, dmg=D, max=hi, min=(smax + D) * mult // 100, mult=mult, min_add=lo_add)
    # efficient: fewest bits among the plans within 0.1% of the target, then the closest
    near = [c for c in cands if c[4] * 1000 >= target_pvm * 999] or cands
    gap, cost, S, D, hi, mult = min(near, key=lambda c: (c[1], c[0]))
    return dict(str_points=S, dmg=D, max=hi, min=(smin + D) * mult // 100, mult=mult, min_add=0)


def split(total, per_line):
    """[per_line, per_line, ..., remainder] summing to total (no zero lines)."""
    out = [per_line] * (total // per_line)
    if total % per_line:
        out.append(total % per_line)
    return out


def spread(total, n):
    """total over n lines as evenly as possible (each >= 1 when total >= n)."""
    if n <= 0:
        return []
    b, e = divmod(total, n)
    return [b + 1] * e + [b] * (n - e)


# ---------------------------------------------------------------------------------- the plan
def options(preset='mock_high', **over):
    """Preset values with the user's overrides (None = keep the preset / default)."""
    if preset not in PRESETS:
        raise PlanError(f'unknown preset {preset!r}')
    o = dict(DEFAULTS)
    o.update(PRESETS[preset])
    o['preset'] = preset
    pos = over.get('position') or o['position']
    o['position'] = pos
    o.setdefault('dtm', POSITIONS[pos]['dtm'])
    o.setdefault('stun', POSITIONS[pos]['stun'])
    for k, v in over.items():
        if v is not None:
            o[k] = v
    o.setdefault('exact', False)
    o.setdefault('weapon', False)
    o.setdefault('switch', None)
    o['smite_max'] = bool(o.get('smite_max', False))
    for k in ('prayer', 'prayer_sources', 'oak', 'med', 'regen'):
        o.setdefault(k, None)                               # None: solved by plan()
    o.setdefault('deli_attack', 63)
    o.setdefault('deli_strike', 62)
    o.setdefault('dopplezon', True)
    o['stun'] = max(0, min(100, int(o['stun'])))
    o['stun_lvl'] = max(0, min(63, int(o['stun_lvl'])))
    for k in ('itd', 'cbf', 'abs_lvl', 'abs_time', 'replenish', 'holy_shield', 'just_hit', 'hf_cap'):
        o[k] = bool(o[k])
    o['level'] = max(99, min(127, int(o['level'])))
    o['tk'] = max(0, min(99, int(o['tk'])))
    o['cls'] = int(o['cls'])
    ea = o.get('enemy_aura')
    if ea:
        if ea not in ENEMY_AURA_MANA:
            raise PlanError(f'enemy aura {ea!r}: one of {", ".join(ENEMY_AURA_MANA)}')
        if o['tk'] >= 31 and not o['exact']:
            o['mana'] = ENEMY_AURA_MANA[ea]
    w = (1 << 19) * max(32 - o['tk'], 1)
    if Fraction(o['mana']).denominator == 1 and o['mana'] % w == 0 and (o['mana'] // w) % 2 == 1:
        o['exact'] = True                                   # a funky zero needs the exact product
    # Battle Orders cast before the duel (clones2 convention: BO 63 + 36 = 99, mana tuned WITH BO): mana and life
    # targets are the BO'd values; 0 = no BO line. Funkies (exact product) default to no BO, like the four TK30
    # reference funkies: their exactness must not hang on the fitted BO % (35 + 3 per level)
    o['bo'] = max(0, min(99, int(o['bo'] if o.get('bo') is not None else 0 if o['exact'] else 99)))
    o['bo_pct'] = 35 + 3 * (o['bo'] - 1) if o['bo'] else 0
    return o


def _stun_from_slider(s):
    """Stun <-> Stability slider (0 = most stable .. 100 = most stun): % per ctc line (attack and hit)."""
    return 0 if s <= 0 else max(5, min(90, round(s * 0.9)))


def _damage_from_slider(s, target):
    """High stun trades smite damage (a mock author: capped smite -> stun <= 10%; <= 600k smite -> 15/15+)."""
    if s <= 30:
        return target
    lo = min(Fraction(target), Fraction(600000) / 2)          # 600k PvP smite, after 50% DR
    return target - (target - lo) * (s - 30) / 70


# stats the proven clones keep on a gear item's own (magic) list or on a charm, never on a set list or a jewel
# (where.py survey of 29 clones: OW / CB / DS, DR%, absorb %, curse res, dodge, CBF, ITD, NV IAS 100% there; IAS,
# FRW, FHR, target defense mostly there); the user: "some stats do not function on set or runeword lists"
MAGIC_ONLY = {93, 96, 99, 105, 67, 68, 109, 116, 135, 136, 141, 35, 36, 142, 143, 144, 145, 146, 147, 148, 149, 338,
              339, 340, 153, 115, 238, 39, 41, 43, 45}
_AURA_KEY = {OAK: 'oak', BARBS: 'barbs', MEDITATION: 'med', HOLY_FREEZE: 'hf_level', THORNS: 'thorns'}


def plan(preset='mock_high', name='Mock', **over):
    """The whole character as data: units with their stat lists, header values, targets and the expected
    analyzer results. Raises PlanError when a target cannot be hit on the list budget."""
    o = options(preset, **over)
    if not o['exact']:
        for key in ('mana',) + (('mana_b',) if o['switch'] else ()):
            m = o.get(key)
            if m is None:
                continue
            if o['tk'] >= 31 and not TK31_RANGE[0] <= m <= TK31_RANGE[1]:
                raise PlanError(f'{key} {m}: TK31 mocks sit in {TK31_RANGE[0]}-{TK31_RANGE[1]}', key=key)
            if o['tk'] == 30 and m < 2097153:
                raise PlanError(f'{key} {m}: at TK30 skip the first negative band (the rolling zero 1048576 is '
                                'a protective barrier): use 2097153-3145727', key=key)
    rng = random.Random(f'{name}/{preset}/{sorted((k, str(v)) for k, v in o.items())}')
    units = []
    gear = list(GEAR) + ([WEAPON] if o['weapon'] else [])
    for role, body, code, sid, sock in gear:
        g = PUnit('gear', role, 6, 'cover', body, code, sid, side='A' if body in (4, 5) else None)
        units.append(g)
        if sock:
            g.socketed = True
            for j in range(JEWELS):
                units.append(PUnit('jewel', f'{role}/{j}', 2, 'cover', parent=g, side=g.side))
    nps = CHARM_COUNT if o['prayer_sources'] is None else max(0, min(CHARM_COUNT, int(o['prayer_sources'])))
    charms = [PUnit('charm', f'charm{i}', 1, 'prayer' if i < nps else 'cover') for i in range(CHARM_COUNT)]
    units += charms
    U = {u.name: u for u in units}
    # ---- aura roles: Holy Freeze sources on the shield's jewels (then charms), one Meditation, one Thorns,
    # one Barbs source; every other gear item / jewel is an Oak Sage "cover" (stacking: one aura)
    H = max(0, int(o['hf_sources'])) if o['hf_level'] else 0
    # Holy Freeze sources on gear jewels (shield first), like the reference clone-05; charms stay Prayer
    hf_jewels = [u for r in ('shield', 'helm', 'armor', 'amulet', 'ring1', 'ring2', 'weapon')
                 for u in units if u.kind == 'jewel' and u.parent.name == r]
    if H > len(hf_jewels):
        raise PlanError(f'{H} Holy Freeze sources: at most {len(hf_jewels)} (gear jewels; charms stay Prayer)',
                        key='hf_sources')
    for u in hf_jewels[:H]:
        u.role = 'hf'
    U['gloves'].role = 'med'
    U['boots'].role = 'thorns'
    if o['barbs']:
        U['belt'].role = 'barbs'
    lists = [s for u in units for s in u.slots]
    nl = len(lists)
    by_role = lambda *roles: [s for s in lists if s.unit.role in roles]
    # ---- Prayer 31 on EVERY list (178 x 31 = 5518); sources only where nothing higher sits (the charms)
    if o['prayer'] is None:
        for s in lists:
            s.add(151, AURA_LINE_MAX, PRAYER)
    else:                                   # a total Prayer level: the source charms first, then the other lists
        total = int(o['prayer'])
        srcs = [u.slots[0] for u in charms if u.role == 'prayer']
        n = max(len(srcs), -(-total // AURA_LINE_MAX))
        if total < len(srcs) or n > nl:
            raise PlanError(f'Prayer {total}: {len(srcs)} sources need {len(srcs)}-{AURA_LINE_MAX * nl} levels',
                            key='prayer')
        for s, v in zip(srcs + [s for s in lists if s not in srcs], spread(total, n) if n else []):
            s.add(151, v, PRAYER)
    cover_units = [u for u in units if u.role == 'cover']
    # ---- mana
    mana = solve_mana(o['mana'], o['exact'], nl, extra_pct=o['bo_pct'])
    if mana is None:
        raise PlanError(f"mana {o['mana']} cannot be hit {'exactly ' if o['exact'] else ''}on {nl} lists",
                        key='mana')
    # the bulk lines (mana, life, str/lvl, damage: totals fixed by the targets) go on the charms first, then the
    # jewels, then the gear, like the clones (user: "build the bulk from mana% balanced with +223 mana lines" and
    # "you're not adding bulk stats to jewels/charms"); a weapon switch keeps the mana on the shield and its jewels
    # first (side B re-tunes the shield copy)
    pref = sorted(lists, key=lambda s: {'charm': 0, 'jewel': 1}.get(s.unit.kind, 2))
    order = pref if not o['switch'] else sorted(
        lists, key=lambda s: (s.unit.code != 'tow ' and (s.unit.parent is None or s.unit.parent.code != 'tow '),
                              s.unit.kind == 'charm'))      # the shield and its jewels first
    for s, v in zip(order, split(mana['flat'], 223)):
        s.add(9, v)
    for s, v in zip(order, split(mana['pct'], 53)):
        s.add(77, v)
    # ---- regen: Warmth 99 + ONE Meditation source + one regen% remainder line
    warmth = 99 if o['cls'] == 1 else 0
    # against the mana the mock fights with (BO'd): the highest mana has the lowest roll-over cap, so the regen
    # stays under the cap before BO is cast too
    rg = solve_regen(mana['mana'], warmth)
    if o['med'] is not None or o['regen'] is not None:     # the user's Meditation level / regen% line
        med = rg['med'] if o['med'] is None else max(0, int(o['med']))
        pct = rg['pct'] if o['regen'] is None else max(0, min(255, int(o['regen'])))
        rg = dict(rg, med=med, pct=pct, total=warmth_pct(warmth) + (meditation_pct(med) if med else 0) + pct)
    # ---- life: +479 lines + Oak Sage on the cover units
    oak_lists = by_role('cover')
    oak_lo, oak_hi = len(cover_units), len(oak_lists) * AURA_LINE_MAX
    if o['oak'] is not None:
        if not oak_lo <= int(o['oak']) <= oak_hi:
            raise PlanError(f"Oak Sage {o['oak']}: {oak_lo}-{oak_hi} on {len(cover_units)} sources", key='oak')
        oak_lo = oak_hi = int(o['oak'])
    life = solve_life(o['life'], (1 << 21) - 1, oak_lo, oak_hi, nl, extra_pct=o['bo_pct'])
    if life is None:
        raise PlanError(f"life {o['life']} cannot be reached", key='life')
    for s, v in zip(pref, split(life['flat'], 479)):
        s.add(7, v)
    # ---- aura levels
    plan_auras = [(OAK, life['oak'], 'cover', ('cover',))]
    if o['barbs']:
        plan_auras.append((BARBS, int(o['barbs']), 'barbs', ('barbs', 'cover')))
    if rg['med']:
        plan_auras.append((MEDITATION, rg['med'], 'med', ('med', 'barbs', 'cover')))
    hf_mast = 0
    if H:
        plan_auras.append((HOLY_FREEZE, int(o['hf_level']), 'hf', ('hf', 'med', 'barbs', 'cover')))
        if o['hf_cap']:
            base = Fraction(holy_freeze_dmg(int(o['hf_level']), True))
            tgt = min(ROLL, int(o['hf_target']))
            hf_mast = max(0, math.floor((Fraction(tgt) / base - 1) * 100))
            while base * (100 + hf_mast) / 100 > tgt:
                hf_mast -= 1
    if o['thorns']:
        plan_auras.append((THORNS, int(o['thorns']), 'thorns', ('thorns', 'hf', 'med', 'barbs', 'cover')))
    expect_src = {PRAYER: sum(1 for u in units if u.role == 'prayer')}
    for aid, total, src_role, allowed in plan_auras:
        seeds = [u for u in units if u.role == src_role]
        if not seeds:
            continue
        expect_src[aid] = len(seeds)
        if total < len(seeds):
            raise PlanError(f'{AURA_NAMES[aid]}: {total} levels for {len(seeds)} sources', key=_AURA_KEY.get(aid))
        n = max(len(seeds), -(-total // AURA_LINE_MAX))
        vals = spread(total, n)
        first = [u.slots[0] for u in seeds]
        pool = [s for s in lists if s.unit.role in allowed and s not in first and s.room() > 0
                and (s.unit.kind != 'charm' or s.unit.role == src_role)]
        pool.sort(key=lambda s: (s.unit.role != src_role, len(s.lines)))
        targets = first + pool
        if len(targets) < n:
            raise PlanError(f'{AURA_NAMES[aid]}: {total} levels need {n} lists, {len(targets)} free',
                            key=_AURA_KEY.get(aid))
        for s, v in zip(targets, vals):
            s.add(151, v, aid)
    # ---- regen % remainder (gloves: the Meditation unit)
    if rg['pct']:
        U['gloves'].slots[1].add(27, rg['pct'])
    # ---- smite: non-class Smite 63 on the shield + str/lvl + damage lines
    slider = int(o['stun'])
    # the slider trades smite damage only when the user moved it (presets keep the capped smite)
    dmg_target = Fraction(o['damage'])
    if over.get('stun') is not None and over.get('damage') is None:
        dmg_target = _damage_from_slider(slider, dmg_target)
    pvm = min(ROLL, math.floor(dmg_target * 2 / PVP))
    if o.get('smite_max') and over.get('damage') is None:
        pvm = ROLL                                          # max damage: the exact cap, no safety margin
    sm = solve_smite(pvm, o['level'], 'tow ', nl, mode='max' if o.get('smite_max') else 'efficient')
    if sm is None:
        raise PlanError('smite target cannot be reached', key='damage')
    sh = U['shield']
    sh.slots[0].add(97, 63, SMITE)
    sh.slots[1].add(97, 63, PRAYER)
    for i, v in enumerate(split(o['bo'], 63)):              # non-class BO (cast before the duel)
        sh.slots[2 + 3 * i].add(97, v, BATTLE_ORDERS)

    def free(sid, param=None):
        return [s for s in pref if s.ok(sid, param)]

    def put(sid, values, param=None, gear_first=True):
        """values over the lists without that line, the least full first (gear and jewels before charms); the
        clones' one-line stats (MAGIC_ONLY) only on a gear item's own (magic) list or a charm."""
        for v in values:
            c = free(sid, param)
            if sid in MAGIC_ONLY:
                c = [x for x in c if x.unit.kind == 'charm' or x.unit.kind == 'gear' and x.idx == 0]
            if not c:
                raise PlanError(f'stat {sid}: no list with room ({LINE_CAP} lines each)')
            c.sort(key=lambda x: ((x.unit.kind == 'charm') if gear_first else 0, x.count()))
            c[0].add(sid, v, param)

    def signed(total, sid):
        """total over lines within the stat's save range (negative values down to -save add)."""
        if total >= 0:
            return split(total, line_max(sid))
        return [-x for x in split(-total, -line_min(sid))] if line_min(sid) < 0 else []

    for s, v in zip(free(220), split(sm['str_points'], 63)):
        s.add(220, v)
    for s, v in zip(free(111), split(sm['dmg'], 491)):
        s.add(111, v)
    if sm.get('min_add'):
        free(21)[0].add(21, sm['min_add'])                   # +min damage: every smite rolls the max
    # ---- attack reset: Delirium on attack and on strike at two different levels; stun per the slider
    sh.slots[3].add(195, DELIRIUM_CHANCE, (DELIRIUM << 6) | max(1, min(63, int(o['deli_attack']))))
    sh.slots[3].add(198, DELIRIUM_CHANCE, (DELIRIUM << 6) | max(1, min(63, int(o['deli_strike']))))
    stun = _stun_from_slider(slider)
    if stun:                    # clones: one low line on attack and on strike (5-30% at level 0-2; xElite 90% L63)
        sh.slots[4].add(195, stun, (STUN << 6) | o['stun_lvl'])
        sh.slots[4].add(198, stun, (STUN << 6) | o['stun_lvl'])
    # ---- the categories every proven clone carries (CLONE_PROFILE): speeds, NV speeds, curse resist, target
    # defense, dodge / avoid / evade, OW / CB / DS, DR, absorb %, flat absorb, DTM, holy aura mastery
    fixed = [(93, o['ias']), (96, o['frw']), (99, o['fhr']), (105, o['fcr']), (68, o['nv_ias']), (67, o['nv_frw']),
             (109, o['curse_res']), (116, o['target_def']), (338, o['dodge']), (339, o['dodge']), (340, o['dodge']),
             (135, o['ow']), (136, o['cb']), (141, o['ds']), (36, o['dr_pct']), (35, o['mdr']),
             (142, o['abs_pct']), (144, o['abs_pct']), (148, o['abs_pct']),
             (143, o['abs_flat']), (145, o['abs_flat']), (149, o['abs_flat']), (238, o['thorns_lvl']),
             (114, int(o['dtm'])), (331, hf_mast), (335, o['pierce'])]
    fixed += [(sid, o['res_flat']) for sid in (39, 41, 43, 45)]
    fixed += [(sid, 1) for sid, on in ((115, o['itd']), (153, o['cbf'])) if on]
    for sid, total in fixed:
        if int(total):
            put(sid, signed(int(total), sid))
    if o['dr']:
        for s in lists:                                 # DR on every list (the clones: 155-178 lists)
            if s.ok(34):
                s.add(34, max(1, min(63, int(o['dr']))))
    # ---- NV states on one charm: Dopplezon (with the Delirium reset it steadies and speeds the attack), Just Hit
    # and Holy Shield (clone-99)
    nv = [st for st, on in ((DOPPLEZON, o['dopplezon']), (NV_JUST_HIT, o['just_hit']),
                            (NV_HOLY_SHIELD, o['holy_shield'])) if on]
    for st in nv:
        charms[0].slots[0].add(98, 1, st)
    # ---- resist by level per element (sum of the 230 / 231 / 232 values; x clvl / 8 in game)
    for sid, key in ((230, 'res_cold'), (231, 'res_fire'), (232, 'res_light')):
        if int(o[key]) > 0:
            put(sid, split(int(o[key]), 63), gear_first=False)
    P = dict(o=o, units=units, lists=lists, U=U, mana=mana, regen=rg, life=life, smite=sm, stun=stun,
             hf_mastery=hf_mast, expect_sources=expect_src, name=name, rng_seed=rng.getrandbits(64),
             dmg_target=dmg_target, pvm=pvm)
    _switch(P)
    _fill_absorb(P)
    over_cap = [f'{s.unit.name}#{s.idx}' for u in P['units'] for s in u.slots if s.count() > LINE_CAP]
    if over_cap:
        raise PlanError(f"more than {LINE_CAP} lines in {', '.join(over_cap[:4])}")
    return P


def _switch(P):
    """Weapon switch side B: a copy of the shield and its jewels in the second weapon pair (body 12)."""
    o = P['o']
    P['side_b'] = None
    if not o['switch']:
        return
    sh = P['U']['shield']
    group = [sh] + [u for u in P['units'] if u.parent is sh]
    copy = PUnit('gear', "shield'", 6, sh.role, 12, sh.code, sh.set_id, side='B')
    copy.socketed = sh.socketed
    copies = [copy]
    for u in group[1:]:
        copies.append(PUnit('jewel', u.name + "'", 2, u.role, parent=copy, side='B'))
    for u, c in zip(group, copies):
        for s, cs in zip(u.slots, c.slots):
            cs.lines = list(s.lines)
    cl = [s for u in copies for s in u.slots]
    # side B: other +mana / mana% on the copy (its 20 lists) so floor(mana B) == mana_b; no stun lines
    for s in cl:
        s.lines = [x for x in s.lines if not (x[0] in (195, 198) and x[1] >> 6 == STUN)]
    Fs = sum(v for s in cl for a, p, v in s.lines if a == 9)
    Ps = sum(v for s in cl for a, p, v in s.lines if a == 77)
    m = P['mana']
    X0 = m['base_raw'] + 256 * (m['flat'] - Fs + SET_BONUS)
    P0 = m['pct'] - Ps
    tgt = Fraction(o['mana_b'])
    best = None
    for Pb in range(-10 * len(cl), 53 * len(cl) + 1):
        mult = 100 + P0 + Pb + o['bo_pct']
        if mult <= 0:
            continue
        X = solve_fp(tgt, mult - 100, False)
        if X is None:
            continue
        Fb = max(0, -(-(X - X0) // 256))
        if Fb > 223 * len(cl):
            continue
        mb = Fraction(pct_fp(X0 + 256 * Fb, mult - 100), 256)
        if math.floor(mb) != tgt:
            continue
        key = -(-Fb // 223) * 17 + -(-abs(Pb) // (53 if Pb >= 0 else 10)) * 15
        if best is None or key < best[0]:
            best = (key, Fb, Pb, mb)
    if best is None:
        raise PlanError(f"side B mana {o['mana_b']} cannot be hit on the switch shield", key='mana_b')
    _, Fb, Pb, mb = best
    for s in cl:
        s.lines = [x for x in s.lines if x[0] not in (9, 77)]
    for s, v in zip(cl, split(Fb, 223)):
        s.lines.append((9, None, v))
    vals = split(Pb, 53) if Pb >= 0 else [-x for x in split(-Pb, 10)]
    for s, v in zip(cl, vals):
        s.lines.append((77, None, v))
    P['side_b'] = dict(mana=mb)
    P['side_a_mana'] = P['mana']['mana']
    P['units'] += copies


def _fill_absorb(P):
    """Absorb by level (cold, fire, lightning) on every list, then the clones' bulk lines (BULK_REPLENISH, then
    BULK_ABS_TIME, or BULK_HOST_RES on a Host) on charms, jewels and gear, while the file stays within the size
    budget."""
    budget = P['o']['size_budget']
    lists = [s for u in P['units'] for s in u.slots]       # with the switch side B copies
    order = sorted(lists, key=lambda s: {'charm': 0, 'jewel': 1}.get(s.unit.kind, 2))
    o = P['o']
    steps = [(s, sid, 63) for s in lists for sid in (234, 235, 236)] if o['abs_lvl'] else []
    # the role's bulk first (clone profile): funkies replenish life (clone-99: on every list), mocks absorb by
    # time (13 / 22 high mocks; no replenish), a Host resist by level (abs-by-time does not work as Host)
    rep = [BULK_REPLENISH] if o['replenish'] else []
    if o['position'] == 'Host':
        bulk = list(BULK_HOST_RES) + rep
    elif o.get('role') == 'funky':
        bulk = rep + (list(BULK_ABS_TIME) if o['abs_time'] else [])
    else:
        bulk = (list(BULK_ABS_TIME) if o['abs_time'] else []) + rep
    steps += [(s, sid, v) for sid, v in bulk for s in order]
    room = (budget - len(build(P))) * 8
    added = []
    for s, sid, v in steps:
        per = line_bits(sid)
        if room < per + 64:
            break
        if s.ok(sid):
            s.add(sid, v)
            added.append(s)
            room -= per
    while added and len(build(P)) > budget:         # byte padding per item: trim the estimate's overshoot
        added.pop().lines.pop()
    P['bulk_lines'] = len(added)


# ---------------------------------------------------------------------------------- the file
_QUESTS = bytes.fromhex('0100fd9ffd9ffd9ffd9ffd9ffd9f010001001d90791cfd9ffd9ffd9fe51f01000100fd9ffd9ffd9ffd9ffd9f'
                        'fd9f01000100fd9ffd9ffd9f0100000000000000010000000000fd9fed9ffd9ffd9ffd9ffd9f000000000000'
                        '0000000000000000')   # quest words of one difficulty: every quest done (reference mock)
_WAYPOINTS = bytes.fromhex('0201ffffffff7f') + bytes(17)


def _header(P):
    o = P['o']
    name = P['name'].encode('latin1')[:15]
    h = bytearray(0x14F)
    struct.pack_into('<IIIII', h, 0, 0xAA55AA55, 96, 0, 0, 0)
    h[0x14:0x14 + len(name)] = name
    h[0x24] = 0x20                                      # expansion
    h[0x25] = 15                                        # every act of every difficulty done
    h[0x28] = o['cls']
    h[0x29], h[0x2A], h[0x2B] = 0x10, 0x1E, o['level']
    struct.pack_into('<III', h, 0x2C, 0, int(time.time()) & 0xFFFFFFFF, 0xFFFFFFFF)
    keys = [ENERGY_SHIELD, PRAYER, BATTLE_ORDERS, SMITE] + [0xFFFF] * 12
    struct.pack_into('<16I', h, 0x38, *keys)
    struct.pack_into('<4I', h, 0x78, SMITE, PRAYER, SMITE, PRAYER)
    h[0x88:0xA8] = b'\xff' * 32
    h[0xA8:0xAB] = b'\x00\x00\x80'                      # Hell, act 1
    out = bytes(h) + b'Woo!' + struct.pack('<IH', 6, 298) + _QUESTS * 3
    out += b'WS' + struct.pack('<IH', 1, 80) + _WAYPOINTS * 3
    out += b'\x01w' + struct.pack('<H', 52) + bytes(48)
    return out


CHAR_STAT_BITS = {0: 10, 1: 10, 2: 10, 3: 10, 4: 10, 5: 8, 6: 21, 7: 21, 8: 21, 9: 21, 10: 21, 11: 21, 12: 7,
                  13: 32, 14: 25, 15: 25}


def _stats(P):
    o = P['o']
    life = (1 << 21) - 1
    st = [(0, 1023), (2, 1), (6, life), (7, life), (8, P['mana']['base_raw']), (9, P['mana']['base_raw']),
          (10, 8000 * 256), (11, 8000 * 256), (12, o['level']), (13, 3520485254)]
    bw = BitWriter()
    for sid, v in st:
        bw.write(9, sid)
        bw.write(CHAR_STAT_BITS[sid], v)
    bw.write(9, 0x1FF)
    return b'gf' + bw.bytes()


def _skills(P):
    o = P['o']
    sk = bytearray(30)
    if o['cls'] == 1:
        for sid, lv in ((WARMTH, 99), (40, 99), (TELEKINESIS, o['tk']), (50, 99), (54, 1), (ENERGY_SHIELD, 99),
                        (60, 99), (61, 99), (63, 99), (65, 99)):
            sk[sid - SOR_FIRST_SKILL] = lv
    return b'if' + bytes(sk)


def _item_records(P):
    """Item records (encode_item layout) of the plan: [top-level item, its socketed children...] per item."""
    rng = random.Random(P['rng_seed'])
    out = []
    units = P['units']
    for u in units:
        if u.kind != 'gear':
            continue
        kids = [k for k in units if k.parent is u]
        f = FLAG_IDENTIFIED | FLAG_ALWAYS | (FLAG_SOCKETED if kids else 0)
        rec = dict(flags=f, version=ITEM_VERSION, location=1, equipped=u.body, x=0, y=0, panel=0, code=u.code,
                   socketed_count=len(kids), id=rng.getrandbits(32), ilvl=90, quality=5, image=None,
                   auto_affix=None, set_unique_id=u.set_id, realm_bit=0, defense_raw=10, max_durability=0,
                   sockets=SOCKET_FIELD.get(u.code, 0), set_mask=31,
                   lists=[([(194, None, MAX_SOCKETS - SOCKET_FIELD.get(u.code, 0))] if kids else []) + u.slots[0].lines],
                   set_lists=[s.lines for s in u.slots[1:6]])
        grp = [rec]
        for j, k in enumerate(kids):
            grp.append(dict(flags=FLAG_IDENTIFIED | FLAG_ALWAYS | FLAG_RUNEWORD, version=ITEM_VERSION,
                            location=6, equipped=0, x=j, y=0, panel=0, code='jew ', socketed_count=0,
                            id=rng.getrandbits(32), ilvl=90, quality=JEWEL_QUALITY, image=None, auto_affix=None,
                            subquality=1, runeword_id=0xFFFF, realm_bit=0, lists=[k.slots[0].lines],
                            rw_list=k.slots[1].lines))
        out.append(grp)
    for i, u in enumerate(x for x in units if x.kind == 'charm'):
        out.append([dict(flags=FLAG_IDENTIFIED | FLAG_ALWAYS, version=ITEM_VERSION, location=0, equipped=0,
                         x=i % 10, y=i // 10, panel=1, code='cm1 ', socketed_count=0, id=rng.getrandbits(32),
                         ilvl=90, quality=CHARM_QUALITY, image=None, auto_affix=None, subquality=1, realm_bit=0,
                         lists=[u.slots[0].lines])])
    return out


def checksum(buf):
    c = 0
    for i, b in enumerate(buf):
        if 12 <= i < 16:
            b = 0
        c = (((c << 1) | (c >> 31)) + b) & 0xFFFFFFFF
    return c


def build(P):
    """The .d2s bytes of a plan (size and checksum filled in)."""
    items = _item_records(P)
    body = b''.join(encode_item(r) for grp in items for r in grp)
    out = bytearray(_header(P) + _stats(P) + _skills(P))
    out += b'JM' + struct.pack('<H', len(items)) + body
    out += b'JM\x00\x00' + b'jf' + b'kf\x00'
    struct.pack_into('<I', out, 8, len(out))
    struct.pack_into('<I', out, 12, checksum(out))
    return bytes(out)


def generate(preset='mock_high', name='Mock', **over):
    """(bytes, plan) of a new mock character."""
    P = plan(preset, name, **over)
    raw = build(P)
    if len(raw) >= FILE_LIMIT:
        raise PlanError(f'{len(raw)} bytes: over the 8 KB save limit')
    return raw, P


def expected(P):
    """What the analyzer should report for the generated file (the plan's targets)."""
    o = P['o']
    mana = P.get('side_a_mana', P['mana']['mana'])
    return dict(mana=mana, exact=o['exact'],
                tk=o['tk'], regen=P['regen']['total'], regen_cap=regen_cap(mana), life=P['life']['life'],
                smite_max=P['smite']['max'], pvm=P['pvm'], sources=dict(P['expect_sources']),
                side_b=P.get('side_b'), stun=P['stun'])


def summary(P, raw=None):
    """Short text lines about a plan (shown after Generate)."""
    o, m, e = P['o'], P['mana'], expected(P)
    out = [f"{o['label']}: TK {o['tk']}, mana {_num(e['mana'])} (base {_num(Fraction(m['base_raw'], 256))}, "
           f"+{m['flat']} flat, +{m['pct']}%)",
           f"regen {e['regen']}% / cap {e['regen_cap']}% (Meditation {P['regen']['med']}), life {_num(e['life'])}",
           f"smite max {e['smite_max']} PvM (target {e['pvm']}), stun {P['stun']}%"]
    if P.get('side_b'):
        out.append(f"side B mana {_num(P['side_b']['mana'])}")
    if raw is not None:
        out.append(f'{len(raw)} bytes')
    return out


def model_from_plan(P, raw=None):
    """The analyzer model of a plan without writing a file (the same keys as model_from_character): the summary
    panel of the generator; analyze(model_from_plan(P)) == analyze(model_from_character(the written file))."""
    o = P['o']
    units, set_ids, shields = [], {'A': set(), 'B': set(), None: set()}, {}
    for u in P['units']:
        L = [list(s.lines) for s in u.slots]
        if u.kind == 'gear':
            kids = [k for k in P['units'] if k.parent is u]
            if kids:
                L[0] = [(194, None, MAX_SOCKETS - SOCKET_FIELD.get(u.code, 0))] + L[0]
            set_ids[u.side].add(u.set_id)
            if u.code in SHIELD_DMG:
                shields[u.side] = u.code
            nm = f'{u.code.strip()}@{u.body}'
        elif u.kind == 'jewel':
            nm = f'{u.parent.code.strip()}@{u.parent.body}/{[k for k in P["units"] if k.parent is u.parent].index(u)}'
        else:
            i = [x for x in P['units'] if x.kind == 'charm'].index(u)
            nm = f'cm1@{i % 10},{i // 10}'
        units.append(Unit(u.kind, nm, L, u.side))
    sk = _skills(P)[2:]
    first = CLASS_FIRST_SKILL[o['cls']] if o['cls'] < 7 else 0
    return dict(name=P['name'], cls=o['cls'], level=o['level'], active_weapon=0, base_str=1023, base_ene=0,
                base_vit=0, base_mana_raw=P['mana']['base_raw'], base_life_raw=(1 << 21) - 1, stat_points=0,
                skills={first + i: lv for i, lv in enumerate(sk) if lv}, units=units, set_ids=set_ids,
                shields=shields, size=len(raw) if raw is not None else len(build(P)), excess_jewels=0)


# ---------------------------------------------------------------------------------- categories and the profile
# (category, [(key, label, stat ids)]) of the summary panel; ids summed over the active units ('lvl': x clvl / 8)
CATEGORIES = (
    ('Defenses', (('dr', 'DR flat', (34,)), ('dr_pct', 'DR %', (36,)), ('mdr', 'Magic DR', (35,)),
                  ('abs_pct', 'Absorb % (c/f/l/m)', (148, 142, 144, 146)),
                  ('abs_flat', 'Absorb flat', (149, 143, 145, 147)),
                  ('abs_lvl', 'Absorb / lvl (c/f/l)', (234, 235, 236)),
                  ('abs_time', 'Absorb by time (c/f/l)', (288, 289, 290)),
                  ('res_lvl', 'Resist / lvl (c/f/l)', (230, 231, 232)), ('res_flat', 'Resist (c/f/l/p)', (43, 39, 41, 45)),
                  ('max_res', 'Max resist (c/f/l)', (44, 40, 42)), ('curse_res', 'Curse resist', (109,)),
                  ('dodge', 'Dodge / avoid / evade', (338, 339, 340)), ('cbf', 'Cannot be frozen', (153,)))),
    ('Speeds', (('ias', 'IAS', (93,)), ('frw', 'FRW', (96,)), ('fhr', 'FHR', (99,)), ('fcr', 'FCR', (105,)),
                ('nv_ias', 'NV IAS', (68,)), ('nv_frw', 'NV FRW', (67,)))),
    ('Damage', (('str_lvl', 'Str / lvl', (220,)), ('damage', '+Damage (max, min)', (111, 21)),
                ('ow', 'Open wounds', (135,)), ('cb', 'Crushing blow', (136,)), ('ds', 'Deadly strike', (141,)),
                ('itd', 'Ignore target defense', (115,)), ('target_def', '-% Target defense', (116,)),
                ('dtm', 'Damage to mana', (114,)), ('mastery', 'Mastery (c/f/l)', (331, 329, 330)),
                ('pierce', 'Pierce (c/f/l)', (335, 333, 334)), ('thorns_lvl', 'Thorns / lvl', (238,)))),
    ('Life / mana', (('life', '+Life', (7,)), ('life_pct', 'Life %', (76,)), ('mana', '+Mana', (9,)),
                     ('mana_pct', 'Mana %', (77,)), ('regen', 'Mana regen %', (27,)), ('replenish', 'Replenish life', (74,)))),
)
# skills, charges and states by parameter: key -> (stat, param, or a ctc skill)
SPECIAL = {'smite': ('skill', SMITE), 'bo': ('skill', BATTLE_ORDERS), 'prayer_skill': ('skill', PRAYER),
           'delirium': ('ctc', DELIRIUM), 'stun': ('ctc', STUN), 'dopplezon': ('state', DOPPLEZON),
           'prayer': ('aura', PRAYER), 'thorns': ('aura', THORNS), 'barbs': ('aura', BARBS), 'oak': ('aura', OAK),
           'meditation': ('aura', MEDITATION), 'holy_aura': ('aura', (HOLY_FREEZE, HOLY_FIRE, HOLY_SHOCK))}


def category_totals(model, side=None):
    """{key: (total, lines)} of every CATEGORIES / SPECIAL key on a weapon side (an inactive switch counts nothing)."""
    t = totals(model, side)
    out = {}
    for _, rows in CATEGORIES:
        for key, _, ids in rows:
            out[key] = (sum(t['T'].get(i, 0) for i in ids), sum(t['N'].get(i, 0) for i in ids))
    for key, (kind, p) in SPECIAL.items():
        ps = p if isinstance(p, tuple) else (p,)
        tot = n = 0
        for u in t['units']:
            for sid, par, v in u.lines():
                hit = (kind == 'skill' and sid in (97, 107) and par in ps
                       or kind == 'aura' and sid == 151 and par in ps
                       or kind == 'state' and sid == 98 and par in ps and v
                       or kind == 'ctc' and sid in (195, 198) and par is not None and par >> 6 in ps)
                if hit:
                    tot += v
                    n += 1
        out[key] = (tot, n)
    return out


# the clone profile (docs/review/mock-pi-data/clone-profile.txt): the categories that (nearly) every proven clone
# of a role carries, and their typical totals (median of the role; line-value sums, per-level stats before x clvl/8)
_BASE = ('dr', 'dr_pct', 'abs_pct', 'abs_lvl', 'str_lvl', 'damage', 'dtm', 'smite', 'prayer_skill', 'dopplezon',
         'prayer', 'thorns', 'barbs', 'oak', 'meditation', 'life', 'mana', 'mana_pct', 'regen')
# 'always': carried by >= 2/3 of the role's proven clones (clones2 + clones; clone-99 / clone-48 weighted);
# 'typical': the role's median total
CLONE_PROFILE = {
    'mock': dict(always=_BASE + ('curse_res', 'dodge', 'ias', 'fhr', 'target_def', 'cb', 'nv_ias', 'res_lvl',
                                 'mastery', 'holy_aura', 'delirium', 'bo'),
                 typical=dict(dr=9717, dr_pct=255, abs_pct=381, abs_lvl=29862, res_lvl=9576, curse_res=511,
                              dodge=381, ias=107, frw=107, fhr=-36, nv_ias=97, nv_frw=97, str_lvl=2520, damage=22095,
                              ow=127, cb=127, target_def=381, dtm=472, mastery=71548, prayer=5518, thorns=4278,
                              barbs=3240, oak=2480, meditation=576, holy_aura=2418, delirium=254, stun=20, bo=99)),
    'host': dict(always=_BASE + ('res_lvl', 'curse_res', 'dodge', 'cbf', 'ias', 'ow', 'target_def', 'nv_ias', 'bo'),
                 typical=dict(dr=8860, dr_pct=227, abs_pct=381, abs_lvl=28570, res_lvl=6552, curse_res=511, dodge=381,
                              cbf=1, ias=107, fhr=-38, nv_ias=97, str_lvl=2520, damage=18591, ow=127, target_def=381,
                              dtm=504, prayer=5456, thorns=3984, barbs=3488, oak=2449, meditation=576, bo=99)),
    'pt': dict(always=_BASE + ('res_lvl', 'ias', 'frw', 'fhr', 'nv_frw'),
               typical=dict(dr=11214, dr_pct=255, abs_pct=381, abs_lvl=33170, res_lvl=11340, ias=-121, frw=71,
                            fhr=-38, nv_frw=97, str_lvl=2394, damage=19117, dtm=378, prayer=5440, thorns=4278,
                            barbs=3828, oak=1876, meditation=579, target_def=1524)),
    'ak': dict(always=('dr_pct', 'abs_pct', 'abs_lvl', 'res_lvl', 'curse_res', 'dodge', 'str_lvl', 'mastery', 'pierce',
                       'life', 'mana', 'mana_pct', 'regen', 'smite', 'delirium', 'holy_aura'),
               typical=dict(abs_lvl=17577, res_lvl=14175, curse_res=511, dodge=381, mastery=81812, pierce=45390,
                            holy_aura=4248, target_def=759, delirium=200)),
    'funky': dict(always=('frw', 'fhr', 'str_lvl', 'damage', 'mana', 'mana_pct', 'regen', 'stun', 'dodge',
                          'replenish'),
                  typical=dict(ias=-121, frw=-164, fhr=-121, fcr=-121, curse_res=511, dodge=381, replenish=2541,
                               str_lvl=3434, damage=25778, mana=17410, mana_pct=3996, stun=180)),
}


def profile_missing(model, role, side=None):
    """The categories every clone of the role carries that this character lacks on that side."""
    ct = category_totals(model, side)
    return [k for k in CLONE_PROFILE[role]['always'] if not ct.get(k, (0, 0))[1]]


def source_groups(names):
    """Source unit names grouped by item: [(item, short text, [every unit name])]; the charms as one group."""
    out = {}
    for nm in names:
        g = 'charms' if nm.startswith('cm') else nm.split('/')[0]
        out.setdefault(g, []).append(nm)
    res = []
    for g, L in out.items():
        if g == 'charms':
            res.append((f'{len(L)} charm(s)', '', L))
            continue
        jw = [x for x in L if '/' in x]
        txt = ('(item' + (f' + {len(jw)} jewel(s))' if jw else ')')) if g in L else f'({len(jw)} jewel(s))'
        res.append((g, txt, L))
    return res


def summary_rows(model, side=None, bo=False, role=None):
    """The summary panel: [(section, label, text, status)] for one weapon side (only its active items count):
    caps (mana band, off-screen, regen, smite, aura damage, size, lines), every active aura with its level and
    number of sources and the units that are its sources, the category totals, and the clone-profile check."""
    a = analyze(model, side, bo=bo)
    t = totals(model, side)
    v = a['values']
    rows = []
    status = {k: (lab, txt, st) for k, lab, txt, st in a['checks']}
    for k in ('mana', 'offscreen', 'regen', 'life', 'damage', 'hf', 'stun', 'delirium', 'size', 'lines', 'lists'):
        if k in status:
            lab, txt, st = status[k]
            rows.append(('Caps', lab, txt, st))
    for aid in sorted(set(t['aura_lv']) | set(t['sources'])):
        n = sum(t['sources'].get(aid, {}).values())
        groups = source_groups(t['source_units'].get(aid, []))
        rows.append(('Auras', AURA_NAMES.get(aid, str(aid)), f"level {t['aura_lv'].get(aid, 0)}, {n} source(s)"
                     + (': ' + ', '.join(f'{g} {d}'.strip() for g, d, _ in groups) if groups else
                        ' (passive levels only)'), status.get(f'aura_{aid}', (0, 0, INFO))[2] if n else INFO,
                     tuple((g, ', '.join(x)) for g, _, x in groups)))
    lvl = model['level']
    ct = category_totals(model, side)
    for cat, items in CATEGORIES:
        for key, label, ids in items:
            tot, n = ct[key]
            if not n:
                continue
            parts = [t['T'].get(i, 0) for i in ids if t['N'].get(i)]
            txt = '/'.join(str(x) for x in parts) if len(ids) > 1 else str(tot)
            if ids[0] in PER_LEVEL:
                txt += f' (x {lvl}/8 = {"/".join(str(x * lvl // 8) for x in parts)})'
            rows.append((cat, label, f'{txt}  [{n} line(s)]', INFO))
    sk = ', '.join(f"{AURA_NAMES.get(p, SKILL_NAMES.get(p, p))} {lv}" for p, lv in sorted(t['nonclass'].items()))
    if sk:
        rows.append(('Skills / states', 'Item skills', sk, INFO))
    st = sorted({p for u in t['units'] for sid, p, x in u.lines() if sid == 98 and x})
    if st:
        rows.append(('Skills / states', 'NV states', ', '.join(STATE_NAMES.get(p, str(p)) for p in st), INFO))
    if role in CLONE_PROFILE:
        miss = profile_missing(model, role, side)
        rows.append(('Clone profile', f'vs {role} clones', 'every category present' if not miss else
                     'missing: ' + ', '.join(miss), GOOD if not miss else WARN))
    return rows


SKILL_NAMES = {SMITE: 'Smite', BATTLE_ORDERS: 'Battle Orders', TELEKINESIS: 'Telekinesis', 8: 'Inner Sight',
               273: 'Mind Blast', 235: 'Cyclone Armor'}
STATE_NAMES = {DOPPLEZON: 'Dopplezon', NV_JUST_HIT: 'Just Hit', NV_HOLY_SHIELD: 'Holy Shield'}
PRESET_ROLE = {k: p.get('role', 'mock') for k, p in PRESETS.items()}


# ---------------------------------------------------------------------------------- generator form fields
# (group, [(key, label, kind, extra)]): kind 'int' = a spin box (extra = (lo, hi)), 'bool' = a check box, 'choice' =
# a combo box (extra = the values); every key is an options() key. 'src' after an aura: its source count (shown).
SWITCHES = ('none', 'balance')
FIELDS = (
    ('Mana / TK', (('tk', 'TK', 'int', (0, 99)), ('mana', 'Mana (BO)', 'int', (1, 16777215)),
                   ('bo', 'BO level', 'int', (0, 99)), ('level', 'Level', 'int', (99, 127)),
                   ('cls', 'Class', 'choice', CLASSES), ('position', 'Position', 'choice', tuple(POSITIONS)),
                   ('enemy_aura', 'Enemy aura', 'choice', ('preset',) + tuple(ENEMY_AURA_MANA)))),
    ('Life / regen', (('life', 'Life (BO)', 'int', (1, ROLL - 1)), ('med', 'Meditation', 'int', (0, 2000)),
                      ('regen', 'Regen % line', 'int', (0, 255)), ('replenish', 'Replenish bulk', 'bool', None))),
    ('Auras', (('prayer', 'Prayer', 'int', (0, 6200)), ('prayer_sources', 'Prayer src', 'int', (0, CHARM_COUNT)),
               ('thorns', 'Thorns', 'int', (0, 6000)), ('barbs', 'Barbs', 'int', (0, 6000)),
               ('oak', 'Oak Sage', 'int', (0, 6000)), ('hf_level', 'Holy Freeze', 'int', (0, 6000)),
               ('hf_sources', 'HF src', 'int', (0, 49)), ('hf_target', 'HF per src', 'int', (0, ROLL)),
               ('hf_cap', 'HF mastery', 'bool', None), ('thorns_lvl', 'Thorns / lvl', 'int', (0, 2000)))),
    ('Damage', (('damage', 'Smite PvP', 'int', (0, int(DMG_CAP_PVP))), ('smite_max', 'Max smite', 'bool', None),
                ('ow', 'Open wounds', 'int', (0, 1000)), ('cb', 'Crushing blow', 'int', (0, 1000)),
                ('ds', 'Deadly strike', 'int', (0, 1000)), ('target_def', '-% Target def', 'int', (0, 3000)),
                ('dtm', 'DTM %', 'int', (0, 2000)), ('pierce', 'Cold pierce', 'int', (0, 60000)),
                ('itd', 'Ignore target def', 'bool', None),
                ('weapon', 'Weapon (+20 lists)', 'bool', None))),
    ('Stun / Delirium', (('stun', 'Stun slider', 'int', (0, 100)), ('stun_lvl', 'Stun level', 'int', (0, 63)),
                         ('deli_attack', f'Deli att {DELIRIUM_CHANCE}%', 'int', (1, 63)),
                         ('deli_strike', f'Deli hit {DELIRIUM_CHANCE}%', 'int', (1, 63)))),
    ('Defenses', (('dr', 'DR / list', 'int', (0, 63)), ('dr_pct', 'DR %', 'int', (0, 2000)),
                  ('mdr', 'Magic DR', 'int', (0, 2000)), ('abs_pct', 'Absorb %', 'int', (0, 1000)),
                  ('abs_flat', 'Absorb flat', 'int', (0, 5000)), ('res_cold', 'Res/lvl cold', 'int', (0, 8000)),
                  ('res_fire', 'Res/lvl fire', 'int', (0, 8000)), ('res_light', 'Res/lvl light', 'int', (0, 8000)),
                  ('res_flat', 'Resist all', 'int', (-200, 8000)), ('curse_res', 'Curse res', 'int', (0, 2000)),
                  ('dodge', 'Dodge/avoid/evade', 'int', (0, 1000)), ('abs_lvl', 'Absorb / lvl', 'bool', None),
                  ('abs_time', 'Absorb by time', 'bool', None), ('cbf', 'Cannot be frozen', 'bool', None))),
    ('Speeds', (('ias', 'IAS', 'int', (-200, 1000)), ('frw', 'FRW', 'int', (-200, 1000)),
                ('fhr', 'FHR', 'int', (-200, 1000)), ('fcr', 'FCR', 'int', (-200, 1000)),
                ('nv_ias', 'NV IAS', 'int', (-300, 1000)), ('nv_frw', 'NV FRW', 'int', (-300, 1000)))),
    ('NV / switch', (('dopplezon', 'Dopplezon', 'bool', None), ('just_hit', 'Just Hit', 'bool', None),
                     ('holy_shield', 'Holy Shield', 'bool', None), ('switch', 'Weapon switch', 'choice', SWITCHES),
                     ('mana_b', 'Side B mana', 'int', (0, 16777215)))),
)
FIELD_KEYS = tuple(f[0] for _, fs in FIELDS for f in fs)
FIELD_KIND = {f[0]: f[2] for _, fs in FIELDS for f in fs}
FIELD_EXTRA = {f[0]: f[3] for _, fs in FIELDS for f in fs}
# the aura fields with the source count shown next to them (the plan's expected sources)
AURA_FIELD_SOURCE = dict(prayer=PRAYER, thorns=THORNS, barbs=BARBS, oak=OAK, med=MEDITATION, hf_level=HOLY_FREEZE)
# a short hint per field: unit and range
HINTS = dict(tk='hard TK points 0-99 (31: band 524288, 30: funky 1048576)', mana='max mana after BO; TK31 '
             '1210000-1572863', bo='BO level cast before the duel, 0-99 (0 = none; % = 35 + 3 per level)',
             level='character level 99-127', cls='character class (TK / ES need a Sorceress)',
             position='Host: DTM 500, no stun; HPJ / LPJ: high / low ping joiner (DTM 420 / 330, stun)',
             enemy_aura='TK31 mana by the enemy aura: high -> 1211974, mid -> 1310719, low -> 1572500, none -> 1572863',
             life='max life after BO, under 8388607', oak='Oak Sage total level (life %), one source per gear item',
             prayer='total Prayer level (31 per list = 5518)', prayer_sources='Prayer charms 0-40',
             thorns='Thorns total level (one source)', barbs='Barbs total level (one source)',
             med='Meditation level (one source: mana regen to the cap)',
             regen='mana regen % line 0-255', hf_level='Holy Freeze total level',
             hf_sources='Holy Freeze sources 0-42 (gear jewels)',
             hf_target='Holy Freeze damage per source (PvM) the cold mastery aims at; cap 8388607 (x 0.17 PvP)',
             hf_cap='cold mastery up to the per-source target (the clones: 43k-82k%)',
             thorns_lvl='attacker takes damage per level (sum of the lines)',
             damage='smite PvP damage, at most 713031', stun='0-100: more stun, less smite',
             stun_lvl='stun skill level of the attack / strike lines (clones: 0-2; xElite 63)',
             deli_attack='Delirium on attack, level 1-63',
             deli_strike='Delirium on strike, level 1-63 (not the attack level)',
             smite_max='on: smite exactly at the cap, every hit the max (thin margin); off: within 0.1% of the cap for the fewest bits',
             ow='chance of open wounds % (the bleed finishes a 1 HP target)', cb='crushing blow %',
             ds='deadly strike %', target_def='-% target defense (clones 254-1016)', dtm='damage taken goes to mana %',
             itd="ignore target's defense", pierce='-% enemy cold resist (clone-05: 255 on every list)', weapon='a socketed weapon (198 lists)',
             dr='flat damage reduced on every list (63 max per line)', dr_pct='damage reduced %',
             mdr='magic damage reduced', abs_pct='absorb % per element (cold, fire, lightning)',
             abs_flat='flat absorb per element', res_cold='cold resist by level (sum of lines, x clvl / 8)',
             res_fire='fire resist by level', res_light='lightning resist by level',
             res_flat='flat resist, every element (-100: the "-100 res" mocks)', curse_res='curse resistance (511)',
             dodge='dodge / avoid / evade % each', abs_lvl='absorb by level 63 on every list',
             abs_time='absorb by time bulk lines (not on a Host)', cbf='cannot be frozen',
             ias='increased attack speed', frw='faster run / walk', fhr='faster hit recovery (clones -36)',
             fcr='faster cast rate', nv_ias='non-visible attack rate (stat 68, 97 per line)',
             nv_frw='non-visible velocity (stat 67, 97 per line)', dopplezon='NV state Dopplezon on a charm',
             just_hit='NV state Just Hit on a charm', holy_shield='NV state Holy Shield on a charm',
             replenish='replenish life 33 bulk lines', switch='balance: side B copy of the shield with its own mana',
             mana_b='side B mana (weapon switch)')
_BOOL_KEYS = tuple(k for k, kind in FIELD_KIND.items() if kind == 'bool')


def prefill(preset='mock_high', **over):
    """The preset's actual values for every form field (the ones plan() solves taken from its plan)."""
    o = options(preset, **over)
    P = plan(preset, 'Mock', **over)
    pr = sum(v for s in P['lists'] for sid, p, v in s.lines if sid == 151 and p == PRAYER)
    solved = dict(oak=P['life']['oak'], med=P['regen']['med'], regen=P['regen']['pct'], prayer=pr,
                  prayer_sources=P['expect_sources'].get(PRAYER, 0), stun=o['stun'], cls=CLASSES[o['cls']],
                  enemy_aura='preset', switch=o['switch'] or 'none', mana_b=int(o.get('mana_b') or 0),
                  damage=int(o['damage']))
    out = {}
    for k in FIELD_KEYS:
        v = solved[k] if k in solved else o.get(k)
        kind = FIELD_KIND[k]
        out[k] = bool(v) if kind == 'bool' else str(v) if kind == 'choice' else int(v or 0)
    return out


def sources_of(P):
    """{aura field key: expected source count} of a plan (shown next to the aura fields)."""
    return {k: P['expect_sources'].get(a, 0) for k, a in AURA_FIELD_SOURCE.items()}


def _parse(k, v):
    kind = FIELD_KIND[k]
    if kind == 'bool':
        return bool(v)
    if kind == 'choice':
        return str(v)
    s = str(v if v is not None else '').strip().replace(' ', '').replace(',', '')
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        raise PlanError(f'{s!r} is not a number', key=k)


def edited(fields, pre):
    """options() overrides from the form: only the fields that differ from the prefill (the others stay solved
    by plan(), so changing the mana re-solves Meditation / Oak). Raises PlanError (with .key) on a bad field."""
    over = {}
    for k in FIELD_KEYS:
        if k not in fields:
            continue
        n = _parse(k, fields.get(k))
        if n is None or n == pre[k]:
            continue
        ex = FIELD_EXTRA[k]
        if FIELD_KIND[k] == 'int' and not ex[0] <= n <= ex[1]:
            raise PlanError(f'{n} outside {ex[0]}-{ex[1]}', key=k)
        if k == 'cls':
            n = CLASSES.index(n) if n in CLASSES else 1
        elif k == 'enemy_aura' and n == 'preset':
            continue
        elif k == 'switch':
            n = '' if n == 'none' else n
        over[k] = n
    if 'enemy_aura' in over:
        over.pop('mana', None)
    if over.get('switch') and not over.get('mana_b') and not pre.get('mana_b'):
        raise PlanError('side B mana needed for a weapon switch', key='mana_b')
    return over


def validate(preset, fields, pre):
    """(overrides, raw, plan, {field key: message}) of the form: the per-field problems (bad number, out of
    range, a target the plan cannot reach) keyed by the field they belong to ('' = the form as a whole)."""
    try:
        over = edited(fields, pre)
        raw, P = generate(preset, 'Mock', **over)
    except PlanError as e:
        return None, None, None, {getattr(e, 'key', None) or '': str(e)}
    return over, raw, P, {}


def plan_line(P, raw):
    """One line about a plan: mana and band, off-screen mana, lists used of the 198 the game keeps, bytes."""
    b = band_info(P.get('side_a_mana', P['mana']['mana']), P['o']['tk'])
    st = 'funky' if b['funky'] else 'good' if b['good'] else 'BAD'
    return (f"mana {_num(P['mana']['mana'])} ({st}), off-screen {_num(b['offscreen'])}, lists {len(P['lists'])}/198, "
            f"{len(raw)}/{FILE_LIMIT - 1} bytes")


# ---------------------------------------------------------------------------------- names and writing
def valid_name(name):
    return (isinstance(name, str) and 2 <= len(name) <= 15
            and all(c in '-_' or (c.isascii() and c.isalpha()) for c in name)
            and sum(c in '-_' for c in name) <= 1 and name[0] not in '-_' and name[-1] not in '-_')


def free_name(folder, name):
    """name, else name + a, b, ... (D2 names allow no digits) that no file in the folder uses yet."""
    if not valid_name(name):
        raise PlanError('name: 2 to 15 letters (A-Z), at most one - or _, not at the start or the end')
    taken = {f.lower().split('.')[0] for f in os.listdir(folder)} if os.path.isdir(folder) else set()
    if name.lower() not in taken:
        return name
    letters = 'abcdefghijklmnopqrstuvwxyz'
    for k in (1, 2, 3):
        for i in range(26 ** k):
            suf, x = '', i
            for _ in range(k):
                suf = letters[x % 26] + suf
                x //= 26
            n = name[:15 - k] + suf
            if valid_name(n) and n.lower() not in taken:
                return n
    raise PlanError('no free name')


def rename_raw(raw, name):
    b = bytearray(raw)
    b[0x14:0x24] = name.encode('latin1')[:15].ljust(16, b'\0')
    struct.pack_into('<I', b, 12, checksum(b))
    return bytes(b)


def write_new(raw, folder, name, read_only=False):
    """Writes a NEW <name>.d2s (the name made free first; exclusive create, never overwrites): the path.
    read_only: mark it read-only, so the game cannot save it (xp at level 127 resets it to 99)."""
    os.makedirs(folder, exist_ok=True)
    name = free_name(folder, name)
    path = os.path.join(folder, name + '.d2s')
    with open(path, 'xb') as f:
        f.write(rename_raw(raw, name))
    if read_only:
        import stat
        os.chmod(path, os.stat(path).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    return path


# ============================================================================================ item crafting
# Mock items carry arbitrary stats (no legit-only rule in Mock Mode). One line per stat: "<stat> [param] <value>"
# or the short forms below; '#' starts a comment.
SHORT = {'mana': 9, 'life': 7, 'mana%': 77, 'life%': 76, 'regen%': 27, 'dr': 34, 'dr%': 36, 'dtm': 114,
         'str/lvl': 220, 'dmg': 111, 'ias': 93, 'cb': 136, 'ow': 135, 'str': 0, 'dex': 2, 'vit': 3, 'ene': 1,
         'abscold/lvl': 234, 'absfire/lvl': 235, 'abslight/lvl': 236, 'coldmast': 331}
AURA_KEYS = {n.lower().replace(' aura', '').replace(' ', ''): k for k, n in AURA_NAMES.items()}
CRAFT_BASES = {'charm': ('cm1 ', 1), 'jewel': ('jew ', 2)}       # code, lists (jewel: magic + runeword list)


def parse_lines(text, isc=_vanilla_isc):
    """Stat lines from text. Forms: '9 223', '151 99 31' (stat param value), 'mana 223', 'aura prayer 31',
    'ctc_attack stun 63 10' (195 / 198 / 201: skill level chance), 'skill smite 63' (97). A blank line or
    '--' starts the next list (jewels: the runeword list). Raises PlanError with the line number."""
    lists, cur = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        s = raw.split('#')[0].strip().lower()
        if not s or s == '--':
            if cur:
                lists.append(cur)
                cur = []
            continue
        w = s.split()
        try:
            if w[0] == 'aura':
                line = (151, AURA_KEYS[w[1].replace('_', '')], int(w[2]))
            elif w[0] in ('ctc_attack', 'ctc_hit', 'ctc_struck'):
                sk = {'stun': STUN, 'delirium': DELIRIUM}.get(w[1]) or int(w[1])
                line = ({'ctc_attack': 195, 'ctc_hit': 198, 'ctc_struck': 201}[w[0]], (sk << 6) | int(w[2]),
                        int(w[3]))
            elif w[0] == 'skill':
                sk = {'smite': SMITE, 'prayer': PRAYER, 'bo': BATTLE_ORDERS}.get(w[1]) or int(w[1])
                line = (97, sk, int(w[2]))
            else:
                sid = SHORT[w[0]] if w[0] in SHORT else int(w[0])
                line = (sid, int(w[1]), int(w[2])) if len(w) == 3 else (sid, None, int(w[1]))
            bits, add, par = isc(line[0])
            if not bits:
                raise PlanError(f'line {n}: stat {line[0]} cannot be saved on an item')
            if not -add <= line[2] <= (1 << bits) - 1 - add:
                raise PlanError(f'line {n}: {line[2]} out of range ({-add} to {(1 << bits) - 1 - add})')
            if par and line[1] is None or not par and line[1] is not None:
                raise PlanError(f'line {n}: stat {line[0]} {"needs" if par else "takes no"} parameter')
            if line[1] is not None and not 0 <= line[1] < (1 << par):
                raise PlanError(f'line {n}: parameter out of range')
        except (KeyError, IndexError, ValueError):
            raise PlanError(f'line {n}: cannot read {raw.strip()!r}')
        cur.append(line)
    if cur:
        lists.append(cur)
    return lists


def craft_item(base, lists, x=0, y=0, seed=None, isc=_vanilla_isc):
    """Bytes of one crafted inventory item (superior small charm, or a jewel with a second, runeword list)."""
    code, n = CRAFT_BASES[base]
    if len(lists) > n:
        raise PlanError(f'a {base} has {n} stat list(s), {len(lists)} given')
    lists = list(lists) + [[]] * (n - len(lists))
    rng = random.Random(seed)
    rec = dict(flags=FLAG_IDENTIFIED | FLAG_ALWAYS | (FLAG_RUNEWORD if n == 2 else 0), version=ITEM_VERSION,
               location=0, equipped=0, x=x, y=y, panel=1, code=code, socketed_count=0, id=rng.getrandbits(32),
               ilvl=90, quality=3, image=0, auto_affix=None, subquality=1, realm_bit=0, runeword_id=0xFFFF,
               lists=[lists[0]], rw_list=lists[1] if n == 2 else None)
    return encode_item(rec, isc)


def free_cell(ch, data, w=10, h=4):
    """First free 1 x 1 cell (x, y) of the character's inventory, or None."""
    used = set()
    for e in ch.items:
        it = e.it
        if it.get('location') == 0 and it.get('panel') == 1:
            try:
                bw, bh = data.base(it.get('code')).size
            except Exception:
                bw = bh = 1
            for i in range(bw):
                for j in range(bh):
                    used.add((it.get('x', 0) + i, it.get('y', 0) + j))
    for y in range(h):
        for x in range(w):
            if (x, y) not in used:
                return x, y
    return None
