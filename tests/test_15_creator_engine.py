"""Item creator, data layer (mxl_creator.Creator) written to a stash copy with the application's writer: unique at
minimum and maximum rolls, edit path with a changed roll, honorific creation, relic labels, bonus-text search.
The same flows through the Creator tab are in test_32_gui_creator.py."""
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
    sp2 = cr.spec_from_item(it)
    r1, r2 = C.decode_item(bytes(blob), E.data)[0], C.decode_item(bytes(cr.build(sp2)[0]), E.data)[0]
    T.eq(sorted(k for k in set(r1) | set(r2) if k != 'id' and r1.get(k) != r2.get(k)), [], 'fields changed by the edit path')


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
    """The Creator list's labels of the relics: 'Relic - <granted skill>' (mxl_creator_gui.fill_list's rule)."""
    cr = E.cr
    out = []
    for i, name, u in cr.uniques():
        if u['code'] != 'cotw':
            continue
        skills = cr.granted_skills(u)
        out.append((i, f"{name} - {' / '.join(skills)}" if skills else f'{name} - {E.data.base(u["code"]).name}'))
    return out


@T.test
def relic_labels_name_the_skill():
    E = T.engine()
    labels = relic_labels(E)
    T.check(len(labels) > 200, f'only {len(labels)} relics listed')
    T.eq([lab for _i, lab in labels if lab == 'Relic - Bladestorm'], ['Relic - Bladestorm'], '"Relic - Bladestorm" in the list')
    T.eq([lab for _i, lab in labels if lab == 'Relic - Relic'], [], 'relics still labelled "Relic - Relic"')


# BUG (open data item of WORKLOG W12): two relic rows grant the same skill, so two list entries read the same.
@T.test(xfail='relic rows 1191 and 1290 both read "Relic - Trinity Beam" in the creator list')
def relic_labels_are_unique():
    E = T.engine()
    seen = {}
    for i, lab in relic_labels(E):
        seen.setdefault(lab, []).append(i)
    T.eq({k: v for k, v in seen.items() if len(v) > 1}, {}, 'relic labels shared by several rows')


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
@T.test(xfail='creator edit mode: spec_from_item -> build of an untouched stash item does not give its bytes back')
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


T.main(globals())
