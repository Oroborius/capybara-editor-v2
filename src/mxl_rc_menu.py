"""Right-click menus on items, in the Hero Editor way.

- Main window (the stash grid): click an item with the right button for Edit item / Item stats / Duplicate /
  Copy / Cut / Paste (replaces the item) / Move to page... / Delete / Change item quality... / Specific editing
  functions (defense, durability, ethereal, sockets, personalize, clear magic attributes) / Quantity... /
  Export item...; an empty cell gives Paste here / Import item... / the Item Creator.
- Character window (equipment slots, mercenary and the inventory): the same set (written through the character
  editor's own remove -> place -> save flow); an empty inventory cell: Create here... / Paste here / Import item...
- Main window's equipment / inventory panel (mxl_inv_gui, next to the stash): that same character menu and the
  same shortcuts, through mxl_inv_gui.PanelWin (the panel behind the CharacterWindow members used here).
- Keyboard shortcuts (acting on the item under the mouse cursor): Ctrl+C / Ctrl+V copy / paste the item itself
  (an empty cell pastes there, an occupied one is replaced); Ctrl+Shift+C / Ctrl+Shift+V copy the item's magic
  attributes to the shared buffer / paste the buffer's attributes onto it.
- Quantity... on any non-stackable item (not just clusters / containers): the "Quantity:" magic attribute
  (stat 501, up to 1000); stackable items keep their own stack-size submenu.

Copy / Paste keep the item's bytes (also across the two windows, the run); a pasted copied item keeps its own
rolls. Everything written goes through the collector's own safe writers (edit_stash, Character.save, backups).
The Hero-Editor features (quality switch, ethereal, personalize, ...) edit the decoded record the same way
the Item Editor does: decode -> adjust -> re-encode losslessly in place, socketed items untouched.
"""
import os

import tkinter as tk
import types

from mxl_save import read_file, item_blob, blob_item, parse_stash, free_spot, edit_stash, EditError, STASH_PAGES, \
    placement_error
from mxl_format import FormatError
from mxl_lang import T

import stat_ids as S
from mxl_format_fix import body_kind

DEBUG = False


def rc(key, default, **fields):
    return T('rc.' + key, default, **fields)


def _dbg(*a):
    """Diagnostic switch for tracing the right-click / hotkey flow into capybara.log (off by default,
    set mxl_rc_menu.DEBUG = True when chasing a report)."""
    if not DEBUG:
        return
    print('capy-rc:', *a)


def _status(app, msg, error=False):
    try:
        app.show_status(msg)
    except Exception:
        try:
            app.status.configure(text=msg)
        except Exception:
            pass


def install(App):
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            # ButtonRelease: a menu posted on the button press closes again on the release
            # (the release goes to the menu's own grab), which made it feel like the menu
            # had to be kept open with the button held down
            self.canvas.bind('<ButtonRelease-3>', self._rc_menu)
        except Exception as e:
            print('right-click menu (stash) not installed:', e)
        _dbg('stash install: menu bound; hotkeys next')
        _bind_hotkeys(self.root if hasattr(self, 'root') else self.canvas, [self.canvas],
                      lambda what, app=self: _stash_hot(app, what))

    App._build = _build
    App._rc_menu = _stash_menu


def install_char():
    """Right-click on the equipment / inventory canvases of the character window."""
    from mxl_char_gui import CharacterWindow
    o_build = CharacterWindow._build_equipment

    def _build_equipment(self):
        o_build(self)
        for cv in (self.doll, self.inv):
            cv.bind('<ButtonRelease-3>', lambda e, cv=cv: _char_menu(self, cv, e))
        _dbg('char install: menu bound on doll/inv; hotkeys next')
        _bind_hotkeys(getattr(self, 'top', None), [self.doll, self.inv],
                      lambda what, win=self: _char_hot(win, what))

    CharacterWindow._build_equipment = _build_equipment


# ------------------------------------------------------------------ main window (stash)
def _stash_menu(app, ev):
    menu = tk.Menu(app.canvas, tearoff=0)
    from mxl_creator_gui import edit_selected, delete_selected, CreatorWindow
    import mxl_he_stats
    it = None
    try:
        it = app.item_at(ev)
    except Exception:
        pass
    _dbg('stash menu:', it['code'] if it else 'empty cell')
    clip = getattr(app, '_capy_clip', None)
    if it is not None:
        app.selected = it
        app.draw_grid()
        app.set_detail(it)
        menu.add_command(label=rc('edit', 'Edit item...'), command=lambda: edit_selected(app))
        menu.add_command(label=rc('stats', 'Item stats...'), command=lambda: mxl_he_stats.open_item_stats(app))
        menu.add_command(label=rc('duplicate', 'Duplicate'), command=lambda: _duplicate(app, it))
        menu.add_command(label=rc('copy', 'Copy'), command=lambda: _copy(app, it))
        menu.add_command(label=rc('cut', 'Cut'), command=lambda: _cut(app, it))
        if clip is not None:
            menu.add_command(label=rc('paste', 'Paste (replaces it; copy: {name})', name=clip[1]),
                             command=lambda: _paste(app, it, clip))
        pages = tk.Menu(menu, tearoff=0)
        for p in range(STASH_PAGES):
            pages.add_command(label=rc('page', 'Page {n}', n=p + 1), command=lambda p=p: _move_page(app, it, p),
                              state='disabled' if p == it['page'] else 'normal')
        menu.add_cascade(label=rc('move', 'Move to page...'), menu=pages)
        _quantity_cascade(app, menu, it)
        _fill_sockets_entry(app, menu, it)
        _socket_cascade(app, menu, it=it)
        _add_hero_editor_menu(app, menu, it=it)
        menu.add_separator()
        menu.add_command(label=rc('delete', 'Delete item'), command=lambda: delete_selected(app))
        menu.add_command(label=rc('export', 'Export item...'), command=lambda: _export_stash(app, it))
        menu.add_command(label=rc('bitedit', 'Open in Bit editor'), command=lambda: _inspect_stash(app, it))
        menu.add_command(label=rc('to_library', 'Add to library...'), command=lambda: _library_stash(app, it))
    else:
        if clip is not None:
            menu.add_command(label=rc('paste_here', 'Paste here ({name})', name=clip[1]),
                             command=lambda: _paste_empty(app, ev, clip))
        menu.add_command(label=rc('import', 'Import item...'), command=lambda: _import_stash(app, ev))
        menu.add_command(label=rc('creator', 'Item Creator...'), command=lambda: CreatorWindow(app))
    try:
        menu.tk_popup(ev.x_root, ev.y_root)
    finally:
        menu.grab_release()


def _selected(app, page, x, y):
    """Refresh after a stash write, the item at (page, x, y) selected. The stash-only reload keeps the page being
    shown: the full app.load() went back to page 1 after every copy / paste / duplicate."""
    from mxl_creator_gui import _reload_main
    _reload_main(app, (page, x, y))


def _now(app, it):
    """(buf, items, blob) of a stash item as the file holds it now; EditError when the window is out of date for
    it (mxl_stash_order.item_now: an offset of an older read can hold a neighbour of the same size)."""
    import mxl_stash_order
    buf, items, _cur, blob = mxl_stash_order.item_now(app.path, app.data, it, app)
    return buf, items, blob


def _copy(app, it):
    try:
        app._capy_clip = (_now(app, it)[2], app.full_name(it))
        _status(app, rc('copied', '{name} copied (right-click an empty cell to paste it)',
                        name=app.full_name(it)))
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return False
    return True


def _duplicate(app, it):
    try:
        _buf, items, blob = _now(app, it)
        pages = [it['page']] + [p for p in range(STASH_PAGES) if p != it['page']]
        spot = free_spot(items, blob_item(blob, app.data), app.data, pages)
        if spot is None:
            _status(app, rc('err.nofree', 'no free place in the stash'), True)
            return
        bak = edit_stash(app.path, app.data, insert=[(spot[0], spot[1], spot[2], blob)],
                         backup=app.needs_backup(app.path))
        app.backup_made(app.path, bak)
        _selected(app, spot[0], spot[1], spot[2])
        _status(app, rc('duplicated', '{name} duplicated: page {page} ({x}, {y}){bak}',
                        name=app.full_name(it), page=spot[0] + 1, x=spot[1], y=spot[2],
                        bak=(' - backup ' + os.path.basename(bak) if bak else '')))
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)


def _paste(app, it, clip):
    """Replaces the clicked item by the copied one (its socketed items follow)."""
    try:
        old = bytes(item_blob(read_file(app.path), it))
        bak = edit_stash(app.path, app.data, remove=[it['_offset']],
                         insert=[(it['page'], it['x'], it['y'], clip[0])],
                         backup=app.needs_backup(app.path))
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return
    _record_stash_replace(app, it, old, app.full_name(it))
    app._capy_clip = None
    app.backup_made(app.path, bak)
    _selected(app, it['page'], it['x'], it['y'])
    _status(app, rc('pasted_over', '{name} pasted (the previous item is replaced)', name=clip[1]))


def _paste_empty(app, ev, clip):
    page = app.page()
    cx, cy = ev.x // app.cell, ev.y // app.cell
    try:
        bak = edit_stash(app.path, app.data, insert=[(page, cx, cy, clip[0])],
                         backup=app.needs_backup(app.path))
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return
    app._capy_clip = None
    app.backup_made(app.path, bak)
    _selected(app, page, cx, cy)
    _status(app, rc('pasted_here', '{name} pasted', name=clip[1]))


def _move_page(app, it, page):
    """Moves the item to another stash page: to the same cell when it is free there, else to the first free
    place of that page (it used to insist on the same cell and failed with "(x, y): overlaps ...")."""
    if page == it['page']:
        return
    try:
        buf = read_file(app.path)
        blob = item_blob(buf, it)
        items = parse_stash(app.path, app.data)
        probe = blob_item(blob, app.data)
        x, y = it['x'], it['y']
        if placement_error(items, probe, page, x, y, app.data) is not None:
            spot = free_spot(items, probe, app.data, [page])
            if spot is None:
                _status(app, rc('err.nofree_page', 'no free place on page {page}', page=page + 1), True)
                return
            x, y = spot[1], spot[2]
        bak = edit_stash(app.path, app.data, remove=[it['_offset']],
                         insert=[(page, x, y, blob)], backup=app.needs_backup(app.path))
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return
    app.backup_made(app.path, bak)
    _selected(app, page, x, y)
    _status(app, rc('moved', '{name} moved to page {page}', name=app.full_name(it), page=page + 1))


