"""Stash tab, right-click → Quantity → Remove...: it never raises the quantity. An item without a quantity (every
non-stackable item that is not a cluster / container shows "Quantity (now 0)") offered Remove..., and the result
was quantity 1 (docs/review/gui.md finding 18). Now Remove... is greyed out at quantity 0 and 1, removing more
than there is stops at 1, and the dialog offers 1 to (quantity - 1)."""
import capytest as T

MODE = 'gui'
RESET = True
G = T.G


def first(pred, what):
    import mxl_save
    app = G.app
    raw = T.read(app.path)
    for it in sorted(app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        rec = T.rec_of(mxl_save.item_blob(raw, it))
        if pred(it, rec, app.data.base(it['code'])):
            return (it['page'], it['x'], it['y'])
    T.skip(f'the sample stash has no {what}')


def entry(menu, label, under='Quantity'):
    inside, base = False, None
    for d, lab, st, mm, i in T.menu_entries(menu):
        if mm.type(i) == 'cascade' and lab.startswith(under):
            inside, base = True, d
            continue
        if inside and d <= base:
            inside = False
        if inside and lab.startswith(label):
            return lab, st
    return None, None


@T.test
def rule():
    import mxl_rc_menu as R
    T.eq(R._quantity_after(0, -1, 5, 1000), 0, 'remove 5 from 0')
    T.eq(R._quantity_after(10, -1, 3, 1000), 7, 'remove 3 from 10')
    T.eq(R._quantity_after(10, -1, 50, 1000), 1, 'remove 50 from 10')
    T.eq(R._quantity_after(995, 1, 50, 1000), 1000, 'add 50 to 995')
    T.eq(R._quantity_after(0, 1, 5, 1000), 5, 'add 5 to 0')
    T.eq(R._most(10, -1, 1000), 9, 'most that can be removed from 10')


@T.test
def no_remove_without_a_quantity():
    import mxl_creator as C
    key = first(lambda it, rec, b: b.stack_max is None and not rec['flags'] & C.FLAG_SIMPLE
                and not any(s['id'] == C.CLUSTER_QUANTITY_STAT for s in rec['stats']), 'item without a quantity')
    snap = T.stash_snap(G.app.path, G.app.data)
    m = T.stash_menu(*key)
    T.check(any(lab == 'Quantity (now 0)' for lab in T.menu_labels(m)), f'no "Quantity (now 0)" in {T.menu_labels(m)}')
    lab, st = entry(m, 'Remove')
    T.eq(st, 'disabled', f'state of {lab!r} at quantity 0')
    lab, st = entry(m, 'Add')
    T.eq(st, 'normal', f'state of {lab!r} at quantity 0')
    T.eq(T.stash_snap(G.app.path, G.app.data), snap, 'the stash changed')


@T.test
def remove_more_than_there_is_stops_at_one():
    import mxl_creator as C
    key = first(lambda it, rec, b: b.stack_max is None and C.CLUSTER_CONTAINER_RE.match(it['code'].strip())
                and any(s['id'] == C.CLUSTER_QUANTITY_STAT and s['value'] > 1 for s in rec['stats']),
                'cluster / container with a quantity above 1')

    def qty():
        snap = T.stash_snap(G.app.path, G.app.data)
        return next(s['value'] for s in T.rec_of(snap[key][1])['stats'] if s['id'] == C.CLUSTER_QUANTITY_STAT)
    start = qty()
    G.answers['int'] = 1
    T.invoke(T.stash_menu(*key), 'Remove...', under='Quantity')
    T.eq(qty(), start - 1, 'quantity after removing 1')
    G.answers['int'] = start + 50
    T.invoke(T.stash_menu(*key), 'Remove...', under='Quantity')
    T.eq(qty(), 1, f'quantity after removing {start + 50}')
    lab, st = entry(T.stash_menu(*key), 'Remove')
    T.eq(st, 'disabled', f'state of {lab!r} at quantity 1')


T.main(globals())
