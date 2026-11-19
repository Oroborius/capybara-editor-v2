"""Instant, undoable deleting plus a multi-action undo (Ctrl+Z).

Deleting no longer asks: Delete with the cursor over an item removes it right away, the same as the
right-click menu's Delete (which also stopped prompting). Every destructive action of the main window
is recorded in a buffer (app._undo), and Ctrl+Z - or the new Undo button - steps back through it:
- delete: the item's exact bytes are kept, the undo puts the item back where it was;
- create (the creator's bulk copies included): the undo removes the written copies;
- replace (the creator's edit mode, Fill sockets on a stash item): the undo restores the previous bytes;
- char (Fill sockets on a character / mercenary item): the undo writes the character file's previous bytes,
  only while the file is still exactly what the action wrote (a later write - the Character tab's SAVE, another
  item action, the game - makes the undo refuse instead of putting older data over the newer file).
- files (an item dragged between stash pages, stash files, the inventory, the equipment, the mercenary - the main
  grid, the Stash tab's panel, the Character tab - and the Character tab's SAVE): every file the action changed
  goes back to its bytes of before, only while EVERY one of them is still exactly what the action wrote.

Each undo is one stash write through the collector's own safe writer (mxl_save.edit_stash), with the
usual backup policy and an instant grid refresh. The buffer holds the last 50 actions of this session.
"""
import os

from mxl_save import (edit_stash, parse_stash, free_spot, item_blob, blob_item, EditError,
                      STASH_PAGES, placement_error)
from mxl_lang import T

MAX_UNDO = 50


def record(app, kind, **kw):
    """Record an undoable action on the app's buffer (best effort: the undo must never break the
    action it records). A 'delete' op keeps the item's exact bytes; a 'replace' op is recorded after
    the write with the previous bytes already in kw['blob']. True when the action was recorded."""
    try:
        stack = getattr(app, '_undo', None)
        if stack is None:
            stack = app._undo = []
        op = dict(kind=kind, **kw)
        if kind in ('delete', 'replace') and 'blob' not in kw:
            blob = item_blob(open(app.path, 'rb').read(), kw['item'])
            op['blob'] = bytes(blob)
        # where the item stands in its page's item list in the file: the undo puts it back at that index,
        # so that action + undo gives the original file bytes (not only the same items)
        try:
            import mxl_stash_order
            if kind == 'delete' and 'index' not in kw:
                at = mxl_stash_order.page_index(app.path, app.data, kw['item']['_offset'])
                if at is not None and at[0] == op['page']:
                    op['index'] = at[1]
            elif kind == 'replace' and 'index' not in kw:
                # recorded after the write: the writer noted the index of the item it removed
                last = mxl_stash_order.last_removed
                if last and last.get('path') == os.path.abspath(app.path) and last.get('page') == op.get('old_page') \
                        and last.get('blob') == bytes(op['blob']):
                    op['index'] = last['index']
        except Exception:
            pass
        stack.append(op)
        del stack[:-MAX_UNDO]
        return True
    except Exception as e:
        # nothing was appended (the append is the last step that can fail): the stack stays as it was - popping
        # here threw away the PREVIOUS action's undo
        _log_error('undo: action not recorded (%s: %s)', type(e).__name__, e)
        return False


def _log_error(msg, *args):
    try:
        import mxl_log
        mxl_log.log.error(msg, *args)
    except Exception:
        pass


def can_undo(app):
    return bool(getattr(app, '_undo', None))


