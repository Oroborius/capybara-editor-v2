"""Character window of the MXL Item Collector: equipment (character and mercenary, weapon sets I / II), inventory,
and progress (level, quests, waypoints, copy of the character).

Items can be dragged between the equipment slots and the inventory, sent to / taken from the stash shown in the
main window, edited or created directly in a slot with the Item Creator. Every save goes through
mxl_char.Character.save (game closed, verification, backup)."""
import os
import struct
import tkinter as tk
from tkinter import ttk, messagebox

import mxl_save
from mxl_save import parse_stash, free_spot, edit_stash, item_blob, read_file, commit_file, EditError, STASH_PAGES
from mxl_format import FormatError
from mxl_gui_detail import setup_detail_tags, item_color, LAYERS_SHOWN
from mxl_tooltip import requirements_unmet
from mxl_theme import BG, GRID_LINE, EMPTY, CELL_OK, CELL_KO, SELECTION, blend
import mxl_char as MC
from mxl_char import Character, CharError, SLOT_NAMES, MERC_SLOTS, INV_W, INV_H, WAYPOINTS, DIFFICULTIES
from mxl_char import slot_name, difficulty_name
from mxl_lang import T
from mxl_creator_gui import CreatorWindow, PreviewPanel, PreviewHost, clean, clamp_window
from mxl_statscreen import StatEditMixin

# the Skills tab's game-like look: near-black stone, the icons and colours of the game itself
SK_BG = '#0b0a08'
SK_CELL = '#151310'
SK_PLATE = '#171208'                 # the tree plates of the vertical tab bar
SK_EDGE = '#4a3f26'                  # gold-ish stone highlight (selected plate / node frames)
SK_OFF = '#241d10'                   # dim stone (unselected plate)
SK_NODE = '#3a2c12'                  # the dim frame around a skill node
SK_STONE = '#141008'                 # the character screen's section boxes
SK_CELL_W, SK_CELL_H = 118, 116      # the game web's own pitch (its 3 columns span 360px, rows ~117)
PAD = 22                         # the web's own inset: the art starts inside the panel
HE_GOLD_RGB = (216, 194, 122)        # HE_GOLD as an RGB triple for the game-font renderer
_SKILL_ICON_CACHE = {}               # (data folder, class) -> {sid: PhotoImage}

# paperdoll: slot -> (x, y, w, h) in cells; weapon set II uses the same boxes as set I
DOLL = {1: (4.5, 0, 2, 2), 2: (7, 1, 1, 1), 3: (4.5, 2.5, 2, 3), 8: (4.5, 6, 2, 1),
        4: (0.5, 0.75, 2, 4), 5: (8.5, 0.75, 2, 4), 6: (3, 5, 1, 1), 7: (7, 5, 1, 1),
        10: (0.5, 5.25, 2, 2), 9: (8.5, 5.25, 2, 2)}
SET2 = {4: 11, 5: 12}
DOLL_W, DOLL_H = 11, 7.5


# ---- extra pages (plug-ins) -------------------------------------------------------------------------------
# Other modules add a page to the Character window without editing this file:
#     import mxl_char_gui; mxl_char_gui.register_page('merc', 'Mercenary', factory)
# factory(win, frame) builds its widgets into frame (a tk.Frame of the window's body) and returns an object
# that may have any of these methods (all optional):
#     refresh()      the character was loaded / saved, or RELOAD was pressed: show win.ch again, forget pending edits
#     rebase()       win.ch was written or read again WITHOUT the page's pending edits (an item was moved / edited
#                    on the Inventory page or from the Stash tab, an item action failed and the file was read
#                    again, a save was refused): keep the pending edits, take win.ch as the new "file" state.
#                    Called only while dirty() is true; a page without rebase() is left untouched then (it must
#                    read win.ch when it applies, not keep a Character of its own). Not dirty: refresh() is called.
#     dirty()        True while the page holds edits not yet written to win.ch
#     apply()        write the pending edits into win.ch (called by SAVE just before the file is written;
#                    raise mxl_char.CharError to refuse: nothing is saved then)
#     set_theme(dark)
# A page asks for the unsaved-changes line with win.update_dirty(). win.ch is the Character, win.data the game
# data, win.app the main window, win.set_status(text, error=False) the status line.
EXTRA_PAGES = []


def register_page(key, title, factory):
    """Adds (or replaces) an extra page; call it before the Character window is built (at install time)."""
    EXTRA_PAGES[:] = [p for p in EXTRA_PAGES if p[0] != key] + [(key, title, factory)]


