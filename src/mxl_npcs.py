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
<tok>\\<ly>\\<tok><ly><part><mode><wc>.dcc. Mode NU (neutral), direction 4 (facing the viewer)."""
import os
import struct
import threading

import mxl_char_render as R
import mxl_dcc as D
import mxl_scene as S

MODES = ('NU', 'WL', 'SC')
FRONT = 4
NAMES = {'PS': 'Akara', 'RC': 'Kashya', 'CI': 'Charsi', 'GH': 'Gheed', 'WA': 'Warriv', 'DC': 'Deckard Cain',
         'CA': 'Deckard Cain', 'GR': 'Greiz', 'EL': 'Elzix', 'FA': 'Fara', 'DR': 'Drognan', 'LG': 'Lysander',
         'GE': 'Geglash', 'JE': 'Jerhyn', 'AT': 'Atma', 'ME': 'Meshif', 'MS': 'Meshif', 'AS': 'Asheara',
         'HR': 'Hratli', 'AL': 'Alkor', 'OR': 'Ormus', 'NA': 'Natalya', 'TY': 'Tyrael', 'TX': 'Tyrael',
         'JM': 'Jamella', 'HL': 'Halbu', 'IZ': 'Izual', 'L1': 'Larzuk', 'L2': 'Larzuk', 'MA': 'Malah',
         'XA': 'Anya', 'XR': 'Qual-Kehk', 'NK': 'Nihlathak', 'XB': 'Anya', 'Q1': 'Qual-Kehk'}
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


def monster_anim(art, folder, pal, mid, direction=FRONT):
    """(frames [RGBA, one canvas], x0, y0 of the canvas relative to the feet, fps) or None."""
    p = monster_plan(folder, mid)
    if p is None:
        return None
    tok, wc, parts = p
    base = f'data\\global\\monsters\\{tok}\\'
    for mode in MODES:
        for w in dict.fromkeys((wc, 'hth')):
            try:
                cof = D.COF(R.read(art, f'{base}cof\\{tok}{mode}{w}.cof'))
            except Exception:
                continue
            layers = {}
            for t, transp, _eff, lwc in cof.layers:
                if t >= len(D.LAYERS):
                    continue
                ly = D.LAYERS[t]
                for part in dict.fromkeys((parts.get(t, 'lit'), 'lit')):
                    try:
                        data = R.read(art, f'{base}{ly}\\{tok}{ly}{part}{mode}{lwc or w}.dcc')
                        nd = D.header(data)[0]
                        layers[t] = (D.decode_direction(data, direction % nd if nd else 0), transp)
                        break
                    except Exception:
                        continue
            if not layers:
                continue
            from PIL import Image
            x0 = min(f[0].x0 for f, _ in layers.values())
            y0 = min(f[0].y0 for f, _ in layers.values())
            x1 = max(f[0].x0 + f[0].w for f, _ in layers.values())
            y1 = max(f[0].y0 + f[0].h for f, _ in layers.values())
            imgs = {}
            for t, (frs, transp) in layers.items():
                ims = [f.image(pal) for f in frs]
                if transp:
                    for im in ims:
                        im.putalpha(im.getchannel('A').point(lambda a: a // 2))
                imgs[t] = ims
            cd = direction % (cof.dirs or 1)
            frames = []
            for f in range(max(1, cof.frames)):
                can = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
                for t in cof.draw_order(cd, f):
                    if t in imgs:
                        ims = imgs[t]
                        fr = layers[t][0][f % len(ims)]
                        can.alpha_composite(ims[f % len(ims)], (fr.x0 - x0, fr.y0 - y0))
                frames.append(can)
            fpd, speed = R._animdata(art, folder).get(f'{tok}{mode}{w}'.lower(), (len(frames), 256))
            fps = max(1.0, min(25.0, speed * 25 / 256)) if speed else 12.5
            return frames, x0, y0, fps
    return None


def _anim_cached(art, folder, act, pal, mid):
    k = (getattr(art, 'game_dir', None), folder, act, mid)
    if k not in _ANIM:
        try:
            _ANIM[k] = monster_anim(art, folder, pal, mid)
        except Exception:
            _ANIM[k] = None
    return _ANIM[k]


def _window(art, folder, act, m, size, centre):
    """(vx, vy): world pixel of .base's top-left, as mxl_scene.build places its window."""
    W, H = size
    if centre is None:
        pre, objrows = S._objects(folder)
        for typ, oid, x, y in m.objects:
            i = (act - 1) * 150 + oid
            if typ == 2 and i < len(pre) and pre[i] < len(objrows) and \
                    S._s(objrows[pre[i]][:64]).lower() == 'waypoint':
                wx, wy = S._sub_px(x, y)
                centre = (wx + 40, wy + 24)
                break
        else:
            centre = S._sub_px(m.w * 5 // 2, m.h * 5 // 2)
    return centre[0] - W // 2, centre[1] - H * 3 // 5


def _front_items(art, folder, act, m, flat, pal):
    """The scene's depth-sorted walls / roofs / objects as (depth key, kind, tile or image, wx, wy) - the same keys
    mxl_scene.build sorts by (kind 0/1 tiles, kind 2 object frame 0 as (PIL RGBA, fx, fy))."""
    tiles = {}
    names = ['data' + f.split('\\data', 1)[1].rsplit('.', 1)[0] + '.dt1' for f in m.files if '\\data\\' in f.lower()]
    seen = set()
    for f in names + S.town_files(folder, act)[1]:
        if f.lower() in seen:
            continue
        seen.add(f.lower())
        try:
            for t in S.dt1_tiles(R.read(art, f)):
                tiles.setdefault((t.orient, t.main, t.sub), []).append(t)
        except Exception:
            continue
    out = []
    for cells, orients in m.walls:
        for i, dw in enumerate(cells):
            o = orients[i]
            if o in (0, 10, 11, 13):
                continue
            c = S.cell(dw)
            if c is None:
                continue
            tx, ty = i % m.w, i // m.w
            wx, wy = (tx - ty) * 80, (tx + ty) * 40
            for oo in ((3, 4) if o == 3 else (o,)):
                cands = tiles.get((oo,) + c)
                if not cands:
                    continue
                t = S._pick(cands, tx, ty)
                if oo == 15:
                    out.append((1 << 30, 0, t, wx, wy - t.roof_y))
                elif oo < 16:
                    out.append((wy + 80, 1, t, wx, wy + 80))
    pre, objrows = S._objects(folder)
    for typ, oid, x, y in m.objects:
        i = (act - 1) * 150 + oid
        if typ == 2 and i < len(pre) and pre[i] < len(objrows):
            a = S._object_anim_cached(art, act, pal, objrows[pre[i]])
            if a:
                ox, oy = S._sub_px(x, y)
                out.append((oy, 2, a[0][0], ox, oy))
    return out


def town_npcs(art, data_folder, act, scene, centre=None):
    """The NPC sprites of an act's town for `scene` (an mxl_scene.Scene built with the same centre)."""
    if scene is None:
        return []
    with _LOCK:
        ds1s, _dt1 = S.town_files(data_folder, act)
        if not ds1s:
            return []
        m = S.DS1(R.read(art, ds1s[0]))
        W, H = scene.base.size
        vx, vy = _window(art, data_folder, act, m, (W, H), centre)
        pal = S.act_palette(art, act)
        pr = presets(data_folder, act)
        npcs = []                                       # (world x, y, monstats row, anim)
        for typ, oid, x, y in m.objects:
            if typ != 1 or not 0 <= oid < len(pr) or pr[oid] is None:
                continue
            ox, oy = S._sub_px(x, y)
            if not (vx - 256 < ox < vx + W + 256 and vy - 64 < oy < vy + H + 384):
                continue
            a = _anim_cached(art, data_folder, act, pal, pr[oid])
            if a:
                npcs.append((ox, oy, pr[oid], a))
        if not npcs:
            return []
        flat = S._flat(pal)
        front_all = _front_items(art, data_folder, act, m, flat, pal)
        front_all += [(oy, 3, (a[0][0], a[1], a[2]), ox, oy) for ox, oy, _mid, a in npcs]
        tcache = {}
        out = []
        ms = _rows(data_folder, 'monstats.bin')
        for ox, oy, mid, (frames, fx, fy, fps) in npcs:
            px, py = ox + fx - vx, oy + fy - vy
            fw, fh = frames[0].size
            x0, y0, x1, y1 = max(0, px), max(0, py), min(W, px + fw), min(H, py + fh)
            if x1 <= x0 or y1 <= y0:
                continue
            from PIL import Image
            bx, by = x0 + vx, y0 + vy
            front = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
            for k, kind, t, wx, wy in sorted(front_all, key=lambda d: (d[0], d[1])):
                if (k, kind) <= (oy, 2) or (kind == 3 and (wx, wy) == (ox, oy)):
                    continue                            # behind (or itself); objects at the same depth: behind
                if kind >= 2:
                    im, ix, iy = t
                    S._paste(front, im, wx + ix - bx, wy + iy - by)
                else:
                    tx0, ty0, tx1, ty1 = t.bbox()
                    if wx + tx1 <= bx or wx + tx0 >= bx + front.width or wy + ty1 <= by or wy + ty0 >= by + front.height:
                        continue
                    got = tcache.get(id(t))
                    if got is None:
                        got = tcache[id(t)] = S._tile_image(t, flat)
                    im, ix, iy = got
                    S._paste(front, im, wx + ix - bx, wy + iy - by)
            fr = []
            for im in frames:
                f = im.crop((x0 - px, y0 - py, x1 - px, y1 - py))
                f.alpha_composite(front)
                fr.append(f)
            tok = S._s(ms[mid][0x10:0x14])
            out.append({'pos': (x0, y0), 'frames': fr, 'fps': fps, 'token': tok, 'monstats': mid,
                        'name': NAMES.get(tok.upper(), tok)})
        return out


def add_npcs(scene, art, data_folder, act, centre=None):
    """scene.sprites followed by the NPCs (a new list; the scene is not changed)."""
    if scene is None:
        return []
    return list(scene.sprites) + town_npcs(art, data_folder, act, scene, centre)
