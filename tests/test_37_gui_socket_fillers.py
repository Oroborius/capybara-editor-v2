"""Socket fillers in the Item Editor (edit mode of the creator): every socketed item of an item is listed in the
Sockets block - gems / runes in their pick field, jewels and other items with a stat list of their own as a line -
and each can be taken out (its x button), all of them at once (Empty sockets). The parent keeps its sockets (they
become empty, as in the game), its socketed flag, and a socketed-item count equal to the children behind it.
Checked on the stash re-read from disk, with the application's save check and `python -m mxlsave verify`; an
Edit -> Replace that changes nothing stays byte-identical.

The sample stash has no socketed item that is not a runeword: the test makes one - a unique armor with two gems
built by the creator, plus the jewel socketed in a runeword of the sample character - and writes it into the stash."""
import os
import subprocess
import sys

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {
    'd2': {'MXL_THEME': 'd2'},
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
    'he-800x600': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0'},
}
G = T.G
MAX_CALLS, MAX_CONFIGURES = 120, 12                 # as in test_36_gui_character_layout
SHOTS = os.environ.get('CAPY_SHOTS')


def shot(name):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    G.root.update()
    try:
        subprocess.run(['import', '-window', 'root', os.path.join(SHOTS, f'sockets-{T.VARIANT}-{name}.png')], timeout=30,
                       capture_output=True)
    except Exception:
        pass


def jewel_raw():
    """Bytes of a socketed jewel (an item with a stat list of its own) from the sample character."""
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


def make_parent():
    """A unique armor with 3 sockets holding [gem, gem, jewel], written into the stash; its (page, x, y)."""
    import mxl_creator as C
    import mxl_save
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
    spec['socketed'] = [gems[0], gems[1]]
    blob, _rec = cr.build(spec)
    rec, kids = cr._split(bytes(blob), d)
    prec = C.decode_item(rec, d)[0]
    prec['socketed_count'] = 3
    jew = C.decode_item(jewel_raw(), d)[0]
    blob = C.encode_item(prec, d) + b''.join(kids) + C.encode_item(
        dict(jew, location=C.LOC_SOCKETED, equipped=0, x=2, y=0, panel=0), d)
    items = mxl_save.parse_stash(G.app.path, d)
    new = mxl_save.blob_item(blob, d)
    T.eq(len(new.get('socketed') or ()), 3, 'socketed items of the made parent')
    spot = mxl_save.free_spot(items, new, d, list(range(mxl_save.STASH_PAGES)))
    mxl_save.edit_stash(G.app.path, d, insert=[(spot[0], spot[1], spot[2], bytes(blob))], backup=False)
    G.app.load(G.app.path, keep_selection=False)
    T.pump(6)
    return tuple(spot), gems[:2], jew


def activity(secs=1.0):
    """(Tk callbacks, <Configure> events) during `secs` of running the event loop."""
    import tkinter
    n = [0, 0]
    orig = tkinter.CallWrapper.__call__

    def call(self, *a):
        n[0] += 1
        return orig(self, *a)

    def conf(_e):
        n[1] += 1
    tkinter.CallWrapper.__call__ = call
    G.root.bind_all('<Configure>', conf, add='+')
    try:
        T.settle(secs)
    finally:
        tkinter.CallWrapper.__call__ = orig
        G.root.unbind_all('<Configure>')
    return n[0], n[1]


def verify_file(path, what):
    import mxl_savecheck
    r = mxl_savecheck.examine(path, T.read(path))
    T.check(r.ok, f'{what}: the save check refuses the file: {r.problems}')
    home = os.path.dirname(os.path.abspath(mxl_savecheck.lib().__file__))
    p = subprocess.run([sys.executable, '-m', 'mxlsave', 'verify', path, '--user-dir', G.user_dir],
                       cwd=os.path.dirname(home), capture_output=True, text=True, timeout=120)
    T.check(p.returncode == 0, f'{what}: mxlsave verify: {(p.stdout + p.stderr).strip()[-300:]}')