def undo(app):
    """Undo the last recorded action. Returns a status message, or None when nothing to undo."""
    stack = getattr(app, '_undo', None)
    if not stack:
        return None
    if stack[-1]['kind'] == 'char':
        return _undo_char(app, stack.pop())
    if stack[-1]['kind'] == 'files':
        return _undo_files(app, stack)
    if not app.path:
        return None
    op = stack.pop()
    try:
        items = parse_stash(app.path, app.data)
        if op['kind'] == 'delete':
            spot = (op['page'], op['x'], op['y'])
            index = op.get('index')
            new = blob_item(op['blob'], app.data)
            new['page'] = spot[0]
            if placement_error(items, new, spot[0], spot[1], spot[2], app.data):   # the place is taken (also
                spot = free_spot(items, new, app.data, (op['page'],) + tuple(         # partly, by a bigger item)
                    p for p in range(STASH_PAGES) if p != op['page']))
                if spot is None:
                    stack.append(op)
                    return T('undo.nospace', 'Undo: no free place for {name} any more',
                             name=op.get('name') or 'item')
            bak = edit_stash(app.path, app.data, insert=[_ins(spot, op['blob'], index, op['page'])],
                             backup=app.needs_backup(app.path))
            app.backup_made(app.path, bak)
            _refresh(app, spot)
            return T('undo.restored', 'Undo: {name} put back (page {page}, {x}, {y})',
                     name=op.get('name') or 'item', page=spot[0] + 1, x=spot[1], y=spot[2])
        if op['kind'] == 'create':
            spots = {tuple(s) for s in op['spots']}
            doomed = [i['_offset'] for i in items if (i['page'], i['x'], i['y']) in spots]
            if not doomed:
                return T('undo.gone', 'Undo: the copies are already gone')
            bak = edit_stash(app.path, app.data, remove=doomed, backup=app.needs_backup(app.path))
            app.backup_made(app.path, bak)
            _refresh(app)
            return T('undo.removed', 'Undo: {n} created item(s) removed', n=len(doomed))
        if op['kind'] == 'replace':
            new_spot = (op['page'], op['x'], op['y'])
            cur = next((i for i in items if (i['page'], i['x'], i['y']) == new_spot), None)
            if op.get('after') is not None and (cur is None or bytes(item_blob(open(app.path, 'rb').read(), cur))
                                                != bytes(op['after'])):
                # the item was changed since (by an action that is not recorded): its old bytes would undo that too
                return T('undo.changed', 'Undo: {name} changed since - not undone', name=op.get('name') or 'item')
            old_spot = (op['old_page'], op['old_x'], op['old_y'])
            free = not any((i['page'], i['x'], i['y']) == old_spot
                           for i in items if i is not cur)
            if not free:
                new = blob_item(op['blob'], app.data)
                old_spot = free_spot([i for i in items if i is not cur], new, app.data, (op['old_page'],))
                if old_spot is None:
                    stack.append(op)
                    return T('undo.nospace', 'Undo: no free place for {name} any more',
                             name=op.get('name') or 'item')
            bak = edit_stash(app.path, app.data,
                             remove=[cur['_offset']] if cur is not None else [],
                             insert=[_ins(old_spot, op['blob'], op.get('index'), op['old_page'])],
                             backup=app.needs_backup(app.path))
            app.backup_made(app.path, bak)
            _refresh(app, old_spot)
            return T('undo.reverted', 'Undo: {name} restored to its previous bytes',
                     name=op.get('name') or 'item')
        stack.append(op)                       # unknown kind: put it back
    except (EditError, OSError) as e:
        stack.append(op)                       # nothing was written: the step stays undoable (it was lost before,
        return T('undo.err', 'Undo failed: {err}', err=e)       # and with it the only copy of a deleted item)
    except Exception as e:                     # a stash the reader refuses (FormatError...), a bug: said, not
        stack.append(op)                       # shown as "Nothing to undo"; the step is kept
        try:
            import mxl_log
            mxl_log.log.exception('undo failed')
        except Exception:
            pass
        return T('undo.err', 'Undo failed: {err}', err=e)
    return None


def record_char(app, path, before, after, name=None):
    """Records a write of the character file (path): before / after are the file's whole bytes."""
    record(app, 'char', path=os.path.abspath(path), before=bytes(before), after=bytes(after), name=name)


