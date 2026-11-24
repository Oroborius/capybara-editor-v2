"""Speed-ups that give the same results: free place search, icon layers, MPQ table decryption, DC6 decoding,
art caches kept across Character window rebuilds.

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
object is used.

3. mpq.decrypt (the collector's MPQ reader decrypts each archive's hash and block table when it opens it): the
same loop over an array of 32-bit words with the key table in a local list instead of struct.unpack / pack per
word and a growing bytearray. Same bytes out (test_21 compares them); about 1.4x faster. Used on the first start
and the first time a class's skill art is needed (a new class in the character dropdown).

4. mxl_d2ui_dc6.dc6_frames remembered by the file's bytes: the Character window is built again for every
character picked in the dropdown, and its Skills page, stat screen and Hotkeys page each decoded the class's skill
icon sheet (and the panel art) again in pure Python (~0.15 s per switch). The decoded frames are kept, keyed by
the file's content (so a different file can never get them), at most DC6_KEEP bytes of input; every call gets
its own copies of the pixel arrays. Big files (panels, decoded to more than DC6_BIG) are not kept: they are
decoded once into the art's PNG cache anyway.

5. The stat screen's and the skill tree's art caches (game-font text lines, panel and button images, the class
skill icons) are kept for the current art object and game data across Character window rebuilds instead of starting empty
in every new window: a wrapper around their constructors hands each new window the dictionaries of the one
before. Nothing in them depends on the character (keys are file paths, sizes, fonts, colours, class numbers).

6. The stat screen's scaled panels: every redraw (each notch of the wheel over the "All Item Attributes" list)
composed both panels of the open book and scaled both with LANCZOS (~16 ms each at 1.25x), although the panel
beside the list had not changed. The image a page composes now carries a resize() that remembers its result by
the image's content (a digest of its pixels): the same pixels at the same size give the same scaled pixels, so
an unchanged panel is not scaled again. Every caller gets its own copy (the redraw draws texts onto it). At most
SCALED_KEEP results are kept. Composing itself is unchanged: every panel is still composed at every redraw.
"""
import sys
import weakref
from collections import OrderedDict

