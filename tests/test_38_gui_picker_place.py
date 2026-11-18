"""Where the attribute picker popup of the Creator's slot list ("Magic Attributes", unrestricted mode) opens: on the
screen, and - where the screen has room - not over the slot list it fills (at 800x600 it covered the list: the user
could not see the slot being filled). Beside the list when there is room, else above / below the list, else below
the slot's row with its height cut to the room, flipped above the row when there is more room there.
Also: typing in the popup and Enter still takes the closest match into the slot, the name list of a slot's
parameter is placed the same way, and the window goes idle with the popup open (no layout loop, W24).

The placement rule itself (mxl_attr_picker.place) is checked on screen sizes 800x600 / 1280x720 / 2560x1440 with
the list where the Creator puts it; the real popup on the X screen of the run (1280x720 in tools/run_tests.sh;
start tests/run.py under `xvfb-run -s "-screen 0 800x600x24"` for a real small screen).
Set CAPY_SHOTS=<folder> for screenshots."""
import os
import subprocess

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {
    'd2-1280x720': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0'},
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
    'he-800x600': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0'},
}
G = T.G
MAX_CALLS, MAX_CONFIGURES = 120, 12                 # as in test_36_gui_character_layout


def shot(name):
    folder = os.environ.get('CAPY_SHOTS')
    if not folder:
        return
    os.makedirs(folder, exist_ok=True)
    G.root.update()
    try:
        subprocess.run(['import', '-window', 'root', os.path.join(folder, f'picker-{T.VARIANT}-{name}.png')],
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


def rect(w):
    return w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()


def overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))


def inside(a, sw, sh):
    x, y, w, h = a
    return x >= 0 and y >= 0 and x + w <= sw and y + h <= sh


def creator_with_slots():
    """The Creator tab on a unique armor in unrestricted mode: its slot list is shown."""
    import mxl_creator_gui as CG
    import mxl_tabs
    CG.CreatorWindow(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    if w is None:
        raise T.Failed('no Creator window')
    w.unrestricted.set(True)
    w.set_unrestricted()
    w.search.set('')
    w.quality.set(dict((k, lab) for lab, k in CG.qualities())['unique'])
    w.on_quality()
    T.pump()
    i = next(i for i, (_l, row) in enumerate(w.entries) if G.app.data.base(G.app.data.uniques[row]['code']).kind == 'armor')
    w.listbox.selection_clear(0, 'end')
    w.listbox.selection_set(i)
    w.on_pick()
    T.settle(0.5)
    if not w._slots_alive():
        raise T.Failed('the slot list is not shown')
    w.scroll.canvas.yview_moveto(1.0)               # the list in view, as when the user clicks a slot
    T.settle(0.3)
    return w


def empty_slot(w):
    return next(n for n, r in enumerate(w.slots.rows) if r['kind'] == 'slot' and r['s'] is None)


@T.test
def placement_rule():
    """mxl_attr_picker.place on the screen sizes of the bug report, the list where the Creator has it."""
    import mxl_attr_picker as AP
    want = (546, 352)
    for sw, sh, lst in ((800, 600, (215, 250, 330, 260)), (800, 600, (100, 40, 600, 520)),
                        (1280, 720, (420, 260, 420, 300)), (2560, 1440, (420, 260, 420, 300)),
                        (800, 600, (0, 0, 800, 560))):
        for row in (0, 5, lst[3] // 20 - 1):
            anchor = (lst[0] + 2, lst[1] + row * 20, 200, 20)
            x, y, w, h = AP.place(want[0], want[1], sw, sh, anchor, lst, min_w=300, min_h=160)
            what = f'screen {sw}x{sh}, list {lst}, slot row {row}: popup {(x, y, w, h)}'
            T.check(inside((x, y, w, h), sw, sh), f'{what} leaves the screen')
            T.check(w >= 300 and h >= 160 or (w, h) == (min(want[0], sw - 16), h), f'{what} is too small')
            T.check(overlap((x, y, w, h), anchor) == 0, f'{what} covers the slot being filled')
            free = (sw - lst[0] - lst[2] >= 300 or lst[0] >= 300 or sh - 32 - lst[1] - lst[3] >= 160 or lst[1] >= 160)
            if free:
                T.check(overlap((x, y, w, h), lst) == 0, f'{what} covers the list although there is room')


@T.test
def stat_popup_beside_the_list_typeahead_and_enter():
    w = creator_with_slots()
    n = empty_slot(w)
    w.slots.select(n)
    w.slot_pick(n, 'fire res')
    T.settle(0.4)
    top = w._popup
    T.check(top is not None and top.winfo_exists(), 'the picker did not open')
    G.root.update()
    sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
    pop, lst, cell = rect(top), rect(w.slots.cv), w.slots.anchor(n)
    cell = (cell.winfo_rootx(), cell.winfo_rooty(), 100, cell.winfo_height())
    shot('stat-popup')
    T.check(inside(pop, sw, sh + 1), f'popup {pop} is not on the {sw}x{sh} screen')
    T.eq(overlap(pop, cell), 0, f'popup {pop} covers the slot row {cell}')
    T.eq(overlap(pop, lst), 0, f'popup {pop} covers the slot list {lst} (screen {sw}x{sh})')
    calls, confs = activity(1.0)
    T.check(calls <= MAX_CALLS and confs <= MAX_CONFIGURES,
            f'the popup does not come to rest: {calls} Tk callbacks and {confs} <Configure> events in one second')
    p = top.picker
    T.eq(p.var.get(), 'fire res', 'text typed into the slot reaches the popup filter')
    want = p.current()
    T.check(want is not None, 'no match for "fire res"')
    # Xvfb has no window manager: X keyboard focus follows the pointer, which may be outside the popup (at
    # 2560x1440 it is); a window manager gives the new popup the focus, focus_force() does it here
    p.entry.focus_force()
    G.root.update()
    p.entry.event_generate('<Return>')
    T.settle(0.4)
    T.check(not top.winfo_exists(), 'Enter did not close the popup')
    r = w.slots.rows[n]
    T.check(r['s'] is not None and r['s']['id'] == want, f'slot {n} holds {r["s"] and r["s"]["id"]}, Enter picked {want}')


@T.test
def name_popup_placed_the_same_way():
    w = creator_with_slots()
    n = empty_slot(w)
    names = ['Alpha', 'Beta', 'Gamma', 'Delta'] * 10
    top = w._name_popup(w.slots.anchor(n, 'name'), names, lambda _n: None, 'ga', None, 'test', parent=w.slots.cv)
    T.settle(0.4)
    G.root.update()
    sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
    pop, lst = rect(top), rect(w.slots.cv)
    shot('name-popup')
    T.check(inside(pop, sw, sh + 1), f'name popup {pop} is not on the {sw}x{sh} screen')
    T.eq(overlap(pop, lst), 0, f'name popup {pop} covers the slot list {lst}')
    T.eq(top.picker.var.get(), 'ga', 'typed text in the name popup')
    w._close_popup()


T.main(globals())
