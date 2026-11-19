"""The town scene behind the character on the Stats page (mxl_char_view, split layout at 1600x900) for test-druid
(MXL_TEST_SAVE_DIR3, act 1): the default framing shows at least one town NPC, the mouse wheel zooms (the scene is
asked for at room / zoom: its size halves / doubles), dragging the empty scene pans (a new centre, rendered again)
and a double click resets the framing. Needs the game folder of the fixture's settings; skipped without it.
Set CAPY_SHOTS=<folder> for screenshots."""
import os
import subprocess

import capytest as T

MODE = 'gui'
RESET = True
NEEDS = ('user', 'saves', 'saves3')
VARIANTS = {'d2-1600x900': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1600x900+0+0'}}
G = T.G


def shot(name):
    folder = os.environ.get('CAPY_SHOTS')
    if folder:
        os.makedirs(folder, exist_ok=True)
        G.root.update()
        subprocess.run(['import', '-window', 'root', os.path.join(folder, f'72-{name}.png')], timeout=30,
                       capture_output=True)


def owlie_view():
    import mxl_char_gui
    import mxl_d2look
    art = mxl_d2look.art()
    if art is None or not os.path.isfile(os.path.join(art.game_dir, 'd2char.mpq')):
        T.skip('no game folder with d2char.mpq')
    cw = T.chartab()
    if cw is None or os.path.basename(cw.ch.path) != 'test-druid.d2s':
        path = os.path.join(T.fresh_saves(3), 'test-druid.d2s')
        if not os.path.isfile(path):
            T.skip('MXL_TEST_SAVE_DIR3 holds no test-druid.d2s')
        G.app.character_file = lambda: path
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    T.select_tab('Character')
    cw.tab.set('stats')
    cw.show_tab()
    T.settle(0.5)
    v = getattr(cw, 'char_view', None)
    if v is None or not getattr(cw.statscreen, 'split', False):
        T.skip('no split Stats page with the character view')
    return v


def ready(v):
    """The scene asked for is the one shown."""
    return (not v._scene_busy and v._scene_key in v._scenes and v.scene is v._scenes[v._scene_key]
            and getattr(v.scene, 'base', None) is not None)


def wait_scene(v, what):
    T.wait_for(lambda: (G.root.update(), ready(v))[1], 90, what)
    T.settle(0.3)


def npcs_seen(v):
    """NPC sprites (the ones add_npcs added) inside the canvas."""
    sc = v.scene
    own = len(getattr(sc._scene, 'sprites', ()))
    w, h = v.box[2], v.box[3]
    n = 0
    for sp in sc.sprites[own:]:
        x, y = sp['pos']
        fw, fh = sp['frames'][0].size
        f = v._scene_f
        bx = (w - sc.base.width * f) / 2 + x * f
        by = (h - sc.base.height * f) / 2 + y * f
        if bx + fw * f > 0 and bx < w and by + fh * f > 0 and by < h:
            n += 1
    return n


def far_point(v):
    """A canvas point of the scene away from the character."""
    w, h = v.box[2], v.box[3]
    for x, y in ((12, 12), (w - 12, 12), (12, h - 12), (w - 12, h - 12)):
        if not v._on_char(x, y):
            return x, y
    T.fail('no empty scene point')


@T.test
def default_framing_shows_npcs():
    v = owlie_view()
    T.eq(v._act(), 1, "test-druid's act")
    wait_scene(v, 'town scene rendered')
    T.check(v.scene.centre is not None, f'scene centre {v.scene.centre}')
    T.check(npcs_seen(v) >= 1, f'town NPCs in the default framing: {npcs_seen(v)}')
    shot('default')


@T.test
def wheel_zooms():
    v = owlie_view()
    wait_scene(v, 'town scene rendered')
    z0 = v._zoom_now(v.box[3])
    w0 = v.scene.base.width
    x, y = far_point(v)
    if z0 > 1:
        v.cv.event_generate('<Button-5>', x=x, y=y)
        wait_scene(v, 'zoomed out')
        T.eq(v.zoom, z0 - 1, 'wheel down: zoom out')
        w1 = v.scene.base.width
        T.check(abs(w1 * (z0 - 1) - w0 * z0) <= z0, f'scene width {w0} -> {w1} (zoom {z0} -> {z0 - 1})')
        v.cv.event_generate('<Button-4>', x=x, y=y)
        wait_scene(v, 'zoomed in again')
        T.eq(v.zoom, z0, 'wheel up: zoom in')
        T.eq(v.scene.base.width, w0, 'the scene size of before')
    v.cv.event_generate('<Button-4>', x=x, y=y)
    wait_scene(v, 'zoomed in')
    z1 = v.zoom
    T.eq(z1, min(z0 + 1, 3), 'wheel up')
    if z1 != z0:
        w2 = v.scene.base.width
        T.check(abs(w2 * z1 - w0 * z0) <= z1, f'scene width {w0} -> {w2} (zoom {z0} -> {z1})')
    for _ in range(3):
        v.cv.event_generate('<Button-4>', x=x, y=y)
    T.eq(v.zoom, 3, 'zoom stops at 3')
    import settings
    T.eq(settings.get('char_view_zoom'), 3, 'zoom remembered (settings.json)')
    wait_scene(v, 'zoom 3 rendered')
    shot('zoom3')
    v.cv.event_generate('<Double-Button-1>', x=x, y=y)
    wait_scene(v, 'reset')


@T.test
def drag_pans_and_double_click_resets():
    v = owlie_view()
    wait_scene(v, 'town scene rendered')
    c0 = v.scene.centre
    k0 = v._scene_key
    x, y = far_point(v)
    dx = 40 if x < v.box[2] / 2 else -40
    dy = 30 if y < v.box[3] / 2 else -30
    v.cv.event_generate('<ButtonPress-1>', x=x, y=y)
    v.cv.event_generate('<B1-Motion>', x=x + dx, y=y + dy)
    v.cv.event_generate('<ButtonRelease-1>', x=x + dx, y=y + dy)
    T.check(v.centre is not None and v.centre != c0, f'centre moved {c0} -> {v.centre}')
    f = v._scene_f
    T.check(abs(v.centre[0] - (c0[0] - dx / f)) <= 1 and abs(v.centre[1] - (c0[1] - dy / f)) <= 1,
            'moved against the drag')
    wait_scene(v, 'panned scene rendered')
    T.eq(v.scene.centre, v.centre, 'the scene rendered at the new centre')
    T.check(v._scene_key != k0, 'a new scene')
    shot('panned')
    v.cv.event_generate('<Double-Button-1>', x=x, y=y)
    T.eq(v.centre, None, 'double click: default framing')
    wait_scene(v, 'default scene again')
    T.eq(v.scene.centre, c0, 'the default centre again')
    T.check(len(v._scenes) <= 4, f'scenes kept: {len(v._scenes)}')
    # a click on the character still turns it
    d0 = v.direction
    v.turn(1)
    T.eq(v.direction, (d0 + 1) % 8, 'character turns')
