"""Offline item creator / editor for Median XL (single player).

Builds item records the way the game generates them (legit values only) and encodes them in the exact bit format
that mxl_format.parse_item reads (D2 1.13c / Median XL Sigma). Created items are written into a stash with the
collector's own safe writer (mxl_save.edit_stash: verification, backup, game-closed check).

Rules used (from the game's code and tables):
- automagic (base auto-prefix group, the innate affix) is rolled for every quality, sets and uniques included (Sigma);
- set items: 15-bit set-item row, no per-item set bonus lists (Median has no aprops), durability x2;
- uniques: 15-bit unique row, durability x3 (capped at 255);
- magic: 11-bit prefix/suffix = affix row + 1; rare: names (8+8 bits), up to 3 prefixes + 3 suffixes;
- runewords: 16-bit id = string-table index of the runeword name key (vanilla: of the row's 'RunewordN' key, see
  Creator.rw_string_id), runes socketed as children;
- ethereal (any item, any quality): stored defense x3/2, max durability /2 + 1;
- armor with Enhanced Defense: base defense = max + 1;
- stats are saved sorted by (stat, param), same stat+param from several mods are added together.
"""
import collections
import copy
import os
import random
import re
import struct

import stat_ids as S
from mxl_format import STAT_GROUPS, SET_UNIQUE_ID_BITS
from mxl_format_fix import (body_kind, ILVL_BITS, MAX_ILVL, QUANTITY_BITS, MAX_QUANTITY, SOCKET_FIELD_BITS,  # noqa: F401
                            SOCKET_FIELD_MAX, SOCKETED_COUNT_BITS, MAX_SOCKETED, socket_field_bits)   # save-format widths
from mxl_lang import T
from mxl_rules import (mod_ranges, mods_stats, item_type_codes, is_innate_damage, runeword_row,
                       stat_range, unique_name, rare_name)
from mxl_statnames import stat_text, param_kind, skilldesc_name, generic_label

HONORIFIC_STAT = 289                            # 'Orb Effects Applied to this Item are Doubled' (honorific items)
RELIC_CODE = 'cotw'                             # the base of every relic (327 unique rows, 90 of them empty)


def one_line(name):
    """One-line display name (multi-line game strings joined, colour codes removed)."""
    txt = str(name).replace('\\n', '\n')
    while 'ÿc' in txt:
        k = txt.index('ÿc')
        txt = txt[:k] + txt[k + 3:]
    return ' '.join(part.strip() for part in txt.split('\n') if part.strip())

QUALITY_ID = {'low': 1, 'normal': 2, 'superior': 3, 'magic': 4, 'set': 5, 'rare': 6, 'unique': 7, 'crafted': 8, 'tempered': 9}
QUALITY_NAME = {v: k for k, v in QUALITY_ID.items()}
ITEM_VERSION = 101
FLAG_IDENTIFIED = 1 << 4
FLAG_EAR = 1 << 16
FLAG_SOCKETED = 1 << 11
FLAG_NEW = 1 << 13                              # set on the one real honorific sample (fresh cube output)
FLAG_SIMPLE = 1 << 21
FLAG_ETHEREAL = 1 << 22
FLAG_ALWAYS = 1 << 23
FLAG_PERSONALIZED = 1 << 24
FLAG_RUNEWORD = 1 << 26
LOC_STORED, LOC_SOCKETED = 0, 6
PANEL_STASH = 5
CRAFTED_AFFIXES = 4  # crafted items: 4 rare affixes (1-3 prefixes, 1-3 suffixes), as the game's crafted items
FOLLOWERS = {s for lead, grp in STAT_GROUPS.items() for s in grp}

# Median XL's cluster / container / vessel items (gem clusters, rune containers, the Container of
# Knowledge, the shrine vessels). Their base rows carry no stackable flag, but the game still stores
# a "Quantity:" magic attribute on them (stat 501, up to 1000) - these codes are the game's own fixed
# item-code families; the trailing spaces some tables carry must not break the match ('asx ').
CLUSTER_CONTAINER_RE = re.compile(r'(?:gc\d\d|asx|cosx|rc\d\d|ec\d\d|sic1|[a-r]0\+s)\Z', re.IGNORECASE)
CLUSTER_QUANTITY_STAT = 501      # "Quantity:" (the Arcane Crystal count stat; the game shows it on clusters)
CLUSTER_QUANTITY_MAX = 1000      # the attribute's own cap (10 bits stored, add 23)


def is_cluster_container(code):
    """Whether an item code is one of Median XL's gem clusters, rune containers or shrine vessels."""
    return bool(code) and bool(CLUSTER_CONTAINER_RE.match(code.strip()))


# Median XL's throwable barrels and crates ("Barrel of Apples", "Crate O' Souls"...): the game holds
# them full at 1000, like the shrine vessels. Their codes span several families, so the item's own
# name decides - data-driven, no code list to maintain.
VESSEL_NAME_RE = re.compile(r'^(barrel|crate)\b', re.IGNORECASE)


def is_vessel(d, code):
    """A cluster / container / shrine vessel / barrel / crate: the items the game holds at Quantity 1000."""
    if is_cluster_container(code):
        return True
    try:
        name = (d.base(code).name or '').replace('\\n', '\n')
        return any(VESSEL_NAME_RE.match(l.strip()) for l in name.split('\n'))
    except Exception:
        return False


def stats_with_cluster_quantity(stats, value=CLUSTER_QUANTITY_MAX):
    """The stat list with the "Quantity:" attribute set: the existing attribute is replaced in place,
    otherwise the attribute is appended to the same list (in-place mutation: the returned list is
    always the `stats` object itself)."""
    value = max(0, min(CLUSTER_QUANTITY_MAX, int(value)))
    for s in stats:
        if s['id'] == CLUSTER_QUANTITY_STAT and not s.get('param'):
            s['value'] = value
            return stats
    stats.append({'id': CLUSTER_QUANTITY_STAT, 'param': None, 'value': value})
    return stats


class CreateError(Exception):
    """Item that cannot be created with legit values (message for the user)."""


def _plain(text):
    """One-line text without the game's colour codes (for labels)."""
    txt = str(text).replace('\\n', '\n')
    while 'ÿc' in txt:
        i = txt.index('ÿc')
        txt = txt[:i] + txt[i + 3:]
    return ' '.join(part.strip() for part in txt.split('\n') if part.strip())


class StoreError(CreateError):
    """A value the save format cannot hold (too many bits)."""


def container_codes(data):
    """Every container / cluster / barrel / crate / shrine vessel base (what is_vessel covers), in code order."""
    return sorted(c for c, b in data.bases.items() if b.kind == 'misc' and is_vessel(data, c))


def plan_container_fill(cr, items, pages):
    """One of every container (see container_codes), each a fresh game-default item at Quantity 1000, placed
    on the first run of adjacent EMPTY stash pages that holds them all (pages filled in order, so the pages
    used are adjacent). items: the stash's parsed items; pages: number of stash pages.
    [(page, x, y, blob)] or None when no such run of empty pages exists (then nothing is to be written)."""
    import mxl_save
    d = cr.data
    blobs = []
    for code in container_codes(d):
        blob, _rec = cr.build(cr.new_spec('normal', code))
        blobs.append(bytes(blob))
    used = {it['page'] for it in items}
    start = 0
    while start < pages:
        if start in used:
            start += 1
            continue
        end = start
        while end + 1 < pages and end + 1 not in used:
            end += 1
        run = list(range(start, end + 1))
        rest, out = [], []
        for blob in blobs:
            new = mxl_save.blob_item(blob, d)
            spot = mxl_save.free_spot(rest, new, d, run)
            if spot is None:
                break
            new['page'], new['x'], new['y'] = spot
            rest.append(new)
            out.append((spot[0], spot[1], spot[2], blob))
        if len(out) == len(blobs):
            return out
        start = end + 1
    return None


class Problem(str):
    """A legit-check message (in the chosen language) that remembers its stat id."""

    def __new__(cls, text, sid=None):
        obj = str.__new__(cls, text)
        obj.sid = sid
        return obj


# --------------------------------------------------------------------------------------------- bit writer

class BitWriter:
    def __init__(self):
        self.value = 0
        self.pos = 0

    def write(self, n, v):
        if n <= 0:
            return
        if v < 0 or v >= (1 << n):
            raise CreateError(f'value {v} does not fit in {n} bits')
        self.value |= v << self.pos
        self.pos += n

    def bytes(self):
        return self.value.to_bytes((self.pos + 7) // 8, 'little') if self.pos else b''


# --------------------------------------------------------------------------------------------- raw tables

def _rows(data, name):
    with open(f'{data.folder}/{name}.bin', 'rb') as f:
        b = f.read()
    n = struct.unpack_from('<I', b)[0]
    rs = (len(b) - 4) // n if n else 0
    return [b[4 + i * rs:4 + (i + 1) * rs] for i in range(n)]


def stat_cap(data, sid):
    """Largest value the game's ItemStatCost save field of stat sid holds (save bits, minus save add)."""
    c = data.isc[sid]
    return (1 << c['bits']) - 1 - c['add']


def durability_cap(data):
    """Most (max) durability an item record holds in this game: the ItemStatCost save fields of maxdurability and
    durability (8 bits in 1.14d: the 255 the game caps set x2 / unique x3 durability at)."""
    return min(stat_cap(data, S.MAX_DURABILITY), stat_cap(data, S.DURABILITY))


class Tables:
    """Fields of the game tables that mxl_data.Data does not load (offsets of the 1.13c structures,
    checked against the extracted tables)."""

    def __init__(self, data):
        self.data = data
        self.item = {}            # code -> extra base item fields
        for kind in ('weapons', 'armor', 'misc'):
            for r in _rows(data, kind):
                code = r[128:132].decode('latin1')
                if code in self.item:
                    continue
                self.item[code] = dict(compact=r[0x143], spawnable=r[0x133], dur=r[0x112], nodur=r[0x113],
                                       spawnstack=struct.unpack_from('<I', r, 0xEC)[0],
                                       qlvl=r[0xFD], magic_lvl=r[0x140], minac=struct.unpack_from('<i', r, 0xCC)[0],
                                       maxac=struct.unpack_from('<i', r, 0xD0)[0])
        self.itype = []           # index -> dict(magic_only, rare, normal_only, maxsock(1, 25, 40))
        for r in _rows(data, 'itemtypes'):
            self.itype.append(dict(magic_only=r[0x14], rare=r[0x15], normal_only=r[0x16],
                                   maxsock=(r[0x1A], r[0x1B], r[0x1C]), gfx=r[0x23]))
        self.affix_extra = {}     # kind -> [dict(rare, cls, freq)]
        for kind in ('magicprefix', 'magicsuffix', 'automagic'):
            self.affix_extra[kind] = [dict(rare=r[0x64], cls=r[0x66], cls_item=r[0x67], freq=r[0x82]) for r in _rows(data, kind)]
        self.rare_names = {}
        for kind in ('rareprefix', 'raresuffix'):
            self.rare_names[kind] = [dict(itypes={t for t in struct.unpack_from('<7h', r, 16) if t > 0},
                                          etypes={t for t in struct.unpack_from('<4h', r, 30) if t > 0},
                                          key=r[38:64].split(b'\0')[0].decode('latin1')) for r in _rows(data, kind)]
        self.superior = []        # qualityitems rows: (weapon ok, armor ok)
        for r in _rows(data, 'qualityitems'):
            self.superior.append(dict(weapon=bool(r[1] or r[3] or r[6]), armor=bool(r[0] or r[2] or r[8] or r[9])))
        self.rw_complete = [r[128] for r in _rows(data, 'runes')]
        self.rw_key = [r[:64].split(b'\0')[0].decode('latin1') for r in _rows(data, 'runes')]   # 'RunewordN'


# --------------------------------------------------------------------------------------------- encoding

def _write_stats(bw, stats, data, preserve_order=False):
    """Write a stat list followed by its end marker."""
    # belt and suspenders: merge same-(stat, param) entries here too (the game sums them; a leftover
    # duplicate once summed past the save range in-game while each entry looked fine) - param 0 and
    # no param are the same key
    acc = {}
    for s in stats:
        k = (s['id'], s.get('param') or None)
        acc[k] = acc.get(k, 0) + (s['value'] or 0)
    ordered = acc.items() if preserve_order else sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0))
    stats = [dict(id=k[0], param=k[1], value=v) for k, v in ordered]
    by_id = {}
    for s in stats:
        by_id.setdefault(s['id'], s)
    leads = {s['id'] for s in stats if s['id'] in STAT_GROUPS}
    for s in stats:
        sid = s['id']
        if sid in FOLLOWERS and any(sid in STAT_GROUPS[l] for l in leads):
            continue                        # written with its group lead
        bw.write(9, sid)
        for x in [sid] + STAT_GROUPS.get(sid, []):
            c = data.isc[x]
            st = s if x == sid else by_id.get(x, {'id': x, 'param': None, 'value': 0})
            if c['param']:
                bw.write(c['param'], st.get('param') or 0)
            raw = st['value'] + c['add']
            if not 0 <= raw < (1 << c['bits']):
                lo, hi = -c['add'], (1 << c['bits']) - 1 - c['add']
                raise StoreError(T('cr.err.store', 'stat {stat}: {value} cannot be stored ({lo} to {hi})',
                                   stat=x, value=st['value'], lo=lo, hi=hi))
            bw.write(c['bits'], raw)
    bw.write(9, 0x1FF)


class BetaItemBlob(bytes):
    """Mark native beta clipboard bytes when they leave a character window."""

    beta_item = True


class BetaItemData:
    """Item tables with the durability width used in the 1.10s beta."""

    realm_stamp_bits = 96
    beta_items = True

    def __init__(self, data):
        self.source = data
        self.isc = dict(data.isc)
        self.isc[S.DURABILITY] = dict(self.isc[S.DURABILITY], bits=8)

    def __getattr__(self, name):
        return getattr(self.source, name)


def encode_item(rec, data, *, preserve_stat_order=False):
    """Bytes ('JM' + bits) of one item record. rec keys: the fields of mxl_format.Item plus
    flags (raw 32-bit header flags), runeword_id (16 bits), tome_bits, realm_bit, set_mask; stats lists are
    lists of {id, param, value}. Socketed children are not included (see build_blob)."""
    bw = BitWriter()
    flags = rec['flags']
    bw.write(32, flags)
    bw.write(10, rec.get('version', ITEM_VERSION))
    bw.write(3, rec.get('location', LOC_STORED))
    bw.write(4, rec.get('equipped', 0))
    bw.write(4, rec.get('x', 0))
    bw.write(4, rec.get('y', 0))
    bw.write(3, rec.get('panel', PANEL_STASH))
    code = rec['code']
    if flags & FLAG_EAR and code == 'ear ':
        name = rec['ear_name']
        if len(name) > 15 or not name.isascii() or '\0' in name:
            raise CreateError('An ear name must fit in 15 ASCII characters.')
        bw.write(3, rec['ear_class'])
        bw.write(7, rec['ear_level'])
        for char in name:
            bw.write(7, ord(char))
        bw.write(7, 0)
        padding = -bw.pos % 8
        bw.write(padding, rec.get('ear_pad', 0) & ((1 << padding) - 1))
        return b'JM' + bw.bytes()
    for ch in code:
        bw.write(8, ord(ch))
    if flags & FLAG_SIMPLE:
        bw.write(1, rec.get('socketed_count', 0))
        return b'JM' + bw.bytes()
    bw.write(SOCKETED_COUNT_BITS, rec.get('socketed_count', 0))
    bw.write(32, rec['id'])
    bw.write(7, rec['ilvl'])
    q = rec['quality']
    bw.write(4, (QUALITY_ID[q] if q != 'unknown' else rec['quality_raw']) if isinstance(q, str) else q)
    q = QUALITY_NAME.get(q, q) if not isinstance(q, str) else q
    if rec.get('image') is not None:
        bw.write(1, 1)
        bw.write(3, rec['image'])
    else:
        bw.write(1, 0)
    if rec.get('auto_affix') is not None:
        bw.write(1, 1)
        bw.write(11, rec['auto_affix'])
    else:
        bw.write(1, 0)
    if q in ('low', 'superior'):
        bw.write(3, rec.get('subquality', 0))
    elif q == 'magic':
        bw.write(11, rec.get('prefix') or 0)
        bw.write(11, rec.get('suffix') or 0)
    elif q in ('set', 'unique'):
        bw.write(SET_UNIQUE_ID_BITS, rec['set_unique_id'])
    elif q == 'tempered':                       # Sigma quality 9: the name only, affix stats in the stat list
        a, b = rec['rare_names']
        bw.write(8, a)
        bw.write(8, b)
    elif q in ('rare', 'crafted'):
        a, b = rec['rare_names']
        bw.write(8, a)
        bw.write(8, b)
        for af in rec['rare_affixes']:
            if af:
                bw.write(1, 1)
                bw.write(11, af)
            else:
                bw.write(1, 0)
    if flags & FLAG_RUNEWORD:
        bw.write(16, rec['runeword_id'])
    if flags & FLAG_PERSONALIZED:
        for ch in rec.get('personalized_name', ''):
            bw.write(7, ord(ch))
        bw.write(7, 0)
    if code in ('tbk ', 'ibk '):
        bw.write(5, rec.get('tome_bits', 0))
    realm_bit = rec.get('realm_bit', 0)
    bw.write(1, realm_bit)
    stamp_bits = getattr(data, 'realm_stamp_bits', 0)
    if realm_bit and stamp_bits:
        bw.write(stamp_bits, rec.get('realm_stamp', 0))
    base = data.base(code)
    kind = body_kind(data, code)
    if kind == 'armor':
        c = data.isc[S.DEFENSE]
        bw.write(c['bits'], rec['defense'] + c['add'])
    if kind in ('armor', 'weapons'):
        cm = data.isc[S.MAX_DURABILITY]
        maxd = rec['max_durability']          # raw value, as read by parse_item
        bw.write(cm['bits'], maxd)
        if maxd != cm['add']:
            bw.write(data.isc[S.DURABILITY]['bits'], rec['durability'])
    if base.stack_max is not None:
        bw.write(QUANTITY_BITS, rec.get('quantity', 1))
    if flags & FLAG_SOCKETED:
        bw.write(socket_field_bits(data), rec.get('sockets', 0))
    set_mask = rec.get('set_mask', 0)
    if q == 'set':
        bw.write(5, set_mask)
    ws = getattr(data, 'rec_write_stats', None) or (lambda w, st: _write_stats(w, st, data, preserve_stat_order))
    ws(bw, rec.get('stats', []))
    for i in range(5):
        if set_mask >> i & 1:
            ws(bw, rec.get(f'set_stats_{i}', []))
    if flags & FLAG_RUNEWORD:
        ws(bw, rec.get('stats_runeword', []))
    if hasattr(data, 'rec_write_end'):
        data.rec_write_end(bw, rec)
    return b'JM' + bw.bytes()


NUM_SOCKETS = 194          # item_numsockets: an affix's "sock" property ("Innate" of Angelic gear: +6) is turned into
                           # real sockets by the game (capped at the item's maximum), never kept as a stat - except
                           # the vanilla sockets beyond the save field (Creator.socket_split: marked sockets=True)


def build_blob(rec, children, data, *, preserve_stat_order=False):
    """Item bytes followed by its socketed items (format of a stash entry)."""
    for k in ('stats', 'stats_runeword'):
        if rec.get(k):
            rec[k] = [s for s in rec[k] if s['id'] != NUM_SOCKETS or s.get('sockets')]
    out = encode_item(rec, data, preserve_stat_order=preserve_stat_order)
    for i, ch in enumerate(children):
        ch = dict(ch, location=LOC_SOCKETED, equipped=0, x=i, y=0, panel=0)
        out += encode_item(ch, data, preserve_stat_order=preserve_stat_order)
    return out


# --------------------------------------------------------------------------------------------- decoding (lossless)

class _BR:
    def __init__(self, b):
        self.v = int.from_bytes(b, 'little')
        self.pos = 0
        self.n = len(b) * 8

    def read(self, n):
        r = (self.v >> self.pos) & ((1 << n) - 1)
        self.pos += n
        return r


def _read_stats(br, data, starts=None):
    out = []
    while True:
        start = br.pos
        sid = br.read(9)
        if sid == 0x1FF:
            if starts is not None:
                starts.append(16 + start)
            return out
        if br.pos > br.n:
            raise CreateError('stat list without end marker')
        for x in [sid] + STAT_GROUPS.get(sid, []):
            if starts is not None:
                starts.append(16 + (start if x == sid else br.pos))
            c = data.isc[x]
            p = br.read(c['param']) if c['param'] else None
            out.append(dict(id=x, param=p, value=br.read(c['bits']) - c['add']))


