"""Personal item library: items kept as .d2i files in <user dir>/library/, with an index (index.json).

- right-click an item -> "Add to library...": its exact bytes (socketed items included, the same bytes as Export
  item...) go into the folder under a name ("Folder/Name" puts it in a folder);
- the Library main tab (More » "Item library..." selects it): the list (icon, name, folder, base) with a search box; "Place a copy" puts a copy on
  the stash page shown (else the first page with room) through the collector's safe writer (edit_stash: verified
  write, backup policy) and records it for Ctrl+Z; Rename / Delete edit the entry.
Each entry records its game (game_tag: 'median' / 'd2-1.14d'); the list shows the current game's only (entries
without a tag were made in Median XL; an entry whose base the game's tables do not know is left out too).
This is not the collector's old library.json (a record of found uniques, removed in V2): other file, other folder.
A copy keeps the item's bytes as they are, the same as Duplicate does.
"""
import json
import os
import re
import time

import tkinter as tk
from tkinter import ttk

from mxl_lang import T

INDEX = 'index.json'


def tr(key, default, **fields):
    return T('lib.' + key, default, **fields)


def folder():
    import paths
    d = os.path.join(paths.USER_DIR, 'library')
    os.makedirs(d, exist_ok=True)
    return d


def load():
    """[entry]: dict(file, name, folder, code, added)."""
    try:
        with open(os.path.join(folder(), INDEX), encoding='utf-8') as f:
            out = json.load(f).get('items', [])
        return [e for e in out if isinstance(e, dict) and e.get('file')]
    except (OSError, ValueError, AttributeError):
        return []


def game_tag():
    """Stock games share a version tag. Mods use the profile id because their tables can differ by folder."""
    try:
        import mxl_profile
        st = mxl_profile.active()
    except Exception:
        st = None
    if not st:
        return 'median'
    if st.get('mod'):
        return st['id']
    return f"{st.get('kind') or 'd2'}-{st.get('version') or 'unknown'}"


def entry_game(entry):
    """The game of an entry; the ones made before the tag existed were made in Median XL."""
    return entry.get('game') or 'median'


def for_game(entries, data=None, tag=None):
    """The entries of the current game: its tag, and (with data) a base code the game's tables know."""
    tag = tag or game_tag()
    out = []
    for e in entries:
        if entry_game(e) != tag:
            continue
        if data is not None:
            try:
                if e.get('code') not in data.bases:
                    continue
            except Exception:
                pass
        out.append(e)
    return out


def _save(entries):
    p = os.path.join(folder(), INDEX)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'items': entries}, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def _split(text):
    text = (text or '').strip().replace('\\', '/')
    if '/' in text:
        fo, name = text.rsplit('/', 1)
        return fo.strip(' /'), name.strip()
    return '', text


def add(blob, name, data, code=None):
    """Stores an item; returns its entry. The blob is checked first (it must read as an item)."""
    from mxl_save import blob_item
    blob = bytes(blob)
    it = blob_item(blob, data)
    fo, nm = _split(name)
    nm = nm or it.get('name') or it['code']
    stem = re.sub(r'[^A-Za-z0-9_.-]+', '_', nm).strip('_')[:40] or 'item'
    d = folder()
    file = stem + '.d2i'
    k = 1
    while os.path.exists(os.path.join(d, file)):
        k += 1
        file = f'{stem}_{k}.d2i'
    with open(os.path.join(d, file), 'wb') as f:
        f.write(blob)
    entry = dict(file=file, name=nm, folder=fo, code=code or it['code'], added=time.strftime('%Y-%m-%d %H:%M'),
                 game=game_tag())
    entries = load()
    entries.append(entry)
    _save(entries)
    _refresh_open()
    return entry


def _refresh_open():
    """A built Library tab shows an added item at once."""
    try:
        import mxl_tabs
        w = mxl_tabs.built_owner('Library')
        if w is not None and w.top.winfo_exists():
            w.refresh()
    except Exception:
        pass


def blob_of(entry):
    with open(os.path.join(folder(), entry['file']), 'rb') as f:
        return f.read()


def rename(entry, text):
    entries = load()
    for e in entries:
        if e['file'] == entry['file']:
            e['folder'], e['name'] = _split(text)
            if not e['name']:
                return False
            _save(entries)
            entry.update(e)
            return True
    return False


