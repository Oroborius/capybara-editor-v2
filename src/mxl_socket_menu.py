"""The item right-click menu's "Socket" submenu (stash items and character items, both profiles), shown only on
items that can have sockets in the game in use:

- Add Sockets (N): the item gets its maximum socket count N, from the selected game folder's tables
  (Creator.socket_limit: the base's gemsockets capped by its itemtype's MaxSock1 / MaxSock25 / MaxSock40 at the
  item's level; 1.14d profile: up to 7 on weapons, shields, body armor, helms, rings and amulets, the user's
  rule). Written like the creator does: the save field up to the base's sockets, the rest as item_numsockets
  (stat 194) in 1.14d (Creator.socket_split). Socketed items stay. Disabled when the item already has N.
- Remove Sockets: no sockets any more, the socketed items are deleted (and a 1.14d stat 194 with them).
- Unsocket: the sockets stay, the socketed items are taken out and put into the next free stash places (the
  shown page first, like 'To stash'); a 1.14d character's into its own stash (panel 5), then its inventory.
  When not all of them fit, nothing is changed.

Every action records one undo step (mxl_undo 'files': the stash and / or character file), Ctrl+Z undoes it."""
import os

import tkinter as tk

from mxl_lang import T
from mxl_save import read_file, item_blob, blob_item, parse_stash, free_spot, edit_stash, commit_file, EditError, \
    STASH_PAGES
from mxl_format import FormatError
from mxl_creator import (decode_item, encode_item, CreateError, FLAG_SIMPLE, FLAG_SOCKETED, FLAG_RUNEWORD)

MAX_COUNT = 7                      # the socketed-item count field of a record is 3 bits
FIELD_MAX = 15                     # the save's socket field is 4 bits
NUMSOCKETS = 194                   # item_numsockets: the 1.14d sockets above the save field
LOC_STORED, PANEL_STASH = 0, 5

ERRORS = (EditError, FormatError, CreateError, OSError, KeyError, ValueError, IndexError, AttributeError)


class SocketError(Exception):
    pass


def _t(key, default, **kw):
    return T('rc.sockm.' + key, default, **kw)


def _vanilla():
    try:
        import mxl_profile
        return not mxl_profile.is_median()
    except Exception:
        return False


def _creator(holder):
    import mxl_rc_menu
    return mxl_rc_menu._creator_for(holder)


# ------------------------------------------------------------------------------------------------ engine
def children(blob, data):
    import mxl_socket_insert as SI
    return SI.children(bytes(blob), data)


def current(rec):
    """Sockets the item has now (save field, plus stat 194 in the 1.14d profile)."""
    import mxl_socket_insert as SI
    return SI.socket_total(rec)


def max_sockets(cr, code, rec):
    """N: the most sockets this item may have in the game in use (0: none)."""
    if rec['flags'] & FLAG_SIMPLE:
        return 0
    try:
        n = cr.socket_limit(code, rec['ilvl'])
    except (KeyError, IndexError, AttributeError, TypeError):
        n = 0
    return max(0, min(n or 0, MAX_COUNT))


def _without_194(stats):
    return [s for s in stats or () if s.get('id') != NUMSOCKETS]


def add_to(rec, cr, data, code, n):
    """The record with n sockets in all (flag, save field, stat 194 in 1.14d); its children are not touched."""
    field_now = (rec.get('sockets') or 0) if rec['flags'] & FLAG_SOCKETED else 0
    spec = dict(sockets=n, code=code, ilvl=rec['ilvl'], quality=None, _sock_field=field_now)
    field, n194 = cr.socket_split(spec)
    if field > FIELD_MAX:
        field, n194 = FIELD_MAX, n - FIELD_MAX
    rec['flags'] |= FLAG_SOCKETED
    rec['sockets'] = field
    rec.setdefault('socketed_count', 0)
    if _vanilla():
        rec['stats'] = _without_194(rec.get('stats'))
        if n194 > 0:
            if not data.isc[NUMSOCKETS]['bits']:
                raise SocketError(_t('err.194', 'this game cannot store more than {n} sockets on it', n=field))
            rec['stats'].append(dict(id=NUMSOCKETS, param=None, value=n194, sockets=True))
    elif n194:
        raise SocketError(_t('err.field', 'the save cannot hold {n} sockets', n=n))
    return rec


