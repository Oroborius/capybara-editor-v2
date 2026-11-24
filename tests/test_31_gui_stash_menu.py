"""Right-click actions on stash items (mxl_rc_menu, mxl_undo, mxl_perfect), driven through the real menu: the menu
is built by the application's handler, captured instead of shown, and its entries are invoked. Every test starts
from the pristine sample files (RESET) and checks the stash re-read from disk: the touched item changed as asked,
every other item byte-identical, the character file untouched."""
import capytest as T

MODE = 'gui'
RESET = True
G = T.G


class Ctx:
    """The stash file before an action."""

    def __init__(self):
        self.app = G.app
        self.path = G.app.path
        self.snap = T.stash_snap(self.path, G.app.data)
        self.raw = T.read(self.path)
        self.char = T.read(G.app.character_file())

    def after(self, gone=(), new=(), chg=(), what=''):
        T.pump()
        now = T.stash_snap(self.path, G.app.data)
        T.only_changed(self.snap, now, gone, new, chg, what)
        T.check(T.read(G.app.character_file()) == self.char, f'{what}: the character file changed')
        memory = {(i['page'], i['x'], i['y']) for i in G.app.items}
        T.eq(sorted(memory), sorted(now), f'{what}: items the window shows vs items on disk')
        return now


def first(pred, what):
    """(page, x, y) of the first stash item whose decoded record satisfies pred(item, record, base)."""
    import mxl_save
    app = G.app
    raw = T.read(app.path)
    for it in sorted(app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        rec = T.rec_of(mxl_save.item_blob(raw, it))
        if pred(it, rec, app.data.base(it['code'])):
            return (it['page'], it['x'], it['y'])
    T.skip(f'the sample stash has no {what}')


def free_cell(page, like):
    """An empty cell of `page` where the item at key `like` fits."""
    import mxl_save
    app = G.app
    it = next(i for i in app.items if (i['page'], i['x'], i['y']) == like)
    probe = mxl_save.blob_item(mxl_save.item_blob(T.read(app.path), it), app.data)
    spot = mxl_save.free_spot(list(app.items), probe, app.data, [page])
    if spot is None:
        T.skip(f'no free place on stash page {page + 1}')
    return tuple(spot)


def any_item(it, rec, base):
    import mxl_creator
    return not rec['flags'] & mxl_creator.FLAG_SIMPLE and rec.get('stats')


@T.test
def menu_lists_the_actions():
    key = first(any_item, 'item with stats')
    c = Ctx()
    labels = T.menu_labels(T.stash_menu(*key))
    for want in ('Edit item...', 'Item stats...', 'Duplicate', 'Copy', 'Cut', 'Move to page...', 'Page 10', 'Quantity (now',
                 'Change item quality', 'Specific editing functions', 'Delete item', 'Export item...'):
        T.check(any(lab.startswith(want) for lab in labels), f'menu entry {want!r} missing: {labels}')
    T.check(not any(lab.startswith('Paste') for lab in labels), 'Paste offered with nothing copied')
    T.eq(G.app.selected and (G.app.selected['page'], G.app.selected['x'], G.app.selected['y']), key, 'the right-clicked item is selected')
    empty = free_cell(key[0], key)
    T.eq(T.menu_labels(T.stash_menu(*empty)), ['Import item...', 'Item Creator...'], 'menu of an empty cell')
    c.after(what='opening menus')
    T.check(T.read(c.path) == c.raw, 'opening menus changed the stash file')


@T.test
def duplicate():
    import os
    key = first(lambda it, rec, b: it['page'] == 1 and any_item(it, rec, b), 'item on page 2')
    G.app.backups_done.add(os.path.abspath(G.app.path))      # not the first write (that case is the next test)
    c = Ctx()
    T.invoke(T.stash_menu(*key), 'Duplicate')
    g, new, chg = T.diff(c.snap, T.stash_snap(c.path, G.app.data))
    T.eq((g, chg, len(new)), ([], [], 1), 'duplicate: (removed, changed, number added)')
    now = c.after(new=new, what='duplicate')
    T.check(T.same_item(now[new[0]][1], c.snap[key][1]), 'the copy is not the same item as the original')
    T.eq(new[0][0], key[0], 'page of the copy (same page as the original)')
    T.eq(G.app.page(), key[0], 'stash page shown after Duplicate')
    T.eq(G.app.selected and (G.app.selected['page'], G.app.selected['x'], G.app.selected['y']), new[0], 'the copy is selected')
    T.check('duplicated' in T.status_text(), f'status: {T.status_text()!r}')


# BUG: mxl_rc_menu._duplicate builds its status text with app.bak_name(bak), a method that does not exist. It is
# only evaluated when the write made a backup, i.e. when Duplicate is the first stash write of the session: the
# copy is written, then AttributeError ('App' object has no attribute 'bak_name') - no status, no selection.
@T.test
def duplicate_as_first_write_of_the_session():
    key = first(lambda it, rec, b: it['page'] == 1 and any_item(it, rec, b), 'item on page 2')
    c = Ctx()
    T.invoke(T.stash_menu(*key), 'Duplicate')
    g, new, chg = T.diff(c.snap, T.stash_snap(c.path, G.app.data))
    T.eq((g, chg, len(new)), ([], [], 1), 'duplicate: (removed, changed, number added)')
    T.check('duplicated' in T.status_text() and 'backup' in T.status_text(), f'status: {T.status_text()!r}')
    for e in T.errors_since((0, 0, 0)):
        if 'bak_name' in e:
            T.check(False, e[-160:])


@T.test
def copy_then_paste_keeps_the_page():
    """Copy on page 1, paste into an empty cell of page 2: the item lands there and page 2 stays shown."""
    key = first(lambda it, rec, b: it['page'] == 0 and any_item(it, rec, b), 'item on page 1')
    c = Ctx()
    T.invoke(T.stash_menu(*key), 'Copy')
    T.check(G.app._capy_clip is not None, 'nothing in the clipboard after Copy')
    c.after(what='copy')
    T.check(T.read(c.path) == c.raw, 'Copy wrote the stash file')
    cell = free_cell(1, key)
    m = T.stash_menu(*cell)
    T.eq(G.app.page(), 1, 'page shown before the paste')
    T.invoke(m, 'Paste here')
    now = c.after(new=[cell], what='paste')
    T.check(T.same_item(now[cell][1], c.snap[key][1]), 'the pasted item is not the copied one')
    T.eq(G.app.page(), 1, 'stash page shown after Paste (must stay on the page pasted into)')
    T.eq(G.app._capy_clip, None, 'clipboard after the paste')


@T.test
def copy_then_paste_replaces():
    src = first(lambda it, rec, b: any_item(it, rec, b) and b.size == (1, 1), '1x1 item with stats')
    import mxl_save
    app = G.app
    raw = T.read(app.path)
    src_blob = bytes(mxl_save.item_blob(raw, next(i for i in app.items if (i['page'], i['x'], i['y']) == src)))
    dst = first(lambda it, rec, b: (it['page'], it['x'], it['y']) != src and b.size == (1, 1) and any_item(it, rec, b)
                and not T.same_item(mxl_save.item_blob(raw, it), src_blob), 'second, different 1x1 item')
    c = Ctx()
    T.invoke(T.stash_menu(*src), 'Copy')
    m = T.stash_menu(*dst)
    T.invoke(m, 'Paste (replaces it')
    now = c.after(chg=[dst], what='paste over an item')
    T.check(T.same_item(now[dst][1], c.snap[src][1]), 'the item at the target is not the copied one')


@T.test
def cut_then_paste():
    key = first(lambda it, rec, b: it['page'] == 0 and any_item(it, rec, b), 'item on page 1')
    c = Ctx()
    T.invoke(T.stash_menu(*key), 'Cut')
    c.after(gone=[key], what='cut')
    T.check(G.app._capy_clip is not None, 'nothing in the clipboard after Cut')
    T.invoke(T.stash_menu(*key), 'Paste here')
    now = c.after(what='cut + paste at the same place')
    T.eq(now[key][1], c.snap[key][1], 'bytes of the item after cut + paste at its own place')


@T.test
def delete_then_undo():
    import mxl_undo
    key = first(any_item, 'item with stats')
    c = Ctx()
    T.invoke(T.stash_menu(*key), 'Delete item')
    c.after(gone=[key], what='delete')
    T.check(mxl_undo.can_undo(G.app), 'nothing to undo after Delete')
    T.check('deleted' in T.status_text(), f'status after Delete: {T.status_text()!r}')
    mxl_undo._do_undo(G.app)
    now = c.after(what='delete + undo')
    T.eq(now[key][1], c.snap[key][1], 'bytes of the item after delete + undo')
    T.check(not mxl_undo.can_undo(G.app), 'undo stack not empty after the undo')
    mxl_undo._do_undo(G.app)
    T.check('Nothing to undo' in T.status_text(), f'status of an empty undo: {T.status_text()!r}')
    c.after(what='a second undo')


# Was a BUG (same cause as WORKLOG W15 "add-then-delete ... leaves the stash 336 bytes different though parsing
# equal"): the stash writer appends an inserted item at the end of its page, so delete + undo changed the item order
# inside the file. The undo now remembers the item's index in its page's list and inserts it there.
@T.test
def delete_then_undo_restores_the_file_bytes():
    """Delete + Undo gives the very same stash file."""
    import mxl_undo
    key = first(any_item, 'item with stats')
    c = Ctx()
    T.invoke(T.stash_menu(*key), 'Delete item')
    mxl_undo._do_undo(G.app)
    T.pump()
    now = T.read(c.path)
    T.eq(len(now), len(c.raw), 'stash file size after delete + undo')
    T.eq(sorted(T.stash_snap(c.path, G.app.data).items()), sorted(c.snap.items()), 'items after delete + undo')
    T.check(now == c.raw, f'file differs from the original in {sum(1 for a, b in zip(now, c.raw) if a != b)} of {len(now)} bytes')
    verified(c.path, 'delete + undo')


def same_file(c, what):
    T.pump()
    now = T.read(c.path)
    T.check(now == c.raw, f'{what}: file differs from the original in {sum(1 for a, b in zip(now, c.raw) if a != b)} '
                          f'of {len(now)} bytes (was {len(c.raw)})')
    c.after(what=what)


def page_lists():
    """{page: [(page, x, y) in file order]} of the stash on disk."""
    import mxl_save
    out = {}
    for it in mxl_save.parse_stash(G.app.path, G.app.data):
        out.setdefault(it['page'], []).append((it['page'], it['x'], it['y']))
    return out


@T.test
def delete_each_position_then_undo():
    """First, middle and last item of a page, and an item of every other page: delete + undo each."""
    import mxl_undo
    c = Ctx()
    lists = page_lists()
    big = max(lists.values(), key=len)
    keys = {big[0], big[len(big) // 2], big[-1]} | {lst[len(lst) // 2] for lst in lists.values()}
    for key in sorted(keys):
        T.invoke(T.stash_menu(*key), 'Delete item')
        T.check(key not in T.stash_snap(c.path, G.app.data), f'{key} not deleted')
        mxl_undo._do_undo(G.app)
        same_file(c, f'delete + undo of {key}')
    T.check(not mxl_undo.can_undo(G.app), 'undo stack not empty at the end')


@T.test
def delete_two_then_undo_twice():
    """Delete A, delete B, undo, undo -> the original file; in both orders, neighbours in the file included."""
    import mxl_undo
    c = Ctx()
    lst = max(page_lists().values(), key=len)
    if len(lst) < 4:
        T.skip('no stash page with 4 items')
    other = next((v[0] for v in page_lists().values() if v[0][0] != lst[0][0]), None)
    pairs = [(lst[1], lst[2]), (lst[2], lst[1]), (lst[0], lst[-1]), (lst[-1], lst[-2])]
    if other is not None:
        pairs.append((lst[1], other))
    for a, b in pairs:
        T.invoke(T.stash_menu(*a), 'Delete item')
        T.invoke(T.stash_menu(*b), 'Delete item')
        c.after(gone=[a, b], what=f'delete {a} and {b}')
        mxl_undo._do_undo(G.app)
        now = c.after(gone=[a], what=f'first undo ({b} back)')
        T.eq(now[b][1], c.snap[b][1], f'bytes of {b}')
        mxl_undo._do_undo(G.app)
        same_file(c, f'delete {a}, delete {b}, undo, undo')
    # three deletes, an unrelated write in between, three undos
    a, b, d = lst[1], lst[3], lst[2]
    for k in (a, b, d):
        T.invoke(T.stash_menu(*k), 'Delete item')
    for _ in range(3):
        mxl_undo._do_undo(G.app)
    same_file(c, 'three deletes, three undos')


@T.test
def undo_of_a_delete_when_the_place_is_taken():
    """The cell was filled meanwhile: the undo still brings the item back (somewhere free), nothing is lost."""
    import mxl_save
    import mxl_undo
    c = Ctx()
    key = first(lambda it, rec, b: any_item(it, rec, b) and b.size == (1, 1), '1x1 item with stats')
    T.invoke(T.stash_menu(*key), 'Delete item')
    mxl_save.edit_stash(c.path, G.app.data, insert=[key + (c.snap[key][1],)], backup=False)
    G.app.load(c.path, keep_selection=False)
    T.pump()
    mxl_undo._do_undo(G.app)
    T.pump()
    now = T.stash_snap(c.path, G.app.data)
    g, new, chg = T.diff(c.snap, now)
    T.eq((g, chg, len(new)), ([], [], 1), 'undo with the place taken: (removed, changed, number added)')
    T.check(new and T.same_item(now[new[0]][1], c.snap[key][1]), 'the item brought back is not the deleted one')
    verified(c.path, 'undo with the place taken')


def creator_window():
    import mxl_creator_gui as CG
    import mxl_tabs
    CG.CreatorWindow(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    if w is None or w.edit_item is not None:
        raise T.Failed('no Creator window')
    T.select_tab('Stash')
    return w


def commit(w):
    w.commit()
    T.pump(8)
    for kind, title, msg in G.boxes:
        if kind == 'showerror':
            raise T.Failed(f'error box {title!r}: {msg[:200]}')


@T.test
def create_copies_then_undo_restores_the_file_bytes():
    """The creator writes 3 copies; one undo removes them: the original file."""
    import mxl_creator_gui as CG
    import mxl_undo
    w = creator_window()
    w.search.set('')
    w.quality.set(dict((k, lab) for lab, k in CG.qualities())['normal'])
    w.on_quality()
    T.pump()
    i = next(i for i, (lab, code) in enumerate(w.entries) if G.app.data.base(code).size == (1, 1) and G.app.data.base(code).kind == 'misc')
    w.listbox.selection_clear(0, 'end')
    w.listbox.selection_set(i)
    w.on_pick()
    T.pump(8)
    c = Ctx()
    w.copies.set(3)
    commit(w)
    g, new, chg = T.diff(c.snap, T.stash_snap(c.path, G.app.data))
    T.eq((g, chg, len(new)), ([], [], 3), 'three copies: (removed, changed, number added)')
    mxl_undo._do_undo(G.app)
    same_file(c, 'create 3 copies + undo')
    key = first(any_item, 'item with stats')                  # delete, create, undo, undo
    T.invoke(T.stash_menu(*key), 'Delete item')
    commit(w)
    mxl_undo._do_undo(G.app)
    mxl_undo._do_undo(G.app)
    same_file(c, 'delete, create, undo, undo')


@T.test
def replace_then_undo_restores_the_file_bytes():
    """Item Editor: a roll changed, Replace, Undo -> the original file (the item is not the last of its page)."""
    import mxl_creator_gui as CG
    import mxl_rc_menu
    import mxl_tabs
    import mxl_undo
    cr = mxl_rc_menu._creator(G.app)
    lists = page_lists()
    found = None
    for it in G.app.items:
        key = (it['page'], it['x'], it['y'])
        if key == lists[it['page']][-1]:
            continue
        try:
            spec = cr.spec_from_item(it)
            m = next((m for m in cr.mods(spec) if m.variable and m.min != m.max and spec['rolls'].get(m.source) is not None), None)
        except Exception:
            continue
        if m is not None and not spec.get('_warning'):
            found = (key, it, m, spec['rolls'][m.source])
            break
    if found is None:
        T.skip('the sample stash has no item with a variable roll the creator knows')
    key, it, m, cur = found
    c = Ctx()
    G.app.selected = it
    CG.edit_selected(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    T.check(w is not None and w.edit_item is not None, 'the Item Editor did not open')
    w.set_roll(m.source, m.min if cur != m.min else m.max)
    T.pump(4)
    commit(w)
    now = c.after(chg=[key], what='replace with a changed roll')
    T.check(mxl_undo.can_undo(G.app), 'nothing to undo after Replace')
    T.eq(page_lists(), lists, 'order of the items in the file after Replace')
    mxl_undo._do_undo(G.app)
    T.check('restored' in T.status_text(), f'status of the undo: {T.status_text()!r}')
    same_file(c, 'replace + undo')


@T.test
def replace_onto_another_page_then_undo_restores_the_file_bytes():
    """A replace whose new item went to another page (what the Item Editor does when the edited item no longer
    fits its place), recorded as the editor records it: the undo puts the old bytes back at the old index."""
    import mxl_save
    import mxl_undo
    c = Ctx()
    lists = page_lists()
    key = max(lists.values(), key=len)[1]
    it = next(i for i in G.app.items if (i['page'], i['x'], i['y']) == key)
    old = c.snap[key][1]
    probe = mxl_save.blob_item(old, G.app.data)
    spot = mxl_save.free_spot(list(G.app.items), probe, G.app.data, [p for p in range(mxl_save.STASH_PAGES) if p != key[0]])
    if spot is None:
        T.skip('no free place on another stash page')
    mxl_save.edit_stash(c.path, G.app.data, remove=[it['_offset']], insert=[(spot[0], spot[1], spot[2], old)], backup=False)
    mxl_undo.record(G.app, 'replace', blob=old, page=spot[0], x=spot[1], y=spot[2],
                    old_page=key[0], old_x=key[1], old_y=key[2], name='test item')
    G.app.load(c.path, keep_selection=False)
    c.after(gone=[key], new=[tuple(spot)], what='replace onto another page')
    mxl_undo._do_undo(G.app)
    same_file(c, 'replace onto another page + undo')


@T.test
def delete_key_and_ctrl_z_at_the_pointer():
    """The real key bindings: Delete removes the item under the mouse pointer, Ctrl+Z puts it back."""
    key = first(lambda it, rec, b: it['page'] == 0 and any_item(it, rec, b), 'item on page 1')
    c = Ctx()
    e = T.stash_ev(*key)
    root = G.root
    root.event_generate('<Motion>', warp=True, x=e.x_root - root.winfo_rootx(), y=e.y_root - root.winfo_rooty())
    T.pump(8)
    cv = G.app.canvas
    if (cv.winfo_pointerx() - cv.winfo_rootx()) // G.app.cell != key[1] or (cv.winfo_pointery() - cv.winfo_rooty()) // G.app.cell != key[2]:
        T.skip('the X server did not move the pointer (no pointer warp on this display)')
    root.focus_force()
    T.pump(4)
    root.event_generate('<Delete>', when='now')
    c.after(gone=[key], what='Delete key')
    root.event_generate('<Control-z>', when='now')
    now = c.after(what='Ctrl+Z')
    T.eq(now[key][1], c.snap[key][1], 'bytes of the item after Delete + Ctrl+Z')


@T.test
def move_to_page():
    key = first(lambda it, rec, b: it['page'] == 0 and any_item(it, rec, b), 'item on page 1')
    c = Ctx()
    T.invoke(T.stash_menu(*key), 'Page 4', under='Move to page')
    dst = (3, key[1], key[2])
    now = c.after(gone=[key], new=[dst], what='move to page 4')
    T.eq(now[dst][1], c.snap[key][1], 'bytes of the moved item')
    T.eq(G.app.page(), 0, 'page shown after the move (the page being looked at stays)')
    T.invoke(T.stash_menu(*dst), 'Page 1', under='Move to page')
    now = c.after(what='moved back to page 1')
    T.eq(sorted(now.items()), sorted(c.snap.items()), 'items after moving there and back')


@T.test
def quantity_of_a_cluster():
    """Clusters / containers keep their quantity in stat 501: Min writes 1, Max writes 1000."""
    import mxl_creator as C
    key = first(lambda it, rec, b: b.stack_max is None and C.CLUSTER_CONTAINER_RE.match(it['code'].strip())
                and any(s['id'] == C.CLUSTER_QUANTITY_STAT for s in rec['stats']), 'cluster / container')
    c = Ctx()

    def qty(snap):
        return next((s['value'] for s in T.rec_of(snap[key][1])['stats'] if s['id'] == C.CLUSTER_QUANTITY_STAT), None)
    start = qty(c.snap)
    T.check(any(lab == f'Quantity (now {start})' for lab in T.menu_labels(T.stash_menu(*key))), f'menu does not show the quantity {start}')
    first_to, then_to = ('Min', 'Max') if start != 1 else ('Max', 'Min')
    T.invoke(T.stash_menu(*key), first_to, under='Quantity')
    now = c.after(chg=[key], what=f'quantity {first_to}')
    T.eq(qty(now), 1 if first_to == 'Min' else C.CLUSTER_QUANTITY_MAX, f'quantity after {first_to}')
    a, b = T.record(c.snap[key][1]), T.record(now[key][1])
    T.eq({k: v for k, v in b[0].items() if k != 'stats'}, {k: v for k, v in a[0].items() if k != 'stats'}, 'other fields of the item')
    T.eq([s for s in b[0]['stats'] if s['id'] != 501], [s for s in a[0]['stats'] if s['id'] != 501], 'other stats of the item')
    T.invoke(T.stash_menu(*key), then_to, under='Quantity')
    now = T.stash_snap(c.path, G.app.data)
    T.eq(qty(now), 1 if then_to == 'Min' else C.CLUSTER_QUANTITY_MAX, f'quantity after {then_to}')
    G.answers['int'] = 5
    T.invoke(T.stash_menu(*key), 'Remove...' if then_to == 'Max' else 'Add...', under='Quantity')
    T.eq(qty(T.stash_snap(c.path, G.app.data)), C.CLUSTER_QUANTITY_MAX - 5 if then_to == 'Max' else 6, 'quantity after Add / Remove 5')
    if start == C.CLUSTER_QUANTITY_MAX:
        T.invoke(T.stash_menu(*key), 'Max', under='Quantity')
        T.eq(T.stash_snap(c.path, G.app.data)[key][1], c.snap[key][1], 'bytes of the item back at its first quantity')


@T.test
def make_perfect():
    import mxl_perfect
    import mxl_rc_menu
    import mxl_save
    app = G.app
    cr = mxl_rc_menu._creator(app)

    def improvable(it, rec, b):
        try:
            return bool(mxl_perfect.plan(mxl_save.blob_item(mxl_save.item_blob(T.read(app.path), it), app.data), app.data, cr)['changes'])
        except Exception:
            return False
    key = first(improvable, 'item with a roll below its maximum')
    c = Ctx()
    before = mxl_perfect.plan(mxl_save.blob_item(c.snap[key][1], app.data), app.data, cr)
    lab = T.invoke(T.stash_menu(*key), 'Make perfect (', under='Specific editing functions')
    T.check(f'({len(before["changes"])} of {before["total"]} rolls' in lab, f'menu label {lab!r} vs plan {len(before["changes"])} of {before["total"]}')
    now = c.after(chg=[key], what='make perfect')
    it0, it1 = mxl_save.blob_item(c.snap[key][1], app.data), mxl_save.blob_item(now[key][1], app.data)
    after = mxl_perfect.plan(it1, app.data, cr)
    T.eq(len(after['changes']), 0, 'rolls still below the maximum')
    T.eq(after['total'], before['total'], 'number of rolls')
    s0 = {(s, p): v for s, p, v in T.stats_of(it0)}
    s1 = {(s, p): v for s, p, v in T.stats_of(it1)}
    T.eq(sorted(s0), sorted(s1), 'stat ids after Make perfect')
    T.check(s0 != s1, 'no stat value changed')
    r0, r1 = T.rec_of(c.snap[key][1]), T.rec_of(now[key][1])
    T.eq({k: v for k, v in r1.items() if k not in ('stats', 'defense')}, {k: v for k, v in r0.items() if k not in ('stats', 'defense')},
         'fields other than the stats')
    labels = T.menu_labels(T.stash_menu(*key))
    T.check('Make perfect (already perfect)' in labels, f'menu after Make perfect: {[x for x in labels if x.startswith("Make perfect")]}')


@T.test
def ethereal_off_and_on():
    import mxl_creator as C
    key = first(lambda it, rec, b: b.kind in ('armor', 'weapons') and rec['quality'] != 'set'
                and not rec['flags'] & C.FLAG_SIMPLE, 'armor or weapon')
    c = Ctx()
    was = bool(T.rec_of(c.snap[key][1])['flags'] & C.FLAG_ETHEREAL)
    steps = ('Remove ethereal', 'Make ethereal') if was else ('Make ethereal', 'Remove ethereal')
    T.invoke(T.stash_menu(*key), steps[0], under='Specific editing functions')
    now = c.after(chg=[key], what=steps[0])
    r0, r1 = T.rec_of(c.snap[key][1]), T.rec_of(now[key][1])
    T.eq(bool(r1['flags'] & C.FLAG_ETHEREAL), not was, f'ethereal flag after {steps[0]!r}')
    T.eq(r1['flags'] ^ r0['flags'], C.FLAG_ETHEREAL, 'flag bits changed')
    T.eq(T.stats_of(r1), T.stats_of(r0), 'stats of the item')
    T.eq(now[key][1][len(now[key][1]) - len(T.record(now[key][1])[1]):], c.snap[key][1][len(c.snap[key][1]) - len(T.record(c.snap[key][1])[1]):],
         'socketed items behind the item')
    T.invoke(T.stash_menu(*key), steps[1], under='Specific editing functions')
    now = c.after(chg=[] if T.stash_snap(c.path, G.app.data)[key] == c.snap[key] else [key], what=steps[1])
    r2 = T.rec_of(now[key][1])
    T.eq(bool(r2['flags'] & C.FLAG_ETHEREAL), was, f'ethereal flag after {steps[1]!r}')
    T.eq(T.stats_of(r2), T.stats_of(r0), 'stats after both steps')
    T.eq({k: r2.get(k) for k in ('defense', 'durability', 'max_durability')}, {k: r0.get(k) for k in ('defense', 'durability', 'max_durability')},
         'defense / durability after removing and making ethereal again')


def seed(spec):
    """Writes a new item into the stash (creator build + the application's stash writer) and reloads the window:
    the sample stash has no item for some actions. Returns its (page, x, y)."""
    import mxl_rc_menu
    import mxl_save
    app = G.app
    blob = bytes(mxl_rc_menu._creator(app).build(spec)[0])
    spot = mxl_save.free_spot(mxl_save.parse_stash(app.path, app.data), mxl_save.blob_item(blob, app.data), app.data, [0, 1, 2])
    mxl_save.edit_stash(app.path, app.data, insert=[(spot[0], spot[1], spot[2], blob)], backup=False)
    app.load(app.path, keep_selection=False)
    T.pump()
    return tuple(spot)


def seed_plain_armor():
    """A plain armor without sockets; returns ((page, x, y), sockets its base allows)."""
    import mxl_rc_menu
    cr = mxl_rc_menu._creator(G.app)
    base = next(b for b in cr.bases() if b.kind == 'armor' and cr.max_sockets(b.code, 99) >= 3 and b.size[0] * b.size[1] <= 6)
    spec = cr.new_spec('normal', base.code)
    spec['ilvl'] = 99
    spec['sockets'] = 0
    spec['max_sockets'] = False
    return seed(spec), cr.max_sockets(base.code, 99)


@T.test
def make_socketed():
    import mxl_creator as C
    key, cap = seed_plain_armor()
    c = Ctx()
    r0 = T.rec_of(c.snap[key][1])
    T.check(not r0['flags'] & C.FLAG_SOCKETED, 'the seeded armor already has sockets')
    G.answers['int'] = 2
    lab = T.invoke(T.stash_menu(*key), 'Make socketed...', under='Specific editing functions')
    T.check(f'up to {cap}' in lab, f'menu label {lab!r}, the base allows {cap}')
    now = c.after(chg=[key], what='make socketed')
    r1 = T.rec_of(now[key][1])
    T.check(r1['flags'] & C.FLAG_SOCKETED, 'socketed flag not set')
    T.eq((r1.get('sockets'), r1.get('socketed_count')), (2, 0), '(sockets, socketed items)')
    T.eq({k: v for k, v in r1.items() if k not in ('flags', 'sockets', 'socketed_count')},
         {k: v for k, v in r0.items() if k not in ('flags', 'sockets', 'socketed_count')}, 'other fields')
    it = T.stash_items(c.path, G.app.data)[key]
    T.check(it.get('has_sockets'), 'the host reader does not see the sockets')
    labels = T.menu_labels(T.stash_menu(*key))
    T.check(not any(x.startswith('Make socketed') for x in labels), 'Make socketed still offered on a socketed item')
    G.answers['int'] = None                       # dialog cancelled: nothing is written
    key2, _cap = seed_plain_armor()
    raw = T.read(c.path)
    T.invoke(T.stash_menu(*key2), 'Make socketed...', under='Specific editing functions')
    T.check(T.read(c.path) == raw, 'a cancelled dialog wrote the stash')


@T.test
def fill_sockets_then_remove_them():
    """Copy a jewel, 'Fill sockets with ...' on an armor (copies of the jewel become its socketed items), then
    'Remove socketed items'."""
    import mxl_creator as C
    import mxl_rc_menu
    cr = mxl_rc_menu._creator(G.app)
    jewel = seed(cr.new_spec('normal', cr.sockets_fillers()[0][0]))
    key, cap = seed_plain_armor()
    cap = min(cap, 7)
    G.answers['int'] = cap
    T.invoke(T.stash_menu(*key), 'Make socketed...', under='Specific editing functions')
    c = Ctx()
    T.eq(T.rec_of(c.snap[key][1]).get('sockets'), cap, 'sockets of the seeded armor')
    T.invoke(T.stash_menu(*jewel), 'Copy')
    lab = T.invoke(T.stash_menu(*key), 'Fill sockets with')
    T.check(f'(now 0 of {cap})' in lab, f'menu label {lab!r}, expected 0 of {cap}')
    T.check(f'{cap} x ' in T.status_text() and 'socketed' in T.status_text(), f'status after the fill: {T.status_text()!r}')
    now = c.after(chg=[key], what='fill sockets')
    rec, kids = mxl_rc_menu._children_blobs(now[key][1], G.app.data)
    T.eq((rec.get('socketed_count'), len(kids)), (cap, cap), '(socketed count, socketed items) after the fill')
    T.check(rec['flags'] & C.FLAG_SOCKETED, 'socketed flag not set by the fill')
    want = T.record(c.snap[jewel][1])[0]
    for k in kids:
        T.eq(T.record(k)[0], want, 'a socketed copy vs the copied jewel')
    T.eq(T.stats_of(T.rec_of(now[key][1])), T.stats_of(T.rec_of(c.snap[key][1])), 'own stats of the armor')
    it = T.stash_items(c.path, G.app.data)[key]
    T.eq(len(it.get('socketed') or ()), cap, 'socketed items the host reader sees')
    lab = T.invoke(T.stash_menu(*key), 'Remove socketed items', under='Specific editing functions')
    T.check(f'({cap})' in lab, f'menu label {lab!r}')
    after = c.after(chg=[key], what='remove socketed items')
    rec2, kids2 = mxl_rc_menu._children_blobs(after[key][1], G.app.data)
    T.eq((rec2.get('socketed_count') or 0, len(kids2)), (0, 0), '(socketed count, socketed items) after the removal')
    T.eq(T.stats_of(rec2), T.stats_of(T.rec_of(c.snap[key][1])), 'own stats of the armor after the removal')


def verified(path, what):
    """The file on disk passes both independent checks: the application's save check (mxl_savecheck, the one
    every write goes through) and the command line `python -m mxlsave verify` (parse -> rebuild -> same bytes)."""
    import os
    import subprocess
    import sys
    import mxl_savecheck
    r = mxl_savecheck.examine(path, T.read(path))
    T.check(r.ok, f'{what}: the save check refuses the file: {r.problems}')
    home = os.path.dirname(os.path.abspath(mxl_savecheck.lib().__file__))
    p = subprocess.run([sys.executable, '-m', 'mxlsave', 'verify', path, '--user-dir', G.user_dir],
                       cwd=os.path.dirname(home), capture_output=True, text=True, timeout=120)
    T.check(p.returncode == 0, f'{what}: mxlsave verify: {(p.stdout + p.stderr).strip()[-300:]}')


def unrestricted(on):
    """The creator's 'Unrestricted' switch (a remembered setting); returns the value it had."""
    import settings
    was = settings.get('capy_unrestricted')
    settings.put('capy_unrestricted', on)
    return was


def filled(c, key, n, sockets, filler, what):
    """Checks a stash item after a fill: n socketed copies of the filler in `sockets` sockets, the item's own
    fields and stats as before, the file valid for the host reader and for the independent checks."""
    import mxl_creator as C
    import mxl_rc_menu
    now = c.after(chg=[key], what=what)
    rec, kids = mxl_rc_menu._children_blobs(now[key][1], G.app.data)
    T.check(rec['flags'] & C.FLAG_SOCKETED, f'{what}: socketed flag not set')
    T.eq((rec.get('sockets'), rec.get('socketed_count'), len(kids)), (sockets, n, n), f'{what}: (sockets, socketed count, socketed items)')
    T.eq(len(now[key][1]), len(T.record(now[key][1])[1]) + len(C.encode_item(rec, G.app.data)), f'{what}: bytes of the entry')
    want = T.record(c.snap[filler][1])[0]
    for i, k in enumerate(kids):
        T.eq(T.record(k)[0], want, f'{what}: socketed copy {i} vs the copied item')
        kr = T.rec_of(k)
        T.eq((kr['location'], kr['x'], kr['y']), (C.LOC_SOCKETED, i, 0), f'{what}: place of socketed copy {i}')
    r0 = T.rec_of(c.snap[key][1])
    skip = ('flags', 'sockets', 'socketed_count')
    T.eq({k: v for k, v in rec.items() if k not in skip}, {k: v for k, v in r0.items() if k not in skip}, f'{what}: other fields of the item')
    T.eq(rec['flags'] & ~C.FLAG_SOCKETED, r0['flags'] & ~C.FLAG_SOCKETED, f'{what}: other flags of the item')
    it = T.stash_items(c.path, G.app.data)[key]
    T.eq(len(it.get('socketed') or ()), n, f'{what}: socketed items the host reader sees')
    verified(c.path, what)
    return now


def fill_labels(key):
    return [x for x in T.menu_labels(T.stash_menu(*key)) if x.startswith('Fill sockets')]


# Was a BUG: "Fill sockets with ..." was offered on an item without sockets and then built a record with socketed
# items behind it but WITHOUT the socketed flag (and without the socket count): no reader takes those records as the
# item's children, the page's item count no longer matched and the next page's 'STASH' header was not where the
# count said ("unexpected file structure: 'STASH' expected at byte N"; nothing was written). Now the entry says
# that it adds the sockets, and the parent gets the flag and the count.
@T.test
def fill_sockets_on_an_item_without_sockets():
    import mxl_creator as C
    import mxl_rc_menu
    was = unrestricted(False)
    try:
        cr = mxl_rc_menu._creator(G.app)
        jewel = seed(cr.new_spec('normal', cr.sockets_fillers()[0][0]))
        key, cap = seed_plain_armor()
        cap = min(cap, 6)
        c = Ctx()
        T.check(not T.rec_of(c.snap[key][1])['flags'] & C.FLAG_SOCKETED, 'the seeded armor already has sockets')
        T.eq(fill_labels(key), [], 'Fill entry with nothing copied')
        T.invoke(T.stash_menu(*jewel), 'Copy')
        lab = T.invoke(T.stash_menu(*key), 'Fill sockets with')
        T.check(f'(adds {cap} sockets' in lab, f'menu label {lab!r}: the base allows {cap} sockets')
        T.check('unexpected file structure' not in T.status_text() and f'{cap} x ' in T.status_text()
                and f'{cap} sockets added' in T.status_text(), f'status after the fill: {T.status_text()!r}')
        filled(c, key, cap, cap, jewel, 'fill an unsocketed armor')
        T.eq(fill_labels(key), [], 'Fill entry on the item at its socket limit')
    finally:
        unrestricted(was)


@T.test
def fill_sockets_fills_the_free_sockets_first():
    """An armor with 2 of its possible sockets: the fill puts 2 copies in (no socket added); the full item is
    then offered the remaining sockets of its base; at the base's limit nothing is offered."""
    import mxl_rc_menu
    was = unrestricted(False)
    try:
        cr = mxl_rc_menu._creator(G.app)
        jewel = seed(cr.new_spec('normal', cr.sockets_fillers()[0][0]))
        key, cap = seed_plain_armor()
        cap = min(cap, 6)
        G.answers['int'] = 2
        T.invoke(T.stash_menu(*key), 'Make socketed...', under='Specific editing functions')
        c = Ctx()
        T.invoke(T.stash_menu(*jewel), 'Copy')
        lab = T.invoke(T.stash_menu(*key), 'Fill sockets with')
        T.check('(now 0 of 2)' in lab, f'menu label {lab!r}, expected 0 of 2')
        T.check('added' not in T.status_text(), f'status after the fill: {T.status_text()!r}')
        filled(c, key, 2, 2, jewel, 'fill 2 free sockets')
        lab = T.invoke(T.stash_menu(*key), 'Fill sockets with')
        T.check(f'(adds {cap - 2} sockets: 2 of {cap})' in lab, f'menu label of the full item {lab!r}, the base allows {cap}')
        filled(c, key, cap, cap, jewel, 'fill a fully socketed armor')
        T.eq(fill_labels(key), [], 'Fill entry on the item at its socket limit')
        raw = T.read(c.path)
        mxl_rc_menu._fill_sockets(G.app, next(i for i in G.app.items if (i['page'], i['x'], i['y']) == key))
        T.check('no sockets available' in T.status_text(), f'status of a fill without room: {T.status_text()!r}')
        T.check(T.read(c.path) == raw, 'a fill without room wrote the stash')
    finally:
        unrestricted(was)


@T.test
def fill_sockets_not_offered_where_it_cannot_work():
    """No entry on an item whose base cannot have sockets, on a compact item, or when the copied item is not a
    gem / rune; the action itself refuses too and writes nothing."""
    import mxl_creator as C
    import mxl_rc_menu
    was = unrestricted(True)                 # even unrestricted: only weapons and armor get sockets
    try:
        cr = mxl_rc_menu._creator(G.app)
        jewel = seed(cr.new_spec('normal', cr.sockets_fillers()[0][0]))
        armor, _cap = seed_plain_armor()
        nosock = first(lambda it, rec, b: any_item(it, rec, b) and b.kind == 'misc' and not rec['flags'] & C.FLAG_SOCKETED
                       and cr.max_sockets(it['code'], rec['ilvl']) == 0, 'item whose base cannot have sockets')
        c = Ctx()
        T.invoke(T.stash_menu(*jewel), 'Copy')
        T.eq(fill_labels(nosock), [], 'Fill entry on an item that cannot have sockets')
        T.eq(fill_labels(jewel), [], 'Fill entry on a compact item (the gem itself)')
        item = lambda k: next(i for i in G.app.items if (i['page'], i['x'], i['y']) == k)
        for k in (nosock, jewel):
            mxl_rc_menu._fill_sockets(G.app, item(k))
            T.check(T.read(c.path) == c.raw, f'the refused fill of {c.snap[k][0]!r} wrote the stash: {T.status_text()!r}')
            T.check('socket' in T.status_text(), f'status of the refused fill: {T.status_text()!r}')
        T.invoke(T.stash_menu(*nosock), 'Copy')                       # not a gem / rune in the clipboard
        T.eq(fill_labels(armor), [], 'Fill entry with a copied item that is not a gem or rune')
        mxl_rc_menu._fill_sockets(G.app, item(armor))
        T.check('not a socketable' in T.status_text(), f'status: {T.status_text()!r}')
        T.check(T.read(c.path) == c.raw, 'a fill with a wrong item wrote the stash')
    finally:
        unrestricted(was)


@T.test
def fill_sockets_unrestricted_goes_past_the_base_limit():
    """Unrestricted on: a weapon / armor gets the game's 6 sockets whatever its base allows."""
    import mxl_rc_menu
    cr = mxl_rc_menu._creator(G.app)
    base = next((b for b in cr.bases() if b.kind in ('armor', 'weapons') and 0 < cr.max_sockets(b.code, 99) < 6
                 and b.size[0] * b.size[1] <= 6), None)
    if base is None:
        T.skip('no weapon / armor base with fewer than 6 sockets')
    cap = cr.max_sockets(base.code, 99)
    spec = cr.new_spec('normal', base.code)
    spec['ilvl'] = 99
    spec['sockets'] = 0
    spec['max_sockets'] = False
    jewel = seed(cr.new_spec('normal', cr.sockets_fillers()[0][0]))
    key = seed(spec)
    was = unrestricted(False)
    try:
        c = Ctx()
        T.invoke(T.stash_menu(*jewel), 'Copy')
        labs = fill_labels(key)
        T.check(len(labs) == 1 and f'(adds {cap} sockets' in labs[0], f'restricted: menu {labs}, the base allows {cap}')
        unrestricted(True)
        lab = T.invoke(T.stash_menu(*key), 'Fill sockets with')
        T.check('(adds 6 sockets' in lab, f'unrestricted: menu label {lab!r}')
        filled(c, key, 6, 6, jewel, 'unrestricted fill')
    finally:
        unrestricted(was)


# Was a BUG: "Fill sockets with ..." wrote the stash without recording anything for undo: Ctrl+Z after it said
# "Nothing to undo" (or undid the action before it). Now the fill is recorded like the creator's replace: the undo
# puts the item's old bytes back at its old index in its page's list.
@T.test
def fill_sockets_then_undo_restores_the_file_bytes():
    """Fill (sockets added to an unsocketed armor, and free sockets of a socketed one), then Ctrl+Z: the very same
    stash file each time; two fills, two undos in a row too."""
    import mxl_rc_menu
    import mxl_undo
    was = unrestricted(False)
    try:
        cr = mxl_rc_menu._creator(G.app)
        jewel = seed(cr.new_spec('normal', cr.sockets_fillers()[0][0]))
        bare, _cap = seed_plain_armor()
        free, _cap = seed_plain_armor()
        G.answers['int'] = 2
        T.invoke(T.stash_menu(*free), 'Make socketed...', under='Specific editing functions')
        T.invoke(T.stash_menu(*jewel), 'Copy')
        G.app._undo = []
        c = Ctx()
        for key, what in ((bare, 'fill of an unsocketed armor'), (free, 'fill of 2 free sockets')):
            T.invoke(T.stash_menu(*key), 'Fill sockets with')
            T.check(T.read(c.path) != c.raw, f'{what}: nothing written ({T.status_text()!r})')
            T.check(mxl_undo.can_undo(G.app), f'{what}: nothing to undo after the fill')
            mxl_undo._do_undo(G.app)
            T.check('Nothing to undo' not in T.status_text() and 'failed' not in T.status_text(),
                    f'{what}: status of the undo {T.status_text()!r}')
            same_file(c, f'{what} + undo')
            T.check(not mxl_undo.can_undo(G.app), f'{what}: undo stack not empty after the undo')
            verified(c.path, f'{what} + undo')
        T.invoke(T.stash_menu(*bare), 'Fill sockets with')
        T.invoke(T.stash_menu(*free), 'Fill sockets with')
        mxl_undo._do_undo(G.app)
        mxl_undo._do_undo(G.app)
        same_file(c, 'two fills, two undos')
        verified(c.path, 'two fills, two undos')
    finally:
        unrestricted(was)


@T.test
def undo_of_a_fill_when_the_item_changed_since():
    """An external stash edit invalidates the fill undo while leaving the newer item intact."""
    import mxl_rc_menu
    import mxl_save
    import mxl_socket_menu
    import mxl_undo
    was = unrestricted(False)
    try:
        cr = mxl_rc_menu._creator(G.app)
        jewel = seed(cr.new_spec('normal', cr.sockets_fillers()[0][0]))
        key, _cap = seed_plain_armor()
        T.invoke(T.stash_menu(*jewel), 'Copy')
        G.app._undo = []
        T.invoke(T.stash_menu(*key), 'Fill sockets with')
        filled = Ctx()
        item = T.stash_items(filled.path, G.app.data)[key]
        replacement, removed = mxl_socket_menu.without(filled.snap[key][1], G.app.data)
        T.check(removed > 0, 'the external edit removes socket fillers')
        mxl_save.edit_stash(filled.path, G.app.data, remove=[item['_offset']],
                            insert=[(*key, replacement)], backup=False)
        G.app.load(filled.path, keep_selection=True)
        c = Ctx()
        T.check(c.raw != filled.raw, 'the stash changed after the fill')
        mxl_undo._do_undo(G.app)
        T.check('changed' in T.status_text(), f'status of the refused undo: {T.status_text()!r}')
        same_file(c, 'refused undo of a fill')
    finally:
        unrestricted(was)


T.main(globals())
