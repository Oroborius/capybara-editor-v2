"""The character as the game draws it: class model + worn gear, animated (town idle), from the game's own DCC / COF
files (data\\global\\chars\\<CL>\\...). Read from the player's MPQs through mxl_d2look_art (raw member cache), decoded
with mxl_dcc. Pure Python + PIL Image methods.

    anim = render(art, data_folder, cls, gear)  ->  Anim(frames=[PIL RGBA], fps, size) or None

gear: {slot: item code or (item code, colour)} (slots of mxl_char.SLOTS: 1 helm, 3 body armor, 4 right hand,
5 left hand). Colour tints as the game: the item's Transform column (armor/weapons .bin byte 321) picks a colormap
file of data\\global\\items\\palette (21 maps of 256 palette indices), the unique's / set item's chrtransform
(uniqueitems.bin 0x38, setitems.bin 0x40; 255 = none) picks the map. Not done: magic / rare affix colours,
the unit's shadow, a background scene."""
import glob
import os
import struct
import threading

import mxl_dcc as D

CLASS_CODES = ('am', 'so', 'ne', 'pa', 'ba', 'dz', 'ai')
ARMTYPES = ('lit', 'med', 'hvy')
FRONT = 4                                  # direction 4 of the 8 / 16 faces the viewer (south)
MODES = ('tn', 'nu')                       # town idle, then neutral
REC = 424                                  # weapons / armor .bin record
# body-armor graphics bytes (armor.bin 278..283: rArm, lArm, Torso, Legs, rSPad, lSPad) -> COF layer types
_BODY = {3: 0, 4: 1, 1: 2, 2: 3, 8: 4, 9: 5}
_ARCH = {}
# Transform column -> colormap file
COLORMAPS = (None, 'grey', 'grey2', 'gold', 'brown', 'greybrown', 'invgrey', 'invgrey2', 'invgreybrown')
_SLOT_LAYERS = {1: (0,), 3: (1, 2, 3, 4, 8, 9)}
_LOCK = threading.Lock()


class Anim:
    __slots__ = ('frames', 'fps', 'size', 'key')

    def __init__(self, frames, fps, key):
        self.frames, self.fps, self.key = frames, fps, key
        self.size = frames[0].size if frames else (0, 0)


def _archives(art):
    """The art reader's archive list plus d2char.mpq (the character animations live there, not in the mod)."""
    import mxl_d2look_art as A
    with _LOCK:
        got = _ARCH.get(art.game_dir)
        if got is None:
            gd = art.game_dir
            names = sorted(glob.glob(os.path.join(gd, 'medianxl-*.mpq')))
            names += [os.path.join(gd, n) for n in ('patch_d2.mpq', 'd2exp.mpq', 'd2char.mpq', 'd2data.mpq')]
            arcs = A._Archives(names)

            def chars():
                return arcs
            chars.__name__ = 'chars'
            got = _ARCH[gd] = chars
    return got


def read(art, name):
    return art._read_raw(name, _archives(art))


