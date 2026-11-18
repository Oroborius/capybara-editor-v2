"""Save safety in the running application: moves that write two files (character + stash) when the second write
is refused, and a stash delete from a window that has not yet re-read a stash written behind its back.
docs/review/save-safety.md (F6, two-file moves)."""
import os

import capytest as T

MODE = 'gui'
RESET = True
ALLOW_ERRORS = True          # the refusals are logged as errors on purpose; tracebacks are checked per test
VARIANTS = {'panel': {'CAPY_HOLDER': 'panel'}, 'tab': {'CAPY_HOLDER': 'tab'}}
G = T.G
HOLDER = os.environ.get('CAPY_HOLDER', 'panel')
SLOT = 1


def view():
    if HOLDER == 'tab':
        cw = T.chartab()
        if cw is None:
            raise T.Failed('no Character tab')
        T.select_tab('Character')
        if cw.tab.get() != 'inventory':
            cw.tab.set('inventory')
            cw.show_tab()
        if cw.merc.get():
            cw.merc.set(False)
            cw.on_view()
    T.pump(6)


def menu(where):
    view()
    return T.chartab_menu(where) if HOLDER == 'tab' else T.panel_menu(where)


def small_equipped():
    import mxl_char
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    for e in ch.entries(False):
        b = G.app.data.base(e.it['code'])
        if e.it['location'] == SLOT and b.size[0] * b.size[1] <= 4:
            return ('slot', e.it['equipped'])
    T.skip('no small equipped item')


def no_traceback(m):
    for e in T.errors_since(m):
        T.check('Traceback' not in e and 'Exception in Tkinter' not in e, 'traceback: ' + e)


def refuse(kind):
    """mxl_savecheck.TEST_HOOK that breaks the bytes of one kind of file: the strict check refuses that write."""
    def hook(path, content):
        if str(path).endswith(kind):
            b = bytearray(content)
            if kind == '.d2s':
                b[12] ^= 0xFF                   # checksum
            else:
                b[8:13] = b'XXXXX'             # first page marker
            return bytes(b)
        return content
    return hook


@T.test
def to_stash_with_the_character_write_refused_changes_nothing():
    """To stash writes the stash first, then the character; the character write refused: the stash is put back.
    Neither file changes, the item is neither lost nor doubled."""
    m0 = T.mark()
    import mxl_savecheck as SC
    where = small_equipped()
    cpath, spath = G.app.character_file(), G.app.path
    c0, s0 = T.read(cpath), T.read(spath)
    m = menu(where)
    SC.TEST_HOOK = refuse('.d2s')
    try:
        T.invoke(m, 'To stash')
        T.pump(6)
    finally:
        SC.TEST_HOOK = None
    T.check(T.read(cpath) == c0, 'the character file changed')
    T.check(T.read(spath) == s0, 'the stash file changed (the item would be doubled)')
    no_traceback(m0)


@T.test
def to_stash_with_the_stash_write_refused_changes_nothing():
    m0 = T.mark()
    import mxl_savecheck as SC
    where = small_equipped()
    cpath, spath = G.app.character_file(), G.app.path
    c0, s0 = T.read(cpath), T.read(spath)
    m = menu(where)
    SC.TEST_HOOK = refuse('.stash')
    try:
        T.invoke(m, 'To stash')
        T.pump(6)
    finally:
        SC.TEST_HOOK = None
    T.check(T.read(cpath) == c0, 'the character file changed (the item would be lost)')
    T.check(T.read(spath) == s0, 'the stash file changed')
    no_traceback(m0)


@T.test
def stash_delete_from_an_out_of_date_view_deletes_nothing():
    """The stash is written behind the window's back (as the game saving it); before the once-a-second re-read,
    Delete on an item: nothing is deleted (it used to delete the neighbour), the window reads the stash again."""
    if HOLDER != 'panel':
        T.skip('stash grid: one variant is enough')
    m0 = T.mark()
    import mxl_save
    import mxl_undo
    from mxl_format import write_bits
    app = G.app
    path = app.path
    raw = T.read(path)
    items = list(app.items)
    pages = sorted({i['page'] for i in items})
    later = [i for i in items if i['page'] == pages[-1]]
    k = next((k for k in range(1, len(later)) if later[k - 1]['_size'] == later[k]['_size']
              and not later[k - 1].get('socketed') and not later[k].get('socketed')), None)
    if k is None or len(pages) < 2:
        T.skip('no two neighbours of the same size on a later page')
    prev, victim = later[k - 1], later[k]
    blob = bytes(mxl_save.item_blob(raw, prev))
    spot = mxl_save.free_spot(items, mxl_save.blob_item(blob, app.data), app.data, [pages[0]])
    new = mxl_save.blob_item(blob, app.data)
    b = bytearray(blob)
    write_bits(b, 16 + new['_pos_bit'], 4, spot[1])
    write_bits(b, 16 + new['_pos_bit'] + 4, 4, spot[2])
    blobs = mxl_save.stash_blobs(raw, mxl_save.parse_stash(path, app.data))
    blobs[spot[0]].append(bytes(b))
    with open(path, 'wb') as f:                  # the other writer (no editor code involved)
        f.write(mxl_save.build_stash(raw[:8], blobs))
    mxl_undo.delete_item(app, victim)
    T.pump(6)
    now = {(i['page'], i['x'], i['y']) for i in mxl_save.parse_stash(path, app.data)}
    T.check((prev['page'], prev['x'], prev['y']) in now, 'the neighbour was deleted')
    T.check((victim['page'], victim['x'], victim['y']) in now, 'something was deleted from the out-of-date view')
    T.pump(10)
    T.eq(len(app.items), len(items) + 1, 'the window read the stash again')
    no_traceback(m0)


