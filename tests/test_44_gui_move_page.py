"""Right-click "Move to page... > Page N" on a stash item whose cell is taken on the target page: the item goes to the
first free place of that page (it failed before with the raw message "(x, y): overlaps <item> at (x, y)" and an
ERROR line in capybara.log); a free cell keeps its position; the item's own page is greyed out."""
import capytest as T

MODE = 'gui'
RESET = True
G = T.G


def probe(it):
    import mxl_save
    return mxl_save.blob_item(mxl_save.item_blob(T.read(G.app.path), it), G.app.data)


def blocked_on(page):
    """A stash item of another page whose own cell is taken on `page`, but which fits somewhere on `page`."""
    import mxl_save
    items = mxl_save.parse_stash(G.app.path, G.app.data)
    for it in sorted(G.app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        if it['page'] == page:
            continue
        p = probe(it)
        if mxl_save.placement_error(items, p, page, it['x'], it['y'], G.app.data) is not None and \
                mxl_save.free_spot(items, p, G.app.data, [page]) is not None:
            return it
    T.skip(f'no item of another page is blocked on page {page + 1}')


@T.test
def move_to_a_page_where_the_cell_is_taken():
    import mxl_save
    app = G.app
    it = blocked_on(0)
    key = (it['page'], it['x'], it['y'])
    items = mxl_save.parse_stash(app.path, app.data)
    want = mxl_save.free_spot(items, probe(it), app.data, [0])
    before = T.stash_snap(app.path, app.data)
    m = T.stash_menu(*key)
    T.invoke(m, 'Page 1', under='Move to page')
    T.settle(0.2)
    after = T.stash_snap(app.path, app.data)
    T.check(key not in after, f'the item is still at {key}; status {T.status_text()!r}')
    T.check(tuple(want) in after, f'nothing at the first free place {tuple(want)}; status {T.status_text()!r}')
    if key not in after and tuple(want) in after:
        T.check(T.same_item(before[key][1], after[tuple(want)][1]), 'the moved item differs from the original (other than its place)')
        T.only_changed(before, after, gone=[key], new=[tuple(want)], what='move to page 1')
    T.check('moved to page 1' in T.status_text(), f'status {T.status_text()!r}')


@T.test
def move_to_a_free_cell_keeps_the_position():
    import mxl_save
    app = G.app
    items = mxl_save.parse_stash(app.path, app.data)
    for it in sorted(app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        target = next((p for p in range(mxl_save.STASH_PAGES) if p != it['page'] and
                       mxl_save.placement_error(items, probe(it), p, it['x'], it['y'], app.data) is None), None)
        if target is not None:
            break
    else:
        T.skip('no item fits at its own cell on another page')
    key = (it['page'], it['x'], it['y'])
    before = T.stash_snap(app.path, app.data)
    T.invoke(T.stash_menu(*key), f'Page {target + 1}', under='Move to page')
    T.settle(0.2)
    after = T.stash_snap(app.path, app.data)
    T.only_changed(before, after, gone=[key], new=[(target, it['x'], it['y'])], what=f'move to page {target + 1}')


@T.test
def own_page_is_greyed_out():
    it = next(i for i in G.app.items if i['page'] == 0)
    m = T.stash_menu(0, it['x'], it['y'])
    states = {}
    inside = False
    for d, lab, st, _m, _i in T.menu_entries(m):
        if d == 0:
            inside = lab.startswith('Move to page')
        elif inside:
            states[lab] = st
    T.eq(states.get('Page 1'), 'disabled', 'state of "Page 1" for an item on page 1')
    T.eq(states.get('Page 2'), 'normal', 'state of "Page 2"')


T.main(globals())
