"""Right-click actions on character items, in both places that have them: the equipment / inventory panel of the
Stash tab ('panel': mxl_inv_gui.MainInventory through its PanelWin adapter) and the Character tab's equipment page
('tab': mxl_char_gui.CharacterWindow). Same menu code (mxl_rc_menu._char_menu), two different writers.

Every test starts from the pristine sample files and checks the character file re-read from disk: header size and
checksum right, the touched item changed as asked, every other item byte-identical, the stash untouched."""
import os

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'panel': {'CAPY_HOLDER': 'panel'}, 'tab': {'CAPY_HOLDER': 'tab'}}
G = T.G
HOLDER = os.environ.get('CAPY_HOLDER', 'panel')
SLOT, INV = 1, 0                      # item location codes of the save format: equipped, stored


def view(merc=False):
    """Shows the character (or the mercenary) in the place under test."""
    if HOLDER == 'tab':
        cw = T.chartab()
        if 'Character' not in str(T.tab_names()) or cw is None:
            raise T.Failed('no Character tab')
        T.select_tab('Character')
        if cw.tab.get() != 'inventory':
            cw.tab.set('inventory')
            cw.show_tab()
        if bool(cw.merc.get()) != merc:
            cw.merc.set(merc)
            cw.on_view()
    else:
        inv = G.app.inventory
        if bool(inv.merc.get()) != merc:
            inv.merc.set(merc)
            inv.on_view()
    T.pump(6)


def menu(where, merc=False):
    view(merc)
    return T.chartab_menu(where) if HOLDER == 'tab' else T.panel_menu(where)


def key_of(where, merc=False):
    """Snapshot key of a place: ('slot', n) or ('inv', x, y)."""
    return (merc, SLOT, where[1], where[1], 0, 0) if where[0] == 'slot' else (merc, INV, 0, where[1], where[2], 1)


def where_of(key):
    if key[1] == SLOT:
        return ('slot', key[2])
    if key[1] == INV and key[5] == 1:
        return ('inv', key[3], key[4])
    return None


class Ctx:
    def __init__(self):
        self.path = G.app.character_file()
        self.snap = T.char_snap(self.path, G.app.data)
        self.raw = T.read(self.path)
        self.stash = T.read(G.app.path)

    def after(self, gone=(), new=(), chg=(), what='', stash_same=True):
        T.pump()
        raw = T.read(self.path)
        for problem in T.d2s_header_ok(raw):
            T.check(False, f'{what}: character file {problem}')
        now = T.char_snap(self.path, G.app.data)
        T.only_changed(self.snap, now, gone, new, chg, what)
        if stash_same:
            T.check(T.read(G.app.path) == self.stash, f'{what}: the stash file changed')
        import mxl_char
        ch = mxl_char.Character(self.path, G.app.data)
        T.check(ch.build() == raw, f'{what}: the written character does not rebuild identically')
        shown = G.app.inventory.ch
        T.check(shown is not None and bytes(shown.raw) == raw, f'{what}: the Stash tab panel does not show the file on disk')
        cw = T.chartab()
        if HOLDER == 'tab' and cw is not None:
            T.check(bytes(cw.ch.raw) == raw, f'{what}: the Character tab does not hold the file on disk')
        return now


def first(pred, what, merc=False):
    """Place of the first character item (in menu reach) for which pred(entry, record, base) holds."""
    import mxl_char
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    for e in ch.entries(merc):
        it = e.it
        where = ('slot', it['equipped']) if it['location'] == SLOT else \
            ('inv', it['x'], it['y']) if it['location'] == INV and it.get('panel') == 1 else None
        if where is None or merc and where[0] != 'slot':
            continue
        try:
            rec = T.rec_of(e.blob)
        except Exception:
            continue
        if pred(e, rec, G.app.data.base(it['code'])):
            return where
    T.skip(f'the sample character has no {what}')


def full(e, rec, base):
    import mxl_creator
    return not rec['flags'] & mxl_creator.FLAG_SIMPLE


def free_inventory_cell(size=(1, 1)):
    import mxl_char
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    used = set()
    for e in ch.inventory():
        w, h = G.app.data.base(e.it['code']).size
        used |= {(e.it['x'] + i, e.it['y'] + j) for i in range(w) for j in range(h)}
    for y in range(mxl_char.INV_H - size[1] + 1):
        for x in range(mxl_char.INV_W - size[0] + 1):
            if all((x + i, y + j) not in used for i in range(size[0]) for j in range(size[1])):
                return ('inv', x, y)
    T.skip('no free inventory cell on the sample character')


