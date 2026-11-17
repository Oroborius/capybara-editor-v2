"""'Fill sockets with ...' (mxl_rc_menu) on character and mercenary items, in both places that have the menu: the
equipment / inventory panel of the Stash tab ('panel') and the Character tab ('tab'). The stash side of the action is
in test_31. The gem is created with the creator, written into the stash and copied with the stash menu.

Every item in menu reach is classified by its own record and the game tables (free sockets / no sockets but a
socketable base / full but below the base's limit / at the limit / cannot have sockets); the menu must agree, and
one item of each class is filled: the character file re-read from disk has the item changed as asked, every other
item byte-identical, and passes the application's save check and `python -m mxlsave verify`."""
import os
import subprocess
import sys

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'panel': {'CAPY_HOLDER': 'panel'}, 'tab': {'CAPY_HOLDER': 'tab'}}
G = T.G
HOLDER = os.environ.get('CAPY_HOLDER', 'panel')
SLOT, INV = 1, 0                      # item location codes of the save format: equipped, stored
LIMIT = 6                             # sockets the game shows on an item


def view(merc=False):
    if HOLDER == 'tab':
        cw = T.chartab()
        if 'Character' not in str(T.tab_names()) or cw is None:
            raise T.Failed('no Character tab')
        T.select_tab('Character')
        if cw.tab.get() != 'inventory':
            cw.tab.set('inventory')
            cw.show_tab()
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


def where_of(it):
    if it['location'] == SLOT:
        return ('slot', it['equipped'])
    if it['location'] == INV and it.get('panel') == 1:
        return ('inv', it['x'], it['y'])
    return None


def key_of(where, merc=False):
    return (merc, SLOT, where[1], where[1], 0, 0) if where[0] == 'slot' else (merc, INV, 0, where[1], where[2], 1)


def unrestricted(on):
    import settings
    was = settings.get('capy_unrestricted')
    settings.put('capy_unrestricted', on)
    return was


def copy_a_gem():
    """A gem / rune made by the creator, written into the stash, copied with the stash menu. Returns its bytes."""
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
    return blob


def seed_inventory(sockets):
    """Writes a plain armor with `sockets` empty sockets into a free place of the character's inventory (the
    sample character wears nothing that can take a gem) and makes the windows read the file again. Returns its
    place, or None when the inventory has no room."""
    import mxl_char
    import mxl_rc_menu
    cr = mxl_rc_menu._creator(G.app)
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    used = set()
    for e in ch.inventory():
        w, h = G.app.data.base(e.it['code']).size
        used |= {(e.it['x'] + i, e.it['y'] + j) for i in range(w) for j in range(h)}
    bases = sorted((b for b in cr.bases() if b.kind == 'armor' and cr.max_sockets(b.code, 99) >= 3),
                   key=lambda b: (b.size[0] * b.size[1], b.code))
    import mxl_creator
    for base in bases:
        w, h = base.size
        spec = cr.new_spec('normal', base.code)
        spec['ilvl'] = 99
        spec['sockets'] = sockets
        spec['max_sockets'] = False
        try:
            blob = bytes(cr.build(spec)[0])
        except mxl_creator.CreateError:               # e.g. a base that needs its innate affix chosen
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
    return None


def classify(merc):
    """{class: [(where, sockets, socketed, cap)]} of the items in menu reach, from a fresh read of the file."""
    import mxl_char
    import mxl_creator as C
    import mxl_rc_menu
    cr = mxl_rc_menu._creator(G.app)
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    out = {'free': [], 'unsocketed': [], 'full_room': [], 'limit': [], 'never': []}
    if merc and ch.merc_items is None:
        return out
    for e in ch.entries(merc):
        where = where_of(e.it)
        if where is None or merc and where[0] != 'slot':
            continue
        rec, kids = mxl_rc_menu._children_blobs(bytes(e.blob), G.app.data)
        if rec['flags'] & C.FLAG_SIMPLE:
            out['never'].append((where, 0, 0, 0))
            continue
        cap = min(cr.max_sockets(e.it['code'], rec['ilvl']), LIMIT)
        socketed = bool(rec['flags'] & C.FLAG_SOCKETED)
        sockets = rec.get('sockets', 0) if socketed else 0
        row = (where, sockets, len(kids), cap)
        if sockets > len(kids):
            out['free'].append(row)
        elif rec['flags'] & C.FLAG_RUNEWORD or cap <= sockets:
            out['limit' if socketed else 'never'].append(row)
        else:
            out['full_room' if socketed else 'unsocketed'].append(row)
    return out


