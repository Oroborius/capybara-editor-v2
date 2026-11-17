"""Stash files: <name>.stash (personal) and _sharedstash.shared (account wide) - docs/SAVE_FORMAT.md, section 7.

    0x00  u32  version, 1 in every sample
    0x04  u32  page shown last in game (0-based)
    then one section per NON-EMPTY page, in page order:
          'STASH' (5 bytes)  u32 page number  'JM'  u16 item count  items (socketed items after their owner)

There is no page count, no page name and no gold field: empty pages are simply absent, and the stash gold is
character stat 15 in the .d2s. No checksum, no file size.
"""
import struct
from dataclasses import dataclass, field
from typing import Optional

from .bits import FormatError
from .items import parse_item_list, build_item_list


@dataclass
class Page:
    number: int
    items: Optional[list] = None        # [Item]; None when parsed without tables
    raw: Optional[bytes] = None         # without tables: the page's bytes after its 'JM' + count
    count: int = 0


@dataclass
class Stash:
    version: int = 1
    last_page: int = 0
    pages: list = field(default_factory=list)

    @classmethod
    def parse(cls, b, tables=None):
        if len(b) < 8:
            raise FormatError('stash: shorter than its 8-byte header')
        version, last_page = struct.unpack_from('<II', b, 0)
        self = cls(version, last_page)
        p = 8
        while p < len(b):
            if b[p:p + 5] != b'STASH':
                raise FormatError(f"'STASH' expected at byte {p}")
            number = struct.unpack_from('<I', b, p + 5)[0]
            if b[p + 9:p + 11] != b'JM':
                raise FormatError(f"'JM' expected at byte {p + 9}")
            count = struct.unpack_from('<H', b, p + 11)[0]
            if tables:
                items, p = parse_item_list(b, p + 13, count, tables)
                self.pages.append(Page(number, items, None, count))
            else:                       # cannot delimit items: the page ends at the next 'STASH' marker
                q = b.find(b'STASH', p + 13)
                q = len(b) if q < 0 else q
                self.pages.append(Page(number, None, bytes(b[p + 13:q]), count))
                p = q
        return self

    def to_bytes(self, tables=None):
        out = bytearray(struct.pack('<II', self.version, self.last_page))
        for pg in self.pages:
            out += b'STASH' + struct.pack('<I', pg.number)
            if pg.items is not None:
                if tables is None:
                    raise FormatError('the item sections need the game tables')
                out += build_item_list(pg.items, tables)
            else:
                out += b'JM' + struct.pack('<H', pg.count) + pg.raw
        return bytes(out)

    def as_dict(self, tables=None):
        return dict(kind='stash', version=self.version, last_page=self.last_page,
                    pages=[dict(number=p.number, count=p.count,
                                items=None if p.items is None else [i.as_dict(tables) for i in p.items])
                           for p in self.pages])
