"""The town's NPCs (Akara, Kashya, Charsi, Gheed, Warriv ... and Median XL's own) for the town backdrop of
mxl_scene: animated sprites in the scene's .base pixel coordinates, same convention as Scene.sprites (frames cut to
the window, walls / roofs / objects standing in front already laid over them).

    town_npcs(art, data_folder, act, scene, centre=None) -> [{'pos': (x, y), 'frames': [RGBA], 'fps': f,
                                                             'token': 'PS', 'monstats': 148}]
    add_npcs(scene, art, data_folder, act, centre=None) -> scene.sprites + the NPCs (a new list; nothing mutated)

centre must be the one given to mxl_scene.scene() (None: the waypoint, as there).
Data: DS1 type-1 entries (sub-tile x, y) -> monpreset.bin (u8 act, u8 kind, u16 place; kind 1 = monstats row;
the DS1 id counts the act's rows) -> monstats.bin (424-byte rows: code @0x10, monstats2 row @0x18) ->
monstats2.bin (308-byte rows: base weapon class @0x10, layer present flags @0x15 (16), layer variants @0x26
(16 x 12 compcode.bin indices)) -> data\\global\\monsters\\<tok>\\cof\\<tok><mode><wc>.cof + the layer DCCs
<tok>\\<ly>\\<tok><ly><part><mode><wc>.dcc. Mode NU (neutral), direction 4 (facing the viewer).
Drawn into the scene's window like its objects (mxl_scene: pal.pl2 draw modes against Scene.index, Scene.front laid
over, Scene.lit), so blended layers and the light match the town."""
import os
import struct
import threading

import mxl_char_render as R
import mxl_dcc as D
import mxl_scene as S

MODES = ('NU', 'WL', 'SC')
FRONT = 4
NAMES = {'PS': 'Akara', 'RC': 'Kashya', 'CI': 'Charsi', 'GH': 'Gheed', 'WA': 'Warriv', 'WX': 'Warriv',
         'DC': 'Deckard Cain', '2D': 'Deckard Cain', '3D': 'Deckard Cain', '4D': 'Deckard Cain', 'GR': 'Greiz',
         'EL': 'Elzix', 'DR': 'Drognan', 'LY': 'Lysander', 'GE': 'Geglash', 'AS': 'Atma', 'OF': 'Fara',
         'MS': 'Meshif', 'AL': 'Alkor', 'OR': 'Ormus', 'AH': 'Asheara', 'TX': 'Tyrael', '20': 'Halbu'}   # token -> name
_LOCK = threading.Lock()
_ANIM = {}
_TAB = {}


def _rows(folder, name):
    k = (folder, name)
    if k not in _TAB:
        _TAB[k] = S._table(folder, name)
    return _TAB[k]


def presets(folder, act):
    """[monstats row or None] indexed by the DS1 type-1 id of the act."""
    out = []
    for r in _rows(folder, 'monpreset.bin'):
        if len(r) >= 4 and r[0] == act:
            out.append(struct.unpack_from('<H', r, 2)[0] if r[1] == 1 else None)
    return out


def monster_plan(folder, mid):
    """monstats row -> (token, base weapon class, {layer type: part code}) or None."""
    ms = _rows(folder, 'monstats.bin')
    if not 0 <= mid < len(ms):
        return None
    r = ms[mid]
    tok = S._s(r[0x10:0x14])
    m2 = _rows(folder, 'monstats2.bin')
    ex = struct.unpack_from('<H', r, 0x18)[0]
    if not tok or ex >= len(m2):
        return None
    r2 = m2[ex]
    codes = [S._s(c) for c in _rows(folder, 'compcode.bin')]
    wc = S._s(r2[0x10:0x14]).lower() or 'hth'
    parts = {}
    for t in range(16):
        if not r2[0x15 + t]:
            continue
        v = r2[0x26 + 12 * t]
        parts[t] = codes[v] if v < len(codes) and v != 0xFF else 'lit'
    return tok, wc, parts


def town_presets(art, data_folder, act):
    """Every NPC preset of the town map: [(name, token, monstats row, (world x, y))]; the whole map, no window."""
    ds1s, _dt1 = S.town_files(data_folder, act)
    if not ds1s:
        return []
    m = S.DS1(R.read(art, ds1s[0]))
    pr = presets(data_folder, act)
    ms = _rows(data_folder, 'monstats.bin')
    out = []
    for typ, oid, x, y in m.objects:
        if typ == 1 and 0 <= oid < len(pr) and pr[oid] is not None and pr[oid] < len(ms):
            tok = S._s(ms[pr[oid]][0x10:0x14])
            out.append((NAMES.get(tok.upper(), tok), tok, pr[oid], S._sub_px(x, y)))
    return out


