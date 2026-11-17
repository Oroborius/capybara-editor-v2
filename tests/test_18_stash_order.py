"""mxl_stash_order: the stash writer keeps an item's place in the file. A replaced item stays at its index in its
page's item list, and an insert may name its index - (page, x, y, blob, index) - which is what Undo uses: remove +
insert-at-index gives the very same file."""
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')


def setup():
    E = T.engine()
    import mxl_stash_order
    mxl_stash_order.install()
    return E, mxl_stash_order, E.save.edit_stash


def stashes(folder):
    return sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(('.stash', '.shared')))


@T.test
def remove_then_insert_at_the_index_gives_the_same_file():
    """Every item of every sample stash: removed, then inserted at its old index."""
    E, SO, edit = setup()
    n = 0
    for path in stashes(T.fresh_saves()):
        raw = T.read(path)
        for it in E.save.parse_stash(path, E.data):
            page, index = SO.page_index(path, E.data, it['_offset'])
            T.eq(page, it['page'], 'page_index: page')
            blob = bytes(E.save.item_blob(raw, it))
            edit(path, E.data, remove=[it['_offset']], backup=False)
            T.check(T.read(path) != raw, 'the removal changed nothing')
            edit(path, E.data, insert=[(it['page'], it['x'], it['y'], blob, index)], backup=False)
            n += 1
            if T.read(path) != raw:
                T.check(False, f'{os.path.basename(path)}: item {it["code"]!r} page {page + 1} index {index}: file differs after remove + insert')
                break
    T.check(n > 0, 'no stash item in the samples')


@T.test
def several_removed_then_inserted_in_one_write():
    """Two neighbours and the last item of a page (and the only item of another page, when there is one) removed in
    one write, put back with their indices in one write, given in any order."""
    E, SO, edit = setup()
    path = T.fresh_saves() + '/XBone.stash'
    raw = T.read(path)
    items = E.save.parse_stash(path, E.data)
    by_page = {}
    for it in items:
        by_page.setdefault(it['page'], []).append(it)
    page = max(by_page, key=lambda p: len(by_page[p]))
    if len(by_page[page]) < 4:
        T.skip('no stash page with 4 items')
    lst = by_page[page]
    picked = [(lst[1], 1), (lst[2], 2), (lst[-1], len(lst) - 1)]
    lone = next((p for p in by_page if len(by_page[p]) == 1 and p != page), None)
    if lone is not None:
        picked.append((by_page[lone][0], 0))
    ins = [(it['page'], it['x'], it['y'], bytes(E.save.item_blob(raw, it)), i) for it, i in picked]
    edit(path, E.data, remove=[it['_offset'] for it, _i in picked], backup=False)
    T.eq(len(E.save.parse_stash(path, E.data)), len(items) - len(picked), 'items after the removal')
    edit(path, E.data, insert=list(reversed(ins)), backup=False)
    T.check(T.read(path) == raw, 'file differs after removing and re-inserting several items')


@T.test
def index_rules():
    """No index / None / an index past the end append (the host's behaviour); an occupied cell is refused and
    nothing is written; a plain 4-tuple insert is still the host's own write."""
    E, SO, edit = setup()
    path = T.fresh_saves() + '/XBone.stash'
    raw = T.read(path)
    items = E.save.parse_stash(path, E.data)
    it = next(i for i in items if len([j for j in items if j['page'] == i['page']]) >= 2
              and SO.page_index(path, E.data, i['_offset'])[1] == 0)
    n_page = len([j for j in items if j['page'] == it['page']])
    blob = bytes(E.save.item_blob(raw, it))
    spot = (it['page'], it['x'], it['y'])
    edit(path, E.data, remove=[it['_offset']], backup=False)
    gone = T.read(path)
    results = []
    for tail in ((), (None,), (999,)):
        edit(path, E.data, insert=[spot + (blob,) + tail], backup=False)
        back = next(i for i in E.save.parse_stash(path, E.data) if (i['page'], i['x'], i['y']) == spot)
        T.eq(SO.page_index(path, E.data, back['_offset']), (it['page'], n_page - 1), f'index of an insert with index {tail}')
        results.append(T.read(path))
        try:
            edit(path, E.data, insert=[spot + (blob, 0)], backup=False)
            T.check(False, 'an insert on an occupied cell was written')
        except E.save.EditError:
            pass
        T.check(T.read(path) == results[-1], 'a refused insert changed the file')
        back = next(i for i in E.save.parse_stash(path, E.data) if (i['page'], i['x'], i['y']) == spot)
        edit(path, E.data, remove=[back['_offset']], backup=False)
        T.check(T.read(path) == gone, 'file after removing the appended item again')
    T.check(results[0] == results[1] == results[2], 'appending: with and without an index the files differ')
    T.check(results[0] != raw and len(results[0]) == len(raw), 'an appended item gave the original order (test item not suitable)')
    try:
        edit(path, E.data, insert=[spot + (blob, -1)], backup=False)
        T.check(False, 'a negative index was accepted')
    except E.save.EditError:
        pass
    T.check(T.read(path) == gone, 'a refused insert changed the file')
    edit(path, E.data, insert=[spot + (blob, 0)], backup=False)
    T.check(T.read(path) == raw, 'file after inserting at index 0')


@T.test
def last_removed_tells_the_index_of_a_replaced_item():
    E, SO, edit = setup()
    path = T.fresh_saves() + '/XBone.stash'
    raw = T.read(path)
    items = E.save.parse_stash(path, E.data)
    it = items[len(items) // 2]
    page, index = SO.page_index(path, E.data, it['_offset'])
    blob = bytes(E.save.item_blob(raw, it))
    edit(path, E.data, remove=[it['_offset']], insert=[(it['page'], it['x'], it['y'], blob)], backup=False)
    T.check(T.read(path) == raw, 'replacing an item by itself changed the file')
    T.eq((SO.last_removed.get('path'), SO.last_removed.get('page'), SO.last_removed.get('index'), SO.last_removed.get('blob')),
         (os.path.abspath(path), page, index, blob), 'last_removed after a replace')
    spot = E.save.free_spot(items, E.save.blob_item(blob, E.data), E.data, list(range(E.save.STASH_PAGES)))
    if spot is not None:
        edit(path, E.data, insert=[(spot[0], spot[1], spot[2], blob)], backup=False)
        T.eq(dict(SO.last_removed), {}, 'last_removed after a write that removed nothing')


T.main(globals())