def _quantity_cascade(app, menu, it):
    """The context menu's Quantity submenu for any non-stackable item: Max / Min fill to the item
    type's own cap (1000), Add / Remove ask for a number.
    Clusters / containers (and any other non-stackable item) store their quantity as the
    "Quantity:" magic attribute (stat 501, up to 1000): the submenu edits that attribute.
    A compact record stores no stat list: no submenu there (a plain edit refuses it too)."""
    from mxl_creator import decode_item, CreateError
    from mxl_format import FormatError
    base = app.data.base(it['code'])
    if base.stack_max is None:
        try:
            blob = item_blob(read_file(app.path), it)
            rec, size = decode_item(blob, app.data)
        except (EditError, FormatError, CreateError, OSError) as e:
            _dbg('quantity: cluster read failed:', repr(e))
            return
        if rec['flags'] & FLAG_SIMPLE:
            _dbg('quantity: cluster record is compact (no stat list) - no submenu')
            return
        cur = next((s['value'] for s in rec['stats']
                    if s['id'] == CLUSTER_QUANTITY_STAT and not s.get('param')), 0)
        _dbg('quantity: cluster', it['code'], 'now', cur, '- adding submenu')
        _cluster_quantity_menu(menu, cur, lambda newq: _set_cluster_quantity(app, it, newq))
        return
    try:
        blob = item_blob(read_file(app.path), it)
        rec, size = decode_item(blob, app.data)
    except (EditError, FormatError, CreateError, OSError) as e:
        _dbg('quantity: stackable read failed:', repr(e))
        return
    if rec['flags'] & 0x20:               # compact record: the game expanded stackable ones (quantity kept)
        _dbg('quantity: compact record - no submenu')
        return
    _dbg('quantity: stackable', it['code'], 'now', rec.get('quantity') or 1, '- adding submenu')
    _quantity_menu(menu, app.data, it['code'], rec.get('quantity') or 1,
                   lambda newq: _set_quantity(app, it, newq))


def _quantity_menu(menu, data, code, cur, set_fn):
    """The shared Max / Min / Add... / Remove... submenu; set_fn(new_quantity) does the write."""
    base = data.base(code)
    q = tk.Menu(menu, tearoff=0)
    q.add_command(label=rc('q.max', 'Max ({n})', n=base.stack_max),
                  command=lambda: set_fn(base.stack_max))
    q.add_command(label=rc('q.min', 'Min (1)'), command=lambda: set_fn(1))
    q.add_command(label=rc('q.add', 'Add...'), command=lambda: _quantity_ask(menu, data, code, cur, +1, set_fn))
    q.add_command(label=rc('q.remove', 'Remove...'), command=lambda: _quantity_ask(menu, data, code, cur, -1, set_fn),
                  state='normal' if cur > 1 else 'disabled')        # nothing to remove: the least quantity is 1
    menu.add_cascade(label=rc('q.title', 'Quantity (now {n})', n=cur), menu=q)


def _cluster_quantity_menu(menu, cur, set_fn):
    """The Quantity submenu of a non-stackable item (its quantity lives in the "Quantity:" magic
    attribute, stat 501, capped at 1000); same Max / Min / Add / Remove shape as the stack submenu."""
    q = tk.Menu(menu, tearoff=0)
    q.add_command(label=rc('q.max', 'Max ({n})', n=CLUSTER_QUANTITY_MAX),
                  command=lambda: set_fn(CLUSTER_QUANTITY_MAX))
    q.add_command(label=rc('q.min', 'Min (1)'), command=lambda: set_fn(1))
    q.add_command(label=rc('q.add', 'Add...'),
                  command=lambda: _cluster_quantity_ask(menu, cur, +1, set_fn))
    q.add_command(label=rc('q.remove', 'Remove...'),
                  command=lambda: _cluster_quantity_ask(menu, cur, -1, set_fn),
                  state='normal' if cur > 1 else 'disabled')        # quantity 0 / 1: "Remove" raised 0 to 1
    menu.add_cascade(label=rc('q.title', 'Quantity (now {n})', n=cur), menu=q)


def _cluster_quantity_ask(menu, cur, sign, set_fn):
    from tkinter import simpledialog
    root = _owner(menu)
    v = simpledialog.askinteger(rc('q.title2', 'Quantity'),
                                rc('q.ask_add' if sign > 0 else 'q.ask_remove', 'Add how many (now {n}, 1 to {m})?' if sign > 0 else
                                   'Remove how many (now {n}, 1 to {m})?', n=cur, m=_most(cur, sign, CLUSTER_QUANTITY_MAX)),
                                parent=root, initialvalue=_most(cur, sign, CLUSTER_QUANTITY_MAX),
                                minvalue=1, maxvalue=_most(cur, sign, CLUSTER_QUANTITY_MAX))
    if v is None:
        return
    new = _quantity_after(cur, sign, v, CLUSTER_QUANTITY_MAX)
    if new != cur:
        set_fn(new)


def _quantity_ask(menu, data, code, cur, sign, set_fn):
    from tkinter import simpledialog
    base = data.base(code)
    root = _owner(menu)
    v = simpledialog.askinteger(rc('q.title2', 'Quantity'),
                                rc('q.ask_add' if sign > 0 else 'q.ask_remove', 'Add how many (now {n}, 1 to {m})?' if sign > 0 else
                                   'Remove how many (now {n}, 1 to {m})?', n=cur, m=_most(cur, sign, base.stack_max)),
                                parent=root, initialvalue=_most(cur, sign, base.stack_max),
                                minvalue=1, maxvalue=_most(cur, sign, base.stack_max))
    if v is None:
        return
    new = _quantity_after(cur, sign, v, base.stack_max)
    if new != cur:
        set_fn(new)


def _most(cur, sign, top):
    """The most that Add... (up to the cap) / Remove... (down to 1) can take: what the dialog offers."""
    return max(1, top - cur) if sign > 0 else max(1, cur - 1)


def _quantity_after(cur, sign, v, top):
    """Quantity after adding / removing v: within 1..top, and Remove never raises it (quantity 0 of an item
    without the stat stays 0 - it went to 1), Add never lowers it."""
    new = max(1, min(top, cur + sign * v))
    return min(new, cur) if sign < 0 else max(new, cur)


def _set_quantity(app, it, newq):
    """Writes a stackable item's quantity in place: the item's own bytes are decoded and re-encoded
    (its socketed items stay behind it), then the stash is written with the collector's safe writer."""
    from mxl_creator import decode_item, encode_item, CreateError
    try:
        buf = read_file(app.path)
        blob = item_blob(buf, it)
        rec, size = decode_item(blob, app.data)
        rec['quantity'] = int(newq)
        new = encode_item(rec, app.data) + bytes(blob[size:])
        bak = edit_stash(app.path, app.data, remove=[it['_offset']],
                         insert=[(it['page'], it['x'], it['y'], new)], backup=app.needs_backup(app.path))
    except (EditError, FormatError, OSError, CreateError, ValueError) as e:
        _status(app, str(e), True)
        return
    _record_stash_replace(app, it, blob, app.full_name(it))
    app.backup_made(app.path, bak)
    _selected(app, it['page'], it['x'], it['y'])
    _status(app, rc('q.set', '{name}: quantity is now {n}', name=app.full_name(it), n=int(newq)))


def _set_cluster_quantity(app, it, newq):
    """Writes a cluster's / container's quantity (the "Quantity:" magic attribute, stat 501) in place,
    through the same decode -> adjust -> re-encode -> safe writer flow as the record quantity."""
    def fn(rec, cr, data):
        stats_with_cluster_quantity(rec['stats'], newq)
        return True
    _mutate_stash(app, it, fn,
                  rc('q.set', '{name}: quantity is now {n}', name=_item_name(app, it, None), n=int(newq)))


# ------------------------------------------------------------------ character window
def inventory_menu(inv, ev):
    """Right-click on the main window's equipment / inventory panel (mxl_inv_gui, next to the stash): the
    Character tab's menu, acting on the character file where the item is (no trip through the stash). Opens
    on an item, an empty inventory cell or an empty equipment slot."""
    app = inv.app
    if app.selected is not None:          # before the adapter is made: this redraw may read the character again
        app.selected = None
        app.draw_grid()
    win = inv.as_win()
    e, slot = win.entry_at(ev.widget, ev)
    if e is None and slot is None:
        if ev.widget is not win.inv or win._cell is None:
            return
        inv.deselect()
        inv.show_detail()
    _char_menu(win, ev.widget, ev)


def install_panel(inv):
    """The Character tab's shortcuts on the main window's panel: Ctrl+C / Ctrl+V (item), Ctrl+Shift+C / V
    (magic attributes) and Delete, each on the item under the mouse pointer. The inventory canvas comes first:
    on the game-art panels it lies on top of the paperdoll canvas."""
    root = inv.app.root
    canvases = [inv.canvas, inv.doll]
    _bind_hotkeys(root, canvases, lambda what: _char_hot(inv.as_win(), what))

    def on_delete(_e=None):
        try:
            w = root.focus_get()
            if w is not None and w.winfo_class() in ('Entry', 'Text', 'Spinbox', 'Combobox', 'TEntry', 'TCombobox',
                                                     'TSpinbox'):
                return
        except Exception:
            pass
        ev = _canvas_at_pointer([cv for cv in canvases if cv.winfo_ismapped()])
        if ev is None or inv.ch is None or inv.drag is not None:
            return
        win = inv.as_win()
        e, _slot = win.entry_at(ev.widget, ev)
        if e is not None:
            win.selected = e
            win.delete_instant(e)

    root.bind('<Delete>', on_delete, add='+')


def _sync(win):
    """The Character tab reads its file again when someone else wrote it (pending page edits kept), so the item
    picked here is the one in the file as it is (CharacterWindow.sync_file; the panel's adapter refuses a stale
    read by itself)."""
    fn = getattr(win, 'sync_file', None)
    if fn is not None:
        try:
            fn()
        except Exception as e:
            _dbg('sync before the item action failed:', e)


