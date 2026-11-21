"""Mock Mode engine (src/mxl_mock.py) in the vanilla profile: the analyzer on reference mock saves matches the
research numbers (docs/review/mock-pi.md 2.5 / 8.2), the vanilla item codec gives every sample item back byte for
byte, and every preset generates a NEW save that re-opens in the editor and that the analyzer scores as hitting
its targets (mana band / funky, regen at the cap, smite at the damage cap, aura sources as planned, < 8192 bytes)
and uses the clones' size tricks with bulk lines up to the size budget.

Fixtures: the vanilla install and the mock samples (see test 75; copies only). Skipped without them."""
import glob
import os
import shutil
import sys
from fractions import Fraction

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
    return _E


def _analyze(path, side=None, bo=False):
    E = engine()
    ch = E.MC.Character(path, E.data)
    m = E.M.model_from_character(ch)
    return E.M.analyze(m, side, bo=bo), m, ch


def _sample(rel):
    return os.path.join(engine().saves, rel)


# (file, side or None = the active one, TK, mana, kind) - mana with the game's percent step (pct_fp, measured in game)
REFERENCE = [
    ('clones/clone-41.d2s', None, 30, Fraction(1048576), 'funky'),
    ('clones/clone-60.d2s', None, 30, Fraction(1048576), 'funky'),
    ('clones/clone-35.d2s', None, 99, '1572835.62', 'good'),
    ('clones/clone-06.d2s', None, 99, '1572835.22', 'good'),
    ('clones/clone-36.d2s', None, 31, '1572631.00', 'good'),
    ('clones/clone-73.d2s', None, 72, '1572581.37', 'good'),
    ('clones/clone-76.d2s', None, 31, '1572194.27', 'good'),
    ('clones/clone-28.d2s', None, 30, '3145723.16', 'good'),
    ('clone-51.d2s', None, 39, '971798.82', 'bad'),
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
            T.check(1571000 <= v['mana'] <= 1572863, f'{rel}: TK31 high mock at 1571000-1572863')
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
        T.check(a['values']['mana'] < 1500000 and 1571000 <= g['mana'] <= 1572863,
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
    T.eq(sorted(skipped), [('clone-68.d2s', True, 0)] + [('clone-20.d2s', True, 0)] * 6
         + [('clone-100.d2s', True, 0)] * 14, 'items the codec cannot read (all opaque to the editor too)')
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
    want = {M.AURA_NAMES[k]: n for k, n in exp['sources'].items()}
    T.eq(srcs, want, f'{key}: aura sources')
    T.eq(v['sources'].get('Prayer'), {'charm': exp['sources'][M.PRAYER]}, f'{key}: Prayer sources only on charms')
    T.eq(v['prayer_level'], 31 * v['lists'], f'{key}: Prayer 31 on every list')
    T.eq(v['lists'], 198 if P['o']['weapon'] else 178, f'{key}: lists')
    T.check(len(raw) == v['size'] <= 8191, f'{key}: {len(raw)} bytes (the game loads at most 8191)')
    T.eq(v['excess_jewels'], 0, f'{key}: every jewel fits the socket count (field + item_numsockets)')
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
        T.eq(int(P['mana']['mana']), mana, f'enemy aura {aura}: mana {mana}')
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
        o = M.options(key)
        T.eq({k: pre[k] for k in ('tk', 'mana', 'thorns', 'barbs', 'hf_sources', 'bo')},
             {k: int(o[k]) for k in ('tk', 'mana', 'thorns', 'barbs', 'hf_sources', 'bo')}, f'{key}: prefill')
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
    T.eq([M.options(k)['bo'] for k in ('funky', 'funky28', 'funky26', 'funky24')], [0] * 4,
         'funkies: no BO (exact without BO, like the reference funkies)')
    T.eq(int(v['mana']), 1572500, 'host: 1572500 WITH BO')
    T.check(any(c[0] == 'mana_nobo' for c in a['checks']), 'the analyzer shows the mana without BO too')
    raw, P = M.generate('mock_high', 'NoBo', bo=0)
    a, m, _ = _analyze(M.write_new(raw, folder, 'NoBo'))
    T.eq((a['values']['bo_pct'], int(a['values']['mana'])), (0, 1572500), 'BO 0: no BO line, mana without BO')


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
def smite_max_and_efficient_modes():
    """Max smite: max = 8388607 exactly and min = max (+min damage closes the shield spread); efficient: within
    0.1% of the cap, never over it."""
    M = engine().M
    mx = M.plan('mock_high', 'X', smite_max=True)['smite']
    T.eq((mx['max'], mx['min']), (M.ROLL, M.ROLL), 'max mode: every smite is the cap')
    ef = M.plan('mock_high', 'X')['smite']
    T.check(M.ROLL * 0.999 <= ef['max'] <= M.ROLL, f"efficient mode within 0.1%: {ef['max']}")


@T.test
def size_tricks_and_bulk_lines():
    """The clones' size tricks (editor-tricks.txt): socketed jewels normal quality without the picture field,
    charms superior without it (a q2 no-picture jewel round-trips byte for byte, the editor reads it back); the
    room under the size budget is filled with target-neutral bulk lines on charms and jewels (replenish life on
    every list; absorb by time, or resist by level on a Host); the target lines (life, +mana) go on the charms
    first; one line per stat per list; every preset ends within 300 bytes under the budget."""
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
    for key in M.PRESET_ORDER:
        raw, P = M.generate(key, 'Bulk')
        T.check(budget - 300 <= len(raw) <= budget, f'{key}: {len(raw)} bytes within 300 under {budget}')
        host = P['o']['position'] == 'Host'
        for u in P['units']:
            for sl in u.slots:
                keys = [(sid, p) for sid, p, _ in sl.lines]
                T.eq(len(keys), len(set(keys)), f'{key}: {u.name}: one line per stat per list')
                if u.kind in ('charm', 'jewel'):
                    T.check(sl.has(74), f'{key}: {u.name}: replenish life bulk line')
            if u.kind == 'charm':
                T.check(u.slots[0].has(230 if host else 288), f'{key}: {u.name}: {"res" if host else "abs"} bulk')
                T.check(u.slots[0].has(7) and (P['o']['switch'] or u.slots[0].has(9)),
                        f'{key}: {u.name}: the life / +mana lines sit on the charms first')
        path = M.write_new(raw, folder, 'Bulk')
        ch = E.MC.Character(path, E.data)
        q = set()
        for e in ch.items:
            recs = M.decode_blob(e.blob, isc, base)
            q |= {(x['code'], x['quality'], x['image']) for x in recs if x['code'] in ('jew ', 'cm1 ')}
        T.eq(q, {('jew ', 2, None), ('cm1 ', 3, None)}, f'{key}: jewels q2 / charms q3, no picture field')


T.main(globals())
