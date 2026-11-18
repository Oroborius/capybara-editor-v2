"""A replaced stash item keeps its place in the file.

The collector's writer mxl_save.edit_stash(path, data, remove=[offset], insert=[(page, x, y, blob)]) drops the removed
item from its page's item list and APPENDS the inserted one at the end of that list. Every "replace" of the editor
(Item stats tab add / delete, Edit item -> Replace, Make perfect, sockets, undo...) is such a call, so the item moved to
the end of its page in the file and every item behind its old position shifted: adding a stat and deleting it again
left the stash the same size, every item with the same bytes, but hundreds of bytes "different" (336 in the report).
Nothing is lost - the game reads a page as a list and takes each item's cell from the item itself - but a no-op edit
should give the same file back.

install() wraps mxl_save.edit_stash: a call that removes ONE item and inserts ONE item on the same page is written
here with the new item at the removed item's index; every other call goes to the collector's function unchanged. The
write itself is the collector's (same structure check, same placement check, same verification, mxl_save.commit_file
for the temp file, verification, backup and the game-closed rule).

Insert at an index: an insert tuple may carry a fifth element, (page, x, y, blob, index) - the item's index in its
page's item list. Undo uses it to put a deleted item back where it stood in the file (delete + undo gives the
original bytes); page_index() tells the index of an item, last_removed the index the last one-item removal had.
Such a call is written here too, with the same checks; an index of None (or past the end) appends.

Parsed stash cache (install_parse_cache): mxl_save.parse_stash reads and parses the whole file at every call, and one
stash action called it four times or more (the action, the writer, its "stale view" / index lookups, the window's
reload): ~85 ms each on a full stash (1340 items). The parse is a function of the file's BYTES only, so the result
is kept per content: every call still reads the file, and a call whose bytes are exactly (byte for byte) those of
a recent parse gets a fresh copy of that result. The writers' verification of a new file (<file>.tmp) is always
parsed by the collector's parser itself, never served from here."""
import os
import sys

import mxl_save
from mxl_format import write_bits

_installed = False
_cache = {'orig': None, 'entries': [], 'hits': 0, 'misses': 0}
CACHE_KEEP = 4          # contents kept (the file now, the file just written, the shared stash, one spare)


def _replace_in_place(path, data, off, ins, backup):
    page, x, y, blob = ins
    buf = mxl_save.read_file(path)
    items = mxl_save.parse_stash(path, data)
    pages = mxl_save.stash_blobs(buf, items)
    if mxl_save.build_stash(buf[:8], pages) != buf:
        raise mxl_save.EditError(mxl_save.tr('err.structure'))
    old = next((i for i in items if i['_offset'] == off), None)
    if old is None:
        raise mxl_save.EditError(mxl_save.tr('err.changed'))
    if old['page'] != page:
        return NotImplemented                     # another page: the collector's own way (appended there)
    index = [i for i in items if i['page'] == page].index(old)
    placed = [i for i in items if i is not old]
    new = mxl_save.blob_item(blob, data)
    new['page'] = page
    err = mxl_save.placement_error(placed, new, page, x, y, data)
    if err:
        raise mxl_save.EditError(err)
    b = bytearray(blob)
    write_bits(b, 16 + new['_pos_bit'], 4, x)
    write_bits(b, 16 + new['_pos_bit'] + 4, 4, y)
    new_pages = {p: list(lst) for p, lst in pages.items()}
    new_pages[page][index] = bytes(b)
    content = mxl_save.build_stash(buf[:8], new_pages)
    expected, code = len(items), new['code']

    def verify(tmp):
        after = mxl_save.parse_stash(tmp, data)
        if len(after) != expected or not any((i['page'], i['x'], i['y']) == (page, x, y) and i['code'] == code
                                             for i in after):
            raise mxl_save.EditError(mxl_save.tr('err.verify'))
    return mxl_save.commit_file(path, content, verify, backup)


def page_index(path, data, off):
    """(page, index within that page's item list) of the stash item at byte offset `off`, or None."""
    items = mxl_save.parse_stash(path, data)
    it = next((i for i in items if i['_offset'] == off), None)
    if it is None:
        return None
    return it['page'], [i['_offset'] for i in items if i['page'] == it['page']].index(off)


last_removed = {}       # {'path', 'page', 'index', 'blob'} of the last write that removed exactly one item


