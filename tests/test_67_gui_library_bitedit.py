"""Library and Bit editor main tabs (mxl_itemlib.LibraryWindow, mxl_bitedit.BitEditor), both looks.

Library: the tab exists from the start, More » Item library... selects it, an added item is listed under its
folder with the tooltip shown, Place a copy writes one copy on the page shown (mxlsave check) and Ctrl+Z removes
it. Bit editor: right-click "Open in Bit editor" opens the item; the fields cover the bits without gap and each
field's value is its bits read LSB first; Space on the ethereal flag + Apply writes an item that decodes ethereal
with exactly that bit changed and nothing else in the stash; a bit inserted (does not parse) refuses Apply and
writes nothing; undo gives the original bytes; the value dialog writes a field. Set CAPY_SHOTS=<folder> for
800x600 screenshots."""
import os
import subprocess

import capytest as T

MODE = 'gui'
RESET = True
SAMPLE = 2
VARIANTS = {'d2': {'MXL_THEME': 'd2'}, 'he': {'MXL_THEME': 'he'}}
G = T.G
ETH = 16 + 22          # ethereal: flag bit 22, the flags start after 'JM'


def shot(name):
    folder = os.environ.get('CAPY_SHOTS')
    if not folder:
        return
    os.makedirs(folder, exist_ok=True)
    G.root.update()
    try:
        subprocess.run(['import', '-window', 'root', os.path.join(folder, f'tabs-{T.VARIANT}-{name}.png')],
                       timeout=30, capture_output=True)
    except Exception:
        pass


