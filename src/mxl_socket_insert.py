"""Socketing an item into another one: a gem, rune, jewel or any other socket filler (item type 'sock', in Median
XL and in 1.14d) dropped onto an item with a free socket goes into that socket, as in the game. The filler is
moved: it leaves its place (stash or character) and is written as the parent's next socketed child (location
'socketed', x = its socket), the parent's socketed-item count grows by one. Nothing else of the parent changes:
no socket is added (the game never does that), a runeword is neither formed nor broken.

Drops handled (mxl_inv_gui calls these from its release handlers, so mxl_undo's move undo records them):
stash -> stash item, stash -> character item, character -> character item, character -> stash item."""
import os

from mxl_lang import T
from mxl_save import read_file, item_blob, blob_item, parse_stash, edit_stash, commit_file, EditError
from mxl_format import FormatError
from mxl_creator import (decode_item, encode_item, FLAG_SIMPLE, FLAG_SOCKETED, LOC_SOCKETED, MAX_SOCKETED,
                         NUM_SOCKETS)

MAX_COUNT = MAX_SOCKETED            # save format: the socketed-item count field of a record (3 bits)
NUMSOCKETS = NUM_SOCKETS            # item_numsockets: the sockets above the save field (1.14d profile)


class InsertError(Exception):
    pass


def _t(key, default, **kw):
    return T('sock.' + key, default, **kw)


def _vanilla():
    try:
        import mxl_profile
        return not mxl_profile.is_median()
    except Exception:
        return False


def _creator(app):
    import mxl_rc_menu
    return mxl_rc_menu._creator(app)


def is_socketable(app, code):
    """A socket filler of the game in use: its item type descends from 'sock' (gems, runes, jewels, Median's
    other fillers)."""
    try:
        return 'sock' in _creator(app).type_codes(code)
    except Exception:
        return False


def blob_socketable(app, blob):
    try:
        return is_socketable(app, decode_item(blob, app.data)[0]['code'])
    except Exception:
        return False


def children(blob, data):
    """(parent record, [raw child blobs]) of an item's bytes."""
    rec, p = decode_item(blob, data)
    kids = []
    if rec['flags'] & FLAG_SOCKETED and not rec['flags'] & FLAG_SIMPLE:
        for _ in range(rec.get('socketed_count', 0)):
            _k, m = decode_item(blob[p:], data)
            kids.append(bytes(blob[p:p + m]))
            p += m
    return rec, kids


def socket_total(rec):
    """Sockets of a record: the save field, plus item_numsockets in the 1.14d profile (Creator.socket_split)."""
    if rec['flags'] & FLAG_SIMPLE or not rec['flags'] & FLAG_SOCKETED:
        return 0
    n = rec.get('sockets') or 0
    if _vanilla():
        n += sum(s['value'] for s in rec.get('stats') or () if s.get('id') == NUMSOCKETS)
    return n


def free_sockets(blob, data):
    rec, kids = children(blob, data)
    return max(0, socket_total(rec) - len(kids))


def as_child(blob, data, index):
    """One item's bytes as socketed child `index`. It must be one record (a filler holds no items)."""
    rec, size = decode_item(blob, data)
    if size != len(blob):
        raise InsertError(_t('err.has_children', 'an item with socketed items cannot go into a socket'))
    rec = dict(rec, location=LOC_SOCKETED, equipped=0, x=index, y=0, panel=0)
    return encode_item(rec, data)


def insert_child(parent, child, data, name=None):
    """The parent's bytes with `child` socketed into its first free socket. Raises InsertError (clear message)
    when the parent has no free socket; the result is checked to read back as one item with all its children."""
    parent, child = bytes(parent), bytes(child)
    rec, kids = children(parent, data)
    what = name or T('sock.this_item', 'this item')
    total = socket_total(rec)
    if not total:
        raise InsertError(_t('err.no_sockets', '{item} has no sockets', item=what))
    if len(kids) >= total or len(kids) >= MAX_COUNT:
        raise InsertError(_t('err.full', '{item} has no free socket', item=what))
    new = encode_item(dict(rec, socketed_count=len(kids) + 1), data) + b''.join(kids) + as_child(child, data, len(kids))
    back, k2 = children(new, data)
    seen = blob_item(new, data)
    if back.get('socketed_count') != len(kids) + 1 or len(k2) != len(kids) + 1 \
            or len(seen.get('socketed') or ()) != len(kids) + 1 or sum(map(len, k2)) + decode_item(new, data)[1] != len(new):
        raise InsertError(_t('err.invalid', 'the socketed item would not be readable: nothing written'))
    return new


def _size(data, it):
    try:
        return data.base(it['code']).size
    except Exception:
        return (1, 1)


