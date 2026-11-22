"""Putting a socket filler (gem, rune, jewel, any item of type 'sock') into a free socket of an item:
- engine (mxl_socket_insert.insert_child): the child is appended after the parent's other socketed items, the
  parent's socketed-item count grows by one, the bytes round-trip; a full / socketless item is refused;
- Item Editor, edit mode: the copied filler goes into a free socket ('Insert copied ...', Creator.add_filler),
  written like the game stores socketed children; a no-op Replace of the result stays byte-identical;
- drag and drop (the game's gesture): a stash jewel dropped on a stash item / a character item, a character
  jewel dropped on a character item; the jewel leaves its place, Ctrl+Z undoes the move; a full item refuses.

The parent is made like test_37's: a unique 2x2 armor with 3 sockets and two gems built by the creator; the
jewel is the one socketed in an item of the sample character."""
import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {
    'd2': {'MXL_THEME': 'd2'},
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
    'he-800x600': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0'},
}
G = T.G


def jewel_raw():
    import mxl_char
    import mxl_creator as C
    d = G.app.data
    ch = mxl_char.Character(G.app.character_file(), d)
    for e in ch.items + (ch.merc_items or []):
        for raw in C.Creator._split(bytes(e.blob), d)[1]:
            k = C.decode_item(raw, d)[0]
            if not k['flags'] & C.FLAG_SIMPLE and k['code'].strip() == 'jew':
                return raw
    raise T.Skip('the sample character has no socketed jewel')


def loose(raw):
    """A socketed child's bytes as a loose item (stored, not socketed)."""
    import mxl_creator as C
    d = G.app.data
    return C.encode_item(dict(C.decode_item(raw, d)[0], location=C.LOC_STORED, equipped=0, x=0, y=0, panel=5), d)


def parent_blob(n_gems=2):
    import mxl_creator as C
    d = G.app.data
    cr = C.Creator(d)
    gems = [c for c, _n in cr.sockets_fillers()]
    for i, _name, u in cr.uniques():
        if d.base(u['code']).kind == 'armor' and d.base(u['code']).size == (2, 2):
            spec = cr.new_spec('unique', None, i)
            if cr.max_sockets(spec['code'], spec['ilvl']) >= 3:
                break
    else:
        raise T.Failed('no unique 2x2 armor that takes 3 sockets')
    cr.roll(spec, 'max')
    spec['sockets'] = 3
    spec['socketed'] = gems[:n_gems]
    blob, _rec = cr.build(spec)
    return bytes(blob), gems[:n_gems]


def put_stash(blob):
    """Writes a blob into a free stash spot; its (page, x, y)."""
    import mxl_save
    d = G.app.data
    items = mxl_save.parse_stash(G.app.path, d)
    spot = mxl_save.free_spot(items, mxl_save.blob_item(blob, d), d, list(range(mxl_save.STASH_PAGES)))
    if spot is None:
        raise T.Skip('stash full')
    mxl_save.edit_stash(G.app.path, d, insert=[(spot[0], spot[1], spot[2], blob)], backup=False)
    G.app.load(G.app.path, keep_selection=False)
    T.pump(6)
    return tuple(spot)


def entry(key):
    import mxl_creator as C
    import mxl_save
    d = G.app.data
    raw = T.read(G.app.path)
    it = next((i for i in mxl_save.parse_stash(G.app.path, d) if (i['page'], i['x'], i['y']) == key), None)
    if it is None:
        return None, None
    return C.decode_blob(bytes(mxl_save.item_blob(raw, it)), d), it


def check_parent(rec, kids, want, what):
    import mxl_creator as C
    T.check(rec['flags'] & C.FLAG_SOCKETED, f'{what}: socketed flag lost')
    T.eq(rec.get('sockets'), 3, f'{what}: socket count')
    T.eq(rec.get('socketed_count'), len(kids), f'{what}: socketed-item count vs children')
    T.eq([k['code'] for k in kids], want, f'{what}: children')
    T.eq([k.get('x') for k in kids], list(range(len(kids))), f'{what}: places of the children')
    T.eq({k.get('location') for k in kids} - {C.LOC_SOCKETED}, set(), f'{what}: children location')


def no_error_boxes(what):
    for kind, title, msg in G.boxes:
        if kind == 'showerror':
            raise T.Failed(f'{what}: error box {title!r}: {msg[:200]}')


