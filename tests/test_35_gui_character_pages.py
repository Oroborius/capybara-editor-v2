"""Editing on the pages of the Character tab: Stats (the game's stat screen in the dark look, the grey page in the
light look), Skills, Waypoints, Quests and the plug-in pages Quests+, Counters, Hotkeys, Mercenary.

Every test starts from the pristine sample files, edits through the page's own widgets (mouse events on the
canvases / trees / cells, the widgets' own invoke(); a key event that does not arrive on this X server falls back
to the handler its binding calls), presses the Character tab's SAVE / RELOAD / CLOSE image buttons, and reads the
character file again from disk: header size and checksum, `mxlsave verify`, the file rebuilds identically, and it
differs from the original in exactly what was edited (header bytes, character stats, skill levels, items - all
compared part by part). The stash files and the companion files must stay byte-identical.

The second half is about pending edits meeting other writers: SAVE of several pages at once, an item action of
the Stash tab's panel or of the Inventory page while pages hold unsaved edits, a refused item action, a file
changed behind the editor's back, another character picked in the dropdown."""
import os
import struct
import subprocess
import sys

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'d2': {'MXL_THEME': 'd2'}, 'he': {'MXL_THEME': 'he'}}
G = T.G
FELL_BACK = set()                       # key events that had to be replaced by their handler (see press_key())


# ------------------------------------------------------------------------------------------- the window
def start(page='stats'):
    """The Character tab on the sample character, nothing pending, the page shown."""
    import mxl_char_gui
    cw = T.chartab()
    path = G.app.character_file()
    if cw is None or getattr(cw, 'ch', None) is None or os.path.abspath(cw.ch.path) != os.path.abspath(path):
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    if cw is None:
        raise T.Failed('no Character tab')
    T.select_tab('Character')
    (getattr(cw, 'discard', None) or cw.reload)()        # what the RELOAD button does
    T.pump(4)
    cw = T.chartab()
    show(cw, page)
    if cw.dirty():
        raise T.Failed('the Character tab reports unsaved changes right after reading the file')
    return cw


def show(cw, page):
    if cw.tab.get() != page:
        cw.tab.set(page)
        cw.show_tab()
    T.settle(0.15)
    if not cw.pages[page].winfo_ismapped():
        raise T.Failed(f'page {page!r} is not shown')


BUTTON = {'reload': 'discard'}           # the RELOAD button's command before it got a name of its own


def stone(cw, command):
    """Presses one of the image buttons: 'save_progress' (SAVE), 'discard' (RELOAD), 'close' (CLOSE)."""
    import mxl_char_gui
    b = next(w for w in cw.bar_status.master.winfo_children()
             if isinstance(w, mxl_char_gui.StoneButton) and BUTTON.get(w.command.__name__, w.command.__name__) == command)
    for seq in ('<Enter>', '<ButtonPress-1>', '<ButtonRelease-1>'):
        b.event_generate(seq, x=5, y=5)
    T.pump(8)
    try:
        b.event_generate('<Leave>')
    except Exception:
        pass                             # CLOSE: the button is gone
    T.pump(2)


def click(widget, x, y, button=1, release=True, state=0):
    widget.event_generate(f'<ButtonPress-{button}>', x=int(x), y=int(y), state=state)
    if release:
        widget.event_generate(f'<ButtonRelease-{button}>', x=int(x), y=int(y), state=state)
    T.pump(4)


def press_key(widget, seq, done, fallback):
    """A key event on a widget; when it does not arrive (no window manager on the test X server: keyboard events
    go to the focus window, which may not follow focus_force) the handler bound to it is called instead."""
    try:
        widget.focus_force()
        T.pump(3)
        widget.event_generate(seq)
        T.pump(3)
    except Exception:
        pass
    if not done():
        FELL_BACK.add(seq)
        fallback()
        T.pump(3)


def retype(entry, text):
    entry.delete(0, 'end')
    entry.insert(0, str(text))
    T.pump(2)


# ------------------------------------------------------------------------------------------- file comparison
def parts(path):
    import mxl_char
    ch = mxl_char.Character(path, G.app.data)
    ids = mxl_char.class_skills(G.app.data, ch.cls)
    body = bytes(ch.skills[2:])
    return dict(head=bytes(ch.head), stats={(s[0], s[1] or 0): s[2] for s in ch.stats},
                order=[(s[0], s[1] or 0) for s in ch.stats], skills=dict(zip(ids, body)), skills_raw=bytes(ch.skills),
                corpse=bytes(ch.corpse), tail=bytes(ch.tail), jf=ch.has_jf,
                merc_list=ch.merc_items is not None, raw=bytes(ch.raw), built=ch.build())


def delta(a, b):
    """What differs between two parts(): only the keys with a difference."""
    out = {}
    if len(a['head']) != len(b['head']):
        out['head_len'] = (len(a['head']), len(b['head']))
    head = {i: (x, y) for i, (x, y) in enumerate(zip(a['head'], b['head'])) if x != y and not 8 <= i < 16}
    if head:
        out['head'] = head
    stats = {k: (a['stats'].get(k), b['stats'].get(k)) for k in set(a['stats']) | set(b['stats'])
             if a['stats'].get(k) != b['stats'].get(k)}
    if stats:
        out['stats'] = stats
    if [k for k in a['order'] if k in b['stats']] != [k for k in b['order'] if k in a['stats']]:
        out['stat_order'] = True
    skills = {k: (a['skills'].get(k), b['skills'].get(k)) for k in set(a['skills']) | set(b['skills'])
              if a['skills'].get(k) != b['skills'].get(k)}
    if skills:
        out['skills'] = skills
    elif a['skills_raw'] != b['skills_raw']:
        out['skills_raw'] = True
    for k in ('corpse', 'tail', 'jf', 'merc_list'):
        if a[k] != b[k]:
            out[k] = True
    return out


def u32_bytes(off, old, new):
    """Expected header difference of a little-endian u32 (or u16 with n=2) changed from old to new."""
    a, b = struct.pack('<I', old), struct.pack('<I', new)
    return {off + i: (a[i], b[i]) for i in range(4) if a[i] != b[i]}


def merge(*ds):
    out = {}
    for d in ds:
        for k, v in d.items():
            if isinstance(v, dict):
                out.setdefault(k, {}).update(v)
            else:
                out[k] = v
    return out


def verify(path, what):
    """`python -m mxlsave verify` (the independent parser of tools/): parse, rebuild, compare."""
    r = subprocess.run([sys.executable, '-m', 'mxlsave', 'verify', path], cwd=os.path.join(T.REPO, 'tools'),
                       capture_output=True, text=True, timeout=120)
    T.check(r.returncode == 0 and r.stdout.startswith('OK'), f'{what}: mxlsave verify: {(r.stdout + r.stderr).strip()[:300]}')