def delete(entry):
    entries = [e for e in load() if e['file'] != entry['file']]
    _save(entries)
    try:
        os.remove(os.path.join(folder(), entry['file']))
    except OSError:
        pass


def search(entries, text):
    text = (text or '').strip().lower()
    if not text:
        return list(entries)
    return [e for e in entries if text in ' '.join((e.get('name', ''), e.get('folder', ''), e.get('code', ''))).lower()]


# ------------------------------------------------------------------ actions
_last_msg = [None]                                  # the Library page repeats why a placement failed


def _status(app, msg, error=False):
    _last_msg[0] = msg
    try:
        app.show_status(msg)
    except Exception:
        try:
            app.status.configure(text=msg)
        except Exception:
            pass


def ask_add(owner, blob, data, default_name):
    """Asks the name ("Folder/Name") and stores the item. The entry, or None when cancelled / failed."""
    from tkinter import simpledialog, messagebox
    name = simpledialog.askstring(tr('add.title', 'Add to library'),
                                  tr('add.ask', 'Name (Folder/Name puts it into a folder):'),
                                  initialvalue=default_name, parent=owner)
    if not name or not name.strip():
        return None
    try:
        return add(blob, name, data)
    except Exception as e:
        messagebox.showerror(tr('add.title', 'Add to library'), str(e), parent=owner)
        return None


def _place_on_character(app, entry):
    """In the vanilla profile (no stash file: the stash is part of the .d2s) a copy goes into the inventory of the
    character open on the Character tab and is saved there. Returns ('inv', x, y), None when it failed (the status
    bar says why), or False when this does not apply (not vanilla / no character open)."""
    try:
        import mxl_profile
        if mxl_profile.is_median():
            return False
        import mxl_tabs
        cw = mxl_tabs.built_owner('Character')
    except Exception:
        return False
    ch = getattr(cw, 'ch', None) if cw is not None else None
    if ch is None:
        _status(app, tr('err.nochar', 'Open a character first: in 1.14d library items go into its inventory'), True)
        return None
    from mxl_save import blob_item
    try:
        blob = blob_of(entry)
        spot = ch.free_inventory_spot(blob_item(blob, app.data))
        if spot is None:
            _status(app, T('ch.err.inv_full', 'no free place in the inventory'), True)
            return None
        ch.place(blob, ('inv',) + tuple(spot))
    except Exception as e:
        _status(app, str(e), True)
        return None
    if not cw.save(tr('placed_char', '{name} placed in the inventory ({x}, {y})', name=entry['name'], x=spot[0], y=spot[1])):
        return None
    try:
        cw.reload()
    except Exception:
        pass
    return ('inv',) + tuple(spot)


def place_copy(app, entry):
    """A copy of the entry on the stash page shown (else the first page with room). Returns (page, x, y)."""
    from mxl_save import blob_item, parse_stash, free_spot, edit_stash, EditError, STASH_PAGES
    from mxl_format import FormatError
    if not getattr(app, 'path', None):
        placed = _place_on_character(app, entry)       # 1.14d: no stash file - the open character's inventory
        if placed is not False:
            return placed
        _status(app, tr('err.nostash', 'Open a stash first'), True)
        return None
    try:
        blob = blob_of(entry)
        probe = blob_item(blob, app.data)
        cur = app.page()
        items = parse_stash(app.path, app.data)
        spot = free_spot(items, probe, app.data, [cur] + [p for p in range(STASH_PAGES) if p != cur])
        if spot is None:
            _status(app, T('rc.err.nofree', 'no free place in the stash'), True)
            return None
        bak = edit_stash(app.path, app.data, insert=[(spot[0], spot[1], spot[2], blob)],
                         backup=app.needs_backup(app.path))
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return None
    app.backup_made(app.path, bak)
    try:
        import mxl_undo
        mxl_undo.record(app, 'create', spots=[tuple(spot)], name=entry['name'])
    except Exception:
        pass
    from mxl_creator_gui import _reload_main
    _reload_main(app, tuple(spot))
    _status(app, tr('placed', '{name} placed: page {page} ({x}, {y}){bak}', name=entry['name'], page=spot[0] + 1,
                    x=spot[1], y=spot[2], bak=(' - backup ' + os.path.basename(bak) if bak else '')))
    return tuple(spot)


# ------------------------------------------------------------------ the Library tab
def _dark():
    try:
        import mxl_d2_theme as D
        return D.dark()
    except Exception:
        return False


