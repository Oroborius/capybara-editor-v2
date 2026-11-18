"""A faster PKWARE DCL "explode" for the collector's MPQ reader (host module `mpq`).

Median XL's panels, fonts and skill icons are stored implode-compressed in the game archives. The collector's
pure-Python explode reads every bit through a method call (about 13 million calls for the art of one start):
the first start with a new game version or an empty user folder spent 15-25 s in it, most of that on the main
thread while the Character tab was built. This one decodes the same stream with a bit buffer held in local
variables and lookup tables for the three fixed Huffman codes (one table index per code instead of one dict
lookup per bit) - same output, about ten times faster. install() swaps it in for mpq.explode, the name the
reader calls (mpq.decompress and MPQ.read look it up at call time); everything else of the reader stays."""

# the fixed codes of the format (as the collector's mpq module has them: code values as read LSB-first)
LEN_BITS = (3, 2, 3, 3, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 7, 7)
LEN_CODE = (5, 3, 1, 6, 10, 2, 12, 20, 4, 24, 8, 48, 16, 32, 64, 0)
EXLEN_BITS = (0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8)
LEN_BASE = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 14, 22, 38, 70, 134, 262)
DIST_BITS = (2, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
             7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8)
DIST_CODE = (3, 13, 5, 25, 9, 17, 1, 62, 30, 46, 14, 54, 22, 38, 6, 58, 26, 42, 10, 50, 18, 34, 66, 2, 124, 60,
             92, 28, 108, 44, 76, 12, 116, 52, 84, 20, 100, 36, 68, 4, 120, 56, 88, 24, 104, 40, 72, 8, 240, 112,
             176, 48, 208, 80, 144, 16, 224, 96, 160, 32, 192, 64, 128, 0)
_host = {}


def _table(bits, codes, width):
    """Lookup table over the next `width` bits (LSB first): entry -> (symbol << 4) | code length.
    -1 where no code matches (the reader's 'bad code')."""
    t = [-1] * (1 << width)
    for sym, (b, c) in enumerate(zip(bits, codes)):
        for hi in range(1 << (width - b)):
            t[(hi << b) | c] = (sym << 4) | b
    return t


_LEN = _table(LEN_BITS, LEN_CODE, 7)
_DIST = _table(DIST_BITS, DIST_CODE, 8)


def explode(src):
    """Decompresses one PKWARE DCL (implode) stream, binary mode; the same result and errors as mpq.explode."""
    ctype, dsize = src[0], src[1]
    data = src[2:]
    if ctype != 0:
        raise NotImplementedError('ascii mode')
    if not data:
        raise IndexError('index out of range')
    LEN, DIST, LBASE, EXL = _LEN, _DIST, LEN_BASE, EXLEN_BITS
    end = len(data)
    out = bytearray()
    buf = nb = p = 0                       # bit buffer (LSB = next bit), bits in it, next byte of data
    while True:
        if nb < 32:                        # enough for the longest step: 1 + 7 + 8 + 8 + 6 bits
            if p < end:
                buf |= int.from_bytes(data[p:p + 6], 'little') << nb
                q = p + 6 if p + 6 < end else end
                nb += (q - p) << 3
                p = q
            pad = nb < 32 and p >= end
        else:
            pad = False
        if not buf & 1:                    # literal byte
            if pad and nb < 9:
                raise IndexError('index out of range')
            out.append((buf >> 1) & 0xFF)
            buf >>= 9
            nb -= 9
            continue
        e = LEN[(buf >> 1) & 0x7F]
        if e < 0:
            raise ValueError('bad code')
        b = e & 15
        li = e >> 4
        x = EXL[li]
        used = 1 + b + x
        if pad and nb < used:
            raise IndexError('index out of range')
        ln = LBASE[li] + ((buf >> (1 + b)) & ((1 << x) - 1))
        buf >>= used
        nb -= used
        if ln == 517:                      # end of stream
            return bytes(out)
        ln += 2
        e = DIST[buf & 0xFF]
        if e < 0:
            raise ValueError('bad code')
        b = e & 15
        lo = 2 if ln == 2 else dsize
        used = b + lo
        if pad and nb < used:
            raise IndexError('index out of range')
        dist = (((e >> 4) << lo) | ((buf >> b) & ((1 << lo) - 1))) + 1
        buf >>= used
        nb -= used
        n = len(out)
        if dist > n:                        # the host reads out[-dist] there (wraps or raises)
            for _k in range(ln):
                out.append(out[-dist])
            continue
        s = n - dist
        if dist >= ln:
            out += out[s:s + ln]
        else:                               # overlapping copy: the last `dist` bytes repeated
            chunk = out[s:]
            out += (chunk * (ln // dist + 1))[:ln]


def install():
    """Puts explode() in place of the collector's mpq.explode (once; harmless when mpq is missing)."""
    try:
        import mpq
    except Exception:
        return False
    if getattr(mpq.explode, '_capy_fast', False):
        return True
    _host['explode'] = mpq.explode
    mpq.explode = explode
    explode._capy_fast = True
    return True


def host_explode():
    """The collector's own explode (for comparisons in the tests)."""
    if 'explode' in _host:
        return _host['explode']
    import mpq
    return mpq.explode
