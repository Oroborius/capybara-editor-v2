"""The Item stats tab (mxl_he_stats.ItemStatsWindow): value edit, add a stat, delete a stat, a parametrised stat -
on a stash item ('stash'), on a character item reached from the Stash tab's panel ('panel') and from the Character
tab ('tab'). The tab is opened through the right-click menu's "Item stats..." entry; its own handlers are driven
(the same ones the keys and clicks call). Checked on the files re-read from disk."""
import os

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'stash': {'CAPY_TARGET': 'stash'}, 'panel': {'CAPY_TARGET': 'panel'}, 'tab': {'CAPY_TARGET': 'tab'}}
G = T.G
TARGET = os.environ.get('CAPY_TARGET', 'stash')
# stats without a parameter (resists, find, attributes, life, leech ...)
PLAIN = (39, 43, 41, 45, 80, 79, 0, 2, 3, 1, 31, 16, 7, 9, 60, 62, 119, 171)


def lone_plain_stats(rec, parsed=None):
    """Ids of the item's stats a test can change on their own: no parameter, once in the list and - on a stash
    item, whose values the collector's in-place editor writes - not tied to other stats by their mod (that editor
    moves e.g. the four resistances of an "all resistances" mod together)."""
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


class Item:
    """One item of the place under test, with its Item stats tab open."""

    def __init__(self, min_stats=3):
        import mxl_creator as C
        import mxl_save
        app = G.app
        self.other = None
        if TARGET == 'stash':
            self.path, self.other = app.path, app.character_file()
            raw = T.read(app.path)
            pick = None
            for it in sorted(app.items, key=lambda i: (i['page'], i['y'], i['x'])):
                rec = T.rec_of(mxl_save.item_blob(raw, it))
                if not rec['flags'] & C.FLAG_SIMPLE and len(rec['stats']) >= min_stats and not rec.get('stats_runeword') \
                        and rec['quality'] in ('magic', 'rare', 'unique', 'crafted') and lone_plain_stats(rec, it):
                    pick = (it['page'], it['x'], it['y'])
                    break
            if pick is None:
                T.skip('the sample stash has no magic / rare / unique item with a plain stat (resist, attribute ...)')
            self.key = pick
            self.menu = lambda: T.stash_menu(*pick)
        else:
            import mxl_char
            self.path, self.other = app.character_file(), app.path
            ch = mxl_char.Character(self.path, app.data)
            pick = None
            for e in ch.entries(False):
                if e.it['location'] != 1:
                    continue
                rec = T.rec_of(e.blob)
                ids = [s['id'] for s in rec['stats']]
                if not rec['flags'] & C.FLAG_SIMPLE and len(rec['stats']) >= min_stats and not rec.get('stats_runeword') \
                        and not rec.get('socketed_count') \
                        and any(s['id'] in PLAIN and not s.get('param') and ids.count(s['id']) == 1 for s in rec['stats']):
                    pick = e.it['equipped']
                    break
            if pick is None:
                T.skip('the sample character wears no item with a plain stat and without socketed items')
            self.key = (False, 1, pick, pick, 0, 0)
            if TARGET == 'tab':
                def menu():
                    cw = T.chartab()
                    T.select_tab('Character')
                    if cw.tab.get() != 'inventory':
                        cw.tab.set('inventory')
                        cw.show_tab()
                    T.pump()
                    return T.chartab_menu(('slot', pick))
                self.menu = menu
            else:
                self.menu = lambda: T.panel_menu(('slot', pick))
        self.snap0 = self.snap()
        self.raw0 = T.read(self.path)
        self.other0 = T.read(self.other)
        self.w = self.open()

    def snap(self):
        return T.stash_snap(self.path, G.app.data) if TARGET == 'stash' else T.char_snap(self.path, G.app.data)

    def open(self):
        import mxl_he_stats as H
        import mxl_tabs
        T.invoke(self.menu(), 'Item stats...')
        T.pump()
        w = mxl_tabs.built_owner(H.TAB_KEY)
        if w is None:
            raise T.Failed('the Item stats tab did not open')
        return w

    def stats(self, snap=None):
        """[(id, param, value)] of the item, decoded from the file on disk."""
        snap = self.snap() if snap is None else snap
        return [(s['id'], s.get('param') or None, s['value']) for s in T.rec_of(snap[self.key][1])['stats']]

    def check(self, what, changed=True):
        """Only this item changed; the other file not at all; a character file is consistent."""
        T.pump()
        now = self.snap()
        T.only_changed(self.snap0, now, chg=[self.key] if changed else [], what=what)
        T.check(T.read(self.other) == self.other0, f'{what}: the other save file changed')
        if TARGET != 'stash':
            for problem in T.d2s_header_ok(T.read(self.path)):
                T.check(False, f'{what}: character file {problem}')
        r0, k0 = T.record(self.snap0[self.key][1])
        r1, k1 = T.record(now[self.key][1])
        T.eq({k: v for k, v in r1.items() if k != 'stats'}, {k: v for k, v in r0.items() if k != 'stats'}, f'{what}: fields other than the stats')
        T.eq(k1, k0, f'{what}: socketed items behind the item')
        return now

    def slot(self, i):
        """Selects slot i of the item's own stat list (None: the first empty slot)."""
        n = self.w._find_slot('stats', i)
        if n is None:
            raise T.Failed(f'no slot {i} in the Item stats list')
        self.w.select(n)
        return n

    def set_value(self, i, v, how='save'):
        self.slot(i)
        self.w.edit_cell('value')
        T.check(self.w._ed is not None and self.w._ed[1] == 'value', f'the value box did not open on slot {i}')
        self.w.ed_var.set(str(v))
        self.w._ed_done(how)
        T.pump()

    def editable_slot(self):
        """(index, new value) of a slot whose value can go up or down by one inside the stat's storage range and
        that the item's mods do not tie to another stat."""
        import mxl_he_stats as H
        cur = self.stats()
        ok = lone_plain_stats(T.rec_of(self.snap()[self.key][1]),
                              T.stash_items(self.path, G.app.data)[self.key] if TARGET == 'stash' else None)
        for i, (sid, param, v) in enumerate(cur):
            rng = H.value_range(G.app.data, sid)
            if rng is None or sid not in ok:
                continue
            return i, v + 1 if v + 1 <= rng[1] else v - 1
        T.skip('the picked item has no plain stat to edit')


