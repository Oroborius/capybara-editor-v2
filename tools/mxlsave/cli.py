"""Command line:  python -m mxlsave dump <file> [--json] [--data DIR]
                  python -m mxlsave verify <file>... [--data DIR]

dump    prints what the file holds (human readable, or everything as JSON)
verify  parse -> rebuild -> compare with the file's bytes; exit status 1 when any file differs or fails

The game tables are looked for in --data, $MXLSAVE_DATA, $MXL_USER_DIR/data, then the editor's user folder.
Without tables a .d2s is read up to its skills section and the items are kept as raw bytes.
"""
import argparse
import json
import os
import re
import sys
import time

from .bits import FormatError
from .tables import Tables
from .d2s import (D2S, CLASSES, DIFFICULTIES, STAT_NAMES, FIXED_POINT_STATS, ACHIEVEMENT_STAT, QUEST_LAYOUT,
                  QUEST_NAMES, QUEST_BITS, STATUS_HARDCORE, STATUS_DIED, STATUS_EXPANSION, STATUS_LADDER)
from .stash import Stash
from .companions import KeyFile, MapFile, AutomapFile
from .items import LOCATION, PANEL


def kind_of(path, data=b''):
    """File kind from the name ('d2s', 'stash', 'key', 'map', 'automap'); backups (.bak-...) keep their kind."""
    name = os.path.basename(path).lower()
    m = re.search(r'\.(d2s|stash|shared|key|map|ma\d)(?=\.|$)', name)
    ext = m.group(1) if m else ''
    if ext == 'd2s' or data[:4] == b'\x55\xaa\x55\xaa':
        return 'd2s'
    if ext in ('stash', 'shared'):
        return 'stash'
    if ext in ('key', 'map'):
        return ext
    if ext.startswith('ma'):
        return 'automap'
    raise FormatError(f'{path}: unknown kind of file')


def load_bytes(data, kind, tables=None):
    if kind == 'd2s':
        return D2S.parse(data, tables)
    if kind == 'stash':
        return Stash.parse(data, tables)
    if kind == 'key':
        return KeyFile.parse(data)
    if kind == 'map':
        return MapFile.parse(data)
    return AutomapFile.parse(data)


def load(path, tables=None):
    with open(path, 'rb') as f:
        data = f.read()
    return load_bytes(data, kind_of(path, data), tables)


def rebuild(obj, tables):
    return obj.to_bytes(tables) if isinstance(obj, (D2S, Stash)) else obj.to_bytes()


def verify(path, tables=None):
    """(True, '') when parse -> rebuild gives the file's bytes, else (False, reason)."""
    with open(path, 'rb') as f:
        data = f.read()
    try:
        out = rebuild(load_bytes(data, kind_of(path, data), tables), tables)
    except (FormatError, ValueError, KeyError, IndexError, OverflowError) as e:
        return False, f'{type(e).__name__}: {e}'
    if out == data:
        return True, ''
    n = next((i for i, (a, b) in enumerate(zip(out, data)) if a != b), min(len(out), len(data)))
    return False, f'rebuilt file differs at byte {n} (sizes {len(out)} / {len(data)})'


# ---------------------------------------------------------------------- human readable dump

def _item_line(it, tables, indent='  '):
    name = tables.base_name(it.code) if tables else ''
    where = f'{LOCATION.get(it.location, it.location)}'
    if it.location == 1:
        where += f' slot {it.equipped}'
    elif it.location != 6:
        where += f' {PANEL.get(it.panel, it.panel)} ({it.x},{it.y})'
    s = f'{indent}{it.code!r:7} {name[:28]:28} {it.quality_name:9} {where:24}'
    if not it.simple:
        s += f' ilvl {it.ilvl:3} id {it.id:08x} stats {len(it.stats)}'
        if it.sockets is not None:
            s += f' sockets {it.socketed_count}/{it.sockets}'
        if it.quantity is not None:
            s += f' qty {it.quantity}'
    return s