def _items(pred):
    import mxl_save
    raw = T.read(G.app.path)
    for it in sorted(G.app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        blob = bytes(mxl_save.item_blob(raw, it))
        if pred(it, blob):
            yield it, blob


def _weapon_or_armor(it, blob):
    import mxl_bitedit
    try:
        d = mxl_bitedit.decode(blob, G.app.data)
    except Exception:
        return False
    top = d.items[0]
    return not top.simple and (top.defense_raw is not None or top.max_durability is not None)


def _open(it):
    import mxl_bitedit
    import mxl_tabs
    T.check(T.invoke(T.stash_menu(it['page'], it['x'], it['y']), 'Open in Bit editor'), 'no Open in Bit editor entry')
    T.pump()
    w = mxl_tabs.built_owner('Bit editor')
    T.check(isinstance(w, mxl_bitedit.BitEditor), 'the Bit editor tab is not built')
    return w


@T.test
def tabs_exist():
    names = T.tab_names()
    T.check('Library' in names and 'Bit editor' in names, f'tabs: {names}')


@T.test
def library_tab_place_undo():
    import mxl_itemlib
    import mxl_tabs
    import mxl_undo
    import mxl_toolbar
    it, blob = next(_items(lambda it, b: it.get('stats')), (None, None))
    if it is None:
        T.skip('no item with stats')
    G.answers['str'] = 'Tab tests/Lib item'
    T.invoke(T.stash_menu(it['page'], it['x'], it['y']), 'Add to library...')
    e = mxl_itemlib.load()[-1]
    entry = next(c for lab, c in mxl_toolbar.EXTRA if lab() == 'Item library...')
    entry(G.app)
    T.pump()
    w = mxl_tabs.built_owner('Library')
    T.check(isinstance(w, mxl_itemlib.LibraryWindow), 'More » Item library... did not build the Library tab')
    nb = mxl_tabs._state['nb']
    T.eq(nb.select(), str(mxl_tabs._state['pages']['Library']), 'the Library tab is selected')
    iid = next(k for k, r in w.rows.items() if r['file'] == e['file'])
    T.eq(w.tree.item(w.tree.parent(iid), 'text').strip(), 'Tab tests/', 'folder node')
    w.tree.selection_set(iid)
    T.pump()
    T.check(len(w.detail.get('1.0', 'end').strip()) > 0, 'no tooltip on the right')
    shot('library')
    path = G.app.path
    raw0 = T.read(path)
    snap = T.stash_snap(path, G.app.data)
    w.place()
    T.pump()
    g, new, chg = T.diff(snap, T.stash_snap(path, G.app.data))
    T.eq((g, chg, len(new)), ([], [], 1), 'place a copy')
    T.eq(new[0][0], G.app.page(), 'on the page shown')
    import mxl_savecheck
    T.check(mxl_savecheck.examine(path, T.read(path), raw0).ok, 'mxlsave check')
    mxl_undo.undo(G.app)
    T.pump()
    T.eq(T.read(path), raw0, 'bytes after undo')


@T.test
def bit_editor_layout_contiguous():
    import mxl_bitedit
    it, blob = next(_items(lambda it, b: it.get('stats')), (None, None))
    w = _open(it)
    T.eq(mxl_bitedit.pack(w.bits), blob, 'bits = the item bytes')
    T.check(w.valid, f'sample item does not parse: {w.error}')
    at = 0
    for off, n, lab, v, _k in w.dec.fields:
        T.eq(off, at, f'field {lab} starts at {off}, expected {at}')
        T.eq(sum(w.bits[off + j] << j for j in range(n)), v, f'field {lab}: value from its bits (LSB first)')
        at = off + n
    T.eq(at, len(w.bits), 'layout ends on the last bit')
    w.cur = ETH
    w.show_status()
    T.check('ethereal' in w.val_l.cget('text'), f'status at the ethereal bit: {w.val_l.cget("text")!r}')
    shot('bits')
    w.toggle_view()
    T.pump()
    T.check('Bit layout' in w.text.get('1.0', 'end'), 'text dump view')
    shot('dump')
    w.toggle_view()
    w.copy_dump()
    T.eq(G.root.clipboard_get(), w.dump_text(), 'Copy text dump')
    w.copy_hex()
    T.eq(bytes.fromhex(G.root.clipboard_get()), blob, 'Copy hex')


@T.test
def bit_editor_ethereal_apply_undo():
    import mxl_bitedit
    import mxl_save
    import mxl_undo
    it, blob = next(_items(_weapon_or_armor), (None, None))
    if it is None:
        T.skip('no weapon / armor')
    path = G.app.path
    raw0 = T.read(path)
    snap = T.stash_snap(path, G.app.data)
    w = _open(it)
    w.cv.focus_set()
    w.cur = ETH
    w.cv.event_generate('<space>')                 # through the canvas binding (must not leak to the root)
    T.pump()
    was = blob[ETH >> 3] >> (ETH & 7) & 1
    T.eq(w.bits[ETH], 1 - was, 'Space toggled the ethereal bit')
    T.check(w.valid, f'ethereal item does not parse: {w.error}')
    undo0 = len(G.app._undo)
    T.check(w.apply(), f'Apply refused: {w.state.cget("text")}')
    T.pump()
    now = T.stash_snap(path, G.app.data)
    g, new, chg = T.diff(snap, now)
    T.eq((g, new, len(chg)), ([], [], 1), 'apply: only one item changed')
    raw1 = T.read(path)
    cur = next(i for i in mxl_save.parse_stash(path, G.app.data) if (i['page'], i['x'], i['y']) ==
               (it['page'], it['x'], it['y']))
    nb = bytes(mxl_save.item_blob(raw1, cur))
    T.eq(len(nb), len(blob), 'same size')
    diff = [i for i in range(len(blob) * 8) if (blob[i >> 3] ^ nb[i >> 3]) >> (i & 7) & 1]
    T.eq(diff, [ETH], 'changed bits')
    d = mxl_bitedit.decode(nb, G.app.data)
    T.eq(d.items[0].flag(22), not was, 'ethereal flag of the written item')
    import mxl_savecheck
    T.check(mxl_savecheck.examine(path, raw1, raw0).ok, 'mxlsave check')
    T.eq(len(G.app._undo), undo0 + 1, 'undo recorded')
    # invalid edit: one bit inserted -> does not parse -> Apply refused, nothing written
    w.toggle_mode()
    w.cur = 20
    w.set_bit(1)
    T.check(not w.valid, 'an inserted bit still parses')
    T.check('does not parse' in w.state.cget('text'), f'state: {w.state.cget("text")!r}')
    T.check(w.dec is not None, 'last valid decode dropped')
    shot('invalid')
    T.check(w.apply() is False, 'Apply wrote bits that do not parse')
    T.eq(T.read(path), raw1, 'file after a refused Apply')
    w.toggle_mode()
    w.revert()
    w.cur = ETH
    T.check(w.valid and mxl_bitedit.pack(w.bits) == nb, 'Revert')
    msg = mxl_undo.undo(G.app)
    T.pump()
    T.eq(T.read(path), raw0, f'bytes after undo ({msg})')
    # the stale guard: the editor still holds the applied item, the file holds the original again (the undo)
    w.toggle()                                      # ethereal off again: other bits than the editor opened
    T.check(w.valid, 'toggled back does not parse')
    T.check(w.apply() is False, 'Apply over an item changed on disk')
    T.check('changed on disk' in w.state.cget('text'), f'state: {w.state.cget("text")!r}')
    T.eq(T.read(path), raw0, 'nothing written')


@T.test
def bit_editor_value_dialog():
    import mxl_bitedit
    it, blob = next(_items(lambda it, b: it.get('stats')), (None, None))
    w = _open(it)
    f = next(x for x in w.dec.fields if x[2] == 'item level')
    w.cur = f[0]
    G.answers['str'] = '0x2A'
    w.edit_value()
    T.eq(w.field_at(f[0])[3], 42, 'item level after typing 0x2A')
    T.check(w.valid, 'item level 42 does not parse')
    T.eq(w.dec.items[0].ilvl, 42, 'decoded ilvl')
    w.revert()
    T.eq(mxl_bitedit.pack(w.bits), blob, 'revert')


T.main(globals())
