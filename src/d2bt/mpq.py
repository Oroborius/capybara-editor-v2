"""Pure-Python, read-only MPQ reader for Diablo II archives (vanilla and protected mods).

Supports header format 0/1 (v2 hi-block table when it looks sane), user-data headers, archives at any
512-byte offset, encrypted and FIX_KEY files, single-unit files, sector CRC tables (ignored), and the
codecs zlib, bzip2, PKWARE DCL implode, Huffman, IMA ADPCM (mono/stereo), sparse and LZMA.

Tolerance (protected archives such as Median XL's): header size, archive size and format version
fields are not trusted; tables that run past EOF are clamped; hash entries that point outside the block
table are ignored; hash tables whose size is not a power of two are scanned linearly; block extents
that run past EOF are clamped.

Files whose name is unknown stay readable through their Entry: the encryption key is recovered from
the sector offset table (its first dword is a known plaintext).
"""
from __future__ import annotations

import base64
import bz2
import lzma
import os
import threading

_PREAD_LOCK = threading.Lock()
import struct
import zlib
from array import array
from dataclasses import dataclass

M32 = 0xFFFFFFFF

# --------------------------------------------------------------------------- crypto

def _build_crypt_table():
    table = [0] * 0x500
    seed = 0x00100001
    for i1 in range(0x100):
        i2 = i1
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            t1 = (seed & 0xFFFF) << 16
            seed = (seed * 125 + 3) % 0x2AAAAB
            t2 = seed & 0xFFFF
            table[i2] = t1 | t2
            i2 += 0x100
    return table


CRYPT = _build_crypt_table()
HASH_OFFSET, HASH_A, HASH_B, HASH_KEY = 0, 1, 2, 3

# upper-case table that also maps '/' to '\' (Storm's normalisation)
_UPPER = bytes((c - 32 if 97 <= c <= 122 else (92 if c == 47 else c)) for c in range(256))


def norm_name(name: str) -> bytes:
    return name.encode('latin-1', 'replace').translate(_UPPER)


def hash_bytes(data: bytes, htype: int, s1=0x7FED7FED, s2=0xEEEEEEEE) -> int:
    """Storm hash of already-normalised bytes; (s1, s2) allow resuming from a cached prefix state."""
    ct = CRYPT
    base = htype << 8
    for ch in data:
        s1 = ct[base + ch] ^ ((s1 + s2) & M32)
        s2 = (ch + s1 + s2 + (s2 << 5) + 3) & M32
    return s1


def hash_state(data: bytes, htype: int, s1=0x7FED7FED, s2=0xEEEEEEEE):
    """(s1, s2) after hashing `data`; feed back into hash_bytes to hash prefix+suffix cheaply."""
    ct = CRYPT
    base = htype << 8
    for ch in data:
        s1 = ct[base + ch] ^ ((s1 + s2) & M32)
        s2 = (ch + s1 + s2 + (s2 << 5) + 3) & M32
    return s1, s2


def hash_string(name: str, htype: int) -> int:
    return hash_bytes(norm_name(name), htype)


def file_key_name(name: str) -> str:
    """Storm derives a file's key from the last path component only."""
    return name.replace('/', '\\').rsplit('\\', 1)[-1]


def decrypt(data, key: int) -> bytes:
    """Decrypt whole dwords; a trailing partial dword is copied as is."""
    n = len(data) // 4
    if n == 0:
        return bytes(data)
    words = array('I')
    words.frombytes(bytes(data[:n * 4]))
    if words.itemsize != 4:  # pragma: no cover
        raise RuntimeError('array I is not 32-bit here')
    ct = CRYPT
    s2 = 0xEEEEEEEE
    for i in range(n):
        s2 = (s2 + ct[0x400 + (key & 0xFF)]) & M32
        p = words[i] ^ ((key + s2) & M32)
        words[i] = p
        key = (((((~key) & M32) << 0x15) + 0x11111111) & M32) | (key >> 0x0B)
        s2 = (p + s2 + (s2 << 5) + 3) & M32
    return words.tobytes() + bytes(data[n * 4:])


def encrypt(data, key: int) -> bytes:
    """Inverse of decrypt (used by the writer): whole dwords, a trailing partial dword is copied."""
    n = len(data) // 4
    if n == 0:
        return bytes(data)
    words = array('I')
    words.frombytes(bytes(data[:n * 4]))
    ct = CRYPT
    s2 = 0xEEEEEEEE
    for i in range(n):
        s2 = (s2 + ct[0x400 + (key & 0xFF)]) & M32
        p = words[i]
        words[i] = p ^ ((key + s2) & M32)
        key = (((((~key) & M32) << 0x15) + 0x11111111) & M32) | (key >> 0x0B)
        s2 = (p + s2 + (s2 << 5) + 3) & M32
    return words.tobytes() + bytes(data[n * 4:])


def recover_seed(enc0: int, plain0: int):
    """All decryption keys under which dword enc0 decrypts to plain0 (usually 0-2 candidates)."""
    out = []
    x = (enc0 ^ plain0) & M32
    for i in range(256):
        s1 = (x - 0xEEEEEEEE - CRYPT[0x400 + i]) & M32
        if s1 & 0xFF == i:
            out.append(s1)
    return out


# --------------------------------------------------------------------------- codecs

class DecompressError(Exception):
    pass


# PKWARE DCL explode (binary and ASCII literals).  Codes are stored LSB-first.
_LEN_BITS = (3, 2, 3, 3, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 7, 7)
_LEN_CODE = (5, 3, 1, 6, 10, 2, 12, 20, 4, 24, 8, 48, 16, 32, 64, 0)
_EXLEN_BITS = (0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8)
_LEN_BASE = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 14, 22, 38, 70, 134, 262)
_DIST_BITS = (2, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
              7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8)
_DIST_CODE = (0x03, 0x0D, 0x05, 0x19, 0x09, 0x11, 0x01, 0x3E, 0x1E, 0x2E, 0x0E, 0x36, 0x16, 0x26, 0x06, 0x3A,
              0x1A, 0x2A, 0x0A, 0x32, 0x12, 0x22, 0x42, 0x02, 0x7C, 0x3C, 0x5C, 0x1C, 0x6C, 0x2C, 0x4C, 0x0C,
              0x74, 0x34, 0x54, 0x14, 0x64, 0x24, 0x44, 0x04, 0x78, 0x38, 0x58, 0x18, 0x68, 0x28, 0x48, 0x08,
              0xF0, 0x70, 0xB0, 0x30, 0xD0, 0x50, 0x90, 0x10, 0xE0, 0x60, 0xA0, 0x20, 0xC0, 0x40, 0x80, 0x00)

def _lut(bits, codes, width):
    t = [-1] * (1 << width)
    for sym, (b, c) in enumerate(zip(bits, codes)):
        for hi in range(1 << (width - b)):
            t[(hi << b) | c] = (sym << 4) | b
    return t


