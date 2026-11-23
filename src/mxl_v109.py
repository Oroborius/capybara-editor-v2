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

The editor reads these saves and writes the character values back in the 92 layout. Item records: the record codec
of mxl_creator (decode_item / encode_item) with a Data109 as data reads and writes them losslessly (stored ids,
skipped single skills, end id and padding kept); mxl_char holds a 1.09 character's items in the 1.10 layout
(to_110) and writes them back with to_109, which refuses (StoreError) what the 1.09 record cannot hold."""
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
def read_stats(b, gf, mask_bytes=2):
    """[[sid, None, value], ...] and the offset after the section ('if' expected there)."""
    mask = struct.unpack_from('<H', b, gf + 2)[0]
    p, out = gf + 2 + mask_bytes, []
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

    def __init__(self, data, version=VERSION):
        self._data = data
        self.save_version = version
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
        return read_item_stats(br, self._data, version=self.save_version)

    # the record codec of mxl_creator (decode_item / encode_item) with this object as data
    @property
    def socket_bits(self):
        return self.isc[194]['bits']

    def rec_read_stats(self, br):
        out, end = read_item_stats(br, self._data, keep=True, version=self.save_version)
        return Stats109(_rec_entry(st) for st in out).ended(end)

    def rec_write_stats(self, bw, stats):
        write_item_stats(bw, stats, self._data, self.save_version)

    @staticmethod
    def rec_read_end(br, rec):
        """The bits after the record's last field up to its last byte (hacked saves leave some set) go with its last
        stat list."""
        last = _last_list(rec)
        if isinstance(last, Stats109):
            last.pad = br.v >> br.pos & (1 << -br.pos % 8) - 1

    @staticmethod
    def rec_write_end(bw, rec):
        pad = getattr(_last_list(rec), 'pad', 0) or 0
        if pad >> -bw.pos % 8 == 0:
            bw.write(-bw.pos % 8, pad)


def _last_list(rec):
    if rec.get('flags', 0) & 1 << 26:
        return rec.get('stats_runeword')
    for i in range(4, -1, -1):
        if rec.get('set_mask', 0) >> i & 1:
            return rec.get(f'set_stats_{i}')
    return rec.get('stats')


class Stats109(list):
    """A decoded 1.09 stat list (mxl_creator.decode_item with a Data109): entries {id, param, value, old, ...};
    .end = the id that ended it in the file (0x1FF, or an id the reader stops at)."""
    end = 0x1FF
    pad = 0

    def ended(self, end):
        self.end = end
        return self


def _rec_entry(st):
    e = {k: st[k] for k in ('id', 'param', 'value', 'old', 'hidden', 'raw') if k in st}
    if 'parts' in st:
        e['parts'] = [_rec_entry(p) for p in st['parts']]
    return e


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


def _entry(data, sid, param, value, pos, old=None):
    c = data.isc.get(sid, {})
    return {'id': sid, 'param': param, 'value': value, 'pos': pos, 'desc': c.get('desc', ''),
            'bits': c.get('bits', 0), 'add': c.get('add', 0), 'old': sid if old is None else old}


def _stat_widths(data, version):
    widths = _widths(data)
    if version >= 90:
        return widths
    widths = dict(widths)
    for sid, bits in ((23, 5), (24, 6)):
        widths[sid] = bits, widths[sid][1]
    widths.update({74: (5, 10), 79: (8, 20), 80: (7, 20)})
    if version < 88:
        for sid in (93, 96, 99, 102, 105):
            widths[sid] = 6, widths[sid][1]
    return widths


def read_item_stats(br, data, keep=False, version=VERSION):
    """One stat list of a version 92 item record, as the 1.14d reader does it: ends at 0x1FF, or (without a
    failure) at an id with no itemstatcost row. Entries use the 1.10 ids / layers, 'old' = the stored id.
    keep (the record codec): also the single skills the game skips (level 0 / above the item_singleskill range,
    marked 'hidden'), a skill tab level above 7 in 'raw', and the id that ended the list: (list, end id)."""
    w = _stat_widths(data, version)
    out = []
    prev = None
    while True:
        pos = br.pos
        sid = br.read(9)
        if sid == 0x1FF or sid not in w or sid == 0 and prev == 0:
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
            out.append(_entry(data, 83, _CLASS_SKILL_LAYER[sid], br.read(3), pos, sid))
        elif sid in _SINGLE_SKILL:
            v = br.read(14)
            skill, level = v & 0x1FF, v >> 9
            top = (1 << data.isc.get(107, {}).get('bits', 3)) - 1
            if 0 < level <= top:
                out.append(_entry(data, 107, skill, level, pos, sid))
            elif keep:
                out.append(dict(_entry(data, 107, skill, level, pos, sid), hidden=True))
        elif sid == 134 and version < 90:
            raw = br.read(16)
            out.append(dict(_entry(data, sid, None, 1, pos), raw=raw))
        elif sid == 126:
            out.append(_entry(data, 126, 1, br.read(4), pos))
        elif 188 <= sid <= 193:
            v = br.read(10)
            n = v & 0x1F
            out.append(_entry(data, 188, n % 3 + 8 * (n // 3), min(v >> 5, 7), pos, sid))
            if keep and v >> 5 > 7:
                out[-1]['raw'] = v >> 5
        elif 195 <= sid <= 203:
            v = br.read(21)
            base = 195 + (sid - 195) // 3 * 3
            out.append(_entry(data, base, 64 * (v & 0x1FF) + (v >> 9 & 0x1F), v >> 14, pos, sid))
        elif 204 <= sid <= 213:
            v = br.read(30)
            out.append(_entry(data, 204, ((v & 0x1FF) << 6) + (v >> 9 & 0x1F), (v >> 14 & 0xFF) + 256 * (v >> 22),
                              pos, sid))
        else:
            out.append(_entry(data, _FAST_TWIN.get(sid, sid), None, isc(sid), pos, sid))
    lay = {st['param']: st['value'] for st in out if st['id'] == 83}
    x = lay.get(0, 0)
    if x > 0 and all(lay.get(k) == x for k in (1, 2, 3, 4)):      # +x to all skills: in read order where it began
        parts = [st for st in out if st['id'] == 83]
        k = out.index(parts[0])
        out = [st for st in out[:k] if st['id'] != 83] + [_entry(data, 127, None, x, parts[0]['pos'], 83)] + \
            [st for st in out[k:] if st['id'] != 83]
        out[k]['parts'] = parts
    return (out, sid) if keep else out


# ------------------------------------------------------------------ item writer
_LAYER_STORED = {v: k for k, v in _CLASS_SKILL_LAYER.items()}
_PACKED = (set(_CLASS_SKILL_LAYER) | set(_SINGLE_SKILL) | set(_FAST_TWIN) | set(range(188, 194)) |   # stored ids
           set(range(195, 214))) - {83, 107, 195, 198, 201, 204}      # the 1.09 reader takes as another stat
_FOLLOWER = {f: lead for lead, fs in _GROUPS.items() for f in fs}


def _stored(data, stats, version):
    """[(stored id, [(bits, raw), ...])] of a stat list given with the 1.10 ids (inverse of read_item_stats).
    An entry's 'old' (the stored id it was read with) picks the old form again when it still fits."""
    w = _stat_widths(data, version)

    def fail(st, why=''):
        from mxl_creator import StoreError
        from mxl_lang import T
        raise StoreError(T('ch.err.old_item_stat', '1.09 item: stat {stat} = {value} cannot be stored{why}',
                           stat=f"{st['id']}" + (f" ({st.get('param')})" if st.get('param') else ''),
                           value=st.get('value'), why=why))

    def plain(sid, st):
        bits, add = w.get(sid, (0, 0))
        raw = (st.get('value') or 0) + add
        if not bits or not 0 <= raw < 1 << bits:
            fail(st, f': 1.09 holds {-add} to {(1 << bits) - 1 - add}' if bits else ': no 1.09 save field')
        return bits, raw

    def oldid(st, ok, default):
        o = st.get('old')
        return o if o in ok else default

    by_id = {}
    for st in stats:
        by_id.setdefault(st['id'], st)
    out = []
    for st in stats:
        sid, prm, val = st['id'], st.get('param') or 0, st.get('value') or 0
        if sid in _FOLLOWER and _FOLLOWER[sid] in by_id:
            continue                                    # written with its lead
        if st.get('hidden'):                            # a single skill the game skips: kept as it was
            out.append((st['old'], [(14, prm | val << 9)]))
        elif sid == 127 and st.get('parts'):
            for p in st['parts']:
                out += _stored(data, [dict(p, value=val) if p['param'] in range(5) else p], version)
        elif sid in _GROUPS:
            fields = [plain(sid, st)]
            for f in _GROUPS[sid]:
                fields.append(plain(f, by_id.get(f, {'id': f, 'value': 0})))
            out.append((sid, fields))
        elif sid == 83:
            if prm not in _LAYER_STORED or not 0 <= val < 8:
                fail(st)
            out.append((_LAYER_STORED[prm], [(3, val)]))
        elif sid == 107:
            top = (1 << data.isc.get(107, {}).get('bits', 3)) - 1
            if not 0 <= prm < 512 or not 0 < val <= min(top, 31):
                fail(st)
            out.append((oldid(st, _SINGLE_SKILL, 107), [(14, prm | val << 9)]))
        elif sid == 134 and version < 90:
            if val != 1:
                fail(st)
            out.append((sid, [(16, st.get('raw', 0))]))
        elif sid == 126:
            if prm != 1 or not 0 <= val < 16:
                fail(st, ': 1.09 holds +elemental skills only')
            out.append((126, [(4, val)]))
        elif sid == 188:
            cls, tree = divmod(prm, 8)
            if tree > 2 or not 0 <= cls * 3 + tree < 32 or not 0 <= val < 8:
                fail(st)
            if st.get('raw') is not None and min(st['raw'], 7) == val:
                val = st['raw']                         # a level above 7 the game reads as 7
            out.append((oldid(st, range(188, 194), 188), [(10, cls * 3 + tree | val << 5)]))
        elif sid in (195, 198, 201):
            skill, lvl = divmod(prm, 64)
            if skill >= 512 or lvl >= 32 or not 0 <= val < 128:
                fail(st)
            out.append((oldid(st, range(sid, sid + 3), sid), [(21, skill | lvl << 9 | val << 14)]))
        elif sid == 204:
            skill, lvl = divmod(prm, 64)
            cur, mx = val & 0xFF, val >> 8
            if skill >= 512 or lvl >= 32 or not 0 <= mx < 256:
                fail(st)
            out.append((oldid(st, range(204, 214), 204), [(30, skill | lvl << 9 | cur << 14 | mx << 22)]))
        else:
            if prm and data.isc.get(sid, {}).get('param') or sid in _PACKED:
                fail(st, ': no 1.09 form')
            o = st.get('old')
            if o is not None and _FAST_TWIN.get(o) == sid:    # an old "fast" twin: its own width, else the id's
                bits, add = w.get(o, (0, 0))
                if 0 <= val + add < 1 << bits:
                    out.append((o, [(bits, val + add)]))
                    continue
            out.append((sid, [plain(sid, st)]))
    return out


