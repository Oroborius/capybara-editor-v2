"""One floating tooltip that does not flicker: shared by the skill tree, the stat screen and the hotkeys page.

User report (Linux AppImage, Tk 9 under XWayland, Hyprland): "the hover tooltips flicker like crazy". The old
tooltips made a new override-redirect Toplevel on every show and destroyed it on every <Leave>:
- the tip sat 18-20 px right / 14-22 px below the pointer; Wayland sends the pointer motion once per frame, so a
  quick move down-right lands the pointer ON the tip before it is moved: the widget gets <Leave>, the tip is
  destroyed, the pointer is back on the widget, <Enter>/<Motion> make a new tip - once per frame (reproduced
  under a headless sway with a virtual pointer: 12 destroy / create cycles in 13 frames);
- the hotkey cells bound <Enter>/<Leave> on each child label: crossing from the icon to the name destroyed and
  re-made the tip (every platform).
Fix of that: never placed under the pointer and moved away when the pointer reaches it; hidden after a <Leave>
only when the pointer really is outside the widget, a moment later (a new show in between cancels it); a hover
that only moves the pointer moves the tip, it is not re-made.

Second user report (same desktop, after a version that REUSED one window - withdrawn / deiconified, typed
_NET_WM_WINDOW_TYPE_TOOLTIP): "they are all a fixed rectangle and the text is cut off and there is a lighter
orange bar". The X window had the right size (xvfb, headless sway + Xwayland: client geometry = content every
time, nothing cut off); Hyprland kept the size of the first map for the re-mapped window, and the empty part
showed the toplevel's background, which was the frame colour (the "lighter bar"). The one thing seen right on
that desktop is a FRESH override-redirect window shown once at its final size. So:
- every new content (another stat, skill, hotkey) gets a fresh window: made withdrawn, override-redirect, filled,
  sized explicitly WxH+X+Y from its content, then mapped; the old one is destroyed after the new one is up.
  Only the position of a shown window changes (same content: the tip follows the pointer, no re-map);
- a hidden tip is destroyed, never re-mapped;
- the window background is the content background and the frame is an inner 1 px frame: an area larger than
  the content (whatever the compositor does) shows nothing but the tip's own background; no highlight rings;
- MXL_TIP_TYPE=1 also types the window _NET_WM_WINDOW_TYPE_TOOLTIP (X11). Default 0: the untyped
  override-redirect window is how the tips were made when they looked right on Hyprland (the type was added on an
  inference - "focused on map" - that was never seen). Nothing here ever takes the focus."""
import os
import tkinter as tk

HIDE_DELAY = 90          # ms: a <Leave> hides this much later, unless the pointer came back / a show came first
POLL = 200               # ms: after a <Leave> with the pointer still inside, how often it is looked at again
MARGIN = 6               # px: the tip keeps this far from the pointer


def tip_type():
    """MXL_TIP_TYPE=1: _NET_WM_WINDOW_TYPE_TOOLTIP on the window (X11); default off."""
    return os.environ.get('MXL_TIP_TYPE', '0').strip().lower() not in ('', '0', 'no', 'false', 'off')


def _inside(w, outer):
    """w is outer or one of its descendants (Tk path names)."""
    try:
        a, b = str(w), str(outer)
    except Exception:
        return False
    return a == b or (a.startswith(b + '.') if b != '.' else a.startswith('.'))


