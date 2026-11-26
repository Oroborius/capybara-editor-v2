"""Bounded MPQ lookups for folder profiles, including archives with no empty hash slots."""

from bisect import bisect_left
import os
import struct

from mpq import MPQ, hs


class ProfileMPQ(MPQ):
    def __init__(self, path):
        with open(path, 'rb') as archive:
            magic, header_size, _, _, shift, hashes, blocks, nh, nb = struct.unpack(
                '<4sIIHHIIII', archive.read(32))
            size = os.fstat(archive.fileno()).st_size
        if (magic != b'MPQ\x1a' or header_size < 32 or shift > 15
                or not 0 < nh <= 262144 or nb > 262144
                or hashes + nh * 16 > size or blocks + nb * 16 > size):
            raise ValueError('unsupported MPQ header or oversized archive index')
        super().__init__(path)
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
