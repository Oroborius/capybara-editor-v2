"""The Creator tab (mxl_creator_gui.CreatorWindow) driven like a user: quality, list, search, rolls, Create; the
Item Editor (edit mode) with a changed roll; honorific creation; undo. Checked on the stash re-read from disk."""
import capytest as T

MODE = 'gui'
RESET = True
G = T.G


def creator():
    """A new Creator window in the Creator tab (an earlier test may have left the Item Editor there)."""
    import mxl_creator_gui as CG
    import mxl_tabs
    CG.CreatorWindow(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    if w is None or w.edit_item is not None:
        raise T.Failed('no Creator window')
    T.select_tab('Stash')
    return w


def set_quality(w, key):
    import mxl_creator_gui as CG
    w.search.set('')
    w.quality.set(dict((k, lab) for lab, k in CG.qualities())[key])
    w.on_quality()
    T.pump()
    T.eq(w.qkey(), key, 'quality shown by the Creator')


def pick(w, index):
    w.listbox.selection_clear(0, 'end')
    w.listbox.selection_set(index)
    w.listbox.see(index)
    w.on_pick()
    T.pump(8)
    if w.spec is None:
        raise T.Failed(f'picking list entry {index} ({w.entries[index][0]!r}) gave no item')


def pick_unique_armor(w, variable=3):
    """Picks a unique armor with a few variable rolls; returns its list label."""
    set_quality(w, 'unique')
    cr = w.cr
    for i, (label, row) in enumerate(w.entries):
        u = G.app.data.uniques[row]
        if u['code'] == 'cotw' or G.app.data.base(u['code']).kind != 'armor':
            continue
        spec = cr.new_spec('unique', row=row)
        if len([m for m in cr.mods(spec) if m.variable and m.min != m.max]) >= variable:
            pick(w, i)
            return label
    raise T.Failed('no unique armor with variable rolls in the list')


class Stash:
    def __init__(self):
        self.path = G.app.path
        self.snap = T.stash_snap(self.path, G.app.data)
        self.char = T.read(G.app.character_file())

    def after(self, gone=(), new=(), chg=(), what=''):
        T.pump()
        now = T.stash_snap(self.path, G.app.data)
        T.only_changed(self.snap, now, gone, new, chg, what)
        T.check(T.read(G.app.character_file()) == self.char, f'{what}: the character file changed')
        return now

    def added(self, what):
        """The one key added since the snapshot (everything else unchanged)."""
        T.pump()
        now = T.stash_snap(self.path, G.app.data)
        g, new, chg = T.diff(self.snap, now)
        T.eq((g, chg, len(new)), ([], [], 1), f'{what}: (removed, changed, number added)')
        if len(new) != 1:
            raise T.Failed(f'{what}: {len(new)} items added')
        return new[0], now


def same_but_id(a, b):
    """Same item apart from its place and its random item id (every build of the creator draws a new id)."""
    ra, ka = T.record(a)
    rb, kb = T.record(b)
    ra.pop('id', None)
    rb.pop('id', None)
    return ra == rb and len(ka) == len(kb)


def commit(w):
    w.commit()
    T.pump(8)
    for kind, title, msg in G.boxes:
        if kind == 'showerror':
            raise T.Failed(f'error box {title!r}: {msg[:200]}')


@T.test
def quality_lists_fill():
    import mxl_creator_gui as CG
    w = creator()
    keys = [k for _lab, k in CG.qualities()]
    for want in ('normal', 'magic', 'rare', 'crafted', 'set', 'unique', 'runeword', 'tempered'):
        T.check(want in keys, f'quality {want!r} missing from the Creator: {keys}')
    T.check('Honorific' in [lab for lab, _k in CG.qualities()], f'no "Honorific" label: {[lab for lab, _k in CG.qualities()]}')
    floor = dict(normal=1500, magic=500, rare=500, set=150, unique=1500, runeword=200, tempered=500)
    for key in keys:
        set_quality(w, key)
        T.check(len(w.entries) >= floor.get(key, 1), f'{key}: {len(w.entries)} list entries')
        T.eq(w.listbox.size(), len(w.entries), f'{key}: rows in the listbox')
        labels = [lab for lab, _k in w.entries]
        T.check(all(lab.strip() for lab in labels), f'{key}: an empty label')


@T.test
def relic_labels_in_the_list():
    w = creator()
    set_quality(w, 'unique')
    labels = [lab for lab, _row in w.entries]
    relics = [lab for lab in labels if lab.startswith('Relic - ')]
    T.check(len(relics) > 200, f'only {len(relics)} relics in the list')
    T.eq(labels.count('Relic - Bladestorm'), 1, '"Relic - Bladestorm" entries')
    T.eq(labels.count('Relic - Relic'), 0, '"Relic - Relic" entries (rows without a granted skill must be hidden)')
    i = labels.index('Relic - Bladestorm')
    pick(w, i)
    T.eq(w.spec['code'], 'cotw', 'base of the picked relic')
    lines = [''.join(t for _c, t in ln) for ln in __import__('mxl_tooltip').item_tooltip(
        __import__('mxl_save').blob_item(bytes(w.current_blob()[0]), G.app.data), G.app.data)]
    T.check(any('Bladestorm' in ln for ln in lines), f'the relic\'s tooltip does not mention Bladestorm: {lines[:6]}')


@T.test
def search_by_name_and_by_bonus():
    w = creator()
    set_quality(w, 'unique')
    total = len(w.entries)
    w.search.set('arrogan')
    T.pump()
    T.check(0 < len(w.entries) < 10 and any(lab.startswith('Arrogance') for lab, _r in w.entries),
            f'"arrogan" lists {[lab for lab, _r in w.entries][:5]}')
    w.search.set('stormlord')                       # not in any name: only the bonus text can match
    T.wait_for(lambda: getattr(w.cr, '_bonus_done', False), 60, 'the bonus-text index')
    T.pump(6)
    labels = [lab for lab, _r in w.entries]
    T.check(any(lab.startswith('Arrogance') for lab in labels), f'"stormlord" lists {labels[:6]} - Arrogance is not among them')
    T.check(len(labels) < 40, f'"stormlord" lists {len(labels)} uniques')
    T.eq(w.listbox.size(), len(labels), 'rows in the listbox')
    w.search.set('zzzz-nothing')
    T.pump()
    T.eq(len(w.entries), 0, 'entries for a text nothing matches')
    w.search.set('')
    T.pump()
    T.eq(len(w.entries), total, 'entries after clearing the search')
    set_quality(w, 'set')
    w.search.set('amulet')
    T.pump()
    T.check(len(w.entries) > 0, 'set items: "amulet" finds nothing')


@T.test
def create_unique_at_min_and_at_max():
    w = creator()
    label = pick_unique_armor(w)
    made = {}
    for how in ('min', 'max'):
        s = Stash()
        w.reroll(how)
        T.pump()
        mods = [m for m in w.cr.mods(w.spec) if m.variable and m.min != m.max]
        for m in mods:
            T.eq(w.spec['rolls'][m.source], m.min if how == 'min' else m.max, f'{how}: roll of {m.source}')
            if m.source in w.number_rows:
                T.eq(int(w.number_rows[m.source].get()), w.spec['rolls'][m.source], f'{how}: number shown for {m.source}')
        blob, rec = w.current_blob()
        commit(w)
        key, now = s.added(f'create {label} ({how})')
        it = T.stash_items(s.path, G.app.data)[key]
        T.eq((it['quality'], it['code']), ('unique', w.spec['code']), f'{how}: (quality, base) on disk')
        T.eq(T.stats_of(it), T.stats_of(rec), f'{how}: stats on disk vs stats of the preview')
        T.check(same_but_id(now[key][1], blob), f'{how}: the item on disk is not the previewed item')
        T.eq(key[0], G.app.page(), f'{how}: created on the stash page being shown')
        T.check('created' in T.status_text(), f'{how}: status {T.status_text()!r}')
        T.eq(G.app.selected and (G.app.selected['page'], G.app.selected['x'], G.app.selected['y']), key, f'{how}: the new item is selected')
        made[how] = dict(((a, b), c) for a, b, c in T.stats_of(it))
    T.eq(sorted(made['min']), sorted(made['max']), 'stat ids of the two items')
    T.check(all(made['min'][k] <= made['max'][k] for k in made['min']) and made['min'] != made['max'],
            'the minimum item is not below the maximum item')


@T.test
def typed_roll_is_written():
    """A number typed into a roll row (then Enter) is the roll of the created item; out of range is clamped."""
    w = creator()
    pick_unique_armor(w)
    m = next(m for m in w.cr.mods(w.spec) if m.variable and m.max - m.min >= 2 and m.source in w.number_rows)
    row = w.number_rows[m.source]
    T.eq(tuple(row.value_range), (m.min, m.max), 'range of the number row')
    T.select_tab('Creator')                         # typing needs the field on screen
    w.scroll.canvas.update_idletasks()
    row.focus_force()
    T.settle(0.2)
    row.delete(0, 'end')
    row.insert(0, str(m.min + 1))
    row.event_generate('<Return>')
    T.settle(0.3)
    T.eq(w.spec['rolls'][m.source], m.min + 1, 'roll after typing min + 1')
    row.delete(0, 'end')
    row.insert(0, str(m.max + 5000))
    row.event_generate('<Return>')
    T.settle(0.3)
    row = w.number_rows[m.source]                   # the options are drawn again after a change
    T.eq((w.spec['rolls'][m.source], int(row.get())), (m.max, m.max), '(roll, number shown) after typing far above the range')
    row.set_value(m.min + 1)
    T.pump(2)
    s = Stash()
    blob, rec = w.current_blob()
    commit(w)
    key, now = s.added('create with a typed roll')
    it = T.stash_items(s.path, G.app.data)[key]
    T.eq(T.stats_of(it), T.stats_of(rec), 'stats on disk vs preview')
    T.eq(w.cr.spec_from_item(it)['rolls'].get(m.source), m.min + 1, 'roll read back from the item on disk')


@T.test
def create_then_undo():
    import mxl_undo
    w = creator()
    pick_unique_armor(w)
    s = Stash()
    commit(w)
    key, _now = s.added('create')
    T.check(mxl_undo.can_undo(G.app), 'nothing to undo after Create')
    mxl_undo._do_undo(G.app)
    s.after(what='create + undo')


@T.test
def copies_field_creates_several():
    w = creator()
    set_quality(w, 'normal')
    i = next(i for i, (lab, code) in enumerate(w.entries) if G.app.data.base(code).size == (1, 1) and G.app.data.base(code).kind == 'misc')
    pick(w, i)
    w.copies.set(3)
    s = Stash()
    commit(w)
    now = T.stash_snap(s.path, G.app.data)
    g, new, chg = T.diff(s.snap, now)
    T.eq((g, chg, len(new)), ([], [], 3), 'three copies: (removed, changed, number added)')
    T.check(len({bytes(T.record(now[k][1])[0].get('code', '').encode()) for k in new}) == 1, 'the copies are different items')
    T.eq(int(w.copies.get()), 1, 'copies field after the write')


@T.test
def edit_mode_replace_with_changed_roll():
    import mxl_creator_gui as CG
    import mxl_tabs
    import mxl_undo
    w = creator()
    pick_unique_armor(w)
    w.reroll('max')
    s0 = Stash()
    commit(w)
    key, _now = s0.added('create')
    # the Item Editor on the item just created, as the toolbar's "Edit item" does
    G.app.selected = next(i for i in G.app.items if (i['page'], i['x'], i['y']) == key)
    CG.edit_selected(G.app)
    T.pump(10)
    w2 = mxl_tabs.built_owner('Creator')
    T.check(w2 is not None and w2.edit_item is not None, 'the Item Editor did not open')
    T.eq(w2.spec['quality'], 'unique', 'quality in the editor')
    m = next(m for m in w2.cr.mods(w2.spec) if m.variable and m.min != m.max)
    T.eq(w2.spec['rolls'].get(m.source), m.max, f'roll of {m.source} read from the item')
    s = Stash()
    before = T.stash_items(s.path, G.app.data)[key]
    w2.set_roll(m.source, m.min)
    T.pump(4)
    blob, rec = w2.current_blob()
    commit(w2)
    s.after(chg=[key], what='replace with a changed roll')
    after = T.stash_items(s.path, G.app.data)[key]
    T.eq(T.stats_of(after), T.stats_of(rec), 'stats on disk vs preview')
    changed = {a for a, _b, _c in set(T.stats_of(after)) ^ set(T.stats_of(before))}
    T.check(changed and changed <= {x['id'] for x in m.stats(G.app.data)}, f'stats changed: {sorted(changed)}; the mod makes {sorted(x["id"] for x in m.stats(G.app.data))}')
    T.check('replaced' in T.status_text(), f'status: {T.status_text()!r}')
    T.eq(w2.cr.spec_from_item(after)['rolls'].get(m.source), m.min, 'roll read back from the replaced item')
    mxl_undo._do_undo(G.app)
    back = s.after(what='replace + undo')
    T.eq(back[key][1], s.snap[key][1], 'bytes of the item after replace + undo')


# BUG (known, WORKLOG W14): the Item Editor rebuilds the item from a spec. Replace without touching anything
# gives a new item id, and on some sample items other stats (the engine test noop_edit_of_sample_items counts them).
@T.test
def edit_mode_noop_replace_is_byte_identical():
    import mxl_creator as C
    import mxl_creator_gui as CG
    import mxl_save
    import mxl_tabs
    raw = T.read(G.app.path)
    tried = 0
    for it in sorted(G.app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        rec = T.rec_of(mxl_save.item_blob(raw, it))
        if rec['flags'] & C.FLAG_SIMPLE or rec['quality'] not in ('unique', 'rare', 'magic') or tried >= 3:
            continue
        tried += 1
        key = (it['page'], it['x'], it['y'])
        s = Stash()
        G.app.selected = next(i for i in G.app.items if (i['page'], i['x'], i['y']) == key)
        CG.edit_selected(G.app)
        T.pump(10)
        w2 = mxl_tabs.built_owner('Creator')
        if w2 is None or w2.edit_item is None or w2.spec is None:
            continue
        commit(w2)
        now = T.stash_snap(s.path, G.app.data)
        r0, r1 = T.rec_of(s.snap[key][1]), T.rec_of(now[key][1])
        differ = sorted(k for k in set(r0) | set(r1) if r0.get(k) != r1.get(k))
        T.eq(differ, [], f'{it["code"].strip()} {rec["quality"]} at {key}: record fields changed by a no-op Replace')
        T.only_changed(s.snap, now, what=f'no-op Replace at {key}')
    T.check(tried > 0, 'no item to edit in the sample stash')


@T.test
def create_honorific():
    import mxl_creator as C
    w = creator()
    set_quality(w, 'tempered')
    T.check(len(w.entries) > 500, f'only {len(w.entries)} honorific bases offered')
    i = next(i for i, (lab, code) in enumerate(w.entries) if G.app.data.base(code).kind == 'armor'
             and G.app.data.base(code).size[0] * G.app.data.base(code).size[1] <= 6)
    pick(w, i)
    T.eq(w.spec['quality'], 'tempered', 'quality of the spec')
    T.check(any(e['id'] == C.HONORIFIC_STAT for e in w.spec.get('extra') or ()), f'recipe stats: {w.spec.get("extra")}')
    s = Stash()
    blob, rec = w.current_blob()
    commit(w)
    key, now = s.added('create honorific')
    it = T.stash_items(s.path, G.app.data)[key]
    T.eq(it['quality'], 'tempered', 'quality on disk (9 = honorific)')
    T.eq(T.stats_of(it), T.stats_of(rec), 'stats on disk vs preview')
    T.check(any(a == C.HONORIFIC_STAT for a, _b, _c in T.stats_of(it)), 'stat 289 (orb effects doubled) missing on disk')
    T.check(isinstance(it.get('rare_names'), (list, tuple)) and len(it['rare_names']) == 2, f'name words: {it.get("rare_names")!r}')
    r = T.rec_of(now[key][1])
    T.check(r['flags'] & C.FLAG_NEW, 'header flag 0x2000 (as on the game\'s own honorific item) not set')
    T.eq(r.get('sockets') or 0, w.cr.max_sockets(it['code'], r['ilvl']), 'sockets (the recipe gives the maximum)')
    for how in ('min', 'max'):
        w.reroll(how)
        T.pump()


@T.test
def create_here_on_the_character_panel():
    """Right-click an empty inventory cell of the Stash tab's panel -> "Create here...": the Creator writes into the
    character file at that cell, not into the stash."""
    import mxl_char
    import mxl_tabs
    app = G.app
    ch = mxl_char.Character(app.character_file(), app.data)
    used = set()
    for e in ch.inventory():
        bw, bh = app.data.base(e.it['code']).size
        used |= {(e.it['x'] + a, e.it['y'] + b) for a in range(bw) for b in range(bh)}
    cell = next((x, y) for y in range(mxl_char.INV_H) for x in range(mxl_char.INV_W) if (x, y) not in used)
    stash0 = T.read(app.path)
    snap0 = T.char_snap(app.character_file(), app.data)
    T.invoke(T.panel_menu(('inv',) + cell), 'Create here...')
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    T.check(w is not None and w.target is not None, 'the Creator did not open with the character as its target')
    set_quality(w, 'normal')
    i = next(i for i, (lab, code) in enumerate(w.entries) if app.data.base(code).size == (1, 1) and app.data.base(code).kind == 'misc')
    pick(w, i)
    blob, _rec = w.current_blob()
    commit(w)
    T.pump(6)
    now = T.char_snap(app.character_file(), app.data)
    k = (False, 0, 0, cell[0], cell[1], 1)
    T.only_changed(snap0, now, new=[k], what='create here')
    if k in now:
        T.check(same_but_id(now[k][1], blob), 'the item in the inventory is not the previewed item')
    T.check(T.read(app.path) == stash0, 'the stash changed')
    for problem in T.d2s_header_ok(T.read(app.character_file())):
        T.check(False, f'character file: {problem}')


T.main(globals())
