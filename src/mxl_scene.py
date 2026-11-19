"""The town of an act as the game draws it, for a backdrop behind the animated character: floor, wall and roof tiles
(DT1) laid out by the town's preset map (DS1), plus the map's objects (torches, fires, waypoint, stash...) from their
DCC animations. Read from the player's MPQs through mxl_d2look_art / mxl_char_render (raw member cache), decoded here.
Pure Python + PIL Image methods.

    sc = scene(art, data_folder, act, size=(w, h), centre=None)
    sc.base      PIL RGB image: the tiles and the still objects (no animated ones)
    sc.sprites   [{'pos': (x, y), 'frames': [PIL RGBA], 'fps': float}]  the animated objects, to paste on .base at
                 pos (top-left; always inside .base): frames are cut to the window and already carry whatever stands
                 in front of the object (walls, roofs), so pasting them in any order is right
    sc.composite(i)  .base with frame i of every sprite
scene() builds under a lock and takes 2-10 s on a cold art cache: call it from a worker thread.
    sc.anchor    (x, y) pixel of .base where the character's feet go

Formats (community documentation: Paul Siramy's DS1 / DT1 notes, OpenDiablo2's d2ds1 / d2dt1):
- DS1: version, width-1, height-1, [act], [substitution type], [DT1 file list], layer counts, then width*height u32
  cells per layer (walls + orientations interleaved, floors, shadow, substitution), then the object list
  (type, id, x, y[, flags]) in sub-tiles (5 per tile).
- DT1: tiles of 'blocks' (32 x 32 RLE or 32 x 15 isometric floor diamonds); a floor tile is a 160 x 80 diamond, a
  wall tile hangs from the bottom of its cell.
Tables: lvlprest.bin (432-byte rows: level id @4, six 60-byte DS1 names @68), lvltypes.bin (32 x 60-byte DT1 names),
objpreset.bin (u32 objects.bin row per act * 150 + preset id), objects.bin (448-byte rows).
Not done: lighting, the light radius, tile animation (water), object overlays / missiles, NPCs and monsters
(DS1 type 1), the wilderness around Act 1's camp (the game generates it)."""
import os
import struct
import threading

import mxl_char_render as R
import mxl_dcc as D

# act -> (town level id, level type)
TOWNS = {1: (1, 1), 2: (40, 12), 3: (75, 20), 4: (103, 26), 5: (109, 29)}
MODES = ('NU', 'OP', 'ON', 'S1', 'S2', 'S3', 'S4', 'S5')
_LOCK = threading.Lock()
_CACHE = {}


def _s(b):
    return b.split(b'\0')[0].decode('latin-1').strip()


# ---------------------------------------------------------------- DS1
class DS1:
    """Parsed map: .w, .h (tiles), .walls [(cells, orients)], .floors [cells], .shadow cells, .objects."""

    def __init__(self, data):
        u = struct.unpack_from
        p = 0

        def i32():
            nonlocal p
            v = u('<i', data, p)[0]
            p += 4
            return v
        self.version = v = i32()
        self.w = i32() + 1
        self.h = i32() + 1
        self.act = min(i32(), 5) if v >= 8 else 0
        self.tag_type = i32() if v >= 10 else 0
        self.files = []
        if v >= 3:
            for _ in range(i32()):
                e = data.index(b'\0', p)
                self.files.append(data[p:e].decode('latin-1'))
                p = e + 1
        if 9 <= v <= 13:
            p += 8
        n = self.w * self.h
        if v >= 4:
            nw = i32()
            nf = i32() if v >= 16 else 1
            order = []
            for i in range(nw):
                order += [('w', i), ('o', i)]
            order += [('f', i) for i in range(nf)] + [('s', 0)]
            if self.tag_type in (1, 2):
                order.append(('t', 0))
        else:
            nw, nf = 1, 1
            order = [('w', 0), ('f', 0), ('o', 0), ('t', 0), ('s', 0)]
        walls = [None] * nw
        orients = [None] * nw
        self.floors = [None] * nf
        self.shadow = None
        for kind, i in order:
            cells = u(f'<{n}I', data, p)
            p += 4 * n
            if kind == 'w':
                walls[i] = cells
            elif kind == 'o':
                orients[i] = [c & 0xFF if v >= 7 else _DIR_LOOKUP[c & 0xFF] if (c & 0xFF) < 25 else 0 for c in cells]
            elif kind == 'f':
                self.floors[i] = cells
            elif kind == 's':
                self.shadow = cells
        self.walls = list(zip(walls, orients))
        self.objects = []                         # (type, id, x, y) in sub-tiles
        if v >= 2 and p + 4 <= len(data):
            for _ in range(i32()):
                t, oid, x, y = u('<4i', data, p)
                p += 16 + (4 if v > 5 else 0)
                self.objects.append((t, oid, x, y))


