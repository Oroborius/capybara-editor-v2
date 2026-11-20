"""Mock Mode engine (src/mxl_mock.py) in the vanilla profile: the analyzer on reference mock saves matches the
research numbers (docs/review/mock-pi.md 2.5 / 8.2), the vanilla item codec gives every sample item back byte for
byte, and every preset generates a NEW save that re-opens in the editor and that the analyzer scores as hitting
its targets (mana band / funky, regen at the cap, smite at the damage cap, aura sources as planned, < 8192 bytes).

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


def _analyze(path, side=None):
    E = engine()
    ch = E.MC.Character(path, E.data)
    m = E.M.model_from_character(ch)
    return E.M.analyze(m, side), m, ch


def _sample(rel):
    return os.path.join(engine().saves, rel)


# (file, side or None = the active one, TK, mana, kind) - mana from docs/review/mock-pi.md 2.5 / 8.2
REFERENCE = [
    ('clones/clone-41.d2s', None, 30, Fraction(1048576), 'funky'),
    ('clones/clone-60.d2s', None, 30, Fraction(1048576), 'funky'),
    ('clones/clone-35.d2s', None, 99, '1572845.96', 'good'),
    ('clones/clone-06.d2s', None, 99, '1572847.19', 'good'),
    ('clones/clone-36.d2s', None, 31, '1572647.84', 'good'),
    ('clones/clone-73.d2s', None, 72, '1572587.79', 'good'),
    ('clones/clone-76.d2s', None, 31, '1572212.12', 'good'),
    ('clones/clone-28.d2s', None, 30, '3145752.95', 'bad'),
    ('clone-51.d2s', None, 39, '971806.30', 'bad'),
    ('clones/clone-20.d2s', None, 53, '1572009.01', 'good'),
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


def _check_generated(key, raw, P, path):
    E = engine()
    M = E.M
    a, m, ch = _analyze(path)
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
        if P['o']['switch'] != 'lock':
            T.eq(int(v['mana']), int(P['o']['mana']), f'{key}: on-screen mana = the target')
    T.eq((v['regen'], v['regen_cap']), (exp['regen'], exp['regen_cap']), f'{key}: regen')
    T.check(v['regen'] <= v['regen_cap'] and v['regen_cap'] - v['regen'] < 25, f'{key}: regen at the cap')
    T.check(exp['pvm'] - 400 <= v['smite']['max'] <= exp['pvm'] <= M.ROLL, f"{key}: smite {v['smite']['max']}")
    T.check(abs(v['life'] - P['o']['life']) < 2000 and v['life'] < M.ROLL, f"{key}: life {float(v['life'])}")
    srcs = {k: sum(x.values()) for k, x in v['sources'].items()}
    want = {M.AURA_NAMES[k]: n for k, n in exp['sources'].items()}
    T.eq(srcs, want, f'{key}: aura sources')
    T.eq(v['sources'].get('Prayer'), {'charm': exp['sources'][M.PRAYER]}, f'{key}: Prayer sources only on charms')
    T.eq(v['prayer_level'], 31 * v['lists'], f'{key}: Prayer 31 on every list')
    T.eq(v['lists'], 198 if P['o']['weapon'] else 178, f'{key}: lists')
    T.check(len(raw) == v['size'] < M.FILE_LIMIT, f'{key}: {len(raw)} bytes')
    lv = {x[1] for x in v['delirium']}
    T.check(len(v['delirium']) == 2 and len(lv) == 2, f'{key}: Delirium on attack + strike at two levels')
    if exp['side_b']:
        b = M.analyze(m, 'B')['values']
        T.eq(b['mana'], exp['side_b']['mana'], f'{key}: side B mana')
        T.eq([c for c in M.analyze(m, 'B')['checks'] if c[3] == M.BAD], [], f'{key}: side B checks')
        if P['o']['switch'] == 'lock':
            T.check(b['band']['funky'] and b['band']['stable'], f'{key}: side B locks on the funky zero')
        else:
            T.eq(int(b['mana']), P['o']['mana_b'], f'{key}: side B on-screen mana')
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
    cases = [('mock_high', dict(mana=1572863)), ('mock_high', dict(level=127, position='Host')),
             ('mock_mid', dict(tk=32, life=6800000)), ('funky', dict(stun=0)), ('mock_low', dict(stun=60)),
             ('mock_high', dict(hf_sources=3, thorns=2500))]
    for key, over in cases:
        raw, P = M.generate(key, 'Over', **over)
        path = M.write_new(raw, folder, 'Over')
        _check_generated(f'{key} {over}', raw, P, path)
    raw, P = M.generate('mock_high', 'Over', mana=1572863)
    a, _, _ = _analyze(M.write_new(raw, folder, 'Over'))
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


T.main(globals())
