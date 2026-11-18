"""Item tooltip damage lines with the minimum above the maximum (docs/review/gui.md finding 9): the collector wrote
"One-Hand Damage: 145 to 132", "Adds 70-45 Damage", "Adds 120-0 Magic Damage" for 16 of 223 runewords and about 18
of 251 crafted bases. src/mxl_dmg_text.py: weapon line max = min + 1, such "Adds" pairs as the stats' own lines.
Every other tooltip stays exactly the host's."""
import glob
import os
import random
import re
import types

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')

P_TO = re.compile(r'(?<![-\d])(\d+) to (\d+)')
P_ADDS = re.compile(r'Adds (-?\d+)-(-?\d+)')


def lines(it, data):
    from mxl_tooltip import item_tooltip
    return [''.join(seg[1] for seg in ln) for ln in item_tooltip(it, data, None)]


def wrong(ls):
    out = []
    for ln in ls:
        for m in P_TO.finditer(ln):
            if int(m.group(1)) > int(m.group(2)):
                out.append(ln)
        for m in P_ADDS.finditer(ln):
            a, b = int(m.group(1)), int(m.group(2))
            if a > b or 0 in (a, b):
                out.append(ln)
    return out


def _prep():
    E = T.engine()
    import mxl_creator_gui as G
    fake = types.SimpleNamespace(cr=E.cr, data=E.data)
    return E, (lambda spec: G.CreatorWindow.prepare_defaults(fake, spec))


def runeword_spec(E, prep, row, how='max'):
    cr, d = E.cr, E.data
    bases = cr.runeword_bases(row)
    if not bases:
        return None
    spec = cr.new_spec('runeword', bases[0].code, row)
    spec['sockets'] = len(d.runewords[row][1])
    spec['ilvl'] = 99
    prep(spec)
    cr.roll(spec, how)
    return spec


def created(E, spec):
    try:
        return E.save.blob_item(E.cr.build(spec)[0], E.data)
    except E.C.CreateError:              # a few runewords have no name string (not creatable at all)
        return None


def rw_row(E, name):
    return next(i for i, r in enumerate(E.data.runewords) if r[0] == name)


@T.test
def every_runeword_and_crafted_base_reads_min_below_max():
    E, prep = _prep()
    cr, d = E.cr, E.data
    bad, n = [], 0
    for how in ('max', 'min'):
        for row in range(len(d.runewords)):
            spec = runeword_spec(E, prep, row, how)
            it = spec and created(E, spec)
            if it is None:
                continue
            n += 1
            bad += [(d.runewords[row][0], how, w) for w in wrong(lines(it, d))]
        random.seed(55)
        for b in cr.bases():
            if b.kind == 'misc' or not cr.can_have_quality(b.code, 'crafted'):
                continue
            spec = cr.new_spec('crafted', b.code)
            spec['ilvl'], spec['max_sockets'] = 99, True
            prep(spec)
            cr.reroll_crafted(spec)
            cr.roll(spec, how)
            it = created(E, spec)
            if it is None:
                continue
            n += 1
            bad += [(b.code, how, w) for w in wrong(lines(it, d))]
    T.check(n > 900, f'only {n} items built')
    T.check(not bad, f'{len(bad)} min > max lines, e.g. {bad[:4]}')


@T.test
def known_lines():
    E, prep = _prep()
    d = E.data
    exp = {'Anak': ['One-Hand Damage: 145 to 146', '+70 to Minimum Damage', '+45 to Maximum Damage'],
           'Aether': ['+120 to Minimum Magic Damage'],
           'Black Cat': ['+8 to Minimum Fire Damage'],
           'Jaguar': ['+203 to Minimum Damage', '+202 to Maximum Damage']}
    for name, want in exp.items():
        it = created(E, runeword_spec(E, prep, rw_row(E, name)))
        ls = lines(it, d)
        for w in want:
            T.check(any(ln.startswith(w) for ln in ls), f'{name}: no line {w!r} in {ls}')
        T.check(not any('Maximum Magic Damage' in ln or 'Maximum Fire Damage' in ln for ln in ls if '+0 ' in ln),
                f'{name}: a +0 line: {ls}')


@T.test
def other_tooltips_unchanged():
    """Every tooltip without a min > max pair is the host's own, line for line: both sample stashes, every
    unique and set item at its maximum rolls."""
    E, _prep_ = _prep()
    import mxl_dmg_text
    d, cr = E.data, E.cr
    items = []
    for folder in (T.SRC_SAVES, T.SRC_SAVES2):
        for p in sorted(glob.glob(os.path.join(folder or '', '*.stash'))):
            items += list(T.stash_items(p, d).values())
    for q, rows in (('unique', d.uniques), ('set', d.set_items)):
        for row in range(len(rows)):
            spec = cr.new_spec(q, row=row)
            spec['ilvl'] = max(spec['ilvl'], 99)
            cr.roll(spec, 'max')
            it = created(E, spec)
            if it is not None:
                items.append(it)
    T.check(len(items) > 1500, f'only {len(items)} items')
    new = [lines(it, d) for it in items]
    with mxl_dmg_text.host_text():
        old = [lines(it, d) for it in items]
    diff = [(o, n) for o, n in zip(old, new) if o != n]
    T.check(all(wrong(o) for o, _ in diff), f'changed without a min > max line: {[x for x in diff if not wrong(x[0])][:2]}')
    T.check(len(diff) <= 4, f'{len(diff)} tooltips changed: {diff[:3]}')
    T.check(not any(wrong(n) for n in new), 'a min > max line is left')


@T.test
def created_item_is_sane_on_disk():
    """The created Anak (min damage 70 over max 45, as the tables give it) written into a stash copy: reads back
    with the same stats, the independent parser finds no problem."""
    E, prep = _prep()
    d = E.data
    spec = runeword_spec(E, prep, rw_row(E, 'Anak'))
    blob, rec = E.cr.build(spec)
    path = sorted(glob.glob(os.path.join(T.fresh_saves(1), '*.stash')))[0]
    items = E.save.parse_stash(path, d)
    spot = E.save.free_spot(items, E.save.blob_item(blob, d), d, list(range(E.save.STASH_PAGES)))
    E.save.edit_stash(path, d, insert=[(spot[0], spot[1], spot[2], blob)], backup=False)
    it = T.stash_items(path, d)[tuple(spot)]
    T.eq(T.stats_of(it, 'stats_runeword'), T.stats_of(E.save.blob_item(blob, d), 'stats_runeword'), 'runeword stats')
    import mxl_savecheck
    mxl_savecheck.lib()
    import mxlsave
    from mxlsave.check import check_bytes
    _obj, problems = check_bytes(T.read(path), 'stash', mxlsave.Tables(d.folder))
    T.check(not problems, f'mxlsave: {problems[:3]}')
    T.check(any(ln.startswith('One-Hand Damage: 145 to 146') for ln in lines(it, d)), 'tooltip from disk')


T.main(globals())
