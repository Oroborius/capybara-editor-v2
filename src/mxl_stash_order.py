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
for the temp file, verification, backup and the game-closed rule)."""
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


def install():
    """Safe to call more than once. Also rebinds the name in modules that imported it before."""
    global _installed
    if _installed:
        return
    _installed = True
    host = mxl_save.edit_stash

    def edit_stash(path, data, remove=(), insert=(), backup=True):
        remove, insert = list(remove), list(insert)
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