class Ctx:
    def __init__(self):
        self.path = G.app.character_file()
        self.before = parts(self.path)
        self.items = T.char_snap(self.path, G.app.data)
        folder = os.path.dirname(self.path)
        self.others = {n: T.read(os.path.join(folder, n)) for n in sorted(os.listdir(folder))
                       if os.path.isfile(os.path.join(folder, n)) and os.path.join(folder, n) != self.path}

    def same_file(self, what):
        return T.check(T.read(self.path) == self.before['raw'], f'{what}: the character file changed')

    def after(self, what, expect, gone=(), new=(), chg=(), views=True):
        """Soft-asserts that the file on disk differs from the original in exactly `expect` (a delta()) and in
        the named items; everything else of the save folder untouched."""
        T.pump(6)
        raw = T.read(self.path)
        for problem in T.d2s_header_ok(raw):
            T.check(False, f'{what}: character file {problem}')
        now = parts(self.path)
        T.check(now['built'] == raw, f'{what}: the written character does not rebuild identically')
        verify(self.path, what)
        T.eq(delta(self.before, now), expect, f'{what}: differences of the file (header bytes, stats, skills)')
        T.only_changed(self.items, T.char_snap(self.path, G.app.data), gone, new, chg, what)
        folder = os.path.dirname(self.path)
        for n, data in self.others.items():
            p = os.path.join(folder, n)
            T.check(os.path.isfile(p) and T.read(p) == data, f'{what}: {n} changed')
        if views:
            cw = T.chartab()
            T.check(cw is not None and bytes(cw.ch.raw) == raw, f'{what}: the Character tab does not hold the file on disk')
            shown = G.app.inventory.ch
            T.check(shown is not None and bytes(shown.raw) == raw, f'{what}: the Stash tab panel does not show the file on disk')
        return now


def no_boxes(what, kinds=('showerror', 'showwarning')):
    bad = [b for b in G.boxes if b[0] in kinds]
    T.check(not bad, f'{what}: message box {bad[:2]}')


# ------------------------------------------------------------------------------------------- page drivers
def stat_type(cw, key, text):
    """Types a value into a box of the Stats page and presses Enter."""
    show(cw, 'stats')
    scr = cw.statscreen
    if scr is None:                                     # the grey page
        e = cw.sv[key]
        e.focus_force()
        retype(e, text)
        press_key(e, '<Return>', lambda: str(cw.st_value(key)) == str(text), lambda: cw._grey_commit(key))
        return
    if scr.box_of(key) is None:
        import mxl_statscreen
        scr.show_page('main' if key in mxl_statscreen.P1_ORDER else 'saved', exact=True)
        T.pump(4)
    box = scr.box_of(key)
    if box is None:
        raise T.Failed(f'the stat screen has no box for {key!r} on {scr.shown}')
    x, y, w, h = box
    click(scr.cv, (x + w / 2) * scr.k, (y + h / 2) * scr.k)
    if scr.edit is None or scr.edit[0] != key:
        raise T.Failed(f'a click on the {key!r} box did not open its entry')
    e = scr.edit[1]
    retype(e, text)
    press_key(e, '<Return>', lambda: scr.edit is None, scr.commit_edit)


def stat_plus(cw, key, button=1):
    """Clicks the + button of an attribute (right button: a point back)."""
    show(cw, 'stats')
    scr = cw.statscreen
    if scr is None:
        b = next(w for w in cw.sv[key].master.grid_slaves(row=int(cw.sv[key].grid_info()['row']), column=2))
        b.event_generate(f'<ButtonRelease-{button}>', x=3, y=3)
        T.pump(4)
        return
    if scr.box_of('strength') is None:
        scr.show_page('main', exact=True)
        T.pump(4)
    x, y, w, h = next(box for kind, k, box, _pg in scr._regions if kind == 'plus' and k == key)
    click(scr.cv, (x + w / 2) * scr.k, (y + h / 2) * scr.k, button=button)


def skill_region(cw, kind, sid):
    tree = cw.sktree
    x, y, w, h = next(b for k, s, b in tree._regions if k == kind and s == sid)
    return (x + w / 2) * tree.k, (y + h / 2) * tree.k


def skill_pick(cw, want=lambda lv: lv < 200):
    """A skill of the tree shown whose level satisfies `want`."""
    tree = cw.sktree
    for sid, _r, _c in tree.cells():
        if want(tree.level(sid)) and any(k == 'icon' and s == sid for k, s, _b in tree._regions):
            return sid
    T.skip('no suitable skill on the first tree of the sample character')