def _items(out, title, items, tables):
    out.append(f'{title}: {len(items)}')
    for it in items:
        out.append(_item_line(it, tables))
        for sub in it.socketed:
            out.append(_item_line(sub, tables, '      '))


def dump_text(obj, tables=None):
    out = []
    if isinstance(obj, D2S):
        h = obj.header
        cls = CLASSES[h.cls] if h.cls < len(CLASSES) else h.cls
        flags = [n for bit, n in ((STATUS_HARDCORE, 'hardcore'), (STATUS_DIED, 'died'),
                                  (STATUS_EXPANSION, 'expansion'), (STATUS_LADDER, 'ladder')) if h.status & bit]
        out.append(f'character {h.name_str!r}  {cls}  level {h.level}  version {h.version}  size {h.file_size}  '
                   f'checksum {h.checksum:08x}')
        out.append(f'status 0x{h.status:02x} {flags}  progression {h.progression}  active weapon {h.active_weapon}')
        out.append(f'last played {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(h.last_played))} UTC  '
                   f'created {h.created}  last difficulty/act {h.last_difficulty()}  map seed {h.map_seed:08x}')

        def skill(v):
            if v == 0xFFFF:
                return '-'
            name = tables.skill_name(v & 0x7FFF) if tables else ''
            return f'{v & 0x7FFF}{"L" if v & 0x8000 else ""}' + (f' {name}' if name else '')
        out.append('skill hotkeys: ' + ', '.join(f'{i}={skill(v)}' for i, v in enumerate(h.hotkeys) if v != 0xFFFF))
        out.append(f'mouse skills: left {skill(h.left_skill)} | right {skill(h.right_skill)} | swap left '
                   f'{skill(h.left_skill_swap)} | swap right {skill(h.right_skill_swap)}')
        out.append(f'appearance {h.appearance[:16].hex(" ")} | {h.appearance[16:].hex(" ")}')
        out.append(f'mercenary: id {h.merc_id:08x} dead {h.merc_dead} name #{h.merc_name} type {h.merc_type} '
                   f'experience {h.merc_exp}')
        out.append(f'unknown: 0x26={h.unknown_26} 0x29=0x{h.unknown_29:02x} 0x2A=0x{h.unknown_2a:02x} '
                   f'0x34=0x{h.unknown_34:08x} 0xAF={h.unknown_af} reserved zero: {not any(h.reserved)}')
        for d in range(3):
            w = obj.quests.words[d]
            out.append(f'quests {DIFFICULTIES[d]}:')
            for act, intro, first, n, done in QUEST_LAYOUT:
                qs = ' '.join(f'{w[first + k]:04x}' for k in range(n))
                out.append(f'  {act:7} intro {w[intro]:04x}  quests {qs}' + (f'  finished {w[done]:04x}'
                                                                               if done is not None else ''))
            other = {i: f'{w[i]:04x}' for i in (29, 30, 31, 33, 34, 41, 42, 43, 44, 45, 46, 47) if w[i]}
            out.append(f'  other words: {other}')
            out.append(f'waypoints {DIFFICULTIES[d]}: {obj.waypoints.active(d)}')
            out.append(f'NPC {DIFFICULTIES[d]}: introduced {obj.npcs.intro[d]:016x}  congratulated '
                       f'{obj.npcs.congrats[d]:016x}')
        out.append('stats:')
        for s in obj.stats:
            if s.id == ACHIEVEMENT_STAT:
                what = (f'kills of monster {s.param} {tables.monster_name(s.param) if tables else ""}'
                        if s.param < 0x2000 else f'counter {s.param - 0x2000}')
                out.append(f'  88 [{s.param}] = {s.value}   ({what})')
            elif s.id in FIXED_POINT_STATS:
                out.append(f'  {s.id} = {s.value}   ({STAT_NAMES.get(s.id, "?")}: {s.value / 256:.2f})')
            else:
                out.append(f'  {s.id} = {s.value}   ({STAT_NAMES.get(s.id, "?")})')
        if tables:
            lv = {k: v for k, v in obj.skill_levels(tables).items() if v}
            out.append('skills: ' + ', '.join(f'{k} {tables.skill_name(k)}={v}' for k, v in lv.items()))
        else:
            out.append(f'skills: {len(obj.skills)} bytes, non-zero {[(i, v) for i, v in enumerate(obj.skills) if v]}')
        if obj.items is None:
            out.append(f'items: {len(obj.items_raw)} raw bytes (no game tables: not decoded)')
        else:
            _items(out, 'items', obj.items, tables)
            out.append(f'corpses: {len(obj.corpses)}')
            for c in obj.corpses:
                _items(out, f'  corpse {c.head.hex()}', c.items, tables)
            if obj.merc_items is not None:
                _items(out, 'mercenary items', obj.merc_items, tables)
            else:
                out.append(f'mercenary items: none ("jf" section: {obj.has_merc_section})')
            out.append('iron golem item: ' + ('none' if obj.golem_item is None else _item_line(obj.golem_item, tables, '')))
            if obj.trailing:
                out.append(f'trailing bytes: {obj.trailing.hex()}')
    elif isinstance(obj, Stash):
        out.append(f'stash  version {obj.version}  last page shown {obj.last_page}  pages with items {len(obj.pages)}')
        for p in obj.pages:
            if p.items is None:
                out.append(f'page {p.number}: {p.count} items, {len(p.raw)} raw bytes (no game tables)')
            else:
                _items(out, f'page {p.number}', p.items, tables)
    elif isinstance(obj, KeyFile):
        out.append(f'key bindings  version 0x{obj.version:x}  {len(obj.bindings)} records')
        for r in obj.bindings:
            out.append(f'  function {r.function:2}  key {"-" if r.key == 0xFFFF else hex(r.key):6}  slot {r.slot}')
    elif isinstance(obj, MapFile):
        out.append(f'map seeds  lead {obj.lead}  next slot {obj.next_slot}  newest {obj.newest_seed():08x}')
        for i, s in enumerate(obj.seeds):
            out.append(f'  .ma{i}: seed {s:08x}')
    else:
        lv = obj.levels()
        out.append(f'automap cache  {len(obj.raw)} bytes  {len(lv)} level blocks')
        for i, (o, s) in lv.items():
            out.append(f'  level {i:3}  offset {o:7}  size {s:7}  head {obj.raw[o:o + 20].hex(" ")}')
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='mxlsave', description='Median XL Sigma save files: dump and verify')
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('dump', help='print the contents of a save file')
    d.add_argument('file')
    d.add_argument('--json', action='store_true')
    v = sub.add_parser('verify', help='parse, rebuild and compare with the file')
    v.add_argument('file', nargs='+')
    for p in (d, v):
        p.add_argument('--data', help='folder with the extracted game tables (*.bin)')
        p.add_argument('--no-tables', action='store_true', help='do not use game tables')
    a = ap.parse_args(argv)
    tables = None if a.no_tables else Tables.find(a.data)
    if tables is None and not a.no_tables:
        print('note: game tables not found, items are not decoded (--data DIR)', file=sys.stderr)
    if a.cmd == 'dump':
        try:
            obj = load(a.file, tables)
        except (FormatError, OSError) as e:
            print(f'{a.file}: {e}', file=sys.stderr)
            return 1
        print(json.dumps(obj.as_dict(tables), indent=1) if a.json else dump_text(obj, tables))
        return 0
    bad = 0
    for f in a.file:
        try:
            ok, why = verify(f, tables)
        except OSError as e:
            ok, why = False, str(e)
        print(f'{"OK  " if ok else "FAIL"} {f}' + (f'  - {why}' if why else ''))
        bad += not ok
    return 1 if bad else 0
