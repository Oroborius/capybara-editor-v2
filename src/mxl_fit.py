"""The Stash tab sized from the room the window has, at every window size.

The stash grid, the equipment / inventory panel and the detail panel used to be built for one cell size chosen
from the screen (and needed about 1700 x 950 pixels). Here the cell size follows the Stash tab's own size, on
every resize: the largest cell with which both panels and a readable detail panel fit, never below MIN_CELL.
In the dark look the panels are Median XL's own art (mxl_d2look): drawn whole when there is room for them at
about their natural size, otherwise only the framed part around the grid and the gear (STASH_CROP / INV_CROP),
which gives the cells about a quarter more room. The rows above the panels (page tabs + Character / Shared stash,
Equipment + Character / Mercenary + weapon set) fold onto two lines when their panel is narrower than they are.

Everything the windows compute from the cell size keeps working: the collector reads app.cell at every use
(hit tests, drops, icons - its icon cache is keyed by the cell size) and MainInventory.layout() does the same
for the character side.

The window itself gets an explicit start size (most of the screen, at most DEFAULT_SIZE at the UI scale): with a
size of its own the content follows the window, never the other way round."""
import math
import tkinter as tk
from tkinter import font as tkfont

MIN_CELL = 14                   # below this the icons are unreadable: the panels are clipped instead
FULL_ART_CELL = 26              # the whole panel art is shown when its cells are at least this large
DEFAULT_SIZE = (1500, 900)      # start size of the window at scale 1 (never more than 86 % of the screen)
PAD = 4