_DIR_LOOKUP = (0x00, 0x01, 0x02, 0x01, 0x02, 0x03, 0x03, 0x05, 0x05, 0x06, 0x06, 0x07, 0x07, 0x08, 0x09, 0x0A,
               0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x14)


def cell(dw):
    """DS1 wall / floor cell -> (main index, sub index) or None (empty or hidden)."""
    if not dw & 0xFF or dw & 0x80000000:
        return None
    return (dw >> 20) & 0x3F, (dw >> 8) & 0x3F


# ---------------------------------------------------------------- DT1
_XJUMP = (14, 12, 10, 8, 6, 4, 2, 0, 2, 4, 6, 8, 10, 12, 14)
_NPIX = (4, 8, 12, 16, 20, 24, 28, 32, 28, 24, 20, 16, 12, 8, 4)


class Tile:
    __slots__ = ('orient', 'main', 'sub', 'rarity', 'roof_y', 'h', 'w', 'blocks', 'data', 'box', 'anim')

    def bbox(self):
        """(x0, y0, x1, y1) of the blocks in tile coordinates."""
        if self.box is None:
            xs = [b[0] for b in self.blocks] or [0]
            ys = [b[1] for b in self.blocks] or [0]
            self.box = (min(xs), min(ys), max(xs) + 32, max(ys) + 32)
        return self.box

    def pixels(self):
        """(width, height, palette indices bytearray (0 = transparent), x0, y0)."""
        x0, y0, x1, y1 = self.bbox()
        W, H = x1 - x0, y1 - y0
        out = bytearray(W * H)
        d = self.data
        for bx, by, fmt, ln, ptr in self.blocks:
            bx -= x0
            by -= y0
            if fmt == 1:                                          # isometric floor diamond 32 x 15
                q = ptr
                for y in range(15):
                    n = _NPIX[y]
                    o = (by + y) * W + bx + _XJUMP[y]
                    out[o:o + n] = d[q:q + n]
                    q += n
            else:                                                 # RLE: (skip, count) pairs, (0, 0) = new row
                q, end = ptr, ptr + ln
                x = y = 0
                while q + 1 < end:
                    a, b = d[q], d[q + 1]
                    q += 2
                    if a or b:
                        x += a
                        o = (by + y) * W + bx + x
                        out[o:o + b] = d[q:q + b]
                        q += b
                        x += b
                    else:
                        x = 0
                        y += 1
        return W, H, out, x0, y0


def dt1_tiles(data):
    """DT1 bytes -> list of Tile (pixels decoded on demand)."""
    u = struct.unpack_from
    n, hp = u('<ii', data, 268)
    out = []
    for i in range(n):
        p = hp + i * 96
        t = Tile()
        t.roof_y = u('<h', data, p + 4)[0]
        t.anim = data[p + 7]
        t.h, t.w = u('<ii', data, p + 8)
        t.orient, t.main, t.sub, t.rarity = u('<iiii', data, p + 20)
        bp, _blen, nb = u('<iii', data, p + 72)
        t.blocks = []
        for k in range(nb):
            x, y, _z, _gx, _gy, fmt, ln, _z2, ptr = u('<hhhBBhihi', data, bp + k * 20)
            t.blocks.append((x, y, fmt, ln, bp + ptr))
        t.data = data
        t.box = None
        out.append(t)
    return out


# ---------------------------------------------------------------- tables
def _table(folder, name):
    try:
        d = open(os.path.join(folder, name), 'rb').read()
        n = struct.unpack_from('<I', d, 0)[0]
        rs = (len(d) - 4) // n if n else 0
    except (OSError, struct.error, ZeroDivisionError):
        return []
    return [d[4 + i * rs:4 + (i + 1) * rs] for i in range(n)]