def tree_click(tree, key):
    """Clicks the tick box of a CheckTree row (waypoints / quests)."""
    tv = tree.tv
    iid = tree.iids[key]
    p = tv.parent(iid)
    while p:
        tv.item(p, open=True)
        p = tv.parent(p)
    tv.see(iid)
    T.pump(4)
    box = tv.bbox(iid)
    if not box:
        raise T.Failed(f'tree row {key} is not visible')
    x, y, w, h = box
    px = next((i for i in range(x, x + w) if 'image' in str(tv.identify_element(i, y + h // 2))), None)
    if px is None:
        raise T.Failed(f'tree row {key}: no tick box found')
    click(tv, px + 2, y + h // 2)


def hk_cell(page, off):
    return page.cells[off]['frame']


def widgets(w, cls):
    out = [w] if w.winfo_class() == cls else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


# ---- one pending edit per page: make(cw) -> (expected delta of the file after SAVE, shown() -> still pending)
def edit_stat(cw):
    cur = cw.st_value('strength')
    stat_type(cw, 'strength', cur + 7)
    return {'stats': {(0, 0): (cur, cur + 7)}}, lambda: cw.st_value('strength') == cur + 7


def edit_skill(cw):
    show(cw, 'skills')
    sid = skill_pick(cw)
    lv = cw.sktree.level(sid)
    click(cw.sktree.cv, *skill_region(cw, 'icon', sid), release=False)
    return {'skills': {sid: (lv, lv + 1)}}, lambda: cw.sktree.level(sid) == lv + 1


def edit_waypoint(cw):
    import mxl_char as MC
    show(cw, 'waypoints')
    k, n = next(((k, n) for k in (2, 1, 0) for n in MC.waypoint_ids(k) if n and n not in cw.w0[k]), (None, None))
    if k is None:
        T.skip('the sample character has every waypoint')
    base = MC.WP_DATA + 24 * k
    head = bytes(cw.ch.head)
    tree_click(cw.wp_trees[k], ('wp', k, n))
    exp = {base + 2 + n // 8: (head[base + 2 + n // 8], head[base + 2 + n // 8] | 1 << n % 8)}
    for i, v in ((0, 2), (1, 1)):                       # the section's own two bytes, as the game writes them
        if head[base + i] != v:
            exp[base + i] = (head[base + i], v)
    return {'head': exp}, lambda: n in cw.wstate[k]


def quest_off(k, w):
    import mxl_char as MC
    return MC.QUEST_DATA + 96 * k + 2 * w


def edit_quest(cw, word=2):
    """Ticks a quest without a reward (2 = Sisters' Burial Grounds) in the highest difficulty where it is open."""
    import mxl_char as MC
    show(cw, 'quests')
    k = next((k for k in (2, 1, 0) if word not in cw.q0[k]), None)
    if k is None:
        T.skip(f'quest word {word} is done in every difficulty of the sample')
    ch = cw.ch
    old = ch.quest_word(k, word)
    tree_click(cw.q_trees[k], ('q', k, word))
    a, b = struct.pack('<H', old), struct.pack('<H', MC.QUEST_DONE)
    exp = {quest_off(k, word) + i: (a[i], b[i]) for i in range(2) if a[i] != b[i]}
    act = next(x for x in MC.ACTS if any(w == word for w, _ in x[2]))
    if not ch.quest_word(k, act[1]):                    # the act's introduction, set with its first quest
        exp[quest_off(k, act[1])] = (0, 1)
    return {'head': exp}, lambda: word in cw.qstate[k]


def edit_quest_word(cw, word=3, bit=2):
    """Quests+: flips one bit of a word in Hell through its check box."""
    show(cw, 'quests_adv')
    page = cw.extra['quests_adv']
    page.diff_buttons[2].invoke()
    T.pump(3)
    page.tv.selection_set(page.rows[word])
    page.tv.see(page.rows[word])
    T.pump(4)
    T.eq(page.sel, word, 'Quests+: the selected word')
    old = cw.ch.quest_word(2, word)
    page.bitboxes[bit].invoke()
    T.pump(3)
    new = old ^ 1 << bit
    a, b = struct.pack('<H', old), struct.pack('<H', new)
    return ({'head': {quest_off(2, word) + i: (a[i], b[i]) for i in range(2) if a[i] != b[i]}},
            lambda: page.value(2, word) == new and (2, word) in page.pend)


def edit_counter(cw):
    """Counters: one more Signet of Learning used, typed into its spin box."""
    show(cw, 'counters')
    page = cw.extra['counters']
    var = page.sig_vars[185]
    old = page.sig0[185]
    sp = next(w for w in widgets(page.frame, 'Spinbox') if str(w.cget('textvariable')) == str(var))
    retype(sp, old + 1)
    T.eq(var.get(), str(old + 1), 'Counters: the signet box after typing')
    return {'stats': {(185, 0): (old or None, old + 1)}}, lambda: page.sig[185] == old + 1


def edit_hotkey(cw):
    """Hotkeys: right click empties the first hotkey that holds a skill (or a skill is put on an empty one)."""
    import mxl_hotkeys as HK
    show(cw, 'hotkeys')
    page = cw.extra['hotkeys']
    offs = [HK.HOTKEY_OFF + 4 * i for i in range(HK.HOTKEYS)]
    off = next((o for o in offs if page.skill_at(o)[0] is not None), None)
    if off is not None:
        old = cw.ch.header_u32(off)
        hk_cell(page, off).event_generate('<Button-3>', x=3, y=3)
        new = HK.EMPTY
    else:
        off, old = offs[0], cw.ch.header_u32(offs[0])
        page.assign(off, HK.TOWN_PORTAL)
        new = HK.TOWN_PORTAL
    T.pump(4)
    return {'head': u32_bytes(off, old, new)}, lambda: page.pending.get(off) == new


def edit_merc(cw):
    """Mercenary: another name picked in its box."""
    import mxl_merc
    show(cw, 'merc')
    page = cw.extra['merc']
    if not cw.ch.merc_hired:
        T.skip('the sample character has no mercenary')
    names = list(page.name_box.cget('values'))
    old = page.rec['name']
    if len(names) < 2:
        T.skip('the mercenary type of the sample has one name only')
    new = (old + 1) % len(names)
    page.name_box.current(new)
    page.name_box.event_generate('<<ComboboxSelected>>')
    T.pump(4)
    off = mxl_merc.RECORD.start + 6                     # 0xB7: the name number (u16)
    a, b = struct.pack('<H', old), struct.pack('<H', new)
    return ({'head': {off + i: (a[i], b[i]) for i in range(2) if a[i] != b[i]}},
            lambda: page.values() is not None and page.values()['name'] == new)


EDITS = (('stat', edit_stat), ('skill', edit_skill), ('waypoint', edit_waypoint), ('quest', edit_quest),
         ('quest word', edit_quest_word), ('counter', edit_counter), ('hotkey', edit_hotkey), ('mercenary', edit_merc))


def edit_all(cw):
    """One pending edit on every page. -> (expected delta, {name: shown()})."""
    exp, shown = {}, {}
    for name, fn in EDITS:
        try:
            e, s = fn(cw)
        except T.Skip:
            continue
        exp = merge(exp, e)
        shown[name] = s
        T.check(s(), f'{name}: the edit is not shown as pending right after it was made')
        T.check(cw.dirty(), f'{name}: the window does not report unsaved changes')
    T.check(len(shown) >= 6, f'only {sorted(shown)} could be edited on this sample')
    return exp, shown


def still(shown, what):
    for name, s in shown.items():
        T.check(s(), f'{what}: the pending {name} edit is gone')


def single(name, fn, page):
    """Edit -> SAVE -> the file holds exactly that edit; the window is clean afterwards."""
    cw = start(page)
    c = Ctx()
    exp, shown = fn(cw)
    T.check(shown(), f'{name}: not shown as pending')
    T.check(cw.dirty(), f'{name}: no unsaved-changes state')
    T.check('Unsaved' in cw.bar_status.cget('text'), f'{name}: status line {cw.bar_status.cget("text")!r}')
    c.same_file(f'{name} before SAVE')
    stone(cw, 'save_progress')
    no_boxes(name)
    c.after(name, exp)
    T.check(not cw.dirty(), f'{name}: still unsaved changes after SAVE')
    return cw, c


# ------------------------------------------------------------------------------------------- Stats
@T.test
def stats_typed_value_is_saved():
    cw, c = single('strength typed', edit_stat, 'stats')
    T.eq(cw.st_value('strength'), c.before['stats'][(0, 0)] + 7, 'the box after SAVE')


@T.test
def stats_gold_and_flag_on_the_saved_values_page():
    cw = start('stats')
    c = Ctx()
    gold = cw.st_value('gold')
    new = gold + 1234 if gold + 1234 <= cw.st_range('gold')[1] else gold - 1
    stat_type(cw, 'gold', new)
    T.eq(cw.st_value('gold'), new, 'gold typed')
    scr = cw.statscreen
    old = cw.ch.flags()['died']
    if scr is not None:
        x, y, w, h = next(box for kind, k, box, _pg in scr._regions if kind == 'flag' and k == 'died')
        click(scr.cv, (x + w / 2) * scr.k, (y + h / 2) * scr.k)
    else:
        box = next(w for w in widgets(cw.st_tab, 'Checkbutton') if str(w.cget('variable')) == str(cw.sv_type['died']))
        box.invoke()
        T.pump(3)
    T.eq(cw.st_sim.flags()['died'], not old, 'the "died" flag after the click')
    stone(cw, 'save_progress')
    no_boxes('gold + flag')
    h24 = c.before['head'][0x24]
    c.after('gold + flag', {'stats': {(14, 0): (gold or None, new)}, 'head': {0x24: (h24, h24 ^ 0x08)}})


@T.test
def stats_plus_button_spends_a_stat_point():
    cw = start('stats')
    c = Ctx()
    pts, vit = cw.st_value('stat_points'), cw.st_value('vitality')
    exp = {}
    if pts == 0:                                         # give the character points to spend first
        stat_type(cw, 'stat_points', 5)
        T.eq(cw.st_value('stat_points'), 5, 'stat points typed')
        base = 5
    else:
        base = pts
    stat_plus(cw, 'vitality')
    T.eq((cw.st_value('vitality'), cw.st_value('stat_points')), (vit + 1, base - 1), 'after +')
    stat_plus(cw, 'vitality')
    stat_plus(cw, 'vitality', button=3)                  # right click: one point back
    T.eq((cw.st_value('vitality'), cw.st_value('stat_points')), (vit + 1, base - 1), 'after +, +, right click')
    stone(cw, 'save_progress')
    no_boxes('plus button')
    exp['stats'] = {(3, 0): (vit, vit + 1)}
    if base - 1 != pts:
        exp['stats'][(4, 0)] = (pts or None, (base - 1) or None)
    c.after('plus button', exp)


@T.test
def stats_refused_value_writes_nothing():
    """A value outside the field's range is refused (status line), SAVE writes nothing while it stands."""
    cw = start('stats')
    c = Ctx()
    lo, hi = cw.st_range('strength')
    show(cw, 'stats')
    scr = cw.statscreen
    if scr is None:
        e = cw.sv['strength']
        retype(e, hi + 1)
        cw._grey_commit('strength')
    else:
        x, y, w, h = scr.box_of('strength')
        click(scr.cv, (x + w / 2) * scr.k, (y + h / 2) * scr.k)
        retype(scr.edit[1], hi + 1)
        T.check(not scr.commit_edit(), 'a strength above the maximum was accepted')
    T.eq(cw.st_value('strength'), c.before['stats'][(0, 0)], 'the stored strength after a refused value')
    stone(cw, 'save_progress')
    c.same_file('SAVE with a refused value in the box')
    if scr is not None:
        scr.cancel_edit()


# ------------------------------------------------------------------------------------------- Skills
@T.test
def skills_click_raises_a_level():
    single('skill +1', edit_skill, 'skills')


@T.test
def skills_typed_level_and_right_click():
    cw = start('skills')
    c = Ctx()
    tree = cw.sktree
    a = skill_pick(cw)
    b = skill_pick(cw, lambda lv: lv >= 1)
    la, lb = tree.level(a), tree.level(b)
    if a == b:
        a = next((s for s, _r, _c in tree.cells() if s != b), None)
        la = tree.level(a)
    click(tree.cv, *skill_region(cw, 'lvl', a), release=False)
    if tree.edit is None or tree.edit[0] != a:
        raise T.Failed('a click on a level box did not open its entry')
    e = tree.edit[1]
    new = 17 if la != 17 else 18
    retype(e, new)
    press_key(e, '<KeyRelease>', lambda: tree.level(a) == new, tree._typed)
    press_key(e, '<Return>', lambda: tree.edit is None, tree.commit_edit)
    T.eq(tree.level(a), new, 'typed level')
    click(tree.cv, *skill_region(cw, 'icon', b), button=3, release=False)
    T.eq(tree.level(b), lb - 1, 'level after a right click')
    stone(cw, 'save_progress')
    no_boxes('skills')
    c.after('skill typed + right click', {'skills': {a: (la, new), b: (lb, lb - 1)}})
    T.eq(len(c.before['skills_raw']), len(parts(c.path)['skills_raw']), 'size of the skills section')


# ------------------------------------------------------------------------------------------- Waypoints / Quests
@T.test
def waypoint_tick_is_saved():
    single('waypoint', edit_waypoint, 'waypoints')


@T.test
def waypoint_untick_is_saved():
    import mxl_char as MC
    cw = start('waypoints')
    c = Ctx()
    k, n = next(((k, n) for k in (0, 1, 2) for n in MC.waypoint_ids(k) if n and n in cw.w0[k]), (None, None))
    if k is None:
        T.skip('the sample character has no waypoint to take away')
    tree_click(cw.wp_trees[k], ('wp', k, n))
    T.check(n not in cw.wstate[k], 'the waypoint is still ticked')
    stone(cw, 'save_progress')
    no_boxes('waypoint off')
    off = MC.WP_DATA + 24 * k + 2 + n // 8
    old = c.before['head'][off]
    c.after('waypoint off', {'head': {off: (old, old & ~(1 << n % 8) & 0xFF)}})
    T.check(not parts(c.path)['head'][MC.WP_DATA + 24 * k + 2] & 1 == 0, 'the town waypoint was taken away')


@T.test
def quest_tick_is_saved():
    cw, c = single('quest', edit_quest, 'quests')
    T.eq(parts(c.path)['head'][0x25], c.before['head'][0x25], 'progression byte after a quest that is no act boss')


@T.test
def quest_with_reward_gives_the_reward_once():
    """Den of Evil (+1 skill point) ticked in a difficulty where it is open; unticking it again before SAVE
    leaves the file alone."""
    import mxl_char as MC
    cw = start('quests')
    c = Ctx()
    k = next((k for k in (2, 1, 0) if 1 not in cw.q0[k]), None)
    if k is None:
        T.skip('Den of Evil is done in every difficulty of the sample')
    tree_click(cw.q_trees[k], ('q', k, 1))
    tree_click(cw.q_trees[k], ('q', k, 1))
    T.check(not cw.dirty(), 'ticked and unticked: still reported as unsaved')
    stone(cw, 'save_progress')
    c.same_file('tick + untick + SAVE')
    tree_click(cw.q_trees[k], ('q', k, 1))
    stone(cw, 'save_progress')
    no_boxes('quest reward')
    pts = c.before['stats'].get((5, 0))
    exp = {quest_off(k, 1): (c.before['head'][quest_off(k, 1)], 0x01), quest_off(k, 1) + 1: (c.before['head'][quest_off(k, 1) + 1], 0x10)}
    exp = {o: v for o, v in exp.items() if v[0] != v[1]}
    if not cw.q0[k] - {1} and not struct.unpack_from('<H', c.before['head'], quest_off(k, 0))[0]:
        exp[quest_off(k, 0)] = (0, 1)
    c.after('Den of Evil', {'head': exp, 'stats': {(5, 0): (pts, (pts or 0) + 1)}})
    T.check('skill point' in cw.bar_status.cget('text'), f'status line does not name the reward: {cw.bar_status.cget("text")!r}')


# ------------------------------------------------------------------------------------------- header progression
def prog_rule(head, MC):
    """The game's progression byte for the quest words of a header (independent of mxl_char): 5 per difficulty
    whose Eve of Destruction (40) is completed, +1 per act boss quest (6, 14, 22) done in the next one."""
    def done(k, w):
        return head[MC.QUEST_DATA + 96 * k + 2 * w] & 1
    d = 0
    while d < 3 and done(d, 40):
        d += 1
    if d == 3:
        return 15
    n = 0
    for w in (6, 14, 22):
        if not done(d, w):
            break
        n += 1
    return 5 * d + n


@T.test
def progression_follows_the_act_bosses_like_the_game():
    """The game-written samples hold 8 (Nightmare, three act bosses dead) and 13 (Hell, the same): the editor
    wrote a bare 10 for 'Nightmare finished' however far Hell was played. Ticking the last quest of the
    difficulty being played, then the next difficulty's act bosses, must give the game's values."""
    import mxl_char as MC
    cw = start('quests')
    c = Ctx()
    T.eq(prog_rule(c.before['head'], MC), c.before['head'][0x25], 'the rule against the game-written byte of the sample')
    d = cw.ch.difficulties_done
    if d >= 2 or 40 in cw.q0[d] or any(w in cw.q0[d + 1] for w in (6, 14, 22)):
        T.skip('the sample is not in the middle of Normal / Nightmare with the next difficulty untouched')
    tree_click(cw.q_trees[d], ('q', d, 40))              # Eve of Destruction: this difficulty finished
    stone(cw, 'save_progress')
    no_boxes('difficulty finished')
    T.eq(parts(c.path)['head'][0x25], 5 * (d + 1), 'progression after finishing the difficulty')
    for i, w in enumerate((6, 14, 22)):
        tree_click(cw.q_trees[d + 1], ('q', d + 1, w))
        stone(cw, 'save_progress')
        now = parts(c.path)['head']
        T.eq(now[0x25], 5 * (d + 1) + i + 1, f'progression after act boss quest {w} of the next difficulty')
        T.eq(prog_rule(now, MC), now[0x25], 'the rule against the written byte')
    no_boxes('act bosses')
    verify(c.path, 'progression')
    tree_click(cw.q_trees[d + 1], ('q', d + 1, 2))       # not an act boss: the byte stays
    stone(cw, 'save_progress')
    T.eq(parts(c.path)['head'][0x25], 5 * (d + 1) + 3, 'progression after another quest')
    for w in (22, 14):                                   # marked here, so they can be unmarked: the byte follows
        tree_click(cw.q_trees[d + 1], ('q', d + 1, w))
    stone(cw, 'save_progress')
    T.eq(parts(c.path)['head'][0x25], 5 * (d + 1) + 1, 'progression after unmarking two act bosses')


@T.test
def progression_untouched_by_other_saves():
    """No page but the quests of the act bosses / the stat screen's own boxes may move the byte."""
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    stone(cw, 'save_progress')
    T.eq(parts(c.path)['head'][0x25], c.before['head'][0x25], 'progression byte after edits on every page')


@T.test
def progression_typed_by_hand_wins():
    cw = start('stats')
    c = Ctx()
    old = c.before['head'][0x25]
    new = 15 if old != 15 else 10
    stat_type(cw, 'progression', new)
    T.eq(cw.st_value('progression'), new, 'progression typed')
    stone(cw, 'save_progress')
    no_boxes('progression typed')
    c.after('progression typed', {'head': {0x25: (old, new)}})


# ------------------------------------------------------------------------------------------- Quests+
@T.test
def questplus_bit_is_saved():
    single('quest word bit', edit_quest_word, 'quests_adv')


@T.test
def questplus_hex_complete_reopen_and_revert():
    cw = start('quests_adv')
    c = Ctx()
    page = cw.extra['quests_adv']
    page.diff_buttons[2].invoke()
    exp = {}
    for word, text in ((4, '1234'), (5, 'abcd')):
        page.tv.selection_set(page.rows[word])
        T.pump(4)
        old = cw.ch.quest_word(2, word)
        page.hex.focus_force()
        retype(page.hex, text)
        press_key(page.hex, '<Return>', lambda: page.value(2, word) == int(text, 16), page.on_hex)
        T.eq(page.value(2, word), int(text, 16), f'word {word} after typing {text}')
        a, b = struct.pack('<H', old), struct.pack('<H', int(text, 16))
        exp.update({quest_off(2, word) + i: (a[i], b[i]) for i in range(2) if a[i] != b[i]})
    page.b_revert.invoke()                               # word 5 back to the file value
    T.pump(3)
    T.check((2, 5) not in page.pend, '"File value" left the word pending')
    exp = {o: v for o, v in exp.items() if o < quest_off(2, 5)}
    retype(page.hex, 'xyz')                              # not a hex number: refused, nothing pending for it
    page.on_hex()
    T.check((2, 5) not in page.pend, 'a bad hex value became pending')
    page.diff_buttons[0].invoke()                        # Normal: a finished quest is re-opened
    T.pump(3)
    word = next((w for w in (1, 9, 17) if cw.ch.quest_word(0, w) & 1), None)
    if word is not None:
        page.tv.selection_set(page.rows[word])
        T.pump(4)
        old = cw.ch.quest_word(0, word)
        page.b_reopen.invoke()
        T.pump(3)
        T.eq(page.value(0, word), 0, 'Re-open')
        a = struct.pack('<H', old)
        exp.update({quest_off(0, word) + i: (a[i], 0) for i in range(2) if a[i]})
    stone(cw, 'save_progress')
    no_boxes('Quests+')
    c.after('Quests+ hex / revert / re-open', {'head': exp})
    T.check(not page.pend, f'words still pending after SAVE: {page.pend}')


# ------------------------------------------------------------------------------------------- Counters
@T.test
def counters_signet_is_saved():
    single('signet counter', edit_counter, 'counters')


@T.test
def counters_value_add_and_delete():
    import mxl_counters as CN
    cw = start('counters')
    c = Ctx()
    page = cw.extra['counters']
    kills = sorted(p for p in page.cnt if p != CN.PLAYTIME and p in page.rows)
    if len(kills) < 2:
        T.skip('the sample character has fewer than two counters')
    a, b = kills[0], kills[1]
    va, vb = page.cnt[a], page.cnt[b]
    retype(page.rows[a][1], va + 100)                    # typed into the row's spin box
    T.eq(page.cnt[a], va + 100, 'counter after typing')
    info = page.rows[b][1].grid_info()                   # the row's "x" button
    x = next(w for w in page.grid.grid_slaves(row=int(info['row']), column=int(info['column']) + 1))
    x.invoke()
    T.pump(4)
    T.check(b not in page.cnt, 'the deleted counter is still listed')
    free = next(p for p in sorted(CN.layers(G.app.data)) if p not in c.before['stats'] and (88, p) not in c.before['stats'])
    page.add_var.set(str(free))
    press_key(page.add_box, '<Return>', lambda: free in page.cnt, page.add_entry)
    T.eq(page.cnt.get(free), 1, 'the added counter')
    play = None
    if CN.PLAYTIME in page.rows:                         # play time: typed as h:mm:ss
        play = page.cnt[CN.PLAYTIME]
        retype(page.rows[CN.PLAYTIME][1], CN.fmt_time(play + 3600))
        T.eq(page.cnt[CN.PLAYTIME], play + 3600, 'play time after typing')
    stone(cw, 'save_progress')
    no_boxes('counters')
    exp = {(88, a): (va, va + 100), (88, b): (vb, None), (88, free): (None, 1)}
    if play is not None:
        exp[(88, CN.PLAYTIME)] = (play, play + 3600)
    c.after('counters typed / deleted / added', {'stats': exp})
    T.check(not page.dirty(), 'Counters still dirty after SAVE')


# ------------------------------------------------------------------------------------------- Hotkeys
@T.test
def hotkeys_right_click_clears():
    single('hotkey cleared', edit_hotkey, 'hotkeys')


@T.test
def hotkeys_assign_hand_swap_and_mouse_button():
    import mxl_hotkeys as HK
    cw = start('hotkeys')
    c = Ctx()
    page = cw.extra['hotkeys']
    offs = [HK.HOTKEY_OFF + 4 * i for i in range(HK.HOTKEYS)]
    old = {o: cw.ch.header_u32(o) for o in offs + list(HK.MOUSE)}
    a, b = offs[14], offs[15]
    # a click on a slot opens the skill list; the skill is picked from it
    fr = hk_cell(page, a)
    page.popup = None
    fr.event_generate('<ButtonPress-1>', x=4, y=4)
    fr.event_generate('<ButtonRelease-1>', x=4, y=4, rootx=fr.winfo_rootx() + 4, rooty=fr.winfo_rooty() + 4)
    T.pump(6)
    if page.popup is None:
        FELL_BACK.add('hotkey click')
        page.pick(a)
        T.pump(4)
    picker = page.popup.picker
    name = next(n for n, sid in page.choices(a) if sid == HK.TOWN_PORTAL)
    picker.on_pick(name)
    T.pump(4)
    T.eq(page.skill_at(a), (HK.TOWN_PORTAL, False), 'the slot after picking Town Portal')
    page.cells[a]['hand'].event_generate('<Button-1>', x=2, y=2)       # R -> L
    T.pump(3)
    T.eq(page.skill_at(a), (HK.TOWN_PORTAL, True), 'the slot after a click on its hand letter')
    T.check(page.warn.cget('text'), 'no warning for Town Portal on the left button')
    page.cells[a]['hand'].event_generate('<Button-1>', x=2, y=2)       # back to R
    T.pump(3)
    # drag slot a onto slot b: they swap
    sb = page.skill_at(b)
    fb = hk_cell(page, b)
    fr.event_generate('<ButtonPress-1>', x=4, y=4)
    fr.event_generate('<ButtonRelease-1>', x=4, y=4, rootx=fb.winfo_rootx() + 4, rooty=fb.winfo_rooty() + 4)
    T.pump(4)
    if page.skill_at(b)[0] != HK.TOWN_PORTAL:
        FELL_BACK.add('hotkey drag')
        page.swap(a, b)
        T.pump(3)
    T.eq((page.skill_at(b), page.skill_at(a)), ((HK.TOWN_PORTAL, False), sb), 'the two slots after the drag')
    page.assign(HK.MOUSE[1], HK.TOWN_PORTAL)             # the right mouse button's skill
    T.pump(3)
    stone(cw, 'save_progress')
    no_boxes('hotkeys')
    new = dict(old)
    new[b] = HK.TOWN_PORTAL
    new[a] = old[b] if old[b] & 0xFFFF != HK.EMPTY else HK.EMPTY
    new[HK.MOUSE[1]] = HK.TOWN_PORTAL
    exp = {}
    for o in old:
        exp.update(u32_bytes(o, old[o], new[o]))
    c.after('hotkeys', {'head': exp})
    T.check(not page.pending, f'hotkeys still pending after SAVE: {page.pending}')


@T.test
def hotkeys_show_the_icons_of_class_skills():
    """Every slot holding a skill of the character's class trees shows that skill's icon (they were all blank:
    the page asked the window for an icon loader the skill-tree rework had removed, and printed
    "hotkeys: no icon" for each)."""
    import mxl_hotkeys as HK
    cw = start('hotkeys')
    page = cw.extra['hotkeys']
    if cw._theme_art() is None:
        T.skip('no game folder: no skill icons')
    in_trees = {sid for _t, _n, cells in cw.sktree.trees for _r, _c, sid, _cel in cells}
    slots = [o for o in page.cells if page.skill_at(o)[0] in in_trees]
    if not slots:
        sid = skill_pick(cw, lambda lv: True)
        page.assign(HK.HOTKEY_OFF, sid)
        T.pump(3)
        slots = [HK.HOTKEY_OFF]
    for o in slots:
        sid = page.skill_at(o)[0]
        T.check(page._icon(sid) is not None, f'no icon for class skill {sid}')
        T.check(str(page.cells[o]['icon'].cget('image')) != str(page._blank), f'slot 0x{o:02X} shows a blank icon')
    page.revert()


# ------------------------------------------------------------------------------------------- Mercenary
@T.test
def mercenary_name_is_saved():
    single('mercenary name', edit_merc, 'merc')


@T.test
def mercenary_level_dead_and_type():
    import mxl_merc as MM
    cw = start('merc')
    c = Ctx()
    page = cw.extra['merc']
    if not cw.ch.merc_hired:
        T.skip('the sample character has no mercenary')
    rec = dict(page.rec)
    xpl = page.xpl()
    lv = MM.level_for_exp(xpl, rec['exp'])
    new_lv = lv - 1 if lv > 1 else lv + 1
    page.e_level.focus_force()
    retype(page.e_level, new_lv)
    press_key(page.e_level, '<KeyRelease>', lambda: page.v_exp.get() == str(MM.exp_for_level(xpl, new_lv)), page.on_level)
    T.eq(page.v_exp.get(), str(MM.exp_for_level(xpl, new_lv)), 'experience after typing a level')
    page.cb_dead.invoke()
    T.pump(3)
    stone(cw, 'save_progress')
    no_boxes('mercenary')
    r0 = MM.RECORD.start
    a = struct.pack('<HIHHI', rec['dead'], rec['id'], rec['name'], rec['type'], rec['exp'])
    b = struct.pack('<HIHHI', 0 if rec['dead'] else 1, rec['id'], rec['name'], rec['type'], MM.exp_for_level(xpl, new_lv))
    T.eq(c.before['head'][r0:r0 + len(a)], a, 'the record as this test reads it')
    c.after('mercenary level + dead', {'head': {r0 + i: (a[i], b[i]) for i in range(len(a)) if a[i] != b[i]}})
    import mxl_char
    T.eq(MM.level(mxl_char.Character(c.path, G.app.data)), new_lv, 'the saved mercenary level')


@T.test
def mercenary_bad_experience_refuses_the_save_and_keeps_the_edits():
    """Junk in the experience box: SAVE is refused with a message, nothing is written, and neither the junk's
    page nor the other pages lose what was edited (the whole window used to be reloaded)."""
    cw = start('merc')
    c = Ctx()
    page = cw.extra['merc']
    if not cw.ch.merc_hired:
        T.skip('the sample character has no mercenary')
    exp, shown = edit_stat(cw)
    exp2, shown2 = edit_counter(cw)
    show(cw, 'merc')
    good = page.v_exp.get()
    retype(page.e_exp, 'lots')
    stone(cw, 'save_progress')
    T.check(any(b[0] == 'showerror' for b in G.boxes), 'no message for the refused save')
    del G.boxes[:]
    c.same_file('refused SAVE')
    T.check(shown() and shown2(), 'the edits of the other pages were dropped by the refused save')
    T.check(cw.dirty(), 'no unsaved-changes state after the refused save')
    retype(page.e_exp, good)
    page.on_exp()
    stone(cw, 'save_progress')
    no_boxes('SAVE after correcting the box')
    c.after('SAVE after correcting the box', merge(exp, exp2))


# ------------------------------------------------------------------------------------------- SAVE / RELOAD / CLOSE
@T.test
def save_without_edits_is_byte_identical():
    cw = start('stats')
    c = Ctx()
    for page in cw.pages:
        show(cw, page)
        T.check(not cw.dirty(), f'unsaved changes after only opening {page!r}')
    stone(cw, 'save_progress')
    no_boxes('SAVE without edits')
    c.same_file('SAVE without edits')
    c.after('SAVE without edits', {})


@T.test
def save_of_every_page_at_once():
    """One edit on each of the eight pages, one SAVE: one consistent file with all of them."""
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    c.same_file('before SAVE')
    stone(cw, 'save_progress')
    no_boxes('SAVE of every page')
    c.after('SAVE of every page', exp)
    T.check(not cw.dirty(), 'still unsaved changes after SAVE')
    stone(cw, 'save_progress')                           # and a second SAVE changes nothing more
    c.after('second SAVE', exp)


@T.test
def reload_discards_every_pending_edit():
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    stone(cw, 'discard')
    no_boxes('RELOAD')
    T.check(not cw.dirty(), 'still unsaved changes after RELOAD')
    for name, s in shown.items():
        T.check(not s(), f'RELOAD kept the pending {name} edit')
    T.eq(cw.bar_status.cget('text'), '', 'status line after RELOAD')
    c.same_file('RELOAD')
    stone(cw, 'save_progress')
    c.same_file('SAVE after RELOAD')


@T.test
def close_asks_about_unsaved_changes():
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    G.answers['askyesnocancel'] = None                   # Cancel: the tab stays, the edits too
    stone(cw, 'close')
    T.check(any(b[0] == 'askyesnocancel' for b in G.boxes), 'CLOSE with unsaved changes did not ask')
    T.check(T.chartab() is cw, 'Cancel closed the tab')
    still(shown, 'Cancel')
    c.same_file('CLOSE + Cancel')
    del G.boxes[:]
    G.answers['askyesnocancel'] = False                  # No: closed, nothing written
    stone(cw, 'close')
    T.check(T.chartab() is None, 'No did not close the tab')
    c.same_file('CLOSE + No')
    cw = start('stats')                                  # built again: the file, nothing pending
    T.check(not cw.dirty(), 'the reopened tab has unsaved changes')
    exp, shown = edit_all(cw)
    del G.boxes[:]
    G.answers['askyesnocancel'] = True                   # Yes: saved, then closed
    stone(cw, 'close')
    T.check(any(b[0] == 'askyesnocancel' for b in G.boxes), 'CLOSE with unsaved changes did not ask (second time)')
    T.check(T.chartab() is None, 'Yes did not close the tab')
    c.after('CLOSE + Yes', exp, views=False)
    del G.boxes[:]
    cw = start('stats')
    stone(cw, 'close')                                   # nothing pending: no question
    T.check(not G.boxes, f'CLOSE without changes asked: {G.boxes}')
    T.check(T.chartab() is None, 'CLOSE did not close the tab')
    start('stats')


# ------------------------------------------------------------------------------------------- other writers
def inventory_item():
    """Place ('inv', x, y) and snapshot key of an item in the character's inventory."""
    import mxl_char
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    for e in ch.inventory():
        it = e.it
        return ('inv', it['x'], it['y']), (False, it['location'], it.get('equipped'), it['x'], it['y'], it.get('panel'))
    T.skip('the sample character has an empty inventory')


@T.test
def panel_item_action_keeps_pending_edits():
    """An item deleted on the Stash tab's character panel while the Character tab holds unsaved edits: the item
    is gone from the file at once, the edits stay pending on top of the new file, and SAVE writes both - no
    refused save, no stale overwrite (the tab was left on its old copy before, then SAVE was refused and
    every edit dropped)."""
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    where, k = inventory_item()
    T.select_tab('Stash')
    T.invoke(T.panel_menu(where), 'Delete')
    T.pump(8)
    no_boxes('panel delete')
    c.after('panel delete with edits pending elsewhere', {}, gone=[k])
    still(shown, 'after the panel action')
    T.check(cw.dirty(), 'the Character tab lost its unsaved state')
    T.select_tab('Character')
    T.pump(4)
    still(shown, 'back on the Character tab')
    stone(cw, 'save_progress')
    no_boxes('SAVE after the panel action')
    c.after('SAVE after the panel action', exp, gone=[k])
    T.check(not cw.dirty(), 'still unsaved changes after SAVE')


@T.test
def inventory_page_item_action_keeps_pending_edits():
    """The same from the Character tab's own Inventory page (its right-click menu writes the file at once): the
    plug-in pages used to forget their edits there, and typed skill levels were reset."""
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    where, k = inventory_item()
    show(cw, 'inventory')
    cw.merc.set(False)
    cw.on_view()
    T.invoke(T.chartab_menu(where), 'Delete')
    T.pump(8)
    no_boxes('inventory page delete')
    c.after('inventory page delete with edits pending', {}, gone=[k])
    still(shown, 'after the item action')
    T.check(cw.dirty(), 'the Character tab lost its unsaved state')
    stone(cw, 'save_progress')
    no_boxes('SAVE after the item action')
    c.after('SAVE after the item action', exp, gone=[k])


@T.test
def refused_item_drag_keeps_pending_edits():
    """An item dragged to a slot that cannot take it: nothing is written, the character is read again - and the
    edits pending on the pages survive that."""
    import mxl_char
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    show(cw, 'inventory')
    cw.merc.set(False)
    cw.on_view()
    T.pump(4)
    ch = cw.ch
    src = next((e for e in ch.inventory() if mxl_char.SLOTS[6] not in mxl_char.item_bodylocs(G.app.data, e.it['code'])), None)
    if src is None:
        T.skip('every inventory item of the sample is a ring')
    cell = cw.cell
    x, y = (src.it['x'] + .5) * cell, (src.it['y'] + .5) * cell
    bx, by, bw, bh = __import__('mxl_char_gui').DOLL[6]                   # the right ring slot
    rx, ry = cw.doll.winfo_rootx() + int((bx + bw / 2) * cell), cw.doll.winfo_rooty() + int((by + bh / 2) * cell)
    cw.inv.event_generate('<ButtonPress-1>', x=int(x), y=int(y))
    cw.inv.event_generate('<B1-Motion>', x=int(x) + 6, y=int(y) + 6)
    cw.inv.event_generate('<ButtonRelease-1>', x=int(x), y=int(y), rootx=rx, rooty=ry)
    T.pump(6)
    T.check('#e06060' in str(cw.status.cget('foreground')), f'the drag was not refused: {cw.status.cget("text")!r}')
    c.same_file('refused drag')
    still(shown, 'after the refused drag')
    stone(cw, 'save_progress')
    no_boxes('SAVE after the refused drag')
    c.after('SAVE after the refused drag', exp)


@T.test
def file_changed_behind_the_editor_is_not_overwritten():
    """The file is rewritten by someone else (here: another Character object, as the game would on save & exit)
    while edits are pending, and nothing told the editor. This build's Character.save does not refuse a file
    that changed on disk (mxl_free: it used to write its stale copy over it, the other writer's change was gone).
    SAVE must read the file again first and put the pending edits on top of the other writer's change."""
    import mxl_char
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    other = mxl_char.Character(c.path, G.app.data)
    gold = other.field('gold_stash')
    theirs_gold = gold - 4321 if gold >= 4321 else gold + 4321
    other.set_field('gold_stash', theirs_gold)
    other.save(backup=False)
    T.check(T.read(c.path) != c.before['raw'], 'the other writer did not change the file')
    still(shown, 'after the other writer')
    stone(cw, 'save_progress')
    no_boxes('SAVE')
    c.after('SAVE over a file changed on disk', merge(exp, {'stats': {(15, 0): (gold or None, theirs_gold or None)}}))
    T.check(not cw.dirty(), 'still unsaved changes after SAVE')


def other_writer(c):
    """Someone else (as the game on save & exit) changes the stash gold of the file; nothing tells the editor.
    -> the expected delta of that change."""
    import mxl_char
    other = mxl_char.Character(c.path, G.app.data)
    gold = other.field('gold_stash')
    theirs = gold - 4321 if gold >= 4321 else gold + 4321
    other.set_field('gold_stash', theirs)
    other.save(backup=False)
    T.check(T.read(c.path) != c.before['raw'], 'the other writer did not change the file')
    return {'stats': {(15, 0): (gold or None, theirs or None)}}


@T.test
def item_action_on_the_tab_after_a_change_on_disk():
    """The file changes behind the editor, then an item is deleted from the Character tab's own Inventory page
    (right-click menu): the action used to change the tab's older copy and Character.save (mxl_free) wrote that
    copy over the file - the other writer's change was gone. Now the tab reads the file again when the item is
    picked: the item goes, the other change stays, the pending page edits stay pending and SAVE writes them."""
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    where, k = inventory_item()
    show(cw, 'inventory')
    cw.merc.set(False)
    cw.on_view()
    theirs = other_writer(c)
    T.invoke(T.chartab_menu(where), 'Delete')
    T.pump(8)
    no_boxes('delete after the change on disk')
    c.after('delete after the change on disk', theirs, gone=[k])
    still(shown, 'after the item action')
    T.check(cw.dirty(), 'the Character tab lost its unsaved state')
    stone(cw, 'save_progress')
    no_boxes('SAVE')
    c.after('SAVE after the item action', merge(exp, theirs), gone=[k])


@T.test
def item_action_refused_when_the_file_changes_after_the_pick():
    """The menu is opened (item picked from the file as it was), THEN the file changes on disk, then Delete is
    chosen: the tab's copy is out of date, so nothing is written - the other writer's file stays as it is, the
    tab reads it again, says so, and keeps the pending page edits."""
    cw = start('stats')
    c = Ctx()
    exp, shown = edit_all(cw)
    where, k = inventory_item()
    show(cw, 'inventory')
    cw.merc.set(False)
    cw.on_view()
    m = T.chartab_menu(where)
    theirs = other_writer(c)
    written = T.read(c.path)
    T.invoke(m, 'Delete')
    T.pump(8)
    T.check(T.read(c.path) == written, 'the item action wrote its out-of-date copy over the changed file')
    c.after('refused item action', theirs, views=False)
    T.check(bytes(cw.ch.raw) == written, 'the Character tab did not read the changed file again')
    T.check('#e06060' in str(cw.status.cget('foreground')), f'no error shown: {cw.status.cget("text")!r}')
    still(shown, 'after the refused item action')
    stone(cw, 'save_progress')
    no_boxes('SAVE')
    c.after('SAVE after the refused item action', merge(exp, theirs))


@T.test
def stash_tab_write_then_save_without_pending_edits():
    """Nothing pending: after an item action of the panel the Character tab simply shows the new file, and its
    SAVE writes nothing."""
    cw = start('stats')
    c = Ctx()
    where, k = inventory_item()
    T.select_tab('Stash')
    T.invoke(T.panel_menu(where), 'Delete')
    T.pump(8)
    c.after('panel delete', {}, gone=[k])
    T.check(not cw.dirty(), 'unsaved changes out of nowhere')
    now = T.read(c.path)
    T.select_tab('Character')
    stone(cw, 'save_progress')
    no_boxes('SAVE')
    T.check(T.read(c.path) == now, 'SAVE without edits changed the file')


# ------------------------------------------------------------------------------------------- the dropdown
def second_character(name='Zweiter'):
    import mxl_char
    src = G.app.character_file()
    dst = mxl_char.copy_character(src, name, G.app.data)
    return src, dst


def pick(name):
    app = G.app
    app.select_character(name, app.view.get())
    app.open_view(keep_page=True)
    T.pump(10)
    T.settle(0.3)


@T.test
def another_character_in_the_dropdown_with_pending_edits():
    """Edits pending, then another character is picked in the main window: the tab stays on the edited character
    (nothing lost, nothing written to either file); SAVE writes the edited character's file only and the tab then
    moves to the picked character. Without pending edits it follows at once."""
    cw = start('stats')
    first = os.path.splitext(os.path.basename(cw.ch.path))[0]
    src, dst = second_character()
    try:
        c = Ctx()
        copy = T.read(dst)
        exp, shown = edit_all(cw)
        pick('Zweiter')
        T.eq(os.path.abspath(G.app.character_file()), os.path.abspath(dst), 'the main window after picking the copy')
        cw2 = T.chartab()
        T.check(cw2 is cw and os.path.abspath(cw.ch.path) == os.path.abspath(src), 'the tab with unsaved edits was replaced')
        still(shown, 'after picking another character')
        c.same_file('picking another character')
        T.check(T.read(dst) == copy, 'the picked character was written')
        T.select_tab('Character')
        stone(cw, 'save_progress')
        no_boxes('SAVE with another character picked')
        c.after('SAVE with another character picked', exp, views=False)
        T.check(T.read(dst) == copy, 'SAVE wrote the picked character')
        T.settle(0.5)
        cw3 = T.chartab()
        T.check(cw3 is not None and os.path.abspath(cw3.ch.path) == os.path.abspath(dst), 'after SAVE the tab did not move to the picked character')
        T.check(cw3 is not None and not cw3.dirty(), 'the new tab has unsaved changes')
        pick(first)                                      # nothing pending: follows at once
        cw4 = T.chartab()
        T.check(cw4 is not None and os.path.abspath(cw4.ch.path) == os.path.abspath(src), 'the tab did not follow the dropdown back')
        T.check(cw4 is not None and bytes(cw4.ch.raw) == T.read(src), 'the tab does not hold the saved file')
    finally:
        del G.boxes[:]
        pick(first)


@T.test
def attack_and_other_skills_have_an_icon_on_the_stat_screen():
    """Page 1's skill frames and names: Attack (skill 0, outside every skill tree; icons-shared.dc6) and a class skill both
    get an icon (Attack had none: the frame stayed empty)."""
    cw = start('stats')
    T.eq(cw._sk_name(0), 'Attack', "Attack's name (no entry in the collector's skill names: was 'hidden #0')")
    scr = cw.statscreen
    if scr is None:
        T.skip('this theme has no game stat screen')
    cls = cw.st_sim.cls
    T.check(scr._skill_icon(cls, 0) is not None, 'Attack has an icon')
    own = next((sid for sid, lv in cw.st_sim.skill_levels().items() if lv), None)
    if own is not None:
        T.check(scr._skill_icon(cls, own) is not None, f'class skill {own} has an icon')


@T.test
def events_reached_the_widgets():
    """Not a check of the application: reports which key / pointer events had to be replaced by their handlers on
    this X server (see press_key())."""
    if FELL_BACK:
        T.skip('handlers called directly instead of these events: ' + ', '.join(sorted(FELL_BACK)))


T.main(globals())
