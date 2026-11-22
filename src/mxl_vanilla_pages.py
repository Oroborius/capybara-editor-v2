"""Character window page "Stash / Cube / Belt" for folder profiles (vanilla Diablo II): the character file's own
personal stash (panel 5), Horadric Cube (panel 4) and belt (location 2), in the game's grid sizes from the
profile's inventory.bin (stash 6 x 8 in LoD 1.10-1.14d, 6 x 4 for a classic character; cube 3 x 4) and belts.bin
(rows of the equipped belt), with the inventory under them: items move between the stash, the cube and the
inventory, socket fillers drop into sockets, right-click gives the Socket submenu (each write one Ctrl+Z step);
the belt is shown only. Median XL keeps its own stash files: install() registers nothing there.

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


class _Win:
    """The Character window as the item actions (mxl_socket_insert / mxl_socket_menu / mxl_rc_menu) see it from
    this page: entry_at hit-tests the page's grids, is_merc() is False (these grids are the character's own),
    the status goes to the page's line too; everything else is the window."""

    def __init__(self, page):
        object.__setattr__(self, '_page', page)
        object.__setattr__(self, '_win', page.win)

    def __getattr__(self, name):
        return getattr(self._win, name)

    def __setattr__(self, name, value):
        setattr(self._win, name, value)

    def is_merc(self):
        return False

    def entry_at(self, cv, ev):
        key = next((k for k, c in self._page.canvases.items() if c is cv), None)
        return (self._page.entry_at(key, ev.x, ev.y) if key else None), None

    def set_status(self, text, error=False):
        self._page.set_status(text, error)
        try:
            self._win.set_status(text, error)
        except Exception:
            pass