def _char_menu(win, cv, ev):
    menu = tk.Menu(cv, tearoff=0)
    import mxl_he_stats
    _sync(win)
    e, slot = win.entry_at(cv, ev)
    _dbg('char menu:', e.it['code'] if e is not None else 'empty spot')
    clip = getattr(win.app, '_capy_clip', None)
    vanilla = getattr(win, 'vanilla_he', False)
    if e is not None or slot is not None:
        win.sel_slot = slot
        win.selected = e
        win.redraw()
    if vanilla:
        paste = None
        if e is None and clip:
            if cv is win.inv and not win.is_merc():
                paste = lambda: _char_paste(win, ev, clip)
            elif slot is not None:
                paste = lambda: _char_paste_slot(win, slot, clip)
        _vanilla_char_commands(win, menu, e, clip, paste=paste, extensions=e is not None)
        if e is None:
            menu.add_command(label='Create here…', command=win.create_here)
    elif e is not None:
        menu.add_command(label=rc('edit', 'Edit item...'), command=win.edit)
        menu.add_command(label=rc('stats', 'Item stats...'), command=lambda: mxl_he_stats.open_char_item_stats(win, e))
        menu.add_command(label=rc('duplicate', 'Duplicate'), command=lambda: _char_duplicate(win, e))
        menu.add_command(label=rc('copy', 'Copy'), command=lambda: _char_copy(win, e))
        menu.add_command(label=rc('cut', 'Cut'), command=lambda: (_char_copy(win, e), win.delete()))
        if clip is not None:
            menu.add_command(label=rc('paste', 'Paste (replaces it; copy: {name})', name=clip[1]),
                             command=lambda: _char_paste_over(win, e, clip))
        _char_quantity_cascade(win, menu, e)
        _fill_sockets_entry(win, menu, None, win=win, e=e)
        _socket_cascade(win, menu, win=win, e=e)
        _add_hero_editor_menu(win, menu, win=win, e=e)
        menu.add_command(label=rc('to_stash', 'To stash'), command=win.to_stash)
        menu.add_command(label=rc('delete_short', 'Delete'), command=win.delete)
        menu.add_command(label=rc('export', 'Export item...'), command=lambda: _export_char(win, e))
        menu.add_command(label=rc('bitedit', 'Open in Bit editor'), command=lambda: _inspect_char(win, e))
        menu.add_command(label=rc('to_library', 'Add to library...'), command=lambda: _library_char(win, e))
    else:
        if clip is not None and cv is win.inv:
            menu.add_command(label=rc('paste_here', 'Paste here ({name})', name=clip[1]),
                             command=lambda: _char_paste(win, ev, clip))
        elif clip is not None and slot is not None:         # an empty equipment slot (character or mercenary)
            menu.add_command(label=rc('paste_here', 'Paste here ({name})', name=clip[1]),
                             command=lambda: _char_paste_slot(win, slot, clip))
        if cv is win.inv:
            menu.add_command(label=rc('import', 'Import item...'), command=lambda: _import_char(win, ev))
        menu.add_command(label=rc('create_here', 'Create here...'), command=win.create_here)
    try:
        menu.tk_popup(ev.x_root, ev.y_root)
    finally:
        menu.grab_release()


def _vanilla_char_commands(win, menu, entry, clip, *, paste=None, delete=None, extensions=True):
    from tkinter import filedialog, messagebox
    from mxl_statnames import stat_text
    from mxl_vanilla_he import allows, set_tab

    can_transfer = allows(win, 'transfer')

    def copy():
        return can_transfer and _char_copy(win, entry)

    if delete is None:
        def delete():
            win.selected = entry
            win.delete()

    def selected(label, action, accelerator='', enabled=True):
        menu.add_command(label=label, command=action, accelerator=accelerator,
                         state='normal' if entry is not None and enabled else 'disabled')

    def view_buffer():
        rows = getattr(win.app, '_capy_he_buffer', ())
        text = '\n'.join(stat_text(win.data, stat['id'], stat.get('param'), stat['value']) or str(stat['id'])
                         for stat in rows)
        messagebox.showinfo('Magic Attribute Buffer', text or 'The buffer is empty.', parent=win.top)

    def delete_buffer():
        win.app._capy_he_buffer = []
        win.set_status('Magic attribute buffer deleted.')

    def import_item():
        from mxl_vanilla_he import draw_pickup

        path = filedialog.askopenfilename(title='Import Item', filetypes=[('Diablo II item', '*.d2i')],
                                          parent=win.top)
        if not path:
            return
        try:
            blob = read_file(path)
            item = blob_item(blob, win.data)
        except (EditError, FormatError, OSError) as error:
            win.set_status(str(error), True)
            return
        from mxl_creator_gui import clean
        win.app._capy_clip = blob, clean(item.get('name') or item['code'])
        draw_pickup(win)
        win.set_status('Item imported into Picked Up.')

    def export_character():
        from mxl_vanilla_he_items import ITEM_ERRORS, character_report

        if win.dirty():
            messagebox.showwarning('Save Character Information', 'Save or reload your pending changes first.',
                                   parent=win.top)
            return
        path = filedialog.asksaveasfilename(title='Save Character Information', initialfile=win.ch.name + '.txt',
                                            initialdir=os.path.dirname(win.ch.path),
                                            defaultextension='.txt', filetypes=[('Text file', '*.txt')],
                                            parent=win.top)
        if not path:
            return
        win.sync_file()
        try:
            with open(path, 'w', encoding='utf-8') as output:
                output.write(character_report(win))
        except ITEM_ERRORS as error:
            win.set_status(str(error), True)
            return
        win.set_status(f'Character information saved to {os.path.basename(path)}.')

    from mxl_vanilla_he_items import (add_specific, add_favorites, buffer_attributes,
                                     cut_item, edit_item, mutate, paste_attributes, paste_one, submenu)

    selected('General Edit of Item (in Extras Window)', lambda: edit_item(win, entry), 'Ctrl+G')
    if entry is None:
        selected('Specific Editing Functions…', None)
    else:
        add_specific(win, menu, entry)
    menu.add_separator()
    if entry is None:
        selected('FAVORITE Item Attributes…', None)
    else:
        add_favorites(win, menu, entry)
    menu.add_separator()
    selected('Add All Item Magic Attributes TO Buffer',
             lambda: buffer_attributes(win, entry), 'Ctrl+A')
    menu.add_command(label='VIEW what is in Buffer', accelerator='Ctrl+P', command=view_buffer)
    menu.add_command(label='DELETE Buffer', accelerator='Ctrl+B', command=delete_buffer)
    menu.add_separator()
    selected('Export Item to File…', lambda: _export_char(win, entry), 'Ctrl+E', can_transfer)
    menu.add_command(label='Import Item from File…', accelerator='Ctrl+I', command=import_item,
                     state='normal' if can_transfer else 'disabled')
    menu.add_separator()
    selected('Cut Item (move to Picked Up)', lambda: cut_item(win, entry), 'Ctrl+X', can_transfer)
    selected('Copy Item (copy into Picked Up)', copy, 'Ctrl+C', can_transfer)
    if paste is None and entry is not None:
        paste = lambda: paste_one(win, entry, clip, lambda: _char_paste_over(win, entry, clip))
    menu.add_command(label='Paste Item (copy of Picked Up)', accelerator='Ctrl+V',
                     state='normal' if clip and paste and can_transfer else 'disabled', command=paste)
    from mxl_vanilla_he_items import fill, fill_count

    can_fill = entry is not None and fill_count(win, entry, clip)
    menu.add_command(label='Fill Item Sockets (copy of Picked Up)', accelerator='Ctrl+Z',
                     state='normal' if can_fill else 'disabled', command=lambda: fill(win, entry, clip))
    selected('Delete Item (remove)', delete, 'Del', allows(win, 'item'))
    menu.add_separator()
    menu.add_command(label='Save Character Information to Text file', command=export_character)
    menu.add_command(label='Help', accelerator='F1', command=lambda: set_tab(win, 'info'))
    if not extensions:
        return
    menu.add_separator()
    more = submenu(menu, 'More Item Tools')
    buffered = getattr(win.app, '_capy_he_buffer', ())
    if entry is not None and buffered:
        more.add_command(label='Apply Buffer to Item',
                         command=lambda: mutate(win, entry, 'Applied magic attribute buffer.',
                                                lambda rec: paste_attributes(rec, buffered)))
    if entry is not None:
        _socket_cascade(win, more, win=win, e=entry)
        more.add_command(label='To stash', command=win.to_stash)
        more.add_command(label='Duplicate', command=lambda: _char_duplicate(win, entry))
        more.add_command(label='Open in Bit editor', command=lambda: _inspect_char(win, entry))


def _char_copy(win, e):
    import mxl_char as MC
    try:
        win.app._capy_clip = (win.ch.stash_blob(e), clean_name(win, e))
    except MC.CharError as err:                       # a 1.09 item kept as read
        win.set_status(str(err), True)
        return
    _status(win.app, rc('copied', '{name} copied (right-click an empty cell to paste it)', name=clean_name(win, e)))
    if getattr(win, 'vanilla_he', False):
        from mxl_vanilla_he import draw_pickup
        draw_pickup(win)
    return True


def _char_quantity_cascade(win, menu, e):
    """The Quantity submenu on any non-stackable item of the character (equipment, mercenary or
    inventory): same Max / Min / Add / Remove as in the stash, written through the character
    editor's own remove -> place -> save flow.  The quantity lives in the "Quantity:" magic
    attribute (stat 501) exactly as on a stash item."""
    from mxl_creator import decode_item, CreateError
    from mxl_format import FormatError
    base = win.data.base(e.it['code'])
    if base.stack_max is None:
        try:
            blob = win.ch.stash_blob(e)
            rec, size = decode_item(blob, win.data)
        except (FormatError, CreateError, OSError, AttributeError) as err:
            _dbg('quantity: cluster read failed:', repr(err))
            return
        if rec['flags'] & FLAG_SIMPLE:
            _dbg('quantity: cluster record is compact (no stat list) - no submenu')
            return
        cur = next((s['value'] for s in rec['stats']
                    if s['id'] == CLUSTER_QUANTITY_STAT and not s.get('param')), 0)
        _dbg('quantity: cluster', e.it['code'], 'now', cur, '- adding submenu')
        _cluster_quantity_menu(menu, cur, lambda newq: _char_set_cluster_quantity(win, e, newq))
        return
    try:
        blob = win.ch.stash_blob(e)
        rec, size = decode_item(blob, win.data)
    except (FormatError, CreateError, OSError, AttributeError) as err:
        _dbg('quantity: stackable read failed:', repr(err))
        return
    if rec['flags'] & 0x20:               # compact record: no quantity field of its own
        _dbg('quantity: compact record - no submenu')
        return
    _dbg('quantity: stackable', e.it['code'], 'now', rec.get('quantity') or 1, '- adding submenu')
    _quantity_menu(menu, win.data, e.it['code'], rec.get('quantity') or 1,
                   lambda newq: _char_set_quantity(win, e, newq))


