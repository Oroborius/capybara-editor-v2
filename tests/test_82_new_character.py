"""More -> "New character..." (src/mxl_newchar.py): a NEW level-N character written into the save folder, for the
vanilla 1.14d profile and for Median XL. Each file passes the independent parser (mxlsave check + verify), re-opens
in the editor (mxl_char.Character, rebuilt byte for byte) and holds the class's starting stats, the level's
experience, stat / skill points, no items, no mercenary; an existing name is refused, nothing is overwritten.

Fixtures: Median = the usual test user folder; vanilla = the vanilla install (see test 75). ISOLATE: the two
profiles cannot share one process."""
import os
import shutil
import sys

import capytest as T

MODE = 'engine'
NEEDS = ()
ISOLATE = True

GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')


def _vanilla():
    if not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        T.skip(f'no vanilla 1.14d install ({GAME})')
    user = T.guard(os.path.join(T.tmp(), 'vuser'), 'user folder')
    saves = T.guard(os.path.join(T.tmp(), 'vsaves'), 'save folder')
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
    import mxl_char
    return T.NS(data=mxl_data.Data(paths.DATA_DIR), MC=mxl_char, saves=saves)


def _median():
    E = T.engine()
    saves = T.guard(os.path.join(T.tmp(), 'msaves'), 'save folder')
    os.makedirs(saves, exist_ok=True)
    return T.NS(data=E.data, MC=E.MC, saves=saves)


def _independent(path):
    import mxl_savecheck
    mxl_savecheck.lib()
    from mxlsave.check import check_bytes
    from mxlsave.cli import verify
    tb = mxl_savecheck.tables()
    T.check(tb is not None, 'mxlsave tables of the profile')
    _obj, problems = check_bytes(T.read(path), 'd2s', tb)
    T.eq(problems, [], f'{os.path.basename(path)}: mxlsave check')
    T.eq(verify(path, tb), (True, ''), f'{os.path.basename(path)}: mxlsave verify')


def _common(E, median, top):
    import mxl_newchar as N
    MC, data = E.MC, E.data
    cases = [('Fresh', 0, 1, dict()), ('Mid-Way', 2, 50, dict(hardcore=True)), ('Top', 6, top, dict(unlocked=True))]
    for name, cls, lv, kw in cases:
        raw, _ch = N.build(data, name, cls, lv, median=median, **kw)
        path = N.write(raw, E.saves, name)
        T.eq(os.path.basename(path), name + '.d2s', f'{name}: file name')
        _independent(path)
        ch = MC.Character(path, data)
        T.eq(ch.build(), T.read(path), f'{name}: re-opened file rebuilds byte for byte')
        T.eq((ch.name, ch.cls, ch.level, ch.stat(12)), (name, cls, lv, lv), f'{name}: name, class, level')
        T.eq((len(ch.items), ch.merc_id, ch.merc_items or []), (0, 0, []), f'{name}: no items, no mercenary')
        r = data._rows('charstats')[cls]
        T.eq([ch.stat(s) for s in (0, 1, 2, 3)], [r[0x30], r[0x32], r[0x31], r[0x33]], f'{name}: starting stats')
        T.eq((ch.stat(4), ch.stat(5)), (5 * (lv - 1), lv - 1), f'{name}: stat / skill points for the level')
        exp = MC.exp_for_level(data, cls, min(lv, MC.max_level(data, cls))) or 0
        T.eq(ch.stat(13), exp, f'{name}: experience of the level')
        T.eq(bool(ch.head[0x24] & 0x04), bool(kw.get('hardcore')), f'{name}: hardcore flag')
        T.eq(ch.head[0x2A], 0x5F if median else 0x1E, f'{name}: header 0x2A of the game')
        T.check(ch.waypoint(0, 0), f'{name}: Rogue Encampment waypoint')
        if kw.get('unlocked'):
            T.eq((ch.progression, ch.waypoint(2, 38), ch.quest_done(2, MC.LAST_QUEST_WORD)), (15, True, True),
                 f'{name}: all difficulties, acts and waypoints')
        else:
            T.eq((ch.progression, ch.waypoint(0, 1)), (0, False), f'{name}: only the act I town')
    # never overwrite: the same name (any case) or a companion file of that name is refused
    before = T.read(os.path.join(E.saves, 'Fresh.d2s'))
    raw, _ = N.build(data, 'Fresh', 1, 5, median=median)
    for n in ('Fresh', 'fresh'):
        try:
            N.write(raw, E.saves, n)
            T.check(False, f'{n}: existing name refused')
        except N.NewCharError:
            pass
    T.eq(T.read(os.path.join(E.saves, 'Fresh.d2s')), before, 'existing file untouched')
    with open(os.path.join(E.saves, 'Orphan.stash'), 'wb') as f:
        f.write(b'x')
    T.check(N.name_taken(E.saves, 'Orphan'), 'a companion file blocks the name')
    for bad in ('A', 'Has2Digits', '-dash', 'two--', 'a-b_c', 'x' * 16):
        try:
            N.build(data, bad, 0, 1, median=median)
            T.check(False, f'{bad!r}: name refused')
        except MC.CharError:
            pass
    try:
        N.build(data, 'Toohigh', 0, top + 1, median=median)
        T.check(False, 'level over the top refused')
    except N.NewCharError:
        pass


@T.test
def vanilla_new_characters():
    E = _vanilla()
    import mxl_newchar as N
    T.check(not N._median(), 'vanilla profile active')
    _common(E, False, 127)
    raw, ch = N.build(E.data, 'Classic', 3, 99, expansion=False, unlocked=True, median=False)
    path = N.write(raw, E.saves, 'Classic')
    _independent(path)
    ch = E.MC.Character(path, E.data)
    T.eq((ch.head[0x24] & 0x20, ch.has_jf, ch.progression, ch.waypoint(0, 29), ch.waypoint(0, 30)),
         (0, False, 12, True, False), 'classic: no expansion flag / mercenary section, acts I-IV')
    try:
        N.build(E.data, 'Classic', 5, 1, expansion=False, median=False)
        T.check(False, 'classic Druid refused')
    except N.NewCharError:
        pass


@T.test
def median_new_characters():
    E = _median()
    import mxl_newchar as N
    T.check(N._median(), 'Median XL profile active')
    MC = E.MC
    _common(E, True, MC.max_level(E.data, 0))
    # the template matches the game's own file in every structural field (sample XBone, level 100)
    src = os.path.join(T.SRC_SAVES, 'XBone.d2s')
    if not os.path.isfile(src):
        T.skip('no XBone sample')
    shutil.copy(src, os.path.join(T.tmp(), 'XBone.d2s'))
    x = MC.Character(os.path.join(T.tmp(), 'XBone.d2s'), E.data)
    raw, ch = N.build(E.data, 'Necro', 2, 100, median=True)
    for off, n in ((4, 4), (0x29, 2), (0x34, 4), (0x14F, 10), (0x279, 8), (0x2C9, 4)):
        T.eq(raw[off:off + n], bytes(x.head[off:off + n]), f'header bytes {off:#x}+{n} as in XBone')
    T.eq((len(ch.skills), ch.corpse, ch.has_jf, ch.tail), (len(x.skills), x.corpse, True, x.tail),
         'skills length, corpse, jf, golem tail as in XBone')
    T.eq((ch.stat(9), ch.stat(10)), (x.stat(9), x.stat(10)), 'level 100 Necromancer: base mana and stamina as XBone')


if __name__ == '__main__':
    T.main(globals())
