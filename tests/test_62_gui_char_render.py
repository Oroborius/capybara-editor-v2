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
    gear = {1: 'crn', 3: 'fld', 4: '382', 5: 'tow'}           # crown, field plate, claymore, tower shield
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


T.main(globals())