class LibraryWindow:
    """The Library main tab: search + folders / items (icons) on the left, the selected item's tooltip on the
    right, Place a copy / Rename / Delete / Inspect in Bit editor. Without the tabs (not installed) a Toplevel."""
    ICON = 32

    def __init__(self, app):
        self.app = app
        master = app.root if hasattr(app, 'root') else app.canvas
        top = None
        try:
            import mxl_tabs
            if mxl_tabs._state.get('nb') is not None:
                top = mxl_tabs.host_window(app, 'Library', owner=self, replace=True)
        except Exception:
            top = None
        if top is None:
            top = tk.Toplevel(master)
        self.top = top
        top.title(tr('title', 'Item library'))
        self.icons = {}
        self.rows = {}
        dark = _dark()
        bar = tk.Frame(top)
        bar.pack(side='bottom', fill='x', padx=2, pady=2)
        self.b_place = tk.Button(bar, text=tr('place', 'Place a copy'), command=self.place)
        self.b_place.pack(side='left', padx=2)
        tk.Button(bar, text=tr('rename', 'Rename...'), command=self.rename).pack(side='left', padx=2)
        tk.Button(bar, text=tr('delete', 'Delete'), command=self.delete).pack(side='left', padx=2)
        tk.Button(bar, text=tr('inspect', 'Inspect in Bit editor'), command=self.inspect).pack(side='left', padx=2)
        self.status = tk.Label(bar, text='', anchor='w')
        self.status.pack(side='left', fill='x', expand=True, padx=4)
        pw = ttk.PanedWindow(top, orient='horizontal')
        pw.pack(fill='both', expand=True)
        left = tk.Frame(pw)
        right = tk.Frame(pw)
        pw.add(left, weight=3)
        pw.add(right, weight=2)
        row = tk.Frame(left)
        row.pack(fill='x', padx=2, pady=2)
        tk.Label(row, text=tr('search', 'Search:')).pack(side='left')
        self.q = tk.StringVar()
        tk.Entry(row, textvariable=self.q, width=18).pack(side='left', fill='x', expand=True, padx=2)
        self.q.trace_add('write', lambda *_a: self.refresh())
        try:
            ttk.Style(top).configure('CapyLib.Treeview', rowheight=self.ICON + 4)
        except tk.TclError:
            pass
        body = tk.Frame(left)
        body.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(body, columns=('base',), style='CapyLib.Treeview', height=8)
        self.tree.heading('#0', text=tr('c.name', 'Name'))
        self.tree.heading('base', text=tr('c.base', 'Base'))
        self.tree.column('#0', width=220)
        self.tree.column('base', width=110)
        sy = ttk.Scrollbar(body, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sy.set)
        sy.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda _e: self.place())
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self.show())
        bg, fg = ('#141112', '#c7b377') if dark else ('white', 'black')
        try:
            det = app.detail
            bg, fg, font = det.cget('bg'), det.cget('fg'), det.cget('font')
        except Exception:
            font = 'TkDefaultFont'
        dsy = ttk.Scrollbar(right, orient='vertical')
        self.detail = tk.Text(right, width=28, wrap='word', bg=bg, fg=fg, bd=0, padx=6, pady=6, font=font,
                              cursor='arrow', highlightthickness=0, yscrollcommand=dsy.set)
        dsy.configure(command=self.detail.yview)
        dsy.pack(side='right', fill='y')
        self.detail.pack(fill='both', expand=True)
        self.panel = None
        try:
            from mxl_creator_gui import PreviewPanel, PreviewHost, setup_detail_tags
            setup_detail_tags(self.detail)
            self.panel = PreviewPanel(self.detail, PreviewHost(app))
        except Exception as e:
            print('library: tooltip panel disabled:', e)
        self.refresh()

    def _icon(self, entry):
        if entry['file'] in self.icons:
            return self.icons[entry['file']]
        img = None
        try:
            from PIL import Image, ImageTk
            from mxl_gfx import icon_layers
            from mxl_save import blob_item
            from paths import ICONS_DIR
            it = blob_item(blob_of(entry), self.app.data)
            import mxl_vanilla_he as V
            on = V.active()
            if on:
                it = V.picture_item(it)
            layers = icon_layers(it, self.app.data, (20, 16, 16), ICONS_DIR)
            im = layers.get(1) if layers else None
            if im is not None and on:           # sockets and the socketed items, as in the inventory
                for layer in (2, 3):
                    if layers.get(layer) is not None:
                        im.alpha_composite(layers[layer])
            if im is not None:
                f = self.ICON / max(im.width, im.height)
                im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)
                img = ImageTk.PhotoImage(im)
        except Exception:
            img = None
        self.icons[entry['file']] = img
        return img

    def _base(self, entry):
        try:
            return self.app.data.base(entry['code']).name
        except Exception:
            return entry.get('code', '')

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        folders = {}
        first = None
        mine = for_game(load(), getattr(self.app, 'data', None))        # this game's entries only
        for e in sorted(search(mine, self.q.get()), key=lambda e: (e.get('folder', '').lower(), e['name'].lower())):
            parent = ''
            fo = e.get('folder', '')
            if fo:
                if fo not in folders:
                    folders[fo] = self.tree.insert('', 'end', text=' ' + fo + '/', open=True, values=('',))
                parent = folders[fo]
            kw = {}
            img = self._icon(e)
            if img is not None:
                kw['image'] = img
            iid = self.tree.insert(parent, 'end', text=' ' + e['name'], values=(self._base(e),), **kw)
            self.rows[iid] = e
            first = first or iid
        if first is not None and not (self.tree.selection() and self.tree.selection()[0] in self.rows):
            self.tree.selection_set(first)
        self.show()

    def current(self):
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def show(self):
        """The selected entry's tooltip (the main window's detail panel, read only) in the right pane."""
        e = self.current()
        try:
            self.detail.configure(state='normal')
            self.detail.delete('1.0', 'end')
        except tk.TclError:
            return
        if e is None:
            return
        try:
            from mxl_save import blob_item
            it = blob_item(blob_of(e), self.app.data)
            import mxl_vanilla_he as V
            it = V.description_item(V.picture_item(it))
            if self.panel is None:
                raise RuntimeError('no panel')
            self.panel.show(it)
        except Exception:
            try:
                import mxl_inspect
                self.detail.delete('1.0', 'end')
                self.detail.insert('1.0', mxl_inspect.dump(blob_of(e), self.app.data, e['name']))
            except Exception as err:
                self.detail.insert('1.0', str(err))

    def place(self):
        e = self.current()
        if e is not None:
            _last_msg[0] = None
            r = place_copy(self.app, e)
            if not r:
                text = _last_msg[0] or ''
            elif r[0] == 'inv':                         # 1.14d: into the open character's inventory
                text = tr('placed.inv', 'placed in the inventory ({x}, {y})', x=r[1], y=r[2])
            else:
                text = tr('placed.short', 'placed: page {page} ({x}, {y})', page=r[0] + 1, x=r[1], y=r[2])
            self.status.configure(text=text)

    def inspect(self):
        e = self.current()
        if e is not None:
            import mxl_bitedit
            mxl_bitedit.open_item(self.app, blob_of(e), e['name'], source=None,
                                 reason=tr('ro', 'library item: read only here'))

    def rename(self):
        from tkinter import simpledialog
        e = self.current()
        if e is None:
            return
        cur = (e.get('folder') + '/' if e.get('folder') else '') + e['name']
        text = simpledialog.askstring(tr('rename.title', 'Rename'), tr('add.ask', 'Name (Folder/Name puts it into a folder):'),
                                      initialvalue=cur, parent=self.top)
        if text and text.strip():
            rename(e, text)
            self.refresh()

    def delete(self):
        from tkinter import messagebox
        e = self.current()
        if e is None:
            return
        if messagebox.askyesno(tr('delete', 'Delete'), tr('delete.ask', 'Remove {name} from the library?', name=e['name']),
                               parent=self.top):
            delete(e)
            self.refresh()


def open_library(app):
    """More » Item library... and the Library tab: builds the tab (or selects it when it is built)."""
    try:
        import mxl_tabs
        w = mxl_tabs.built_owner('Library')
        if w is not None:
            mxl_tabs.focus_existing('Library')
            w.refresh()
            return w
    except Exception:
        pass
    return LibraryWindow(app)


def install(App=None):
    """More » "Item library..." (mxl_toolbar) selects the Library tab."""
    import mxl_toolbar
    mxl_toolbar.add_entry(lambda: tr('menu', 'Item library...'), open_library)
