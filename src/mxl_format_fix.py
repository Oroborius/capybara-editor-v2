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


def _opaque_end(blob, data, start_bit):
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
    it['socketed_count'] = br.read(3)
    if not flags >> 21 & 1:
        it['id'] = br.read(32)
        it['ilvl'] = br.read(7)
        it['quality'] = mxl_format.QUALITY.get(br.read(4), 'unknown')
    it.opaque = True                                  # stats not readable with these tables: never re-encoded
    end = _opaque_end(blob, data, br.pos)
    br.pos = (end - 2) * 8
    _keep_raw(it, blob, br)
    return it, br


def _parse_item(blob, data):
    expect(blob, 0, b'JM')
    br = BitReader(blob[2:])
    it = Item()
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
    if LENIENT and flags >> 16 & 1:
        return _ear(it, br, blob)
    code = ''.join(chr(br.read(8)) for _ in range(4))
    it['code'] = code
    base = data.base(code)
    kind, name = body_kind(data, code), base.name
    it['name'] = name
    it['stats'] = []
    if simple:
        it['socketed_count'] = br.read(1)
        _keep_raw(it, blob, br)
        return it, br
    it['socketed_count'] = br.read(3)
    it['id'] = br.read(32)
    it['ilvl'] = br.read(7)
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
    elif q in ('rare', 'crafted'):
        it['rare_names'] = (br.read(8), br.read(8))
        it['rare_affixes'] = [br.read(11) if br.read(1) else None for _ in range(6)]
    elif q == TEMPERED:
        it['rare_names'] = (br.read(8), br.read(8))
    if runeword:
        it['runeword'] = br.read(12)
        br.read(4)
    if personalized:
        s = ''
        while True:
            c = br.read(7)
            if not c:
                break
            s += chr(c)
        it['personalized_name'] = s
    if code in ('tbk ', 'ibk '):
        br.read(5)
    br.read(1)
    if kind == 'armor':
        it['_def_bit'] = br.pos
        c = data.isc[S.DEFENSE]
        it['defense'] = br.read(c['bits']) - c['add']
    if kind in ('armor', 'weapons'):
        maxd = br.read(data.isc[S.MAX_DURABILITY]['bits'])
        it['max_durability'] = maxd
        if maxd != data.isc[S.MAX_DURABILITY]['add']:
            it['durability'] = br.read(data.isc[S.DURABILITY]['bits'])
    if data.base(code).stack_max is not None:
        it['quantity'] = br.read(9)
    if it['has_sockets']:
        it['sockets'] = br.read(4)
    set_lists = br.read(5) if q == 'set' else 0
    it['stats'] = read_stats(br, data)
    for i in range(5):
        if set_lists >> i & 1:
            it['set_stats_%d' % i] = read_stats(br, data)
    if runeword:
        it['stats_runeword'] = read_stats(br, data)
    _keep_raw(it, blob, br)
    return it, br


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
        import mxl_statnames              # names for the skills without a skilldesc string ("skill #2064")
        mxl_statnames.install()
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
