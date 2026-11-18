"""A frame whose content scrolls when the window is too small for it - and only then.

The editor's pages were laid out for one large window; in a small one pack / grid simply cut off what did not
fit (buttons at the bottom included). Scrolled gives a page an `inner` frame to build into: while the room is
enough, inner fills it exactly as a plain frame would (so expanding content keeps expanding); when inner asks for
more than there is, it keeps the size it asks for and scrollbars appear on the side that is short."""
import time
import tkinter as tk
from tkinter import ttk

NO_WHEEL = ('Listbox', 'Text', 'Treeview', 'TScale', 'Scale')      # they scroll themselves
# their class bindings CHANGE THE VALUE on a wheel notch (Tk 8.6 and 9): over them the wheel scrolls the page and
# never reaches the class (a notch while scrolling past a dropdown changed a class, a level, a mercenary type)
VALUE_WHEEL = ('TCombobox', 'TSpinbox')

# ---------------------------------------------------------------------------------------------- the mouse wheel
# One place that turns wheel / touchpad input into whole "notches", the same under the Tk of each build:
#  - Tk 8.6 (Windows exe): <MouseWheel> with delta = 120 per notch; precision touchpads send small deltas
#    (8, 15 ...) many times a second. On X11, 8.6 reports the wheel as <Button-4> (up) / <Button-5> (down).
#  - Tk 9 (Linux AppImage): on X11 every wheel click, touchpad scrolling under XWayland included, is ONE
#    <MouseWheel> with delta +-120 (Shift held: <Shift-MouseWheel>, the horizontal wheel); <Button-4>/<Button-5>
#    are the mouse's side buttons (back / forward) - not the wheel - and must not scroll. <TouchpadScroll> (Tk 9
#    on Windows / macOS) carries pixel deltas, x and y packed into one number (tk::PreciseScrollDeltas).
# Small deltas are added up, so a touchpad moves as far as the same swipe of a wheel would (it moved a whole
# notch per tiny event before); each notch is handled exactly once.
TK9 = float(tk.TkVersion) >= 8.7
WHEEL_NOTCH = 120.0                      # delta of one wheel notch
TOUCHPAD_NOTCH = 40.0                    # pixels of a touchpad swipe that count as one notch
_RESET_AFTER = 0.6                       # seconds without input: a part-notch left over is forgotten


def wheel_seqs():
    """The event sequences that carry the wheel / touchpad under this Tk."""
    return ('<MouseWheel>',) + (('<TouchpadScroll>',) if TK9 else ('<Button-4>', '<Button-5>'))


def touchpad_deltas(d):
    """(dx, dy) pixels of a <TouchpadScroll> event's packed %D (tk::PreciseScrollDeltas)."""
    d = int(d)
    low = d & 0xFFFF
    return d >> 16, (low if low < 0x8000 else low - 0x10000)


def wheel_notches(ev):
    """(vertical, horizontal) amounts of one wheel event in notches, positive = down / right (the sign
    yview_scroll / xview_scroll take); fractions for touchpads. (0, 0) for what is not a wheel."""
    try:
        etype = str(ev.type)
    except Exception:
        etype = ''
    shift = bool(getattr(ev, 'state', 0) & 0x1) if isinstance(getattr(ev, 'state', 0), int) else False
    if etype in ('TouchpadScroll', '39') or etype.endswith('TouchpadScroll'):
        dx, dy = touchpad_deltas(getattr(ev, 'delta', 0) or 0)
        return -dy / TOUCHPAD_NOTCH, -dx / TOUCHPAD_NOTCH
    num = getattr(ev, 'num', None)
    if num in (4, 5) and etype in ('ButtonPress', '4', 'Button'):
        if TK9:
            return 0.0, 0.0              # Tk 9: the side buttons of the mouse
        v = -1.0 if num == 4 else 1.0
    else:
        try:
            delta = float(getattr(ev, 'delta', 0) or 0)
        except (TypeError, ValueError):
            delta = 0.0
        v = -delta / WHEEL_NOTCH
    return (0.0, v) if shift else (v, 0.0)


class WheelHandler:
    """A wheel event handler: whole notches go to on_vertical(n, ev) / on_horizontal(n, ev) (n: int, positive =
    down / right); their return value ('break' or None) is the handler's. Part-notches (touchpads) are added up
    and a whole notch handed on once it is complete; an event that leaves only a part is swallowed ('break')
    unless nothing would take it. Without on_horizontal a sideways event goes unhandled (None)."""

    def __init__(self, on_vertical=None, on_horizontal=None):
        self.on_vertical = on_vertical
        self.on_horizontal = on_horizontal
        self._acc = [0.0, 0.0]
        self._t = 0.0

    def __call__(self, ev):
        v, h = wheel_notches(ev)
        now = time.monotonic()
        if now - self._t > _RESET_AFTER:
            self._acc = [0.0, 0.0]
        self._t = now
        out = None
        for axis, amount, fn in ((0, v, self.on_vertical), (1, h, self.on_horizontal)):
            if not amount or fn is None:
                continue
            acc = self._acc[axis]
            if acc and (acc > 0) != (amount > 0):
                acc = 0.0                # turned round: start again
            acc += amount
            n = int(round(acc, 6))       # towards 0: a part-notch stays (15 x 8/120 is 0.99999...)
            self._acc[axis] = acc - n
            if n:
                r = fn(n, ev)
                if r is not None:
                    out = r
            else:
                out = 'break'
        return out


