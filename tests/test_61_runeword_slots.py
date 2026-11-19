"""Runeword mods read from all 13 property slots of Median XL's runes.bin (384-byte rows, slots from +176). The
collector read slots 2-8 only (+192..+304): slot 1 (pr85 = stat 372 "Equipped runeword amount" on every Sigma
runeword) and slots 9-13 were missing from Data.runeword_mods, so created runewords lacked them.
src/mxl_runes_fix.py rebuilds runeword_mods with every slot."""
import struct

import capytest as T

MODE = 'engine'
NEEDS = ('user',)


def rw_row(E, name):
    return next(i for i, r in enumerate(E.data.runewords) if r[0] == name)


def slot_props(E, row):
    r = E.data._rows('runes')[row]
    return [m[0] for m in struct.iter_unpack('<4i', r[176:176 + 16 * 13]) if m[0] >= 0]


@T.test
def runeword_mods_have_every_slot():
    E = T.engine()
    d = E.data
    T.eq(len(d._rows('runes')[0]), 384, 'runes.bin row size')
    # runes.txt: Rebel pr85 pr87 pr76 pr131 pr80 pr82 pr94 pr86 pr146 pr112 pr18 pr15; Thelema 9 slots
    T.eq([m['prop'] for m in d.runeword_mods[rw_row(E, 'Rebel')]],
         [85, 87, 76, 131, 80, 82, 94, 86, 146, 112, 18, 15], 'Rebel mods')
    T.eq([m['prop'] for m in d.runeword_mods[rw_row(E, 'Thelema')]],
         [85, 94, 221, 76, 83, 433, 125, 90, 108], 'Thelema mods')
    bad = [n for i, (n, *_r) in enumerate(d.runewords) if [m['prop'] for m in d.runeword_mods[i]] != slot_props(E, i)]
    T.eq(bad, [], 'runewords whose mods are not their 13 runes.bin slots')
    T.eq(sorted(d.runeword_mods[rw_row(E, 'Rebel')][0]), ['max', 'min', 'param', 'prop'], 'record keys')


@T.test
def created_rebel_carries_slot_1_and_slot_9_up():
    E = T.engine()
    cr, d = E.cr, E.data
    row = rw_row(E, 'Rebel')
    bases = cr.runeword_bases(row)
    T.check(bases, 'no base for Rebel')
    spec = cr.new_spec('runeword', bases[0].code, row)
    spec['sockets'] = len(d.runewords[row][1])
    spec['ilvl'] = 99
    cr.roll(spec, 'max')
    rec, _size = E.C.decode_item(bytes(cr.build(spec)[0]), d)
    have = {s['id'] for k in ('stats', 'stats_runeword') for s in rec.get(k) or ()}
    T.check(372 in have, f'stat 372 (slot 1, Equipped runeword amount) missing: {sorted(have)}')
    mods = d.runeword_mods[row]
    for m in mods[8:]:
        want = [s['id'] for s in E.C.mods_stats([(m['prop'], m['param'], m['min'], m['max'])], d, 'min')]
        T.check(want and set(want) <= have, f'slot-9+ prop {m["prop"]} stats {want} missing: {sorted(have)}')


T.main(globals())