def new_plain_stat(item):
    have = {s[0] for s in item.stats()}
    return next(s for s in PLAIN if s not in have and G.app.data.isc.get(s, {}).get('bits'))


@T.test
def opening_the_tab_writes_nothing():
    import mxl_he_stats as H
    it = Item()
    T.check(H.TAB_KEY in str(T.tab_names()) or len(T.tab_names()) == 4, f'tabs: {T.tab_names()}')
    T.check(T.read(it.path) == it.raw0, 'opening the Item stats tab changed the file')
    shown = [(r['s']['id'], r['s'].get('param') or None, r['s']['value']) for r in it.w.rows if r['kind'] == 'slot' and r['s'] is not None]
    T.eq(shown, it.stats(), 'stats listed in the tab vs stats on disk')
    T.check(any(r['kind'] == 'slot' and r['s'] is None for r in it.w.rows), 'no empty slot to add a stat into')
    it.w.save()
    T.check(T.read(it.path) == it.raw0, 'Save without a change wrote the file')
    T.check(all(r.get('label') for r in it.w.rows if r['kind'] == 'slot' and r['s'] is not None), 'a row without a label')


@T.test
def value_edit():
    it = Item()
    before = it.stats()
    i, new = it.editable_slot()
    sid = before[i][0]
    it.set_value(i, new)
    now = it.check('value edit')
    after = it.stats(now)
    T.eq(sorted(after), sorted(before[:i] + [(sid, None, new)] + before[i + 1:]), f'stats on disk after setting stat {sid} to {new}')
    T.eq(len(now[it.key][1]), len(it.snap0[it.key][1]), 'size of the item')
    T.eq(it.w.pending, {}, 'pending values after the write')
    T.check('written' in it.w.bar['text'], f'status of the tab: {it.w.bar["text"]!r}')
    # and back: the original bytes
    j = next(k for k, s in enumerate(after) if s[0] == sid)
    it.set_value(j, before[i][2])
    T.eq(it.snap()[it.key][1], it.snap0[it.key][1], 'bytes of the item after setting the value back')
    T.check(T.read(it.path) == it.raw0, 'the file after setting the value back is not the original file')


@T.test
def value_typed_but_not_saved_is_not_written():
    it = Item()
    i, new = it.editable_slot()
    it.set_value(i, new, how='down')                 # Down arrow: the value stays pending, the selection moves
    T.eq(list(it.w.pending.values()), [new], 'pending values')
    T.check(T.read(it.path) == it.raw0, 'a value that was only typed was written')
    it.w.save()
    T.pump()
    T.check(T.read(it.path) != it.raw0, 'Save did not write the pending value')
    it.check('pending value saved')


