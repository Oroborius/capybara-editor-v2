"""Save safety follow-ups: the newest N backups per file are kept (setting "backups_keep", default 5, at least 1;
docs/review/save-safety.md F10), and Ctrl+Z (mxl_undo 'files') undoes a drag move (stash page -> other page,
stash -> inventory: both files byte for byte) and a SAVE of the Character tab; an undo is refused when a file
changed since."""
import glob
import os

import capytest as T

MODE = 'gui'
RESET = True
ALLOW_ERRORS = True
G = T.G


def no_traceback(m):
    for e in T.errors_since(m):
        T.check('Traceback' not in e and 'Exception in Tkinter' not in e, 'traceback: ' + e)


def _setting(value):
    import settings
    settings.put('backups_keep', value)


def _dated(path):
    import mxl_savecheck
    return [os.path.basename(f) for _k, f in mxl_savecheck._dated(path)]


# ------------------------------------------------------------------------------------------- backups
@T.test
def save_safety_keeps_the_newest_five_backups():
    import mxl_save
    path = G.app.character_file()
    stash = G.app.path
    for f in glob.glob(glob.escape(path) + '.bak-*') + glob.glob(glob.escape(stash) + '.bak-*'):
        os.remove(f)
    base = os.path.basename(path)
    seeds = [f'{base}.bak-2020010{d}-120000' for d in range(1, 6)] + [f'{base}.bak-20200106-120000-2',
                                                                       f'{base}.bak-20200106-120000-10']
    others = [f'{base}.bak-savecheck-20190101-000000', os.path.basename(stash) + '.bak-20190101-000000',
              f'{base}.bak-before-restore-20190101-000000']
    folder = os.path.dirname(path)
    for n in seeds + others:
        with open(os.path.join(folder, n), 'wb') as f:
            f.write(b'x')
    raw = T.read(path)
    try:
        _setting(None)
        bak = mxl_save.commit_file(path, raw, lambda tmp: None, True)      # the collector's writer: its backup
        T.check(bak and os.path.isfile(bak), f'no backup returned: {bak!r}')
        T.eq(T.read(bak) if bak else None, raw, 'the backup holds the file before the write')
        now = _dated(path)
        # numeric order of -n: -10 is newer than -2; the oldest three seeds are gone
        T.eq(now, seeds[3:5] + [seeds[5], seeds[6], os.path.basename(bak)], 'kept backups (default 5)')
        for n in others:
            T.check(os.path.isfile(os.path.join(folder, n)), f'{n} was removed')
        _setting(2)
        bak2 = mxl_save.commit_file(path, raw, lambda tmp: None, True)
        T.eq(_dated(path), [os.path.basename(bak), os.path.basename(bak2)], 'kept backups (backups_keep 2)')
        _setting(0)
        bak3 = mxl_save.commit_file(path, raw, lambda tmp: None, True)
        T.eq(_dated(path), [os.path.basename(bak3)], 'kept backups (backups_keep 0 -> 1)')
        for n in others:
            T.check(os.path.isfile(os.path.join(folder, n)), f'{n} was removed')
        T.eq(T.read(path), raw, 'the file itself')
    finally:
        _setting(None)


# ------------------------------------------------------------------------------------------- drag moves
def _small_item():
    app = G.app
    it = next((i for i in sorted(app.items, key=lambda i: (i['page'], i['y'], i['x']))
               if app.data.base(i['code']).size == (1, 1)), None)
    if it is None:
        T.skip('no 1x1 stash item')
    return it


def _other_page_spot(it):
    import mxl_save
    app = G.app
    items = mxl_save.parse_stash(app.path, app.data)
    for p in range(mxl_save.STASH_PAGES):
        if p == it['page']:
            continue
        spot = mxl_save.free_spot(items, dict(it), app.data, (p,))
        if spot is not None:
            return spot
    T.skip('no free place on another page')


def _drag_to_page(it, spot):
    app = G.app
    app.on_click(T.stash_ev(it['page'], it['x'], it['y']))
    T.check(app.drag is not None, 'no drag started')
    e = T.stash_ev(spot[0], spot[1], spot[2])          # selects the other page during the drag
    app.on_drag(e)
    app.on_release(e)
    T.pump(8)


@T.test
def undo_of_a_drag_to_another_stash_page():
    import mxl_save
    import mxl_undo
    m0 = T.mark()
    app = G.app
    raw0 = T.read(app.path)
    it = _small_item()
    spot = _other_page_spot(it)
    _drag_to_page(it, spot)
    raw1 = T.read(app.path)
    T.check(raw1 != raw0, 'the drag wrote nothing')
    items = mxl_save.parse_stash(app.path, app.data)
    T.check(any((i['page'], i['x'], i['y']) == tuple(spot) and i['code'] == it['code'] for i in items),
            f'the item is not at {spot}')
    T.check(app._undo and app._undo[-1]['kind'] == 'files', f'no move step: {app._undo[-1:]}')
    msg = mxl_undo.undo(app)
    T.pump(8)
    T.eq(T.read(app.path), raw0, f'stash after the undo ({msg})')
    T.check(any((i['page'], i['x'], i['y']) == (it['page'], it['x'], it['y']) for i in app.items),
            'the main window does not show the item back')
    no_traceback(m0)