def _undo_char(app, op):
    """Writes the character file's bytes of before the action back - only when the file is still the one the
    action wrote; then the panel and the Character tab read it again (the tab keeps its pending page edits on
    top of it: CharacterWindow.sync_file)."""
    path, name = op['path'], op.get('name') or 'item'
    try:
        with open(path, 'rb') as f:
            now = f.read()
    except OSError as e:
        return T('undo.err', 'Undo failed: {err}', err=e)
    if now != op['after']:
        return T('undo.char_changed', 'Undo: the character file changed since ({name}) - not undone', name=name)
    try:
        from mxl_save import commit_file, load_character
        from mxl_char import Character

        def verify(tmp):
            with open(tmp, 'rb') as f:
                if f.read() != op['before']:
                    raise EditError('undo: written bytes differ')
            Character(tmp, app.data)
            load_character(tmp, app.data)
        bak = commit_file(path, op['before'], verify, app.needs_backup(path))
    except Exception as e:
        return T('undo.err', 'Undo failed: {err}', err=e)
    app.backup_made(path, bak)
    _refresh_char(app, path)
    return T('undo.char', 'Undo: {name} restored to its previous bytes', name=name)


def _read(path):
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def snapshot(paths):
    """{absolute path: bytes or None} of the given files (None / empty entries skipped)."""
    out = {}
    for p in paths:
        if p:
            p = os.path.abspath(str(p))
            if p not in out:
                out[p] = _read(p)
    return out


def record_files(app, before, name=None):
    """After an action: records a 'files' step of the files of before (snapshot()) whose bytes changed. Nothing
    is recorded when no file changed (refused, rolled back). True when recorded."""
    try:
        files = []
        for p, old in before.items():
            new = _read(p)
            if old is not None and new is not None and new != old:
                files.append((p, bytes(old), bytes(new)))
        if not files:
            return False
        return record(app, 'files', files=files, name=name)
    except Exception as e:
        _log_error('undo: move not recorded (%s: %s)', type(e).__name__, e)
        return False


def _verify_for(path, want, data):
    def verify(tmp):
        with open(tmp, 'rb') as f:
            if f.read() != want:
                raise EditError('undo: written bytes differ')
        if path.lower().endswith('.d2s'):
            from mxl_char import Character
            from mxl_save import load_character
            Character(tmp, data)
            load_character(tmp, data)
        else:
            parse_stash(tmp, data)
    return verify


def _undo_files(app, stack):
    """Puts every file of the last 'files' step back to its bytes of before; refused (step kept) when one of
    them changed since. A failure half-way writes the files already restored back to what the action wrote."""
    import mxl_save
    op = stack.pop()
    name = op.get('name') or 'item'
    for path, _before, after in op['files']:
        if _read(path) != after:
            stack.append(op)
            return T('undo.files_changed', 'Undo: {file} changed since ({name}) - not undone',
                     file=os.path.basename(path), name=name)
    done = []
    try:
        for path, before, after in op['files']:
            bak = mxl_save.commit_file(path, before, _verify_for(path, before, app.data), app.needs_backup(path))
            done.append((path, after))
            app.backup_made(path, bak)
    except Exception as e:
        for path, after in done:
            try:
                mxl_save.commit_file(path, after, _verify_for(path, after, app.data), False)
            except Exception as rb:
                _log_error('undo: %s not written back (%s)', path, rb)
        stack.append(op)
        return T('undo.err', 'Undo failed: {err}', err=e)
    for path, _b, _a in op['files']:
        if path.lower().endswith('.d2s'):
            _refresh_char(app, path)
    if app.path:
        _refresh(app)
    return T('undo.files', 'Undo: {name} undone', name=name)


def _refresh_item_stats_later(app):
    try:
        app.root.after_idle(_refresh_item_stats)
    except Exception:
        _refresh_item_stats()


