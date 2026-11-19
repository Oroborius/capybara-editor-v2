"""Runeword mods with all 13 property slots of Median XL's runes.bin.

Median XL's runes.bin rows are 384 bytes with 13 property slots (4 x i32: prop, param, min, max) from +176; vanilla
has 7. The collector's mxl_data.Data._load_runewords reads +192..+304 only (slots 2-8), so Data.runeword_mods lost
slot 1 (on every Sigma runeword: pr85 = stat 372 "Equipped runeword amount") and slots 9-13 (Rebel: 12 mods, 7
read). The Creator builds a runeword's stats from runeword_mods, so created runewords lacked those stats.

install() wraps _load_runewords: the host builds runewords as before, then runeword_mods is rebuilt from the same
rows with every slot, in the host's record format ({'prop', 'param', 'min', 'max'}, empty slots (prop < 0)
skipped). Rows of another size (vanilla 288) keep the host's list."""
import struct

FIRST = 176          # slot 1
SLOTS = 13
ROW = 384


def mods_of(row):
    return [dict(zip(('prop', 'param', 'min', 'max'), m))
            for m in struct.iter_unpack('<4i', row[FIRST:FIRST + 16 * SLOTS]) if m[0] >= 0]


def install():
    import mxl_data
    D = mxl_data.Data
    orig = D._load_runewords
    if getattr(orig, '_all_slots', False):
        return

    def _load_runewords(self, *a, **k):
        res = orig(self, *a, **k)
        try:
            rows = self._rows('runes')
            if rows and len(rows) == len(self.runeword_mods) and all(len(r) == ROW for r in rows):
                self.runeword_mods = [mods_of(r) for r in rows]
        except Exception:
            pass
        return res

    _load_runewords._all_slots = True
    D._load_runewords = _load_runewords
