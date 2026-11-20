"""Game profile "other folder" with vanilla Diablo II LoD 1.14d (MXL_GAME=vanilla): the vanilla tables, strings and
icons are extracted from the game's MPQs (only read) into the profile's own data folder, and a vanilla 1.14d
character (d2s version 96, samples of the d2s parser project dschu012/d2s, ISC) opens with its items, names and
stats; a save without edits leaves the file byte-identical.

Fixtures: the vanilla install (MXL_TEST_VANILLA_GAME, default ~/Games/diablo-ii-lord-of-destruction/drive_c/
Program Files (x86)/Diablo II, read only) and the sample saves (MXL_TEST_VANILLA_SAVES, default
.cache/samples/vanilla of this checkout, else of the main checkout). Skipped without them."""
import glob
import json
import os
import shutil
import sys

import capytest as T

MODE = 'engine'
NEEDS = ()

GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')


def _samples():
    cands = [os.environ.get('MXL_TEST_VANILLA_SAVES', ''), os.path.join(T.REPO, '.cache', 'samples', 'vanilla')]
    if os.sep + '.claude' + os.sep + 'worktrees' + os.sep in T.REPO:
        cands.append(os.path.join(T.REPO.split(os.sep + '.claude' + os.sep)[0], '.cache', 'samples', 'vanilla'))
    return next((c for c in cands if c and glob.glob(os.path.join(c, '*.d2s'))), None)


_E = None


def engine():
    """Data layer in the vanilla profile, on a fresh user folder (the extraction runs once per process)."""
    global _E
    if _E is not None:
        return _E
    src = _samples()
    if not os.path.isfile(os.path.join(GAME, 'd2data.mpq')) or not src:
        T.skip(f'no vanilla 1.14d install ({GAME}) or no vanilla samples (.cache/samples/vanilla)')
    user = T.guard(os.path.join(T.tmp(), 'vuser'), 'user folder')
    saves = T.guard(os.path.join(T.tmp(), 'vsaves'), 'save folder')
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
        prof = mxl_profile.install()
    finally:
        sys.stdout = out
    import mxl_data
    import mxl_char
    import mxl_tooltip
    _E = T.NS(data=mxl_data.Data(paths.DATA_DIR), MC=mxl_char, tip=mxl_tooltip, paths=paths, prof=prof,
              saves=saves, src=src)
    return _E


def _key(name):
    return ''.join(c for c in name.lower() if c.isalnum())


def _text(ln):
    return ''.join(x[1] if isinstance(x, tuple) else str(x) for x in (ln if isinstance(ln, list) else [ln]))


@T.test
def profile_detects_vanilla_and_extracts_its_own_data():
    E = engine()
    T.eq((E.prof['kind'], E.prof['version']), ('d2', '1.14d'), 'detected game')
    T.check(E.paths.DATA_DIR.startswith(os.path.join(E.paths.USER_DIR, 'profiles')), 'profile data folder')
    T.check(os.path.isfile(os.path.join(E.paths.DATA_DIR, 'itemstatcost.bin')), 'tables extracted')
    T.check(len(glob.glob(os.path.join(E.paths.DATA_DIR, 'items', '*.png'))) > 300, 'item icons extracted')
    T.check(not os.path.exists(os.path.join(E.paths.USER_DIR, 'data')), 'the Median data folder is not touched')
    import settings
    T.eq(settings.get('game_dir'), GAME, "settings 'game_dir' reads the profile's folder")


@T.test
def vanilla_character_items_and_stats():
    E = engine()
    path = os.path.join(E.saves, 'complex.d2s')
    ref = json.load(open(os.path.join(E.src, 'complex.json'), encoding='utf-8'))
    ch = E.MC.Character(path, E.data)
    T.eq(len(ch.items), len(ref['items']), 'item count')
    T.eq(len(ch.merc_items or []), len(ref['merc_items']), 'mercenary item count')
    a = ref['attributes']
    T.eq([ch.stat(i) for i in (0, 1, 2, 3, 12, 13, 14, 15)],
         [a['strength'], a['energy'], a['dexterity'], a['vitality'], a['level'], a['experience'], a['gold'],
          a['stashed_gold']], 'character stats')
    T.eq(len(ch.skills), 2 + 30, "vanilla skill section: 'if' + 30 bytes")
    names = []
    for e, r in zip(ch.items, ref['items']):
        T.eq(e.it['code'].strip(), r['type'], 'item code')
        tip = [_text(x) for x in E.tip.item_tooltip(e.it, E.data)]
        want = r.get('unique_name') or r.get('set_name') or r.get('rare_name')
        if r.get('unique_name') or r.get('set_name'):
            # the parser's names are the table's index column ("Wartraveler"), the game shows the string
            T.eq(_key(tip[0]), _key(want), f"name of {r['type']}: {tip[0]!r} / {want!r}")
            names.append(tip[0])
    T.check("Trang-Oul's Claws" in names and 'Raven Frost' in names, 'set and unique names')
    raven = next(e for e in ch.items if E.tip.item_tooltip(e.it, E.data) and
                 _text(E.tip.item_tooltip(e.it, E.data)[0]) == 'Raven Frost')
    lines = [_text(x) for x in E.tip.item_tooltip(raven.it, E.data)]
    T.check('+40 to Mana' in lines and any(x.startswith('+19 to Dexterity') for x in lines),
            f'Raven Frost stat lines: {lines}')


