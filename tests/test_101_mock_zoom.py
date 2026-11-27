"""Mock Mode: dragging the window bigger scales the Hero Editor pages and the Mock tab by one factor; off -> 1x."""
import os
from pathlib import Path
import shutil

import capytest as T

MODE = 'gui'
GEOMETRY = '760x620+0+0'
REPO = Path(T.REPO)
GAME = Path(os.environ.get('MXL_TEST_VANILLA_GAME') or REPO / '.cache/ingame/game')
SOURCE = REPO / '.cache/samples/vanilla'
SAVES = Path(T.guard(os.path.join(T.tmp(), 'zoom101-saves')))
AVAILABLE = (GAME / 'd2data.mpq').is_file() and (SOURCE / 'complex.d2s').is_file()
SAVES.mkdir(exist_ok=True)
if AVAILABLE:
    shutil.copy2(SOURCE / 'complex.d2s', SAVES)
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': str(GAME), 'MXL_SAVE_DIR': str(SAVES)}


def sample(root):
    """(a placed widget's width, a tuple-font size, TkDefaultFont size)"""
    from tkinter import font as tkfont
    placed = fonted = None
    stack = [root]
    while stack and (placed is None or fonted is None):
        w = stack.pop()
        stack.extend(w.winfo_children())
        if placed is None and w.winfo_manager() == 'place' and str(w.place_info().get('width', '')).isdigit() \
                and int(w.place_info()['width']) > 40:
            placed = w
        if fonted is None:
            try:
                f = w.cget('font')
            except Exception:
                f = None
            if f and str(f) not in tkfont.names(w):
                fonted = w
    return placed, fonted


def size_of(w):
    from tkinter import font as tkfont
    return abs(tkfont.Font(root=w, font=w.cget('font')).actual()['size'])


@T.test
def mock_zoom_scales_with_the_window():
    if not AVAILABLE:
        T.skip('no 1.14d game data or sample character')
    import mxl_mock_gui
    from tkinter import font as tkfont
    T.chartab()
    T.pump(5)
    root = T.G.root
    placed, fonted = sample(root)
    T.check(placed is not None and fonted is not None, 'found a placed widget and a widget font')
    w0, f0 = int(placed.place_info()['width']), size_of(fonted)
    d0 = abs(tkfont.nametofont('TkDefaultFont').cget('size'))
    mxl_mock_gui.set_mode(True, select=False)
    T.pump(5)
    zoom = mxl_mock_gui._state['zoom']
    root.geometry('1200x700+0+0')
    T.pump(5)
    zoom.apply()
    T.pump(5)
    T.check(zoom.z > 1.2, f'zoomed to {zoom.z}')
    T.check(int(placed.place_info()['width']) > w0, f"placed width {w0} -> {placed.place_info()['width']}")
    T.check(size_of(fonted) > f0, f'font {f0} -> {size_of(fonted)}')
    T.check(abs(tkfont.nametofont('TkDefaultFont').cget('size')) > d0, 'TkDefaultFont scaled')
    root.update_idletasks()
    shot = os.environ.get('ZOOM_SHOT')
    if shot:
        os.system(f'import -window root {shot}')
        import mxl_tabs
        page = mxl_mock_gui._state['page']
        if page is not None and mxl_tabs._state.get('nb') is not None:
            mxl_tabs._state['nb'].select(page.host)
            T.pump(10)
            zoom.apply()
            T.pump(5)
            os.system(f'import -window root {shot[:-4]}-mock.png')
    mxl_mock_gui.set_mode(False)
    T.pump(5)
    zoom.apply()
    T.pump(3)
    T.eq(zoom.z, 1.0, 'Mock Mode off: back to 1x')
    T.eq(int(placed.place_info()['width']), w0, 'placed width restored')
    T.eq(size_of(fonted), f0, 'font restored')
    T.eq(abs(tkfont.nametofont('TkDefaultFont').cget('size')), d0, 'TkDefaultFont restored')


T.main(globals())