@T.test
def undo_of_a_drag_refused_when_the_stash_changed():
    import mxl_save
    import mxl_undo
    app = G.app
    it = _small_item()
    _drag_to_page(it, _other_page_spot(it))
    T.check(app._undo and app._undo[-1]['kind'] == 'files', 'no move step')
    items = mxl_save.parse_stash(app.path, app.data)
    other = next(i for i in items if (i['page'], i['x'], i['y']) != (it['page'], it['x'], it['y']))
    mxl_save.edit_stash(app.path, app.data, remove=[other['_offset']], backup=False)     # not recorded
    raw2 = T.read(app.path)
    n = len(app._undo)
    msg = mxl_undo.undo(app)
    T.check(msg and 'changed since' in msg, f'undo not refused: {msg!r}')
    T.eq(T.read(app.path), raw2, 'the stash after the refused undo')
    T.eq(len(app._undo), n, 'the refused step was dropped')


@T.test
def undo_of_a_drag_from_stash_to_inventory():
    import mxl_char
    import mxl_save
    import mxl_undo
    m0 = T.mark()
    app = G.app
    inv = app.inventory
    if inv is None or inv.ch is None:
        T.skip('no character panel')
    T.select_tab('Stash')
    cpath = app.character_file()
    raw_s, raw_c = T.read(app.path), T.read(cpath)
    it = _small_item()
    ch = mxl_char.Character(cpath, app.data)
    spot = ch.free_inventory_spot(mxl_save.blob_item(mxl_save.item_blob(raw_s, it), app.data))
    if spot is None:
        T.skip('inventory full')
    app.on_click(T.stash_ev(it['page'], it['x'], it['y']))
    T.check(app.drag is not None, 'no drag started')
    e = T.ev(inv.canvas, (spot[0] + .5) * inv.cell, (spot[1] + .5) * inv.cell)
    app.on_drag(e)
    app.on_release(e)
    T.pump(8)
    T.check(T.read(app.path) != raw_s and T.read(cpath) != raw_c,
            f'the drag did not write both files: {T.status_text()!r}')
    T.check(app._undo and app._undo[-1]['kind'] == 'files' and len(app._undo[-1]['files']) == 2,
            'no two-file move step')
    msg = mxl_undo.undo(app)
    T.pump(8)
    T.eq(T.read(app.path), raw_s, f'stash after the undo ({msg})')
    T.eq(T.read(cpath), raw_c, 'character after the undo')
    no_traceback(m0)


# ------------------------------------------------------------------------------------------- Character SAVE
def _chartab():
    import mxl_char_gui
    cw = T.chartab()
    if cw is None or getattr(cw, 'ch', None) is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    if cw is None:
        raise T.Failed('no Character tab')
    T.select_tab('Character')
    cw.reload(keep=False)
    T.pump(4)
    return cw


def _gold_save(cw):
    gold = cw.st_value('gold')
    new = gold + 1234 if gold + 1234 <= cw.st_range('gold')[1] else gold - 1
    T.check(cw.st_set('gold', str(new)), 'gold not typed')
    cw.save_progress()
    T.pump(8)
    return gold, new


@T.test
def undo_of_a_character_save():
    import mxl_undo
    m0 = T.mark()
    app = G.app
    cw = _chartab()
    path = cw.ch.path
    raw0 = T.read(path)
    gold, new = _gold_save(cw)
    T.check(T.read(path) != raw0, 'SAVE wrote nothing')
    T.check(app._undo and app._undo[-1]['kind'] == 'files', 'no SAVE step')
    msg = mxl_undo.undo(app)
    T.pump(10)
    T.eq(T.read(path), raw0, f'character file after the undo ({msg})')
    cw = T.chartab()
    T.eq(cw.st_value('gold'), gold, 'gold shown after the undo')
    T.check(not cw.dirty(), 'pending changes after the undo')
    no_traceback(m0)


@T.test
def undo_of_a_character_save_refused_when_the_file_changed():
    import mxl_char
    import mxl_undo
    app = G.app
    cw = _chartab()
    path = cw.ch.path
    _gold_save(cw)
    T.check(app._undo and app._undo[-1]['kind'] == 'files', 'no SAVE step')
    ch = mxl_char.Character(path, app.data)                 # "the game" writes the file
    ch.set_field('gold', 7)
    ch.save(backup=False)
    raw2 = T.read(path)
    msg = mxl_undo.undo(app)
    T.check(msg and 'changed since' in msg, f'undo not refused: {msg!r}')
    T.eq(T.read(path), raw2, 'the character file after the refused undo')


T.main(globals())