class Ctx:
    def __init__(self):
        self.path = G.app.character_file()
        self.snap = T.char_snap(self.path, G.app.data)
        self.raw = T.read(self.path)
        self.stash = T.read(G.app.path)

    def after(self, chg=(), what=''):
        T.pump()
        raw = T.read(self.path)
        for problem in T.d2s_header_ok(raw):
            T.check(False, f'{what}: character file {problem}')
        now = T.char_snap(self.path, G.app.data)
        T.only_changed(self.snap, now, (), (), chg, what)
        T.check(T.read(G.app.path) == self.stash, f'{what}: the stash file changed')
        import mxl_char
        T.check(mxl_char.Character(self.path, G.app.data).build() == raw, f'{what}: the written character does not rebuild identically')
        shown = G.app.inventory.ch
        T.check(shown is not None and bytes(shown.raw) == raw, f'{what}: the Stash tab panel does not show the file on disk')
        cw = T.chartab()
        if HOLDER == 'tab' and cw is not None:
            T.check(bytes(cw.ch.raw) == raw, f'{what}: the Character tab does not hold the file on disk')
        return now


def verified(path, what):
    import mxl_savecheck
    r = mxl_savecheck.examine(path, T.read(path))
    T.check(r.ok, f'{what}: the save check refuses the file: {r.problems}')
    home = os.path.dirname(os.path.abspath(mxl_savecheck.lib().__file__))
    p = subprocess.run([sys.executable, '-m', 'mxlsave', 'verify', path, '--user-dir', G.user_dir],
                       cwd=os.path.dirname(home), capture_output=True, text=True, timeout=120)
    T.check(p.returncode == 0, f'{what}: mxlsave verify: {(p.stdout + p.stderr).strip()[-300:]}')


def in_reach(rows, merc):
    """The rows whose place is shown (the second weapon set's slots are not)."""
    view(merc)
    out = []
    for row in rows:
        try:
            T.chartab_ev(row[0]) if HOLDER == 'tab' else T.panel_ev(row[0])
            out.append(row)
        except StopIteration:
            pass
    return out


def fill_labels(where, merc):
    return [x for x in T.menu_labels(menu(where, merc)) if x.startswith('Fill sockets')]


def fill_and_check(c, gem, where, merc, n_after, sockets_after, label_part, what):
    """Invokes the entry on one item and checks the file; the context's snapshot moves on to the new state."""
    import mxl_creator as C
    import mxl_rc_menu
    key = key_of(where, merc)
    lab = T.invoke(menu(where, merc), 'Fill sockets with')
    T.check(label_part in lab, f'{what}: menu label {lab!r}, expected {label_part!r}')
    now = c.after(chg=[key], what=what)
    if key not in now or now[key] == c.snap[key]:
        T.check(False, f'{what}: the item did not change (status {T.status_text()!r})')
        return now
    rec, kids = mxl_rc_menu._children_blobs(now[key][1], G.app.data)
    r0, kids0 = mxl_rc_menu._children_blobs(c.snap[key][1], G.app.data)
    T.check(rec['flags'] & C.FLAG_SOCKETED, f'{what}: socketed flag not set')
    T.eq((rec.get('sockets'), rec.get('socketed_count'), len(kids)), (sockets_after, n_after, n_after),
         f'{what}: (sockets, socketed count, socketed items)')
    T.eq(kids[:len(kids0)], kids0, f'{what}: the items that were socketed before')
    want = T.record(gem)[0]
    for i, k in enumerate(kids[len(kids0):], len(kids0)):
        T.eq(T.record(k)[0], want, f'{what}: socketed copy {i} vs the copied gem')
        kr = T.rec_of(k)
        T.eq((kr['location'], kr['x']), (C.LOC_SOCKETED, i), f'{what}: place of socketed copy {i}')
    skip = ('flags', 'sockets', 'socketed_count')
    T.eq({k: v for k, v in rec.items() if k not in skip}, {k: v for k, v in r0.items() if k not in skip}, f'{what}: other fields of the item')
    T.eq(rec['flags'] & ~C.FLAG_SOCKETED, r0['flags'] & ~C.FLAG_SOCKETED, f'{what}: other flags of the item')
    verified(c.path, what)
    c.snap = now
    return now


