"""Character window page "Stash / Cube / Belt" for folder profiles (vanilla Diablo II): the character file's own
personal stash (panel 5), Horadric Cube (panel 4) and belt (location 2), in the game's grid sizes from the
profile's inventory.bin (stash 6 x 8 in LoD 1.10-1.14d, 6 x 4 for a classic character; cube 3 x 4) and belts.bin
(rows of the equipped belt). Shown, not edited: hovering an item shows it in the preview panel. Median XL keeps
its own stash files: install() registers nothing there.

Also in folder profiles only: the main window's stash pane shows the same personal stash (read-only, no page
tabs, no shared stash: the game has neither), and the item stats count the runeword list of socketed jewels
(the game adds both lists of a jewel to its parent)."""
import tkinter as tk
from tkinter import ttk

from mxl_lang import T

LOC_STORED, LOC_BELT = 0, 2
PANEL_CUBE, PANEL_STASH = 4, 5


def containers(ch, data):
    """[(key, title, cols, rows, [Entry])] of the character's stash, cube and belt (game grid sizes)."""
    import mxl_profile
    g = (mxl_profile.active() or {}).get('grids') or mxl_profile.grid_sizes(data.folder)
    expansion = bool(ch.raw[0x24] & 0x20) if hasattr(ch, 'raw') and len(ch.raw) > 0x24 else True
    stash = [e for e in ch.items if e.it.get('location') == LOC_STORED and e.it.get('panel') == PANEL_STASH]
    cube = [e for e in ch.items if e.it.get('location') == LOC_STORED and e.it.get('panel') == PANEL_CUBE]
    belt = [e for e in ch.items if e.it.get('location') == LOC_BELT]
    sw, sh = g['stash'] if expansion else g['stash_classic']
    cw, chh = g['cube']
    rows = 4
    try:
        worn = ch.equipped(False).get(8)                 # belt slot
        rows = mxl_profile.belt_rows(data, worn.it['code']) if worn is not None else 1
    except Exception:
        pass
    rows = max([rows] + [e.it.get('x', 0) // 4 + 1 for e in belt])
    return [('stash', T('van.stash', 'Stash'), sw, sh, stash),
            ('cube', T('van.cube', 'Horadric Cube'), cw, chh, cube),
            ('belt', T('van.belt', 'Belt'), 4, rows, belt)]


class ContainersPage:
    """Read-only grids; items outside a grid (hacked saves) are listed under it, never dropped."""

    def __init__(self, win, frame):
        self.win, self.frame = win, frame
        self.cell = 30
        self.icons = {}
        self.canvases = {}
        self.hits = {}
        body = ttk.Frame(frame, padding=4)
        body.pack(fill='both', expand=True)
        self.body = body
        self.note = ttk.Label(body, text=T('van.note', 'The character file\'s own stash, cube and belt (shown, not '
                                           'edited). Hover an item to see it.'), justify='left')
        self.note.pack(anchor='w')
        self.row = ttk.Frame(body)
        self.row.pack(anchor='nw', fill='x', pady=(4, 0))
        self.refresh()

    # ------------------------------------------------------------------ drawing
    def _icon(self, it, bg):
        try:
            from PIL import Image, ImageTk
            from mxl_gfx import icon_layers, icon_name, ICON_CELL
            import paths
            d = self.win.data
            key = (it['code'], icon_name(it, d), it.get('image'), it.get('ethereal'), self.cell)
            if key not in self.icons:
                layers = icon_layers(it, d, bg, paths.ICONS_DIR)
                im = layers.get(1) if layers else None
                if im is not None:
                    f = self.cell / ICON_CELL
                    im = ImageTk.PhotoImage(im.resize((max(1, round(im.width * f) - 2),
                                                       max(1, round(im.height * f) - 2)), Image.LANCZOS))
                self.icons[key] = im
            return self.icons[key]
        except Exception:
            return None

    def refresh(self):
        for w in self.row.winfo_children():
            w.destroy()
        self.canvases, self.hits = {}, {}
        ch, d = self.win.ch, self.win.data
        if ch is None:
            return
        try:
            boxes = containers(ch, d)
        except Exception as err:
            ttk.Label(self.row, text=f'{type(err).__name__}: {err}').pack(anchor='w')
            return
        c = self.cell
        for key, title, cols, rows, entries in boxes:
            fr = ttk.Frame(self.row)
            fr.pack(side='left', anchor='nw', padx=(0, 10))
            ttk.Label(fr, text=f'{title} ({cols} x {rows})').pack(anchor='w')
            cv = tk.Canvas(fr, width=cols * c + 1, height=rows * c + 1, bg='#101010', highlightthickness=0)
            cv.pack(anchor='nw')
            for x in range(cols):
                for y in range(rows):
                    cv.create_rectangle(x * c, y * c, (x + 1) * c, (y + 1) * c, fill='#181818', outline='#404040')
            hits, outside = [], []
            for e in entries:
                it = e.it
                try:
                    w, h = (1, 1) if key == 'belt' else d.base(it['code']).size
                except Exception:
                    w, h = 1, 1
                x, y = (it.get('x', 0) % 4, it.get('x', 0) // 4) if key == 'belt' else (it.get('x', 0), it.get('y', 0))
                if key == 'belt':
                    y = rows - 1 - y                         # the game fills the belt from the bottom row
                if x + w > cols or y + h > rows or y < 0:
                    outside.append(e)
                    continue
                x0, y0 = x * c, y * c
                cv.create_rectangle(x0 + 1, y0 + 1, x0 + w * c - 1, y0 + h * c - 1, fill='#1c2a40', outline='')
                img = self._icon(it, '#1c2a40')
                if img is not None:
                    cv.create_image(x0 + w * c / 2, y0 + h * c / 2, image=img)
                else:
                    cv.create_text(x0 + w * c / 2, y0 + h * c / 2, text=it['code'].strip(), fill='#c0c0c0')
                hits.append((x, y, w, h, e))
            if outside:
                ttk.Label(fr, text=T('van.outside', 'outside the grid: {items}',
                                     items=', '.join(e.it.get('name') or e.it['code'] for e in outside)),
                          wraplength=max(120, cols * c)).pack(anchor='w')
            cv.bind('<Motion>', lambda ev, k=key: self._hover(k, ev))
            self.canvases[key], self.hits[key] = cv, hits

    def entry_at(self, key, x, y):
        c = self.cell
        cx, cy = x // c, y // c
        for x0, y0, w, h, e in self.hits.get(key, ()):
            if x0 <= cx < x0 + w and y0 <= cy < y0 + h:
                return e
        return None

    def _hover(self, key, ev):
        e = self.entry_at(key, ev.x, ev.y)
        try:
            self.win.panel.show(e.it if e is not None else None)
        except Exception:
            pass


def install():
    """Registers the page in folder profiles only (before the Character window is built)."""
    import mxl_profile
    if mxl_profile.is_median():
        return
    import mxl_char_gui
    mxl_char_gui.register_page('containers', T('van.tab', 'Stash / Cube / Belt'), ContainersPage)
    try:                       # main window inventory: the standard D2 screen, not Median's 15 x 10 panel art
        import mxl_inv_gui
        mxl_inv_gui.D2 = _NoSigma(mxl_inv_gui.D2)
        _native_cover(mxl_inv_gui)
    except Exception as err:
        print('vanilla inventory panel:', err)
    try:
        install_sockets()
    except Exception as err:
        print('vanilla socket stats:', err)
    try:
        import mxl_gui
        install_main(mxl_gui.App)
    except Exception as err:
        print('vanilla main stash:', err)


# ---------------------------------------------------------------------------------------- socketed jewels
def install_sockets():
    """mxl_stat_text.socket_contents gave a socketed jewel's magic list only; a vanilla (mock) jewel often carries
    a runeword list too, which the game adds to the parent as well. One entry per child (mxl_edit's owners)."""
    import mxl_stat_text
    orig = mxl_stat_text.socket_contents
    if getattr(orig, '_capy_rw', False):
        return

    def socket_contents(it, data):
        out = orig(it, data)
        res = []
        for sub, src, stats in out:
            rw = sub.get('stats_runeword') if src == 'J' else None
            res.append((sub, src, list(stats) + list(rw)) if rw else (sub, src, stats))
        return res
    socket_contents._capy_rw = True
    mxl_stat_text.socket_contents = socket_contents
    import mxl_tooltip
    if getattr(mxl_tooltip, 'socket_contents', None) is orig:
        mxl_tooltip.socket_contents = socket_contents


# ---------------------------------------------------------------------------------------- main window stash pane
def stash_view(ch, data):
    """(cols, rows, [item dict]) of the character's personal stash for the main window's grid: copies with
    page 0 (the collector's grid draws one page); items outside the grid are left out (the Character window's
    page lists them)."""
    _k, _t, cols, rows, entries = containers(ch, data)[0]
    items = []
    for e in entries:
        it = e.it
        try:
            w, h = data.base(it['code']).size
        except Exception:
            w, h = 1, 1
        x, y = it.get('x', 0), it.get('y', 0)
        if 0 <= x and 0 <= y and x + w <= cols and y + h <= rows:
            items.append(dict(it, page=0))
    return cols, rows, items


def install_main(App):
    """The main window's stash pane in a folder profile: the character file's own stash (panel 5) in the game's
    grid (6 x 8, classic 6 x 4), no page tabs and no Character / Shared buttons, no '.stash not found'. Read-only:
    app.path stays None, so every stash writer of the editor (moves, menus, undo, drops) finds no stash file;
    clicking an item shows it in the detail panel."""
    import os
    import mxl_gui
    import mxl_profile
    g = (mxl_profile.active() or {}).get('grids') or {}
    mxl_gui.COLS, mxl_gui.ROWS = g.get('stash') or (6, 8)
    mxl_gui.NB_PAGES = 1
    o_build, o_click, o_status, o_watch = App._build, App.on_click, App.show_status, App.watch_files

    def _build(self):
        o_build(self)
        try:
            self.notebook.master.pack_forget()        # page tabs 1..10 and Character / Shared stash
            self.van_title = ttk.Label(self.canvas.master, text='')
            self.van_title.pack(side='top', anchor='w', before=self.canvas)
        except Exception as err:
            print('vanilla main stash:', err)

    def open_view(self, keep_page=False):
        cf = self.character_file()
        if not cf:
            return
        try:
            mxl_gui.settings.put('last_character', self.char_combo.get())
        except Exception:
            pass
        old = self.selected
        self.path, self.char_file = None, cf
        self.van_sig = mxl_gui.file_signature(cf)
        items, err, cols, rows = [], None, mxl_gui.COLS, mxl_gui.ROWS
        if os.path.exists(cf):
            try:
                import mxl_char
                cols, rows, items = stash_view(mxl_char.Character(cf, self.data), self.data)
            except Exception as e:
                err = f'{type(e).__name__}: {e}'
            try:
                self.char, self.char_error = mxl_gui.load_character(cf, self.data), None
            except Exception as e:
                self.char, self.char_error = None, f'{type(e).__name__}: {e}'
        else:
            self.char, self.char_error = None, None
        self.van_error = err
        self.icons.clear()
        self.items = items
        self.selected = None
        if keep_page and old is not None:
            self.selected = next((i for i in items if (i['x'], i['y'], i['code']) ==
                                  (old.get('x'), old.get('y'), old.get('code'))), None)
        if (cols, rows) != (mxl_gui.COLS, mxl_gui.ROWS):
            mxl_gui.COLS, mxl_gui.ROWS = cols, rows
            fit = getattr(self, 'fit', None)
            try:
                if fit is not None:
                    fit.plan = None
                    fit.update()
                else:
                    self.canvas.configure(width=cols * self.cell + 1, height=rows * self.cell + 1)
            except Exception:
                pass
        try:
            self.van_title.configure(text=T('van.main_stash', 'Stash ({cols} x {rows}) - shown, not edited here',
                                            cols=cols, rows=rows))
        except Exception:
            pass
        self.root.title(mxl_gui.tr('app.title_file', file=os.path.basename(cf)))
        self.draw_grid()
        self.set_detail(self.selected)
        self.show_status()

    def show_status(self):
        if self.path or not self.char_file:
            return o_status(self)
        try:
            self.count_total.configure(text=mxl_gui.tr('count.stash', n=len(self.items)))
            self.count_page.configure(text='')
            ch = self.char
            txt = None
            try:
                import mxl_status_attr
                txt = mxl_status_attr.status_text(self)
            except Exception:
                pass
            if not txt and ch:
                txt = mxl_gui.tr('status.char', name=ch['name'], cls=mxl_gui.CLASSES[ch['cls']], level=ch['level'],
                                 str=ch['strength'], dex=ch['dexterity'])
            elif not txt:
                txt = mxl_gui.tr('status.char_error', error=self.char_error) if self.char_error else ''
            self.char_label.configure(text=txt)
            self.status.configure(text=getattr(self, 'van_error', None) or T('van.main_hint', 'Click an item to see it'))
        except Exception as err:
            print('vanilla main stash status:', err)

    def on_click(self, ev):
        o_click(self, ev)
        self.drag = None                              # read-only: no move, no drop into the character

    def watch_files(self):
        try:                                          # the character file changed on disk (the game, a save)
            if self.drag is None and self.char_combo.get():
                cf = self.character_file()
                if cf != self.char_file or mxl_gui.file_signature(cf) != getattr(self, 'van_sig', None):
                    self.open_view(keep_page=True)
        except Exception:
            pass
        o_watch(self)

    App._build, App.open_view, App.show_status = _build, open_view, show_status
    App.on_click, App.watch_files = on_click, watch_files
    import mxl_rc_menu                                # its stash menu edits the stash file: none here
    o_menu = mxl_rc_menu._stash_menu

    def _stash_menu(app, ev):
        if app.path is None:
            return None
        return o_menu(app, ev)
    mxl_rc_menu._stash_menu = _stash_menu


# The game's own inventory screen at its native size (invchar6.dc6, 320 x 432: paperdoll + the 10 x 4 grid +
# gold box), instead of Median XL's 512 x 704 layout (the paperdoll x1.6 over mirror-tiled stone for a 15 x 10
# grid: "a smeared mess" with the 10 x 4 grid of the base game). Positions in native panel pixels: the grid and
# the boxes from inventory.bin (row 0: grid 339,255 - panel 320,0; cells 29 = the editor's ART_CELL), the gold box
# and the I / II tabs measured on the art.
NATIVE_SCALE = 1.6                  # Median layout pixels per native pixel (mxl_d2look.GEAR_D2 & co.)
NATIVE_PANEL = (320, 432)
NATIVE_GRID = (18, 254)
NATIVE_GOLD_BTN = (25, 390)         # goldbtn.dc6 (19 x 19) centred in the small box at 17,383 (34 x 34)
NATIVE_GOLD = (111, 400)            # left end of the amount: the long part of the gold box (106-198, y 390-410)


def _n(v):
    return int(round(v / NATIVE_SCALE))


class _NativeArt:
    """The character art with char_panel_d2() = the game's whole inventory screen, unscaled."""

    def __init__(self, art):
        self._art = art

    def char_panel_d2(self):
        a = self._art

        def build():
            import mxl_d2ui_dc6 as DC6
            fr = DC6.dc6_frames(a.read_base('data\\global\\ui\\PANEL\\invchar6.dc6'))
            return DC6.compose(fr[4:8], a.pal(), 2)
        return a._cached('panel-d2-character-native', build)

    def __getattr__(self, name):
        return getattr(self._art, name)


def _native_cover(inv):
    """The mercenary view's stone patches (mxl_inv_gui D2_COVER_*) in native pixels."""
    for name in ('D2_COVER_SRC',):
        v = getattr(inv, name, None)
        if isinstance(v, dict):
            setattr(inv, name, {k: tuple(_n(x) for x in xy) for k, xy in v.items()})
    for name in ('D2_COVER_WSET',):
        v = getattr(inv, name, None)
        if isinstance(v, tuple):
            setattr(inv, name, tuple(tuple(_n(x) for x in r) for r in v))
    if isinstance(getattr(inv, 'D2_COVER_WSET_SRC', None), tuple):
        inv.D2_COVER_WSET_SRC = tuple(_n(x) for x in inv.D2_COVER_WSET_SRC)
    for name in ('D2_COVER_MARGIN', 'D2_COVER_FADE', 'D2_COVER_WSET_FADE'):
        if isinstance(getattr(inv, name, None), int):
            setattr(inv, name, max(2, _n(getattr(inv, name))))


class _NoSigma:
    """mxl_d2look as mxl_inv_gui sees it in a folder profile: active() (Median XL's own inventory panel) is
    False, so the panel is the standard Diablo II character screen, at the game's own size and layout."""

    def __init__(self, mod):
        self._mod = mod
        self.PANEL_W, self.PANEL_H = NATIVE_PANEL
        self.GEAR_D2 = {k: tuple(_n(v) for v in box) for k, box in mod.GEAR_D2.items()}
        self.GEAR_D2_INSET = 2
        self.CHAR_GRID = NATIVE_GRID
        self.CHAR_GOLD_BTN = NATIVE_GOLD_BTN
        self.CHAR_GOLD = NATIVE_GOLD
        self.WSET_TABS_D2 = {k: tuple(tuple(_n(v) for v in xy) for xy in t) for k, t in mod.WSET_TABS_D2.items()}
        self.WSET_TAB_D2 = tuple(_n(v) for v in mod.WSET_TAB_D2)

    def active(self):
        return False

    def char_art(self):
        a = self._mod.char_art()
        return _NativeArt(a) if a is not None else None

    def __getattr__(self, name):
        return getattr(self._mod, name)
