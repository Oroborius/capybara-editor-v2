"""Structural diff of two character (.d2s) or stash files.

    changes = diff_bytes(old_bytes, new_bytes, 'd2s' | 'stash', tables)      # or diff_files(old_path, new_path)
    print(format_text(changes))      # one line per change, grouped by section
    print(summary(changes))          # one line for a log

A change is a dict: section ('header', 'hotkeys', 'mercenary', 'quests', 'waypoints', 'npcs', 'stats',
'skills', 'items', 'file'), kind ('changed', 'added', 'removed', 'moved'), text (the readable line) and, where
they apply, name / old / new / place / old_place / details (JSON friendly values only).

Items have no reliable identity in the file (compact items have no id at all), so they are paired in passes:
same place and same bytes (unchanged, not reported); same bytes somewhere else (moved); same id and code, or
same place and code (changed - fields and stats are compared one by one); what is left was added or removed.
Without game tables the items cannot be decoded: the item data is compared as one block.
"""
import time

from .d2s import (D2S, CLASSES, DIFFICULTIES, STAT_NAMES, FIXED_POINT_STATS, ACHIEVEMENT_STAT, QUEST_LAYOUT,
                  QUEST_NAMES, QUEST_BITS, STATUS_HARDCORE, STATUS_DIED, STATUS_EXPANSION, STATUS_LADDER)
from .stash import Stash
from .items import FLAG_NAMES, LOCATION, PANEL, QUALITY

SECTIONS = ('file', 'header', 'hotkeys', 'mercenary', 'quests', 'waypoints', 'npcs', 'stats', 'skills', 'items')
SECTION_TITLES = {'file': 'file', 'header': 'header', 'hotkeys': 'skill keys', 'mercenary': 'mercenary',
                  'quests': 'quests', 'waypoints': 'waypoints', 'npcs': 'NPC flags', 'stats': 'stats',
                  'skills': 'skills', 'items': 'items'}
BODY_SLOTS = {1: 'head', 2: 'amulet', 3: 'body', 4: 'right hand', 5: 'left hand', 6: 'right ring', 7: 'left ring',
              8: 'belt', 9: 'boots', 10: 'gloves', 11: 'right hand II', 12: 'left hand II'}
SHORT_PANEL = {'inventory': 'inv'}
STATUS_BITS = ((STATUS_HARDCORE, 'hardcore'), (STATUS_DIED, 'died'), (STATUS_EXPANSION, 'expansion'),
               (STATUS_LADDER, 'ladder'))
# header fields compared one by one: (attribute, label, section)
HEADER_FIELDS = (('version', 'file version', 'header'), ('active_weapon', 'active weapon set', 'header'),
                 ('progression', 'progression', 'header'), ('unknown_26', 'unknown 0x26', 'header'),
                 ('unknown_29', 'unknown 0x29', 'header'), ('unknown_2a', 'unknown 0x2A', 'header'),
                 ('level', 'level (header)', 'header'), ('created', 'created', 'header'),
                 ('unknown_34', 'unknown 0x34', 'header'), ('unknown_af', 'unknown 0xAF', 'header'),
                 ('merc_dead', 'dead', 'mercenary'), ('merc_name', 'name index', 'mercenary'),
                 ('merc_type', 'type (hireling row)', 'mercenary'), ('merc_exp', 'experience', 'mercenary'))
ITEM_FIELDS = (('code', 'code'), ('version', 'version'), ('id', 'id'), ('ilvl', 'item level'),
               ('quality', 'quality'), ('image', 'picture'), ('auto_affix', 'automatic affix'),
               ('subquality', 'low / superior kind'), ('prefix', 'prefix'), ('suffix', 'suffix'),
               ('set_unique_id', 'set / unique id'), ('rare_names', 'rare name'), ('rare_affixes', 'affixes'),
               ('runeword_id', 'runeword'), ('personalized_name', 'personalized name'), ('tome_bits', 'tome bits'),
               ('realm_bit', 'realm bit'), ('defense_raw', 'defense (stored)'), ('max_durability', 'max durability'),
               ('durability', 'durability'), ('quantity', 'quantity'), ('sockets', 'sockets'),
               ('socketed_count', 'socketed items'), ('set_mask', 'set bonus mask'), ('padding', 'padding bits'))


