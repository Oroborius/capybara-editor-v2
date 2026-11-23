"""New character creation and round trips in the vanilla and Median profiles."""
import os
import shutil
import sys
import time

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
        item_count = 0 if median else (7 if cls == 2 else 8)
        T.eq((len(ch.items), ch.merc_id, ch.merc_items or []), (item_count, 0, []),
             f'{name}: starting items and no mercenary')
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
        N.build(E.data, 'Classic', 5, 1, version=71)
        T.check(False, 'classic Druid refused')
    except N.NewCharError:
        pass


def _normalized_early(ch, raw, original):
    """Clear character name, map seed, and the random fields of each full record."""
    from mxl_early_save import starter_tail

    out = bytearray(raw)
    out[8:24] = bytes(16)        # character name
    out[126:130] = bytes(4)      # last game's map seed (the early header has no timestamp)
    pos = ch.offsets[2] + 4
    for entry in ch.items:
        n = entry.it['_size'] - 2
        if original or not int.from_bytes(raw[pos + 2:pos + 6], 'little') & (1 << 21):
            if ch.version == 71:
                bit, width = (123 if original else 155), 64  # item ID and generation seed
            else:
                bit, width = 95, 32                          # item ID only
            value = int.from_bytes(raw[pos + 2:pos + 2 + n], 'little')
            value &= ~(((1 << width) - 1) << bit)
            out[pos + 2:pos + 2 + n] = value.to_bytes(n, 'little')
        pos += n + 2
    if ch.version != 71:
        # Several uninitialized bytes of the old hotkey block echo the
        # item buffer, including parts of the randomized weapon ID.
        tail = pos + len(ch.corpse)
        normalized_tail = starter_tail(ch.version, bytes(out[ch.offsets[2] + 4:pos]), ch.corpse)
        original_tail = starter_tail(ch.version, raw[ch.offsets[2] + 4:pos], ch.corpse)
        for i, (before, after) in enumerate(zip(original_tail, normalized_tail)):
            out[tail + i] ^= before ^ after
    return bytes(out)


@T.test
def vanilla_early_starter_bytes():
    E = _vanilla()
    import mxl_newchar as N
    import mxl_save
    for folder, version in (('100', 71), ('106b', 71), ('107', 87), ('108', 89)):
        original = folder == '100'
        for cls, fixture, name in ((0, 'Ashbow', 'TestAmazon'), (3, 'Dawnshield', 'TestPaladin')):
            sample = os.path.join(T.REPO, '.cache', 'samples', 'oldver', folder, fixture + '.d2s')
            expected = E.MC.Character(sample, E.data)
            raw, _ = N.build(E.data, name, cls, 1, version=version, classic_100=original)
            path = N.write(raw, os.path.join(E.saves, folder), name)
            ch = E.MC.Character(path, E.data)
            tag = f'{folder}, class {cls}'
            T.eq(ch.build(), raw, f'{tag}: byte-identical rebuild')
            T.eq(len(mxl_save.load_character(path, E.data)['items']), 8, f'{tag}: collector can reopen')
            a = _normalized_early(ch, raw, original)
            b = _normalized_early(expected, T.read(sample), original)
            differences = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
            T.eq((len(a), differences), (len(b), []), f'{tag}: first-save bytes match the game')
            T.eq((bool(ch.status & 0x20), ch.has_jf, ch.merc_id), (version != 71, False, 0), tag)


def _normalized_starters(ch, raw):
    """Clear the checksum, character name, save time, map seed, item IDs and defense rolls."""
    from mxl_creator import decode_item
    from mxl_v109 import Data109

    data = Data109(ch.data, ch.version) if ch.version == 92 else ch.data
    out = bytearray(raw)
    out[0x0C:0x10] = bytes(4)
    out[0x14:0x24] = bytes(16)
    out[0x30:0x34] = bytes(4)
    out[0xAB:0xAF] = bytes(4)
    for entry in ch.items:
        start = entry.it['_offset']
        rec, size = decode_item(raw[start:], data)
        if 'id' not in rec:
            continue
        pos = start + 2
        mask = 0xFFFFFFFF << 95
        if rec['code'] == 'buc ':
            lo, hi = data.base(rec['code']).def_range
            T.check(lo <= rec['defense'] <= hi, f"buckler defense {rec['defense']} in {lo}–{hi}")
            # Normal armor without optional image, affix or name fields starts defense at bit 141.
            mask |= ((1 << data.isc[31]['bits']) - 1) << 141
        value = int.from_bytes(raw[pos:start + size], 'little') & ~mask
        out[pos:start + size] = value.to_bytes(size - 2, 'little')
    return bytes(out)


@T.test
def vanilla_current_and_109_starters():
    E = _vanilla()
    import mxl_newchar as N
    import mxl_save
    for folder, version in (('109d', 92), ('114d', 96)):
        for cls, name, fixture, weapon in ((0, 'TestAmazon', 'Ashbow', 'jav '),
                                           (3, 'TestPaladin', 'Dawnshield', 'ssd ')):
            before = int(time.time())
            raw, _ = N.build(E.data, name, cls, 1, version=version)
            stamp = int.from_bytes(raw[0x30:0x34], 'little')
            path = N.write(raw, os.path.join(E.saves, str(version)), name)
            ch = E.MC.Character(path, E.data)
            tag = f'{version}, class {cls}'
            T.check(before <= stamp <= int(time.time()), f'{tag}: current Unix save timestamp')
            T.eq((ch.version, ch.cls, ch.level, ch.name, ch.status), (version, cls, 1, name, 0x20), tag)
            T.eq((ch.offsets[0], ch.offsets[1], ch.skills), (765, 813 if version == 92 else 803,
                                                          b'if' + bytes(30)), tag)
            T.eq([e.it['code'] for e in ch.items], ['hp1 '] * 4 + ['tsc ', 'isc ', weapon, 'buc '], tag)
            T.eq((ch.corpse, ch.has_jf, ch.merc_id, ch.tail), (b'JM\0\0', True, 0, b'kf\0'), tag)
            T.eq(ch.build(), raw, f'{tag}: byte-identical rebuild')
            T.eq(len(mxl_save.load_character(path, E.data)['items']), 8, f'{tag}: collector can reopen')
            sample = os.path.join(T.REPO, '.cache', 'samples', 'oldver', folder, fixture + '.d2s')
            expected = E.MC.Character(sample, E.data)
            a = _normalized_starters(ch, raw)
            b = _normalized_starters(expected, T.read(sample))
            differences = [(hex(i), x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
            T.eq((len(a), differences), (len(b), []), f'{tag}: first-save bytes match the game')
            if version == 96:
                _independent(path)


@T.test
def median_new_characters():
    E = _median()
    import mxl_newchar as N
    T.check(N._median(), 'Median XL profile active')
    MC = E.MC
    try:
        N.build(E.data, 'OldMedian', 0, 1, version=92)
        T.check(False, 'Median refuses the legacy format')
    except N.NewCharError:
        pass
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