def _note_removed(path, data, off):
    last_removed.clear()
    try:
        buf = mxl_save.read_file(path)
        items = mxl_save.parse_stash(path, data)
        it = next(i for i in items if i['_offset'] == off)
        index = [i['_offset'] for i in items if i['page'] == it['page']].index(off)
        return dict(path=os.path.abspath(path), page=it['page'], index=index, blob=bytes(mxl_save.item_blob(buf, it)))
    except Exception:
        return None


def _edit_indexed(path, data, remove, insert, backup):
    """remove + insert where inserts may name their index in the page's list: (page, x, y, blob[, index])."""
    buf = mxl_save.read_file(path)
    items = mxl_save.parse_stash(path, data)
    pages = mxl_save.stash_blobs(buf, items)
    if mxl_save.build_stash(buf[:8], pages) != buf:
        raise mxl_save.EditError(mxl_save.tr('err.structure'))
    doomed = set(remove)
    if len(doomed) != len(remove) or doomed - {i['_offset'] for i in items}:
        raise mxl_save.EditError(mxl_save.tr('err.changed'))
    new_pages = {}
    for p, lst in pages.items():
        here = [i for i in items if i['page'] == p]
        if len(here) != len(lst):
            raise mxl_save.EditError(mxl_save.tr('err.structure'))
        new_pages[p] = [b for i, b in zip(here, lst) if i['_offset'] not in doomed]
    placed = [i for i in items if i['_offset'] not in doomed]
    spots, tail = [], []
    for ins in sorted(insert, key=lambda t: (t[0], len(t) < 5 or t[4] is None, t[4] if len(t) > 4 and t[4] is not None else 0)):
        page, x, y, blob = ins[:4]
        index = ins[4] if len(ins) > 4 else None
        if index is not None and index < 0:
            raise mxl_save.EditError(mxl_save.tr('err.structure'))
        if page not in new_pages:
            # a page without items has no section in the file: the undo of deleting the last item of a page
            # (or an insert onto any empty page) starts it again; build_stash writes the pages in order
            if not (isinstance(page, int) and 0 <= page < mxl_save.STASH_PAGES):
                raise mxl_save.EditError(mxl_save.tr('err.structure'))
            new_pages[page] = []
        new = mxl_save.blob_item(blob, data)
        new['page'] = page
        err = mxl_save.placement_error(placed, new, page, x, y, data)
        if err:
            raise mxl_save.EditError(err)
        new['x'], new['y'] = x, y
        placed.append(new)
        b = bytearray(blob)
        write_bits(b, 16 + new['_pos_bit'], 4, x)
        write_bits(b, 16 + new['_pos_bit'] + 4, 4, y)
        lst = new_pages[page]
        if index is None or index >= len(lst):
            tail.append((page, bytes(b)))
        else:
            lst.insert(index, bytes(b))           # ascending order: every index is the final one
        spots.append((page, x, y, new['code']))
    for page, b in tail:
        new_pages[page].append(b)
    content = mxl_save.build_stash(buf[:8], new_pages)
    expected = len(items) - len(doomed) + len(insert)

    def verify(tmp):
        after = mxl_save.parse_stash(tmp, data)
        have = {(i['page'], i['x'], i['y'], i['code']) for i in after}
        if len(after) != expected or any(s not in have for s in spots):
            raise mxl_save.EditError(mxl_save.tr('err.verify'))
    return mxl_save.commit_file(path, content, verify, backup)


_views = []             # weakrefs to the windows showing a stash: objects with .path and .items (mxl_gui.App)


def watch_view(view):
    """Registers a window whose shown items (view.items of view.path) the removals are checked against."""
    import weakref
    _views[:] = [r for r in _views if r() is not None and r() is not view] + [weakref.ref(view)]