def _chg(section, kind, text, **more):
    d = dict(section=section, kind=kind, text=text)
    d.update(more)
    return d


def _val(section, name, old, new, show=str):
    return _chg(section, 'changed', f'{name}: {show(old)} -> {show(new)}', name=name, old=_js(old), new=_js(new))


def _js(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    if isinstance(v, tuple):
        return list(v)
    return v


def _hex(width):
    return lambda v: f'{v:0{width}x}'


def _when(t):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t)) + ' UTC' if t else '0'


# ---------------------------------------------------------------------- names

def stat_label(sid, param, tables):
    name = (tables.stat_name(sid) if tables is not None and hasattr(tables, 'stat_name') else '') or ''
    s = f'stat {sid}' + (f' "{name}"' if name else '')
    return s + (f' [{param}]' if param else '')


def item_name(it, tables):
    name = (tables.base_name(it.code) if tables is not None else '') or it.code.strip()
    q = QUALITY.get(it.quality)
    return f'{name} ({q})' if q and q != 'normal' else name


def place_of(it, container, short=False):
    """Readable place of an item; `container` is 'items', 'mercenary', 'corpse', 'golem' or 'page N'."""
    if container.startswith('page'):
        return f'{container} ({it.x},{it.y})' if not short else f'{container.replace("page ", "p")} {it.x},{it.y}'
    lead = '' if container == 'items' else container + ' '
    if container == 'golem':
        return 'iron golem'
    if it.location == 1:
        return f'{lead}{BODY_SLOTS.get(it.equipped, f"slot {it.equipped}")}' + ('' if lead or short else ' (equipped)')
    if it.location == 2:
        return f'{lead}belt {it.x}'
    if it.location == 0:
        panel = PANEL.get(it.panel, f'panel {it.panel}')
        return f'{lead}{SHORT_PANEL.get(panel, panel)} {it.x},{it.y}' if short else f'{lead}{panel} ({it.x},{it.y})'
    return f'{lead}{LOCATION.get(it.location, it.location)}'


# ---------------------------------------------------------------------- character sections

def _skill(v, tables):
    if v == 0xFFFF:
        return 'none'
    name = tables.skill_name(v & 0x7FFF) if tables is not None else ''
    return (name or f'skill {v & 0x7FFF}') + (' (left)' if v & 0x8000 else '')


def _diff_header(a, b, tables, out):
    if a.name != b.name:
        out.append(_val('header', 'name', a.name_str, b.name_str))
    if a.cls != b.cls:
        out.append(_val('header', 'class', a.cls, b.cls, lambda c: CLASSES[c] if c < len(CLASSES) else str(c)))
    if a.status != b.status:
        out.append(_val('header', 'status', a.status, b.status, lambda s: f'0x{s:02x} ' + '+'.join(
            n for bit, n in STATUS_BITS if s & bit)))
    for attr, label, section in HEADER_FIELDS:
        x, y = getattr(a, attr), getattr(b, attr)
        if x != y:
            out.append(_val(section, label, x, y))
    if a.merc_id != b.merc_id:
        out.append(_val('mercenary', 'id', a.merc_id, b.merc_id, lambda v: f'{v:08x}' if v else 'none'))
    if a.last_played != b.last_played:
        out.append(_val('header', 'last played', a.last_played, b.last_played, _when))
    if a.difficulty != b.difficulty:
        def where(d):
            for i, x in enumerate(d):
                if x & 0x80:
                    return f'{DIFFICULTIES[i]} act {(x & 7) + 1}'
            return d.hex()
        out.append(_val('header', 'last difficulty / act', a.difficulty, b.difficulty, where))
    if a.map_seed != b.map_seed:
        out.append(_val('header', 'map seed', a.map_seed, b.map_seed, _hex(8)))
    if a.appearance != b.appearance:
        n = sum(x != y for x, y in zip(a.appearance, b.appearance))
        out.append(_chg('header', 'changed', f'appearance: {n} of 32 bytes ({a.appearance.hex()} -> '
                        f'{b.appearance.hex()})', name='appearance', old=a.appearance.hex(), new=b.appearance.hex()))
    if a.reserved != b.reserved:
        n = sum(x != y for x, y in zip(a.reserved, b.reserved))
        out.append(_chg('header', 'changed', f'reserved bytes 0xBF..0x14E: {n} differ', name='reserved',
                        old=a.reserved.hex(), new=b.reserved.hex()))
    for i, (x, y) in enumerate(zip(a.hotkeys, b.hotkeys)):
        if x != y:
            out.append(_chg('hotkeys', 'changed', f'key {i + 1}: {_skill(x, tables)} -> {_skill(y, tables)}',
                            name=f'key {i + 1}', old=x, new=y))
    for attr, label in (('left_skill', 'left mouse'), ('right_skill', 'right mouse'),
                        ('left_skill_swap', 'left mouse (set II)'), ('right_skill_swap', 'right mouse (set II)')):
        x, y = getattr(a, attr), getattr(b, attr)
        if x != y:
            out.append(_chg('hotkeys', 'changed', f'{label}: {_skill(x, tables)} -> {_skill(y, tables)}',
                            name=label, old=x, new=y))


