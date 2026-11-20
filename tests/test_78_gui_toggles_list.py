"""Item Editor, "Toggles / upgrades": every in-place recipe of the item is listed (no 40-row cap); a long list
gets a filter box that narrows it; item-type inputs are named and mod chances shown (engine side: test 76)."""
import os

import capytest as T

MODE = 'gui'
G = T.G


@T.test
def toggles_list_has_filter_and_no_cap():
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
    lst = getattr(w, '_tog_list', None)
    T.check(lst is not None, 'toggles list built')
    n_all = len(lst.winfo_children())
    want = len(cr.inplace_for(w.spec.get('code'), w.spec.get('quality'), w.spec.get('row')))
    T.eq(n_all, want, 'every recipe listed')
    flt = getattr(w, '_tog_filter', None)
    T.check(flt is not None, 'filter box above a long list')
    flt.set('zzzz-no-such-recipe')
    T.pump(4)
    T.eq(len(lst.winfo_children()), 1, 'filter with no match: one "no recipe matches" line')
    flt.set('')
    T.pump(4)
    T.eq(len(lst.winfo_children()), n_all, 'filter cleared: all again')
    flt.set(f"recipe {cr.inplace_for(w.spec.get('code'), w.spec.get('quality'), w.spec.get('row'))[0]['row']}")
    T.pump(4)
    T.check(1 <= len(lst.winfo_children()) < n_all, 'filter by recipe number narrows the list')
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        os.system(f'import -window root {os.path.join(shot, "v78.png")} 2>/dev/null')


T.main(globals())
