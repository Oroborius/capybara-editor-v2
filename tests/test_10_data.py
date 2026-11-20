"""Game data: every extracted table loads, and tools/audit_game_data.py (builds and round-trips every catalogue
item) reports no round-trip failure."""
import collections
import os
import re
import struct
import subprocess
import sys

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')

# audit problem classes that mean "the editor writes or reads an item wrongly" (as opposed to oddities of the
# game's own tables, which are listed by audit_open_data_items below)
ROUNDTRIP = ('build raised', 'built bytes do not parse', 'stats read back differently',
             'record does not re-encode identically', 'decode / re-encode raised', 'edit path', 'tooltip raised',
             'honorific', 'item does not re-encode identically', 'no-op character rebuild', 'file could not be read',
             'audit step crashed', 'creator refuses to build', 'property cannot be turned into stats',
             'display name raised', 'unique / set')


@T.test
def every_table_file_loads():
    E = T.engine()
    d = E.data
    names = sorted(f[:-4] for f in os.listdir(d.folder) if f.endswith('.bin'))
    T.check(len(names) >= 100, f'only {len(names)} .bin tables in {d.folder}')
    record_tables = 0
    for n in names:
        raw = T.read(os.path.join(d.folder, n + '.bin'))
        count = struct.unpack_from('<I', raw, 0)[0] if len(raw) >= 4 else 0
        if not count or (len(raw) - 4) % count or (len(raw) - 4) // count > 4096:
            # not a table of fixed-size records: the compiled formula files (itemscode.bin ...)
            T.check(n.endswith('code') or len(raw) <= 4, f'{n}.bin: {len(raw)} bytes do not divide into {count} records')
            continue
        try:
            rows = d._rows(n)
            T.eq(len(rows), count, f'{n}.bin: rows read vs the count in its header')
            record_tables += 1
        except Exception as e:
            T.check(False, f'{n}.bin does not load: {e!r}')
    T.check(record_tables >= 100, f'only {record_tables} record tables loaded')
    import tbl
    for f in sorted(os.listdir(d.folder)):
        if f.endswith('.tbl'):
            try:
                T.check(len(tbl.load_tbl(os.path.join(d.folder, f))) > 0, f'{f}: empty')
            except Exception as e:
                T.check(False, f'{f} does not load: {e!r}')


@T.test
def parsed_tables_are_filled():
    d = T.engine().data
    floor = dict(bases=2000, uniques=1500, set_items=150, runewords=200, runeword_mods=200, isc=400, props=300,
                 skill_names=1000, skill_class=2500, strings=15000, gems=100, itypes=250, monster_names=1000,
                 rare_prefix=30, rare_suffix=50, item_index=2000)
    for name, n in floor.items():
        T.check(len(getattr(d, name)) >= n, f'data.{name}: {len(getattr(d, name))} entries, expected at least {n}')
    for k in ('magicprefix', 'magicsuffix', 'automagic'):
        T.check(len(d.affixes.get(k) or ()) > 50, f'data.affixes[{k!r}] is short')
    T.check(d.base('cotw').name, 'base cotw (relic) has no name')
    for sid in (0, 39, 83, 97, 107, 415):
        T.check(sid in d.isc and d.isc[sid].get('bits'), f'stat {sid} missing from itemstatcost or without save bits')


@T.test
def creator_catalogue_counts():
    cr = T.engine().cr
    T.check(len(cr.uniques()) > 1500, f'creator lists {len(cr.uniques())} uniques')
    T.check(len(cr.set_items()) > 150, f'creator lists {len(cr.set_items())} set items')
    T.check(len(cr.runewords()) > 200, f'creator lists {len(cr.runewords())} runewords')
    T.check(len(cr.bases()) > 2000, f'creator lists {len(cr.bases())} bases')
    T.check(len(cr.honorific_recipes()) > 0, 'no honorific recipe found')


