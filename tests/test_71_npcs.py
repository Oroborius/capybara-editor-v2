"""Town NPCs (mxl_npcs): Act 1's map presets resolve to Akara, Kashya, Charsi, Gheed and Warriv with non-empty
animations (monpreset -> monstats -> monstats2 -> COF + DCC layers); every act has resolvable NPCs; the NPC sprites
of a scene window are equal-size frames inside .base, and add_npcs leaves the scene's own list alone. Needs the game
folder of the fixture's settings.json; skipped without it."""
import json
import os

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
        T.skip('no game folder in the fixture settings.json (game_dir): the monster archives are needed')
    import sys
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import mxl_d2look_art as A
    folder = os.path.join(T.SRC_USER, 'data')
    if not os.path.isfile(os.path.join(folder, 'monpreset.bin')):
        T.skip('no monpreset.bin in the fixture tables')
    return A.get_art(gd, 'tartarus', os.path.join(T.tmp(), 'npc_art')), folder


@T.test
def act1_npcs_resolve():
    import mxl_npcs as N
    import mxl_scene as S
    art, folder = setup()
    pal = S.act_palette(art, 1)
    got = {}
    for name, tok, mid, _pos in N.town_presets(art, folder, 1):
        a = N.monster_anim(art, folder, pal, mid)
        if a:
            got[name] = a
    for want in ('Akara', 'Kashya', 'Charsi', 'Gheed', 'Warriv'):
        T.check(want in got, f'{want} resolves ({sorted(got)})')
        if want in got:
            frames, x0, y0, fps = got[want]
            T.check(frames and frames[0].getbbox(), f'{want}: frame 0 not empty')
            T.check(y0 < 0 and 1 <= fps <= 25, f'{want}: above the feet ({y0}), {fps} fps')
    for act in range(2, 6):
        ps = N.town_presets(art, folder, act)
        T.check(ps, f'act {act}: NPC presets')


@T.test
def act1_window_sprites():
    import mxl_npcs as N
    import mxl_scene as S
    art, folder = setup()
    size = (1600, 1000)
    sc = S.scene(art, folder, 1, size)
    sp = N.town_npcs(art, folder, 1, sc)
    T.check(any(s['name'] == 'Akara' for s in sp) or len(sp) >= 3, f'NPCs in the window: {[s["name"] for s in sp]}')
    for s in sp:
        x, y = s['pos']
        fw, fh = s['frames'][0].size
        T.check(x >= 0 and y >= 0 and x + fw <= size[0] and y + fh <= size[1], f'{s["name"]} box {s["pos"]} inside')
        T.check(len({f.size for f in s['frames']}) == 1 and 1 <= s['fps'] <= 25, f'{s["name"]} frames')
    n = len(sc.sprites)
    both = N.add_npcs(sc, art, folder, 1)
    T.eq(len(sc.sprites), n, 'scene sprites untouched')
    T.eq(len(both), n + len(sp), 'add_npcs appends')


T.main(globals())