def _quest_word_name(i):
    if i in QUEST_NAMES:
        return QUEST_NAMES[i]
    for act, intro, _first, _n, done in QUEST_LAYOUT:
        if i == intro:
            return f'{act} introduction'
        if i == done:
            return f'{act} finished'
    return f'word {i}'


def _bits(old, new, names):
    parts = []
    for bit in range(16):
        x, y = old >> bit & 1, new >> bit & 1
        if x != y:
            parts.append(('+' if y else '-') + names.get(bit, f'bit {bit}'))
    return ', '.join(parts)


def _diff_quests(a, b, out):
    for name, x, y in (('version', a.version, b.version), ('size', a.size, b.size)):
        if x != y:
            out.append(_val('quests', f'section {name}', x, y))
    for d in range(3):
        for i, (x, y) in enumerate(zip(a.words[d], b.words[d])):
            if x != y:
                label = f'{DIFFICULTIES[d]} {_quest_word_name(i)}'
                out.append(_chg('quests', 'changed', f'{label}: {x:04x} -> {y:04x} ({_bits(x, y, QUEST_BITS)})',
                                name=label, difficulty=d, word=i, old=x, new=y))


def _diff_waypoints(a, b, out):
    for name, x, y in (('version', a.version, b.version), ('size', a.size, b.size), ('lead words', a.lead, b.lead)):
        if x != y:
            out.append(_val('waypoints', f'section {name}', x, y))
    for d in range(3):
        x, y = set(a.active(d)), set(b.active(d))
        if x != y:
            parts = []
            if y - x:
                parts.append('+' + ','.join(map(str, sorted(y - x))))
            if x - y:
                parts.append('-' + ','.join(map(str, sorted(x - y))))
            out.append(_chg('waypoints', 'changed', f'{DIFFICULTIES[d]}: {" ".join(parts)} ({len(x)} -> {len(y)} '
                            f'active)', name=DIFFICULTIES[d], difficulty=d, added=sorted(y - x),
                            removed=sorted(x - y)))


def _diff_npcs(a, b, out):
    if a.size != b.size:
        out.append(_val('npcs', 'section size', a.size, b.size))
    for label, x, y in (('introduced', a.intro, b.intro), ('congratulated', a.congrats, b.congrats)):
        for d in range(3):
            if x[d] != y[d]:
                out.append(_val('npcs', f'{DIFFICULTIES[d]} {label}', x[d], y[d], _hex(16)))


def _char_stat_name(sid, param, tables):
    if sid == ACHIEVEMENT_STAT and param is not None:
        if param < 0x2000:
            name = tables.monster_name(param) if tables is not None else ''
            return f'kills of {name or "monster"} #{param}'
        return f'counter {param - 0x2000}'
    return STAT_NAMES.get(sid) or stat_label(sid, param, tables)


def _char_stat_value(sid, v):
    return f'{v / 256:g}' if sid in FIXED_POINT_STATS else str(v)


