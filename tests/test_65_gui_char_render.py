"""The animated character on the Character tab (mxl_dcc, mxl_char_render, mxl_char_view): the DCC decoder against
the COF and animdata.d2 numbers, a stable non-empty composite, and the Stats page's canvas that animates only
while it is visible (no timer when another page or tab is shown). Needs the game folder of the fixture's settings
with d2char.mpq (the character animations); skipped without it."""
import os
import time

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'d2': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0'}}
G = T.G


def art_or_skip():
    import mxl_d2look
    art = mxl_d2look.art()
    if art is None or not os.path.isfile(os.path.join(art.game_dir, 'd2char.mpq')):
        T.skip('no game folder with d2char.mpq')
    return art


def shot(name):
    folder = os.environ.get('CAPY_SHOTS')                 # optional screenshots (ImageMagick import)
    if folder:
        import subprocess
        os.makedirs(folder, exist_ok=True)
        G.root.update()
        subprocess.run(['import', '-window', 'root', os.path.join(folder, f'62-{name}.png')], timeout=30,
                       capture_output=True)


def view():
    import mxl_char_gui
    cw = T.chartab()
    if cw is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    T.select_tab('Character')
    cw.tab.set('stats')
    cw.show_tab()
    T.settle(0.3)
    return cw


@T.test
def dcc_decode_matches_cof_and_animdata():
    import mxl_char_render as R
    import mxl_dcc as D
    art = art_or_skip()
    folder = view().data.folder
    ad = R._animdata(art, folder)
    for name in ('patnhth', 'sonuhth', 'aitnhth'):
        cl = name[:2]
        cof = D.COF(R.read(art, f'data\\global\\chars\\{cl}\\cof\\{name}.cof'))
        T.check(name in ad, f'{name} in animdata.d2')
        T.eq(cof.frames, ad[name][0], f'{name}: COF frames = animdata frames per direction')
        T.check(cof.layers and cof.order is not None, f'{name}: COF layers and draw order')
        t, _tr, _ef, wc = next(l for l in cof.layers if l[0] == 1)          # torso
        data = R.read(art, f'data\\global\\chars\\{cl}\\tr\\{cl}trlit{name[2:4]}{wc}.dcc')
        ndir, nfr, _o = D.header(data)
        T.eq((ndir, nfr), (cof.dirs, cof.frames), f'{name}: DCC directions / frames = COF')
        frs = D.decode_direction(data, R.FRONT)
        T.eq(len(frs), cof.frames, f'{name}: decoded frames')
        T.eq(len({(f.w, f.h, f.x0, f.y0) for f in frs}), 1, f'{name}: one box for the direction')
        T.check(10 < frs[0].w < 200 and 10 < frs[0].h < 200, f'{name}: torso size {frs[0].w}x{frs[0].h}')
        T.check(sum(1 for b in frs[0].pixels if b) > 100, f'{name}: torso has pixels')


@T.test
def composite_is_non_empty_and_stable():
    import mxl_char_render as R
    art = art_or_skip()
    folder = view().data.folder
    gear = {1: 'crn', 3: 'fld', 4: '14@', 5: 'tow'}           # crown, field plate, crystal sword, tower shield
    t = time.time()
    a = R.render(art, folder, 3, gear)
    secs = time.time() - t
    b = R.render(art, folder, 3, gear)
    T.check(a is not None and len(a.frames) == 16, 'paladin town idle: 16 frames')
    T.check(a.fps > 1, f'fps {a.fps}')
    T.eq([f.tobytes() for f in a.frames], [f.tobytes() for f in b.frames], 'the same frames twice')
    opaque = sum(a.frames[0].split()[3].histogram()[1:])
    T.check(opaque > 1500, f'opaque pixels {opaque}')
    plain = R.render(art, folder, 3, {})
    T.check(plain.frames[0].tobytes() != a.frames[0].tobytes(), 'gear changes the picture')
    T.check(secs < 20, f'render time {secs:.1f}s')


@T.test
def canvas_animates_only_while_visible():
    art_or_skip()
    cw = view()
    v = getattr(cw, 'char_view', None)
    T.check(v is not None, 'Stats page has the character view')
    T.wait_for(lambda: v.anim is not None and v.shown, 30, 'character rendered and placed')
    T.check(v.cv.winfo_viewable(), 'canvas viewable on the Stats page')
    shot('stats')
    i0 = v.index
    T.settle(0.5)
    T.check(v._job is not None and v.index != i0, 'animating on the Stats page')
    cw.tab.set('inventory')
    cw.show_tab()
    T.settle(0.4)
    i1 = v.index
    T.settle(0.4)
    T.check(v._job is None and v.index == i1, 'stopped on the Inventory page')
    cw.tab.set('stats')
    cw.show_tab()
    T.settle(0.5)
    T.check(v._job is not None and v.index != i1, 'animating again on the Stats page')
    T.select_tab('Stash' if 'Stash' in T.tab_names() else T.tab_names()[0])
    T.settle(0.4)
    i2 = v.index
    T.settle(0.4)
    T.check(v._job is None and v.index == i2, 'stopped when another main tab is shown')
    T.select_tab('Character')
    T.settle(0.5)
    T.check(v._job is not None, 'animating again on the Character tab')


