"""DCC and COF: Diablo II's animation formats for characters, monsters and missiles in the game world.

Pure Python (no numpy). Follows the public community description of the format (Paul Siramy's DCC notes,
the same algorithm as the open-source OpenDiablo2 / d2dcc decoders):

DCC file:   u8 signature 0x74, u8 version 6, u8 directions, u32 frames per direction, u32 tag, u32 final dc6 size,
            u32 direction offsets[directions]
Direction:  a little-endian (LSB first) bit stream: header (field widths), frame headers, then five streams that
            follow each other at BIT offsets: equal cells, pixel mask, encoding type, raw pixel codes, and the
            pixel code / displacement stream (rest). The image is built in 4x4 cells over the direction's
            bounding box; a cell either repeats the previous frame's cell or gets up to 4 palette entries + 0-2 bit
            per pixel indices.
COF file:   28-byte header (layers, frames per direction, directions), 9-byte layer records (type, shadow,
            selectable, transparent, draw effect, weapon class), frame trigger bytes, then the draw order
            (layer type per layer) for every direction and frame.

Decoded frames are palette indices (0 = transparent) over the direction box: Frame(w, h, x0, y0, bytes), where
(x0, y0) is the box's top-left relative to the sprite's anchor (the unit's feet)."""
import struct

_CRAZY = (0, 1, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 26, 28, 30, 32)
_MASK_BITS = (0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4)
LAYERS = ('HD', 'TR', 'LG', 'RA', 'LA', 'RH', 'LH', 'SH',
          'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8')


class DCCError(Exception):
    pass


class _Bits:
    """LSB-first bit reader over bytes (positions in bits)."""
    __slots__ = ('d', 'pos')

    def __init__(self, data, pos=0):
        self.d = data + b'\0' * 8
        self.pos = pos

    def get(self, n):
        if n == 0:
            return 0
        p = self.pos
        b = p >> 3
        v = (int.from_bytes(self.d[b:b + 5], 'little') >> (p & 7)) & ((1 << n) - 1)
        self.pos = p + n
        return v

    def bit(self):
        p = self.pos
        self.pos = p + 1
        return (self.d[p >> 3] >> (p & 7)) & 1

    def signed(self, n):
        v = self.get(n)
        if n and v & (1 << (n - 1)):
            v -= 1 << n
        return v


class Frame:
    __slots__ = ('w', 'h', 'x0', 'y0', 'pixels')

    def __init__(self, w, h, x0, y0, pixels):
        self.w, self.h, self.x0, self.y0, self.pixels = w, h, x0, y0, pixels

    def image(self, pal):
        """RGBA PIL image; pal = 256 (r, g, b) tuples."""
        from PIL import Image
        im = Image.frombytes('P', (self.w, self.h), bytes(self.pixels))
        flat = []
        for c in pal[:256]:
            flat.extend(c[:3])
        im.putpalette(flat)
        im.info['transparency'] = 0
        return im.convert('RGBA')


def header(data):
    if len(data) < 15 or data[0] != 0x74:
        raise DCCError('not a DCC file')
    ndir = data[2]
    nfr = struct.unpack_from('<I', data, 3)[0]
    offs = list(struct.unpack_from(f'<{ndir}I', data, 15))
    return ndir, nfr, offs