def _char_replace(win, e, new, where, merc):
    """remove -> place: the item's new bytes at the spot it stood on. Character.place's slot rules refuse some
    items the game itself put there (a Sigma mercenary's gloves / belt / boots / amulet): the same base then
    goes back into the slot it was worn in, as it was (what MainInventory.edit and mxl_perfect do)."""
    import mxl_char as MC
    ch = win.ch
    if not any(x is e for x in ch.entries(merc)):
        raise MC.CharError(T('inv.err.item_gone', 'the item is no longer where it was: select it again'))
    if ch.version == 71:
        return ch.place(new, where, merc, replace=e)
    ch.remove(e, merc)
    try:
        return ch.place(new, where, merc)
    except MC.CharError:
        it = blob_item(new, win.data)
        if where[0] != 'slot' or it['code'] != e.it['code']:
            raise
        ent = MC.Entry(it, new)
        ent.blob = ent.moved(win.data, location=MC.LOC_EQUIPPED, equipped=where[1], x=where[1], y=0, panel=0)
        ent.it = blob_item(ent.blob, win.data)
        ch.entries(merc).append(ent)
        return ent


def _char_set_cluster_quantity(win, e, newq):
    """Writes a character item's cluster / container quantity (the "Quantity:" magic attribute)
    through the character editor's own remove -> place -> save flow."""
    def fn(rec, cr, data):
        stats_with_cluster_quantity(rec['stats'], newq)
        return True
    _mutate_char(win, e, fn,
                 rc('q.set', '{name}: quantity is now {n}', name=_item_name(win, None, e), n=int(newq)))


def _char_set_quantity(win, e, newq):
    """Writes a stackable character item's quantity: the item blob is decoded and re-encoded in place
    (its socketed items stay behind it), then put back where it was through remove -> place -> save."""
    import mxl_char as MC
    from mxl_char import CharError
    from mxl_creator import decode_item, encode_item, CreateError
    merc = win.is_merc()
    where = MC.where_of(e)
    path, before = win.ch.path, bytes(win.ch.raw)
    try:
        blob = win.ch.stash_blob(e)
        rec, size = decode_item(blob, win.data)
        rec['quantity'] = int(newq)
        new = encode_item(rec, win.data) + bytes(blob[size:])
        _char_replace(win, e, new, where, merc)
    except (CharError, FormatError, OSError, CreateError, ValueError) as err:
        win.reload()
        win.set_status(str(err), True)
        return
    if not win.save(rc('q.set', '{name}: quantity is now {n}', name=clean_name(win, e), n=int(newq))):
        win.set_status(T('ch.err.not_saved', 'character not saved'), True)
        return
    _record_char_write(win, path, before, clean_name(win, e))


def _char_duplicate(win, e):
    import mxl_char as MC
    from mxl_char import CharError
    if win.is_merc() and not getattr(win, 'merc_inventory', False):
        win.set_status(rc('err.merc', 'the mercenary has no inventory to duplicate into'), True)
        return
    try:
        blob = win.ch.stash_blob(e)
        spot = win.ch.free_inventory_spot(MC.blob_item(blob, win.data))
        if spot is None:
            win.set_status(rc('err.nofree_inv', 'no free place in the inventory'), True)
            return
        win.ch.place(blob, ('inv',) + spot, False)        # the copy goes to the character's inventory
    except (CharError, FormatError, OSError) as err:
        win.set_status(str(err), True)
        return
    win.save(rc('duplicated_char', '{name} duplicated', name=clean_name(win, e)))


def _char_paste(win, ev, clip):
    from mxl_char import CharError
    cx, cy = ev.x // win.cell, ev.y // win.cell
    try:
        win.ch.place(clip[0], ('inv', cx, cy), win.is_merc())
    except (CharError, FormatError, OSError) as err:
        win.set_status(str(err), True)
        return
    if win.save(rc('pasted', '{name} pasted', name=clip[1]), operation='transfer') and not getattr(win, 'vanilla_he', False):
        _clear_char_clip(win)


def _char_paste_slot(win, slot, clip):
    """Paste onto an EMPTY equipment slot: the copied item is worn there (the mercenary's slot when the
    mercenary is shown). Character.place applies the slot rules (body location, two hands, mercenary slots)."""
    from mxl_char import CharError
    merc = win.is_merc()
    try:
        win.ch.place(clip[0], ('slot', slot), merc)       # refuses before it changes anything
    except (CharError, FormatError, OSError) as err:
        win.set_status(str(err), True)
        return
    if win.save(rc('pasted', '{name} pasted', name=clip[1]), operation='transfer') and not getattr(win, 'vanilla_he', False):
        _clear_char_clip(win)


def _clear_char_clip(win):
    win.app._capy_clip = None
    if getattr(win, 'vanilla_he', False):
        from mxl_vanilla_he import draw_pickup
        draw_pickup(win)


def clean_name(win, e):
    from mxl_creator_gui import clean
    return clean(e.it.get('name') or '')


# ------------------------------------------------------------------ Hero-Editor item functions
# "Change item quality" / "Specific editing functions" / "Export item" — the same menu features the
# original editor's right-click menu has, written like everything else here: the item's bytes are decoded,
# the record is adjusted, re-encoded losslessly in place (socketed items stay behind it) and written
# through the safe writers. Stash and character items share the record-level logic below.

from mxl_creator import (decode_item, encode_item, CreateError, FLAG_ETHEREAL, FLAG_PERSONALIZED,
                         FLAG_RUNEWORD, FLAG_SOCKETED, FLAG_SIMPLE, LOC_SOCKETED,
                         is_cluster_container, stats_with_cluster_quantity,
                         CLUSTER_QUANTITY_STAT, CLUSTER_QUANTITY_MAX)

_QUALS = ('normal', 'superior', 'magic', 'rare', 'crafted', 'tempered', 'set', 'unique')


def _creator(app):
    cr = getattr(app, '_creator', None)
    if cr is None:
        from mxl_creator import Creator
        cr = app._creator = Creator(app.data)
    return cr


def _creator_for(holder):
    """The Creator cache (held on the app, shared with the Item Editor); holder may be the app or the
    character window."""
    return _creator(getattr(holder, 'app', holder))


def _mutate_stash(app, it, fn, msg):
    """fn(rec, cr, data) adjusts the decoded record of a stash item (returning False aborts); the
    re-encoded bytes replace the item at its own place, socketed items untouched."""
    try:
        blob = item_blob(read_file(app.path), it)
        rec, size = decode_item(blob, app.data)
        if rec['flags'] & FLAG_SIMPLE:
            raise EditError(rc('err.compact', 'this item is saved in the compact form: nothing to change here'))
        if fn(rec, _creator(app), app.data) is False:
            return
        new = encode_item(rec, app.data) + bytes(blob[size:])
        bak = edit_stash(app.path, app.data, remove=[it['_offset']],
                         insert=[(it['page'], it['x'], it['y'], new)], backup=app.needs_backup(app.path))
    except (EditError, FormatError, OSError, CreateError, ValueError) as e:
        _status(app, str(e), True)
        return
    _record_stash_replace(app, it, blob, _item_name(app, it, None))
    app.backup_made(app.path, bak)
    _selected(app, it['page'], it['x'], it['y'])
    _status(app, msg)


def _mutate_char(win, e, fn, msg):
    """Same as _mutate_stash for a character item: remove -> place -> save (the character editor's own
    flow; a result that no longer fits its spot is refused and nothing is written)."""
    import mxl_char as MC
    from mxl_char import CharError
    merc = win.is_merc()
    where = MC.where_of(e)
    path, before, name = win.ch.path, bytes(win.ch.raw), _item_name(win, None, e)
    try:
        blob = win.ch.stash_blob(e)
        rec, size = decode_item(blob, win.data)
        if rec['flags'] & FLAG_SIMPLE:
            raise CharError(rc('err.compact', 'this item is saved in the compact form: nothing to change here'))
        if fn(rec, _creator(win.app), win.data) is False:
            return
        new = encode_item(rec, win.data) + bytes(blob[size:])
        _char_replace(win, e, new, where, merc)
    except (CharError, FormatError, OSError, CreateError, ValueError) as err:
        win.reload()
        win.set_status(str(err), True)
        return
    if not win.save(msg):
        win.set_status(T('ch.err.not_saved', 'character not saved'), True)
        return
    _record_char_write(win, path, before, name)


# ---- change item quality

def _quality_to(rec, cr, data, code, q, pick=None, pick2=None):
    """Switches the record's quality the way Hero Editor's 'Change item quality' does: the quality fields
    are replaced, the rolled stats stay exactly as they are. pick = chosen set/unique row or rare-name
    index; pick2 = rare-name suffix index."""
    for k in ('subquality', 'prefix', 'suffix', 'set_unique_id', 'rare_names', 'rare_affixes'):
        rec.pop(k, None)
    rec['set_mask'] = 0
    rec['quality'] = q
    if q == 'superior':
        ch = cr.superior_choices(code)
        rec['subquality'] = pick if pick is not None else (ch[0] if ch else 0)
    elif q == 'magic':
        rec['prefix'] = rec['suffix'] = 0
    elif q in ('rare', 'crafted', 'tempered'):
        rec['rare_names'] = (pick + len(data.rare_suffix), pick2)
        rec['rare_affixes'] = [None] * 6
    elif q in ('set', 'unique'):
        rec['set_unique_id'] = pick
    # runeword items stay runewords: the flag, its runes and their stats are untouched


def _quality_ok(cr, code, q):
    """Whether the base can carry this quality (the creator's own rules; a set/unique row must exist)."""
    if q == 'normal':
        return True
    if q == 'superior':
        return bool(cr.superior_choices(code)) and cr.can_have_quality(code, 'superior')
    if q == 'magic':
        return cr.can_have_quality(code, 'magic')
    if q in ('rare', 'crafted', 'tempered'):
        if not cr.rare_name_choices(code)['rareprefix'] or not cr.rare_name_choices(code)['raresuffix']:
            return False
        return q != 'crafted' or bool(cr.craft_rows(code))
    if q in ('set', 'unique'):
        rows = cr.set_items() if q == 'set' else cr.uniques()
        return any(u[2]['code'] == code for u in rows)
    return False


def _owner(menu):
    """The window a dialog opened from a menu entry belongs to: a tk.Menu is a toplevel of its own, so
    menu.winfo_toplevel() was the (unposted) menu itself - dialogs were made its children / transients."""
    top = menu.winfo_toplevel()
    return menu._root() if isinstance(top, tk.Menu) else top


