"""The mouse wheel and the stat screen's page arrows (user report on the Linux AppImage, Tk 9 under XWayland, UI scale
1.25: "the page count doesn't actually go up to 5. It skips numbers" and "it scrolls really slowly or not at all
in the stats page").

- Page arrows of the Stats page (dark look): as an open book the pages went 1-2, 3-4, 4-5 - the left page number
  read 1, 3, 4 (2 skipped, 5 never). Now every turn moves one page, each visible number counts up by exactly 1,
  every page is reached, the view is always a full book of the same width.
- "All Item Attributes" list: every notch redrew both panels (60-100 ms); a quick turn of the wheel or a touchpad
  swipe queued one redraw per notch and the list crawled on for seconds. Now the redraws are merged. Real wheel
  clicks go through the X server (xdotool, skipped without it): that is the only way to see how this Tk turns
  X buttons 4/5 into events (Tk 9: one <MouseWheel> delta +-120 per click, <Button-4>/<Button-5> = side buttons).
- One notch is handled once: by the list, or by the page around it when the list cannot move - never by both.
- Over dropdowns / spinboxes of a scrolling page or of the Creator the wheel scrolls; it never changes their value.
The arithmetic of mxl_scroll's wheel helper (Tk 8.6 / Tk 9 / touchpads) is tested in test_21_wheel_notches."""
import shutil
import subprocess
import time

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {
    'd2-scale1.25': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0', 'MXL_UI_SCALE': '1.25'},
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
}
G = T.G
XDOTOOL = shutil.which('xdotool')


def stats_screen():
    import mxl_char_gui
    cw = T.chartab()
    if cw is None or getattr(cw, 'ch', None) is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    T.select_tab('Character')
    if cw.tab.get() != 'stats':
        cw.tab.set('stats')
        cw.show_tab()
    T.settle(0.3)
    scr = cw.statscreen
    if scr is None:
        T.skip('no stat screen (light look)')
    return cw, scr


def numbers(scr):
    return [scr.pages.index(p) + 1 for p in scr.shown]


