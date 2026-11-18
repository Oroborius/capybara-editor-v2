"""One floating tooltip window that does not flicker: shared by the skill tree, the stat screen and the hotkeys page.

User report (Linux AppImage, Tk 9 under XWayland, Hyprland): "the hover tooltips flicker like crazy". The old
tooltips made a new override-redirect Toplevel on every show and destroyed it on every <Leave>:
- the tip sat 18-20 px right / 14-22 px below the pointer; Wayland sends the pointer motion once per frame, so a
  quick move down-right lands the pointer ON the tip before it is moved: the widget gets <Leave>, the tip is
  destroyed, the pointer is back on the widget, <Enter>/<Motion> make a new tip - once per frame (reproduced
  under a headless sway with a virtual pointer: 12 destroy / create cycles in 13 frames);
- the hotkey cells bound <Enter>/<Leave> on each child label: crossing from the icon to the name destroyed and
  re-made the tip (every platform);
- an override-redirect window without a window type "wants focus" for wlroots / Hyprland (their XWayland code
  focuses such a window when it is mapped), and every re-made tip was a new map.
Now: one window per owner, made once (withdrawn, override-redirect, _NET_WM_WINDOW_TYPE_TOOLTIP on X11 so the
compositor never focuses it), shown with deiconify and moved with geometry; never placed under the pointer and
moved away when the pointer reaches it; hidden after a <Leave> only when the pointer really is outside the
widget, a moment later (a new show in between cancels it). Nothing here ever takes the focus."""
import tkinter as tk

HIDE_DELAY = 90          # ms: a <Leave> hides this much later, unless the pointer came back / a show came first
POLL = 200               # ms: after a <Leave> with the pointer still inside, how often it is looked at again
MARGIN = 6               # px: the tip keeps this far from the pointer


def _inside(w, outer):
    """w is outer or one of its descendants (Tk path names)."""
    try:
        a, b = str(w), str(outer)
    except Exception:
        return False
    return a == b or (a.startswith(b + '.') if b != '.' else a.startswith('.'))


class FloatTip:
    """A tooltip window. content: the caller fills tip.window() (a Label, a Canvas ...), then calls show().

    gap: (right, below, above) offsets from the pointer; within: a widget whose toplevel bounds the tip (the
    screen when the tip is larger, or without one); alpha: window opacity where supported."""

    def __init__(self, master, gap=(18, 14, 14), within=None, alpha=None, **toplevel_kw):
        self.master = master
        self.gap = gap
        self.within = within
        self.alpha = alpha
        self.kw = toplevel_kw
        self.win = None
        self.shown = False
        self.owner = None            # the widget the tip belongs to now (for the <Leave> check)
        self.on_hide = None          # called after a delayed hide (the owner forgets what it showed)
        self._job = None
        self._geo = None
        self.maps = 0                # counters for the tests
        self.unmaps = 0

    # ------------------------------------------------------------------ the window
    def window(self):
        w = self.win
        if w is not None:
            try:
                if w.winfo_exists():
                    return w
            except tk.TclError:
                pass
        w = tk.Toplevel(self.master, **self.kw)
        w.withdraw()                                   # nothing is mapped before the attributes are set
        w.overrideredirect(True)
        try:
            ws = w.tk.call('tk', 'windowingsystem')
        except tk.TclError:
            ws = ''
        if ws == 'x11':
            try:
                w.wm_attributes('-type', 'tooltip')    # wlroots / Hyprland: no focus on map; X11 WMs: no decoration
            except tk.TclError:
                pass
        for k, v in (('-topmost', True), ('-alpha', self.alpha)):
            if v is not None:
                try:
                    w.wm_attributes(k, v)
                except tk.TclError:
                    pass
        try:
            w.configure(takefocus=0)
        except tk.TclError:
            pass
        w.bind('<Enter>', self._on_tip_enter, add='+')
        w.bind('<Map>', lambda e: e.widget is w and self._count('maps'), add='+')
        w.bind('<Unmap>', lambda e: e.widget is w and self._count('unmaps'), add='+')
        self.win = w
        self._geo = None
        self.shown = False
        return w

    def _count(self, name):
        setattr(self, name, getattr(self, name) + 1)

    def exists(self):
        try:
            return self.win is not None and bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    # ------------------------------------------------------------------ show / hide
    def show(self, owner=None):
        """Places the (filled) tip beside the pointer and maps it if it is not shown yet."""
        self._cancel()
        if owner is not None:
            self.owner = owner
        w = self.window()
        self.place()
        if not self.shown:
            try:
                w.deiconify()
                w.lift()
            except tk.TclError:
                return
            self.shown = True

    def hide(self):
        self._cancel()
        if self.shown and self.exists():
            try:
                self.win.withdraw()
            except tk.TclError:
                pass
        self.shown = False

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
        if self.exists():
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self.shown = False

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
    def place(self):
        """Beside the pointer, inside the bounds, never under the pointer."""
        w = self.win
        if w is None:
            return
        try:
            w.update_idletasks()
            px, py = w.winfo_pointerxy()
            tw, th = w.winfo_reqwidth(), w.winfo_reqheight()
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
            geo = f'+{int(x)}+{int(y)}'
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