@T.test
def menu_lists_the_actions():
    where = first(lambda e, rec, b: full(e, rec, b) and e.it['location'] == SLOT, 'equipped item')
    c = Ctx()
    labels = T.menu_labels(menu(where))
    for want in ('Edit item...', 'Item stats...', 'Duplicate', 'Copy', 'Cut', 'Quantity (now', 'Change item quality',
                 'Specific editing functions', 'To stash', 'Delete', 'Export item...'):
        T.check(any(lab.startswith(want) for lab in labels), f'menu entry {want!r} missing: {labels}')
    T.eq(T.menu_labels(menu(free_inventory_cell())), ['Import item...', 'Create here...'], 'menu of an empty inventory cell')
    c.after(what='opening menus')
    T.check(T.read(c.path) == c.raw, 'opening menus changed the character file')


@T.test
def duplicate_equipped_item_into_inventory():
    where = first(lambda e, rec, b: full(e, rec, b) and e.it['location'] == SLOT and b.size[0] * b.size[1] <= 6, 'small equipped item')
    c = Ctx()
    T.invoke(menu(where), 'Duplicate')
    g, new, chg = T.diff(c.snap, T.char_snap(c.path, G.app.data))
    T.eq((g, chg, len(new)), ([], [], 1), 'duplicate: (removed, changed, number added)')
    now = c.after(new=new, what='duplicate')
    T.eq(new[0][:2] + new[0][5:], (False, INV, 1), 'the copy is in the inventory')
    T.check(T.same_item(now[new[0]][1], c.snap[key_of(where)][1]), 'the copy is not the same item as the original')


@T.test
def copy_then_paste_here():
    where = first(lambda e, rec, b: full(e, rec, b) and e.it['location'] == INV and b.size == (1, 1), '1x1 inventory item')
    c = Ctx()
    T.invoke(menu(where), 'Copy')
    T.check(G.app._capy_clip is not None, 'nothing in the clipboard after Copy')
    T.check(T.read(c.path) == c.raw, 'Copy wrote the character file')
    cell = free_inventory_cell()
    T.invoke(menu(cell), 'Paste here')
    now = c.after(new=[key_of(cell)], what='paste here')
    T.check(T.same_item(now[key_of(cell)][1], c.snap[key_of(where)][1]), 'the pasted item is not the copied one')


@T.test
def copy_then_paste_replaces():
    src = first(lambda e, rec, b: full(e, rec, b) and e.it['location'] == INV and b.size == (1, 1), '1x1 inventory item')
    src_blob = T.char_snap(G.app.character_file(), G.app.data)[key_of(src)][1]
    dst = first(lambda e, rec, b: e.it['location'] == INV and b.size == (1, 1) and ('inv', e.it['x'], e.it['y']) != src
                and full(e, rec, b) and not T.same_item(e.blob, src_blob), 'second 1x1 inventory item')
    c = Ctx()
    T.invoke(menu(src), 'Copy')
    T.invoke(menu(dst), 'Paste (replaces it')
    now = c.after(chg=[key_of(dst)], what='paste over an item')
    T.check(T.same_item(now[key_of(dst)][1], c.snap[key_of(src)][1]), 'the item at the target is not the copied one')


@T.test
def cut_then_paste():
    where = first(lambda e, rec, b: full(e, rec, b) and e.it['location'] == INV, 'inventory item')
    c = Ctx()
    T.invoke(menu(where), 'Cut')
    c.after(gone=[key_of(where)], what='cut')
    T.check(any(kind == 'askyesno' for kind, _t, _m in G.boxes), 'Cut removed the item without the delete confirmation')
    T.check(G.app._capy_clip is not None, 'nothing in the clipboard after Cut')
    T.invoke(menu(where), 'Paste here')
    now = c.after(what='cut + paste at the same place')
    T.eq(now[key_of(where)][1], c.snap[key_of(where)][1], 'bytes of the item after cut + paste at its own place')


@T.test
def delete_asks_and_deletes():
    where = first(lambda e, rec, b: e.it['location'] == INV, 'inventory item')
    c = Ctx()
    G.answers['askyesno'] = False
    T.invoke(menu(where), 'Delete')
    T.check(any(kind == 'askyesno' for kind, _t, _m in G.boxes), 'Delete did not ask')
    c.after(what='delete answered No')
    T.check(T.read(c.path) == c.raw, 'Delete answered No wrote the character file')
    G.answers['askyesno'] = True
    T.invoke(menu(where), 'Delete')
    c.after(gone=[key_of(where)], what='delete')


