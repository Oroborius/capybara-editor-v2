"""Item creator, data layer (mxl_creator.Creator) written to a stash copy with the application's writer: unique at
minimum and maximum rolls, edit path with a changed roll, honorific creation, relic labels, bonus-text search.
The same flows through the Creator tab are in test_32_gui_creator.py."""
import collections
import glob
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')
PLACE = ('x', 'y', 'panel', 'location', 'equipped')


def stash_copy():
    return sorted(glob.glob(os.path.join(T.fresh_saves(1), '*.stash')))[0]


def insert(E, path, blob):
    """Writes the item into the first free place of the stash; returns its (page, x, y)."""
    items = E.save.parse_stash(path, E.data)
    spot = E.save.free_spot(items, E.save.blob_item(blob, E.data), E.data, list(range(E.save.STASH_PAGES)))
    assert spot is not None, 'no free place in the sample stash'
    E.save.edit_stash(path, E.data, insert=[(spot[0], spot[1], spot[2], blob)], backup=False)
    return tuple(spot)


def pick_unique(E, variable=3):
    """A unique armor with a few variable mods (row id, name)."""
    cr = E.cr
    for i, name, u in cr.uniques():
        if u['code'] == 'cotw' or E.data.base(u['code']).kind != 'armor':
            continue
        spec = cr.new_spec('unique', None, i)
        if len([m for m in cr.mods(spec) if m.variable and m.min != m.max]) >= variable:
            return i, name
    raise T.Failed('no unique with variable mods found')


@T.test
def unique_at_min_and_max_into_stash():
    E = T.engine()
    cr = E.cr
    row, name = pick_unique(E)
    path = stash_copy()
    before = T.stash_snap(path, E.data)
    made = {}
    for how in ('min', 'max'):
        spec = cr.new_spec('unique', None, row)
        cr.roll(spec, how)
        blob, rec = cr.build(spec)
        snap0 = T.stash_snap(path, E.data)
        spot = insert(E, path, bytes(blob))
        snap1 = T.stash_snap(path, E.data)
        T.only_changed(snap0, snap1, new=[spot], what=f'{name} ({how})')
        it = T.stash_items(path, E.data)[spot]
        T.eq(it['quality'], 'unique', f'{how}: quality read back')
        T.eq(it.get('set_unique_id'), row, f'{how}: unique row read back')
        T.eq(T.stats_of(it), T.stats_of(rec), f'{how}: stats on disk vs stats built')
        made[how] = it
        for m in cr.mods(spec):
            if m.variable:
                T.eq(spec['rolls'][m.source], m.min if how == 'min' else m.max, f'{how}: roll of {m.source}')
    lo, hi = dict(((s, p), v) for s, p, v in T.stats_of(made['min'])), dict(((s, p), v) for s, p, v in T.stats_of(made['max']))
    T.check(lo != hi, 'minimum and maximum builds have the same stats')
    T.eq(sorted(lo), sorted(hi), 'stat ids of the minimum and the maximum build')
    after = T.stash_snap(path, E.data)
    T.check(all(after[k] == v for k, v in before.items()), 'an item that was in the stash before changed')
    T.eq(len(after), len(before) + 2, 'number of stash items')


