"""Equipment and inventory of the selected character shown in the main window, next to the stash.

- Equipment (paperdoll, character or mercenary, weapon set I / II) above the 15x10 inventory.
- Drag items between the stash grid, the inventory and the equipment slots, in any direction; drag inside the
  inventory or between slots to move them there. While dragging from the character, hovering a stash page tab or
  the Shared / Character button switches to it, as in the stash.
- Click an item to see its tooltip in the detail panel.
Every write goes through the collector's safe writers (game closed, verification, .bak backup). When an item
crosses between two files and the second write fails, the first file is put back as it was."""
import os
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk

import mxl_save
from mxl_save import (parse_stash, edit_stash, item_blob, read_file, commit_file, placement_error, EditError,
                      STASH_COLS, STASH_ROWS)
from mxl_format import FormatError
from mxl_gui_detail import item_color, LAYERS_SHOWN
from mxl_gfx import icon_layers, icon_name, ICON_CELL
from paths import ICONS_DIR
from mxl_tooltip import requirements_unmet
from mxl_theme import BG, GRID_LINE, EMPTY, CELL_OK, CELL_KO, SELECTION, DROP_OK, DROP_KO, blend
import mxl_char as MC
from mxl_char import Character, CharError, INV_W, INV_H, MERC_SLOTS, SLOT_NAMES, slot_name
from mxl_lang import T
from mxl_creator_gui import PreviewPanel, PreviewHost, clean
from mxl_char_gui import DOLL, SET2, DOLL_W, DOLL_H
import mxl_d2look as D2

ERRORS = (CharError, EditError, FormatError, OSError, KeyError, ValueError)


def _sig(path):
    try:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path, None, None)


# Stone of the base-game character screen (panel pixels, see mxl_d2look.char_panel_d2) laid over the equipment
# boxes the mercenary has no slot for: the game's hireling inventory (inventory.bin, the "Hireling" rows) has no
# ring boxes, so a ring frame on his view could never take an item. Source: the open stone between the left
# hand and the helm / between the armour and the right hand, edges faded in.
D2_COVER_SRC = {6: (134, 128), 7: (318, 128)}
D2_COVER_MARGIN, D2_COVER_FADE = 10, 6


def d2_panel_without(path, boxes):
    """Path of a copy of the base-game character panel (cached PNG at path) with the frames of boxes (slots
    6 / 7) painted over with stone; the panel itself when there is nothing to hide or the copy cannot be made."""
    boxes = sorted(b for b in boxes if b in D2_COVER_SRC)
    if not boxes:
        return path
    out = f"{os.path.splitext(path)[0]}-without-{'-'.join(map(str, boxes))}.png"
    try:
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
            return out
        im = Image.open(path).convert('RGBA')
        src = im.copy()
        m, f = D2_COVER_MARGIN, D2_COVER_FADE
        for b in boxes:
            x, y, w, h = D2.GEAR_D2[b]
            sx, sy = D2_COVER_SRC[b]
            pw, ph = w + 2 * m, h + 2 * m
            mask = Image.new('L', (pw, ph), 0)
            px = mask.load()
            for i in range(pw):
                for j in range(ph):
                    d = min(i, j, pw - 1 - i, ph - 1 - j)
                    px[i, j] = 255 if d >= f else 255 * d // f
            im.paste(src.crop((sx, sy, sx + pw, sy + ph)), (x - m, y - m), mask)
        tmp = f'{out}.{os.getpid()}.tmp'
        im.save(tmp, 'PNG')
        os.replace(tmp, out)
        return out
    except Exception as e:                        # the frames stay (inert): never a crash over looks
        print('D2 look: mercenary panel not made:', e)
        return path


def _local(widget, x_root, y_root):
    """Pointer position inside widget, or None when outside."""
    try:
        if not widget.winfo_ismapped():
            return None
        x = x_root - widget.winfo_rootx()
        y = y_root - widget.winfo_rooty()
        if 0 <= x < widget.winfo_width() and 0 <= y < widget.winfo_height():
            return x, y
    except tk.TclError:
        pass
    return None


