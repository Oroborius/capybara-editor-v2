"""The Creator tab and the Item Editor at small window sizes: every control of the three columns is inside its
column - no horizontal scrolling. At 800x600 the middle column's corruption row ("Roll like the cube" right of a
40 characters wide box) was wider than the column: the button was only reachable with the horizontal scrollbar.
Checked for every item type of the Creator (a weapon of each, when there is one: sockets, corruption, ethereal...),
in unrestricted mode as well (the slot list), and in the Item Editor on items of the stash; then the window has to
go idle (no layout loop, W24: fold() of the bottom row / the paned window's separators / the scroll area's
horizontal scrollbar ping-ponged at 1280x720).
Set CAPY_SHOTS=<folder> for screenshots."""
import os
import subprocess

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
    'he-800x600': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0'},
    'd2-800x600-scale1.25': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0', 'MXL_UI_SCALE': '1.25'},
    'he-800x600-scale1.25': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0', 'MXL_UI_SCALE': '1.25'},
    'd2-1280x720': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0'},
    'he-1280x720': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '1280x720+0+0'},
}
if os.environ.get('CAPY_BIG'):    # (the runner reads VARIANTS without running this): every variant at 2560x1440,
    os.environ['CAPY_GEOMETRY'] = '2560x1440+0+0'   # on an X screen of that size (xvfb-run -s "-screen 0 2560x1440x24")
G = T.G
MAX_CALLS, MAX_CONFIGURES = 120, 12                 # as in test_36_gui_character_layout


def shot(name):
    folder = os.environ.get('CAPY_SHOTS')
    if not folder:
        return
    os.makedirs(folder, exist_ok=True)
    G.root.update()
    try:
        subprocess.run(['import', '-window', 'root', os.path.join(folder, f'creator-{T.VARIANT}-{name}.png')],
                       timeout=30, capture_output=True)
    except Exception:
        pass


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