@T.test
def edit_path_changed_roll_replaces_item():
    """Edit mode: spec_from_item of an item on disk, one roll changed, written back to the same place."""
    E = T.engine()
    cr = E.cr
    row, name = pick_unique(E)
    path = stash_copy()
    spec = cr.new_spec('unique', None, row)
    cr.roll(spec, 'max')
    spot = insert(E, path, bytes(cr.build(spec)[0]))
    before = T.stash_snap(path, E.data)
    it = T.stash_items(path, E.data)[spot]
    sp2 = cr.spec_from_item(it)
    T.eq(sp2['quality'], 'unique', 'quality of the edit spec')
    m = next(m for m in cr.mods(sp2) if m.variable and m.min != m.max)
    T.eq(sp2['rolls'].get(m.source), m.max, f'roll of {m.source} read from the item')
    sp2['rolls'][m.source] = m.min
    blob2, rec2 = cr.build(sp2)
    E.save.edit_stash(path, E.data, remove=[it['_offset']], insert=[(spot[0], spot[1], spot[2], bytes(blob2))], backup=False)
    after = T.stash_snap(path, E.data)
    T.only_changed(before, after, chg=[spot], what='replace with a changed roll')
    it2 = T.stash_items(path, E.data)[spot]
    T.eq(T.stats_of(it2), T.stats_of(rec2), 'stats on disk vs stats built')
    T.check(T.stats_of(it2) != T.stats_of(it), 'the changed roll changed no stat')
    changed = set(T.stats_of(it2)) ^ set(T.stats_of(it))
    want = {s['id'] for s in m.stats(E.data)}
    T.check({s for s, _p, _v in changed} <= want, f'stats changed {sorted(changed)} outside the mod\'s stats {sorted(want)}')
    T.eq(cr.spec_from_item(it2)['rolls'].get(m.source), m.min, 'roll read back from the replaced item')


@T.test
def honorific_item_created_into_stash():
    E = T.engine()
    cr, C = E.cr, E.C
    base = next(b for b in cr.bases() if b.kind == 'armor' and cr.rare_name_choices(b.code)['rareprefix']
                and cr.rare_name_choices(b.code)['raresuffix'] and cr.honorific_stats(b.code))
    names = cr.rare_name_choices(base.code)
    spec = cr.new_spec('tempered', base.code)
    spec['ilvl'] = max(spec['ilvl'] or 1, 99)
    spec['rare_names'] = (names['rareprefix'][0][0], names['raresuffix'][0][0])
    spec['sockets'] = cr.max_sockets(base.code, spec['ilvl'])
    spec['extra'] = cr.honorific_stats(base.code)
    T.check(any(s['id'] == C.HONORIFIC_STAT for s in spec['extra']), 'recipe output lacks the "orb effects doubled" stat')
    blob, rec = cr.build(spec)
    path = stash_copy()
    before = T.stash_snap(path, E.data)
    spot = insert(E, path, bytes(blob))
    T.only_changed(before, T.stash_snap(path, E.data), new=[spot], what='honorific item')
    it = T.stash_items(path, E.data)[spot]
    T.eq(it['quality'], 'tempered', 'quality read back (9 = honorific)')
    T.eq(T.stats_of(it), T.stats_of(rec), 'stats on disk vs stats built')
    T.eq(tuple(it.get('rare_names') or ()), tuple(rec.get('rare_names') or ()), 'name words')
    T.check(E.rules.rare_name(it, E.data), 'the created honorific item has no name')
    lines = [''.join(t for _c, t in ln) for ln in E.tip.item_tooltip(it, E.data)]
    T.check(len(lines) >= 3, f'tooltip of the created item has {len(lines)} lines')
    sp2 = cr.spec_from_item(it)        # the edit path keeps the item's own bytes: its place in the stash differs
    r1, r2 = C.decode_item(bytes(blob), E.data)[0], C.decode_item(bytes(cr.build(sp2)[0]), E.data)[0]
    T.eq(sorted(k for k in set(r1) | set(r2) if k not in ('id', 'x', 'y') and r1.get(k) != r2.get(k)), [], 'fields changed by the edit path')


@T.test
def honorific_stats_min_below_max():
    E = T.engine()
    cr = E.cr
    n = 0
    for b in cr.bases():
        if b.kind not in ('armor', 'weapons'):
            continue
        hi, lo = cr.honorific_stats(b.code), cr.honorific_stats(b.code, 'min')
        if not hi:
            continue
        n += 1
        T.eq(sorted(s['id'] for s in lo), sorted(s['id'] for s in hi), f'{b.code!r}: stat ids of min and max')
        T.check(all(a['value'] <= c['value'] for a, c in zip(sorted(lo, key=lambda s: s['id']), sorted(hi, key=lambda s: s['id']))),
                f'{b.code!r}: a minimum above its maximum')
        if n >= 60:
            break
    T.check(n >= 20, f'only {n} bases with honorific stats')


