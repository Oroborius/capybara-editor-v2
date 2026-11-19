"""The town backdrop (mxl_scene): the DS1 maps of the five towns parse with sane sizes, layers and objects; DT1
tiles decode (floor diamonds and RLE walls); Act 1's scene is a non-empty, colourful picture with at least one
animated object (a torch / fire / waypoint) whose frames are the same size. Needs the game folder of the fixture's
settings.json (the map and tile archives); skipped without it."""
import json
import os
import time

import capytest as T

MODE = 'engine'
NEEDS = ('user',)


def setup():
    try:
        with open(os.path.join(T.SRC_USER, 'settings.json'), encoding='utf-8') as f:
            gd = json.load(f).get('game_dir')
    except (OSError, ValueError):
        gd = None
    if not gd or not os.path.isfile(os.path.join(gd, 'medianxl-version.mpq')):
        T.skip('no game folder in the fixture settings.json (game_dir): the map archives are needed')
    import sys
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import mxl_d2look_art as A
    folder = os.path.join(T.SRC_USER, 'data')
    if not os.path.isfile(os.path.join(folder, 'lvlprest.bin')):
        T.skip('no lvlprest.bin in the fixture tables')
    return A.get_art(gd, 'tartarus', os.path.join(T.tmp(), 'scene_art')), folder


@T.test
def town_maps_parse():
    import mxl_char_render as R
    import mxl_scene as S
    art, folder = setup()
    for act in range(1, 6):
        ds1, dt1 = S.town_files(folder, act)
        T.check(ds1 and dt1, f'act {act}: town DS1 {ds1} and DT1 list {len(dt1)}')
        m = S.DS1(R.read(art, ds1[0]))
        T.check(20 <= m.w <= 200 and 20 <= m.h <= 200, f'act {act}: size {m.w}x{m.h}')
        T.eq(m.act, act - 1, f'act {act}: the DS1 act')
        T.check(m.walls and m.floors and all(len(f) == m.w * m.h for f in m.floors), f'act {act}: layers')
        objs = [o for o in m.objects if o[0] == 2]
        T.check(len(objs) >= 10, f'act {act}: {len(objs)} objects')
        T.check(all(0 <= x <= m.w * 5 and 0 <= y <= m.h * 5 for _t, _i, x, y in objs), f'act {act}: objects inside')


@T.test
def tiles_decode():
    import mxl_char_render as R
    import mxl_scene as S
    art, folder = setup()
    _ds1, dt1 = S.town_files(folder, 1)
    tiles = S.dt1_tiles(R.read(art, dt1[0]))                     # Act1/Town/Floor.dt1
    floors = [t for t in tiles if t.orient == 0]
    T.check(len(floors) > 20, f'{len(floors)} floor tiles')
    w, h, px, x0, y0 = floors[0].pixels()
    T.check(w == 160 and h >= 80, f'floor tile {w}x{h}')
    T.check(sum(1 for b in px if b) > 160 * 80 // 3, 'floor diamond filled')
    walls = [t for d in dt1[1:4] for t in S.dt1_tiles(R.read(art, d)) if 0 < t.orient < 15]
    T.check(walls, 'wall tiles')
    w, h, px, x0, y0 = walls[0].pixels()
    T.check(y0 < 0 and sum(1 for b in px if b) > 100, f'wall tile hangs up from its cell ({w}x{h} @ {y0})')


@T.test
def act1_scene():
    import mxl_scene as S
    art, folder = setup()
    t = time.time()
    sc = S.scene(art, folder, 1, (512, 384))
    secs = time.time() - t
    T.check(sc is not None, 'scene built')
    T.eq(sc.base.size, (512, 384), 'size')
    cols = sc.base.getcolors(1 << 20) or []
    T.check(len(cols) > 100, f'{len(cols)} colours')
    black = sum(n for n, c in cols if c == (0, 0, 0))
    T.check(black < 512 * 384 // 10, f'{black} black pixels')
    ax, ay = sc.anchor
    T.check(0 <= ax < 512 and 0 <= ay < 384, f'anchor {sc.anchor}')
    T.check(sc.sprites, 'animated objects')
    for s in sc.sprites:
        T.check(len(s['frames']) > 1 and len({f.size for f in s['frames']}) == 1 and 1 <= s['fps'] <= 25,
                f'sprite at {s["pos"]}: {len(s["frames"])} frames, {s["fps"]} fps')
    T.check(S.scene(art, folder, 1, (512, 384)) is sc, 'cached per (act, size)')
    print(f'act 1 scene: {secs:.1f} s, {len(sc.sprites)} animated objects')


T.main(globals())
