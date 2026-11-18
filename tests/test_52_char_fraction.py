"""F8 (docs/review/save-safety.md): life / mana / stamina keep 1/256 points. Changing one and typing the old whole
number back gives the stored fraction back (it was dropped), so such an edit + its revert saves the same bytes."""
import glob
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')
KEYS = ('life_cur', 'life_max', 'mana_cur', 'mana_max', 'stamina_cur', 'stamina_max')


@T.test
def retyping_the_old_whole_number_keeps_the_fraction():
    E = T.engine()
    MC = E.MC
    folder = T.fresh_saves(1)
    path = sorted(glob.glob(os.path.join(folder, '*.d2s')))[0]
    ch = MC.Character(path, E.data)
    for key in KEYS:                                   # a fraction in every field, saved
        fd = ch.stat_field(key)
        w = max(fd.min + 2, min(fd.max - 2, ch.field(key) if hasattr(ch, 'field') else 100))
        ch.set_field_raw(key, (w << 8) + 37)
    ch.save(backup=False)
    saved = T.read(path)
    for key in KEYS:
        ch = MC.Character(path, E.data)
        sid = MC._FIELD[key][1]
        raw = ch.stat(sid)
        T.eq(raw & 0xFF, 37, f'{key}: fraction in the file')
        w = raw >> 8
        fd = ch.stat_field(key)
        ch.set_field(key, w + 1 if w + 1 <= fd.max else w - 1)
        ch.set_field(key, w)
        T.eq(ch.stat(sid), raw, f'{key}: stored value after {w}+-1 and back to {w}')
        ch.save(backup=False)
        T.check(T.read(path) == saved, f'{key}: the file after the edit and its revert is not the same')
    # after a save, the saved value is the one kept (not the fraction of an older read)
    ch = MC.Character(path, E.data)
    sid = MC._FIELD['life_max'][1]
    w = ch.stat(sid) >> 8
    ch.set_field('life_max', w + 1)
    ch.save(backup=False)
    ch.set_field('life_max', w)
    T.eq(ch.stat(sid), w << 8, 'after a save: the saved whole number has no fraction to bring back')


T.main(globals())
