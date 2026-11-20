"""Median XL reagents made in the Creator get what the game puts on them (Creator.reagent_stats: the mods of the cube
recipe that makes the reagent - Quantity plus the "display text" stat 377 of a gem cluster / rune container), and
plan_container_fill puts one of every container on adjacent empty stash pages or refuses."""
import glob
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')


def game_copies(E):
    """{code: [(blob, stats list in file order)]} of the game-made reagents with a display text in the sample stashes."""
    out = {}
    for folder in (T.fresh_saves(1), T.fresh_saves(2) if T.saves_ok(T.SRC_SAVES2) else None):
        if not folder:
            continue
        for path in glob.glob(os.path.join(folder, '*.stash')):
            raw = T.read(path)
            for it in E.save.parse_stash(path, E.data):
                st = [(s['id'], s.get('param') or 0, s['value']) for s in it.get('stats') or ()]
                if it.get('quality') == 'normal' and any(s[0] == 377 for s in st) and (501, 0, 1000) in st:
                    out.setdefault(it['code'], []).append((bytes(E.save.item_blob(raw, it)), st))
    return out


@T.test
def created_reagents_match_game_made_ones():
    E = T.engine()
    copies = game_copies(E)
    if not copies:
        T.skip('no game-made full cluster / container with a display text in the samples')
    for code, made in sorted(copies.items()):
        blob, rec = E.cr.build(E.cr.new_spec('normal', code))
        st = [(s['id'], s.get('param') or 0, s['value']) for s in rec['stats']]
        T.eq(st, made[0][1], f'{code.strip()}: stat list of a created item vs the game-made one')
        # the stat list is the item's tail (after the random id): the same bytes as the game's copy
        T.eq(bytes(blob)[-10:], made[0][0][-10:], f'{code.strip()}: stat bytes at the end of the item')


@T.test
def every_container_has_its_game_default_stats():
    E = T.engine()
    codes = E.C.container_codes(E.data)
    T.check(len(codes) > 90, f'only {len(codes)} containers found')
    T.eq([s['id'] for s in E.cr.reagent_stats('gc01')], [377, 501], 'Ruby Cluster: display text + Quantity')
    for code in codes:
        blob, rec = E.cr.build(E.cr.new_spec('normal', code))
        T.check(rec is not None and (501, None, 1000) in [(s['id'], s.get('param'), s['value']) for s in rec['stats']],
                f'{code.strip()}: Quantity 1000 on the created item')


def _stash():
    return sorted(glob.glob(os.path.join(T.fresh_saves(1), '*.stash')))[0]


@T.test
def container_fill_uses_adjacent_empty_pages():
    E = T.engine()
    path = _stash()
    items = E.save.parse_stash(path, E.data)
    used = {it['page'] for it in items}
    plan = E.C.plan_container_fill(E.cr, items, E.save.STASH_PAGES)
    T.check(plan is not None, 'no plan on a stash with empty pages')
    pages = sorted({p for p, _x, _y, _b in plan})
    T.eq(pages, list(range(pages[0], pages[0] + len(pages))), 'pages used are adjacent')
    T.check(not used & set(pages), f'a used page was filled: {sorted(used & set(pages))}')
    T.eq(len(plan), len(E.C.container_codes(E.data)), 'one of every container')
    snap0 = T.stash_snap(path, E.data)
    E.save.edit_stash(path, E.data, insert=plan, backup=False)
    T.only_changed(snap0, T.stash_snap(path, E.data), new=[(p, x, y) for p, x, y, _b in plan], what='container fill')


@T.test
def container_fill_refuses_without_a_run_of_empty_pages():
    E = T.engine()
    path = _stash()
    items = E.save.parse_stash(path, E.data)
    n = E.save.STASH_PAGES
    # every page in use (all containers fit on one empty page, so no empty page at all is the refusal case)
    blob, _ = E.cr.build(E.cr.new_spec('normal', 'gc01'))
    used = {it['page'] for it in items}
    ins = [(p, 0, 0, bytes(blob)) for p in range(n) if p not in used]
    if ins:
        E.save.edit_stash(path, E.data, insert=ins, backup=False)
    items = E.save.parse_stash(path, E.data)
    T.eq(sorted({it['page'] for it in items}), list(range(n)), 'test setup: every page in use')
    T.eq(E.C.plan_container_fill(E.cr, items, n), None, 'plan without an empty page')
    # a run of empty pages too short: only the last page of the stash is left, with no room for all
    T.eq(E.C.plan_container_fill(E.cr, [dict(it) for it in items if it['page'] != n - 1], 1), None,
         'plan limited to 1 page that is in use')


T.main(globals())
