"""Vanilla profile in the window (MXL_GAME=vanilla): the Character tab's inventory is the game's 10 x 4 (from
inventory.bin), the "Stash / Cube / Belt" page shows the character file's personal stash (6 x 8), cube (3 x 4) and
belt; a mock (hacked clone) character with extreme stats opens. Copies of the vanilla / mock samples only.
Skipped without the vanilla install or the samples (see test 75)."""
import glob
import os
import shutil

import capytest as T

MODE = 'gui'
G = T.G
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')


def _src(name):
    cands = [os.path.join(T.REPO, '.cache', 'samples', name)]
    if os.sep + '.claude' + os.sep + 'worktrees' + os.sep in T.REPO:
        cands.append(os.path.join(T.REPO.split(os.sep + '.claude' + os.sep)[0], '.cache', 'samples', name))
    return next((c for c in cands if glob.glob(os.path.join(c, '*.d2s'))), None)


def _saves():
    v, m = _src('vanilla'), _src('mock')
    if not v or not m or not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        return None
    dst = T.guard(os.path.join(T.tmp(), 'vsaves'), 'vanilla save copies')
    if not os.path.isdir(dst):
        os.makedirs(dst)
        for f in glob.glob(os.path.join(v, '*.d2s')) + [os.path.join(m, 'clones', 'clone-26.d2s'),
                                                       os.path.join(m, 'clones', 'clone-35.d2s'),
                                                       os.path.join(m, 'clones', 'clone-59.d2s')]:
            shutil.copy(f, dst)
    return dst


_S = _saves()
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': GAME, **({'MXL_SAVE_DIR': _S} if _S else {})}
WAIT_TABS = True


def _open(name):
    T.check(_S is not None, 'vanilla samples')
    G.app.select_character(name, G.app.view.get())
    G.app.open_view(keep_page=True)
    T.pump(20, 0.02)
    cw = T.chartab()
    T.check(cw is not None, 'Character tab built')
    return cw


@T.test
def vanilla_inventory_and_containers():
    if _S is None:
        T.skip('no vanilla install / samples')
    import mxl_char
    import mxl_char_gui
    import mxl_profile
    T.check(mxl_profile.active() is not None, 'vanilla profile active')
    T.eq((mxl_char.INV_W, mxl_char.INV_H), (10, 4), 'inventory grid from inventory.bin')
    T.eq((mxl_char_gui.INV_W, mxl_char_gui.INV_H), (10, 4), 'Character window grid')
    g = mxl_profile.active()['grids']
    T.eq((g['stash'], g['cube']), ((6, 8), (3, 4)), 'stash / cube grids')
    cw = _open('complex')
    T.check(cw.ch is not None and cw.ch.name.lower() == 'complex', f'character opened: {getattr(cw.ch, "name", None)}')
    import mxl_vanilla_pages as VP
    boxes = {k: (c, r, len(es)) for k, _t, c, r, es in VP.containers(cw.ch, cw.data)}
    T.eq(boxes['stash'][:2], (6, 8), 'stash page grid')
    T.check(sum(b[2] for b in boxes.values()) > 0, f'containers hold items: {boxes}')
    page = cw.extra.get('containers')
    T.check(page is not None, 'Stash / Cube / Belt page built')
    cw.tab.set('containers')
    cw.show_tab()
    page.refresh()
    T.pump(6)
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        import mxl_tabs
        mxl_tabs._state['nb'].select(mxl_tabs._state['pages']['Character'])
        T.pump(10)
        os.system(f'import -window root {os.path.join(shot, "v77.png")} 2>/dev/null')
        mxl_tabs._state['nb'].select(mxl_tabs._state['pages']['Stash'])
        T.pump(10)
        os.system(f'import -window root {os.path.join(shot, "v77b.png")} 2>/dev/null')
    T.eq(sorted(page.canvases), ['belt', 'cube', 'inv', 'stash'], 'stash, cube, belt and the inventory')


