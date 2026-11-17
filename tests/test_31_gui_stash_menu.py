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
@T.test(xfail="Duplicate as the first stash write of a session raises AttributeError: 'App' object has no attribute "
              "'bak_name' (mxl_rc_menu._duplicate) after the copy is written")
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


# BUG (same cause as WORKLOG W15 "add-then-delete ... leaves the stash 336 bytes different though parsing equal"):
# the stash writer appends a (re)inserted item at the end of its page, so the item order inside the file changes.
# Every item is back byte for byte (test above) and the game reads the file the same; the file is not identical.
@T.test(xfail='Delete + Undo: every item is back byte for byte, but the stash file differs from the original '
              '(the restored item is written at the end of its page)')
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


# BUG: "Fill sockets with ..." is also offered on an item that has no sockets at all (the entry only compares the
# base's socket cap with the number of socketed items). The action then builds a record with socketed items but
# without the socketed flag; the safe writer refuses it ("unexpected file structure: 'STASH' expected at byte N"),
# so nothing is written - but the user gets that message instead of sockets, or no menu entry.
@T.test(xfail="'Fill sockets' on an item without sockets fails with \"unexpected file structure: 'STASH' expected\" "
              '(entry offered although the item is not socketed)')
def fill_sockets_on_an_item_without_sockets():
    import mxl_creator as C
    import mxl_rc_menu
    cr = mxl_rc_menu._creator(G.app)
    jewel = seed(cr.new_spec('normal', cr.sockets_fillers()[0][0]))
    key, cap = seed_plain_armor()
    c = Ctx()
    T.invoke(T.stash_menu(*jewel), 'Copy')
    labels = T.menu_labels(T.stash_menu(*key))
    if not any(x.startswith('Fill sockets with') for x in labels):
        c.after(what='no Fill entry on an unsocketed item')          # fixed by not offering it: fine
        return
    T.invoke(T.stash_menu(*key), 'Fill sockets with')
    T.check('unexpected file structure' not in T.status_text(), f'status after the fill: {T.status_text()!r}')
    now = T.stash_snap(c.path, G.app.data)
    rec, kids = mxl_rc_menu._children_blobs(now[key][1], G.app.data)
    T.check(len(kids) > 0 and rec['flags'] & C.FLAG_SOCKETED, f'{len(kids)} socketed items after the fill')


T.main(globals())