def _refresh_char(app, path):
    """The views of the character file after an undo wrote it."""
    _refresh_item_stats_later(app)
    inv = getattr(app, 'inventory', None)
    if inv is not None:
        try:
            inv.reload()                 # its refresh syncs a Character tab open on the same file
        except Exception as e:
            print('undo: character panel not refreshed:', e)
    try:
        import mxl_tabs
        w = mxl_tabs.built_owner('Character')
        if w is not None and getattr(w, 'ch', None) is not None \
                and os.path.abspath(w.ch.path) == os.path.abspath(path):
            w.sync_file()
    except Exception as e:
        print('undo: character tab not refreshed:', e)


def _ins(spot, blob, index, page):
    """The insert tuple of an undo: at the item's old index in its page's list when the item goes back to
    its own page and the writer knows indexed inserts (mxl_stash_order), appended otherwise."""
    import mxl_save
    if index is not None and spot[0] == page and getattr(mxl_save.edit_stash, '_capy_in_place', False):
        return (spot[0], spot[1], spot[2], blob, index)
    return (spot[0], spot[1], spot[2], blob)


def _refresh_item_stats():
    """The Item stats tab shows the values of an item an undo may just have written: read again."""
    try:
        import mxl_tabs
        w = mxl_tabs.built_owner('Item stats')
        if w is not None and hasattr(w, 'external_change'):
            w.external_change()
    except Exception as e:
        print('undo: item stats tab not refreshed:', e)


def _refresh(app, sel_key=None):
    """The grid refresh after an undo (same fast path as the creator's writes)."""
    _refresh_item_stats_later(app)
    try:
        from mxl_creator_gui import _reload_main
        _reload_main(app, sel_key)
    except Exception:
        try:
            app.load(app.path, keep_selection=False)
        except Exception:
            pass


def _char_path(app):
    try:
        return app.character_file()
    except Exception:
        return None


def _track(fn, paths_of):
    """Wraps a drag-release handler: paths_of(self) -> (app, files it may write, item name); the files are read
    before, and the ones the handler changed are recorded as one 'files' undo step."""
    import functools

    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        try:
            app, paths, name = paths_of(self)
            before = snapshot(paths) if app is not None else None
        except Exception:
            before = None
        r = fn(self, *a, **kw)
        if before and record_files(app, before, name):
            try:
                st = getattr(self, 'status', None) or app.status
                txt = st.cget('text')
                if txt and 'Ctrl+Z' not in txt:
                    st.configure(text=txt + T('undo.move_hint', ' - Ctrl+Z moves it back'))
            except Exception:
                pass
        return r
    wrapper._capy_undo_track = True
    return wrapper


def _clean(name):
    try:
        from mxl_creator_gui import clean
        return clean(name)
    except Exception:
        return name


def _install_move_undo(App):
    """Drag moves become undoable: the main grid (move_item / transfer_item of the collector, stash -> character
    of mxl_inv_gui), the Stash tab's character panel and the Character tab. The classes are patched before any
    window binds the handlers."""
    def main_paths(app):
        d = getattr(app, 'drag', None)
        if not d or d.get('item') is None:
            return None, (), None
        try:
            name = app.full_name(d['item'])
        except Exception:
            name = None
        return app, (app.path, d.get('path'), _char_path(app)), name

    def panel_paths(w):
        d = getattr(w, 'drag', None)
        if not d or not d.get('moved'):
            return None, (), None
        ch = getattr(w, 'ch', None)
        try:
            name = _clean(d['entry'].it['name'])
        except Exception:
            name = None
        return w.app, (w.app.path, ch.path if ch is not None else None), name

    targets = [(App, main_paths)]
    try:
        import mxl_inv_gui
        targets.append((mxl_inv_gui.MainInventory, panel_paths))
    except Exception as e:
        print('undo of panel moves disabled:', e)
    try:
        import mxl_char_gui
        targets.append((mxl_char_gui.CharacterWindow, panel_paths))
    except Exception as e:
        print('undo of character tab moves disabled:', e)
    for cls, paths_of in targets:
        if not getattr(cls.on_release, '_capy_undo_track', False):
            cls.on_release = _track(cls.on_release, paths_of)