@T.test
def to_stash():
    where = first(lambda e, rec, b: full(e, rec, b) and e.it['location'] == SLOT and b.size[0] * b.size[1] <= 4, 'small equipped item')
    c = Ctx()
    stash0 = T.stash_snap(G.app.path, G.app.data)
    T.invoke(menu(where), 'To stash')
    c.after(gone=[key_of(where)], what='to stash', stash_same=False)
    stash1 = T.stash_snap(G.app.path, G.app.data)
    g, new, chg = T.diff(stash0, stash1)
    T.eq((g, chg, len(new)), ([], [], 1), 'stash: (removed, changed, number added)')
    if new:
        T.check(T.same_item(stash1[new[0]][1], c.snap[key_of(where)][1]), 'the item in the stash is not the one taken off')


@T.test
def quantity_of_a_stack():
    """A stackable item (quiver ...): the quantity field of its record."""
    where = first(lambda e, rec, b: b.stack_max is not None and not rec['flags'] & 0x20 and full(e, rec, b), 'stackable item')
    c = Ctx()
    k = key_of(where)
    cap = G.app.data.base(c.snap[k][0]).stack_max
    start = T.rec_of(c.snap[k][1]).get('quantity')
    T.check(f'Quantity (now {start})' in T.menu_labels(menu(where)), f'menu does not show the quantity {start}')
    T.invoke(menu(where), 'Min', under='Quantity')
    now = c.after(chg=[k], what='quantity Min')
    r0, r1 = T.rec_of(c.snap[k][1]), T.rec_of(now[k][1])
    T.eq(r1.get('quantity'), 1, 'quantity after Min')
    T.eq({x: v for x, v in r1.items() if x != 'quantity'}, {x: v for x, v in r0.items() if x != 'quantity'}, 'other fields')
    T.invoke(menu(where), f'Max ({cap})', under='Quantity')
    now = T.char_snap(c.path, G.app.data)
    T.eq(T.rec_of(now[k][1]).get('quantity'), cap, 'quantity after Max')
    if start == cap:
        T.eq(now[k][1], c.snap[k][1], 'bytes of the item back at its first quantity')
        T.check(T.read(c.path) == c.raw, 'Min then Max did not give the original file back')
    G.answers['int'] = 7
    T.invoke(menu(where), 'Remove...', under='Quantity')
    T.eq(T.rec_of(T.char_snap(c.path, G.app.data)[k][1]).get('quantity'), cap - 7, 'quantity after Remove 7')


@T.test
def quantity_of_a_cluster():
    import mxl_creator as C
    where = first(lambda e, rec, b: b.stack_max is None and e.it['location'] == INV
                  and any(s['id'] == C.CLUSTER_QUANTITY_STAT for s in rec.get('stats') or ()), 'cluster / container in the inventory')
    c = Ctx()
    k = key_of(where)

    def qty(snap):
        return next(s['value'] for s in T.rec_of(snap[k][1])['stats'] if s['id'] == C.CLUSTER_QUANTITY_STAT)
    start = qty(c.snap)
    how = 'Max' if start != C.CLUSTER_QUANTITY_MAX else 'Min'
    T.invoke(menu(where), how, under='Quantity')
    now = c.after(chg=[k], what=f'quantity {how}')
    T.eq(qty(now), C.CLUSTER_QUANTITY_MAX if how == 'Max' else 1, f'quantity after {how}')
    r0, r1 = T.rec_of(c.snap[k][1]), T.rec_of(now[k][1])
    T.eq([s for s in r1['stats'] if s['id'] != 501], [s for s in r0['stats'] if s['id'] != 501], 'other stats')