def town_files(folder, act):
    """(DS1 names, DT1 names) of an act's town, from lvlprest.bin / lvltypes.bin (game paths, '\\' separators)."""
    lid, ltype = TOWNS[act]
    ds1 = []
    for r in _table(folder, 'lvlprest.bin'):
        if len(r) >= 428 and struct.unpack_from('<I', r, 4)[0] == lid:
            ds1 = [_s(r[68 + 60 * k:128 + 60 * k]) for k in range(6)]
            ds1 = [f for f in ds1 if f and f != '0']
            break
    dt1 = []
    rows = _table(folder, 'lvltypes.bin')
    if ltype < len(rows):
        r = rows[ltype]
        dt1 = [_s(r[60 * k:60 * k + 60]) for k in range(32)]
        dt1 = [f for f in dt1 if f and f != '0' and f.lower().endswith('.dt1')]
    fix = lambda f: 'data\\global\\tiles\\' + f.replace('/', '\\')
    return [fix(f) for f in ds1], [fix(f) for f in dt1]


def _objects(folder):
    """(objpreset list, {objects.bin row: row bytes})."""
    pre = b''.join(_table(folder, 'objpreset.bin'))
    pre = struct.unpack(f'<{len(pre) // 4}I', pre) if pre else ()
    return pre, _table(folder, 'objects.bin')