def write_item_stats(bw, stats, data, version=VERSION):
    """One stat list in the version 92 layout, in the given order (the game keeps none there), then 0x1FF (or the
    id a decoded list ended at: Stats109.end)."""
    for sid, fields in _stored(data, stats, version):
        bw.write(9, sid)
        for bits, raw in fields:
            bw.write(bits, raw)
    bw.write(9, getattr(stats, 'end', 0x1FF))


# ------------------------------------------------------------------ 1.09 <-> 1.10 record layout
# The character editor keeps a 1.09 character's items in the 1.10 layout (what the Creator, the clipboard, the
# import and every item menu read and write with the plain game data) and writes them back as 1.09 records when
# saving. hints: {(item id, 1.10 stat list (canonical)) -> its decoded 1.09 list}, filled by to_110: a list an
# item still holds is encoded again from its 1.09 form (order, stored ids, skipped single skills, end id, padding).
_RUNEWORD = 1 << 26
_SOCKETED = 1 << 11


def _list_keys(rec):
    keys = ['stats'] + [f'set_stats_{i}' for i in range(5) if rec.get('set_mask', 0) >> i & 1]
    return [k for k in keys + (['stats_runeword'] if rec['flags'] & _RUNEWORD else []) if k in rec]


def _canon(stats):
    acc = {}
    for st in stats:
        k = (st['id'], st.get('param') or 0)
        acc[k] = acc.get(k, 0) + (st.get('value') or 0)
    return tuple(sorted(acc.items()))