class Fit:
    def __init__(self, app):
        import mxl_gui
        self.app = app
        self.G = mxl_gui
        self.inv = getattr(app, 'inventory', None)
        self.left = app.canvas.master
        self.body = self.left.master
        self.right = app.detail.master
        self.tabs = app.notebook.master
        self.scale = max(0.5, app.root.winfo_fpixels('1i') / 96.0)
        self.cap = max(app.cell, round(48 * self.scale))
        self.plan = None
        self.job = None
        self.tab_rows = None
        try:
            self.char_w = tkfont.Font(font=app.detail.cget('font')).measure('0')
        except tk.TclError:
            self.char_w = 7
        for w, pad in ((self.body, (PAD, 2, PAD, 2)), (self.right, (PAD, 0, 0, 0))):
            try:
                w.configure(padding=pad)
            except tk.TclError:
                pass
        try:
            app.detail.configure(width=1)        # takes what the panels leave, asks for nothing itself
            app.detail.pack_configure(fill='both', expand=True)
        except tk.TclError:
            pass
        try:                                     # page tabs 1..10: the themes' narrow 'Pages' tabs
            from tkinter import ttk
            app.notebook.configure(style='Pages.TNotebook')
            for b in self._views():                      # a plain tool button with a visible selected state
                b.configure(style='Toolbutton')
            if app.view.get() not in app.btn_views:      # a stored value of another kind: the character's
                app.view.set('character')                # stash is what is shown, so mark its button
            for i, t in enumerate(app.notebook.tabs()):      # '1' instead of ' 1 '
                app.notebook.tab(t, text=str(i + 1))
        except tk.TclError:
            pass
        if not getattr(app, 'd2', False):
            try:
                app.canvas.pack_configure(pady=(2, 0))
            except tk.TclError:
                pass
        if self.inv is not None:
            self.inv.on_loaded = self.later
        self.body.bind('<Configure>', self._configure, add='+')
        self.body.bind('<<ThemeChanged>>', self._configure, add='+')   # other row sizes
        # images are only dropped once the event loop runs: before it, another thread (the art warm-up) may be
        # the one collecting them, which Tk does not allow
        self.running = False
        app.root.after(1, lambda: setattr(self, 'running', True))

    # ------------------------------------------------------------------ the row of page tabs
    def _views(self):
        b = getattr(self.app, 'btn_views', {})
        return [b[k] for k in ('character', 'shared') if k in b]

    def tabs_width(self, rows):
        nb = self.app.notebook.winfo_reqwidth()
        v = sum(b.winfo_reqwidth() for b in self._views())
        return nb + v if rows == 1 else max(nb, v)

    def tabs_height(self, rows):
        nb = self.app.notebook.winfo_reqheight()
        v = max([b.winfo_reqheight() for b in self._views()] or [0])
        return max(nb, v) if rows == 1 else nb + v

    def set_tab_rows(self, rows):
        if rows == self.tab_rows:
            return
        self.tab_rows = rows
        nb, views = self.app.notebook, self._views()
        for w in [nb] + views:
            w.pack_forget()
            w.grid_forget()
        self.tabs.columnconfigure(0, weight=1)
        if rows == 1:
            nb.grid(row=0, column=0, sticky='ew')
            for i, b in enumerate(views):
                b.grid(row=0, column=1 + i, sticky='n')
        else:
            nb.grid(row=0, column=0, columnspan=1 + len(views), sticky='ew')
            for i, b in enumerate(views):
                b.grid(row=1, column=i, sticky='w')
            self.tabs.columnconfigure(0, weight=0)
            self.tabs.columnconfigure(len(views), weight=1)

    # ------------------------------------------------------------------ sizes
    def stash_size(self, c, crop):
        if getattr(self.app, 'd2', False):
            import mxl_d2look as D2
            box = D2.STASH_CROP if crop else D2.FULL
            k = c / D2.ART_CELL
            return round((box[2] - box[0]) * k), round((box[3] - box[1]) * k) + 2
        return self.G.COLS * c + 1, self.G.ROWS * c + 3

    def measure(self, c, crop, W, H):
        """(tab rows, inventory rows, spare height) when cell size c fits into W x H, else None."""
        inv = self.inv
        detail = min(max(26 * self.char_w, 0.22 * W), 56 * self.char_w)
        sw, sh = self.stash_size(c, crop)
        trows = 1 if self.tabs_width(1) <= sw else 2
        lw, lh = max(sw, self.tabs_width(trows)), self.tabs_height(trows) + sh
        rw = rh = 0
        irows = 1
        if inv is not None:
            wu, hu, extra = inv.panel_units(crop)
            iw, ih = math.ceil(wu * c), math.ceil(hu * c) + extra
            irows = 1 if inv.row_width(1) <= iw else 2
            rw, rh = max(iw, inv.row_width(irows)) + PAD, inv.row_height(irows) + 2 + ih
        if lw + rw + detail + 3 * PAD > W or max(lh, rh) + 4 > H:
            return None
        return trows, irows, H - 4 - rh

    def choose(self, W, H):
        """(cell, crop, tab rows, inventory rows, hint shown) for a Stash tab of W x H pixels."""
        art = bool(getattr(self.app, 'd2', False))
        found = {}
        for crop in ((False, True) if art else (False,)):
            for c in range(self.cap, MIN_CELL - 1, -1):
                m = self.measure(c, crop, W, H)
                if m is not None:
                    found[crop] = (c,) + m
                    break
        full, cut = found.get(False), found.get(True)
        if full is not None and (cut is None or full[0] >= FULL_ART_CELL or full[0] >= cut[0]):
            crop, got = False, full
        elif cut is not None:
            crop, got = True, cut
        else:                                    # nothing fits: smallest cells, the rest is clipped
            return (MIN_CELL, art, 2, 2, False)
        c, trows, irows, spare = got
        hint = False
        if self.inv is not None and not self.inv.d2:
            hint = spare >= self.inv.hint.winfo_reqheight() + 6
        return (c, crop, trows, irows, hint)

    # ------------------------------------------------------------------ applying
    def later(self):
        if self.job is None:
            try:
                self.job = self.app.root.after(60, self.update)
            except tk.TclError:
                pass

    def _configure(self, ev):
        if ev.widget is self.body:
            self.later()

    def update(self, size=None):
        self.job = None
        app = self.app
        try:
            W, H = size or (self.body.winfo_width(), self.body.winfo_height())
            if W < 50 or H < 50:
                return
            plan = self.choose(W, H)
            if plan == self.plan or getattr(app, 'drag', None) or (self.inv is not None and self.inv.drag):
                return
            self.plan = plan
            c, crop, trows, irows, hint = plan
            changed = c != app.cell
            app.cell = c
            if changed and self.running:
                app.icons.clear()                # one size at a time: the caches are keyed by the cell size
                if self.inv is not None:
                    self.inv.icons.clear()
            self.set_tab_rows(trows)
            if getattr(app, 'd2', False):
                import mxl_d2look as D2
                if self.running:
                    D2.release('main')
                D2.layout_stash(app, c, crop)
            else:
                app.canvas.configure(width=self.G.COLS * c + 1, height=self.G.ROWS * c + 1)
            if self.inv is not None:
                self.inv.set_rows(irows)
                self.inv.layout(c, crop, hint, redraw=False)
            app.draw_grid()
            if self.inv is not None:
                self.inv.redraw()
        except Exception as e:                   # a layout that stays as it was, never a crash
            print('mxl_fit:', type(e).__name__, e)


def start_size(root):
    """Explicit size for the main window: most of the screen, but not a wall-to-wall window on a large one."""
    try:
        scale = max(0.5, root.winfo_fpixels('1i') / 96.0)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = min(int(sw * 0.86), round(DEFAULT_SIZE[0] * scale))
        h = min(int(sh * 0.86), round(DEFAULT_SIZE[1] * scale))
        geo = f'{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}'
        root.geometry(geo)
        root.minsize(min(w, 640), min(h, 400))
        # once more when the event loop starts: a launcher may have cut the window down to what the content
        # asked for at that moment (the Linux launcher's fit_to_screen does, before the styles are in place)
        root.after(1, lambda: root.geometry(geo))
        return w, h
    except tk.TclError:
        return None


def install(App):
    """Installed after mxl_inv_gui and before mxl_tabs' wrapper runs (any position after mxl_inv_gui in the chain:
    mxl_tabs is the first installed, so its wrapper is the last to run among the earlier ones)."""
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            self.fit = Fit(self)
            size = start_size(self.root)
            if size:                             # first layout for the size the window is about to get
                self.fit.update((size[0] - 8, size[1] - 110))
        except Exception as e:
            print('mxl_fit disabled:', type(e).__name__, e)

    App._build = _build
