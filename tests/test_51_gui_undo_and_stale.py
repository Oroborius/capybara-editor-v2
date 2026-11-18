"""Undo (Ctrl+Z, mxl_undo) of "Make perfect" and of the Item stats tab's edits, on a stash item ('stash'), on a
character item from the Stash tab's panel ('panel') and from the Character tab ('tab'): the file comes back byte
for byte, and an undo is refused when the file changed since. Stash only: Copy / Duplicate / Export from a window
that has not yet re-read a stash written behind its back copy nothing (they read the item by offset alone and could
take its neighbour), and the Item stats tab refuses to write over an item changed on disk.
docs/review/save-safety.md (F6 follow-up, F19 follow-up)."""
import os

import capytest as T

MODE = 'gui'
RESET = True
ALLOW_ERRORS = True
VARIANTS = {'stash': {'CAPY_TARGET': 'stash'}, 'panel': {'CAPY_TARGET': 'panel'}, 'tab': {'CAPY_TARGET': 'tab'}}
G = T.G
TARGET = os.environ.get('CAPY_TARGET', 'stash')
PLAIN = (39, 43, 41, 45, 80, 79, 0, 2, 3, 1, 31, 16, 7, 9, 60, 62, 119, 171)


def no_traceback(m):
    for e in T.errors_since(m):
        T.check('Traceback' not in e and 'Exception in Tkinter' not in e, 'traceback: ' + e)


def lone_plain(rec, parsed=None):
    import mxl_save
    ids = [s['id'] for s in rec['stats']]
    out = []
    for s in rec['stats']:
        if s['id'] not in PLAIN or s.get('param') or ids.count(s['id']) != 1:
            continue
        if parsed is not None:
            try:
                if len(mxl_save.linked_stats(parsed, s['id'], G.app.data, 'stats')) > 1:
                    continue
            except Exception:
                continue
        out.append(s['id'])
    return out


def char_view():
    if TARGET == 'tab':
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


class Target:
    """An item of the place under test with a menu opener; pred(rec, parsed_or_None) picks it."""

    def __init__(self, pred, what, bring=False):
        import mxl_creator as C
        import mxl_save
        app = G.app
        self.pick = None
        if TARGET == 'stash':
            self.path = app.path
            raw = T.read(app.path)
            for it in sorted(app.items, key=lambda i: (i['page'], i['y'], i['x'])):
                rec = T.rec_of(mxl_save.item_blob(raw, it))
                if not rec['flags'] & C.FLAG_SIMPLE and pred(rec, it, mxl_save.item_blob(raw, it)):
                    self.pick = (it['page'], it['x'], it['y'])
                    break
            self.menu = lambda: T.stash_menu(*self.pick)
        else:
            import mxl_char
            self.path = app.character_file()
            ch = mxl_char.Character(self.path, app.data)
            for e in ch.entries(False):            # worn items first, then the inventory
                if e.it.get('socketed_count'):
                    continue
                if e.it['location'] == mxl_char.LOC_EQUIPPED:
                    where = ('slot', e.it['equipped'])
                elif e.it['location'] == mxl_char.LOC_STORED and e.it.get('panel') == mxl_char.PANEL_INVENTORY:
                    where = ('inv', e.it['x'], e.it['y'])
                else:
                    continue
                rec = T.rec_of(e.blob)
                if not rec['flags'] & C.FLAG_SIMPLE and pred(rec, None, e.blob):
                    if self.pick is None or (self.pick[0] == 'inv' and where[0] == 'slot'):
                        self.pick = where

            def menu():
                char_view()
                return T.chartab_menu(self.pick) if TARGET == 'tab' else T.panel_menu(self.pick)
            self.menu = menu
        if self.pick is None and TARGET != 'stash' and bring:
            self.pick = self._bring(pred)               # a fitting stash item pasted into the inventory first
        if self.pick is None:
            T.skip(f'no {what} here')
        self.raw0 = T.read(self.path)

    def _bring(self, pred):
        import mxl_char
        import mxl_save
        app = G.app
        raw = T.read(app.path)
        src = next((it for it in app.items if app.data.base(it['code']).size == (1, 1)
                    and pred(T.rec_of(mxl_save.item_blob(raw, it)), None, mxl_save.item_blob(raw, it))), None)
        if src is None:
            return None
        ch = mxl_char.Character(self.path, app.data)
        used = set()
        for e in ch.inventory():
            w, h = app.data.base(e.it['code']).size
            used |= {(e.it['x'] + i, e.it['y'] + j) for i in range(w) for j in range(h)}
        cell = next((('inv', x, y) for y in range(mxl_char.INV_H) for x in range(mxl_char.INV_W)
                     if (x, y) not in used), None)
        if cell is None:
            return None
        T.invoke(T.stash_menu(src['page'], src['x'], src['y']), 'Copy')
        char_view()
        T.invoke(T.chartab_menu(cell) if TARGET == 'tab' else T.panel_menu(cell), 'Paste here')
        T.pump(6)
        return cell

    def tab(self):
        import mxl_he_stats as H
        import mxl_tabs
        T.invoke(self.menu(), 'Item stats...')
        T.pump()
        w = mxl_tabs.built_owner(H.TAB_KEY)
        if w is None:
            raise T.Failed('the Item stats tab did not open')
        return w