def install(App):
    """Delete-key-on-hover (instant, no prompt) + Ctrl+Z + the Undo button."""
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            import mxl_stash_order
            mxl_stash_order.watch_view(self)     # removals are checked against what this window shows
        except Exception as e:
            print('stale-view check disabled:', e)
        try:
            self._undo = []
            _install_delete(self)
            _install_undo_button(self)
        except Exception as e:
            print('undo / delete-on-hover disabled:', e)

    App._build = _build
    _wrap_release_late(App)


def _wrap_release_late(App):
    """The move undo wraps the release handlers after mxl_inv_gui (installed after this module) patched
    App.on_release: done at the first _build, before any widget binds them."""
    o_build = App._build

    def _build(self):
        try:
            _install_move_undo(type(self))
        except Exception as e:
            print('undo of moves disabled:', e)
        o_build(self)
    App._build = _build


def _install_delete(app):
    """<Delete> anywhere in the window: the item under the mouse pointer on the stash grid is
    deleted at once, no prompt. Bound on the root window (a canvas never has the keyboard focus,
    so a binding on the grid itself never fired); the character window has its own handler for
    its doll / inventory canvases - each handler acts only on its own visible canvas."""
    def on_delete(_e=None):
        try:
            w = app.root.focus_get()
            if w is not None and w.winfo_class() in ('Entry', 'Text', 'Spinbox', 'Combobox'):
                return
        except Exception:
            pass
        it = None
        try:
            cv = app.canvas
            if cv.winfo_ismapped():
                x, y = cv.winfo_pointerx() - cv.winfo_rootx(), cv.winfo_pointery() - cv.winfo_rooty()
                if 0 <= x < cv.winfo_width() and 0 <= y < cv.winfo_height():
                    import types
                    it = app.item_at(types.SimpleNamespace(x=x, y=y))
        except Exception:
            it = None
        if it is not None:
            delete_item(app, it)

    app.root.bind('<Delete>', on_delete, add='+')
    app.root.bind('<Control-z>', lambda _e: _do_undo(app))
    app.root.bind('<Control-Z>', lambda _e: _do_undo(app))


def _do_undo(app):
    msg = undo(app)
    if msg is None:
        msg = T('undo.nothing', 'Nothing to undo')
    try:
        app.status.configure(text=msg)
    except Exception:
        pass


def delete_item(app, it):
    """Delete one stash item instantly (no prompt), recording it for undo."""
    if it is None or not app.path:
        return
    try:
        name = app.full_name(it)
    except Exception:
        name = 'item'
    recorded = False
    try:
        recorded = record(app, 'delete', item=it, page=it['page'], x=it['x'], y=it['y'], name=name)
        bak = edit_stash(app.path, app.data, remove=[it['_offset']],
                         backup=app.needs_backup(app.path))
    except Exception as e:
        if recorded:                           # only this delete's own record (never an older action's)
            try:
                app._undo.pop()
            except (IndexError, AttributeError):
                pass
        _log_error('delete of %s failed: %s: %s', name, type(e).__name__, e)
        try:
            app.status.configure(text=T('undo.del_err', 'Delete failed: {err}', err=e))
        except Exception:
            pass
        return
    app.backup_made(app.path, bak)
    _refresh(app)
    try:
        app.status.configure(text=T('cr.deleted', '{name} deleted', name=name)
                             + (T('undo.hint', ' - Ctrl+Z puts it back') if recorded else ''))
    except Exception:
        pass


def _install_undo_button(app):
    """The Undo button, next to the collector's own button row."""
    try:
        bar = getattr(app, 'btn_library', None)
        bar = bar.master if bar is not None else None
        if bar is None:
            return
        import mxl_creator_gui
        btn = mxl_creator_gui.D2.button(bar, T('undo.btn', 'Undo'), lambda: _do_undo(app), 6)
        btn.pack(side='left', padx=(12, 0))
    except Exception as e:
        print('undo button disabled:', e)