def stash_item(pred, what):
    import mxl_creator as C
    raw = T.read(G.app.path)
    import mxl_save
    for it in G.app.items:
        try:
            rec = T.rec_of(mxl_save.item_blob(raw, it))
        except Exception:
            continue
        if not rec['flags'] & C.FLAG_SIMPLE and pred(it, rec, G.app.data.base(it['code'])):
            return it
    T.skip(f'no {what} in the stash')


def undo_restores(path, raw, what):
    import mxl_undo
    msg = mxl_undo.undo(G.app)
    T.pump(6)
    T.check(T.read(path) == raw, f'{what} then Ctrl+Z: the file is not the original ({msg})')


@T.test
def stash_paste_over_an_item_then_undo():
    """Paste over an item replaces it (no prompt): Ctrl+Z gives it back (there was no undo: the replaced item was
    only in the session's first backup, if at all - F19)."""
    if HOLDER != 'panel':
        T.skip('stash grid: one variant is enough')
    import mxl_save
    m0 = T.mark()
    app = G.app
    raw = T.read(app.path)
    src = stash_item(lambda it, rec, b: b.size == (1, 1), '1x1 item')
    dst = stash_item(lambda it, rec, b: b.size == (1, 1) and it is not src
                     and bytes(mxl_save.item_blob(raw, it)) != bytes(mxl_save.item_blob(raw, src)), 'second 1x1 item')
    T.invoke(T.stash_menu(src['page'], src['x'], src['y']), 'Copy')
    T.invoke(T.stash_menu(dst['page'], dst['x'], dst['y']), 'Paste (replaces it')
    T.check(T.read(app.path) != raw, 'paste wrote nothing')
    undo_restores(app.path, raw, 'paste over an item')
    no_traceback(m0)


@T.test
def stash_specific_edit_then_undo():
    """Quality change and ethereal on a stash item: Ctrl+Z restores the file bytes."""
    if HOLDER != 'panel':
        T.skip('stash grid: one variant is enough')
    m0 = T.mark()
    app = G.app
    it = stash_item(lambda it, rec, b: b.kind in ('armor', 'weapons') and rec['quality'] != 'set', 'armor / weapon')
    raw = T.read(app.path)
    import mxl_creator as C
    import mxl_save
    eth = T.rec_of(mxl_save.item_blob(raw, it))['flags'] & C.FLAG_ETHEREAL
    step = 'Remove ethereal' if eth else 'Make ethereal'
    T.invoke(T.stash_menu(it['page'], it['x'], it['y']), step, under='Specific editing functions')
    T.check(T.read(app.path) != raw, f'{step} wrote nothing')
    undo_restores(app.path, raw, step)
    no_traceback(m0)


@T.test
def character_specific_edit_then_undo():
    """Make / remove ethereal on a worn item (Stash-tab panel and Character tab): Ctrl+Z restores the character
    file bytes (character item actions other than Fill sockets had no undo - F19)."""
    import mxl_char
    import mxl_creator as C
    m0 = T.mark()
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    where = None
    for e in ch.entries(False):
        if e.it['location'] != SLOT:
            continue
        rec = T.rec_of(e.blob)
        b = G.app.data.base(e.it['code'])
        if b.kind in ('armor', 'weapons') and not rec['flags'] & C.FLAG_SIMPLE and rec['quality'] != 'set':
            where = ('slot', e.it['equipped'])
            step = 'Remove ethereal' if rec['flags'] & C.FLAG_ETHEREAL else 'Make ethereal'
            break
    if where is None:
        T.skip('no worn armor / weapon')
    path = G.app.character_file()
    raw = T.read(path)
    T.invoke(menu(where), step, under='Specific editing functions')
    T.pump(6)
    T.check(T.read(path) != raw, f'{step} wrote nothing')
    undo_restores(path, raw, step)
    no_traceback(m0)


T.main(globals())
