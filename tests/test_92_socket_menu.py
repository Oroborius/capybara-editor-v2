"""The item right-click menu's "Socket" submenu (mxl_socket_menu): Add Sockets (N) / Remove Sockets / Unsocket.
- engine: N comes from the game folder's tables (Creator.max_sockets: the base's gemsockets capped by the itemtype's
  MaxSock1 / 25 / 40 at the item's level; 1.14d: 7 on the user's rule types), the three results, no-room refusal;
- Median (stash grid, the Stash tab's character panel): the menu only on items that can have sockets, the results
  on disk, one undo step each (Ctrl+Z gives the bytes back), Unsocket refused when the stash has no room;
- 1.14d (variant 'vanilla', the Character tab): Add Sockets gives 7 (field + item_numsockets 194), Unsocket puts
  the socketed items into the character's own stash (panel 5), undo.
The Median parent is test_91's: a unique 2x2 armor with 3 sockets and two gems built by the creator."""
import glob
import os
import shutil

import capytest as T

MODE = 'gui'
VARIANTS = {
    'd2': {'MXL_THEME': 'd2'},
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
    'he-800x600': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0'},
    'vanilla': {'MXL_THEME': 'd2', 'CAPY92_VANILLA': '1'},
}
G = T.G
VANILLA = bool(os.environ.get('CAPY92_VANILLA'))
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')


def _src(name):
    cands = [os.path.join(T.REPO, '.cache', 'samples', name)]
    if os.sep + '.claude' + os.sep + 'worktrees' + os.sep in T.REPO:
        cands.append(os.path.join(T.REPO.split(os.sep + '.claude' + os.sep)[0], '.cache', 'samples', name))
    return next((c for c in cands if glob.glob(os.path.join(c, '*.d2s'))), None)


def _saves():
    v = _src('vanilla')
    if not v or not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        return None
    dst = T.guard(os.path.join(T.tmp(), 'vsaves92'), 'vanilla save copies')
    if not os.path.isdir(dst):
        os.makedirs(dst)
        for f in glob.glob(os.path.join(v, '*.d2s')):
            shutil.copy(f, dst)
    return dst


_S = _saves() if VANILLA else None
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': GAME, **({'MXL_SAVE_DIR': _S} if _S else {})} if VANILLA else {}


def median():
    import mxl_profile
    if VANILLA or not mxl_profile.is_median():
        T.skip('Median XL profile only')
    T.reset()


def vanilla():
    if not VANILLA:
        T.skip('1.14d profile only (variant vanilla)')
    if _S is None:
        T.skip('no vanilla install / samples')


def parent_blob(n_gems=2, sockets=3):
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
    spec['sockets'] = sockets
    spec['socketed'] = gems[:n_gems]
    blob, _rec = cr.build(spec)
    return bytes(blob), gems[:n_gems]


def gem_loose():
    import mxl_creator as C
    d = G.app.data
    blob, _g = parent_blob(1)
    kid = C.Creator._split(blob, d)[1][0]
    return C.encode_item(dict(C.decode_item(kid, d)[0], location=0, equipped=0, x=0, y=0, panel=5), d)


def put_stash(blob):
    import mxl_save
    d = G.app.data
    items = mxl_save.parse_stash(G.app.path, d)
    pages = [G.app.page()] + [p for p in range(mxl_save.STASH_PAGES) if p != G.app.page()]
    spot = mxl_save.free_spot(items, mxl_save.blob_item(blob, d), d, pages)
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


def socket_labels(m):
    """Labels inside the 'Socket' cascade of a captured menu (None: no such cascade)."""
    out, inside, base = None, False, None
    for d, lab, st, mm, i in T.menu_entries(m):
        if mm.type(i) == 'cascade' and lab == 'Socket':
            out, inside, base = [], True, d
            continue
        if inside and d <= base:
            inside = False
        if inside:
            out.append((lab, st))
    return out


def undo_to(paths_raw, what):
    import mxl_undo
    T.check(G.app._undo and G.app._undo[-1]['kind'] == 'files', f'{what}: no undo step')
    mxl_undo.undo(G.app)
    T.pump(8)
    for p, raw in paths_raw:
        T.eq(T.read(p), raw, f'{what}: {os.path.basename(p)} after the undo')