def wheel(widget, delta, x=None, y=None):
    """One synthetic notch (delta 120 = up) over the widget."""
    widget.event_generate('<MouseWheel>', delta=delta, x=widget.winfo_width() // 2 if x is None else x,
                          y=min(widget.winfo_height() // 2, 200) if y is None else y)
    T.pump(3)


def pointer_to(widget, x, y):
    subprocess.run([XDOTOOL, 'mousemove', str(widget.winfo_rootx() + int(x)), str(widget.winfo_rooty() + int(y))])
    T.pump(3, 0.02)


def list_point(scr):
    """A point inside the totals list (canvas coordinates)."""
    import mxl_statscreen as S
    slot = scr.shown.index('totals')
    x, y, w, h = S.LIST_BOX
    pw = round(S.PANEL_W * scr.k)
    return slot * pw + (x + w / 2) * scr.k, (y + h / 2) * scr.k


def show_totals(cw, scr):
    scr.show_page('totals', exact=True)
    scr.scroll_at = 0
    scr.redraw()
    T.pump(4)
    if getattr(scr, '_list_top', None) is None or scr._list_top < 12:
        T.skip(f'the totals list is too short to scroll ({scr._list_top})')


# --------------------------------------------------------------------------------------------- page arrows
@T.test
def stat_page_numbers_count_up_to_the_last_page():
    cw, scr = stats_screen()
    n = len(scr.pages)
    scr.show_page('main')
    T.pump(4)
    width = scr.cv.winfo_reqwidth()
    seen, views = set(), []
    for _ in range(n + 2):
        views.append(numbers(scr))
        seen.update(numbers(scr))
        T.eq(len(scr.shown), scr.spread, f'pages side by side on {scr.shown}')
        T.eq(scr.cv.winfo_reqwidth(), width, f'width of the stat screen on {scr.shown}')
        scr.activate('page', 'next')
        T.pump(2)
    T.eq(seen, set(range(1, n + 1)), f'pages reached with the next arrow ({views})')
    last = n - scr.spread + 1
    want = list(range(1, last + 1))
    lefts = [v[0] for v in views]
    T.eq(lefts[:last + 1], want + [1], f'left page numbers, one click each ({views})')
    for a, b in zip(views, views[1:]):                       # every number on screen moves by exactly one page
        if a[0] != last:
            T.eq([y - x for x, y in zip(a, b)], [1] * scr.spread, f'turn from {a} to {b}')
    # backwards, and the Prior / Next keys
    scr.show_page('main')
    T.pump(2)
    back = []
    for _ in range(last):
        scr.activate('page', 'prev')
        T.pump(2)
        back.append(numbers(scr)[0])
    T.eq(back, list(range(last, 0, -1)), 'left page numbers with the previous arrow')
    scr.turn(1)
    T.eq(numbers(scr)[0], 2, 'Next key: one page on')
    # a page asked for near the end still fills the book
    scr.show_page('saved', exact=True)
    T.pump(2)
    T.eq(len(scr.shown), scr.spread, 'pages shown for Saved values')
    T.check('saved' in scr.shown and scr.shown[-1] == 'saved', f'Saved values shown last: {scr.shown}')


# ----------------------------------------------------------------------------------------- the totals list
@T.test
def one_notch_moves_the_totals_list_once():
    cw, scr = stats_screen()
    show_totals(cw, scr)
    x, y = list_point(scr)
    page_before = cw.scroll.canvas.yview()
    wheel(scr.cv, -120, x, y)
    T.pump(4)
    T.eq(scr.scroll_at, 3, 'rows moved by one notch down')
    T.eq(cw.scroll.canvas.yview(), page_before, 'the page around moved with the list')
    wheel(scr.cv, 120, x, y)
    T.pump(4)
    T.eq(scr.scroll_at, 0, 'rows after one notch back up')
    # Tk 9: <Button-4>/<Button-5> are the mouse's side buttons, not the wheel
    import mxl_scroll
    if mxl_scroll.TK9:
        scr.cv.event_generate('<Button-5>', x=int(x), y=int(y))
        T.pump(4)
        T.eq(scr.scroll_at, 0, 'rows after a side button (Tk 9)')


@T.test
def real_wheel_clicks_one_step_each():
    if not XDOTOOL:
        T.skip('xdotool not installed')
    cw, scr = stats_screen()
    show_totals(cw, scr)
    x, y = list_point(scr)
    pointer_to(scr.cv, x, y)
    if G.root.winfo_containing(scr.cv.winfo_rootx() + int(x), scr.cv.winfo_rooty() + int(y)) is not scr.cv:
        T.skip('the list is not on screen at this window size')
    for k in (1, 2):
        subprocess.run([XDOTOOL, 'click', '5'])
        T.pump(10, 0.01)
        T.eq(scr.scroll_at, 3 * k, f'rows after {k} real wheel click(s) down')
    subprocess.run([XDOTOOL, 'click', '4'])
    T.pump(10, 0.01)
    T.eq(scr.scroll_at, 3, 'rows after a real click back up')


@T.test
def a_quick_burst_of_notches_is_drawn_without_lag():
    if not XDOTOOL:
        T.skip('xdotool not installed')
    cw, scr = stats_screen()
    show_totals(cw, scr)
    x, y = list_point(scr)
    pointer_to(scr.cv, x, y)
    n = [0]
    orig = scr.redraw

    def counted(*a):
        n[0] += 1
        return orig(*a)
    scr.redraw = counted
    try:
        clicks = 30
        p = subprocess.Popen([XDOTOOL, 'click', '--repeat', str(clicks), '--delay', '8', '5'])
        t0 = time.monotonic()
        done = None
        while time.monotonic() - t0 < 15:
            G.root.update()
            if p.poll() is not None and done is None:
                done = time.monotonic()
            if done is not None and time.monotonic() - done > 0.6:
                break
        T.check(done is not None, 'xdotool did not finish')
    finally:
        scr.redraw = orig
    T.eq(scr.scroll_at, min(scr._list_top, 3 * clicks), 'rows after the burst')
    T.check(n[0] < clicks // 2, f'{n[0]} redraws for {clicks} notches (one per notch makes the list lag)')


@T.test
def the_page_scrolls_where_the_list_cannot():
    """At the end of the list (or over a page without one) the notch goes to the page around, when it is
    taller than the window."""
    cw, scr = stats_screen()
    show_totals(cw, scr)
    x, y = list_point(scr)
    wheel(scr.cv, 120, x, y)                       # at the top of the list already: not taken by the list
    T.eq(scr.scroll_at, 0, 'rows after a notch up at the top')
    if not cw.scroll._shown[0]:
        return                                     # the page fits: nothing else to scroll
    cv = cw.scroll.canvas
    cv.yview_moveto(0)
    T.pump(2)
    scr.scroll_at = scr._list_top
    scr.redraw()
    T.pump(2)
    wheel(scr.cv, -120, x, y)
    T.check(cv.yview()[0] > 0, f'the page did not scroll at the end of the list ({cv.yview()})')
    T.eq(scr.scroll_at, scr._list_top, 'the list stays at its end')


# ------------------------------------------------------------------------------------ value widgets
@T.test
def the_wheel_never_changes_a_dropdown_on_a_page():
    import mxl_merc
    cw, _scr = stats_screen()
    cw.tab.set('merc')
    cw.show_tab()
    T.settle(0.3)
    page = cw.pages['merc']
    box = next((w for w in _walk(page) if w.winfo_class() == 'TCombobox' and str(w.cget('state')) == 'readonly'
                and w.cget('values')), None)
    if box is None:
        T.skip('no dropdown on the Mercenary page')
    before = box.get()
    for d in (-120, -120, 120, -120):
        wheel(box, d, 5, 5)
    T.eq(box.get(), before, 'dropdown value after wheel notches over it')
    T.check(not cw.dirty(), 'the Character tab reports a pending edit after wheel notches')
    del mxl_merc


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


@T.test
def creator_value_box_steps_once_per_notch_and_spinbox_keeps_its_value():
    import mxl_creator_gui as CG
    import mxl_tabs
    CG.CreatorWindow(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    T.select_tab('Creator')
    T.settle(0.3)
    if w is None:
        raise T.Failed('no Creator window')
    copies = w.copies_spin
    before = copies.get()
    for d in (120, 120, -120):
        wheel(copies, d, 5, 5)
    T.eq(copies.get(), before, 'number of copies after wheel notches over it')
    # a value box of a roll: one step per notch while it has the focus
    w.quality.set(dict((k, lab) for lab, k in CG.qualities())['unique'])
    w.on_quality()
    T.pump()
    ent = None
    for i in range(min(len(w.entries), 60)):
        w.listbox.selection_clear(0, 'end')
        w.listbox.selection_set(i)
        w.on_pick()
        T.pump(6)
        ent = next((e for e in w._spins if getattr(e, 'value_range', None) and e.winfo_exists()
                    and e.value_range[1] - e.value_range[0] >= 4 and e.winfo_ismapped()), None)
        if ent is not None:
            break
    if ent is None:
        T.skip('no unique with a variable roll in the first list entries')
    lo, hi = ent.value_range
    ent.set_value(lo)
    T.pump(2)
    ent.focus_force()
    T.pump(4)
    if ent.focus_get() is not ent:
        T.skip('the value box does not get the focus on this X server')
    wheel(ent, 120, 3, 3)
    T.eq(int(ent.get()), lo + 1, 'value after one notch up')
    wheel(ent, 240, 3, 3)                          # a two-notch event (fast wheel on Windows)
    T.eq(int(ent.get()), lo + 3, 'value after a two-notch event')
    wheel(ent, -120, 3, 3)
    T.eq(int(ent.get()), lo + 2, 'value after one notch down')


T.main(globals())