def stash_item_at(app, x_root, y_root):
    """The stash item of the shown page under the pointer, or None."""
    cv = app.canvas
    try:
        x, y = x_root - cv.winfo_rootx(), y_root - cv.winfo_rooty()
        if not (0 <= x < cv.winfo_width() and 0 <= y < cv.winfo_height()):
            return None
        cx, cy, page = int(x // app.cell), int(y // app.cell), app.page()
    except Exception:
        return None
    for it in app.items or ():
        if it.get('page') != page:
            continue
        w, h = _size(app.data, it)
        if it['x'] <= cx < it['x'] + w and it['y'] <= cy < it['y'] + h:
            return it
    return None


def _clean(name):
    try:
        from mxl_creator_gui import clean
        return clean(name)
    except Exception:
        return name


def _done_msg(child, parent):
    return _t('done', '{child} socketed into {item}', child=_clean(child), item=_clean(parent))


ERRORS = (InsertError, EditError, FormatError, OSError, KeyError, ValueError)


def _where(e):
    import mxl_char as MC
    return ('slot', e.it['equipped']) if e.it['location'] == MC.LOC_EQUIPPED else ('inv', e.it['x'], e.it['y'])


# ------------------------------------------------------------------------------------------ main stash grid
def stash_on_stash(app, d, ev):
    """Main-grid drag released over another stash item. True when handled (inserted or refused)."""
    it, src = d.get('item'), d.get('path') or app.path
    if it is None or not app.path:
        return False
    target = stash_item_at(app, ev.x_root, ev.y_root)
    if target is None or (os.path.abspath(src) == os.path.abspath(app.path) and target.get('_offset') == it.get('_offset')):
        return False
    if not is_socketable(app, it['code']):
        return False
    pname, cname = app.full_name(target), app.full_name(it)
    data = app.data
    same = os.path.abspath(src) == os.path.abspath(app.path)
    try:
        raw_s = read_file(src)
        cur = next((i for i in parse_stash(src, data) if i['_offset'] == it['_offset'] and i['code'] == it['code']), None)
        raw_t = raw_s if same else read_file(app.path)
        tgt = next((i for i in parse_stash(app.path, data)
                    if i['_offset'] == target['_offset'] and i['code'] == target['code']), None)
        if cur is None or tgt is None:
            raise EditError(T('inv.err.stash_changed', 'the stash changed on disk since it was read: try again'))
        new = insert_child(item_blob(raw_t, tgt), item_blob(raw_s, cur), data, _clean(pname))
        place = (tgt['page'], tgt['x'], tgt['y'], new)
        if same:
            # one write; the item keeps its place in its page's list (index after the filler is taken out)
            items = parse_stash(app.path, data)
            here = [i for i in items if i['page'] == tgt['page'] and i['_offset'] != cur['_offset']]
            idx = next(n for n, i in enumerate(here) if i['_offset'] == tgt['_offset'])
            bak = edit_stash(app.path, data, remove=[tgt['_offset'], cur['_offset']], insert=[place + (idx,)],
                             backup=app.needs_backup(app.path))
            app.backup_made(app.path, bak)
        else:
            bak = edit_stash(app.path, data, remove=[tgt['_offset']], insert=[place], backup=app.needs_backup(app.path))
            app.backup_made(app.path, bak)
            try:
                bak2 = edit_stash(src, data, remove=[cur['_offset']], backup=app.needs_backup(src))
                app.backup_made(src, bak2)
            except ERRORS:
                commit_file(app.path, raw_t, lambda tmp: None, backup=False)     # target back as it was
                raise
    except ERRORS as err:
        app.status.configure(text=T('inv.cannot_drop', 'Cannot drop here: {error}', error=err))
        return True
    app.load(app.path, keep_selection=False)
    app.selected = next((i for i in app.items if (i['page'], i['x'], i['y']) == (tgt['page'], tgt['x'], tgt['y'])), None)
    app.draw_grid()
    app.set_detail(app.selected)
    app.status.configure(text=_done_msg(cname, pname))
    return True


# ------------------------------------------------------------------------------------------ character panel
def _target_entry(inv, ev):
    """(entry, merc) of the character item under the pointer (doll or inventory), or (None, False)."""
    from mxl_inv_gui import _local
    for cv in (inv.canvas, inv.doll):
        p = _local(cv, ev.x_root, ev.y_root)
        if p is not None:
            if cv is inv.doll and _local(inv.canvas, ev.x_root, ev.y_root) is not None:
                continue
            return inv.entry_at(cv, p[0], p[1])
    return None, False


def stash_on_char(inv, d, ev):
    """Main-grid drag released over a character item (MainInventory.drop_from_stash). True when handled."""
    app = inv.app
    it, src = d.get('item'), d.get('path') or app.path
    if it is None or inv.ch is None:
        return False
    tgt, merc = _target_entry(inv, ev)
    if tgt is None or not is_socketable(app, it['code']):
        return False
    import mxl_char as MC
    import mxl_rc_menu
    pname, cname = tgt.it['name'], app.full_name(it)
    try:
        inv._check_char()
        cur = next((i for i in parse_stash(src, inv.data) if i['_offset'] == it['_offset'] and i['code'] == it['code']), None)
        if cur is None:
            raise EditError(T('inv.err.stash_changed', 'the stash changed on disk since it was read: try again'))
        new = insert_child(inv.ch.stash_blob(tgt), item_blob(read_file(src), cur), inv.data, _clean(pname))
        before_char = inv.ch.raw
        where = _where(tgt)
        mxl_rc_menu._char_replace(inv, tgt, new, where, merc)
        bak_c = inv._save_char()
    except ERRORS + (MC.CharError,) as err:
        inv.reload()
        app.status.configure(text=T('inv.cannot_drop', 'Cannot drop here: {error}', error=err))
        return True
    try:
        bak_s = edit_stash(src, inv.data, remove=[cur['_offset']], backup=app.needs_backup(src))
        app.backup_made(src, bak_s)
    except ERRORS as err:
        note = ''
        try:
            commit_file(inv.ch.path, before_char, lambda tmp: None, backup=False)
        except Exception as rb:
            note = MC.rollback_note(inv.ch.path, rb)
        inv._error(T('inv.to_char', 'To character'), f'{err}{note}')
        return True
    app.selected = None
    inv._done(_done_msg(cname, pname), [bak_c, bak_s], select_char=(where, merc))
    return True


def char_on_char(inv, d, ev):
    """Character item dragged over another character item (MainInventory.on_release). True when handled."""
    e, src_merc = d['entry'], d['merc']
    tgt, merc = _target_entry(inv, ev)
    if tgt is None or tgt is e or not is_socketable(inv.app, e.it['code']):
        return False
    import mxl_char as MC
    import mxl_rc_menu
    pname, cname = tgt.it['name'], e.it['name']
    try:
        inv._check_char()
        new = insert_child(inv.ch.stash_blob(tgt), inv.ch.stash_blob(e), inv.data, _clean(pname))
        where = _where(tgt)
        inv.ch.remove(e, src_merc)
        mxl_rc_menu._char_replace(inv, tgt, new, where, merc)
        bak = inv._save_char()
    except ERRORS + (MC.CharError,) as err:
        inv.reload()
        inv.app.status.configure(text=T('inv.cannot_drop', 'Cannot drop here: {error}', error=err))
        return True
    inv.selected = None
    inv._done(_done_msg(cname, pname), [bak], select_char=(where, merc))
    return True


def char_on_stash(inv, d, ev):
    """Character item dragged over a stash item (MainInventory.on_release). True when handled."""
    app = inv.app
    e, src_merc = d['entry'], d['merc']
    if not app.path:
        return False
    target = stash_item_at(app, ev.x_root, ev.y_root)
    if target is None or not is_socketable(app, e.it['code']):
        return False
    import mxl_char as MC
    pname, cname = app.full_name(target), e.it['name']
    path = app.path
    try:
        inv._check_char()
        before = read_file(path)
        tgt = next((i for i in parse_stash(path, inv.data)
                    if i['_offset'] == target['_offset'] and i['code'] == target['code']), None)
        if tgt is None:
            raise EditError(T('inv.err.stash_changed', 'the stash changed on disk since it was read: try again'))
        new = insert_child(item_blob(before, tgt), inv.ch.stash_blob(e), inv.data, _clean(pname))
        bak_s = edit_stash(path, inv.data, remove=[tgt['_offset']], insert=[(tgt['page'], tgt['x'], tgt['y'], new)],
                           backup=app.needs_backup(path))
        app.backup_made(path, bak_s)
    except ERRORS + (MC.CharError,) as err:
        app.status.configure(text=T('inv.cannot_drop', 'Cannot drop here: {error}', error=err))
        return True
    try:
        inv.ch.remove(e, src_merc)
        bak_c = inv._save_char()
    except ERRORS + (MC.CharError,) as err:
        note = ''
        try:
            commit_file(path, before, lambda tmp: None, backup=False)
        except Exception as rb:
            note = MC.rollback_note(path, rb)
        inv._error(T('ch.btn.to_stash', 'To stash'), f'{err}{note}')
        return True
    inv.selected = None
    inv._done(_done_msg(cname, pname), [bak_s, bak_c], select_stash=(tgt['page'], tgt['x'], tgt['y']))
    return True


# ------------------------------------------------------------------------------------------ Character tab
def char_tab_drop(cw, e, cv, ev):
    """Character tab (mxl_char_gui.CharacterWindow.on_release, both profiles): item e released over another item
    of the doll / inventory (ev: x, y inside cv). True when handled (inserted, or refused with a status)."""
    tgt, _slot = cw.entry_at(cv, ev)
    if tgt is None or tgt is e or not is_socketable(cw.app, e.it['code']):
        return False
    import mxl_char as MC
    import mxl_rc_menu
    merc = cw.is_merc()
    pname, cname = tgt.it['name'], e.it['name']
    try:
        new = insert_child(cw.ch.stash_blob(tgt), cw.ch.stash_blob(e), cw.data, _clean(pname))
        where = _where(tgt)
        cw.ch.remove(e, merc)
        mxl_rc_menu._char_replace(cw, tgt, new, where, merc)
    except ERRORS + (MC.CharError,) as err:
        cw.set_status(T('inv.cannot_drop', 'Cannot drop here: {error}', error=err), True)
        cw.reload()
        return True
    if not cw.save(_done_msg(cname, pname)):
        cw.reload()
    return True
