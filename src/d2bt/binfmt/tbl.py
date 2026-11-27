"""Classic D2 string tables (.tbl): read and write, hash table included.

Layout (all little endian):
    0x00 u16 crc        CRC-16/CCITT over the string data [X, S)
    0x02 u16 H          number of strings (ID table entries)
    0x04 u32 N          hash node count (modulus)
    0x08 u8  version    (1 in shipped files)
    0x09 u32 X          offset of string data
    0x0D u32 P          longest probe chain + 1
    0x11 u32 S          file size
    0x15 u16[H]         ID table: string id -> node slot
    N x 17-byte nodes:  u8 used, u16 id, u32 hash, u32 key_off, u32 text_off, u16 text_len+1
    string data (latin-1, NUL terminated)

String ids: string.tbl = 0.., patchstring.tbl = 10000.., expansionstring.tbl = 20000..
"""
import struct

HEADER = 0x15
NODE = 17

# base string id of each classic table
TBL_BASE = {'string': 0, 'patchstring': 10000, 'expansionstring': 20000}


def key_hash(key: bytes, modulus: int) -> int:
    h = 0
    for b in key:
        h = ((h << 4) + b) & 0xFFFFFFFF
        if h & 0xF0000000:
            h = (((h & 0xF0000000) >> 24) ^ h) & 0x0FFFFFFF
    return h % modulus if modulus else 0


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def _cstr(data, off):
    end = data.find(b'\0', off)
    if end < 0:
        end = len(data)
    return data[off:end].decode('latin-1')


def pretty(s: str) -> str:
    """latin-1 string -> UTF-8 decoded when the bytes are valid UTF-8."""
    if s.isascii():
        return s
    try:
        return s.encode('latin-1').decode('utf-8')
    except UnicodeError:
        return s


class Tbl:
    """A string table: ordered list of (key, text); index = string id - base."""

    def __init__(self, entries=None, hash_size=0, version=1):
        self.entries = list(entries or [])
        self.hash_size = hash_size
        self.version = version

    # ------------------------------------------------------------------ read
    @classmethod
    def parse(cls, data: bytes) -> 'Tbl':
        if len(data) < HEADER:
            raise ValueError('tbl: truncated header')
        _crc, count, nodes, version, _x, _p, _s = struct.unpack_from('<HHIBIII', data, 0)
        ids = struct.unpack_from('<%dH' % count, data, HEADER)
        nstart = HEADER + count * 2
        if nstart + nodes * NODE > len(data):
            raise ValueError('tbl: node table runs past end of file')
        entries = []
        for slot in ids:
            if slot >= nodes:
                entries.append(('', ''))
                continue
            o = nstart + slot * NODE
            used, _idx, _h, koff, toff, _tl = struct.unpack_from('<BHIIIH', data, o)
            if not used or koff >= len(data) or toff >= len(data):
                entries.append(('', ''))
                continue
            entries.append((_cstr(data, koff), _cstr(data, toff)))
        return cls(entries, nodes, version)

    @classmethod
    def load(cls, path) -> 'Tbl':
        with open(path, 'rb') as fh:
            return cls.parse(fh.read())

    def key(self, i):
        return self.entries[i][0] if 0 <= i < len(self.entries) else None

    def text(self, i):
        return self.entries[i][1] if 0 <= i < len(self.entries) else None

    def lookup(self, key):
        for k, t in self.entries:
            if k == key:
                return t
        return None

    # ----------------------------------------------------------------- write
    def to_bytes(self) -> bytes:
        n = len(self.entries)
        if n > 0xFFFF:
            raise ValueError('tbl: more than 65535 strings')
        size = max(self.hash_size, n, 1)
        node = [None] * size
        slot_of = [0] * n
        maxp = 0
        keys = [k.encode('latin-1') for k, _ in self.entries]
        texts = [t.encode('latin-1') for _, t in self.entries]
        for i, k in enumerate(keys):
            s = key_hash(k, size)
            probes = 0
            while node[s] is not None:
                s = (s + 1) % size
                probes += 1
            maxp = max(maxp, probes + 1)
            node[s] = i
            slot_of[i] = s
        data_start = HEADER + n * 2 + size * NODE
        blob = bytearray()
        offs = []
        for k, t in zip(keys, texts):
            ko = data_start + len(blob)
            blob += k + b'\0'
            to = data_start + len(blob)
            blob += t + b'\0'
            offs.append((ko, to))
        total = data_start + len(blob)
        out = bytearray(struct.pack('<HHIBIII', 0, n, size, self.version, data_start, maxp, total))
        out += struct.pack('<%dH' % n, *slot_of)
        for i in node:
            if i is None:
                out += bytes(NODE)
            else:
                out += struct.pack('<BHIIIH', 1, i, key_hash(keys[i], size), offs[i][0],
                                   offs[i][1], len(texts[i]) + 1)
        out += blob
        struct.pack_into('<H', out, 0, crc16(bytes(out[data_start:])))
        return bytes(out)

    def save(self, path):
        with open(path, 'wb') as fh:
            fh.write(self.to_bytes())

    # ------------------------------------------------------------------- txt
    def to_txt(self) -> str:
        """'key<TAB>text' lines in id order; newlines written as \\n.

        Strings are kept as latin-1 internally (byte exact).  Text that is valid
        UTF-8 (Median XL stores its colour codes that way) is shown decoded."""
        return ''.join('%s\t%s\n' % (pretty(k), pretty(t).replace('\n', '\\n'))
                       for k, t in self.entries)

    @classmethod
    def from_txt(cls, text: str, hash_size=0, utf8=True) -> 'Tbl':
        """Inverse of to_txt.  utf8=True stores non-ASCII text as UTF-8 bytes."""
        ents = []
        for line in text.splitlines():
            if not line:
                continue
            k, _, t = line.partition('\t')
            t = t.replace('\\n', '\n')
            if utf8:
                k = k.encode('utf-8').decode('latin-1')
                t = t.encode('utf-8').decode('latin-1')
            ents.append((k, t))
        return cls(ents, hash_size)


class StringSet:
    """The three classic tables merged by string id (for KEYTOWORD lookups)."""

    def __init__(self):
        self.tables = {}   # base -> Tbl

    def add(self, name_or_base, tbl):
        base = TBL_BASE.get(name_or_base, name_or_base) if isinstance(name_or_base, str) \
            else name_or_base
        self.tables[base] = tbl

    def _find(self, sid):
        for base in sorted(self.tables, reverse=True):
            if sid >= base:
                t = self.tables[base]
                if sid - base < len(t.entries):
                    return t.entries[sid - base]
                return None
        return None

    def key(self, sid):
        e = self._find(sid)
        return e[0] if e else None

    def text(self, sid):
        e = self._find(sid)
        return e[1] if e else None

    def text_by_key(self, key):
        # patch > expansion > string priority, like the game
        for base in (10000, 20000, 0):
            t = self.tables.get(base)
            if t:
                v = t.lookup(key)
                if v is not None:
                    return v
        return None

    def __bool__(self):
        return bool(self.tables)
