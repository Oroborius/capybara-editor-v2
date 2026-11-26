"""Character engine (mxl_char.Character): set_field for every key, flags, progression, rename - each on a fresh
copy, saved, read again from disk and compared; the rest of the file must stay byte-identical."""
import glob
import os
import struct

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')

# save bits of the character stats section, from the 1.13c format description (independent of mxl_char)
WIDTHS = {0: 11, 1: 11, 2: 11, 3: 11, 4: 11, 5: 9, 6: 21, 7: 21, 8: 21, 9: 21, 10: 21, 11: 21, 12: 8, 13: 32,
          14: 25, 15: 25}
IDS = dict(strength=0, energy=1, dexterity=2, vitality=3, stat_points=4, skill_points=5, life_cur=6, life_max=7,
           mana_cur=8, mana_max=9, stamina_cur=10, stamina_max=11, level=12, experience=13, gold=14, gold_stash=15)


def samples():
    """[(tag, folder)] of the sample folders there are."""
    out = [('sample1', T.SRC_SAVES)]
    if T.saves_ok(T.SRC_SAVES2):
        out.append(('sample2', T.SRC_SAVES2))
    return out


def fresh(which):
    folder = T.fresh_saves(1 if which == 'sample1' else 2)
    return sorted(glob.glob(os.path.join(folder, '*.d2s')))[0]


def split(raw, widths):
    """(header, stats section, rest, [(stat id, raw value)]) found by walking the bit stream here."""
    gf = raw.find(b'gf', 0x2C9)
    assert gf > 0, 'no gf section'
    v = int.from_bytes(raw[gf + 2:gf + 2 + 400], 'little')
    pos, stats = 0, []
    while True:
        sid = (v >> pos) & 511
        pos += 9
        if sid == 511:
            break
        w = widths[sid]
        stats.append((sid, (v >> pos) & ((1 << w) - 1)))
        pos += w
    end = gf + 2 + (pos + 7) // 8
    assert raw[end:end + 2] == b'if', 'skills section does not follow the stats'
    return raw[:gf], raw[gf:end], raw[end:], stats


def widths_for(E):
    """Ids 0-15 are the classic widths above; Median XL saves carry a few more character stats, whose widths
    (param bits + value bits, read as one field here) are taken from the raw itemstatcost rows."""
    w = dict(WIDTHS)
    for r in E.data._rows('itemstatcost'):
        sid = struct.unpack_from('<H', r, 0)[0]
        if sid not in w and r[10]:
            w[sid] = r[10] + r[11]
    return w


def snapshot(E, c):
    MC = E.MC
    return dict({k: c.stat_field(k).raw for k in MC.FIELD_KEYS}, name=c.name, status=c.head[0x24],
                prog=c.head[0x25], hlevel=c.head[0x2B], other=[s for s in c.stats if s[0] > 15])


def check_file(E, path, base_raw, what, head_changes=()):
    """Header size + checksum right; outside the stats section only the allowed header bytes changed."""
    raw = T.read(path)
    for problem in T.d2s_header_ok(raw):
        T.check(False, f'{what}: {problem}')
    w = widths_for(E)
    h0, _s0, r0, _ = split(base_raw, w)
    h1, _s1, r1, st = split(raw, w)
    T.check(r0 == r1, f'{what}: bytes after the stats section changed (skills / items / tail)')
    allowed = set(range(8, 16)) | set(head_changes)
    T.check(len(h0) == len(h1) and all(h0[i] == h1[i] for i in range(len(h0)) if i not in allowed),
            f'{what}: header bytes changed outside {sorted(set(head_changes))}')
    return raw, st


@T.test
def set_field_every_key_roundtrip():
    E = T.engine()
    MC = E.MC
    n = 0
    for tag, _src in samples():
        for k in MC.FIELD_KEYS:
            p = fresh(tag)
            raw = T.read(p)
            c = MC.Character(p, E.data)
            before = snapshot(E, c)
            fd = c.stat_field(k)
            new = fd.value + 3 if fd.value + 3 <= fd.max else fd.value - 3
            c.set_field(k, new)
            c.save(backup=False)
            c2 = MC.Character(p, E.data)
            exp = dict(before)
            exp[k] = new << fd.shift
            if k == 'level':
                exp['hlevel'] = new
            T.eq(snapshot(E, c2), exp, f'{tag} {k}: fields after reload')
            T.eq(c2.field(k), new, f'{tag} {k}: value after reload')
            _raw2, st = check_file(E, p, raw, f'{tag} {k}', (0x2B,) if k == 'level' else ())
            T.eq(dict(st).get(IDS[k], 0), new << fd.shift, f'{tag} {k}: raw value in the bit stream (independent reader)')
            n += 1
    T.check(n >= len(MC.FIELD_KEYS), f'{n} cases')