# ------------------------------------------------------------------------------------------------ engine
@T.test
def engine_n_from_the_game_tables():
    """N is the base's gemsockets capped by its itemtype's MaxSock band at the item's level, per profile."""
    import mxl_creator as C
    import mxl_socket_menu as SM
    d = G.app.data
    cr = C.Creator(d)
    seen = 0
    for b in cr.bases():
        base = d.base(b.code)
        if not base.max_sockets or base.type < 0:
            continue
        ms = cr.t.itype[base.type]['maxsock']
        for ilvl in (1, 30, 99):
            rec = dict(flags=0, ilvl=ilvl)
            want = min(base.max_sockets, ms[0] if ilvl <= 25 else ms[1] if ilvl <= 40 else ms[2])
            if VANILLA and cr.type_codes(b.code) & C.Creator.VANILLA_SOCKET_TYPES:
                want = max(want, 7)
            T.eq(SM.max_sockets(cr, b.code, rec), min(want, 7), f'N of {b.code} at ilvl {ilvl}')
            seen += 1
    T.check(seen > 20, 'socketable bases checked')
    if VANILLA:
        boots = next((b for b in cr.bases() if 'boot' in cr.type_codes(b.code)), None)
        T.check(boots is not None, 'a boots base in the 1.14d tables')
        if boots is not None:
            T.check(SM.max_sockets(cr, boots.code, dict(flags=0, ilvl=99)) == cr.max_sockets(boots.code, 99) < 7,
                    'boots keep the data value (no 7-socket rule)')


@T.test
def engine_add_remove_unsocket():
    median()
    import mxl_creator as C
    import mxl_socket_menu as SM
    d = G.app.data
    cr = C.Creator(d)
    blob, gems = parent_blob(2)
    code = C.decode_item(blob, d)[0]['code']
    n = SM.max_sockets(cr, code, C.decode_item(blob, d)[0])
    if n > 3:
        new, got = SM.with_max(blob, d, cr, code)
        rec, kids = C.decode_blob(new, d)
        T.eq((got, rec['sockets'], [k['code'] for k in kids]), (n, n, gems), 'add: N sockets, gems kept')
    new, gone = SM.without(blob, d)
    rec, kids = C.decode_blob(new, d)
    T.check(not rec['flags'] & C.FLAG_SOCKETED and not kids and gone == 2, 'remove: no sockets, no children')
    parent, loose = SM.emptied(blob, d)
    rec, kids = C.decode_blob(parent, d)
    T.eq((rec['sockets'], rec.get('socketed_count'), kids), (3, 0, []), 'unsocket: sockets kept, emptied')
    T.eq([C.decode_item(b, d)[0]['code'] for b in loose], gems, 'unsocket: the gems as loose items')
    T.eq({C.decode_item(b, d)[0]['location'] for b in loose}, {0}, 'loose items stored')
    # no room: a stash whose every cell is taken
    import mxl_save
    full = [dict(code=gems[0], page=p, x=x, y=y) for p in range(mxl_save.STASH_PAGES)
            for x in range(mxl_save.STASH_COLS) for y in range(mxl_save.STASH_ROWS)]
    T.eq(SM.stash_spots(full, loose, d, list(range(mxl_save.STASH_PAGES))), None, 'no room: refused')


# ------------------------------------------------------------------------------------------------ Median GUI
@T.test
def stash_menu_only_on_socketable_items():
    median()
    import mxl_creator as C
    blob, _g = parent_blob(2)
    pkey = put_stash(blob)
    gkey = put_stash(gem_loose())
    T.check(socket_labels(T.stash_menu(*gkey)) is None, 'Socket menu on a gem')
    labs = socket_labels(T.stash_menu(*pkey))
    T.check(labs is not None, 'no Socket menu on a socketed armor')
    cr = C.Creator(G.app.data)
    rec = C.decode_item(blob, G.app.data)[0]
    n = min(cr.max_sockets(rec['code'], rec['ilvl']), 7)
    T.eq(labs[0], (f'Add Sockets ({n})', 'disabled' if n <= 3 else 'normal'), 'Add Sockets entry')
    T.eq([lab for lab, _s in labs[1:]], ['Remove Sockets', 'Unsocket'], 'entries')