class CharacterWindow(StatEditMixin):
    def __init__(self, app, tab='stats'):
        self.app = app
        self.data = app.data
        path = app.character_file()
        if not path or not os.path.exists(path):
            messagebox.showinfo(T('ch.title', 'Character'), T('ch.choose_first', 'Choose a character in the main window first.'))
            return
        try:
            self.ch = Character(path, self.data)
        except (FormatError, CharError, OSError, KeyError) as e:
            messagebox.showerror(T('ch.title', 'Character'), f'{path}\n\n{e}')
            return
        self.merc = tk.BooleanVar(value=False)
        self.wset = tk.IntVar(value=1)
        self.selected = None          # Entry
        self.sel_slot = None          # slot number of the selected box (even when empty)
        self.drag = None
        self.icons = {}
        import mxl_tabs
        old = mxl_tabs.built_owner('Character')
        if old is not None:
            same = getattr(old, 'ch', None) is not None and \
                os.path.abspath(old.ch.path) == os.path.abspath(self.ch.path)
            try:
                dirty = old.dirty()
            except Exception:
                dirty = False
            if same or dirty:
                mxl_tabs.focus_existing('Character')
                return          # this character (or its unsaved edits) is already showing: just focus it
            # a different character was picked in the dropdown: rebuild the tab with the new data
            self.top = mxl_tabs.host_window(app, 'Character', owner=self, replace=True)
        else:
            self.top = mxl_tabs.host_window(app, 'Character', owner=self)
        self.top.title(f'Median XL Capybara Editor V2 - {self.ch.name}')
        self.top.geometry('1180x930')
        self.top.configure(bg=HE_BG)
        self.top.after_idle(lambda: clamp_window(self.top, size=(1180, 930)))
        try:
            import mxl_he_art
            import sys
            if sys.platform == 'win32':
                import mxl_app_icon
                self.top.wm_iconbitmap(mxl_app_icon.ico_path('hero_editor.ico', mxl_he_art.ICO_FILE))
            self._icon = tk.PhotoImage(master=self.top, data=mxl_he_art.ICON)
            self.top.iconphoto(False, self._icon)
        except Exception:
            pass
        self.cell = app.cell
        self.icons = {}
        self._fit_job = None
        # tab row and stone buttons at the bottom, like the Hero Editor
        bottom = tk.Frame(self.top, bg='#000000')
        bottom.pack(side='bottom', fill='x')
        tabbar = tk.Frame(bottom, bg='#000000')
        tabbar.pack(side='top', fill='x')
        actions = tk.Frame(bottom, bg='#000000')
        actions.pack(side='top', fill='x', padx=4, pady=(1, 2))
        StoneButton(actions, 'SAVE', self.save_progress).pack(side='left', padx=(0, 6))
        StoneButton(actions, 'RELOAD', self.discard).pack(side='left', padx=(0, 6))
        StoneButton(actions, 'CLOSE', self.close).pack(side='right')
        # packed before the credit line: in a narrow window the credit is what gets cut, not the status
        self.bar_status = tk.Label(actions, text='', font=HE_FONT, bg='#000000', fg=HE_GOLD, anchor='w')
        self.bar_status.pack(side='left', fill='x', expand=True, padx=6)
        tk.Label(actions, text=T('ch.glory', 'Glory to the real Heroes ZonFire99 and Mastadex'), font=('Times New Roman', 12, 'italic'),
                 bg='#000000', fg=HE_GOLD).pack(side='right', padx=8)
        self.top.protocol('WM_DELETE_WINDOW', self.close)
        import mxl_scroll                            # the pages scroll when the window is smaller than they are
        self.scroll = mxl_scroll.Scrolled(self.top, bg=HE_BG)
        self.scroll.pack(fill='both', expand=True, padx=2, pady=(2, 0))
        body = self.scroll.inner
        self.body = body
        self.scroll.bind('<Configure>', self._fit_later, add='+')
        self.st_tab = tk.Frame(body, bg=HE_BG)
        self.eq_tab = ttk.Frame(body, padding=3)
        self.sk_tab = tk.Frame(body, bg=HE_BG)
        self.wp_tab = tk.Frame(body, bg=HE_BG)
        self.q_tab = tk.Frame(body, bg=HE_BG)
        self.pages = {'stats': self.st_tab, 'inventory': self.eq_tab, 'skills': self.sk_tab,
                      'waypoints': self.wp_tab, 'quests': self.q_tab}
        self.tab = tk.StringVar(value='stats')
        self.tab_buttons = []
        self.extra = {}                              # key -> the object a registered page's factory returned
        self._extra_frames = {}
        extra_pages = [page for page in EXTRA_PAGES if not (self.ch.early and page[0] == 'hotkeys')]
        for key, _title, _factory in extra_pages:
            self._extra_frames[key] = self.pages[key] = tk.Frame(body, bg=HE_BG)
        for key, text in (('stats', T('ch.tab.stats', 'Stats')), ('inventory', T('ch.tab.inventory', 'Inventory')),
                          ('skills', T('ch.tab.skills', 'Skills')),
                          ('waypoints', T('ch.tab.waypoints', 'Waypoints')), ('quests', T('ch.tab.quests', 'Quests')),
                          *((k, t) for k, t, _f in extra_pages)):
            rb = tk.Radiobutton(tabbar, text=text, value=key, variable=self.tab, indicatoron=0, font=('Times New Roman', 12),
                                underline=0, bd=1, relief='raised', padx=6, pady=0, bg='#e8e8e8', selectcolor='#ffffff',
                                activebackground='#ffffff', command=self.show_tab)
            rb.pack(side='left', padx=(2 if key == 'stats' else 0, 0), pady=(0, 1))
            self.tab_buttons.append(rb)
            ch0 = text[:1].lower()
            if ch0.isascii() and ch0.isalpha():              # Alt + first letter (a translated label may not have one)
                try:
                    self.top.bind(f'<Alt-{ch0}>', lambda e, k=key: (self.tab.set(k), self.show_tab()))
                except tk.TclError:
                    pass
        try:                                  # one look for the whole editor: the global theme decides
            import mxl_d2_theme
            dark = bool(mxl_d2_theme.dark())
        except Exception:
            dark = False
        self.dark = tk.BooleanVar(value=dark)
        self.scroll.bind('<Configure>', self._fit_stats, add='+')
        self._build_skills()
        self._build_equipment()
        self._build_progress()
        for key, _title, factory in extra_pages:     # after the built-in pages: win.ch and the state exist
            try:
                self.extra[key] = factory(self, self._extra_frames[key])
            except Exception as e:                   # a broken plug-in page never keeps the window from opening
                print(f'character page {key!r} disabled:', e)
                tk.Label(self._extra_frames[key], text=str(e), bg=HE_BG).pack(padx=8, pady=8)
        self.apply_theme(save=False)
        self.tab.set({'equipment': 'inventory', 'progress': 'stats'}.get(tab, tab))
        self.show_tab()
        self.redraw()

    def close(self):
        if self.dirty():
            ans = messagebox.askyesnocancel(T('ch.close', 'Close'), T('ch.save_before_close', 'Save the changes before closing?'),
                                            parent=self.top)
            if ans is None:
                return
            if ans:
                self.save_progress()
                if self.dirty():
                    return
        self.top.destroy()

    def apply_theme(self, save=True):
        """Light (Hero Editor grey) or dark colours for the Stats, Inventory, Waypoints and Quests tabs."""
        dark = bool(self.dark.get())
        t = THEMES[dark]

        def walk(w):
            cls = w.winfo_class()
            try:
                if cls in ('Frame', 'Toplevel'):
                    w.configure(bg=t['bg'])
                elif cls == 'Labelframe':
                    w.configure(bg=t['bg'], fg=t['frame_fg'])
                elif cls == 'Label':
                    w.configure(bg=t['bg'], fg=t['fg'])
                elif cls in ('Checkbutton', 'Radiobutton'):
                    w.configure(bg=t['bg'], fg=t['fg'], activebackground=t['bg'], activeforeground=t['fg'],
                                disabledforeground=t['fg'], selectcolor=t['entry'])
                elif cls == 'Button':
                    w.configure(bg=t['btn'], fg=t['fg'], activebackground=t['btn'], activeforeground=t['fg'])
                elif cls == 'Entry':
                    w.configure(bg=t['entry'], fg=t['entry_fg'], readonlybackground=t['entry'],
                                insertbackground=t['entry_fg'])
            except tk.TclError:
                pass
            for c in w.winfo_children():
                walk(c)
        self.top.configure(bg=t['bg'])
        self.body.configure(bg=t['bg'])
        self.scroll.set_bg(t['bg'])
        for page in (self.st_tab, self.wp_tab, self.q_tab):
            walk(page)
        for tree in self.wp_trees + self.q_trees:
            tree.set_theme(dark)
        self._extra_call('set_theme', dark)
        for rb in self.tab_buttons:
            rb.configure(bg=t['tab'], fg=t['tab_fg'], selectcolor=t['tab_sel'], activebackground=t['tab_sel'],
                         activeforeground=t['tab_fg'])
        # Inventory tab: drawn with the collector's own dark theme (dark in both modes)

    def show_tab(self):
        for key, page in self.pages.items():
            if key == self.tab.get():
                page.pack(fill='both', expand=True)
            else:
                page.pack_forget()
        self._fit_stats()
        self._fit_skills()
        self.scroll.refresh()
        self._scroll_later()

    # ================================================================== equipment tab
    def _build_equipment(self):
        f = self.eq_tab
        left = ttk.Frame(f)
        left.pack(side='left', fill='y')
        row = ttk.Frame(left)
        row.pack(fill='x', pady=(0, 2))
        for text, val in ((T('ch.character', 'Character'), False), (T('ch.mercenary', 'Mercenary'), True)):
            b = ttk.Radiobutton(row, text=text, value=val, variable=self.merc, command=self.on_view)
            b.pack(side='left', padx=2)
            if val:
                self.merc_rb = b                     # enabled while a mercenary is hired (see redraw)
        ttk.Label(row, text='   ' + T('ch.weapon_set', 'Weapon set')).pack(side='left')
        self.wset_rbs = []              # disabled on the mercenary view: he has one weapon set (see slot_of)
        for n in (1, 2):
            rb = ttk.Radiobutton(row, text='I' if n == 1 else 'II', value=n, variable=self.wset, command=self.redraw)
            rb.pack(side='left', padx=2)
            self.wset_rbs.append(rb)
        c = self.cell
        self.doll = tk.Canvas(left, width=int(DOLL_W * c) + 1, height=int(DOLL_H * c) + 1, bg=BG, highlightthickness=0)
        self.doll.pack(anchor='w')
        self.inv_label = ttk.Label(left, text=T('ch.tab.inventory', 'Inventory'))
        self.inv_label.pack(anchor='w', pady=(3, 1))
        self.inv = tk.Canvas(left, width=INV_W * c + 1, height=INV_H * c + 1, bg=BG, highlightthickness=0)
        self.inv.pack(anchor='w')
        for cv in (self.doll, self.inv):
            cv.bind('<Button-1>', self.on_press)
            cv.bind('<B1-Motion>', self.on_drag)
            cv.bind('<ButtonRelease-1>', self.on_release)
            cv.bind('<Double-Button-1>', self.on_double)
        # window-level binding: the tab-hosted page forwards it to the root window, so Del works
        # wherever the focus is; the handler only acts when the pointer is over these canvases
        self.top.bind('<Delete>', self.on_delete_key, add='+')
        btns = ttk.Frame(left)
        btns.pack(fill='x', pady=(3, 0))
        for text, cmd in ((T('ch.btn.to_stash', 'To stash'), self.to_stash), (T('ch.btn.from_stash', 'From stash'), self.from_stash),
                          (T('ch.btn.edit', 'Edit...'), self.edit), (T('ch.btn.create_here', 'Create here...'), self.create_here),
                          (T('ch.btn.delete', 'Delete'), self.delete)):
            ttk.Button(btns, text=text, command=cmd).pack(side='left', padx=1)
        self.status = ttk.Label(left, text=T('ch.inv_hint', 'Drag items between the slots and the inventory. '
                                             '"From stash" takes the item selected in the main window.'),
                                wraplength=max(260, INV_W * c), justify='left')
        self.status.pack(anchor='w', pady=(2, 0))
        if getattr(self.ch, 'old', False):           # a 1.09 save: said up front
            import mxl_char
            self.set_status(mxl_char.old_save_note(self.ch.version))
        right = ttk.Frame(f)
        right.pack(side='left', fill='both', expand=True, padx=(4, 0))
        d = self.app.detail
        self.preview = tk.Text(right, width=16, wrap='word', bg=d.cget('bg'), fg=d.cget('fg'), bd=0,
                               padx=int(str(d.cget('padx'))), pady=8, font=d.cget('font'), cursor='arrow',
                               highlightthickness=0)
        sb = ttk.Scrollbar(right, orient='vertical', command=self.preview.yview)
        self.preview.configure(yscrollcommand=sb.set)
        self.preview.pack(side='left', fill='both', expand=True)
        sb.pack(side='left', fill='y')
        setup_detail_tags(self.preview)
        self.panel = PreviewPanel(self.preview, PreviewHost(self.app))

    def is_merc(self):
        return bool(self.merc.get())

    def slot_of(self, box):
        """The slot an equipment box stands for: set II's 11 / 12 for the weapon boxes when the character's set II
        is chosen; never on the mercenary view (his slots are MERC_SLOTS: one weapon set)."""
        return SET2.get(box, box) if self.wset.get() == 2 and not self.is_merc() else box

    def visible_boxes(self):
        return [b for b in DOLL if not self.is_merc() or b in MERC_SLOTS]

    def on_view(self):
        self.selected = None
        self.sel_slot = None
        self.redraw()

    # ---- drawing
    def icon(self, it, bg):
        """Icon layers at this page's own cell size, in its own cache (the main window drops its icons whenever
        its cell size changes; an image that is still shown here must not go with them)."""
        try:
            from PIL import Image, ImageTk
            from mxl_gfx import icon_layers, icon_name, ICON_CELL
            from paths import ICONS_DIR
            d = self.data
            key = (it['code'], icon_name(it, d), it.get('image'), it.get('ethereal'), it.get('sockets'),
                   tuple(icon_name(x, d) for x in it.get('socketed', [])), bg, self.cell)
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

    def fit_cell(self, _e=None):
        """Cell size of the Inventory page from the room the page has (called when the page is resized)."""
        self._fit_job = None
        try:
            W, H = self.scroll.winfo_width(), self.scroll.winfo_height()
            if W < 50 or H < 50 or not hasattr(self, 'inv') or not self.doll.winfo_exists():
                return
            c0 = self.cell
            left = self.doll.master
            over = left.winfo_reqheight() - (int(DOLL_H * c0) + 1) - (int(self.inv.cget('height')))
            try:
                from tkinter import font as tkfont
                side = 26 * tkfont.Font(font=self.preview.cget('font')).measure('0')
            except tk.TclError:
                side = 180
            cap = getattr(getattr(self.app, 'fit', None), 'cap', 48)
            c = int(min(cap, (H - over - 12) / (DOLL_H + INV_H), (W - side - 24) / INV_W))
            c = max(14, c)
            if c == c0:
                return
            self.cell = c
            self.icons.clear()
            self.doll.configure(width=int(DOLL_W * c) + 1, height=int(DOLL_H * c) + 1)
            self.inv.configure(width=INV_W * c + 1, height=INV_H * c + 1)
            self.status.configure(wraplength=max(260, INV_W * c))
            self.redraw()
            self.scroll.refresh()
        except (tk.TclError, AttributeError) as e:
            print('character inventory fit:', e)

    def _fit_later(self, _e=None):
        if getattr(self, '_fit_job', None) is None:
            try:
                self._fit_job = self.top.after(80, self.fit_cell)
            except tk.TclError:
                pass

    def draw_item(self, cv, it, x0, y0, x1, y1, selected):
        d = self.data
        unmet = (not self.is_merc()) and self.app.char is not None and requirements_unmet(it, d, self.app.char)
        bg = CELL_KO if unmet else CELL_OK
        fill = blend(SELECTION, bg, 0.12) if selected else bg
        col = item_color(it, d)
        cv.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill=fill, outline=col if selected else '',
                            width=2 if selected else 0)
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
        if not self.ch.merc_hired:                   # none, or dismissed on the Mercenary page
            self.merc.set(False)
        self.merc_rb.state(['!disabled'] if self.ch.merc_hired else ['disabled'])
        merc = self.is_merc()
        for rb in getattr(self, 'wset_rbs', ()):
            rb.state(['disabled'] if merc else ['!disabled'])
        eq = self.ch.equipped(merc)
        cv = self.doll
        cv.delete('all')
        for box in self.visible_boxes():
            x, y, w, h = DOLL[box]
            slot = self.slot_of(box)
            x0, y0, x1, y1 = x * c, y * c, (x + w) * c, (y + h) * c
            cv.create_rectangle(x0, y0, x1, y1, fill=EMPTY, outline='#d4b062' if slot == self.sel_slot else GRID_LINE,
                                width=2 if slot == self.sel_slot else 1)
            e = eq.get(slot)
            if e is not None:
                self.draw_item(cv, e.it, x0, y0, x1, y1, e is self.selected)
            elif box in (4, 5) and not merc:
                cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text='I' if self.wset.get() == 1 else 'II',
                               fill='#444444', font=('Segoe UI', 14))
        inv = self.inv
        inv.delete('all')
        if merc:
            self.inv_label.configure(text=T('ch.merc_no_inv', '(the mercenary has no inventory)'))
            inv.configure(height=1)
        else:
            self.inv_label.configure(text=T('ch.inv_label', 'Inventory - {name}, level {level}', name=self.ch.name, level=self.ch.level))
            inv.configure(height=INV_H * c + 1)
            for x in range(INV_W):
                for y in range(INV_H):
                    inv.create_rectangle(x * c, y * c, (x + 1) * c, (y + 1) * c, fill=EMPTY, outline=GRID_LINE)
            for e in self.ch.inventory():
                w, h = self.data.base(e.it['code']).size
                x0, y0 = e.it['x'] * c, e.it['y'] * c
                self.draw_item(inv, e.it, x0, y0, x0 + w * c, y0 + h * c, e is self.selected)
        self.panel.show(self.selected.it if self.selected else None)

    # ---- hit tests
    def target_at(self, cv, ev, size=(1, 1), dx=0, dy=0):
        c = self.cell
        if cv is self.doll:
            for box in self.visible_boxes():
                x, y, w, h = DOLL[box]
                if x * c <= ev.x < (x + w) * c and y * c <= ev.y < (y + h) * c:
                    return ('slot', self.slot_of(box))
            return None
        if self.is_merc():
            return None
        return ('inv', ev.x // c - dx, ev.y // c - dy)

    def entry_at(self, cv, ev):
        t = self.target_at(cv, ev)
        if t is None:
            return None, None
        if t[0] == 'slot':
            return self.ch.equipped(self.is_merc()).get(t[1]), t[1]
        for e in self.ch.inventory():
            w, h = self.data.base(e.it['code']).size
            if e.it['x'] <= t[1] < e.it['x'] + w and e.it['y'] <= t[2] < e.it['y'] + h:
                return e, None
        return None, None

    # ---- mouse
    def on_press(self, ev):
        cv = ev.widget
        self.sync_file()                  # the item is picked from the file as it is now (see save)
        e, slot = self.entry_at(cv, ev)
        self.selected = e
        self.sel_slot = slot
        self.drag = None
        if e is not None:
            dx = dy = 0
            if cv is self.inv:
                dx, dy = ev.x // self.cell - e.it['x'], ev.y // self.cell - e.it['y']
            self.drag = dict(entry=e, dx=dx, dy=dy, moved=False)
        self.redraw()

    def on_drag(self, ev):
        if self.drag:
            self.drag['moved'] = True
            self.top.configure(cursor='fleur')

    def on_release(self, ev):
        self.top.configure(cursor='')
        d, self.drag = self.drag, None
        if not d or not d['moved']:
            return
        x = ev.x_root - self.doll.winfo_rootx()
        y = ev.y_root - self.doll.winfo_rooty()
        cv = self.doll
        if not (0 <= x < self.doll.winfo_width() and 0 <= y < self.doll.winfo_height()):
            cv = self.inv
            x = ev.x_root - self.inv.winfo_rootx()
            y = ev.y_root - self.inv.winfo_rooty()
            if not (0 <= x < self.inv.winfo_width() and 0 <= y < self.inv.winfo_height()):
                return
        fake = type('E', (), {'x': x, 'y': y})()
        where = self.target_at(cv, fake, dx=d['dx'], dy=d['dy'])
        if where is None:
            return
        e = d['entry']
        try:                                              # a gem / rune / jewel onto an item: into its socket
            import mxl_socket_insert
            if mxl_socket_insert.char_tab_drop(self, e, cv, fake):
                return
        except Exception as err:
            print('socket insert:', err)
        try:
            self.ch.move(e, where, self.is_merc())
            self.save(T('ch.moved', '{item} moved', item=clean(e.it['name'])))
        except CharError as err:
            self.set_status(str(err), True)
            self.reload()

    # ---- actions
    def set_status(self, text, error=False):
        self.status.configure(text=text, foreground='#e06060' if error else '')

    def reload(self, keep=True):
        """Reads the character file again. keep (the default: every item action that fails ends here, and a file
        written from the Stash tab): the edits pending on the pages - stats, skills, waypoints, quests, the
        plug-in pages - stay pending on top of the file as it is now. keep=False is the RELOAD button: the file
        as it is, nothing pending."""
        self.ch = Character(self.ch.path, self.data)
        self.selected = None
        self.redraw()
        self._init_state(keep)
        self.refresh_progress(keep)

    def discard(self):
        """The RELOAD button: the file again, every pending edit dropped."""
        scr = getattr(self, 'statscreen', None)
        if scr is not None:
            scr.cancel_edit()
        tree = getattr(self, 'sktree', None)
        if tree is not None and hasattr(tree, 'cancel_edit'):
            tree.cancel_edit()
        self.reload(keep=False)
        self._follow_later()

    def changed_on_disk(self):
        """True when the character file is no longer the one this window read (written by someone else)."""
        try:
            with open(self.ch.path, 'rb') as f:
                return f.read() != bytes(self.ch.raw)
        except OSError:
            return False

    def sync_file(self):
        """The character file was written by someone else (an item action of the Stash tab's panel, an undo, the
        game): when it differs from what this window holds it is read again, pending edits kept (see reload) -
        so they are neither lost nor saved over the newer file. True when it was read again. Called before
        SAVE and whenever an item is picked (click, right-click, shortcut), so an item action works on the file
        as it is; save() refuses what slips through."""
        if self.drag is not None or not self.changed_on_disk():
            return False
        self.reload()
        return True

    def current_entry(self, e, merc):
        """The entry of self.ch standing for e, an entry of an earlier read (same list, place and bytes), or
        None when the item is no longer there as it was."""
        lst = self.ch.entries(merc)
        if any(x is e for x in lst):
            return e
        key = ('location', 'equipped', 'x', 'y', 'panel')
        return next((x for x in lst if bytes(x.blob) == bytes(e.blob)
                     and all(x.it.get(k) == e.it.get(k) for k in key)), None)

    def _follow_later(self):
        """Nothing pending any more: when another character was picked in the main window meanwhile (the tab
        stayed on this one because of its unsaved edits), the tab moves to that character now."""
        def go():
            try:
                import mxl_follow
                if not self.dirty():
                    mxl_follow._follow(self.app)
            except Exception as e:
                print('character tab did not follow the dropdown:', e)
        try:
            self.top.after_idle(go)
        except tk.TclError:
            pass

    def save(self, msg):
        """Writes the character as it is in memory (an item action: the pages' pending edits are not part of
        it and stay pending; save_progress applies them first).

        The file must still be the one self.ch was read from: Character.save writes over a file changed on disk
        (mxl_free), and an item action that changed this window's older copy would put that copy back over the
        other writer's change (the Stash tab's panel, an undo, the game). Then nothing is written, the file is
        read again (pending edits kept) and False is returned: the action is to be done again."""
        app = self.app
        if self.changed_on_disk():
            self.reload()
            self.set_status(T('ch.err.changed_on_disk', 'The character file changed on disk since this item was '
                              'picked: nothing written, the file has been read again - do it again.'), True)
            return False
        try:
            bak = self.ch.save(backup=app.needs_backup(self.ch.path))
        except (CharError, EditError, OSError) as e:   # EditError: the safe writer or the save check refused
            messagebox.showerror(T('ch.title', 'Character'), str(e) + (
                '\n\n' + T('ch.kept_pending', 'The file has been read again. The changes not yet saved are still '
                           'shown: check them and click SAVE again (RELOAD drops them).') if self.dirty() else ''),
                parent=self.top)
            self.reload()
            return False
        app.backup_made(self.ch.path, bak)
        self.selected = None
        self.redraw()
        self._init_state(keep=True)
        self.refresh_progress(keep=True)
        if app.path:
            app.load(app.path, keep_selection=True)
        self.set_status(msg + (T('cr.backup', ' - backup: {file}', file=os.path.basename(bak)) if bak else ''))
        return True

    def to_stash(self):
        app, e = self.app, self.selected
        if e is None:
            self.set_status(T('ch.select_first', 'Select an item of the character first.'), True)
            return
        if not app.path:
            self.set_status(T('cr.open_stash', 'Open a stash in the main window first.'), True)
            return
        merc = self.is_merc()
        try:
            blob = self.ch.stash_blob(e)
            before = read_file(app.path)
            items = parse_stash(app.path, self.data)
            new = mxl_save.blob_item(blob, self.data)
            pages = [app.page()] + [i for i in range(STASH_PAGES) if i != app.page()]
            spot = free_spot(items, new, self.data, pages)
            if spot is None:
                raise EditError(T('ch.err.stash_full', 'no free place in the stash'))
            bak = edit_stash(app.path, self.data, insert=[(spot[0], spot[1], spot[2], blob)],
                             backup=app.needs_backup(app.path))
            app.backup_made(app.path, bak)
        except (CharError, EditError, FormatError, OSError) as err:
            messagebox.showerror(T('ch.btn.to_stash', 'To stash'), str(err), parent=self.top)
            return
        self.ch.remove(e, merc)
        if not self.save(T('ch.sent', '{item} sent to {file}, page {page}', item=clean(e.it['name']),
                           file=os.path.basename(app.path), page=spot[0] + 1)):
            try:                       # character not written: put the stash back as it was
                commit_file(app.path, before, lambda tmp: None, backup=False)
            except Exception as rb:
                messagebox.showerror(T('ch.btn.to_stash', 'To stash'),
                                     T('ch.err.not_saved', 'character not saved') + MC.rollback_note(app.path, rb),
                                     parent=self.top)
            app.load(app.path, keep_selection=True)

    def from_stash(self):
        app = self.app
        it = app.selected
        if it is None or not app.path:
            self.set_status(T('ch.select_stash_first', 'Select an item in the stash of the main window first.'), True)
            return
        merc = self.is_merc()
        try:
            buf = read_file(app.path)
            blob = item_blob(buf, it)
            cur_slot = self.sel_slot
            if cur_slot is not None and self.ch.equipped(merc).get(cur_slot) is None:
                where = ('slot', cur_slot)
            else:
                if merc:
                    raise CharError(T('ch.err.merc_slot', 'select an empty mercenary slot first'))
                spot = self.ch.free_inventory_spot(mxl_save.blob_item(blob, self.data))
                if spot is None:
                    raise CharError(T('ch.err.inv_full', 'no free place in the inventory'))
                where = ('inv',) + spot
            if where[0] == 'slot' and not merc and app.char is not None and requirements_unmet(it, self.data, app.char):
                if not messagebox.askyesno(T('ch.equip', 'Equip'), T('ch.equip_ask', 'The character does not meet the requirements '
                                           'of this item: it will be inactive until he does. Equip anyway?'), parent=self.top):
                    return
            self.ch.place(blob, where, merc)
        except (CharError, EditError, FormatError, OSError) as err:
            self.set_status(str(err), True)
            self.reload()
            return
        before_char = self.ch.raw
        if not self.save(T('ch.taken', '{item} taken from the stash', item=clean(it['name']))):
            return
        try:
            bak = edit_stash(app.path, self.data, remove=[it['_offset']], backup=app.needs_backup(app.path))
            app.backup_made(app.path, bak)
        except (EditError, FormatError, OSError) as err:
            note = ''
            try:                       # stash not written: put the character back as it was
                commit_file(self.ch.path, before_char, lambda tmp: None, backup=False)
            except Exception as rb:
                note = MC.rollback_note(self.ch.path, rb)
            messagebox.showerror(T('ch.btn.from_stash', 'From stash'), str(err) + note, parent=self.top)
            self.reload()
        app.load(app.path, keep_selection=False)

    def delete(self):
        e = self.selected
        if e is None:
            self.set_status(T('ch.select_first', 'Select an item of the character first.'), True)
            return
        if getattr(e.blob, 'read_only_reason', None):
            self.set_status(e.blob.read_only_reason, True)
            return
        name = clean(e.it['name'])
        if not messagebox.askyesno(T('ch.btn.delete', 'Delete'), T('ch.delete_ask', 'Delete {item} (and its socketed items) from '
                                   '{name}?\nA backup of the character is made first.', item=name, name=self.ch.name), parent=self.top):
            return
        self.ch.remove(e, self.is_merc())
        self.save(T('cr.deleted', '{name} deleted', name=name))

    def edit(self):
        e = self.selected
        if e is None:
            self.set_status(T('ch.select_first', 'Select an item of the character first.'), True)
            return
        if getattr(e.blob, 'read_only_reason', None):
            self.set_status(e.blob.read_only_reason, True)
            return
        merc = self.is_merc()
        where = MC.where_of(e)

        def write(blob):
            self.sync_file()                  # the file may have been written while the editor was open
            cur = self.current_entry(e, merc)
            if cur is None:
                raise CharError(T('inv.err.item_gone', 'the item is no longer where it was: select it again'))
            self.ch.remove(cur, merc)
            try:
                self.ch.place(blob, where, merc)
            except CharError:
                if where[0] in ('inv', 'store'):
                    spot = self.ch.free_inventory_spot(mxl_save.blob_item(blob, self.data))
                    if spot is None:
                        self.reload()
                        raise
                    self.ch.place(blob, ('inv',) + spot, merc)
                else:
                    self.reload()
                    raise
            if not self.save(T('ch.replaced', '{item} replaced', item=clean(e.it['name']))):
                raise CharError(T('ch.err.not_saved', 'character not saved'))
            return T('ch.item_replaced', '{name}: item replaced', name=self.ch.name)
        CreatorWindow(self.app, edit_item=e.it, target=write, target_label=f'{self.ch.name}')

    def create_here(self):
        merc = self.is_merc()
        slot = self.sel_slot

        def write(blob):
            self.sync_file()                  # the file may have been written while the creator was open
            if slot is not None and self.ch.equipped(merc).get(slot) is None:
                where = ('slot', slot)
            else:
                if merc:
                    raise CharError(T('ch.err.merc_slot', 'select an empty mercenary slot first'))
                spot = self.ch.free_inventory_spot(mxl_save.blob_item(blob, self.data))
                if spot is None:
                    raise CharError(T('ch.err.inv_full', 'no free place in the inventory'))
                where = ('inv',) + spot
            try:
                self.ch.place(blob, where, merc)
            except CharError:
                self.reload()
                raise
            if not self.save(T('ch.item_created', 'item created')):
                raise CharError(T('ch.err.not_saved', 'character not saved'))
            return T('ch.created_in', '{name}: item created in {where}', name=self.ch.name,
                     where=slot_name(where[1]) if where[0] == 'slot' else T('ch.the_inventory', 'the inventory'))
        label = (f"{self.ch.name}{T('ch.merc_suffix', ' (mercenary)') if merc else ''} - "
                 + (slot_name(slot, T('ch.inventory_l', 'inventory')) if slot else T('ch.inventory_l', 'inventory')))
        CreatorWindow(self.app, target=write, target_label=label)

    # ---- mouse extras: double-click opens the item editor / creates in an empty spot
    def on_double(self, ev):
        cv = ev.widget
        self.sync_file()
        e, slot = self.entry_at(cv, ev)
        self.selected, self.sel_slot = e, slot
        self.redraw()
        if e is not None:
            self.edit()
        elif slot is not None or cv is self.inv:
            self.create_here()

    def on_delete_key(self, _e=None):
        """Del over the paperdoll / inventory: the item under the mouse pointer is deleted at once
        (no prompt, like the stash grid). Nothing happens when the pointer is elsewhere or inside
        a text field."""
        try:
            w = self.top.winfo_toplevel().focus_get()
            if w is not None and w.winfo_class() in ('Entry', 'Text', 'Spinbox', 'Combobox'):
                return
        except Exception:
            pass
        for cv in (self.doll, self.inv):
            try:
                if not cv.winfo_ismapped():
                    continue
                x = cv.winfo_pointerx() - cv.winfo_rootx()
                y = cv.winfo_pointery() - cv.winfo_rooty()
                if not (0 <= x < cv.winfo_width() and 0 <= y < cv.winfo_height()):
                    continue
                e, _slot = self.entry_at(cv, type('E', (), {'widget': cv, 'x': x, 'y': y})())
            except Exception:
                continue
            if e is not None:
                if self.sync_file():          # read again: the item under the pointer in the file as it is
                    e, _slot = self.entry_at(cv, type('E', (), {'widget': cv, 'x': x, 'y': y})())
                    if e is None:
                        return
                self.delete_instant(e)
                return

    def delete_instant(self, e):
        """Deletes one item of the character at once (no prompt): the same remove -> save flow as
        the Delete button, which keeps its confirmation dialog."""
        name = clean(e.it['name'])
        try:
            self.ch.remove(e, self.is_merc())
        except CharError as err:
            self.set_status(str(err), True)
            self.reload()
            return
        self.save(T('cr.deleted', '{name} deleted', name=name))

    # ================================================================== Skills tab
    def _build_skills(self):
        """The Skills page: a slim bar (find, all levels 0) over the game's skill-tree panel (mxl_skilltree)."""
        import mxl_skilltree
        f = self.sk_tab
        self.sk_vars = {}
        self._skills_cls = None
        top = tk.Frame(f, bg=HE_BG)
        top.pack(fill='x', padx=4, pady=(2, 1))
        self.sk_title = tk.Label(top, text='', font=HE_FONT_I, bg=HE_BG)
        self.sk_title.pack(side='left')
        tk.Label(top, text='   ' + T('he.skills_find', 'Find:'), font=HE_FONT, bg=HE_BG).pack(side='left')
        self.sk_search = tk.StringVar()
        se = tk.Entry(top, textvariable=self.sk_search, width=16, font=HE_FONT, relief='sunken', bd=2)
        se.pack(side='left', padx=4)
        se.bind('<KeyRelease>', lambda _e: self._filter_skills())
        tk.Button(top, text=T('he.skills_zero', 'All levels 0'), font=HE_FONT, bg=HE_BTN, pady=0,
                  command=self._zero_skills).pack(side='left', padx=4)
        self.sk_other = tk.Button(top, text=T('sk.other', 'Other skills'), font=HE_FONT, bg=HE_BTN, pady=0,
                                  command=lambda: self.sktree.toggle_other())
        self.sk_other.pack(side='left', padx=4)
        self.sk_top = top
        self.sktree = mxl_skilltree.SkillTree(f, self)
        self.sktree.frame.pack(fill='both', expand=True)
        self.scroll.bind('<Configure>', self._fit_skills, add='+')

    def _fit_skills(self, _e=None):
        tree = getattr(self, 'sktree', None)
        if tree is None or self.tab.get() != 'skills':
            return
        try:
            W, H = self.scroll.winfo_width(), self.scroll.winfo_height()
            if W > 40 and H > 40:
                k = tree.k
                tree.fit(W - 2, H - self.sk_top.winfo_reqheight() - 6)
                if tree.k != k:
                    self._scroll_later()
        except tk.TclError:
            pass

    def _rebuild_skills(self):
        """The class's trees again (another character or class): see mxl_skilltree.SkillTree."""
        ch, d = self.ch, self.data
        self._skills_cls = ch.cls
        names = MC.class_names(d)
        cname = names[ch.cls] if ch.cls < len(names) else str(ch.cls)
        self.sk_title.configure(text=T('he.skills_of2', '{cls} skills', cls=cname))
        self.sktree.rebuild()
        self._fit_skills()

    def _filter_skills(self):
        self.sktree.set_filter(self.sk_search.get())

    def _theme_art(self):
        """The game's Sigma theme artwork (None without the game folder): stone panels and fonts.
        Independent of mxl_d2look's own switch - the main window's plain grids stay untouched."""
        key = (self.data.folder,)
        cache = getattr(self, '_art_cache', None)
        if cache is None:
            cache = self._art_cache = {}
        if key in cache:
            return cache[key]
        art = None
        try:
            import mxl_d2look_art
            import settings
            import paths
            gd = settings.get('game_dir')
            if gd and os.path.isdir(gd):
                art = mxl_d2look_art.get_art(gd, 'classic_sigma', os.path.join(paths.USER_DIR, 'ui_art'))
                art.pal()
        except Exception as e:
            print('game art for the skills screen disabled:', e)
        cache[key] = art
        return art

    def _sk_name(self, sid):
        nm = self.data.skill_names.get(sid) or ''
        if not nm or 'OLAR BUFFALO' in nm.upper():     # the game's placeholder for an unnamed skill
            try:                                       # the skilldesc's own name string (Attack, skill 0, has
                import re                              # no entry in the collector's skill names)
                import mxl_skilldesc
                nm = re.sub('\xffc.', '', mxl_skilldesc.tables(self.data).name(sid) or '').strip()
                if 'OLAR BUFFALO' in nm.upper() or 'hidden #' in nm or nm.startswith('skill #'):
                    nm = ''
            except Exception:
                nm = ''
        if not nm:
            try:                                       # a hidden helper skill: the name derived from what it does
                import mxl_statnames
                nm = mxl_statnames.hidden_skill_name(self.data, sid) or ''
            except Exception:
                nm = ''
        if not nm:
            nm = T('skill.unknown', 'skill #{id}', id=sid)
        return nm

    def _art_photo(self, path, size=None):
        """The game font/panel PNG as a tk image (None without the game folder)."""
        try:
            import mxl_d2look
            return mxl_d2look.photo(path, size=size)
        except Exception:
            return None

    def _sk_tip(self, text, owner=None):
        """The game's floating tooltip: gold text on dark stone with a gold frame, beside the pointer.
        mxl_floattip: a fresh window per text, sized to it (never re-mapped); the same text only follows the
        pointer (no flicker under XWayland compositors); '' hides it at once."""
        import mxl_floattip
        tip = getattr(self, '_sk_tipper', None)
        if not text:
            if tip is not None:
                tip.hide()
            return
        if tip is None:
            tip = self._sk_tipper = mxl_floattip.FloatTip(self.top, build=self._sk_tip_build, gap=(18, 14, 14),
                                                          bg=SK_BG, edge=SK_EDGE)
        self._sk_tip_text = text
        tip.show(owner, key=text)

    def _sk_tip_build(self, body):
        tk.Label(body, text=getattr(self, '_sk_tip_text', ''), font=HE_FONT, bg=SK_BG, fg=HE_GOLD, justify='left',
                 padx=10, pady=6, bd=0, highlightthickness=0).pack()

    def _sk_tip_leave(self, widget):
        """<Leave> of a widget with a tooltip: hidden a moment later if the pointer really left it."""
        tip = getattr(self, '_sk_tipper', None)
        if tip is not None:
            tip.leave(widget)

    def _zero_skills(self):
        for var in self.sk_vars.values():
            var.set('0')
        self.update_dirty()

    def _skills_from_vars(self):
        out = {}
        for sid, v in self.sk_vars.items():
            try:
                out[sid] = max(0, min(255, int(v.get())))
            except ValueError:
                pass                      # blank / junk: keep 0
        return out

    def on_class_change(self):
        try:
            cls = self.class_names.index(self.new_class.get())
        except ValueError:
            self._reset_class_box()
            return
        if cls == self.ch.cls:
            self.pending_cls = None
            self.update_dirty()
            return
        if cls != self.pending_cls and not messagebox.askyesno(
                T('he.class', 'Class'),
                T('he.class_ask', 'Change the class of {name} to {cls}?\nAll skill levels are reset '
                  '(the save keeps one skill list per class).', name=self.ch.name, cls=self.new_class.get()),
                parent=self.top):
            self._reset_class_box()
            return
        self.pending_cls = cls
        self.update_dirty()

    def _reset_class_box(self):
        self.new_class.set(self.class_names[self.ch.cls] if self.ch.cls < len(self.class_names) else str(self.ch.cls))
        self.pending_cls = None
        self.update_dirty()

    # ================================================================== Hero Editor style tabs
    # Stats / Waypoints / Quests tabs in the look of the old Hero Editor (Mastadex, ZonFire99): classic grey
    # frames, Times New Roman, white tree panes with check boxes, the tab row at the bottom of the window.
    # Stat fields the user may edit: key -> (character stat id, right shift). Life / mana / stamina are stored
    # in the save in 256ths, so their boxes show the game's own numbers (value >> 8) and writes go << 8.
    # the grey page's number boxes: mxl_char field keys (edited through the StatEditMixin engine)
    GREY_KEYS = ('level', 'experience', 'strength', 'dexterity', 'vitality', 'energy', 'stat_points', 'skill_points',
                 'life_cur', 'life_max', 'mana_cur', 'mana_max', 'stamina_cur', 'stamina_max', 'gold', 'gold_stash',
                 'progression', 'name')

    def _stat_art(self):
        """The game art for the in-game stat screen (dark look with the game folder known), or None."""
        try:
            import mxl_d2look
            art = mxl_d2look.art() if self.dark.get() else None
            if art is not None:
                art.panel('stat-screen')
                art.frame('buttons\\stat-screen', 0)
                art.font('font16')
                art.font('font6')
            return art
        except Exception as e:
            print('in-game stat screen disabled:', e)
            return None

    def _scroll_later(self):
        """Asks the scroll area to measure the page again once Tk has laid it out: a page that changed its size
        while it is held at the size of the tab sends no event of its own."""
        def again():
            try:
                self.scroll.update_idletasks()
                self.scroll.refresh()
            except tk.TclError:
                pass
        try:
            self.scroll.after(40, again)
        except tk.TclError:
            pass

    def _fit_stats(self, _e=None):
        scr = getattr(self, 'statscreen', None)
        if scr is None or self.tab.get() != 'stats':
            return
        try:
            W, H = self.scroll.winfo_width(), self.scroll.winfo_height()
            if W > 40 and H > 40:
                k = scr.k
                scr.fit(W - 2, H - 2)
                if scr.k != k:                # another panel size: the page may now need (or drop) its scrollbar
                    self._scroll_later()
        except tk.TclError:
            pass

    def _build_progress(self):
        ch, d = self.ch, self.data
        self._init_state()
        # ---------------------------------------------------------------- Stats
        f = self.st_tab
        self.sv = {}
        self.statscreen = None
        self.copy_name = tk.StringVar()
        self.class_names = MC.class_names(d)
        self.new_class = tk.StringVar(value=self.class_names[ch.cls] if ch.cls < len(self.class_names) else str(ch.cls))
        from tkinter import font as tkfont
        note_w = tkfont.Font(font=HE_FONT_S).measure('0') * 34    # notes wrap instead of widening their column
        art = self._stat_art()
        if art is not None:                 # the game's own character screen, values edited in place
            import mxl_statscreen
            f.configure(bg='#000000')
            self.statscreen = mxl_statscreen.StatScreen(f, self, art)
            self.statscreen.frame.pack(fill='both', expand=True)
        else:
            self._build_stats_grey(f, note_w)

        # ---------------------------------------------------------------- Waypoints / Quests
        self.wp_trees = []
        self.q_trees = []
        for k, _dn in enumerate(DIFFICULTIES):
            dn = difficulty_name(k)
            self.wp_tab.grid_columnconfigure(k, weight=1, uniform='he')
            self.q_tab.grid_columnconfigure(k, weight=1, uniform='he')
            fr = tk.LabelFrame(self.wp_tab, text=dn, font=HE_FONT_I, bg=SK_STONE, bd=2, relief='groove', padx=2, pady=2)
            fr.grid(row=0, column=k, sticky='nsew', padx=2, pady=2)
            t = CheckTree(fr, self.on_tree_change)
            root = t.add('', T('he.mode_waypoints', '{mode} Mode Waypoints', mode=dn))
            ids = set(self.ch.waypoint_ids(k))
            for act, wps in WAYPOINTS:
                visible = [(n, name) for n, name in wps if n in ids]
                if not visible:
                    continue
                a = t.add(root, act)
                for n, name in visible:
                    t.add(a, name + (T('he.hell_suffix', ' (Hell)') if n in MC.HELL_ONLY_WAYPOINTS else ''), key=('wp', k, n), locked=(n == 0))
            t.open(root)
            self.wp_trees.append(t)
            fr = tk.LabelFrame(self.q_tab, text=dn, font=HE_FONT_I, bg=SK_STONE, bd=2, relief='groove', padx=2, pady=2)
            fr.grid(row=0, column=k, sticky='nsew', padx=2, pady=2)
            t = CheckTree(fr, self.on_tree_change)
            root = t.add('', T('he.mode_quests', '{mode} Mode Quests', mode=dn))
            for act, intro, quests, done in self.ch.quest_acts():
                a = t.add(root, act)
                for word, key in quests:
                    r = MC.QUEST_REWARDS.get(word)
                    extra = ''
                    if r:
                        extra = {'skill': (T('he.reward.skill1', '  (+{n} skill point)', n=r[1]) if r[1] == 1 else
                                           T('he.reward.skill', '  (+{n} skill points)', n=r[1])),
                                 'stats': T('he.reward.stats', '  (+{n} stat points)', n=r[1]),
                                 'life': T('he.reward.life', '  (+{n} life)', n=r[1])}[r[0]]
                    t.add(a, clean(d.key(key)) + extra, key=('q', k, word))
            t.open(root)
            self.q_trees.append(t)
        self.wp_tab.grid_rowconfigure(0, weight=1)
        self.q_tab.grid_rowconfigure(0, weight=1)
        tk.Label(self.wp_tab, text=T('he.wp_note', 'Waypoints marked (Hell) are Median XL areas that only exist in Hell. '
                                     'Click a box to tick it; a mode or act box ticks everything under it.'),
                 font=HE_FONT_S, bg=SK_STONE, justify='left', wraplength=note_w * 2).grid(row=1, column=0, columnspan=3, sticky='w', padx=4)
        tk.Label(self.q_tab, text=T('he.q_note', 'Ticking a quest gives its reward in that difficulty (shown in brackets). '
                                    'Quests completed in game stay ticked and cannot be changed here.'),
                 font=HE_FONT_S, bg=SK_STONE, justify='left', wraplength=note_w * 2).grid(row=1, column=0, columnspan=3, sticky='w', padx=4)
        self.refresh_progress()

    def _build_stats_grey(self, f, note_w):
        """The Hero-Editor style page (light look, or no game art): the same values, edited through the same engine."""
        ch, d = self.ch, self.data

        def frame(parent, text, **grid):
            """One of the character screen's sections: stone box, gold title, gold game-font text."""
            fr = tk.LabelFrame(parent, text=' ' + text, font=HE_FONT_I, bg=SK_STONE, fg=HE_GOLD,
                               bd=2, relief='groove', padx=4, pady=1,
                               highlightbackground=SK_EDGE, highlightthickness=1)
            fr.grid(sticky='nsew', padx=2, pady=1, **grid)
            return fr

        def entry(parent, key, width, justify='right', **grid):
            e = tk.Entry(parent, width=width, font=HE_FONT, relief='sunken', bd=2, bg='#000000',
                         readonlybackground='#0b0a08', fg=HE_GOLD, insertbackground=HE_GOLD, justify=justify)
            e.grid(**grid)
            if key in self.GREY_KEYS:                # editable: Enter / leaving the box stores it, SAVE writes it
                e.bind('<KeyRelease>', lambda _e: self.update_dirty())
                e.bind('<Return>', lambda _e, k=key: self._grey_commit(k))
                e.bind('<KP_Enter>', lambda _e, k=key: self._grey_commit(k))
                e.bind('<FocusOut>', lambda _e, k=key: self._grey_commit(k, leaving=True))
                e.bind('<Escape>', lambda _e: self._refresh_stats_grey())
                if key != 'name':
                    e.bind('<Up>', lambda ev, k=key: self._grey_step(k, 10 if ev.state & 1 else 1))
                    e.bind('<Down>', lambda ev, k=key: self._grey_step(k, -10 if ev.state & 1 else -1))
            else:
                e.configure(state='readonly')
            self.sv[key] = e
            return e

        def field(parent, r, label, key, width=12, col=0):
            tk.Label(parent, text=label, font=HE_FONT, bg=SK_STONE).grid(row=r, column=col, sticky='e', padx=(0, 4), pady=1)
            return entry(parent, key, width, row=r, column=col + 1, sticky='w', pady=1)

        for c in range(3):
            f.grid_columnconfigure(c, weight=1, uniform='he')
        fr = frame(f, T('he.name', 'Name'), row=0, column=0)
        e = entry(fr, 'name', 16, justify='left', row=0, column=0, columnspan=3, sticky='w')
        e.configure(font=('Times New Roman', 13, 'bold'))
        tk.Label(fr, text=T('he.copy_as', 'Copy as'), font=HE_FONT, bg=SK_STONE).grid(row=1, column=0, sticky='w', pady=(4, 0))
        tk.Entry(fr, textvariable=self.copy_name, width=11, font=HE_FONT, relief='sunken', bd=2).grid(row=1, column=1, pady=(4, 0))
        tk.Button(fr, text=T('he.copy', 'Copy'), font=HE_FONT, command=self.copy_char, bg=HE_BTN).grid(row=1, column=2, padx=4, pady=(4, 0))

        fr = frame(f, T('he.class', 'Class'), row=1, column=0)
        tk.Label(fr, text=T('he.class_c', 'Class:'), font=HE_FONT, bg=SK_STONE).grid(row=0, column=0, sticky='e', padx=(0, 4), pady=1)
        self.class_box = ttk.Combobox(fr, state='readonly', width=14, textvariable=self.new_class,
                                      values=self.class_names)
        self.class_box.grid(row=0, column=1, sticky='w', pady=1)
        self.class_box.bind('<<ComboboxSelected>>', lambda _e: self.on_class_change())
        tk.Label(fr, text=T('he.class_note', 'Changing the class resets the skill levels\n(the save keeps one skill list per class).'),
                 font=HE_FONT_S, bg=SK_STONE, justify='left', wraplength=note_w).grid(row=1, column=0, columnspan=2, sticky='w', pady=(2, 0))
        fr = frame(f, T('he.level', 'Level'), row=2, column=0)
        field(fr, 0, T('he.level_c', 'Level:'), 'level', 6)
        tk.Label(fr, text=T('he.level_up_c', 'Level up to:'), font=HE_FONT, bg=SK_STONE).grid(row=1, column=0, sticky='e', padx=(0, 4))
        self.new_level = tk.StringVar(value='')
        self.level_box = ttk.Combobox(fr, state='readonly', width=6, textvariable=self.new_level)
        self.level_box.grid(row=1, column=1, sticky='w')
        self.level_box.bind('<<ComboboxSelected>>', lambda _e: self._grey_levelup())
        tk.Label(fr, text=T('he.level_note2', 'The Level box is written as typed. "Level up to" works like the game: '
                            'experience, 5 stat points and 1 skill point per level, life / mana / stamina per level.'),
                 font=HE_FONT_S, bg=SK_STONE, justify='left', wraplength=note_w).grid(row=2, column=0, columnspan=2, sticky='w', pady=(2, 0))
        fr = frame(f, T('he.experience', 'Experience'), row=3, column=0)
        field(fr, 0, T('he.experience_c', 'Experience:'), 'experience', 14)
        tk.Button(fr, text=T('ss.match', 'Match to level'), font=HE_FONT_S, command=self.st_match_exp, bg=HE_BTN,
                  pady=0).grid(row=1, column=1, sticky='w')
        self.exp_note = tk.Label(fr, text='', font=HE_FONT_S, bg=SK_STONE, justify='left', wraplength=note_w)
        self.exp_note.grid(row=2, column=0, columnspan=2, sticky='w')

        fr = frame(f, T('he.characteristics', 'Characteristics'), row=0, column=1, rowspan=2)
        for r, (lab, key) in enumerate(((T('he.str', 'Strength:'), 'strength'), (T('he.dex', 'Dexterity:'), 'dexterity'),
                                        (T('he.vit', 'Vitality:'), 'vitality'), (T('he.ene', 'Energy:'), 'energy'),
                                        (T('he.statpts', 'Stat Points Left:'), 'stat_points'),
                                        (T('he.skillpts', 'Skill Points Left:'), 'skill_points'))):
            field(fr, r, lab, key, 8)
            if key in ('strength', 'dexterity', 'vitality', 'energy'):
                b = tk.Button(fr, text='+', font=HE_FONT_S, bg=HE_BTN, padx=3, pady=0, takefocus=0)
                b.grid(row=r, column=2, padx=(3, 0))
                b.bind('<ButtonRelease-1>', lambda ev, k=key: self._grey_plus(k, ev))
                b.bind('<ButtonRelease-3>', lambda ev, k=key: self._grey_plus(k, ev, take=True))
        fr = frame(f, T('he.constitution', 'Constitution'), row=2, column=1, rowspan=2)
        tk.Label(fr, text=T('he.current', 'Current'), font=HE_FONT_S, bg=SK_STONE).grid(row=0, column=1)
        tk.Label(fr, text=T('he.max', 'Max'), font=HE_FONT_S, bg=SK_STONE).grid(row=0, column=3)
        for r, (lab, key) in enumerate(((T('he.life', 'Life:'), 'life'), (T('he.mana', 'Mana:'), 'mana'),
                                        (T('he.stamina', 'Stamina:'), 'stamina')), start=1):
            field(fr, r, lab, key + '_cur', 8)
            tk.Label(fr, text='/', font=HE_FONT, bg=SK_STONE).grid(row=r, column=2, padx=2)
            entry(fr, key + '_max', 8, row=r, column=3, sticky='w')

        fr = frame(f, T('he.gold', 'Gold'), row=0, column=2)
        field(fr, 0, T('he.person', 'Person:'), 'gold', 12)
        field(fr, 1, T('he.stash', 'Stash:'), 'gold_stash', 12)
        fr = frame(f, T('he.char_type', 'Character Type'), row=1, column=2)
        self.sv_type = {}
        for r, (text, key) in enumerate(((T('he.expansion', 'Expansion'), 'expansion'), (T('he.ladder', 'Ladder'), 'ladder'),
                                         (T('he.hardcore', 'Hardcore'), 'hardcore'), (T('he.dead', 'You were Dead'), 'died'))):
            v = tk.BooleanVar()
            tk.Checkbutton(fr, text=text, variable=v, font=HE_FONT, bg=SK_STONE,
                           command=lambda k=key, v=v: self.st_flag(k, v.get())).grid(row=r, column=0, sticky='w')
            self.sv_type[key] = v
        fr = frame(f, T('he.char_diff', 'Character Difficulty'), row=2, column=2)
        self.sv_diff = tk.IntVar()
        names = [difficulty_name(r) for r in range(len(DIFFICULTIES))] + [T('ss.hell_done', 'Hell finished')]
        for r, n in enumerate(names):
            tk.Radiobutton(fr, text=n, value=r, variable=self.sv_diff, font=HE_FONT, bg=SK_STONE,
                           command=lambda: self.st_done(self.sv_diff.get())).grid(row=r, column=0, sticky='w')
        tk.Label(fr, text=T('he.diff_note', '(highest difficulty unlocked)'), font=HE_FONT_S, bg=SK_STONE).grid(row=4, column=0, sticky='w')
        field(fr, 5, T('ss.progression_c', 'Progression:'), 'progression', 5)
        fr = frame(f, T('he.misc', 'Miscellaneous Info.'), row=3, column=2)
        field(fr, 0, T('he.file_size', 'File Size:'), 'size', 10)
        field(fr, 1, T('he.version', 'Version:'), 'version', 10)
        tk.Label(f, text=T('he.stats_note2', 'Type any value in the boxes (Enter stores it, Up / Down step by 1, '
                           'Shift: 10) and click SAVE. The + buttons spend stat points like the game (Shift +10, '
                           'Ctrl all, right click gives a point back, Alt leaves the stat points alone).'),
                 font=HE_FONT_S, bg=SK_STONE, justify='left', wraplength=note_w * 2).grid(
            row=4, column=0, columnspan=3, sticky='w', padx=4, pady=(2, 0))

    def _grey_commit(self, key, leaving=False):
        e = self.sv.get(key)
        if e is None or e.get() == str(self.st_value(key)):
            return True
        ok = self.st_set(key, e.get())
        if not ok and leaving:                   # refused and the box was left: back to the stored value
            e.delete(0, 'end')
            e.insert(0, str(self.st_value(key)))
        return ok

    def _grey_step(self, key, n):
        e = self.sv[key]
        try:
            v = int(e.get().replace(',', '').replace(' ', ''))
        except ValueError:
            v = self.st_value(key)
        lo, hi = self.st_range(key)
        e.delete(0, 'end')
        e.insert(0, str(max(lo, min(hi, v + n))))
        self._grey_commit(key)
        return 'break'

    def _grey_plus(self, key, ev, take=False):
        if not self._grey_flush():
            return
        self.st_plus(key, 10 if ev.state & 0x1 else 1, take=take, free=bool(ev.state & 0x8),
                     everything=bool(ev.state & 0x4) and not ev.state & 0x8 and not take)

    def _grey_levelup(self):
        try:
            self.st_do('levelup', int(self.new_level.get()))
        except ValueError:
            pass
        self.new_level.set('')

    def _grey_flush(self):
        """Stores what is typed in the boxes and not yet committed. False when a value is refused."""
        return all(self._grey_commit(k) for k in self.GREY_KEYS if k in self.sv)

    def _refresh_stats_grey(self):
        ch, sim = self.ch, self.st_sim
        vals = {k: self.st_value(k) for k in self.GREY_KEYS}
        vals['size'] = f'{len(ch.raw):,}'
        vals['version'] = str(struct.unpack_from('<I', ch.raw, 4)[0])
        for key, e in self.sv.items():
            e.configure(state='normal')
            e.delete(0, 'end')
            e.insert(0, str(vals.get(key, '')))
            e.configure(state='normal' if key in self.GREY_KEYS else 'readonly')
        top = MC.max_level(self.data, sim.cls) if sim.cls < 7 else sim.level
        self.level_box.configure(values=[str(v) for v in range(sim.level + 1, top + 1)])
        self.new_level.set('')
        flags = sim.flags()
        for key, v in self.sv_type.items():
            v.set(flags[key])
        self.sv_diff.set(sim.difficulties_done)
        if sim.cls < 7:
            lo, hi = sim.exp_range()
            self.exp_note.configure(text=T('ss.exp_note', 'level {level}: {lo} to {hi}', level=sim.level, lo=lo, hi=hi),
                                    fg='#ff6060' if not lo <= sim.field('experience') <= hi else HE_GOLD)

    def st_flush(self):
        """Commits an edit still open in a box (the art page's entry or the grey page's boxes)."""
        scr = getattr(self, 'statscreen', None)
        if scr is not None:
            return scr.commit_edit()
        return self._grey_flush()

    def _init_state(self, keep=False):
        """The window's picture of the file (self.ch). keep: what is pending on the built-in pages (ticks of
        quests / waypoints, typed skill levels, the class, the stat-screen operations) stays pending against the
        new file state; otherwise nothing is pending."""
        ch = self.ch
        old = (self.q0, self.qstate, self.w0, self.wstate) if keep and hasattr(self, 'wstate') else None
        self.q0 = {k: {w for _, _, quests, _ in ch.quest_acts() for w, _ in quests if ch.quest_done(k, w)} for k in range(3)}
        self.w0 = {k: {n for n in self.ch.waypoint_ids(k) if ch.waypoint(k, n)} | {0} for k in range(3)}
        self.qstate = {k: set(v) for k, v in self.q0.items()}
        self.wstate = {k: set(v) for k, v in self.w0.items()}
        if old is not None:                           # the ticks set / taken away since the old file state
            for new, (base, cur) in ((self.qstate, old[:2]), (self.wstate, old[2:])):
                for k in range(3):
                    new[k] |= cur[k] - base[k]
                    new[k] -= base[k] - cur[k]
        # quests completed in game (not by this tool): never unticked
        self.qlocked = {k: {w for w in self.q0[k] if ch.quest_word(k, w) != MC.QUEST_DONE} for k in range(3)}
        for k in range(3):
            self.qstate[k] |= self.qlocked[k]
        sk_old = getattr(self, 'sk0', {})
        self._sk_keep = {}
        if keep and getattr(self, '_skills_cls', None) == ch.cls:      # levels typed and not saved yet
            self._sk_keep = {sid: self._level_of(v) for sid, v in getattr(self, 'sk_vars', {}).items()
                             if self._level_of(v) != sk_old.get(sid, 0)}
        self.sk0 = ch.skill_levels()
        if keep and hasattr(self, 'st_ops'):
            if getattr(self, 'pending_cls', None) == ch.cls:
                self.pending_cls = None
            self.st_rebuild()
        else:
            self.pending_cls = None
            self.st_reset()

    def on_tree_change(self, key, value):
        kind, k, n = key
        st = self.wstate[k] if kind == 'wp' else self.qstate[k]
        (st.add if value else st.discard)(n)
        self.update_dirty()

    def _extra_call(self, name, *args, default=None, collect=False):
        """Calls an optional method on every plug-in page; collect: list of the results."""
        out = []
        for key, obj in getattr(self, 'extra', {}).items():
            fn = getattr(obj, name, None)
            if fn is None:
                continue
            try:
                out.append(fn(*args))
            except CharError:
                raise
            except Exception as e:
                print(f'character page {key!r}: {name} failed:', e)
        return out if collect else default

    def dirty(self):
        if any(self._extra_call('dirty', collect=True)):
            return True
        sk0 = getattr(self, 'sk0', {})
        sk_typed = any(sk0.get(sid, 0) != self._level_of(v) for sid, v in self.sk_vars.items())
        typed = any(e.get() != str(self.st_value(k)) for k, e in getattr(self, 'sv', {}).items() if k in self.GREY_KEYS)
        return (self.qstate != self.q0 or self.wstate != self.w0 or self.st_dirty() or typed
                or getattr(self, 'pending_cls', None) is not None or sk_typed)

    @staticmethod
    def _level_of(var):
        try:
            return max(0, min(255, int(var.get())))
        except ValueError:
            return 0

    def update_dirty(self):
        if self.dirty():
            self.set_bar(T('he.unsaved', 'Unsaved changes: click Save.'))
        else:
            self.set_bar('')

    def _extra_refresh(self, keep=False):
        """refresh() of every plug-in page; keep: a page with pending edits gets rebase() instead (see the
        comment above EXTRA_PAGES)."""
        for key, obj in getattr(self, 'extra', {}).items():
            try:
                if keep and getattr(obj, 'dirty', None) is not None and obj.dirty():
                    fn = getattr(obj, 'rebase', None)
                else:
                    fn = getattr(obj, 'refresh', None)
                if fn is not None:
                    fn()
            except Exception as e:
                print(f'character page {key!r}: refresh failed:', e)

    def refresh_progress(self, keep=False):
        """Shows self.ch on every page. keep: after an item action / a re-read that leaves pending edits alone
        (the state itself is carried over by _init_state(keep=True))."""
        ch, d = self.ch, self.data
        self._extra_refresh(keep)
        self.st_rebuild()                 # the character may have been written (items) or read again
        cls = ch.cls if not keep or self.pending_cls is None else self.pending_cls
        self.new_class.set(self.class_names[cls] if cls < len(self.class_names) else str(cls))
        if not keep:
            self.pending_cls = None
        typed = getattr(self, '_sk_keep', {}) if keep else {}
        self._sk_keep = {}
        rebuilt = getattr(self, '_skills_cls', None) != ch.cls
        if rebuilt:
            self._rebuild_skills()        # (draws the tree: no second drawing below)
        else:
            lv = ch.skill_levels()
            for sid, var in self.sk_vars.items():
                var.set(str(typed.get(sid, lv.get(sid, 0))))
        if self.statscreen is not None:
            self.statscreen.redraw()
        else:
            self._refresh_stats_grey()
        if getattr(self, 'sktree', None) is not None and not rebuilt:       # levels and the remaining points
            self.sktree.redraw()
        for k in range(3):
            self.wp_trees[k].set_values({('wp', k, n): n in self.wstate[k] for n in self.ch.waypoint_ids(k)})
            self.q_trees[k].set_values({('q', k, w): w in self.qstate[k] for _, _, qs, _ in self.ch.quest_acts() for w, _ in qs})
            for _, _, qs, _ in self.ch.quest_acts():
                for w, _ in qs:
                    self.q_trees[k].set_locked(('q', k, w), w in self.qlocked[k])
        self.update_dirty()

    def all_waypoints(self):
        for k in range(3):
            self.wstate[k] = set(self.ch.waypoint_ids(k))
        self.refresh_progress()

    def save_progress(self):
        ch = self.ch
        if not self.st_flush():               # a value still being typed is refused: nothing is written
            return
        # the file may have been written behind this window (the game on save & exit, another program): this
        # build's Character.save would write the copy read earlier over it. Read it again first; the pending
        # edits are kept and go on top of what is in the file now.
        if self.sync_file():
            print('character file changed on disk: read again before SAVE, pending edits applied on top')
            ch = self.ch
        new_name = self.st_name if self.st_name and self.st_name != ch.name else None
        before = ch.level
        try:
            self._extra_call('apply')         # plug-in pages write their pending edits (CharError refuses)
            self.st_commit(ch)                # the stat-screen edits, in the order they were made
            cls_changed = self.pending_cls is not None and self.pending_cls != ch.cls
            if cls_changed:
                ch.set_class(self.pending_cls)    # resets the skills: the old levels are the other class's
                self.pending_cls = None
            elif any(self.sk0.get(sid, 0) != self._level_of(v) for sid, v in self.sk_vars.items()):
                ch.set_skill_levels(self._skills_from_vars())     # only when edited: the section is kept as it is
            prog = ch.progression             # as typed / picked on the stat screen (or untouched)
            typed = any(op[0] in ('prog', 'done') for op in self.st_ops)
            for k in range(3):
                if self.qstate[k] != self.q0[k]:
                    ch.set_quests(k, self.qstate[k])      # follows the act bosses / the last quest (game's rule)
                if self.wstate[k] != self.w0[k]:
                    ch.set_waypoints(k, self.wstate[k])
            if typed and ch.progression != prog:      # a value set by hand in the same save wins over the rule
                ch.set_progression(prog)
        except CharError as e:
            messagebox.showerror(T('ch.title', 'Character'), str(e), parent=self.top)
            self.reload()
            return
        log, ch.reward_log = getattr(ch, 'reward_log', {}), {}
        names = {'skill': (T('he.n_skill1', 'skill point'), T('he.n_skill', 'skill points')),
                 'stats': (T('he.n_stat1', 'stat point'), T('he.n_stat', 'stat points')),
                 'life': (T('he.n_life', 'life'), T('he.n_life', 'life'))}
        rewards = ', '.join(f'{v:+d} {names[k][0] if abs(v) == 1 else names[k][1]}' for k, v in log.items() if v)
        if (self._save_renamed(new_name) if new_name else self._save_undoable(ch)):
            self._init_state()
            self.refresh_progress()
            self.set_bar(T('he.saved_level', '{name} saved: level {level}', name=ch.name, level=ch.level)
                         + (T('he.saved_up', ' (+{n}: stat and skill points to spend in game)', n=ch.level - before)
                            if ch.level > before else '')
                         + (T('he.saved_rewards', ' - quest rewards: {rewards}', rewards=rewards) if rewards else ''))
            self.top.title(f'Median XL Capybara Editor V2 - {ch.name}')
            self._follow_later()

    def _save_undoable(self, ch):
        """SAVE without a rename: one undo step of the main window's Ctrl+Z (mxl_undo 'files': the file's bytes of
        before, refused when the file changed since)."""
        before = None
        try:
            import mxl_undo
            before = mxl_undo.snapshot([ch.path])
        except Exception as e:
            print('character save not undoable:', e)
        ok = self.save(T('he.saved', '{name} saved', name=ch.name))
        if ok and before:
            mxl_undo.record_files(self.app, before, T('undo.char_save', 'SAVE of {name}', name=ch.name))
        return ok

    def _save_renamed(self, new_name):
        """SAVE with a new name: the character (with every pending change) is written as <new name>.d2s through
        mxl_char.Character.rename, its companion files follow, and the main window moves to the renamed files."""
        app, ch = self.app, self.ch
        old = ch.name
        try:
            _dst, bak = ch.rename(new_name, backup=app.needs_backup(ch.path))
        except (CharError, EditError, OSError) as e:
            messagebox.showerror(T('ch.title', 'Character'), str(e), parent=self.top)
            self.reload()
            return False
        self.selected = None
        self.redraw()
        try:                                  # the dropdown lists the new name; its stash is the one shown
            view = app.view.get()
            app.select_character(new_name, view)
            app.open_view(keep_page=True)
        except Exception as e:
            print('main window not moved to the renamed character:', e)
        self.set_status(T('he.renamed', '{old} renamed to {new}', old=old, new=new_name)
                        + (T('cr.backup', ' - backup: {file}', file=os.path.basename(bak)) if bak else ''))
        return True

    def copy_char(self):
        if self.statscreen is not None and not self.statscreen.commit_edit():
            return
        name = self.copy_name.get().strip()
        try:
            dst = MC.copy_character(self.ch.path, name, self.data)
        except (CharError, EditError, OSError) as e:
            messagebox.showerror(T('he.copy_title', 'Copy character'), str(e), parent=self.top)
            return
        self.set_bar(T('he.copied', '{name} copied as {new} ({file}).', name=self.ch.name, new=name, file=os.path.basename(dst)))
        self.app.select_character(self.app.char_combo.get(), self.app.view.get())

    def set_bar(self, text, error=False):
        self.bar_status.configure(text=text, fg='#ff6060' if error else HE_GOLD)


HE_BG = '#f0f0f0'
HE_BTN = '#e1e1e1'
HE_GOLD = '#d8c27a'


class StoneButton(tk.Label):
    """The Hero Editor's own stone button images (normal / hover / pressed)."""

    @staticmethod
    def scale_of(widget):
        """How much larger than its 94x32 pixels a button is drawn: the height of the status text beside it
        (Times New Roman 11 = 17 px at 100 %; it grows with the UI scale / the DPI), in quarter steps; never
        smaller than the original. MXL_BUTTON_SCALE overrides it."""
        try:
            return max(1.0, min(4.0, float(os.environ['MXL_BUTTON_SCALE'])))
        except (KeyError, ValueError):
            pass
        try:
            from tkinter import font as tkfont
            by_font = tkfont.Font(root=widget, font=HE_FONT).metrics('linespace') / 17.0
            by_dpi = widget.winfo_fpixels('1i') / 96.0
            k = by_font if abs(by_font - by_dpi) < 0.4 else by_dpi    # another font family was substituted
        except tk.TclError:
            return 1.0
        return max(1.0, min(4.0, round(k * 4) / 4))

    @staticmethod
    def images(parent, text, k):
        """[normal, hover, pressed] at scale k (1 = the original pixels; otherwise resampled with Lanczos)."""
        import mxl_he_art as A
        if k > 1.01:
            try:
                import base64
                import io
                from PIL import Image, ImageTk
                out = []
                for d in A.BUTTONS[text]:
                    im = Image.open(io.BytesIO(base64.b64decode(d))).convert('RGB')
                    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
                    out.append(ImageTk.PhotoImage(im, master=parent))
                return out
            except Exception as e:
                print('stone buttons not scaled:', e)
        return [tk.PhotoImage(master=parent, data=d) for d in A.BUTTONS[text]]

    def __init__(self, parent, text, command):
        self.scale = self.scale_of(parent)
        self.imgs = self.images(parent, text, self.scale)
        super().__init__(parent, image=self.imgs[0], bd=0, bg='#000000', cursor='hand2', padx=0, pady=0)
        self.command = command
        self.inside = False
        self.bind('<Enter>', lambda e: self._state(1, True))
        self.bind('<Leave>', lambda e: self._state(0, False))
        self.bind('<ButtonPress-1>', lambda e: self.configure(image=self.imgs[2]))
        self.bind('<ButtonRelease-1>', self._release)

    def _state(self, i, inside):
        self.inside = inside
        self.configure(image=self.imgs[i])

    def _release(self, e):
        self.configure(image=self.imgs[1] if self.inside else self.imgs[0])
        if self.inside:
            self.command()


HE_FONT = ('Times New Roman', 11)
HE_FONT_I = ('Times New Roman', 11, 'italic')
HE_FONT_S = ('Times New Roman', 10)


THEMES = {
    False: dict(bg='#f0f0f0', fg='#000000', entry='#ffffff', entry_fg='#000000', btn='#e1e1e1', frame_fg='#000000',
                pane='#ffffff', pane_fg='#000000', tab='#e8e8e8', tab_fg='#000000', tab_sel='#ffffff',
                box_fill='#ffffff', box_mark='#000000', box_dark='#404040', box_mid='#808080', box_light='#d4d0c8',
                part_fill='#ffffff', part_mark='#000000', lock_fill='#b8b8b8', lock_mark='#404040'),
    # the game's own screen: dark stone with gold text
    True: dict(bg='#141008', fg='#d8c27a', entry='#0b0a08', entry_fg='#e0c880', btn='#2a2008', frame_fg='#d8c27a',
               pane='#191208', pane_fg='#e0c880', tab='#2a2008', tab_fg='#d8c27a', tab_sel='#4a3a14',
               box_fill='#0b0a08', box_mark='#d8c27a', box_dark='#5a4a20', box_mid='#8a7a4a', box_light='#c8b478',
               part_fill='#0b0a08', part_mark='#d8c27a', lock_fill='#241d10', lock_mark='#a8945a'),
}


def _paint_box(im, kind, t):
    """Draws a 13x13 check box (kind: off / on / part / lock) into the 15x13 image im, in theme t."""
    fill, mark = {'off': (t['box_fill'], None), 'on': (t['box_fill'], t['box_mark']),
                  'part': (t['part_fill'], t['part_mark']), 'lock': (t['lock_fill'], t['lock_mark'])}[kind]
    im.put(t['pane'], to=(0, 0, 15, 13))
    im.put(t['box_mid'], to=(0, 0, 13, 1))
    im.put(t['box_mid'], to=(0, 0, 1, 13))
    im.put(t['box_dark'], to=(1, 1, 12, 2))
    im.put(t['box_dark'], to=(1, 1, 2, 12))
    im.put(t['pane'], to=(12, 0, 13, 13))
    im.put(t['pane'], to=(0, 12, 13, 13))
    im.put(t['box_light'], to=(11, 1, 12, 12))
    im.put(t['box_light'], to=(1, 11, 12, 12))
    im.put(fill, to=(2, 2, 11, 11))
    if kind == 'part':                       # partly ticked: a filled square, not a tick (it read as all ticked)
        im.put(mark, to=(4, 4, 9, 9))
    elif mark:
        for x, y in ((3, 5), (3, 6), (3, 7), (4, 6), (4, 7), (4, 8), (5, 7), (5, 8), (5, 9), (6, 6), (6, 7),
                     (6, 8), (7, 5), (7, 6), (7, 7), (8, 4), (8, 5), (8, 6), (9, 3), (9, 4), (9, 5)):
            im.put(mark, to=(x, y, x + 1, y + 1))


def _box_images(master, dark=False):
    """Check box images: unchecked, checked, partly checked, locked (checked, grey)."""
    imgs = {k: tk.PhotoImage(master=master, width=15, height=13) for k in ('off', 'on', 'part', 'lock')}
    for k, im in imgs.items():
        _paint_box(im, k, THEMES[dark])
    return imgs


class CheckTree:
    """Tree with check boxes (like the Hero Editor's TreeView): leaves carry a value; a mode / act box shows
    whether everything, nothing or part of what is under it is ticked, and ticks / unticks all of it."""

    def __init__(self, parent, on_change):
        style = ttk.Style()
        from tkinter import font as tkfont
        try:                                         # rows as tall as the text (and the 13 px tick box) needs
            row_h = max(16, tkfont.Font(font=HE_FONT).metrics('linespace') + 3)
        except tk.TclError:
            row_h = 20
        style.configure('HE.Treeview', background='#ffffff', fieldbackground='#ffffff', foreground='#000000',
                        font=HE_FONT, rowheight=row_h, borderwidth=0, indent=20)
        style.map('HE.Treeview', background=[('selected', '#ffffff')], foreground=[('selected', '#000000')])
        style.layout('HE.Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        wrap = tk.Frame(parent, bg='#ffffff', bd=2, relief='sunken')
        self.wrap = wrap
        wrap.pack(fill='both', expand=True)
        self.tv = ttk.Treeview(wrap, show='tree', style='HE.Treeview', selectmode='browse')
        self.tv.column('#0', width=150, minwidth=150, stretch=True)   # asks for little, takes what the column has
        sb = ttk.Scrollbar(wrap, orient='vertical', command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.img = _box_images(parent)
        self.on_change = on_change
        self.keys = {}          # iid -> key (leaves)
        self.iids = {}          # key -> iid
        self.value = {}         # iid -> bool (leaves)
        self.locked = set()
        self.tv.bind('<Button-1>', self.on_click)
        self.tv.bind('<space>', lambda e: self.toggle(self.tv.focus()))

    def add(self, parent, text, key=None, locked=False):
        iid = self.tv.insert(parent, 'end', text=' ' + text, image=self.img['off'])
        if key is not None:
            self.keys[iid] = key
            self.iids[key] = iid
            self.value[iid] = False
            if locked:
                self.locked.add(iid)
        return iid

    def set_theme(self, dark):
        t = THEMES[dark]
        style = ttk.Style()
        style.configure('HE.Treeview', background=t['pane'], fieldbackground=t['pane'], foreground=t['pane_fg'])
        style.map('HE.Treeview', background=[('selected', t['pane'])], foreground=[('selected', t['pane_fg'])])
        self.wrap.configure(bg=t['pane'])
        for k, im in self.img.items():
            _paint_box(im, k, t)

    def open(self, iid):
        self.tv.item(iid, open=True)

    def leaves(self, iid):
        if iid in self.keys:
            return [iid]
        out = []
        for c in self.tv.get_children(iid):
            out += self.leaves(c)
        return out

    def set_values(self, values):
        for key, v in values.items():
            iid = self.iids.get(key)
            if iid is not None:
                self.value[iid] = bool(v) or iid in self.locked
        self.paint()

    def set_locked(self, key, locked):
        iid = self.iids.get(key)
        if iid is None:
            return
        (self.locked.add if locked else self.locked.discard)(iid)
        if locked:
            self.value[iid] = True
        self.paint()

    def paint(self, iid=''):
        for c in self.tv.get_children(iid):
            if c in self.keys:
                img = 'lock' if c in self.locked else ('on' if self.value[c] else 'off')
            else:
                self.paint(c)
                vals = [self.value[l] for l in self.leaves(c)]
                img = 'on' if vals and all(vals) else ('part' if any(vals) else 'off')
            self.tv.item(c, image=self.img[img])

    def toggle(self, iid):
        if not iid:
            return
        leaves = [l for l in self.leaves(iid) if l not in self.locked]
        if not leaves:
            return
        new = not all(self.value[l] for l in leaves)
        for l in leaves:
            if self.value[l] != new:
                self.value[l] = new
                self.on_change(self.keys[l], new)
        self.paint()

    def on_click(self, ev):
        iid = self.tv.identify_row(ev.y)
        if not iid:
            return
        elem = self.tv.identify_element(ev.x, ev.y)
        if 'image' in elem:
            self.tv.focus(iid)
            self.tv.selection_set(iid)
            self.toggle(iid)
            return 'break'


def install(App):
    original = App._build

    def _build(self):
        original(self)
        top = self.btn_library.master
        bar = ttk.Frame(top)
        bar.pack(side='left', padx=(6, 0))
        ttk.Button(bar, text=T('ch.title', 'Character'), command=lambda: CharacterWindow(self, 'stats')).pack(side='left', padx=2)

    App._build = _build