def _diff_stats(a, b, tables, out):
    x = {(s.id, s.param): s.value for s in a}
    y = {(s.id, s.param): s.value for s in b}
    for key in sorted(set(x) | set(y), key=lambda k: (k[0], k[1] or 0)):
        sid, param = key
        name = _char_stat_name(sid, param, tables)
        show = lambda v, sid=sid: 'absent' if v is None else _char_stat_value(sid, v)   # noqa: E731
        if x.get(key) != y.get(key):
            out.append(_chg('stats', 'changed', f'{name}: {show(x.get(key))} -> {show(y.get(key))}', name=name,
                            stat=sid, param=param, old=x.get(key), new=y.get(key)))
    if [(s.id, s.param) for s in a if (s.id, s.param) in y] != [(s.id, s.param) for s in b if (s.id, s.param) in x]:
        out.append(_chg('stats', 'changed', 'order of the stats in the file', name='order'))


def _diff_skills(a, b, tables, out):
    if tables is not None and a.header.cls == b.header.cls and len(a.skills) == len(b.skills):
        ids = tables.class_skills(a.header.cls)
        for sid, x, y in zip(ids, a.skills, b.skills):
            if x != y:
                name = tables.skill_name(sid) or f'skill {sid}'
                out.append(_chg('skills', 'changed', f'{name}: {x} -> {y}', name=name, skill=sid, old=x, new=y))
    elif a.skills != b.skills:
        n = sum(x != y for x, y in zip(a.skills, b.skills)) + abs(len(a.skills) - len(b.skills))
        out.append(_chg('skills', 'changed', f'{n} skill bytes differ ({len(a.skills)} -> {len(b.skills)} bytes)',
                        name='skills', old=a.skills.hex(), new=b.skills.hex()))


# ---------------------------------------------------------------------- items

class _Entry:
    __slots__ = ('item', 'container', 'place', 'key', 'index')

    def __init__(self, item, container, buf, tables, index):
        self.item, self.container, self.index = item, container, index
        self.place = (container, item.location, item.equipped, item.x, item.y, item.panel)
        parts = []
        for it in [item] + list(item.socketed):
            if buf is not None and it.offset >= 0 and it.size:
                parts.append(buf[it.offset:it.offset + it.size])
            else:
                parts.append(it.to_bytes(tables))
        raw = bytearray(parts[0])
        if len(raw) >= 10:              # the position fields: bits 42..59 of the item's bit stream
            raw[7] &= 0x03
            raw[8] = 0
            raw[9] &= 0xF0
        self.key = bytes(raw) + b''.join(parts[1:])


def _entries(obj, buf, tables):
    out = []

    def add(items, container):
        for i, it in enumerate(items or ()):
            out.append(_Entry(it, container, buf, tables, i))
    if isinstance(obj, Stash):
        for p in obj.pages:
            add(p.items, f'page {p.number + 1}')
    else:
        add(obj.items, 'items')
        for n, c in enumerate(obj.corpses or ()):
            add(c.items, 'corpse' if not n else f'corpse {n + 1}')
        add(obj.merc_items, 'mercenary')
        if obj.golem_item is not None:
            add([obj.golem_item], 'golem')
    return out


def _stat_changes(old, new, tables, title=''):
    out = []
    x, y = {}, {}
    for lst, d in ((old or (), x), (new or (), y)):
        for s in lst:
            d.setdefault((s.id, s.param), []).append(s.value)
    for key in sorted(set(x) | set(y), key=lambda k: (k[0], k[1] or 0)):
        a, b = x.get(key), y.get(key)
        if a == b:
            continue
        label = title + stat_label(key[0], key[1], tables)
        one = lambda v: ('/'.join(map(str, v)) if v else 'absent')      # noqa: E731
        if a is None:
            out.append(dict(stat=key[0], param=key[1], old=None, new=b[0] if len(b) == 1 else b,
                            text=f'+{label} = {one(b)}'))
        elif b is None:
            out.append(dict(stat=key[0], param=key[1], old=a[0] if len(a) == 1 else a, new=None,
                            text=f'-{label} (was {one(a)})'))
        else:
            out.append(dict(stat=key[0], param=key[1], old=a[0] if len(a) == 1 else a,
                            new=b[0] if len(b) == 1 else b, text=f'{label}: {one(a)} -> {one(b)}'))
    return out