@T.test
def value_out_of_range_is_capped():
    import mxl_he_stats as H
    it = Item()
    i, _new = it.editable_slot()
    sid = it.stats()[i][0]
    lo, hi = H.value_range(G.app.data, sid)
    it.set_value(i, hi + 100000)
    now = it.check('capped value')
    got = next(s for s in it.stats(now) if s[0] == sid)[2]
    T.eq(got, hi, f'stat {sid}: value stored for {hi + 100000} (storage range {lo}..{hi})')
    T.check('capped' in it.w.bar['text'], f'status of the tab: {it.w.bar["text"]!r}')
    it.set_value(next(k for k, s in enumerate(it.stats()) if s[0] == sid), 'abc')
    T.eq(next(s for s in it.stats() if s[0] == sid)[2], hi, 'value after typing letters')


@T.test
def add_stat():
    it = Item()
    before = it.stats()
    sid = new_plain_stat(it)
    it.slot(None)
    it.w.picked(sid)
    T.pump()
    now = it.check('add stat')
    T.eq(sorted(it.stats(now)), sorted(before + [(sid, None, 0)]), f'stats on disk after adding stat {sid}')
    T.check(it.w._ed is not None and it.w._ed[1] == 'value', 'the value box is not open on the new stat')
    it.w.ed_var.set('17')
    it.w._ed_done('save')
    T.pump()
    now = it.check('add stat + value')
    T.eq(sorted(it.stats(now)), sorted(before + [(sid, None, 17)]), f'stats on disk after giving stat {sid} the value 17')
    ids = [s[0] for s in it.stats(now)]
    T.eq(ids, sorted(ids), 'stat list in the game\'s order (by stat id)')


@T.test
def delete_stat():
    it = Item()
    before = it.stats()
    i = len(before) // 2
    it.slot(i)
    it.w.delete_selected()
    T.pump()
    now = it.check('delete stat')
    T.eq(it.stats(now), before[:i] + before[i + 1:], f'stats on disk after clearing slot {i + 1}')
    T.check(len(now[it.key][1]) <= len(it.snap0[it.key][1]), 'the item grew')
    T.check('slot cleared' in it.w.bar['text'], f'status of the tab: {it.w.bar["text"]!r}')


@T.test
def replace_stat_keeps_the_value():
    it = Item()
    before = it.stats()
    i, _new = it.editable_slot()
    sid = new_plain_stat(it)
    it.slot(i)
    it.w.picked(sid)
    if it.w._ed is not None:
        it.w._ed_done('cancel')
    T.pump()
    now = it.check('replace stat')
    import mxl_he_stats as H
    lo, hi = H.value_range(G.app.data, sid)
    want = max(lo, min(hi, before[i][2]))
    T.eq(sorted(it.stats(now)), sorted(before[:i] + before[i + 1:] + [(sid, None, want)]), f'stats on disk after replacing slot {i + 1} by stat {sid}')


@T.test
def add_then_delete_restores_the_item():
    """Add a stat, clear its slot again: the item is byte for byte what it was."""
    it = Item()
    sid = new_plain_stat(it)
    it.slot(None)
    it.w.picked(sid)
    if it.w._ed is not None:
        it.w._ed_done('cancel')
    T.pump()
    T.check(T.read(it.path) != it.raw0, 'adding a stat wrote nothing')
    j = next(k for k, s in enumerate(it.stats()) if s[0] == sid)
    it.slot(j)
    it.w.delete_selected()
    T.pump()
    now = it.check('add + delete', changed=False)
    T.eq(now[it.key][1], it.snap0[it.key][1], 'bytes of the item after add + delete')
    T.eq(sorted(now.items()), sorted(it.snap0.items()), 'every item after add + delete')


# BUG (known, WORKLOG W15): "add-then-delete in the Item stats tab leaves the stash 336 bytes different though
# parsing equal". Every item is byte-identical afterwards (test above); the file as a whole is not.
# A character file does come back byte for byte (variants 'panel' and 'tab'): there the test must pass.
@T.test
def add_then_delete_restores_the_file():
    it = Item()
    sid = new_plain_stat(it)
    it.slot(None)
    it.w.picked(sid)
    if it.w._ed is not None:
        it.w._ed_done('cancel')
    T.pump()
    j = next(k for k, s in enumerate(it.stats()) if s[0] == sid)
    it.slot(j)
    it.w.delete_selected()
    T.pump()
    raw = T.read(it.path)
    T.eq(len(raw), len(it.raw0), 'file size after add + delete')
    T.check(raw == it.raw0, f'file differs from the original in {sum(1 for a, b in zip(raw, it.raw0) if a != b)} of {len(raw)} bytes')