def decode_item(blob, data, *, offsets=None):
    """Read one item and its byte length. Optionally record the field offsets from the start of JM."""
    if getattr(blob, 'beta_item', False) and not getattr(data, 'beta_items', False):
        raise CreateError('This item uses the 1.10s beta layout. Open a beta character to use it.')
    if blob[:2] != b'JM':
        raise CreateError('not an item')
    reason = getattr(blob, 'read_only_reason', None) or getattr(blob, 'edit_reason', None)
    if reason:
        raise CreateError(reason)
    if getattr(blob, 'v109_raw', False):            # mxl_v109.Raw109: a 1.09 record kept as read
        raise CreateError(T('cr.err.old_raw', 'This 1.09 item holds values the item editor cannot keep: it can be '
                            'moved or deleted, not edited.'))
    br = _BR(bytes(blob[2:]))

    def mark(field):
        if offsets is not None:
            offsets[field] = 16 + br.pos

    r = {}
    mark('flags')
    r['flags'] = flags = br.read(32)
    mark('version')
    r['version'] = br.read(10)
    mark('location')
    r['location'] = br.read(3)
    mark('equipped')
    r['equipped'] = br.read(4)
    mark('x')
    r['x'] = br.read(4)
    mark('y')
    r['y'] = br.read(4)
    mark('panel')
    r['panel'] = br.read(3)
    if flags & FLAG_EAR:
        from mxl_format_fix import LENIENT

        if LENIENT and getattr(data, 'save_version', 96) == 96:
            r.update(code='ear ', socketed_count=0)
            mark('ear_class')
            r['ear_class'] = br.read(3)
            mark('ear_level')
            r['ear_level'] = br.read(7)
            mark('ear_name')
            name = []
            for _ in range(16):
                char = br.read(7)
                if not char and br.pos <= br.n:
                    break
                name.append(chr(char))
            else:
                raise CreateError('An ear record has no complete name.')
            r['ear_name'] = ''.join(name)
            r['ear_pad'] = br.read(-br.pos % 8)
            return r, 2 + br.pos // 8
    mark('code')
    r['code'] = code = ''.join(chr(br.read(8)) for _ in range(4))
    if flags & FLAG_SIMPLE:
        mark('socketed_count')
        r['socketed_count'] = br.read(1)
        return r, 2 + (br.pos + 7) // 8
    mark('socketed_count')
    r['socketed_count'] = br.read(SOCKETED_COUNT_BITS)
    mark('id')
    r['id'] = br.read(32)
    mark('ilvl')
    r['ilvl'] = br.read(ILVL_BITS)
    q = r['quality'] = QUALITY_NAME.get(br.read(4), 'unknown')
    if q == 'unknown':
        r['quality_raw'] = br.v >> (br.pos - 4) & 15      # (0: hacked saves) written back as it was
    mark('image')
    r['image'] = br.read(3) if br.read(1) else None
    mark('auto_affix')
    r['auto_affix'] = br.read(11) if br.read(1) else None
    if q in ('low', 'superior'):
        mark('subquality')
        r['subquality'] = br.read(3)
    elif q == 'magic':
        mark('prefix')
        r['prefix'] = br.read(11)
        mark('suffix')
        r['suffix'] = br.read(11)
    elif q in ('set', 'unique'):
        mark('set_unique_id')
        r['set_unique_id'] = br.read(SET_UNIQUE_ID_BITS)
    elif q == 'tempered':
        mark('rare_names')
        r['rare_names'] = (br.read(8), br.read(8))
    elif q in ('rare', 'crafted'):
        mark('rare_names')
        r['rare_names'] = (br.read(8), br.read(8))
        mark('rare_affixes')
        r['rare_affixes'] = [br.read(11) if br.read(1) else None for _ in range(6)]
    if flags & FLAG_RUNEWORD:
        mark('runeword_id')
        r['runeword_id'] = br.read(16)
    if flags & FLAG_PERSONALIZED:
        mark('personalized_name')
        s = ''
        while True:
            ch = br.read(7)
            if not ch:
                break
            s += chr(ch)
        r['personalized_name'] = s
    if code in ('tbk ', 'ibk '):
        mark('tome_bits')
        r['tome_bits'] = br.read(5)
    mark('realm_bit')
    r['realm_bit'] = br.read(1)
    stamp_bits = getattr(data, 'realm_stamp_bits', 0)
    if r['realm_bit'] and stamp_bits:
        mark('realm_stamp')
        r['realm_stamp'] = br.read(stamp_bits)
    base = data.base(code)
    kind = body_kind(data, code)
    if kind == 'armor':
        c = data.isc[S.DEFENSE]
        mark('defense')
        r['defense'] = br.read(c['bits']) - c['add']
    if kind in ('armor', 'weapons'):
        mark('max_durability')
        cm = data.isc[S.MAX_DURABILITY]
        r['max_durability'] = br.read(cm['bits'])
        if r['max_durability'] != cm['add']:
            mark('durability')
            r['durability'] = br.read(data.isc[S.DURABILITY]['bits'])
    if base.stack_max is not None:
        mark('quantity')
        r['quantity'] = br.read(QUANTITY_BITS)
    if flags & FLAG_SOCKETED:
        mark('sockets')
        r['sockets'] = br.read(socket_field_bits(data))
    mark('set_mask')
    r['set_mask'] = br.read(5) if q == 'set' else 0
    legacy_stats = getattr(data, 'rec_read_stats', None)

    def read_stats(field):
        mark(field)
        if legacy_stats is not None:
            return legacy_stats(br)
        starts = [] if offsets is not None else None
        stats = _read_stats(br, data, starts)
        if starts is not None:
            offsets.update((f'{field}:{i}', start) for i, start in enumerate(starts))
        return stats

    r['stats'] = read_stats('stats')
    for i in range(5):
        if r['set_mask'] >> i & 1:
            key = f'set_stats_{i}'
            r[key] = read_stats(key)
    if flags & FLAG_RUNEWORD:
        r['stats_runeword'] = read_stats('stats_runeword')
    if hasattr(data, 'rec_read_end'):
        data.rec_read_end(br, r)
    return r, 2 + (br.pos + 7) // 8