def undo_all(path, raw, what, most=3):
    """Ctrl+Z until the file is the original (at most `most` steps)."""
    import mxl_undo
    msgs = []
    for _k in range(most):
        if T.read(path) == raw:
            break
        msgs.append(mxl_undo.undo(G.app))
        T.pump(6)
    T.check(T.read(path) == raw, f'{what} then Ctrl+Z: the file is not the original ({msgs})')
    return len(msgs)


def stats_item(rec, parsed, blob):
    return len(rec['stats']) >= 2 and not rec.get('stats_runeword') and \
        rec['quality'] in ('magic', 'rare', 'unique', 'crafted') and bool(lone_plain(rec, parsed))


def editable(w, tgt):
    import mxl_he_stats as H
    rec = w.rec
    ok = lone_plain(rec)
    for i, s in enumerate(rec['stats']):
        rng = H.value_range(G.app.data, s['id'])
        if rng is None or s['id'] not in ok:
            continue
        return i, s['value'] + 1 if s['value'] + 1 <= rng[1] else s['value'] - 1
    T.skip('no plain stat to edit')


def set_value(w, i, v):
    n = w._find_slot('stats', i)
    w.select(n)
    w.edit_cell('value')
    w.ed_var.set(str(v))
    w._ed_done('save')
    T.pump()


@T.test
def item_stats_value_edit_then_undo():
    m0 = T.mark()
    tgt = Target(stats_item, 'magic / rare / unique item with a plain stat')
    w = tgt.tab()
    i, v = editable(w, tgt)
    orig = w.rec['stats'][i]['value']
    set_value(w, i, v)
    T.check(T.read(tgt.path) != tgt.raw0, 'the value edit wrote nothing')
    n = undo_all(tgt.path, tgt.raw0, 'Item stats value edit')
    T.eq(n, 1, 'undo steps for one value edit')
    T.pump(6)
    T.eq(w.rec['stats'][i]['value'], orig, 'the tab shows the value of after the undo')
    no_traceback(m0)


@T.test
def item_stats_add_value_and_clear_then_undo():
    """Add a stat (one write), give it a value (in-place / re-encode), clear another slot: three actions, three undo
    steps, the original bytes at the end."""
    m0 = T.mark()
    tgt = Target(stats_item, 'magic / rare / unique item with a plain stat')
    w = tgt.tab()
    have = {s['id'] for s in w.rec['stats']}
    sid = next((s for s in PLAIN if s not in have and G.app.data.isc.get(s, {}).get('bits')), None)
    if sid is None:
        T.skip('no plain stat to add')
    w.select(w._find_slot('stats', None))
    w.picked(sid)
    T.pump()
    if w._ed is not None:
        w.ed_var.set('7')
        w._ed_done('save')
    T.pump()
    w.select(w._find_slot('stats', 0))
    w.delete_selected()
    T.pump()
    T.check(T.read(tgt.path) != tgt.raw0, 'the edits wrote nothing')
    n = undo_all(tgt.path, tgt.raw0, 'add + value + clear', most=4)
    T.check(n <= 3, f'{n} undo steps for three actions')
    no_traceback(m0)


@T.test
def item_stats_param_edit_then_undo():
    """A stat with a parameter (chance to cast: skill + level) goes through the lossless re-encode: undone too."""
    import mxl_statnames as SN
    m0 = T.mark()
    tgt = Target(stats_item, 'magic / rare / unique item with a plain stat')
    w = tgt.tab()
    have = {s['id'] for s in w.rec['stats']}
    sid = next((s for s in SN.CHANCE_TO_CAST if s not in have), None)
    if sid is None:
        T.skip('no chance-to-cast stat free')
    w.select(w._find_slot('stats', None))
    w.picked(sid)
    T.pump()
    if w._pick_mode is not None:
        w._name_cancel()
    T.pump()
    n = next(k for k, r in enumerate(w.rows) if r['kind'] == 'slot' and r['s'] is not None and r['s']['id'] == sid)
    T.check(w._set_param(n, level=5) is not False, 'cast level not written')
    T.pump()
    undo_all(tgt.path, tgt.raw0, 'chance to cast + level', most=3)
    no_traceback(m0)