def _records(blob, data):
    """The records of an item and its socketed items; the blob must hold exactly these."""
    import mxl_creator as C
    rec, p = C.decode_item(bytes(blob), data)
    out = [rec]
    for _ in range(rec.get('socketed_count', 0) if rec['flags'] & _SOCKETED else 0):
        r, n = C.decode_item(bytes(blob[p:]), data)
        out.append(r)
        p += n
    if p != len(blob):
        raise C.CreateError(f'{len(blob) - p} bytes after the item')
    return out


def _set_row_109(data, row, code):
    """The sets row a 1.09 record stores for setitems row `row` (inverse of set_item_row); None: not storable."""
    sets = unwrap(data).set_items
    if 0 <= row < len(sets) and sets[row].get('code') == code:
        s = sets[row].get('set_id')
        if s is not None and set_item_row(data, s, code) == row:
            return s
    if set_item_row(data, row, code) == row and not (0 <= row < len(sets) and sets[row].get('code') == code):
        return row                                    # read with no member of that base: kept as it was
    return None


def _check_early_record(rec, version):
    # Affix and special-item metadata depend on the historical table order.
    if version < VERSION and (rec.get('quality') not in (None, 'normal')
                               or rec.get('auto_affix') is not None
                               or rec.get('realm_bit') or rec['flags'] & 1 << 21 and rec.get('socketed_count')
                               or rec['flags'] & (_RUNEWORD | 1 << 16 | 1 << 24 | 1 << 25)
                               or rec['code'] in ('gld ', 'tbk ', 'ibk ', 'nec ')):
        from mxl_creator import StoreError
        from mxl_early_save import VERSIONS
        raise StoreError(f"Diablo II {VERSIONS[version]}: this item's layout is read-only.")


