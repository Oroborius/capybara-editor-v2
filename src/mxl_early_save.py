"""Diablo II save versions before 1.09.

Header and record fields follow the d2s-legacy and bitstream-legacy specs,
with the Classic record sizes (including two trailing bytes) verified against
1.00 and 1.06b saves and the 1.00 layout checked against Hero Editor.
"""
import struct
from random import getrandbits

VERSIONS = {71: 'Classic 1.00–1.06', 87: '1.07', 89: '1.08'}
HEADER_END = 130
QUEST_OFF = HEADER_END
WP_OFF = QUEST_OFF + 298
NPC_OFF = WP_OFF + 80
STATS_OFF = NPC_OFF + 52
WP_END_CLASSIC = 30


def read_header(raw, quest_off):
    """Expose the common fields at the editor's usual offsets."""
    from mxl_format import FormatError
    if (raw[32:34] != b'\x82\0' or raw[QUEST_OFF:QUEST_OFF + 4] != b'Woo!'
            or raw[WP_OFF:WP_OFF + 2] != b'WS' or raw[NPC_OFF:NPC_OFF + 2] != b'\x01w'
            or raw[STATS_OFF:STATS_OFF + 2] != b'gf'):
        raise FormatError('Unexpected pre-1.09 character layout')
    status = struct.unpack_from('<I', raw, 24)[0]
    head = bytearray(quest_off)
    head[:8] = raw[:8]
    head[0x14:0x24] = raw[8:24]
    head[0x24] = status & 0xFF
    head[0x25] = (status >> 8) & 0x1F
    head[0x28] = raw[34]
    head.extend(raw[QUEST_OFF:STATS_OFF])
    return head


def build_header(raw, head, quest_off):
    out = bytearray(raw[:HEADER_END])
    out[8:24] = head[0x14:0x24]
    status = struct.unpack_from('<I', raw, 24)[0]
    struct.pack_into('<I', out, 24, (status & ~0x1FFF) | head[0x24] | head[0x25] << 8)
    out[34] = head[0x28]
    out.extend(head[quest_off:])
    return out


def classic_codes(data):
    """Codes indexed by the selected game's version-zero item table order."""
    cache = data.__dict__
    if '_classic_codes' not in cache:
        cache['_classic_codes'] = [
            r[0x80:0x84].decode('latin1')
            for table in ('weapons', 'armor', 'misc') for r in data._rows(table)
            if r[0xF6:0xF8] == b'\0\0'
        ]
    return cache['_classic_codes']


_CODED = 0x100000
_SIMPLE = 0x200000
_EAR = 0x10000
_POSITION = ((3, 'location'), (5, 'x'), (3, 'y'))
_PAGE = ((8, 'page'),)


def _classic_layout(flags):
    """Fields following the flags, and the total record size including JM."""
    coded = bool(flags & _CODED)
    simple = coded and bool(flags & _SIMPLE)
    ear = bool(flags & _EAR)
    fields = ((10, 'version'),) if coded else ()
    if coded and not simple:
        fields += ((32, 'code_bits'),)
    fields += ((5, 'equipped'),)
    if simple:
        fields += _POSITION + _PAGE
        if not ear:
            fields += ((32, 'code_bits'),)
        return fields, 26 if ear else 15
    if ear and not coded:
        return fields + ((10, 'ear_prefix'),) + _POSITION + ((10, 'ear_middle'),) + _PAGE, 27
    fields += ((3, 'socketed_count'), (12, 'ilvl'))
    if not coded:
        fields += ((10, 'row'),)
    fields += ((3, 'location'), (4, 'quality_id'), (20, 'quantity'),
               (8, 'durability'), (8, 'max_durability'), (5, 'x'), (3, 'y'),
               (10, 'quality_index'), (32, 'id'), (32, 'seed')) + _PAGE
    return fields, 31 if coded else 27


def is_original(blob):
    return not bool(struct.unpack_from('<I', blob, 2)[0] & _CODED)


def decode_classic(blob):
    """Decode one native record, including the reserved bits after its fields."""
    from mxl_format import BitReader, FormatError, expect

    expect(blob, 0, b'JM')
    if len(blob) < 6:
        raise FormatError('Truncated Classic item')
    br = BitReader(blob[2:])
    flags = br.read(32)
    fields, size = _classic_layout(flags)
    if len(blob) < size:
        raise FormatError('Truncated Classic item')
    rec = {name: br.read(width) for width, name in fields}
    rec['flags'] = flags
    rec['reserved'] = br.read((size - 2) * 8 - br.pos)
    return rec, size


def encode_classic(rec):
    """Encode one native record from its fields."""
    from mxl_creator import BitWriter, CreateError, StoreError

    bw = BitWriter()
    fields, size = _classic_layout(rec['flags'])
    bw.write(32, rec['flags'])
    for width, name in fields:
        try:
            bw.write(width, rec.get(name, 0))
        except CreateError as ex:
            raise StoreError(f'Classic item: {name} does not fit in {width} bits') from ex
    bw.write((size - 2) * 8 - bw.pos, rec.get('reserved', 0))
    return b'JM' + bw.bytes()