def perfectable(rec, parsed, blob):
    import mxl_perfect
    import mxl_save
    try:
        p = mxl_perfect.plan(mxl_save.blob_item(bytes(blob), G.app.data), G.app.data, G.app._creator
                             if getattr(G.app, '_creator', None) else _cr())
    except Exception:
        return False
    return bool(p['changes'])


def _cr():
    import mxl_rc_menu as RC
    return RC._creator(G.app)


@T.test
def make_perfect_then_undo():
    m0 = T.mark()
    tgt = Target(perfectable, 'item with a roll below its maximum', bring=True)
    T.invoke(tgt.menu(), 'Make perfect', under='Specific editing functions')
    T.pump(6)
    T.check(T.read(tgt.path) != tgt.raw0, 'Make perfect wrote nothing')
    T.eq(undo_all(tgt.path, tgt.raw0, 'Make perfect'), 1, 'undo steps')
    no_traceback(m0)


@T.test
def undo_is_refused_after_the_file_changed():
    """Make perfect, then another writer changes the file (another item / a stat-screen value): Ctrl+Z must not
    write anything over it - the file stays exactly as the other writer left it."""
    import mxl_undo
    m0 = T.mark()
    tgt = Target(perfectable, 'item with a roll below its maximum', bring=True)
    T.invoke(tgt.menu(), 'Make perfect', under='Specific editing functions')
    T.pump(6)
    written = T.read(tgt.path)
    T.check(written != tgt.raw0, 'Make perfect wrote nothing')
    other = third_state(tgt)
    T.check(other not in (written, tgt.raw0), 'the outside change is not a third state')
    with open(tgt.path, 'wb') as f:          # the other writer (no editor code)
        f.write(other)
    msg = mxl_undo.undo(G.app)
    T.pump(6)
    T.check(T.read(tgt.path) == bytes(other), f'the undo wrote over a file changed since ({msg})')
    T.check(msg and 'not undone' in msg, f'undo message: {msg!r}')
    no_traceback(m0)


def third_state(tgt):
    """The file as another writer would leave it after the action: on the stash the item itself changed again (a
    stash undo works per item: a change to ANOTHER item does not stop it), on the character one stat point more /
    less (a character undo needs the whole file as written). Neither the bytes of before nor those of after."""
    import mxl_save
    import mxl_creator as C
    app = G.app
    raw = T.read(tgt.path)
    if TARGET == 'stash':
        items = mxl_save.parse_stash(tgt.path, app.data)
        blobs = mxl_save.stash_blobs(raw, items)
        cur = next(x for x in items if (x['page'], x['x'], x['y']) == tgt.pick)
        blob = bytes(mxl_save.item_blob(raw, cur))
        rec, size = C.decode_item(blob, app.data)
        s0 = rec['stats'][0]
        rec['stats'][0] = dict(s0, value=s0['value'] - 1 if s0['value'] > 0 else s0['value'] + 1)
        here = [x['_offset'] for x in items if x['page'] == cur['page']]
        blobs[cur['page']][here.index(cur['_offset'])] = C.encode_item(rec, app.data) + blob[size:]
        return mxl_save.build_stash(raw[:8], blobs)
    import mxl_char
    ch = mxl_char.Character(tgt.path, app.data)
    v = ch.field('stat_points')
    ch.set_field('stat_points', v + 1 if v + 1 <= ch.stat_field('stat_points').max else v - 1)
    return bytes(ch.build())


def other_value(sid, *avoid):
    import mxl_he_stats as H
    lo, hi = H.value_range(G.app.data, sid)
    base = avoid[0]
    for d in (2, -2, 3, -3, 1, -1, 4, -4):
        if lo <= base + d <= hi and base + d not in avoid:
            return base + d
    T.skip('no value to type')


