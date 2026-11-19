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
Drawing: like the game, in palette indices: tiles and opaque COF layers are copied, a COF layer with its
transparent flag set is drawn with its draw-effect byte as the draw mode through the act's pal.pl2 tables against
what is already on screen (0/1/2 = 25/50/75 %, 3 additive - fires, waypoint flames -, 4 multiply, 6 max-channel
alpha); shadow tiles take the floor down SHADOW_LEVEL light levels. The indices are coloured with the act palette.
Lighting: AMBIENT darkness, the character's (white) light radius around .anchor, pools around objects with a
Lit0-7 radius in their objects.txt Red / Green / Blue colour, baked into .base and the sprite frames (.light = the
intensity map, .light_rgb = the coloured one). Scene.window / .index / .items / .front() / .lit() let other
modules (mxl_npcs) draw sprites into the same window.
Not done: flicker, tile animation (water), object overlays / missiles, monsters, the wilderness around Act 1's
camp (the game generates it), the light-level (shadow table) rendering of the software renderer (lights are an RGB
multiply here)."""
import collections
import os
import struct
import threading

import mxl_char_render as R
import mxl_dcc as D

# act -> (town level id, level type)
TOWNS = {1: (1, 1), 2: (40, 12), 3: (75, 20), 4: (103, 26), 5: (109, 29)}
MODES = ('NU', 'OP', 'ON', 'S1', 'S2', 'S3', 'S4', 'S5')
_LOCK = threading.Lock()
_CACHE = collections.OrderedDict()      # (game dir, folder, act, size, centre) -> Scene, least recently used first
CACHE_SIZE = 6


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


# ---------------------------------------------------------------- draw modes (pal.pl2)
# COF layer draw mode: the draw-effect byte when the layer's transparent flag is set, else 5 (opaque copy).
# pal.pl2 blend tables (256 x 256, row = the palette index already on screen, column = the sprite's index) per mode:
# 0 25 % sprite, 1 50 %, 2 75 %, 3 additive, 4 multiply, 6 alpha = brightest channel; 5 / 7 plain copy.
# Offsets / modes after D2-Development-Kit (MIT) d2bt/gfx/palette.py and cof.py (D2MOO D2PL2FileStrc, D2DDraw).
NORMAL = 5
_PL2_OFF = {0: 0x23500, 1: 0x13500, 2: 0x3500, 3: 0x33500, 4: 0x43500, 6: 0x5B500}
_PL2_LIGHT = 0x400          # 32 light-level rows of 256 (row 31 = unchanged)
SHADOW_LEVEL = 17           # light level of the floor under a shadow tile (~57 % brightness)
_PL2C = {}


def draw_mode(transparent, effect):
    return effect if transparent else NORMAL


def pl2_tables(art, act):
    """{draw mode: 256 rows (bytes) of result indices, 'light': 32 rows} of act<N>\\pal.pl2; {} when missing."""
    k = (getattr(art, 'game_dir', None), act)
    if k not in _PL2C:
        out = {}
        for a in (act, 1):
            try:
                d = R.read(art, f'data\\global\\palette\\act{a}\\pal.pl2')
            except Exception:
                continue
            if len(d) < 0x5B500 + 65536:
                continue
            for mode, off in _PL2_OFF.items():
                out[mode] = [d[off + 256 * r:off + 256 * r + 256] for r in range(256)]
            out['light'] = [d[_PL2_LIGHT + 256 * r:_PL2_LIGHT + 256 * r + 256] for r in range(32)]
            break
        _PL2C[k] = out
    return _PL2C[k]


def blend(cb, W, H, layers, tables, dm=None, sm=None):
    """Draw layers [(index bytes, w, h, x, y, mode)] into the palette-index canvas cb (bytearray W*H) as the game
    does: opaque copy, or tables[mode][screen][sprite] for blended modes; index 0 of a layer is transparent.
    dm (bytearray W*H): set where a layer drew, 255 by an opaque layer, draw mode + 1 by a blended one;
    sm (bytearray W*H): the sprite index of that last layer."""
    for px, w, h, x, y, mode in layers:
        T = tables.get(mode) if mode != NORMAL else None
        xa, xb = max(0, -x), min(w, W - x)
        if xa >= xb:
            continue
        for yy in range(max(0, -y), min(h, H - y)):
            r = yy * w
            o0 = (y + yy) * W + x
            for xx in range(xa, xb):
                s = px[r + xx]
                if s:
                    o = o0 + xx
                    cb[o] = T[cb[o]][s] if T is not None else s
                    if dm is not None:
                        dm[o] = mode + 1 if T is not None else 255
                        sm[o] = s


def compose(bg, layers, tables):
    """bg: 'L' palette-index image (what is on screen under the sprite); -> ('L' indices, 'L' mask of the drawn
    pixels, blend info ('L' draw mode + 1 where a blended layer drew
    last, else 0; 'L' that layer's sprite index) for Scene.lit."""
    from PIL import Image
    W, H = bg.size
    cb = bytearray(bg.tobytes())
    dm = bytearray(W * H)
    sm = bytearray(W * H)
    blend(cb, W, H, layers, tables, dm, sm)
    dm = Image.frombytes('L', (W, H), bytes(dm))
    return Image.frombytes('L', (W, H), bytes(cb)), dm.point(lambda v: 255 if v else 0), \
        (dm.point(lambda v: 0 if v == 255 else v), Image.frombytes('L', (W, H), bytes(sm)))


def layers_rgba(layers, size, pal):
    """The layers over NOTHING (no screen pixel to blend with): RGBA, blended layers approximated with an opacity
    (25 / 50 / 75 %; additive / max-channel: opacity = brightness; multiply: darkening)."""
    from PIL import Image
    can = Image.new('RGBA', size, (0, 0, 0, 0))
    flat = _flat(pal)
    for px, w, h, x, y, mode in layers:
        im = Image.frombytes('P', (w, h), bytes(px))
        im.putpalette(flat)
        im.info['transparency'] = 0
        im = im.convert('RGBA')
        if mode in (3, 6):
            _glow(im)
        elif mode in (0, 1, 2):
            a = (64, 128, 191)[mode]
            im.putalpha(im.getchannel('A').point(lambda v: v * a // 255))
        elif mode == 4:
            lum = im.convert('L').point(lambda v: 255 - v)
            dark = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            dark.putalpha(Image.composite(lum, Image.new('L', (w, h), 0), im.getchannel('A')))
            im = dark
        _paste(can, im, x, y)
    return can


def to_rgba(idx, mask, pal):
    """'L' palette indices + 'L' mask -> RGBA with the palette's colours."""
    from PIL import Image
    p = Image.frombytes('P', idx.size, idx.tobytes())
    p.putpalette(_flat(pal))
    im = p.convert('RGBA')
    if mask is not None:
        im.putalpha(mask)
    return im


# ---------------------------------------------------------------- objects
def object_layers(art, row):
    """An objects.bin row -> (frames, box, fps) or None: frames[f] = [(index bytes, w, h, x, y, draw mode)] in draw
    order, x / y relative to box's top-left; box = (x0, y0, x1, y1) around the object's pivot. The mode: an animated
    (CycleAnim) one, 'ON' first (a lit waypoint), else the neutral one."""
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
                layers[t] = (D.decode_direction(data, 0), draw_mode(transp, eff))
            except Exception:
                continue
        if not layers:
            continue
        box = _union(layers)
        frames = [_frame_layers(cof, 0, f, layers, box) for f in range(max(1, cof.frames))]
        delta = fd[m] or 256
        fps = max(1.0, min(25.0, delta * 25 / 256))
        return frames, box, fps
    return None


def _union(layers):
    fs = [f for frs, _m in layers.values() for f in frs if f.w and f.h] or [layers[next(iter(layers))][0][0]]
    return (min(f.x0 for f in fs), min(f.y0 for f in fs), max(f.x0 + f.w for f in fs), max(f.y0 + f.h for f in fs))


def _frame_layers(cof, d, f, layers, box, remap=None):
    """One frame of a COF as [(index bytes, w, h, x, y, mode)] in draw order (remap: 256-byte palette shift)."""
    out = []
    for t in cof.draw_order(d, f):
        if t not in layers:
            continue
        frs, mode = layers[t]
        fr = frs[f % len(frs)]
        if not (fr.w and fr.h):
            continue
        px = bytes(fr.pixels)
        if remap:
            px = px.translate(remap)
        out.append((px, fr.w, fr.h, fr.x0 - box[0], fr.y0 - box[1], mode))
    return out


def object_anim(art, pal, row):
    """An objects.bin row -> (frames [(PIL RGBA, x0, y0)], fps) or None, drawn over nothing (see layers_rgba;
    the scene itself blends them with the game's tables)."""
    got = object_layers(art, row)
    if got is None:
        return None
    frames, (x0, y0, x1, y1), fps = got
    return [(layers_rgba(fl, (x1 - x0, y1 - y0), pal), x0, y0) for fl in frames], fps


def _glow(im):
    """A blended (Trans / additive) layer over nothing, in place: opacity = brightness, so black adds nothing and
    the bright flame core covers fully."""
    from PIL import Image
    a = im.getchannel('A')
    lum = im.convert('RGB').point(lambda v: min(255, v * 3 // 2)).convert('L')
    im.putalpha(Image.composite(lum, Image.new('L', im.size, 0), a))


def object_light(row):
    """Light radius (objects.txt Lit0-7, the largest; 0 = none) of an objects.bin row."""
    return max(row[0x110:0x118])


def object_light_rgb(row):
    """Light colour (objects.txt Red, Green, Blue @ 356..358) of an objects.bin row."""
    return tuple(row[356:359]) if len(row) >= 359 else (255, 255, 255)


AMBIENT = 96            # darkness of the town away from any light (0 black .. 255 unlit)
CHAR_LIGHT = 0.42       # the character's light radius, as a share of the window width


def _pool(rx, strength=255):
    """RGBA white with a soft round falloff, rx wide, flattened to the isometric ground (half as high)."""
    from PIL import Image
    g = Image.radial_gradient('L').point(lambda v: max(0, 255 - v * 2) * strength // 255 if v < 128 else 0)
    w = max(2, int(rx * 2))
    h = max(2, w // 2)
    im = Image.new('RGBA', (w, h), (255, 255, 255, 0))
    im.putalpha(g.resize((w, h)))
    return im


def light_map(size, anchor, lights, channel=None):
    """'L' light image: AMBIENT away from lights, up to 255 in the character's (white) light around anchor and in
    the pools of lights [(x, y, radius px[, (r, g, b)])]; pools add up like light (screen). channel 0/1/2: that
    colour channel of the light (pools scaled by their colour), None: the intensity."""
    from PIL import Image
    W, H = size
    acc = Image.new('RGBA', size, (255, 255, 255, 0))
    rx = W * CHAR_LIGHT
    _paste(acc, _pool(rx), int(anchor[0] - rx), int(anchor[1] - rx / 2))
    for li in lights:
        x, y, r = li[:3]
        s = 230
        if channel is not None and len(li) > 3:
            s = s * li[3][channel] // 255
        if s > 0:
            _paste(acc, _pool(r, s), int(x - r), int(y - r / 2))
    amb = AMBIENT
    return acc.getchannel('A').point(lambda a: amb + (255 - amb) * a // 255)


def _lit(im, lm):
    """im (RGB / RGBA) multiplied by the light map lm (same size; 'L' grey or 'RGB' coloured light)."""
    from PIL import Image
    rgb = im.convert('RGB')
    black = Image.new('L', im.size, 0)
    if lm.mode == 'L':
        out = Image.composite(rgb, Image.new('RGB', im.size, (0, 0, 0)), lm)
    else:
        out = Image.merge('RGB', [Image.composite(c, black, l) for c, l in zip(rgb.split(), lm.split())])
    if im.mode == 'RGBA':
        out = out.convert('RGBA')
        out.putalpha(im.getchannel('A'))
    return out


# ---------------------------------------------------------------- scene
class Scene:
    """See the module doc. Also, for sprites made elsewhere (mxl_npcs):
    .window   (vx, vy) world pixel of .base's top-left
    .index    'L' palette indices of the unlit window (tiles + still objects; what blended layers blend with)
    .pal      the 256 (r, g, b) of .index;  .tables  the pl2 draw-mode tables (pl2_tables)
    .items    depth-sorted [(key, kind, 'L' indices, 'L' mask, x, y)] of the walls / roofs / objects drawn after
              the floor (window coordinates; kind 0 lower wall / roof, 1 wall, 2 object)
    .front(box, depth, kind)  what is drawn in front of a sprite standing at world y = depth
    .lit(im, pos)  im lit like .base at window position pos."""
    __slots__ = ('base', 'sprites', 'anchor', 'act', 'light', 'light_rgb', 'window', 'index', 'pal', 'tables',
                 'items')

    def __init__(self, base, sprites, anchor, act, light=None, light_rgb=None, window=(0, 0), index=None,
                 pal=None, tables=None, items=()):
        self.base, self.sprites, self.anchor, self.act = base, sprites, anchor, act
        self.light = light          # the 'L' light map baked into .base and the sprites (None: unlit)
        self.light_rgb = light_rgb  # its colours ('RGB'; the object lights' Red / Green / Blue)
        self.window, self.index, self.pal, self.tables, self.items = window, index, pal, tables or {}, list(items)

    def composite(self, i=0):
        """.base with frame i of every animated object (RGB)."""
        im = self.base.convert('RGBA')
        for s in self.sprites:
            im.alpha_composite(s['frames'][i % len(s['frames'])], s['pos'])
        return im.convert('RGB')

    def front(self, box, depth, kind=2):
        """('L' indices, 'L' mask) of box (window x0, y0, x1, y1): the items drawn after (depth, kind) - walls,
        roofs and objects standing lower than world y = depth (objects at the same depth count as behind)."""
        from PIL import Image
        x0, y0, x1, y1 = box
        idx = Image.new('L', (x1 - x0, y1 - y0), 0)
        msk = Image.new('L', idx.size, 0)
        for k, kd, im, m, x, y in self.items:
            if (k, kd) <= (depth, kind) or x >= x1 or y >= y1 or x + im.width <= x0 or y + im.height <= y0:
                continue
            idx.paste(im, (x - x0, y - y0), m)
            msk.paste(255, (x - x0, y - y0), m)
        return idx, msk

    def lit(self, im, pos, info=None):
        """im (RGBA) at window pos lit like .base (the light map crop; outside the window: ambient). info: the
        blend info of compose() (cut like im): pixels drawn last by a blended layer are blended again in RGB over
        the LIT scene with their draw mode (additive: lit screen + sprite colour), so a flame or fog glows instead
        of being darkened like the ground under it."""
        from PIL import Image
        lm = self.light_rgb or self.light
        if lm is None:
            return im
        x, y = pos
        w, h = im.size
        amb = Image.new(lm.mode, (w, h), AMBIENT if lm.mode == 'L' else (AMBIENT,) * 3)
        c = (max(0, x), max(0, y), min(lm.width, x + w), min(lm.height, y + h))
        if c[0] < c[2] and c[1] < c[3]:
            amb.paste(lm.crop(c), (c[0] - x, c[1] - y))
        out = _lit(im, amb)
        if info is None or self.base is None or not info[0].getbbox():
            return out
        pal = self.pal
        W, H = self.base.size
        modes, srcs = info[0].tobytes(), info[1].tobytes()
        under = self.base.crop((x, y, x + w, y + h)).tobytes()
        px = out.load()
        for o, v in enumerate(modes):
            if not v:
                continue
            i, j = divmod(o, w)
            if not (0 <= x + j < W and 0 <= y + i < H):
                continue
            px[j, i] = _rgb_blend(v - 1, under[3 * o:3 * o + 3], pal[srcs[o]]) + (px[j, i][3],)
        return out


def _rgb_blend(mode, d, s):
    """Screen colour d, sprite colour s, draw mode -> (r, g, b) (the pl2 tables' formulas, in RGB)."""
    if mode == 3:
        return tuple(min(255, a + b) for a, b in zip(d, s))
    if mode == 4:
        return tuple(a * b // 255 for a, b in zip(d, s))
    k = {0: 64, 1: 128, 2: 191}.get(mode)
    if k is None:                                           # 6: opacity = the brightest channel
        k = max(s)
    return tuple((b * k + a * (255 - k)) // 255 for a, b in zip(d, s))


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
    """RGBA of a tile (shadow: a darkening black)."""
    from PIL import Image
    W, H, px, x0, y0 = t.pixels()
    if shadow:
        m = Image.frombytes('L', (W, H), bytes(px)).point(lambda v: 110 if v else 0)
        im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        im.putalpha(m)
        return im, x0, y0
    im = Image.frombytes('P', (W, H), bytes(px))
    im.putpalette(flat)
    im.info['transparency'] = 0
    return im.convert('RGBA'), x0, y0


def _tile_idx(t):
    """('L' palette indices, 'L' mask, x0, y0) of a tile."""
    from PIL import Image
    W, H, px, x0, y0 = t.pixels()
    im = Image.frombytes('L', (W, H), bytes(px))
    return im, im.point(lambda v: 255 if v else 0), x0, y0


def _pick(cands, tx, ty):
    """One of the tile variants of a cell: rarity-weighted, stable per cell."""
    if len(cands) == 1:
        return cands[0]
    if cands[0].anim & 1:                   # animated tile group (flags 0x100): its frames, ordered by rarity
        return min(cands, key=lambda t: t.rarity)
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
    """The Scene of an act's town (see the module doc); centre = world pixel to centre on (None: the waypoint).
    Drawn in palette indices like the game (blended COF layers through the pl2 tables), lit, then coloured."""
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
    tables = pl2_tables(art, act)
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
    idx = Image.new('L', (W, H), 0)                              # the window in palette indices (0 = black)
    cache = {}

    def tile_at(t, wx, wy):
        """(indices, mask, window x, y) of tile t at world (wx, wy), or None outside the window."""
        x0, y0, x1, y1 = t.bbox()
        if wx + x1 <= vx or wx + x0 >= vx + W or wy + y1 <= vy or wy + y0 >= vy + H:
            return None
        got = cache.get(id(t))
        if got is None:
            got = cache[id(t)] = _tile_idx(t)
        im, mk, ox, oy = got
        return im, mk, wx + ox - vx, wy + oy - vy

    def tile_of(orient, dw, tx, ty):
        c = cell(dw)
        if c is None:
            return None
        cands = tiles.get((orient,) + c)
        return _pick(cands, tx, ty) if cands else None

    # floors, then shadows (the floor under them goes down SHADOW_LEVEL light levels)
    for layer in m.floors:
        for i, dw in enumerate(layer):
            tx, ty = i % m.w, i // m.w
            t = tile_of(0, dw, tx, ty)
            g = t and tile_at(t, (tx - ty) * 80, (tx + ty) * 40)
            if g:
                idx.paste(g[0], g[2:], g[1])
    if m.shadow:
        dark = tables['light'][SHADOW_LEVEL] if 'light' in tables else None
        for i, dw in enumerate(m.shadow):
            tx, ty = i % m.w, i // m.w
            t = tile_of(13, dw, tx, ty)
            g = t and tile_at(t, (tx - ty) * 80, (tx + ty) * 40)
            if g:
                im, mk, x, y = g
                under = idx.crop((x, y, x + im.width, y + im.height))
                under = under.point(list(dark)) if dark else under.point(lambda v: 0)
                idx.paste(under, (x, y), mk)
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
    lights = []
    for ox, oy, row in objs:
        r = object_light(row)
        if r and vx - 400 < ox < vx + W + 400 and vy - 300 < oy < vy + H + 300:
            lights.append((ox - vx, oy - vy - 20, r * 14, object_light_rgb(row)))
        if not (vx - 256 < ox < vx + W + 256 and vy - 64 < oy < vy + H + 384):
            continue
        a = _object_layers_cached(art, row)
        if a is not None:
            draw.append((oy, 2, a, ox, oy))
    draw.sort(key=lambda d: (d[0], d[1]))
    items = []                                   # what Scene.front lays over sprites
    anim = []                                    # (index in items, window box, frames [(indices, mask)], fps)
    for _k, kind, t, wx, wy in draw:
        if kind == 2:
            frames, (bx0, by0, bx1, by1), fps = t
            px, py = wx + bx0 - vx, wy + by0 - vy
            if px + bx1 - bx0 <= 0 or py + by1 - by0 <= 0 or px >= W or py >= H:
                continue
            bg = idx.crop((px, py, px + bx1 - bx0, py + by1 - by0))    # what this object blends with
            comp = [compose(bg, fl, tables) for fl in frames]
            items.append((_k, kind, comp[0][0], comp[0][1], px, py))
            if len(frames) > 1:                  # animated: kept out of .base, drawn by the UI
                anim.append((len(items) - 1, (max(0, px), max(0, py), min(W, px + bx1 - bx0), min(H, py + by1 - by0)),
                             (px, py), comp, fps))
            else:
                idx.paste(comp[0][0], (px, py), comp[0][1])
        else:
            g = tile_at(t, wx, wy)
            if g:
                idx.paste(g[0], g[2:], g[1])
                items.append((_k, kind) + g)
    sc = Scene(None, [], (anchor_w[0] - vx, anchor_w[1] - vy), act, window=(vx, vy), index=idx, pal=pal,
               tables=tables, items=items)
    # each animated object: its frames cut to the window, with what is drawn in front of it (walls, roofs, objects
    # standing lower) laid over them, so the UI only has to paste the frames on .base
    raw = []
    for n, box, (px, py), comp, fps in anim:
        x0, y0, x1, y1 = box
        k, kind = items[n][:2]
        fi, fm = sc.front(box, k, kind)
        out = []
        for ci, cm, (bm, bs) in comp:
            c = (x0 - px, y0 - py, x1 - px, y1 - py)
            ci, cm, bm = ci.crop(c), cm.crop(c), bm.crop(c)
            ci.paste(fi, (0, 0), fm)
            bm.paste(0, (0, 0), fm)
            out.append((to_rgba(ci, cm, pal), (bm, bs.crop(c))))
        raw.append({'pos': (x0, y0), 'frames': out, 'fps': fps})
    # lighting: the character's light around the anchor, pools (in the objects' light colours) around the
    # light-emitting objects, the rest dark; baked into .base and every sprite frame
    sc.light = light_map((W, H), sc.anchor, lights)
    sc.light_rgb = Image.merge('RGB', [light_map((W, H), sc.anchor, lights, c) for c in range(3)])
    sc.base = _lit(to_rgba(idx, None, pal), sc.light_rgb)
    sc.sprites = [dict(sp, frames=[sc.lit(f, sp['pos'], bi) for f, bi in sp['frames']]) for sp in raw]
    return sc


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


def _object_layers_cached(art, row):
    k = (getattr(art, 'game_dir', id(art)), bytes(row[:0xC4]), bytes(row[0x108:0x147]))
    if k not in _OBJ:
        try:
            _OBJ[k] = object_layers(art, row)
        except Exception:
            _OBJ[k] = None
    return _OBJ[k]


def scene(art, data_folder, act, size=(512, 384), centre=None):
    """Cached per (act, size, centre), the CACHE_SIZE most recently used; None when the town's files are missing."""
    k = (getattr(art, 'game_dir', None), data_folder, act, tuple(size), centre)
    with _LOCK:
        if k in _CACHE:
            _CACHE.move_to_end(k)
        else:
            try:
                _CACHE[k] = build(art, data_folder, act, size, centre)
            except Exception:
                import logging
                logging.getLogger('mxl_scene').exception('town scene of act %s', act)
                _CACHE[k] = None
            while len(_CACHE) > CACHE_SIZE:
                _CACHE.popitem(last=False)
        return _CACHE[k]