_audit = {}
_info = {}                        # {section title: {game-data property: count}} - the audit's 'i' lines


def title_of(cur):
    return next(t for t, v in _audit.items() if v is cur)


def audit():
    """{section title: (totals {key: text}, problems {class: count})}, the audit run once per process."""
    if _audit:
        return _audit
    user, saves = T.fresh_user(), T.fresh_saves()
    out = os.path.join(T.tmp(), 'audit.txt')
    p = subprocess.run([sys.executable, '-B', os.path.join(T.REPO, 'tools', 'audit_game_data.py'), '--app', T.APP,
                        '--user-dir', user, '--save-dir', saves, '--out', out],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240,
                       env=dict(os.environ, MXL_USER_DIR=user, MXL_SAVE_DIR=saves))
    if p.returncode != 0:
        raise T.Failed('audit_game_data.py exit code %d: %s' % (p.returncode, p.stdout.decode(errors='replace')[-400:]))
    cur = None
    with open(out, encoding='utf-8') as f:
        for line in f:
            if line.startswith('== '):
                cur = _audit.setdefault(line[3:].strip(), ({}, {}))
            elif cur is not None and line.startswith('   ! '):
                m = re.match(r'   ! (.*): (\d+)$', line.rstrip())
                cur[1][m.group(1)] = int(m.group(2))
            elif line.startswith('   i '):
                m = re.match(r'   i (.*): (\d+)$', line.rstrip())
                _info.setdefault(title_of(cur), {})[m.group(1)] = int(m.group(2))
            elif cur is not None and re.match(r'   \S', line) and ': ' in line:
                k, v = line.strip().rsplit(': ', 1)
                cur[0][k] = v
    return _audit


@T.test
def audit_runs_every_section():
    a = audit()
    for title in ('Unique items', 'Relics (uniques on base cotw)', 'Set items', 'Runewords', 'Mystic orbs',
                  'Gems and runes (socket fillers)', 'Other base items', 'Honorific items (quality 9, cube output)',
                  'Skills table', 'Items of the save files'):
        T.check(title in a, f'audit section missing: {title}')
    for title, (_tot, problems) in a.items():
        T.check('audit step crashed' not in problems, f'{title}: audit step crashed')


@T.test
def audit_roundtrip_no_failures():
    """Build at min and max -> parse -> same stats -> re-encode identical -> edit path: no failure anywhere."""
    for title, (_tot, problems) in audit().items():
        for cls, n in problems.items():
            T.check(not cls.startswith(ROUNDTRIP), f'{title}: {cls}: {n}')


@T.test
def audit_every_listed_item_builds():
    a = audit()
    for title in ('Unique items', 'Relics (uniques on base cotw)', 'Set items', 'Mystic orbs',
                  'Gems and runes (socket fillers)', 'Other base items'):
        tot = a[title][0]
        T.eq(tot.get('built'), tot.get('listed by the creator'), f'{title}: built vs listed')
        T.check(int(tot.get('built') or 0) > 50, f'{title}: only {tot.get("built")} built')
    tot, problems = a['Runewords']
    hidden = problems.get('no base can hold it (the creator list hides it)', 0)
    T.eq(int(tot['built']), int(tot['listed by the creator']) - hidden, 'Runewords: built vs listed minus hidden')
    T.check(int(a['Honorific items (quality 9, cube output)'][0].get('built') or 0) > 10, 'honorific: few built')


@T.test
def audit_save_items_clean():
    tot, problems = audit()['Items of the save files']
    T.check(int(tot.get('items') or 0) > 100, f'save items audited: {tot.get("items")}')
    T.check(int(tot.get('character files') or 0) >= 1 and int(tot.get('stash files') or 0) >= 1, f'files: {tot}')
    T.eq(problems, {}, 'problems on the items of the sample saves')