class MainInventory:
    def __init__(self, app):
        self.app = app
        self.data = app.data
        self.ch = None
        self.sig = None
        self.error = None
        self.selected = None          # Entry of the character or of the mercenary
        self.sel_merc = False
        self.drag = None
        self.icons = {}
        self._imgs = {}
        self.merc = tk.BooleanVar(value=False)
        self.wset = tk.IntVar(value=1)
        stash = app.canvas
        left = stash.master
        body = left.master
        right = app.detail.master
        # same cell size as the stash; mxl_fit chooses it from the room the window has (layout())
        self.sigma = bool(getattr(app, 'd2', False)) and D2.active()   # Median XL's own inventory panel (dark look)
        self.d2 = self.sigma or D2.char_active()   # else the standard Diablo II character screen (base-game art)
        self.org = (0, 0)
        fr = ttk.Frame(body, padding=(4, 0, 0, 0))
        fr.pack(side='left', fill='y', before=right)
        self.frame = fr
        row = ttk.Frame(fr)
        row.pack(fill='x', pady=(2, 0))
        self.row = row
        self.title = ttk.Label(row, text=T('inv.equipment', 'Equipment'))
        self.row_btns = ttk.Frame(row)
        self.rb_merc = []
        for text, val in ((T('ch.character', 'Character'), False), (T('ch.mercenary', 'Mercenary'), True)):
            b = ttk.Radiobutton(self.row_btns, text=text, value=val, variable=self.merc, command=self.on_view)
            b.pack(side='left', padx=(6 if not val else 2, 2))
            self.rb_merc.append(b)
        self._wset_made = False
        if not self.d2:                               # on the game's panels the I / II tabs themselves are clicked
            self._wset_buttons()
        self.row_rows = None
        self.set_rows(1)
        self.doll = tk.Canvas(fr, bg='#000000' if self.d2 else BG, highlightthickness=0)
        self.doll.pack(anchor='nw', pady=(2, 0))
        if self.d2:                                   # the game's own panel; the grid sits on the panel's grid
            self.inv_label = ttk.Label(fr, text='')
            self.canvas = tk.Canvas(fr, bg=D2.CELL_BG if self.sigma else D2.CHAR_CELL_BG, highlightthickness=0)
        else:
            self.inv_label = ttk.Label(fr, text=T('ch.tab.inventory', 'Inventory'))
            self.inv_label.pack(anchor='w', pady=(2, 0))
            self.canvas = tk.Canvas(fr, bg=BG, highlightthickness=0)
            self.canvas.pack(anchor='nw', pady=(2, 0))
        for cv in (self.doll, self.canvas):
            cv.bind('<Button-1>', self.on_press)
            cv.bind('<B1-Motion>', self.on_drag)
            cv.bind('<ButtonRelease-1>', self.on_release)
            cv.bind('<Motion>', self.on_motion)
            cv.bind('<Leave>', lambda e: self.drag is None and self.app.show_status())
            cv.bind('<ButtonRelease-3>', self.on_menu)      # on release, like the stash menu (see mxl_rc_menu)
        self.hint = ttk.Label(fr, text=T('inv.hint', 'Drag items between the stash, the inventory and the equipment. '
                                         'It can stay open while the game runs; a backup is made before the first change.'),
                              justify='left')
        self.panel = PreviewPanel(app.detail, PreviewHost(app))
        self.layout(app.cell, redraw=False)
        self.refresh(force=True)
        try:                                          # Ctrl+C / Ctrl+V / Ctrl+Shift+C / V / Del at the pointer
            import mxl_rc_menu
            mxl_rc_menu.install_panel(self)
        except Exception as e:
            print('item hotkeys (inventory panel) not installed:', e)

    def _wset_buttons(self):
        if self._wset_made:
            return
        self._wset_made = True
        ttk.Label(self.row_btns, text='  ' + T('ch.weapon_set', 'Weapon set')).pack(side='left')
        for n in (1, 2):
            ttk.Radiobutton(self.row_btns, text='I' if n == 1 else 'II', value=n, variable=self.wset,
                            command=self.redraw).pack(side='left', padx=2)

    # ------------------------------------------------------------------ sizes
    def set_rows(self, n):
        """The row above the paperdoll on one line, or on two (title above the buttons) when the panel is narrow."""
        if n == self.row_rows:
            return
        self.row_rows = n
        self.title.pack_forget()
        self.row_btns.pack_forget()
        if n == 1:
            self.title.pack(side='left')
            self.row_btns.pack(side='left')
        else:
            self.title.pack(side='top', anchor='w')
            self.row_btns.pack(side='top', anchor='w')

    def row_width(self, n):
        t, b = self.title.winfo_reqwidth(), self.row_btns.winfo_reqwidth()
        return t + b if n == 1 else max(t, b)

    def row_height(self, n):
        t, b = self.title.winfo_reqheight(), self.row_btns.winfo_reqheight()
        return (max(t, b) if n == 1 else t + b) + 2

    def panel_units(self, crop=False):
        """(width, height) of everything below the row in cells, plus extra pixels of height."""
        if self.sigma:
            box = D2.INV_CROP if crop else D2.FULL
            return (box[2] - box[0]) / D2.ART_CELL, (box[3] - box[1]) / D2.ART_CELL, 2
        if self.d2:
            return D2.PANEL_W / D2.ART_CELL, D2.PANEL_H / D2.ART_CELL, 2
        return max(DOLL_W, INV_W) + 0.1, DOLL_H + INV_H + 0.1, self.inv_label.winfo_reqheight() + 8

    def layout(self, c, crop=False, hint=False, redraw=True):
        """Sizes the paperdoll and the inventory for a cell size; crop=True keeps only the framed part of the
        Median XL panel (small windows)."""
        self.cell = c
        self.k = k = c / D2.ART_CELL
        A = D2.ART_CELL
        if self.sigma:
            box = D2.INV_CROP if crop else D2.FULL
            ox, oy = self.org = box[0], box[1]
            self.boxes = {slot: ((x - ox) / A, (y - oy) / A, D2.GEAR_SIZE[f][0] / A, D2.GEAR_SIZE[f][1] / A)
                          for slot, (f, _p, x, y) in D2.GEAR.items()}
            self.doll.configure(width=round((box[2] - ox) * k), height=round((box[3] - oy) * k))
            self.canvas.configure(width=INV_W * c, height=INV_H * c)
            self.canvas.place(in_=self.doll, x=round((D2.INV_GRID[0] - ox) * k), y=round((D2.INV_GRID[1] - oy) * k))
            self.canvas.tk.call('raise', self.canvas._w)
        elif self.d2:
            self.org = (0, 0)
            self.boxes = {slot: (x / A, y / A, w / A, h / A) for slot, (x, y, w, h) in D2.GEAR_D2.items()}
            self.doll.configure(width=round(D2.PANEL_W * k), height=round(D2.PANEL_H * k))
            self.canvas.configure(width=INV_W * c, height=INV_H * c)
            self.canvas.place(in_=self.doll, x=round(D2.CHAR_GRID[0] * k), y=round(D2.CHAR_GRID[1] * k))
            self.canvas.tk.call('raise', self.canvas._w)
        else:
            self.boxes = DOLL
            self.doll.configure(width=int(DOLL_W * c) + 1, height=int(DOLL_H * c) + 1)
            self.canvas.configure(width=INV_W * c + 1, height=INV_H * c + 1)
        self.hint.configure(wraplength=max(120, INV_W * c))
        if hint and not self.d2:
            self.hint.pack(anchor='w', pady=(4, 0))
        else:
            self.hint.pack_forget()
        if redraw:
            self.redraw()

    # ------------------------------------------------------------------ loading / drawing
    def is_merc(self):
        return bool(self.merc.get()) and self.ch is not None and self.ch.merc_hired

    def slot_of(self, box):
        return SET2.get(box, box) if self.wset.get() == 2 else box

    def visible_boxes(self):
        if not self.is_merc():
            return list(self.boxes)
        # the mercenary: his own slots, plus any other slot he really wears something in (Sigma mercenaries
        # have gloves, belts, boots, amulets...) - shown so the item can be reached, edited or taken off
        worn = self.ch.equipped(True)
        return [b for b in self.boxes if b in MERC_SLOTS or self.slot_of(b) in worn]

    def as_win(self):
        """This panel behind the interface mxl_rc_menu's character-item functions expect (see PanelWin)."""
        return PanelWin(self)

    def on_view(self):
        self.selected = None
        self.redraw()
        self.show_detail()

    def refresh(self, force=False):
        """Reloads the character when the selection or the file changed (called with every stash redraw)."""
        if self.drag is not None:
            return
        path = self.app.character_file()
        sig = _sig(path) if path else None
        if not force and sig == self.sig:
            return
        self.sig = sig
        self.ch, self.error, self.selected = None, None, None
        if path and os.path.exists(path):
            try:
                self.ch = Character(path, self.data)
            except Exception as e:                        # unreadable save: shown, never written
                self.error = f'{type(e).__name__}: {e}'
        hired = self.ch is not None and self.ch.merc_hired
        self.rb_merc[1].state(['!disabled'] if hired else ['disabled'])
        if not hired:
            self.merc.set(False)
        self.redraw()
        self._sync_char_tab()                             # whoever wrote the file (this panel, an undo, the game)
        cb = getattr(self, 'on_loaded', None)   # mxl_fit: the title changed, the row may need another layout
        if cb is not None:
            cb()

    def reload(self):
        self.refresh(force=True)

    def icon(self, it, bg):
        # always this panel's own cache: the collector empties its cache when another stash is opened, and an
        # image still shown here would go blank with it
        try:
            d = self.data
            key = (it['code'], icon_name(it, d), it.get('image'), it.get('ethereal'), it.get('sockets'),
                   tuple(icon_name(s, d) for s in it.get('socketed', [])), bg, self.cell)
            if key not in self.icons:
                layers = icon_layers(it, d, bg, ICONS_DIR)
                if layers is not None and layers.get(1) is not None:
                    f = self.cell / ICON_CELL
                    size = (max(1, round(layers[1].width * f) - 2), max(1, round(layers[1].height * f) - 2))
                    layers = {k: (ImageTk.PhotoImage(im.resize(size, Image.LANCZOS)) if im is not None else None)
                              for k, im in layers.items()}
                self.icons[key] = layers
            return self.icons[key]
        except Exception:
            return None

    def size(self, it):
        return self.data.base(it['code']).size

    def draw_item(self, cv, it, x0, y0, x1, y1, sel, check_req=True):
        d, char = self.data, self.app.char
        try:
            unmet = check_req and char is not None and requirements_unmet(it, d, char)
        except Exception:
            unmet = False
        bg = CELL_KO if unmet else CELL_OK
        fill = blend(SELECTION, bg, 0.12) if sel else bg
        col = item_color(it, d)
        cv.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill=fill, outline=col if sel else '',
                            width=2 if sel else 0)
        imgs = self.icon(it, fill)
        if imgs:
            for k in (1, 2, 3):
                if imgs.get(k) is not None and k in LAYERS_SHOWN:
                    cv.create_image((x0 + x1) / 2, (y0 + y1) / 2, image=imgs[k])
        else:
            cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=clean(it['name']), fill=col,
                           width=max(20, x1 - x0 - 6), font=('Segoe UI', 8), justify='center')

    def redraw(self):
        c = self.cell
        ch = self.ch
        merc = self.is_merc()
        if ch is None:
            name = self.app.char_combo.get() if hasattr(self.app, 'char_combo') else ''
            self.title.configure(text=T('inv.title_error', 'Equipment - {name}: {error}', name=name, error=self.error)
                                 if self.error else T('inv.title_none', 'Equipment - choose a character'))
            self.inv_label.configure(text=T('ch.tab.inventory', 'Inventory'))
        else:
            self.title.configure(text=T('inv.title', 'Equipment - {name}, level {level}', name=ch.name, level=ch.level))
            self.inv_label.configure(text=T('inv.inv_title', 'Inventory - {name}', name=ch.name))
        if self.d2:
            try:
                return self.redraw_d2()
            except Exception as e:
                print('D2 look (inventory) drawing failed:', e)
                self.d2 = self.sigma = False       # plain layout from now on (also for the hit tests)
                self.doll.configure(bg=BG)
                self.canvas.place_forget()
                self.inv_label.pack(anchor='w', pady=(2, 0))
                self.canvas.pack(anchor='nw', pady=(2, 0))
                self.canvas.configure(bg=BG)
                self._wset_buttons()
                self.layout(c, redraw=False)
        # paperdoll
        dv = self.doll
        dv.delete('all')
        eq = ch.equipped(merc) if ch is not None else {}
        for box in self.visible_boxes():
            x, y, w, h = DOLL[box]
            slot = self.slot_of(box)
            x0, y0, x1, y1 = x * c, y * c, (x + w) * c, (y + h) * c
            dv.create_rectangle(x0, y0, x1, y1, fill=EMPTY, outline=GRID_LINE)
            e = eq.get(slot)
            if e is not None:
                self.draw_item(dv, e.it, x0, y0, x1, y1, e is self.selected, check_req=not merc)
            elif box in (4, 5):
                dv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text='I' if self.wset.get() == 1 else 'II',
                               fill='#444444', font=('Segoe UI', 14))
            else:
                dv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=slot_name(slot).split(' (')[0],
                               fill='#3a3a3a', font=('Segoe UI', 7), width=max(20, x1 - x0 - 4), justify='center')
        # inventory
        cv = self.canvas
        cv.delete('all')
        for x in range(INV_W):
            for y in range(INV_H):
                cv.create_rectangle(x * c, y * c, (x + 1) * c, (y + 1) * c, fill=EMPTY, outline=GRID_LINE)
        if ch is None:
            return
        for e in ch.inventory():
            it = e.it
            w, h = self.size(it)
            x0, y0 = it['x'] * c, it['y'] * c
            self.draw_item(cv, it, x0, y0, x0 + w * c, y0 + h * c, e is self.selected)

    def redraw_d2(self):
        """The standard Diablo II character screen (the game's own base art): the paperdoll with every
        equipment box and the I / II weapon-set tabs, the character's gold, and the 15 x 10 inventory drawn
        in the game's own grid style (dark cells, grey borders) over the stone below the paperdoll."""
        k, c, ch = self.k, self.cell, self.ch
        merc = self.is_merc()
        if ch is None:
            name = self.app.char_combo.get() if hasattr(self.app, 'char_combo') else ''
            self.title.configure(text=T('inv.title_error', 'Equipment - {name}: {error}', name=name, error=self.error)
                                 if self.error else T('inv.title_none', 'Equipment - choose a character'))
        else:
            self.title.configure(text=T('inv.title', 'Equipment - {name}, level {level}', name=ch.name, level=ch.level))
        if self.sigma:
            return self.redraw_sigma()
        a = D2.char_art()
        dv = self.doll
        dv.delete('all')
        panel = a.char_panel_d2()
        if merc:                                  # no ring frames on the mercenary (he has no ring slots)
            panel = d2_panel_without(panel, set(D2_COVER_SRC) - set(self.visible_boxes()))
        dv.create_image(0, 0, anchor='nw', image=D2.photo(panel, (round(D2.PANEL_W * k), round(D2.PANEL_H * k))),
                        tags=('panel',))
        eq = ch.equipped(merc) if ch is not None else {}
        for box in self.visible_boxes():
            x, y, w, h = D2.GEAR_D2[box]
            e = eq.get(self.slot_of(box))
            if e is not None:
                i = D2.GEAR_D2_INSET
                self.draw_item_d2(dv, e.it, (x + i) * k, (y + i) * k, (x + w - i) * k, (y + h - i) * k,
                                  e is self.selected, check_req=not merc)
        if 4 in self.visible_boxes() or 5 in self.visible_boxes():
            tw, th = D2.WSET_TAB_D2
            for tx, ty in D2.WSET_TABS_D2.get(self.wset.get(), ()):     # the game's own tabs, active set marked
                dv.create_rectangle(round(tx * k) + 1, round(ty * k) + 1,
                                    round((tx + tw) * k) - 1, round((ty + th) * k) - 1,
                                    outline='#%02x%02x%02x' % D2.GOLD_TXT, width=2)
        if ch is not None and not merc:
            try:
                dv.create_image(round(D2.CHAR_GOLD_BTN[0] * k), round(D2.CHAR_GOLD_BTN[1] * k), anchor='nw',
                                image=D2.photo(a.base_frame('goldbtn.DC6', 0), (round(19 * k), round(19 * k))))
            except Exception:
                pass
            D2.draw_text(dv, D2.CHAR_GOLD[0] * k, D2.CHAR_GOLD[1] * k, D2.fmt_gold(ch.stat(14)), k, anchor='w')
        cv = self.canvas
        cv.delete('all')
        for yy in range(INV_H):                     # the game's grid style instead of a panel crop
            for xx in range(INV_W):
                cv.create_rectangle(xx * c, yy * c, (xx + 1) * c, (yy + 1) * c,
                                    fill=D2.CHAR_CELL_BG, outline=D2.CHAR_GRID_LINE)
        if ch is None:
            return
        for e in ch.inventory():
            it = e.it
            w, h = self.size(it)
            x0, y0 = it['x'] * c, it['y'] * c
            self.draw_item_d2(cv, it, x0, y0, x0 + w * c, y0 + h * c, e is self.selected)

    def redraw_sigma(self):
        """Dark look: Median XL's own inventory panel, gear frames (silhouette when empty), weapon-set tabs, gold,
        the inventory on the panel's own grid."""
        k, c, ch = self.k, self.cell, self.ch
        ox, oy = self.org
        merc = self.is_merc()
        a = D2.art()
        dv = self.doll
        dv.delete('all')
        dv.create_image(round(-ox * k), round(-oy * k), anchor='nw',
                        image=D2.photo(a.panel('character-inventory'), (round(D2.PANEL_W * k), round(D2.PANEL_H * k)),
                                       tag='main'))
        try:
            dv.create_image(round((D2.CLOSE_INV[0] - ox) * k), round((D2.CLOSE_INV[1] - oy) * k), anchor='nw',
                            image=D2.photo(a.frame('buttons\\close', 0), (round(23 * k), round(23 * k))))
        except Exception:
            pass
        eq = ch.equipped(merc) if ch is not None else {}
        boxes = self.visible_boxes()
        for box in boxes:
            sil, plain, x, y = D2.GEAR[box]
            x, y = x - ox, y - oy
            e = eq.get(self.slot_of(box))
            dv.create_image(round(x * k), round(y * k), anchor='nw',
                            image=D2.gear_photo(plain if e is not None else sil, k))
            if e is not None:
                w, h = D2.GEAR_SIZE[sil]
                i = D2.GEAR_INSET
                self.draw_item_d2(dv, e.it, (x + i) * k, (y + i) * k, (x + w - i) * k, (y + h - i) * k,
                                  e is self.selected, check_req=not merc)
        if 4 in boxes or 5 in boxes:
            f = D2.WSET_TAB[0] if self.wset.get() == 1 else D2.WSET_TAB[1]
            for tx, ty in D2.WSET_TABS:
                dv.create_image(round((tx - ox) * k), round((ty - oy) * k), anchor='nw', image=D2.gear_photo(f, k))
        if ch is not None and not merc:
            D2.draw_text(dv, (D2.INV_GOLD[0] - ox) * k, (D2.INV_GOLD[1] - oy) * k, D2.fmt_gold(ch.stat(14)), k,
                         anchor='w')
        cv = self.canvas
        cv.delete('all')
        gx, gy = D2.INV_GRID
        cv.create_image(0, 0, anchor='nw', image=D2.photo(
            a.panel('character-inventory'), (INV_W * c, INV_H * c),
            (gx, gy, gx + INV_W * D2.ART_CELL, gy + INV_H * D2.ART_CELL), tag='main'))
        if ch is None:
            return
        for e in ch.inventory():
            it = e.it
            w, h = self.size(it)
            x0, y0 = it['x'] * c, it['y'] * c
            self.draw_item_d2(cv, it, x0, y0, x0 + w * c, y0 + h * c, e is self.selected)

    def draw_item_d2(self, cv, it, x0, y0, x1, y1, sel, check_req=True):
        d, char = self.data, self.app.char
        try:
            unmet = check_req and char is not None and requirements_unmet(it, d, char)
        except Exception:
            unmet = False
        bg = D2.UNMET_BG if unmet else (D2.CELL_BG if self.sigma else D2.CHAR_CELL_BG)
        fill = blend(SELECTION, bg, 0.14) if sel else bg
        col = item_color(it, d)
        if unmet or sel:
            cv.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill=fill, outline=col if sel else '',
                                width=2 if sel else 0)
        imgs = self.icon(it, fill)
        if imgs:
            for kk in (1, 2, 3):
                if imgs.get(kk) is not None and kk in LAYERS_SHOWN:
                    cv.create_image((x0 + x1) / 2, (y0 + y1) / 2, image=imgs[kk])
        else:
            cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=clean(it['name']), fill=col,
                           width=max(20, x1 - x0 - 6), font=('Segoe UI', 8), justify='center')

    def wset_tab_at(self, x, y):
        """Weapon set (1 / 2) of the "I" / "II" tab under (x, y) of the D2 panel, or None."""
        if not self.d2 or not any(b in self.visible_boxes() for b in (4, 5)):
            return None
        k = self.k
        if self.sigma:
            ox, oy = self.org
            _a, _b, tw, th = D2.WSET_TAB
            for tx, ty in D2.WSET_TABS:
                tx, ty = tx - ox, ty - oy
                if tx * k <= x < (tx + tw) * k and ty * k <= y < (ty + th) * k:
                    return 1 if x < (tx + tw / 2) * k else 2
            return None
        tw, th = D2.WSET_TAB_D2
        for n, tabs in D2.WSET_TABS_D2.items():
            for tx, ty in tabs:
                if tx * k <= x < (tx + tw) * k and ty * k <= y < (ty + th) * k:
                    return n
        return None

    # ------------------------------------------------------------------ hit tests
    def doll_slot(self, x, y):
        c = self.cell
        for box in self.visible_boxes():
            bx, by, w, h = self.boxes[box]
            if bx * c <= x < (bx + w) * c and by * c <= y < (by + h) * c:
                return self.slot_of(box)
        return None

    def entry_at(self, cv, x, y):
        """(entry, merc list) under (x, y) of the doll or inventory canvas."""
        if self.ch is None:
            return None, False
        if cv is self.doll:
            slot = self.doll_slot(x, y)
            if slot is None:
                return None, False
            merc = self.is_merc()
            return self.ch.equipped(merc).get(slot), merc
        cx, cy = x // self.cell, y // self.cell
        for e in self.ch.inventory():
            w, h = self.size(e.it)
            if e.it['x'] <= cx < e.it['x'] + w and e.it['y'] <= cy < e.it['y'] + h:
                return e, False
        return None, False

    def char_target(self, x_root, y_root, it, dx, dy, ignore=None):
        """(where, dst_merc, error) of a drop on the doll or the inventory, or None when not over them."""
        p = None if self.over_inventory(x_root, y_root) else _local(self.doll, x_root, y_root)
        if p is not None:
            slot = self.doll_slot(*p)
            if slot is None:
                return None
            merc = self.is_merc()
            if self.ch is None:
                return ('slot', slot), merc, T('inv.err.no_char', 'choose a character first')
            return ('slot', slot), merc, self.ch.slot_error(it, slot, merc, ignore=ignore)
        p = _local(self.canvas, x_root, y_root)
        if p is None:
            return None
        x, y = p[0] // self.cell - dx, p[1] // self.cell - dy
        if self.ch is None:
            return ('inv', x, y), False, T('inv.err.no_char', 'choose a character first')
        return ('inv', x, y), False, self.ch.inventory_error(it, x, y, ignore=ignore)

    def stash_target(self, x_root, y_root, it, dx, dy):
        app = self.app
        p = _local(app.canvas, x_root, y_root)
        if p is None:
            return None
        x, y = p[0] // app.cell - dx, p[1] // app.cell - dy
        if not app.path:
            return x, y, T('inv.err.no_stash', 'open a stash first')
        return x, y, placement_error(app.items, it, app.page(), x, y, self.data)

    def over_inventory(self, x_root, y_root):
        return _local(self.canvas, x_root, y_root) is not None

    def over_doll(self, ev):
        return not self.over_inventory(ev.x_root, ev.y_root) and _local(self.doll, ev.x_root, ev.y_root) is not None

    def over_character(self, ev):
        return (_local(self.canvas, ev.x_root, ev.y_root) is not None
                or _local(self.doll, ev.x_root, ev.y_root) is not None)

    # ------------------------------------------------------------------ drop preview
    def _rect(self, cv, x0, y0, x1, y1, ok):
        cv.delete('depot')
        if x1 <= x0 or y1 <= y0:
            return
        rgba, outline = DROP_OK if ok else DROP_KO
        img = ImageTk.PhotoImage(Image.new('RGBA', (int(x1 - x0), int(y1 - y0)), rgba))
        self._imgs[str(cv)] = img
        cv.create_image(x0, y0, image=img, anchor='nw', tags=('depot',))
        cv.create_rectangle(x0, y0, x1, y1, outline=outline, width=1, tags=('depot',))

    def _grid_box(self, cv, cell, cols, rows, x, y, w, h, ok):
        self._rect(cv, max(x, 0) * cell, max(y, 0) * cell, min(x + w, cols) * cell, min(y + h, rows) * cell, ok)

    def clear_preview(self):
        for cv in (self.canvas, self.doll, self.app.canvas):
            cv.delete('depot')

    def preview_char(self, t, it):
        """Shows a drop on the doll / inventory; t from char_target."""
        where, merc, err = t
        c = self.cell
        self.app.canvas.delete('depot')
        if where[0] == 'slot':
            self.canvas.delete('depot')
            box = next((b for b in self.visible_boxes() if self.slot_of(b) == where[1]), None)
            if box is not None:
                x, y, w, h = self.boxes[box]
                self._rect(self.doll, x * c, y * c, (x + w) * c, (y + h) * c, err is None)
            dest = slot_name(where[1], T('inv.slot', 'slot')) + (T('ch.merc_suffix', ' (mercenary)') if merc else '')
        else:
            self.doll.delete('depot')
            w, h = self.size(it)
            self._grid_box(self.canvas, c, INV_W, INV_H, where[1], where[2], w, h, err is None)
            dest = T('inv.inv_at', 'inventory ({x}, {y})', x=where[1], y=where[2])
        self.app.status.configure(text=f'{clean(it["name"])} -> {dest}' if err is None else
                                  T('inv.cannot_drop', 'Cannot drop here: {error}', error=err))

    def _cancel_tab_hover(self):
        app = self.app
        th = getattr(app, 'tab_hover', None)
        if th:
            try:
                app.root.after_cancel(th[1])
            except Exception:
                pass
            app.tab_hover = None

    def show_detail(self):
        self.app.set_detail(None)                         # clears the collector's own edit widgets
        if self.selected is not None:
            self.panel.show(self.selected.it)

    def deselect(self):
        if self.selected is not None:
            self.selected = None
            self.redraw()

    def select_at(self, where, merc):
        if self.ch is None:
            self.selected = None
        elif where[0] == 'slot':
            self.selected = self.ch.equipped(merc).get(where[1])
        else:
            self.selected = next((e for e in self.ch.inventory() if (e.it['x'], e.it['y']) == where[1:]), None)
        self.sel_merc = merc
        self.redraw()
        self.show_detail()

    # ------------------------------------------------------------------ mouse on the character
    def on_motion(self, ev):
        if self.drag is not None:
            return
        e, merc = self.entry_at(ev.widget, ev.x, ev.y)
        if e is not None:
            if e.it['location'] == MC.LOC_EQUIPPED:
                where = slot_name(e.it['equipped'], T('inv.equipped', 'equipped')) + (T('ch.merc_suffix', ' (mercenary)') if merc else '')
            else:
                where = T('inv.inv_at', 'inventory ({x}, {y})', x=e.it['x'], y=e.it['y'])
            self.app.status.configure(text=f'{clean(e.it["name"])} - {where}')
        else:
            self.app.show_status()

    def on_press(self, ev):
        cv = ev.widget
        if cv is self.doll:
            ws = self.wset_tab_at(ev.x, ev.y)
            if ws is not None:
                self.drag = None
                self.wset.set(ws)
                self.redraw()
                return
        e, merc = self.entry_at(cv, ev.x, ev.y)
        app = self.app
        if app.selected is not None:
            app.selected = None
            app.draw_grid()
        self.selected, self.sel_merc = e, merc
        self.drag = None
        if e is not None:
            dx = dy = 0
            if cv is self.canvas:
                dx, dy = ev.x // self.cell - e.it['x'], ev.y // self.cell - e.it['y']
            self.drag = dict(entry=e, merc=merc, dx=dx, dy=dy, moved=False)
        self.redraw()
        self.show_detail()

    def on_menu(self, ev):
        """Right-click: selects the item under the pointer (as a left click does, without a drag) and opens its
        menu - the Character tab's own menu (mxl_rc_menu._char_menu), on an item, an empty inventory cell or
        an empty slot."""
        if self.ch is None or self.drag is not None:
            return
        import mxl_rc_menu
        mxl_rc_menu.inventory_menu(self, ev)

    def on_drag(self, ev):
        d = self.drag
        if not d:
            return
        d['moved'] = True
        ev.widget.configure(cursor='fleur')
        app = self.app
        it = d['entry'].it
        if app.watch_tab(ev) is not None:                 # over a stash page tab / view button
            self.clear_preview()
            return
        t = self.char_target(ev.x_root, ev.y_root, it, d['dx'], d['dy'], ignore=d['entry'])
        if t is not None:
            self.preview_char(t, it)
            return
        self.canvas.delete('depot')
        self.doll.delete('depot')
        t = self.stash_target(ev.x_root, ev.y_root, it, d['dx'], d['dy'])
        if t is not None:
            w, h = self.size(it)
            x, y, err = t
            self._grid_box(app.canvas, app.cell, STASH_COLS, STASH_ROWS, x, y, w, h, err is None)
            app.status.configure(text=T('inv.to_stash_at', '{item} -> stash page {page} ({x}, {y})', item=clean(it['name']),
                                        page=app.page() + 1, x=x, y=y) if err is None
                                 else T('inv.cannot_drop', 'Cannot drop here: {error}', error=err))
        else:
            app.canvas.delete('depot')

    def on_release(self, ev):
        ev.widget.configure(cursor='')
        self._cancel_tab_hover()
        self.clear_preview()
        d, self.drag = self.drag, None
        if not d or not d['moved']:
            return
        e = d['entry']
        it = e.it
        t = self.char_target(ev.x_root, ev.y_root, it, d['dx'], d['dy'], ignore=e)
        if t is not None:
            where, merc, err = t
            if err:
                self.app.status.configure(text=T('inv.cannot_move', 'Cannot move: {error}', error=err))
                return
            cur = (('slot', it['equipped']) if it['location'] == MC.LOC_EQUIPPED else ('inv', it['x'], it['y']))
            if cur == where and merc == d['merc']:
                return
            self.move_in_character(e, d['merc'], where, merc)
            return
        t = self.stash_target(ev.x_root, ev.y_root, it, d['dx'], d['dy'])
        if t is not None:
            x, y, err = t
            if err:
                self.app.status.configure(text=T('inv.cannot_drop', 'Cannot drop here: {error}', error=err))
                return
            self.to_stash(e, d['merc'], self.app.page(), x, y)
            return
        self.refresh()                                    # a reload postponed during the drag

    # ------------------------------------------------------------------ writes
    def _check_char(self):
        """The character file must not have changed since it was read (game, other window...)."""
        if self.ch is None:
            raise CharError(T('inv.err.no_char', 'choose a character first'))
        if read_file(self.ch.path) != self.ch.raw:
            raise CharError(T('inv.err.changed', 'the character file changed on disk: it has been reloaded, try again'))

    def _save_char(self):
        app = self.app
        bak = self.ch.save(backup=app.needs_backup(self.ch.path))
        app.backup_made(self.ch.path, bak)
        self.sig = _sig(self.ch.path)
        return bak

    def _confirm_equip(self, it, where, merc):
        if where[0] != 'slot' or merc or self.app.char is None:
            return True
        try:
            unmet = requirements_unmet(it, self.data, self.app.char)
        except Exception:
            unmet = False
        if not unmet:
            return True
        return messagebox.askyesno(T('ch.equip', 'Equip'), T('ch.equip_ask', 'The character does not meet the requirements '
                                   'of this item: it will be inactive until he does. Equip anyway?'), parent=self.app.root)

    def _done(self, msg, baks, select_stash=None, select_char=None):
        app = self.app
        if app.path:
            app.load(app.path, keep_selection=False)
        if select_stash is not None:
            page, x, y = select_stash
            app.selected = next((i for i in app.items if (i['page'], i['x'], i['y']) == (page, x, y)), None)
            app.draw_grid()
            app.set_detail(app.selected)
        merc_view = self.merc.get()
        self.refresh(force=True)
        self.merc.set(merc_view and self.ch is not None and self.ch.merc_hired)
        if select_char is not None:
            self.select_at(*select_char)
        else:
            self.redraw()
            if select_stash is None:
                self.show_detail()
        self._sync_char_tab()
        baks = [os.path.basename(b) for b in baks if b]
        app.status.configure(text=msg + (T('cr.backup', ' - backup: {file}', file=', '.join(baks)) if baks else ''))

    def _sync_char_tab(self):
        """After a write from this panel: a Character tab open on the same character reads the file again, so it
        shows the new items and its next save starts from them. (The other way round its save reloads the stash,
        whose redraw calls refresh() here.) Edits pending on the tab's pages stay pending on top of the new file
        (CharacterWindow.sync_file): they are neither dropped nor saved over the items written here."""
        try:
            import mxl_tabs
            w = mxl_tabs.built_owner('Character')
            wch = getattr(w, 'ch', None)
            if wch is None or self.ch is None or os.path.abspath(wch.path) != os.path.abspath(self.ch.path):
                return
            w.sync_file()
        except Exception as e:
            print('character tab not refreshed:', e)

    def _error(self, title, err):
        messagebox.showerror(title, str(err), parent=self.app.root)
        self.reload()
        if self.app.path:
            self.app.load(self.app.path, keep_selection=True)

    @staticmethod
    def _dest(where, merc):
        if where[0] == 'slot':
            return slot_name(where[1], T('inv.slot', 'slot')) + (T('inv.of_merc', ' of the mercenary') if merc else '')
        return T('inv.inv_at', 'inventory ({x}, {y})', x=where[1], y=where[2])

    def move_in_character(self, e, src_merc, where, dst_merc):
        name = clean(e.it['name'])
        if not self._confirm_equip(e.it, where, dst_merc):
            return
        try:
            self._check_char()
            if src_merc == dst_merc:
                self.ch.move(e, where, dst_merc)
            else:
                self.ch.remove(e, src_merc)
                self.ch.place(e.blob, where, dst_merc)
            bak = self._save_char()
        except ERRORS as err:
            self._error(T('inv.move', 'Move'), err)
            return
        self.selected = None
        self._done(T('inv.moved_to', '{item} moved to {dest}', item=name, dest=self._dest(where, dst_merc)), [bak],
                   select_char=(where, dst_merc))

    def edit(self):
        """Edit the selected item of the character / mercenary / inventory where it is (the main window's Edit
        item button and the panel's right-click menu): the Item Editor writes the result back through the
        character editor's remove -> place -> save flow, like the Character window's own Edit."""
        from mxl_creator_gui import CreatorWindow
        e, merc = self.selected, self.sel_merc
        if e is None or self.ch is None:
            self.app.status.configure(text=T('ch.select_first', 'Select an item of the character first.'))
            return
        where = ('slot', e.it['equipped']) if e.it['location'] == MC.LOC_EQUIPPED else ('inv', e.it['x'], e.it['y'])
        old, name = bytes(e.blob), clean(e.it['name'])

        def write(blob):
            self._check_char()
            # the panel reloads the character whenever its file changes: the item is looked up again
            # (same bytes, same place) instead of trusting the entry the editor was opened with
            cur = (self.ch.equipped(merc).get(where[1]) if where[0] == 'slot' else
                   next((x for x in self.ch.inventory() if (x.it['x'], x.it['y']) == where[1:]), None))
            if cur is None or bytes(cur.blob) != old:
                raise CharError(T('inv.err.item_gone', 'the item is no longer where it was: select it again'))
            try:
                self.ch.remove(cur, merc)
                try:
                    self.ch.place(blob, where, merc)
                except CharError:
                    new = mxl_save.blob_item(blob, self.data)
                    if where[0] == 'slot':
                        if new['code'] != e.it['code']:
                            raise
                        # same base in the slot the game itself put it in (Sigma mercenaries wear amulets,
                        # rings... that the slot rules here do not know): it goes back there as it was
                        ent = MC.Entry(new, blob)
                        ent.blob = ent.moved(self.data, location=MC.LOC_EQUIPPED, equipped=where[1], x=where[1],
                                             y=0, panel=0)
                        ent.it = mxl_save.blob_item(ent.blob, self.data)
                        self.ch.entries(merc).append(ent)
                    else:
                        spot = self.ch.free_inventory_spot(new)
                        if spot is None:                  # grew (other base): no room where it was nor elsewhere
                            raise
                        self.ch.place(blob, ('inv',) + spot, merc)
                bak = self._save_char()
            except Exception:
                self.reload()                             # nothing written: the character as it is on disk
                raise
            self.selected = None
            msg = T('ch.item_replaced', '{name}: item replaced', name=self.ch.name)
            self._done(msg, [bak])
            return msg
        CreatorWindow(self.app, edit_item=e.it, target=write, target_label=f'{self.ch.name}')

    def to_stash(self, e, src_merc, page, x, y):
        """Character (inventory or slot) -> stash page shown in the main window, at (x, y)."""
        app = self.app
        name = clean(e.it['name'])
        path = app.path
        try:
            self._check_char()
            blob = self.ch.stash_blob(e)
            before = read_file(path)
            items = parse_stash(path, self.data)
            new = mxl_save.blob_item(blob, self.data)
            new['page'] = page
            err = placement_error(items, new, page, x, y, self.data)
            if err:
                raise EditError(err)
            bak_s = edit_stash(path, self.data, insert=[(page, x, y, blob)], backup=app.needs_backup(path))
            app.backup_made(path, bak_s)
        except ERRORS as err:
            self._error(T('ch.btn.to_stash', 'To stash'), err)
            return
        try:
            self.ch.remove(e, src_merc)
            bak_c = self._save_char()
        except ERRORS as err:
            try:                                          # character not written: stash back as it was
                commit_file(path, before, lambda tmp: None, backup=False)
            except Exception:
                pass
            self._error(T('ch.btn.to_stash', 'To stash'), err)
            return
        self.selected = None
        self._done(T('inv.moved_stash', '{item} moved to {file}, page {page} ({x}, {y})', item=name, file=os.path.basename(path),
                     page=page + 1, x=x, y=y), [bak_s, bak_c],
                   select_stash=(page, x, y))

    def drop_from_stash(self, d, ev):
        """Stash item dragged from the main grid and released over the inventory or an equipment slot."""
        app = self.app
        it, src = d['item'], d['path']
        dx, dy = d['dx'], d['dy']
        if self.over_doll(ev):
            dx = dy = 0
        t = self.char_target(ev.x_root, ev.y_root, it, dx, dy)
        if t is None:
            return
        where, merc, err = t
        if err:
            app.status.configure(text=T('inv.cannot_drop', 'Cannot drop here: {error}', error=err))
            return
        if not self._confirm_equip(it, where, merc):
            return
        name = clean(app.full_name(it))
        try:
            self._check_char()
            items = parse_stash(src, self.data)
            cur = next((i for i in items if i['_offset'] == it['_offset'] and i['code'] == it['code']), None)
            if cur is None:
                raise EditError(T('inv.err.stash_changed', 'the stash changed on disk since it was read: try again'))
            blob = item_blob(read_file(src), cur)
            before_char = self.ch.raw
            self.ch.place(blob, where, merc)
            bak_c = self._save_char()
        except ERRORS as err:
            self._error(T('inv.to_char', 'To character'), err)
            return
        try:
            bak_s = edit_stash(src, self.data, remove=[cur['_offset']], backup=app.needs_backup(src))
            app.backup_made(src, bak_s)
        except ERRORS as err:
            try:                                          # stash not written: character back as it was
                commit_file(self.ch.path, before_char, lambda tmp: None, backup=False)
            except Exception:
                pass
            self._error(T('inv.to_char', 'To character'), err)
            return
        app.selected = None
        self._done(T('inv.moved_char', '{item} moved to the {dest} of {name}', item=name, dest=self._dest(where, merc),
                     name=self.ch.name), [bak_c, bak_s],
                   select_char=(where, merc))