# ------------------------------------------------------------------------------------------------ engine
@T.test
def engine_insert_appends_one_child():
    import mxl_creator as C
    import mxl_save
    import mxl_socket_insert as SI
    d = G.app.data
    blob, gems = parent_blob(2)
    jew = jewel_raw()
    new = SI.insert_child(blob, loose(jew), d)
    rec, kids = C.decode_blob(new, d)
    check_parent(rec, kids, gems + ['jew '], 'jewel inserted')
    T.eq(C.encode_item(rec, d) + b''.join(C.encode_item(k, d) for k in kids), new, 'bytes round-trip')
    T.eq(len(mxl_save.blob_item(new, d).get('socketed') or ()), 3, 'children the application reads')
    try:
        SI.insert_child(new, loose(jew), d)
        raise T.Failed('a full item took a fourth child')
    except SI.InsertError as err:
        T.check('free socket' in str(err), f'refusal message: {err}')
    plain = C.encode_item(dict(C.decode_item(blob, d)[0], flags=C.decode_item(blob, d)[0]['flags'] & ~C.FLAG_SOCKETED,
                               socketed_count=0, sockets=0), d)
    try:
        SI.insert_child(plain, loose(jew), d)
        raise T.Failed('an item without sockets took a child')
    except SI.InsertError as err:
        T.check('no sockets' in str(err), f'refusal message: {err}')
    T.check(SI.is_socketable(G.app, 'jew ') and SI.is_socketable(G.app, gems[0]), 'jewel / gem are socket fillers')
    T.check(not SI.is_socketable(G.app, C.decode_item(blob, d)[0]['code']), 'an armor is no socket filler')


# ------------------------------------------------------------------------------------------- Item Editor
@T.test
def edit_mode_inserts_the_copied_jewel():
    import mxl_creator_gui as CG
    import mxl_tabs
    blob, gems = parent_blob(2)
    key = put_stash(blob)
    G.app._capy_clip = (loose(jewel_raw()), 'Jewel')

    def editor():
        G.app.selected = next(i for i in G.app.items if (i['page'], i['x'], i['y']) == key)
        CG.edit_selected(G.app)
        T.pump(10)
        w = mxl_tabs.built_owner('Creator')
        if w is None or w.edit_item is None or w.spec is None:
            raise T.Failed('the Item Editor did not open')
        return w
    w = editor()
    T.eq(w.cr.free_sockets(w.spec), 1, 'free sockets of the edited item')
    T.check(w.copied_filler() is not None, 'the copied jewel is not offered')
    w.add_copied_filler()
    T.pump(4)
    T.eq([r['code'] for r in w.filler_rows()], gems + ['jew '], 'socket rows after the insert')
    T.eq(w.cr.free_sockets(w.spec), 0, 'free sockets after the insert')
    w.commit()
    T.pump(8)
    no_error_boxes('edit-mode insert')
    (rec, kids), _it = entry(key)
    check_parent(rec, kids, gems + ['jew '], 'edit-mode insert')
    w = editor()                                        # opens again, Replace changes nothing
    before = T.stash_snap(G.app.path, G.app.data)
    w.commit()
    T.pump(8)
    T.only_changed(before, T.stash_snap(G.app.path, G.app.data), what='no-op Replace after the insert')
    G.app._capy_clip = None


@T.test
def edit_mode_character_item_rune_out_jewel_in():
    """The character's set item with six Ko runes: one taken out, the copied jewel put in its place."""
    import mxl_char as MC
    import mxl_creator as C
    import mxl_tabs
    d = G.app.data
    inv = G.app.inventory
    inv.merc.set(False)
    inv.on_view()
    T.pump(4)
    e = next((x for x in inv.ch.entries(False) if x.it['code'].strip() == '@04'), None)
    if e is None:
        raise T.Skip('the sample character has no item @04')
    G.app._capy_clip = (loose(jewel_raw()), 'Jewel')
    inv.selected, inv.sel_merc = e, False
    inv.edit()
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    if w is None or w.edit_item is None or w.spec is None:
        raise T.Failed('the Item Editor did not open on the character item')
    w.remove_filler(0)
    T.pump(2)
    w.add_copied_filler()
    T.pump(4)
    w.commit()
    T.pump(8)
    no_error_boxes('character edit-mode insert')
    ch = MC.Character(G.app.character_file(), d)
    e2 = next(x for x in ch.entries(False) if x.it['code'] == e.it['code'])
    rec, kids = C.decode_blob(bytes(e2.blob), d)
    T.eq([k['code'] for k in kids], ['r18 '] * 5 + ['jew '], 'children on disk')
    T.eq(rec.get('socketed_count'), 6, 'socketed-item count')
    T.eq([k.get('x') for k in kids], list(range(6)), 'places of the children')
    G.app._capy_clip = None


