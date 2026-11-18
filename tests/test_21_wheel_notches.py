"""mxl_scroll's wheel helper: wheel / touchpad events -> whole notches, each notch handed on exactly once, under
the Tk of both builds (no window: fake events with the fields tkinter fills in).

- Tk 8.6 (Windows exe): <MouseWheel> delta 120 per notch (240 for two notches in one event); precision touchpads
  send small deltas that must add up to a notch (each tiny event scrolled a whole notch before); on X11 8.6
  reports the wheel as <Button-4> / <Button-5>.
- Tk 9 (Linux AppImage): <MouseWheel> delta +-120 per click (XWayland touchpads too); <Button-4>/<Button-5> are the
  mouse's side buttons and do nothing; <TouchpadScroll> packs x / y pixels in one number; Shift = sideways."""
import sys

import capytest as T

MODE = 'engine'


class Ev:
    serial = 0

    def __init__(self, type='38', delta=0, num='??', state=0):
        self.type, self.delta, self.num, self.state = type, delta, num, state

    def copy(self):
        """The same event as another binding sees it (tkinter makes an Event per binding)."""
        e = Ev(self.type, self.delta, self.num, self.state)
        e.serial = self.serial
        return e


def evs(n, **kw):
    """n separate events (each with a serial of its own, like the X server's)."""
    out = []
    for _ in range(n):
        Ev.serial += 1
        e = Ev(**kw)
        e.serial = Ev.serial
        out.append(e)
    return out


def fresh(S):
    S._count.update(acc=[0.0, 0.0], t=0.0, key=None, res=None)


def mod(tk9):
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import mxl_scroll
    mxl_scroll.TK9 = tk9
    return mxl_scroll


def run(S, events, horizontal=False):
    fresh(S)
    got = []
    h = S.WheelHandler(lambda n, e: got.append(('v', n)) or 'break',
                       (lambda n, e: got.append(('h', n)) or 'break') if horizontal else None)
    res = [h(e) for e in events]
    return got, res


@T.test
def tk86_wheel_notches():
    S = mod(False)
    got, res = run(S, evs(1, delta=120) + evs(1, delta=-120) + evs(1, delta=-240) + evs(1, delta=360))
    T.eq(got, [('v', -1), ('v', 1), ('v', 2), ('v', -3)], 'notches of 120 / 240 / 360 deltas')
    T.eq(res, ['break'] * 4, 'results')
    got, _ = run(S, evs(1, type='4', num=4) + evs(2, type='4', num=5))
    T.eq(got, [('v', -1), ('v', 1), ('v', 1)], 'X11 Button-4 / Button-5 under Tk 8.6')


@T.test
def tk86_touchpad_small_deltas_add_up():
    S = mod(False)
    got, res = run(S, evs(7, delta=-30))
    T.eq(got, [('v', 1)], 'seven events of -30: one notch (and 90 left over)')
    T.eq(res[:3], ['break'] * 3, 'part-notches are swallowed (the page around must not take them)')
    got, _ = run(S, evs(2, delta=-60) + evs(3, delta=60))
    T.eq(got, [('v', 1), ('v', -1)], 'a turn of direction starts counting again')
    got, _ = run(S, evs(15, delta=-8))
    T.eq(got, [('v', 1)], 'fifteen deltas of -8 = one notch')


@T.test
def tk9_side_buttons_are_not_the_wheel():
    S = mod(True)
    got, res = run(S, evs(1, type='4', num=8) + evs(1, type='4', num=4, delta=0) + evs(1, type='4', num=5))
    T.eq(got, [], 'Button-4/5 under Tk 9 (the side buttons)')
    T.eq(res, [None] * 3, 'not handled')
    T.check('<Button-4>' not in S.wheel_seqs() and '<TouchpadScroll>' in S.wheel_seqs(), f'Tk 9 sequences {S.wheel_seqs()}')
    S = mod(False)
    T.check('<Button-4>' in S.wheel_seqs() and '<TouchpadScroll>' not in S.wheel_seqs(), f'Tk 8.6 sequences {S.wheel_seqs()}')


@T.test
def shift_and_touchpad_scroll():
    S = mod(True)
    got, res = run(S, evs(1, delta=-120, state=1))
    T.eq((got, res), ([], [None]), 'Shift + wheel without a sideways handler')
    got, _ = run(S, evs(1, delta=-120, state=1) + evs(1, delta=120, state=0x11), horizontal=True)
    T.eq(got, [('h', 1), ('h', -1)], 'Shift + wheel = sideways')
    T.eq(S.touchpad_deltas((3 << 16) | (-20 & 0xFFFF)), (3, -20), 'packed touchpad deltas')
    T.eq(S.touchpad_deltas((-5 << 16) | 7), (-5, 7), 'packed touchpad deltas (negative x)')
    step = int(S.TOUCHPAD_NOTCH)
    got, _ = run(S, evs(step // 10 * 2, type='39', delta=(-10) & 0xFFFF))   # 10 px finger up = content down
    T.eq(got, [('v', 1), ('v', 1)], f'touchpad: {step // 10 * 2} events of 10 px')


@T.test
def nested_handlers_share_the_count():
    """A list inside a scrolling page, the list at its end (declines every notch): a Windows touchpad under Tk 8.6
    (30 events of -8 = 2 notches) must scroll the page by those 2 notches - with a count per handler the list
    swallowed the part-notches and the page saw a 15th of a notch per completed one."""
    S = mod(False)
    fresh(S)
    inner_got, outer_got = [], []
    inner = S.WheelHandler(lambda n, e: inner_got.append(n))          # declines (None)
    outer = S.WheelHandler(lambda n, e: outer_got.append(n) or 'break')
    for e in evs(30, delta=-8):
        if inner(e) != 'break':
            outer(e.copy())
    T.eq(inner_got, [1, 1], 'notches offered to the list')
    T.eq(outer_got, [1, 1], 'notches the page got')
    # the list taking its notches: the page gets nothing
    fresh(S)
    outer_got[:] = []
    taker = S.WheelHandler(lambda n, e: 'break')
    for e in evs(30, delta=-8):
        if taker(e) != 'break':
            outer(e.copy())
    T.eq(outer_got, [], 'page notches while the list takes them')


T.main(globals())