# ------------------------------------------------------------------ stash: out-of-date view
def stale_pair():
    """Writes the stash behind the window's back with one more item on its first page; returns (neighbour, victim)
    as the window still shows them: same size, the victim's old offset is now the neighbour's."""
    import mxl_save
    from mxl_format import write_bits
    app = G.app
    path = app.path
    raw = T.read(path)
    items = list(app.items)
    pages = sorted({i['page'] for i in items})
    later = [i for i in items if i['page'] == pages[-1]]
    k = next((k for k in range(1, len(later)) if later[k - 1]['_size'] == later[k]['_size']
              and not later[k - 1].get('socketed') and not later[k].get('socketed')
              and bytes(mxl_save.item_blob(raw, later[k - 1])) != bytes(mxl_save.item_blob(raw, later[k]))), None)
    if k is None or len(pages) < 2:
        T.skip('no two different neighbours of the same size on a later page')
    prev, victim = later[k - 1], later[k]
    blob = bytes(mxl_save.item_blob(raw, prev))
    new = mxl_save.blob_item(blob, app.data)
    spot = mxl_save.free_spot(items, new, app.data, [pages[0]])
    b = bytearray(blob)
    write_bits(b, 16 + new['_pos_bit'], 4, spot[1])
    write_bits(b, 16 + new['_pos_bit'] + 4, 4, spot[2])
    blobs = mxl_save.stash_blobs(raw, mxl_save.parse_stash(path, app.data))
    blobs[spot[0]].append(bytes(b))
    with open(path, 'wb') as f:
        f.write(mxl_save.build_stash(raw[:8], blobs))
    return prev, victim, blob, bytes(mxl_save.item_blob(raw, victim))


@T.test
def copy_duplicate_export_from_an_out_of_date_view_take_nothing():
    if TARGET != 'stash':
        T.skip('stash grid: one variant is enough')
    import mxl_rc_menu as RC
    m0 = T.mark()
    app = G.app
    for action in ('copy', 'duplicate', 'export'):
        T.reset()
        T.pump(6)
        app._capy_clip = None
        prev, victim, nblob, vblob = stale_pair()
        written = T.read(app.path)
        out = os.path.join(T.tmp(), f'export-{action}.d2i')
        if action == 'copy':
            RC._copy(app, victim)
            clip = getattr(app, '_capy_clip', None)
            T.check(clip is None or clip[0] == vblob, 'Copy took the neighbour\'s bytes')
        elif action == 'duplicate':
            RC._duplicate(app, victim)
        else:
            G.answers['file'] = out
            try:
                RC._export_stash(app, victim)
            finally:
                G.answers.pop('file', None)
            if os.path.exists(out):
                T.check(T.read(out) == vblob, 'Export wrote the neighbour\'s bytes')
        T.pump(6)
        T.check(T.read(app.path) == written, f'{action} from an out-of-date view wrote the stash')
        T.check('changed on disk' in T.status_text() or action == 'copy' and app._capy_clip is None,
                f'{action}: status {T.status_text()!r}')
    no_traceback(m0)


@T.test
def item_stats_tab_refuses_an_item_changed_on_disk():
    """The tab shows an item; another writer changes that item; a value typed in the tab is not written over it
    (the rows are read again). The item moving in the file (another item added before it) is not a change: the
    edit goes to the right item."""
    if TARGET != 'stash':
        T.skip('stash grid: one variant is enough')
    import mxl_save
    import mxl_creator as C
    m0 = T.mark()
    app = G.app
    tgt = Target(stats_item, 'magic / rare / unique item with a plain stat')
    w = tgt.tab()
    i, v = editable(w, tgt)
    # another writer changes the item itself (one stat + 1 / - 1, through the codec)
    raw = T.read(app.path)
    items = mxl_save.parse_stash(app.path, app.data)
    cur = next(x for x in items if (x['page'], x['x'], x['y']) == tgt.pick)
    blob = bytes(mxl_save.item_blob(raw, cur))
    rec, size = C.decode_item(blob, app.data)
    rec['stats'][i] = dict(rec['stats'][i], value=v)
    new = C.encode_item(rec, app.data) + blob[size:]
    blobs = mxl_save.stash_blobs(raw, items)
    lst = blobs[cur['page']]
    lst[[x['_offset'] for x in items if x['page'] == cur['page']].index(cur['_offset'])] = new
    outside = mxl_save.build_stash(raw[:8], blobs)
    with open(app.path, 'wb') as f:
        f.write(outside)
    shown = w.rec['stats'][i]['value']
    set_value(w, i, other_value(w.rec['stats'][i]['id'], shown, v))
    T.pump(6)
    T.check(T.read(app.path) == outside, 'the tab wrote over an item changed on disk')
    T.check('changed on disk' in str(w.bar['text']), f'tab status: {w.bar["text"]!r}')
    T.eq(w.rec['stats'][i]['value'], v, 'the tab shows the value on disk now')
    no_traceback(m0)