def _ask_pick(menu, title, options, on_pick):
    """Small modal listbox over [(value, label)]; Enter / double-click / OK picks."""
    root = _owner(menu)
    top = tk.Toplevel(root)
    top.title(title)
    top.transient(root)
    bar = tk.Frame(top)                      # packed first: the buttons get the bottom row, under the list
    bar.pack(side='bottom', fill='x')
    # 'dotbox' (Tk knows dotbox / none / underline): 'dotselect' raised a TclError here, so every rare /
    # crafted / tempered quality change and every "Which set / unique item?" choice did nothing
    lb = tk.Listbox(top, width=64, height=min(18, max(5, len(options))), activestyle='dotbox',
                    exportselection=False)
    for _, lab in options:
        lb.insert('end', lab)
    lb.pack(side='left', fill='both', expand=True, padx=4, pady=4)
    sb = tk.Scrollbar(top, command=lb.yview)
    sb.pack(side='right', fill='y')
    lb.config(yscrollcommand=sb.set)

    def ok(_e=None):
        sel = lb.curselection()
        if sel:
            top.destroy()
            on_pick(options[sel[0]][0])
    lb.bind('<Double-Button-1>', ok)
    lb.bind('<Return>', ok)
    tk.Button(bar, text=rc('ok', 'OK'), width=10, command=ok).pack(side='left', padx=4, pady=2)
    tk.Button(bar, text=rc('cancel', 'Cancel'), width=10, command=top.destroy).pack(side='right', padx=4, pady=2)
    top.bind('<Escape>', lambda _e: top.destroy())
    if options:
        lb.selection_set(0)                  # Enter right away picks the first entry instead of nothing
        lb.activate(0)
    try:                                     # centred over the editor, not at the screen's top left corner
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        x = root.winfo_rootx() + (root.winfo_width() - w) // 2
        y = root.winfo_rooty() + (root.winfo_height() - h) // 3
        top.geometry(f'+{max(0, min(x, top.winfo_screenwidth() - w))}+{max(0, min(y, top.winfo_screenheight() - h))}')
    except tk.TclError:
        pass
    lb.focus_set()


def _ask_rare_names(menu, cr, code, on_done):
    """Two-step rare-name pick (first part, then second part), like the game rolls them."""
    ch = cr.rare_name_choices(code)
    _ask_pick(menu, rc('name.pre', 'Rare name (first part)'), ch['rareprefix'],
              lambda a: _ask_pick(menu, rc('name.suf', 'Rare name (second part)'), ch['raresuffix'],
                                  lambda b: on_done(a, b)))


def _apply_quality(holder, menu, it, win, q):
    """Menu entry for one quality: asks for the pieces the quality needs (set/unique row, rare names,
    superior bonus), then writes through the picked values."""
    code = it['code'] if win is None else win.selected.it['code']
    cr = _creator_for(holder)
    pick = pick2 = None
    if q in ('set', 'unique'):
        rows = [(u[0], u[1]) for u in (cr.set_items() if q == 'set' else cr.uniques()) if u[2]['code'] == code]
        if len(rows) > 1:
            _ask_pick(menu, rc('quality.pick', 'Which {q} item?', q=rc('q.' + q, q)), rows,
                      lambda row: _apply_quality_picked(holder, it, win, q, row))
            return
        pick = rows[0][0]
    elif q in ('rare', 'crafted', 'tempered'):
        _ask_rare_names(menu, cr, code,
                        lambda a, b: _apply_quality_picked(holder, it, win, q, a, b))
        return
    elif q == 'superior' and len(cr.superior_choices(code)) > 1:
        ch = cr.superior_choices(code)
        _ask_pick(menu, rc('quality.sup', 'Superior bonus'), [(i, _sup_label(holder, i)) for i in ch],
                  lambda v: _apply_quality_picked(holder, it, win, q, v))
        return
    _apply_quality_picked(holder, it, win, q, pick, pick2)


def _sup_label(holder, i):
    """A superior bonus as the Creator's Superior box shows it ("[3] Enhanced Defense 5-15"); it was only
    "Bonus #4", which said nothing about the bonus."""
    try:
        import mxl_creator_gui
        return mxl_creator_gui.CreatorWindow.sup_label(types.SimpleNamespace(data=holder.data), i)
    except Exception:
        return rc('quality.supn', 'Bonus #{n}', n=i + 1)


def _apply_quality_picked(holder, it, win, q, pick=None, pick2=None):
    code = it['code'] if win is None else win.selected.it['code']
    msg = rc('quality.set', '{name}: quality is now {q}',
             name=_item_name(holder, it, win.selected if win is not None else None), q=rc('q.' + q, q))

    def fn(rec, cr, data):
        _quality_to(rec, cr, data, code, q, pick, pick2)
        return True
    if win is None:
        _mutate_stash(holder, it, fn, msg)
    else:
        _mutate_char(win, win.selected, fn, msg)


def _quality_cascade(holder, menu, code, cur, win=None, it=None):
    """'Change item quality (now X)' with one entry per quality the base can carry, the Hero-Editor way."""
    cr = _creator_for(holder)
    qm = tk.Menu(menu, tearoff=0)
    for q in _QUALS:
        if q == cur:
            continue
        if not _quality_ok(cr, code, q):
            qm.add_command(label=rc('q.' + q, q), state='disabled')
            continue
        multi = q in ('rare', 'crafted', 'tempered') \
            or q in ('set', 'unique') and len([u for u in (cr.set_items() if q == 'set' else cr.uniques())
                                               if u[2]['code'] == code]) > 1 \
            or q == 'superior' and len(cr.superior_choices(code)) > 1
        qm.add_command(label=rc('q.' + q, q) + (rc('pick.dots', '...') if multi else ''),
                       command=lambda q=q: _apply_quality(holder, menu, it, win, q))
    menu.add_cascade(label=rc('quality.title', 'Change item quality (now {q})', q=rc('q.' + cur, cur)), menu=qm)


# ---- specific editing functions (defense / durability / ethereal / sockets / personalize / clear mods)

def _store_ok(data, sid, v):
    c = data.isc[sid]
    return 0 <= v + c['add'] < (1 << c['bits'])


def _ethereal_to(rec, data, code, make):
    """Toggles the ethereal flag with the game's own consequences (the creator's rules): stored defense
    x3/2 (or back x2/3) and max durability /2 + 1 (or back x2-2)."""
    kind = body_kind(data, code)
    if make:
        if rec['flags'] & FLAG_ETHEREAL:
            return
        rec['flags'] |= FLAG_ETHEREAL
    else:
        if not rec['flags'] & FLAG_ETHEREAL:
            return
        rec['flags'] &= ~FLAG_ETHEREAL
    if kind == 'armor':
        c = data.isc[S.DEFENSE]
        v = rec['defense'] * 3 // 2 if make else rec['defense'] * 2 // 3
        if not _store_ok(data, S.DEFENSE, v):
            raise CreateError(rc('eth.store', 'the resulting defense ({v}) does not fit the save format', v=v))
        rec['defense'] = v
    if kind in ('armor', 'weapons') and rec['max_durability'] != data.isc[S.MAX_DURABILITY]['add']:
        cm, cd = data.isc[S.MAX_DURABILITY], data.isc[S.DURABILITY]
        dur = rec['max_durability'] - cm['add']
        dur = dur // 2 + 1 if make else (dur - 1) * 2
        if not _store_ok(data, S.MAX_DURABILITY, dur):
            raise CreateError(rc('eth.dur', 'the resulting durability ({v}) does not fit the save format', v=dur))
        rec['max_durability'] = dur + cm['add']
        rec['durability'] = dur + cd['add']