def _same_file(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (TypeError, ValueError):
        return False


def _key(it):
    return it.get('page'), it.get('x'), it.get('y'), it.get('code')


def stale_view(path, data, remove):
    """The window that shows `path` is out of date for these removals: an offset it shows holds another item in
    the file now (the game or another writer saved the stash since the window read it, and the watcher has not
    read it again yet). An item is only known by its offset to edit_stash, so removing it then would remove a
    DIFFERENT item (a neighbour of the same size). Returns the view, or None when every removed offset is still
    the item the view shows (or no view shows these offsets)."""
    if not remove:
        return None
    now = None
    for ref in list(_views):
        view = ref()
        if view is None:
            continue
        items = getattr(view, 'items', None)
        if not items or not getattr(view, 'path', None) or not _same_file(view.path, path):
            continue
        shown = {i.get('_offset'): i for i in items if isinstance(i, dict)}
        if not any(o in shown for o in remove):
            continue
        if now is None:
            now = {i['_offset']: i for i in mxl_save.parse_stash(path, data)}
        for o in remove:
            if o in shown and (o not in now or _key(now[o]) != _key(shown[o])):
                return view
    return None


def _refuse_stale(view):
    try:
        if view is not None:
            view.root.after_idle(lambda: _reload_keep_status(view))
    except Exception:
        pass
    raise mxl_save.EditError(_T('so.err.stale', 'The stash changed on disk since it was shown (the game or another '
                                'window saved it): nothing was written, it has been read again - do it again.'))


def item_now(path, data, it, view=None):
    """The item `it` (a parsed item a window shows, or a copy of one) as the file holds it NOW: (buf, items,
    cur, blob) from one read of the file. Copy / Duplicate / Export and the Item stats tab read an item's bytes by
    its offset alone: from an out-of-date view (the game or another window saved the stash since it was read)
    that offset can hold a neighbour of the same size. Here the item at that offset must be the same item (page,
    x, y, code), and no window showing the file may be out of date for it (stale_view); otherwise nothing is
    returned: EditError, the window(s) read the stash again."""
    off = it.get('_offset')
    buf = bytes(mxl_save.read_file(path))
    items = cached_parse_stash(path, data, buf)
    cur = next((i for i in items if i['_offset'] == off), None)
    if cur is None or _key(cur) != _key(it):
        _refuse_stale(view if view is not None else _view_of(path))
    shown = stale_view(path, data, [off])
    if shown is not None:
        _refuse_stale(shown)
    return buf, items, cur, bytes(mxl_save.item_blob(buf, cur))


def _view_of(path):
    for ref in list(_views):
        v = ref()
        if v is not None and getattr(v, 'path', None) and _same_file(v.path, path):
            return v
    return None


def _reload_keep_status(view):
    """The view reads the stash again; the status line keeps the refusal the caller showed (the reload writes its
    own hint there)."""
    try:
        text = view.status.cget('text')
    except Exception:
        text = None
    try:
        view.reload()
    finally:
        if text:
            try:
                view.status.configure(text=text)
            except Exception:
                pass


def _T(key, default, **kw):
    try:
        from mxl_lang import T
        return T(key, default, **kw)
    except Exception:
        return default.format(**kw) if kw else default


# ------------------------------------------------------------------------------------- parsed stash cache
_ATOMS = (int, str, bool, type(None), float, bytes)


def _clone(o):
    """A copy of a parsed item list that shares nothing mutable with the original (the items are mxl_format.Record
    dict subclasses holding dicts and lists; the window, the writers and the menus may change what they get)."""
    t = type(o)
    if t in _ATOMS:
        return o
    if t is list:
        return [_clone(v) for v in o]
    if t is dict:
        return {k: _clone(v) for k, v in o.items()}
    if isinstance(o, dict):
        n = t.__new__(t)
        dict.update(n, {k: _clone(v) for k, v in dict.items(o)})   # no Record.__setitem__ check: same keys
        d = getattr(o, '__dict__', None)
        if d:
            n.__dict__.update(_clone(d))
        return n
    if t is tuple:
        return tuple(_clone(v) for v in o)
    if t is bytearray:
        return bytearray(o)
    if t is set:
        return {_clone(v) for v in o}
    import copy
    return copy.deepcopy(o)


def _parse_bytes(orig, path, buf, data):
    """The collector's own parse_stash on exactly these bytes (its read of the file is answered with them):
    what is cached is what was parsed, even when the file changes again in the meantime."""
    if orig.__closure__ is not None or 'read_file' not in orig.__code__.co_names:
        items = orig(path, data)                 # not the collector's plain function: kept only when the file
        if bytes(mxl_save.read_file(path)) != buf:   # still holds the bytes it was read with
            raise _Changed(items)
        return items
    import types
    g = dict(orig.__globals__)
    g['read_file'] = lambda p, _b=buf: _b
    fn = types.FunctionType(orig.__code__, g, orig.__name__, orig.__defaults__, orig.__closure__)
    return fn(path, data)


class _Changed(Exception):
    def __init__(self, items):
        Exception.__init__(self)
        self.items = items


def _lookup(buf, data, parser):
    for e in _cache['entries']:
        if e[1] is data and e[2] is parser and e[0] == buf:
            _cache['entries'].remove(e)
            _cache['entries'].append(e)          # most recently used last
            return e[3]
    return None


def cached_parse_stash(path, data, buf=None):
    """mxl_save.parse_stash with the result kept per file content (see the module doc). buf: the file's bytes
    when the caller has just read them (the result is then the parse of exactly these bytes)."""
    orig = _cache['orig']
    if orig is None:                              # not installed: the collector's parser, which reads the file
        items = mxl_save.parse_stash(path, data)
        if buf is not None and bytes(mxl_save.read_file(path)) != bytes(buf):
            raise mxl_save.EditError(mxl_save.tr('err.changed'))
        return items
    buf = bytes(mxl_save.read_file(path)) if buf is None else bytes(buf)
    import mxl_format
    parser = getattr(mxl_format, 'parse_item', None)         # a format fix installed later: other results
    verify = str(path).lower().endswith('.tmp')               # a writer's verification: always parsed here
    items = None if verify else _lookup(buf, data, parser)
    if items is not None:
        _cache['hits'] += 1
        return _clone(items)
    _cache['misses'] += 1
    try:
        items = _parse_bytes(orig, path, buf, data)           # an exception is raised, nothing is kept
    except _Changed as c:
        return c.items
    _cache['entries'] = [e for e in _cache['entries'] if not (e[0] == buf and e[1] is data)]
    _cache['entries'].append((buf, data, parser, _clone(items)))
    del _cache['entries'][:-CACHE_KEEP]
    return items


def clear_parse_cache():
    _cache['entries'] = []


def install_parse_cache():
    """Wraps mxl_save.parse_stash (also where a module bound it by name). Idempotent."""
    host = mxl_save.parse_stash
    if getattr(host, '_capy_cached', False):
        return
    _cache['orig'] = host

    def parse_stash(path, data):
        return cached_parse_stash(path, data)
    parse_stash.__doc__ = getattr(host, '__doc__', None)
    parse_stash.__wrapped__ = host
    parse_stash._capy_cached = True
    mxl_save.parse_stash = parse_stash
    for mod in list(sys.modules.values()):
        try:
            if mod is not None and mod is not mxl_save and getattr(mod, 'parse_stash', None) is host:
                mod.parse_stash = parse_stash
        except Exception:
            pass


def install():
    """Safe to call more than once. Also rebinds the name in modules that imported it before."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        install_parse_cache()
    except Exception as e:
        print('stash parse cache disabled:', e)
    host = mxl_save.edit_stash

    def edit_stash(path, data, remove=(), insert=(), backup=True):
        remove, insert = list(remove), list(insert)
        view = stale_view(path, data, remove)
        if view is not None:
            _refuse_stale(view)
        note = _note_removed(path, data, remove[0]) if len(remove) == 1 else None
        last_removed.clear()
        try:
            return _edit(path, data, remove, insert, backup)
        finally:
            if note:
                last_removed.update(note)       # (kept after a failed write too: readers compare the bytes)

    def _edit(path, data, remove, insert, backup):
        if any(len(i) > 4 for i in insert):
            if any(i[4] is not None for i in insert if len(i) > 4):
                return _edit_indexed(path, data, remove, insert, backup)
            insert = [tuple(i[:4]) for i in insert]
        if len(remove) == 1 and len(insert) == 1:
            r = _replace_in_place(path, data, remove[0], insert[0], backup)
            if r is not NotImplemented:
                return r
        return host(path, data, remove=remove, insert=insert, backup=backup)
    edit_stash.__doc__ = getattr(host, '__doc__', None)
    edit_stash._capy_in_place = True
    mxl_save.edit_stash = edit_stash
    for mod in list(sys.modules.values()):
        try:
            if mod is not None and mod is not mxl_save and getattr(mod, 'edit_stash', None) is host:
                mod.edit_stash = edit_stash
        except Exception:
            pass
