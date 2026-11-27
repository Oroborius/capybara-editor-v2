"""Legit mode (vanilla profile): exclusive with Mock Mode, same rules as the dev kit's server validator
(the dev kit validator, vendored unchanged as src/d2bt), refuses hacked characters / items and lets them through with the mode off.

Fixtures: the vanilla install (MXL_TEST_VANILLA_GAME), the vanilla sample character and, read only, the dev kit's
legit_*.d2s files (skipped when the dev kit is not at its usual path)."""
import os
from pathlib import Path
import shutil

import capytest as T

MODE = 'gui'
GEOMETRY = '760x620+0+0'
REPO = Path(T.REPO)
GAME = Path(os.environ.get('MXL_TEST_VANILLA_GAME') or REPO / '.cache/ingame/game')
SOURCE = next((c for c in (REPO / '.cache/samples/vanilla',
                           Path(os.environ.get('MXL_TEST_SAVE_DIR', '/nonexistent')).parent / 'vanilla')
               if (c / 'complex.d2s').is_file()), REPO / '.cache/samples/vanilla')
DEVKIT = Path('/home/ps5/Downloads/D2-Development-Kit/tests')
SAVES = Path(T.guard(os.path.join(T.tmp(), 'legit102-saves')))
AVAILABLE = (GAME / 'd2data.mpq').is_file() and (SOURCE / 'complex.d2s').is_file()
SAVES.mkdir(exist_ok=True)
if AVAILABLE:
    shutil.copy2(SOURCE / 'complex.d2s', SAVES)
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': str(GAME), 'MXL_SAVE_DIR': str(SAVES)}


def need():
    if not AVAILABLE:
        T.skip('no 1.14d game data or sample character')


@T.test
def toggles_are_exclusive():
    need()
    import mxl_legit
    import mxl_mock_gui as G
    import settings
    T.chartab()
    T.pump(5)
    T.check(G._state['lvar'] is not None, 'the Legit Mode checkbox exists next to Mock Mode')
    G.set_mode(False)
    G.set_legit(True)
    T.check(G._state['lvar'].get() and not G._state['var'].get(), 'legit on, mock off')
    T.check(mxl_legit.enabled() and settings.get('legit_mode') is True, 'legit setting saved')
    T.check(G._state['llabel'].winfo_manager() == 'pack', 'the "checked against the server rules" label shows')
    G.set_mode(True)
    T.check(G._state['var'].get() and not G._state['lvar'].get(), 'mock on turns legit off')
    T.check(not mxl_legit.enabled() and not settings.get('legit_mode'), 'legit setting cleared')
    G.set_legit(True)
    T.check(G._state['lvar'].get() and not G._state['var'].get(), 'legit on turns mock off')
    T.check(not settings.get('mock_mode'), 'mock setting cleared')
    G.set_legit(False)
    T.check(not mxl_legit.enabled(), 'legit off')


@T.test
def devkit_legit_saves_validate_clean():
    need()
    starter = DEVKIT / 'legit_starter.d2s'
    if not starter.is_file():
        T.skip('dev kit fixtures not found')
    import mxl_legit
    import mxl_mock_gui as G
    import mxl_char
    T.chartab()
    G.set_legit(True)
    for name in ('starter', 'level_up', 'level_down'):
        raw = (DEVKIT / f'legit_{name}.d2s').read_bytes()
        T.eq(mxl_legit.check_character(raw), [], f'{name}: dev kit bytes')
        path = SAVES / f'fx_{name}.d2s'
        path.write_bytes(raw)
        ch = mxl_char.Character(str(path), T.G.app.data)
        T.eq(mxl_legit.check_character(ch.build()), [], f'{name}: the editor\'s own bytes')
    bad = mxl_legit.check_character((DEVKIT / 'legit_mockhighd.d2s').read_bytes())
    T.check({'experience', 'stat-points', 'skill-points'} <= {f.rule for f in bad}, 'mock clone is not legit')
    G.set_legit(False)


@T.test
def hacked_character_refused_only_in_legit_mode():
    need()
    starter = DEVKIT / 'legit_starter.d2s'
    if not starter.is_file():
        T.skip('dev kit fixtures not found')
    import mxl_char
    import mxl_legit
    import mxl_mock_gui as G
    T.chartab()
    path = SAVES / 'hack.d2s'
    path.write_bytes(starter.read_bytes())
    before = path.read_bytes()
    ch = mxl_char.Character(str(path), T.G.app.data)
    ch.set_stat(0, 500)                                  # strength way over the stat point budget
    G.set_legit(True)
    try:
        ch.save(backup=False)
    except mxl_char.CharError as e:
        T.check(isinstance(e, mxl_legit.LegitError) and 'stat-points' in str(e), f'refused with the rule: {e}')
    else:
        T.check(False, 'the hacked character was written in Legit mode')
    T.check(path.read_bytes() == before, 'file unchanged after the refusal')
    G.set_legit(False)
    ch = mxl_char.Character(str(path), T.G.app.data)
    ch.set_stat(0, 500)
    ch.save(backup=False)
    T.check(path.read_bytes() != before, 'written with Legit mode off')