@T.test
def stash_add_remove_unsocket_and_undo():
    median()
    import mxl_creator as C
    import mxl_save
    d = G.app.data
    blob, gems = parent_blob(2)
    pkey = put_stash(blob)
    raw0 = T.read(G.app.path)
    rec0 = C.decode_item(blob, d)[0]
    n = min(C.Creator(d).max_sockets(rec0['code'], rec0['ilvl']), 7)
    if n > 3:
        T.invoke(T.stash_menu(*pkey), 'Add Sockets', under='Socket')
        (rec, kids), _it = entry(pkey)
        T.eq((rec['sockets'], [k['code'] for k in kids]), (n, gems), 'added: N sockets, gems kept')
        undo_to([(G.app.path, raw0)], 'add')
    T.invoke(T.stash_menu(*pkey), 'Remove Sockets', under='Socket')
    (rec, kids), _it = entry(pkey)
    T.check(not rec['flags'] & C.FLAG_SOCKETED and not kids, 'removed: sockets / gems still there')
    undo_to([(G.app.path, raw0)], 'remove')
    before = mxl_save.parse_stash(G.app.path, d)
    T.invoke(T.stash_menu(*pkey), 'Unsocket', under='Socket')
    (rec, kids), _it = entry(pkey)
    T.eq((rec['sockets'], rec.get('socketed_count'), kids), (3, 0, []), 'unsocketed parent')
    after = mxl_save.parse_stash(G.app.path, d)
    new = [i for i in after if (i['page'], i['x'], i['y']) not in {(b['page'], b['x'], b['y']) for b in before}]
    T.eq(sorted(i['code'] for i in new), sorted(gems), 'the gems are loose in the stash')
    T.eq({i['page'] for i in new}, {pkey[0]}, 'the gems on the shown page')
    undo_to([(G.app.path, raw0)], 'unsocket')
    # always exercised: a 2-socket copy with one gem grows to N
    b2, g2 = parent_blob(1, sockets=2)
    k2 = put_stash(b2)
    raw2 = T.read(G.app.path)
    T.invoke(T.stash_menu(*k2), f'Add Sockets ({n})', under='Socket')
    (rec, kids), _it = entry(k2)
    T.eq((rec['sockets'], rec.get('socketed_count'), [k['code'] for k in kids]), (n, 1, g2), 'added to 2 sockets')
    undo_to([(G.app.path, raw2)], 'add to 2 sockets')


@T.test
def unsocket_refused_without_room():
    median()
    import mxl_socket_menu as SM
    blob, _g = parent_blob(2)
    pkey = put_stash(blob)
    raw0 = T.read(G.app.path)
    orig = SM.free_spot
    SM.free_spot = lambda *a, **k: None                # the stash has no free place left
    try:
        T.invoke(T.stash_menu(*pkey), 'Unsocket', under='Socket')
    finally:
        SM.free_spot = orig
    T.eq(T.read(G.app.path), raw0, 'the stash after a refused Unsocket')
    T.check('not enough free room' in T.status_text(), f'status: {T.status_text()!r}')


@T.test
def character_item_unsocket_to_stash_and_undo():
    median()
    import mxl_char as MC
    import mxl_creator as C
    import mxl_save
    inv = G.app.inventory
    if inv is None or inv.ch is None:
        T.skip('no character panel')
    T.select_tab('Stash')
    d = G.app.data
    blob, gems = parent_blob(2)
    path = G.app.character_file()
    ch = MC.Character(path, d)
    spot = ch.free_inventory_spot(mxl_save.blob_item(blob, d))
    if spot is None:
        T.skip('inventory full')
    where = ('inv', spot[0], spot[1])
    ch.place(blob, where, False)
    ch.save(backup=False)
    inv.merc.set(False)
    inv.refresh(force=True)
    T.pump(6)
    raw_s, raw_c = T.read(G.app.path), T.read(path)
    n_s = len(mxl_save.parse_stash(G.app.path, d))
    T.invoke(T.panel_menu(where), 'Unsocket', under='Socket')
    e = next(x for x in MC.Character(path, d).inventory() if ('inv', x.it['x'], x.it['y']) == where)
    rec, kids = C.decode_blob(bytes(e.blob), d)
    T.eq((rec['sockets'], kids), (3, []), 'character item emptied, sockets kept')
    T.eq(len(mxl_save.parse_stash(G.app.path, d)) - n_s, len(gems), 'gems in the stash')
    T.eq(len(G.app._undo[-1]['files']), 2, 'one undo step over stash + character')
    undo_to([(G.app.path, raw_s), (path, raw_c)], 'character unsocket')
    T.invoke(T.panel_menu(where), 'Remove Sockets', under='Socket')
    e = next(x for x in MC.Character(path, d).inventory() if ('inv', x.it['x'], x.it['y']) == where)
    rec, kids = C.decode_blob(bytes(e.blob), d)
    T.check(not rec['flags'] & C.FLAG_SOCKETED and not kids, 'character item: sockets removed')
    undo_to([(path, raw_c)], 'character remove')


