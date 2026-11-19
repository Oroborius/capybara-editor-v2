"""Ctrl+Z after 'Fill sockets with ...' (mxl_rc_menu) on character and mercenary items, from the Stash tab's
equipment / inventory panel ('panel') and from the Character tab ('tab'). The stash side is in test_31.

Was a BUG: the fill wrote the character file without recording anything for undo (Ctrl+Z: "Nothing to undo").
Now the undo writes the file's bytes of before the fill back - the whole file byte-identical, checked with the
application's save check and `python -m mxlsave verify` - and only while the file is still exactly what the fill
wrote: after a later write (the Character tab's SAVE of pending page edits) it refuses, so it never puts older
data over a newer file. Edits pending on the Character tab's pages survive the undo, still pending."""
import os
import subprocess
import sys

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'panel': {'CAPY_HOLDER': 'panel'}, 'tab': {'CAPY_HOLDER': 'tab'}}
G = T.G
HOLDER = os.environ.get('CAPY_HOLDER', 'panel')


def chartab():
    """The Character tab on the sample character (built when needed), equipment page shown."""
    import mxl_char_gui
    cw = T.chartab()
    path = G.app.character_file()
    if cw is None or getattr(cw, 'ch', None) is None or os.path.abspath(cw.ch.path) != os.path.abspath(path):
        mxl_char_gui.CharacterWindow(G.app, 'inventory')
        cw = T.chartab()
    if cw is None:
        raise T.Failed('no Character tab')
    T.select_tab('Character')
    if cw.tab.get() != 'inventory':
        cw.tab.set('inventory')
        cw.show_tab()
    T.pump(6)
    return cw


def view(merc=False):
    if HOLDER == 'tab':
        cw = chartab()
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


def fill_labels(where, merc):
    return [x for x in T.menu_labels(menu(where, merc)) if x.startswith('Fill sockets')]


def unrestricted(on):
    import settings
    was = settings.get('capy_unrestricted')
    settings.put('capy_unrestricted', on)
    return was


def copy_a_gem():
    import mxl_rc_menu
    import mxl_save
    app = G.app
    cr = mxl_rc_menu._creator(app)
    blob = bytes(cr.build(cr.new_spec('normal', cr.sockets_fillers()[0][0]))[0])
    spot = mxl_save.free_spot(mxl_save.parse_stash(app.path, app.data), mxl_save.blob_item(blob, app.data), app.data, [0, 1, 2])
    mxl_save.edit_stash(app.path, app.data, insert=[(spot[0], spot[1], spot[2], blob)], backup=False)
    app.load(app.path, keep_selection=False)
    T.select_tab('Stash')
    T.pump()
    T.invoke(T.stash_menu(*spot), 'Copy')
    T.check(app._capy_clip is not None, 'nothing in the clipboard after Copy')


def seed_inventory():
    """A plain armor without sockets (its base allows some) in a free place of the inventory; the windows read
    the file again. Returns ('inv', x, y)."""
    import mxl_char
    import mxl_creator
    import mxl_rc_menu
    cr = mxl_rc_menu._creator(G.app)
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    used = set()
    for e in ch.inventory():
        w, h = G.app.data.base(e.it['code']).size
        used |= {(e.it['x'] + i, e.it['y'] + j) for i in range(w) for j in range(h)}
    bases = sorted((b for b in cr.bases() if b.kind == 'armor' and cr.max_sockets(b.code, 99) >= 3),
                   key=lambda b: (b.size[0] * b.size[1], b.code))
    for base in bases:
        w, h = base.size
        spec = cr.new_spec('normal', base.code)
        spec['ilvl'] = 99
        spec['sockets'] = 0
        spec['max_sockets'] = False
        try:
            blob = bytes(cr.build(spec)[0])
        except mxl_creator.CreateError:
            continue
        for y in range(mxl_char.INV_H - h + 1):
            for x in range(mxl_char.INV_W - w + 1):
                if any((x + i, y + j) in used for i in range(w) for j in range(h)):
                    continue
                ch.place(blob, ('inv', x, y), False)
                ch.save(backup=False)
                G.app.inventory.reload()
                cw = T.chartab()
                if cw is not None:
                    cw.reload()
                T.pump(8)
                return ('inv', x, y)
    T.skip('no room in the inventory for a test armor')


def merc_target():
    """An equipped mercenary item the menu offers to fill, or None."""
    import mxl_char
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    if ch.merc_items is None or not ch.merc_hired:
        return None
    for e in ch.entries(True):
        if e.it['location'] != mxl_char.LOC_EQUIPPED:
            continue
        where = ('slot', e.it['equipped'])
        try:
            if fill_labels(where, True):
                return where
        except StopIteration:            # a slot the view does not show
            continue
    return None


def verified(path, what):
    import mxl_savecheck
    r = mxl_savecheck.examine(path, T.read(path))
    T.check(r.ok, f'{what}: the save check refuses the file: {r.problems}')
    home = os.path.dirname(os.path.abspath(mxl_savecheck.lib().__file__))
    p = subprocess.run([sys.executable, '-m', 'mxlsave', 'verify', path, '--user-dir', G.user_dir],
                       cwd=os.path.dirname(home), capture_output=True, text=True, timeout=120)
    T.check(p.returncode == 0, f'{what}: mxlsave verify: {(p.stdout + p.stderr).strip()[-300:]}')