@T.test
def main_window_stash_is_the_character_stash():
    """The main window's stash pane: the character file's personal stash in the game's grid, no page tabs / shared
    stash buttons, no '.stash not found'; read-only (app.path None: no stash writer runs); a click shows the item."""
    if _S is None:
        T.skip('no vanilla install / samples')
    import types
    import mxl_char
    import mxl_vanilla_pages as VP
    app = G.app
    cw = _open('complex')
    T.pump(10)
    T.check(app.path is None, f'no stash file: {app.path}')
    T.check(not app.notebook.master.winfo_ismapped(), 'page tabs / shared stash buttons hidden')
    ch = mxl_char.Character(app.character_file(), app.data)
    cols, rows, want = VP.stash_view(ch, app.data)
    T.eq((cols, rows), (6, 8), 'stash grid')
    T.check(len(want) > 0, 'the sample has stash items')
    T.eq(len(app.items), len(want), 'stash items shown')
    T.eq(sorted((i['x'], i['y'], i['code']) for i in app.items), sorted((i['x'], i['y'], i['code']) for i in want),
         'same items')
    c = app.cell
    T.eq((int(app.canvas.cget('width')), int(app.canvas.cget('height'))), (cols * c + 1, rows * c + 1), 'canvas size')
    T.check('.stash' not in app.status.cget('text'), f'status: {app.status.cget("text")!r}')
    it = app.items[0]
    ev = types.SimpleNamespace(x=it['x'] * c + c // 2, y=it['y'] * c + c // 2, x_root=0, y_root=0, widget=app.canvas)
    app.on_click(ev)
    T.pump(4)
    T.check(app.panel.item is it, 'clicked item shown in the detail panel')
    T.check(app.drag is None, 'no drag from the read-only stash')
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        import mxl_tabs
        mxl_tabs._state['nb'].select(mxl_tabs._state['pages']['Stash'])
        T.pump(10)
        os.system(f'import -window root {os.path.join(shot, "v77c.png")} 2>/dev/null')


@T.test
def mock_character_opens():
    if _S is None:
        T.skip('no vanilla install / samples')
    cw = _open('clone-26')
    T.check(cw.ch is not None and os.path.basename(cw.ch.path) == 'clone-26.d2s', 'hacked clone character opened')
    T.check(any(getattr(e.it, 'ear', None) for e in cw.ch.items), 'player ears read')


@T.test
def extreme_characters_open_clean():
    """Mana / life near the stat maximum, junk after the stat list: the window shows them with nothing pending
    (a SAVE without edits writes nothing new)."""
    if _S is None:
        T.skip('no vanilla install / samples')
    for name in ('clone-35', 'clone-59'):          # clone-59: a 1.09 save (version 92)
        cw = _open(name)
        T.check(cw.ch is not None and os.path.basename(cw.ch.path) == name + '.d2s', f'{name} opened')
        T.check(not cw.dirty(), f'{name}: nothing pending after loading')


@T.test
def character_tab_drag_gem_into_free_socket():
    """1.14d: a gem dragged onto an inventory item with a free socket goes into it (mxl_socket_insert, the
    Character tab's drop); the gem leaves the inventory, the socketed-item count grows, Ctrl+Z undoes it."""
    if _S is None:
        T.skip('no vanilla install / samples')
    import mxl_creator as C
    import mxl_save
    import mxl_undo
    cw = _open('complex')
    cw.tab.set('inventory')
    cw.show_tab()
    cw.merc.set(False)
    T.pump(4)
    d = cw.data
    cr = C.Creator(d)
    gem = next(c for c, _n in cr.sockets_fillers())
    base = next((b for b in cr.bases() if b.kind == 'weapons' and b.size[1] <= 3
                 and cr.max_sockets(b.code, C.MAX_ILVL) >= 2), None)
    if base is None:
        T.skip('no weapon base with 2 sockets')
    spec = cr.new_spec('normal', base.code)
    spec['ilvl'] = C.MAX_ILVL
    spec['sockets'] = 2
    spec['socketed'] = [gem]
    blob = bytes(cr.build(spec)[0])
    kid = C.Creator._split(blob, d)[1][0]
    gem_blob = C.encode_item(dict(C.decode_item(kid, d)[0], location=0, equipped=0, x=0, y=0, panel=1), d)
    for x in list(cw.ch.inventory()):                  # room for the test items (a copy of the sample)
        cw.ch.remove(x, False)
    spots = []
    for b in (blob, gem_blob):
        spot = cw.ch.free_inventory_spot(mxl_save.blob_item(b, d))
        if spot is None:
            T.skip('inventory full')
        cw.ch.place(b, ('inv', spot[0], spot[1]), False)
        spots.append(('inv', spot[0], spot[1]))
    T.check(cw.save('test items placed'), 'test items not saved')
    T.pump(4)
    raw0 = T.read(cw.ch.path)
    a, b = T.chartab_ev(spots[1]), T.chartab_ev(spots[0])
    cw.on_press(a)
    cw.on_drag(b)
    cw.on_release(b)
    T.pump(8)
    T.check(T.read(cw.ch.path) != raw0, f'nothing written: {cw.status.cget("text")!r}')
    e = next(x for x in cw.ch.inventory() if ('inv', x.it['x'], x.it['y']) == spots[0])
    rec, kids = C.decode_blob(bytes(e.blob), d)
    T.eq([k['code'] for k in kids], [gem, gem], 'children of the item')
    T.eq(rec.get('socketed_count'), 2, 'socketed-item count')
    T.check(not any(('inv', x.it['x'], x.it['y']) == spots[1] for x in cw.ch.inventory()), 'the gem is still loose')
    mxl_undo.undo(G.app)
    T.pump(8)
    T.eq(T.read(cw.ch.path), raw0, 'character after the undo')


T.main(globals())
