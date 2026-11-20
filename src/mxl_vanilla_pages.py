"""Character window page "Stash / Cube / Belt" for folder profiles (vanilla Diablo II): the character file's own
personal stash (panel 5), Horadric Cube (panel 4) and belt (location 2), in the game's grid sizes from the
profile's inventory.bin (stash 6 x 8 in LoD 1.10-1.14d, 6 x 4 for a classic character; cube 3 x 4) and belts.bin
(rows of the equipped belt). Shown, not edited: hovering an item shows it in the preview panel. Median XL keeps
its own stash files: install() registers nothing there."""
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
    except Exception as err:
        print('vanilla inventory panel:', err)


class _NoSigma:
    """mxl_d2look as mxl_inv_gui sees it in a folder profile: active() (Median XL's own inventory panel) is
    False, so the panel is the standard Diablo II character screen with the game's grid size."""

    def __init__(self, mod):
        self._mod = mod

    def active(self):
        return False

    def __getattr__(self, name):
        return getattr(self._mod, name)
