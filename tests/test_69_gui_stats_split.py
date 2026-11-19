"""The Stats page's split layout (dark look): at 1600x900 the stat screen's two pages sit at the left and right
edges with the scene (the animated character, mxl_char_view) between them, a page dragged towards the middle stays
there (settings.json) and a double click puts it back, the window's minsize keeps two pages + the scene, the scene
takes a background (set_background) and animates its sprites; at 800x600 the layout of before (no split, no minsize forced, the character beside the pages).
Set CAPY_SHOTS=<folder> for screenshots."""
import os
import subprocess

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'d2-1600x900': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1600x900+0+0'}}
G = T.G


def shot(name):
    folder = os.environ.get('CAPY_SHOTS')
    if folder:
        os.makedirs(folder, exist_ok=True)
        G.root.update()
        subprocess.run(['import', '-window', 'root', os.path.join(folder, f'68-{name}.png')], timeout=30,
                       capture_output=True)


def stats():
    import mxl_char_gui
    cw = T.chartab()
    if cw is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    T.select_tab('Character')
    cw.tab.set('stats')
    cw.show_tab()
    T.settle(0.5)
    scr = cw.statscreen
    if scr is None:
        T.skip('no stat screen (no game art)')
    return cw, scr


def page_boxes(scr):
    import mxl_statscreen as S
    pw = round(S.PANEL_W * scr.k)
    return [(scr.slot_x(i), scr.slot_x(i) + pw) for i in range(len(scr.shown))]


@T.test
def pages_at_the_edges_scene_between():
    cw, scr = stats()
    T.check(scr.split, f'split layout at 1600x900 (k {scr.k}, canvas {scr.cv.winfo_width()})')
    T.eq(len(scr.shown), 2, 'two pages')
    (a0, a1), (b0, b1) = page_boxes(scr)
    W = scr.cv.winfo_width()
    T.eq(a0, 0, 'page A at the left edge')
    T.eq(b1, W, 'page B at the right edge')
    T.check(a1 + scr.min_scene() <= b0, f'pages apart by the scene: A ends {a1}, B starts {b0}')
    box = scr.scene_box()
    T.eq((box[0], box[0] + box[2]), (a1, b0), 'scene box between the pages')
    v = getattr(cw, 'char_view', None)
    if v is not None:
        T.settle(0.3)
        T.check(v.shown and v.box is not None, 'scene canvas placed')
        x = v.cv.winfo_x() - scr.cv.winfo_x()
        T.check(a1 <= x and x + v.cv.winfo_width() <= b0, f'scene canvas {x}+{v.cv.winfo_width()} between {a1} and {b0}')
    # a click on a page still reaches its boxes (regions follow the page)
    T.check(any(b[0] * scr.k >= b0 - 1 for _k, _s, b, _p in scr._regions), 'regions of page B at its place')
    shot('1600x900')


@T.test
def scene_background_hook():
    cw, scr = stats()
    v = getattr(cw, 'char_view', None)
    if v is None:
        T.skip('no character view')
    from PIL import Image

    class Scene:
        base = Image.new('RGBA', (400, 300), (40, 80, 40, 255))
        sprites = [{'pos': (10, 10), 'frames': [Image.new('RGBA', (8, 8), (255, 0, 0, 255)),
                                                 Image.new('RGBA', (8, 8), (0, 0, 255, 255))], 'fps': 10}]
        anchor = (200, 250)
    v.set_background(Scene())
    T.settle(0.4)
    T.check(v._bg_photo is not None and v.cv.itemcget(v._bg, 'state') == 'normal', 'background drawn')
    T.eq(len(v._sprites), 1, 'sprite on the scene')
    T.check(v._job is not None, 'scene animates')
    v.set_background(None)
    T.settle(0.2)
    T.eq(v.cv.itemcget(v._bg, 'state'), 'hidden', 'no background: dark ground')