@T.test
def item_stats_edit_goes_to_the_moved_item():
    """Another writer adds an item before the tab's item (its offset moves, its bytes stay): before the window
    re-reads, a value edit and a slot clear in the tab reach that item - or are refused - and never its
    neighbour; the only other change is the outside one."""
    if TARGET != 'stash':
        T.skip('stash grid: one variant is enough')
    import mxl_save
    m0 = T.mark()
    app = G.app
    tgt = Target(stats_item, 'magic / rare / unique item with a plain stat')
    w = tgt.tab()
    i, _v = editable(w, tgt)
    raw = T.read(app.path)
    items = mxl_save.parse_stash(app.path, app.data)
    blobs = mxl_save.stash_blobs(raw, items)
    first = min(blobs)
    donor = next((x for x in items if x['page'] == first and (x['page'], x['x'], x['y']) != tgt.pick), None)
    spot = mxl_save.free_spot(items, mxl_save.blob_item(bytes(mxl_save.item_blob(raw, donor)), app.data), app.data,
                              [first]) if donor else None
    if spot is None or tgt.pick[0] < first:
        T.skip('no place for an outside item before the tab\'s item')
    from mxl_format import write_bits
    b = bytearray(mxl_save.item_blob(raw, donor))
    probe = mxl_save.blob_item(bytes(b), app.data)
    write_bits(b, 16 + probe['_pos_bit'], 4, spot[1])
    write_bits(b, 16 + probe['_pos_bit'] + 4, 4, spot[2])
    blobs[first].insert(0, bytes(b))                 # first in the file: every later offset moves
    with open(app.path, 'wb') as f:
        f.write(mxl_save.build_stash(raw[:8], blobs))
    before = {(x['page'], x['x'], x['y']): bytes(mxl_save.item_blob(T.read(app.path), x))
              for x in mxl_save.parse_stash(app.path, app.data)}

    def others_unchanged(what):
        now_raw = T.read(app.path)
        now = {(x['page'], x['x'], x['y']): bytes(mxl_save.item_blob(now_raw, x))
               for x in mxl_save.parse_stash(app.path, app.data)}
        T.eq(sorted(now), sorted(before), f'{what}: places of the items')
        for k in before:
            if k != tgt.pick:
                T.check(now.get(k) == before[k], f'{what}: the item at {k} changed')
        return now
    shown = w.rec['stats'][i]['value']
    typed = other_value(w.rec['stats'][i]['id'], shown)
    set_value(w, i, typed)
    T.pump(6)
    now = others_unchanged('value edit')
    print('  value edit on the moved item:', 'written' if now[tgt.pick] != before[tgt.pick] else 'refused')
    if now[tgt.pick] != before[tgt.pick]:
        T.eq(T.rec_of(now[tgt.pick])['stats'][i]['value'], typed, 'the value written into the item')
    else:
        T.check('not written' in str(w.bar['text']), f'nothing written and no refusal: {w.bar["text"]!r}')
    before = {k: v for k, v in now.items()}
    w.select(w._find_slot('stats', 0))
    w.delete_selected()
    T.pump(6)
    others_unchanged('slot clear')
    no_traceback(m0)


@T.test
def typed_values_survive_a_delete_elsewhere():
    """A value typed but not saved (Down arrow) stays pending when another stash item is deleted (the main
    window's refresh after a Delete / an undo does not reset the tab unless its own item changed)."""
    import mxl_undo
    m0 = T.mark()
    tgt = Target(stats_item, 'magic / rare / unique item with a plain stat')
    w = tgt.tab()
    i, v = editable(w, tgt)
    w.select(w._find_slot('stats', i))
    w.edit_cell('value')
    w.ed_var.set(str(v))
    w._ed_done('down')
    T.pump()
    pending = dict(w.pending)
    T.check(pending, 'the typed value is not pending')
    app = G.app
    victim = next((x for x in app.items if TARGET != 'stash' or (x['page'], x['x'], x['y']) != tgt.pick), None)
    if victim is None:
        T.skip('no other stash item')
    mxl_undo.delete_item(app, victim)
    T.pump(10)
    T.eq(w.pending, pending, 'typed values after a Delete of another item')
    mxl_undo.undo(app)
    T.pump(10)
    T.eq(w.pending, pending, 'typed values after the undo of that Delete')
    no_traceback(m0)


T.main(globals())