class FloatTip:
    """A tooltip window. build(body): fills body (a Frame of a fresh tip window) from the caller's current content;
    called for every new window. show(owner, key): key names the content - a new key makes a new window, the
    same key (or None) only moves the shown one.

    gap: (right, below, above) offsets from the pointer; within: a widget whose toplevel bounds the tip (the
    screen when the tip is larger, or without one); alpha: window opacity where supported; bg: the tip's
    background (window and frame inside); edge: colour of a 1 px frame around the content (None: no frame)."""

    def __init__(self, master, build=None, gap=(18, 14, 14), within=None, alpha=None, bg='#000000', edge=None):
        self.master = master
        self.build = build
        self.gap = gap
        self.within = within
        self.alpha = alpha
        self.bg = bg
        self.edge = edge
        self.win = None
        self.body = None
        self.key = None
        self.shown = False
        self.owner = None            # the widget the tip belongs to now (for the <Leave> check)
        self.on_hide = None          # called after a delayed hide (the owner forgets what it showed)
        self._job = None
        self._geo = None
        self.maps = 0                # counters for the tests: windows mapped,
        self.unmaps = 0              # tips hidden (or unmapped by someone else while shown),
        self.swaps = 0               # shown tips replaced by a new window (new content)

    # ------------------------------------------------------------------ the window
    def _make(self):
        """A fresh, withdrawn, override-redirect window with the content built into it (not mapped)."""
        w = tk.Toplevel(self.master, bg=self.bg, bd=0, highlightthickness=0, takefocus=0)
        w.withdraw()                                   # nothing is mapped before the attributes are set
        w.overrideredirect(True)
        try:
            ws = w.tk.call('tk', 'windowingsystem')
        except tk.TclError:
            ws = ''
        if ws == 'x11' and tip_type():
            try:
                w.wm_attributes('-type', 'tooltip')
            except tk.TclError:
                pass
        for k, v in (('-topmost', True), ('-alpha', self.alpha)):
            if v is not None:
                try:
                    w.wm_attributes(k, v)
                except tk.TclError:
                    pass
        edge = self.edge is not None
        body = tk.Frame(w, bg=self.edge if edge else self.bg, bd=0, highlightthickness=0,
                        padx=1 if edge else 0, pady=1 if edge else 0)
        body.pack(anchor='nw')                         # not stretched: a larger window shows only self.bg
        w.bind('<Enter>', self._on_tip_enter, add='+')
        w.bind('<Unmap>', lambda e: self._unmapped(e, w), add='+')
        old_win, old_body = self.win, self.body
        self.win, self.body = w, body
        try:
            if self.build is not None:
                self.build(body)
        except Exception:
            self.win, self.body = old_win, old_body
            try:
                w.destroy()
            except tk.TclError:
                pass
            raise
        return w

    def window(self):
        """The current tip window (a fresh one, built, when there is none)."""
        if not self.exists():
            self.win = None
            self._make()
            self._geo = None
            self.shown = False
        return self.win

    def _unmapped(self, e, w):
        if e.widget is w and w is self.win and self.shown:
            self.unmaps += 1                           # not ours: a compositor / WM took it down

    def exists(self):
        try:
            return self.win is not None and bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    # ------------------------------------------------------------------ show / hide
    def show(self, owner=None, key=None, force=False):
        """Beside the pointer. A tip already shown with this content (same key, or key None) only moves; new
        content (or force) comes in a fresh window, mapped at its own size, the old window goes after it."""
        self._cancel()
        if owner is not None:
            self.owner = owner
        fresh = force or not self.shown or not self.exists() or (key is not None and key != self.key)
        if key is not None:
            self.key = key
        if not fresh:
            self.place()
            return
        old = self.win if self.shown and self.exists() else None
        if not self.shown and self.exists():
            self._drop(self.win)                       # made but never shown (window() before show())
        self.win = None
        try:
            w = self._make()
        except Exception as e:
            self.win = self.body = None                # nothing half made stays on the screen
            self.shown = False
            self._drop(old)
            if isinstance(e, tk.TclError):
                return
            raise
        self._geo = None
        self.place()
        try:
            w.deiconify()
            w.lift()
        except tk.TclError:
            self.shown = False
            return
        self.shown = True
        self.maps += 1
        if old is not None:
            self.swaps += 1
            self._drop(old)

    def _drop(self, w):
        if w is None:
            return
        try:
            w.destroy()
        except tk.TclError:
            pass

    def hide(self):
        self._cancel()
        if self.shown:
            self.unmaps += 1
        self.shown = False
        w, self.win, self.body = self.win, None, None
        self._geo = None
        self._drop(w)                                  # never re-mapped: the next show makes a fresh window

    def leave(self, widget=None):
        """For <Leave>: hides a moment later, unless the pointer is still on the widget (or on the tip)."""
        self._cancel()
        if not self.shown:
            return
        widget = widget if widget is not None else self.owner
        try:
            self._job = self.master.after(HIDE_DELAY, self._check, widget)
        except tk.TclError:
            self.hide()

    def destroy(self):
        self._cancel()
        w, self.win, self.body = self.win, None, None
        self.shown = False
        self._drop(w)

    def _cancel(self):
        if self._job is not None:
            try:
                self.master.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _check(self, widget):
        self._job = None
        if not self.shown:
            return
        where = self._pointer_on()
        if where == 'tip':
            self.place()
        if where in ('tip', 'owner') and widget is not None and self._pointer_in(widget):
            # a <Leave> with the pointer still there: a grab, or the compositor moving the pointer focus.
            # Looked at again until the pointer really goes.
            try:
                self._job = self.master.after(POLL, self._check, widget)
            except tk.TclError:
                pass
            return
        self.hide()
        cb = self.on_hide
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _pointer_on(self):
        try:
            px, py = self.master.winfo_pointerxy()
            under = self.master.winfo_containing(px, py)
        except (tk.TclError, KeyError):
            return None
        if under is None:
            return None
        if self.exists() and _inside(under, self.win):
            return 'tip'
        return 'owner'

    def _pointer_in(self, widget):
        """The pointer is over the widget's rectangle, and nothing else of the app (but the tip) is on top."""
        try:
            px, py = widget.winfo_pointerxy()
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            if not (x <= px < x + widget.winfo_width() and y <= py < y + widget.winfo_height()):
                return False
            under = widget.winfo_containing(px, py)
        except (tk.TclError, KeyError):
            return False
        return under is not None and (_inside(under, widget) or (self.exists() and _inside(under, self.win)))

    def _on_tip_enter(self, _e=None):
        """The pointer got onto the tip (a quick move, or the compositor's pointer focus): moved aside, never
        hidden for that. Then looked at like a <Leave>: kept while the pointer is on the owner (whose next
        <Motion> / show() takes over), hidden when the jump took the pointer off the owner."""
        self.place()
        if self.shown and self.owner is not None:
            self._cancel()
            try:
                self._job = self.master.after(HIDE_DELAY, self._check, self.owner)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ position
    def size(self):
        """The size the content asks for (the window itself has no border)."""
        b = self.body if self.body is not None else self.win
        return max(1, b.winfo_reqwidth()), max(1, b.winfo_reqheight())

    def place(self):
        """Beside the pointer, inside the bounds, never under the pointer; the size set explicitly from the content
        (WxH+X+Y), so the window is never left at another size."""
        w = self.win
        if w is None:
            return
        try:
            w.update_idletasks()
            px, py = w.winfo_pointerxy()
            tw, th = self.size()
            sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
            x0, y0, x1, y1 = 0, 0, sw, sh
            if self.within is not None:
                top = self.within.winfo_toplevel()
                bx0, by0 = top.winfo_rootx(), top.winfo_rooty()
                bx1, by1 = bx0 + top.winfo_width(), by0 + top.winfo_height()
                if tw <= bx1 - bx0 and th <= by1 - by0:
                    x0, y0, x1, y1 = bx0, by0, bx1, by1
            x, y = self._spot(px, py, tw, th, (x0, y0, x1, y1))
            if self._covers(x, y, tw, th, px, py):
                x, y = self._spot(px, py, tw, th, (0, 0, sw, sh))
            if self._covers(x, y, tw, th, px, py):              # a tip larger than the room: beside, cut off
                x = px + self.gap[0] if px + self.gap[0] + tw <= sw or px < sw // 2 else px - self.gap[0] - tw
            geo = f'{int(tw)}x{int(th)}+{int(x)}+{int(y)}'
            if geo != self._geo:
                self._geo = geo
                w.geometry(geo)
        except tk.TclError:
            pass

    def _spot(self, px, py, tw, th, box):
        x0, y0, x1, y1 = box
        right, below, above = self.gap
        x = px + right
        if x + tw > x1:
            x = px - right - tw
        x = max(x0, min(x, x1 - tw))
        y = py + below
        if y + th > y1:
            y = py - above - th
        y = max(y0, min(y, y1 - th))
        if self._covers(x, y, tw, th, px, py):                 # clamped back onto the pointer: other side
            for cx, cy in ((px + right, py - above - th), (px - right - tw, py + below), (px - right - tw, py - above - th)):
                if x0 <= cx and cx + tw <= x1 and y0 <= cy and cy + th <= y1:
                    return cx, cy
            if px - x0 > x1 - px:                               # no free corner: left / right of the pointer
                x = max(x0, px - right - tw)
            else:
                x = min(px + right, x1 - tw)
        return x, y

    @staticmethod
    def _covers(x, y, tw, th, px, py):
        return x - MARGIN <= px < x + tw + MARGIN and y - MARGIN <= py < y + th + MARGIN