def creator():
    import mxl_creator_gui as CG
    import mxl_tabs
    CG.CreatorWindow(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    if w is None or w.edit_item is not None:
        raise T.Failed('no Creator window')
    T.select_tab('Creator')
    T.settle(0.3)
    return w


def mapped(w):
    out = []
    for c in w.winfo_children():
        try:
            if c.winfo_ismapped() and c.winfo_class() not in ('Toplevel', 'Menu'):
                out.append(c)
                out.extend(mapped(c))
        except Exception:
            pass
    return out


def name(c):
    try:
        t = str(c.cget('text'))
    except Exception:
        t = ''
    path = '.'.join(str(c).split('.')[-3:])
    return f'{c.winfo_class()} {t[:30]!r} ({path})' if t else f'{c.winfo_class()} ({path})'


def clipped(w):
    """Controls of the Creator outside their column (or the columns outside the window): [description]."""
    G.root.update()
    bad = []
    rx, rw = G.root.winfo_rootx(), G.root.winfo_width()
    pr = w.paned.winfo_rootx() + w.paned.winfo_width()
    if pr > rx + rw + 1:
        bad.append(f'the columns end at x {pr - rx}, the window at {rw}')
    if w.scroll._hsb_on:
        bad.append(f'horizontal scrollbar in the middle column (content {w.scroll.inner.winfo_reqwidth()} px, '
                   f'column {w.scroll.canvas.winfo_width()} px)')
    cv = w.scroll.canvas
    view = (cv.winfo_rootx(), cv.winfo_rootx() + cv.winfo_width())
    for pane in w.paned.panes():
        pane = G.root.nametowidget(str(pane))
        x0, x1 = pane.winfo_rootx(), pane.winfo_rootx() + pane.winfo_width()
        for c in mapped(pane):
            if c is w.scroll.inner or c.winfo_width() <= 1:
                continue
            l, r = c.winfo_rootx(), c.winfo_rootx() + c.winfo_width()
            lo, hi = (view if str(c).startswith(str(w.scroll.inner) + '.') else (x0, x1))
            if l < lo - 1 or r > hi + 1:
                bad.append(f'{name(c)} at x {l - rx}..{r - rx}, its column {lo - rx}..{hi - rx}')
    return bad


def weapon_entry(w, key):
    """Index of the first list entry of the quality `key` whose item is a weapon (most option rows), else 0."""
    import mxl_creator_gui as CG
    w.search.set('')
    w.quality.set(dict((k, lab) for lab, k in CG.qualities())[key])
    w.on_quality()
    T.pump()
    if not w.entries:
        return None
    d = G.app.data
    for i, (_lab, row) in enumerate(w.entries[:400]):
        try:
            spec = w.cr.new_spec(key, row=row)
            if d.base(spec['code']).kind == 'weapons' and (key in ('runeword', 'set', 'unique') or w.cr.corrupt_choices(spec)):
                return i
        except Exception:
            continue
    return 0


def pick(w, i):
    w.listbox.selection_clear(0, 'end')
    w.listbox.selection_set(i)
    w.listbox.see(i)
    w.on_pick()
    T.settle(0.6)


def popdown_is_wide(w):
    """The corruption box asks for little room now (it takes the column's width): its list still opens as wide as
    its longest entry, on the screen."""
    from tkinter import font as tkfont
    cbs = [c for c in mapped(w.opts) if c.winfo_class() == 'TCombobox' and str(c.cget('postcommand'))
           and any('corrupted' in str(v) for v in c.tk.splitlist(c.cget('values')))]
    if not cbs:
        return
    cb = cbs[0]
    vals = cb.tk.splitlist(cb.cget('values'))
    cb.tk.call('ttk::combobox::Post', str(cb))
    try:
        T.settle(0.3)
        pd = cb.tk.call('ttk::combobox::PopdownWindow', str(cb))
        f = tkfont.Font(root=cb, font=cb.tk.call(f'{pd}.f.l', 'cget', '-font'))
        want = min(max(f.measure(str(v)) for v in vals), cb.winfo_screenwidth() - 24)
        pw, px = int(cb.tk.call('winfo', 'width', pd)), int(cb.tk.call('winfo', 'rootx', pd))
        shot('corruption-list')
        T.check(pw >= want and pw >= cb.winfo_width(),
                f'corruption list {pw} px wide, box {cb.winfo_width()} px, longest entry {want} px')
        T.check(px >= 0 and px + pw <= cb.winfo_screenwidth(), f'corruption list at x {px}..{px + pw}: off the screen')
    finally:
        cb.tk.call('ttk::combobox::Unpost', str(cb))
        T.settle(0.2)


@T.test
def every_item_type_fits_the_columns():
    import mxl_creator_gui as CG
    w = creator()
    seen_cube = False
    for unrestricted in (False, True):
        w.unrestricted.set(unrestricted)
        w.set_unrestricted()
        for _lab, key in CG.qualities():
            i = weapon_entry(w, key)
            if i is None:
                continue
            pick(w, i)
            if w.spec is None:
                continue
            seen_cube = seen_cube or any('Roll like' in name(c) for c in mapped(w.scroll.inner))
            for where in (0.0, 1.0):
                w.scroll.canvas.yview_moveto(where)
                T.settle(0.2)
                bad = clipped(w)
                T.check(not bad, f'{key} ({w.entries[i][0]!r}, unrestricted {unrestricted}): ' + '; '.join(bad[:4]))
            if key in ('unique', 'rare') and not unrestricted:
                shot(key)
                popdown_is_wide(w)
    T.check(seen_cube, 'no item with the "Roll like the cube" button was shown')
    calls, confs = activity(1.0)
    T.check(calls <= MAX_CALLS and confs <= MAX_CONFIGURES,
            f'the Creator does not come to rest: {calls} Tk callbacks and {confs} <Configure> events in one second')


@T.test
def item_editor_fits_the_columns():
    import mxl_creator as C
    import mxl_creator_gui as CG
    import mxl_save
    import mxl_tabs
    raw = T.read(G.app.path)
    want = {'unique': 2, 'rare': 2, 'set': 1, 'magic': 1, 'crafted': 1, None: 2}     # quality -> items to open
    done = 0
    for it in sorted(G.app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        try:
            rec = T.rec_of(mxl_save.item_blob(raw, it))
            q = None if rec['flags'] & C.FLAG_SIMPLE else rec['quality']
        except Exception:
            q = None
        q = q if q in want else None
        if want[q] <= 0:
            continue
        want[q] -= 1
        G.app.selected = it
        CG.edit_selected(G.app)
        T.pump(10)
        w = mxl_tabs.built_owner('Creator')
        if w is None or w.edit_item is None or w.spec is None:
            continue
        done += 1
        T.select_tab('Creator')
        T.settle(0.6)
        bad = clipped(w)
        T.check(not bad, f'Item Editor on {w.title.cget("text")!r}: ' + '; '.join(bad[:4]))
        if done == 1:
            shot('editor')
            calls, confs = activity(1.0)
            T.check(calls <= MAX_CALLS and confs <= MAX_CONFIGURES,
                    f'the Item Editor does not come to rest: {calls} callbacks and {confs} <Configure> events')
    T.check(done > 0, 'no stash item opened in the Item Editor')


T.main(globals())