def classic_item(blob, data):
    from mxl_format import BitReader, Item, QUALITY
    from mxl_format_fix import _keep_raw

    rec, size = decode_classic(blob)
    flags = rec['flags']
    if flags & _EAR:
        code = 'ear '
    elif 'code_bits' in rec:
        code = rec['code_bits'].to_bytes(4, 'little').decode('latin1')
    else:
        codes = classic_codes(data)
        code = codes[rec['row']] if rec['row'] < len(codes) else '????'
    it = Item()
    it.update({key: rec[key] for key in ('equipped', 'location', 'x', 'y', 'id', 'durability',
                                        'max_durability') if key in rec})
    it.update(code=code, stats=[], version=rec.get('version', 0), identified=bool(flags & 0x10),
              socketed_count=rec.get('socketed_count', 0), panel=_panel(rec['page']),
              has_sockets=bool(flags & 0x800 or rec.get('socketed_count')), ethereal=False)
    if 'quality_id' in rec:
        it['quality'] = QUALITY.get(rec['quality_id'], 'unknown')
        it['ilvl'] = rec['ilvl'] & 0xFF
    if rec.get('quantity'):
        it['quantity'] = rec['quantity']
    it.opaque = True
    try:
        it['name'] = data.base(code).name
    except (KeyError, AttributeError):
        it['name'] = code.strip()
    br = BitReader(blob[2:])
    br.pos = (size - 2) * 8
    _keep_raw(it, blob, br)
    return it, br


def _panel(page):
    return 0 if page == 255 else page + 1


def _page(panel):
    return panel - 1 if panel else 255


def to_editor(it, rec, data):
    """Project the editable fields of a native normal item into the Creator layout."""
    import mxl_creator as C

    code = it['code']
    if (code not in data.bases or it['has_sockets'] or rec['flags'] & _EAR
            or rec.get('quality_id', 2) != 2):
        raise C.StoreError(ClassicRaw.edit_reason)
    base = data.base(code)
    flags = C.FLAG_ALWAYS | (C.FLAG_IDENTIFIED if it['identified'] else 0)
    editor = {key: it[key] for key in ('code', 'location', 'equipped', 'x', 'y', 'panel')}
    if 'quality_id' not in rec:
        editor['flags'] = flags | C.FLAG_SIMPLE
    else:
        editor.update(flags=flags, quality='normal', ilvl=it['ilvl'], id=it['id'], stats=[])
        kind = C.body_kind(data, code)
        if kind in ('armor', 'weapons'):
            editor['max_durability'] = it['max_durability'] + data.isc[73]['add']
            editor['durability'] = it['durability'] + data.isc[72]['add']
        if kind == 'armor':
            # The seed determines the actual roll. The Creator record needs a baseline field.
            editor['defense'] = base.def_range[0]
        if base.stack_max is not None:
            editor['quantity'] = rec['quantity']
    return C.encode_item(editor, data)


class ClassicClipboard(bytes):
    """Creator bytes carrying the seed and other native fields for same-layout paste."""

    def __new__(cls, blob, template):
        obj = super().__new__(cls, blob)
        obj.template = template
        return obj

    def matches_layout(self, original):
        return original == (not bool(self.template[1]['flags'] & _CODED))


