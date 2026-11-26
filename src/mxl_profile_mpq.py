"""Bounded MPQ lookups for folder profiles, including archives with no empty hash slots."""

from bisect import bisect_left
import mmap
import os
import struct

import mpq
from mpq import MPQ, hs


def _open_archive(path, flags):
    if os.name != 'nt':
        return os.open(path, flags)

    import _winapi
    import msvcrt

    handle = _winapi.CreateFile(os.fsdecode(path), 0x80000000, 7, 0, 3, 0x80, 0)
    # GENERIC_READ, share read/write/delete, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL.
    try:
        return msvcrt.open_osfhandle(handle, flags)
    except OSError:
        _winapi.CloseHandle(handle)
        raise


class ProfileMPQ(MPQ):
    def __init__(self, path):
        with open(path, 'rb', opener=_open_archive) as archive:
            magic, header_size, _, _, shift, hashes, blocks, nh, nb = struct.unpack(
                '<4sIIHHIIII', archive.read(32))
            size = os.fstat(archive.fileno()).st_size
            if (magic != b'MPQ\x1a' or header_size < 32 or shift > 15
                    or not 0 < nh <= 262144 or nb > 262144
                    or hashes + nh * 16 > size or blocks + nb * 16 > size):
                raise ValueError('unsupported MPQ header or oversized archive index')
            self.f = mmap.mmap(archive.fileno(), 0, access=mmap.ACCESS_READ)
        self.sector = 512 << shift
        self.hn = nh
        self.ht = mpq.decrypt(self.f[hashes:hashes + nh * 16], hs('(hash table)', 3))
        self.bt = mpq.decrypt(self.f[blocks:blocks + nb * 16], hs('(block table)', 3))
        self.hashes = list(struct.iter_unpack('<IIHHI', self.ht))
        self.blocks = list(struct.iter_unpack('<IIII', self.bt))
        self._empty = []
        self._entries = {}
        for pos, (a, b, _, _, block) in enumerate(self.hashes):
            if block == 0xffffffff:
                self._empty.append(pos)
            elif block < nb:
                self._entries.setdefault((a, b), []).append(pos)

    def find(self, name):
        positions = self._entries.get((hs(name, 1), hs(name, 2)))
        if not positions:
            return None
        start = hs(name, 0) % self.hn
        pos = positions[bisect_left(positions, start) % len(positions)]
        if self._empty:
            stop = self._empty[bisect_left(self._empty, start) % len(self._empty)]
            if (stop - start) % self.hn <= (pos - start) % self.hn:
                return None
        return self.hashes[pos][4]

    def read(self, name):
        block = self.find(name)
        if block is None:
            return None
        offset, compressed, expanded, _ = self.blocks[block]
        if max(compressed, expanded) > 32 * 1024 * 1024 or offset + compressed > len(self.f):
            raise ValueError(f'invalid or oversized MPQ member {name}')
        return super().read(name)