_LEN_LUT = _lut(_LEN_BITS, _LEN_CODE, 7)
_DIST_LUT = _lut(_DIST_BITS, _DIST_CODE, 8)


def explode(src, limit: int) -> bytes:
    """PKWARE DCL explode, binary literals only. Stops at the end marker or after `limit` bytes."""
    if len(src) < 3:
        raise DecompressError('implode: stream too short')
    ctype, dbits = src[0], src[1]
    if ctype != 0:
        raise DecompressError('implode: ASCII mode is not supported')
    if dbits not in (4, 5, 6):
        raise DecompressError(f'implode: bad dictionary size {dbits}')
    data = bytes(src[2:])
    end = len(data)
    LEN, DIST, LBASE, EXL = _LEN_LUT, _DIST_LUT, _LEN_BASE, _EXLEN_BITS
    out = bytearray()
    buf = nb = p = 0
    while True:
        if nb < 32 and p < end:
            q = min(p + 6, end)
            buf |= int.from_bytes(data[p:q], 'little') << nb
            nb += (q - p) << 3
            p = q
        if len(out) >= limit:
            return bytes(out[:limit])
        if not buf & 1:
            if nb < 9:
                break
            out.append((buf >> 1) & 0xFF)
            buf >>= 9
            nb -= 9
            continue
        e = LEN[(buf >> 1) & 0x7F]
        if e < 0:
            raise DecompressError('implode: bad length code')
        b = e & 15
        li = e >> 4
        x = EXL[li]
        used = 1 + b + x
        if nb < used:
            break
        ln = LBASE[li] + ((buf >> (1 + b)) & ((1 << x) - 1))
        buf >>= used
        nb -= used
        if ln == 517:
            return bytes(out)
        ln += 2
        e = DIST[buf & 0xFF]
        if e < 0:
            raise DecompressError('implode: bad distance code')
        b = e & 15
        lo = 2 if ln == 2 else dbits
        used = b + lo
        if nb < used:
            break
        dist = (((e >> 4) << lo) | ((buf >> b) & ((1 << lo) - 1))) + 1
        buf >>= used
        nb -= used
        n = len(out)
        if dist > n:
            raise DecompressError('implode: distance before start of output')
        s = n - dist
        if dist >= ln:
            out += out[s:s + ln]
        else:
            chunk = out[s:]
            out += (chunk * (ln // dist + 1))[:ln]
    # ran out of input without an end marker: accept what we have
    return bytes(out[:limit])


# Huffman weight tables (9 x 0x102 bytes, Storm's own tables).
_HUFF_W = zlib.decompress(base64.b64decode(
    'eNrjYhjRgImBIURMjJeHg40VCJlZWJhZ+bhFhIU5udlYWZiZmJmYmHjZOdnYgGwWZhBgYuJkYwECiByQYOFgZmHnZIXIgQTB4iDAyMjI'
    'xMjExMbFwcHGzgI0m4mJhYmZmYWZHWgi0DSQJBBwgbUwgjhszKxANiMcMDGDzYCwgZayc3LwIEmD5ZhZgFKsCD4jC5zFiMJiRuXDrPRG'
    'Cg1mdQYGZcxA+s+I0MLGJ8DCxsHKAnI/0DNQK4EeA0mygJwMDBlGZjYWmGUgeU12MSEHLi5BVUZmcQE1LQFGZWV9ATZ2Jk6wmkGQDP5z'
    's7Nyg0ID6AsWJkZmkMOYWSCeA2FQ+PKihTtycHIBNbFBYw4kAYxGUHKBJgFgMIECCmgIMHkBmSAJFmYuNiTzmBi5QPJM7EziIMv4GEkD'
    'bEADWaFuYcKjjh1NDZQWBIbA7xmzWlqTU+zslJSEhSXER15R8P/j3HmzZs+aPnlyT19bR0NTTU1RcWZ2fEJomJe3g6O5ub6+urqiorSM'
    'uLiwsIAALy83NycnBwc7OxsrMDewSEoM/RA4fPqr4//q74rk6t9/5pPD35rvSuTqr3Ib8BC4+d72Z81Lub+rP+r8if5Hci7Ye/ON7dfa'
    'F7K/133Q+R3zn+Q0UZAz0CGw6+gt48e5NySeTrmlfN/rosC79U90XkXdE/3S/lLxm/MfIUL6Nxy/Yfw4+5rE86k3lG97XhB8uemR9ouY'
    'u6If258rfHf5L0xIf/y8gQ4BAB1pauM='))


class _HNode:
    __slots__ = ('prev', 'next', 'parent', 'lo', 'weight', 'value')

    def __init__(self, value=0, weight=0):
        self.prev = self.next = self.parent = self.lo = None
        self.value = value
        self.weight = weight


def huffman(src, limit: int) -> bytes:
    """Storm's adaptive Huffman decoder (port of StormLib's huff.cpp semantics)."""
    if not src:
        raise DecompressError('huffman: empty')
    data = bytes(src)
    nbits = len(data) * 8
    pos = 8
    ctype = data[0]
    if (ctype & 0x0F) > 8:
        raise DecompressError(f'huffman: bad table {ctype}')
    t = (ctype & 0x0F) * 0x102
    weights = _HUFF_W[t:t + 256]

    head = _HNode()
    head.prev = head.next = head

    def unlink(n):
        if n.prev is not None:
            n.prev.next = n.next
            n.next.prev = n.prev
            n.prev = n.next = None

    def insert_after(n, at):
        unlink(n)
        n.next = at.next
        n.prev = at
        at.next.prev = n
        at.next = n

    def insert_before(n, at):
        unlink(n)
        n.prev = at.prev
        n.next = at
        at.prev.next = n
        at.prev = n

    def find_ge(start, w):
        it = start
        while it is not head:
            if it.weight >= w:
                return it
            it = it.prev
        return head

    by_byte = [None] * 0x102
    maxw = 0
    for i in range(256):
        w = weights[i]
        if w:
            n = _HNode(i, w)
            insert_after(n, head)
            by_byte[i] = n
            if w < maxw:
                insert_after(n, find_ge(head.prev, w))
            else:
                maxw = w
    for v in (0x100, 0x101):
        n = _HNode(v, 1)
        insert_before(n, head)
        by_byte[v] = n
    lo = head.prev
    while lo is not head:
        hi = lo.prev
        if hi is head:
            break
        p = _HNode(0, hi.weight + lo.weight)
        insert_after(p, head)
        lo.parent = p
        hi.parent = p
        p.lo = lo
        if p.weight < maxw:
            insert_after(p, find_ge(hi.prev, p.weight))
        else:
            maxw = p.weight
        lo = hi.prev

    def inc(n):
        while n is not None:
            n.weight += 1
            higher = find_ge(n.prev, n.weight)
            chi = higher.next
            if chi is not n:
                insert_after(chi, n)
                insert_after(n, higher)
                chi_par = chi.parent
                chi_par_lo = chi_par.lo if chi_par is not None else None
                par = n.parent
                if par is not None and par.lo is n:
                    par.lo = chi
                if chi_par_lo is chi:
                    chi_par.lo = n
                n.parent, chi.parent = chi_par, par
            n = n.parent

    out = bytearray()
    cmp0 = ctype == 0
    while True:
        n = head.next
        while n.lo is not None:
            if pos >= nbits:
                return bytes(out)
            bit = (data[pos >> 3] >> (pos & 7)) & 1
            pos += 1
            n = n.lo.prev if bit else n.lo
        v = n.value
        if v == 0x100:
            break
        if v == 0x101:
            if pos + 8 > nbits:
                break
            v = 0
            for k in range(8):
                v |= ((data[pos >> 3] >> (pos & 7)) & 1) << k
                pos += 1
            last = head.prev
            c1 = _HNode(last.value, last.weight)
            insert_before(c1, head)
            c1.parent = last
            by_byte[c1.value] = c1
            c2 = _HNode(v, 0)
            insert_before(c2, head)
            c2.parent = last
            by_byte[v] = c2
            last.lo = c2
            inc(c2)
            if not cmp0:
                inc(by_byte[v])
        out.append(v)
        if len(out) >= limit:
            break
        if cmp0:
            inc(by_byte[v])
    return bytes(out)


_ADPCM_NEXT = (-1, 0, -1, 4, -1, 2, -1, 6, -1, 1, -1, 5, -1, 3, -1, 7,
               -1, 1, -1, 5, -1, 3, -1, 7, -1, 2, -1, 4, -1, 6, -1, 8)
_ADPCM_STEP = (7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66,
               73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
               494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272,
               2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493,
               10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767)


def adpcm(src, limit: int, channels: int) -> bytes:
    """Storm's IMA ADPCM variant (mono or stereo), 16-bit little-endian output (checked against StormLib)."""
    data = bytes(src)
    if len(data) < 2 + 2 * channels:
        raise DecompressError('adpcm: too short')
    shift = data[1]
    pred = [0] * channels
    idx = [0x2C] * channels
    out = array('h')
    p = 2
    for c in range(channels):
        s = struct.unpack_from('<h', data, p)[0]
        p += 2
        pred[c] = s
        out.append(s)
    maxs = limit // 2
    ch = channels - 1
    n = len(data)
    STEP, NEXT = _ADPCM_STEP, _ADPCM_NEXT
    while p < n and len(out) < maxs:
        e = data[p]
        p += 1
        ch = (ch + 1) % channels
        if e == 0x80:
            if idx[ch]:
                idx[ch] -= 1
            out.append(pred[ch])
        elif e == 0x81:
            idx[ch] = min(idx[ch] + 8, 0x58)
            ch = (ch + 1) % channels
        else:
            step = STEP[idx[ch]]
            d = step >> shift
            if e & 1: d += step
            if e & 2: d += step >> 1
            if e & 4: d += step >> 2
            if e & 8: d += step >> 3
            if e & 16: d += step >> 4
            if e & 32: d += step >> 5
            if e & 0x40:
                v = pred[ch] - d
                if v < -32768: v = -32768
            else:
                v = pred[ch] + d
                if v > 32767: v = 32767
            pred[ch] = v
            out.append(v)
            i = idx[ch] + NEXT[e & 0x1F]
            idx[ch] = 0 if i < 0 else (0x58 if i > 0x58 else i)
    if out.itemsize != 2:  # pragma: no cover
        raise RuntimeError('array h is not 16-bit here')
    if os.sys.byteorder != 'little':  # pragma: no cover
        out.byteswap()
    return out.tobytes()[:limit]


def sparse(src, limit: int) -> bytes:
    data = bytes(src)
    if len(data) < 5:
        raise DecompressError('sparse: too short')
    size = struct.unpack_from('>I', data, 0)[0]
    out = bytearray()
    p = 4
    while p < len(data) and len(out) < min(size, limit):
        b = data[p]
        p += 1
        if b & 0x80:
            k = (b & 0x7F) + 1
            out += data[p:p + k]
            p += k
        else:
            out += bytes((b & 0x7F) + 3)
    return bytes(out[:min(size, limit)])


def _lzma(src, limit: int) -> bytes:
    data = bytes(src)
    # StormLib layout: 1 padding byte? then 5 property bytes, then 8-byte size (LZMA alone), or props+data
    for start in (0, 1):
        try:
            props = data[start:start + 5]
            d = props[0]
            lc, lp, pb = d % 9, (d // 9) % 5, d // 45
            dict_size = struct.unpack_from('<I', props, 1)[0]
            f = {'id': lzma.FILTER_LZMA1, 'lc': lc, 'lp': lp, 'pb': pb, 'dict_size': dict_size}
            for skip in (5, 13):
                try:
                    dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[f])
                    out = dec.decompress(data[start + skip:], limit)
                    if out:
                        return out
                except lzma.LZMAError:
                    pass
        except (IndexError, struct.error, ValueError):
            pass
    raise DecompressError('lzma: cannot decode')


COMP_HUFFMAN, COMP_ZLIB, COMP_PKWARE, COMP_BZIP2 = 0x01, 0x02, 0x08, 0x10
COMP_SPARSE, COMP_ADPCM_MONO, COMP_ADPCM_STEREO, COMP_LZMA = 0x20, 0x40, 0x80, 0x12


def _zlib(src, limit):
    try:
        d = zlib.decompressobj()
        return d.decompress(bytes(src), limit)
    except zlib.error as e:
        # some writers emit raw deflate
        try:
            return zlib.decompressobj(-15).decompress(bytes(src), limit)
        except zlib.error:
            raise DecompressError(f'zlib: {e}') from None


def _bz2(src, limit):
    try:
        return bz2.BZ2Decompressor().decompress(bytes(src), limit)
    except (OSError, ValueError) as e:
        raise DecompressError(f'bzip2: {e}') from None


def decompress_unit(data, expected: int, implode: bool = False) -> bytes:
    """Decompress one stored sector / single unit into (up to) `expected` bytes."""
    if implode:
        return explode(data, expected)
    if not data:
        raise DecompressError('empty unit')
    mask = data[0]
    body = data[1:]
    if mask == COMP_LZMA:
        return _lzma(body, expected)
    # Intermediate stages are bounded generously (the wave codecs expand ~4x after Huffman).
    big = max(expected * 4, 1 << 16)
    cur = body
    if mask & ~0xFB:
        raise DecompressError(f'unknown compression mask {mask:#04x}')
    if mask & COMP_BZIP2:
        cur = _bz2(cur, big)
    if mask & COMP_PKWARE:
        cur = explode(cur, big)
    if mask & COMP_ZLIB:
        cur = _zlib(cur, big)
    if mask & COMP_HUFFMAN:
        cur = huffman(cur, big)
    if mask & COMP_ADPCM_STEREO:
        cur = adpcm(cur, expected, 2)
    if mask & COMP_ADPCM_MONO:
        cur = adpcm(cur, expected, 1)
    if mask & COMP_SPARSE:
        cur = sparse(cur, expected)
    return bytes(cur[:expected])


# --------------------------------------------------------------------------- sniffing

def sniff_ext(head: bytes, size: int | None = None) -> str:
    """Best-guess extension from the first bytes of a file (`size` = full size if known)."""
    if size is None:
        size = len(head)
    h = head
    if size == 0:
        return 'dat'
    if h[:4] == b'RIFF':
        return 'wav'
    if h[:3] == b'BIK':
        return 'bik'
    if h[:4] in (b'SMK2', b'SMK4'):
        return 'smk'
    if h[:2] == b'MZ':
        return 'dll'
    if h[:4] in (b'MPQ\x1a', b'MPQ\x1b'):
        return 'mpq'
    if h[:2] == b'BM' and len(h) >= 6 and struct.unpack_from('<I', h, 2)[0] == size:
        return 'bmp'
    if h[:3] == b'ID3' or h[:2] in (b'\xff\xfb', b'\xff\xf3'):
        return 'mp3'
    if h[:4] == b'Woo!':
        return 'tbl'
    if h[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return 'txt'
    if h[:4] == b'\x89PNG':
        return 'png'
    if h[:3] == b'\xff\xd8\xff':
        return 'jpg'
    if len(h) >= 16:
        v, f, e, term = struct.unpack_from('<iiiI', h, 0)
        if v == 6 and f in (0, 1, 5) and e == 0 and len(h) >= 24:
            dirs, frames = struct.unpack_from('<II', h, 16)
            if term in (0xEEEEEEEE, 0xCDCDCDCD, 0) and 1 <= dirs <= 64 and 1 <= frames <= 1024:
                return 'dc6'
    if len(h) >= 2 and h[0] == 0x74 and h[1] == 6:
        return 'dcc'
    if len(h) >= 8 and struct.unpack_from('<ii', h, 0) == (7, 6):
        return 'dt1'
    if len(h) >= 4 and h[3] == 0x14 and 1 <= h[0] <= 16 and h[2] in (1, 4, 8, 16, 32, 64) and h[1] > 0:
        return 'cof'
    if len(h) >= 4 and h[0] == 0x0A and h[1] in (0, 2, 3, 4, 5) and h[2] == 1 and h[3] in (1, 2, 4, 8):
        return 'pcx'
    if len(h) >= 21:
        cnt = struct.unpack_from('<H', h, 2)[0]
        hsize = struct.unpack_from('<I', h, 4)[0]
        idx_end = struct.unpack_from('<I', h, 17)[0]
        if idx_end == size and hsize >= cnt and h[8] in (0, 1):
            return 'tbl'
    if size in (768, 1024):
        return 'dat'
    if len(h) >= 20:
        ver, w, hh, act, tag = struct.unpack_from('<iiiii', h, 0)
        if 1 <= ver <= 18 and 0 <= w < 1024 and 0 <= hh < 1024 and size > 20 \
                and (ver < 8 or 0 <= act <= 5) and (ver < 10 or 0 <= tag <= 2) \
                and size >= (w + 1) * (hh + 1) * 4 + 20:
            return 'ds1'
    if len(h) >= 4 and size >= 4:
        cnt = struct.unpack_from('<I', h, 0)[0]
        if cnt == 0 and size == 4:
            return 'bin'
        if 0 < cnt <= 100000 and (size - 4) % cnt == 0 and 1 <= (size - 4) // cnt <= 8192:
            return 'bin'
    sample = h[:512]
    if sample and all(32 <= c < 127 or c in (9, 10, 13) for c in sample):
        return 'txt'
    return 'dat'


# --------------------------------------------------------------------------- archive

FLAG_IMPLODE = 0x00000100
FLAG_COMPRESS = 0x00000200
FLAG_ENCRYPTED = 0x00010000
FLAG_FIX_KEY = 0x00020000
FLAG_PATCH_FILE = 0x00100000
FLAG_SINGLE_UNIT = 0x01000000
FLAG_DELETE_MARKER = 0x02000000
FLAG_SECTOR_CRC = 0x04000000
FLAG_EXISTS = 0x80000000

HASH_EMPTY = 0xFFFFFFFF
HASH_DELETED = 0xFFFFFFFE
MAX_FILE_SIZE = 1 << 30

KEY_HASH_TABLE = hash_string('(hash table)', HASH_KEY)
KEY_BLOCK_TABLE = hash_string('(block table)', HASH_KEY)


class MPQError(Exception):
    pass


@dataclass
class Entry:
    index: int                 # block table index (stable id of the file inside the archive)
    name: str | None
    hash_a: int | None
    hash_b: int | None
    locale: int
    size: int
    csize: int
    flags: int
    pos: int = 0               # absolute file offset of the data

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & FLAG_ENCRYPTED)

    @property
    def compressed(self) -> bool:
        return bool(self.flags & (FLAG_COMPRESS | FLAG_IMPLODE))


class MPQArchive:
    """Read-only MPQ archive.  `entries()`, `read(name_or_entry)`, `contains(name)`."""

    def __init__(self, path, load_names: bool = True):
        self.path = os.fspath(path)
        self._f = open(self.path, 'rb')
        self.file_len = os.fstat(self._f.fileno()).st_size
        self.names: dict[int, str] = {}           # block index -> name
        self._keys: dict[int, int] = {}           # block index -> recovered decryption key
        self.warnings: list[str] = []
        self._open()
        if load_names:
            self.load_known_names()

    # -- io
    def close(self):
        self._f.close()

    def ensure_open(self):
        """Re-open the file after close() (a lazily parsed DT1 of a map that stays open across an install switch
        still reads its remaining tiles)."""
        if self._f.closed:
            self._f = open(self.path, 'rb')

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _pread(self, off: int, n: int) -> bytes:
        if off < 0 or n <= 0 or off >= self.file_len:
            return b''
        n = min(n, self.file_len - off)
        if hasattr(os, 'pread'):
            return os.pread(self._f.fileno(), n, off)
        with _PREAD_LOCK:                  # Windows has no os.pread: positioned read under a lock
            self._f.seek(off)
            return self._f.read(n)

    # -- header and tables
    def _find_header(self):
        step = 0x200
        off = 0
        while off + 32 <= self.file_len:
            m = self._pread(off, 16)
            if m[:4] == b'MPQ\x1a':
                return off
            if m[:4] == b'MPQ\x1b' and len(m) >= 12:
                t = off + struct.unpack_from('<I', m, 8)[0]
                if self._pread(t, 4) == b'MPQ\x1a':
                    return t
            off += step
        raise MPQError(f'{self.path}: no MPQ header')

    def _open(self):
        base = self._find_header()
        raw = self._pread(base, 0x44).ljust(0x44, b'\0')
        hsize, _asize, fmt, shift, hpos, bpos, hcount, bcount = struct.unpack_from('<IIHHIIII', raw, 4)
        self.archive_offset = base
        self.format_version = fmt
        if shift > 16:
            self.warnings.append(f'sector shift {shift} clamped')
            shift &= 0x0F
        self.sector_size = 512 << shift
        hi_block = 0
        if fmt == 1 and hsize >= 0x2C:
            hb = struct.unpack_from('<Q', raw, 0x20)[0]
            hh, bh = struct.unpack_from('<HH', raw, 0x28)
            # only trust the v2 extension when it points inside the file
            if (hh == 0 and bh == 0) and (hb == 0 or base + hb + 2 * bcount <= self.file_len):
                hi_block = hb
        self.hash_count_raw, self.block_count_raw = hcount, bcount
        # Storm (D2 era) computes positions modulo 2^32 relative to the archive start
        habs = (base + hpos) & M32 if self.file_len < (1 << 32) else base + hpos
        babs = (base + bpos) & M32 if self.file_len < (1 << 32) else base + bpos
        hcount = self._clamp_count(habs, hcount, 16, 'hash')
        bcount = self._clamp_count(babs, bcount, 16, 'block')
        hraw = decrypt(self._pread(habs, hcount * 16).ljust(hcount * 16, b'\xff'), KEY_HASH_TABLE)
        braw = decrypt(self._pread(babs, bcount * 16).ljust(bcount * 16, b'\0'), KEY_BLOCK_TABLE)
        self.hashes = [struct.unpack_from('<IIHHI', hraw, i * 16) for i in range(hcount)]  # a, b, locale, platform, block
        his = None
        if hi_block:
            his = struct.unpack_from(f'<{bcount}H', self._pread(base + hi_block, bcount * 2).ljust(bcount * 2, b'\0'))
        self.blocks = []
        for i in range(bcount):
            pos, csize, fsize, flags = struct.unpack_from('<IIII', braw, i * 16)
            if his:
                pos |= his[i] << 32
            self.blocks.append((pos, csize, fsize, flags))
        # hash lookup index: (a, b) -> [(locale, block)]
        self._by_hash: dict[tuple[int, int], list[tuple[int, int]]] = {}
        self._hash_of_block: dict[int, tuple[int, int, int]] = {}
        nb = len(self.blocks)
        for (a, b, loc, _plat, blk) in self.hashes:
            if blk >= HASH_DELETED or blk >= nb:
                continue
            if not self._block_ok(blk):
                continue
            self._by_hash.setdefault((a, b), []).append((loc, blk))
            if blk not in self._hash_of_block or loc == 0:
                self._hash_of_block[blk] = (a, b, loc)
        self.hash_a_set = {k[0] for k in self._by_hash}

    def _clamp_count(self, pos, count, size, what):
        avail = max(0, (self.file_len - pos) // size) if pos < self.file_len else 0
        if count > avail:
            self.warnings.append(f'{what} table: {count} entries clamped to {avail}')
            return avail
        return count

    def _block_ok(self, idx: int) -> bool:
        pos, csize, fsize, flags = self.blocks[idx]
        if not flags & FLAG_EXISTS or flags & FLAG_DELETE_MARKER:
            return False
        if fsize > MAX_FILE_SIZE:
            return False
        start = self._abs(pos)
        return start < self.file_len or fsize == 0

    def _abs(self, pos: int) -> int:
        a = self.archive_offset + pos
        return a & M32 if self.file_len < (1 << 32) and a > M32 else a

    # -- names
    def find(self, name: str) -> int | None:
        """Block index for `name` (locale 0 preferred)."""
        nb = norm_name(name)
        hits = self._by_hash.get((hash_bytes(nb, HASH_A), hash_bytes(nb, HASH_B)))
        if not hits:
            return None
        for loc, blk in hits:
            if loc == 0:
                return blk
        return hits[0][1]

    def match_hashes(self, a: int, b: int):
        """Block indexes whose hash entry has exactly (a, b)."""
        return [blk for _loc, blk in self._by_hash.get((a, b), ())]

    def contains(self, name: str) -> bool:
        return self.find(name) is not None

    def add_name(self, name: str) -> int | None:
        blk = self.find(name)
        if blk is not None:
            self.names.setdefault(blk, name)
        return blk

    def add_names(self, names) -> int:
        """Hash each candidate name; returns how many files got a name."""
        before = len(self.names)
        for n in names:
            self.add_name(n)
        return len(self.names) - before

    def load_known_names(self) -> int:
        """Apply the embedded (listfile) and any cached recovery result (cache/listfiles/)."""
        n = self.add_names(self.listfile())
        try:
            from .names import _load_cache
            n += self.add_names(_load_cache(self) or ())
        except Exception:
            pass
        return n

    def file_count(self) -> int:
        return len(self._hash_of_block)

    def entries(self, include_orphans: bool = False) -> list[Entry]:
        out = []
        for i, (pos, csize, fsize, flags) in enumerate(self.blocks):
            h = self._hash_of_block.get(i)
            if h is None and not (include_orphans and self._block_ok(i)):
                continue
            a, b, loc = h if h else (None, None, 0)
            out.append(Entry(i, self.names.get(i), a, b, loc, fsize, csize, flags, self._abs(pos)))
        return out

    def entry(self, index: int) -> Entry:
        pos, csize, fsize, flags = self.blocks[index]
        a, b, loc = self._hash_of_block.get(index, (None, None, 0))
        return Entry(index, self.names.get(index), a, b, loc, fsize, csize, flags, self._abs(pos))

    # -- keys
    def _key_for(self, e: Entry, name: str | None):
        if name:
            k = hash_string(file_key_name(name), HASH_KEY)
            if e.flags & FLAG_FIX_KEY:
                k = ((k + (e.pos - self.archive_offset)) & M32) ^ e.size
            return k
        if e.index in self._keys:
            return self._keys[e.index]
        k = self.recover_key(e)
        if k is None:
            raise MPQError(f'block {e.index}: encrypted and the key could not be recovered')
        return k

    def base_key(self, e: Entry, key: int) -> int:
        """Undo FIX_KEY: the hash of the file's basename (type 3) that produced `key`."""
        if e.flags & FLAG_FIX_KEY:
            return ((key ^ e.size) - (e.pos - self.archive_offset)) & M32
        return key

    def recover_key(self, e: Entry, head: bytes | None = None):
        """Recover the decryption key of an encrypted file without its name."""
        if not e.encrypted:
            return None
        if e.index in self._keys:
            return self._keys[e.index]
        key = None
        if not (e.flags & FLAG_SINGLE_UNIT) and e.compressed and e.size:
            ns = (e.size + self.sector_size - 1) // self.sector_size
            raw = self._pread(e.pos, (ns + 2) * 4)
            if len(raw) >= 8:
                enc0 = struct.unpack_from('<I', raw, 0)[0]
                for n_ent in ((ns + 1), (ns + 2)):
                    for s1 in recover_seed(enc0, n_ent * 4):
                        tbl = decrypt(raw[:min(len(raw), n_ent * 4)], s1)
                        offs = struct.unpack_from(f'<{len(tbl) // 4}I', tbl)
                        if offs[0] == n_ent * 4 and all(x <= y for x, y in zip(offs, offs[1:])) \
                                and offs[min(ns, len(offs) - 1)] <= e.csize:
                            key = (s1 + 1) & M32
                            break
                    if key is not None:
                        break
        elif e.flags & FLAG_SINGLE_UNIT or not e.compressed:
            key = self._recover_unit_key(e)
        if key is not None:
            self._keys[e.index] = key
        return key

    def _recover_unit_key(self, e: Entry):
        """Best effort for single-unit (or uncompressed) files: guess the first plaintext dword."""
        raw = self._pread(e.pos, min(e.csize, 4096))
        if len(raw) < 8:
            return None
        enc0 = struct.unpack_from('<I', raw, 0)[0]
        guesses = []
        compressed = e.compressed and e.csize < e.size
        if compressed and not e.flags & FLAG_IMPLODE:
            guesses.append(int.from_bytes(b'\x10BZh', 'little'))
            for z in (b'\x02\x78\x9c', b'\x02\x78\xda', b'\x02\x78\x01', b'\x02\x78\x5e'):
                guesses += [int.from_bytes(z + bytes([x]), 'little') for x in range(256)]
        if not compressed:
            for magic in (b'RIFF', b'\x06\0\0\0', b'\x07\0\0\0', b'BIKi', b'SMK2'):
                guesses.append(int.from_bytes(magic, 'little'))
        for g in guesses:
            for s1 in recover_seed(enc0, g):
                head = decrypt(raw[:64], s1)
                try:
                    if compressed:
                        full = self._read_unit_with_key(e, s1)
                        if full is not None:
                            return s1
                    elif self._plain_ok(head, e.size):
                        return s1
                except Exception:
                    continue
        return None

    @staticmethod
    def _plain_ok(head: bytes, size: int) -> bool:
        """More known plaintext than the guessed first dword, so a wrong key is rejected."""
        if len(head) < 16:
            return False
        w = struct.unpack_from('<4I', head)
        if head[:4] == b'RIFF':
            return w[1] == size - 8 and head[8:12] == b'WAVE'
        if w[0] == 6:
            return w[1] in (0, 1, 5) and w[2] == 0
        if w[0] == 7:
            return w[1] == 6
        if head[:3] in (b'BIK', b'SMK'):
            return struct.unpack_from('<I', head, 4)[0] in (size - 8, size)
        return False

    def _read_unit_with_key(self, e, key):
        try:
            data = decrypt(self._pread(e.pos, e.csize), key)
            out = decompress_unit(data, e.size, bool(e.flags & FLAG_IMPLODE))
            return out if len(out) == e.size else None
        except Exception:
            return None

    # -- reading
    def read(self, what, name: str | None = None) -> bytes:
        """Read a file by name, by Entry, or by block index."""
        if isinstance(what, str):
            idx = self.find(what)
            if idx is None:
                raise KeyError(what)
            name = what
            e = self.entry(idx)
        elif isinstance(what, Entry):
            e = what
        else:
            e = self.entry(int(what))
        if name is None:
            name = self.names.get(e.index)
        return self._read_entry(e, name)

    def read_head(self, e: Entry, n: int = 64) -> bytes:
        """First bytes of a file (decodes only the first sector)."""
        return self._read_entry(e, self.names.get(e.index), first_sector_only=True)[:n]

    def _read_entry(self, e: Entry, name: str | None, first_sector_only=False) -> bytes:
        if e.flags & FLAG_PATCH_FILE:
            raise MPQError(f'block {e.index}: patch files are not supported')
        size = e.size
        if size == 0:
            return b''
        if size > MAX_FILE_SIZE:
            raise MPQError(f'block {e.index}: implausible size {size}')
        start = e.pos
        csize = min(e.csize, max(0, self.file_len - start))
        implode = bool(e.flags & FLAG_IMPLODE)
        compressed = bool(e.flags & (FLAG_COMPRESS | FLAG_IMPLODE))
        key = self._key_for(e, name) if e.encrypted else 0
        if e.flags & FLAG_SINGLE_UNIT:
            data = self._pread(start, csize)
            if key:
                data = decrypt(data, key)
            if compressed and e.csize < size:
                data = decompress_unit(data, size, implode)
            if len(data) < size:
                raise MPQError(f'block {e.index}: short read ({len(data)} of {size} bytes)')
            return data[:size]
        ss = self.sector_size
        ns = (size + ss - 1) // ss
        if first_sector_only:
            ns_read = 1
        else:
            ns_read = ns
        if compressed:
            n_ent = ns + 1
            raw = self._pread(start, (ns + 2) * 4)
            tbl = decrypt(raw, (key - 1) & M32) if key else raw
            offs = list(struct.unpack_from(f'<{len(tbl) // 4}I', tbl))
            if len(offs) < n_ent:
                raise MPQError(f'block {e.index}: sector table truncated')
            offs = offs[:n_ent]
            if first_sector_only:
                data = self._pread(start, min(csize, max(offs[0], offs[1])))
            else:
                data = self._pread(start, csize)
        else:
            offs = [min(i * ss, size) for i in range(ns + 1)]
            data = self._pread(start, min(csize, ss) if first_sector_only else csize)
        out = bytearray()
        for i in range(ns_read):
            a, b = offs[i], offs[i + 1]
            want = min(ss, size - i * ss)
            if a > b or b > len(data):
                if b > len(data) and a <= len(data):
                    b = len(data)  # truncated archive: decode what is there
                else:
                    raise MPQError(f'block {e.index}: sector {i} has a bad extent {a:#x}..{b:#x}')
            sec = data[a:b]
            if key:
                sec = decrypt(sec, (key + i) & M32)
            if compressed and len(sec) < want:
                sec = decompress_unit(sec, want, implode)
            if len(sec) < want and not (first_sector_only and i == ns_read - 1 and len(sec) > 0):
                raise MPQError(f'block {e.index}: sector {i} decoded to {len(sec)} of {want} bytes')
            out += sec[:want]
        if not first_sector_only and len(out) != size:
            raise MPQError(f'block {e.index}: short read ({len(out)} of {size} bytes)')
        return bytes(out)

    def ranged(self, what, name: str | None = None) -> 'RangedFile':
        """Random-access view of one stored file (by name, Entry or block index) that decodes only the sectors a
        read touches; see RangedFile."""
        if isinstance(what, str):
            idx = self.find(what)
            if idx is None:
                raise KeyError(what)
            name = what
            e = self.entry(idx)
        elif isinstance(what, Entry):
            e = what
        else:
            e = self.entry(int(what))
        if name is None:
            name = self.names.get(e.index)
        return RangedFile(self, e, name)

    def listfile(self) -> list[str]:
        """Names from the embedded (listfile), if any."""
        idx = self.find('(listfile)')
        if idx is None:
            return []
        try:
            text = self.read(self.entry(idx), '(listfile)').decode('latin-1')
        except Exception:
            return []
        out = []
        for part in text.replace('\r', '\n').replace(';', '\n').split('\n'):
            part = part.strip().strip('\0')
            if part:
                out.append(part)
        return out

    def default_name(self, e: Entry, sniff: bool = True) -> str:
        """Name if known, else unknown/FileNNNNN.<sniffed ext>."""
        n = self.names.get(e.index)
        if n:
            return n
        ext = 'dat'
        if sniff:
            try:
                ext = sniff_ext(self.read_head(e, 512), e.size)
            except Exception:
                ext = 'dat'
        return f'unknown\\File{e.index:05d}.{ext}'


class _SectorCache:
    """Process-wide LRU of decoded sectors, keyed by (archive path, size, mtime, block, sector), bounded in bytes.
    Keys name the archive file, not the MPQArchive object, so a re-opened archive reuses them."""

    def __init__(self, cap: int):
        from collections import OrderedDict
        import threading
        self.cap, self.size = cap, 0
        self._d = OrderedDict()
        self._lock = threading.Lock()

    def get(self, k):
        with self._lock:
            v = self._d.get(k)
            if v is not None:
                self._d.move_to_end(k)
            return v

    def put(self, k, v):
        with self._lock:
            old = self._d.pop(k, None)
            if old is not None:
                self.size -= len(old)
            self._d[k] = v
            self.size += len(v)
            while self.size > self.cap and len(self._d) > 1:
                self.size -= len(self._d.popitem(last=False)[1])


SECTOR_CACHE = _SectorCache(96 << 20)


class _SectorDiskCache:
    """Decoded sectors of compressed files kept on disk across sessions (RangedFile only; off until enabled).
    One append-only file per stored file, under `<archive basename>-<size>-<mtime_ns>/`, of records
    `u32 sector, u32 length, u32 crc32, bytes`; a short or bad record ends the read (it is decoded again). The
    folder is trimmed to `cap` bytes (oldest files first) when enabled."""

    def __init__(self):
        import threading
        self.root = None
        self.cap = 0
        self._lock = threading.Lock()

    def enable(self, root: str, cap: int = 256 << 20):
        self.root, self.cap = root, cap
        try:
            self.trim()
        except OSError:
            pass

    def trim(self):
        files = []
        for d, _dirs, fs in os.walk(self.root):
            for f in fs:
                p = os.path.join(d, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                files.append((st.st_mtime, st.st_size, p))
        total = sum(f[1] for f in files)
        if total <= self.cap:
            return
        files.sort()
        for _mt, size, p in files:
            if total <= self.cap * 0.8:
                break
            try:
                os.remove(p)
                total -= size
            except OSError:
                pass

    def _path(self, rid):
        apath, (asize, amtime), index, pos, csize, size, flags, name = rid
        tag = f'{index}-{pos}-{csize}-{size}-{flags:x}'
        if name is not None:          # encrypted: the key depends on the name
            tag += f'-{zlib.crc32(name.lower().encode("latin-1", "replace")):08x}'
        return os.path.join(self.root, f'{os.path.basename(apath)}-{asize}-{amtime}', tag + '.sec')

    def load(self, rid) -> dict:
        out = {}
        if not self.root:
            return out
        try:
            with open(self._path(rid), 'rb') as fh:
                data = fh.read()
        except OSError:
            return out
        p, n = 0, len(data)
        while p + 12 <= n:
            i, ln, crc = struct.unpack_from('<III', data, p)
            body = data[p + 12:p + 12 + ln]
            if len(body) != ln or zlib.crc32(body) != crc:
                break
            out[i] = body
            p += 12 + ln
        return out

    def append(self, rid, i: int, sec: bytes):
        if not self.root:
            return
        path = self._path(rid)
        rec = struct.pack('<III', i, len(sec), zlib.crc32(sec)) + sec
        with self._lock:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                try:
                    os.write(fd, rec)
                finally:
                    os.close(fd)
            except OSError:
                pass


SECTOR_DISK = _SectorDiskCache()


class RangedFile:
    """Random access to one stored file: `read(off, n)` decodes only the sectors the range touches (one unit for
    single-unit files) and keeps them in SECTOR_CACHE. Sector decoding and every consistency check mirror
    MPQArchive._read_entry, so `read(0, size)` equals `MPQArchive.read()`. Safe from several threads (os.pread)."""

    def __init__(self, arc: MPQArchive, e: Entry, name: str | None = None):
        if e.flags & FLAG_PATCH_FILE:
            raise MPQError(f'block {e.index}: patch files are not supported')
        if e.size > MAX_FILE_SIZE:
            raise MPQError(f'block {e.index}: implausible size {e.size}')
        self.arc, self.e, self.name = arc, e, name
        self.size = e.size
        try:
            st = os.stat(arc.path)
            ident = (st.st_size, st.st_mtime_ns)
        except OSError:
            ident = (arc.file_len, id(arc))
        self._id = (arc.path, ident, e.index, e.pos, e.csize, e.size, e.flags, name if e.encrypted else None)
        self._single = bool(e.flags & FLAG_SINGLE_UNIT) or e.size == 0
        self._ss = e.size if self._single else arc.sector_size
        self._offs = None
        self._key = None
        self._disk = None         # sectors found in SECTOR_DISK (loaded on the first cache miss)

    def _table(self):
        if self._offs is not None:
            return self._offs
        e, arc = self.e, self.arc
        size, ss = e.size, self._ss
        ns = (size + ss - 1) // ss
        if e.compressed:
            raw = arc._pread(e.pos, (ns + 2) * 4)
            key = self._key_for()
            tbl = decrypt(raw, (key - 1) & M32) if key else raw
            offs = list(struct.unpack_from(f'<{len(tbl) // 4}I', tbl))
            if len(offs) < ns + 1:
                raise MPQError(f'block {e.index}: sector table truncated')
            offs = offs[:ns + 1]
        else:
            offs = [min(i * ss, size) for i in range(ns + 1)]
        self._offs = offs
        return offs

    def _key_for(self):
        if self._key is None:
            self._key = self.arc._key_for(self.e, self.name) if self.e.encrypted else 0
        return self._key

    def _sector(self, i: int) -> bytes:
        ck = self._id + (i,)
        got = SECTOR_CACHE.get(ck)
        if got is not None:
            return got
        if SECTOR_DISK.root and self.e.compressed:
            if self._disk is None:
                self._disk = SECTOR_DISK.load(self._id)
            got = self._disk.get(i)
            want = self.e.size if self._single else min(self._ss, self.e.size - i * self._ss)
            if got is not None and len(got) == want:
                SECTOR_CACHE.put(ck, got)
                return got
        e, arc = self.e, self.arc
        arc.ensure_open()
        if self._single:
            sec = arc._read_entry(e, self.name)
        else:
            ss, size = self._ss, e.size
            offs = self._table()
            csize = min(e.csize, max(0, arc.file_len - e.pos))
            a, b = offs[i], offs[i + 1]
            want = min(ss, size - i * ss)
            if a > b or b > csize:
                if b > csize and a <= csize:
                    b = csize
                else:
                    raise MPQError(f'block {e.index}: sector {i} has a bad extent {a:#x}..{b:#x}')
            sec = arc._pread(e.pos + a, b - a) if b > a else b''
            key = self._key_for()
            if key:
                sec = decrypt(sec, (key + i) & M32)
            if e.compressed and len(sec) < want:
                sec = decompress_unit(sec, want, bool(e.flags & FLAG_IMPLODE))
            if len(sec) < want:
                raise MPQError(f'block {e.index}: sector {i} decoded to {len(sec)} of {want} bytes')
            sec = bytes(sec[:want])
        SECTOR_CACHE.put(ck, sec)
        if SECTOR_DISK.root and e.compressed:
            SECTOR_DISK.append(self._id, i, sec)
        return sec

    def read(self, off: int, n: int) -> bytes:
        """Bytes [off, off+n) clipped to the file."""
        end = min(off + n, self.size)
        if off < 0 or end <= off:
            return b''
        ss = self._ss
        first, last = off // ss, (end - 1) // ss
        if first == last:
            s = self._sector(first)
            return s[off - first * ss:end - first * ss]
        out = bytearray()
        for i in range(first, last + 1):
            s = self._sector(i)
            out += s[max(0, off - i * ss):end - i * ss]
        return bytes(out)


class MPQStack:
    """Several archives searched in priority order (first = highest priority)."""

    def __init__(self, paths):
        self.archives = [p if isinstance(p, MPQArchive) else MPQArchive(p) for p in paths]

    def find(self, name: str):
        for a in self.archives:
            idx = a.find(name)
            if idx is not None:
                return a, idx
        return None

    def contains(self, name: str) -> bool:
        return self.find(name) is not None

    def read(self, name: str) -> bytes:
        hit = self.find(name)
        if hit is None:
            raise KeyError(name)
        a, idx = hit
        return a.read(a.entry(idx), name)

    def list(self) -> list[str]:
        seen = {}
        for a in self.archives:
            for e in a.entries():
                n = a.names.get(e.index)
                if n:
                    seen.setdefault(n.lower().replace('/', '\\'), n)
        return sorted(seen.values(), key=str.lower)

    def close(self):
        for a in self.archives:
            a.close()


def default_archive_order(game_dir, lang=None) -> list[str]:
    """Archive search order (highest priority first) the way the game builds it. See docs/MODDING_PIPELINE.md.

    Open sequence and Storm priority (confirmed by code):
      vanilla 1.13c D2Win OpenMpqArchives 0x6f8eaa20 / 1.14d Game.exe 0x4fab90:
        d2data, d2sfx, d2speech, d2delta, d2kfixup @1000, patch_d2 @5000, d2exp @3000;
      Median (D2Sigma FUN_10046a20 replaces OpenMpqArchives via a jmp patch at D2Win+0xaa20):
        list 0x101d8388: d2data, d2sfx, d2speech, d2delta, d2kfixup @1000, d2exp @3000, patch_d2 @5000;
        then every medianxl-*.mpq in the current directory @6000 (FindFirstFileExW order),
        lang-<x>.mpq @7000 (only with the -lang <x> switch), font.mpq @8000;
      then, both (stock D2Win 0x6f8ea890 / Game.exe 0x4faec0): d2char, d2music @1000,
        LoD only d2xmusic, d2xtalk, d2xvideo @3000. d2video @1000 is opened on demand (0x6f8ea820).
    Ties: Storm SFileOpenArchive (0x6f62a0b0) links a new archive in front of the first one whose
    priority is <= its own, and SFileOpenFile searches from the head, so among equal priorities the
    archive opened LAST is searched FIRST.
    medianxl-* enumeration order is whatever FindNextFileW returns. We assume NTFS collation
    (case-insensitive, upper-cased) - an ASSUMPTION; under Wine it depends on the host directory.
    Missing files are skipped; names match case-insensitively."""
    game_dir = os.fspath(game_dir)
    try:
        files = os.listdir(game_dir)
    except OSError:
        return []
    low = {f.lower(): f for f in files}
    median = sorted((f for f in files if f.lower().startswith('medianxl-') and f.lower().endswith('.mpq')),
                    key=str.upper)
    base = ['d2data', 'd2sfx', 'd2speech', 'd2delta', 'd2kfixup']
    if median:      # D2Sigma's list, then its own archives
        seq = [(n, 1000) for n in base] + [('d2exp', 3000), ('patch_d2', 5000)]
        seq += [(f[:-4], 6000) for f in median]
        if lang:
            seq.append(('lang-%s' % lang, 7000))
        seq.append(('font', 8000))
    else:
        seq = [(n, 1000) for n in base] + [('patch_d2', 5000), ('d2exp', 3000)]
    seq += [('d2char', 1000), ('d2music', 1000)]
    if 'd2exp.mpq' in low:
        seq += [('d2xmusic', 3000), ('d2xtalk', 3000), ('d2xvideo', 3000)]
    seq.append(('d2video', 1000))
    # d2gl.mpq (third-party renderer) is not game data and is not listed.
    opened = [(prio, i, low[(n + '.mpq').lower()]) for i, (n, prio) in enumerate(seq)
              if (n + '.mpq').lower() in low]
    opened.sort(key=lambda t: (-t[0], -t[1]))      # higher priority first; ties: last opened first
    return [os.path.join(game_dir, f) for _, _, f in opened]
