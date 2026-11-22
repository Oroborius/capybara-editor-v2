"""Vanilla profile (MXL_GAME=vanilla): the main window's stash pane is a read-only view of the character file's
own stash (no stash file). A drop onto it says the 1.14d stash is part of the character (not "open a stash
first"); the stash shortcuts (Ctrl+C / Ctrl+V / Ctrl+Shift+C / Ctrl+Shift+V, Delete, Ctrl+Z) raise nothing and
write nothing (Ctrl+C copies the item from the view); the pane title follows a live language switch. Copies of
the vanilla samples only; skipped without the vanilla install or the samples (see test 77)."""
import glob
import os
import shutil

import capytest as T

MODE = 'gui'
G = T.G
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')


def _saves():
    v = os.path.join(T.REPO, '.cache', 'samples', 'vanilla')
    if not glob.glob(os.path.join(v, '*.d2s')) or not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        return None
    dst = T.guard(os.path.join(T.tmp(), 'v89saves'), 'vanilla save copies')
    if not os.path.isdir(dst):
        os.makedirs(dst)
        for f in glob.glob(os.path.join(v, '*.d2s')):
            shutil.copy(f, dst)
    return dst


_S = _saves()
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': GAME, **({'MXL_SAVE_DIR': _S} if _S else {})}
WAIT_TABS = True


def _open():
    app = G.app
    app.select_character('complex', app.view.get())
    app.open_view(keep_page=True)
    T.pump(20, 0.02)
    T.select_tab('Stash')
    T.pump(10)
    T.check(app.path is None and app.items, f'read-only view with items: {app.path} {len(app.items)}')
    return app


def _point(app, it):
    """The mouse pointer over the item's cell of the stash grid."""
    c = app.cell
    app.canvas.event_generate('<Motion>', warp=True, x=it['x'] * c + c // 2, y=it['y'] * c + c // 2)
    T.pump(6, 0.02)


def _snap():
    return {f: T.read(f) for f in glob.glob(os.path.join(_S, '*'))}


@T.test
def drop_on_readonly_stash_says_why():
    if _S is None:
        T.skip('no vanilla install / samples')
    import mxl_vanilla_pages as VP
    app = _open()
    inv = app.inventory
    T.check(inv is not None, 'inventory panel')
    cv = app.canvas
    t = inv.stash_target(cv.winfo_rootx() + 5, cv.winfo_rooty() + 5, app.items[0], 0, 0)
    T.check(t is not None, 'the pane is a drop target')
    T.check('open a stash' not in (t[2] or ''), f'misleading message: {t[2]!r}')
    T.eq(t[2], VP.readonly_text(), 'the 1.14d stash is part of the character')


@T.test
def stash_shortcuts_are_safe():
    if _S is None:
        T.skip('no vanilla install / samples')
    import mxl_rc_menu
    import mxl_undo
    app = _open()
    before = _snap()
    it = app.items[0]
    _point(app, it)
    m = T.mark()
    app._capy_clip = None
    for what in ('copy', 'paste', 'magic_copy', 'magic_paste'):
        try:
            mxl_rc_menu._stash_hot(app, what)
        except Exception as e:
            T.check(False, f'{what}: {type(e).__name__}: {e}')
        T.pump(4)
    T.check(getattr(app, '_capy_clip', None) is not None, 'Ctrl+C copied the item from the view')
    mxl_rc_menu._stash_hot(app, 'paste')           # over the item: refused, nothing written
    T.check('1.14d' in app.status.cget('text'), f'paste refused: {app.status.cget("text")!r}')
    for fn in (lambda: mxl_undo.delete_item(app, it), lambda: mxl_undo._do_undo(app)):
        try:
            fn()
        except Exception as e:
            T.check(False, f'delete / undo: {type(e).__name__}: {e}')
    for seq in ('<Delete>', '<Control-z>', '<Control-c>', '<Control-v>'):
        app.root.event_generate(seq)
        T.pump(4)
    T.eq(T.errors_since(m), [], 'no errors')
    T.check(_snap() == before, 'no save file written')
    T.eq(len(app.items), len(VP_items(app)), 'the view still shows the stash')


def VP_items(app):
    import mxl_char
    import mxl_vanilla_pages as VP
    return VP.stash_view(mxl_char.Character(app.character_file(), app.data), app.data)[2]


@T.test
def pane_title_follows_language():
    if _S is None:
        T.skip('no vanilla install / samples')
    import mxl_lang
    app = _open()
    langs = [x[0] for x in app.languages]
    if 'fr' not in langs or 'en' not in langs:
        T.skip('no fr / en language offered')

    def switch(code):
        app.lang_combo.current(langs.index(code))
        app.change_language()
        T.settle(0.3)

    want = lambda: mxl_lang.T('van.main_stash', 'Stash ({cols} x {rows}) - shown, not edited here',
                              cols=6, rows=8)
    en = app.van_title.cget('text')
    switch('fr')
    try:
        T.check(want() != en, f'French text for the title: {want()!r}')
        T.eq(app.van_title.cget('text'), want(), 'title in French')
    finally:
        switch('en')
    T.eq(app.van_title.cget('text'), en, 'title back in English')


T.main(globals())