def with_max(blob, data, cr, code):
    """(new bytes, N) of the item with its maximum socket count, socketed items kept."""
    rec, kids = children(blob, data)
    n = max_sockets(cr, code, rec)
    if rec['flags'] & FLAG_RUNEWORD:
        raise SocketError(_t('err.rw', 'a runeword keeps the sockets of its runes'))
    if n <= 0:
        raise SocketError(_t('err.none', 'this item cannot have sockets'))
    if current(rec) >= n:
        raise SocketError(_t('err.at_max', 'the item already has {n} sockets', n=n))
    rec = add_to(rec, cr, data, code, n)
    new = encode_item(rec, data) + b''.join(kids)
    _check(new, data, len(kids), n)
    return new, n


def without(blob, data):
    """(new bytes, children deleted): no sockets, no socketed items."""
    rec, kids = children(blob, data)
    if not rec['flags'] & FLAG_SOCKETED and not kids:
        raise SocketError(_t('err.no_sockets', 'the item has no sockets'))
    rec['flags'] &= ~FLAG_SOCKETED
    rec['socketed_count'] = 0
    rec.pop('sockets', None)
    if _vanilla():
        rec['stats'] = _without_194(rec.get('stats'))
    new = encode_item(rec, data)
    _check(new, data, 0, 0)
    return new, len(kids)


def emptied(blob, data):
    """(parent bytes with its sockets kept and empty, [children as loose stash items])."""
    rec, kids = children(blob, data)
    if not kids:
        raise SocketError(_t('err.empty', 'nothing is socketed in the item'))
    total = current(rec)
    new = encode_item(dict(rec, socketed_count=0), data)
    _check(new, data, 0, total)
    loose = []
    for k in kids:
        krec, size = decode_item(k, data)
        loose.append(encode_item(dict(krec, location=LOC_STORED, equipped=0, x=0, y=0, panel=PANEL_STASH), data)
                     + bytes(k[size:]))
    return new, loose


def _check(new, data, n_kids, n_sockets):
    """The new bytes read back as one item with n_kids children and n_sockets sockets (nothing written else)."""
    back, kids = children(new, data)
    seen = blob_item(new, data)
    if back.get('socketed_count', 0) != n_kids or len(kids) != n_kids or len(seen.get('socketed') or ()) != n_kids \
            or decode_item(new, data)[1] + sum(map(len, kids)) != len(new) or current(back) != n_sockets:
        raise SocketError(_t('err.invalid', 'the item would not be readable: nothing written'))


def stash_spots(items, blobs, data, pages):
    """[(page, x, y)] for the loose items, each in the first free place (pages in order), or None when one
    does not fit. items: the stash as parse_stash read it (the places taken)."""
    taken = list(items)
    out = []
    for b in blobs:
        it = blob_item(b, data)
        spot = free_spot(taken, it, data, pages)
        if spot is None:
            return None
        out.append(tuple(spot[:3]))
        taken.append(dict(it, page=spot[0], x=spot[1], y=spot[2]))
    return out


def _personal_stash_free(ch, data):
    """(cols, rows, set of taken cells) of a 1.14d character's own stash (panel 5)."""
    import mxl_vanilla_pages as VP
    _k, _t2, cols, rows, entries = VP.containers(ch, data)[0]
    used = set()
    for e in entries:
        try:
            w, h = data.base(e.it['code']).size
        except Exception:
            w, h = 1, 1
        for i in range(w):
            for j in range(h):
                used.add((e.it.get('x', 0) + i, e.it.get('y', 0) + j))
    return cols, rows, used


def place_on_character(ch, blobs, data):
    """1.14d: the loose items into the character's own stash (panel 5), then its inventory; in memory. Raises
    SocketError when one does not fit (the caller reloads: nothing is written)."""
    import mxl_char as MC
    cols, rows, used = _personal_stash_free(ch, data)
    for b in blobs:
        it = blob_item(b, data)
        w, h = data.base(it['code']).size
        spot = next(((x, y) for y in range(rows - h + 1) for x in range(cols - w + 1)
                     if not any((x + i, y + j) in used for i in range(w) for j in range(h))), None)
        if spot is not None:
            for i in range(w):
                for j in range(h):
                    used.add((spot[0] + i, spot[1] + j))
            ent = MC.Entry(None, MC.Entry(it, b).moved(data, location=LOC_STORED, equipped=0, x=spot[0], y=spot[1],
                                                       panel=PANEL_STASH))
            ent.it = blob_item(ent.blob, data)
            ch.items.append(ent)
            continue
        spot = ch.free_inventory_spot(it)
        if spot is None:
            raise SocketError(_t('err.room_char', 'not enough free room in the stash and the inventory for {n} '
                                 'socketed items: nothing changed', n=len(blobs)))
        ch.place(b, ('inv', spot[0], spot[1]), False)