@T.test
def set_field_bounds():
    """Minimum, maximum and raw maximum are stored; values outside the range are refused and change nothing."""
    E = T.engine()
    MC = E.MC
    tag = samples()[0][0]
    for k in MC.FIELD_KEYS:
        for which in ('min', 'max', 'rawmax'):
            p = fresh(tag)
            raw = T.read(p)
            c = MC.Character(p, E.data)
            before = snapshot(E, c)
            fd = c.stat_field(k)
            if which == 'rawmax':
                c.set_field_raw(k, fd.raw_max)
                want = fd.raw_max
            else:
                v = getattr(fd, which)
                c.set_field(k, v)
                want = fd.raw if v == fd.value else v << fd.shift
            c.save(backup=False)
            c2 = MC.Character(p, E.data)
            exp = dict(before)
            exp[k] = want
            if k == 'level':
                exp['hlevel'] = want
            T.eq(snapshot(E, c2), exp, f'{k} {which}')
            T.eq(c2.stat_field(k).present, want != 0 or k == 'level', f'{k} {which}: stat present in the file')
            check_file(E, p, raw, f'{k} {which}', (0x2B,) if k == 'level' else ())
        c = MC.Character(fresh(tag), E.data)
        fd = c.stat_field(k)
        b0 = c.build()
        for bad in (fd.max + 1, fd.min - 1, -1, True, None, 'x', float('nan'), float('inf'), 1e30):
            try:
                c.set_field(k, bad)
                T.check(False, f'{k}: accepted {bad!r}')
            except MC.CharError:
                pass
        try:
            c.set_field_raw(k, fd.raw_max + 1)
            T.check(False, f'{k}: raw maximum + 1 accepted')
        except MC.CharError:
            pass
        T.check(c.build() == b0, f'{k}: a refused value changed the character')
    c = MC.Character(fresh(tag), E.data)
    for call, what in ((lambda: c.set_field('nope', 1), 'unknown field'), (lambda: c.set_flag('nope', 1), 'unknown flag'),
                       (lambda: c.set_difficulties_done(4), 'difficulties_done 4'), (lambda: c.set_progression(256), 'progression 256'),
                       (lambda: c.set_progression(-1), 'progression -1')):
        try:
            call()
            T.check(False, f'{what} accepted')
        except MC.CharError:
            pass


@T.test
def zero_stats_left_out_and_restored():
    """A stat set to 0 is left out of the file (as the game does); setting it and zeroing it again gives the
    original bytes."""
    E = T.engine()
    MC = E.MC
    tag = samples()[0][0]
    p = fresh(tag)
    raw = T.read(p)
    c = MC.Character(p, E.data)
    for k in MC.FIELD_KEYS:
        if k != 'level':
            c.set_field(k, 0)
    c.save(backup=False)
    _raw, st = check_file(E, p, raw, 'all zero')
    T.eq([s for s, _v in st if s < 16], [12], 'stat ids below 16 left in the file')
    p = fresh(tag)
    c = MC.Character(p, E.data)
    k = next((k for k in ('stat_points', 'skill_points', 'gold') if not c.stat_field(k).present), None)
    if k is None:
        k, old = 'gold', c.field('gold')
    else:
        old = 0
    c.set_field(k, 7)
    c.save(backup=False)
    T.check(T.read(p) != raw, 'setting a field wrote nothing')
    _raw, st = check_file(E, p, raw, 'one stat set')
    T.eq([s for s, _v in st], sorted(s for s, _v in st), 'stats in id order')
    c = MC.Character(p, E.data)
    c.set_field(k, old)
    c.save(backup=False)
    T.check(T.read(p) == raw, f'{k} set to 7 and back to {old}: file differs from the original')


