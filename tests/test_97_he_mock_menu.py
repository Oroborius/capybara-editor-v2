"""Hero Editor layout: Mock Mode from the Menu shows its tools page; opening the Menu repeatedly keeps texts."""
import os
from pathlib import Path
import shutil

import capytest as T

MODE = 'gui'
GEOMETRY = '760x620+0+0'
REPO = Path(T.REPO)
GAME = Path(os.environ.get('MXL_TEST_VANILLA_GAME') or REPO / '.cache/ingame/game')
SOURCE = REPO / '.cache/samples/vanilla'
SAVES = Path(T.guard(os.path.join(T.tmp(), 'he97-saves')))
AVAILABLE = (GAME / 'd2data.mpq').is_file() and (SOURCE / 'complex.d2s').is_file()
SAVES.mkdir(exist_ok=True)
if AVAILABLE:
    shutil.copy2(SOURCE / 'complex.d2s', SAVES)
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': str(GAME), 'MXL_SAVE_DIR': str(SAVES)}


def texts(root):
    out = {}
    stack = [root]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        for key in ('text',):
            try:
                out[(str(w), key)] = str(w.cget(key))
            except Exception:
                pass
        if w.winfo_class() == 'Canvas':
            for item in w.find_all():
                try:
                    t = w.itemcget(item, 'text')
                except Exception:
                    continue
                out[(str(w), 'item', item)] = t
    return out


@T.test
def he_menu_open_close_keeps_every_text():
    if not AVAILABLE:
        T.skip('no 1.14d game data or sample character')
    cw = T.chartab()
    T.pump(5)
    menu = cw.he_menu
    before = texts(T.G.root)
    for _ in range(20):
        menu.tk.call(menu.cget('postcommand'))
        T.pump(2)
    after = texts(T.G.root)
    T.eq({k: v for k, v in before.items() if after.get(k) != v}, {}, 'texts changed or vanished')
    T.check(len(before) > 20, f'{len(before)} texts compared')


@T.test
def he_menu_mock_mode_shows_the_mock_tools():
    if not AVAILABLE:
        T.skip('no 1.14d game data or sample character')
    import mxl_mock_gui
    import mxl_tabs
    cw = T.chartab()
    menu = cw.he_menu
    var = mxl_mock_gui._state['var']
    T.check(var is not None, 'Mock Mode switch exists in the vanilla profile')
    menu.tk.call(menu.cget('postcommand'))
    idx = {menu.entrycget(i, 'label'): i for i in range(menu.index('end') + 1)
           if menu.type(i) in ('command', 'cascade', 'checkbutton')}
    T.check('Mock Mode' in idx and 'Open Mock Tools' in idx, 'Mock entries in the HE Menu')
    T.eq(menu.entrycget(idx['Open Mock Tools'], 'state'), 'disabled', 'tools entry off while Mock Mode is off')
    menu.invoke(idx['Mock Mode'])
    T.pump(10)
    T.check(var.get() and mxl_mock_gui._state['page'] is not None, 'Mock page created')
    menu.tk.call(menu.cget('postcommand'))
    T.eq(menu.entrycget(idx['Open Mock Tools'], 'state'), 'normal', 'tools entry on')
    menu.invoke(idx['Open Mock Tools'])
    T.pump(10)
    page = mxl_mock_gui._state['page']
    nb = mxl_tabs._state['nb']
    T.check(str(page.host).startswith(nb.select()), 'the Mock tools page is shown in the Hero Editor window')
    T.check(page.host.winfo_ismapped(), 'Mock page is visible')
    T.check(cw.he_back is not None if hasattr(cw, 'he_back') else True, 'ok')
    menu.invoke(idx['Mock Mode'])
    T.pump(10)
    T.check(mxl_mock_gui._state['page'] is None, 'Mock page removed again')


T.main(globals())
