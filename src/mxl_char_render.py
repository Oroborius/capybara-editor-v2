"""The character as the game draws it: class model + worn gear, animated (town idle), from the game's own DCC / COF
files (data\\global\\chars\\<CL>\\...). Read from the player's MPQs through mxl_d2look_art (raw member cache), decoded
with mxl_dcc. Pure Python + PIL Image methods.

    anim = render(art, data_folder, cls, gear)  ->  Anim(frames=[PIL RGBA], fps, size) or None

gear: {slot: item code} (slots of mxl_char.SLOTS: 1 helm, 3 body armor, 4 right hand, 5 left hand).
Not done here: item colour tints (colormaps), the unit's shadow, a background scene."""
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
    """(component layer type, alternate gfx code, weapon class, body armtypes bytes) of an item code, or None."""
    t = _TABLES.get(folder)
    if t is None:
        t = _TABLES[folder] = {**_rows(folder, 'weapons.bin'), **_rows(folder, 'armor.bin')}
    r = t.get(code)
    if r is None:
        return None
    alt = r[144:148].split(b'\0')[0].decode('latin-1').strip().lower() or code.lower()
    wc = r[192:196].split(b'\0')[0].decode('latin-1').strip().lower()
    return r[277], alt, wc, bytes(r[278:284])


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


def render(art, folder, cls, gear, direction=FRONT):
    """The animated character (list of RGBA frames on one canvas) or None when the class files are missing."""
    cl, wclass, arm = plan(folder, cls, gear)
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
        if t in (5, 6, 7) and t not in arm:
            continue                               # an empty hand has no weapon layer
        for a in dict.fromkeys((want, 'lit')):
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
    return Anim(frames, fps, (cl, wclass, tuple(sorted(arm.items()))))


def gear_of(ch, merc=False):
    """{slot: item code} of the worn gear (first weapon set)."""
    out = {}
    try:
        for slot, e in ch.equipped(merc).items():
            if slot in (1, 3, 4, 5):
                out[slot] = e.it['code']
    except Exception:
        pass
    return out