@T.test
def add_chance_to_cast_with_skill_and_level():
    """A parametrised stat: the skill is picked by name, the level typed; param = skill << 6 | level on disk."""
    import mxl_statnames as SN
    it = Item()
    before = it.stats()
    sid = next(s for s in SN.CHANCE_TO_CAST if s not in {x[0] for x in before})
    it.slot(None)
    it.w.picked(sid)
    T.pump()
    T.check(it.w._pick_mode is not None, 'the skill list did not open after adding a chance-to-cast stat')
    names = [n for n, _v in SN.param_choices(G.app.data, sid)]
    name = next(n for n in names if 'Nova' in n or 'Bolt' in n)
    it.w._name_picked(name)
    T.pump()
    row = it.w._row()
    T.eq(row['name'], name, 'skill of the row after the pick')
    T.check(it.w._ed is not None and it.w._ed[1] == 'value', f'the value box is not open after the skill pick: {it.w._ed!r}')
    it.w.ed_var.set('7')
    it.w._ed_done('next')
    T.check(it.w._ed is not None and it.w._ed[1] == 'level', f'Tab did not move to the level cell: {it.w._ed!r}')
    it.w.ed_var.set('12')
    it.w._ed_done('save')
    it.w.save()
    T.pump()
    now = it.check('chance to cast')
    got = [s for s in it.stats(now) if s[0] == sid]
    T.eq(len(got), 1, f'stat {sid} entries on disk')
    if got:
        T.eq(SN.decode_param(G.app.data, sid, got[0][1]), (name, 12), 'skill and level decoded from the param on disk')
        T.eq(got[0][1] & 63, 12, 'level bits of the param')
        T.eq(got[0][2], 7, 'value (chance) on disk')
    T.eq(sorted(s for s in it.stats(now) if s[0] != sid), sorted(before), 'the other stats')


@T.test
def enumerated_param_picked_by_name():
    """Stat 415 (innate elemental damage): 'Cold / Vitality' is stored as element | attribute << 8."""
    it = Item()
    before = it.stats()
    if any(s[0] == 415 for s in before):
        T.skip('the picked item already has stat 415')
    it.slot(None)
    it.w.picked(415)
    T.pump()
    T.check(it.w._pick_mode is not None, 'the name list did not open for stat 415')
    it.w._name_picked('Cold / Vitality')
    if it.w._ed is not None:
        it.w._ed_done('cancel')
    T.pump()
    now = it.check('stat 415')
    T.eq([s[:2] for s in it.stats(now) if s[0] == 415], [(415, 2 | 3 << 8)], 'stat 415 and its param on disk')
    row = next(r for r in it.w.rows if r['kind'] == 'slot' and r['s'] and r['s']['id'] == 415)
    T.eq(row['name'], 'Cold / Vitality', 'name shown in the row')
    T.eq(sorted(s for s in it.stats(now) if s[0] != 415), sorted(before), 'the other stats')


# BUG: on a STASH item the Item stats tab writes typed values in place through the collector's apply_edits, which
# refuses stat 415 ("innate damage, based on a character attribute, cannot be edited"). The tab itself adds the
# stat (at 0) and sets its element / attribute, but its value can then not be typed: 'not written: ...'. On a
# character item (variants 'panel', 'tab') the same edit is written.
@T.test(xfail="Item stats tab, stash item: the value of stat 415 cannot be set ('not written: stat 415 (innate damage, "
              "based on a character attribute) cannot be edited'); works on character items" if TARGET == 'stash' else None)
def enumerated_param_stat_takes_a_value():
    it = Item()
    if any(s[0] == 415 for s in it.stats()):
        T.skip('the picked item already has stat 415')
    it.slot(None)
    it.w.picked(415)
    T.pump()
    it.w._name_picked('Cold / Vitality')
    T.check(it.w._ed is not None and it.w._ed[1] == 'value', f'the value box is not open after the name pick: {it.w._ed!r}')
    if it.w._ed is not None:
        it.w.ed_var.set('40')
        it.w._ed_done('save')
    T.pump()
    now = T.rec_of(it.snap()[it.key][1])['stats']
    T.eq([(s['id'], s.get('param'), s['value']) for s in now if s['id'] == 415], [(415, 2 | 3 << 8, 40)],
         f'stat 415 on disk (status of the tab: {it.w.bar["text"]!r})')


T.main(globals())
