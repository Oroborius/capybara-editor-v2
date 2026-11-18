"""Floating tooltips do not flicker (user report, Linux AppImage under Hyprland / XWayland: "the hover tooltips flicker
like crazy"). The tips of the Stats page (dark look), the Skills tree and the Hotkeys page are one reused window
each (mxl_floattip). A real pointer (xdotool on this X server; skipped without it) is parked and moved; the tip's
own <Map> / <Unmap> events are counted:
- a stationary hover maps the tip once and it stays (no hide / re-show for 2 s); small moves inside the item keep it;
- the tip is never under the pointer, and when the pointer jumps onto it (Wayland sends one motion per frame,
  tens of px apart) it steps aside instead of being hidden and re-made;
- crossing from label to label inside one hotkey cell keeps it;
- a <Leave> with the pointer still on the widget (a grab, or a compositor moving its pointer focus) keeps it;
- leaving the widget hides it (after the short debounce);
- on X11 the window is typed _NET_WM_WINDOW_TYPE_TOOLTIP only with MXL_TIP_TYPE=1 (default: untyped);
- the window is exactly the size its content asks for, after a short then a long tip and the reverse, shown or
  re-shown (user report under Hyprland: "a fixed rectangle, the text is cut off, a lighter orange bar": a re-mapped
  window kept an old size and its frame-coloured background filled the rest); its background is the tip's own,
  no widget in it has a highlight ring.
CAPY_VPTR_FIFO=<fifo>: the pointer moves through a Wayland virtual pointer instead (a headless sway session:
the compositor's own pointer focus, as on the user's desktop)."""
import os
import shutil
import subprocess
import time
import tkinter as tk

import capytest as T

MODE = 'gui'
RESET = False
VARIANTS = {
    'd2-scale1.25': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1180x680+0+0', 'MXL_UI_SCALE': '1.25'},
    'he': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '1180x680+0+0'},
}
G = T.G
XDOTOOL = shutil.which('xdotool')
FIFO = os.environ.get('CAPY_VPTR_FIFO')


def need_pointer():
    if not (XDOTOOL or FIFO):
        T.skip('xdotool is not installed: no real pointer to hover with')


def move(x, y, settle=0.15):
    """The pointer to root coordinates x, y."""
    x, y = int(x), int(y)
    if FIFO:
        with open(FIFO, 'w') as f:
            f.write(f'abs {x} {y}\n')
    else:
        subprocess.run([XDOTOOL, 'mousemove', str(x), str(y)])
    T.settle(settle)


def move_to(widget, x, y, settle=0.15):
    move(widget.winfo_rootx() + x, widget.winfo_rooty() + y, settle)