def from_editor(blob, data, original, template=None):
    """Encode a Creator record, preserving native fields on edits to an existing item."""
    import mxl_creator as C

    def refuse(field):
        raise C.StoreError(f'Classic item: {field} cannot be stored in a version 71 record')

    if blob[:2] == b'JM' and len(blob) >= 6 and struct.unpack_from('<I', blob, 2)[0] & _EAR:
        refuse('ear data')
    rec, size = C.decode_item(blob, data)
    code = rec['code']
    codes = classic_codes(data)
    if code not in codes:
        refuse(f'item base {code.strip()!r}')
    native = None
    if template is not None:
        native_code, native_rec = template
        if code == native_code and ('quality_id' not in native_rec or rec.get('id') == native_rec.get('id')):
            native = native_rec
    flags = rec['flags']
    for flag, name in ((C.FLAG_SOCKETED, 'sockets'), (C.FLAG_ETHEREAL, 'ethereal'),
                       (C.FLAG_RUNEWORD, 'runewords'), (C.FLAG_PERSONALIZED, 'personalization')):
        if flags & flag:
            refuse(name)
    if rec.get('socketed_count') or size != len(blob):
        refuse('socketed items or extra item data')
    if rec.get('stats'):
        refuse('stat ' + ', '.join(str(st['id']) for st in rec['stats']))
    if rec.get('quality', 'normal') != 'normal':
        refuse(f"{rec['quality']} quality and its generated modifiers")
    if rec.get('auto_affix') is not None or rec.get('realm_bit') or rec.get('tome_bits'):
        refuse('automagic, realm or tome metadata')
    if rec.get('location') not in (0, 1, 2) or rec['panel'] not in (0, 1, 4, 5):
        refuse('item location')
    if rec['equipped'] > 10:
        refuse('alternate weapon slots')

    simple = bool(flags & C.FLAG_SIMPLE)
    if native is None:
        native_flags = 0x2000 if original else 0x182000 | (_SIMPLE if simple else 0)
        native_flags |= flags & 0x20000  # starter gear
        item = dict(flags=native_flags, quality_id=2, row=codes.index(code),
                    code_bits=int.from_bytes(code.encode('latin1'), 'little'),
                    id=rec['id'] if 'id' in rec else getrandbits(32), seed=getrandbits(32))
    else:
        item = dict(native)
    item['flags'] = (item['flags'] & ~C.FLAG_IDENTIFIED) | (flags & C.FLAG_IDENTIFIED)
    item.update({key: rec[key] for key in ('location', 'equipped', 'x', 'y')})
    if rec['location'] == 1:
        item['x'] = (native['x'] if native is not None and native['location'] == 1
                     and native['equipped'] == rec['equipped'] else 0)
    item['page'] = _page(rec['panel'])
    if native is not None and simple == ('quality_id' in native):
        refuse('changing the native compact layout')
    if not simple:
        item['ilvl'] = (item.get('ilvl', 0) & ~0xFF) | rec['ilvl']
        for key in ('id', 'quantity'):
            if key in rec:
                item[key] = rec[key]
        if 'max_durability' in rec:
            item['max_durability'] = rec['max_durability'] - data.isc[73]['add']
            item['durability'] = rec.get('durability', data.isc[72]['add']) - data.isc[72]['add']
        if 'defense' in rec and (native is None or rec['defense'] != data.base(code).def_range[0]):
            lo, hi = data.base(code).def_range
            if lo != hi or rec['defense'] != lo:
                refuse('an explicit defense roll')
        if rec.get('image') is not None:
            refuse('an explicit item graphic')
    elif native is None:
        item['ilvl'] = 1
    return encode_classic(item)


class ClassicRaw(bytes):
    """Native item with fields that cannot be projected into the Creator layout."""
    edit_reason = 'This Classic item can be moved or deleted. Its generated properties cannot be edited here.'

    def moved(self, fields):
        rec, size = decode_classic(self)
        fields = dict(fields)
        if 'panel' in fields:
            fields['page'] = _page(fields.pop('panel'))
        if fields.get('location') == 1:
            fields['x'] = rec['x'] if rec['location'] == 1 and rec['equipped'] == fields.get('equipped') else 0
        rec.update(fields)
        return ClassicRaw(encode_classic(rec) + self[size:])


class ClassicData:
    def __init__(self, data):
        self.data = data

    def parse_legacy_item(self, blob):
        return classic_item(blob, self.data)


class RawEarly(bytes):
    """Unsupported item record kept verbatim in the original character."""
    v109_raw = True
    read_only_reason = 'This item uses a pre-1.09 layout that is read-only.'


def starter_header(magic, version, cls, expansion, weapon, shield, seed):
    """The 130-byte header of a first save, after the game has initialized the character."""
    h = bytearray(HEADER_END)
    classic = version == 71
    struct.pack_into('<II16xIHHHHH', h, 0, magic, version, 0x20 if expansion else 0,
                     221 if classic else 319, 16, HEADER_END, cls, 1)
    h[38:70] = b'\xff' * 32
    h[43], h[45] = weapon, shield
    h[70:86] = b'\xff\0' * 8
    struct.pack_into('<I', h, 126, seed)
    return bytes(h)


def classic_starter_item(rec, data, original=False):
    """Encode a normal starting item in the 1.00 row-index or 1.06b code layout."""
    simple = rec.get('simple') and not original
    flags = 0x22010 if original else 0x1a2010 | (_SIMPLE if simple else 0)
    item = dict(rec, flags=flags, page=_page(rec['panel']), ilvl=1, quality_id=2,
                version=0, code_bits=int.from_bytes(rec['code'].encode('latin1'), 'little'),
                max_durability=rec.get('durability', 0))
    if original:
        item['row'] = classic_codes(data).index(rec['code'])
    return encode_classic(item)


def starter_tail(version, items, corpse):
    if version == 71:
        # Empty fixed-width hireling placeholder in the Classic framing.
        return b'JM' + bytes(6)
    # The old writer reused its item buffer for the empty hireling byte
    # and the hotkey block. Only the first two bytes of each hotkey were set.
    tail = bytearray((items + corpse)[-76:-19].ljust(57, b'\0'))
    tail[0] = 0
    for pos in range(1, 49, 6):
        tail[pos:pos + 2] = b'\xff\0'
    tail[49:] = bytes(8)
    return bytes(tail)