@T.test
def moved_page_persists_and_double_click_resets():
    import settings
    import mxl_statscreen as S
    cw, scr = stats()
    m = scr.max_offset()
    T.check(m > 20, f'room to move a page ({m})')
    # drag page A by 60 px to the right on an empty part of the panel
    (a0, a1), _ = page_boxes(scr)
    y = scr.cv.winfo_height() - 8
    x = next((x for x in range(a0 + 4, a1 - 4, 4) if scr._at(type('E', (), {'x': x, 'y': y})())[0] is None), None)
    T.check(x is not None, 'an empty point on page A')
    scr.cv.event_generate('<ButtonPress-1>', x=x, y=y)
    scr.cv.event_generate('<B1-Motion>', x=x + 30, y=y, state=0x100)
    scr.cv.event_generate('<B1-Motion>', x=x + 60, y=y, state=0x100)
    scr.cv.event_generate('<ButtonRelease-1>', x=x + 60, y=y)
    T.pump(4)
    T.check(abs(scr.slot_x(0) - 60) <= 2, f'page A moved to {scr.slot_x(0)}')
    saved = settings.get(S.OFFSETS_SETTING)
    T.check(saved and abs(saved[0] * scr.k - 60) <= 2, f'offset saved: {saved}')
    T.eq(S.StatScreen._load_offsets(scr)[0], saved[0], 'offset read back')
    scr.move_page(1, 40)
    _, (b0, b1) = page_boxes(scr)
    T.check(abs(scr.cv.winfo_width() - b1 - round(40 * scr.k)) <= 1, 'page B moved from the right edge')
    shot('moved')
    xx = scr.slot_x(0) + (x - a0)
    for t in (1000, 1050):                          # two clicks 50 ms apart: <Double-Button-1>
        scr.cv.event_generate('<ButtonPress-1>', x=xx, y=y, time=t)
        scr.cv.event_generate('<ButtonRelease-1>', x=xx, y=y, time=t + 10)
    T.pump(3)
    T.eq(scr.slot_x(0), 0, 'double click: page A back at the edge')
    scr.move_page(1, 0)


@T.test
def minsize_and_small_window():
    cw, scr = stats()
    root = G.root
    nw, nh = scr.min_size()
    mw, mh = root.minsize()
    T.check(mw >= nw and mh >= nh, f'minsize {mw}x{mh} holds two pages + scene ({nw}x{nh})')
    T.check(mw <= 1600 and mh <= 900, f'minsize {mw}x{mh} within the window')
    cw.tab.set('inventory')
    cw.show_tab()
    T.settle(0.3)
    T.check(root.minsize()[0] < nw, f'minsize back on the Inventory page: {root.minsize()}')
    cw.tab.set('stats')
    cw.show_tab()
    T.settle(0.3)
    T.check(root.minsize()[0] >= nw, f'minsize again on the Stats page: {root.minsize()}')
    T.select_tab('Stash')
    T.settle(0.3)
    T.check(root.minsize()[0] < nw, f'minsize back on another tab: {root.minsize()}')
    root.geometry('800x600+0+0')
    T.settle(0.5)
    cw, scr = stats()
    T.settle(0.4)
    T.eq(root.winfo_width(), 800, 'window width 800')
    T.check(not scr.split, 'no split layout at 800x600')
    T.eq(len(scr.shown), scr.spread, 'the layout of before (the book of two pages, or one page)')
    T.check(root.minsize()[0] <= 800, f'no minsize forced at 800x600: {root.minsize()}')
    T.check(scr.slot_x(len(scr.shown) - 1) + round(512 * scr.k) <= scr.cv.winfo_width(), 'pages inside the canvas')
    v = getattr(cw, 'char_view', None)
    if v is not None and v.shown:                    # the character beside the pages, never over them
        x0 = scr.cv.winfo_x()
        vx = v.cv.winfo_x()
        T.check(vx + v.cv.winfo_width() <= x0, f'character {vx}+{v.cv.winfo_width()} left of the pages at {x0}')
    shot('800x600')
    root.geometry('1600x900+0+0')
    T.settle(0.5)


T.main(globals())
