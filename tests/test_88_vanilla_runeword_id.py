"""Vanilla 1.14d runeword field of created items: the game stores the string-table index of the runes row's Name key
('RunewordN'), read as a 12-bit id + a 4-bit table part (patchstring 10000+ wins over expansionstring 20000+:
Delirium 10910 = 2718 + 2 << 12, Spirit 20635 = 155 + 5 << 12). The creator used to look the runeword's display
name up as a key (no hit for most rows, so Insight / Enigma / Delirium were missing from the list, and a wrong index
for names that collide with other keys, e.g. Spirit). Median XL keeps its own path (tests 15 / 61).
Needs only the vanilla install (MXL_TEST_VANILLA_GAME); skipped without it."""
import os
import sys

import capytest as T

MODE = 'engine'
NEEDS = ()

GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')
NAMES = ('Spirit', 'Insight', 'Enigma', 'Delirium', 'Call to Arms', 'Steel')
_E = None


def engine():
    global _E
    if _E is not None:
        return _E
    if not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        T.skip(f'no vanilla 1.14d install ({GAME})')
    user = T.guard(os.path.join(T.tmp(), 'v88user'), 'user folder')
    saves = T.guard(os.path.join(T.tmp(), 'v88saves'), 'save folder')
    os.makedirs(user, exist_ok=True)
    os.makedirs(saves, exist_ok=True)
    os.environ.update(MXL_USER_DIR=user, MXL_SAVE_DIR=saves, MXL_GAME='vanilla', MXL_GAME_DIR=GAME)
    os.environ.setdefault('LOCALAPPDATA', T.tmp())
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import paths
    T.guard(paths.USER_DIR, 'paths.USER_DIR')
    out = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        import mxl_free
        import mxl_format_fix
        mxl_free.install()
        mxl_format_fix.install()
        import mxl_profile
        mxl_profile.install()
    finally:
        sys.stdout = out
    import mxl_data
    import mxl_creator
    import mxl_profile
    T.check(not mxl_profile.is_median(), 'vanilla profile active')
    d = mxl_data.Data(paths.DATA_DIR)
    _E = T.NS(data=d, C=mxl_creator, cr=mxl_creator.Creator(d), fix=mxl_format_fix)
    return _E


def _row(E, name):
    return next(i for i, r in enumerate(E.data.runewords) if r[0] == name)


def _game_index(E, key):
    """Independent lookup: the game's string index of `key` (patchstring, then expansionstring, then string)."""
    hits = [i for i, v in E.data.strings.items() if isinstance(v, tuple) and v[0] == key]
    for lo, hi in ((10000, 20000), (20000, 1 << 16), (0, 10000)):
        inside = [i for i in hits if lo <= i < hi]
        if inside:
            return inside[0]
    return None


@T.test
def known_vanilla_runeword_ids():
    E = engine()
    cr = E.cr
    T.eq(cr.rw_string_id(_row(E, 'Delirium')), 2718 | 2 << 12, 'Delirium (patchstring Runeword22)')
    T.eq(cr.rw_string_id(_row(E, 'Spirit')), 155 | 5 << 12, 'Spirit (expansionstring Runeword130)')
    listed = {n for _i, n, _r in cr.runewords()}
    T.check(set(NAMES) <= listed, f'runewords missing from the creator list: {sorted(set(NAMES) - listed)}')
    T.check(len(listed) > 70, f'only {len(listed)} vanilla runewords listed')


@T.test
def created_runewords_read_back_as_the_same_runeword():
    E = engine()
    cr, d = E.cr, E.data
    by_id = {}
    for i, (n, *_r) in enumerate(d.runewords):
        sid = cr.rw_string_id(i)
        if sid is not None and cr.t.rw_complete[i]:
            by_id.setdefault(sid & 0xFFF, []).append(n)
    for name in NAMES:
        row = _row(E, name)
        want = _game_index(E, cr.t.rw_key[row])
        T.check(want is not None, f'{name}: no string for {cr.t.rw_key[row]}')
        bases = [b for b in cr.runeword_bases(row) if cr.max_sockets(b.code, 99) >= len(d.runewords[row][1])]
        T.check(bases, f'no base for {name}')
        spec = cr.new_spec('runeword', bases[0].code, row)
        spec['sockets'] = len(d.runewords[row][1])
        spec['ilvl'] = 99
        cr.roll(spec, 'max')
        blob = bytes(cr.build(spec)[0])
        rec, _size = E.C.decode_item(blob, d)
        T.eq(rec['runeword_id'], want, f'{name}: 16-bit field')
        rid = E.fix.parse_item(blob, d)[0]['runeword']
        T.eq(rid, want & 0xFFF, f'{name}: 12-bit id read by the item reader')
        T.eq(by_id.get(rid), [name], f'{name}: 12-bit id {rid} names the runeword')


T.main(globals())