def item_changes(a, b, tables):
    """Field and stat differences of two versions of one item (place not included): list of dicts with text."""
    out = []
    if a.flags != b.flags:
        parts = [('+' if b.flags >> bit & 1 else '-') + FLAG_NAMES.get(bit, f'bit {bit}')
                 for bit in range(32) if (a.flags ^ b.flags) >> bit & 1]
        out.append(dict(field='flags', old=a.flags, new=b.flags, text='flags ' + ', '.join(parts)))
    for attr, label in ITEM_FIELDS:
        x, y = getattr(a, attr), getattr(b, attr)
        if x != y:
            show = (lambda v: QUALITY.get(v, v)) if attr == 'quality' else (
                (lambda v: 'none' if v is None else f'{v:08x}') if attr == 'id' else
                (lambda v: 'none' if v is None else v))
            out.append(dict(field=attr, old=_js(x), new=_js(y), text=f'{label}: {show(x)} -> {show(y)}'))
    out += _stat_changes(a.stats, b.stats, tables)
    for bit in sorted(set(a.set_stats) | set(b.set_stats)):
        out += _stat_changes(a.set_stats.get(bit), b.set_stats.get(bit), tables, f'set bonus {bit + 1}: ')
    out += _stat_changes(a.runeword_stats, b.runeword_stats, tables, 'runeword: ')
    sa = [s.to_bytes(tables) if tables is not None else b'' for s in a.socketed]
    sb = [s.to_bytes(tables) if tables is not None else b'' for s in b.socketed]
    if sa != sb:
        gone = [item_name(s, tables) for s, raw in zip(a.socketed, sa) if raw not in sb]
        came = [item_name(s, tables) for s, raw in zip(b.socketed, sb) if raw not in sa]
        text = ', '.join(['+' + n for n in came] + ['-' + n for n in gone]) or 'order / position'
        out.append(dict(field='socketed', old=[s.code for s in a.socketed], new=[s.code for s in b.socketed],
                        text=f'in the sockets: {text}'))
    return out


def _take(pool, key):
    lst = pool.get(key)
    return lst.pop(0) if lst else None


def _diff_items(old, new, old_buf, new_buf, tables, out):
    A, B = _entries(old, old_buf, tables), _entries(new, new_buf, tables)
    # 1. same place, same bytes: unchanged
    pool = {}
    for e in A:
        pool.setdefault((e.place, e.key), []).append(e)
    rest_b = []
    used = set()
    for e in B:
        m = _take(pool, (e.place, e.key))
        if m is None:
            rest_b.append(e)
        else:
            used.add(id(m))
    rest_a = [e for e in A if id(e) not in used]
    pairs = []                                  # (old entry, new entry) of one item that moved and / or changed

    def match(keyfunc):
        nonlocal rest_a, rest_b
        pool = {}
        for e in rest_a:
            k = keyfunc(e)
            if k is not None:
                pool.setdefault(k, []).append(e)
        left, used = [], set()
        for e in rest_b:
            k = keyfunc(e)
            m = _take(pool, k) if k is not None else None
            if m is None:
                left.append(e)
            else:
                used.add(id(m))
                pairs.append((m, e))
        rest_a = [e for e in rest_a if id(e) not in used]
        rest_b = left
    match(lambda e: (e.container, e.key))                                   # 2. moved inside its container
    match(lambda e: e.key)                                                  #    ... or to another one
    match(lambda e: (e.item.id, e.item.code) if e.item.id else None)        # 3. same id: changed (maybe moved)
    match(lambda e: (e.place, e.item.code))                                 # 4. same place and base: changed
    order = {id(e): n for n, e in enumerate(B)}
    for a, b in sorted(pairs, key=lambda p: order[id(p[1])]):
        name = item_name(b.item, tables)
        pa, pb = place_of(a.item, a.container), place_of(b.item, b.container)
        details = item_changes(a.item, b.item, tables) if a.key != b.key else []
        if details:
            where = pb if a.place == b.place else f'{pa} -> {pb}'
            out.append(_chg('items', 'changed', f'changed: {name} at {where}: ' + '; '.join(d['text'] for d in details),
                            title=f'changed: {name} at {where}', name=name, code=b.item.code, place=pb,
                            old_place=pa, details=details,
                            short_place=place_of(b.item, b.container, True)))
        elif a.place != b.place:
            out.append(_chg('items', 'moved', f'moved: {name}: {pa} -> {pb}', name=name, code=b.item.code, place=pb,
                            old_place=pa, short_place=place_of(b.item, b.container, True)))
        else:       # same place, different bytes, nothing decoded differs (cannot happen with a byte-exact rebuild)
            out.append(_chg('items', 'changed', f'changed: {name} at {pb}: bytes differ', name=name,
                            code=b.item.code, place=pb, old_place=pa, details=[],
                            short_place=place_of(b.item, b.container, True)))
    for kind, sign, rest in (('removed', '-', rest_a), ('added', '+', rest_b)):
        for e in rest:
            name = item_name(e.item, tables)
            extra = ''
            if e.item.socketed:
                extra = ' with ' + ', '.join(item_name(s, tables) for s in e.item.socketed)
            if e.item.quantity is not None:
                extra += f' x{e.item.quantity}'
            out.append(_chg('items', kind, f'{sign} {name}{extra} at {place_of(e.item, e.container)}', name=name,
                            code=e.item.code, place=place_of(e.item, e.container),
                            short_place=place_of(e.item, e.container, True), stats=len(e.item.stats)))
    if not any(c['section'] == 'items' for c in out):
        # nothing above: the same items at the same places; only their order in the file can differ
        for cont in sorted({e.container for e in A}):
            if [e.key for e in A if e.container == cont] != [e.key for e in B if e.container == cont] or \
                    [e.place for e in A if e.container == cont] != [e.place for e in B if e.container == cont]:
                out.append(_chg('items', 'changed', f'order of the items in the file ({cont})', name='order',
                                place=cont))