@T.test
def make_perfect():
    """An item with a roll below its maximum is brought over from the stash (Copy there, Paste here), then made
    perfect where it lies."""
    import mxl_perfect
    import mxl_rc_menu
    import mxl_save
    app = G.app
    cr = mxl_rc_menu._creator(app)
    raw = T.read(app.path)
    src = next((it for it in app.items if app.data.base(it['code']).size == (1, 1)
                and mxl_perfect.plan(mxl_save.blob_item(mxl_save.item_blob(raw, it), app.data), app.data, cr)['changes']), None)
    if src is None:
        T.skip('the sample stash has no 1x1 item with a roll below its maximum')
    T.invoke(T.stash_menu(src['page'], src['x'], src['y']), 'Copy')
    cell = free_inventory_cell()
    T.invoke(menu(cell), 'Paste here')
    T.pump()
    c = Ctx()
    k = key_of(cell)
    before = mxl_perfect.plan(mxl_save.blob_item(c.snap[k][1], app.data), app.data, cr)
    T.check(before['changes'], 'the pasted item has no roll to raise')
    T.invoke(menu(cell), 'Make perfect (', under='Specific editing functions')
    now = c.after(chg=[k], what='make perfect')
    after = mxl_perfect.plan(mxl_save.blob_item(now[k][1], app.data), app.data, cr)
    T.eq((len(after['changes']), after['total']), (0, before['total']), '(rolls below the maximum, rolls) afterwards')
    r0, r1 = T.rec_of(c.snap[k][1]), T.rec_of(now[k][1])
    T.eq(sorted((s['id'], s.get('param')) for s in r1['stats']), sorted((s['id'], s.get('param')) for s in r0['stats']), 'stat ids')
    T.check(T.stats_of(r0) != T.stats_of(r1), 'no stat value changed')
    T.eq(len(now[k][1]), len(c.snap[k][1]), 'size of the item')
    T.check('Make perfect (already perfect)' in T.menu_labels(menu(cell)), 'menu after Make perfect does not say "already perfect"')


@T.test
def ethereal_off_and_on():
    import mxl_creator as C
    where = first(lambda e, rec, b: b.kind in ('armor', 'weapons') and rec['quality'] != 'set' and full(e, rec, b)
                  and e.it['location'] == SLOT and rec['max_durability'] != G.app.data.isc[73]['add'], 'equipped armor / weapon')
    c = Ctx()
    k = key_of(where)
    r0 = T.rec_of(c.snap[k][1])
    was = bool(r0['flags'] & C.FLAG_ETHEREAL)
    steps = ('Remove ethereal', 'Make ethereal') if was else ('Make ethereal', 'Remove ethereal')
    T.invoke(menu(where), steps[0], under='Specific editing functions')
    now = c.after(chg=[k], what=steps[0])
    r1 = T.rec_of(now[k][1])
    T.eq(r1['flags'] ^ r0['flags'], C.FLAG_ETHEREAL, f'flag bits changed by {steps[0]!r}')
    T.eq(T.stats_of(r1), T.stats_of(r0), 'stats of the item')
    T.eq(T.record(now[k][1])[1], T.record(c.snap[k][1])[1], 'socketed items behind the item')
    T.invoke(menu(where), steps[1], under='Specific editing functions')
    T.pump()
    r2 = T.rec_of(T.char_snap(c.path, G.app.data)[k][1])
    T.eq(bool(r2['flags'] & C.FLAG_ETHEREAL), was, f'ethereal flag after {steps[1]!r}')
    T.eq({x: r2.get(x) for x in ('defense', 'durability', 'max_durability')}, {x: r0.get(x) for x in ('defense', 'durability', 'max_durability')},
         'defense / durability after removing and making ethereal again')


@T.test
def sockets_remove_then_make():
    import mxl_creator as C
    where = first(lambda e, rec, b: rec.get('socketed_count') and e.it['location'] == SLOT and full(e, rec, b), 'equipped item with socketed items')
    c = Ctx()
    k = key_of(where)
    r0, kids0 = T.record(c.snap[k][1])
    T.invoke(menu(where), f'Remove socketed items ({r0["socketed_count"]})', under='Specific editing functions')
    now = c.after(chg=[k], what='remove socketed items')
    r1, kids1 = T.record(now[k][1])
    T.eq((r1.get('socketed_count') or 0, len(kids1)), (0, 0), '(socketed count, bytes of socketed items) afterwards')
    T.check(len(kids0) > 0 and len(now[k][1]) < len(c.snap[k][1]), 'the item did not get shorter')
    T.eq(T.stats_of(r1), T.stats_of(r0), 'own stats of the item')
    labels = T.menu_labels(menu(where))
    make = next((x for x in labels if x.startswith('Make socketed...')), None)
    if make is None:
        T.check(False, f'no "Make socketed..." after the removal: {[x for x in labels if "ocket" in x]}')
        return
    G.answers['int'] = 2
    c2 = Ctx()
    T.invoke(menu(where), 'Make socketed...', under='Specific editing functions')
    now = c2.after(chg=[k], what='make socketed')
    r2 = T.rec_of(now[k][1])
    T.check(r2['flags'] & C.FLAG_SOCKETED, 'socketed flag not set')
    T.eq((r2.get('sockets'), r2.get('socketed_count') or 0), (2, 0), '(sockets, socketed items)')
    T.eq(T.stats_of(r2), T.stats_of(r0), 'own stats after both steps')


