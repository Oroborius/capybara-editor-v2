"""Personal item library: items kept as .d2i files in <user dir>/library/, with an index (index.json).

- right-click an item -> "Add to library...": its exact bytes (socketed items included, the same bytes as Export
  item...) go into the folder under a name ("Folder/Name" puts it in a folder);
- More » "Item library...": the list (icon, name, folder, base) with a search box; "Place a copy" puts a copy on
  the stash page shown (else the first page with room) through the collector's safe writer (edit_stash: verified
  write, backup policy) and records it for Ctrl+Z; Rename / Delete edit the entry.
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
    entry = dict(file=file, name=nm, folder=fo, code=code or it['code'], added=time.strftime('%Y-%m-%d %H:%M'))
    entries = load()
    entries.append(entry)
    _save(entries)
    return entry


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
def _status(app, msg, error=False):
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


def place_copy(app, entry):
    """A copy of the entry on the stash page shown (else the first page with room). Returns (page, x, y)."""
    from mxl_save import blob_item, parse_stash, free_spot, edit_stash, EditError, STASH_PAGES
    from mxl_format import FormatError
    if not getattr(app, 'path', None):
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


# ------------------------------------------------------------------ the window
class LibraryWindow:
    ICON = 32

    def __init__(self, app):
        self.app = app
        master = app.root if hasattr(app, 'root') else app.canvas
        top = self.top = tk.Toplevel(master)
        top.title(tr('title', 'Item library'))
        self.icons = {}
        row = tk.Frame(top)
        row.pack(fill='x', padx=2, pady=2)
        tk.Label(row, text=tr('search', 'Search:')).pack(side='left')
        self.q = tk.StringVar()
        ent = tk.Entry(row, textvariable=self.q, width=24)
        ent.pack(side='left', fill='x', expand=True, padx=2)
        self.q.trace_add('write', lambda *_a: self.refresh())
        bar = tk.Frame(top)
        bar.pack(side='bottom', fill='x', padx=2, pady=2)
        self.b_place = tk.Button(bar, text=tr('place', 'Place a copy'), command=self.place)
        self.b_place.pack(side='left', padx=2)
        tk.Button(bar, text=tr('inspect', 'Inspect...'), command=self.inspect).pack(side='left', padx=2)
        tk.Button(bar, text=tr('rename', 'Rename...'), command=self.rename).pack(side='left', padx=2)
        tk.Button(bar, text=tr('delete', 'Delete'), command=self.delete).pack(side='left', padx=2)
        tk.Button(bar, text=tr('close', 'Close'), command=top.destroy).pack(side='right', padx=2)
        try:
            ttk.Style(top).configure('CapyLib.Treeview', rowheight=self.ICON + 4)
        except tk.TclError:
            pass
        body = tk.Frame(top)
        body.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(body, columns=('folder', 'base'), style='CapyLib.Treeview', height=10)
        self.tree.heading('#0', text=tr('c.name', 'Name'))
        self.tree.heading('folder', text=tr('c.folder', 'Folder'))
        self.tree.heading('base', text=tr('c.base', 'Base'))
        self.tree.column('#0', width=240)
        self.tree.column('folder', width=100)
        self.tree.column('base', width=140)
        sy = ttk.Scrollbar(body, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sy.set)
        sy.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda _e: self.place())
        self.rows = {}
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
            layers = icon_layers(it, self.app.data, (20, 16, 16), ICONS_DIR)
            im = layers.get(1) if layers else None
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
        for e in sorted(search(load(), self.q.get()), key=lambda e: (e.get('folder', '').lower(), e['name'].lower())):
            kw = {}
            img = self._icon(e)
            if img is not None:
                kw['image'] = img
            iid = self.tree.insert('', 'end', text=' ' + e['name'], values=(e.get('folder', ''), self._base(e)), **kw)
            self.rows[iid] = e
        kids = self.tree.get_children()
        if kids and not self.tree.selection():
            self.tree.selection_set(kids[0])

    def current(self):
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def place(self):
        e = self.current()
        if e is not None:
            place_copy(self.app, e)

    def inspect(self):
        e = self.current()
        if e is not None:
            import mxl_inspect
            mxl_inspect.open_blob(self.top, blob_of(e), self.app.data, e['name'])

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
    return LibraryWindow(app)


def install(App=None):
    """More » "Item library..." (mxl_toolbar)."""
    import mxl_toolbar
    mxl_toolbar.add_entry(lambda: tr('menu', 'Item library...'), open_library)