@T.test
def vanilla_save_without_edits_is_byte_identical():
    E = engine()
    for name in ('complex.d2s', 'simple.d2s'):
        path = os.path.join(E.saves, name)
        before = T.read(path)
        ch = E.MC.Character(path, E.data)
        T.check(bytes(ch.build()) == before, f'{name}: rebuilt bytes')
        ch.save(backup=False)
        T.eq(T.read(path), before, f'{name}: file after SAVE without edits')
        E.MC.Character(path, E.data)                       # still reads


@T.test
def vanilla_skill_tab_line_and_grids():
    """Stat 188 with the game's charstats strings per param (not the raw '+%d to Javelin and Spear Skills');
    grid sizes from inventory.bin."""
    E = engine()
    T.eq([x[1] for x in E.tip.stat_lines([dict(id=188, param=8 * 3 + 1, value=3)], E.data)],
         ['+3 to Offensive Auras (Paladin Only)'], 'stat 188 line (Paladin tab 2)')
    T.eq([x[1] for x in E.tip.stat_lines([dict(id=188, param=2, value=1)], E.data)],
         ['+1 to Javelin and Spear Skills (Amazon Only)'], 'stat 188 line (Amazon tab 3)')
    import mxl_profile
    g = mxl_profile.grid_sizes(E.paths.DATA_DIR)
    T.eq((g['inv'], g['stash'], g['stash_classic'], g['cube']), ((10, 4), (6, 8), (6, 4), (3, 4)), 'grids')
    T.eq((E.MC.INV_W, E.MC.INV_H), (10, 4), 'mxl_char inventory size')


@T.test
def vanilla_mercenary_types():
    """The expansion hireling rows (version 100), not the classic ones sharing the ids."""
    E = engine()
    import mxl_merc
    h = mxl_merc.hirelings(E.data)
    T.eq(sorted(h), list(range(30)), 'LoD hireling ids')
    T.check('Defiance' in h[7].label() and 'Normal' in h[7].label() and h[7].act == 2, h[7].label())
    T.check('Might' in h[11].label() and 'Nightmare' in h[11].label(), h[11].label())
    ch = E.MC.Character(os.path.join(E.saves, 'complex.d2s'), E.data)
    T.eq(mxl_merc.record(ch)['type'], 11, 'complex.d2s mercenary type')


def _mock_dir():
    cands = [os.environ.get('MXL_TEST_MOCK_SAVES', ''), os.path.join(T.REPO, '.cache', 'samples', 'mock')]
    if os.sep + '.claude' + os.sep + 'worktrees' + os.sep in T.REPO:
        cands.append(os.path.join(T.REPO.split(os.sep + '.claude' + os.sep)[0], '.cache', 'samples', 'mock'))
    return next((c for c in cands if c and glob.glob(os.path.join(c, '*.d2s'))), None)


@T.test
def mock_samples_open_and_save_byte_identical():
    """The Mock Mode characters (vanilla d2s 96, extreme stats, 40 charms, auras on items): COPIES open, every
    item gets a tooltip, and a SAVE without edits leaves each file byte-identical."""
    E = engine()
    src = _mock_dir()
    if not src:
        T.skip('no mock samples (.cache/samples/mock)')
    dst = T.guard(os.path.join(T.tmp(), 'vmock'), 'mock copies')
    shutil.copytree(src, dst)
    files = sorted(glob.glob(os.path.join(dst, '*.d2s')) + glob.glob(os.path.join(dst, 'clones', '*.d2s')))
    T.check(len(files) >= 38, f'{len(files)} mock samples')
    import mxl_save
    bad = []
    for path in files:
        name = os.path.relpath(path, dst)
        before = T.read(path)
        try:
            ch = E.MC.Character(path, E.data)
            for e in list(ch.items) + list(ch.merc_items or []):
                E.tip.item_tooltip(e.it, E.data)
            mxl_save.load_character(path, E.data)          # the main window's reader (character list)
            if bytes(ch.build()) != before:
                bad.append(f'{name}: rebuilt bytes differ')
                continue
            ch.save(backup=False)
            if T.read(path) != before:
                bad.append(f'{name}: file changed by SAVE')
                continue
            E.MC.Character(path, E.data)
        except Exception as err:
            bad.append(f'{name}: {type(err).__name__}: {err}')
    T.eq(bad, [], 'mock samples')


T.main(globals())