# ---------------------------------------------------------------------------------------- right-click adapter

class PanelWin:
    """The main window's panel seen as the 'win' that mxl_rc_menu's character functions (_char_menu, _char_hot,
    _mutate_char, mxl_perfect, mxl_he_stats...) were written for, i.e. the Character tab's CharacterWindow.

    One is made per right-click / shortcut (and kept by an Item stats tab). It is tied to the Character object
    the panel showed at that moment: the panel reads the file again whenever it changes, and an entry of an older
    read must never be written - save() then refuses instead. Whether the item is the mercenary's is decided by
    where the pointer was (entry_at), not by the Character / Mercenary buttons later on."""
    merc_inventory = True                 # the inventory stays reachable while the mercenary's gear is shown

    def __init__(self, panel):
        self.panel = panel
        self.app, self.data = panel.app, panel.data
        self.doll, self.inv = panel.doll, panel.canvas
        self.top = panel.app.root
        self.sel_slot = None
        self._ch = panel.ch
        self._merc = bool(panel.sel_merc) if panel.selected is not None else False
        self._sel = None
        self._where = None
        self._cell = None

    # ---- what the panel shows
    ch = property(lambda self: self._ch)
    cell = property(lambda self: self.panel.cell)

    def current(self):
        return self._ch is not None and self.panel.ch is self._ch

    def is_merc(self):
        return self._merc

    def entry_at(self, cv, ev):
        """(entry, slot) like CharacterWindow.entry_at: slot is set for an equipment box, even an empty one."""
        p = self.panel
        self._cell = None
        if self._ch is None:
            return None, None
        if cv is p.doll:
            slot = p.doll_slot(ev.x, ev.y)
            if slot is None:
                return None, None
            self._merc = p.is_merc()
            return self._ch.equipped(self._merc).get(slot), slot
        self._merc = False
        cx, cy = ev.x // p.cell, ev.y // p.cell
        if 0 <= cx < INV_W and 0 <= cy < INV_H:
            self._cell = (cx, cy)
        return p.entry_at(cv, ev.x, ev.y)[0], None

    @property
    def selected(self):
        return self._sel

    @selected.setter
    def selected(self, e):
        self._sel = e
        if e is not None:
            self._where = (('slot', e.it['equipped']) if e.it['location'] == MC.LOC_EQUIPPED
                           else ('inv', e.it['x'], e.it['y']))
        if self.current():
            p = self.panel
            p.selected, p.sel_merc, p.drag = e, self._merc, None

    def redraw(self):
        if self.current():
            self.panel.redraw()
            self.panel.show_detail()

    def set_status(self, text, error=False):
        try:
            self.app.status.configure(text=text)
        except Exception:
            pass

    def _stale(self):
        if self.current():
            return False
        self.set_status(T('inv.err.reloaded', 'the character was read again since this item was picked: '
                          'nothing written, pick the item again'), True)
        return True

    # ---- reading / writing
    def reload(self):
        self.panel.reload()
        self._ch, self._sel = self.panel.ch, None

    def save(self, msg):
        """Writes the character (changed in memory by the caller) through the panel's writer; False when nothing
        was written. The item standing where the picked one stood is selected again."""
        p = self.panel
        if self._stale():
            return False
        try:
            bak = p._save_char()
        except ERRORS as err:
            p._error(T('ch.title', 'Character'), err)
            self._ch, self._sel = p.ch, None
            return False
        p.selected = None
        p._done(msg, [bak], select_char=(self._where, self._merc) if self._where is not None else None)
        self._ch, self._sel = p.ch, p.selected
        return True

    # ---- the menu's own actions
    def edit(self):
        self.panel.edit()

    def delete(self):
        e = self._sel
        if e is None:
            self.set_status(T('ch.select_first', 'Select an item of the character first.'), True)
            return
        if not messagebox.askyesno(T('ch.btn.delete', 'Delete'), T('ch.delete_ask', 'Delete {item} (and its socketed '
                                   'items) from {name}?\nA backup of the character is made first.',
                                   item=clean(e.it['name']), name=self._ch.name), parent=self.top):
            return
        self.delete_instant(e)

    def delete_instant(self, e):
        """No prompt (the Delete key at the pointer), like CharacterWindow.delete_instant."""
        if self._stale():
            return
        name = clean(e.it['name'])
        try:
            self._ch.remove(e, self._merc)
        except ValueError:
            self.reload()
            self.set_status(T('inv.err.item_gone', 'the item is no longer where it was: select it again'), True)
            return
        self._where = None
        self.save(T('cr.deleted', '{name} deleted', name=name))

    def to_stash(self):
        """First free place of the stash, the shown page first (as the Character tab's To stash)."""
        app, e, p = self.app, self._sel, self.panel
        if e is None:
            self.set_status(T('ch.select_first', 'Select an item of the character first.'), True)
            return
        if not app.path:
            self.set_status(T('cr.open_stash', 'Open a stash in the main window first.'), True)
            return
        if self._stale():
            return
        try:
            new = mxl_save.blob_item(self._ch.stash_blob(e), self.data)
            pages = [app.page()] + [i for i in range(mxl_save.STASH_PAGES) if i != app.page()]
            spot = mxl_save.free_spot(parse_stash(app.path, self.data), new, self.data, pages)
        except ERRORS as err:
            self.set_status(str(err), True)
            return
        if spot is None:
            self.set_status(T('ch.err.stash_full', 'no free place in the stash'), True)
            return
        p.to_stash(e, self._merc, spot[0], spot[1], spot[2])
        self._ch, self._sel = p.ch, None

    def create_here(self):
        """Item Creator writing into the empty slot / inventory cell that was clicked (the first free place of
        the inventory when the new item does not fit there)."""
        from mxl_creator_gui import CreatorWindow
        p, slot, cell, merc = self.panel, self.sel_slot, self._cell, self._merc

        def write(blob):
            p._check_char()
            ch = p.ch                                     # the creator stays open: the character as it is now
            m = bool(merc and ch.merc_hired)
            new = mxl_save.blob_item(blob, self.data)
            if slot is not None and ch.equipped(m).get(slot) is None:
                where = ('slot', slot)
            else:
                m = False
                if cell is not None and not ch.inventory_error(new, cell[0], cell[1]):
                    where = ('inv',) + cell
                else:
                    spot = ch.free_inventory_spot(new)
                    if spot is None:
                        raise CharError(T('ch.err.inv_full', 'no free place in the inventory'))
                    where = ('inv',) + spot
            try:
                ch.place(blob, where, m)
                bak = p._save_char()
            except Exception:
                p.reload()                                # nothing written: the character as it is on disk
                raise
            msg = T('ch.created_in', '{name}: item created in {where}', name=ch.name,
                    where=slot_name(where[1]) if where[0] == 'slot' else T('ch.the_inventory', 'the inventory'))
            p.selected = None
            p._done(msg, [bak], select_char=(where, m))
            return msg
        label = (f"{self._ch.name}{T('ch.merc_suffix', ' (mercenary)') if merc and slot is not None else ''} - "
                 + (slot_name(slot, T('ch.inventory_l', 'inventory')) if slot else T('ch.inventory_l', 'inventory')))
        CreatorWindow(self.app, target=write, target_label=label)