# ---------------------------------------------------------------- objects
def object_anim(art, pal, row):
    """An objects.bin row -> (frames [(PIL RGBA, x0, y0)], fps) or None. The mode: an animated (CycleAnim) one,
    'ON' first (a lit waypoint), else the neutral one."""
    tok = _s(row[0xC0:0xC3])
    if not tok:
        return None
    fc = struct.unpack_from('<8I', row, 0xD8)
    fd = struct.unpack_from('<8H', row, 0xF8)
    cyc = row[0x108:0x110]
    have = row[0x13F:0x147]
    cand = [m for m in (2, 0, 1) if have[m] and cyc[m] and fc[m] > 1] + [m for m in (0, 2, 1) if have[m]]
    base = f'data\\global\\objects\\{tok}\\'
    for m in dict.fromkeys(cand):
        mode = MODES[m]
        try:
            cof = D.COF(R.read(art, f'{base}cof\\{tok}{mode}hth.cof'))
        except Exception:
            continue
        layers = {}
        for t, transp, eff, wc in cof.layers:
            ly = D.LAYERS[t] if t < len(D.LAYERS) else None
            if ly is None:
                continue
            try:
                data = R.read(art, f'{base}{ly}\\{tok}{ly}lit{mode}{wc or "hth"}.dcc')
                layers[t] = (D.decode_direction(data, 0), transp)
            except Exception:
                continue
        if not layers:
            continue
        nfr = max(1, cof.frames)
        x0 = min(f[0].x0 for f, _ in layers.values())
        y0 = min(f[0].y0 for f, _ in layers.values())
        x1 = max(f[0].x0 + f[0].w for f, _ in layers.values())
        y1 = max(f[0].y0 + f[0].h for f, _ in layers.values())
        from PIL import Image
        imgs = {}
        for t, (frs, transp) in layers.items():
            ims = [f.image(pal) for f in frs]
            if transp:                                            # blended layers (glow): half opacity
                for im in ims:
                    im.putalpha(im.getchannel('A').point(lambda a: a // 2))
            imgs[t] = ims
        frames = []
        for f in range(nfr):
            can = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
            for t in cof.draw_order(0, f):
                if t in imgs:
                    ims = imgs[t]
                    fr = layers[t][0][f % len(ims)]
                    can.alpha_composite(ims[f % len(ims)], (fr.x0 - x0, fr.y0 - y0))
            frames.append(can)
        delta = fd[m] or 256
        fps = max(1.0, min(25.0, delta * 25 / 256))
        return [(im, x0, y0) for im in frames], fps
    return None


# ---------------------------------------------------------------- scene
class Scene:
    __slots__ = ('base', 'sprites', 'anchor', 'act')

    def __init__(self, base, sprites, anchor, act):
        self.base, self.sprites, self.anchor, self.act = base, sprites, anchor, act

    def composite(self, i=0):
        """.base with frame i of every animated object (RGB)."""
        im = self.base.convert('RGBA')
        for s in self.sprites:
            im.alpha_composite(s['frames'][i % len(s['frames'])], s['pos'])
        return im.convert('RGB')


def act_palette(art, act):
    """256 (r, g, b) of data\\global\\palette\\act<N>\\pal.dat, with the editor's in-game brightness curve."""
    try:
        d = R.read(art, f'data\\global\\palette\\act{act}\\pal.dat')
    except Exception:
        d = R.read(art, 'data\\global\\palette\\act1\\pal.dat')
    lut = art._lut
    return [(lut[d[i * 3 + 2]], lut[d[i * 3 + 1]], lut[d[i * 3]]) for i in range(256)]


def _flat(pal):
    out = []
    for c in pal:
        out.extend(c)
    return out


def _tile_image(t, flat, shadow=False):
    from PIL import Image
    W, H, px, x0, y0 = t.pixels()
    if shadow:                                   # shadow tiles darken what is below them
        m = Image.frombytes('L', (W, H), bytes(px)).point(lambda v: 110 if v else 0)
        im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        im.putalpha(m)
        return im, x0, y0
    im = Image.frombytes('P', (W, H), bytes(px))
    im.putpalette(flat)
    im.info['transparency'] = 0
    return im.convert('RGBA'), x0, y0


def _pick(cands, tx, ty):
    """One of the tile variants of a cell: rarity-weighted, stable per cell."""
    if len(cands) == 1:
        return cands[0]
    tot = sum(max(0, t.rarity) for t in cands)
    if tot <= 0:
        return cands[0]
    r = (tx * 7919 + ty * 104729) % tot
    for t in cands:
        r -= max(0, t.rarity)
        if r < 0:
            return t
    return cands[0]


def _sub_px(x, y):
    """DS1 sub-tile -> world pixel (tile (0, 0)'s box top-left = (0, 0); its top vertex at (80, 0))."""
    return (x - y) * 16 + 80, (x + y) * 8


def build(art, folder, act, size=(512, 384), centre=None):
    """The Scene of an act's town (see the module doc); centre = world pixel to centre on (None: the waypoint)."""
    from PIL import Image
    W, H = size
    ds1s, dt1s = town_files(folder, act)
    if not ds1s:
        return None
    m = DS1(R.read(art, ds1s[0]))
    names = ['data' + f.split('\\data', 1)[1].rsplit('.', 1)[0] + '.dt1' for f in m.files if '\\data\\' in f.lower()
             or '\\data\\' in f]
    tiles = {}
    seen = set()
    for f in names + dt1s:
        if f.lower() in seen:
            continue
        seen.add(f.lower())
        try:
            for t in dt1_tiles(R.read(art, f)):
                tiles.setdefault((t.orient, t.main, t.sub), []).append(t)
        except Exception:
            continue
    pal = act_palette(art, act)
    flat = _flat(pal)
    pre, objrows = _objects(folder)
    # objects of the map: (world x, y, objects.bin row)
    objs = []
    for typ, oid, x, y in m.objects:
        if typ != 2:
            continue
        i = (act - 1) * 150 + oid
        row = objrows[pre[i]] if i < len(pre) and pre[i] < len(objrows) else None
        if row is not None:
            objs.append(_sub_px(x, y) + (row,))
    if centre is None:
        wp = [o for o in objs if _s(o[2][:64]).lower() == 'waypoint']
        if wp:
            centre = (wp[0][0] + 40, wp[0][1] + 24)
        else:
            centre = _sub_px(m.w * 5 // 2, m.h * 5 // 2)
    anchor_w = centre
    vx, vy = centre[0] - W // 2, centre[1] - H * 3 // 5          # window: the anchor a bit below the middle
    img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    cache = {}

    def put(t, wx, wy, shadow=False, dst=None, box=None):
        """Draw tile t at world (wx, wy) into the window (or into dst, whose window box is (x0, y0, x1, y1))."""
        bx0, by0, bx1, by1 = box or (vx, vy, vx + W, vy + H)
        x0, y0, x1, y1 = t.bbox()
        if wx + x1 <= bx0 or wx + x0 >= bx1 or wy + y1 <= by0 or wy + y0 >= by1:
            return
        k = (id(t), shadow)
        got = cache.get(k)
        if got is None:
            got = cache[k] = _tile_image(t, flat, shadow)
        im, ox, oy = got
        _paste(img if dst is None else dst, im, wx + ox - bx0, wy + oy - by0)

    def tile_of(orient, dw, tx, ty):
        c = cell(dw)
        if c is None:
            return None
        cands = tiles.get((orient,) + c)
        return _pick(cands, tx, ty) if cands else None

    # floors, then shadows
    for layer in m.floors:
        for i, dw in enumerate(layer):
            tx, ty = i % m.w, i // m.w
            t = tile_of(0, dw, tx, ty)
            if t:
                put(t, (tx - ty) * 80, (tx + ty) * 40)
    if m.shadow:
        for i, dw in enumerate(m.shadow):
            tx, ty = i % m.w, i // m.w
            t = tile_of(13, dw, tx, ty)
            if t:
                put(t, (tx - ty) * 80, (tx + ty) * 40, True)
    # walls, roofs and objects in depth order (world y of the base line)
    draw = []
    for cells, orients in m.walls:
        for i, dw in enumerate(cells):
            o = orients[i]
            if o in (0, 10, 11, 13):
                continue
            tx, ty = i % m.w, i // m.w
            wx, wy = (tx - ty) * 80, (tx + ty) * 40
            for oo in ((3, 4) if o == 3 else (o,)):
                t = tile_of(oo, dw, tx, ty)
                if t is None:
                    continue
                if oo == 15:                                       # roof: lifted by its height, drawn last
                    draw.append((1 << 30, 0, t, wx, wy - t.roof_y))
                elif oo >= 16:                                     # lower walls: below the floor line
                    draw.append((wy - 1, 0, t, wx, wy))
                else:
                    draw.append((wy + 80, 1, t, wx, wy + 80))
    sprites = []
    for ox, oy, row in objs:
        if not (vx - 256 < ox < vx + W + 256 and vy - 64 < oy < vy + H + 384):
            continue
        a = _object_anim_cached(art, act, pal, row)
        if a is None:
            continue
        draw.append((oy, 2, a, ox, oy))
    draw.sort(key=lambda d: (d[0], d[1]))
    anim = []                                    # (index in draw, window box) of the animated objects
    for n, (_k, kind, t, wx, wy) in enumerate(draw):
        if kind == 2:
            frames, fps = t
            im, fx, fy = frames[0]
            px, py = wx + fx - vx, wy + fy - vy
            if px + im.width <= 0 or py + im.height <= 0 or px >= W or py >= H:
                continue
            if len(frames) > 1:                  # animated: kept out of .base, drawn by the UI
                anim.append((n, (max(0, px), max(0, py), min(W, px + im.width), min(H, py + im.height)),
                             (px, py), frames, fps))
            else:
                _paste(img, im, px, py)
        else:
            put(t, wx, wy)
    # each animated object: its frames cut to the window, with what is drawn in front of it (walls, roofs, objects
    # standing lower) laid over them, so the UI only has to paste the frames on .base
    for n, (x0, y0, x1, y1), (px, py), frames, fps in anim:
        box = (x0 + vx, y0 + vy, x1 + vx, y1 + vy)
        front = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
        for _k, kind, t, wx, wy in draw[n + 1:]:
            if kind == 2:
                im, fx, fy = t[0][0]
                _paste(front, im, wx + fx - box[0], wy + fy - box[1])
            else:
                put(t, wx, wy, dst=front, box=box)
        out = []
        for im, _fx, _fy in frames:
            f = im.crop((x0 - px, y0 - py, x1 - px, y1 - py))
            f.alpha_composite(front)
            out.append(f)
        sprites.append({'pos': (x0, y0), 'frames': out, 'fps': fps})
    return Scene(img.convert('RGB'), sprites, (anchor_w[0] - vx, anchor_w[1] - vy), act)


def _paste(img, im, x, y):
    """alpha_composite at any (also negative) position."""
    if x < 0 or y < 0:
        cx, cy = max(0, -x), max(0, -y)
        if cx >= im.width or cy >= im.height:
            return
        im = im.crop((cx, cy, im.width, im.height))
        x, y = x + cx, y + cy
    if x >= img.width or y >= img.height:
        return
    img.alpha_composite(im, (x, y))


_OBJ = {}


def _object_anim_cached(art, act, pal, row):
    k = (id(art), act, bytes(row[:0xC4]))
    if k not in _OBJ:
        try:
            _OBJ[k] = object_anim(art, pal, row)
        except Exception:
            _OBJ[k] = None
    return _OBJ[k]


def scene(art, data_folder, act, size=(512, 384), centre=None):
    """Cached per (act, size, centre); None when the town's files are missing."""
    k = (getattr(art, 'game_dir', None), data_folder, act, tuple(size), centre)
    with _LOCK:
        if k not in _CACHE:
            try:
                _CACHE[k] = build(art, data_folder, act, size, centre)
            except Exception:
                import logging
                logging.getLogger('mxl_scene').exception('town scene of act %s', act)
                _CACHE[k] = None
        return _CACHE[k]
