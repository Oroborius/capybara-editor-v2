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
    def __init__(self, type='38', delta=0, num='??', state=0):
        self.type, self.delta, self.num, self.state = type, delta, num, state


def mod(tk9):
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import mxl_scroll
    mxl_scroll.TK9 = tk9
    return mxl_scroll


def run(S, events, horizontal=False):
    got = []
    h = S.WheelHandler(lambda n, e: got.append(('v', n)) or 'break',
                       (lambda n, e: got.append(('h', n)) or 'break') if horizontal else None)
    res = [h(e) for e in events]
    return got, res


@T.test
def tk86_wheel_notches():
    S = mod(False)
    got, res = run(S, [Ev(delta=120), Ev(delta=-120), Ev(delta=-240), Ev(delta=360)])
    T.eq(got, [('v', -1), ('v', 1), ('v', 2), ('v', -3)], 'notches of 120 / 240 / 360 deltas')
    T.eq(res, ['break'] * 4, 'results')
    got, _ = run(S, [Ev(type='4', num=4), Ev(type='4', num=5), Ev(type='4', num=5)])
    T.eq(got, [('v', -1), ('v', 1), ('v', 1)], 'X11 Button-4 / Button-5 under Tk 8.6')


@T.test
def tk86_touchpad_small_deltas_add_up():
    S = mod(False)
    got, res = run(S, [Ev(delta=-30)] * 4 + [Ev(delta=-30)] * 3)
    T.eq(got, [('v', 1)], 'seven events of -30: one notch (and 90 left over)')
    T.eq(res[:3], ['break'] * 3, 'part-notches are swallowed (the page around must not take them)')
    got, _ = run(S, [Ev(delta=-60), Ev(delta=-60), Ev(delta=60), Ev(delta=60), Ev(delta=60)])
    T.eq(got, [('v', 1), ('v', -1)], 'a turn of direction starts counting again')
    got, _ = run(S, [Ev(delta=-8)] * 15)
    T.eq(got, [('v', 1)], 'fifteen deltas of -8 = one notch')


@T.test
def tk9_side_buttons_are_not_the_wheel():
    S = mod(True)
    got, res = run(S, [Ev(type='4', num=8), Ev(type='4', num=4, delta=0), Ev(type='4', num=5)])
    T.eq(got, [], 'Button-4/5 under Tk 9 (the side buttons)')
    T.eq(res, [None] * 3, 'not handled')
    T.check('<Button-4>' not in S.wheel_seqs() and '<TouchpadScroll>' in S.wheel_seqs(), f'Tk 9 sequences {S.wheel_seqs()}')
    S = mod(False)
    T.check('<Button-4>' in S.wheel_seqs() and '<TouchpadScroll>' not in S.wheel_seqs(), f'Tk 8.6 sequences {S.wheel_seqs()}')


@T.test
def shift_and_touchpad_scroll():
    S = mod(True)
    got, res = run(S, [Ev(delta=-120, state=1)])
    T.eq((got, res), ([], [None]), 'Shift + wheel without a sideways handler')
    got, _ = run(S, [Ev(delta=-120, state=1), Ev(delta=120, state=0x11)], horizontal=True)
    T.eq(got, [('h', 1), ('h', -1)], 'Shift + wheel = sideways')
    T.eq(S.touchpad_deltas((3 << 16) | (-20 & 0xFFFF)), (3, -20), 'packed touchpad deltas')
    T.eq(S.touchpad_deltas((-5 << 16) | 7), (-5, 7), 'packed touchpad deltas (negative x)')
    step = int(S.TOUCHPAD_NOTCH)
    ev = Ev(type='39', delta=(-10) & 0xFFFF)                 # 10 px finger movement up = content down
    got, _ = run(S, [ev] * (step // 10 * 2))
    T.eq(got, [('v', 1), ('v', 1)], f'touchpad: {step // 10 * 2} events of 10 px')


T.main(globals())