# ------------------------------------------------------------------------------------------- drag and drop
def _drag_stash(src, dst_ev):
    app = G.app
    app.on_click(T.stash_ev(*src))
    T.check(app.drag is not None, 'no drag started')
    if src[0] != app.page():
        raise T.Failed('the drag source page is not shown')
    app.on_drag(dst_ev)
    app.on_release(dst_ev)
    T.pump(8)


@T.test
def drag_stash_jewel_onto_stash_item_and_undo():
    import mxl_undo
    blob, gems = parent_blob(2)
    pkey = put_stash(blob)
    jkey = put_stash(loose(jewel_raw()))
    if jkey[0] != pkey[0]:
        raise T.Skip('parent and jewel not on one page')
    raw0 = T.read(G.app.path)
    _drag_stash(jkey, T.stash_ev(*pkey))
    no_error_boxes('drag insert')
    (rec, kids), _it = entry(pkey)
    check_parent(rec, kids, gems + ['jew '], 'stash drag insert')
    T.check(entry(jkey)[1] is None, 'the jewel is still in the stash')
    T.check('socketed into' in T.status_text(), f'status: {T.status_text()!r}')
    T.check(G.app._undo and G.app._undo[-1]['kind'] == 'files', f'no undo step: {G.app._undo[-1:]}')
    mxl_undo.undo(G.app)
    T.pump(8)
    T.eq(T.read(G.app.path), raw0, 'stash after the undo')


@T.test
def drag_onto_a_full_item_is_refused():
    blob, _gems = parent_blob(3)
    pkey = put_stash(blob)
    jkey = put_stash(loose(jewel_raw()))
    if jkey[0] != pkey[0]:
        raise T.Skip('parent and jewel not on one page')
    raw0 = T.read(G.app.path)
    _drag_stash(jkey, T.stash_ev(*pkey))
    T.eq(T.read(G.app.path), raw0, 'the stash after a refused drop')
    T.check('no free socket' in T.status_text(), f'status: {T.status_text()!r}')


def _char_place(blob):
    """Puts a blob into the character's inventory (file written); its ('inv', x, y)."""
    import mxl_char as MC
    import mxl_save
    d = G.app.data
    path = G.app.character_file()
    ch = MC.Character(path, d)
    spot = ch.free_inventory_spot(mxl_save.blob_item(blob, d))
    if spot is None:
        raise T.Skip('inventory full')
    where = ('inv', spot[0], spot[1])
    ch.place(blob, where, False)
    ch.save(backup=False)
    inv = G.app.inventory
    inv.merc.set(False)
    inv.refresh(force=True)
    T.pump(6)
    return where


def _char_item(where):
    import mxl_char as MC
    import mxl_creator as C
    ch = MC.Character(G.app.character_file(), G.app.data)
    e = next((x for x in ch.inventory() if ('inv', x.it['x'], x.it['y']) == where), None)
    return None if e is None else C.decode_blob(bytes(e.blob), G.app.data)


@T.test
def drag_stash_jewel_onto_character_item():
    import mxl_undo
    inv = G.app.inventory
    if inv is None or inv.ch is None:
        T.skip('no character panel')
    T.select_tab('Stash')
    blob, gems = parent_blob(2)
    where = _char_place(blob)
    jkey = put_stash(loose(jewel_raw()))
    cpath = G.app.character_file()
    raw_s, raw_c = T.read(G.app.path), T.read(cpath)
    _drag_stash(jkey, T.panel_ev(where))
    no_error_boxes('stash -> character insert')
    rec, kids = _char_item(where)
    check_parent(rec, kids, gems + ['jew '], 'stash -> character insert')
    T.check(entry(jkey)[1] is None, 'the jewel is still in the stash')
    T.check(G.app._undo and G.app._undo[-1]['kind'] == 'files' and len(G.app._undo[-1]['files']) == 2,
            'no two-file undo step')
    mxl_undo.undo(G.app)
    T.pump(8)
    T.eq((T.read(G.app.path), T.read(cpath)), (raw_s, raw_c), 'both files after the undo')