def renew_item_ids(blob, data):
    """A copy of blob (an item and its socketed items) with a fresh random 32-bit item id in each record. The game
    gives every item its own id; copies sharing one are what the server reports as duplicates. Vanilla only
    (Median keeps its copies as they are); other blobs are returned unchanged."""
    if not Creator._vanilla() or type(blob) not in (bytes, bytearray) or bytes(blob[:2]) != b'JM':
        return blob
    ba = bytearray(blob)
    pos = 0
    try:
        while pos < len(ba) and ba[pos:pos + 2] == b'JM':
            off = {}
            rec, size = decode_item(bytes(ba[pos:]), data, offsets=off)
            if 'id' in off:
                start, value = pos * 8 + off['id'], random.getrandbits(32)
                for i in range(32):
                    k = start + i
                    ba[k // 8] = (ba[k // 8] & ~(1 << (k % 8))) | (((value >> i) & 1) << (k % 8))
            pos += size
    except Exception:
        return blob
    return bytes(ba)


class ClipItem(tuple):
    """The item clipboard entry (blob, name): every read of the blob gives a copy with its own fresh item id, so
    pasting twice (or Paste All) never makes duplicates."""

    def __new__(cls, blob, name, data=None):
        self = super().__new__(cls, (blob, name))
        self.data = data
        return self

    def __getitem__(self, i):
        v = super().__getitem__(i)
        if i == 0 and self.data is not None:
            return renew_item_ids(v, self.data)
        return v


def decode_blob(blob, data, *, exact=False):
    """Item + socketed children of a stash entry: (record, [child records])."""
    rec, n = decode_item(blob, data)
    kids = []
    p = n
    socketed = rec['flags'] & FLAG_SOCKETED and not rec['flags'] & FLAG_SIMPLE
    for _ in range(rec.get('socketed_count', 0) if socketed else 0):
        k, m = decode_item(blob[p:], data)
        kids.append(k)
        p += m
    if exact and p != len(blob):
        raise CreateError(f'Item data consumes {p} bytes of a {len(blob)}-byte record.')
    return rec, kids


# --------------------------------------------------------------------------------------------- stats from mods

def layered_stats(mods, data, how):
    """mods_stats with the stat param the item stores: vanilla skill tabs (property function 10) pack the sheet's
    param (class * 3 + tab) as class << 3 | tab, so affix / mod stats compare with the saved item's."""
    out = []
    for m in mods:
        part = mods_stats([m], data, how)
        if Creator._vanilla() and data.prop_func[m[0]] == 10:
            part = [dict(x, param=((x['param'] // 3) << 3) | (x['param'] % 3)) if x.get('param') is not None else x
                    for x in part]
        out += part
    return merge_stats(out)


def merge_stats(stats):
    """Same (stat, param) added together, then sorted as the game saves them."""
    acc = {}
    for s in stats:
        k = (s['id'], s.get('param'))
        acc[k] = acc.get(k, 0) + s['value']
    return [dict(id=k[0], param=k[1], value=v) for k, v in sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0))]


def _skill_req(skill):
    """(reqlevel, maxlvl) of a skill id from the stock tables of the legit validator (vanilla); (1, 20) unknown."""
    try:
        import mxl_legit
        row = mxl_legit._validator().rows('skills')[int(skill)]
        return int(row.get('reqlevel') or 1), int(row.get('maxlvl') or 20)
    except Exception:
        return 1, 20


def _charged(ilvl, req, top, lo, hi):
    from d2bt.itemgen.stats import charged_level_capacity
    return charged_level_capacity(ilvl, req, top, lo, hi)


class Mod:
    """One mod (property, param, min, max) of an item and its rolled value."""

    def __init__(self, source, prop, param, lo, hi, data, label=''):
        self.source, self.prop, self.param = source, prop, param
        self.min, self.max = min(lo, hi), max(lo, hi)
        self.raw = (prop, param, lo, hi)
        self.label = label
        funcs = data.prop_funcs[prop]
        fixed_kind = (any(f in (15, 16, 17) for f in funcs) or data.prop_func[prop] in (11, 19)
                      or any(is_innate_damage(s, data) for s in data.props[prop] if s >= 0))
        self.variable = (self.min != self.max) and not fixed_kind
        self.value = self.max if self.variable else None

    def stats(self, data):
        out = self._stats(data)
        if Creator._vanilla():
            lo, hi = self.raw[2], self.raw[3]
            if data.prop_func[self.prop] == 36:
                # random class skills: the sheet's range is the CLASS (the stat's param), the bonus is the
                # property's own value (the server's rule: Hellfire Torch rolls +3 to one class)
                for s in out:
                    if s['id'] == 83:
                        s['param'], s['value'] = s['value'], data.prop_vals[self.prop][0]
            for s in out:
                if s['id'] == 107 and lo < hi and s.get('param') in (42, 50, 60) and lo <= s['param'] <= hi:
                    # a random skill of lo..hi (skill-rand): the game never picks skills 42, 50 and 60
                    s['param'] = next(x for x in (s['param'] - 1, s['param'] + 1, s['param'] - 2, s['param'] + 2)
                                      if lo <= x <= hi and x not in (42, 50, 60))
        if data.prop_func[self.prop] == 10 and Creator._vanilla():
            # Properties.txt function 10 (skill tab): the sheet's param is class * 3 + tab, the stat's layer
            # (class << 3) | tab - the server's legit rule (d2bt.tooltip.item.apply_property)
            for s in out:
                if s['param'] is not None:
                    s['param'] = ((s['param'] // 3) << 3) | (s['param'] % 3)
        return out

    def _stats(self, data):
        prop, param, lo, hi = self.raw
        funcs = data.prop_funcs[prop]
        if data.prop_func[prop] == 19 and Creator._vanilla():
            # charged skill (function 11, skill on hit / striking / level up, keeps the sheet's level as it is): the game's level and charges for the item level (ITEMMODS_PropertyFunc19, the dev
            # kit's d2bt.itemgen.stats.charged_level_capacity): min = charges (negative: level x |min| / 8 + |min|),
            # max = level (0 / negative: from the item level and the skill's reqlevel / maxlvl)
            req, top = _skill_req(param)
            level, capacity = _charged(getattr(self, 'ilvl', 99), req, top, lo, hi)
            lo, hi = capacity, level
        if any(f in (15, 16, 17) for f in funcs):
            # min / max / param given as such to each stat (no min-max swap: e.g. cold length + affix count)
            out = {}
            vanilla = Creator._vanilla()     # a blank param (the sheet's) is the property's own min - the server's rule
            for sid, f in zip(data.props[prop], funcs):
                if sid < 0:
                    continue
                v = lo if f == 15 else hi if f == 16 else (param or lo if vanilla else param) if f == 17 else lo
                out[sid] = v
            for one, others in ((S.MIN_DAMAGE, (S.MIN_DAMAGE_2, S.THROW_MIN_DAMAGE)),
                                (S.MAX_DAMAGE, (S.MAX_DAMAGE_2, S.THROW_MAX_DAMAGE))):
                if one in out:
                    for o in others:
                        out.setdefault(o, out[one])
            return [dict(id=sid, param=param if data.isc[sid]['param'] else None, value=v) for sid, v in out.items()]
        if not self.variable:
            return mods_stats([(prop, param, lo, hi)], data, 'min')
        if getattr(self, 'free', False) and self.value is not None:
            v = self.value          # unrestricted: the chosen value, even outside the mod's own range
        else:
            v = max(self.min, min(self.max, self.value))
        return mods_stats([(prop, param, v, v)], data, 'min')

    def stat_ids(self, data):
        return [s['id'] for s in mods_stats([self.raw], data, 'min')]


# --------------------------------------------------------------------------------------------- creator

def _clean_orange(name):
    """One-line display text (multi-line game strings joined, colour codes removed)."""
    txt = str(name).replace('\\n', '\n')
    while 'ÿc' in txt:
        i = txt.index('ÿc')
        txt = txt[:i] + txt[i + 3:]
    return ' '.join(part.strip() for part in txt.split('\n') if part.strip())


class Creator:
    """Catalogs and legit generation of items, on top of mxl_data.Data."""

    def __init__(self, data):
        self.data = data
        self.t = Tables(data)
        data.key('x')                                      # builds data._bykey
        self.rw_list = [i for i, (n, runes, ok, ex) in enumerate(data.runewords)
                        if runes and self.t.rw_complete[i] and self.rw_string_id(i) is not None]
        try:
            data._sn_string_tags_fn = self.orange_effect_tags    # the attribute picker's orange-text labels
        except Exception:
            pass

    def orange_effect_tags(self):
        """{string id: tag} for the orange-text stats' picker (375/377/378/385): what the text DOES - the
        effect stats the game's own rows pair with it ('effect: Demon Blood aura'), or 'display only' when
        the text is the whole thing."""
        tags = {}
        for t in self.orange_texts():
            disp = t.get('display') or {}
            if disp.get('id') not in (375, 377, 378, 385) or disp.get('param') is None:
                continue
            fx = [e.get('label') for e in (t.get('effects') or []) + (t.get('hidden') or []) if e.get('label')]
            old = tags.get(disp['param'])
            if fx:
                tags[disp['param']] = 'effect: ' + ', '.join(dict.fromkeys(fx))[:70]
            elif old is None:
                tags[disp['param']] = 'display only'
        return tags

    # ---- catalogs
    def base_name(self, code):
        b = self.data.base(code)
        return b.name

    def bases(self):
        """Base items that can be created (weapons, armor, misc with a name and an icon), sorted by name."""
        out = []
        for code, b in self.data.bases.items():
            if not code.strip() or not b.name:      # quest items too (keys, quest drops): the editor makes anything
                continue
            if 'POLAR BUFFALO' in b.name.upper():
                continue                    # 15 unused item rows whose name string is the game's placeholder
            out.append(b)
        return sorted(out, key=lambda b: (b.kind, b.name.lower()))

    def uniques(self):
        """[(row, name, row dict)] of the uniques the creator lists. Left out: rows without a base or a name string,
        the 90 empty relic rows ('RelicX' on base cotw with no mod at all: table padding between the real
        relics - built, they are a relic that grants nothing and all read "Relic - Relic") and any other row that
        has no mod and is not enabled (the same kind of leftover; all 90 relic rows are not enabled either). A row
        without mods that IS enabled stays: those are the game's own items whose text is the base's description
        (Golden Cycle, Ring of Pride, Book of Cain reagent, Dulra Aegis, Corrupted Wormhole)."""
        out = []
        for i, u in enumerate(self.data.uniques):
            if u['code'].strip() and u['code'] in self.data.bases and u['name'] in self.data._bykey:
                if u['code'] == RELIC_CODE and not u['mods']:
                    continue
                if not u['mods'] and not self.unique_enabled(i):
                    continue                # an empty row the game never makes (2.14.6: the second "Windforce")
                out.append((i, self.data.key(u['name']).replace('\n', ' '), u))
        return sorted(out, key=lambda x: x[1].lower())

    def set_items(self):
        out = []
        for i, u in enumerate(self.data.set_items):
            if u['code'].strip() and u['code'] in self.data.bases and u['name'] in self.data._bykey:
                out.append((i, self.data.key(u['name']).replace('\n', ' '), u))
        return sorted(out, key=lambda x: x[1].lower())

    def rw_string_id(self, row):
        """The item's 16-bit runeword field for runes row `row`: the string-table index of the row's name key.
        Median XL: the key is the runeword's name (data._bykey). Vanilla 1.10+: the key is the row's Name column
        ('RunewordN'); the game takes it from patchstring (10000+) before expansionstring (20000+) and string (0+),
        so the field reads as a 12-bit id plus a 4-bit table part (Spirit 20635 = 155 + 5 << 12; Delirium,
        redefined in patchstring: 10910 = 2718 + 2 << 12)."""
        if not self._vanilla():
            return self.data._bykey.get(self.data.runewords[row][0])
        ids = getattr(self, '_rw_ids', None)
        if ids is None:
            keys = set(self.t.rw_key)
            rank = {}
            for i, v in self.data.strings.items():
                if isinstance(v, tuple) and v[0] in keys and 0 <= i < 0x10000:
                    r = 0 if 10000 <= i < 20000 else 1 if i >= 20000 else 2
                    if v[0] not in rank or r < rank[v[0]][0]:
                        rank[v[0]] = (r, i)
            ids = self._rw_ids = {k: v[1] for k, v in rank.items()}
        return ids.get(self.t.rw_key[row]) if row < len(self.t.rw_key) else None

    def runewords(self):
        out = []
        for i in self.rw_list:
            n, runes, ok, ex = self.data.runewords[i]
            out.append((i, self.data.key(n), [self.data.item_index[r] for r in runes]))
        return sorted(out, key=lambda x: x[1].lower())

    def types_of(self, code):
        return self.data.type_ancestors(self.data.base(code).type) | self.data.type_ancestors(self.data.base(code).type2)

    def type_codes(self, code):
        return {self.data.itypes[t][0] for t in self.types_of(code)}

    def runeword_bases(self, rw):
        n, runes, ok, ex = self.data.runewords[rw]
        out = []
        for b in self.bases():
            if b.kind == 'misc':
                continue
            anc = self.types_of(b.code)
            if anc & set(ok) and not anc & set(ex) and self.max_sockets(b.code, self.max_ilvl()) >= len(runes):
                out.append(b)
        return out

    def quantity_max(self, code):
        """Largest quantity of a stackable base: its maxstack (misc / weapons table), at most what the save's
        quantity field holds. None when the base does not stack."""
        b = self.data.base(code)
        return None if b.stack_max is None else min(b.stack_max, MAX_QUANTITY)

    def qlvl(self, code):
        return self.t.item.get(code, {}).get('qlvl', 1)

    def max_sockets(self, code, ilvl):
        b = self.data.base(code)
        if not b.max_sockets or b.type < 0 or b.type >= len(self.t.itype):
            return 0
        ms = self.t.itype[b.type]['maxsock']
        cap = ms[0] if ilvl <= 25 else ms[1] if ilvl <= 40 else ms[2]
        return min(b.max_sockets, cap)

    # vanilla (folder profile): the user's rule - up to 7 sockets on weapons, shields, body armor, helms, rings and
    # amulets (not boots / belts / gloves). The save's socket field keeps the base's count (the game clamps it) and
    # item_numsockets (194) gives the rest, as the mock clones do (mxl_mock.MAX_SOCKETS / SOCKET_FIELD).
    VANILLA_SOCKET_TYPES = frozenset(('weap', 'shld', 'tors', 'helm', 'ring', 'amul'))
    VANILLA_MAX_SOCKETS = 7

    @staticmethod
    def _vanilla():
        try:
            import mxl_profile
            return not mxl_profile.is_median()
        except Exception:
            return False

    def socket_limit(self, code, ilvl):
        """Most sockets the editor offers: the base's (max_sockets) in Median, up to 7 on the vanilla rule's types."""
        ms = self.max_sockets(code, ilvl)
        if not self._vanilla() or code not in self.data.bases:
            return ms
        try:
            ok = bool(self.type_codes(code) & self.VANILLA_SOCKET_TYPES)
        except Exception:
            ok = False
        return max(ms, self.VANILLA_MAX_SOCKETS) if ok else ms

    def creator_socket_limit(self, spec):
        """Most sockets the item creator offers for a NEW item. Vanilla: what the game generates - the base's
        sockets at the item level (itemtypes MaxSock) on low / normal / superior / magic items, none on rare,
        crafted, set and unique items (only a quest adds sockets to those). More (up to 7) is a hand edit:
        Specific item edit > Socketing. Median and an item opened with Edit item: socket_limit."""
        code, ilvl = spec['code'], spec['ilvl']
        if not self._vanilla() or spec.get('_from_item') or code not in self.data.bases:
            return self.socket_limit(code, ilvl)
        if spec.get('quality') in ('rare', 'crafted', 'tempered', 'set', 'unique'):
            return 0
        if spec.get('quality') == 'magic':
            return min(self.max_sockets(code, ilvl), 2)      # the server's legit rule: a magic item has up to 2
        return self.max_sockets(code, ilvl)

    def socket_split(self, spec):
        """(save field, item_numsockets 194) for spec['sockets'] in all: the field up to the base's sockets (or the
        edited item's own field), the rest as stat 194. Median: (sockets, 0)."""
        n = spec.get('sockets') or 0
        if not self._vanilla() or spec.get('quality') == 'runeword' or spec.get('code') not in self.data.bases:
            return n, 0
        cap = max(self.max_sockets(spec['code'], spec['ilvl']), spec.get('_sock_field') or 0)
        f = min(n, cap, (1 << socket_field_bits(self.data)) - 1)
        return f, n - f

    def image_count(self, code):
        b = self.data.base(code)
        return len(self.data.itype_gfx[b.type]) if 0 <= b.type < len(self.data.itype_gfx) else 0

    def _val_base(self, code):
        """(validator, row, item type row) of a vanilla base, or None."""
        try:
            import mxl_legit
            v = mxl_legit._validator()
            kind, row = v.bases[code.strip()]
            return v, kind, row, v.item_types.get(row.get('type'), {})
        except Exception:
            return None

    def can_have_quality(self, code, q):
        b = self.data.base(code)
        vb = self._val_base(code) if self._vanilla() and q in ('low', 'superior') else None
        if vb:
            v, kind, row, itype = vb
            from d2bt.itemgen import coerced_quality
            if kind not in ('weapons', 'armor') or coerced_quality(QUALITY_ID[q], row, itype) != QUALITY_ID[q]:
                return False
            return q == 'low' or bool(self.superior_choices(code))
        it = self.t.itype[b.type] if 0 <= b.type < len(self.t.itype) else {}
        if q in ('normal', 'superior'):
            return not it.get('magic_only') and b.kind in ('weapons', 'armor') or (q == 'normal')
        if q == 'magic':
            return not it.get('normal_only')
        if q == 'rare':
            return not it.get('normal_only') and bool(it.get('rare'))
        if q == 'crafted':
            return bool(self.craft_rows(code))
        return True

    def can_roll_affixes(self, code, q):
        """Whether the base can carry the affixes a magic (one or more) / rare (a prefix, a suffix, 3 in all) item
        needs, at the highest item level (quest items, relics... cannot: no affix spawns on them)."""
        cache = self.__dict__.setdefault('_roll_ok', {})
        key = (code, q)
        if key not in cache:
            rare = q == 'rare'
            pre = self.affix_choices('magicprefix', code, self.max_ilvl(), rare=rare)
            suf = self.affix_choices('magicsuffix', code, self.max_ilvl(), rare=rare)
            if rare:
                gp = {a['group'] for _, _, a in pre}
                gs = {a['group'] for _, _, a in suf}
                cache[key] = bool(gp) and bool(gs) and min(len(gp), 3) + min(len(gs), 3) >= 3
            else:
                cache[key] = bool(pre or suf)
        return cache[key]

    def _unique_props(self, spec):
        """Property codes of the unique row of spec (vanilla): from the stock sheet the legit checker reads."""
        try:
            import mxl_legit
            row = mxl_legit._validator().uniques[spec['row']]
            return {row.get(f'prop{i}') for i in range(1, 13)} - {None, ''}
        except Exception:
            return set()

    def ethereal_forced(self, spec):
        """Vanilla: a unique with the 'ethereal' property is always ethereal (the server requires the flag)."""
        return (self._vanilla() and spec.get('quality') == 'unique' and not spec.get('_from_item')
                and 'ethereal' in self._unique_props(spec))

    def max_ilvl(self, spec=None):
        """Highest item level the creator offers: the save's field holds 127 (Median); vanilla: the dev kit's
        ilvl_range (1..110)."""
        if not self._vanilla():
            return MAX_ILVL
        return self.ilvl_bounds(spec)[1]

    def ilvl_bounds(self, spec=None):
        """Vanilla (lo, hi) item level from d2bt ilvl_range (a set / unique row's lvl is the least)."""
        try:
            import mxl_legit
            from d2bt.itemgen import ilvl_range
            v = mxl_legit._validator()
            q = (spec or {}).get('quality')
            row = None
            if spec and spec.get('row') is not None and q in ('unique', 'set'):
                row = (v.uniques if q == 'unique' else v.set_items)[spec['row']]
            code = ((spec or {}).get('code') or '').strip()
            return ilvl_range(v, code, QUALITY_ID.get(q, 2), row) or (1, 110)
        except Exception:
            return (1, 110)

    def crafted_counts(self, ilvl):
        """(fewest, most) random affixes of a crafted item. Median: always 4. Vanilla: the item level sets the
        fewest (1 below 31, 2 from 31, 3 from 51, 4 from 71 - the server's legit rule), 4 at most."""
        if not self._vanilla():
            return CRAFTED_AFFIXES, CRAFTED_AFFIXES
        return (4 if ilvl >= 71 else 3 if ilvl >= 51 else 2 if ilvl >= 31 else 1), CRAFTED_AFFIXES

    def ethereal_ok(self, spec):
        """Whether the item can be ethereal. Vanilla: the validator's rule (d2bt ethereal_allowed: no misc /
        no-durability / quest bases, not low or set, not an indestructible unique unless it authors 'ethereal').
        Median: any item."""
        code = spec.get('code')
        if not self._vanilla() or code not in self.data.bases or spec.get('_from_item'):
            return True
        try:
            import mxl_legit
            from d2bt.itemgen import ethereal_allowed
            v = mxl_legit._validator()
            kind, base = v.bases[code.strip()]
            q = spec.get('quality')
            props = self._unique_props(spec) if q == 'unique' else set()
            return bool(ethereal_allowed(kind, base, 2 if q == 'runeword' else QUALITY_ID.get(q, 2),
                                         indestructible=q == 'unique' and 'indestruct' in props,
                                         authored='ethereal' in props))
        except Exception:
            return False

    def affix_level(self, code, ilvl):
        """The level the game picks affixes at. Vanilla: the item level clamped to 99 and raised to the base's
        qlvl, plus its magic level, else lowered by qlvl / 2 (2 x level - 99 near the top) - the server's legit
        rule (d2bt.legit.affix_level). Median: the item level, as before."""
        if not self._vanilla():
            return ilvl
        it = self.t.item.get(code, {})
        qlvl, magic = it.get('qlvl', 1) or 0, it.get('magic_lvl', 0) or 0
        level = max(min(ilvl, 99), qlvl)
        if magic:
            return min(99, level + magic)
        half = qlvl // 2
        return level - half if level < 99 - half else 2 * level - 99

    def _legal(self, code, ilvl, quality):
        """legal_affixes of the validator for base code (cached): the rows it accepts at ilvl and quality id."""
        cache = self.__dict__.setdefault('_legal_cache', {})
        key = (code, min(ilvl, 99), quality)
        if key not in cache:
            import mxl_legit
            from d2bt.itemgen import legal_affixes
            cache[key] = legal_affixes(mxl_legit._validator(), code.strip(), key[1], quality)
        return cache[key]

    def _affix_ok(self, a, extra, anc, ilvl, rare=False):
        if not a['spawnable'] or a['level'] > ilvl or (a['maxlevel'] and ilvl > a['maxlevel']):
            return False
        if rare and not extra['rare']:
            return False
        return bool(a['itypes'] & anc) and not (a['etypes'] & anc)

    def affix_choices(self, kind, code, ilvl, rare=False):
        """[(save id, label, affix)] of magic prefixes / suffixes that can spawn on this base at this ilvl.
        Vanilla: the validator's legal_affixes."""
        out = []
        if self._vanilla():
            legal = self._legal(code, ilvl, 6 if rare else 4)['prefix' if kind == 'magicprefix' else 'suffix']
            return [(r['id'], self.affix_label(kind, r['id']), self.data.affixes[kind][r['id'] - 1]) for r in legal]
        anc = self.types_of(code)
        ilvl = self.affix_level(code, ilvl)
        for i, a in enumerate(self.data.affixes[kind]):
            if self._affix_ok(a, self.t.affix_extra[kind][i], anc, ilvl, rare):
                out.append((i + 1, self.affix_label(kind, i + 1), a))
        return out

    def _runeword_api_stats(self, spec, rolled):
        """Vanilla runeword stats from the dev kit's runeword_stats (runes.txt mods plus each rune's slot mods):
        a rolled value of the creator's own mod stays when it lies in the range, else the range's maximum."""
        try:
            import mxl_legit
            from d2bt.itemgen import runeword_stats
            v = mxl_legit._validator()
            key = self.rw_string_id(spec['row'])
            if key not in v.runewords:
                key = None
            if key is None:
                return rolled
            api = runeword_stats(v, key, spec['code'].strip(), spec.get('ilvl') or 0)
        except Exception:
            return rolled
        have = {(x['id'], x.get('param')): x['value'] for x in rolled}
        out = []
        for sid, par, lo, hi, src in api:
            if sid >= len(self.data.isc) or not self.data.isc[sid]['bits']:
                continue
            val = have.get((sid, par if self.data.isc[sid]['param'] else None)) if src == 'runeword' else None
            lo, hi = min(lo, hi), max(lo, hi)
            out.append(dict(id=sid, param=par if self.data.isc[sid]['param'] else None,
                            value=val if val is not None and lo <= val <= hi else hi))
        merged = merge_stats(out)
        # the game writes a stat masked to its save bits: ((value + add) & (2^bits - 1)) - add (ignore target defense
        # x3 of Last Wish, 1 bit: saved as 1 - dev kit, item write path; the validator accepts it)
        for x in merged:
            c = self.data.isc[x['id']]
            x['value'] = ((x['value'] + c['add']) & ((1 << c['bits']) - 1)) - c['add']
        return merged

    def mods_text(self, mods, code=None):
        """Tooltip lines of mods [(prop, param, min, max)] as the game writes them, ranges merged:
        "+(31 to 40) to all Attributes", "+(180 to 200)% Enhanced Damage" (affix / recipe / corruption labels)."""
        d = self.data
        lo_d, hi_d = {}, {}
        for p, pa, a, b in mods:
            m = Mod('x', p, pa, a, b, d)
            try:
                if m.variable:
                    m.value = m.min
                    sa = m.stats(d)
                    m.value = m.max
                    sb = m.stats(d)
                else:
                    sa = sb = m.stats(d)
            except Exception:
                continue
            for src, dst in ((sa, lo_d), (sb, hi_d)):
                for x in src:
                    if x['id'] in (S.PREFIX_COUNT, S.SUFFIX_COUNT):
                        continue
                    k = (x['id'], x.get('param'))
                    dst[k] = dst.get(k, 0) + x['value']
        keys = sorted(set(lo_d) | set(hi_d), key=lambda k: (k[0], k[1] or 0))
        lo = [dict(id=k[0], param=k[1], value=lo_d.get(k, 0)) for k in keys]
        hi = [dict(id=k[0], param=k[1], value=hi_d.get(k, 0)) for k in keys]

        class _Ctx:
            pass
        ctx = _Ctx()
        ctx.data, ctx.lo, ctx.hi, ctx.mods = d, lo, hi, list(mods)
        b = d.base(code) if code and code in d.bases else None

        class _B:
            two_handed = bool(getattr(b, 'two_handed', False))
        ctx.base = _B()
        ctx.total = lambda sid: tuple(sum(x['value'] for x in st if x['id'] == sid) for st in (lo, hi))
        try:
            from mxl_catalog_tooltip import catalog_affixes
            lines = [str(t).strip() for line in catalog_affixes(ctx) for _c, t in line]
            return [t for t in lines if t]
        except Exception:
            pass
        try:                                   # fallback: the tooltip at the maximum
            from mxl_tooltip import stat_lines
            return [str(x[1]).strip() for x in stat_lines(hi, d, None) if str(x[1]).strip()]
        except Exception:
            return []

    def affix_label(self, kind, save_id):
        cache = self.__dict__.setdefault('_affix_labels', {})
        if (kind, save_id) not in cache:
            a = self.data.affixes[kind][save_id - 1]
            lines = self.mods_text([(m['prop'], m['param'], m['min'], m['max']) for m in a['mods']])
            cache[(kind, save_id)] = f"{'; '.join(lines) or T('cr.hidden', '(hidden)')}   [L{a['level']}, #{save_id}]"
        return cache[(kind, save_id)]

    def auto_choices(self, code, ilvl, quality=None):
        b = self.data.base(code)
        if not b.auto_group:
            return []
        if self._vanilla():
            legal = self._legal(code, ilvl, 6 if quality in ('rare', 'crafted') else 2)['automagic']
            return [(r['id'], self.affix_label('automagic', r['id']), self.data.affixes['automagic'][r['id'] - 1])
                    for r in legal]
        anc = self.types_of(code)
        out = []
        ilvl = self.affix_level(code, ilvl)
        for i, a in enumerate(self.data.affixes['automagic']):
            if a['group'] == b.auto_group and self._affix_ok(a, self.t.affix_extra['automagic'][i], anc, ilvl, False):
                out.append((i + 1, self.affix_label('automagic', i + 1), a))
        return out

    def superior_choices(self, code):
        vb = self._val_base(code) if self._vanilla() else None
        if vb and vb[0].superior is not None:
            v, _kind, row, itype = vb
            from d2bt.itemgen import superior_candidates
            types = v.save_tables.ancestors(row.get('type')) | v.save_tables.ancestors(row.get('type2'))
            return superior_candidates(v.superior, types, row.get('type'),
                                       no_durability=row.get('nodurability') == '1',
                                       throwable=itype.get('throwable') == '1')
        k = self.data.base(code).kind
        return [i for i, r in enumerate(self.t.superior) if (k == 'weapons' and r['weapon']) or (k == 'armor' and r['armor'])]

    def rare_names_stored(self, names):
        """The save's two 8-bit name fields of (prefix row, suffix row). Median: row + number of suffixes, row.
        Vanilla: the game numbers the rare names from 1 (suffixes first, then the prefixes; 0 = no name), so both
        fields are one higher (the server's legit rule)."""
        a, c = names
        one = 1 if self._vanilla() else 0
        return a + len(self.data.rare_suffix) + one, c + one

    def rare_names_from_stored(self, stored):
        a, b = stored
        one = 1 if self._vanilla() else 0
        return a - len(self.data.rare_suffix) - one, max(0, b - one)

    def rare_name_choices(self, code):
        anc = self.types_of(code)
        res = {}
        for kind in ('rareprefix', 'raresuffix'):
            # the item stores a rare prefix as (its index + number of rare suffixes) in 8 bits: Sigma's last
            # rare prefixes (index + 183 > 255) cannot be saved, so the game cannot give them
            lim = 255 - (len(self.data.rare_suffix) if kind == 'rareprefix' else 0) - (1 if self._vanilla() else 0)
            res[kind] = [(i, self.data.key(n['key'])) for i, n in enumerate(self.t.rare_names[kind])
                         if i <= lim and (n['itypes'] & anc if self._vanilla() else (not n['itypes'] or n['itypes'] & anc))
                         and not (n['etypes'] & anc)]
        return res

    # ---- crafted items (Median XL Sigma: rare / crafted gear + shrine vessel (+ oil), amulets + alchemy oils...)
    def _craft_table(self):
        """Cube recipes whose output is a crafted item: [dict(row, itype, item, inputs, mods)], one per distinct
        (base input, other inputs, mods); a rare or a crafted item as input gives the same recipe."""
        if not hasattr(self, '_crafts'):
            d = self.data
            out, seen = [], set()
            for i, r in enumerate(_rows(d, 'cubemain')):
                if len(r) < 0x4C + 0x54 or not r[0] or r[0x4C + 6] != QUALITY_ID['crafted']:
                    continue
                n_in = r[16]
                ins = [struct.unpack_from('<HHHBB', r, 0x14 + 8 * k) for k in range(min(n_in, 7))]
                ins = [x for x in ins if x[0]]
                if not ins:
                    continue
                fl, item, _iid, _q, _qty = ins[0]
                itype = item if fl & 2 else None
                code = d.item_index[item] if not fl & 2 and 0 <= item < len(d.item_index) else None
                others = []
                for fl2, it2, _a, _b, qty in ins[1:]:
                    if fl2 & 2:
                        others.append(f'type:{it2}')
                    elif 0 <= it2 < len(d.item_index):
                        others.append((d.item_index[it2], max(1, qty)))
                mods = []
                for j in range(5):
                    p, pa, lo, hi, _ch = struct.unpack_from('<iHhhH', r, 0x4C + 24 + 12 * j)
                    if 0 <= p < len(d.props):
                        mods.append((p, pa, lo, hi))
                key = (itype, code, tuple(map(str, others)), tuple(mods))
                if not mods or key in seen:
                    continue
                seen.add(key)
                out.append(dict(row=i, itype=itype, item=code, inputs=others, mods=mods))
            self._crafts = out
            self._craft_by_row = {c['row']: c for c in out}
        return self._crafts

    def craft_recipe(self, row):
        self._craft_table()
        return self._craft_by_row.get(row)

    def craft_label(self, rc):
        d = self.data
        names = []
        for x in rc['inputs']:
            if isinstance(x, tuple):
                code, qty = x
                nm = self.display_name(code).split(' - ')[0] if code in d.bases else code
                names.append(f'{qty} x {nm}' if qty > 1 else nm)
            else:
                t = int(x.split(':')[1])
                names.append(d.itypes[t][0] if 0 <= t < len(d.itypes) else x)
        parts = self.mods_text(rc['mods'])
        return ' + '.join(names or ['(nothing)']) + (': ' + '; '.join(parts) if parts else '')

    def craft_rows(self, code):
        """Rows of the crafting recipes that take this base (cached)."""
        if not code or code not in self.data.bases:
            return []
        cache = self.__dict__.setdefault('_craft_rows', {})
        if code not in cache:
            anc = self.types_of(code)
            cache[code] = [rc['row'] for rc in self._craft_table()
                           if (rc['itype'] is not None and rc['itype'] in anc) or rc['item'] == code]
        return cache[code]

    def craft_choices(self, code):
        """[(recipe row, label)] of the crafting recipes that take this base."""
        labels = self.__dict__.setdefault('_craft_labels', {})
        out = []
        for row in self.craft_rows(code):
            if row not in labels:
                labels[row] = self.craft_label(self.craft_recipe(row))
            out.append((row, labels[row]))
        return out

    # ---- corruption (Median XL Sigma: Sacred / Angelic gear and jewelry + Corrupted Crystal in the cube; a
    # "not revealed yet" corruption is cubed with an Oil of Craft, its hidden roll 1-10000 picks the outcome)
    def reagent_stats(self, code):
        """The stats the game gives a fresh Median XL reagent (gem cluster, rune container, shrine vessel,
        barrel, crate, catalyst...): the mods of the cube recipe that MAKES it - the first enabled cubemain
        row with this base as a normal-quality output (any of the 3 outputs) that does not take the base
        itself as an input (those rows refill it). E.g. Ruby Gem + Oil of Craft -> Ruby Cluster with
        'ac-hth' (Quantity, stat 501) and 'dmg-slash' (stat 377 = the display text: param = string index of
        "Shields: Fire Resist +30% ..."). [] for every other base (no recipe, or the recipe has no mods)."""
        cache = self.__dict__.setdefault('_reagent_stats', None)
        if cache is None:
            d = self.data
            cache = self._reagent_stats = {}
            n_idx = len(d.item_index)
            for r in _rows(d, 'cubemain'):
                if len(r) < 0x4C + 3 * 0x54 or not r[0]:
                    continue
                ins = set()
                for k in range(min(r[16], 7)):
                    fl, it, _q = self._cube_input(r, k)
                    if not fl & 2 and 0 <= it < n_idx:
                        ins.add(d.item_index[it])
                for slot in range(3):
                    o = 0x4C + 0x54 * slot
                    _fl, widx, _wid, post, _qty, btype = struct.unpack_from('<HHHBBB', r, o)
                    if btype != 0xFC or not 0 <= widx < n_idx or post not in (0, QUALITY_ID['normal']):
                        continue
                    out = d.item_index[widx]
                    if out in cache or out in ins or d.base(out).kind != 'misc':
                        continue
                    mods = []
                    for j in range(5):
                        p, pa, lo, hi, _ch = struct.unpack_from('<iHhhH', r, o + 24 + 12 * j)
                        if 0 <= p < len(d.props):
                            mods.append((p, pa, lo, hi))
                    if mods:
                        cache[out] = [s for s in merge_stats(mods_stats(mods, d, 'min')) if d.isc[s['id']]['bits']]
        return [dict(s) for s in cache.get(code, ())]

    def _cube_input(self, r, k):
        fl, item, _iid, q, qty = struct.unpack_from('<HHHBB', r, 0x14 + 8 * k)
        return fl, item, q

    def _cube_match(self, r, code, quality):
        """True if the cube row's first input is this base (type or item code, quality)."""
        d = self.data
        fl, item, q = self._cube_input(r, 0)
        if q and QUALITY_ID.get(quality) != q:
            return False
        if fl & 2:
            return item in self.types_of(code)
        return 0 <= item < len(d.item_index) and d.item_index[item] == code

    def _cube_mods(self, r):
        out = []
        for j in range(5):
            p, pa, lo, hi, _ch = struct.unpack_from('<iHhhH', r, 0x4C + 24 + 12 * j)
            if 0 <= p < len(self.data.props):
                out.append((p, pa, lo, hi))
        return out

    # ---- toggles / upgrades: cube recipes whose output is 'useitem' (input 1 itself, changed in place). Their
    # condition (cubemain op / param / value, plus cubemainext layer and a second op2 / param2 / value2 / layer2)
    # is tested on input 1's stats; their mods add stats (negative values take them away). E.g. Vial of Elder
    # Blood + Token of Absolution: "state 505 >= 1" -> state 505 -1 and the bottom text "(visual aura toggled off)";
    # the paired row does the reverse. Op meanings from D2-Development-Kit (MIT), data/columns/cubemain.json.
    ITEM_OPS = {15: '>=', 16: '<=', 17: '!=', 18: '=', 19: '>=', 20: '<=', 21: '!=', 22: '=',
                23: '>=', 24: '<=', 25: '!=', 26: '='}
    CHAR_OPS = {3: '>=', 4: '<=', 5: '!=', 6: '=', 7: '>=', 8: '<=', 9: '!=', 10: '=',
                11: '>=', 12: '<=', 13: '!=', 14: '='}

    def inplace_recipes(self):
        """Every enabled cube row whose output is input 1 modified in place ('useitem', output type 0xFE) and
        that has mods: [{'row', 'first': (flags, item, unique/set id, quality), 'inputs': [(flags, item, id,
        quality, qty)] of inputs 2+, 'conds': [(op, param, layer, value)], 'mods': [(prop, param, min, max)]}]."""
        cache = self.__dict__.get('_inplace')
        if cache is not None:
            return cache
        d = self.data
        try:
            ext = _rows(d, 'cubemainext')
        except OSError:
            ext = []
        out = []
        for i, r in enumerate(_rows(d, 'cubemain')):
            if len(r) < 0x4C + 0x54 or not r[0] or r[0x4C + 8] != 0xFE:
                continue
            mods = self._cube_mods(r)
            if not mods:
                continue
            chances = [struct.unpack_from('<iHhhH', r, 0x4C + 24 + 12 * j)[4] for j in range(5)
                       if 0 <= struct.unpack_from('<i', r, 0x4C + 24 + 12 * j)[0] < len(d.props)]
            ins = [struct.unpack_from('<HHHBB', r, 0x14 + 8 * k) for k in range(min(r[16], 7))]
            if not ins:
                continue
            conds = []
            op, param, value = r[4], *struct.unpack_from('<ii', r, 8)
            e = struct.unpack_from('<iiiiii', ext[i]) if i < len(ext) and len(ext[i]) >= 24 else (0,) * 6
            if op:
                conds.append((op, param, e[5], value))
            if e[1]:
                conds.append((e[1], e[2], e[4], e[3]))
            out.append(dict(row=i, first=ins[0][:4], inputs=ins[1:], conds=conds, mods=mods, chances=chances))
        self._inplace = out
        return out

    def inplace_for(self, code, quality=None, row=None):
        """The in-place recipes whose input 1 is this item: its base code, its unique / set row (the cube input
        holds row + 1) or one of its item types; the input's quality must match when it names one."""
        if not code:
            return []
        d = self.data
        types = self.types_of(code)
        qid = QUALITY_ID.get(quality)
        out = []
        for rec in self.inplace_recipes():
            fl, item, iid, q = rec['first']
            if q and q != qid:
                continue
            if fl & 0x40 and iid and (row is None or iid - 1 != row or quality not in ('unique', 'set')):
                continue
            if fl & 2:
                if item not in types:
                    continue
            elif not (0 <= item < len(d.item_index) and d.item_index[item] == code):
                continue
            out.append(rec)
        return out

    @staticmethod
    def _cmp(a, how, b):
        return {'>=': a >= b, '<=': a <= b, '!=': a != b, '=': a == b}[how]

    def recipe_applies(self, rec, totals):
        """True if the recipe's item conditions hold for the item's stats {(stat, param or None): value} (a missing
        stat counts as 0). Character / chance / date conditions are not checked here (see recipe_texts)."""
        for op, sid, layer, value in rec['conds']:
            how = self.ITEM_OPS.get(op)
            if how is None:
                continue
            if not self._cmp(totals.get((sid, layer or None), 0), how, value):
                return False
        return True

    def _at(self, mods, how):
        """The mods at their min or max roll. A damage pair (property funcs 15 / 16: the min stat takes the mod's
        min, the max stat its max - "+5-10 damage") is no roll and keeps both ends (collapsed it gave 10-10)."""
        out = []
        for p, pa, lo, hi in mods:
            try:
                pair = any(f in (15, 16) for f in self.data.prop_funcs[p])
            except (IndexError, TypeError):
                pair = False
            v = hi if how == 'max' else lo
            out.append((p, pa, lo, hi) if pair else (p, pa, v, v))
        return out

    def recipe_deltas(self, rec, how='max'):
        """[(stat, param or None, delta)] the recipe's mods make (at the mods' max, or min)."""
        mods = self._at(rec['mods'], how)
        return [(s['id'], s.get('param') or None, s['value'])
                for s in merge_stats(mods_stats(mods, self.data, 'min')) if s['value']]

    def recipe_result(self, rec, totals, how='max'):
        """New {(stat, param): value} after the recipe: the deltas added; a stat that ends at 0 or below is gone."""
        out = dict(totals)
        for sid, pa, v in self.recipe_deltas(rec, how):
            nv = out.get((sid, pa), 0) + v
            if nv > 0 or (nv < 0 and (self.stat_bounds(sid) or (0, 0))[0] < 0):
                out[(sid, pa)] = nv
            else:
                out.pop((sid, pa), None)
        return out

    def stat_label(self, sid, param=None):
        """A short name of a stat (orange text stats: their text)."""
        d = self.data
        if sid == 98 and param:
            return T('cr.tog.state', 'state {n}', n=param)
        if sid in (375, 377, 378, 385) and param:
            try:
                txt = d.s(param)
                if txt:
                    return '"' + _clean_orange(' / '.join(x.strip() for x in txt.splitlines() if x.strip()))[:80] + '"'
            except Exception:
                pass
        nm = dict(self.stat_choices()).get(sid)
        if not nm:
            import mxl_statnames_ext
            nm = mxl_statnames_ext.fallback_label(sid)
        if not nm:
            try:
                nm = (d.isc[sid].get('name') or '').strip()
            except (IndexError, KeyError, TypeError, AttributeError):
                nm = ''
        nm = nm or f'stat #{sid}'
        return f'{nm} ({param})' if param else nm

    def _input_name(self, fl, item, iid, q, qty=0):
        d = self.data
        if fl & 0x40 and iid:
            try:
                src = d.uniques if q == QUALITY_ID['unique'] else d.set_items if q == QUALITY_ID['set'] else None
                if src is not None:
                    nm = d.key(src[iid - 1]['name'])
                    return f'{nm} x{qty}' if qty > 1 else nm
            except Exception:
                pass
        if fl & 2:
            nm = T('cr.tog.any_type', 'any {t}', t=self.type_name(item))
        elif 0 <= item < len(d.item_index):
            nm = self.display_name(d.item_index[item]) or d.item_index[item].strip()
        else:
            nm = f'#{item}'
        if q and q in QUALITY_NAME and not fl & 0x40:
            nm += f' ({QUALITY_NAME[q]})'
        return f'{nm} x{qty}' if qty > 1 else nm

    def type_name(self, t):
        """Name of item type row t: "Shield (shie)"; mxl_rownames.itemtype_name (vanilla itemtypes.txt names, else
        the one base item of that type), else its code."""
        d = self.data
        code = str(d.itypes[t][0]).strip() if 0 <= t < len(d.itypes) else str(t)
        try:
            import mxl_rownames
            nm = mxl_rownames.itemtype_name(d, t, self.display_name)
        except Exception:
            nm = None
        return f'{nm} ({code})' if nm and nm.lower() != code.lower() else code

    def recipe_texts(self, rec):
        """{'inputs': [names of inputs 2+], 'conds': [plain words], 'changes': [plain words]} of an in-place recipe."""
        ins = [self._input_name(*x) for x in rec['inputs']]
        conds = []
        for op, sid, layer, value in rec['conds']:
            if op in self.ITEM_OPS:
                part = {15: '', 16: '', 17: '', 18: ''}.get(op, ' (base)' if op < 23 else ' (bonus)')
                conds.append(T('cr.tog.cond_item', 'when {stat} (stat {sid}){part} {how} {v}',
                               stat=self.stat_label(sid, layer), sid=sid, part=part, how=self.ITEM_OPS[op], v=value))
            elif op in self.CHAR_OPS:
                conds.append(T('cr.tog.cond_char', 'character: {stat} (stat {sid}) {how} {v} (not checked)',
                               stat=self.stat_label(sid, layer), sid=sid, how=self.CHAR_OPS[op], v=value))
            elif op == 37:
                conds.append(T('cr.tog.cond_chance', '{v}% chance', v=value))
            elif op == 27:
                conds.append(T('cr.tog.cond_id', 'unique / set id {v}', v=value))
            elif op in (32, 33):
                conds.append(T('cr.tog.cond_cstate', 'character has state {p} (not checked)', p=sid) if op == 32 else
                             T('cr.tog.cond_cnostate', 'character has not state {p} (not checked)', p=sid))
            elif op in (38, 39, 40, 41):
                who = T('cr.tog.char', 'character') if op < 40 else T('cr.tog.game', 'game')
                conds.append(T('cr.tog.cond_flag', '{who} flag {p} set (not checked)', who=who, p=sid) if op % 2 == 0
                             else T('cr.tog.cond_noflag', '{who} flag {p} not set (not checked)', who=who, p=sid))
            else:
                conds.append(T('cr.tog.cond_other', 'game condition op {op} ({p}, {v}) (not checked)',
                               op=op, p=sid, v=value))
        changes = []
        chances = rec.get('chances') or []
        parts = [(dict(rec, mods=[m]), chances[j] if j < len(chances) else 0) for j, m in enumerate(rec['mods'])] \
            if len(chances) == len(rec['mods']) and any(0 < c < 100 for c in chances) else [(rec, 0)]
        for one, chance in parts:                    # a mod with its own chance column: "(20% chance)"
            for sid, pa, v in self.recipe_deltas(one):
                lab = self.stat_label(sid, pa)
                flag = sid in (98, 375, 377, 378, 385)      # a state / an orange text: on or off
                if flag:
                    txt = (T('cr.tog.removes', 'removes {stat}', stat=lab) if v < 0 else
                           T('cr.tog.adds', 'adds {stat}', stat=lab))
                else:
                    txt = f'{v:+d} {lab}'
                if 0 < chance < 100:
                    txt += ' ' + T('cr.tog.mod_chance', '({n}% chance)', n=chance)
                changes.append(txt)
        lo = self.recipe_deltas(rec, 'min')
        if lo != self.recipe_deltas(rec):
            changes.append(T('cr.tog.rolled', '(rolled; Apply uses the highest roll)'))
        return dict(inputs=ins, conds=conds, changes=changes)

    # ---- honorific items (quality 9, 'tempered' in this code; the game's own strings call it "Honorific")
    def honorific_recipes(self):
        """Cube rows whose output is a quality 9 item: magic / rare weapon or armor + Mark of Infusion ->
        a blank item with a rare-style name, maximum sockets and the recipe's mods ("Orb Effects Applied to this
        Item are Doubled" = stat 289 value 2, plus Physical Resist 0-1% on armor, a weapon bonus on weapons).
        [(row, input item type index, [(prop, param, min, max)])]."""
        if not hasattr(self, '_honorific'):
            out = []
            for i, r in enumerate(_rows(self.data, 'cubemain')):
                if len(r) < 0x4C + 0x54 or not r[0] or r[0x4C + 6] != QUALITY_ID['tempered']:
                    continue
                fl, item, _q = self._cube_input(r, 0)
                if fl & 2:
                    out.append((i, item, self._cube_mods(r)))
            self._honorific = out
        return self._honorific

    def honorific_stats(self, code, how='max'):
        """Stats the honorific recipe gives this base ([] when no recipe takes it), at the mods' min or max."""
        anc = self.types_of(code)
        for _row, itype, mods in self.honorific_recipes():
            if itype in anc:
                return merge_stats(mods_stats(self._at(mods, how), self.data, 'min'))
        return []

    def _corrupt_tables(self):
        """(step rows, reveal rows): cube rows whose 2nd input is the Corrupted Crystal / the Oil of Craft alone."""
        if not hasattr(self, '_corrupt_t'):
            d = self.data
            step, reveal = [], []
            for i, r in enumerate(_rows(d, 'cubemain')):
                if len(r) < 0x4C + 0x54 or not r[0] or r[16] != 2:
                    continue
                fl2, it2, _q2 = self._cube_input(r, 1)
                if fl2 & 2 or not 0 <= it2 < len(d.item_index):
                    continue
                c2 = d.item_index[it2]
                if c2 == 'scum':
                    step.append(i)
                elif c2 == '7o[ ':
                    reveal.append(i)
            self._corrupt_t = (step, reveal)
        return self._corrupt_t

    CORRUPT_CONTROL = (363, 7, 413, 410, 412, 5)     # props: hidden flags / roll / "Corrupted" (added on their own)

    def corrupt_options(self, code, quality, stats=None):
        """[(row, kind, probability, label)] of the corruptions the game can give this item; kind: 'step' (the
        crystal's outcome: no effect, Required Level...), 'pending' (not revealed yet), 'reveal' (an Oil of Craft
        outcome; probability within the reveal). stats: {stat id: value} of the item (conditions of the recipes)."""
        if not code or code not in self.data.bases or quality in ('tempered', 'runeword'):
            return []
        stats = stats or {}
        key = (code, quality, tuple(sorted((k, v) for k, v in stats.items() if k in (372, 92, 494, 496, 497))))
        cache = self.__dict__.setdefault('_corrupt_opts', {})
        if key in cache:
            return cache[key]
        rows = _rows(self.data, 'cubemain')
        step, reveal = self._corrupt_tables()
        out, left, pending = [], 1.0, False
        for i in step:
            r = rows[i]
            if not self._cube_match(r, code, quality):
                continue
            op = r[4]
            param, value = struct.unpack_from('<ii', r, 8)
            mods = self._cube_mods(r)
            if op == 37:                                     # random: value % of what is left
                pct = max(0, min(100, value)) / 100.0
                if pct <= 0:
                    continue
                pr = left * pct
                left -= pr
                kind = 'pending' if any(m[0] == 410 for m in mods) else 'step'
                pending = pending or kind == 'pending'
                out.append((i, kind, pr, mods))
                if left <= 1e-9:
                    break
                continue
            if op == 18:
                cond = stats.get(param, 0) == value
            elif op == 15:
                cond = stats.get(param, 0) > value
            elif op == 0:
                cond = True
            else:
                cond = False
            if cond and not mods:
                break                                        # the game refuses this item
        if pending:
            last = 0
            for i in reveal:
                r = rows[i]
                if r[4] != 16 or not self._cube_match(r, code, quality):
                    continue
                param, value = struct.unpack_from('<ii', r, 8)
                if param != 498 or value <= last or value > 10000:
                    continue
                out.append((i, 'reveal', (value - last) / 10000.0, self._cube_mods(r)))
                last = value
        res = []
        for i, kind, pr, mods in out:
            shown = [m for m in mods if m[0] not in self.CORRUPT_CONTROL]
            txt = '; '.join(self.mods_text(shown)) if shown else ''
            pct = f'{pr * 100:.4g}%'
            if kind == 'pending':
                lab = T('cr.cor.pending', 'Corrupted, not revealed yet (cube it with an Oil of Craft) ({p})', p=pct)
            elif kind == 'reveal':
                lab = T('cr.cor.reveal', 'Corrupted: {text} ({p} of the reveals)', text=txt or '?', p=pct)
            elif any(m[0] == 5 for m in mods):
                lab = (T('cr.cor.step', 'Corrupted: {text} ({p})', text=txt, p=pct) if txt
                       else T('cr.cor.plain', 'Corrupted, no effect ({p})', p=pct))
            else:
                lab = T('cr.cor.failed', 'Not corrupted: {text} ({p})', text=txt or '?', p=pct)
            res.append((i, kind, pr, lab))
        cache[key] = res
        return res

    def corrupt_choices(self, spec):
        """corrupt_options of the spec's item (conditions checked on its stats without corruption)."""
        q = spec.get('quality')
        if q == 'crafted' or q == 'rare' or q in QUALITY_ID:
            qq = q
        else:
            return []
        stats = {}
        for m in self.mods(dict(spec, corrupt=None)):
            try:
                for x in m.stats(self.data):
                    stats[x['id']] = stats.get(x['id'], 0) + x['value']
            except Exception:
                pass
        for x in spec.get('extra') or []:
            stats[x['id']] = stats.get(x['id'], 0) + x['value']
        return self.corrupt_options(spec.get('code'), qq, stats)

    def corrupt_mods(self, spec):
        """[(prop, param, min, max)] the corruption of the spec adds (the "Corrupted" mark included)."""
        row = spec.get('corrupt')
        if row is None:
            return []
        rows = _rows(self.data, 'cubemain')
        if not 0 <= row < len(rows):
            return []
        mods = self._cube_mods(rows[row])
        mark = any(m[0] in (5, 412) for m in mods) or row in self._corrupt_tables()[1]
        out = [(5, 0, 1, 1)] if mark else []
        if any(m[0] == 410 for m in mods):                  # not revealed: the flag and the hidden roll
            roll = spec.get('corrupt_roll') or 1
            out += [(413, 0, 1, 1), (410, 1, roll, roll)]
        out += [m for m in mods if m[0] not in self.CORRUPT_CONTROL]
        return out

    def _corrupt_stats(self, spec):
        d = self.data
        out = {}
        for p, pa, lo, hi in self.corrupt_mods(spec):
            for x in Mod('c', p, pa, lo, hi, d).stats(d):
                k = (x['id'], x.get('param'))
                out[k] = out.get(k, 0) + x['value']
        return out

    def _check_rare_affixes(self, code, ilvl, pre, suf):
        d = self.data
        groups = set()
        for kind, lst in (('magicprefix', pre), ('magicsuffix', suf)):
            ok = {i for i, _, _ in self.affix_choices(kind, code, ilvl, rare=True)}
            for sid in lst:
                if sid not in ok:
                    raise CreateError(T('cr.err.affix_level', 'an affix cannot spawn on this item at this item level'))
                g = d.affixes[kind][sid - 1]['group']
                if g and (kind, g) in groups:
                    raise CreateError(T('cr.err.same_group', 'two affixes of the same group'))
                groups.add((kind, g))

    def _pick_affixes(self, kind, code, ilvl, n, taken=()):
        """n random rare affixes of one kind (weighted by the game's frequency, one per group)."""
        d = self.data
        groups = {d.affixes[kind][x - 1]['group'] for x in taken}
        out = list(taken)
        pool = [(i, a) for i, _, a in self.affix_choices(kind, code, ilvl, rare=True)]
        while len(out) < n:
            cand = [(i, a) for i, a in pool if i not in out and (not a['group'] or a['group'] not in groups)]
            if not cand:
                break
            w = [max(1, self.t.affix_extra[kind][i - 1]['freq']) for i, _ in cand]
            i, a = random.choices(cand, weights=w)[0]
            out.append(i)
            groups.add(a['group'])
        return out

    def reroll_crafted(self, spec):
        """A new random crafted item on the same base and recipe: name, 4 affixes, every value (a roll whose
        values the save cannot hold, e.g. Enhanced Damage over its limit, is rolled again)."""
        for _ in range(40):
            self._reroll_crafted(spec)
            try:
                self.build(spec)
                return spec
            except CreateError as e:
                if not isinstance(e, StoreError):
                    return spec
        return spec

    def _reroll_crafted(self, spec):
        code, ilvl = spec['code'], spec['ilvl']
        names = self.rare_name_choices(code)
        spec['rare_names'] = (random.choice(names['rareprefix'])[0] if names['rareprefix'] else 0,
                              random.choice(names['raresuffix'])[0] if names['raresuffix'] else 0)
        n_pre = random.randint(max(1, CRAFTED_AFFIXES - 3), min(3, CRAFTED_AFFIXES - 1))
        spec['rare_prefixes'] = self._pick_affixes('magicprefix', code, ilvl, n_pre)
        spec['rare_suffixes'] = self._pick_affixes('magicsuffix', code, ilvl, CRAFTED_AFFIXES - len(spec['rare_prefixes']))
        if len(spec['rare_suffixes']) < CRAFTED_AFFIXES - len(spec['rare_prefixes']):   # few suffixes: more prefixes
            spec['rare_prefixes'] = self._pick_affixes('magicprefix', code, ilvl,
                                                       CRAFTED_AFFIXES - len(spec['rare_suffixes']), spec['rare_prefixes'])
        spec['rolls'] = {}
        self.roll(spec, 'random')
        return spec

    def _visible(self, st):
        """True if the stat shows a tooltip line on its own."""
        try:
            from mxl_tooltip import stat_lines
            return any(str(x[1] if isinstance(x, (tuple, list)) else x).strip()
                       for x in stat_lines([st], self.data, None))
        except Exception:
            return True

    def _infer_affixes(self, it, code, ilvl, leftover):
        """Rare affixes that explain the stats of an item saved without its affix ids (e.g. an imported copy):
        greedy, the affix whose shown stats are all on the item within its range, most stats first; the
        "Prefixes: n / Suffixes: n" counters of the item give how many of each."""
        d = self.data
        have = {}
        for x in leftover:
            k = (x['id'], x.get('param'))
            have[k] = have.get(k, 0) + x['value']
        want = {'magicprefix': have.get((S.PREFIX_COUNT, None)), 'magicsuffix': have.get((S.SUFFIX_COUNT, None))}
        if want['magicprefix'] is None and want['magicsuffix'] is None:
            want = {'magicprefix': 3, 'magicsuffix': 3}
        want = {k: min(3, v or 0) for k, v in want.items()}
        cache = {}

        def ranges(kind, a):
            key = (kind, id(a))
            if key not in cache:
                try:
                    mods = [(m['prop'], m['param'], m['min'], m['max']) for m in a['mods']]
                    lo = {(x['id'], x.get('param')): x['value'] for x in layered_stats(mods, d, 'min')}
                    hi = {(x['id'], x.get('param')): x['value'] for x in layered_stats(mods, d, 'max')}
                    vis = {k for k in set(lo) | set(hi) if k[0] not in (S.PREFIX_COUNT, S.SUFFIX_COUNT)
                           and self._visible(dict(id=k[0], param=k[1], value=hi.get(k, lo.get(k, 1)) or 1))}
                    cache[key] = (lo, hi, vis)
                except Exception:
                    cache[key] = None
            return cache[key]

        chosen = {'magicprefix': [], 'magicsuffix': []}
        groups = set()
        while sum(len(v) for v in chosen.values()) < CRAFTED_AFFIXES:
            best = None
            for kind in ('magicprefix', 'magicsuffix'):
                if len(chosen[kind]) >= want[kind]:
                    continue
                for i, _, a in self.affix_choices(kind, code, ilvl, rare=True):
                    if a['group'] and (kind, a['group']) in groups:
                        continue
                    r = ranges(kind, a)
                    if not r or not r[2]:
                        continue
                    lo, hi, vis = r
                    ok, score = True, 0.0
                    for k in vis:
                        v = have.get(k)
                        x, y = sorted((lo.get(k, 0), hi.get(k, 0)))
                        if v is None or (v < x if x >= 0 else v > y) or (v > 0 > x):
                            ok = False
                            break
                        score += 3 + (1 if x <= v <= y else 0)
                    if ok and (best is None or score > best[0]):
                        best = (score, kind, i, a, lo, hi, vis)
            if best is None:
                break
            _sc, kind, i, a, lo, hi, vis = best
            chosen[kind].append(i)
            groups.add((kind, a['group']))
            for k in vis:
                x, y = sorted((lo.get(k, 0), hi.get(k, 0)))
                take = max(x, min(y, have[k]))
                have[k] -= take
                if not have[k]:
                    del have[k]
        return chosen['magicprefix'], chosen['magicsuffix']

    def sockets_fillers(self):
        """Gems and runes (simple socketables with gem bonuses), as (code, name)."""
        out = []
        for code in self.data.gems:
            b = self.data.base(code)
            if b.name and self.t.item.get(code, {}).get('compact'):
                out.append((code, b.name))
        return sorted(out, key=lambda x: x[1].lower())

    # ---- raw (unrestricted) stat editing
    def stat_bounds(self, sid):
        """(lo, hi) of what the save format can hold for a stat (ItemStatCost save bits / add), or None when
        the stat has no storage: the whole range the game's file format gives, not the game's own ranges."""
        try:
            ic = self.data.isc[sid]
            if not ic.get('bits'):
                return None
        except (IndexError, KeyError, TypeError):
            return None
        add = ic.get('add') or 0
        return -add, (1 << ic['bits']) - 1 - add

    def storage_range(self, m):
        """(lo, hi) a value of one variable mod can take and stay storable (its direct stat's ItemStatCost
        bits / add), or None when the mod's value is not one stat's value (damage pairs, per-level...)."""
        d = self.data
        try:
            a = {(x['id'], x.get('param')): x['value'] for x in mods_stats([(m.prop, m.param, m.min, m.min)], d, 'min')}
            b = {(x['id'], x.get('param')): x['value'] for x in mods_stats([(m.prop, m.param, m.max, m.max)], d, 'min')}
            ks = [k for k in a if k in b and a[k] == m.min and b[k] == m.max]
            if len(ks) != 1:
                return None
            return self.stat_bounds(ks[0][0])
        except Exception:
            return None

    def stat_choices(self):
        """[(stat id, label)] of every stat the save format can hold, sorted by name: the list of the editor's
        raw stat rows (unrestricted mode). Labels use the stat's tooltip text at value 1."""
        cache = self.__dict__.get('_stat_choices')
        if cache is None:
            from mxl_profile import is_median

            d = self.data
            out = []
            for sid in range(0x1FF):                   # the save stores a 9-bit stat id, 0x1FF is the end mark
                try:
                    ic = d.isc[sid]
                    bits = ic.get('bits')
                except (IndexError, KeyError, TypeError):
                    continue
                if not bits:
                    continue
                txt = generic_label(sid) if is_median() else None  # the game's string names ONE param value: the neutral name
                if not txt:
                    try:
                        txt = stat_text(d, sid, None, value=1, desc=ic.get('desc'))
                    except Exception:
                        txt = ''
                if not txt:
                    import mxl_statnames_ext
                    txt = mxl_statnames_ext.fallback_label(sid)
                out.append((sid, txt or f'(stat #{sid})'))          # clean labels: no id / bits / param numbers
                # (the picker's status shows the picked stat's numbers when one is picked)
            # the game gives several stats the same tooltip text (e.g. the chance-to-cast stats 192 and
            # 196 both read '%d%% Chance to cast level %d %s on Kill'): picking by text must stay
            # deliberate, so the later duplicates are marked ' (2)', ' (3)'... and among identical
            # labels the stats with a skill param (the ones with a skill dropdown) come first
            groups = {}
            for sid, lab in out:
                groups.setdefault(lab.casefold(), []).append(sid)
            labelled = {}
            for sids in groups.values():
                if len(sids) > 1:
                    order = sorted(sids, key=lambda s: (0 if param_kind(s) else 1, s))
                    texts = dict(out)
                    labelled[order[0]] = texts[order[0]]
                    for n, s in enumerate(order[1:], 2):
                        labelled[s] = f'{texts[s]} ({n})'
                else:
                    labelled[sids[0]] = dict(out)[sids[0]]
            out = [(sid, labelled[sid]) for sid, _t in out]
            cache = self._stat_choices = sorted(out, key=lambda x: (x[1].lower(), x[0]))
        return cache

    def orange_texts(self):
        """Every orange text the game draws on items, with the hidden markers and the paired effect
        stats the game's own sources write alongside it: [{'label', 'display', 'hidden', 'effects',
        'skilldesc'}], sorted by label.
        'display' goes into the item's own stat list as-is (id / param / value); 'hidden' is the list of
        hidden-marker options the data co-occurs with this exact display entry (each option
        {'id', 'param', 'value', 'label'}); 'effects' are the MECHANIC stats of the same source row - the
        real attributes that make the text true (an oskill grant, a stance counter, the companion text
        block), each {'id', 'param', 'value', 'label'} with the value the game's own row writes.
        'skilldesc' True for the proc stats, whose display IS the
        hidden effect (the param picks which skill proc it names).

        Four string stats carry orange text (param = string-table id, value set by the source row):        - 385 desc_orange: the uniques' orange flavor text (48 via prop 156);
        - 375 desc_top: the top text block (374 uniques + 2 set items + 50 runewords + 3 magic suffixes
          + 18 automagic);
        - 377 desc_bottom: the bottom block (131 uniques + 1 runeword);
        - 378 desc_less_top: the secondary top block (32 uniques + 1 automagic).
        The proc stats (200 Mega Impact, 260 Thunderfury, 266/277 Area Effect Attack, 371 Amazing Grace)
        and the plain orange flags (257 Vessel mod, 288 Blood Hatred, 418 Black Road upgrade) come from
        the same scan of every source table (uniques, set items, runewords, affixes)."""
        cache = self.__dict__.get('_orange_texts')
        if cache is not None:
            return cache
        d = self.data
        DISPLAY = (385, 375, 377, 378, 200, 260, 266, 277, 371, 257, 288, 418)
        MARKERS = (490, 491, 492, 493, 494, 478, 450, 473)
        PROC = (200, 260, 266, 277, 371)
        # the stats the game pairs with an orange text to MAKE IT TRUE (proven from the game's own
        # rows): 151 is THE hidden-mechanic stat (param = mechanic id, value = level: auras, stances,
        # morphs - Khazra Plate's Demon Blood aura is 151/1900/1), 97/383/393 grant oskills, 98 sets a
        # state, 411/450/452-455 are the counters that ride along. Everything else in a carrier row is
        # that item's own mods, not part of the text's effect.
        MECH = (97, 98, 151, 383, 393, 411, 450, 452, 453, 454, 455)
        hidden_names = self._marker_names(MARKERS)
        choices = dict(self.stat_choices())            # the named stats the save format can hold

        def stat_name(sid):
            nm = choices.get(sid)
            if nm:
                return nm
            import mxl_statnames_ext
            return mxl_statnames_ext.fallback_label(sid) or f'stat #{sid}'

        def stats_of(mods):
            """[(stat, param, value)] of a source row's mods: every stat, display and effect alike."""
            out = []
            for m in mods or []:
                for s, f in zip(d.props[m['prop']], d.prop_funcs[m['prop']]):
                    if s >= 0 and f == 11:      # "on event" (the procs): param = skill << 6 | level (max), value = min
                        out.append((s, ((m['param'] or 0) << 6) | ((m.get('max') or 1) & 63), m['min']))
                    elif s >= 0:
                        out.append((s, m['param'], m['min']))
            return out

        found = {}      # (stat, param, value) -> {'labels': set(), 'markers': set(), 'effects': set()}
        for rows in (self.uniques_source(), self.set_source(), self.runeword_source(),
                     self.affix_sources(), self.cube_source()):
            for row in rows:
                sts = stats_of(row)
                disp = [x for x in sts if x[0] in DISPLAY]
                if not disp:
                    continue
                hid = [x for x in sts if x[0] in MARKERS]
                for x in disp:
                    e = found.setdefault(x, {'labels': set(), 'markers': set(), 'effects': set()})
                    for h in hid:
                        e['markers'].add(h)
                    for o in sts:
                        if (o[0], o[1]) == (x[0], x[1]) or o[0] in MARKERS:
                            continue         # the text itself, and the hidden dropdown's markers
                        if o[0] in MECH or o[0] in DISPLAY:   # the mechanic + companion text blocks
                            e['effects'].add(o)

        out = []
        for (sid, param, val), e in sorted(found.items()):
            if sid in PROC:
                try:
                    ic = d.isc[sid]
                except (IndexError, KeyError, TypeError):
                    continue
                desc = _clean_orange(ic.get('desc') or f'(stat #{sid})')
                import mxl_statnames                  # param = skill << 6 | level (an "on event" packing)
                sk = mxl_statnames.skill_label(d, param >> 6) or f'skill #{param >> 6}'
                label = f'{desc} (skill: {sk}, level {param & 63})'
                out.append(dict(label=label, display=dict(id=sid, param=param, value=val),
                                hidden=[], effects=[], skilldesc=True))
                continue
            if sid in (257, 288, 418):
                try:
                    ic = d.isc[sid]
                except (IndexError, KeyError, TypeError):
                    continue
                desc = _clean_orange((ic.get('desc') or f'(stat #{sid})').splitlines()[0])
                out.append(dict(label=f'{desc} (flag)', display=dict(id=sid, param=None, value=val),
                                hidden=[], effects=[], skilldesc=False))
                continue
            try:
                txt = d.s(param)
            except Exception:
                txt = None
            if not txt:
                continue
            label = _clean_orange(' / '.join(part.strip() for part in txt.splitlines()
                                             if part.strip()))[:200]
            hidden = []
            for (hs, hp, hv) in sorted(e['markers']):
                name = hidden_names.get(hs) or f'stat #{hs}'
                hidden.append(dict(id=hs, param=hp if hp else None, value=hv,
                                   label=f'{name} (param {hp}, value {hv})'))
            effects = []
            for (es, ep, ev) in sorted(e['effects']):
                nm = stat_name(es)
                effects.append(dict(id=es, param=ep if ep else None, value=ev,
                                    label=f'{nm} (param {ep}, value {ev})' if ep else f'{nm} = {ev}'))
            out.append(dict(label=label, display=dict(id=sid, param=param, value=val),
                            hidden=hidden, effects=effects, skilldesc=False))
        cache = self._orange_texts = sorted(out, key=lambda t: t['label'].lower())
        return cache

    def uniques_source(self):
        """[mods] of every unique row."""
        return [u['mods'] for _i, _n, u in self.uniques()]

    def set_source(self):
        """[mods] of every set-item row."""
        return [r['mods'] for r in self.data.set_items]

    def cube_source(self):
        """[mods] of every enabled cube recipe output (3 outputs per row): the orange texts and effects the
        recipes add (the reagents' 377 text, Vial of Elder Blood's text + the 20% voidtouched state 98/505).
        Mods with a value <= 0 are left out (those rows take a stat away)."""
        out = []
        for r in _rows(self.data, 'cubemain'):
            if len(r) < 0x4C + 3 * 0x54 or not r[0]:
                continue
            for slot in range(3):
                mods = []
                for j in range(5):
                    p, pa, lo, _hi, _ch = struct.unpack_from('<iHhhH', r, 0x4C + 0x54 * slot + 24 + 12 * j)
                    if 0 <= p < len(self.data.props) and lo > 0:
                        mods.append({'prop': p, 'param': pa, 'min': lo})
                if mods:
                    out.append(mods)
        return out

    def runeword_source(self):
        """[mods] of every runeword row."""
        return list(self.data.runeword_mods)

    def affix_sources(self):
        """[mods] of every affix row (magic prefix / suffix / automagic)."""
        out = []
        for v in self.data.affixes.values():
            out.extend(r['mods'] for r in v)
        return out

    def _marker_names(self, sids):
        """{stat id: label} of the hidden-marker stats (from the editor's own fallback names)."""
        import mxl_statnames_ext
        out = {}
        for sid in sids:
            try:
                ic = self.data.isc[sid]
            except (IndexError, KeyError, TypeError):
                continue
            txt = None
            try:
                txt = stat_text(self.data, sid, None, value=1, desc=ic.get('desc'))
            except Exception:
                pass
            out[sid] = txt or mxl_statnames_ext.fallback_label(sid) or f'hidden stat #{sid}'
        return out

    # ---- building
    def new_spec(self, quality, code=None, row=None):
        """Default spec. quality: normal, superior, magic, rare, set, unique, runeword."""
        spec = dict(quality=quality, code=code, row=row, ilvl=None, ethereal=False, sockets=0,
                    socketed=[], image=None, auto=None, superior=None, prefix=None, suffix=None,
                    rare_names=None, rare_prefixes=[], rare_suffixes=[], quantity=None, defense=None,
                    rolls={}, craft=None, extra=[], corrupt=None, corrupt_roll=None, max_sockets=False)
        if quality == 'unique':
            spec['code'] = self.data.uniques[row]['code']
        elif quality == 'set':
            spec['code'] = self.data.set_items[row]['code']
        spec['ilvl'] = self.min_ilvl(spec)
        return spec

    def min_ilvl(self, spec):
        lv = max(1, self.qlvl(spec['code']) if spec['code'] else 1)
        if spec['quality'] == 'unique':
            lv = max(lv, self.data.uniques[spec['row']]['level'])
        elif spec['quality'] == 'set':
            lv = max(lv, self.data.set_items[spec['row']]['level'])
        if self._vanilla():
            lv = max(lv, self.ilvl_bounds(spec)[0])
        return min(lv, self.max_ilvl(spec))

    def mods(self, spec):
        """[Mod] of the spec, in display order; rolled values taken from spec['rolls'] (key -> value)."""
        d = self.data
        out = []
        q = spec['quality']
        if spec.get('auto'):
            for k, m in enumerate(d.affixes['automagic'][spec['auto'] - 1]['mods']):
                out.append(Mod(f'auto:{spec["auto"]}:{k}', m['prop'], m['param'], m['min'], m['max'], d, 'Innate'))
        if q in ('superior', 'runeword') and spec.get('superior') is not None:
            for k, m in enumerate(d.quality_mods[spec['superior']]):
                out.append(Mod(f'sup:{k}', m['prop'], m['param'], m['min'], m['max'], d, 'Superior'))
        if q == 'magic':
            for kind, key in (('magicprefix', 'prefix'), ('magicsuffix', 'suffix')):
                if spec.get(key):
                    for k, m in enumerate(d.affixes[kind][spec[key] - 1]['mods']):
                        out.append(Mod(f'{key}:{spec[key]}:{k}', m['prop'], m['param'], m['min'], m['max'], d,
                                       'Prefix' if key == 'prefix' else 'Suffix'))
        if q in ('rare', 'crafted'):
            for kind, key in (('magicprefix', 'rare_prefixes'), ('magicsuffix', 'rare_suffixes')):
                for n, sid in enumerate(spec.get(key) or []):
                    for k, m in enumerate(d.affixes[kind][sid - 1]['mods']):
                        out.append(Mod(f'{key}:{n}:{sid}:{k}', m['prop'], m['param'], m['min'], m['max'], d,
                                       'Prefix' if kind == 'magicprefix' else 'Suffix'))
        if q in ('unique', 'set'):
            row = (d.uniques if q == 'unique' else d.set_items)[spec['row']]
            for k, m in enumerate(row['mods']):
                out.append(Mod(f'{q}:{spec["row"]}:{k}', m['prop'], m['param'], m['min'], m['max'], d))
        if q == 'crafted' and spec.get('craft') is not None:
            rc = self.craft_recipe(spec['craft'])
            if rc:
                for k, (p, pa, lo, hi) in enumerate(rc['mods']):
                    out.append(Mod(f'craft:{spec["craft"]}:{k}', p, pa, lo, hi, d, 'Crafting'))
        if q == 'runeword':
            for k, m in enumerate(d.runeword_mods[spec['row']]):
                out.append(Mod(f'rw:{spec["row"]}:{k}', m['prop'], m['param'], m['min'], m['max'], d, 'Runeword'))
        for k, (p, pa, lo, hi) in enumerate(self.corrupt_mods(spec)):
            m = Mod(f'corrupt:{spec["corrupt"]}:{k}', p, pa, lo, hi, d, 'Corruption')
            m.variable, m.value = False, None                 # fixed values (the hidden roll included)
            out.append(m)
        self._fit_storage(out)
        for m in out:
            if m.variable and m.source in spec['rolls']:
                m.value = spec['rolls'][m.source]
        if spec.get('unrestricted'):                          # free mode: every mod's value is taken as set
            for m in out:
                m.free = True
        for m in out:
            m.ilvl = spec.get('ilvl') or 99      # charged skills: level and charges follow the item level (vanilla)
        return out

    def _fit_storage(self, mods):
        """Narrows mod ranges to what the item can store: a stat is saved in a fixed number of bits
        (ItemStatCost save bits / add), and a value outside cannot exist on a game item (Sigma rows that ask more:
        Alnair / Thelema "to Summon Attack Rating" up to 200 / 180 of 155, Spire of Kehjan 250 Damage Reflected of
        155, a Halberd suffix +33 to a skill of 30, Ring of Woe's corruption roll 1 + 10000 of 10000). Mods adding
        to the same stat share the room (the runeword's own stat list is separate)."""
        d = self.data
        info, fixed = [], {}
        for m in mods:
            prop, param, lo, hi = m.raw
            if any(f in (15, 16, 17) for f in d.prop_funcs[prop]):
                info.append(None)                            # given as such: a fixed share of the room
                try:
                    for x in m.stats(d):
                        key = (m.source.startswith('rw:'), (x['id'], x.get('param')))
                        fixed[key] = fixed.get(key, 0) + x['value']
                except Exception:
                    pass
                continue
            try:
                a = {(x['id'], x.get('param')): x['value'] for x in layered_stats([(prop, param, m.min, m.min)], d, 'min')}
                b = {(x['id'], x.get('param')): x['value'] for x in layered_stats([(prop, param, m.max, m.max)], d, 'min')}
            except Exception:
                info.append(None)
                continue
            # stats whose value is the mod's value itself (others: per-level, damage pairs...: left alone)
            info.append([k for k in a if k in b and a[k] == m.min and b[k] == m.max])
        groups = {}
        for m, ks in zip(mods, info):
            for k in ks or []:
                groups.setdefault((m.source.startswith('rw:'), k), []).append(m)
        for (_rw, k), ms in groups.items():
            ic = d.isc[k[0]]
            if not ic['bits']:
                continue
            lo_s, hi_s = -ic['add'], (1 << ic['bits']) - 1 - ic['add']
            f = fixed.get((_rw, k), 0)
            lo_s, hi_s = lo_s - f, hi_s - f
            tot_lo = sum(m.min for m in ms)
            tot_hi = sum(m.max for m in ms)
            if lo_s <= tot_lo and tot_hi <= hi_s:
                continue
            for m in ms:
                others_lo = tot_lo - m.min
                others_hi = tot_hi - m.max
                lo_a, hi_a = lo_s - others_hi, hi_s - others_lo
                # both ends into [lo_a, hi_a]: a fixed value below the range (Athame's Light Radius -6 of -5..250,
                # read since all 13 rune slots are) becomes the nearest storable value, not left as it was
                nmin = min(max(m.min, lo_a), hi_a)
                nmax = max(min(m.max, hi_a), lo_a)
                nmin = min(nmin, nmax)
                if (nmin, nmax) == (m.min, m.max):
                    continue
                tot_lo += nmin - m.min
                tot_hi += nmax - m.max
                m.min, m.max = nmin, nmax
                prop, param, lo, hi = m.raw
                m.raw = (prop, param, nmin, nmax) if lo <= hi else (prop, param, nmax, nmin)
                m.variable = m.variable and nmin != nmax
                if m.value is not None:
                    m.value = max(nmin, min(nmax, m.value))
                if not m.variable:
                    m.value = None

    def roll(self, spec, how='random'):
        """Fills spec['rolls'] for every variable mod: 'random', 'max', 'min' or 'mid'."""
        for m in self.mods(spec):
            if m.variable:
                spec['rolls'][m.source] = (random.randint(m.min, m.max) if how == 'random' else
                                           m.max if how == 'max' else m.min if how == 'min' else (m.min + m.max) // 2)

    def defense_range(self, spec):
        """(lo, hi) of the base defense, or (v, v) when fixed (Enhanced Defense: max + 1), before ethereal."""
        t = self.t.item.get(spec['code'], {})
        lo, hi = t.get('minac', 0), t.get('maxac', 0)
        if any(s['id'] == S.ENH_DEFENSE for m in self.mods(spec) for s in m.stats(self.data)):
            return hi + 1, hi + 1
        return lo, hi

    def innate_sockets(self, spec):
        """Sockets the item's affixes give ("sock" property, e.g. the Angelic innate +6), as the game makes them:
        capped at the base's maximum for the item level."""
        try:
            n = sum(s['value'] for m in self.mods(spec) for s in m.stats(self.data) if s['id'] == NUM_SOCKETS)
        except Exception:
            return 0
        return min(n, self.max_sockets(spec['code'], spec['ilvl'])) if n > 0 else 0

    def validate(self, spec):
        """Raises CreateError if the spec is not something the game could generate. An item opened with Edit item
        that breaks a rule (hacked / outside values, Sigma upgrades the rules don't know) is allowed: the problem is
        kept in spec['_warning'] instead."""
        spec.pop('_warning', None)
        if spec.get('code') in self.data.bases and spec.get('ilvl') and spec.get('quality') != 'runeword':
            n = self.innate_sockets(spec)
            if n > (spec.get('sockets') or 0):
                spec['sockets'] = n               # the game gives them: the item always has at least these
        if spec.get('_from_item') and spec.get('code') in self.data.bases:
            try:
                self._validate(spec)
            except CreateError as e:
                spec['_warning'] = str(e)
            return
        self._validate(spec)

    def _validate(self, spec):
        d, q, code = self.data, spec['quality'], spec['code']
        if not code or code not in d.bases:
            raise CreateError(T('cr.err.base', 'choose a base item'))
        b = d.base(code)
        ilvl = spec['ilvl']
        if not self.min_ilvl(spec) <= ilvl <= self.max_ilvl(spec):
            raise CreateError(T('cr.err.ilvl', 'item level must be {lo} to {hi}', lo=self.min_ilvl(spec), hi=self.max_ilvl(spec)))
        qq = 'normal' if q == 'runeword' else q
        if qq in ('normal', 'superior', 'magic', 'rare') and not self.can_have_quality(code, qq):
            raise CreateError(T('cr.err.quality', '{base} cannot be {quality}', base=b.name, quality=T(f'cr.quality.{qq}', qq)))
        if spec.get('ethereal') and not self.ethereal_ok(spec):
            raise CreateError(T('cr.err.ethereal', '{base} cannot be ethereal', base=b.name))
        if self.ethereal_forced(spec) and not spec.get('ethereal'):
            raise CreateError(T('cr.err.ethereal_forced', '{base} is always ethereal', base=b.name))
        ms = self.socket_limit(code, ilvl) if q != 'runeword' else self.max_sockets(code, ilvl)
        if spec['sockets'] > ms:
            raise CreateError(T('cr.err.max_sockets', '{base} can have at most {n} socket(s) at item level {ilvl}', base=b.name, n=ms, ilvl=ilvl))
        if len(spec['socketed']) + len(spec.get('_added') or ()) > spec['sockets']:
            raise CreateError(T('cr.err.too_many_socketed', 'more socketed items than sockets'))
        autos = [a for a, _, _ in self.auto_choices(code, ilvl, q)]
        # Median XL Sigma: uniques and set items get their base's innate (automagic) affix too, like the game's
        # own (e.g. Azurewrath's Innate Cold Damage on its Crystal Sword)
        if autos and spec.get('auto') not in autos and not (spec.get('extra') and not spec.get('auto')):
            raise CreateError(T('cr.err.innate', 'choose the innate affix of this base'))
        if q == 'superior' and spec.get('superior') not in self.superior_choices(code):
            raise CreateError(T('cr.err.superior', 'choose the Superior bonus'))
        if q == 'magic':
            if not spec.get('prefix') and not spec.get('suffix') and not self._vanilla():   # vanilla: Legit mode checks
                raise CreateError(T('cr.err.magic', 'a magic item needs a prefix or a suffix'))
            for kind, key in (('magicprefix', 'prefix'), ('magicsuffix', 'suffix')):
                if spec.get(key) and spec[key] not in {i for i, _, _ in self.affix_choices(kind, code, ilvl)}:
                    raise CreateError(T('cr.err.magic_affix', '{affix} cannot spawn on this item at item level {ilvl}',
                                        affix=T(f'cr.{key}', key.capitalize()), ilvl=ilvl))
        if q == 'rare':
            pre, suf = spec.get('rare_prefixes') or [], spec.get('rare_suffixes') or []
            if (len(pre) > 3 or len(suf) > 3) if self._vanilla() else (
                    not 1 <= len(pre) <= 3 or not 1 <= len(suf) <= 3 or len(pre) + len(suf) < 3):
                raise CreateError(T('cr.err.rare_count', 'a rare item has 1-3 prefixes and 1-3 suffixes (3 to 6 affixes)'))
            groups = set()
            for kind, lst in (('magicprefix', pre), ('magicsuffix', suf)):
                ok = {i for i, _, _ in self.affix_choices(kind, code, ilvl, rare=True)}
                for sid in lst:
                    if sid not in ok:
                        raise CreateError(T('cr.err.rare_affix', 'an affix cannot spawn on this rare at this item level'))
                    g = d.affixes[kind][sid - 1]['group']
                    if g and (kind, g) in groups:
                        raise CreateError(T('cr.err.same_group', 'two affixes of the same group'))
                    groups.add((kind, g))
            names = self.rare_name_choices(code)
            rn = spec.get('rare_names')
            if not rn or rn[0] not in {i for i, _ in names['rareprefix']} or rn[1] not in {i for i, _ in names['raresuffix']}:
                raise CreateError(T('cr.err.rare_name', 'choose the rare name'))
        if q == 'crafted':
            if spec.get('craft') not in self.craft_rows(code) and not (spec.get('extra') and spec.get('craft') is None):
                raise CreateError(T('cr.err.recipe', 'choose the shrine / crafting recipe'))
            pre, suf = spec.get('rare_prefixes') or [], spec.get('rare_suffixes') or []
            if spec.get('extra'):
                # an edited item whose affixes could not all be found: the rest of its stats are kept as they are
                if len(pre) > 3 or len(suf) > 3 or len(pre) + len(suf) > CRAFTED_AFFIXES:
                    raise CreateError(T('cr.err.crafted_max', 'a crafted item has at most {n} affixes (3 prefixes, 3 suffixes)', n=CRAFTED_AFFIXES))
            elif (len(pre) > 3 or len(suf) > 3 or len(pre) + len(suf) > self.crafted_counts(ilvl)[1]) if self._vanilla() else (
                    not 1 <= len(pre) <= 3 or not 1 <= len(suf) <= 3 or len(pre) + len(suf) != CRAFTED_AFFIXES):
                raise CreateError(T('cr.err.crafted_count', 'a crafted item has {n} affixes: 1-3 prefixes and 1-3 suffixes', n=CRAFTED_AFFIXES))
            self._check_rare_affixes(code, ilvl, pre, suf)
            names = self.rare_name_choices(code)
            rn = spec.get('rare_names')
            if not rn or rn[0] not in {i for i, _ in names['rareprefix']} or rn[1] not in {i for i, _ in names['raresuffix']}:
                raise CreateError(T('cr.err.name', 'choose the name'))
        if q == 'runeword':
            n, runes, ok, ex = d.runewords[spec['row']]
            anc = self.types_of(code)
            if not (anc & set(ok)) or anc & set(ex):
                raise CreateError(T('cr.err.rw_base', 'this runeword cannot be made in this base'))
            if spec['sockets'] != len(runes):
                raise CreateError(T('cr.err.rw_sockets', 'the base needs exactly {n} sockets', n=len(runes)))
            if spec.get('superior') is not None and spec['superior'] not in self.superior_choices(code):
                raise CreateError(T('cr.err.bad_superior', 'invalid Superior bonus'))
        if b.stack_max is not None:
            qn = spec.get('quantity') or 1
            if not 1 <= qn <= self.quantity_max(code):
                raise CreateError(T('cr.err.quantity', 'quantity 1 to {n}', n=self.quantity_max(code)))
        n_img = self.image_count(code)
        if spec.get('image') is not None and not 0 <= spec['image'] < max(n_img, 1):
            raise CreateError(T('cr.err.picture', 'invalid picture'))
        if spec.get('corrupt') is not None and spec['corrupt'] not in {r for r, *_ in self.corrupt_choices(spec)}:
            raise CreateError(T('cr.err.corrupt', 'this item cannot be corrupted that way'))
        for m in self.mods(spec):
            if m.variable and not m.min <= m.value <= m.max:
                if spec.get('unrestricted'):
                    spec.setdefault('_warning', T('cr.warn.unrestricted', 'unrestricted: a value is outside the '
                                                  "game's own ranges, kept as it is"))
                    continue
                raise CreateError(T('cr.err.range', 'value {v} out of range {lo}-{hi}', v=m.value, lo=m.min, hi=m.max))

    def build(self, spec):
        """(blob, record) of a validated spec: bytes of the item and its socketed items."""
        self.validate(spec)
        blob, rec = self._build(spec)
        if spec.get('_from_item') and spec.get('_orig'):
            blob, rec = self._carry(spec, blob, rec)
        try:
            from mxl_format_fix import parse_item
            parse_item(blob, self.data)      # the written item must read back exactly (a bad write once
        except Exception as e:               # corrupted a stash: never let an unreadable blob reach a file)
            raise CreateError(T('cr.err.verify', 'the encoded item failed verification ({error}); '
                                                  'nothing was written', error=e))
        import mxl_legit                     # Legit mode: only items the server's rules accept
        try:
            mxl_legit.guard_item(blob)
        except mxl_legit.LegitItemError as e:
            raise CreateError(str(e))
        return blob, rec

    def _build(self, spec):
        d, q, code = self.data, spec['quality'], spec['code']
        b = d.base(code)
        t = self.t.item.get(code, {})
        # simple (compact) misc items are saved without a stat list; one is chosen only when its own stat
        # list is empty (unrestricted editing adds stats through a full record instead)
        simple = bool(t.get('compact')) and q == 'normal' and b.kind == 'misc' and not spec.get('extra')
        fresh = [] if spec.get('_from_item') else self.reagent_stats(code)
        if is_cluster_container(code) or fresh:
            simple = False       # the game stores clusters / containers / vessels with their stat list (Quantity:)
        flags = FLAG_IDENTIFIED | FLAG_ALWAYS
        if simple:
            return encode_item(dict(flags=flags | FLAG_SIMPLE, code=code), d), None
        if spec['ethereal']:
            flags |= FLAG_ETHEREAL
        if spec['sockets'] or spec.get('_socket_flag'):
            flags |= FLAG_SOCKETED
        if q == 'runeword':
            flags |= FLAG_RUNEWORD
        if spec.get('_new_flag'):         # a created honorific: as the cube leaves it (see the creator's on_pick)
            flags |= FLAG_NEW
        rq = 'superior' if (q == 'runeword' and spec.get('superior') is not None) else ('normal' if q == 'runeword' else q)
        rec = dict(flags=flags, code=code, id=random.getrandbits(32), ilvl=spec['ilvl'], quality=rq,
                   socketed_count=len(spec['socketed']))
        if spec.get('_from_item') and spec.get('_item_id') is not None:
            rec['id'] = spec['_item_id']                      # an edited item stays the same item
        n_img = self.image_count(code)
        if n_img:
            rec['image'] = spec['image'] if spec.get('image') is not None else random.randrange(n_img)
        if spec.get('auto'):
            rec['auto_affix'] = spec['auto']
        if rq == 'superior':
            rec['subquality'] = spec['superior']
        elif q == 'magic':
            rec['prefix'], rec['suffix'] = spec.get('prefix') or 0, spec.get('suffix') or 0
        elif q in ('set', 'unique'):
            rec['set_unique_id'] = spec['row']
        elif q == 'tempered':
            rec['rare_names'] = self.rare_names_stored(spec['rare_names'])
        elif q in ('rare', 'crafted'):
            rec['rare_names'] = self.rare_names_stored(spec['rare_names'])
            pre, suf = list(spec['rare_prefixes']), list(spec['rare_suffixes'])
            slots = []
            for k in range(3):
                slots += [pre[k] if k < len(pre) else None, suf[k] if k < len(suf) else None]
            rec['rare_affixes'] = slots
        if q == 'runeword':
            idx = self.rw_string_id(spec['row'])
            if idx is None:
                raise CreateError(T('cr.err.rw_name', 'runeword name not found in the string tables'))
            rec['runeword_id'] = idx
        mods = self.mods(spec)
        own = [s for m in mods if m.source.split(':')[0] != 'rw' for s in m.stats(d)]
        rw = [s for m in mods if m.source.split(':')[0] == 'rw' for s in m.stats(d)]
        if q == 'runeword' and self._vanilla():
            rw = self._runeword_api_stats(spec, rw)
        own += [dict(x) for x in spec.get('extra') or []]              # kept as they were on an edited item
        if fresh:                    # a new reagent: what the game's own making recipe puts on it (display text...)
            have = {(s['id'], s.get('param')) for s in own}
            own += [s for s in fresh if (s['id'], s.get('param')) not in have]
        own = [s for s in merge_stats(own) if d.isc[s['id']]['bits']]
        if is_vessel(d, code) and not spec.get('_from_item'):
            own = stats_with_cluster_quantity(own)   # a fresh vessel / barrel / crate starts full (Quantity: 1000);
                                                     # an edited one keeps the amount it holds (or no attribute)
        if spec.get('_drop'):                 # edited item: attributes the user deleted (see the editor)
            own = [s for s in own if (s['id'], s.get('param')) not in spec['_drop']]
        if '_keep_zero' in spec:              # edited item: a stat its mods give but the item had not cancels out
            own = [s for s in own if s['value'] or (s['id'], s.get('param')) in spec['_keep_zero']]
        field, n194 = self.socket_split(spec)
        if self._vanilla() and q != 'runeword':         # the sockets beyond the field: item_numsockets (194)
            own = [s for s in own if s['id'] != 194]
            if n194 and d.isc[194]['bits']:
                own.append(dict(id=NUM_SOCKETS, param=None, value=n194, sockets=True))   # kept by build_blob
        rec['stats'] = own
        if q == 'runeword':
            rw += [dict(x) for x in spec.get('extra_rw') or []]
            rec['stats_runeword'] = [s for s in merge_stats(rw) if d.isc[s['id']]['bits']]
            if '_keep_zero_rw' in spec:
                rec['stats_runeword'] = [s for s in rec['stats_runeword']
                                         if s['value'] or (s['id'], s.get('param')) in spec['_keep_zero_rw']]
        if body_kind(d, code) == 'armor':
            lo, hi = self.defense_range(spec)
            v = spec.get('defense')
            raw = spec.get('_defense_raw')
            if raw and v == raw[0]:
                v = raw[1]                                        # edited item, defense untouched: as it was
            else:
                v = hi if v is None else max(lo, min(hi, v))
                if spec['ethereal']:
                    v = v * 3 // 2
            rec['defense'] = v
        if body_kind(d, code) in ('armor', 'weapons'):
            cm, cd = d.isc[S.MAX_DURABILITY], d.isc[S.DURABILITY]
            dur = 0 if t.get('nodur') else t.get('dur', 0)
            if dur:
                if q == 'set':
                    dur = min(dur * 2, durability_cap(d))
                elif q == 'unique':
                    dur = min(dur * 3, durability_cap(d))
                if spec['ethereal']:
                    dur = dur // 2 + 1
            rec['max_durability'] = dur + cm['add']
            rec['durability'] = dur + cd['add']
        if b.stack_max is not None:
            rec['quantity'] = spec.get('quantity') or 1
        if spec['sockets'] or spec.get('_socket_flag'):
            rec['sockets'] = field
        children = []
        if q == 'runeword':
            runes = [d.item_index[r] for r in d.runewords[spec['row']][1]]
            fill = runes
        else:
            fill = spec['socketed']
        for c in fill:
            children.append(dict(flags=FLAG_IDENTIFIED | FLAG_ALWAYS | FLAG_SIMPLE, code=c))
        rec['socketed_count'] = len(children)
        return build_blob(rec, children, d), rec

    # ---- editing an existing item
    def spec_from_item(self, it):
        """Spec of an item read by mxl_format (quality, base, affixes, rolled values), to edit it in the creator.
        Values that several mods add together cannot be split back: those mods get their maximum. A corrupted
        item: the corruption outcome that explains its stats best is found and taken out of them first.

        The spec is a model: it holds what the creator can choose, not everything an item stores (item id, the
        header flags it does not set, worn durability, socketed jewels, personalisation, set bonus lists, the place
        of the item...). So the item as it was read is kept beside it (spec['_orig']: its bytes, their lossless
        decode, the bytes of its socketed items and a copy of the spec as it starts), and build() writes only what
        the user changed over it (_carry): an edit that changes nothing gives the item's own bytes back."""
        spec = self._spec_model(it)
        spec['_item_id'] = it.get('id')
        spec.pop('_orig', None)
        try:
            orig = self._original(it)
        except Exception:
            orig = None
        if orig is not None:
            # the socketed items the spec cannot name (jewels..., also beside a runeword's runes): kept by their
            # place in the original list, so that each one can be taken out (remove_filler / clear_fillers)
            spec['_kept'] = [i for i, raw in enumerate(orig['kids'])
                             if not decode_item(raw, self.data)[0]['flags'] & FLAG_SIMPLE]
            orig['spec'] = copy.deepcopy(spec)
            spec['_orig'] = orig
        return spec

    # ---- socket fillers of an edited item
    def fillers(self, spec):
        """The filled sockets of a spec, in the order build() writes them: dicts with kind 'pick' (a gem / rune /
        other simple socketable of spec['socketed'], slot = its index there) or 'item' (an original socketed item
        with a stat list of its own, a jewel..., index = its place in the item as read), code and name."""
        d = self.data
        out = []
        for k, c in enumerate(spec.get('socketed') or []):
            if c:
                out.append(dict(kind='pick', slot=k, code=c, name=d.base(c).name if c in d.bases else c.strip()))
        o = spec.get('_orig')
        if spec.get('_kept') and o:
            for i in spec['_kept']:
                rec = decode_item(o['kids'][i], d)[0]
                c = rec['code']
                name = d.base(c).name if c in d.bases else c.strip()
                q = rec.get('quality')
                if q not in (None, 'normal'):
                    name = '%s (%s)' % (name, T('cr.quality.' + q, q.capitalize()))
                out.append(dict(kind='item', index=i, code=c, name=name))
        for j, raw in enumerate(spec.get('_added') or ()):     # socketables put in while editing (add_filler)
            rec = decode_item(raw, d)[0]
            c = rec['code']
            out.append(dict(kind='item', added=j, code=c, name=d.base(c).name if c in d.bases else c.strip()))
        return out

    def free_sockets(self, spec):
        """Empty sockets of an edited item (sockets minus runes / picks, kept and added socketed items)."""
        if spec.get('quality') == 'runeword':
            used = len(self.data.runewords[spec['row']][1])
        else:
            used = len([c for c in spec.get('socketed') or () if c])
        used += len(spec.get('_kept') or ()) + len(spec.get('_added') or ())
        return max(0, (spec.get('sockets') or 0) - used)

    def is_socketable(self, code):
        """A socket filler (its item type descends from 'sock': gems, runes, jewels, other fillers)."""
        try:
            return 'sock' in self.type_codes(code)
        except Exception:
            return False

    def add_filler(self, spec, blob):
        """Puts a socketable item (its bytes, e.g. the copied item) into the next free socket of an edited item:
        written after the item's other socketed items, as the game appends one. Raises CreateError."""
        if not spec.get('_orig'):
            raise CreateError(T('cr.err.add_filler_new', 'socketed items can be added to an edited item only'))
        rec, n = decode_item(bytes(blob), self.data)
        if n != len(blob) or rec['flags'] & FLAG_SOCKETED:
            raise CreateError(T('cr.err.add_filler_kids', 'an item with socketed items cannot go into a socket'))
        if not self.is_socketable(rec['code']):
            raise CreateError(T('cr.err.add_filler_type', 'the copied item is not a gem, rune, jewel or other socket filler'))
        if not self.free_sockets(spec):
            raise CreateError(T('cr.err.add_filler_full', 'the item has no free socket'))
        spec['_added'] = list(spec.get('_added') or ()) + [bytes(blob)]

    def remove_filler(self, spec, n):
        """Takes filler n of fillers(spec) out of its socket (the socket stays, empty)."""
        f = self.fillers(spec)[n]
        if f.get('added') is not None:
            a = list(spec.get('_added') or ())
            del a[f['added']]
            spec['_added'] = a
        elif f['kind'] == 'pick':
            s = list(spec.get('socketed') or [])
            del s[f['slot']]
            spec['socketed'] = s
        else:
            spec['_kept'] = [i for i in spec['_kept'] if i != f['index']]

    def clear_fillers(self, spec):
        """Empties every socket of a spec; a runeword keeps its runes (they are the runeword)."""
        if spec.get('quality') != 'runeword':
            spec['socketed'] = []
        if '_kept' in spec:
            spec['_kept'] = []
        spec.pop('_added', None)

    def _original(self, it):
        """What _carry needs of the item as read, or None when its bytes are not known (an item that did not come
        from mxl_format_fix.parse_item) or do not match the fields any more."""
        raw = getattr(it, '_raw', None)
        if not raw:
            return None
        rec, n = decode_item(raw, self.data)
        if n != len(raw) or encode_item(rec, self.data) != raw:
            return None

        def key(stats):
            return sorted((s['id'], s.get('param') or 0, s['value']) for s in stats or [])
        if rec['code'] != it.get('code') or rec.get('id') != it.get('id') or key(rec.get('stats')) != key(it.get('stats')):
            return None
        if (rec.get('ilvl'), rec.get('quality'), rec.get('sockets'), bool(rec['flags'] & FLAG_ETHEREAL)) != \
                (it.get('ilvl'), it.get('quality'), it.get('sockets'), bool(it.get('ethereal'))):
            return None                       # the fields were changed after the item was read: no original to keep
        kids = [getattr(k, '_raw', None) for k in it.get('socketed') or []]
        want = rec.get('socketed_count', 0) if rec['flags'] & FLAG_SOCKETED else 0
        if len(kids) != want or not all(kids):
            return None
        return dict(raw=raw, rec=rec, kids=kids, base={})

    @staticmethod
    def _split(blob, data):
        """(bytes of the item, [bytes of each socketed item]) of a built blob."""
        _rec, n = decode_item(blob, data)
        kids, p = [], n
        while p < len(blob):
            _k, m = decode_item(blob[p:], data)
            kids.append(blob[p:p + m])
            p += m
        return blob[:n], kids

    def _carry(self, spec, blob, rec):
        """The edited item written over the original one: (blob, record). `blob` / `rec` are what the spec alone
        builds. The same build of the spec as it was when the item was opened (the baseline) shows what the user
        changed: every header field, flag bit, stat and socketed item that is the same in both builds is taken
        from the original item, everything else from the new build. Nothing changed -> the original bytes."""
        d, o = self.data, spec['_orig']
        orec = o['rec']
        free = bool(spec.get('unrestricted'))
        if free not in o['base']:
            try:
                bs = copy.deepcopy(o['spec'])
                bs['unrestricted'] = free
                self.validate(bs)
                o['base'][free] = self._build(bs) + (bs,)
            except Exception:
                o['base'][free] = None
        base = o['base'][free]
        if base is None:
            return blob, rec
        bblob, brec, bspec = base
        oblob = o['raw'] + b''.join(o['kids'])
        if rec is None or brec is None or orec['flags'] & FLAG_SIMPLE:
            return (oblob if blob == bblob else blob), rec          # simple items: all or nothing
        _n, nkids = self._split(blob, d)
        _b, bkids = self._split(bblob, d)
        out = dict(orec)
        for k in set(rec) | set(brec):
            if k in ('id', 'flags', 'socketed_count') or k.startswith('stats') or k.startswith('set_stats'):
                continue
            if k == 'image':
                if spec.get('image') != bspec.get('image'):
                    out[k] = rec.get(k)
                continue
            if rec.get(k) != brec.get(k):
                if k in rec:
                    out[k] = rec[k]
                else:
                    out.pop(k, None)
        out['flags'] = orec['flags'] ^ (rec['flags'] ^ brec['flags'])     # only the bits the edit switched
        for k in {x for r in (rec, brec, orec) for x in r if x.startswith('stats') or x.startswith('set_stats')}:
            out[k] = self._carry_stats(orec.get(k), rec.get(k), brec.get(k))
            if out[k] is None:
                del out[k]
        odec = [decode_item(raw, d)[0] for raw in o['kids']]
        fixed = [i for i, k in enumerate(odec) if not k['flags'] & FLAG_SIMPLE]   # jewels...: not in the spec
        keep = fixed if spec.get('_kept') is None else [i for i in fixed if i in spec['_kept']]
        added = [bytes(x) for x in spec.get('_added') or ()]       # add_filler: appended after the others
        if nkids == bkids and keep == fixed and not added:
            kids = list(o['kids'])
        else:
            if nkids == bkids:
                # only socketed items the spec cannot name were taken out: the others stay as they were, in order
                both = [i for i in range(len(odec)) if i not in fixed or i in keep]
            else:
                # the socket fillers were changed: the new ones, and the original socketed items the spec cannot
                # name (jewels and other items with a stat list of their own) that were not taken out
                new = [decode_item(x, d)[0] for x in nkids]
                room = max(len(new), spec.get('sockets', 0) if out['flags'] & FLAG_SOCKETED else 0)
                both = (new + keep)[:max(room, len(new))]
            both = both + added
            kids = []
            for x, k in enumerate(both):
                if isinstance(k, int):                    # an original child: its own bytes when its place holds
                    if odec[k].get('x') == x and odec[k].get('location') == LOC_SOCKETED:
                        kids.append(o['kids'][k])
                        continue
                    k = odec[k]
                elif isinstance(k, bytes):
                    k = decode_item(k, d)[0]
                kids.append(encode_item(dict(k, location=LOC_SOCKETED, equipped=0, x=x, y=0, panel=0), d))
        out['socketed_count'] = len(kids)
        if out == orec and kids == o['kids']:
            return oblob, orec
        return encode_item(out, d) + b''.join(kids), out

    @staticmethod
    def _carry_stats(orig, new, base):
        """One stat list of _carry: the original list with the changes between the baseline and the new build
        (a stat added, removed, or given another value). No change: the original list itself, order included."""
        def table(lst):
            acc = {}
            for s in lst or []:
                k = (s['id'], s.get('param') or 0)
                acc[k] = acc.get(k, 0) + (s['value'] or 0)
            return acc
        n, b = table(new), table(base)
        if n == b and (new is None) == (base is None):
            return orig
        if new is None:
            return None
        out = table(orig)
        for k in b:
            if k not in n:
                out.pop(k, None)
        for k, v in n.items():
            if k not in b or b[k] != v:
                out[k] = v
        return [dict(id=k[0], param=k[1] or None, value=v) for k, v in sorted(out.items())]

    def _spec_model(self, it):
        have = {}
        for x in it.get('stats') or []:
            k = (x['id'], x.get('param'))
            have[k] = have.get(k, 0) + x['value']
        if not any(k[0] in (496, 497, 498) for k in have):
            spec = self._spec_from_item(it)
            self._mark_max_sockets(spec)
            return spec
        plain = self._spec_from_item(it)

        def score(sp):
            ex = [x for x in sp.get('extra') or [] if x['value']]
            return (len([x for x in ex if self._visible(x)]), len(ex))
        best = (score(plain), 0, plain)
        plain_ex = {}
        for x in plain.get('extra') or []:
            k = (x['id'], x.get('param'))
            plain_ex[k] = plain_ex.get(k, 0) + x['value']
        q = plain['quality']
        for n, (row, kind, _p, _l) in enumerate(self.corrupt_options(plain['code'], q)):
            roll = have.get((498, None))
            if kind == 'pending' and roll is None:
                continue
            cs = self._corrupt_stats(dict(corrupt=row, corrupt_roll=roll))
            if not cs or any(k not in have for k in cs):
                continue
            if any(v > 0 and plain_ex.get(k, 0) < v or v < 0 and plain_ex.get(k, 0) > v for k, v in cs.items()):
                continue                       # the outcome must be what the item has beyond its own mods
            stats = []
            for k, v in have.items():
                v2 = v - cs.get(k, 0)
                if v2 or k not in cs:
                    stats.append(dict(id=k[0], param=k[1], value=v2))
            try:
                sp = self._spec_from_item(dict(it, stats=stats))
            except CreateError:
                continue
            sc = score(sp)
            if (sc, n + 1) < best[:2]:
                sp['corrupt'], sp['corrupt_roll'] = row, roll if kind == 'pending' else None
                best = (sc, n + 1, sp)
        spec = best[2]
        self._mark_max_sockets(spec)
        return spec

    def _mark_max_sockets(self, spec):
        ms = self.socket_limit(spec['code'], spec['ilvl']) if spec.get('code') in self.data.bases else 0
        spec['max_sockets'] = bool(ms) and spec.get('sockets') == ms and spec.get('quality') != 'runeword'

    def _spec_from_item(self, it):
        d = self.data
        q = it.get('quality')
        if it.get('runeword') is not None or 'stats_runeword' in it:
            row = runeword_row(it, d)
            if row is None:
                raise CreateError(T('cr.err.rw_unknown', 'unknown runeword'))
            spec = self.new_spec('runeword', it['code'], row)
            spec['superior'] = it.get('subquality') if q == 'superior' else None
        elif q in ('unique', 'set'):
            row, table = it.get('set_unique_id'), (d.uniques if q == 'unique' else d.set_items)
            if not isinstance(row, int) or not 0 <= row < len(table):
                # e.g. a unique-quality Wirt's Leg whose id is 32767: no row to take the mods from
                raise CreateError(T('cr.err.row_unknown', 'the item names no row of the {quality} table (id {row})',
                                    quality=T(f'cr.quality.{q}', q), row=row))
            spec = self.new_spec(q, it['code'], row)
        elif q in ('normal', 'superior', 'magic', 'rare'):
            spec = self.new_spec(q, it['code'])
            if q == 'superior':
                spec['superior'] = it.get('subquality')
            if q == 'magic':
                spec['prefix'], spec['suffix'] = it.get('prefix') or None, it.get('suffix') or None
            if q == 'rare':
                spec['rare_names'] = self.rare_names_from_stored(it['rare_names'])
                ra = it.get('rare_affixes') or []
                spec['rare_prefixes'] = [x for x in ra[0::2] if x]
                spec['rare_suffixes'] = [x for x in ra[1::2] if x]
        elif q == 'tempered':                 # Sigma quality 9: name only, every stat kept as it is
            spec = self.new_spec('tempered', it['code'])
            spec['rare_names'] = self.rare_names_from_stored(it.get('rare_names') or (len(d.rare_suffix), 0))
        elif q == 'crafted':
            spec = self.new_spec('crafted', it['code'])
            spec['rare_names'] = self.rare_names_from_stored(it.get('rare_names') or (len(d.rare_suffix), 0))
            ra = it.get('rare_affixes') or []
            spec['rare_prefixes'] = [x for x in ra[0::2] if x]
            spec['rare_suffixes'] = [x for x in ra[1::2] if x]
            spec['ilvl'] = it.get('ilvl') or spec['ilvl']
            spec['craft'] = self._find_craft(it, spec)
            if not spec['rare_prefixes'] and not spec['rare_suffixes']:
                left = list(it.get('stats') or [])
                if spec['craft'] is not None:
                    rc_ids = {(st['id'], st.get('param')) for m in self.mods(dict(spec, rare_prefixes=[], rare_suffixes=[]))
                              for st in m.stats(d)}
                    left = [x for x in left if (x['id'], x.get('param')) not in rc_ids]
                spec['rare_prefixes'], spec['rare_suffixes'] = self._infer_affixes(it, it['code'], spec['ilvl'], left)
        elif q is None:
            # simple item (rune, gem, key, rechargeable...): readable/kept as a normal item, with no stat list
            # of its own - the raw stat rows of unrestricted editing add stats to it like to any other item
            if not it.get('code') or it.get('code') not in d.bases:
                raise CreateError(T('cr.err.simple', 'simple items (runes, gems, keys...) have nothing to edit'))
            spec = self.new_spec('normal', it['code'])
        else:
            raise CreateError(T('cr.err.not_editable_q', '{quality} items cannot be edited here', quality=T(f'cr.quality.{q}', str(q))))
        spec['ilvl'] = it.get('ilvl') or spec['ilvl']
        spec['ethereal'] = bool(it.get('ethereal'))
        spec['sockets'] = it.get('sockets') or 0
        if spec['quality'] != 'runeword':
            spec['socketed'] = [s['code'] for s in it.get('socketed', []) if d.base(s['code']).kind == 'misc'
                                and self.t.item.get(s['code'], {}).get('compact')]
        spec['image'] = it.get('image')
        spec['auto'] = it.get('auto_affix')
        if 'quantity' in it:
            spec['quantity'] = it['quantity']
        if 'defense' in it:
            v = it['defense']
            spec['defense'] = v * 2 // 3 if spec['ethereal'] else v
            spec['_defense_raw'] = (spec['defense'], v)        # kept exactly while the slider isn't moved
        spec['_socket_flag'] = bool(it.get('has_sockets'))
        counts = {}
        mods = self.mods(spec)
        for m in mods:
            for sid in m.stat_ids(d):
                counts[sid] = counts.get(sid, 0) + 1
        have = {}
        for lst in ('stats', 'stats_runeword'):
            for s in it.get(lst) or []:
                have[(lst, s['id'])] = s['value']
        for m in mods:
            if not m.variable:
                continue
            lst = 'stats_runeword' if m.source.startswith('rw:') else 'stats'
            ids = m.stat_ids(d)
            v = next((have[(lst, sid)] for sid in ids if (lst, sid) in have and counts.get(sid) == 1), None)
            spec['rolls'][m.source] = v if v is not None and m.min <= v <= m.max else m.max
        used = set()
        for m in mods:                       # random skill / monster mods: the rolled value is the stat's param
            if m.variable and d.prop_func[m.prop] == 12:
                ids = set(m.stat_ids(d))
                for s in it.get('stats') or []:
                    p = s.get('param')
                    if s['id'] in ids and p is not None and m.min <= p <= m.max and (s['id'], p) not in used:
                        used.add((s['id'], p))
                        spec['rolls'][m.source] = p
                        break
        # what the item's mods do not give, or give outside their range (other upgrades, corruption, an
        # imported copy, a hacked value...): kept on the item exactly as it is (the user's rule: such items
        # are allowed; the status line warns about them)
        made = {}
        for m in self.mods(spec):
            if m.source.startswith('rw:'):
                continue                      # runeword mods go to the runeword list
            for x in m.stats(d):
                k = (x['id'], x.get('param'))
                made[k] = made.get(k, 0) + x['value']
        have = {}
        for x in it.get('stats') or []:
            k = (x['id'], x.get('param'))
            have[k] = have.get(k, 0) + x['value']
        extra = []
        # a stat the mods give but the item does not hold at all (the user deleted that attribute in an earlier
        # edit - e.g. the skill of an Essence of Time): marked like the editor's own delete, so it stays off the
        # stat list. As a cancelling delta row it came back in the list as a 0 on every re-edit.
        gone = {k for k in made if k not in have}
        if gone:
            spec['_drop'] = gone
        for k in list(have):
            dv = have.get(k, 0) - made.get(k, 0)
            if dv or (k not in made and have.get(k) == 0):
                extra.append(dict(id=k[0], param=k[1], value=dv))
        # the stats the item holds beyond what its own mods produce (upgrades, corruption, an imported
        # copy...): the ones the status line reports as kept while they are still on the item and the
        # user has not taken the value over
        spec['_extra_kept'] = {k for k in have if have[k] != made.get(k, 0)}
        made_rw = {}
        for m in self.mods(spec):
            if m.source.startswith('rw:'):
                for x in m.stats(d):
                    k = (x['id'], x.get('param'))
                    made_rw[k] = made_rw.get(k, 0) + x['value']
        have_rw = {}
        for x in it.get('stats_runeword') or []:
            k = (x['id'], x.get('param'))
            have_rw[k] = have_rw.get(k, 0) + x['value']
        spec['extra_rw'] = [dict(id=k[0], param=k[1], value=have_rw.get(k, 0) - made_rw.get(k, 0))
                            for k in list(have_rw) + [k for k in made_rw if k not in have_rw]
                            if have_rw.get(k, 0) != made_rw.get(k, 0)]
        spec['_keep_zero_rw'] = {k for k, v in have_rw.items() if v == 0}
        spec['extra'] = extra
        spec['_keep_zero'] = {k for k, v in have.items() if v == 0}
        spec['_from_item'] = True
        if self._vanilla() and spec['quality'] != 'runeword':
            # sockets in all = the save field + item_numsockets (194, see socket_split); build() writes 194 again
            spec['_sock_field'] = it.get('sockets') or 0
            spec['sockets'] = spec['_sock_field'] + sum(v for k, v in have.items() if k[0] == 194)
            spec['extra'] = [x for x in extra if x['id'] != 194]
            spec['_extra_kept'] = {k for k in spec['_extra_kept'] if k[0] != 194}
            spec['_keep_zero'] = {k for k in spec['_keep_zero'] if k[0] != 194}
        return spec

    def _find_craft(self, it, spec):
        """Recipe of a crafted item: the one whose stats are on the item with values in its ranges, most of
        them (several shrine sizes share the same ranges: any of them gives the same item)."""
        d = self.data
        have = {}
        for x in it.get('stats') or []:
            have[(x['id'], x.get('param'))] = x['value']
        ids = {k[0] for k in have}
        best = None
        for row in self.craft_rows(it['code']):
            score, n = 0, 0
            for m in self.mods(dict(spec, craft=row, rare_prefixes=[], rare_suffixes=[], auto=None)):
                try:
                    lo = mods_stats([(m.prop, m.param, m.min, m.min)], d, 'min') if m.variable else m.stats(d)
                    hi = mods_stats([(m.prop, m.param, m.max, m.max)], d, 'min') if m.variable else m.stats(d)
                except Exception:
                    continue
                la = {(x['id'], x.get('param')): x['value'] for x in lo}
                lb = {(x['id'], x.get('param')): x['value'] for x in hi}
                for k in set(la) | set(lb):
                    n += 1
                    if k[0] not in ids:
                        score -= 10
                        continue
                    x, y = sorted((la.get(k, 0), lb.get(k, 0)))
                    v = have.get(k)
                    if d.prop_func[m.prop] == 12:
                        score += 2
                    elif v is not None and x <= v:
                        score += 3 if v <= y else 2
            if not n:
                continue
            known = bool(spec.get('rare_prefixes') or spec.get('rare_suffixes'))
            probs = len(self._crafted_problems(it, dict(spec, craft=row))) if known else 0
            key = (-probs, score, n)
            if best is None or key > best[0]:
                best = (key, row)
        if best is None or (best[0][0] < 0 or not known) and best[0][1] <= 0:
            ch = self.craft_rows(it['code'])
            return ch[0] if ch else None
        return best[1]

    def check_legit(self, it):
        """Problems [text] of an item read by mxl_format, checked with the collector's own range rules."""
        d = self.data
        out = []
        if it.get('quality') == 'crafted':
            return self._check_crafted(it)
        rand_skill = {x for p, f in enumerate(d.prop_func) if f == 12 for x in d.props[p] if x >= 0}
        pair_stats = {x for p, fs in enumerate(d.prop_funcs) if any(f in (15, 16, 17) for f in fs)
                      for x in d.props[p] if x >= 0}
        for lst in ('stats', 'stats_runeword'):
            for s in it.get(lst) or []:
                if lst == 'stats_runeword' or s['id'] in pair_stats:
                    continue                    # several mods add up / min-max pairs: checked by construction
                if s['id'] in (S.PREFIX_COUNT, S.SUFFIX_COUNT) or s['id'] in rand_skill or is_innate_damage(s['id'], d):
                    continue
                rng = stat_range(it, s['id'], d, lst, s.get('param'))
                if rng is not None and not rng[0] <= s['value'] <= rng[1]:
                    out.append(Problem(T('cr.prob.outside_list', '{where} stat {stat} = {value} outside {lo}-{hi}',
                                         where=T('cr.list.' + lst, lst), stat=s['id'], value=s['value'], lo=rng[0], hi=rng[1]), s['id']))
        return out

    def _check_crafted(self, it):
        """Crafted items: each stat within the sum of the ranges of its affixes and of the crafting recipe."""
        try:
            spec = self.spec_from_item(it)
        except CreateError as e:
            return [str(e)]
        return self._crafted_problems(it, spec)

    def _crafted_problems(self, it, spec):
        d = self.data
        rng = {}
        for m in self.mods(spec):
            if d.prop_func[m.prop] == 12 and m.max - m.min <= 4096:      # random skill / monster: the param
                for st in m.stats(d):
                    for p in range(m.min, m.max + 1):
                        k = (st['id'], p)
                        r = rng.get(k, (0, 0))
                        rng[k] = (r[0], r[1] + st['value'])
                continue
            try:
                if not m.variable:                                    # fixed (incl. skill on event: chance / level)
                    lo = hi = m.stats(d)
                else:
                    lo = mods_stats([(m.prop, m.param, m.min, m.min)], d, 'min')
                    hi = mods_stats([(m.prop, m.param, m.max, m.max)], d, 'min')
            except Exception:
                continue
            la = {(a['id'], a.get('param')): a['value'] for a in lo}
            lb = {(b['id'], b.get('param')): b['value'] for b in hi}
            for k in set(la) | set(lb):
                x, y = sorted((la.get(k, 0), lb.get(k, 0)))
                r = rng.get(k, (0, 0))
                rng[k] = (r[0] + x, r[1] + y)
        out = []
        for s in it.get('stats') or []:
            k = (s['id'], s.get('param'))
            if s['id'] in FOLLOWERS and not s['value'] and k not in rng:
                continue                      # saved with its group (e.g. cold length after cold damage)
            if k not in rng:
                out.append(Problem(T('cr.prob.no_source', 'stat {stat} = {value} comes from no affix or recipe', stat=s['id'], value=s['value']), s['id']))
            elif not rng[k][0] <= s['value'] <= rng[k][1]:
                out.append(Problem(T('cr.prob.outside', 'stat {stat} = {value} outside {lo}-{hi}', stat=s['id'], value=s['value'],
                                     lo=rng[k][0], hi=rng[k][1]), s['id']))
        return out

    # ---- Angelic items (Median XL Sigma: Library of Fate tier, not in the normal drop pool)
    def angelic_bases(self):
        """Weapons / armor of the Angelic tier (item type ancestors include 'aaaa'): Full Helm (Angelic) ...
        They are not spawnable as plain bases; they come as rares with their own Angelic-only affixes."""
        d = self.data
        tag = next((i for i, t in enumerate(d.itypes) if t[0] == 'aaaa'), None)
        if tag is None:
            return []
        out = [b for b in d.bases.values() if b.kind in ('weapons', 'armor') and b.name and tag in self.types_of(b.code)]
        return sorted(out, key=lambda b: (b.kind, b.name.lower()))

    def is_angelic(self, code):
        return any(b.code == code for b in self.angelic_bases())

    # ---- display names and mystic orbs
    def display_name(self, code):
        """Name as the game shows it: multi-line names are drawn bottom line on top, so "Mystic Orb\nKara's Trinket"
        reads "Kara's Trinket - Mystic Orb"."""
        b = self.data.base(code)
        raw = (b.name_raw or b.name or '').replace('\\n', '\n')
        lines = []
        for line in raw.split('\n'):
            while 'ÿc' in line:
                i = line.index('ÿc')
                line = line[:i] + line[i + 3:]
            line = line.strip()
            if line:
                lines.append(line)
        if not lines:
            return b.name or code
        if len(lines) == 1:
            return lines[0]
        return lines[-1] + ' - ' + ' / '.join(reversed(lines[:-1]))

    def granted_skills(self, u):
        """Names of the skills a unique's mods grant: what tells the 200+ uniques all named "Relic" apart. The skill
        is the param of an oskill mod (stat 97, "+x to Bladestorm"); a relic without one is told by its class-only
        skill bonus (stat 107). Unnamed skills ("skill #1905": hidden helper skills) are left out."""
        d = self.data
        for sid in (97, 107):
            out = []
            for m in u.get('mods') or ():
                if not 0 <= m['prop'] < len(d.props) or sid not in d.props[m['prop']]:
                    continue
                name = str(d.skill_names.get(m['param']) or '').strip()     # own names only: no hidden helpers
                if name and 'POLAR BUFFALO' not in name.upper() and name not in out:
                    out.append(name)
            if out:
                return out
        return []

    def unique_enabled(self, row):
        """The 'enabled' bit of a uniqueitems row (u32 flags at 0x2C of the record, bit 0, as in the vanilla
        table): 0 = the game does not drop the row (cube / quest results, and leftover rows). True when the
        table cannot be read."""
        flags = self.__dict__.get('_uniq_flags')
        if flags is None:
            try:
                flags = [struct.unpack_from('<I', r, 0x2C)[0] for r in _rows(self.data, 'uniqueitems')]
            except Exception:
                flags = []
            self._uniq_flags = flags
        return bool(flags[row] & 1) if 0 <= row < len(flags) else True

    def catalog_labels(self, q):
        """{row: label} of the creator list of the 'unique' or 'set' quality: "<name> - <base>"; a relic (name =
        base name, 200+ rows) reads "Relic - <granted skill>". Rows that would read the same are told apart by
        what differs between them, the others keep their label:
        - the bonus line the other rows of the group do not have (the one naming the granted skill first):
          "Relic - Trinity Beam: +(8 to 16) to Trinity Beam", "Zann Esu's Stone - Jewel: Maximum Cold Resist +1%";
        - rows with the same bonuses: "[not dropped]" on the row that is not enabled (Hratli's Craft), and the
          table row "[#1535]" when nothing but the rarity differs (Darkfeast)."""
        cache = self.__dict__.setdefault('_catalog_labels', {})
        if q in cache:
            return cache[q]
        d = self.data
        rows = self.uniques() if q == 'unique' else self.set_items()
        labels, us = {}, {}
        for i, name, u in rows:
            nm, bn = one_line(name), one_line(d.base(u['code']).name)
            label = f'{nm} - {bn}'
            if nm == bn:                                         # "Relic - Relic" x200: the granted skill instead
                skills = self.granted_skills(u)
                if skills:
                    label = f"{nm} - {' / '.join(skills)}"
            labels[i], us[i] = label, u

        def groups():
            g = {}
            for i in labels:
                g.setdefault(labels[i].casefold(), []).append(i)
            return [v for v in g.values() if len(v) > 1]

        for grp in groups():                                     # 1: the bonus line the others do not have
            lines = {}
            for i in grp:
                try:
                    lines[i] = self.mods_text([(m['prop'], m['param'], m['min'], m['max']) for m in us[i]['mods']],
                                              us[i]['code'])
                except Exception:
                    lines[i] = []
            count = {}
            for i in grp:
                for ln in set(lines[i]):
                    count[ln] = count.get(ln, 0) + 1
            for i in grp:
                skills = [x.lower() for x in self.granted_skills(us[i])]
                own = [(count[ln], 0 if any(x in ln.lower() for x in skills) else 1, k, ln)
                       for k, ln in enumerate(lines[i]) if count[ln] < len(grp)]
                if own:
                    tag = min(own)[3]
                    labels[i] += ': ' + (tag if len(tag) <= 64 else tag[:61] + '...')
        if q == 'unique':
            for grp in groups():                                 # 2: same bonuses, one row not enabled
                en = [self.unique_enabled(i) for i in grp]
                if any(en) and not all(en):
                    for i, e in zip(grp, en):
                        if not e:
                            labels[i] += ' ' + T('cr.list.not_dropped', '[not dropped]')
        for grp in groups():                                     # 3: nothing a player sees differs: the table row
            for i in grp:
                labels[i] += f' [#{i}]'
        cache[q] = labels
        return labels

    def base_list_rows(self, bases, kind_label=None):
        """[(label, code)] of base items for the creator list: the name as the game shows it, a mystic orb with
        its effect, "[Weapon]" / "[Armor]" / "[Misc]" behind it. Items of the same name are told apart by their
        description (desc_summary) or, without one, by the picture's name; what still reads the same gets its
        item code ("Custom Signet of Learning: Right-click: Free Attribute Points [Misc, 07^]" - the 22 signets
        differ in nothing but the code)."""
        d = self.data
        kl = kind_label or (lambda k: {'weapons': 'Weapon', 'armor': 'Armor', 'misc': 'Misc'}.get(k, ''))
        rows = []
        for b in bases:
            label = self.display_name(b.code)
            if ' / ' in label:                                    # long multi-line names: the top line only
                label = label.split(' - ')[0]
            orb = self.orb_effects(b.code)
            if orb and orb[0]:                                    # mystic orbs: their effect tells them apart
                label += ': ' + '; '.join(orb[0])
            rows.append((f'{label} [{kl(b.kind)}]', b.code))
        seen = {}
        for label, _ in rows:
            seen[label.casefold()] = seen.get(label.casefold(), 0) + 1
        named = []
        for label, code in rows:                                  # same name: the description tells them apart
            if seen[label.casefold()] > 1:
                summary = self.desc_summary(code)
                if not summary:                                   # no description: the picture's name (dye-rainbow)
                    inv = (d.base(code).inv_file or '').lower()
                    if 'dye' in inv and 'rainbow' in inv:
                        summary = 'Color: Rainbow'
                    else:
                        inv = inv.replace('_', ' ').replace('-', ' ').strip()
                        summary = f'({inv})' if inv else ''
                if summary:
                    head, tail = label.rsplit(' [', 1)
                    label = f'{head}: {summary} [{tail}'
            named.append((label, code))
        seen = {}
        for label, _ in named:
            seen[label.casefold()] = seen.get(label.casefold(), 0) + 1
        return [(f'{label[:-1]}, {code.strip()}]' if seen[label.casefold()] > 1 else label, code)
                for label, code in named]

    def bonus_text(self, q, row):
        """Lower-case tooltip lines of the bonuses a unique / set item / runeword comes with ("+(18 to 32) to
        stormlord"): what the creator's search matches besides the names. One row costs about a millisecond
        (the catalog tooltip), so it is kept; the creator window fills the cache in the background."""
        cache = self.__dict__.setdefault('_bonus_text', {})
        if (q, row) not in cache:
            d = self.data
            try:
                if q == 'runeword':
                    mods, code = d.runeword_mods[row], None
                else:
                    u = (d.uniques if q == 'unique' else d.set_items)[row]
                    mods, code = u['mods'], u['code']
                lines = self.mods_text([(m['prop'], m['param'], m['min'], m['max']) for m in mods], code)
            except Exception:
                lines = []
            cache[(q, row)] = '\n'.join(lines).lower()
        return cache[(q, row)]

    def _orb_table(self):
        """Median XL Sigma mysticorbs.bin: one 143-byte row per mystic orb, in the order of the 'myst' items of
        misc.txt. Row: name (32 bytes), Required Level added per orb (u8 @32), u16 string @33 ("(Armor Only)"),
        2 u16 item types it applies to @35, 2 u16 item types it never applies to @39 ('nomo'), max orbs of this kind
        per item (u8 @43), then 6 property blocks of 16 bytes from @45: u16 property, u16 -, i32 param, i32 min,
        i32 max (property 0xFFFF = none); u8 @141 / @142: item quality + 1 the include / exclude types are limited
        to (7 = rare: "Rare items only"; 0 = any). D2Sigma.dll D2MysticOrbs.cpp (FUN_1008f840) checks the types."""
        if hasattr(self, '_orbs'):
            return self._orbs
        self._orbs = {}
        d = self.data
        try:
            with open(os.path.join(d.folder, 'mysticorbs.bin'), 'rb') as f:
                raw = f.read()
            n = struct.unpack_from('<I', raw, 0)[0]
            rs = (len(raw) - 4) // n if n else 0
            codes = [b.code for b in d.bases.values()
                     if b.kind == 'misc' and 0 <= b.type < len(d.itypes) and d.itypes[b.type][0] == 'myst']
            if n and rs >= 61 and len(codes) == n:
                for i, code in enumerate(codes):
                    r = raw[4 + rs * i:4 + rs * (i + 1)]
                    mods = []
                    for k in range(6):
                        o = 45 + 16 * k
                        if o + 16 > len(r):
                            break
                        prop = struct.unpack_from('<H', r, o)[0]
                        if prop == 0xFFFF or prop >= len(d.props):
                            continue
                        param, lo, hi = struct.unpack_from('<iii', r, o + 4)
                        mods.append((prop, param, lo, hi))
                    inc = [t for t in struct.unpack_from('<HH', r, 35) if 0 < t < len(d.itypes)]
                    exc = [t for t in struct.unpack_from('<HH', r, 39) if 0 < t < len(d.itypes)]
                    self._orbs[code] = dict(name=r[:32].split(b'\0')[0].decode('latin1'), max=r[43], mods=mods,
                                            row=i, lvl=r[32], inc=inc, exc=exc,
                                            q_inc=r[141] if len(r) > 142 else 0, q_exc=r[142] if len(r) > 142 else 0)
        except (OSError, struct.error, ZeroDivisionError, AttributeError):
            self._orbs = {}
        return self._orbs

    def item_desc(self, code):
        """Lines of the item's in-game description (misc.txt spelldescstr, u16 string index at 0xB6 of the 1.13c
        misc record): the colour of a Mystic Dye, the bonus of a cycle or enchantment scroll, ... or []."""
        if not hasattr(self, '_desc_idx'):
            self._desc_idx = {}
            for r in _rows(self.data, 'misc'):
                c = r[128:132].decode('latin1')
                if c not in self._desc_idx and len(r) > 0xB7:
                    self._desc_idx[c] = struct.unpack_from('<H', r, 0xB6)[0]
        i = self._desc_idx.get(code)
        if not i:
            return []
        ent = self.data.strings.get(i)
        if not ent or ent[0] == 'dummy':
            return []
        out = []
        for line in str(ent[1]).replace('\\n', '\n').split('\n'):
            while 'ÿc' in line:
                k = line.index('ÿc')
                line = line[:k] + line[k + 3:]
            line = line.strip()
            if line and not line.startswith('%'):
                out.append(line)
        return out

    def desc_summary(self, code, limit=90):
        """Short text telling items of the same name apart: the description lines before the usage hint."""
        keep = []
        for line in self.item_desc(code):
            low = line.lower()
            if low.startswith(('right-click', 'right click', 'cube', '- transmute', 'transmute')):
                break
            keep.append(line)
        text = '; '.join(keep or self.item_desc(code)[:1])
        # "Free Attribute Points: %d": the game fills the number in from the character when it draws the item
        text = re.sub(r'\s*:?\s*%[+]?[ds]', '', text).strip()
        return text if len(text) <= limit else text[:limit - 3] + '...'

    def orb_effects(self, code):
        """(lines of text, max per item) of a mystic orb, or None for other items."""
        o = self._orb_table().get(code)
        if o is None:
            return None
        from mxl_tooltip import stat_lines
        lines = []
        for prop, param, lo, hi in o['mods']:
            try:
                st = Mod('orb', prop, param, lo, hi, self.data).stats(self.data)
                for ln in stat_lines(st, self.data, None):
                    text = ln[1] if isinstance(ln, (tuple, list)) else str(ln)
                    if text.strip():
                        lines.append(text.strip())
            except Exception:
                continue
        return lines, o['max']

    # ---- applying mystic orbs to an item (what right-clicking the orb onto it does in game)
    ORB_COUNTER, ORB_LEVELREQ = 290, 92

    def orb_fits(self, orb, code, quality):
        """Can this mystic orb (code) go on an item of this base / quality? The game's check: an exclude type
        ('nomo') of the item blocks it (unless limited to another quality), else one include type must match
        (limited to one quality for the rare-only orbs)."""
        o = self._orb_table().get(orb)
        if code and code not in self.data.bases:
            code = code.ljust(4)                         # a stash item's code comes without the padding
        if o is None or not code or code not in self.data.bases:
            return False
        anc = self.types_of(code)
        qv = QUALITY_ID.get(quality, 0) + 1
        if any(t in anc for t in o['exc']) and o['q_exc'] in (0, qv):
            return False
        return any(t in anc for t in o['inc']) and o['q_inc'] in (0, qv)

    def orbs_for(self, code, quality):
        """[(orb code, orb record)] of the mystic orbs that can go on this item, in the table's order."""
        return [(c, o) for c, o in self._orb_table().items() if o['max'] and self.orb_fits(c, code, quality)]

    def orbs_applied(self, totals):
        """{orb code: how many are on the item} from the counter stat 290 (param = row of mysticorbs.bin)."""
        by_row = {o['row']: c for c, o in self._orb_table().items()}
        out = {}
        for (sid, pa), v in totals.items():
            if sid == self.ORB_COUNTER and (pa or 0) in by_row and v > 0:
                out[by_row[pa or 0]] = out.get(by_row[pa or 0], 0) + v
        return out

    def orb_room(self, orb, totals):
        """How many more of this orb the item can take (its per-item max minus the ones already on it)."""
        o = self._orb_table().get(orb)
        return max(0, o['max'] - self.orbs_applied(totals).get(orb, 0)) if o else 0

    ORB_MULT = 289          # "Orb Effects Applied to this Item are Doubled / Quadrupled": the value is the factor

    def orb_deltas(self, orb, count, code=None, mult=1):
        """[(stat, param, value)] that `count` orbs add: each orb's property stats (a ranged one at its max),
        Required Level (stat 92) and the counter (stat 290, param = the orb's row). As in the saves: 5 x
        'MO - Max Dmg Armor' = +10 to stats 22/24/160, +20 to stat 92, stat 290 param 37 = 5. On a weapon (code)
        the min / max damage stats go only to the damage kinds the base has (a dagger: 21/22, no 2-hand / throw:
        test-druid's Dirk with 2 x 'MO - Max Damage' holds 22 = 12 only)."""
        o = self._orb_table().get(orb)
        if o is None or count <= 0:
            return []
        acc = {}
        skip = set()
        code = code.ljust(4) if code and code not in self.data.bases else code
        b = self.data.base(code) if code and code in self.data.bases else None
        if b is not None and b.kind == 'weapons':
            dmg = getattr(b, 'damage', None) or {}
            for kind, ids in (('one_hand', (21, 22)), ('two_hand', (23, 24)), ('throw', (159, 160))):
                if not any(dmg.get(kind) or ()):
                    skip.update(ids)
        for prop, param, lo, hi in o['mods']:
            for x in Mod('orb', prop, param, lo, hi, self.data).stats(self.data):
                if x.get('value') and x['id'] not in skip:
                    k = (x['id'], x.get('param') or None)
                    acc[k] = acc.get(k, 0) + x['value'] * count * max(1, mult)   # x2 / x4 items: the
                    # orb's own stats only - Required Level and the counter are not multiplied (samples: a sash
                    # with 289 = 2 and 5 x +5 Energy orbs holds +50 Energy, Required Level 25 orbs x 4 = 100)
        if o['lvl']:
            k = (self.ORB_LEVELREQ, None)
            acc[k] = acc.get(k, 0) + o['lvl'] * count
        acc[(self.ORB_COUNTER, o['row'] or None)] = count
        return [(k[0], k[1], v) for k, v in acc.items()]

    def orb_result(self, orb, count, totals, code=None):
        """New {(stat, param): value} of an item after `count` orbs (CreateError past the per-item max)."""
        if count > self.orb_room(orb, totals):
            raise CreateError(f'{orb}: at most {self.orb_room(orb, totals)} more on this item')
        out = {(k[0], k[1] or None): v for k, v in totals.items()}
        mult = totals.get((self.ORB_MULT, None), totals.get(self.ORB_MULT, 1)) or 1
        for sid, pa, v in self.orb_deltas(orb, count, code, mult):
            nv = out.get((sid, pa), 0) + v
            if nv:
                out[(sid, pa)] = nv
            else:
                out.pop((sid, pa), None)
        return out

    def describe(self, spec):
        d, q = self.data, spec['quality']
        if q == 'unique':
            return d.key(d.uniques[spec['row']]['name'])
        if q == 'set':
            return d.key(d.set_items[spec['row']]['name'])
        if q == 'runeword':
            return d.key(d.runewords[spec['row']][0])
        return self.display_name(spec['code']) if spec.get('code') else '?'
