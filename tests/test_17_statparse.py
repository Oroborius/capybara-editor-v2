"""Tooltip-line stat parser (mxl_statparse.StatParser, used by the web-page import): the stat lines the tooltip
renderer gives for the items of the sample saves are parsed back into stats that render to the same lines.

The import of a saved median-xl.com page itself (mxl_import.import_character) needs such a page as a fixture and
is not covered (listed in test_19_not_covered.py)."""
import glob
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')


def sample_stat_lists(E):
    """[(where, stats)] of every item with stats in the sample stash and character."""
    out = []
    folder = T.fresh_saves(1)
    for p in sorted(glob.glob(os.path.join(folder, '*.stash'))):
        for it in E.save.parse_stash(p, E.data):
            if it.get('stats'):
                out.append((f'{it["code"].strip()} at {it["page"], it["x"], it["y"]}', it['stats']))
    for p in sorted(glob.glob(os.path.join(folder, '*.d2s'))):
        ch = E.MC.Character(p, E.data)
        for e in ch.items + (ch.merc_items or []):
            if e.it.get('stats'):
                out.append((f'{e.it["code"].strip()} of {ch.name}', e.it['stats']))
    return out


@T.test
def rendered_lines_parse_back():
    E = T.engine()
    import mxl_statparse
    sp = mxl_statparse.StatParser(E.data, char_level=100)
    items = lines_total = missed = changed = 0
    examples = []
    for where, stats in sample_stat_lists(E):
        lines = sp.render(stats)
        if not lines:
            continue
        items += 1
        lines_total += len(lines)
        parsed, missing = sp.parse(lines)
        missed += len(missing)
        again = sp.render(parsed)
        want = [ln for ln in lines if ln not in missing]
        if sorted(mxl_statparse.canon(x) for x in again) != sorted(mxl_statparse.canon(x) for x in want):
            changed += 1
        if (missing or sorted(mxl_statparse.canon(x) for x in again) != sorted(mxl_statparse.canon(x) for x in want)) and len(examples) < 4:
            examples.append(f'{where}: {(missing or want)[:2]}')
    T.check(items > 100 and lines_total > 400, f'only {items} items / {lines_total} lines rendered')
    T.eq(missed, 0, f'lines the parser does not understand (of {lines_total}; e.g. {examples})')
    T.eq(changed, 0, f'items whose parsed stats render differently (of {items}; e.g. {examples})')


@T.test
def merge_and_subtract():
    import mxl_statparse as SP
    T.engine()
    a = [dict(id=39, param=None, value=10), dict(id=39, param=None, value=5), dict(id=83, param=2, value=1)]
    T.eq(sorted((s['id'], s['param'], s['value']) for s in SP.merge(a)), [(39, None, 15), (83, 2, 1)], 'merge')
    left = SP.subtract(SP.merge(a), [dict(id=39, param=None, value=15), dict(id=7, param=None, value=3)])
    T.eq(sorted((s['id'], s['param'], s['value']) for s in left), [(7, None, -3), (83, 2, 1)], 'subtract')
    T.eq(SP.canon('ÿc4+10%  Fire   Resist'), SP.canon('10% fire resist'), 'canon ignores colour codes, "+" and spacing')


T.main(globals())
