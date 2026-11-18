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
G = T.G
SHOTS = os.environ.get('CAPY_SHOTS')


def shot(name):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    G.root.update()
    try:
        subprocess.run(['import', '-window', 'root', os.path.join(SHOTS, f'sockets-{name}.png')], timeout=30,
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
    import mxl_savecheck
    (rec, kids), it = entry(key)
    T.check(rec['flags'] & C.FLAG_SOCKETED, f'{what}: socketed flag lost')
    T.eq(rec.get('sockets'), 3, f'{what}: socket count (removing fillers empties sockets, it does not take them away)')
    T.eq(rec.get('socketed_count'), len(kids), f'{what}: socketed-item count vs children behind the item')
    T.eq(len(it.get('socketed') or ()), len(kids), f'{what}: children the application reads')
    T.eq([k.get('x') for k in kids], list(range(len(kids))), f'{what}: places of the children')
    r = mxl_savecheck.examine(G.app.path, T.read(G.app.path))
    T.check(r.ok, f'{what}: the save check refuses the stash: {r.problems}')
    home = os.path.dirname(os.path.abspath(mxl_savecheck.lib().__file__))
    p = subprocess.run([sys.executable, '-m', 'mxlsave', 'verify', G.app.path, '--user-dir', G.user_dir],
                       cwd=os.path.dirname(home), capture_output=True, text=True, timeout=120)
    T.check(p.returncode == 0, f'{what}: mxlsave verify: {(p.stdout + p.stderr).strip()[-300:]}')
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


T.main(globals())