def views_hold(raw, what):
    """The panel (and the Character tab, when built) hold the file as it is on disk."""
    T.pump()
    shown = G.app.inventory.ch
    T.check(shown is not None and bytes(shown.raw) == raw, f'{what}: the Stash tab panel does not show the file on disk')
    cw = T.chartab()
    if cw is not None and getattr(cw, 'ch', None) is not None:
        T.check(bytes(cw.ch.raw) == raw, f'{what}: the Character tab does not hold the file on disk')


def fill_then_undo(where, merc, what):
    import mxl_undo
    path = G.app.character_file()
    raw = T.read(path)
    stash = T.read(G.app.path)
    G.app._undo = []
    T.invoke(menu(where, merc), 'Fill sockets with')
    T.pump()
    T.check(T.read(path) != raw, f'{what}: the fill wrote nothing ({T.status_text()!r})')
    T.check(mxl_undo.can_undo(G.app), f'{what}: nothing to undo after the fill')
    mxl_undo._do_undo(G.app)
    T.pump()
    now = T.read(path)
    T.check(now == raw, f'{what}: the file after fill + undo differs from the original in '
                        f'{sum(1 for a, b in zip(now, raw) if a != b)} of {len(now)} bytes (was {len(raw)})')
    T.check(T.read(G.app.path) == stash, f'{what}: the stash file changed')
    T.check(not mxl_undo.can_undo(G.app), f'{what}: undo stack not empty after the undo')
    views_hold(raw, what)
    verified(path, f'{what} + undo')
    return raw


@T.test
def fill_then_undo_on_a_character_item():
    was = unrestricted(False)
    try:
        copy_a_gem()
        where = seed_inventory()
        fill_then_undo(where, False, f'character item at {where}')
        T.check(fill_labels(where, False), 'the armor is not offered the fill again after the undo')
    finally:
        unrestricted(was)


@T.test
def fill_then_undo_on_a_mercenary_item():
    was = unrestricted(True)            # Unrestricted: a weapon / armor without room gets sockets up to 6
    try:
        copy_a_gem()
        where = merc_target()
        if where is None:
            T.skip('no mercenary item in reach can take a socketed item')
        fill_then_undo(where, True, f'mercenary item at {where}')
    finally:
        unrestricted(was)


@T.test
def undo_keeps_the_pending_page_edits():
    """A stat edit pending on the Character tab, then a fill, then Ctrl+Z: the file is the original again, the
    stat edit is still pending (not written, not lost), and SAVE then writes it."""
    import mxl_char
    was = unrestricted(False)
    try:
        copy_a_gem()
        where = seed_inventory()
        cw = chartab()
        cur = cw.st_value('strength')
        T.check(cw.st_set('strength', str(cur + 7)) is not False, 'the stat edit was refused')
        T.check(cw.dirty(), 'no pending edit on the Character tab')
        raw = fill_then_undo(where, False, 'fill + undo with a pending stat edit')
        cw = T.chartab()
        T.check(cw.dirty(), 'the pending stat edit is gone after the undo')
        T.eq(cw.st_value('strength'), cur + 7, 'pending strength after the undo')
        cw.save_progress()
        T.pump(6)
        ch = mxl_char.Character(G.app.character_file(), G.app.data)
        T.eq(ch.stat(0), cur + 7, 'strength in the file after SAVE')
        T.check(T.read(G.app.character_file()) != raw, 'SAVE wrote nothing')
    finally:
        unrestricted(was)


@T.test
def undo_refused_after_a_newer_save():
    """Fill, then the Character tab's SAVE writes a pending stat edit. The SAVE is an undo step of its own
    (test_62): the first Ctrl+Z gives the file of after the fill back, the second the file of before the fill.
    A write that is NOT recorded (the game) between the fill and its undo makes the undo refuse and write nothing."""
    import mxl_undo
    import mxl_char
    was = unrestricted(False)
    try:
        copy_a_gem()
        where = seed_inventory()
        path = G.app.character_file()
        G.app._undo = []
        raw0 = T.read(path)
        T.invoke(menu(where, False), 'Fill sockets with')
        T.pump()
        filled = T.read(path)
        cw = chartab()
        cur = cw.st_value('strength')
        cw.st_set('strength', str(cur + 7))
        cw.save_progress()
        T.pump(6)
        T.check(not cw.dirty(), 'still pending after SAVE')
        mxl_undo._do_undo(G.app)
        T.pump()
        T.check(T.read(path) == filled, f'the first undo did not undo the SAVE: {T.status_text()!r}')
        ch = mxl_char.Character(path, G.app.data)           # "the game" writes the file: not recorded
        ch.set_field('gold', 7)
        ch.save(backup=False)
        saved = T.read(path)
        mxl_undo._do_undo(G.app)
        T.pump()
        T.check('changed' in T.status_text(), f'status of the refused undo: {T.status_text()!r}')
        T.check(T.read(path) == saved, 'the refused undo wrote the character file')
        T.check(T.read(path) != raw0, 'the file is the one before the fill')
    finally:
        unrestricted(was)


T.main(globals())