@T.test
def flags_roundtrip():
    E = T.engine()
    MC = E.MC
    for tag, _src in samples():
        for flag, bit in MC.STATUS_FLAGS.items():
            if flag == 'ladder':
                continue                          # Median profile: saving takes ladder off (test 22)
            p = fresh(tag)
            raw = T.read(p)
            c = MC.Character(p, E.data)
            before = snapshot(E, c)
            f0 = c.flags()
            c.set_flag(flag, not f0[flag])
            c.save(backup=False)
            c2 = MC.Character(p, E.data)
            T.eq(c2.flags(), dict(f0, **{flag: not f0[flag]}), f'{tag} flag {flag}')
            after = snapshot(E, c2)
            after.pop('status')
            before.pop('status')
            T.eq(after, before, f'{tag} flag {flag}: other fields')
            T.eq(raw[0x24] ^ T.read(p)[0x24], bit, f'{tag} flag {flag}: bits changed in byte 0x24')
            check_file(E, p, raw, f'{tag} flag {flag}', (0x24,))


@T.test
def progression_roundtrip():
    E = T.engine()
    MC = E.MC
    for tag, _src in samples():
        p = fresh(tag)
        raw = T.read(p)
        c = MC.Character(p, E.data)
        before = snapshot(E, c)
        new = 15 if c.progression != 15 else 10
        c.set_progression(new)
        c.save(backup=False)
        c2 = MC.Character(p, E.data)
        T.eq(snapshot(E, c2), dict(before, prog=new), f'{tag}: fields after set_progression({new})')
        T.eq(c2.difficulties_done, new // 5, f'{tag}: difficulties_done')
        check_file(E, p, raw, f'{tag} progression', (0x25,))
        # Normal finished + the act bosses dead in Nightmare (+1 each for Andariel, Duriel, Mephisto: both samples
        # have all three), as the game counts it: its own files hold 8 / 13 in that state, never a bare 5 / 10
        bosses = sum(1 for w in (6, 14, 22) if c2.quest_done(1, w))
        c2.set_difficulties_done(1)
        T.eq(c2.progression, 5 + bosses, 'set_difficulties_done(1)')
        T.eq(bosses, 3, f'{tag}: Nightmare act bosses dead in the sample')
        c2.set_difficulties_done(3)
        T.eq(c2.progression, 15, 'set_difficulties_done(3)')
        c2.set_difficulties_done(0)
        T.eq(c2.progression, 3, 'set_difficulties_done(0): Normal with its three bosses dead')
    for tag, src in samples():                    # the game's own byte is what the rule gives for its quest words
        c = MC.Character(sorted(glob.glob(os.path.join(src, '*.d2s')))[0], E.data)
        T.eq(c.game_progression(), c.progression, f'{tag}: game_progression() against the game-written byte')


@T.test
def rename_roundtrip():
    """rename(): the save and its companion files get the new name, a backup of the old file is kept, a pending
    field change travels along, the items are untouched."""
    E = T.engine()
    MC = E.MC
    for tag, _src in samples():
        p = fresh(tag)
        raw = T.read(p)
        folder = os.path.dirname(p)
        old_name = os.path.basename(p)[:-4]
        names0 = sorted(x for x in os.listdir(folder) if not x.startswith(old_name + '.d2s.bak-'))
        items0 = T.char_snap(p, E.data)
        c = MC.Character(p, E.data)
        before = snapshot(E, c)
        gold = 123 if c.field('gold') != 123 else 124
        c.set_field('gold', gold)
        dst, bak = c.rename('Capy-Bara')
        names1 = sorted(os.listdir(folder))
        want = sorted([x.replace(old_name, 'Capy-Bara', 1) if x.split('.')[0] == old_name and '.bak' not in x and
                       not x.endswith('.d2s') or x == old_name + '.d2s' else x for x in names0] + [os.path.basename(bak)])
        T.eq(names1, want, f'{tag}: files after the rename')
        T.check(T.read(bak) == raw, f'{tag}: the backup is not the old file')
        c2 = MC.Character(dst, E.data)
        T.eq(snapshot(E, c2), dict(before, name='Capy-Bara', gold=gold), f'{tag}: fields after the rename')
        check_file(E, dst, raw, f'{tag} rename', range(0x14, 0x24))
        T.eq(T.char_snap(dst, E.data), items0, f'{tag}: items after the rename')
        for bad in ('A', 'x' * 16, 'Ab_c-d', '-Abc', 'Abc_', 'Ab1', 'Ab c', ''):
            try:
                c2.rename(bad)
                T.check(False, f'{tag}: bad name {bad!r} accepted')
            except MC.CharError:
                pass
        with open(os.path.join(folder, 'Taken.d2s'), 'wb') as f:
            f.write(b'x')
        try:
            c2.rename('taken')
            T.check(False, f'{tag}: a name that exists was accepted')
        except MC.CharError:
            pass
        T.eq((c2.name, sorted(os.listdir(folder))), ('Capy-Bara', sorted(names1 + ['Taken.d2s'])),
             f'{tag}: a refused rename left a trace')


@T.test
def level_and_experience_helpers():
    E = T.engine()
    MC = E.MC
    c = MC.Character(fresh(samples()[0][0]), E.data)
    lo, hi = MC.level_exp_range(E.data, c.cls, 50)
    c.set_level_raw(50)
    T.eq((c.level, c.stat(12)), (50, 50), 'set_level_raw(50)')
    T.eq(c.match_exp_to_level(), lo, 'match_exp_to_level at 50')
    c.set_field('experience', MC.level_exp_range(E.data, c.cls, 77)[0])
    T.eq(c.match_level_to_exp(), 77, 'match_level_to_exp')
    T.check(lo < hi, f'exp range of level 50: {lo}..{hi}')


@T.test
def gold_stays_within_the_games_limit():
    """The game sets gold above its limit to 0 when the character loads: inventory 10 000 x level, stash the base
    game's 50 000 x (level / 2 + 1) above level 30, at most 2 500 000 (Median XL). set_field refuses more; raw
    editing (set_field_raw) is limited by the file only."""
    E = T.engine()
    MC = E.MC
    T.eq(MC.gold_limit('gold', 81), 810000, 'inventory, level 81')
    T.eq(MC.gold_limit('gold_stash', 81), 2050000, 'stash, level 81: 50 000 x 41')
    T.eq(MC.gold_limit('gold_stash', 117), 2500000, 'stash, level 117: Median XL cap')
    T.eq(MC.gold_limit('gold_stash', 20), 150000, 'stash, level 20: 50 000 x 3')
    c = MC.Character(fresh(samples()[0][0]), E.data)
    for k in ('gold', 'gold_stash'):
        cap = MC.gold_limit(k, c.level)
        T.check(c.stat_field(k).max >= cap, f'{k}: the limit can be typed')
        if c.stat_field(k).raw <= cap:
            T.eq(c.stat_field(k).max, cap, f'{k}: field maximum is the game limit')
            try:
                c.set_field(k, cap + 1)
                T.check(False, f'{k}: {cap + 1} accepted')
            except MC.CharError:
                pass
        c.set_field(k, cap)
        c.set_field_raw(k, cap + 1)                 # raw editing: the file's limits only


@T.test
def median_character_rejects_truncated_stats_and_item_lists():
    E = T.engine()
    saved = E.MC.Character(fresh('sample1'), E.data)
    raw = bytes(saved.raw)
    gf, skills, items = saved.offsets

    for label, truncated in (
        ('header', raw[:7]),
        ('stat list', raw[:gf + 2] + bytes(8)),
        ('missing item marker', raw[:skills + 2]),
        ('item count', raw[:items + 3]),
        ('corpse count', raw[:items] + b'JM\0\0JM'),
        ('corpse item count', raw[:items] + b'JM\0\0JM\1\0' + bytes(12) + b'JM'),
        ('mercenary count', raw[:items] + b'JM\0\0JM\0\0jfJM'),
    ):
        try:
            character = E.MC.Character.__new__(E.MC.Character)
            character.data = E.data
            character.parse(truncated)
        except E.MC.FormatError:
            pass
        else:
            raise AssertionError(f'{label}: expected the normal character format error')

    T.eq(saved.build(), raw, 'the intact Median save still rebuilds byte for byte')


T.main(globals())
