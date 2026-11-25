"""Convert game text overrides to the table records consumed by the collector."""

import csv
from functools import lru_cache
import json
from pathlib import Path
from io import StringIO
import struct


EXCEL_PATH = 'data\\global\\excel\\'
TEXT_LAYOUTS = {'itemstatcost': 324, 'weapons': 424, 'armor': 424, 'misc': 424,
                'itemtypes': 228, 'inventory': 240}


def text_rows(raw):
    stream = StringIO(raw.decode('latin1').removeprefix('ï»¿'))
    rows = csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE)
    return [{k.strip().lower(): v.strip() for k, v in row.items() if k is not None and v is not None}
            for row in rows]


def bin_rows(raw):
    if not raw or len(raw) < 4:
        return []
    count = struct.unpack_from('<I', raw)[0]
    if not count or count > len(raw) - 4 or (len(raw) - 4) % count:
        return []
    size = (len(raw) - 4) // count
    return [raw[i:i + size] for i in range(4, len(raw), size)]


def _number(row, column):
    value = row.get(column, '')
    return int(value, 10) if value else 0


def _pack(row, source, fields):
    for column, offset, fmt in fields:
        if column in source:
            width = 8 * struct.calcsize('<' + fmt)
            value = _number(source, column) & ((1 << width) - 1)
            row[offset:offset + width // 8] = value.to_bytes(width // 8, 'little')


def _string_ids(folder):
    from mxl_data import all_strings
    return {key.lower(): idx for idx, (key, _) in sorted(all_strings(folder).items())}


def _records(rows):
    return struct.pack('<I', len(rows)) + b''.join(rows)


def statcost(raw, binary, strings, legacy):
    """1.10f through 1.14d use 0x144-byte ISC records. Pre-1.10 TXT names the old widths directly."""
    original = bin_rows(binary)
    rows = {struct.unpack_from('<H', r)[0]: bytearray(r) for r in original if len(r) == 324}
    text = [r for r in text_rows(raw) if r.get('id', '').isdigit()]
    names = {r.get('stat', '').lower(): int(r['id']) for r in text}
    for source in text:
        sid = int(source['id'])
        if not 0 <= sid < 511:
            continue
        row = rows.setdefault(sid, bytearray(324))
        struct.pack_into('<H', row, 0, sid)
        _pack(row, source, (
            ('csvbits', 10, 'B'), ('csvparam', 11, 'B'), ('valshift', 24, 'B'), ('save bits', 25, 'B'),
            ('1.09-save bits', 26, 'B'), ('save add', 28, 'i'), ('1.09-save add', 32, 'i'),
            ('save param bits', 36, 'I'), ('encode', 48, 'B'), ('descpriority', 52, 'h'),
            ('descfunc', 54, 'B'), ('descval', 55, 'B'), ('dgrp', 62, 'H'),
            ('dgrpfunc', 64, 'B'), ('dgrpval', 65, 'B'), ('op', 84, 'B'), ('op param', 85, 'B'),
        ))
        for col, offset in (('descstrpos', 56), ('descstrneg', 58), ('descstr2', 60),
                            ('dgrpstrpos', 66), ('dgrpstrneg', 68), ('dgrpstr2', 70)):
            if col in source:
                struct.pack_into('<H', row, offset, strings.get(source[col].lower(), 0))
        if 'op base' in source:
            struct.pack_into('<H', row, 86, names.get(source['op base'].lower(), 0xffff))
        if legacy and '1.09-save bits' not in source:
            row[26] = row[25]
            row[32:36] = row[28:32]
    return _records([rows[sid] for sid in sorted(rows)])


def legacy_statcost(binary):
    """Translate the 36-byte LoD itemstatcost records when no text source is present."""
    rows = []
    for sid, source in enumerate(bin_rows(binary)):
        row = bytearray(324)
        struct.pack_into('<H', row, 0, sid)
        row[12:24] = source[4:16]
        row[24:27] = bytes((source[16], source[17], source[17]))
        row[28:36] = source[20:24] * 2
        row[48] = source[32]
        rows.append(row)
    return _records(rows)


def base_items(raw, binary, strings, types):
    """Map text fields shared by the old and current item catalogues to collector offsets."""
    original = {r[128:132]: r for r in bin_rows(binary) if len(r) == 424}
    rows = []
    for source in text_rows(raw):
        code = source.get('code', '').encode('latin1')
        if not 1 <= len(code) <= 4 or source.get('name', '').lower() == 'expansion':
            continue
        code = code.ljust(4)
        row = bytearray(original.get(code, bytes(424)))
        row[128:132] = code
        for column, offset, size in (('invfile', 32, 32), ('wclass', 192, 4)):
            if column in source:
                row[offset:offset + size] = source[column].encode('latin1')[:size].ljust(size, b'\0')
        name = source.get('namestr') or code.decode('latin1').strip()
        if name.lower() in strings:
            struct.pack_into('<H', row, 244, strings[name.lower()])
        for column, offset in (('type', 286), ('type2', 288)):
            if column in source:
                struct.pack_into('<h', row, offset, types.get(source[column].lower(), -1))
        _pack(row, source, (
            ('pspell', 148, 'I'), ('minac', 204, 'i'), ('maxac', 208, 'i'), ('speed', 216, 'i'),
            ('maxstack', 228, 'I'), ('maxstack', 232, 'I'), ('spawnstack', 236, 'I'), ('auto prefix', 248, 'H'),
            ('rarity', 252, 'B'), ('version', 246, 'H'), ('level', 253, 'B'), ('mindam', 254, 'B'), ('maxdam', 255, 'B'),
            ('minmisdam', 256, 'B'), ('maxmisdam', 257, 'B'), ('2handmindam', 258, 'B'),
            ('2handmaxdam', 259, 'B'), ('strbonus', 262, 'H'), ('dexbonus', 264, 'H'),
            ('reqstr', 266, 'H'), ('reqdex', 268, 'H'), ('invwidth', 271, 'B'),
            ('invheight', 272, 'B'), ('block', 273, 'B'), ('durability', 274, 'B'),
            ('nodurability', 275, 'B'), ('2handed', 284, 'B'), ('quest', 298, 'B'),
            ('belt', 304, 'B'), ('stackable', 306, 'B'), ('spawnable', 307, 'B'),
            ('gemsockets', 312, 'B'), ('levelreq', 319, 'B'), ('magic lvl', 320, 'B'),
            ('compactsave', 323, 'B'),
        ))
        rows.append(row)
    return _records(rows)


def item_types(raw, binary):
    sources = [r for r in text_rows(raw) if r.get('itemtype', '').lower() != 'expansion']
    codes = {}
    for i, source in enumerate(sources):
        codes.setdefault(source.get('code', '').lower(), i)
    rows = []
    old = bin_rows(binary)
    classes = {'ama': 0, 'sor': 1, 'nec': 2, 'pal': 3, 'bar': 4, 'dru': 5, 'ass': 6}
    for i, source in enumerate(sources):
        code = source.get('code', '').encode('latin1')[:4].ljust(4)
        row = bytearray(old[i] if i < len(old) and len(old[i]) == 228 and old[i][:4] == code else bytes(228))
        row[:4] = code
        for col, offset in (('equiv1', 4), ('equiv2', 6), ('shoots', 12), ('quiver', 14)):
            struct.pack_into('<h', row, offset, codes.get(source.get(col, '').lower(), 0))
        for col, offset in (('staffmods', 31), ('class', 33)):
            row[offset] = classes.get(source.get(col, '').lower(), 255)
        _pack(row, source, (
            ('repair', 8, 'B'), ('body', 9, 'B'), ('throwable', 16, 'B'),
            ('reload', 17, 'B'), ('reequip', 18, 'B'), ('autostack', 19, 'B'),
            ('magic', 20, 'B'), ('rare', 21, 'B'), ('normal', 22, 'B'),
            ('charm', 23, 'B'), ('gem', 24, 'B'), ('beltable', 25, 'B'),
            ('maxsock1', 26, 'B'), ('maxsock25', 27, 'B'), ('maxsock40', 28, 'B'),
            ('treasureclass', 29, 'B'), ('rarity', 30, 'B'), ('costformula', 32, 'B'),
            ('varinvgfx', 35, 'B'),
        ))
        for slot in range(6):
            key = f'invgfx{slot + 1}'
            if key in source:
                offset = 36 + 32 * slot
                row[offset:offset + 32] = source[key].encode('latin1')[:31].ljust(32, b'\0')
        rows.append(row)
    return _records(rows)


def inventory(raw, binary):
    sources = text_rows(raw)
    rows = bin_rows(binary)
    result = []
    frames = ('grid', 'rarm', 'torso', 'larm', 'head', 'neck', 'rhand', 'lhand', 'belt', 'feet', 'gloves')
    for i, source in enumerate(sources):
        row = bytearray(rows[i] if i < len(rows) and len(rows[i]) == 240 else bytes(240))
        _pack(row, source, tuple(('inv' + col, k * 4, 'i')
                                  for k, col in enumerate(('left', 'right', 'top', 'bottom'))))
        _pack(row, source, (('gridx', 16, 'B'), ('gridy', 17, 'B'),
                            ('gridrows', 16, 'B'), ('gridcols', 17, 'B')))
        for j, frame in enumerate(frames):
            start = 20 + j * 20
            w, h = ('boxwidth', 'boxheight') if frame == 'grid' else ('width', 'height')
            fields = [(frame + col, start + k * 4, 'i')
                      for k, col in enumerate(('left', 'right', 'top', 'bottom'))]
            fields += [(frame + w, start + 16, 'B'), (frame + h, start + 17, 'B')]
            _pack(row, source, fields)
        result.append(row)
    return _records(result)


def text_layouts():
    return _layouts()['text_tables']


def _link_indices(source_text, read_text):
    cache = {}
    for table, key in (('weapons', 'code'), ('itemtypes', 'code')):
        sources = [source_text.get(table) or read_text(table)]
        if table == 'weapons':
            sources += [source_text.get(t) or read_text(t) for t in ('armor', 'misc')]
        records = (r for raw in sources if raw for r in text_rows(raw))
        keys = [r.get(key, '').lower() for r in records
                if r.get('name', r.get('itemtype', '')).lower() != 'expansion']
        cache[f'{table}.{key}'] = {code: i for i, code in reversed(list(enumerate(keys)))}

    def lookup(link):
        if link not in cache:
            table, key = link.lower().split('.', 1)
            raw = source_text.get(table) or read_text(table)
            rows = [r for r in text_rows(raw) if next(iter(r.values()), '').lower() != 'expansion'] if raw else []
            if table == 'itemstatcost':
                lookup_rows = [(int(r['id']), r) for r in rows if r.get('id', '').isdigit()]
            else:
                lookup_rows = list(enumerate(rows))
            cache[link] = {r[key].lower(): i for i, r in reversed(lookup_rows) if key in r}
        return cache[link]
    return lookup


def excel_table(raw, binary, name, strings, indices):
    """Project data and linked column values into the 1.10–1.14d reader's record layout."""
    size, fields = text_layouts()[name]
    rows = bin_rows(binary)
    if rows and len(rows[0]) != size:
        rows = []
    result = []
    for i, source in enumerate(r for r in text_rows(raw) if next(iter(r.values()), '').lower() != 'expansion'):
        row = bytearray(rows[i] if i < len(rows) else bytes(size))
        for key, offset, width, kind, link, bit in fields:
            cell = source.get(key)
            if cell is None:
                continue
            lower = cell.lower()
            if kind in (1, 7, 16):
                # These descriptors specify the number of characters, with NUL in the following byte.
                field_size = min(width + 1, size - offset)
                row[offset:offset + field_size] = cell.encode('latin1')[:width].ljust(field_size, b'\0')
                continue
            if kind in (9, 10):
                row[offset:offset + width] = cell.encode('latin1')[:width].ljust(width, b' ')
                continue
            if kind == 26:
                at, mask = offset + bit // 8, 1 << (bit % 8)
                row[at] = (row[at] & ~mask) | (mask if _number(source, key) else 0)
                continue
            if kind in (17, 18):
                value = i
            elif kind == 22:
                value = strings.get(lower, 0)
            elif kind == 25 and link == 'param':
                if lower.lstrip('-').isdigit():
                    value = int(lower)
                else:
                    value = next((m[lower] for lname in ('skills.skill', 'montype.type', 'states.state',
                                                        'itemstatcost.stat')
                                  if (m := indices(lname)).get(lower) is not None), 0)
            elif kind in (11, 13, 15, 19, 20, 21) and link and '.' in link:
                value = indices(link).get(lower, -1)
            elif kind in (2, 3, 4, 5, 6, 8):
                value = _number(source, key)
            else:
                # Engine callback and formula bytecode columns are retained from the compiled records.
                continue
            row[offset:offset + width] = (value & ((1 << (8 * width)) - 1)).to_bytes(width, 'little')
        result.append(row)
    return _records(result)


def apply(folder, preferred, version, read_text):
    """Apply supported text tables after extracting the string tables that they reference."""
    if not preferred:
        return
    strings = _string_ids(folder)
    legacy = version in (87, 89, 92)

    def replace(name, convert, *args):
        if name not in preferred:
            return
        target = folder / (name + '.bin')
        binary = target.read_bytes() if target.is_file() else None
        converted = convert(preferred[name], binary, *args)
        if len(converted) > 4:
            target.write_bytes(converted)

    replace('itemtypes', item_types)
    replace('inventory', inventory)
    replace('itemstatcost', statcost, strings, legacy)
    type_file = folder / 'itemtypes.bin'
    types = {r[:4].decode('latin1').strip('\0 ').lower(): i
             for i, r in enumerate(bin_rows(type_file.read_bytes()))} if type_file.is_file() else {}
    for name in ('armor', 'weapons', 'misc'):
        replace(name, base_items, strings, types)
    pending = preferred.keys() & text_layouts().keys()
    if pending:
        indices = _link_indices(preferred, read_text)
        for name in sorted(pending):
            replace(name, excel_table, name, strings, indices)


@lru_cache(maxsize=1)
def _layouts():
    path = Path(__file__).with_name('mxl_profile_table_layouts.json')
    return json.loads(path.read_text(encoding='utf-8'))


def _project_legacy(name, raw, layouts, strings):
    """Copy fields into the collector's layout using the matching source record size."""
    rows = bin_rows(raw)
    size, variants = layouts[name]
    if not rows or len(rows[0]) == size:
        return raw
    fields = variants.get(str(len(rows[0])))
    if not fields:
        return raw
    result = []
    for index, source in enumerate(rows):
        row = bytearray(size)
        for old_at, old_width, new_at, new_width, signed in fields:
            value = source[old_at:old_at + old_width]
            if new_width <= old_width:
                value = value[:new_width]
            else:
                sign_byte = b'\xff' if signed and value[-1] == 255 else b'\0'
                value = value.ljust(new_width, sign_byte)
            row[new_at:new_at + new_width] = value
        if name in ('armor', 'weapons', 'misc'):
            key = row[128:132].decode('latin1').rstrip().lower()
            struct.pack_into('<H', row, 244, strings.get(key, 0))
        elif name == 'skills':
            struct.pack_into('<H', row, 0, index)
            struct.pack_into('<H', row, 404, index)
        elif name == 'monstats':
            key = source[:60].split(b'\0')[0].decode('latin1').lower()
            struct.pack_into('<HH', row, 0, index, index)
            struct.pack_into('<H', row, 6, strings.get(key, 0))
        result.append(row)
    return _records(result)


def project_legacy(folder):
    """Prepare the tables used when opening original 1.07–1.09 installations."""
    layouts = _layouts()['tables']
    strings = _string_ids(folder)
    for name in layouts:
        path = folder / (name + '.bin')
        if path.is_file():
            raw = path.read_bytes()
            result = _project_legacy(name, raw, layouts, strings)
            if result != raw:
                path.write_bytes(result)
    stat_file = folder / 'itemstatcost.bin'
    if stat_file.is_file():
        raw = stat_file.read_bytes()
        rows = bin_rows(raw)
        if rows and len(rows[0]) == 36:
            stat_file.write_bytes(legacy_statcost(raw))
    prop_file = folder / 'properties.bin'
    properties = bin_rows(prop_file.read_bytes()) if prop_file.is_file() else []
    if properties and len(properties[0]) == 16:
        # These records only store names. Legacy property functions live in the game DLL.
        prop_file.write_bytes(_records([bytes(32) + b'\xff' * 14 for _ in properties]))
    set_file = folder / 'setitems.bin'
    sets = bin_rows(set_file.read_bytes()) if set_file.is_file() else []
    if sets and len(sets[0]) == 1332:
        members = []
        set_names = []
        for sid, group in enumerate(sets):
            name = group[:96].split(b'\0')[0]
            set_names.append(struct.pack('<3H', sid, strings.get(name.decode('latin1').lower(), 0),
                                         struct.unpack_from('<H', group, 96)[0]) + bytes(290))
            for k in range(min(group[100], 6)):
                at = 140 + k * 60
                row = bytearray(440)
                row[2:34] = group[at + 25:at + 57]
                row[40:44] = group[at:at + 4]
                struct.pack_into('<hHHI', row, 44, sid,
                                 struct.unpack_from('<I', group, 136)[0] & 0xffff, group[at + 12],
                                 struct.unpack_from('<I', group, at + 8)[0])
                for offset in range(136, 280, 16):
                    struct.pack_into('<i', row, offset, -1)
                members.append(row)
        set_file.write_bytes(_records(members))
        (folder / 'sets.bin').write_bytes(_records(set_names))
    desc_file = folder / 'skilldesc.bin'
    if not desc_file.is_file():
        skills = bin_rows((folder / 'skills.bin').read_bytes())
        rows = []
        for index in range(len(skills)):
            row = bytearray(288)
            struct.pack_into('<H', row, 8, strings.get(f'skillname{index}', 0))
            rows.append(row)
        desc_file.write_bytes(_records(rows))
