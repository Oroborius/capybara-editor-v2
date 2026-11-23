"""Diablo II save versions before 1.09.

Header and record fields follow the d2s-legacy and bitstream-legacy specs,
with the Classic record sizes (including two trailing bytes) verified against
1.00 and 1.06b saves and the 1.00 layout checked against Hero Editor.
"""
import struct

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


def classic_item(blob, data):
    from mxl_format import BitReader, FormatError, Item, QUALITY, expect
    from mxl_format_fix import _keep_raw

    expect(blob, 0, b'JM')
    br = BitReader(blob[2:])
    flags = br.read(32)
    coded = bool(flags & 0x100000)
    simple = coded and bool(flags & 0x200000)
    ear = bool(flags & 0x10000)
    size = (26 if ear else 15) if simple else (31 if coded else 27)
    if len(blob) < size:
        raise FormatError('Truncated Classic item')
    it = Item()
    it['stats'] = []
    it['version'] = br.read(10) if coded else 0
    code = br.read(32).to_bytes(4, 'little').decode('latin1') if coded and not simple else None
    it['identified'] = bool(flags & 0x10)
    it['equipped'] = br.read(5)
    it['socketed_count'] = 0
    if simple or ear and not coded:
        if not simple:
            br.read(10)
        it['location'] = br.read(3)
        it['x'], it['y'] = br.read(5), br.read(3)
        if not simple:
            br.read(10)
        page = br.read(8)
        code = 'ear ' if ear else br.read(32).to_bytes(4, 'little').decode('latin1')
    else:
        it['socketed_count'] = br.read(3)
        it['ilvl'] = br.read(12) & 0xFF
        if not coded:
            codes = classic_codes(data)
            row = br.read(10)
            code = codes[row] if row < len(codes) else '????'
        it['location'] = br.read(3)
        it['quality'] = QUALITY.get(br.read(4), 'unknown')
        quantity = br.read(20)
        it['durability'], it['max_durability'] = br.read(8), br.read(8)
        it['x'], it['y'] = br.read(5), br.read(3)
        br.read(10)  # quality-specific index, in the original game's table order
        it['id'] = br.read(32)
        br.read(32)  # item generation seed
        page = br.read(8)
        if quantity:
            it['quantity'] = quantity
    it['code'] = code
    it['panel'] = 0 if page == 255 else page + 1
    it['has_sockets'] = bool(flags & 0x800 or it['socketed_count'])
    it['ethereal'] = False
    it.opaque = True
    try:
        it['name'] = data.base(code).name
    except (KeyError, AttributeError):
        it['name'] = code.strip()
    br.pos = (size - 2) * 8
    _keep_raw(it, blob, br)
    return it, br


class ClassicData:
    def __init__(self, data):
        self.data = data

    def parse_legacy_item(self, blob):
        return classic_item(blob, self.data)


class RawEarly(bytes):
    """Unsupported item record kept verbatim in the original character."""
    v109_raw = True
    read_only_reason = 'This item uses a pre-1.09 layout that is read-only.'