_state = {'orig': None, 'icon_orig': None, 'data': None, 'decrypt_orig': None, 'dc6_orig': None}
DC6_KEEP = 16 * 2 ** 20             # bytes of file + decoded pixels kept
DC6_BIG = 2 * 2 ** 20                # a file decoding to more than this is not kept (panels: cached as PNG)
_dc6 = OrderedDict()                 # file bytes -> (cost, frames as the collector's function returns them)
_dc6_size = [0]
_shared = {}                         # kind -> (art, weakref to the game data, value): one per kind
SCALED_KEEP = 6
_scaled = OrderedDict()              # (digest, mode, size, new size, resample) -> scaled image
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
        from mxl_profile import is_median

        sockets = it.get('sockets')
        if not is_median() and it.get('has_sockets'):
            from mxl_format_fix import shown_sockets

            sockets = shown_sockets(it)
        key = (it['code'], icon_name(it, data), it.get('image'), it.get('ethereal'), sockets,
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


# ------------------------------------------------------------------ 3. mpq.decrypt
def _decrypt_with(ct):
    from array import array
    M = 0xFFFFFFFF

    def decrypt(data, key):
        n = len(data) // 4
        a = array('I')
        a.frombytes(bytes(data[:n * 4]))
        s2 = 0xEEEEEEEE
        for i in range(n):
            s2 = (s2 + ct[key & 255]) & M
            v = (a[i] ^ (key + s2)) & M
            a[i] = v
            key = (((~key << 21) + 0x11111111) | (key >> 11)) & M
            s2 = (v + s2 + (s2 << 5) + 3) & M
        return a.tobytes() + data[n * 4:]
    return decrypt


def _install_decrypt():
    from array import array
    import mpq
    cur = mpq.decrypt
    if getattr(cur, '_capy_fast', False):
        return
    if sys.byteorder != 'little' or array('I').itemsize != 4:
        return
    ct = [int(v) for v in mpq.CT[1024:1280]]
    if len(ct) != 256:
        return
    fast = _decrypt_with(ct)
    for probe in (b'', b'\x01\x02\x03', bytes(range(256)) * 3 + b'\x07'):          # the same bytes or not at all
        for key in (0, 0xC3AF3770, 0xEC83B3A3, 0xFFFFFFFF):
            if fast(probe, key) != cur(probe, key):
                print('mxl_speed: mpq.decrypt differs, not replaced')
                return
    fast._capy_fast = True
    fast.original = cur
    _state['decrypt_orig'] = cur
    mpq.decrypt = fast


# ------------------------------------------------------------------ 4. dc6 frames
def dc6_frames(data):
    orig = _state['dc6_orig']
    try:
        key = bytes(data)
    except Exception:
        return orig(data)
    ent = _dc6.get(key)
    if ent is None:
        got = orig(key)
        cost = len(key) + sum(len(f[4]) + len(f[5]) for f in got)
        if cost > DC6_BIG:                      # a big panel: decoded once into its PNG cache anyway
            return got
        _dc6[key] = (cost, got)
        _dc6_size[0] += cost
        while _dc6_size[0] > DC6_KEEP and len(_dc6) > 1:
            _k, (c, _v) = _dc6.popitem(last=False)
            _dc6_size[0] -= c
    else:
        _dc6.move_to_end(key)
        got = ent[1]
    return [(w, h, ox, oy, bytearray(px), bytearray(mask)) for w, h, ox, oy, px, mask in got]


def _install_dc6():
    import mxl_d2ui_dc6 as DC6
    cur = DC6.dc6_frames
    if getattr(cur, '_capy_fast', False):
        return
    _state['dc6_orig'] = cur
    dc6_frames._capy_fast = True
    dc6_frames.original = cur
    DC6.dc6_frames = dc6_frames
    _rebind('mxl_d2ui_dc6', 'dc6_frames', cur, dc6_frames)


# ------------------------------------------------------------------ 5. window art caches
def shared(kind, art, data, make):
    """The value kept for (kind, art, data); make() builds it the first time (or for other game data)."""
    ent = _shared.get(kind)
    if ent is not None and ent[0] is art and ent[1]() is data:
        return ent[2]
    try:
        ref = weakref.ref(data)
    except TypeError:
        return make()
    val = make()
    _shared[kind] = (art, ref, val)              # another art (theme) or game data: the old value is dropped
    return val


def _wrap_statscreen(cls):
    orig = cls.__init__
    if getattr(orig, '_capy_fast', False):
        return

    def __init__(self, parent, win, art, *a, **k):
        orig(self, parent, win, art, *a, **k)
        try:
            got = shared('statscreen', art, win.data, lambda: (self.text, self._pil, self._bg))
            self.text, self._pil, self._bg = got
        except Exception as e:
            print('mxl_speed: stat screen caches not shared:', e)
    __init__._capy_fast = True
    __init__.original = orig
    cls.__init__ = __init__


def remember_resize(img):
    """Gives a PIL image a resize() whose result is kept by the image's content (see 6.)."""
    import hashlib
    real = img.resize

    def resize(size, resample=None, *a, **k):
        if a or k or resample is None:
            return real(size, resample, *a, **k) if resample is not None else real(size, *a, **k)
        # the pixels as they are now (~1.5 ms for a panel; a resize is ~16 ms)
        key = (hashlib.blake2b(img.tobytes(), digest_size=20).digest(), img.mode, img.size, tuple(size), resample)
        got = _scaled.get(key)
        if got is None:
            got = real(size, resample)
            _scaled[key] = got
            while len(_scaled) > SCALED_KEEP:
                _scaled.popitem(last=False)
        else:
            _scaled.move_to_end(key)
        return got.copy()
    img.resize = resize
    return img


def _wrap_compose(cls):
    orig = cls.compose
    if getattr(orig, '_capy_fast', False):
        return

    def compose(self, *a, **k):
        img = orig(self, *a, **k)
        try:
            remember_resize(img)
        except Exception:
            pass
        return img
    compose._capy_fast = True
    compose.original = orig
    cls.compose = compose


def _wrap_skilltree(cls):
    orig = cls.__init__
    if getattr(orig, '_capy_fast', False):
        return

    def __init__(self, parent, win, *a, **k):
        orig(self, parent, win, *a, **k)
        try:
            import mxl_d2look
            art = mxl_d2look.art()
            if art is not None:
                from mxl_statscreen import GameText
                self._pil, self._text = shared('skilltree', art, win.data, lambda: ({}, GameText(art)))
        except Exception as e:
            print('mxl_speed: skill tree caches not shared:', e)
    __init__._capy_fast = True
    __init__.original = orig
    cls.__init__ = __init__


def install_windows():
    """The stat screen / skill tree wrappers (their modules import the collector's data modules)."""
    try:
        import mxl_statscreen
        _wrap_statscreen(mxl_statscreen.StatScreen)
        _wrap_compose(mxl_statscreen.StatScreen)
        import mxl_skilltree
        _wrap_skilltree(mxl_skilltree.SkillTree)
    except Exception as e:
        print('mxl_speed: window caches not shared:', e)


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
    for step in (_install_decrypt, _install_dc6):
        try:
            step()
        except Exception as e:
            print('mxl_speed:', step.__name__, 'skipped:', e)
    import mxl_save
    cur = mxl_save.free_spot
    if getattr(cur, '_capy_fast', False):
        return
    _state['orig'] = cur
    free_spot._capy_fast = True
    free_spot.original = cur
    mxl_save.free_spot = free_spot
    _rebind('mxl_save', 'free_spot', cur, free_spot)