# ------------------------------------------------------------------------------------------------ 1.14d
def _vanilla_char():
    import mxl_creator as C
    import mxl_save
    G.app.select_character('complex', G.app.view.get())
    G.app.open_view(keep_page=True)
    T.pump(20, 0.02)
    cw = T.chartab()
    T.check(cw is not None, 'Character tab built')
    cw.tab.set('inventory')
    cw.show_tab()
    cw.merc.set(False)
    T.pump(4)
    d = cw.data
    cr = C.Creator(d)
    gem = next(c for c, _n in cr.sockets_fillers())
    base = next((b for b in cr.bases() if b.kind == 'weapons' and b.size[1] <= 3
                 and 2 <= cr.max_sockets(b.code, C.MAX_ILVL) < 7), None)
    if base is None:
        T.skip('no weapon base with 2 sockets')
    spec = cr.new_spec('normal', base.code)
    spec['ilvl'] = C.MAX_ILVL
    spec['sockets'] = 2
    spec['socketed'] = [gem, gem]
    blob = bytes(cr.build(spec)[0])
    for x in list(cw.ch.inventory()):                  # room for the test item (a copy of the sample)
        cw.ch.remove(x, False)
    spot = cw.ch.free_inventory_spot(mxl_save.blob_item(blob, d))
    cw.ch.place(blob, ('inv', spot[0], spot[1]), False)
    T.check(cw.save('test item placed'), 'test item not saved')
    T.pump(4)
    return cw, ('inv', spot[0], spot[1]), gem, cr.max_sockets(base.code, C.MAX_ILVL)


def _vitem(cw, where):
    import mxl_creator as C
    e = next(x for x in cw.ch.inventory() if ('inv', x.it['x'], x.it['y']) == where)
    return C.decode_blob(bytes(e.blob), cw.data)


@T.test
def vanilla_add_sockets_gives_seven_and_undo():
    vanilla()
    import mxl_socket_insert as SI
    cw, where, gem, field = _vanilla_char()
    raw0 = T.read(cw.ch.path)
    labs = socket_labels(T.chartab_menu(where))
    T.check(labs is not None and labs[0] == ('Add Sockets (7)', 'normal'), f'Socket menu: {labs}')
    T.invoke(T.chartab_menu(where), 'Add Sockets', under='Socket')
    rec, kids = _vitem(cw, where)
    T.eq(SI.socket_total(rec), 7, 'sockets in all (field + 194)')
    T.eq(rec['sockets'], field, 'save field: the base\'s sockets')
    T.eq([s['value'] for s in rec['stats'] if s['id'] == 194], [7 - field], 'item_numsockets')
    T.eq([k['code'] for k in kids], [gem, gem], 'gems kept')
    undo_to([(cw.ch.path, raw0)], '1.14d add')


@T.test
def vanilla_unsocket_into_personal_stash_and_undo():
    vanilla()
    cw, where, gem, _f = _vanilla_char()
    raw0 = T.read(cw.ch.path)
    n5 = sum(1 for e in cw.ch.items if e.it.get('location') == 0 and e.it.get('panel') == 5)
    T.invoke(T.chartab_menu(where), 'Unsocket', under='Socket')
    rec, kids = _vitem(cw, where)
    T.eq((rec['sockets'], kids), (2, []), 'emptied, sockets kept')
    stash = [e for e in cw.ch.items if e.it.get('location') == 0 and e.it.get('panel') == 5]
    T.eq(len(stash) - n5, 2, 'the gems in the personal stash')
    undo_to([(cw.ch.path, raw0)], '1.14d unsocket')
    T.invoke(T.chartab_menu(where), 'Remove Sockets', under='Socket')
    rec, kids = _vitem(cw, where)
    T.check(not kids and not rec.get('sockets') and not [s for s in rec['stats'] if s['id'] == 194],
            '1.14d: sockets removed')
    undo_to([(cw.ch.path, raw0)], '1.14d remove')