def monster_layers(art, folder, mid, direction=FRONT):
    """(frames, (x0, y0, x1, y1) box relative to the feet, fps) or None; frames[f] = [(index bytes, w, h, x, y,
    draw mode)] in draw order (mxl_scene.blend), x / y relative to the box. The monster's colour: monstats TransLvl
    > 0 picks that row of <tok>\\cof\\palshift.dat (all the towns' NPCs have 0: their own colours)."""
    p = monster_plan(folder, mid)
    if p is None:
        return None
    tok, wc, parts = p
    base = f'data\\global\\monsters\\{tok}\\'
    remap = None
    shift = _rows(folder, 'monstats.bin')[mid][77]
    if shift:
        try:
            ps = R.read(art, f'{base}cof\\palshift.dat')
            if len(ps) >= 256 * (shift + 1):
                remap = ps[256 * shift:256 * (shift + 1)]
        except Exception:
            pass
    for mode in MODES:
        for w in dict.fromkeys((wc, 'hth')):
            try:
                cof = D.COF(R.read(art, f'{base}cof\\{tok}{mode}{w}.cof'))
            except Exception:
                continue
            layers = {}
            for t, transp, eff, lwc in cof.layers:
                if t >= len(D.LAYERS):
                    continue
                ly = D.LAYERS[t]
                for part in dict.fromkeys((parts.get(t, 'lit'), 'lit')):
                    try:
                        data = R.read(art, f'{base}{ly}\\{tok}{ly}{part}{mode}{lwc or w}.dcc')
                        nd = D.header(data)[0]
                        layers[t] = (D.decode_direction(data, direction % nd if nd else 0), S.draw_mode(transp, eff))
                        break
                    except Exception:
                        continue
            if not layers:
                continue
            box = S._union(layers)
            cd = direction % (cof.dirs or 1)
            frames = [S._frame_layers(cof, cd, f, layers, box, remap) for f in range(max(1, cof.frames))]
            fpd, speed = R._animdata(art, folder).get(f'{tok}{mode}{w}'.lower(), (len(frames), 256))
            fps = max(1.0, min(25.0, speed * 25 / 256)) if speed else 12.5
            return frames, box, fps
    return None


def monster_anim(art, folder, pal, mid, direction=FRONT):
    """(frames [RGBA over nothing, one canvas], x0, y0 of the canvas relative to the feet, fps) or None."""
    got = monster_layers(art, folder, mid, direction)
    if got is None:
        return None
    frames, (x0, y0, x1, y1), fps = got
    return [S.layers_rgba(fl, (x1 - x0, y1 - y0), pal) for fl in frames], x0, y0, fps


def _layers_cached(art, folder, mid):
    k = (getattr(art, 'game_dir', None), folder, mid)
    if k not in _ANIM:
        try:
            _ANIM[k] = monster_layers(art, folder, mid)
        except Exception:
            _ANIM[k] = None
    return _ANIM[k]


def town_npcs(art, data_folder, act, scene, centre=None):
    """The NPC sprites of an act's town for `scene` (an mxl_scene.Scene of that act; its window is used, centre is
    only kept for the old signature). Each frame: the NPC's layers drawn over the scene's palette indices with the
    game's draw modes, what stands in front laid over, lit like the scene."""
    if scene is None or scene.index is None:
        return []
    with _LOCK:
        W, H = scene.base.size
        vx, vy = scene.window
        npcs = []                                       # (world y, monstats row, window box, (frames, masks), fps)
        for _name, _tok, mid, (ox, oy) in town_presets(art, data_folder, act):
            if not (vx - 256 < ox < vx + W + 256 and vy - 64 < oy < vy + H + 384):
                continue
            a = _layers_cached(art, data_folder, mid)
            if not a:
                continue
            frames, (bx0, by0, bx1, by1), fps = a
            px, py = ox + bx0 - vx, oy + by0 - vy
            if px + bx1 - bx0 <= 0 or py + by1 - by0 <= 0 or px >= W or py >= H:
                continue
            bg = scene.index.crop((px, py, px + bx1 - bx0, py + by1 - by0))
            comp = [S.compose(bg, fl, scene.tables) for fl in frames]
            npcs.append((oy, mid, (px, py), comp, fps))
        out = []
        ms = _rows(data_folder, 'monstats.bin')
        for n, (oy, mid, (px, py), comp, fps) in enumerate(npcs):
            fw, fh = comp[0][0].size
            box = (max(0, px), max(0, py), min(W, px + fw), min(H, py + fh))
            x0, y0, x1, y1 = box
            if x1 <= x0 or y1 <= y0:
                continue
            fi, fm = scene.front(box, oy, 2)            # objects at the same depth: behind
            for k, (oy2, _m, (qx, qy), comp2, _f) in enumerate(npcs):
                if k != n and (oy2, k) > (oy, n):       # NPCs standing lower: in front
                    fi.paste(comp2[0][0], (qx - x0, qy - y0), comp2[0][1])
                    fm.paste(255, (qx - x0, qy - y0), comp2[0][1])
            fr = []
            for ci, cm, (bm, bs) in comp:
                c = (x0 - px, y0 - py, x1 - px, y1 - py)
                ci, cm, bm = ci.crop(c), cm.crop(c), bm.crop(c)
                ci.paste(fi, (0, 0), fm)
                bm.paste(0, (0, 0), fm)
                fr.append(scene.lit(S.to_rgba(ci, cm, scene.pal), (x0, y0), (bm, bs.crop(c))))
            tok = S._s(ms[mid][0x10:0x14])
            out.append({'pos': (x0, y0), 'frames': fr, 'fps': fps, 'token': tok, 'monstats': mid,
                        'name': NAMES.get(tok.upper(), tok)})
        return out


def add_npcs(scene, art, data_folder, act, centre=None):
    """scene.sprites followed by the NPCs (a new list; the scene is not changed)."""
    if scene is None:
        return []
    return list(scene.sprites) + town_npcs(art, data_folder, act, scene, centre)