@T.test
def drag_character_jewel_onto_character_item():
    import mxl_undo
    inv = G.app.inventory
    if inv is None or inv.ch is None:
        T.skip('no character panel')
    T.select_tab('Stash')
    blob, gems = parent_blob(2)
    where = _char_place(blob)
    jw = _char_place(loose(jewel_raw()))
    cpath = G.app.character_file()
    raw_c = T.read(cpath)
    src = T.panel_ev(jw)
    inv.on_press(src)
    dst = T.panel_ev(where)
    inv.on_drag(dst)
    inv.on_release(dst)
    T.pump(8)
    no_error_boxes('character -> character insert')
    rec, kids = _char_item(where)
    check_parent(rec, kids, gems + ['jew '], 'character -> character insert')
    T.check(_char_item(jw) is None, 'the jewel is still in the inventory')
    T.check(G.app._undo and G.app._undo[-1]['kind'] == 'files', 'no undo step')
    mxl_undo.undo(G.app)
    T.pump(8)
    T.eq(T.read(cpath), raw_c, 'character after the undo')


@T.test
def drag_character_jewel_onto_stash_item():
    inv = G.app.inventory
    if inv is None or inv.ch is None:
        T.skip('no character panel')
    T.select_tab('Stash')
    blob, gems = parent_blob(2)
    pkey = put_stash(blob)
    jw = _char_place(loose(jewel_raw()))
    dst = T.stash_ev(*pkey)
    inv.on_press(T.panel_ev(jw))
    inv.on_drag(dst)
    inv.on_release(dst)
    T.pump(8)
    no_error_boxes('character -> stash insert')
    (rec, kids), _it = entry(pkey)
    check_parent(rec, kids, gems + ['jew '], 'character -> stash insert')
    T.check(_char_item(jw) is None, 'the jewel is still in the inventory')
    T.check(G.app._undo and G.app._undo[-1]['kind'] == 'files', 'no undo step')


def chartab_drag(src, dst):
    """Character tab: drags the item at src onto dst (('inv', x, y) / ('slot', n))."""
    cw = T.chartab()
    a = T.chartab_ev(src)
    cw.on_press(a)
    b = T.chartab_ev(dst)
    cw.on_drag(b)
    cw.on_release(b)
    T.pump(8)


def open_chartab():
    import mxl_char_gui
    cw = T.chartab()
    if cw is None:
        mxl_char_gui.CharacterWindow(G.app, 'inventory')
        cw = T.chartab()
    T.select_tab('Character')
    if cw.tab.get() != 'inventory':
        cw.tab.set('inventory')
        cw.show_tab()
    cw.merc.set(False)
    cw.reload()
    T.pump(6)
    return cw


@T.test
def character_tab_drag_jewel_onto_item_and_full_refused():
    import mxl_undo
    blob, gems = parent_blob(2)
    where = _char_place(blob)
    jw = _char_place(loose(jewel_raw()))
    jw2 = _char_place(loose(jewel_raw()))
    cw = open_chartab()
    cpath = G.app.character_file()
    raw_c = T.read(cpath)
    chartab_drag(jw, where)
    no_error_boxes('Character tab insert')
    rec, kids = _char_item(where)
    check_parent(rec, kids, gems + ['jew '], 'Character tab insert')
    T.check(_char_item(jw) is None, 'the jewel is still in the inventory')
    T.check(G.app._undo and G.app._undo[-1]['kind'] == 'files', 'no undo step')
    raw1 = T.read(cpath)
    chartab_drag(jw2, where)                            # now full: refused, nothing written
    T.eq(T.read(cpath), raw1, 'character after a refused drop')
    T.check('no free socket' in cw.status.cget('text'), f'status: {cw.status.cget("text")!r}')
    mxl_undo.undo(G.app)
    T.pump(8)
    T.eq(T.read(cpath), raw_c, 'character after the undo')


T.main(globals())
