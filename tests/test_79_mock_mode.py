"""Mock Mode engine (src/mxl_mock.py) in the vanilla profile: the analyzer on reference mock saves matches the
research numbers (docs/review/mock-pi.md 2.5 / 8.2), the vanilla item codec gives every sample item back byte for
byte, and every preset generates a NEW save that re-opens in the editor and that the analyzer scores as hitting
its targets (mana band / funky, regen at the cap, smite at the damage cap, aura sources as planned, < 8192 bytes)
and uses the clones' size tricks with bulk lines up to the size budget.

Fixtures: the vanilla install and the mock samples (see test 75; copies only). Skipped without them."""
import glob
import math
import os
import shutil
import sys
from fractions import Fraction
from types import SimpleNamespace

import capytest as T

MODE = 'engine'
NEEDS = ()

GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')


def _mock_dir():
    cands = [os.environ.get('MXL_TEST_MOCK_SAVES', ''), os.path.join(T.REPO, '.cache', 'samples', 'mock')]
    if os.sep + '.claude' + os.sep + 'worktrees' + os.sep in T.REPO:
        cands.append(os.path.join(T.REPO.split(os.sep + '.claude' + os.sep)[0], '.cache', 'samples', 'mock'))
    return next((c for c in cands if c and glob.glob(os.path.join(c, '*.d2s'))), None)


_E = None


def engine():
    global _E
    if _E is not None:
        return _E
    src = _mock_dir()
    if not os.path.isfile(os.path.join(GAME, 'd2data.mpq')) or not src:
        T.skip(f'no vanilla 1.14d install ({GAME}) or no mock samples (.cache/samples/mock)')
    user = T.guard(os.path.join(T.tmp(), 'mvuser'), 'user folder')
    saves = T.guard(os.path.join(T.tmp(), 'mvsaves'), 'save folder')
    os.makedirs(user, exist_ok=True)
    shutil.copytree(src, saves)
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
    import mxl_mock
    _E = T.NS(data=mxl_data.Data(paths.DATA_DIR), MC=mxl_char, M=mxl_mock, saves=saves)
    mxl_mock.set_data(_E.data)
    return _E


def _analyze(path, side=None, bo=False):
    E = engine()
    ch = E.MC.Character(path, E.data)
    m = E.M.model_from_character(ch)
    return E.M.analyze(m, side, bo=bo), m, ch


def _sample(rel):
    return os.path.join(engine().saves, rel)


# (file, side or None = the active one, TK, mana, kind) - mana with the game's percent step (pct_fp, measured in game)
# and item Energy after it (in game); four clones land exactly on their band top with it (the game shows the integer)
REFERENCE = [
    ('clones/clone-41.d2s', None, 30, Fraction(1048576), 'funky'),
    ('clones/clone-60.d2s', None, 30, Fraction(1048576), 'funky'),
    ('clones/clone-35.d2s', None, 99, '1572863.62', 'good'),
    ('clones/clone-06.d2s', None, 99, '1572863.22', 'good'),
    ('clones/clone-36.d2s', None, 31, '1572863.00', 'good'),
    ('clones/clone-73.d2s', None, 72, '1572581.37', 'good'),
    ('clones/clone-76.d2s', None, 31, '1572194.27', 'good'),
    ('clones/clone-28.d2s', None, 30, '3145727.16', 'good'),
    ('clone-51.d2s', None, 39, Fraction(229759679, 256), 'bad'),
    ('clones/clone-20.d2s', None, 53, '1572005.77', 'good'),
]


@T.test
def analyzer_matches_the_research_numbers():
    """Mana with the calibrated rule (+20 Sigon's set bonus, no item Energy), band / funky and off-screen."""
    E = engine()
    for rel, side, tk, mana, kind in REFERENCE:
        a, m, _ = _analyze(_sample(rel), side)
        v = a['values']
        b = v['band']
        got = v['mana'] if isinstance(mana, Fraction) else f"{float(v['mana']):.2f}"
        T.eq((v['tk'], got), (tk, mana), f'{rel}: TK, mana')
        state = 'funky' if b['funky'] else 'good' if b['good'] else 'bad'
        T.eq(state, kind, f'{rel}: band')
        if kind == 'funky':
            T.eq((b['offscreen'], b['stable']), (-8388608, True), f'{rel}: perfect TK30 funky')
        if kind == 'good' and tk >= 31:
            T.check(1571000 <= int(v['mana']) <= 1572863, f'{rel}: TK31 high mock at 1571000-1572863')
    a, m, _ = _analyze(_sample('clone-90.d2s'))
    v = a['values']
    T.eq((v['side'], v['lists'], v['size']), ('B', 178, 8191), 'clone-90: active side B, 178 lists, 8191 bytes')
    T.eq(v['sources']['Prayer'], {'charm': 31}, 'clone-90: Prayer sources only on charms')
    T.eq((sum(v['sources']['Holy Freeze'].values()), sum(v['sources']['Thorns'].values()),
          sum(v['sources']['Meditation'].values())), (7, 1, 1), 'clone-90: 7 Holy Freeze, 1 Thorns, 1 Meditation')
    T.check(v['regen'] <= v['regen_cap'], 'clone-90: regen under the roll-over cap')
    T.check(v['smite']['max'] <= E.M.ROLL, 'clone-90: smite under the roll')
    # socket capacity = save field + item_numsockets (194) lines, settled by clones2: the proven clones size 194 as
    # 7 - field (clone-03, clone-06, clone-80, clone-37 ...) or 15 and never overfill; only the
    # undescribed clone-82 (11) and clone-74 (7 jewels in 1-socket rings / amulet: 21) do (scored bad)
    for rel in ('clones/clone-41.d2s', 'clones/clone-60.d2s', 'clones/clone-05.d2s', 'clone-90.d2s'):
        T.eq(_analyze(_sample(rel))[1]['excess_jewels'], 0, f'{rel}: every jewel fits its sockets')
    a, m, _ = _analyze(_sample('clone-74.d2s'))
    T.eq(m['excess_jewels'], 21, 'clone-74: 21 jewels beyond the socket count')
    T.check(any(c[0] == 'sockets' and c[3] == E.M.BAD for c in a['checks']), 'clone-74: scored bad')
    T.eq(_analyze(_sample('clones/clone-05.d2s'))[0]['values']['dopplezon'], 1, 'clone-05: Dopplezon line')


def _clones2():
    d = os.path.join(engine().saves, 'clones2')
    files = sorted(glob.glob(os.path.join(d, '*.d2s')) + glob.glob(os.path.join(d, '*', '*.d2s')))
    if not files:
        T.skip('no clones2 samples (.cache/samples/mock/clones2)')
    return [f for f in files if T.read(f)[4] == 96]