# ---------------------------------------------------------------------- entry points

def diff_objects(old, new, tables=None, old_bytes=None, new_bytes=None):
    """Changes from `old` to `new` (two D2S or two Stash objects parsed with the same tables). The bytes the
    objects were parsed from make the item comparison faster; they are optional."""
    out = []
    if type(old) is not type(new):
        raise TypeError('two files of the same kind expected')
    if isinstance(old, D2S):
        _diff_header(old.header, new.header, tables, out)
        _diff_quests(old.quests, new.quests, out)
        _diff_waypoints(old.waypoints, new.waypoints, out)
        _diff_npcs(old.npcs, new.npcs, out)
        _diff_stats(old.stats, new.stats, tables, out)
        _diff_skills(old, new, tables, out)
        if old.items is None or new.items is None:
            if old.items_raw != new.items_raw:
                out.append(_chg('items', 'changed', f'item data differs ({len(old.items_raw or b"")} -> '
                                f'{len(new.items_raw or b"")} bytes; not decoded: no game tables)', name='raw'))
        else:
            for label, x, y in (('mercenary section', old.has_merc_section, new.has_merc_section),
                                ('mercenary item list', old.merc_items is not None, new.merc_items is not None),
                                ('golem section', old.has_golem_section, new.has_golem_section)):
                if x != y:
                    out.append(_val('mercenary' if 'merc' in label else 'items', label, x, y,
                                    lambda v: 'present' if v else 'absent'))
            if len(old.corpses) != len(new.corpses):
                out.append(_val('items', 'corpses', len(old.corpses), len(new.corpses)))
            if old.trailing != new.trailing:
                out.append(_val('file', 'bytes after the last section', len(old.trailing), len(new.trailing)))
            _diff_items(old, new, old_bytes, new_bytes, tables, out)
    elif isinstance(old, Stash):
        if old.version != new.version:
            out.append(_val('header', 'version', old.version, new.version))
        if old.last_page != new.last_page:
            out.append(_val('header', 'page shown last', old.last_page + 1, new.last_page + 1))
        if any(p.items is None for p in old.pages + new.pages):
            x = {p.number: (p.count, p.raw) for p in old.pages}
            y = {p.number: (p.count, p.raw) for p in new.pages}
            for n in sorted(set(x) | set(y)):
                if x.get(n) != y.get(n):
                    out.append(_chg('items', 'changed', f'page {n + 1}: {(x.get(n) or (0,))[0]} -> '
                                    f'{(y.get(n) or (0,))[0]} items (not decoded: no game tables)', name='raw'))
        else:
            _diff_items(old, new, old_bytes, new_bytes, tables, out)
    else:
        raise TypeError('character or stash file expected')
    if old_bytes is not None and new_bytes is not None and len(old_bytes) != len(new_bytes):
        out.insert(0, _chg('file', 'changed', f'size: {len(old_bytes)} -> {len(new_bytes)} bytes', name='size',
                           old=len(old_bytes), new=len(new_bytes)))
    order = {s: n for n, s in enumerate(SECTIONS)}
    out.sort(key=lambda c: order.get(c['section'], 99))
    return out