@T.test
def audit_skill_names_resolve():
    tot, problems = audit()['Skills table']
    T.eq(tot.get('rows the editor has no name for'), '0', 'skills without a name')
    T.eq(tot.get('of these without a name'), '0', 'skill ids used by items without a name')
    T.eq(problems, {}, 'skills table problems')


# The open data items of WORKLOG W12 are closed: same-named rows are told apart (Creator.catalog_labels /
# base_list_rows), the empty not-enabled "Windforce" row is hidden, and what is a property of the game's own tables
# is listed by the audit as information (next test).
@T.test
def audit_open_data_items():
    """Everything else the audit lists as a problem. Not round-trip failures: oddities of the game's tables the
    editor does not handle. Kept visible here so that a new class shows up."""
    left = []
    for title, (_tot, problems) in audit().items():
        for cls, n in problems.items():
            if not cls.startswith(ROUNDTRIP) and not cls.startswith('no base can hold it'):
                left.append(f'{title}: {cls}: {n}')
    T.eq(left, [], 'open data items')


# what the audit may list as a property of the game's data ('i' lines), and why it is no editor defect
GAME_DATA = {
    "game data: mod value outside the stat's save range (the creator stores the nearest value)":
        'the table asks for more than the save bits hold; Creator.roll narrows the range',
    'game data: enabled row without any mod (quest / reagent items)':
        'the item\'s text is its base item\'s description',
    'game data: name string starts with a line break (one empty line ends the tooltip)':
        'the string itself begins with a line break',
}


@T.test
def audit_game_data_properties_are_known():
    """The audit's information lines: only the known classes, each really present in the sample tables (a class
    that no longer occurs should leave this list), none of them a round-trip matter."""
    audit()
    seen = collections.Counter()
    for title, classes in _info.items():
        for cls, n in classes.items():
            T.check(cls in GAME_DATA, f'{title}: unknown information class {cls!r} ({n})')
            T.check(n > 0, f'{title}: {cls}: {n}')
            seen[cls] += n
    for cls in GAME_DATA:
        T.check(seen[cls] > 0, f'not reported any more: {cls!r}')


@T.test
def over_range_mod_values_are_stored_at_the_nearest_value():
    """What the creator does with a mod whose table value the stat's save bits cannot hold (the audit's 'mod value
    outside the save range' rows): the item builds, the stat is stored at the end of its range, never wrapped."""
    E = T.engine()
    d, cr = E.data, E.cr
    import mxl_rules
    found = 0
    for i, _name, u in cr.uniques():
        over = []
        for m in u['mods']:
            if not 0 <= m['prop'] < len(d.props):
                continue
            for v in (m['min'], m['max']):
                for s in mxl_rules.mods_stats([(m['prop'], m['param'], v, v)], d, 'min'):
                    c = d.isc.get(s['id'])
                    if c and c.get('bits') and not 0 <= s['value'] + c['add'] < (1 << c['bits']):
                        over.append((s['id'], s['value'], -c['add'], (1 << c['bits']) - 1 - c['add']))
        if not over:
            continue
        found += 1
        for how in ('min', 'max'):
            spec = cr.new_spec('unique', None, i)
            auto = cr.auto_choices(spec['code'], spec['ilvl'])
            if auto:
                spec['auto'] = auto[0][0]
            cr.roll(spec, how)
            _blob, rec = cr.build(spec)
            for sid, want, lo, hi in over:
                got = [s['value'] for s in rec['stats'] if s['id'] == sid]
                T.check(got and all(lo <= g <= hi for g in got), f'unique {i} stat {sid} ({how}): stored {got}, range {lo}..{hi}')
                if how == 'max' and want > hi:
                    T.eq(got, [hi], f'unique {i} stat {sid}: table value {want} above the range is stored as')
                if how == 'min' and want < lo:
                    T.eq(got, [lo], f'unique {i} stat {sid}: table value {want} below the range is stored as')
    T.check(found > 0, 'the sample tables have no mod value outside a save range (nothing was checked)')


T.main(globals())