class ContainersPage:
    """The character's stash, cube and belt, with its inventory under them. Items move by drag and drop between
    the stash, the cube and the inventory (one write of the character, one Ctrl+Z step); a gem / rune / jewel
    dropped on an item goes into its socket (mxl_socket_insert); right-click: the Socket submenu
    (mxl_socket_menu). The belt is shown only. Items outside a grid (hacked saves) are listed under it."""

    def __init__(self, win, frame):
        self.win, self.frame = win, frame
        self.cell = 30
        self.icons = {}
        self.canvases = {}
        self.hits = {}
        self.frames = {}
        self.drag = None
        self._sig = None
        body = ttk.Frame(frame, padding=4)
        body.pack(fill='both', expand=True)
        self.body = body
        self.note = ttk.Label(body, text=T('van.note2', 'The character file\'s own stash, cube and belt. Drag items '
                                           'between the stash, the cube and the inventory; drop a gem, rune or jewel '
                                           'on an item to socket it; right-click: Socket. Hover an item to see it.'),
                              justify='left', wraplength=520)
        self.note.pack(anchor='w')
        self.row = ttk.Frame(body)
        self.row.pack(anchor='nw', fill='x', pady=(4, 0))
        self.row2 = ttk.Frame(body)
        self.row2.pack(anchor='nw', fill='x', pady=(6, 0))
        self.status = ttk.Label(body, text='', justify='left', wraplength=520)
        self.status.pack(anchor='w', pady=(4, 0))
        self.refresh()

    def as_win(self):
        return _Win(self)

    def set_status(self, text, error=False):
        try:
            self.status.configure(text=text, foreground='#e06060' if error else '')
        except tk.TclError:
            pass

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

    def _boxes(self, ch, d):
        import mxl_char
        return containers(ch, d) + [('inv', T('ch.inventory_t', 'Inventory'), mxl_char.INV_W, mxl_char.INV_H,
                                     ch.inventory())]

    def _build(self, boxes):
        """The grids' widgets, made again only when their sizes change: a refresh in the middle of a drag (the
        file read again on the press) keeps the canvas that gets the release."""
        for row in (self.row, self.row2):
            for w in row.winfo_children():
                w.destroy()
        self.canvases, self.frames = {}, {}
        c = self.cell
        for key, title, cols, rows, _e in boxes:
            fr = ttk.Frame(self.row2 if key == 'inv' else self.row)
            fr.pack(side='left', anchor='nw', padx=(0, 10))
            lab = ttk.Label(fr, text=f'{title} ({cols} x {rows})')
            lab.pack(anchor='w')
            cv = tk.Canvas(fr, width=cols * c + 1, height=rows * c + 1, bg='#101010', highlightthickness=0)
            cv.pack(anchor='nw')
            out = ttk.Label(fr, text='', wraplength=max(120, cols * c))
            out.pack(anchor='w')
            cv.bind('<Motion>', lambda ev, k=key: self._hover(k, ev))
            cv.bind('<Button-1>', lambda ev, k=key: self.on_press(k, ev))
            cv.bind('<B1-Motion>', self.on_drag)
            cv.bind('<ButtonRelease-1>', self.on_release)
            cv.bind('<ButtonRelease-3>', lambda ev, k=key: self.on_menu(k, ev))
            self.canvases[key], self.frames[key] = cv, (fr, out)

    def refresh(self):
        self.hits = {}
        ch, d = self.win.ch, self.win.data
        if ch is None:
            return
        try:
            boxes = self._boxes(ch, d)
        except Exception as err:
            for row in (self.row, self.row2):
                for w in row.winfo_children():
                    w.destroy()
            self.canvases, self._sig = {}, None
            ttk.Label(self.row, text=f'{type(err).__name__}: {err}').pack(anchor='w')
            return
        sig = tuple((k, cols, rows) for k, _t, cols, rows, _e in boxes)
        if sig != self._sig or any(not cv.winfo_exists() for cv in self.canvases.values()):
            self._build(boxes)
            self._sig = sig
        c = self.cell
        sel = getattr(self.win, 'selected', None)
        for key, _title, cols, rows, entries in boxes:
            cv = self.canvases[key]
            cv.delete('all')
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
                cv.create_rectangle(x0 + 1, y0 + 1, x0 + w * c - 1, y0 + h * c - 1, fill='#1c2a40',
                                    outline='#d4b062' if e is sel else '', width=2 if e is sel else 0)
                img = self._icon(it, '#1c2a40')
                if img is not None:
                    cv.create_image(x0 + w * c / 2, y0 + h * c / 2, image=img)
                else:
                    cv.create_text(x0 + w * c / 2, y0 + h * c / 2, text=it['code'].strip(), fill='#c0c0c0')
                hits.append((x, y, w, h, e))
            self.frames[key][1].configure(text=T('van.outside', 'outside the grid: {items}', items=', '.join(
                e.it.get('name') or e.it['code'] for e in outside)) if outside else '')
            self.hits[key] = hits

    def entry_at(self, key, x, y):
        c = self.cell
        cx, cy = x // c, y // c
        for x0, y0, w, h, e in self.hits.get(key, ()):
            if x0 <= cx < x0 + w and y0 <= cy < y0 + h:
                return e
        return None

    def _hover(self, key, ev):
        if self.drag is not None:
            return
        e = self.entry_at(key, ev.x, ev.y)
        try:
            self.win.panel.show(e.it if e is not None else None)
        except Exception:
            pass

    # ------------------------------------------------------------------ mouse
    def _pick(self, key, ev):
        """The entry under the pointer in the file as it is now (the window reads it again when someone else
        wrote it; the grids are drawn again then)."""
        try:
            self.win.sync_file()
        except Exception as err:
            print('stash page sync:', err)
        cv = self.canvases.get(key)
        if cv is None:
            return None
        return self.entry_at(key, ev.x_root - cv.winfo_rootx(), ev.y_root - cv.winfo_rooty())

    def on_press(self, key, ev):
        self.drag = None
        e = self._pick(key, ev)
        self.win.selected = e
        if e is not None and key != 'belt':
            c = self.cell
            self.drag = dict(entry=e, key=key, dx=ev.x // c - e.it['x'], dy=ev.y // c - e.it['y'], moved=False)
        self.refresh()
        try:
            self.win.panel.show(e.it if e is not None else None)
        except Exception:
            pass

    def on_drag(self, _ev):
        if self.drag:
            self.drag['moved'] = True
            try:
                self.frame.configure(cursor='fleur')
            except tk.TclError:
                pass

    def target(self, x_root, y_root):
        """(key, canvas, x, y) of the grid under a screen point, or None."""
        for key, cv in self.canvases.items():
            try:
                x, y = x_root - cv.winfo_rootx(), y_root - cv.winfo_rooty()
                if 0 <= x < cv.winfo_width() and 0 <= y < cv.winfo_height():
                    return key, cv, x, y
            except tk.TclError:
                continue
        return None

    def on_release(self, ev):
        try:
            self.frame.configure(cursor='')
        except tk.TclError:
            pass
        d, self.drag = self.drag, None
        if not d or not d['moved']:
            return
        t = self.target(ev.x_root, ev.y_root)
        if t is None:
            return
        key, cv, x, y = t
        import mxl_char as MC
        e, win = d['entry'], self.win
        name = e.it.get('name') or e.it['code']
        try:
            import mxl_undo
            before = mxl_undo.snapshot([win.ch.path])
        except Exception as err:
            print('stash page: move not undoable:', err)
            before = None
        done = False
        try:
            done = self._drop(d, key, cv, x, y)
        finally:
            if done and before:
                try:
                    import mxl_undo
                    if mxl_undo.record_files(win.app, before, _clean(name)):
                        self.set_status(self.status.cget('text') + T('undo.move_hint', ' - Ctrl+Z moves it back'))
                except Exception as err:
                    print('stash page: undo not recorded:', err)
        return done

    def _drop(self, d, key, cv, x, y):
        """True when the character file was written."""
        import mxl_char as MC
        e, win, c = d['entry'], self.win, self.cell
        adapter = self.as_win()
        fake = type('E', (), {'x': x, 'y': y, 'x_root': cv.winfo_rootx() + x, 'y_root': cv.winfo_rooty() + y})()
        raw = bytes(win.ch.raw)
        try:                                              # a gem / rune / jewel onto an item: into its socket
            import mxl_socket_insert
            if mxl_socket_insert.char_tab_drop(adapter, e, cv, fake):
                self.refresh()
                return bytes(win.ch.raw) != raw
        except Exception as err:
            print('socket insert:', err)
        gx, gy = x // c - d['dx'], y // c - d['dy']
        if key == 'belt':
            self.set_status(T('van.belt_ro', 'The belt is shown only: potions go there in the game.'), True)
            return False
        where = ('inv', gx, gy) if key == 'inv' else ('store', PANEL_CUBE if key == 'cube' else PANEL_STASH, gx, gy)
        if MC.where_of(e) == where:
            return False
        if key == 'cube' and e.it['code'] == CUBE_CODE:
            self.set_status(T('van.cube_in_cube', 'The Horadric Cube cannot go into itself.'), True)
            return False
        try:
            win.ch.move(e, where, False)
        except MC.CharError as err:
            self.set_status(T('inv.cannot_drop', 'Cannot drop here: {error}', error=err), True)
            win.reload()
            return False
        msg = T('ch.moved', '{item} moved', item=_clean(e.it['name']))
        if not win.save(msg):
            return False
        self.set_status(msg)
        return True

    def on_menu(self, key, ev):
        """Right-click on an item: the Socket submenu (Add Sockets / Remove Sockets / Unsocket)."""
        e = self._pick(key, ev)
        if e is None:
            return
        self.win.selected = e
        self.refresh()
        menu = tk.Menu(self.canvases.get(key) or self.frame, tearoff=0)
        try:
            import mxl_socket_menu
            win = self.as_win()
            sub = mxl_socket_menu.add_menu(win, menu, win=win, e=e)
        except Exception as err:
            print('stash page socket menu:', err)
            sub = None
        if sub is None:
            return
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            menu.grab_release()


CUBE_CODE = 'box '


def _clean(name):
    try:
        from mxl_creator_gui import clean
        return clean(name)
    except Exception:
        return name


def panel_size(ch, panel):
    """mxl_char.PANEL_SIZE for folder profiles: the cube's / personal stash's grid of this character."""
    key = {PANEL_CUBE: 'cube', PANEL_STASH: 'stash'}.get(panel)
    if key is None:
        return None
    for k, _t, cols, rows, _e in containers(ch, ch.data):
        if k == key:
            return cols, rows
    return None


def install():
    """Registers the page in folder profiles only (before the Character window is built)."""
    import mxl_profile
    if mxl_profile.is_median():
        return
    import mxl_char
    mxl_char.PANEL_SIZE = panel_size
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
    install_aura_levels()


AURA_STAT = 151


def merge_auras(stats):
    """One item_aura (151) line per aura with the levels added: the parent's and every socketed jewel's lines
    (the game adds them, mxl_mock.totals' aura_lv). The host printed the level of one line only."""
    out, at = [], {}
    for s in stats or ():
        if isinstance(s, dict) and s.get('id') == AURA_STAT:
            k = s.get('param')
            if k in at:
                d = out[at[k]]
                out[at[k]] = dict(d, value=(d.get('value') or 0) + (s.get('value') or 0))
                continue
            at[k] = len(out)
        out.append(s)
    return out


def install_aura_levels():
    import sys
    import mxl_stat_text
    orig = mxl_stat_text.stat_lines
    if getattr(orig, '_capy_aura', False):
        return

    def stat_lines(stats, *a, **k):
        try:
            stats = merge_auras(stats)
        except Exception:
            pass
        return orig(stats, *a, **k)
    stat_lines._capy_aura = True
    for name in ('mxl_stat_text', 'mxl_tooltip', 'mxl_gui_detail', 'mxl_catalog_tooltip'):
        m = sys.modules.get(name)
        if m is not None and getattr(m, 'stat_lines', None) is orig:
            m.stat_lines = stat_lines


# ---------------------------------------------------------------------------------------- main window stash pane
def stash_view(ch, data):
    """(cols, rows, [item dict]) of the character's personal stash for the main window's grid: copies with
    page 0 (the collector's grid draws one page); items outside the grid are left out (the Character window's
    page lists them)."""
    cols, rows, pairs = stash_pairs(ch, data)
    return cols, rows, [it for it, _e in pairs]


def stash_pairs(ch, data):
    """(cols, rows, [(item dict, Entry)]) behind stash_view: the Entry gives the item's bytes (Ctrl+C)."""
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
            items.append((dict(it, page=0), e))
    return cols, rows, items


def readonly_text():
    """Why the main window's stash pane takes no drop / paste / delete in a folder profile."""
    return T('van.stash_readonly', "the 1.14d stash is part of the character: edit it on the character's "
             'Stash / Cube / Belt page')


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
    o_lang = getattr(App, 'change_language', None)

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
        self.van_ch, self.van_entries = None, {}
        if os.path.exists(cf):
            try:
                import mxl_char
                self.van_ch = mxl_char.Character(cf, self.data)
                cols, rows, pairs = stash_pairs(self.van_ch, self.data)
                items = [it for it, _e in pairs]
                self.van_entries = {id(it): e for it, e in pairs}
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
        self.van_dims = (cols, rows)
        retitle(self)
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

    def retitle(self):
        cols, rows = getattr(self, 'van_dims', None) or (mxl_gui.COLS, mxl_gui.ROWS)
        try:
            self.van_title.configure(text=T('van.main_stash', 'Stash ({cols} x {rows}) - shown, not edited here',
                                            cols=cols, rows=rows))
        except Exception:
            pass

    def change_language(self, *a, **k):
        result = o_lang(self, *a, **k)
        retitle(self)                                 # a text with fields: mxl_lang.retranslate leaves it
        return result

    App._build, App.open_view, App.show_status = _build, open_view, show_status
    App.on_click, App.watch_files = on_click, watch_files
    if o_lang is not None:
        App.change_language = change_language
    install_main_readonly()


def _readonly(app):
    """The main window shows the read-only view (no stash file)."""
    return not getattr(app, 'path', None) and getattr(app, 'van_entries', None) is not None


def _say(app, msg):
    try:
        app.status.configure(text=msg)
    except Exception:
        pass


def install_main_readonly():
    """The stash writers that act on the pane, on the read-only view: a drop says why it is refused
    (readonly_text), Ctrl+C / Ctrl+Shift+C copy from the view (the character file's bytes), Ctrl+V /
    Ctrl+Shift+V / Delete are refused with the same text, the right-click menu is not offered."""
    import types
    import mxl_inv_gui
    import mxl_rc_menu
    import mxl_undo
    o_menu, o_hot, o_del = mxl_rc_menu._stash_menu, mxl_rc_menu._stash_hot, mxl_undo.delete_item
    o_target = mxl_inv_gui.MainInventory.stash_target

    def _stash_menu(app, ev):
        if app.path is None:
            return None
        return o_menu(app, ev)

    def stash_target(self, x_root, y_root, it, dx, dy):
        t = o_target(self, x_root, y_root, it, dx, dy)
        if t is not None and _readonly(self.app):
            return t[0], t[1], readonly_text()
        return t

    def _stash_hot(app, what):
        if not _readonly(app):
            return o_hot(app, what)
        ev = mxl_rc_menu._canvas_at_pointer([app.canvas])
        if ev is None:
            return
        if what in ('paste', 'magic_paste'):
            _say(app, readonly_text())
            return
        try:
            it = app.item_at(ev)
        except Exception:
            it = None
        e = app.van_entries.get(id(it)) if it is not None else None
        if e is None or app.van_ch is None:
            _say(app, mxl_rc_menu.rc('hot.none', 'no item under the mouse cursor'))
            return
        name = mxl_rc_menu.clean_name(None, e)
        if what == 'copy':
            try:
                app._capy_clip = (app.van_ch.stash_blob(e), name)
            except Exception as err:
                _say(app, f'{type(err).__name__}: {err}')
                return
            _say(app, mxl_rc_menu.rc('copied', '{name} copied (right-click an empty cell to paste it)',
                                     name=name))
        elif what == 'magic_copy':
            win = types.SimpleNamespace(ch=app.van_ch, app=app, set_status=lambda m, error=False: _say(app, m))
            mxl_rc_menu._add_magic_to_buffer(app, None, win=win, e=e)

    def delete_item(app, it):
        if it is not None and _readonly(app):
            _say(app, readonly_text())
            return
        return o_del(app, it)

    mxl_rc_menu._stash_menu, mxl_rc_menu._stash_hot, mxl_undo.delete_item = _stash_menu, _stash_hot, delete_item
    mxl_inv_gui.MainInventory.stash_target = stash_target


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