# ------------------------------------------------------------------------------------------------ actions
def _app(holder):
    return getattr(holder, 'app', holder)


def _say(holder, win, msg, error=False):
    import mxl_rc_menu
    mxl_rc_menu._say(holder, win, msg, error)


def _name(holder, it, e):
    import mxl_rc_menu
    return mxl_rc_menu._item_name(holder, it, e)


def _blob(holder, it, win, e):
    return bytes(win.ch.stash_blob(e)) if win is not None else bytes(item_blob(read_file(holder.path), it))


def _where(e):
    import mxl_char as MC
    return ('slot', e.it['equipped']) if e.it['location'] == MC.LOC_EQUIPPED else ('inv', e.it['x'], e.it['y'])


def _record(app, before, name):
    try:
        import mxl_undo
        mxl_undo.record_files(app, before, name)
    except Exception as err:
        print('socket menu: undo not recorded:', err)


def _snap(app, win):
    import mxl_undo
    return mxl_undo.snapshot([getattr(app, 'path', None), win.ch.path if win is not None else None])


def _write_parent(holder, it, win, e, new, msg, extra=None):
    """The item's new bytes at its own place (stash: edit_stash; character: remove -> place -> save), one undo
    step. extra: [(page, x, y, blob)] stash items written in the same edit (stash item) - or, for a character
    item, a callable(ch) that adds the loose items to the character in memory. True when written."""
    app = _app(holder)
    name = _name(holder, it, e)
    before = _snap(app, win)
    if win is None:
        try:
            bak = edit_stash(holder.path, holder.data, remove=[it['_offset']],
                             insert=[(it['page'], it['x'], it['y'], new)] + list(extra or ()),
                             backup=holder.needs_backup(holder.path))
        except ERRORS as err:
            _say(holder, None, str(err), True)
            return False
        holder.backup_made(holder.path, bak)
        _record(app, before, name)
        import mxl_rc_menu
        mxl_rc_menu._selected(holder, it['page'], it['x'], it['y'])
        _say(holder, None, msg + T('undo.hint_any', ' - Ctrl+Z undoes it'))
        return True
    import mxl_rc_menu
    try:
        mxl_rc_menu._char_replace(win, e, new, _where(e), win.is_merc())
        if callable(extra):
            extra(win.ch)
    except Exception as err:
        win.reload()
        win.set_status(str(err), True)
        return False
    if not win.save(msg + T('undo.hint_any', ' - Ctrl+Z undoes it')):
        win.set_status(T('ch.err.not_saved', 'character not saved'), True)
        return False
    _record(app, before, name)
    return True


def add_sockets(holder, it=None, win=None, e=None):
    data = holder.data
    try:
        code = it['code'] if win is None else e.it['code']
        new, n = with_max(_blob(holder, it, win, e), data, _creator(holder), code)
    except (SocketError,) + ERRORS as err:
        _say(holder, win, str(err), True)
        return False
    return _write_parent(holder, it, win, e, new, _t('add.done', '{name}: {n} sockets', name=_name(holder, it, e), n=n))


def remove_sockets(holder, it=None, win=None, e=None):
    data = holder.data
    try:
        blob = _blob(holder, it, win, e)
        rec, _k = children(blob, data)
        new, n = without(blob, data)
    except (SocketError,) + ERRORS as err:
        _say(holder, win, str(err), True)
        return False
    msg = _t('remove.done', '{name}: sockets removed ({n} socketed items deleted)', name=_name(holder, it, e), n=n)
    if rec['flags'] & FLAG_RUNEWORD:
        msg += T('rc.unsock.rw', ' (the runeword keeps its stats, but its runes are gone)')
    return _write_parent(holder, it, win, e, new, msg)


