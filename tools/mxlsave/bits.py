"""Bit streams, least significant bit first (the order of every bit field in a Diablo II save)."""


class FormatError(Exception):
    """The bytes are not what the format description expects."""


class BitReader:
    """Reads fields of n bits from `data`, starting at byte `start`. `pos` is the bit position from `start`."""

    def __init__(self, data, start=0, end=None):
        chunk = bytes(data[start:end])
        self._v = int.from_bytes(chunk, 'little')
        self.nbits = len(chunk) * 8
        self.pos = 0

    def read(self, n):
        if self.pos + n > self.nbits:
            raise FormatError('read past the end of the data')
        v = (self._v >> self.pos) & ((1 << n) - 1)
        self.pos += n
        return v

    def bytes_used(self):
        return (self.pos + 7) // 8

    def read_padding(self):
        """Reads the bits up to the next byte boundary (0 to 7 bits) and returns their value."""
        n = -self.pos % 8
        return self.read(n) if n else 0


class BitWriter:
    def __init__(self):
        self._v = 0
        self.pos = 0

    def write(self, n, value):
        if value < 0 or value >> n:
            raise FormatError(f'value {value} does not fit in {n} bits')
        self._v |= value << self.pos
        self.pos += n

    def write_padding(self, value=0):
        n = -self.pos % 8
        if n:
            self.write(n, value)

    def to_bytes(self):
        return self._v.to_bytes((self.pos + 7) // 8, 'little')