@T.test
def mercenary_item_make_ethereal_or_perfect():
    """One write on a mercenary item (his list is a different section of the file)."""
    import mxl_char
    import mxl_creator as C
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    if not ch.merc_hired or not ch.entries(True):
        T.skip('the sample character has no mercenary items')
    where = first(lambda e, rec, b: b.kind in ('armor', 'weapons') and rec['quality'] != 'set' and full(e, rec, b)
                  and rec['max_durability'] != G.app.data.isc[73]['add'], 'mercenary armor / weapon', merc=True)
    c = Ctx()
    k = key_of(where, merc=True)
    r0 = T.rec_of(c.snap[k][1])
    step = 'Remove ethereal' if r0['flags'] & C.FLAG_ETHEREAL else 'Make ethereal'
    T.invoke(menu(where, merc=True), step, under='Specific editing functions')
    now = c.after(chg=[k], what=f'mercenary {step}')
    T.eq(T.rec_of(now[k][1])['flags'] ^ r0['flags'], C.FLAG_ETHEREAL, 'flag bits changed')
    view(False)


def hot(what, where, merc=False):
    """A shortcut (Ctrl+V ...) with the mouse pointer over a place: the pointer lookup is replaced by the event."""
    import mxl_rc_menu
    view(merc)
    e = T.chartab_ev(where) if HOLDER == 'tab' else T.panel_ev(where)
    win = T.chartab() if HOLDER == 'tab' else G.app.inventory.as_win()
    saved = mxl_rc_menu._canvas_at_pointer
    mxl_rc_menu._canvas_at_pointer = lambda canvases: e
    try:
        mxl_rc_menu._char_hot(win, what)
    finally:
        mxl_rc_menu._canvas_at_pointer = saved
    T.pump(4)


@T.test
def mercenary_paste_onto_an_empty_slot():
    """Cut a mercenary item, then paste it back onto his now EMPTY slot: by the right-click menu, then (cut again)
    by Ctrl+V with the pointer over the empty slot. Both used to do nothing (the menu had no Paste entry on an
    empty slot, Ctrl+V said "paste onto an inventory cell or an occupied slot")."""
    import mxl_char
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    if not ch.merc_hired or not ch.entries(True):
        T.skip('the sample character has no mercenary items')
    where = first(lambda e, rec, b: e.it['location'] == SLOT, 'mercenary item', merc=True)
    k = key_of(where, merc=True)
    c = Ctx()
    for how in ('menu', 'Ctrl+V'):
        T.invoke(menu(where, merc=True), 'Cut')
        c.after(gone=[k], what=f'cut of the mercenary item ({how})')
        T.check(G.app._capy_clip is not None, 'nothing in the clipboard after Cut')
        if how == 'menu':
            labels = T.menu_labels(menu(where, merc=True))
            T.check(any(lab.startswith('Paste here') for lab in labels), f'no Paste entry on the empty slot: {labels}')
            if any(lab.startswith('Paste here') for lab in labels):
                T.invoke(menu(where, merc=True), 'Paste here')
        else:
            hot('paste', where, merc=True)
        now = c.after(what=f'paste onto the empty mercenary slot ({how})')
        T.check(k in now, f'{how}: nothing in the mercenary slot after the paste')
        if k in now:
            T.eq(now[k][1], c.snap[k][1], f'{how}: bytes of the item after cut + paste at its own slot')
    view(False)


@T.test
def character_paste_onto_an_empty_slot():
    """The same on the character: an equipped item cut and pasted back onto its empty slot with Ctrl+V."""
    where = first(lambda e, rec, b: e.it['location'] == SLOT and e.it['equipped'] in (1, 3, 8, 9, 10), 'helm / armor / belt / boots / gloves')
    k = key_of(where)
    c = Ctx()
    T.invoke(menu(where), 'Cut')
    c.after(gone=[k], what='cut of an equipped item')
    hot('paste', where)
    now = c.after(what='Ctrl+V onto the empty slot')
    T.check(k in now and now[k][1] == c.snap[k][1], 'the item is not back in its slot as it was')


T.main(globals())