# ---------------------------------------------------------------------------------------- main window hooks

def install(App):
    o_build, o_draw, o_click, o_drag, o_release = App._build, App.draw_grid, App.on_click, App.on_drag, App.on_release

    def _build(self):
        o_build(self)
        self.inventory = None
        try:
            self.inventory = MainInventory(self)
        except Exception as e:                            # never block the collector itself
            print('inventory panel disabled:', e)

    def draw_grid(self):
        o_draw(self)
        inv = getattr(self, 'inventory', None)
        if inv is not None:
            inv.refresh()

    def on_click(self, ev):
        inv = getattr(self, 'inventory', None)
        if inv is not None:
            inv.deselect()
        o_click(self, ev)

    def on_drag(self, ev):
        inv = getattr(self, 'inventory', None)
        if inv is not None and self.drag and inv.over_character(ev):
            inv._cancel_tab_hover()
            self.canvas.delete('depot')
            self.drag['target'] = None
            d = self.drag
            over_doll = inv.over_doll(ev)
            t = inv.char_target(ev.x_root, ev.y_root, d['item'], 0 if over_doll else d['dx'], 0 if over_doll else d['dy'])
            if t is not None:
                inv.preview_char(t, d['item'])
            else:
                inv.clear_preview()
            return
        if inv is not None:
            inv.canvas.delete('depot')
            inv.doll.delete('depot')
        o_drag(self, ev)

    def on_release(self, ev):
        inv = getattr(self, 'inventory', None)
        if inv is not None:
            inv.canvas.delete('depot')
            inv.doll.delete('depot')
            if self.drag and self.drag.get('item') is not None and inv.over_character(ev):
                d, self.drag = self.drag, None
                inv._cancel_tab_hover()
                self.canvas.delete('depot')
                inv.drop_from_stash(d, ev)
                return
        o_release(self, ev)

    App._build = _build
    App.draw_grid = draw_grid
    App.on_click = on_click
    App.on_drag = on_drag
    App.on_release = on_release
