"""Companion files of a character - docs/SAVE_FORMAT.md, section 8.

<name>.key   key bindings (vanilla Diablo II format; Sigma keeps its own bindings in preferences.json)
<name>.map   the seeds of the last four games, a ring buffer that names the .ma0 - .ma3 files
<name>.maN   automap cache of the game whose seed is entry N of <name>.map

These are understood from the samples only. KeyFile and MapFile are parsed into fields and rebuilt from them;
AutomapFile keeps the file bytes and only indexes them (its block contents are not decoded).
"""
import struct
from dataclasses import dataclass, field

from .bits import FormatError


@dataclass
class KeyBinding:
    function: int       # 0..56, the game's key function number (0 character screen, 1 inventory, ...)
    key: int            # Windows virtual-key code; 0x100+ mouse buttons / wheel; 0xFFFF = not bound
    slot: int           # 1 on one of the two entries of each function, 0 on the other


@dataclass
class KeyFile:
    """u16 version (0x25) + 114 records of 10 bytes: u32 function, u16 key, u32 slot (two per function).
    The game's default.key has the same records behind a 6-byte header: 'WS', u16 0x25, u16 file size."""
    version: int = 0x25
    bindings: list = field(default_factory=list)
    default_header: bool = False

    @classmethod
    def parse(cls, b):
        start = 0
        default_header = b[:2] == b'WS'
        if default_header:
            start = 2
            if struct.unpack_from('<H', b, 4)[0] != len(b):
                raise FormatError('.key: size field does not match')
        version = struct.unpack_from('<H', b, start)[0]
        body = start + (4 if default_header else 2)
        if (len(b) - body) % 10:
            raise FormatError('.key: the records do not fill the file')
        recs = [KeyBinding(*struct.unpack_from('<IHI', b, o)) for o in range(body, len(b), 10)]
        return cls(version, recs, default_header)

    def to_bytes(self):
        body = b''.join(struct.pack('<IHI', r.function, r.key, r.slot) for r in self.bindings)
        if self.default_header:
            return b'WS' + struct.pack('<HH', self.version, 6 + len(body)) + body
        return struct.pack('<H', self.version) + body

    def as_dict(self, tables=None):
        return dict(kind='key', version=self.version, bindings=[r.__dict__ for r in self.bindings])


@dataclass
class MapFile:
    """24 bytes: u32 12 (constant in the samples), u32 next slot to overwrite (0..3), 4 x u32 game seeds.
    Slot N belongs to the file <name>.maN; the newest seed (slot next - 1) equals header 0xAB of the .d2s."""
    lead: int = 12
    next_slot: int = 0
    seeds: list = field(default_factory=lambda: [0, 0, 0, 0])
    extra: bytes = b''

    @classmethod
    def parse(cls, b):
        if len(b) < 24:
            raise FormatError('.map: 24 bytes expected')
        v = struct.unpack_from('<6I', b, 0)
        return cls(v[0], v[1], list(v[2:]), bytes(b[24:]))

    def to_bytes(self):
        return struct.pack('<6I', self.lead, self.next_slot, *self.seeds) + self.extra

    def newest_seed(self):
        return self.seeds[(self.next_slot - 1) % 4]

    def as_dict(self, tables=None):
        return dict(kind='map', lead=self.lead, next_slot=self.next_slot, seeds=self.seeds,
                    newest_seed=self.newest_seed())


@dataclass
class AutomapFile:
    """<name>.maN. A 4096-byte table of 1024 u32 file offsets indexed by level id (levels.bin row; entries past
    the level count hold uninitialised memory), then one block per visited level, appended in visit order.
    A block starts with: u32 ?, u32 level id, u32 ?, u32 seed, u32 ?, ... (rest not decoded)."""
    raw: bytes = b''

    @classmethod
    def parse(cls, b):
        if len(b) < 4096:
            raise FormatError('.maN: shorter than its offset table')
        return cls(bytes(b))

    def to_bytes(self):
        return self.raw

    def levels(self):
        """{level id: (offset, size)} of the blocks whose header carries the level id of their table index."""
        table = struct.unpack_from('<1024I', self.raw, 0)
        ok = {i: off for i, off in enumerate(table)
              if 4096 <= off <= len(self.raw) - 8 and struct.unpack_from('<I', self.raw, off + 4)[0] == i}
        starts = sorted(ok.values()) + [len(self.raw)]
        return {i: (off, starts[starts.index(off) + 1] - off) for i, off in sorted(ok.items())}

    def as_dict(self, tables=None):
        lv = self.levels()
        return dict(kind='automap', size=len(self.raw),
                    levels=[dict(level=i, offset=o, size=s, head=self.raw[o:o + 20].hex()) for i, (o, s) in lv.items()])