def to_110(blob, data, hints=None, version=VERSION):
    """Bytes of a 1.09 item (+ its socketed items) in the 1.10 layout of the game data. CreateError: a value the
    1.10 layout cannot hold (the item then stays as read)."""
    import mxl_creator as C
    d9 = Data109(unwrap(data), version)
    out = b''
    for rec in _records(blob, d9):
        _check_early_record(rec, version)
        r10 = dict(rec)
        if rec.get('quality') == 'set':
            r10['set_unique_id'] = set_item_row(data, rec['set_unique_id'], rec['code'])
        for k in _list_keys(rec):
            r10[k] = [{'id': st['id'], 'param': st['param'], 'value': st['value']} for st in rec[k]
                      if not st.get('hidden')]
        b10 = C.encode_item(r10, unwrap(data))
        if hints is not None:
            back = C.decode_item(b10, unwrap(data))[0]
            for k in _list_keys(rec):
                hints[rec.get('id'), _canon(back[k])] = rec[k]
        out += b10
    return out


def to_109(blob, data, hints=None, version=VERSION):
    """Bytes of an item (+ its socketed items) in the 1.10 layout as 1.09 records. Checked by reading them back:
    StoreError / CreateError (message for the user) when the 1.09 record cannot hold the item as it is."""
    import mxl_creator as C
    from mxl_lang import T
    data = unwrap(data)
    d9 = Data109(data, version)
    out = b''
    recs = _records(blob, data)
    for rec in recs:
        _check_early_record(rec, version)
        r9 = dict(rec)
        if rec.get('quality') == 'set':
            r9['set_unique_id'] = _set_row_109(data, rec['set_unique_id'], rec['code'])
            if r9['set_unique_id'] is None:
                raise C.StoreError(T('ch.err.old_item_set', '1.09 item: this set item has no 1.09 form (another '
                                     'member of its set has the same base)'))
        for k in _list_keys(rec):
            c = _canon(rec[k])
            h = (hints or {}).get((rec.get('id'), c))
            r9[k] = h if h is not None else rec[k]
        out += C.encode_item(r9, d9)
    try:
        back = to_110(out, data, version=version)
    except C.CreateError:
        back = None
    same = back == bytes(blob)
    if back is not None and not same:                 # a blob the game / Mock Mode wrote: in this codec's form
        try:
            same = back == b''.join(C.encode_item(r, data) for r in recs)
        except C.CreateError:
            pass
    if not same:                                      # the 1.09 reader would see something else
        diff = []
        if back is not None:
            for a, b in zip(recs, _records(back, data)):
                for k in _list_keys(a):
                    diff += sorted({i for (i, _p), _v in set(_canon(a[k])) ^ set(_canon(b.get(k, [])))})
                diff += [f for f in ('defense', 'max_durability', 'durability', 'sockets', 'quantity')
                         if a.get(f) != b.get(f)]
        raise C.StoreError(T('ch.err.old_item', '1.09 item: {what} cannot be stored in a 1.09 record',
                             what=', '.join(f'stat {x}' if isinstance(x, int) else x for x in diff) or 'it'))
    return out


class Raw109(bytes):
    """A 1.09 item kept as read (a value the 1.10 layout cannot hold, e.g. a hacked clone's maxed stat): it can be
    moved (moved_raw) or deleted; mxl_creator.decode_item refuses it (no edit through the 1.10 item code)."""
    v109_raw = True


def moved_raw(blob, fields):
    """Raw109 copy of `blob` with header fields (location, equipped, x, y, panel) changed; the same bit
    positions in both layouts. Socketed items unchanged."""
    v = int.from_bytes(blob[2:], 'little')
    for name, pos, n in (('location', 42, 3), ('equipped', 45, 4), ('x', 49, 4), ('y', 53, 4), ('panel', 57, 3)):
        if name in fields:
            x = fields[name]
            if not 0 <= x < 1 << n:
                raise ValueError(f'{name} = {x}')
            v = v & ~((1 << n) - 1 << pos) | x << pos
    return Raw109(blob[:2] + v.to_bytes(len(blob) - 2, 'little'))
