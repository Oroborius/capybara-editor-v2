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
Such a call is written here too, with the same checks; an index of None (or past the end) appends."""
import os
import sys

import mxl_save
from mxl_format import write_bits

_installed = False


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
        if page not in new_pages or (index is not None and index < 0):
            raise mxl_save.EditError(mxl_save.tr('err.structure'))
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


def install():
    """Safe to call more than once. Also rebinds the name in modules that imported it before."""
    global _installed
    if _installed:
        return
    _installed = True
    host = mxl_save.edit_stash

    def edit_stash(path, data, remove=(), insert=(), backup=True):
        remove, insert = list(remove), list(insert)
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