@T.test
def vanilla_menu_only_on_socketable_items():
    vanilla()
    import mxl_creator as C
    import mxl_save
    cw, where, _gem, _f = _vanilla_char()
    d = cw.data
    cr = C.Creator(d)
    kid = C.Creator._split(bytes(cw.ch.stash_blob(_ventry(cw, where))), d)[1][0]
    loose = [C.encode_item(dict(C.decode_item(kid, d)[0], location=0, equipped=0, x=0, y=0, panel=1), d)]
    boots = next((b for b in cr.bases() if 'boot' in cr.type_codes(b.code)), None)
    if boots is not None:
        spec = cr.new_spec('normal', boots.code)
        spec['ilvl'] = C.MAX_ILVL
        loose.append(bytes(cr.build(spec)[0]))
    spots = []
    for b in loose:
        spot = cw.ch.free_inventory_spot(mxl_save.blob_item(b, d))
        if spot is None:
            T.skip('inventory full')
        cw.ch.place(b, ('inv', spot[0], spot[1]), False)
        spots.append(('inv', spot[0], spot[1]))
    T.check(cw.save('test items placed'), 'test items not saved')
    T.pump(4)
    T.check(socket_labels(T.chartab_menu(spots[0])) is None, 'Socket menu on a gem')
    if boots is not None:
        T.check(socket_labels(T.chartab_menu(spots[1])) is None, 'Socket menu on 1.14d boots (no sockets in the data)')


@T.test
def vanilla_unsocket_refused_without_room():
    vanilla()
    import mxl_socket_menu as SM
    cw, where, gem, _f = _vanilla_char()
    raw0 = T.read(cw.ch.path)
    ch = cw.ch
    orig = SM._personal_stash_free
    SM._personal_stash_free = lambda ch, data: (0, 0, set())
    ch.free_inventory_spot = lambda it: None
    try:
        T.invoke(T.chartab_menu(where), 'Unsocket', under='Socket')
    finally:
        SM._personal_stash_free = orig
        ch.__dict__.pop('free_inventory_spot', None)
    T.pump(4)
    T.eq(T.read(cw.ch.path), raw0, 'the character after a refused Unsocket')
    T.check('not enough free room' in cw.status.cget('text'), f"status: {cw.status.cget('text')!r}")
    _rec, kids = _vitem(cw, where)
    T.eq([k['code'] for k in kids], [gem, gem], 'the gems are still socketed (in memory too)')


def _ventry(cw, where):
    return next(x for x in cw.ch.inventory() if ('inv', x.it['x'], x.it['y']) == where)



# ------------------------------------------------------------------- 1.14d: Stash / Cube / Belt page
def _vbuild(cr, sockets, n_gems):
    import mxl_creator as C
    gem = next(c for c, _n in cr.sockets_fillers())
    base = next((b for b in cr.bases() if b.kind == 'weapons' and b.size[0] <= 2 and b.size[1] <= 3
                 and sockets <= cr.max_sockets(b.code, C.MAX_ILVL) < 7), None)
    if base is None:
        T.skip(f'no 2 x 3 weapon base with {sockets} sockets')
    spec = cr.new_spec('normal', base.code)
    spec['ilvl'] = C.MAX_ILVL
    spec['sockets'] = sockets
    spec['socketed'] = [gem] * n_gems
    return bytes(cr.build(spec)[0]), gem


def _vfree(ch, panel, blob, skip=()):
    import mxl_save
    it = mxl_save.blob_item(blob, ch.data)
    for y in range(12):
        for x in range(12):
            if (x, y) not in skip and ch.stored_error(it, panel, x, y) is None:
                return ('store', panel, x, y)
    T.skip(f'panel {panel} full')


def _vpage(cw):
    cw.tab.set('containers')
    cw.show_tab()
    page = cw.extra.get('containers')
    T.check(page is not None, 'Stash / Cube / Belt page built')
    page.refresh()
    T.pump(4)
    return page


def _pev(page, key, gx, gy):
    c = page.cell
    return T.ev(page.canvases[key], (gx + .5) * c, (gy + .5) * c)


def _pkey(where):
    return ('inv', where[1], where[2]) if where[0] == 'inv' else ({4: 'cube', 5: 'stash'}[where[1]], where[2], where[3])


def _pdrag(page, src, dst):
    page.on_press(src[0], _pev(page, *src))
    b = _pev(page, *dst)
    page.on_drag(b)
    page.on_release(b)
    T.pump(6)