def relic_labels(E):
    """The Creator list's labels of the relics: 'Relic - <granted skill>' (Creator.catalog_labels, what
    mxl_creator_gui.fill_list shows)."""
    cr = E.cr
    labels = cr.catalog_labels('unique')
    return [(i, labels[i]) for i, _name, u in cr.uniques() if u['code'] == 'cotw']


def plain_labels(E, q):
    """{row: '<name> - <base>'} (relics: the granted skill): the labels before same-named rows are told apart."""
    import mxl_creator as C
    cr = E.cr
    out = {}
    for i, name, u in (cr.uniques() if q == 'unique' else cr.set_items()):
        nm, bn = C.one_line(name), C.one_line(E.data.base(u['code']).name)
        skills = cr.granted_skills(u) if nm == bn else []
        out[i] = f"{nm} - {' / '.join(skills)}" if skills else f'{nm} - {bn}'
    return out


@T.test
def relic_labels_name_the_skill():
    E = T.engine()
    labels = relic_labels(E)
    T.check(len(labels) > 200, f'only {len(labels)} relics listed')
    T.eq([lab for _i, lab in labels if lab == 'Relic - Bladestorm'], ['Relic - Bladestorm'], '"Relic - Bladestorm" in the list')
    T.eq([lab for _i, lab in labels if lab == 'Relic - Relic'], [], 'relics still labelled "Relic - Relic"')


# Was an open data item (WORKLOG W12): two relic rows grant the same skill (Trinity Beam, at +(1 to 4) with enemy
# resistances and at +(8 to 16)), so two list entries read the same. Each now carries the line that differs.
@T.test
def relic_labels_are_unique():
    E = T.engine()
    seen = {}
    for i, lab in relic_labels(E):
        seen.setdefault(lab, []).append(i)
    T.eq({k: v for k, v in seen.items() if len(v) > 1}, {}, 'relic labels shared by several rows')
    plain = plain_labels(E, 'unique')
    for skill, rows in collections.Counter(plain[i] for i, _l in relic_labels(E)).items():
        if rows == 1:
            continue
        twins = [(i, lab) for i, lab in relic_labels(E) if plain[i] == skill]
        for i, lab in twins:
            T.check(lab.startswith(skill + ': ') and len(lab) > len(skill) + 4, f'relic row {i}: {lab!r} does not say what differs')
            tag = lab[len(skill) + 2:]
            u = E.data.uniques[i]
            text = E.cr.mods_text([(m['prop'], m['param'], m['min'], m['max']) for m in u['mods']], u['code'])
            T.check(any(tag.rstrip('.') in ln or ln.startswith(tag[:40]) for ln in text), f'relic row {i}: {tag!r} is not one of its bonus lines {text}')


@T.test
def catalogue_labels_are_unique_and_keep_unique_names():
    """Unique and set lists: no two rows read the same; a row whose '<name> - <base>' was already alone keeps
    exactly that label; a row told apart starts with it."""
    E = T.engine()
    for q in ('unique', 'set'):
        labels = E.cr.catalog_labels(q)
        rows = E.cr.uniques() if q == 'unique' else E.cr.set_items()
        T.eq(sorted(labels), sorted(i for i, _n, _u in rows), f'{q}: rows with a label')
        seen = {}
        for i, lab in labels.items():
            seen.setdefault(lab.casefold(), []).append(i)
        T.eq({k: v for k, v in seen.items() if len(v) > 1}, {}, f'{q} labels shared by several rows')
        plain = plain_labels(E, q)
        count = collections.Counter(v.casefold() for v in plain.values())
        told = 0
        for i, lab in labels.items():
            if count[plain[i].casefold()] == 1:
                T.eq(lab, plain[i], f'{q} row {i}: a label that was already unique')
            else:
                told += 1
                T.check(lab.startswith(plain[i]), f'{q} row {i}: {lab!r} does not start with {plain[i]!r}')
                T.check(len(lab) <= len(plain[i]) + 80, f'{q} row {i}: label of {len(lab)} characters')
        T.check(told > 0, f'{q}: the sample tables have no same-named rows (nothing was checked)')
        for lab in labels.values():
            T.check('\n' not in lab and lab == lab.strip(), f'{q}: label {lab!r}')