def _specific_cascade(holder, menu, code, rec, win=None, it=None, e=None):
    """'Specific editing functions', Hero Editor's submenu: defense, durability, ethereal, sockets,
    personalize, and clearing all magic attributes. Written the same decode -> adjust -> encode way."""
    data = holder.data
    cr = _creator_for(holder)
    kind = body_kind(data, code)
    base = data.base(code)
    write = (lambda fn, msg: _mutate_stash(holder, it, fn, msg)) if win is None else \
            (lambda fn, msg: _mutate_char(win, e, fn, msg))

    sp = tk.Menu(menu, tearoff=0)
    if kind == 'armor':
        c = data.isc[S.DEFENSE]
        sp.add_command(label=rc('sp.defense', 'Set defense... (now {n}, up to {m})',
                                n=rec['defense'], m=(1 << c['bits']) - 1 - c['add']),
                       command=lambda: _ask_value(menu, rc('sp.defense2', 'Defense'),
                                                  rc('sp.defense_ask', 'Defense (0 to {m}):', m=(1 << c['bits']) - 1 - c['add']),
                                                  rec['defense'], 0, (1 << c['bits']) - 1 - c['add'],
                                                  lambda v: write(lambda r, cr2, d: (r.__setitem__('defense', v) or True),
                                                                  rc('sp.set', '{name}: defense is now {n}',
                                                                     name=_item_name(holder, it, e), n=v))))
    if kind in ('armor', 'weapons'):
        cm = data.isc[S.MAX_DURABILITY]
        indestructible = rec['max_durability'] == cm['add']
        if not indestructible:
            dcur = rec.get('durability')
            sp.add_command(label=rc('sp.dur', 'Set durability... (now {n})', n=dcur if dcur is not None else 0),
                           command=lambda: _ask_value(menu, rc('sp.dur2', 'Durability'),
                                                      rc('sp.dur_ask', 'Durability (1 to {m}):', m=rec['max_durability'] - cm['add']),
                                                      dcur or 0, 1, rec['max_durability'] - cm['add'],
                                                      lambda v: write(lambda r, cr2, d: (r.__setitem__('durability', v) or True),
                                                                      rc('sp.set2', '{name}: durability is now {n}',
                                                                         name=_item_name(holder, it, e), n=v))))
        else:
            sp.add_command(label=rc('sp.indest', 'Indestructible'), state='disabled')
        if not indestructible:
            sp.add_command(label=rc('sp.make_indest', 'Make indestructible'),
                           command=lambda: write(lambda r, cr2, d: (
                               r.__setitem__('max_durability', cm['add']), r.pop('durability', None), True)[2],
                               rc('sp.indest_set', '{name}: indestructible', name=_item_name(holder, it, e))))
    if rec['flags'] & FLAG_ETHEREAL:
        sp.add_command(label=rc('sp.un_eth', 'Remove ethereal'),
                       command=lambda: write(lambda r, cr2, d: (_ethereal_to(r, d, code, False) or True),
                                             rc('sp.eth_off', '{name}: no longer ethereal', name=_item_name(holder, it, e))))
    else:                                         # any item can be ethereal
        sp.add_command(label=rc('sp.eth', 'Make ethereal'),
                       command=lambda: write(lambda r, cr2, d: (_ethereal_to(r, d, code, True) or True),
                                             rc('sp.eth_on', '{name}: ethereal', name=_item_name(holder, it, e))))
    if rec.get('socketed_count', 0) == 0:
        ms = cr.max_sockets(code, rec['ilvl'])
        if ms > 0 and not rec['flags'] & FLAG_SOCKETED:
            sp.add_command(label=rc('sp.sockets', 'Make socketed... (up to {n})', n=ms),
                           command=lambda: _ask_value(menu, rc('sp.sockets2', 'Sockets'),
                                                      rc('sp.sockets_ask', 'Number of sockets (1 to {n}):', n=ms),
                                                      1, 1, ms,
                                                      lambda v: write(lambda r, cr2, d: (
                                                          r.__setitem__('flags', r['flags'] | FLAG_SOCKETED),
                                                          r.__setitem__('sockets', v),
                                                          r.__setitem__('socketed_count', 0), True)[3],
                                                          rc('sp.sockets_set', '{name}: {n} sockets', name=_item_name(holder, it, e), n=v))))
    elif rec['flags'] & FLAG_SOCKETED:
        # Hero Editor's mnuRemoveSocketed: delete the socketed children and clear the socket fields
        # (the children's bytes live behind the record, so this writes through its own writer)
        sp.add_command(label=rc('sp.un_sockets', 'Remove socketed items ({n})', n=rec.get('socketed_count', 0)),
                       command=lambda: _remove_socketed(holder, it, win, e))
    if rec['flags'] & FLAG_PERSONALIZED:
        sp.add_command(label=rc('sp.un_pers', 'Remove personalization ({n})', n=rec.get('personalized_name', '')),
                       command=lambda: write(lambda r, cr2, d: (
                           r.__setitem__('flags', r['flags'] & ~FLAG_PERSONALIZED), r.pop('personalized_name', None), True)[2],
                           rc('sp.unpers_set', '{name}: personalization removed', name=_item_name(holder, it, e))))
    else:
        sp.add_command(label=rc('sp.pers', 'Personalize...'),
                       command=lambda: _ask_personalize(menu, lambda s: write(
                           lambda r, cr2, d: (
                               r.__setitem__('flags', r['flags'] | FLAG_PERSONALIZED),
                               r.__setitem__('personalized_name', s), True)[2],
                           rc('sp.pers_set', '{name}: personalized ({s})', name=_item_name(holder, it, e), s=s))))
    if rec['stats']:
        sp.add_command(label=rc('sp.clear', 'Delete all magic attributes ({n})', n=len(rec['stats'])),
                       command=lambda: write(lambda r, cr2, d: (r.__setitem__('stats', []) or True),
                                             rc('sp.clear_set', '{name}: all magic attributes deleted',
                                                name=_item_name(holder, it, e))))
    try:                                   # 'Make perfect': every roll at its maximum (replaces the value sliders)
        import mxl_perfect
        mxl_perfect.add_menu(sp, holder, it=it, win=win, e=e, name=_item_name(holder, it, e))
    except Exception as err:               # never keeps the menu from opening
        _dbg('make perfect entry:', err)
    menu.add_cascade(label=rc('sp.title', 'Specific editing functions'), menu=sp)


def _item_name(holder, it, e):
    from mxl_creator_gui import clean
    name = (it or {}).get('name') if it is not None else e.it.get('name')
    return clean(name or '')


def _ask_value(menu, title, prompt, cur, lo, hi, on_ok):
    from tkinter import simpledialog
    v = simpledialog.askinteger(title, prompt, parent=_owner(menu),
                                initialvalue=max(lo, min(hi, cur)), minvalue=lo, maxvalue=hi)
    if v is None:
        return
    on_ok(max(lo, min(hi, v)))


def _ask_personalize(menu, on_ok):
    from tkinter import simpledialog, messagebox
    s = simpledialog.askstring(rc('sp.pers2', 'Personalize'),
                               rc('sp.pers_ask', 'Name to engrave on the item (2 to 15 ASCII characters):'),
                               parent=_owner(menu))
    if not s:
        return
    s = s.strip()
    if not 2 <= len(s) <= 15 or any(not 32 <= ord(c) <= 126 for c in s):
        messagebox.showerror(rc('sp.pers2', 'Personalize'),
                             rc('sp.pers_bad', 'Use 2 to 15 letters / numbers (ASCII).'),
                             parent=_owner(menu))
        return
    on_ok(s)


# ---- export / import (Hero Editor's item files; the bytes are exactly the stash's own item format)
def _export_stash(app, it):
    from tkinter import filedialog
    try:
        blob = _now(app, it)[2]
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return
    path = filedialog.asksaveasfilename(defaultextension='.d2i',
                                        initialfile=app.full_name(it).replace('/', '_') + '.d2i',
                                        title=rc('exp.title', 'Export item'),
                                        parent=app.root if hasattr(app, 'root') else app.canvas)
    if not path:
        return
    try:
        with open(path, 'wb') as f:
            f.write(blob)
    except OSError as e:
        _status(app, str(e), True)
        return
    _status(app, rc('exp.done', '{name} exported to {file}', name=app.full_name(it),
                    file=os.path.basename(path)))


def _export_char(win, e):
    from tkinter import filedialog
    path = filedialog.asksaveasfilename(defaultextension='.d2i',
                                        initialfile=clean_name(win, e).replace('/', '_') + '.d2i',
                                        title=rc('exp.title', 'Export item'), parent=win.top)
    if not path:
        return
    try:
        with open(path, 'wb') as f:
            f.write(win.ch.stash_blob(e))
    except (OSError, AttributeError) as err:
        win.set_status(str(err), True)
        return
    win.set_status(rc('exp.done', '{name} exported to {file}', name=clean_name(win, e),
                      file=os.path.basename(path)))


def _import_stash(app, ev):
    from tkinter import filedialog
    path = filedialog.askopenfilename(title=rc('imp.title', 'Import item'),
                                      filetypes=[(rc('exp.files', 'Item files'), '*.d2i'), ('*.*', '*.*')],
                                      parent=app.root if hasattr(app, 'root') else app.canvas)
    if not path:
        return
    try:
        with open(path, 'rb') as f:
            blob = f.read()
        blob_item(blob, app.data)          # validates before anything is written
        page = app.page()
        cx, cy = ev.x // app.cell, ev.y // app.cell
        bak = edit_stash(app.path, app.data, insert=[(page, cx, cy, blob)], backup=app.needs_backup(app.path))
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return
    app.backup_made(app.path, bak)
    _selected(app, page, cx, cy)
    _status(app, rc('imp.done', 'item imported from {file}', file=os.path.basename(path)))