def _logged(R):
    """Wraps R.read: the list of member names read successfully."""
    got = []
    real = R.read

    def read(art, name):
        d = real(art, name)
        got.append(name.lower())
        return d
    R.read = read
    return got, real


@T.test
def owlie_render_uses_worn_gear():
    import glob
    import mxl_char
    import mxl_char_render as R
    art = art_or_skip()
    cw = view()
    data = cw.data
    path = sorted(glob.glob(os.path.join(T.fresh_saves(3), 'test-druid*.d2s')))[0]
    ch = mxl_char.Character(path, data)
    gear = R.gear_of(ch)
    T.eq({k: v[0] for k, v in gear.items()}, {1: 'k23', 3: '838', 4: '483', 5: '851'},
         'test-druid: Tiara / Splint Mail / Dirk / Buckler (save codes without the padding space)')
    T.eq({k: v[1] for k, v in gear.items()}, {1: 4, 3: 5, 4: 19, 5: 7}, 'unique colours (chrtransform)')
    got, real = _logged(R)
    try:
        a = R.render(art, data.folder, ch.cls, gear)
    finally:
        R.read = real
    d = 'data\\global\\chars\\dz\\'
    for want in ('cof\\dztn1ht.cof', 'tr\\dztrhvytnhth.dcc', 'ra\\dzramedtn1ht.dcc', 'la\\dzlamedtn1ht.dcc',
                 'rh\\dzrhdirtn1ht.dcc', 'sh\\dzshbuctnhth.dcc', 'hd\\dzhdlittnhth.dcc'):
        T.check(d + want in got, f'read {want}')
    T.check(any('items\\palette\\grey2.dat' in n for n in got), 'colormap grey2.dat read (tints)')
    T.check(a is not None and a.key[1] == '1ht', f'one-handed thrust animation: {a and a.key[:2]}')
    plain = R.render(art, data.folder, ch.cls, {})
    T.check(plain.frames[0].tobytes() != a.frames[0].tobytes(), 'differs from the bare model')
    untinted = R.render(art, data.folder, ch.cls, {k: v[0] for k, v in gear.items()})
    T.check(untinted.frames[0].tobytes() != a.frames[0].tobytes(), 'colour tints change the picture')
    folder = os.environ.get('CAPY_SHOTS')
    if folder:
        os.makedirs(folder, exist_ok=True)
        a.frames[0].resize((a.size[0] * 4, a.size[1] * 4)).save(os.path.join(folder, '65-owlie.png'))


@T.test
def every_class_wears_a_typical_outfit():
    import mxl_char_render as R
    art = art_or_skip()
    folder = view().data.folder
    for cls, cl in enumerate(R.CLASS_CODES):
        gear = {1: 'crn', 3: 'fld', 4: '382'}                  # crown, field plate, claymore (two-handed) ...
        if cl == 'ba':
            gear[5] = 'tow'                                    # ... the barbarian wields it in one hand + shield
        got, real = _logged(R)
        try:
            a = R.render(art, folder, cls, gear)
        finally:
            R.read = real
        T.check(a is not None, f'{cl}: rendered')
        T.eq(a.key[1], '1hs' if cl == 'ba' else '2hs', f'{cl}: claymore weapon class')
        for ly, part in (('hd', 'crn'), ('tr', 'hvy'), ('rh', 'clm')) + ((('sh', 'tow'),) if cl == 'ba' else ()):
            T.check(any(f'\\{ly}\\{cl}{ly}{part}' in n for n in got), f'{cl}: {ly} layer {part}')


@T.test
def view_renders_the_loaded_characters_gear():
    import mxl_char_render as R
    art_or_skip()
    cw = view()
    v = cw.char_view
    T.wait_for(lambda: v.anim is not None and not v._busy, 30, 'character rendered')
    gear = R.gear_of(cw.ch)
    T.check(gear, 'the loaded character wears something')
    T.eq(v._key, (cw.ch.cls, tuple(sorted(gear.items()))), 'render key = class + gear with colours')
    T.check(len(v.anim.key[2]) > 0, f'gear layers in the shown render: {v.anim.key[2]}')
    # another character (test-druid, druid) in the window: the view renders it again
    import glob
    import mxl_char
    path = sorted(glob.glob(os.path.join(T.fresh_saves(3), 'test-druid*.d2s')))[0]
    old = cw.ch
    cw.ch = mxl_char.Character(path, cw.data)
    try:
        T.wait_for(lambda: v.anim is not None and v.anim.key[0] == 'dz' and not v._busy, 30, 'druid rendered')
        T.eq(v.anim.key[1], '1ht', 'with the dirk')
        T.eq(v._key, (cw.ch.cls, tuple(sorted(R.gear_of(cw.ch).items()))), 'render key follows the character')
    finally:
        cw.ch = old


T.main(globals())