def bind_wheel(widget, on_vertical=None, on_horizontal=None, add=None):
    """Binds the wheel sequences of this Tk on the widget; returns the WheelHandler."""
    h = on_vertical if isinstance(on_vertical, WheelHandler) else WheelHandler(on_vertical, on_horizontal)
    for seq in wheel_seqs():
        widget.bind(seq, h, add)
    return h


def bind_wheel_class(widget, tag, handler):
    for seq in wheel_seqs():
        widget.bind_class(tag, seq, handler)


def bind_wheel_all(widget, handler):
    for seq in wheel_seqs():
        widget.bind_all(seq, handler)


def unbind_wheel_all(widget):
    for seq in wheel_seqs():
        widget.unbind_all(seq)


class Scrolled(tk.Frame):
    def __init__(self, parent, bg=None, horizontal=True, **kw):
        super().__init__(parent, **kw)
        if bg is None:
            bg = self.cget('bg')
        self.configure(bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, width=10, height=10,
                                yscrollincrement=16, xscrollincrement=16)
        self.vbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self._horizontal = horizontal
        self._job = None
        self._shown = (False, False)
        self.canvas.bind('<Configure>', self._later)
        self.inner.bind('<Configure>', self._later)
        self._wheel_id = None
        # the wheel: a binding tag of its own given to every widget inside (bind_all is taken, and dropped
        # again, by other scroll areas of the editor), placed AFTER the widget's own and class bindings: a widget
        # that scrolls something itself (a list on the stat screen) has the first say and returns 'break'
        # when it took the notch - the page scrolled along with the list before
        self._tag = 'MxlScrolled%d' % id(self)
        self._wheel = WheelHandler(self._wheel_v, self._wheel_h)
        bind_wheel_class(self, self._tag, self._wheel)
        self._tag_all(self)

    def set_bg(self, bg):
        for w in (self, self.canvas, self.inner):
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ layout
    def refresh(self):
        """To call when the content asks for another size (a page was swapped): Tk reports nothing by itself
        while inner is held at the size given to it."""
        self._later()

    def _later(self, _e=None):
        if self._job is None:
            try:
                self._job = self.after_idle(self._fit)
            except tk.TclError:
                pass

    def _fit(self):
        self._job = None
        try:
            if not self.winfo_exists():
                return
            W, H = self.winfo_width(), self.winfo_height()
            if W < 4 or H < 4:
                return
            rw, rh = self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()
            bw = self.vbar.winfo_reqwidth()
            bh = self.hbar.winfo_reqheight()
            need_h = self._horizontal and rw > W
            need_v = rh > H - (bh if need_h else 0)
            if need_v and self._horizontal and rw > W - bw:
                need_h = True
            if (need_v, need_h) != self._shown:
                self._shown = (need_v, need_h)
                if need_v:
                    self.vbar.grid(row=0, column=1, sticky='ns')
                else:
                    self.vbar.grid_remove()
                if need_h:
                    self.hbar.grid(row=1, column=0, sticky='ew')
                else:
                    self.hbar.grid_remove()
            cw = W - (bw if need_v else 0)
            ch = H - (bh if need_h else 0)
            w = max(cw, rw) if self._horizontal else cw
            h = max(ch, rh)
            self.canvas.itemconfigure(self._win, width=w, height=h)
            self.canvas.configure(scrollregion=(0, 0, w, h))
            if not need_v:
                self.canvas.yview_moveto(0)
            if not need_h:
                self.canvas.xview_moveto(0)
            self._tag_all(self)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ mouse wheel
    def _tag_all(self, w):
        try:
            if w.winfo_class() not in NO_WHEEL:      # those scroll themselves
                tags = w.bindtags()
                if self._tag not in tags:
                    tags = list(tags)
                    cls = w.winfo_class()
                    at = tags.index(cls) + (cls not in VALUE_WHEEL) if cls in tags else min(1, len(tags))
                    tags.insert(at, self._tag)
                    w.bindtags(tuple(tags))
            for c in w.winfo_children():
                self._tag_all(c)
        except tk.TclError:
            pass

    @staticmethod
    def _keep_value(ev):
        try:
            return 'break' if ev.widget.winfo_class() in VALUE_WHEEL else None
        except (AttributeError, tk.TclError):
            return None

    def _wheel_v(self, n, ev=None):
        try:
            if not self._shown[0]:
                return self._keep_value(ev)
            self.canvas.yview_scroll(n * 3, 'units')
        except tk.TclError:
            pass
        return 'break'

    def _wheel_h(self, n, ev=None):
        try:
            if not self._shown[1]:
                return self._keep_value(ev)
            self.canvas.xview_scroll(n * 3, 'units')
        except tk.TclError:
            pass
        return 'break'