def _import_char(win, ev):
    from tkinter import filedialog
    from mxl_char import CharError
    path = filedialog.askopenfilename(title=rc('imp.title', 'Import item'),
                                      filetypes=[(rc('exp.files', 'Item files'), '*.d2i'), ('*.*', '*.*')],
                                      parent=win.top)
    if not path:
        return
    try:
        with open(path, 'rb') as f:
            blob = f.read()
        blob_item(blob, win.data)
        win.ch.place(blob, ('inv', ev.x // win.cell, ev.y // win.cell), win.is_merc())
    except (CharError, FormatError, OSError) as err:
        win.set_status(str(err), True)
        win.reload()
        return
    win.app._capy_clip = None
    win.save(rc('imp.done', 'item imported from {file}', file=os.path.basename(path)))


# ---- inspector (mxl_inspect) and personal item library (mxl_itemlib): read the item's bytes as Export does
def _inspect_stash(app, it):
    import mxl_bitedit
    try:
        blob = _now(app, it)[2]
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return None
    src = {k: it.get(k) for k in ('page', 'x', 'y', 'code', '_offset')}
    return mxl_bitedit.open_item(app, blob, app.full_name(it), source=src)


def _inspect_char(win, e):
    import mxl_bitedit
    try:
        blob = win.ch.stash_blob(e)
    except (OSError, AttributeError) as err:
        win.set_status(str(err), True)
        return None
    return mxl_bitedit.open_item(win.app, blob, clean_name(win, e), source=None,
                                 reason=rc('bitedit.char', 'character item: read only here'))


def _library_stash(app, it):
    import mxl_itemlib
    try:
        blob = _now(app, it)[2]
    except (EditError, FormatError, OSError) as e:
        _status(app, str(e), True)
        return None
    entry = mxl_itemlib.ask_add(app.root if hasattr(app, 'root') else app.canvas, blob, app.data, app.full_name(it))
    if entry is not None:
        _status(app, rc('lib.added', '{name} added to the item library', name=entry['name']))
    return entry


def _library_char(win, e):
    import mxl_itemlib
    try:
        blob = win.ch.stash_blob(e)
    except (OSError, AttributeError) as err:
        win.set_status(str(err), True)
        return None
    entry = mxl_itemlib.ask_add(win.top, blob, win.data, clean_name(win, e))
    if entry is not None:
        win.set_status(rc('lib.added', '{name} added to the item library', name=entry['name']))
    return entry


# ------------------------------------------------------------------ the Hero-Editor submenu pair

def _add_hero_editor_menu(holder, menu, it=None, win=None, e=None):
    """'Change item quality' + 'Specific editing functions' for one item, shared by the stash and the
    character menus. Needs the item's decoded record; silently absent when it cannot be decoded."""
    try:
        if win is None:
            blob = item_blob(read_file(holder.path), it)
            rec, _n = decode_item(blob, holder.data)
            code = it['code']
        else:
            blob = win.ch.stash_blob(e)
            rec, _n = decode_item(blob, win.data)
            code = e.it['code']
    except (EditError, FormatError, OSError, CreateError, AttributeError, ValueError):
        return
    if rec['flags'] & FLAG_SIMPLE:
        return
    _quality_cascade(holder, menu, code, rec['quality'], win=win, it=it)
    _specific_cascade(holder, menu, code, rec, win=win, it=it, e=e)
    # the magic-attributes buffer (Hero Editor's mnuAddAllMagicAttributesToBuffer & friends)
    app = getattr(holder, 'app', holder)
    buf = _magic_buf(app)
    if rec['stats'] or rec.get('stats_runeword'):
        menu.add_command(label=rc('buf.add_menu', 'Add all magic attributes to buffer ({n})',
                                  n=len(rec['stats'])),
                         command=lambda: _add_magic_to_buffer(holder, it, win, e))
    if buf:
        menu.add_command(label=rc('buf.paste_menu', 'Paste magic attributes from buffer ({src}: {n})',
                                  src=buf['name'], n=len(buf['stats'])),
                         command=lambda: _paste_magic_from_buffer(holder, it, win, e))
        menu.add_command(label=rc('buf.clear_menu', 'Delete magic attribute buffer'),
                         command=lambda: _delete_magic_buffer(holder, win))


def _cut(app, it):
    """Hero Editor's cut: the item goes to the clipboard (paste it anywhere afterwards) and is removed."""
    if not _copy(app, it):                 # not copied (an out-of-date view...): nothing is removed either
        return
    from mxl_creator_gui import delete_selected
    delete_selected(app)


# ------------------------------------------------------------------ fill sockets (Hero Editor's Paste Fill)
# The original editor's 'Paste Fill' auto-sockets copies of a 1x1 clipboard item (jewel / rune / gem) into the
# selected item's free sockets.  Here: a socketed item's children are the records right behind it, and the
# base's real socket cap (the creator's max_sockets) limits how many copies are appended.  The copies keep
# their own bytes; only their location fields are rewritten to 'socketed in this parent'.

def _children_blobs(blob, data):
    """(parent record, [raw child blobs]) of a stash entry."""
    rec, size = decode_item(blob, data)
    kids, p = [], size
    if rec['flags'] & FLAG_SOCKETED:
        for _ in range(rec.get('socketed_count', 0)):
            _k, m = decode_item(blob[p:], data)
            kids.append(bytes(blob[p:p + m]))
            p += m
    return rec, kids


def _relocate_child(blob, data, index):
    """One child's bytes with its location rewritten to 'socketed, slot index'."""
    rec, size = decode_item(blob, data)
    rec['location'] = LOC_SOCKETED
    rec['equipped'] = 0
    rec['x'] = index
    rec['y'] = 0
    rec['panel'] = 0
    return encode_item(rec, data) + bytes(blob[size:])


MAX_SOCKETED = 6        # what the game shows on an item; the count field of the record is 3 bits


def _unrestricted():
    """The creator's 'Unrestricted' switch (remembered setting)."""
    try:
        import settings
        return bool(settings.get('capy_unrestricted'))
    except Exception:
        return False


def _socket_limit(holder, code, rec):
    """How many sockets this item may have: the base's cap from the game tables at the item's level;
    with Unrestricted on, weapons and armor may have the game's 6 whatever their base says."""
    data = holder.data
    try:
        ms = _creator_for(holder).max_sockets(code, rec['ilvl'])
    except (KeyError, IndexError, AttributeError):
        ms = 0
    if _unrestricted() and body_kind(data, code) in ('armor', 'weapons'):
        ms = MAX_SOCKETED
    return min(ms, MAX_SOCKETED)


def _fill_plan(holder, blob, code):
    """What 'Fill sockets' would do on this entry: (record, [child blobs], sockets now, copies to add,
    sockets after).  Free sockets are filled first; an item without a free socket (not socketed at all, or
    full) gets new sockets up to its limit - a runeword does not, its socket count is its rune list.
    Raises CreateError when nothing can be done."""
    from mxl_creator import CreateError
    data = holder.data
    rec, kids = _children_blobs(blob, data)
    if rec['flags'] & FLAG_SIMPLE:
        raise CreateError(rc('fill.compact', 'this item cannot have sockets'))
    have = max(rec.get('sockets', 0), len(kids)) if rec['flags'] & FLAG_SOCKETED else 0
    total = min(have, 7)                                     # 7: what the 3-bit count field holds
    if total <= len(kids) and not rec['flags'] & FLAG_RUNEWORD:
        total = max(total, _socket_limit(holder, code, rec))
    free = total - len(kids)
    if free <= 0:
        raise CreateError(rc('fill.none', 'no sockets available on this item'))
    return rec, kids, have, free, total


def _filler_ok(holder, clip):
    chrec, _n = decode_item(clip[0], holder.data)
    return any(c == chrec['code'] for c, _n2 in _creator_for(holder).sockets_fillers())


def _fill_sockets(holder, it, win=None, e=None):
    """Appends copies of the clipboard item (a gem / rune, the creator's own filler list) into the item's
    free sockets; an item without a free socket gets sockets first, up to the base's cap (_fill_plan).
    Stash items go through edit_stash, character items through remove -> place -> save.
    The parent record always carries what its children need: the socketed flag, a socket count that
    covers them, and their number (children behind a record without the flag are not read as its
    children by any reader: the page's structure breaks)."""
    app = getattr(holder, 'app', holder)
    clip = getattr(app, '_capy_clip', None)
    if not clip:
        return
    from mxl_creator import CreateError
    import mxl_char as MC
    data = holder.data
    if win is None:
        getter = lambda: item_blob(read_file(holder.path), it)
    else:
        getter = lambda: win.ch.stash_blob(e)
    try:
        blob = getter()
        code = it['code'] if win is None else e.it['code']
        rec, kids, have, free, total = _fill_plan(holder, blob, code)
        if not _filler_ok(holder, clip):
            raise CreateError(rc('fill.filler', 'the copied item is not a socketable gem or rune'))
        parent = dict(rec, flags=rec['flags'] | FLAG_SOCKETED, sockets=max(have, total),
                      socketed_count=len(kids) + free)
        new = encode_item(parent, data) + b''.join(
            [_relocate_child(k, data, i) for i, k in enumerate(kids)]
            + [_relocate_child(clip[0], data, i) for i in range(len(kids), len(kids) + free)])
        # validates the grown entry before anything is written: it must read back as ONE item with all
        # its children, nothing left over
        back, used = decode_item(new, data)
        seen = blob_item(new, data)
        if not back['flags'] & FLAG_SOCKETED or back.get('socketed_count') != len(kids) + free \
                or len(_children_blobs(new, data)[1]) != len(kids) + free \
                or len(seen.get('socketed') or ()) != len(kids) + free:
            raise CreateError(rc('fill.invalid', 'the filled item would not be readable: nothing written'))
    except (EditError, FormatError, OSError, CreateError, AttributeError, ValueError, KeyError) as err:
        if win is None:
            _status(holder, str(err), True)
        else:
            win.set_status(str(err), True)
            win.reload()
        return
    name = clip[1]
    msg = rc('fill.done', '{n} x {name} socketed', n=free, name=name)
    if total > have:
        msg += rc('fill.added', ' ({n} sockets added)', n=total - have)
    if win is None:
        try:
            bak = edit_stash(holder.path, holder.data, remove=[it['_offset']],
                             insert=[(it['page'], it['x'], it['y'], new)],
                             backup=holder.needs_backup(holder.path))
        except (EditError, FormatError, OSError) as err:
            _status(holder, str(err), True)
            return
        _record_fill(app, 'replace', blob=bytes(blob), after=bytes(new), page=it['page'], x=it['x'], y=it['y'],
                     old_page=it['page'], old_x=it['x'], old_y=it['y'], name=_item_name(holder, it, None))
        holder.backup_made(holder.path, bak)
        _selected(holder, it['page'], it['x'], it['y'])
        _status(holder, msg + T('undo.hint_any', ' - Ctrl+Z undoes it'))
    else:
        merc = win.is_merc()
        where = MC.where_of(e)
        path, before = win.ch.path, bytes(win.ch.raw)      # what is on disk: save() refuses anything else
        name = _item_name(holder, None, e)
        try:
            _char_replace(win, e, new, where, merc)
        except Exception as err:
            win.reload()
            win.set_status(str(err), True)
            return
        if not win.save(msg + T('undo.hint_any', ' - Ctrl+Z undoes it')):
            win.set_status(T('ch.err.not_saved', 'character not saved'), True)
            return
        try:
            after = read_file(path)
        except OSError:
            return
        if bytes(after) != before:
            import mxl_undo
            mxl_undo.record_char(app, path, before, after, name)


def _record_fill(app, kind, **kw):
    """The undo record of a stash fill (mxl_undo; never breaks the write it records)."""
    try:
        import mxl_undo
        mxl_undo.record(app, kind, **kw)
    except Exception as err:
        _dbg('fill sockets: undo not recorded:', err)


def _record_stash_replace(app, it, old_blob, name):
    """Undo record of a stash item replaced in place (quantity, quality, ethereal, personalize, paste over it...):
    Ctrl+Z puts the previous bytes back while the item is still as written. These actions had no undo, and the
    session's one backup is taken before the first write only: a paste over the wrong item lost it."""
    try:
        buf = read_file(app.path)
        cur = next((i for i in parse_stash(app.path, app.data)
                    if (i['page'], i['x'], i['y']) == (it['page'], it['x'], it['y'])), None)
        if cur is None:
            return
        _record_fill(app, 'replace', blob=bytes(old_blob), after=bytes(item_blob(buf, cur)), page=it['page'],
                     x=it['x'], y=it['y'], old_page=it['page'], old_x=it['x'], old_y=it['y'], name=name)
    except Exception as err:
        _dbg('undo not recorded:', err)


def _record_char_write(win, path, before, name):
    """Undo record of a character item action (the character file's bytes before / after, mxl_undo 'char')."""
    try:
        after = read_file(path)
        if bytes(after) != bytes(before):
            import mxl_undo
            mxl_undo.record_char(getattr(win, 'app', win), path, before, after, name)
    except Exception as err:
        _dbg('undo not recorded:', err)


def _socket_cascade(holder, menu, it=None, win=None, e=None):
    """'Socket' submenu: Add Sockets (N) / Remove Sockets / Unsocket (mxl_socket_menu); never keeps the menu from
    opening."""
    try:
        import mxl_socket_menu
        mxl_socket_menu.add_menu(holder, menu, it=it, win=win, e=e)
    except Exception as err:
        _dbg('socket menu:', err)


def _remove_socketed(holder, it, win=None, e=None):
    """Hero Editor's mnuRemoveSocketed: the socket menu's Remove Sockets (mxl_socket_menu: undoable, the 1.14d
    item_numsockets stat goes too)."""
    import mxl_socket_menu
    return mxl_socket_menu.remove_sockets(holder, it, win, e)


def _fill_sockets_entry(holder, menu, it, win=None, e=None):
    """The menu entry, only when the action can work: the clipboard holds a socketable filler and the item
    has free sockets, or can be given some (then the label says how many are added)."""
    app = getattr(holder, 'app', holder)
    clip = getattr(app, '_capy_clip', None)
    if not clip:
        return
    try:
        blob = win.ch.stash_blob(e) if win is not None else item_blob(read_file(holder.path), it)
        code = it['code'] if win is None else e.it['code']
        rec, kids, have, free, total = _fill_plan(holder, blob, code)
        if not _filler_ok(holder, clip):
            return
    except (EditError, FormatError, OSError, CreateError, AttributeError, ValueError, KeyError, IndexError):
        return
    if total > have:
        label = rc('fill.menu_add', 'Fill sockets with {name} (adds {n} sockets: {k} of {m})',
                   name=clip[1], n=total - have, k=len(kids), m=total)
    else:
        label = rc('fill.menu', 'Fill sockets with {name} (now {k} of {m})', name=clip[1], k=len(kids), m=total)
    menu.add_command(label=label, command=lambda: _fill_sockets(holder, it, win, e))


# ------------------------------------------------------------------ magic-attributes buffer
# Hero Editor's mnuAddAllMagicAttributesToBuffer / PasteMagicAttributesfromBuffer (the paste handler is
# commented out in the VB6 source; here it works): an item's whole stat list (its runeword list included,
# kept apart) is held in a shared buffer, and another item can take it over wholesale. Replacing the list
# changes the record's size — written through the same splice writers as everything else.

def _magic_buf(app):
    return getattr(app, '_capy_magicbuf', None)


def _say(holder, win, msg, error=False):
    if win is None:
        _status(holder, msg, error)
    else:
        win.set_status(msg, error)


def _add_magic_to_buffer(holder, it, win=None, e=None):
    app = getattr(holder, 'app', holder)
    data = holder.data
    try:
        blob = win.ch.stash_blob(e) if win is not None else _now(holder, it)[2]
        rec, _n = decode_item(blob, data)
    except (EditError, FormatError, OSError, CreateError, AttributeError, ValueError) as err:
        _say(holder, win, str(err), True)
        return
    if rec['flags'] & FLAG_SIMPLE or not rec['stats'] and not rec.get('stats_runeword'):
        _say(holder, win, rc('buf.none', 'this item has no magic attributes to buffer'), True)
        return
    name = _item_name(holder, it, e)
    app._capy_magicbuf = {'stats': [dict(s) for s in rec['stats']],
                          'rw': [dict(s) for s in rec.get('stats_runeword', [])],
                          'name': name}
    _say(holder, win, rc('buf.added', '{n} magic attributes buffered from {name}',
                         n=len(rec['stats']), name=name))


def _paste_magic_from_buffer(holder, it, win=None, e=None):
    app = getattr(holder, 'app', holder)
    buf = _magic_buf(app)
    if not buf:
        return

    def fn(rec, cr, data):
        rec['stats'] = [dict(s) for s in buf['stats']]
        if buf['rw']:
            rec['stats_runeword'] = [dict(s) for s in buf['rw']]
        else:
            rec.pop('stats_runeword', None)
        return True

    msg = rc('buf.pasted', '{name}: magic attributes replaced with {n} from {src}',
             name=_item_name(holder, it, e), n=len(buf['stats']), src=buf['name'])
    if win is None:
        _mutate_stash(holder, it, fn, msg)
    else:
        _mutate_char(win, e, fn, msg)


def _delete_magic_buffer(holder, win=None):
    app = getattr(holder, 'app', holder)
    if _magic_buf(app):
        app._capy_magicbuf = None
        _say(holder, win, rc('buf.cleared', 'magic attribute buffer deleted'))


# ------------------------------------------------------------------ keyboard shortcuts (at the mouse cursor)
# Hero-Editor-style hotkeys, acting on the item under the mouse cursor:
#   Ctrl+C / Ctrl+V              copy / paste the item itself (an empty stash cell or inventory cell
#                                pastes there, an occupied one is replaced)
#   Ctrl+Shift+C / Ctrl+Shift+V  copy the item's magic attributes to the shared buffer / paste the
#                                buffer's attributes onto the item under the cursor
# They are bound on the two windows themselves (never bind_all: Ctrl+C stays the text copy inside
# entry fields) and only act while the mouse pointer is over the stash grid / a character canvas.

def _bind_hotkeys(widget, canvases, dispatch):
    """Binds the four shortcuts on one window; dispatch('copy' | 'paste' | 'magic_copy' | 'magic_paste')
    resolves the canvas under the mouse pointer itself and acts on the item at that spot."""
    if widget is None:
        _dbg('hotkeys: no widget to bind on!')
        return

    def on_key(key):
        ev = _canvas_at_pointer(canvases)
        _dbg('key', key, '- pointer over canvas:', ev is not None,
             canvases[0]._w if canvases else '')
        if ev is not None:
            dispatch(key)

    try:
        # add='+': the stash and the character window share the root window when the character
        # is a tab, so their bindings must not replace each other - each handler ignores keys
        # whose mouse pointer is not over its own canvases
        widget.bind('<Control-KeyPress-c>', lambda e: on_key('copy'), add='+')
        widget.bind('<Control-KeyPress-C>', lambda e: on_key('copy'), add='+')
        widget.bind('<Control-KeyPress-v>', lambda e: on_key('paste'), add='+')
        widget.bind('<Control-KeyPress-V>', lambda e: on_key('paste'), add='+')
        widget.bind('<Control-Shift-KeyPress-C>', lambda e: on_key('magic_copy'), add='+')
        widget.bind('<Control-Shift-KeyPress-c>', lambda e: on_key('magic_copy'), add='+')
        widget.bind('<Control-Shift-KeyPress-V>', lambda e: on_key('magic_paste'), add='+')
        widget.bind('<Control-Shift-KeyPress-v>', lambda e: on_key('magic_paste'), add='+')
        _dbg('hotkeys bound on', getattr(widget, '_w', widget), '->', widget.bind())
    except Exception as e:
        print('item hotkeys not installed:', e)


def _canvas_at_pointer(canvases):
    """A small event-like object (widget, x, y) for the canvas holding the mouse pointer, or None."""
    if not canvases:
        return None
    try:
        px, py = canvases[0].winfo_pointerx(), canvases[0].winfo_pointery()
    except Exception:
        return None
    for cv in canvases:
        try:
            x, y = px - cv.winfo_rootx(), py - cv.winfo_rooty()
            if 0 <= x < cv.winfo_width() and 0 <= y < cv.winfo_height():
                return types.SimpleNamespace(widget=cv, x=x, y=y)
        except Exception:
            pass
    return None


def _stash_hot(app, what):
    """Ctrl+C / Ctrl+V / Ctrl+Shift+C / Ctrl+Shift+V over the stash grid."""
    ev = _canvas_at_pointer([app.canvas])
    if ev is None:
        _dbg('stash hot', what, '- pointer not over the stash grid, ignored')
        return
    try:
        it = app.item_at(ev)
    except Exception:
        it = None
    _dbg('stash hot', what, '- item:', it['code'] if it else None)
    clip = getattr(app, '_capy_clip', None)
    if what == 'copy':
        if it is None:
            _status(app, rc('hot.none', 'no item under the mouse cursor'), True)
        else:
            _copy(app, it)
    elif what == 'paste':
        if clip is None:
            _status(app, rc('hot.noclip', 'the item clipboard is empty (copy an item first)'), True)
        elif it is not None:
            _paste(app, it, clip)
        else:
            _paste_empty(app, ev, clip)
    elif what == 'magic_copy':
        if it is None:
            _status(app, rc('hot.none', 'no item under the mouse cursor'), True)
        else:
            _add_magic_to_buffer(app, it)
    elif what == 'magic_paste':
        if _magic_buf(app) is None:
            _status(app, rc('hot.nobuf', 'the magic-attribute buffer is empty (copy attributes first)'), True)
        elif it is None:
            _status(app, rc('hot.none', 'no item under the mouse cursor'), True)
        else:
            _paste_magic_from_buffer(app, it)


def _char_hot(win, what):
    """The same four shortcuts over the character window's doll / inventory canvases."""
    ev = _canvas_at_pointer([win.inv, win.doll])
    if ev is None:
        _dbg('char hot', what, '- pointer not over a character canvas, ignored')
        return
    _sync(win)
    try:
        e, slot = win.entry_at(ev.widget, ev)
    except Exception:
        e, slot = None, None
    if e is not None:
        win.selected = e                  # the entry the writers below work on (and what stays selected)
    _dbg('char hot', what, '- item:', e.it['code'] if e is not None else None)
    clip = getattr(win.app, '_capy_clip', None)
    if what == 'copy':
        if e is None:
            win.set_status(rc('hot.none', 'no item under the mouse cursor'), True)
        else:
            _char_copy(win, e)
    elif what == 'paste':
        if clip is None:
            win.set_status(rc('hot.noclip', 'the item clipboard is empty (copy an item first)'), True)
        elif e is not None:
            _char_paste_over(win, e, clip)
        elif ev.widget is win.inv:
            _char_paste(win, ev, clip)
        elif slot is not None:
            _char_paste_slot(win, slot, clip)
        else:
            win.set_status(rc('hot.nospot', 'paste onto an inventory cell or an equipment slot'), True)
    elif what == 'magic_copy':
        if e is None:
            win.set_status(rc('hot.none', 'no item under the mouse cursor'), True)
        else:
            _add_magic_to_buffer(win, None, win=win, e=e)
    elif what == 'magic_paste':
        if _magic_buf(win.app) is None:
            win.set_status(rc('hot.nobuf', 'the magic-attribute buffer is empty (copy attributes first)'), True)
        elif e is None:
            win.set_status(rc('hot.none', 'no item under the mouse cursor'), True)
        else:
            _paste_magic_from_buffer(win, None, win=win, e=e)


def _char_paste_over(win, e, clip):
    """Ctrl+V over an occupied character slot / cell: the pasted item replaces the one there
    (the same remove -> place -> save flow the menus write with)."""
    import mxl_char as MC
    from mxl_char import CharError
    merc = win.is_merc()
    where = MC.where_of(e)
    path, before, name = win.ch.path, bytes(win.ch.raw), clean_name(win, e)
    try:
        _char_replace(win, e, clip[0], where, merc)
    except (CharError, FormatError, OSError) as err:
        win.reload()
        win.set_status(str(err), True)
        return
    if win.save(rc('pasted_over', '{name} pasted (the previous item is replaced)', name=clip[1]), operation='transfer'):
        if not getattr(win, 'vanilla_he', False):
            _clear_char_clip(win)
        _record_char_write(win, path, before, name)