@T.test
def empty_rows_that_are_not_enabled_are_not_listed():
    """A unique row without any mod is listed only when the game's table enables it (its own quest / reagent
    items); the leftover rows - 90 empty relics and the second "Windforce" in 2.14.6 - are not."""
    E = T.engine()
    cr = E.cr
    listed = {i for i, _n, _u in cr.uniques()}
    flags = [cr.unique_enabled(i) for i in range(len(E.data.uniques))]
    T.check(sum(flags) > 1000 and not all(flags), f'enabled flag: {sum(flags)} of {len(flags)} rows enabled')
    for i, u in enumerate(E.data.uniques):
        if not u['mods'] and not flags[i]:
            T.check(i not in listed, f'unique row {i} ({u["name"]}): empty and not enabled, but listed')
    empty = [i for i in listed if not E.data.uniques[i]['mods']]
    for i in empty:
        T.check(flags[i], f'unique row {i}: listed without mods and not enabled')
        spec = cr.new_spec('unique', None, i)
        cr.roll(spec, 'max')
        blob, _rec = cr.build(spec)
        T.check(blob[:2] == b'JM', f'unique row {i}: does not build')


@T.test
def base_labels_are_unique_and_without_placeholders():
    """Base items of the same name are told apart (description, picture, at last the item code) and no label
    shows a format placeholder ("Free Attribute Points: %d": the game fills that in when it draws the item)."""
    E = T.engine()
    cr = E.cr
    bases = [b for b in cr.bases() if b.code != 'gld ']
    rows = cr.base_list_rows(bases)
    T.eq([c for _l, c in rows], [b.code for b in bases], 'one row per base, in order')
    seen = {}
    for lab, code in rows:
        seen.setdefault(lab.casefold(), []).append(code)
        T.check('%d' not in lab and '%s' not in lab, f'{code!r}: placeholder in {lab!r}')
        T.check(lab.endswith(']'), f'{code!r}: {lab!r}')
    T.eq({k: v for k, v in seen.items() if len(v) > 1}, {}, 'base labels shared by several items')
    names = collections.Counter(cr.display_name(b.code) for b in bases)
    alone = next(b for b in bases if names[cr.display_name(b.code)] == 1 and b.kind == 'weapons' and ' / ' not in cr.display_name(b.code))
    T.eq(dict((c, l) for l, c in rows)[alone.code], f'{cr.display_name(alone.code)} [Weapon]', 'label of a base whose name is alone')
    T.eq(cr.desc_summary('02^ ') if '02^ ' in E.data.bases else 'Right-click: Free Attribute Points',
         'Right-click: Free Attribute Points', 'description summary of a Custom Signet of Learning')