def unsocket(holder, it=None, win=None, e=None):
    """The socketed items out into free places (see the module text); nothing is changed when they do not fit."""
    app = _app(holder)
    data = holder.data
    try:
        new, loose = emptied(_blob(holder, it, win, e), data)
    except (SocketError,) + ERRORS as err:
        _say(holder, win, str(err), True)
        return False
    name = _name(holder, it, e)
    msg = _t('unsock.done', '{name}: {n} socketed items taken out', name=name, n=len(loose))
    path = getattr(app, 'path', None)
    pages = []
    if path:
        try:
            cur = app.page()
        except Exception:
            cur = 0
        pages = [cur] + [p for p in range(STASH_PAGES) if p != cur]
    if win is None:                                    # stash item: one edit of the stash
        try:
            spots = stash_spots(parse_stash(path, data), loose, data, pages)
        except ERRORS as err:
            _say(holder, None, str(err), True)
            return False
        if spots is None:
            _say(holder, None, _t('err.room', 'not enough free room in the stash for {n} socketed items: nothing '
                                  'changed', n=len(loose)), True)
            return False
        return _write_parent(holder, it, None, None, new, msg + _pages_note(spots),
                             extra=[s + (b,) for s, b in zip(spots, loose)])
    if not path:
        if not _vanilla():
            win.set_status(T('cr.open_stash', 'Open a stash in the main window first.'), True)
            return False
        # 1.14d: no stash file - the character's own stash, then its inventory (one write of the character)
        return _write_parent(holder, None, win, e, new, msg,
                             extra=lambda ch: place_on_character(ch, loose, data))
    # character item, stash file open: the stash first, then the character; the stash is put back when the
    # character is not written
    try:
        spots = stash_spots(parse_stash(path, data), loose, data, pages)
        if spots is None:
            raise SocketError(_t('err.room', 'not enough free room in the stash for {n} socketed items: nothing '
                                 'changed', n=len(loose)))
        before = _snap(app, win)
        raw_s = read_file(path)
        bak = edit_stash(path, data, insert=[s + (b,) for s, b in zip(spots, loose)], backup=app.needs_backup(path))
        app.backup_made(path, bak)
    except (SocketError,) + ERRORS as err:
        win.set_status(str(err), True)
        return False
    import mxl_rc_menu
    ok = False
    try:
        mxl_rc_menu._char_replace(win, e, new, _where(e), win.is_merc())
        ok = win.save(msg + _pages_note(spots) + T('undo.hint_any', ' - Ctrl+Z undoes it'))
    except Exception as err:
        win.set_status(str(err), True)
    if not ok:
        try:
            commit_file(path, raw_s, lambda tmp: None, backup=False)
        except Exception as rb:
            import mxl_char as MC
            win.set_status(T('ch.err.not_saved', 'character not saved') + MC.rollback_note(path, rb), True)
        win.reload()
        _reload_stash(app)
        return False
    _record(app, before, name)
    _reload_stash(app)
    return True


def _pages_note(spots):
    pages = sorted({s[0] + 1 for s in spots})
    return _t('pages', ' (stash page {p})', p=', '.join(map(str, pages)))


def _reload_stash(app):
    try:
        app.load(app.path, keep_selection=True)
    except Exception as err:
        print('socket menu: stash not reloaded:', err)


# ------------------------------------------------------------------------------------------------ menu
def add_menu(holder, menu, it=None, win=None, e=None):
    """The 'Socket' submenu, only on an item that can have sockets in the game in use (or has some)."""
    data = holder.data
    try:
        code = it['code'] if win is None else e.it['code']
        rec, kids = children(_blob(holder, it, win, e), data)
    except ERRORS:
        return None
    if rec['flags'] & FLAG_SIMPLE:
        return None
    n = max_sockets(_creator(holder), code, rec)
    now = current(rec)
    if n <= 0 and not now and not kids:
        return None
    sub = tk.Menu(menu, tearoff=0)
    if n > 0 and not rec['flags'] & FLAG_RUNEWORD:
        sub.add_command(label=_t('add', 'Add Sockets ({n})', n=n), state='disabled' if now >= n else 'normal',
                        command=lambda: add_sockets(holder, it, win, e))
    if now or kids:
        sub.add_command(label=_t('remove', 'Remove Sockets'), command=lambda: remove_sockets(holder, it, win, e))
    sub.add_command(label=_t('unsocket', 'Unsocket'), state='normal' if kids else 'disabled',
                    command=lambda: unsocket(holder, it, win, e))
    menu.add_cascade(label=_t('title', 'Socket'), menu=sub)
    return sub