def decode_direction(data, d):
    """All frames of direction d as a list of Frame (same box for every frame of the direction)."""
    ndir, nfr, offs = header(data)
    if not 0 <= d < ndir:
        raise DCCError(f'direction {d} of {ndir}')
    end = offs[d + 1] if d + 1 < ndir else len(data)
    bm = _Bits(data[offs[d]:end])
    bm.get(32)                                      # out size coded
    comp = bm.get(2)
    v0b, wb, hb, xb, yb, ob, cb = (_CRAZY[bm.get(4)] for _ in range(7))
    frames = []
    for _ in range(nfr):
        bm.get(v0b)
        w = bm.get(wb)
        h = bm.get(hb)
        xo = bm.signed(xb)
        yo = bm.signed(yb)
        opt = bm.get(ob)
        bm.get(cb)
        if bm.bit():
            raise DCCError('bottom-up DCC frames are not supported')
        frames.append([xo, yo - h + 1, w, h, opt])  # left, top, width, height
    optional = sum(f[4] for f in frames)
    if optional:
        bm.pos = (bm.pos + 7) & ~7
        bm.pos += optional * 8
    ec_size = bm.get(20) if comp & 2 else 0
    pm_size = bm.get(20)
    et_size = rp_size = 0
    if comp & 1:
        et_size = bm.get(20)
        rp_size = bm.get(20)
    pal = [i for i in range(256) if bm.bit()]
    pal += [0] * (256 - len(pal))
    ec = _Bits(bm.d, bm.pos)
    pm = _Bits(bm.d, ec.pos + ec_size)
    et = _Bits(bm.d, pm.pos + pm_size)
    rp = _Bits(bm.d, et.pos + et_size)
    pcd = _Bits(bm.d, rp.pos + rp_size)

    # direction box
    bl = min(f[0] for f in frames)
    bt = min(f[1] for f in frames)
    br = max(f[0] + f[2] for f in frames)
    bb = max(f[1] + f[3] for f in frames)
    BW, BH = br - bl, bb - bt
    if BW <= 0 or BH <= 0 or BW * BH > 4_000_000:
        raise DCCError('bad direction box')
    hcells = 1 + (BW - 1) // 4

    # frame cells (offsets relative to the direction box)
    fcells = []
    for (left, top, w, h, _o) in frames:
        def split(size, first):
            if size - first <= 1:
                return [size]
            tmp = size - first - 1
            n = 2 + tmp // 4
            if tmp % 4 == 0:
                n -= 1
            sizes = [4] * n
            sizes[0] = first
            sizes[-1] = size - (first + 4 * (n - 2))
            return sizes
        ws = split(w, 4 - ((left - bl) % 4))
        hs = split(h, 4 - ((top - bt) % 4))
        cells = []
        oy = top - bt
        for ch in hs:
            ox = left - bl
            for cw in ws:
                cells.append((ox, oy, cw, ch))
                ox += cw
            oy += ch
        fcells.append((len(ws), cells))

    # pixel buffer
    pbuf = []                                       # [values(4), frame, cell index]
    cellbuf = {}
    for fi, (left, top, w, h, _o) in enumerate(frames):
        nx, cells = fcells[fi]
        ocx = (left - bl) // 4
        ocy = (top - bt) // 4
        ny = len(cells) // nx if nx else 0
        for cy in range(ny):
            for cx in range(nx):
                cur = ocx + cx + (ocy + cy) * hcells
                old = cellbuf.get(cur)
                if old is not None:
                    if ec_size and ec.bit():
                        continue
                    mask = pm.get(4)
                else:
                    mask = 0x0F
                nbits = _MASK_BITS[mask]
                enc = et.bit() if (nbits and et_size) else 0
                stack = [0, 0, 0, 0]
                last = 0
                decoded = 0
                for i in range(nbits):
                    if enc:
                        stack[i] = rp.get(8)
                    else:
                        v = last
                        disp = pcd.get(4)
                        v += disp
                        while disp == 15:
                            disp = pcd.get(4)
                            v += disp
                        stack[i] = v
                    if stack[i] == last:
                        stack[i] = 0
                        break
                    last = stack[i]
                    decoded += 1
                vals = [0, 0, 0, 0]
                idx = decoded - 1
                for i in range(4):
                    if mask & (1 << i):
                        if idx >= 0:
                            vals[i] = stack[idx] & 0xFF
                            idx -= 1
                    else:
                        vals[i] = old[0][i]
                entry = [vals, fi, cx + cy * nx]
                pbuf.append(entry)
                cellbuf[cur] = entry
    for e in pbuf:
        e[0] = [pal[v] for v in e[0]]

    # frames
    canvas = bytearray(BW * BH)
    last = {}                                       # direction cell -> (w, h, x, y)
    out = []
    pi = 0
    for fi in range(len(frames)):
        img = bytearray(BW * BH)
        for c, (ox, oy, cw, ch) in enumerate(fcells[fi][1]):
            key = (ox // 4) + (oy // 4) * hcells
            e = pbuf[pi] if pi < len(pbuf) else None
            if e is None or e[1] != fi or e[2] != c:
                lw = last.get(key)
                if lw is None or lw[0] != cw or lw[1] != ch:
                    for y in range(oy, oy + ch):
                        canvas[y * BW + ox:y * BW + ox + cw] = bytes(cw)
                else:
                    lx, ly = lw[2], lw[3]
                    for y in range(ch):
                        s = (ly + y) * BW + lx
                        t = (oy + y) * BW + ox
                        row = canvas[s:s + cw]
                        canvas[t:t + cw] = row
                        img[t:t + cw] = row
            else:
                v = e[0]
                if v[0] == v[1]:
                    row = bytes([v[0]]) * cw
                    for y in range(oy, oy + ch):
                        canvas[y * BW + ox:y * BW + ox + cw] = row
                else:
                    nb = 2 if v[1] != v[2] else 1
                    for y in range(oy, oy + ch):
                        b = y * BW + ox
                        canvas[b:b + cw] = bytes(v[pcd.get(nb)] for _ in range(cw))
                for y in range(oy, oy + ch):
                    b = y * BW + ox
                    img[b:b + cw] = canvas[b:b + cw]
                pi += 1
            last[key] = (cw, ch, ox, oy)
        out.append(Frame(BW, BH, bl, bt, img))
    return out


# ---------------------------------------------------------------- COF
class COF:
    __slots__ = ('layers', 'frames', 'dirs', 'speed', 'order')

    def __init__(self, data):
        if len(data) < 28:
            raise DCCError('short COF')
        nl, self.frames, self.dirs = data[0], data[1], data[2]
        self.speed = data[24]
        self.layers = []                            # (type, transparent, draw effect, weapon class)
        p = 28
        for _ in range(nl):
            t, _shadow, _sel, transp, eff = data[p:p + 5]
            wc = data[p + 5:p + 9].split(b'\0')[0].decode('latin-1').lower()
            self.layers.append((t, transp, eff, wc))
            p += 9
        p += self.frames                            # frame triggers
        need = self.dirs * self.frames * nl
        pr = data[p:p + need]
        self.order = None
        if len(pr) == need:
            self.order = [[list(pr[(d * self.frames + f) * nl:(d * self.frames + f + 1) * nl])
                           for f in range(self.frames)] for d in range(self.dirs)]

    def draw_order(self, d, f):
        if self.order:
            return self.order[d % self.dirs][f % self.frames]
        return [l[0] for l in self.layers]


def animdata(data):
    """animdata.d2 -> {cof name lower: (frames per direction, speed)}; game frames per second = speed * 25 / 256."""
    out = {}
    p = 0
    n = len(data)
    for _ in range(256):
        if p + 4 > n:
            break
        cnt = struct.unpack_from('<I', data, p)[0]
        p += 4
        for _ in range(cnt):
            if p + 160 > n:
                return out
            name = data[p:p + 8].split(b'\0')[0].decode('latin-1').lower()
            fpd, spd = struct.unpack_from('<II', data, p + 8)
            out[name] = (fpd, spd)
            p += 160
    return out