@T.test
def bonus_text_search_finds_arrogance():
    """Searching the creator list by bonus: 'stormlord' is in the bonus text of the unique 'Arrogance'."""
    E = T.engine()
    cr = E.cr
    hits = [name for i, name, _u in cr.uniques() if 'stormlord' in cr.bonus_text('unique', i)]
    T.check(any('Arrogance' in n for n in hits), f'"stormlord" finds {hits[:6]}, not Arrogance')
    T.check(len(hits) < 40, f'"stormlord" matches {len(hits)} uniques')
    i, name = next((i, n) for i, n, _u in cr.uniques() if 'Arrogance' in n)
    text = cr.bonus_text('unique', i)
    T.check(text == text.lower() and len(text) > 20, f'bonus text of {name}: {text[:60]!r}')
    for kind, rows in (('set', cr.set_items()), ('runeword', cr.runewords())):
        T.check(cr.bonus_text(kind, rows[len(rows) // 2][0]), f'no bonus text for a {kind} row')


# BUG (known, WORKLOG W14): "a no-op Replace through the creator's edit mode assigns a new item id and changes the
# parsed stats of 18 of 80 test items". The creator rebuilds from a spec; the Item stats tab is the lossless path.
@T.test
def noop_edit_of_sample_items_is_byte_identical():
    E = T.engine()
    cr = E.cr
    path = stash_copy()
    raw = T.read(path)
    n = bad_bytes = bad_stats = 0
    examples, why = [], {}
    for it in E.save.parse_stash(path, E.data):
        blob = bytes(E.save.item_blob(raw, it))
        try:
            spec = cr.spec_from_item(it)
        except E.C.CreateError:
            continue                              # simple / unknown rows: the creator does not open them
        n += 1
        rec, size = E.C.decode_item(blob, E.data)
        again = bytes(cr.build(spec)[0])
        rec2, size2 = E.C.decode_item(again, E.data)
        for k in PLACE:                           # the rebuilt item is put back where the original is
            if k in rec:
                rec2[k] = rec[k]
        again = bytes(E.C.encode_item(rec2, E.data)) + again[size2:]
        if again != blob:
            bad_bytes += 1
            fields = sorted(k for k in set(rec) | set(rec2) if rec.get(k) != rec2.get(k))
            for k in fields:
                why[k] = why.get(k, 0) + 1
            if T.stats_of(rec2) != T.stats_of(rec):
                bad_stats += 1
                if len(examples) < 3:
                    examples.append(f'{it["code"].strip()} {str(it.get("name"))[:24]!r}')
    T.check(n > 100, f'only {n} items the creator edits')
    T.eq(bad_stats, 0, f'items whose STATS change in a no-op edit (of {n}; e.g. {examples})')
    T.eq(bad_bytes, 0, f'items whose bytes change in a no-op edit (of {n}; record fields that differ: {why})')


@T.test
def any_item_can_be_ethereal():
    """User (2026-11-21): any item can be ethereal - charms, jewels, rings, amulets, set items too. The creator
    no longer refuses it; the flag reads back from the built bytes."""
    E = T.engine()
    cr = E.cr
    done = []
    for code in ('rin ', 'amu ', 'jew ', 'cm1 '):
        if code not in E.data.bases:
            continue
        spec = cr.new_spec('normal', code)
        spec['ethereal'] = True
        blob, rec = cr.build(spec)
        T.check(rec['flags'] & E.C.FLAG_ETHEREAL, f'{code}: ethereal flag built')
        it = E.save.blob_item(bytes(blob), E.data)
        T.check(it.get('ethereal'), f'{code}: ethereal read back')
        done.append(code)
    T.check(len(done) >= 3, f'bases tried: {done}')
    for i, _name, _u in cr.set_items():
        spec = cr.new_spec('set', None, i)
        spec['ethereal'] = True
        _blob, rec = cr.build(spec)
        T.check(rec['flags'] & E.C.FLAG_ETHEREAL, 'set item: ethereal flag built')
        break


@T.test
def proc_texts_name_their_skill_and_level():
    """Mega Impact / Thunderfury / Area Effect Attack / Amazing Grace: the param packs skill << 6 | level (the game's
    own rows: a hidden skill at level 1). The creator's label names that skill, not a skilldesc entry; adding one
    with another skill keeps the level bits (an unpacked index wrote level 0 and a wrong skill)."""
    E = T.engine()
    import mxl_statnames
    procs = [t for t in E.cr.orange_texts() if t['skilldesc']]
    T.check(len(procs) >= 4, f'proc texts: {len(procs)}')
    for t in procs:
        p = t['display']['param']
        T.eq(p & 63, 1, f"{t['label']}: level 1")
        T.check(mxl_statnames.skill_label(E.data, p >> 6) is not None, f"{t['label']}: a real skill id {p >> 6}")
        T.check(f'level {p & 63}' in t['label'] and 'skilldesc' not in t['label'], t['label'])


@T.test
def recipe_damage_pair_keeps_its_range():
    """A cube recipe's "+5-10 damage" (a damage pair: min stat from the mod's min, max stat from its max) was
    applied as 10-10 (the mod collapsed to its max before the stats were made). It keeps both ends now."""
    E = T.engine()
    cr, d = E.cr, E.data
    seen = 0
    for rec in cr.inplace_recipes():
        pairs = [(p, lo, hi) for p, _pa, lo, hi in rec['mods']
                 if lo < hi and any(f in (15, 16) for f in d.prop_funcs[p])]
        if not pairs:
            continue
        seen += 1
        p, lo, hi = pairs[0]
        stats = list(d.props[p])
        got = {sid: v for sid, _pa, v in cr.recipe_deltas(rec, 'max')}
        mn, mx = [sid for sid, f in zip(stats, d.prop_funcs[p]) if f == 15], [sid for sid, f in zip(stats, d.prop_funcs[p]) if f == 16]
        if mn:
            T.eq(got.get(mn[0]), lo, f'recipe {rec.get("row")}: min damage {lo}')
        if mx:
            T.eq(got.get(mx[0]), hi, f'recipe {rec.get("row")}: max damage {hi}')
    T.check(seen, 'a recipe with a damage pair')


@T.test
def unsocket_runeword_drops_its_stats():
    """Unsocketing a runeword (the user): the runes come out and the stats the runeword gave go with them (its own
    stat list, flag and id); the item's own stats stay; Remove Sockets the same."""
    E = T.engine()
    cr, d = E.cr, E.data
    import mxl_socket_menu as SM
    from mxl_creator import FLAG_RUNEWORD, decode_item
    for row in range(len(d.runewords)):
        bases = [b for b in cr.runeword_bases(row) if cr.max_sockets(b.code, 99) >= len(d.runewords[row][1])]
        if bases and len(d.runewords[row][1]) >= 2:
            break
    spec = cr.new_spec('runeword', bases[0].code, row)
    spec['sockets'] = len(d.runewords[row][1])
    spec['ilvl'] = 99
    cr.roll(spec, 'max')
    blob = bytes(cr.build(spec)[0])
    rec, _n = SM.children(blob, d)
    T.check(rec['flags'] & FLAG_RUNEWORD and rec.get('stats_runeword'), 'a runeword with its own stat list')
    own = sorted((s['id'], s.get('param'), s['value']) for s in rec.get('stats') or [])
    new, loose = SM.emptied(blob, d)
    r2 = decode_item(new, d)[0]
    T.eq(bool(r2['flags'] & FLAG_RUNEWORD), False, 'unsocket: no longer a runeword')
    T.eq(r2.get('stats_runeword'), None, 'unsocket: the runeword stats are gone')
    T.eq(sorted((s['id'], s.get('param'), s['value']) for s in r2.get('stats') or []), own, 'unsocket: own stats kept')
    T.eq(len(loose), len(d.runewords[row][1]), 'unsocket: every rune out')
    T.eq(SM.current(r2), spec['sockets'], 'unsocket: sockets kept')
    new2, n = SM.without(blob, d)
    r3 = decode_item(new2, d)[0]
    T.eq((bool(r3['flags'] & FLAG_RUNEWORD), r3.get('stats_runeword')), (False, None), 'remove sockets: no runeword')


T.main(globals())
