"""Speed-ups of the collector's code that give the same results: free place search, icon layers.

1. A faster mxl_save.free_spot (same answer, same order of search).

The collector's free_spot tries every (page, y, x) in order and calls placement_error for each, which loops over
every item of the stash: positions x items. With a full stash (1340 items, the first free place on page 7) one
call took 1.4 s, and Duplicate / Paste / Import / the Item Creator / Undo / Take out call it once per placed item.
Here the cells taken on the searched pages are collected once (one pass over the items), then the positions are
tried in the collector's order against that set: ~5 ms for the same stash.

Same result as the collector's function: positions in the same order (pages as given, then rows, then columns),
the item itself is ignored (identity, as placement_error does), pages outside 0..STASH_PAGES-1 give nothing.
Anything this version is not sure to answer exactly like the original (a size below 1, coordinates that are not
integers, an unknown base code, any error) is handed to the collector's function unchanged.

2. mxl_gfx.icon_layers remembered (the item's icon composed on its cell background, before any scaling).
Every cache of scaled icons (the stash's, the equipment panel's, the Character pages') is keyed by the cell size
and emptied when the window's cell size changes: each resize that changes it read and composed every visible
icon again from its PNG files (~half of the icon time of a resize). The layers are kept here under the key those
caches use without the cell size (code, icon name, image, ethereal, sockets, socketed icons, background), at most
ICON_KEEP of them (least recently used dropped); every call gets its own copies of the images. Emptied when the
icons are extracted again (mxl_gfx.extract_icons: game data rebuilt or repaired) and when another game-data
object is used."""
import sys
import weakref
from collections import OrderedDict

_state = {'orig': None, 'icon_orig': None, 'data': None}
ICON_KEEP = 400
_layers = OrderedDict()


def _occupied(items, it, data, pages):
    """{page: set of (x, y) cells taken} for the pages searched, or None when the fast path does not apply."""
    want = set(pages)
    taken = {p: set() for p in want}
    for o in items:
        if o is it:
            continue
        p = o['page']
        if p not in want:
            continue
        ow, oh = data.base(o['code']).size
        ox, oy = o['x'], o['y']
        if not (type(ow) is int and type(oh) is int and type(ox) is int and type(oy) is int) or ow < 1 or oh < 1:
            return None
        cells = taken[p]
        for yy in range(oy, oy + oh):
            for xx in range(ox, ox + ow):
                cells.add((xx, yy))
    return taken


def free_spot(items, it, data, pages=range(0, 10)):
    import mxl_save
    orig = _state['orig']
    pages = list(pages)
    try:
        w, h = data.base(it['code']).size
        if not (type(w) is int and type(h) is int) or w < 1 or h < 1:
            raise ValueError('size')
        cols, rows, npages = mxl_save.STASH_COLS, mxl_save.STASH_ROWS, mxl_save.STASH_PAGES
        taken = _occupied(items, it, data, [p for p in pages if type(p) is int and 0 <= p < npages])
    except Exception:
        taken = None
    if taken is None:
        return orig(items, it, data, pages)
    for page in pages:
        cells = taken.get(page) if type(page) is int else None
        if cells is None:                        # outside the stash: the collector finds no place there either
            continue
        for y in range(rows - h + 1):
            for x in range(cols - w + 1):
                if not any((xx, yy) in cells for yy in range(y, y + h) for xx in range(x, x + w)):
                    return (page, x, y)
    return None


def icon_layers(it, data, bg, folder='data/items'):
    orig = _state['icon_orig']
    try:
        ref = _state['data']
        if ref is None or ref() is not data:          # other game data: nothing remembered applies
            _layers.clear()
            _state['data'] = weakref.ref(data)
    except TypeError:
        return orig(it, data, bg, folder)
    try:
        from mxl_gfx import icon_name
        key = (it['code'], icon_name(it, data), it.get('image'), it.get('ethereal'), it.get('sockets'),
               tuple(icon_name(s, data) for s in it.get('socketed', [])), bg, folder)
        hash(key)
    except Exception:
        return orig(it, data, bg, folder)
    if key in _layers:
        _layers.move_to_end(key)
        got = _layers[key]
    else:
        got = orig(it, data, bg, folder)
        if got is not None and not isinstance(got, dict):
            return got
        _layers[key] = got
        while len(_layers) > ICON_KEEP:
            _layers.popitem(last=False)
    if got is None:
        return None
    return {k: (im.copy() if im is not None else None) for k, im in got.items()}


def _extract_wrapper(cur):
    def extract_icons(*a, **k):
        _layers.clear()
        try:
            return cur(*a, **k)
        finally:
            _layers.clear()
    extract_icons._capy_fast = True
    extract_icons.original = cur
    return extract_icons


def _rebind(mod_name, name, cur, new):
    for mod in list(sys.modules.values()):
        try:
            if mod is not None and getattr(mod, '__name__', '') != mod_name and getattr(mod, name, None) is cur:
                setattr(mod, name, new)
        except Exception:
            pass


def install():
    """Replaces mxl_save.free_spot and mxl_gfx.icon_layers, also where a module imported them by name already."""
    try:
        import mxl_gfx
        cur = mxl_gfx.icon_layers
        if not getattr(cur, '_capy_fast', False):
            _state['icon_orig'] = cur
            icon_layers._capy_fast = True
            icon_layers.original = cur
            mxl_gfx.icon_layers = icon_layers
            _rebind('mxl_gfx', 'icon_layers', cur, icon_layers)
        ex = getattr(mxl_gfx, 'extract_icons', None)
        if ex is not None and not getattr(ex, '_capy_fast', False):
            new = _extract_wrapper(ex)
            mxl_gfx.extract_icons = new
            _rebind('mxl_gfx', 'extract_icons', ex, new)
    except Exception as e:
        print('mxl_speed: icon layers not cached:', e)
    import mxl_save
    cur = mxl_save.free_spot
    if getattr(cur, '_capy_fast', False):
        return
    _state['orig'] = cur
    free_spot._capy_fast = True
    free_spot.original = cur
    mxl_save.free_spot = free_spot
    _rebind('mxl_save', 'free_spot', cur, free_spot)