def _pat(cw, where):
    import mxl_char as MC
    import mxl_creator as C
    e = next((x for x in cw.ch.items if MC.where_of(x) == where), None)
    return (e, C.decode_blob(bytes(e.blob), cw.data)) if e is not None else (None, None)


@T.test
def vanilla_page_moves_stash_cube_inventory_and_undo():
    vanilla()
    cw, where, gem, _f = _vanilla_char()
    page = _vpage(cw)
    T.eq(sorted(page.canvases), ['belt', 'cube', 'inv', 'stash'], 'grids of the page')
    blob = bytes(cw.ch.stash_blob(_ventry(cw, where)))
    path = cw.ch.path
    raw0 = T.read(path)
    st = _vfree(cw.ch, 5, blob)
    _pdrag(page, _pkey(where), _pkey(st))
    e, _r = _pat(cw, st)
    T.check(e is not None and _pat(cw, where)[0] is None, 'inventory -> stash: moved')
    raw1 = T.read(path)
    T.check(raw1 != raw0, 'inventory -> stash written')
    cb = _vfree(cw.ch, 4, blob)
    _pdrag(page, _pkey(st), _pkey(cb))
    e, (rec, kids) = _pat(cw, cb)
    T.check(e is not None and _pat(cw, st)[0] is None, 'stash -> cube: moved')
    T.eq([k['code'] for k in kids], [gem, gem], 'socketed items move with it')
    _pdrag(page, _pkey(cb), _pkey(where))
    T.check(_pat(cw, where)[0] is not None and _pat(cw, cb)[0] is None, 'cube -> inventory: moved')
    T.eq(T.read(path), raw0, 'back where it was: byte-identical')
    import mxl_undo
    mxl_undo.undo(G.app)
    T.pump(8)
    undo_to([(path, raw1)], 'cube move undone, then stash -> cube')
    undo_to([(path, raw0)], 'inventory -> stash')
    _pdrag(page, _pkey(where), ('belt', 0, 0))
    T.eq(T.read(path), raw0, 'a drop on the belt writes nothing')
    T.check('belt' in page.status.cget('text'), f"belt drop status: {page.status.cget('text')!r}")
    T.check(not [b for b in G.boxes if b[0] == 'showerror'], f'error boxes: {G.boxes}')


@T.test
def vanilla_page_socket_drop_and_menu_keep_the_stash_place():
    vanilla()
    import mxl_creator as C
    import mxl_save
    import mxl_socket_insert as SI
    cw, where, _g, _f = _vanilla_char()
    d = cw.data
    cr = C.Creator(d)
    parent, gem = _vbuild(cr, 3, 1)
    st = _vfree(cw.ch, 5, parent)
    cw.ch.place(parent, st, False)
    loose = C.Creator._split(parent, d)[1][0]
    loose = C.encode_item(dict(C.decode_item(loose, d)[0], location=0, equipped=0, x=0, y=0, panel=4), d)
    cb = _vfree(cw.ch, 4, loose)
    cw.ch.place(loose, cb, False)
    T.check(cw.save('test items placed'), 'test items not saved')
    T.pump(4)
    page = _vpage(cw)
    path = cw.ch.path
    raw0 = T.read(path)
    _pdrag(page, _pkey(cb), _pkey(st))
    e, (rec, kids) = _pat(cw, st)
    T.check(e is not None, 'the parent stays in the stash at its place')
    T.eq([k['code'] for k in kids], [gem, gem], 'cube gem socketed into the stash item')
    T.check(_pat(cw, cb)[0] is None, 'the gem left the cube')
    undo_to([(path, raw0)], 'socket drop on the stash page')
    G.menu = None
    page.on_menu('stash', _pev(page, 'stash', st[2], st[3]))
    T.pump(2)
    labs = socket_labels(G.menu)
    T.check(labs is not None and labs[0] == ('Add Sockets (7)', 'normal'), f'page Socket menu: {labs}')
    T.invoke(G.menu, 'Add Sockets', under='Socket')
    e, (rec, kids) = _pat(cw, st)
    T.check(e is not None, 'Add Sockets: still in the stash at its place')
    T.eq(SI.socket_total(rec), 7, 'sockets in all')
    undo_to([(path, raw0)], 'Add Sockets on the stash page')
    G.menu = None
    page.on_menu('stash', _pev(page, 'stash', st[2], st[3]))
    T.pump(2)
    T.invoke(G.menu, 'Unsocket', under='Socket')
    e, (rec, kids) = _pat(cw, st)
    T.check(e is not None and not kids, 'Unsocket: emptied in place')
    undo_to([(path, raw0)], 'Unsocket on the stash page')
    T.check(not [b for b in G.boxes if b[0] == 'showerror'], f'error boxes: {G.boxes}')