def diff_bytes(old_bytes, new_bytes, kind, tables=None):
    from .cli import load_bytes
    if kind not in ('d2s', 'stash'):
        raise TypeError('character or stash file expected')
    return diff_objects(load_bytes(old_bytes, kind, tables), load_bytes(new_bytes, kind, tables), tables,
                        old_bytes, new_bytes)


def diff_files(old_path, new_path, tables=None):
    from .cli import kind_of
    with open(old_path, 'rb') as f:
        a = f.read()
    with open(new_path, 'rb') as f:
        b = f.read()
    ka, kb = kind_of(old_path, a), kind_of(new_path, b)
    if ka != kb:
        raise TypeError(f'{ka} and {kb}: two files of the same kind expected')
    return diff_bytes(a, b, ka, tables)


def format_text(changes, indent='  '):
    """The changes as lines of text, grouped by section; 'no differences' when there are none."""
    if not changes:
        return 'no differences'
    lines, last = [], None
    for c in changes:
        if c['section'] != last:
            last = c['section']
            n = sum(1 for k in changes if k['section'] == last)
            lines.append(f'{SECTION_TITLES.get(last, last)} ({n})')
        if len(c.get('details') or ()) > 1:         # an item with several differences: one per line
            lines.append(indent + c['title'] + ':')
            lines.extend(indent * 3 + d['text'] for d in c['details'])
        else:
            lines.append(indent + c['text'])
    return '\n'.join(lines)


def _few(texts, limit):
    texts = list(texts)
    more = len(texts) - limit
    return ', '.join(texts[:limit]) + (f' (+{more} more)' if more > 0 else '')


def summary(changes, limit=3, old_size=None, new_size=None):
    """One line: 'stats strength 817->900; items +1 (Ring at inv 3,4); 4107->4131 bytes'."""
    parts = []
    by = {}
    for c in changes:
        by.setdefault(c['section'], []).append(c)
    for section in SECTIONS:
        lst = by.get(section)
        if not lst or section == 'file':
            continue
        if section == 'items':
            bits = []
            for kind, sign in (('added', '+'), ('removed', '-')):
                sel = [c for c in lst if c['kind'] == kind]
                if sel:
                    bits.append(f'{sign}{len(sel)} (' + _few((f'{c["name"]} at {c["short_place"]}' for c in sel),
                                                              limit) + ')')
            sel = [c for c in lst if c['kind'] == 'moved']
            if sel:
                bits.append(f'{len(sel)} moved (' + _few((c['name'] for c in sel), limit) + ')')
            sel = [c for c in lst if c['kind'] == 'changed' and 'details' in c]
            if sel:
                bits.append(f'{len(sel)} changed (' + _few(
                    (f'{c["name"]}: ' + _few((d['text'] for d in c['details']), 2) for c in sel), limit) + ')')
            bits += [c['text'] for c in lst if c['kind'] == 'changed' and 'details' not in c]
            parts.append('items ' + ' '.join(bits))
        else:
            parts.append(f'{SECTION_TITLES[section]} ' + _few((c['text'].replace(' -> ', '->').replace(': ', ' ', 1)
                                                               for c in lst), limit))
    if not parts:
        parts.append('no structural change')
    size = next((c for c in changes if c['section'] == 'file' and c.get('name') == 'size'), None)
    if size is not None:
        parts.append(f'{size["old"]}->{size["new"]} bytes')
    elif new_size is not None:
        parts.append(f'{new_size} bytes' if old_size in (None, new_size) else f'{old_size}->{new_size} bytes')
    return '; '.join(parts)