@T.test
def mana_matches_the_game():
    """In-game 1.14d max mana (globe, 2026-11-20) of the saves main generated before the fix: MockHigh 1572480
    (base raw 2096942, +15361 +20, +6571%) and FunkyXXX 1048560 (2096896, +12269 +20, +5020%) - the game takes
    v + (v // 100) x pct on the 1/256 fixed point, not the exact product (1572500.1 / 1048576)."""
    M = engine().M
    T.eq(int(M.pct_fp(2096942 + 256 * (15361 + 20), 6571) // 256), 1572480, 'old MockHigh: 1572480 in game')
    T.eq(int(M.pct_fp(2096896 + 256 * (12269 + 20), 5020) // 256), 1048560, 'old FunkyXXX: 1048560 in game')
    T.eq(M.pct_fp(2096640 + 256 * 17410, 3996), 256 * 1048576, 'clone-63: exactly 1048576 in game')
    for key in ('funky', 'mock_high'):
        P = M.plan(key, 'Pin')
        m = P['mana']
        X = m['base_raw'] + 256 * (m['flat'] + M.SET_BONUS)
        T.eq(Fraction(M.pct_fp(X, m['pct'] + P['o']['bo_pct']), 256), m['mana'], f'{key}: planned with the game step')
    T.eq(M.plan('funky', 'Pin')['mana']['mana'], 1048576, 'funky: exactly 1048576 with the game step')


@T.test
def clones2_settle_sockets_funky_bo_and_smite():
    """The clan-channel clones (clones2): jewels fit field + 194, the TK30 funkies sit at 1048576 / -8388608,
    BO (effective level <= 99) lifts the high sides to the top of band 2, a smite over 8388607 is bad."""
    E = engine()
    M = E.M
    over = {}
    for f in _clones2():
        n = _analyze(f)[1]['excess_jewels']
        if n:
            over[os.path.basename(f)] = n
    T.eq(over, {'clone-82.d2s': 11, 'clone-74.d2s': 21}, 'clones2: only clone-82 / Pompeliusz overfill')
    for n in ('clone-63', 'clone-69', 'clone-99', 'clone-65'):
        b = _analyze(_sample(f'clones2/{n}.d2s'))[0]['values']['band']
        T.eq((b['funky'], b['stable'], b['offscreen']), (True, True, -8388608), f'{n}: TK30 funky zero')
    m = _analyze(_sample('clones2/clone-63.d2s'))[1]
    T.check(not M.analyze(m, energy=True)['values']['band']['funky'],
            'clone-63: spending its 1023 attributes on Energy would break the funky')
    for n, side in (('clone-45', None), ('clone-02', 'A'), ('clone-93', None), ('clone-32', None),
                    ('clone-53', 'A'), ('clone-77', 'B')):
        a, m, _ = _analyze(_sample(f'clones2/{n}.d2s'), side)
        g = M.analyze(m, side, bo=True, energy=True)['values']
        T.check(a['values']['mana'] < 1500000 and 1571000 <= int(g['mana']) <= 1572863,
                f"{n}: BO + Energy lift {float(a['values']['mana']):.0f} to {float(g['mana']):.0f} (top of band 2)")
        T.check(any(c[0] == 'ingame' for c in a['checks']), f'{n}: the in-game BO / Energy value is shown')
    a, m, _ = _analyze(_sample('clones2/clone-45.d2s'))
    T.check(a['values']['smite']['slvl'] == 99 and a['values']['smite']['max'] <= M.ROLL,
            'clone-45: Smite 63 + 63 counts as level 99 (capped smite)')
    m['units'].append(M.Unit('charm', 'extra', [[(111, None, 491)]]))
    a = M.analyze(m)
    T.check(a['values']['smite']['max'] > M.ROLL and
            any(c[0] == 'damage' and c[3] == M.BAD for c in a['checks']), 'a smite over 8388607 is bad (rolls to 1)')


@T.test
def vanilla_item_codec_round_trips_every_sample_item():
    """decode_item -> encode_item gives the same bytes for every item (with its socketed jewels) of the d2s 96
    samples. Known exceptions: ears (trophies, kept raw) and the ethereal charms whose stat lists do not parse
    with the 1.10+ widths (clone-20 6, clone-100 14, clone-68 1; the editor keeps them opaque)."""
    E = engine()
    isc, base = E.M.isc_from_data(E.data), E.M.base_from_data(E.data)
    bad, skipped = [], []
    files = sorted(glob.glob(os.path.join(E.saves, '*.d2s')) + glob.glob(os.path.join(E.saves, 'clones', '*.d2s')))
    n = 0
    for path in files:
        if T.read(path)[4] != 96:
            continue
        ch = E.MC.Character(path, E.data)
        rel = os.path.relpath(path, E.saves)
        for e in ch.items:
            if e.it.get('code') == 'ear ':
                continue
            try:
                recs = E.M.decode_blob(e.blob, isc, base)
            except Exception:
                skipped.append((os.path.basename(rel), bool(e.it.get('ethereal')), len(e.it.get('stats') or [])))
                continue
            n += 1
            if b''.join(E.M.encode_item(r, isc, base) for r in recs) != e.blob:
                bad.append(f"{rel}: {e.it.get('code')}")
    T.eq(bad, [], 'items not given back byte for byte')
    T.eq(sorted(skipped), sorted([('clone-68.d2s', True, 0)] + [('clone-20.d2s', True, 0)] * 6
         + [('clone-100.d2s', True, 0)] * 14), 'items the codec cannot read (all opaque to the editor too)')
    T.check(n > 1500, f'{n} items checked')


def _gen_dir():
    d = T.guard(os.path.join(T.tmp(), 'mockgen'), 'generated saves')
    os.makedirs(d, exist_ok=True)
    return d


_MS = []


def _independent(key, raw, v):
    """The independent parser mxlsave: no structural problem; every socketed child fits the item's socket
    count (save field + item_numsockets lines, as in the reference mocks: the game drops the rest); Dopplezon
    present; the mana sum recomputed from its own parse (active side, inventory charms) equals the analyzer's."""
    E = engine()
    if not _MS:
        import mxl_savecheck
        ms = mxl_savecheck.lib()
        _MS.append(ms.Tables(E.data.folder))
    from mxlsave.check import check_bytes
    obj, problems = check_bytes(raw, 'd2s', _MS[0])
    T.eq(problems, [], f'{key}: mxlsave finds no problem')
    side = (5, 4) if v['side'] == 'A' else (11, 12)
    F, Pc, dz, over = 0, 0, 0, []
    units = []
    for it in obj.items:
        if it.location == 1 and (it.equipped not in (4, 5, 11, 12) or it.equipped in side):
            cap = (it.sockets or 0) + sum(x.value for x in it.stats if x.id == 194)
            if len(it.socketed) > cap:
                over.append(it.code)
            units.append([it.stats] + list(it.set_stats.values()))
            for k in it.socketed[:cap]:
                units.append([k.stats] + ([k.runeword_stats] if k.runeword_stats is not None else []))
        elif it.location == 0 and it.panel == 1 and it.code in ('cm1 ', 'cm2 ', 'cm3 '):
            units.append([it.stats])
    for lists in units:
        for L in lists:
            for x in L:
                F += x.value if x.id == 9 else 0
                Pc += x.value if x.id == 77 else 0
                dz += 1 if x.id == 98 and x.param == 63 and x.value else 0
    T.eq(over, [], f'{key}: mxlsave: no item with more jewels than sockets')
    T.check(dz >= 1, f'{key}: mxlsave: Dopplezon line')
    base = next(x.value for x in obj.stats if x.id == 9)
    vfp = base + 256 * (F + 20)              # the game's percent step: v + (v // 100) x pct (1/256 fixed point)
    mana = Fraction(vfp + (vfp // 100) * (Pc + v['bo_pct'] * (v['mana'] != v['mana_nobo'])), 256)
    T.eq(mana, v['mana'], f'{key}: mxlsave mana sum = the analyzer mana')


def _check_generated(key, raw, P, path):
    E = engine()
    M = E.M
    bo = P['o']['bo'] > 0                   # the targets are the BO'd values (cast before the duel)
    a, m, ch = _analyze(path, bo=bo)
    T.eq(bytes(ch.build()), T.read(path), f'{key}: the editor re-builds the same bytes')
    import mxl_save
    mxl_save.load_character(path, E.data)
    v = a['values']
    exp = M.expected(P)
    bad = [c for c in a['checks'] if c[3] == M.BAD]
    T.eq(bad, [], f'{key}: checks scored bad')
    T.eq(v['tk'], exp['tk'], f'{key}: TK')
    if exp['exact']:
        T.eq(v['mana'], Fraction(P['o']['mana']), f'{key}: exact funky mana')
        T.check(v['band']['funky'] and v['band']['stable'], f'{key}: stable funky zero')
    else:
        T.eq(v['mana'], exp['mana'], f'{key}: mana as planned')
        T.check(v['band']['good'] and not v['band']['funky'], f'{key}: good band')
        T.eq(int(v['mana']), int(P['o']['mana']), f'{key}: on-screen mana = the target')
        if exp['tk'] >= 31:
            T.check(M.TK31_RANGE[0] <= v['mana'] < M.TK31_RANGE[1] + 1, f'{key}: TK31 mock range 1.21M-1572863')
    T.eq((v['regen'], v['regen_cap']), (exp['regen'], exp['regen_cap']), f'{key}: regen')
    T.check(v['regen'] <= v['regen_cap'] and v['regen_cap'] - v['regen'] < 25, f'{key}: regen at the cap')
    v0 = M.analyze(m)['values']             # BO not (yet) cast: a higher cap, regen stays under it
    T.check(v0['regen'] <= v0['regen_cap'], f'{key}: regen under the cap without BO too')
    T.check(exp['pvm'] - 400 <= v['smite']['max'] <= exp['pvm'] <= M.ROLL, f"{key}: smite {v['smite']['max']}")
    T.check(abs(v['life'] - P['o']['life']) < 2000 and v['life'] < M.ROLL, f"{key}: life {float(v['life'])}")
    srcs = {k: sum(x.values()) for k, x in v['sources'].items()}
    want = {M.AURA_NAMES[k]: n for k, n in exp['sources'].items() if n}
    T.eq(srcs, want, f'{key}: aura sources')
    funky = P['o'].get('role') == 'funky'   # no Prayer aura on a Funky
    T.eq(v['sources'].get('Prayer'), None if funky else {'charm': exp['sources'][M.PRAYER]}, f'{key}: Prayer sources only on charms')
    T.eq(v['prayer_level'], 0 if funky else 31 * v['lists'], f'{key}: Prayer 31 on every list')
    T.eq(v['lists'], 198 if P['o']['weapon'] else 178, f'{key}: lists')
    T.check(len(raw) == v['size'] <= 8191, f'{key}: {len(raw)} bytes (the game loads at most 8191)')
    T.eq(v['excess_jewels'], 0, f'{key}: every jewel fits the socket count (field + item_numsockets)')
    T.check(v['longest'] <= M.LINE_CAP, f"{key}: at most {M.LINE_CAP} lines per stat list ({v['longest']})")
    T.check(v['dopplezon'] >= 1, f'{key}: NV state Dopplezon (stat 98, state 63)')
    _independent(key, raw, v)
    lv = {x[1] for x in v['delirium']}
    T.check(len(v['delirium']) == 2 and len(lv) == 2, f'{key}: Delirium on attack + strike at two levels')
    if exp['side_b']:
        b = M.analyze(m, 'B', bo=bo)['values']
        T.eq(b['mana'], exp['side_b']['mana'], f'{key}: side B mana')
        T.eq([c for c in M.analyze(m, 'B', bo=bo)['checks'] if c[3] == M.BAD], [], f'{key}: side B checks')
        T.eq(int(b['mana']), P['o']['mana_b'], f'{key}: side B on-screen mana')
        T.check(M.TK31_RANGE[0] <= b['mana'] < M.TK31_RANGE[1] + 1, f'{key}: side B in the TK31 mock range')
        T.eq(b['stun'], [], f'{key}: side B without stun')


@T.test
def open_wounds_damage_uses_level_bands_and_player_divisors():
    M = engine().M
    for level, damage in ((15, (166, 41, 20)), (30, (436, 109, 54)), (99, (3136, 784, 392))):
        for divisor, per_frame in zip((1, 4, 8), damage):
            T.eq(M.open_wounds_damage_per_second(level, divisor), Fraction(per_frame * 25, 256),
                 f'level {level}, divisor {divisor}')

    raw, _ = M.generate('mock_high', 'Mocky', level=99, ow=127)
    path = M.write_new(raw, _gen_dir(), 'Mocky')
    analysis, _, _ = _analyze(path)
    rows = {key: (label, value) for key, label, value, _ in analysis['checks']}
    T.eq(rows['ow_damage'], ('Open Wounds damage/s', '100% on hit; 306.25 PvM, 76.56 melee PvP, 38.28 ranged PvP'),
         'Analyzer reports the generated bleed')
    T.eq(rows['ow_formula'][1], 'community formula, unverified in game', 'Analyzer labels the estimate')


@T.test
def every_preset_generates_a_save_that_hits_its_targets():
    E = engine()
    M = E.M
    folder = _gen_dir()
    for key in M.PRESET_ORDER:
        raw, P = M.generate(key, 'Mocky')
        path = M.write_new(raw, folder, 'Mocky')
        T.check(os.path.basename(path) != 'Mocky.d2s' or key == M.PRESET_ORDER[0], f'{key}: a new name')
        _check_generated(key, raw, P, path)


@T.test
def overrides_hit_their_targets():
    E = engine()
    M = E.M
    folder = _gen_dir()
    cases = [('mock_high', dict(mana=1572863)), ('mock_high', dict(level=99, position='Host')),
             ('mock_mid', dict(tk=32, life=6800000)), ('funky', dict(stun=0)), ('mock_low', dict(stun=60)),
             ('mock_high', dict(hf_sources=3, thorns=2500))]
    for key, over in cases:
        raw, P = M.generate(key, 'Over', **over)
        path = M.write_new(raw, folder, 'Over')
        _check_generated(f'{key} {over}', raw, P, path)
    raw, P = M.generate('mock_high', 'Over', mana=1572863)
    a, _, _ = _analyze(M.write_new(raw, folder, 'Over'), bo=True)
    T.eq(a['values']['band']['to_roll'] < 1, True, '1572863: the top of the good band')
    raw, P = M.generate('mock_high', 'Over', position='Host')
    T.eq(P['stun'], 0, 'Host: no stun')
    raw, P = M.generate('mock_low', 'Over', stun=60)
    T.check(P['smite']['max'] < M.ROLL * 0.9, 'more stun trades smite damage')
    try:
        M.generate('mock_high', 'Over', tk=24, mana=4194304, weapon=False)
        T.check(False, 'TK24 funky on 178 lists must be refused (no exact product)')
    except M.PlanError:
        pass
    for over in (dict(tk=30, mana=1572863), dict(mana=1100000), dict(hf_sources=60)):
        try:
            M.plan('mock_high', 'Over', **over)
            T.check(False, f'{over} must be refused (TK30 first band / outside the TK31 range / HF on charms)')
        except M.PlanError:
            pass
    T.check('mana_lock' not in M.PRESETS and 'mana_lock' not in M.PRESET_ORDER, 'Mana lock preset removed')
    for aura, mana in M.ENEMY_AURA_MANA.items():
        raw, P = M.generate('mock_high', 'Over', enemy_aura=aura)
        want = min(mana, P['o']['best_mana'])               # capped at the overheal-safe mana
        T.eq(int(P['mana']['mana']), want, f'enemy aura {aura}: mana {want}')
    T.eq(M.PRESETS['prayer_thorner']['mana'], 1572863, 'P/T (no enemy aura): 1572863')
    P = M.plan('aura_killer', 'AK')
    T.check(all(u.role == 'prayer' for u in P['units'] if u.kind == 'charm'), 'Aura Killer: every charm Prayer')
    T.eq(P['expect_sources'][M.HOLY_FREEZE], 28, 'Aura Killer: 28 Holy Freeze sources on gear jewels')


@T.test
def form_prefill_battle_orders_and_edited_fields():
    """The generator form: every field prefilled with the preset's values, only edited fields reach plan(); BO 99
    (the clones' convention) is in the targets, BO 0 gives a mock without BO."""
    E = engine()
    M = E.M
    for key in M.PRESET_ORDER:
        pre = M.prefill(key)
        o = M.plan(key, 'Mock')['o']          # Thorns / Barbs / DTM: solved by the plan
        T.eq({k: pre[k] for k in ('tk', 'es', 'mana', 'thorns', 'barbs', 'dtm', 'hf_sources', 'bo')},
             {k: int(o[k]) for k in ('tk', 'es', 'mana', 'thorns', 'barbs', 'dtm', 'hf_sources', 'bo')},
             f'{key}: prefill')
        T.eq(M.edited(dict(pre), pre), {}, f'{key}: an untouched form overrides nothing')
    pre = M.prefill('host')
    T.eq((pre['bo'], pre['prayer_sources'], pre['prayer'], pre['deli_attack'], pre['deli_strike']),
         (99, 40, 5518, 63, 62), 'host: BO 99, 40 Prayer charms, Prayer 5518, Delirium 63 / 62')
    form = dict(pre, thorns='2500', prayer_sources='35', prayer=str(5000), dopplezon=False, deli_strike='61')
    over = M.edited(form, pre)
    T.eq(over, dict(thorns=2500, prayer_sources=35, prayer=5000, dopplezon=False, deli_strike=61), 'edited fields')
    folder = _gen_dir()
    raw, P = M.generate('host', 'Form', **over)
    a, m, _ = _analyze(M.write_new(raw, folder, 'Form'), bo=True)
    v = a['values']
    T.eq((v['aura_levels']['Thorns'], v['prayer_level'], v['sources']['Prayer'], v['dopplezon']),
         (2500, 5000, {'charm': 35}, 0), 'the edited fields reach the save')
    T.eq(sorted(lv for _, lv, _ in v['delirium']), [61, 63], 'Delirium levels as edited')
    T.check('lists 178/198' in M.plan_line(P, raw) and f'{len(raw)}/8191 bytes' in M.plan_line(P, raw), 'plan line')
    T.eq(v['bo_pct'], 35 + 3 * 98, 'BO 99 on the shield: +329%')
    T.eq([M.options(k)['bo'] for k in M.PRESET_ORDER], [99] * len(M.PRESET_ORDER), 'BO defaults to 99 everywhere')
    T.eq(int(v['mana']), P['o']['best_mana'], 'host: 1572500 capped at the overheal-safe mana, WITH BO')
    T.check(any(c[0] == 'mana_nobo' for c in a['checks']), 'the analyzer shows the mana without BO too')
    raw, P = M.generate('mock_high', 'NoBo', bo=0)
    a, m, _ = _analyze(M.write_new(raw, folder, 'NoBo'))
    T.eq((a['values']['bo_pct'], int(a['values']['mana'])), (0, P['o']['best_mana']),
         'BO 0: no BO line, mana without BO')


@T.test
def new_files_never_overwrite():
    E = engine()
    M = E.M
    folder = T.guard(os.path.join(T.tmp(), 'mocknames'), 'name test folder')
    os.makedirs(folder)
    raw, _ = M.generate('mock_high', 'Dup')
    p1 = M.write_new(raw, folder, 'Dup')
    before = T.read(p1)
    p2 = M.write_new(raw, folder, 'Dup')
    T.eq((os.path.basename(p1), os.path.basename(p2)), ('Dup.d2s', 'Dupa.d2s'), 'second file gets a letter suffix')
    T.eq(T.read(p1), before, 'the first file is untouched')
    T.eq(T.read(p2)[0x14:0x19], b'Dupa\0', 'the name inside the file follows')
    E.MC.Character(p2, E.data)
    for bad in ('Mock1', 'a', '-Mock', 'Mo--ck'):
        try:
            M.write_new(raw, folder, bad)
            T.check(False, f'{bad!r} accepted')
        except M.PlanError:
            pass




@T.test
def read_only_clone_stays_read_only_after_an_editor_save():
    """Mock clones are made read-only (the game cannot save them: xp at level 127 resets it to 99); a save from
    the editor writes the file and makes it read-only again."""
    E = engine()
    folder = T.guard(os.path.join(T.tmp(), 'mockro'), 'read-only test folder')
    os.makedirs(folder)
    raw, _ = E.M.generate('mock_high', 'Ro')
    p = E.M.write_new(raw, folder, 'Ro', read_only=True)
    T.check(E.MC.is_read_only(p), 'the new clone is read-only')
    ch = E.MC.Character(p, E.data)
    ch.save(backup=False)
    T.check(E.MC.is_read_only(p), 'still read-only after the editor saved it')
    T.eq(T.read(p), ch.raw, 'the save went through')
    E.MC.set_read_only(p, False)


@T.test
def mastery_percent_per_holy_aura():
    """Holy Freeze / Shock / Fire each take a mastery % typed by hand (tester: only HF had a mastery setting)."""
    M = engine().M
    names = {k for _tab, fields in M.FIELDS for k, *_r in fields}
    P = M.plan('mock_high', 'Mast', hfire_level=500, hfire_sources=2, hsk_level=500, hsk_sources=2,
               hf_mast_pct=1234, hsk_mast_pct=2345, hfire_mast_pct=3456)
    t = M.totals(M.model_from_plan(P))['T']
    T.eq((t.get(331), t.get(330), t.get(329)), (1234, 2345, 3456), 'cold / lightning / fire mastery written')
    T.check({'hf_mast_pct', 'hsk_mast_pct', 'hfire_mast_pct'} <= names, 'the three fields are on the form')

@T.test
def calc_keeps_a_typed_holy_freeze_level():
    """Calc of the Auras page solves Holy Fire from its target and keeps a Holy Freeze level typed by hand
    (tester: Calc put Holy Freeze back while setting Holy Fire)."""
    M = engine().M
    pre = M.prefill('mock_high')
    fields = dict(pre)
    hf = int(pre['hf_level']) + 7
    fields.update(hf_level=str(hf), hfire_target='2000000', hfire_sources='1')
    vals = M.calc_group('mock_high', 'Auras', fields, pre)
    T.check('hf_level' not in vals or int(vals['hf_level']) == hf, f"typed Holy Freeze level kept: {vals.get('hf_level')}")
    T.check(int(vals['hfire_level']) > 0, f"Holy Fire level solved from its target: {vals['hfire_level']}")
    fields.update(hf_target='5000000', hf_solve=True)
    vals = M.calc_group('mock_high', 'Auras', fields, pre)
    T.check(int(vals['hf_level']) != hf, 'with an HF damage target typed, Calc solves the HF level')

@T.test
def max_holy_fire_and_smite_stay_under_the_roll_unrounded():
    """Tester: a max Holy Fire and a max Smite rolled in game. Holy Fire (HitShift 7) has half points that its
    mastery multiplies; str/lvl strength keeps its fraction. Both are checked with no rounding."""
    M = engine().M
    r = M.solve_aura_dmg(M.HOLY_FIRE, M.ROLL)
    lo, hi = M.aura_raw_dmg(M.HOLY_FIRE, r['level'])
    internal = hi + hi * r['mast'] // 100
    T.check(internal < 2 ** 31, f'Holy Fire max {internal} (1/256) stays under 2^31')
    T.check(Fraction(hi, 256) * (100 + r['mast']) / 100 < M.ROLL + 1, 'exact Holy Fire max under the roll')
    T.check(r['max'] >= M.ROLL * 0.999, f"still a max Holy Fire: {r['max']}")
    P = M.plan('mock_high', 'X', smite_max=True)
    sm = P['smite']
    _smin, smax = M.shield_dmg(M.SHIELD_DEFAULT)
    mult = Fraction(sm['mult'])
    T.check((smax + sm['dmg']) * mult / 100 < M.ROLL + 1, f"exact max Smite under the roll: {sm['max']}")
    T.check(mult.denominator in (1, 2, 4, 8), 'the strength keeps its str/lvl fraction')

@T.test
def funky_mana_shows_a_flat_000():
    """A funky mana is exact and shown as such (.000); the mana ranges follow the TK."""
    M = engine().M
    P = M.plan('funky', 'Fk')
    a = M.analyze(M.model_from_plan(P), bo=True)
    line = next(text for key, _lab, text, _st in a['checks'] if key == 'mana')
    T.check(line.startswith('1048576.000'), line)
    T.check('1,048,576.000' in M.mana_ranges(30) and '2,097,152-3,145,727' in M.mana_ranges(30), M.mana_ranges(30))

@T.test
def weapon_by_hand_in_a_dopplezon_build_adds_its_lists():
    """Tester: Weapon on + a 5242880 funky said "cannot be hit on 178 lists" (Dopplezon dropped the weapon). A
    weapon asked for by hand is a dex-bug weapon there: 198 lists, the mana exact."""
    M = engine().M
    P = M.plan('funky', 'Fk', tk=30, mana=5242880, weapon=True)
    T.eq((P['mana']['mana'], len(P['lists']), P['o']['dex_bug']), (5242880, 198, True), 'weapon kept as dex-bug')
    T.eq(len(M.plan('funky', 'Fk')['lists']), 178, 'no weapon unless asked for')

@T.test
def smite_max_and_efficient_modes():
    """Max smite: max = 8388607 exactly, min = (shield min + damage) x mult (no +min line: stat 21 does not reach
    Smite in game, duel 2026-11-22); the analyzer ignores stat 21 too. Efficient: within 0.1% of the cap."""
    M = engine().M
    P = M.plan('mock_high', 'X', smite_max=True)
    mx = P['smite']
    smin = M.SHIELD_DMG['tow '][0]
    T.eq((mx['max'], mx['min']), (M.ROLL, (smin + mx['dmg']) * mx['mult'] // 100), 'max mode: max at the cap')
    T.check(mx['min'] < mx['max'], 'max mode: the shield spread stays')
    T.check(not any(l[0] == 21 for u in P['units'] for s in u.slots for l in s.lines), 'no +min damage line')
    m = M.model_from_plan(P)
    t = M.totals(m)
    a = M.smite_of(m, t)
    t['T'][21] = t['T'].get(21, 0) + 4
    T.eq(M.smite_of(m, t)['min'], a['min'], 'stat 21 does not change the smite min')
    ef = M.plan('mock_high', 'X')['smite']
    T.check(M.ROLL * 0.999 <= ef['max'] <= M.ROLL, f"efficient mode within 0.1%: {ef['max']}")


@T.test
def holy_shield_adds_smite_damage_before_the_multiplier():
    """Holy Shield (skill 117; skills.bin MinDam 3 / MaxDam 6, +2/3/4/4/4 per level bracket) adds its damage to the
    shield's range before the Smite multiplier (1.13c D2Game SrvDo150 reads the holyshield state's stat list); the
    NV state alone (stat 98 = 101) adds nothing. Max mode with holy_shield_cast keeps the max exactly at the cap."""
    M = engine().M
    T.eq([M.holy_shield_dmg(l) for l in (0, 1, 2, 8, 9, 16, 17, 20, 22, 23, 29)],
         [(0, 0), (3, 6), (5, 8), (17, 20), (20, 23), (41, 44), (45, 48), (57, 60), (65, 68), (69, 72), (93, 96)],
         'Holy Shield damage per level')
    P = M.plan('mock_high', 'X', smite_max=True)
    m = M.model_from_plan(P)
    t = M.totals(m)
    base = M.smite_of(m, t)
    T.eq(base['hs_lvl'], 0, 'no Holy Shield skill: no bonus')
    t['T'][98] = t['T'].get(98, 0) + 1                  # the NV state only
    T.eq(M.smite_of(m, t)['max'], base['max'], 'the NV state alone adds nothing')
    t['nonclass'][M.HOLY_SHIELD] = 15
    m['skills'][M.HOLY_SHIELD] = 5                      # hard points + oskill: level 20 (57-60)
    hs = M.smite_of(m, t)
    smin, smax = M.SHIELD_DMG['tow ']
    d, mult = P['smite']['dmg'], base['mult']
    T.eq((hs['hs_lvl'], hs['min'], hs['max']),
         (20, (smin + 57 + d) * mult // 100, (smax + 60 + d) * mult // 100), 'Holy Shield 20 before the multiplier')
    t['nonclass'][M.HOLY_SHIELD] = 120
    T.eq(M.smite_of(m, t)['hs_lvl'], 99, 'Holy Shield level capped at 99')
    for lv in (20, 70):
        P = M.plan('mock_high', 'X', smite_max=True, holy_shield_cast=lv)
        sm = P['smite']
        T.eq(sm['max'], M.ROLL, f'max mode with Holy Shield {lv}: max exactly at the cap')
        m = M.model_from_plan(P)
        a = M.smite_of(m, M.totals(m))
        T.eq((a['hs_lvl'], a['max'], a['min']), (lv, sm['max'], sm['min']), f'analyzer = plan with Holy Shield {lv}')
    raw, P = M.generate('mock_high', 'Xs', smite_max=True, holy_shield_cast=20)
    v = M.analyze(M.model_from_plan(P, raw))['values']['smite']
    T.eq((v['hs_lvl'], v['max']), (20, M.ROLL), 'the written save scores Holy Shield 20 at the cap')


@T.test
def size_tricks_and_bulk_lines():
    """The clones' size tricks (editor-tricks.txt): socketed jewels normal quality without the picture field,
    charms superior without it (a q2 no-picture jewel round-trips byte for byte, the editor reads it back); the
    room under the size budget is filled with target-neutral bulk lines on charms and jewels (replenish life on
    every list; resist by level first on a Host; absorb is planned to its need, not bulk); the target lines
    (life, +mana) go on the charms first; one line per stat per list; every preset stays under the budget."""
    E = engine()
    M = E.M
    isc, base = M.isc_from_data(E.data), M.base_from_data(E.data)
    jew = dict(flags=M.FLAG_IDENTIFIED | M.FLAG_ALWAYS | M.FLAG_RUNEWORD, version=M.ITEM_VERSION, location=6,
               equipped=0, x=0, y=0, panel=0, code='jew ', socketed_count=0, id=12345, ilvl=90, quality=2,
               image=None, auto_affix=None, runeword_id=0xFFFF, realm_bit=0, lists=[[(74, None, 33)]],
               rw_list=[(288, None, 4194303)])
    b = M.encode_item(jew, isc, base)
    r, end = M.decode_item(b, isc, base)
    T.eq((end, r['quality'], r['image'], M.encode_item(r, isc, base)), (len(b), 2, None, b), 'q2 no-img jewel')
    with_img = M.encode_item(dict(jew, quality=3, image=0, subquality=1), isc, base)
    T.check(len(b) <= len(with_img), 'no sub-quality and no picture: never larger (6 bits less)')
    budget = M.FILE_LIMIT - 1 - M.SIZE_MARGIN
    folder = _gen_dir()
    for key, at in [(k, None) for k in M.PRESET_ORDER] + [('mock_high', False)]:
        raw, P = M.generate(key, 'Bulk', abs_time=at)
        T.check(len(raw) <= budget, f'{key}: {len(raw)} bytes under {budget}')
        host = P['o']['position'] == 'Host'
        # the first bulk stat: Host resist by level, else replenish
        first = 230 if host else 74
        for u in P['units']:
            for sl in u.slots:
                keys = [(sid, p) for sid, p, _ in sl.lines]
                T.eq(len(keys), len(set(keys)), f'{key}: {u.name}: one line per stat per list')
                T.check(sl.count() <= M.LINE_CAP, f'{key}: {u.name}: at most {M.LINE_CAP} lines per list')
                if u.side != 'B':
                    T.check(all(sl.has(x) for x in (234, 235, 236)), f'{key}: {u.name}: absorb by level')
            room = P['bulk_lines'] >= 3 * len(P['lists']) + 40      # the size budget reached the role's bulk
            if u.kind == 'charm' and room and not P['o']['switch']:
                T.check(u.slots[0].has(first), f'{key}: {u.name}: bulk stat {first}')
                T.check(u.slots[0].has(7) and (P['o']['switch'] or u.slots[0].has(9)),
                        f'{key}: {u.name}: the life / +mana lines sit on the charms first')
        path = M.write_new(raw, folder, 'Bulk')
        ch = E.MC.Character(path, E.data)
        q = set()
        for e in ch.items:
            recs = M.decode_blob(e.blob, isc, base)
            q |= {(x['code'], x['quality'], x['image']) for x in recs if x['code'] in ('jew ', 'cm1 ')}
        T.eq(q, {('jew ', 2, None), ('cm1 ', 3, None)}, f'{key}: jewels q2 / charms q3, no picture field')



# proven clones per role (clone profile, docs/review/mock-pi-data/clone-profile.txt); clone-99 is the user's own
ROLE_CLONES = {
    'mock': ['clone-02', 'clone-80', 'clone-77', 'clone-90', 'clone-13', 'clone-10', 'clone-67',
             'clone-92', 'clone-53', 'clone-34', 'clone-85', 'Assault', 'Cold', 'Glitch',
             'clone-33', 'Hero', 'clone-70', 'clone-86', 'clone-105', 'clone-73', 'clone-81'],
    'host': ['clone-45', 'clone-09', 'clone-32', 'clone-64'],
    'pt': ['clone-104', 'clone-87', 'clone-76', 'clone-29'],
    'ak': ['clone-05', 'clone-96', 'clone-39', 'clone-58'],
    'funky': ['clone-99', 'clone-63', 'clone-65', 'clone-41', 'clone-60', 'clone-69'],
}


@T.test
def every_preset_has_every_clone_category():
    """The clone profile holds on the samples (each 'always' category is carried by >= 2/3 of the role's clone
    sides) and every preset's generated save carries every one of them, on both weapon sides, with a total of at
    least a third of the clones' median."""
    E = engine()
    M = E.M
    found = {}
    for f in sorted(glob.glob(os.path.join(E.saves, '**', '*.d2s'), recursive=True)):
        base = os.path.splitext(os.path.basename(f))[0]
        role = next((r for r, L in ROLE_CLONES.items() if base in L), None)
        if role is None or (role, base) in found:
            continue
        m = E.M.model_from_character(E.MC.Character(f, E.data))
        found[(role, base)] = [M.category_totals(m, sd) for sd in M.sides(m)]
    for role, prof in M.CLONE_PROFILE.items():
        sides = [ct for (r, _), L in found.items() if r == role for ct in L]
        T.check(len(sides) >= 3, f'{role}: {len(sides)} clone sides in the samples')
        for k in prof['always']:
            n = sum(1 for ct in sides if ct[k][1])
            T.check(3 * n >= 2 * len(sides), f'{role}: {k} on {n} of {len(sides)} clone sides')
    folder = _gen_dir()
    for key in M.PRESET_ORDER:
        role = M.PRESET_ROLE[key]
        raw, P = M.generate(key, 'Prof')
        m = E.M.model_from_character(E.MC.Character(M.write_new(raw, folder, 'Prof'), E.data))
        for sd in M.sides(m):           # side B only on a switch (otherwise weapon slot II is empty in game)
            T.eq(M.profile_missing(m, role, sd), [], f'{key} side {sd}: no clone category missing')
        ct = M.category_totals(m, 'A')
        for k in M.CLONE_PROFILE[role]['always']:
            t = M.CLONE_PROFILE[role]['typical'].get(k)
            if t and t > 0:
                T.check(ct[k][0] * 3 >= t, f'{key}: {k} total {ct[k][0]} vs the clones {t}')


@T.test
def plan_model_matches_the_written_save():
    """The summary panel of the generator (model_from_plan, no file) shows what the analyzer reads from the
    written save, on both weapon sides: same checks, same summary rows; an inactive switch counts nothing."""
    E = engine()
    M = E.M
    folder = _gen_dir()
    for key in M.PRESET_ORDER:
        raw, P = M.generate(key, 'Same')
        mp = M.model_from_plan(P, raw)
        mc = M.model_from_character(E.MC.Character(M.write_new(raw, folder, 'Same'), E.data))
        role = M.PRESET_ROLE[key]
        for sd in ('A', 'B'):
            T.eq(M.analyze(mp, sd, bo=True)['checks'], M.analyze(mc, sd, bo=True)['checks'], f'{key} {sd}: checks')
            T.eq(M.summary_rows(mp, sd, True, role), M.summary_rows(mc, sd, True, role), f'{key} {sd}: summary')
    raw, P = M.generate('balance_switch', 'Sw')
    m = M.model_from_plan(P, raw)
    a, b = M.category_totals(m, 'A'), M.category_totals(m, 'B')
    T.check(a['stun'][1] > 0 and b['stun'][1] == 0, 'balance switch: stun only on side A (the inactive shield adds none)')
    T.check(a['mana'][0] != b['mana'][0], 'balance switch: each side has its own +mana total')
    rows = M.summary_rows(m, 'A', True, 'mock')
    sect = {r[0] for r in rows}
    T.check({'Caps', 'Auras', 'Defenses', 'Speeds', 'Damage', 'Life / mana', 'Clone profile'} <= sect,
            f'summary sections {sorted(sect)}')
    hf = next(r for r in rows if r[0] == 'Auras' and r[1] == 'Holy Freeze')
    T.check('7 source(s)' in hf[2] and 'tow@5 (7 jewel(s))' in hf[2], f'Holy Freeze row groups its sources: {hf[2]}')
    T.eq(hf[4], (('tow@5', ', '.join(f'tow@5/{j}' for j in range(7))),), 'every active source listed')


@T.test
def form_validation_names_the_field():
    """validate(): a bad number, a value out of range or a target the plan cannot reach is reported on its field."""
    M = engine().M
    pre = M.prefill('mock_high')
    T.eq(M.validate('mock_high', dict(pre), pre)[3], {}, 'untouched form: no problem')
    for form, key in ((dict(pre, thorns='x1'), 'thorns'), (dict(pre, level='140'), 'level'),
                      (dict(pre, mana='1100000'), 'mana'), (dict(pre, hf_sources='45'), 'hf_sources'),
                      (dict(pre, switch='balance', mana_b='900000'), 'mana_b')):
        errs = M.validate('mock_high', form, pre)[3]
        T.eq(list(errs), [key], f'{key}: reported on its field ({errs})')
    over, raw, P, errs = M.validate('mock_high', dict(pre, ias='-100', res_light='630', just_hit=True), pre)
    T.eq((over, errs), (dict(ias=-100, res_light=630, just_hit=True), {}), 'edited speed / resist / NV state')
    T.eq(P['o']['ias'], -100, 'the edited IAS reaches plan()')


@T.test
def stat_totals_limited_by_file_size_not_made_up_caps():
    """No made-up upper limits on stat totals: 8000+ res/lvl is accepted when it fits, an absurd value gives the
    size warning (with the costliest fields) instead of a field-range error."""
    M = engine().M
    pre = M.prefill('mock_high')
    errs = M.validate('mock_high', dict(pre, res_fire='60000'), pre)[3]
    T.eq(errs, {}, '60000 total fire resist fits')
    o, raw, P, errs = M.validate('mock_high', dict(pre, res_fire='60000', level='99'), pre)
    T.eq(errs, {}, '60000 total at clvl 99 fits')
    rl = sum(v for l in P['lists'] for sid, _p, v in l.lines if sid == 231)
    T.check(60000 <= M.element_res(0, rl, 99, 10 ** 6) < 60013, 'res/lvl sum gives the total (+ step rounding)')
    errs = M.validate('mock_high', dict(pre, res_fire='2000000000'), pre)[3]
    T.check(list(errs) == [''] and 'over the 8 KB save limit' in errs[''] and 'res_fire' in errs[''], f'size warning: {errs}')


@T.test
def prayer_drain_energy_vitality_and_dtm_ceiling():
    """Prayer drains 1 + 0.1875 (L - 1) per source per pulse; item Energy (stat 1) / Vitality (stat 3) add after
    the % boost (in game: sorceress 1000 base, +50%, +90 Energy / Vitality -> 1680 mana and life); the
    DTM ceilings (HPJ without, LPJ with the doubled drain x TK ratio)."""
    M = engine().M
    T.eq((M.prayer_drain(1), M.prayer_drain(17), M.prayer_drain(0)), (1, 4, 0), 'Prayer drain per pulse')
    T.eq(M.prayer_drain(5518), Fraction(16 + 3 * 5517, 16), 'Prayer 5518')
    t = dict(T={77: 50, 1: 90, 76: 50, 3: 90}, side='A', nonclass={}, aura_lv={})
    m = dict(cls=1, base_mana_raw=256 * 1000, base_life_raw=256 * 1000, set_ids={None: set(), 'A': set()},
             skills={})
    T.eq(M.mana_of(m, t)[0], 1680, 'Sorceress: item Energy after the % (in game 1680)')
    T.eq(M.life_of(m, t), 1680, 'Sorceress: item Vitality after the % (in game 1680)')
    hpj = M.dtm_ceiling(1572500, 11214)
    T.eq(round(float(hpj), 2), round((8388607 - 1572500) / ((1426063 - 11214) * 0.5) * 100, 2), 'HPJ ceiling')
    d = M.prayer_drain(5518)
    lpj = M.dtm_ceiling(1572500, 11214, d, 31)
    T.eq(round(float(lpj), 2), round((8388607 - 1572500) / ((1426063 + 2 * float(d) * 16 - 11214) * 0.5) * 100, 2),
         'LPJ ceiling')
    for key in M.PRESET_ORDER:
        P = M.plan(key, 'Dtm')
        a = M.analyze(M.model_from_plan(P), bo=True)
        c = [x for x in a['checks'] if x[0] == 'dtm_cap']
        T.check(c and c[0][3] == M.GOOD, f'{key}: DTM under the ceiling ({c[0][2] if c else "no check"})')


@T.test
def thorns_barbs_safe_window():
    """Thorns + Barbs return wraps at 2^24 (negative above 2^23): with Thorns 4278 against DR 11214 / 50% and ES
    off the positive Barbs windows are 1-887, 1836-2784, 3733-4278 (the return is not floored; safe_barbs still finds them for a user's
    Barbs); every preset's written save's return check is good (ES up and gone)."""
    M = engine().M
    pos = [lv for lv in range(1, 4279) if M.thorns_return(4278, lv, 11214, 255) > 0]
    runs, start = [], pos[0]
    for a, b in zip(pos, pos[1:] + [None]):
        if b != a + 1:
            runs.append((start, a))
            start = b
    T.eq(runs, [(1, 887), (1836, 2784), (3733, 4278)], 'ES-off windows')
    T.eq(M.safe_barbs(4278, 3472, 11214, 255), 2784, '112 lists -> 2784')
    T.eq(M.safe_barbs(4278, 2784, 11214, 255), 2784, 'the window edge itself')
    T.eq(M.safe_barbs(4278, 3500, 11214, 255), 2784, 'the ES-off gap is skipped')
    for key in M.PRESET_ORDER:
        raw, P = M.generate(key, 'Thorn')
        if not P['o']['thorns']:
            continue                                        # funkies / Aura Killer: no Thorns (rule 1 test)
        c = [x for x in M.analyze(M.model_from_plan(P))['checks'] if x[0] == 'thorns_return']
        T.check(c and c[0][3] == M.GOOD, f'{key}: return a positive hit ({c[0][2] if c else "no check"})')
    m = M.model_from_plan(M.plan('mock_high', 'Thorn', barbs=3100))
    c = [x for x in M.analyze(m)['checks'] if x[0] == 'thorns_return']
    T.eq(c[0][3], M.WARN, 'Barbs 3100: the return rolls over with ES off')


@T.test
def old_save_versions_open():
    """A pre-1.10 save (header version 92, 1.09) opens: its u32 stats and 1.09 item records are read (test 94 has
    the details); the version 96 samples (vanilla 1.10+, Median XL) still open."""
    E = engine()
    old = [f for f in glob.glob(os.path.join(E.saves, '**', '*.d2s'), recursive=True) if T.read(f)[4] == 92]
    T.check(any(os.path.basename(f) == 'clone-59.d2s' for f in old), 'clone-59 is a version 92 save')
    for f in old:
        ch = E.MC.Character(f, E.data)
        T.check(ch.old and ch.stat(12) > 0, 'version 92 opened and level read')
        report = E.M.analyze(E.M.model_from_character(ch))
        T.check(report['checks'] and report['values']['mana'] >= 0, 'version 92 analyzed')
    E.MC.Character(_sample('clones/clone-35.d2s'), E.data)


@T.test
def thorns_override_picks_a_safe_barbs():
    """Thorns set by the user, Barbs left to the plan: Barbs 0 when that Thorns alone is safe, else the highest
    safe Barbs; the return stays a positive hit with the target's Energy Shield up and gone."""
    M = engine().M
    for th in (3000, 3500, 4000):
        raw, P = M.generate('mock_high', 'ThOver', thorns=th)
        o = P['o']
        dr = M.totals(M.model_from_plan(P))['T'].get(34, 0)
        on = M.thorns_return(th, int(o['barbs']), dr, int(o['dr_pct']), M.ES_ABSORB)
        off = M.thorns_return(th, int(o['barbs']), dr, int(o['dr_pct']), 0)
        T.check(0 < on < M.ROLL * Fraction(99, 100) and off > 0, f'Thorns {th}, Barbs {o["barbs"]}: {on} / {off}')
        T.eq(o['barbs'], 0 if M.thorns_safe(th, 0, dr, int(o['dr_pct'])) else o['barbs'], f'Thorns {th}: Barbs 0')


def _lines(P):
    return [(sid, p) for s in P['lists'] for sid, p, _ in s.lines]


@T.test
def rule_no_item_vitality_or_energy():
    """User rule 1: the generator never writes item Vitality (stat 3) nor item Energy (stat 1) and no base
    Vitality / Energy; the analyzer warns on item Vitality and notes item Energy on a read save."""
    M = engine().M
    for key in M.PRESET_ORDER:
        P = M.plan(key, 'Vit')
        T.check(not [x for x in _lines(P) if x[0] in (1, 3)], f'{key}: no stat 1 / 3 line')
        m = M.model_from_plan(P)
        T.eq((m['base_vit'], m['base_ene'], m['stat_points']), (0, 0, 0), f'{key}: no base Vitality / Energy')
    m = M.model_from_plan(M.plan('mock_high', 'Vit'))
    m['units'][0].lists[0] += [(3, None, 50), (1, None, 20)]
    st = {c[0]: c[3] for c in M.analyze(m)['checks']}
    T.eq((st.get('vitality'), st.get('energy')), (M.WARN, M.INFO), 'analyzer: Vitality warned, Energy noted')


@T.test
def rule_thorns_first_barbs_only_if_needed():
    """User rule 2: every preset's Thorns is the highest the non-charm lists take (31 per list) whose return alone
    is safe (ES up and gone) and its Barbs is 0 when that Thorns alone is safe."""
    M = engine().M
    for key in M.PRESET_ORDER:
        if M.PRESETS[key].get('thorns') == 0:
            continue                                        # no Thorns at all (rule_no_thorns_on_funky_and_ak)
        raw, P = M.generate(key, 'Thorn')
        o = P['o']
        dr = M.totals(M.model_from_plan(P))['T'].get(34, 0)
        es = Fraction(o['es'], 100)
        cap = M.AURA_LINE_MAX * sum(1 for s in P['lists'] if s.unit.kind != 'charm')
        T.eq(o['thorns'], M.max_thorns(cap, dr, int(o['dr_pct']), es), f'{key}: Thorns maximised ({cap} cap)')
        T.check(M.thorns_safe(o['thorns'], 0, dr, int(o['dr_pct']), es), f'{key}: Thorns alone safe')
        T.eq(o['barbs'], 0, f'{key}: Barbs 0 (Thorns alone is safe)')
        T.check(not [x for x in _lines(P) if x == (151, M.BARBS)], f'{key}: no Barbs line')
    T.eq((M.plan('mock_high', 'T')['o']['thorns'], M.plan('mock_high', 'T', weapon=True, dex_bug=True)['o']['thorns']),
         (4278, 4898),
         '138 / 158 non-charm lists x 31')
    # a Thorns the return rolls with alone: Barbs comes back only then (the ES-off windows above)
    th = next(t for t in range(4278, 0, -1) if not M.thorns_safe(t, 0, 11214, 255)
              and M.safe_barbs(t, 3000, 11214, 255))
    T.check(M.pick_barbs(th, 3000, 11214, 255) > 0, f'Thorns {th} unsafe alone -> Barbs')
    T.eq(M.pick_barbs(4278, 3000, 11214, 255), 0, 'Thorns 4278 safe alone -> Barbs 0')
    st = {c[0]: c for c in M.analyze(M.model_from_plan(M.plan('mock_high', 'T', barbs=500)))['checks']}
    T.check('Barbs 0 saves' in st['thorns_return'][2], 'analyzer: Barbs not needed')


@T.test
def rule_es_and_tk_defaults_drive_everything():
    """User rule 3: target ES 95% and TK 31 by default (form fields 'es' / 'tk'); a changed ES or TK re-solves
    the Thorns safety, the DTM (refill vs the LPJ ceiling) and a funky's mana - no stale constants."""
    M = engine().M
    T.eq((M.DEFAULTS['es'], M.DEFAULTS['tk'], M.FIELD_KIND['es']), (95, 31, 'int'), 'defaults + form field')
    for key in M.PRESET_ORDER:
        o = M.plan(key, 'Es')['o']
        T.eq(o['es'], 95, f'{key}: ES 95')
        if M.PRESET_ROLE[key] != 'funky':
            T.eq(o['tk'], 31, f'{key}: TK 31')
    T.eq(M.prefill('mock_high')['es'], 95, 'form prefill ES')
    hi = M.plan('mock_high', 'Es')
    lo = M.plan('mock_high', 'Es', es=80)
    b, b2 = hi['balance'], lo['balance']
    T.check(b2['need'] < b['need'], f"ES 80 needs less DTM refill ({float(b2['need']):.0f} < {float(b['need']):.0f})")
    T.check(lo['o']['thorns'] < hi['o']['thorns'], f"ES 80: lower safe Thorns ({lo['o']['thorns']})")
    T.check(M.thorns_safe(lo['o']['thorns'], lo['o']['barbs'], 11214, 255, Fraction(80, 100)), 'ES 80: safe')
    a = M.analyze(M.model_from_plan(lo))
    T.eq(a['values']['es'], Fraction(80, 100), 'analyzer uses the plan ES')
    T.eq({c[0]: c[3] for c in a['checks']}['thorns_return'], M.GOOD, 'ES 80: return check good')
    # TK: a funky at TK 28 is the TK 28 funky (mana, DTM at its LPJ ceiling: the refill is higher)
    f = M.plan('funky', 'Tk', tk=28)
    g = M.plan('funky28', 'Tk')
    T.eq((f['mana']['mana'], f['o']['dtm']), (g['mana']['mana'], g['o']['dtm']), 'TK 28 re-solves mana + DTM')
    T.eq(f['o']['dtm'], math.floor(f['balance']['lpj']), 'TK 28: DTM at the LPJ ceiling')
    T.check(f['balance']['need'] > f['balance']['lpj'], 'TK 28: refill over the ceiling')
    T.eq(M.plan('mock_high', 'Tk')['o']['dtm'], 330, 'TK31 LPJ: the position DTM (refill 282 under it)')
    T.eq(round(float(M.dtm_need(Fraction(95, 100), 31, 11214, 255))), 282, 'refill ES95 / TK31')
    model = M.model_from_plan(M.plan('mock_high', 'TkZero'))
    model.pop('target_tk')
    model['skills'].pop(M.TELEKINESIS)
    a = M.analyze(model)['values']
    T.eq(a['dtm_need'], M.dtm_need(a['es'], 0, a['dr'], a['dr_pct']), 'a save with no TK points uses TK 0')


@T.test
def rule_holy_shield_off_by_default():
    """User rule 4: Holy Shield (the oskill on the shield) is an optional form setting, off by default."""
    M = engine().M
    T.eq(M.DEFAULTS['holy_shield_cast'], 0, 'default off')
    for key in M.PRESET_ORDER:
        P = M.plan(key, 'Hs')
        T.eq(P['o']['holy_shield_cast'], 0, f'{key}: off')
        T.check(not [x for x in _lines(P) if x == (97, M.HOLY_SHIELD)], f'{key}: no Holy Shield oskill')
    P = M.plan('mock_high', 'Hs', holy_shield_cast=5)
    T.check((97, M.HOLY_SHIELD) in _lines(P), 'on when set')


@T.test
def rule_absorb_need_filled_by_level_then_by_time():
    """User rule 5 (reference calculator): the absorb need is 8388607 x 0.17 x 0.6 x (100 - res) / 100 (res 75 ->
    213909.4785); absorb by character level first (63 x clvl / 8 a line, one per list), the rest by time in 767
    lines. In game (2026-11-22 duels) by time works on gear / jewels, not on charms, and the game sums the RAW
    fields of several lines into one, so the plan writes ONE by-time line (at most 767) per element on a jewel or
    gear magic list; the analyzer models the summed field and warns on charm / stacked lines."""
    M = engine().M
    T.eq(float(M.absorb_need(75)), 213909.4785, 'need at res 75')
    T.eq(M.absorb_fill(M.absorb_need(75), 127, 178), (178, [767]), '178 by clvl + one 767 line')
    T.eq(M.absorb_fill(1000, 127, 178), (1, []), 'under one by-clvl line: one by-clvl line')
    T.eq(M.absorb_fill(1000, 127, 0), (0, [767]), 'no list free: one by-time line, capped at 767')
    T.eq(M.abs_time_game([M.abs_time_raw(767), M.abs_time_raw(10)]), 10, 'game: 767 + 10 lines decode as 10')
    T.eq(M.abs_time_game([4194303] * 2), 767, 'game: 767 + 767 is still 767')
    T.eq(M.absorb_fill(M.absorb_need(75), 127, 300), (214, []), 'more lists: by clvl only, rounded up to the need')
    T.eq((M.abs_time_raw(767), M.abs_time_value(M.abs_time_raw(605)), M.abs_time_value(4194303)),
         (4194303, 605, 767), 'by-time field: time 3, min = max, stored +256')
    T.eq(M.DEFAULTS['abs_time'], True, 'by time on where the need requires it')
    for key in M.PRESET_ORDER:
        raw, P = M.generate(key, 'Abs')
        A = P['o']['absorb']
        L = [(s.unit.kind, s.idx, sid, v) for s in P['lists'] for sid, _, v in s.lines]
        st = {c[0]: c[3] for c in M.analyze(M.model_from_plan(P, raw))['checks']}
        for name, _, _, _, sid_l, sid_t in M.ELEMENTS:
            a = A[name]
            T.eq(sum(1 for x in L if x[2] == sid_l), a['lvl'], f'{key} {name}: by-clvl lines')
            bt = [x for x in L if x[2] == sid_t]
            T.check(len(bt) <= 1, f'{key} {name}: at most one by-time line')
            T.check(all(k == 'jewel' or k == 'gear' and i == 0 for k, i, _, _ in bt), f'{key} {name}: on gear / a jewel')
            T.eq(sum(M.abs_time_value(x[3]) for x in bt), sum(a['time']), f'{key} {name}: by time')
            if a['res'] <= M.HELL_RES:
                T.eq(a['time'], [], f'{key} {name}: no by time (no resist)')
        # Sigon's full set supplies 12 fire resistance on top of the written lines.
        effective = {name: min(M.MAX_RES, a['res'] + (12 if name == 'fire' else 0)) for name, a in A.items()}
        short = any(res > M.HELL_RES and A[name]['total'] < int(M.absorb_need(res))
                    for name, res in effective.items())
        T.eq(st.get('absorb'), M.WARN if short else M.GOOD, f'{key}: absorb check with worn set bonuses')
        T.check('abs_time' not in st, f'{key}: no by-time warning on a generated file')
    P = M.plan('mock_high', 'Abs')
    T.eq((P['o']['absorb']['cold']['lvl'], P['o']['absorb']['cold']['time']), (178, [767]), 'mock_high cold')
    raw, P = M.generate('mock_high', 'Abs', abs_time=False)
    T.check(not [x for x in _lines(P) if x[0] in (288, 289, 290)], 'by time off on request')
    # clone-style by-time lines: on a charm they count 0, stacked on gear they decode as one field
    raw, P = M.generate('mock_high', 'Abs', abs_time=False)
    base = M.analyze(M.model_from_plan(P, raw))['values']['absorb']['cold']['total']
    charm = next(u for u in P['units'] if u.kind == 'charm')
    charm.slots[0].add(288, M.abs_time_raw(767))
    r = M.analyze(M.model_from_plan(P, M.build(P)))
    T.eq((r['values']['absorb']['cold']['total'], {c[0]: c[3] for c in r['checks']}.get('abs_time')),
         (base, M.WARN), 'charm by time: 0 and a warning')
    charm.slots[0].lines.pop()
    for j in [u for u in P['units'] if u.kind == 'jewel'][:2]:
        j.slots[0].add(288, M.abs_time_raw(767))
    r = M.analyze(M.model_from_plan(P, M.build(P)))
    T.eq((r['values']['absorb']['cold']['total'] - base, {c[0]: c[3] for c in r['checks']}.get('abs_time')),
         (767, M.WARN), 'two jewel lines: one 767 field and a warning')


@T.test
def rule_every_preset_defaults_to_thorns():
    """User rule (2026-11-24): every preset, funkies and the Aura Killer included, defaults to a Thorns setup."""
    M = engine().M
    for key in M.PRESET_ORDER:
        raw, P = M.generate(key, 'Th')
        T.check(P['o']['thorns'] > 0 and (151, M.THORNS) in _lines(P), f'{key}: Thorns {P["o"]["thorns"]}')
        T.eq(M.prefill(key)['thorns'], P['o']['thorns'], f'{key}: form prefill')
        T.check(not [c for c in M.analyze(M.model_from_plan(P, raw), bo=True)['checks'] if c[3] == M.BAD], f'{key}: no bad check')


@T.test
def new_defaults_speeds_bo_stun_and_exact_funky_with_bo():
    """Speeds -121 / 107 / -36 / -121 / 0 / 97 on every preset; BO 99; stun at most 90 (100 only typed, a warning);
    a Funky is EXACT with BO cast, a fraction is BAD."""
    E = engine()
    M = E.M
    for key in M.PRESET_ORDER:
        o = M.options(key)
        T.eq(tuple(o[k] for k in ('ias', 'frw', 'fhr', 'fcr', 'nv_ias', 'nv_frw')), (-121, 107, -36, -121, 0, 97), f'{key}: speeds')
        T.check(M.prefill(key)['stun'] <= 90 and M.prefill(key)['stun_pct'] <= 90, f'{key}: stun at most 90')
        raw, P = M.generate(key, 'Sp')
        T.check(P['stun'] <= 90, f'{key}: stun line {P["stun"]}')
        v = M.analyze(M.model_from_plan(P, raw), bo=True)['values']
        T.eq((v['bo_pct'], P['o']['bo']), (35 + 3 * 98, 99), f'{key}: BO 99')
        if M.PRESET_ROLE[key] == 'funky':
            T.eq(v['mana'].denominator, 1, f'{key}: exact mana with BO ({v["mana"]})')
            T.eq(int(v['mana']), int(P['o']['mana']), f'{key}: the funky mana')
    P = M.plan('funky', 'S100', stun_pct=100)
    T.eq(P['stun'], 100, 'a typed 100% is allowed')
    c = {x[0]: x[3] for x in M.analyze(M.model_from_plan(P), bo=True)['checks']}
    T.eq(c['stun'], M.WARN, '... with a warning')
    m = M.model_from_plan(M.plan('funky', 'Fr'))
    t = M.totals(m, 'A')
    m['units'][0].lists[0].append((9, None, 1))             # +1 mana breaks the exact product
    a = M.analyze(m, 'A', bo=True)
    T.check(not a['values']['mana'].denominator == 1 and {x[0]: x[3] for x in a['checks']}['mana'] == M.BAD, 'fraction: BAD')


@T.test
def dr_total_respected_and_aura_sources():
    """DR: 63 on every list by default, a lower total puts lines only where needed; Holy Freeze / Shock / Fire
    levels place counted sources like Prayer / Meditation."""
    M = engine().M
    P = M.plan('mock_high', 'Dr')
    full = sum(v for s in P['lists'] for sid, _p, v in s.lines if sid == 34)
    T.eq(full, 63 * len(P['lists']), 'default: 63 on every list')
    T.eq(M.prefill('mock_high')['dr_total'], full, 'prefill shows the total')
    P2 = M.plan('mock_high', 'Dr2', dr_total=1000)
    ls = [v for s in P2['lists'] for sid, _p, v in s.lines if sid == 34]
    T.eq((sum(ls), len(ls)), (1000, 16), 'total 1000: 15 lines of 63 + 55, not every list')
    try:
        M.plan('mock_high', 'Dr3', dr_total=full + 1)
        T.check(False, 'a DR total beyond the available lists should be rejected')
    except M.PlanError as e:
        T.eq(e.key, 'dr_total', 'the impossible DR target is identified')
    for kw, aid, n in ((dict(hfire_level=1500, hfire_sources=3), M.HOLY_FIRE, 3),
                       (dict(hsk_level=2000, hsk_sources=2), M.HOLY_SHOCK, 2),
                       (dict(hf_level=3100, hf_sources=5), M.HOLY_FREEZE, 5)):
        P = M.plan('mock_high', 'Au', **kw)
        key = next(k for k, a in M.AURA_FIELD_SOURCE.items() if a == aid)
        T.eq(M.sources_of(P)[key], n, f'{M.AURA_NAMES[aid]}: sources shown')
        t = M.totals(M.model_from_plan(P), 'A')
        T.eq(sum(t['sources'].get(aid, {}).values()), n, f'{M.AURA_NAMES[aid]}: sources counted')
        T.eq(t['aura_lv'].get(aid), list(kw.values())[0], f'{M.AURA_NAMES[aid]}: level placed')


@T.test
def defense_totals_compare_with_generator_targets_on_both_sides():
    M = engine().M
    plan = M.plan('balance_switch', 'Df', dr_total=1000, pierce=117, pierce_fire=88,
                  res_cold=60000, abs_cold=20000, abs_fire=15000, abs_light=25000)
    model = M.model_from_plan(plan)
    targets = M.defense_targets(plan)
    side_b = next(unit for unit in model['units'] if unit.side == 'B' and unit.kind == 'gear')
    side_b.lists[0].extend([(34, None, 25), (333, None, 27)])

    def rows(side):
        return {key: (value, status) for key, _, value, status in M.analyze(model, side, targets=targets)['checks']}

    a, b = rows('A'), rows('B')
    T.eq(a['target_dr'], ('1007 / 1000 target', M.WARN), 'full-set DR is added to the written total')
    T.eq(b['target_dr'], ('1032 / 1000 target', M.WARN), 'DR follows the active switch')
    T.eq(a['target_pierce_cold'], ('117% / 117% target', M.GOOD), 'cold pierce')
    T.eq(b['target_pierce_fire'], ('115% / 88% target', M.WARN), 'fire pierce on B')
    T.eq(b['target_pierce_light'], ('0% / 0% target', M.GOOD), 'lightning shown even at zero')
    T.check('/ 60000% target (75% effective in Hell)' in a['target_res_cold'][0], 'uncapped resist compared')
    for name, target in (('cold', 20000), ('fire', 15000), ('light', 25000)):
        text, status = a['target_abs_' + name]
        T.check(f' / {target} target' in text and status == M.GOOD, f'{name} absorb compared: {text}')


@T.test
def aura_damage_targets_solved_per_formula():
    """A damage target per source picks the level + mastery with the fewest bits; Holy Fire and Holy Shock have
    different skills.bin formulas; the analyzer shows the damage per source and in total."""
    M = engine().M
    d = {a: [M.aura_base_dmg(a, l) for l in (10, 40)] for a in (M.HOLY_FIRE, M.HOLY_SHOCK, M.HOLY_FREEZE)}
    T.check(d[M.HOLY_FIRE] != d[M.HOLY_SHOCK], f'the formulas differ: {d}')
    tgt = {M.HOLY_FIRE: 6000000, M.HOLY_SHOCK: 4000000}
    P = M.plan('mock_high', 'Ad', hfire_target=tgt[M.HOLY_FIRE], hfire_sources=2, hsk_target=tgt[M.HOLY_SHOCK], hsk_sources=3)
    a = M.analyze(M.model_from_plan(P), bo=True)
    for aid, n in ((M.HOLY_FIRE, 2), (M.HOLY_SHOCK, 3)):
        lo, hi, got = a['values']['aura_damage'][M.AURA_NAMES[aid]]
        T.check(0.99 * tgt[aid] <= hi <= tgt[aid] and got == n, f'{M.AURA_NAMES[aid]}: {hi} per source of {tgt[aid]}, {got} sources')
    T.check({c[0]: c[3] for c in a['checks']}[f'auradmg_{M.HOLY_FIRE}'] == M.GOOD, 'damage check shown')
    r = M.solve_aura_dmg(M.HOLY_FIRE, tgt[M.HOLY_FIRE])
    T.eq(P['o']['hfire_level'], r['level'], 'the solved level reaches plan()')
    T.check(M.prefill('mock_high', hfire_target=tgt[M.HOLY_FIRE], hfire_sources=2)['hfire_level'] == r['level'], 'prefill shows it')
    target = 4000000
    P = M.plan('mock_high', 'Au', hf_sources=0, hf_target=target)
    a = M.analyze(M.model_from_plan(P))['values']['aura_damage']['Holy Freeze']
    T.eq(a[2], 1, 'a typed Holy Freeze damage target adds a source when the source count is zero')
    T.check(target - target // 1000 <= a[1] <= target, 'the Holy Freeze target uses the selected formula')


@T.test
def thorns_damage_target_uses_reflection_and_active_defenses():
    M = engine().M
    target = 1800000
    for es, dr in ((95, 1000), (90, 2000)):
        plan = M.plan('mock_high', 'Th', dr_total=dr, es=es, thorns_target=target)
        model = M.model_from_plan(plan)
        report = M.analyze(model)
        level = plan['o']['thorns']
        damage, maximum, sources = report['values']['aura_damage']['Thorns']
        T.eq((damage, maximum, sources), (M.thorns_return(level, 0, dr + 7, 255, Fraction(es, 100)),
                                        damage, 1), 'one source returns Thorns only')
        T.check(target * .99 <= damage <= target, f'closest safe hit to {target}: {damage}')
        T.eq(plan['o']['barbs'], 0, 'the safe Thorns hit needs no Barbs')
        T.check(any(key == f'auradmg_{M.THORNS}' and status == M.GOOD
                    for key, _, _, status in report['checks']), 'Thorns source damage is in the analyzer')
        T.check(any(section == 'Damage' and label == 'Thorns damage'
                    for section, label, *_ in M.summary_rows(model)), 'Thorns damage is in the generator summary')
    model['units'].append(M.Unit('charm', 'extra', [[(151, M.THORNS, 1)]]))
    a = M.analyze(model)['values']
    T.eq(a['sources']['Thorns'].get('charm'), 1, 'the added source is counted')
    returned = M.thorns_return(level + 1, 0, dr + 7, 255, Fraction(es, 100))
    T.eq(a['aura_damage']['Thorns'], (returned, returned, 1), 'both item sources form one aura')
    T.eq(M.solve_aura_dmg(M.THORNS, 1, max_lines=1), None, 'an unreachable target does not select an unsafe level')


@T.test
def absorb_totals_per_element_round_trip():
    """Absorb fields are TOTALS per element (cold / fire / lightning): the plan lands on the typed total, the
    analyzer shows it, the prefill gives it back; CB / DS are not generated and warned when added."""
    M = engine().M
    P = M.plan('mock_high', 'Ab', abs_cold=20000, abs_fire=15000, abs_light=25000)
    a = M.analyze(M.model_from_plan(P), bo=True)['values']['absorb']
    for el, t in (('cold', 20000), ('fire', 15000), ('light', 25000)):
        T.check(t <= a[el]['total'] < t + 1 and a[el]['total'] - t < 1, f'{el}: total {float(a[el]["total"])} for {t}')
    pre = M.prefill('mock_high', abs_cold=20000, abs_fire=15000, abs_light=25000)
    T.eq((pre['abs_cold'], pre['abs_fire'], pre['abs_light']), (20000, 15000, 25000), 'the fields round-trip')
    T.check(not {'cb', 'ds'} & set(M.FIELD_KEYS), 'the PvP generator has no CB or DS fields')
    raw, P = M.generate('mock_high', 'PvP', cb=50, ds=50, ow=35)
    T.check(not any(sid in (136, 141) for sid, _ in _lines(P)), 'the generator omits CB and DS')
    model = M.model_from_plan(P, raw)
    T.eq(M.totals(model)['T'].get(135), 35, 'Open Wounds is kept')
    model['units'][0].lists[0].extend([(136, None, 50), (141, None, 50)])
    T.check(any(c[0] == 'wasted_cb_ds' for c in M.analyze(model, bo=True)['checks']), 'CB and DS flagged on loaded items')


@T.test
def life_target_cheapest_and_dtm_check():
    """Life targets up and down land within 1 (or on the closest) with a cheap mix of +life / Oak Sage; an
    over-high DTM is a BAD check, the preset DTMs are good."""
    M = engine().M
    for tgt in (40, 3000, 500000, 4000000, 7300000):
        P = M.plan('funky', 'Lf', life=tgt)
        T.check(tgt - 2 <= float(P['life']['life']) <= tgt + 0.0 or tgt < 100, f'life {tgt}: {float(P["life"]["life"])}')
    a, b = M.plan('funky', 'L1', life=500000)['life'], M.plan('funky', 'L2', life=7300000)['life']
    T.check(b['oak'] > a['oak'], 'more life: more Oak Sage')
    d31, d28 = (M.plan('funky28' if tk == 28 else 'funky', 'Dk', tk=tk)['o']['dtm'] for tk in (30, 28))
    T.check(d31 != d28, f'the optimal DTM follows the TK / mana pool ({d31} at TK30, {d28} at TK28)')
    T.check(all(M.analyze(M.model_from_plan(M.plan(k, 'Dk')), bo=True)['values']['dtm'] <= M.analyze(
        M.model_from_plan(M.plan(k, 'Dk')), bo=True)['values']['dtm_lpj'] for k in ('funky', 'funky28')), 'under the ceiling')
    P = M.plan('mock_high', 'Dt', dtm=2000)
    c = {x[0]: x[3] for x in M.analyze(M.model_from_plan(P), bo=True)['checks']}
    T.eq(c['dtm_cap'], M.BAD, 'excessive DTM: BAD')


@T.test
def rule_thorns_return_reference_numbers():
    """User rule 2 (reference calculator defaults: Thorns 4093, Barbs 3512, DR 10314, DR% 50, ES absorb 0.95,
    TK 31, hit 1426063.19): return (0.4 Th + 2.1 + 0.1 Ba + 0.4) x ((hit x (1 - 0.95) - DR) x 0.5) / 8 =
    7588957.35 with ES (0.9047 of 8388607), 176163441.40 without (mod 2^24: 8391281.40, rolled); the Thorns DTM
    return x 0.17 x 0.95 / TK ratio (16 at TK31) = 76601.04."""
    M = engine().M
    es = Fraction(95, 100)
    on = M.thorns_return(4093, 3512, 10314, 50, es)
    off = M.thorns_return(4093, 3512, 10314, 50, 0)
    T.eq(round(float(on), 2), 7588957.35, 'return with ES')
    T.eq(round(float(on) / M.ROLL, 4), 0.9047, 'fraction of 8388607')
    T.eq(round(float(off + (1 << 24)), 2), 8391281.40, 'ES off: wrapped (rolled over)')
    T.check(off < 0 and not M.thorns_safe(4093, 3512, 10314, 50, es), 'ES off rolled: not safe')
    T.eq(round(float(M.thorns_dtm(on, es, 31)), 2), 76601.04, 'Thorns DTM')
    T.eq((M.tk_ratio(31), M.tk_ratio(30), M.tk_ratio(99), M.tk_ratio(0)), (16, 8, 16, Fraction(1, 2)), 'TK ratio')
    P = M.plan('mock_high', 'Th')
    a = M.analyze(M.model_from_plan(P))
    T.check(a['values']['thorns_dtm'] > 0, 'analyzer: Thorns DTM')
    T.check(any('mana damage per hit' in x for x in M.summary(P)), 'summary: Thorns DTM')


@T.test
def rule_best_mana_caps_the_mana():
    """User rule 4 (reference calculator 'Best Mana'): (8388608 / TK ratio) x 3 - 1 - floor(absorb / ((100 - res)
    / 100) x 0.36) at res -100: TK31, absorb 213909 -> 1534360. Presets with absorb cap their mana there (mock_mid
    / mock_low stay under it), a typed mana is kept; the analyzer shows it; funkies (exact) are not capped."""
    M = engine().M
    T.eq(M.best_mana(31, 213909), 1534360, 'TK31, absorb 213909, res -100')
    T.eq(M.best_mana(31, 0), 1572863, 'no absorb: the top of good band 2')
    T.eq(M.best_mana(30, 213909), 3107224, 'TK30')
    for key in M.PRESET_ORDER:
        P = M.plan(key, 'Best')
        o = P['o']
        if o['exact']:
            T.eq(o['best_mana'], None, f'{key}: exact funky, no cap')
            continue
        T.check(int(P['mana']['mana']) <= o['best_mana'], f"{key}: mana {int(P['mana']['mana'])} <= {o['best_mana']}")
        st = {c[0]: c[3] for c in M.analyze(M.model_from_plan(P), bo=True)['checks']}
        T.eq(st.get('best_mana'), M.GOOD, f'{key}: analyzer overheal check')
    P = M.plan('mock_high', 'Best')     # absorb: 178 by-clvl lines + one 767 by-time line (several do not add)
    ab = max(a['total'] for a in P['o']['absorb'].values())
    T.eq((int(P['mana']['mana']), M.best_mana(31, ab)), (1540681, 1540681), 'mock_high: 1572500 -> 1540681')
    T.eq(int(M.plan('mock_mid', 'Best')['mana']['mana']), 1310719, 'mock_mid kept')
    P = M.plan('mock_high', 'Best', mana=1572863)
    T.eq(int(P['mana']['mana']), 1572863, 'a typed mana is kept')
    st = {c[0]: c[3] for c in M.analyze(M.model_from_plan(P), bo=True)['checks']}
    T.eq(st['best_mana'], M.WARN, 'analyzer: over the overheal-safe mana')


@T.test
def rule_tk_change_resolves_mana():
    """User rule 5: a TK with another ratio re-solves the mana as that TK's overheal-safe mana (TK30: 3107224 on
    mock_high); a mana out of the list budget (TK28: 6259273) or over the roll point (TK26) is refused clearly."""
    M = engine().M
    raw, P = M.generate('mock_high', 'Tk', tk=30)
    T.eq(int(P['mana']['mana']), M.best_mana(30, max(a['total'] for a in P['o']['absorb'].values())), 'TK30')
    T.eq(P['o']['best_mana'], 3113545, 'TK30 best mana (by clvl + one by-time line)')
    T.eq(int(M.plan('mock_mid', 'Tk', tk=32)['mana']['mana']), 1310719, 'TK32: same ratio as TK31, mana kept')
    for tk, want in ((28, '6259273'), (26, 'roll point')):
        try:
            M.plan('mock_high', 'Tk', tk=tk)
            T.check(False, f'TK{tk} refused')
        except M.PlanError as e:
            T.check(want in str(e), f'TK{tk}: {e}')


@T.test
def rule_prayer_drain_in_the_balance():
    """User rule 6: the Prayer drain (1 + 0.1875 (L - 1) per source per 2 s pulse) is in every Prayer preset's
    plan balance and its analyzer check (under the regen); a drain over the regen is refused."""
    M = engine().M
    for key in M.PRESET_ORDER:
        P = M.plan(key, 'Pr')
        b = P['balance']
        if not b['prayer_sources']:
            continue
        T.eq(b['drain_s'], M.prayer_drain(b['prayer_level']) * b['prayer_sources'] / 2, f'{key}: drain per s')
        T.check(b['drain_s'] < b['regen_s'], f"{key}: drain {float(b['drain_s']):.0f} < regen")
        a = M.analyze(M.model_from_plan(P), bo=True)
        c = {c[0]: c for c in a['checks']}['prayer']
        T.check(c[3] == M.GOOD and 'drain' in c[2], f'{key}: analyzer Prayer check')
        T.check(abs(a['values']['prayer_drain_s'] - float(b['drain_s'])) < 1, f'{key}: analyzer = plan drain')
        T.check(any('Prayer drain' in x for x in M.summary(P)), f'{key}: summary shows the drain')
    P = M.plan('mock_high', 'Pr', life=150000, oak=0, prayer_sources=3)
    a = M.analyze(M.model_from_plan(P), bo=True)['values']
    T.eq((a['prayer_sources'], P['balance']['prayer_sources']), (3, 3),
         'lower life with no Oak only creates the three requested Prayer sources')
    T.eq(a['prayer_drain_s'], float(P['balance']['drain_s']), 'the resulting drain is included in the balance')
    try:
        M.plan('mock_high', 'Pr', cls=0, med=0, regen=0)
        T.check(False, 'drain over the regen refused')
    except M.PlanError as e:
        T.eq(getattr(e, 'key', None), 'prayer', f'refused: {e}')




@T.test
def shield_base_option_from_the_tables():
    """Max smite shield base: the form lists the shields the class may use with their min-max from the game tables
    (armor.bin mindam / maxdam, itemtypes class along the Equiv chain); the default stays the Tower Shield (output
    unchanged); another base keeps the lists and the file size, max mode still sits at the cap and the spread
    (max - min) narrows with the base's range (Small Shield 2-3 vs Tower Shield 1-5); a class's shields only."""
    E = engine()
    M = E.M
    sor = M.shield_choices(1, data=E.data)
    T.check(any(c.startswith('tow 1-5') and 'Tower Shield' in c for c in sor), f'tower listed: {sor[:5]}')
    T.check(any(c.startswith('sml 2-3') for c in sor), 'small shield listed')
    T.check(not any(c.startswith(('pa', 'ne')) for c in sor), 'no paladin shields / necro heads for a Sorceress')
    T.check(any(c.startswith('pae 46-46') for c in M.shield_choices(3)), 'paladin shields for a Paladin')
    T.eq(M.shield_dmg('tow '), (1, 5), 'tower 1-5 from armor.bin')
    pre = M.prefill('mock_high')
    T.check(pre['shield'].startswith('tow 1-5'), f"prefill {pre['shield']}")
    lab = next(c for c in sor if c.startswith('sml '))
    T.eq(M.edited({'shield': lab}, pre), {'shield': 'sml '}, 'form label -> code')
    sizes, spread = {}, {}
    for sh in ('tow ', 'sml '):
        raw, P = M.generate('mock_high', 'Sh', smite_max=True, shield=sh)
        T.eq(P['o']['shield'], sh, 'option kept')
        p = os.path.join(T.tmp(), f'shield_{sh.strip()}.d2s')
        with open(p, 'wb') as f:
            f.write(raw)
        a, m, _ch = _analyze(p)
        sm = a['values']['smite']
        T.eq(sm['shield'], sh, f'{sh}: analyzer sees the base')
        T.eq(sm['max'], M.ROLL, f'{sh}: max at the cap')
        sizes[sh] = (len(raw), len(P['lists']))
        spread[sh] = sm['max'] - sm['min']
        T.check(any('spread' in str(c) for c in a['checks']), 'spread shown in the analyzer')
    T.eq(sizes['sml '], sizes['tow '], 'same size and lists')
    T.check(spread['sml '] * 3 < spread['tow '], f'narrower spread {spread}')
    T.eq(M.plan('mock_high', 'D')['o']['shield'], 'tow ', 'default tower')
    try:
        M.plan('mock_high', 'X', shield='pae ')
        T.check(False, 'a paladin shield on a Sorceress is refused')
    except M.PlanError as e:
        T.eq(getattr(e, 'key', None), 'shield', 'error on the shield field')




@T.test
def rule_no_prayer_aura_on_funky_and_no_weapon_in_dopplezon():
    """Funky mocks carry no Prayer aura (its mana drain can kill a Funky) while the PI mock keeps it; a Dopplezon
    morph build equips no weapon unless it is a dex-bug build or the weapon is Ith."""
    M = engine().M
    for key in ('funky', 'funky28', 'funky26', 'funky24'):
        P = M.plan(key, 'NoPr')
        T.check(not [x for x in _lines(P) if x[0] in (151, 97) and x[1] == M.PRAYER], f'{key}: no Prayer aura / oskill')
        T.eq(P['expect_sources'].get(M.PRAYER, 0), 0, f'{key}: no Prayer source')
        T.check(any(x[0] == 74 for x in _lines(P)), f'{key}: Replenish Life present')
    T.check([x for x in _lines(M.plan('mock_high', 'Pr')) if x == (151, M.PRAYER)], 'PI mock keeps Prayer')
    for key in M.PRESET_ORDER:
        o = M.plan(key, 'Dz')['o']
        T.check(not (o['dopplezon'] and o['weapon']) or o['dex_bug'] or o['ith_weapon'], f'{key}: weapon rule')
    o = M.plan('mock_high', 'W', weapon=True)['o']
    T.eq((o['weapon'], o['dex_bug']), (True, True), 'a weapon asked for in a Dopplezon morph is a dex-bug one')
    T.eq(M.plan('mock_high', 'W', weapon=True, dex_bug=True)['o']['weapon'], True, 'dex-bug build keeps it')
    T.eq(M.plan('mock_high', 'W', weapon=True, dopplezon=False)['o']['weapon'], True, 'no morph keeps it')


@T.test
def rule_meditation_life_oak_holy_shock():
    """Typed Meditation / regen top up to the roll-over cap, a lower life is never exceeded, Oak Sage 0 means no
    Oak source, Oak is preferred over +life lines, and Holy Shock is an aura option."""
    M = engine().M
    base = M.plan('mock_high', 'Ms')
    cap = base['regen']['cap']
    P = M.plan('mock_high', 'Ms', med=40)
    r = P['regen']
    T.eq(r['med'], 40, 'typed Meditation kept')
    T.check(r['total'] <= cap and cap - r['total'] < 25 + 1 or r['pct'] == 255, f"regen near the cap {r['total']}/{cap}")
    T.eq(P['expect_sources'].get(M.MEDITATION, 0), 1, 'one Meditation source')
    P = M.plan('mock_high', 'Lf', life=1000000)
    T.check(P['life']['life'] <= 1000000, f"life {P['life']['life']} not raised over 1000000")
    P = M.plan('mock_high', 'Ok', oak=0, life=150000)
    T.eq(P['life']['oak'], 0, 'oak 0 solved as 0')
    T.eq(P['expect_sources'].get(M.OAK, 0), 0, 'no Oak Sage source')
    T.check(not [x for x in _lines(P) if x[0] == 151 and x[1] == M.OAK], 'no Oak Sage lines')
    T.check(P['life']['life'] <= P['o']['life'], 'life under target with Oak 0')
    A = M.plan('mock_high', 'Ok')
    T.check(A['life']['oak'] > 0, 'auto life uses Oak Sage')
    P = M.plan('mock_high', 'Hs', hsk_level=1500, hsk_sources=2)
    T.eq(P['expect_sources'].get(M.HOLY_SHOCK, 0), 2, 'Holy Shock sources')
    T.eq(sum(x[2] if len(x) > 2 else 0 for x in []), 0, 'noop')
    T.check('hsk_level' in M.FIELD_KEYS and M.sources_of(P)['hsk_level'] == 2, 'Holy Shock field + source count')
    try:
        M.plan('mock_high', 'Hs', hsk_level=1500, hsk_sources=40)
        T.check(False, 'too many Holy Shock sources refused')
    except M.PlanError as e:
        T.eq(getattr(e, 'key', None), 'hsk_sources', 'refused on the field')


@T.test
def ith_items_vanish_but_keep_their_sources():
    """Ith (runeword flag, id 0xFFFF, empty runeword list): the weapon, its jewels and the Ith charms (inventory and
    stash) count as aura sources but add no levels; the flag round-trips through save and reload; a Dopplezon morph
    weapon is only an Ith weapon or a dex-bug weapon whose requirements stay unmet."""
    E = engine()
    M = E.M
    base = M.generate('mock_high', 'Ba')[1]
    raw, P = M.generate('mock_high', 'Ith', ith_weapon=True, ith_charms=12, ith_inv=3)
    ith = [u for u in P['units'] if u.ith]
    T.eq(len(ith), 1 + 7 + 3 + 12, 'weapon + 7 jewels + 3 inventory + 12 stash charms')
    for u in ith:
        T.check(not any(s.lines and sid != 151 for s in u.slots for sid, _p, _v in s.lines), 'only the Prayer source line')
    mp = M.model_from_plan(P, raw)
    folder = _gen_dir()
    mc = M.model_from_character(E.MC.Character(M.write_new(raw, folder, 'Ith'), E.data))
    T.eq(sum(1 for u in mc['units'] if u.ith), len(ith) - 12, 'the flag survives save / reload (stash ones are not units)')
    T.eq((mc['stash_ith'], mp['stash_ith']), (12, 12), 'stash Ith charms are counted apart, not as sources')
    ch = E.MC.Character(M.write_new(raw, folder, 'Ithb'), E.data)
    T.check(any(e.it.get('panel') == 5 and e.it.get('stats_runeword') is not None for e in ch.items), 'stash Ith charm')
    for m in (mp, mc):
        t = M.totals(m, 'A')
        T.eq(sum(t['sources'].get(M.PRAYER, {}).values()), P['expect_sources'][M.PRAYER], 'sources counted')
        T.eq(sum(1 for u in t['units'] if u.ith for _ in u.lines()), 0, 'Ith units add no stat lines')
    ca, cb = M.analyze(mp, 'A', bo=True)['checks'], M.analyze(mc, 'A', bo=True)['checks']
    T.eq([c for c in ca if c not in cb], [c for c in cb if c not in ca], 'plan model == written save')
    src = lambda m: sum(M.totals(m, 'A')['sources'].get(M.PRAYER, {}).values())
    T.eq(src(mc) - src(M.model_from_plan(base)), 1 + 7 + 3 - 3, 'Ith items in the inventory add Prayer sources (3 replace charms); the stash adds none')
    T.check(any(c[0] == 'ith_stash' and 'by hand' in c[2] for c in M.analyze(mc, 'A', bo=True)['checks']), 'stash label: move in by hand')
    # Dopplezon morph weapon rule
    T.check(M.plan('mock_high', 'Nw', weapon=True)['o']['dex_bug'], 'a weapon in the morph keeps its requirements unmet')
    P2 = M.plan('mock_high', 'Dx', weapon=True, dex_bug=True)
    T.check(P2['o']['weapon'], 'dex-bug weapon kept: its requirements stay unmet (dexterity 1 < 27)')
    d = M.WEAPON_REQ[M.WEAPON[2]]
    T.check(1 < d[1] and not any(sid == 2 for u in P2['units'] for s in u.slots for sid, _p, _v in s.lines), 'no dexterity lines')
    # funky24 (Ith weapon) still hits its exact mana, or fails loudly
    try:
        M.generate('funky24', 'Fkb', ith_weapon=True)
        T.check(False, 'an Ith weapon lacks the lists for the funky24 exact mana')
    except M.PlanError as e:
        T.check('cannot be hit exactly' in str(e), 'funky24 needs its weapon counted: ' + str(e))
    T.check(M.generate('funky24', 'Fkc')[1]['o']['weapon'], 'funky24 keeps a counted dex-bug weapon')




@T.test
def regen_remainder_on_shield_and_low_life_funky():
    """The leftover mana regen line sits on the shield (also side B of a switch), total <= cap; Funky life 40 is solvable."""
    E = engine()
    M = E.M
    for kw in ({}, dict(switch='balance', mana_b=1211974)):
        raw, P = M.generate('balance_switch' if kw else 'mock_high', 'Rg', **({} if kw else kw))
        sh = P['U']['shield']
        got = sum(v for s in sh.slots for sid, _p, v in s.lines if sid == 27)
        T.eq(got, P['regen']['pct'], 'the regen remainder is on the shield')
        T.check(P['regen']['total'] <= P['regen']['cap'], 'regen within the cap')
        mp = M.model_from_plan(P, raw)
        mc = M.model_from_character(E.MC.Character(M.write_new(raw, _gen_dir(), 'Rg'), E.data))
        T.eq(M.analyze(mp, 'A', bo=True)['values']['regen'], M.analyze(mc, 'A', bo=True)['values']['regen'], 'regen round-trips')
    raw, P = M.generate('funky', 'Lo', life=40)
    T.check(38 <= P['life']['life'] <= 40, 'life 40 reached on a Funky')
    mc = M.model_from_character(E.MC.Character(M.write_new(raw, _gen_dir(), 'Lo'), E.data))
    T.eq(mc['base_life_raw'], P['life']['base_raw'], 'low base life round-trips')


@T.test
def auto_meditation_lands_at_the_cap_and_rollover_is_bad():
    """Auto Meditation: level > 0 and total regen in [cap - 40, cap] on every preset; the cap itself does not roll
    (8388607 mana x (100 + regen) / 3000 <= ROLL); a rolled regen is BAD and a typed over-cap Meditation is refused."""
    E = engine()
    M = E.M
    for pr in M.PRESETS:
        P = M.plan(pr, 'Au')
        r = P['regen']
        T.check(r['med'] > 0 and r['cap'] - 40 <= r['total'] <= r['cap'], f'{pr}: auto regen at the cap')
    for mana in (1048576, 1572500, 2000000):
        c = M.regen_cap(mana)
        T.check(mana * (100 + c) <= M.ROLL * 3000 < mana * (100 + c + 1), 'regen_cap has no off-by-one')
    P = M.plan('funky', 'Ro')
    try:
        M.plan('funky', 'Ro', med=P['regen']['med'] + 50)
        T.check(False, 'over-cap Meditation refused')
    except M.PlanError:
        pass


@T.test
def set_bonus_lists_and_owner_bonuses_follow_weapon_side():
    """Civerb's shield uses member slots, its amulet uses a count, and its scepter has add_func 0."""
    E = engine()
    M = E.M

    def item(row, code, body, lists=(), *, flags=0, location=1):
        record = dict(quality='set', set_unique_id=row, code=code, equipped=body, location=location, flags=flags)
        for index, value in lists:
            record[f'set_stats_{index}'] = [dict(id=9, value=value)]
        return T.NS(it=record)

    head = bytearray(64)
    head[0x10] = 1
    ch = SimpleNamespace(head=head, stats=[], skill_levels=lambda: {}, items=[
        item(0, 'lrg ', 5, [(0, 10), (1, 20)]),
        item(0, 'lrg ', 12, [(0, 10), (1, 20)]),
        item(1, 'amu ', 2, [(1, 40)]),
        item(1, 'amu ', 6),  # a duplicate leaves the set member count unchanged
        item(2, 'gsc ', 4, [(0, 80)]),
        item(2, 'gsc ', 11, flags=0x100),
        item(2, 'gsc ', 0, location=0),
    ], raw=b'', name='Sets', data=E.data)

    model = M.model_from_character(ch)
    a, b = M.totals(model, 'A'), M.totals(model)
    T.eq((a['T'][9], b['T'][9]), (70, 10), 'pair-specific, count-based and sparse saved lists')
    T.eq((a['T'][39], b['T'][39]), (15, 15), 'two-item fire resistance applies once per side')
    T.eq((a['T'][0], a['T'][41], b['T'].get(0), b['T'].get(41)), (15, 25, None, None),
         'only the complete side gets the full-set strength and lightning resistance')
    T.eq((a['complete_sets'], b['complete_sets']), ({0}, set()), 'the active switch defaults to B')


@T.test
def analyzer_handles_empty_classic_and_legacy_characters():
    E = engine()
    import mxl_newchar

    for version in (71, 92, 96):
        _, ch = mxl_newchar.build(E.data, 'Empty', 1, 1, expansion=False, median=False, version=version)
        ch.items.clear()
        ch.parse(ch.build())
        model = E.M.model_from_character(ch)
        T.check(not ch.flags()['expansion'] and not ch.has_jf and not model['units'],
                'empty non-expansion character has no active item or mercenary list')
        T.eq(E.M.analyze(model)['values']['tk'], 0, 'no hard points')

    # Simulate a selected mod's class-skill ordering in the same reader used by Character.
    skills = E.data._capy_class_skills
    stock = skills[1]
    try:
        skills[1] = (E.M.TELEKINESIS, *[sid for sid in stock if sid != E.M.TELEKINESIS])
        ch.set_skill_levels({E.M.TELEKINESIS: 7})
        ch.parse(ch.build())
        T.eq(E.M.analyze(E.M.model_from_character(ch))['values']['tk'], 7,
             'the Analyzer uses the selected table ordering')
    finally:
        skills[1] = stock

    from mxl_creator import Creator, decode_item, encode_item

    creator = Creator(E.data)
    item, _ = creator.build(creator.new_spec('normal', 'hp1 '))
    record, _ = decode_item(item, E.data)
    record['code'] = 'zxq '
    unknown = encode_item(record, E.data)
    ch.items = [E.MC.Entry(record, unknown)]
    ch.parse(ch.build())
    T.eq(ch.items[0].it['code'], 'zxq ', 'an unavailable mod item code is kept')
    T.eq(E.M.analyze(E.M.model_from_character(ch))['values']['units'], 0,
         'an unknown item in storage contributes no combat modifiers')

    # A signed socket stat in a mod can lower the capacity below zero.
    for stats in ([], [dict(id=194, value=-1)]):
        ch.items = [T.NS(it=dict(code='zxq ', location=1, equipped=4, sockets=0, stats=stats,
                                 socketed=[dict(stats=[dict(id=9, value=20)])] * 2))]
        model = E.M.model_from_character(ch)
        T.eq(model['excess_jewels'], 2, 'both children exceed the effective capacity')
        T.eq([unit.kind for unit in model['units']], ['gear'], 'out-of-range children are inactive')


T.main(globals())