@T.test
def hacked_item_refused_only_in_legit_mode():
    need()
    import mxl_legit
    import mxl_mock_gui as G
    from mxl_creator import CreateError, Creator
    T.chartab()
    cr = Creator(T.G.app.data)
    spec = None
    for i, _name, u in cr.uniques():
        if T.G.app.data.base(u['code']).kind == 'armor' and T.G.app.data.base(u['code']).size == (2, 2):
            spec = cr.new_spec('unique', None, i)
            break
    T.check(spec is not None, 'a unique armor to build')
    cr.roll(spec, 'max')
    autos = cr.auto_choices(spec['code'], spec['ilvl'])
    if autos:
        spec['auto'] = autos[0][0]
    G.set_legit(False)
    ok, _rec = cr.build(dict(spec))                        # the item as the game makes it
    G.set_legit(True)
    T.eq(mxl_legit.impossible(mxl_legit.check_item(ok)), [], 'a rolled unique passes the item rules')
    spec['unrestricted'] = True
    spec['sockets'] = 7                                    # no unique takes seven sockets
    G.set_legit(False)
    hacked, _rec = cr.build(dict(spec))
    T.check(hacked, 'built with Legit mode off')
    G.set_legit(True)
    try:
        cr.build(dict(spec))
    except CreateError as e:
        T.check('sockets' in str(e), f'refused with the rule: {e}')
    else:
        T.check(False, '7 sockets on a unique built in Legit mode')
    G.set_legit(False)



def _illegit_charm(cr):
    """A small charm (cm1) carrying a medium-charm life suffix, its life value far above any small charm's."""
    import mxl_legit
    from d2bt.legit import allowed
    v = mxl_legit._validator()
    types = v.save_tables.ancestors(v.bases['cm1'][1].get('type'))
    hp = [i for (t, i), (_t, r) in v.affixes.items()
          if t == 'magicsuffix' and r.get('name') and r.get('mod1code') == 'hp' and r.get('spawnable') == '1'
          and not allowed(types, r) and to_int(r.get('level')) <= 30]
    T.check(hp, 'a life suffix that small charms cannot take')
    spec = cr.new_spec('magic', 'cm1 ')
    spec['ilvl'] = 60
    spec['suffix'] = next(i for i, _l, a in cr.affix_choices('magicsuffix', 'cm1 ', 60)
                          if v.affixes[('magicsuffix', i)][1].get('mod1code') == 'hp')
    spec['prefix'] = None
    blob, rec = cr.build(spec)
    from mxl_creator import decode_blob, build_blob
    rec, kids = decode_blob(blob, T.G.app.data)
    rec['suffix'] = hp[0]
    for st in rec['stats']:
        if st['id'] == 7:                               # maximum life
            st['value'] = 400
    return build_blob(rec, kids, T.G.app.data, preserve_stat_order=True)


def to_int(x):
    from d2bt.tooltip.data import to_int as f
    return f(x)