def _rows(folder, name):
    out = {}
    try:
        d = open(os.path.join(folder, name), 'rb').read()
    except OSError:
        return out
    n = struct.unpack_from('<I', d, 0)[0]
    for i in range(min(n, (len(d) - 4) // REC)):
        r = d[4 + i * REC:4 + (i + 1) * REC]
        code = r[128:132].split(b'\0')[0].decode('latin-1').strip()
        if code:
            out.setdefault(code, r)
    return out


_TABLES = {}


def item_gfx(folder, code):
    """(component layer type, alternate gfx code, weapon class, body armtypes bytes, transform) of an item code,
    or None."""
    t = _TABLES.get(folder)
    if t is None:
        t = _TABLES[folder] = {**_rows(folder, 'weapons.bin'), **_rows(folder, 'armor.bin')}
    r = t.get((code or '').strip())              # save codes are 4 bytes, padded with a space ('k23 ')
    if r is None:
        return None
    alt = r[144:148].split(b'\0')[0].decode('latin-1').strip().lower() or code.lower()
    wc = r[192:196].split(b'\0')[0].decode('latin-1').strip().lower()
    return r[277], alt, wc, bytes(r[278:284]), r[321]


def _split(g):
    """gear value -> (code, colour or None)."""
    if isinstance(g, (tuple, list)):
        return g[0], (g[1] if len(g) > 1 else None)
    return g, None


_COLORS = {}


def item_color(folder, it):
    """The character colour (0..20) of a unique / set item dict of the save, or None."""
    q = it.get('quality')
    n = it.get('set_unique_id')
    if q not in ('unique', 'set') or n is None:
        return None
    name, rs, off = ('uniqueitems.bin', 332, 0x38) if q == 'unique' else ('setitems.bin', 440, 0x40)
    t = _COLORS.get((folder, name))
    if t is None:
        try:
            d = open(os.path.join(folder, name), 'rb').read()
            cnt = struct.unpack_from('<I', d, 0)[0]
            t = bytes(d[4 + i * rs + off] for i in range(min(cnt, (len(d) - 4) // rs)))
        except (OSError, struct.error):
            t = b''
        _COLORS[(folder, name)] = t
    c = t[n] if 0 <= n < len(t) else 255
    return c if c < 21 else None


def _animdata(art, folder):
    try:
        return D.animdata(open(os.path.join(folder, 'animdata.d2'), 'rb').read())
    except OSError:
        return {}


def _palette(art):
    lut = art._lut
    return [(lut[r], lut[g], lut[b]) for r, g, b in art.pal()]


def plan(folder, cls, gear):
    """(class code, weapon class, {layer type: armtype}) the gear asks for."""
    cl = CLASS_CODES[cls] if 0 <= cls < len(CLASS_CODES) else 'pa'
    arm = {}
    wclass = 'hth'
    gear = {k: _split(v)[0] for k, v in gear.items()}
    helm = gear.get(1) and item_gfx(folder, gear[1])
    if helm and helm[0] == 0:
        arm[0] = helm[1]
    body = gear.get(3) and item_gfx(folder, gear[3])
    if body and body[0] == 1:
        for lt, i in _BODY.items():
            v = body[3][i]
            if v < 3:
                arm[lt] = ARMTYPES[v]
    for slot in (4, 5):
        g = gear.get(slot) and item_gfx(folder, gear[slot])
        if not g or g[0] not in (5, 6, 7):
            continue
        lt = g[0]
        if lt == 5 and slot == 5:                  # a second one-hander is drawn in the left hand
            lt = 6
        arm.setdefault(lt, g[1])
        if lt != 7 and g[2] and wclass == 'hth':
            wclass = g[2]
    return cl, wclass, arm


def tints(folder, gear):
    """{layer type: (colormap file, colour)} of the coloured worn items."""
    out = {}
    for slot, v in gear.items():
        code, col = _split(v)
        g = col is not None and item_gfx(folder, code)
        if not g or not 0 < g[4] < len(COLORMAPS):
            continue
        lts = _SLOT_LAYERS.get(slot)
        if lts is None:
            lts = (g[0],) if g[0] in (5, 6, 7) else ()
            if g[0] == 5 and slot == 5:
                lts = (6,)
            if g[0] in (5, 6) and g[2] in ('bow', 'xbw', 'stf', '2hs', '2ht'):
                lts = (5, 6)
        for lt in lts:
            out.setdefault(lt, (COLORMAPS[g[4]], col))
    return out


def _colormap(art, name, col):
    try:
        d = read(art, f'data\\global\\items\\palette\\{name}.dat')
    except Exception:
        return None
    m = d[col * 256:(col + 1) * 256]
    if len(m) != 256:
        return None
    return b'\0' + bytes(m[1:])                     # index 0 stays transparent


def render(art, folder, cls, gear, direction=FRONT):
    """The animated character (list of RGBA frames on one canvas) or None when the class files are missing."""
    cl, wclass, arm = plan(folder, cls, gear)
    tint = tints(folder, gear)
    cof = None
    for wc in (wclass, 'hth'):
        for mode in MODES:
            try:
                cof = D.COF(read(art, f'data\\global\\chars\\{cl}\\cof\\{cl}{mode}{wc}.cof'))
                break
            except Exception:
                continue
        if cof is not None:
            break
    if cof is None:
        return None
    if wc != wclass:                               # no animation for that weapon class: plain hands
        arm = {k: v for k, v in arm.items() if k not in (5, 6, 7)}
    name = f'{cl}{mode}{wc}'
    layers = {}
    for t, _transp, _eff, lwc in cof.layers:
        ly = D.LAYERS[t].lower() if t < len(D.LAYERS) else None
        if ly is None:
            continue
        want = arm.get(t, 'lit')
        if t in (5, 6) and t not in arm:           # two-handed bows / crossbows / staves draw in both hands
            want = arm.get(11 - t)
        if want is None or t == 7 and t not in arm:
            continue                               # an empty hand has no weapon layer
        for a in (want,) if t in (5, 6, 7) else dict.fromkeys((want, 'lit')):
            try:
                data = read(art, f'data\\global\\chars\\{cl}\\{ly}\\{cl}{ly}{a}{mode}{lwc}.dcc')
                nd = D.header(data)[0]
                layers[t] = D.decode_direction(data, direction % nd if nd else 0)
                break
            except Exception:
                continue
    if not layers:
        return None
    nfr = cof.frames
    fpd, speed = _animdata(art, folder).get(name, (nfr, 256))
    fps = max(1.0, min(25.0, speed * 25 / 256)) if speed else 12.5
    # one canvas for all frames: the union of every layer's box (anchor = the feet)
    x0 = min(fr[0].x0 for fr in layers.values())
    y0 = min(fr[0].y0 for fr in layers.values())
    x1 = max(fr[0].x0 + fr[0].w for fr in layers.values())
    y1 = max(fr[0].y0 + fr[0].h for fr in layers.values())
    pal = _palette(art)
    from PIL import Image
    maps = {}
    for t in layers:
        if t in tint:
            m = _colormap(art, *tint[t])
            if m:
                maps[t] = m
                for f in layers[t]:
                    f.pixels = bytes(f.pixels).translate(m)
    imgs = {t: [f.image(pal) for f in frs] for t, frs in layers.items()}
    frames = []
    dirs = cof.dirs or 1
    cd = direction % dirs
    for f in range(nfr):
        can = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
        for t in cof.draw_order(cd, f):
            ims = imgs.get(t)
            if not ims:
                continue
            fr = layers[t][f % len(ims)]
            can.alpha_composite(ims[f % len(ims)], (fr.x0 - x0, fr.y0 - y0))
        frames.append(can)
    return Anim(frames, fps, (cl, wclass, tuple(sorted(arm.items())), tuple(sorted(tint.items()))))


def gear_of(ch, merc=False):
    """{slot: (item code, colour or None)} of the worn gear (first weapon set)."""
    out = {}
    try:
        folder = ch.data.folder
    except Exception:
        folder = None
    try:
        for slot, e in ch.equipped(merc).items():
            if slot in (1, 3, 4, 5):
                col = None
                if folder:
                    try:
                        col = item_color(folder, e.it)
                    except Exception:
                        col = None
                out[slot] = (e.it['code'].strip(), col)
    except Exception:
        pass
    return out