def editor(key):
    import mxl_creator_gui as CG
    import mxl_tabs
    G.app.selected = next(i for i in G.app.items if (i['page'], i['x'], i['y']) == key)
    CG.edit_selected(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    if w is None or w.edit_item is None or w.spec is None:
        raise T.Failed('the Item Editor did not open')
    return w


def commit(w):
    w.commit()
    T.pump(8)
    for kind, title, msg in G.boxes:
        if kind == 'showerror':
            raise T.Failed(f'error box {title!r}: {msg[:200]}')


def entry(key):
    """(parent record, [child records]) of the stash entry at key, read from disk."""
    import mxl_creator as C
    import mxl_save
    d = G.app.data
    raw = T.read(G.app.path)
    it = next(i for i in mxl_save.parse_stash(G.app.path, d) if (i['page'], i['x'], i['y']) == key)
    return C.decode_blob(bytes(mxl_save.item_blob(raw, it)), d), it


def consistent(key, what):
    """The parent on disk carries what its children need; the file passes both checks. Returns the child codes."""
    import mxl_creator as C
    (rec, kids), it = entry(key)
    T.check(rec['flags'] & C.FLAG_SOCKETED, f'{what}: socketed flag lost')
    T.eq(rec.get('sockets'), 3, f'{what}: socket count (removing fillers empties sockets, it does not take them away)')
    T.eq(rec.get('socketed_count'), len(kids), f'{what}: socketed-item count vs children behind the item')
    T.eq(len(it.get('socketed') or ()), len(kids), f'{what}: children the application reads')
    T.eq([k.get('x') for k in kids], list(range(len(kids))), f'{what}: places of the children')
    verify_file(G.app.path, what)
    return [k['code'] for k in kids]


@T.test
def fillers_are_listed_and_noop_replace_is_identical():
    key, gems, _jew = make_parent()
    before = T.stash_snap(G.app.path, G.app.data)
    w = editor(key)
    rows = w.filler_rows()
    T.eq([(r['code'], r['kind']) for r in rows], [(gems[0], 'pick'), (gems[1], 'pick'), ('jew ', 'item')],
         'socket rows of the editor')
    shot('editor')
    calls, confs = activity(1.0)
    T.check(calls <= MAX_CALLS and confs <= MAX_CONFIGURES,
            f'the Item Editor does not come to rest: {calls} Tk callbacks and {confs} <Configure> events in one second')
    commit(w)
    after = T.stash_snap(G.app.path, G.app.data)
    T.only_changed(before, after, what='no-op Replace of a socketed item')


@T.test
def remove_one_gem_and_the_jewel():
    key, gems, _jew = make_parent()
    w = editor(key)
    w.remove_filler(0)                                  # the first gem
    T.pump(4)
    T.eq([r['code'] for r in w.filler_rows()], [gems[1], 'jew '], 'rows after taking out the first gem')
    commit(w)
    T.eq(consistent(key, 'first gem removed'), [gems[1], 'jew '], 'children on disk after removing the first gem')
    w = editor(key)
    rows = w.filler_rows()
    w.remove_filler(next(i for i, r in enumerate(rows) if r['kind'] == 'item'))      # the jewel
    T.pump(4)
    shot('jewel-removed')
    commit(w)
    T.eq(consistent(key, 'jewel removed'), [gems[1]], 'children on disk after removing the jewel')


@T.test
def empty_all_sockets():
    key, _gems, _jew = make_parent()
    before = T.stash_snap(G.app.path, G.app.data)
    w = editor(key)
    w.clear_fillers()
    T.pump(4)
    T.eq(w.filler_rows(), [], 'rows after Empty sockets')
    commit(w)
    T.eq(consistent(key, 'all fillers removed'), [], 'children on disk after Empty sockets')
    after = T.stash_snap(G.app.path, G.app.data)
    T.only_changed(before, after, chg=[key], what='Empty sockets')
    w = editor(key)                                     # the emptied item opens and replaces unchanged again
    before = T.stash_snap(G.app.path, G.app.data)
    commit(w)
    T.only_changed(before, T.stash_snap(G.app.path, G.app.data), what='no-op Replace of the emptied item')


def char_item(code):
    """(entry, place) of an item of the character (equipped or in the inventory) with that base code."""
    import mxl_char as MC
    inv = G.app.inventory
    inv.merc.set(False)
    inv.on_view()
    T.pump(4)
    for e in inv.ch.entries(False):
        if e.it['code'].strip() != code:
            continue
        if e.it['location'] == MC.LOC_EQUIPPED:
            return e, ('slot', e.it['equipped'])
        if e.it['location'] == 0 and e.it.get('panel') == 1:
            return e, ('inv', e.it['x'], e.it['y'])
    raise T.Skip(f'the sample character has no item {code!r} equipped or in the inventory')


def char_edit(code, change, want, what):
    """Item Editor on a character item (the Stash tab's panel: Edit item), change(w), Replace; the item re-read
    from the character file has the children `want` (codes), its flags / sockets kept, everything else as it was."""
    import mxl_char as MC
    import mxl_creator as C
    import mxl_tabs
    d = G.app.data
    path = G.app.character_file()
    e, where = char_item(code)
    rec0 = C.decode_item(bytes(e.blob), d)[0]
    snap0 = T.char_snap(path, d)
    inv = G.app.inventory
    inv.selected, inv.sel_merc = e, False
    inv.edit()
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    if w is None or w.edit_item is None or w.spec is None:
        raise T.Failed(f'{what}: the Item Editor did not open on the character item')
    change(w)
    T.pump(4)
    shot(what.replace(' ', '-'))
    commit(w)
    ch = MC.Character(path, d)
    e2 = next((x for x in ch.entries(False) if x.it['code'] == e.it['code'] and (
        ('slot', x.it['equipped']) if x.it['location'] == MC.LOC_EQUIPPED else ('inv', x.it['x'], x.it['y'])) == where
        and x.it['location'] == e.it['location']), None)
    if e2 is None:
        raise T.Failed(f'{what}: the item is not at {where} after Replace')
    rec, kids = C.decode_blob(bytes(e2.blob), d)
    T.eq([k['code'] for k in kids], want, f'{what}: children on disk')
    T.eq(rec.get('socketed_count'), len(kids), f'{what}: socketed-item count vs children')
    T.eq([k.get('x') for k in kids], list(range(len(kids))), f'{what}: places of the children')
    for k in ('flags', 'sockets', 'id', 'runeword_id', 'quality', 'stats', 'stats_runeword'):
        T.eq(rec.get(k), rec0.get(k), f'{what}: parent field {k}')
    snap1 = T.char_snap(path, d)
    changed = [k for k in set(snap0) | set(snap1) if snap0.get(k) != snap1.get(k)]
    T.eq(len(changed), 1, f'{what}: character items changed ({changed})')
    for problem in T.d2s_header_ok(T.read(path)):
        T.check(False, f'{what}: character file: {problem}')
    verify_file(path, what)


@T.test
def character_item_remove_a_rune():
    """Set item @04 with six Ko runes, in the character file: one taken out."""
    def change(w):
        T.eq([r['code'] for r in w.filler_rows()], ['r18 '] * 6, 'socket rows of @04')
        w.remove_filler(0)
    char_edit('@04', change, ['r18 '] * 5, 'rune removed')


@T.test
def character_runeword_jewel_removed_runes_kept():
    """Runeword 152 (Tir + a jewel in 2 sockets): the jewel can be taken out, the rune stays; Empty sockets on a
    runeword takes out the jewels only."""
    def change(w):
        rows = w.filler_rows()
        T.eq([(r['code'], r['kind']) for r in rows], [('jew ', 'item')], 'socket rows of the runeword')
        w.clear_fillers()
        T.eq(w.filler_rows(), [], 'rows after Empty sockets')
    char_edit('152', change, ['r03 '], 'runeword jewel removed')


T.main(globals())
