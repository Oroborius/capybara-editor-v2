"""Item Editor, "Toggles / upgrades": every in-place recipe of the item is reachable through two dropdowns (what
the recipe takes, then the recipe); only the picked one is written out (engine side: test 76)."""
import os

import capytest as T

MODE = 'gui'
G = T.G


@T.test
def toggles_in_two_dropdowns():
    import mxl_creator_gui as CG
    import mxl_tabs
    import mxl_creator
    cr = mxl_creator.Creator(G.app.data)
    best = None
    for it in G.app.items:
        try:
            n = len(cr.inplace_for(it['code'], it.get('quality'), None))
        except Exception:
            continue
        if n > CG.CreatorWindow.TOGGLES_FILTER_AT and (best is None or n > best[0]):
            best = (n, it)
    if best is None:
        T.skip('no stash item with a long in-place recipe list')
    G.app.selected = best[1]
    CG.edit_selected(G.app)
    T.pump(12)
    w = mxl_tabs.built_owner('Creator')
    T.check(w is not None and w.edit_item is not None, 'the Item Editor did not open')
    groups = getattr(w, '_tog_groups', None)
    T.check(groups, 'recipe dropdowns built')
    want = cr.inplace_for(w.spec.get('code'), w.spec.get('quality'), w.spec.get('row'))
    T.eq(sum(len(v) for v in groups.values()), len(want), 'every recipe reachable through the dropdowns')
    on_group, on_rec = w._tog_sync
    for g, items in groups.items():                 # each group lists only its own recipes
        w._tog_gvar.set(f'{g}  ({len(items)})')
        on_group()
        T.check(w._tog_cur['rec'] is items[0][1], f'{g}: its first recipe picked')
        w._tog_rvar.set(items[-1][0])
        on_rec()
        T.check(w._tog_cur['rec'] is items[-1][1], f'{g}: picking a recipe selects it')
    T.check(all(x[0][0] in '\u2713~\u2717' and f"(#{x[1]['row']})" in x[0] for v in groups.values() for x in v),
            'each entry: applies mark, changes, row number')
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        try:
            w.scroll.canvas.yview_moveto(0.62)
        except Exception:
            pass
        T.pump(6)
        os.system(f'import -window root {os.path.join(shot, "v78.png")} 2>/dev/null')


T.main(globals())