@T.test
def convert_to_strict_legit_charm_and_sockets():
    need()
    import mxl_legit
    import mxl_legit_convert as C
    import mxl_mock_gui as G
    from mxl_creator import Creator, decode_blob, build_blob, FLAG_SOCKETED
    T.chartab()
    cr = Creator(T.G.app.data)
    G.set_legit(False)
    blob = _illegit_charm(cr)
    G.set_legit(True)
    bad = mxl_legit.impossible(mxl_legit.check_item(blob))
    T.check({f.rule for f in bad} >= {'affix-type'}, f'the charm is not legit: {[f.rule for f in bad]}')
    T.check(C.needs_conversion(blob), 'conversion is offered')
    res = C.convert(blob, T.G.app.data)
    T.check(res.blob is not None, f'converted: {C.report(res)} ;; {res.changes} ;; {[(f.rule, f.detail) for f in bad]}')
    T.eq(mxl_legit.impossible(mxl_legit.check_item(res.blob)), [], 'the converted charm is legit')
    kinds = lambda b: sorted({s['id'] for s in decode_blob(b, T.G.app.data)[0]['stats']})
    T.eq(kinds(res.blob), kinds(blob), 'same stat kinds kept')
    T.check(any('->' in c for c in res.changes), f'changes listed: {res.changes}')
    T.check(not C.needs_conversion(res.blob), 'nothing left to convert')
    # (b) too many sockets: a small charm cannot be socketed at all; use a body armor with 7
    G.set_legit(False)
    spec = None
    for code in ('plt ', 'ltp ', 'qui '):
        if code in T.G.app.data.bases:
            spec = cr.new_spec('normal', code)
            break
    spec['sockets'] = 3
    sblob, rec = cr.build(spec)
    rec, kids = decode_blob(sblob, T.G.app.data)
    rec['sockets'] = 7
    sblob = build_blob(rec, kids, T.G.app.data, preserve_stat_order=True)
    G.set_legit(True)
    T.check(any(f.rule == 'sockets' for f in mxl_legit.impossible(mxl_legit.check_item(sblob))),
            f'too many sockets: {[(f.rule, f.detail) for f in mxl_legit.check_item(sblob)]}')
    res = C.convert(sblob, T.G.app.data)
    T.check(res.blob is not None, f'sockets converted: {C.report(res)}')
    T.eq(mxl_legit.impossible(mxl_legit.check_item(res.blob)), [], 'legit after reducing sockets')
    rec, _k = decode_blob(res.blob, T.G.app.data)
    T.check(0 < rec.get('sockets', 0) <= 4, f"sockets reduced to the legal max: {rec.get('sockets')}")
    G.set_legit(False)


@T.test
def convert_menu_entry_only_for_illegit_items_in_legit_mode():
    need()
    import tkinter as tk
    import mxl_legit_convert as C
    import mxl_mock_gui as G
    from mxl_creator import Creator
    win = T.chartab()
    cr = Creator(T.G.app.data)
    G.set_legit(False)
    blob = _illegit_charm(cr)

    class E:
        pass
    e = E()
    e.blob = blob
    menu = tk.Menu(win.top, tearoff=False)
    T.check(not C.add_menu_entry(win, menu, e), 'hidden with Legit mode off')
    G.set_legit(True)
    T.check(C.add_menu_entry(win, menu, e), 'shown for an illegit item in Legit mode')
    T.eq(menu.entrycget(0, 'label'), C.LABEL, 'label')
    res = C.convert(blob, T.G.app.data)
    e.blob = res.blob
    menu2 = tk.Menu(win.top, tearoff=False)
    T.check(not C.add_menu_entry(win, menu2, e), 'hidden once the item passes')
    G.set_legit(False)


# impossible findings per private reference save (sorted order), as the dev kit's checker at the vendored commit
# reports them (None: unreadable = hacked). The saves are private (.cache/samples, never committed): skipped without.
REF_EXPECTED = {
    'legit-ref': [0, 59, 81, 124, 150, 81, 90, 85, 28, 28, 45, 12, 87, 94, 123, 123, 127, None, 48, 26, 77, 15, 82,
                  0, 79, 78, 79, 78, 14, 111, 116, 12, 59, 52, 45, 77],
    'lld-ref': [163, 163, 166, 166, 128, 166, 40],
}


@T.test
def legit_verdicts_match_the_dev_kit_on_the_references():
    import glob
    import mxl_legit
    root = Path(T.REPO) / '.cache' / 'samples'
    if not all((root / d).is_dir() for d in REF_EXPECTED) or not mxl_legit.prepare():
        T.skip('private reference saves or stock tables unavailable')
    for d, want in REF_EXPECTED.items():
        files = sorted(glob.glob(str(root / d / '**' / '*.d2s'), recursive=True))
        T.eq(len(files), len(want), f'{d}: file count')
        got = []
        for f in files:
            fs = mxl_legit.check_character(Path(f).read_bytes())
            got.append(None if any(x.rule in ('unreadable', 'stat') and x.item == 'character' for x in fs)
                       else len(mxl_legit.impossible(fs)))
        T.eq(got, want, f'{d}: impossible findings per save, as the dev kit')


@T.test
def mpq_reads_work_without_os_pread():
    """Windows has no os.pread (tester: Legit mode "module 'os' has no attribute 'pread'"): the stand-in reads the
    game's archives the same way (the vendored reader's own fallback)."""
    import os
    from d2bt.mpq import MPQArchive
    mpq = next((p for p in GAME.glob('*.mpq') if p.name.lower() == 'patch_d2.mpq'), None)
    if mpq is None:
        T.skip('no patch_d2.mpq')
    name = r'data\global\excel\magicprefix.txt'
    want = MPQArchive(str(mpq)).read(name)
    real = os.pread
    try:
        del os.pread
        T.eq(MPQArchive(str(mpq)).read(name), want, 'same bytes without os.pread (the seek + read fallback)')
    finally:
        os.pread = real

T.main(globals())
