"""Two item layouts of Median XL Sigma that the collector's reader (mxl_format.parse_item) did not know, which made it
lose its place in a stash ("FormatError: 'JM' expected at byte ..."):

1. Quality 9: HONORIFIC items ('tempered' is the game's internal name - string key StrLootFilterCfgTempered reads
   "Honorific"; this code keeps the key 'tempered'). Made in the cube: magic / rare weapon or armor + Mark of
   Infusion (cubemain rows with output quality 9) -> a blank item with a rare-style name, maximum sockets and
   stat 289 = 2 ("Orb Effects Applied to this Item are Doubled"). After the item header it holds only the two
   rare-name bytes (8 + 8 bits); there are no affix slots, every stat is in the stat list. The collector's own
   reader takes quality 9 for 'unknown', reads no name bytes and loses its place: a character or stash holding
   one honorific item did not open at all (the "honorific items crash the editor" report).
2. Weapons / armor whose item type is not under 'weap' / 'armo' (Staff of Herding, wd02). The game reads defense
   and durability only for items of those types (D2Common: item type 0x2d weap / 0x32 armo checks); for any other
   type these fields are not in the save.

install() replaces mxl_format.parse_item with the same reader plus these two cases (read_item_list and every
caller go through mxl_format.parse_item) and adds 'tempered' to the quality and name-colour tables."""
import mxl_format
from mxl_format import BitReader, Item, expect, read_stats, SET_UNIQUE_ID_BITS
import stat_ids as S

# save-format field widths of an item record (the d2s / stash item layout, the same in both profiles): these are
# limits of the file, not of the game - the game's own limits come from the tables (Creator.quantity_max,
# Creator.max_sockets, durability_cap, defense_range ...)
ILVL_BITS = 7
MAX_ILVL = (1 << ILVL_BITS) - 1                 # 127
QUANTITY_BITS = 9                               # stackable items: the quantity field
MAX_QUANTITY = (1 << QUANTITY_BITS) - 1         # 511
SOCKET_FIELD_BITS = 4                           # socketed items: the socket count field
SOCKET_FIELD_MAX = (1 << SOCKET_FIELD_BITS) - 1   # 15
SOCKETED_COUNT_BITS = 3                         # the count of items held in the sockets
MAX_SOCKETED = (1 << SOCKETED_COUNT_BITS) - 1   # 7

def socket_field_bits(data):
    """Socket count field in the selected game's item record."""
    if hasattr(data, 'socket_bits'):
        return data.socket_bits
    import mxl_profile
    if not mxl_profile.is_median():
        return (data.isc.get(194) or {}).get('bits') or SOCKET_FIELD_BITS
    return SOCKET_FIELD_BITS


TEMPERED = 'tempered'
WEAP, ARMO = 'weap', 'armo'


def _tag_index(data, tag):
    cache = data.__dict__.setdefault('_fix_tags', {})
    if tag not in cache:
        cache[tag] = next((i for i, t in enumerate(data.itypes) if t[0] == tag), None)
    return cache[tag]


def body_kind(data, code):
    """'armor' / 'weapons' only when the item type is really under 'armo' / 'weap' (what the game checks to read
    defense and durability), else 'misc'."""
    cache = data.__dict__.setdefault('_fix_kinds', {})
    if code in cache:
        return cache[code]
    base = data.base(code)
    kind = base.kind
    if kind in ('armor', 'weapons'):
        try:
            anc = data.type_ancestors(base.type) | data.type_ancestors(base.type2)
            tag = _tag_index(data, ARMO if kind == 'armor' else WEAP)
            if tag is not None and tag not in anc:
                kind = 'misc'
        except Exception:
            pass
    cache[code] = kind
    return kind