@T.test
def vanilla_page_item_menu_edit_delete_paste_keep_places_and_undo():
    vanilla()
    import mxl_creator as C
    import mxl_tabs
    cw, _w, _g, _f = _vanilla_char()
    d = cw.data
    cr = C.Creator(d)
    parent, _gem = _vbuild(cr, 3, 1)
    other, _gem = _vbuild(cr, 2, 0)
    for x in [x for x in cw.ch.items if x.it.get('location') == 0 and x.it.get('panel') in (4, 5)]:
        cw.ch.remove(x, False)                         # room in the stash and the cube (a copy of the sample)
    st = _vfree(cw.ch, 5, parent)
    cw.ch.place(parent, st, False)
    cb = _vfree(cw.ch, 4, parent)
    cw.ch.place(parent, cb, False)
    T.check(cw.save('test items placed'), 'test items not saved')
    T.pump(4)
    page = _vpage(cw)
    path = cw.ch.path
    raw0 = T.read(path)

    def menu(key, gx, gy):
        G.menu = None
        page.on_menu(key, _pev(page, key, gx, gy))
        T.pump(2)
        T.check(G.menu is not None, f'no menu on {key} {gx},{gy}')
        return G.menu
    labs = T.menu_labels(menu('stash', st[2], st[3]))
    for want in ('Edit item', 'Item stats', 'Duplicate', 'Copy', 'Cut', 'Socket', 'To inventory',
                 'To Horadric Cube', 'Delete', 'Export item', 'Open in Bit editor', 'Add to library'):
        T.check(any(str(l).startswith(want) for l in labs), f'stash menu has {want!r}: {labs}')
    T.check(not any(str(l).startswith('To stash') for l in labs), f'no To stash on a stash item: {labs}')
    # Edit: the editor's write puts the new bytes at the stash / cube place
    for key, where in (('stash', st), ('cube', cb)):
        T.invoke(menu(key, where[2], where[3]), 'Edit item')
        T.pump(6)
        w = mxl_tabs.built_owner('Creator')
        T.check(w is not None and w.edit_item is not None and w.target is not None, 'the Item Editor did not open')
        w.target(other)
        T.pump(4)
        e, (rec, kids) = _pat(cw, where)
        T.check(e is not None and not kids and e.it['code'] == C.decode_item(other, d)[0]['code'],
                f'edit of the {key} item: replaced at its place')
        undo_to([(path, raw0)], f'edit on the {key} item')
    # Delete (the cube item) and undo
    T.invoke(menu('cube', cb[2], cb[3]), 'Delete')
    T.pump(4)
    T.check(_pat(cw, cb)[0] is None and _pat(cw, st)[0] is not None, 'cube item deleted, stash item kept')
    undo_to([(path, raw0)], 'delete on the cube item')
    # Copy the stash item, paste into an empty cube cell: placed at that cell
    T.invoke(menu('stash', st[2], st[3]), 'Copy')
    T.check(getattr(G.app, '_capy_clip', None) is not None, 'copied')
    empty = _vfree(cw.ch, 5, parent)
    T.invoke(menu('stash', empty[2], empty[3]), 'Paste here')
    T.pump(4)
    T.check(_pat(cw, empty)[0] is not None and _pat(cw, st)[0] is not None, 'pasted into the clicked stash cell')
    undo_to([(path, raw0)], 'paste into the stash')
    # Copy the edited-looking other item over the cube item: replaced at the cube place
    G.app._capy_clip = (other, 'other')
    T.invoke(menu('cube', cb[2], cb[3]), 'Paste (replaces')
    T.pump(4)
    e, (rec, kids) = _pat(cw, cb)
    T.check(e is not None and not kids, 'paste over the cube item: replaced at its place')
    undo_to([(path, raw0)], 'paste over the cube item')
    # Move to inventory and undo
    T.invoke(menu('stash', st[2], st[3]), 'To inventory')
    T.pump(4)
    T.check(_pat(cw, st)[0] is None, 'stash item moved out')
    undo_to([(path, raw0)], 'move to the inventory')
    T.check(not [b for b in G.boxes if b[0] == 'showerror'], f'error boxes: {G.boxes}')

T.main(globals())
