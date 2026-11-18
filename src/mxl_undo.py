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

Each undo is one stash write through the collector's own safe writer (mxl_save.edit_stash), with the
usual backup policy and an instant grid refresh. The buffer holds the last 50 actions of this session.
"""
import os

from mxl_save import (edit_stash, parse_stash, free_spot, item_blob, blob_item, EditError,
                      STASH_PAGES)
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
    if not app.path:
        return None
    op = stack.pop()
    try:
        items = parse_stash(app.path, app.data)
        if op['kind'] == 'delete':
            spot = (op['page'], op['x'], op['y'])
            index = op.get('index')
            if any((i['page'], i['x'], i['y']) == spot for i in items):
                new = blob_item(op['blob'], app.data)
                spot = free_spot(items, new, app.data, (op['page'],) + tuple(
                    p for p in range(STASH_PAGES) if p != op['page']))
                if spot is None:
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
        return T('undo.err', 'Undo failed: {err}', err=e)
    except Exception as e:                     # a stash the reader refuses (FormatError...), a bug: said, not
        try:                                   # shown as "Nothing to undo"
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


def _refresh_char(app, path):
    """The views of the character file after an undo wrote it."""
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


def _refresh(app, sel_key=None):
    """The grid refresh after an undo (same fast path as the creator's writes)."""
    try:
        from mxl_creator_gui import _reload_main
        _reload_main(app, sel_key)
    except Exception:
        try:
            app.load(app.path, keep_selection=False)
        except Exception:
            pass


def install(App):
    """Delete-key-on-hover (instant, no prompt) + Ctrl+Z + the Undo button."""
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            self._undo = []
            _install_delete(self)
            _install_undo_button(self)
        except Exception as e:
            print('undo / delete-on-hover disabled:', e)

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