def _keep_raw(it, blob, br):
    """The item's own bytes ('JM' to its last byte, socketed items not included) as the ATTRIBUTE it._raw - not a
    key: nothing that copies, compares or lists the item's fields sees it. The creator's edit mode uses it to give
    back, untouched, everything its spec model does not hold (mxl_creator.Creator.spec_from_item)."""
    try:
        it._raw = bytes(blob[:2 + (br.pos + 7) // 8])
    except Exception:
        pass


def raw_of(it):
    """Bytes of a parsed item as they were read (None when unknown: a plain dict, a copy)."""
    return getattr(it, '_raw', None)


# Folder profiles (vanilla D2) only, set by mxl_profile: player ears, and items whose stat list does not fit the
# game tables (hacked "clone" characters written with another itemstatcost) are kept as opaque items - header
# fields shown, bytes kept as they are - instead of the whole file failing to open. Median XL: False, unchanged.
LENIENT = False


def _ear(it, br, blob):
    """Player ear (flag bit 16): class 3 bits, level 7 bits, name of 7-bit chars ending with 0; no item code."""
    ear = (br.read(3), br.read(7))
    s = ''
    for _ in range(16):
        c = br.read(7)
        if not c:
            break
        s += chr(c)
    it.ear = ear + (s,)                               # (class, level, name): an attribute, not an item field
    it['code'] = 'ear '
    it['name'] = f"{s}'s Ear" if s else 'Ear'
    it['socketed_count'] = 0
    it['has_sockets'] = False
    _keep_raw(it, blob, br)
    return it, br


def _ends_with_terminator(blob, end):
    """True when the bits just before byte `end` (after the zero padding) are a stat list end (0x1FF)."""
    if end < 4:
        return False
    v = int.from_bytes(bytes(blob[max(2, end - 4):end]), 'little')
    n = 8 * min(4, end - 2)
    k = n - v.bit_length()
    if v == 0 or k >= 8:
        return False
    return (v >> (n - k - 9)) & 0x1FF == 0x1FF if n - k >= 9 else False


def _opaque_end(blob, data, start_bit, socketed_count=0):
    """Byte offset (in blob, 'JM' at 0) where an item whose stats cannot be read ends: the first later 'JM' that
    follows a stat-list end (0x1FF + zero padding) and starts an item header of the same item version (or the
    corpse list after the last item, or the 'jf' / 'kf' section after a corpse / mercenary list's last item)."""
    b = bytes(blob)
    ver = int.from_bytes(b[2:8], 'little') >> 32 & 0x3FF
    i = 2 + start_bit // 8
    while True:
        hits = [k for k in (b.find(b'JM', i), b.find(b'jf', i), b.find(b'kf', i)) if k >= 0]
        if not hits:
            raise mxl_format.FormatError('item stats do not fit the game tables')
        i = min(hits)
        if (socketed_count and b[i:i + 2] == b'JM' and len(b) >= i + 14):
            header = int.from_bytes(b[i + 2:i + 14], 'little')
            child_code = (header >> 60 & 0xFFFFFFFF).to_bytes(4, 'little').decode('latin1')
            if header >> 42 & 7 == 6 and (header >> 32 & 0x3FF in (ver, 100, 101)) and child_code in data.bases:
                return i
        if _ends_with_terminator(b, i):
            if b[i:i + 2] != b'JM':
                return i
            same = int.from_bytes(b[i + 2:i + 8].ljust(6, b'\0'), 'little') >> 32 & 0x3FF == ver
            if same or b[i + 4:i + 6] in (b'jf', b'JM'):     # or the corpse list after the last item
                return i
        i += 1


def _trailing(blob, it, br):
    """Hacked saves may hold bytes after an item's last field (an ear name with junk after its end): the game
    finds the next item at its 'JM'. The item keeps those bytes (byte-identical save) when no 'JM' / 'jf' / 'kf' / end
    of file follows its end."""
    end = 2 + (br.pos + 7) // 8
    b = blob[end:end + 2]
    if len(b) < 2 or bytes(b) in (b'JM', b'kf', b'jf'):
        return it, br
    nxt = bytes(blob[end:end + 4096]).find(b'JM')
    if nxt > 0:
        br.pos = (end + nxt - 2) * 8
        _keep_raw(it, blob, br)
    return it, br


def parse_item(blob, data):
    if getattr(blob, 'beta_item', False) and not getattr(data, 'beta_items', False):
        raise mxl_format.FormatError('This item uses the 1.10s beta layout. Open a beta character to use it.')
    legacy = getattr(data, 'parse_legacy_item', None)
    if legacy is not None:
        return legacy(blob)
    try:
        it, br = _parse_item(blob, data)
        return _trailing(blob, it, br) if LENIENT else (it, br)
    except mxl_format.FormatError:
        if not LENIENT:
            raise
    br = BitReader(blob[2:])
    flags = br.read(32)
    it = Item()
    it['identified'] = bool(flags >> 4 & 1)
    it['has_sockets'] = bool(flags >> 11 & 1)
    it['ethereal'] = bool(flags >> 22 & 1)
    it['version'] = br.read(10)
    it['location'] = br.read(3)
    it['equipped'] = br.read(4)
    it['_pos_bit'] = br.pos
    it['x'] = br.read(4)
    it['y'] = br.read(4)
    it['panel'] = br.read(3)
    it['code'] = ''.join(chr(br.read(8)) for _ in range(4))
    try:
        it['name'] = data.base(it['code']).name
    except Exception:
        it['name'] = it['code'].strip()
    it['stats'] = []
    it['socketed_count'] = br.read(SOCKETED_COUNT_BITS)
    if not flags >> 21 & 1:
        it['id'] = br.read(32)
        it['ilvl'] = br.read(ILVL_BITS)
        it['quality'] = mxl_format.QUALITY.get(br.read(4), 'unknown')
    it.opaque = True                                  # stats not readable with these tables: never re-encoded
    if getattr(data, 'v109', False):
        it.v109 = True
    end = _opaque_end(blob, data, br.pos, it['socketed_count'] if it['has_sockets'] else 0)
    br.pos = (end - 2) * 8
    _keep_raw(it, blob, br)
    return it, br


def _read_early_trailer(br):
    if br.read(1):
        br.read(64)


def _parse_item(blob, data):
    expect(blob, 0, b'JM')
    br = BitReader(blob[2:])
    it = Item()
    early_lod = getattr(data, 'save_version', 96) in (87, 89)
    if getattr(data, 'v109', False):                  # legacy LoD record: mxl_v109.Data109
        it.v109 = True                                # (written back by mxl_char through mxl_v109.to_109)
    flags = br.read(32)
    it['identified'] = bool(flags >> 4 & 1)
    it['has_sockets'] = bool(flags >> 11 & 1)
    simple = bool(flags >> 21 & 1)
    it['ethereal'] = bool(flags >> 22 & 1)
    personalized = flags >> 24 & 1
    runeword = flags >> 26 & 1
    it['version'] = br.read(10)
    it['location'] = br.read(3)
    it['equipped'] = br.read(4)
    it['_pos_bit'] = br.pos
    it['x'] = br.read(4)
    it['y'] = br.read(4)
    it['panel'] = br.read(3)
    ear = bool(flags & 1 << 16)
    if ear and (simple if early_lod else LENIENT):
        it, br = _ear(it, br, blob)
        if early_lod:
            _read_early_trailer(br)
            _keep_raw(it, blob, br)
        return it, br
    code = ''.join(chr(br.read(8)) for _ in range(4))
    it['code'] = code
    base = data.base(code)
    kind, name = body_kind(data, code), base.name
    it['name'] = name
    it['stats'] = []
    if early_lod and (simple or flags & 1 << 25):
        it['socketed_count'] = 0
        if simple:
            if code == 'gld ':
                it['quantity'] = br.read(32 if br.read(1) else 12)
            _read_early_trailer(br)
        _keep_raw(it, blob, br)
        return it, br
    if simple:
        it['socketed_count'] = br.read(1)
        _keep_raw(it, blob, br)
        return it, br
    it['socketed_count'] = br.read(SOCKETED_COUNT_BITS)
    it['id'] = br.read(32)
    it['ilvl'] = br.read(ILVL_BITS)
    q = mxl_format.QUALITY.get(br.read(4), 'unknown')
    it['quality'] = q
    if br.read(1):
        it['image'] = br.read(3)
    if br.read(1):
        it['_auto_bit'] = br.pos
        it['auto_affix'] = br.read(11)
    if q in ('low', 'superior'):
        it['subquality'] = br.read(3)
    elif q == 'magic':
        it['prefix'] = br.read(11)
        it['suffix'] = br.read(11)
    elif q in ('set', 'unique'):
        it['set_unique_id'] = br.read(SET_UNIQUE_ID_BITS)
        if q == 'set' and getattr(data, 'v109', False):      # 1.09: a sets row, not a setitems row (mxl_v109)
            import mxl_v109
            it['set_unique_id'] = mxl_v109.set_item_row(data, it['set_unique_id'], code)
    elif q in ('rare', 'crafted'):
        it['rare_names'] = (br.read(8), br.read(8))
        it['rare_affixes'] = [br.read(11) if br.read(1) else None for _ in range(6)]
    elif q == TEMPERED:
        it['rare_names'] = (br.read(8), br.read(8))
    if early_lod and q == 'normal':
        types = data.type_ancestors(base.type) | data.type_ancestors(base.type2)
        if _tag_index(data, 'char') in types:
            br.read(12)
        if _tag_index(data, 'body') in types and _tag_index(data, 'play') not in types:
            br.read(10)
        if code in ('tbk ', 'ibk ', 'tsc ', 'isc '):
            br.read(5)
    if runeword:
        it['runeword'] = br.read(12)
        br.read(4)
    if personalized and not (early_lod and ear):
        s = ''
        while True:
            c = br.read(7)
            if not c:
                break
            s += chr(c)
        it['personalized_name'] = s
    if early_lod:
        if ear:
            _ear(it, br, blob)
        _read_early_trailer(br)
    else:
        if code in ('tbk ', 'ibk '):
            br.read(5)
        realm_bit = br.read(1)
        stamp_bits = getattr(data, 'realm_stamp_bits', 0)
        if realm_bit and stamp_bits:
            br.read(stamp_bits)
    if kind == 'armor':
        it['_def_bit'] = br.pos
        c = data.isc[S.DEFENSE]
        it['defense'] = br.read(c['bits']) - c['add']
    if kind in ('armor', 'weapons'):
        maxd = br.read(data.isc[S.MAX_DURABILITY]['bits'])
        it['max_durability'] = maxd
        if maxd != data.isc[S.MAX_DURABILITY]['add']:
            it['durability'] = br.read(data.isc[S.DURABILITY]['bits'])
    if early_lod and code == 'gld ':
        it['quantity'] = br.read(32 if br.read(1) else 12)
    if data.base(code).stack_max is not None:
        it['quantity'] = br.read(QUANTITY_BITS)
    old = getattr(data, 'v109', False)
    rs = data.read_stats if old else (lambda b, _d=data: read_stats(b, _d))
    if it['has_sockets']:
        it['sockets'] = br.read(socket_field_bits(data))
    set_lists = br.read(5) if q == 'set' else 0
    it['stats'] = rs(br)
    for i in range(5):
        if set_lists >> i & 1:
            it['set_stats_%d' % i] = rs(br)
    if runeword:
        it['stats_runeword'] = rs(br)
    _keep_raw(it, blob, br)
    return it, br


def _install_no_picture_icon():
    """An item of a type with picture variants (jewels, charms, rings, amulets) whose save has no picture field
    (the mock clones' size trick) is drawn by the game with its first variant; the host fell back to the base's own
    inv file (1.14d: the jewel's is the perfect diamond 'invgswe', the small charm's no charm at all)."""
    import mxl_gfx
    orig = mxl_gfx.base_icon_name
    if getattr(orig, '_no_pic', False):
        return

    def base_icon_name(it, data):
        if it.get('image') is None:
            try:
                t = data.base(it['code']).type
                var = data.itype_gfx[t] if 0 <= t < len(data.itype_gfx) else []
                if var and var[0]:
                    return var[0]
            except Exception:
                pass
        return orig(it, data)
    base_icon_name._no_pic = True
    mxl_gfx.base_icon_name = base_icon_name


def shown_sockets(it):
    """Sockets the game gives an item: the save's socket field plus its item_numsockets (194) lines (mock clones:
    field 3 + 194 = 4 -> 7 jewels). The host drew / printed only the field."""
    n = it.get('sockets') or 0
    for st in it.get('stats') or ():
        if st.get('id') == 194:
            n += st.get('value') or 0
    return n


def _with_shown_sockets(it):
    if not isinstance(it, dict) or not it.get('has_sockets'):
        return it
    n = shown_sockets(it)
    if n == (it.get('sockets') or 0):
        return it
    c = dict(it)
    c['sockets'] = n
    return c


def _install_socket_display():
    """Draw and print field + 194 sockets (display only: the item dict and the save keep the field)."""
    import sys
    import mxl_gfx
    import mxl_tooltip
    orig = mxl_gfx.icon_layers
    if getattr(orig, '_shown_sock', False):
        return

    native_positions = mxl_gfx.socket_positions

    def socket_positions(w, h, n, cell=mxl_gfx.ICON_CELL):
        from mxl_profile import is_median

        if is_median():
            return native_positions(w, h, n, cell)
        count = min(n, w * h)
        positions = native_positions(w, h, count, cell)
        if all(0 <= x <= (w - 1) * cell and 0 <= y <= (h - 1) * cell for x, y in positions):
            return positions
        # Small or modded item shapes can require more columns than the native layout uses.
        rows = (count + w - 1) // w
        positions = []
        for row in range(rows):
            columns = min(w, count - row * w)
            y = ((h - rows) * cell) // 2 + row * cell
            left = ((w - columns) * cell) // 2
            positions.extend((left + col * cell, y) for col in range(columns))
        return positions

    mxl_gfx.socket_positions = socket_positions

    def icon_layers(it, *a, **k):
        return orig(_with_shown_sockets(it), *a, **k)
    icon_layers._shown_sock = True
    for name in ('mxl_gfx', 'mxl_gui', 'mxl_library_gui'):
        m = sys.modules.get(name)
        if m is not None and getattr(m, 'icon_layers', None) is orig:
            m.icon_layers = icon_layers
    sec = mxl_tooltip.section_sockets

    def section_sockets(ctx):                  # the host's section with the shown count (it, data from ctx)
        it, data, out = ctx.it, ctx.data, []
        n = shown_sockets(it)
        if n:
            count = n
            if isinstance(it, dict) and dict.get(it, '_show_socket_fill'):
                count = f'{len(it.get("socketed") or ())}/{n}'
            out.append(mxl_tooltip.sockets_line(data, count))
        if it.get('ethereal'):
            out.append([(mxl_tooltip.BLUE, data.key('EtherealQ'))])
        return out
    mxl_tooltip.section_sockets = section_sockets
    for k, v in list(vars(mxl_tooltip).items()):     # a section table built at import keeps the old function
        if isinstance(v, (list, tuple)) and any(x is sec for x in v):
            nv = [section_sockets if x is sec else x for x in v]
            setattr(mxl_tooltip, k, type(v)(nv) if isinstance(v, tuple) else nv)
    _swap_in_defaults(mxl_tooltip, sec, section_sockets)


def _swap_in_defaults(mod, old, new):
    """item_tooltip(it, data, char, sections=(...)): the section table is the function's default argument, so
    patching the module name alone left the tooltip with the host's section ("Socketed (3)" with 7 jewels)."""
    for v in list(vars(mod).values()):
        dfl = getattr(v, '__defaults__', None)
        if not callable(v) or not dfl:
            continue
        nd, hit = [], False
        for x in dfl:
            if isinstance(x, (list, tuple)) and any(y is old for y in x):
                x = type(x)(new if y is old else y for y in x)
                hit = True
            nd.append(x)
        if hit:
            v.__defaults__ = tuple(nd)


# ---------------------------------------------------------------------------------------- source breakdowns
SOCKET_SOURCES = ('R', 'G', 'J')


def _install_no_socket_breakdown():
    """The host wrote a source breakdown after every stat a rune / gem / jewel adds to ("Damage +7365 (B:491 +
    J:491 + ...)"). The user finds it cluttered and the game shows only the total: the rune / gem / jewel entries are
    left out of the breakdown; the base / runeword entries and their roll ranges stay. Both profiles."""
    import sys
    import mxl_stat_text as st
    orig = st.stat_ranges
    if getattr(orig, '_no_sock', False):
        return

    def stat_ranges(it, data):
        res = orig(it, data)
        try:
            out = {}
            for k, v in res.items():
                sid = k[0] if isinstance(k, tuple) else k
                try:
                    reanimate = data.isc[sid].get('func') == 23
                except Exception:
                    reanimate = False
                if reanimate:
                    # "2% Reanimate as: <monster>": the row's min / max pick the MONSTER (param 3374-3381), the
                    # chance is fixed - as a value range it gave [3374-3381] and an item quality of -9576%
                    continue
                keep = [e for e in v if not (isinstance(e, tuple) and e and e[-1] in SOCKET_SOURCES)]
                if keep:
                    out[k] = keep
            return out
        except Exception:
            return res
    stat_ranges._no_sock = True
    _install_reanimate_range()
    for name in ('mxl_stat_text', 'mxl_tooltip', 'mxl_gui_detail', 'mxl_catalog_tooltip'):
        m = sys.modules.get(name)
        if m is not None and getattr(m, 'stat_ranges', None) is orig:
            m.stat_ranges = stat_ranges



def _install_reanimate_range():
    """Reanimate ("2% Reanimate as: <monster>", description func 23): the mod's min / max pick the MONSTER (param),
    the chance is fixed. The host's stat_range returned the monster range as the VALUE range: the Item Editor showed
    [3374-3381], a slider over it and an item quality of -9576%. No value range for those stats (both profiles)."""
    import sys
    try:
        import mxl_rules
    except Exception:
        return
    orig = getattr(mxl_rules, 'stat_range', None)
    if orig is None or getattr(orig, '_reanimate', False):
        return

    def stat_range(it, stat_id, data, *a, **k):
        try:
            if data.isc[stat_id].get('func') == 23:
                return None
        except Exception:
            pass
        return orig(it, stat_id, data, *a, **k)
    stat_range._reanimate = True
    for name in ('mxl_rules', 'mxl_edit', 'mxl_creator', 'mxl_stat_text', 'mxl_gui_detail'):
        m = sys.modules.get(name)
        if m is not None and getattr(m, 'stat_range', None) is orig:
            m.stat_range = stat_range

# ---------------------------------------------------------------------------------------- by-time stats
# itemstatcost op 6 ("by time"), descfunc 17 / 18: the 22 saved bits are 2 bits time of day, 10 bits the start and
# 10 bits the end value (low bits first), each stored with 256 added (value = field - 256: -256..767, so the bulk
# 4194303 is +767). The host printed the raw number ("+4194303 Absorbs Cold
# Damage"); the game prints the value and "(Increases Near Dawn)" etc. Periods 0-3: day, dusk, night, dawn.
TIME_KEYS = ('ModStre9e', 'ModStre9g', 'ModStre9d', 'ModStre9f')
TIME_DEFAULT = ('(Increases During Daytime)', '(Increases Near Dusk)', '(Increases During Nighttime)',
                '(Increases Near Dawn)')


def bytime_parts(v):
    """(period, start, end) of a by-time stat value."""
    v = int(v or 0)
    return v & 3, ((v >> 2) & 1023) - 256, ((v >> 12) & 1023) - 256


def bytime_text(c, v, data):
    return bytime_range_text(c, *bytime_parts(v), data)


def bytime_range_text(c, period, lo, hi, data):
    try:
        when = data.key(TIME_KEYS[period]) or TIME_DEFAULT[period]
    except Exception:
        when = TIME_DEFAULT[period]
    desc = (c.get('pos') or c.get('desc') or '').strip()
    pct = '%' if c.get('func') == 18 else ''
    num = f'{hi:+d}{pct}' if lo == hi else f'{min(lo, hi):+d}{pct} to {max(lo, hi)}{pct}'
    return f'{num} {desc} {when}'.strip()


def is_bytime(c):
    return bool(c) and c.get('op') == 6 and c.get('func') in (17, 18)


def _install_bytime_text():
    import mxl_stat_text as st
    orig = st._stat_text
    if getattr(orig, '_bytime', False):
        return

    def _stat_text(s, c, v, p, s1, data, *rest):
        try:
            if is_bytime(c):
                return bytime_text(c, v, data)
        except Exception:
            pass
        return orig(s, c, v, p, s1, data, *rest)
    _stat_text._bytime = True
    st._stat_text = _stat_text


def install():
    if getattr(mxl_format, '_sigma_fix', False):
        return
    mxl_format.QUALITY.setdefault(9, TEMPERED)
    mxl_format.parse_item = parse_item
    try:
        import mxl_tooltip
        nc = getattr(mxl_tooltip, 'NAME_COLOR', None)
        if isinstance(nc, dict) and 'crafted' in nc:
            nc.setdefault(TEMPERED, nc['crafted'])
    except Exception:
        pass
    try:
        _install_no_picture_icon()        # no-picture jewels / charms (mock clones): first variant, not the base file
    except Exception:
        pass
    try:
        _install_socket_display()         # field + item_numsockets (194) sockets, like the game
    except Exception:
        pass
    try:
        _install_no_socket_breakdown()    # no "(B:491 + J:491 + ...)" after the stats sockets add to
    except Exception:
        pass
    try:
        import mxl_statnames              # names for the skills without a skilldesc string ("skill #2064")
        mxl_statnames.install()
    except Exception:
        pass
    try:
        _install_bytime_text()            # by-time stats: "+767 Absorbs Cold Damage (Increases Near Dawn)"
    except Exception:
        pass
    try:
        import mxl_dmg_text               # tooltip damage lines with min > max ("145 to 132", "Adds 120-0")
        mxl_dmg_text.install()
    except Exception:
        pass
    try:
        import mxl_stash_order            # a replaced stash item keeps its place in the file (no-op edit = same file)
        mxl_stash_order.install()
    except Exception:
        pass
    try:
        import mxl_runes_fix              # runeword mods from all 13 runes.bin slots (the host read slots 2-8)
        mxl_runes_fix.install()
    except Exception:
        pass
    try:
        import mxl_char                   # the collector's character reader finds its sections by searching
        mxl_char.install_reader_fix()
    except Exception:
        pass
    mxl_format._sigma_fix = True