def run(merc):
    import mxl_rc_menu
    who = 'mercenary' if merc else 'character'
    was = unrestricted(False)
    try:
        gem = copy_a_gem()
        if not merc:
            seed_inventory(0)
            seed_inventory(2)
        cls = {k: in_reach(v, merc) for k, v in classify(merc).items()}
        counts = {k: len(v) for k, v in cls.items()}
        if not any(cls.values()):
            T.skip(f'the sample has no {who} items')
        c = Ctx()
        # the menu agrees with the item, for every item in reach; nothing is written by opening menus
        for name, rows in cls.items():
            for where, sockets, n, cap in rows:
                labs = fill_labels(where, merc)
                if name == 'free':
                    ok = len(labs) == 1 and f'(now {n} of {sockets})' in labs[0]
                elif name in ('unsocketed', 'full_room'):
                    ok = len(labs) == 1 and f'(adds {cap - sockets} sockets: {n} of {cap})' in labs[0]
                else:
                    ok = labs == []
                T.check(ok, f'{who} item at {where} ({name}: {sockets} sockets, {n} socketed, base allows {cap}): menu {labs}')
        T.check(T.read(c.path) == c.raw, 'opening menus changed the character file')
        # the action itself refuses where no entry is shown, and writes nothing
        done = []
        for name in ('limit', 'never'):
            if not cls[name]:
                continue
            where = cls[name][0][0]
            view(merc)
            win = T.chartab() if HOLDER == 'tab' else G.app.inventory.as_win()
            e = next((x for x in win.ch.entries(merc) if where_of(x.it) == where), None)
            if e is None:
                T.check(False, f'{who}: no entry at {where} in the window')
                continue
            mxl_rc_menu._fill_sockets(win, None, win=win, e=e)
            T.pump()
            T.check(T.read(c.path) == c.raw, f'{who}: a refused fill ({name}) at {where} wrote the character file')
            done.append(name + ' (refused)')
        if cls['free']:
            where, sockets, n, cap = cls['free'][0]
            fill_and_check(c, gem, where, merc, sockets, sockets, f'(now {n} of {sockets})', f'{who}: fill free sockets at {where}')
            done.append('free')
            if cap > sockets and not T.rec_of(c.snap[key_of(where, merc)][1])['flags'] & 0x4000000:    # not a runeword
                fill_and_check(c, gem, where, merc, cap, cap, f'(adds {cap - sockets} sockets: {sockets} of {cap})',
                               f'{who}: fill the now full item at {where}')
                T.eq(fill_labels(where, merc), [], f'{who}: Fill entry on the item now at its limit')
                done.append('full, sockets added')
        if cls['unsocketed']:
            where, sockets, n, cap = cls['unsocketed'][0]
            fill_and_check(c, gem, where, merc, cap, cap, f'(adds {cap} sockets', f'{who}: fill an unsocketed item at {where}')
            T.eq(fill_labels(where, merc), [], f'{who}: Fill entry on the item now at its limit')
            done.append('unsocketed')
        if cls['full_room']:
            where, sockets, n, cap = cls['full_room'][0]
            fill_and_check(c, gem, where, merc, cap, cap, f'(adds {cap - sockets} sockets', f'{who}: fill a full item at {where}')
            done.append('full_room')
        print(f'      {who} [{HOLDER}]: tested {done}; items per class {counts}')
        if not {'free', 'unsocketed', 'full_room'} & set(done):
            T.skip(f'no {who} item in menu reach can take a socketed item (items per class: {counts})')
    finally:
        unrestricted(was)


@T.test
def fill_sockets_on_character_items():
    run(False)


@T.test
def fill_sockets_on_mercenary_items():
    run(True)


@T.test
def fill_sockets_unrestricted_on_a_character_item():
    """Unrestricted on: an equipped weapon / armor without a free socket and below 6 goes to 6."""
    import mxl_creator as C
    was = unrestricted(False)
    try:
        gem = copy_a_gem()
        cls = {k: in_reach(v, False) for k, v in classify(False).items()}
        rows = [r for name in ('never', 'limit', 'unsocketed', 'full_room') for r in cls[name]
                if r[0][0] == 'slot' and r[3] < LIMIT]
        c = Ctx()
        pick = None
        for where, sockets, n, cap in rows:
            code, blob = c.snap[key_of(where)]
            rec = T.rec_of(blob)
            if G.app.data.base(code).kind in ('armor', 'weapons') and not rec['flags'] & (C.FLAG_SIMPLE | C.FLAG_RUNEWORD) \
                    and n >= sockets and n < LIMIT:
                pick = (where, sockets, n, cap)
                break
        if pick is None:
            T.skip('no equipped weapon / armor below 6 sockets without a free socket')
        where, sockets, n, cap = pick
        before = fill_labels(where, False)
        T.check(not before or f'{n} of {cap})' in before[0], f'restricted menu {before}; the base allows {cap}')
        unrestricted(True)
        fill_and_check(c, gem, where, False, LIMIT, LIMIT, f'(adds {LIMIT - sockets} sockets: {n} of {LIMIT})', f'unrestricted fill at {where}')
    finally:
        unrestricted(was)


T.main(globals())