def away():
    """The pointer onto the status bar (no tooltip there)."""
    st = G.app.status
    move_to(st, 5, max(1, st.winfo_height() // 2), 0.6)


def char(page):
    import mxl_char_gui
    cw = T.chartab()
    if cw is None or getattr(cw, 'ch', None) is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    T.select_tab('Character')
    if cw.tab.get() != page:
        cw.tab.set(page)
        cw.show_tab()
    T.settle(0.4)
    return cw


def tip_rect(tip):
    w = tip.win
    return w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()


def under_pointer(tip):
    px, py = G.root.winfo_pointerxy()
    x, y, w, h = tip_rect(tip)
    return x <= px < x + w and y <= py < y + h


def mapped(tip):
    try:
        return bool(tip.win.winfo_ismapped())
    except (tk.TclError, AttributeError):
        return False


def reset_counts(tip):
    tip.maps = tip.unmaps = 0


def stable(tip, what, hold=2.0):
    """The tip is shown, stays shown without a hide for `hold` seconds, and is not under the pointer."""
    T.settle(hold)
    T.check(mapped(tip), f'{what}: tip not shown')
    T.check(tip.unmaps == 0, f'{what}: tip hidden {tip.unmaps}x while the pointer stood still')
    T.check(tip.maps <= 1, f'{what}: tip shown {tip.maps}x (once expected)')
    T.check(not under_pointer(tip), f'{what}: tip under the pointer {tip_rect(tip)} at {G.root.winfo_pointerxy()}')


def wiggle(tip, widget, x, y, what):
    for dx, dy in ((2, 1), (4, 3), (1, 4), (-2, 2), (0, 0)):
        move_to(widget, x + dx, y + dy, 0.08)
    T.settle(0.3)
    T.check(tip.unmaps == 0 and mapped(tip), f'{what}: moving inside the item hid the tip ({tip.unmaps}x)')


def gone(tip, what):
    away()
    T.check(not mapped(tip), f'{what}: tip still shown after the pointer left')


def typed(tip, what):
    import mxl_floattip
    if G.root.tk.call('tk', 'windowingsystem') == 'x11':
        want = mxl_floattip.tip_type()
        T.check(('tooltip' in str(tip.win.wm_attributes('-type'))) == want,
                f'{what}: window type {tip.win.wm_attributes("-type")!r} (MXL_TIP_TYPE {"on" if want else "off"})')


def x_size(w):
    """The X window's own size (the wrapper of the toplevel) by xdotool, else Tk's idea of it."""
    if XDOTOOL and G.root.tk.call('tk', 'windowingsystem') == 'x11':
        try:
            out = subprocess.run([XDOTOOL, 'getwindowgeometry', str(int(w.wm_frame(), 16))],
                                 capture_output=True, text=True, timeout=5).stdout
            geo = out.split('Geometry:')[1].split()[0]
            a, b = geo.split('x')
            return int(a), int(b)
        except Exception:
            pass
    return w.winfo_width(), w.winfo_height()


def fits(tip, what):
    """Shown at exactly its content's size, own background, no highlight ring anywhere in it."""
    T.pump(5)
    w = tip.win
    T.check(w is not None and mapped(tip), f'{what}: tip not shown')
    want = tip.size()
    T.check((w.winfo_width(), w.winfo_height()) == want,
            f'{what}: Tk size {w.winfo_width()}x{w.winfo_height()}, content asks {want[0]}x{want[1]}')
    T.check(x_size(w) == want, f'{what}: X window {x_size(w)}, content asks {want[0]}x{want[1]}')
    T.check(str(w.cget('bg')).lower() == str(tip.bg).lower(), f'{what}: window bg {w.cget("bg")} != tip bg {tip.bg}')
    T.check(int(str(w.cget('bd'))) == 0, f'{what}: window has a border')
    todo = [w]
    while todo:
        c = todo.pop()
        todo += c.winfo_children()
        try:
            ht = int(str(c.cget('highlightthickness')))
        except tk.TclError:
            continue
        T.check(ht == 0, f'{what}: {c.winfo_class()} {c} has a highlight ring ({ht} px)')


@T.test
def stats_page_tip_is_stable():
    need_pointer()
    cw = char('stats')
    scr = cw.statscreen
    if scr is None:
        T.skip('no stat screen in this look')
    import mxl_statscreen
    scr.show_page('main', exact=True)
    T.settle(0.3)
    box = next((b for kind, k, b, _pg in scr._regions if scr.tip_of(kind, k) and b[2] * scr.k >= 20), None)
    if box is None:
        T.skip('no region with a tooltip on the stat screen')
    bx, by, bw, bh = box
    x, y = (bx + bw / 2) * scr.k, (by + bh / 2) * scr.k
    away()
    move_to(scr.cv, x, y, 0.3)
    tip = getattr(cw, '_sk_tipper', None)
    if tip is None or not mapped(tip):
        raise T.Failed('hovering a stat screen value shows no tooltip')
    typed(tip, 'stats')
    fits(tip, 'stats')
    reset_counts(tip)
    stable(tip, 'stats: stationary hover')
    wiggle(tip, scr.cv, x, y, 'stats')
    reset_counts(tip)
    scr.cv.event_generate('<Leave>')                 # pointer still on the value: a grab / compositor Leave
    T.settle(0.6)
    T.check(mapped(tip) and tip.unmaps == 0, 'stats: a <Leave> with the pointer still on the value hid the tip')
    gone(tip, 'stats')
    del mxl_statscreen


@T.test
def skill_tree_tip_is_stable():
    need_pointer()
    cw = char('skills')
    tree = getattr(cw, 'sktree', None)
    if tree is None:
        T.skip('no skill tree')
    T.settle(0.3)
    box = next((b for k, _s, b in tree._regions if k == 'icon'), None)
    if box is None:
        T.skip('no skill icon on the tree shown')
    bx, by, bw, bh = box
    x, y = (bx + bw / 2) * tree.k, (by + bh / 2) * tree.k
    away()
    move_to(tree.cv, x, y, 1.0)                     # the tree's tip comes after a short wait (like the game)
    tip = tree._tipper
    if tip is None or not mapped(tip):
        raise T.Failed('hovering a skill icon shows no tooltip')
    typed(tip, 'skills')
    fits(tip, 'skills')
    reset_counts(tip)
    stable(tip, 'skills: stationary hover')
    wiggle(tip, tree.cv, x, y, 'skills')
    gone(tip, 'skills')


@T.test
def hotkey_cell_tip_survives_label_crossings():
    need_pointer()
    import mxl_hotkeys as HK
    cw = char('hotkeys')
    page = cw.extra.get('hotkeys')
    if page is None:
        T.skip('no Hotkeys page')
    off = next((o for o in page.cells if page.skill_at(o)[0] is not None), None)
    if off is None:
        T.skip('no hotkey with a skill on the sample character')
    c = page.cells[off]
    away()
    move_to(c['icon'], c['icon'].winfo_width() // 2, c['icon'].winfo_height() // 2, 0.3)
    tip = getattr(cw, '_sk_tipper', None)
    if tip is None or not mapped(tip):
        raise T.Failed('hovering a hotkey shows no tooltip')
    fits(tip, 'hotkey')
    reset_counts(tip)
    stable(tip, 'hotkey: stationary hover', hold=1.5)
    for name in ('head', 'name', 'icon', 'name', 'head'):          # label to label inside the one cell
        w = c[name]
        move_to(w, w.winfo_width() // 2, w.winfo_height() // 2, 0.1)
    T.settle(0.3)
    T.check(tip.unmaps == 0 and mapped(tip), f'hotkey: crossing the labels of one cell hid the tip {tip.unmaps}x')
    gone(tip, 'hotkey')
    del HK


@T.test
def tip_steps_aside_when_the_pointer_lands_on_it():
    """Wayland: one pointer motion per frame. A jump onto the tip (before it followed) must not hide it."""
    need_pointer()
    import mxl_floattip
    top = tk.Toplevel(G.root)
    top.geometry('600x400+40+40')
    cv = tk.Canvas(top, width=600, height=400, bg='grey20', highlightthickness=0)
    cv.pack(fill='both', expand=True)
    tip = mxl_floattip.FloatTip(top, build=lambda b: tk.Label(b, text='tip\nline 2\nline 3', padx=10, pady=6, bg='#1a1612',
                                                               fg='#c7b377', highlightthickness=0).pack(),
                                bg='#1a1612', edge='#4a3f26')
    cv.bind('<Motion>', lambda e: tip.show(cv, key='one'))
    cv.bind('<Enter>', lambda e: tip.show(cv, key='one'))
    cv.bind('<Leave>', lambda e: tip.leave(cv))
    try:
        T.settle(0.5)
        move_to(cv, 60, 60, 0.4)
        T.check(mapped(tip), 'canvas: no tip')
        reset_counts(tip)
        stable(tip, 'canvas: stationary hover', hold=1.0)
        for i in range(3):                                   # jumps down-right onto the tip, one per "frame"
            x, y, w, h = tip_rect(tip)
            move(x + w // 2, y + h // 2, 0.03)
        T.settle(0.5)
        T.check(tip.unmaps == 0 and mapped(tip), f'canvas: pointer jumps onto the tip hid it {tip.unmaps}x')
        T.check(not under_pointer(tip), 'canvas: the tip stayed under the pointer')
        away()                                               # out of the window, onto the main window
        T.check(not mapped(tip), 'canvas: tip still shown after the pointer left the window')
    finally:
        tip.destroy()
        top.destroy()
        T.pump(3)


@T.test
def tip_is_sized_to_its_content():
    """Short then long then short, while shown and after a hide: the window always takes the new content's size
    (a fresh window per content; Hyprland kept the first size of a re-mapped one), with the stat screen's colours."""
    import mxl_floattip
    top = tk.Toplevel(G.root)
    top.geometry('700x500+40+40')
    T.settle(0.3)
    texts = {'short': 'Strength',
             'long': 'Life: 1234 / 1234\nReplenish life +12\nIncreases the duration of poison spells by a lot\n4\n5',
             'wide': 'Increases the duration of poison spells'}
    cur = {}
    tip = mxl_floattip.FloatTip(top, build=lambda b: tk.Label(b, text=cur['t'], padx=10, pady=6, justify='left',
                                                               bg='#1a1612', fg='#c7b377', bd=0,
                                                               highlightthickness=0).pack(),
                                bg='#1a1612', edge='#4a3f26')
    if XDOTOOL:
        move_to(top, 150, 150, 0.2)
    try:
        sizes = {}
        for i, (name, hide_first) in enumerate((('short', False), ('long', False), ('short', False), ('wide', True),
                                                 ('long', True), ('short', True), ('long', False), ('wide', False))):
            if hide_first:
                tip.hide()
                T.settle(0.2)
            cur['t'] = texts[name]
            tip.show(top, key=name)
            T.settle(0.3)
            what = f'step {i} {name}{" after a hide" if hide_first else " while shown"}'
            fits(tip, what)
            sizes.setdefault(name, set()).add(tip.size())
        T.check(all(len(v) == 1 for v in sizes.values()), f'same text, different sizes: {sizes}')
        T.check(len({next(iter(v)) for v in sizes.values()}) == 3, f'the three texts got the same size: {sizes}')
        n = tip.maps
        tip.show(top, key='wide')                        # same content: moved only, no new window
        tip.show(top)
        T.settle(0.2)
        T.check(tip.maps == n, f'the same content re-made the window ({tip.maps - n}x)')
    finally:
        tip.destroy()
        top.destroy()
        T.pump(3)


T.main(globals())
