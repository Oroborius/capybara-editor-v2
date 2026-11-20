"""Mock Mode in the window (vanilla profile): the "Mock Mode" toggle sits at the right end of the top bar, turns
the Mock tab on / off and is kept in the settings; the analyzer lists colour-coded checks of the loaded mock;
Generate writes a NEW save (asked first) that the analyzer scores without a bad check; the item crafter adds a
charm to the loaded character. Copies of the mock samples only; skipped without the vanilla install / samples
(see test 75). The Median XL side (no toggle) is test 81."""
import glob
import os
import shutil

import capytest as T

MODE = 'gui'
G = T.G
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')


def _saves():
    cands = [os.path.join(T.REPO, '.cache', 'samples', 'mock')]
    if os.sep + '.claude' + os.sep + 'worktrees' + os.sep in T.REPO:
        cands.append(os.path.join(T.REPO.split(os.sep + '.claude' + os.sep)[0], '.cache', 'samples', 'mock'))
    m = next((c for c in cands if glob.glob(os.path.join(c, '*.d2s'))), None)
    if not m or not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        return None
    dst = T.guard(os.path.join(T.tmp(), 'mocksaves'), 'mock save copies')
    if not os.path.isdir(dst):
        os.makedirs(dst)
        for f in ('clone-90.d2s', 'clones/clone-41.d2s', 'clones/clone-35.d2s', 'clones/clone-55.d2s'):
            shutil.copy(os.path.join(m, f), dst)
    return dst


_S = _saves()
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': GAME, **({'MXL_SAVE_DIR': _S} if _S else {})}
WAIT_TABS = True


def _tab_names():
    import mxl_tabs
    nb = mxl_tabs._state['nb']
    return [nb.tab(t, 'text') for t in nb.tabs()]


@T.test
def toggle_tab_analyzer_generator_crafter():
    if _S is None:
        T.skip('no vanilla install / mock samples')
    import mxl_mock_gui as MG
    import mxl_mock as M
    import settings
    b = MG._state['button']
    T.check(b is not None, 'Mock Mode toggle built')
    T.eq(b.cget('text'), 'Mock Mode', 'toggle text')
    bar = G.app.char_combo.master
    T.pump(10, 0.02)
    right = max((w for w in bar.pack_slaves() if w.winfo_ismapped()), key=lambda w: w.winfo_x())
    T.check(right is b, 'the toggle is the right-most item of the top bar')
    T.check('Mock' not in _tab_names(), 'no Mock tab while off')
    b.invoke()
    T.pump(10, 0.02)
    T.check('Mock' in _tab_names(), 'Mock tab after the toggle')
    T.eq(settings.get('mock_mode'), True, 'setting kept')
    page = MG._state['page']
    G.app.select_character('clone-90', G.app.view.get())
    T.pump(10, 0.02)
    a = page.analyze()
    T.check(a is not None, 'analysis of the loaded character')
    rows = [page.tree.item(i) for i in page.tree.get_children()]
    T.check(any('Mana' in r['text'] and '1438462' in r['values'][0] for r in rows), 'mana row of clone-90')
    T.check(any(r['tags'] and r['tags'][0] == 'good' for r in rows), 'colour tags')
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        import mxl_tabs
        mxl_tabs._state['nb'].select(page.host)
        T.pump(10, 0.02)
        os.system(f'import -window root {os.path.join(shot, "v80.png")} 2>/dev/null')
    # ---- Generate: asked first, a NEW file, the analyzer has no bad check
    page.preset.set(M.PRESETS['funky']['label'])
    page._preset_changed()
    page.name.set('GuiMock')
    before = set(os.listdir(_S))
    G.boxes.clear()
    page.generate()
    T.pump(10, 0.02)
    new = set(os.listdir(_S)) - before
    T.eq(sorted(new), ['GuiMock.d2s'], 'new file')
    T.check(any(x[0] == 'askyesno' for x in G.boxes), 'asked before writing')
    a = page.analyze()
    T.eq([c for c in a['checks'] if c[3] == 'bad'], [], 'generated funky: no bad check')
    T.check(a['values']['band']['funky'], 'generated funky: on the funky zero')
    page.generate()                                     # same name again: a free name, nothing overwritten
    T.eq(sorted(set(os.listdir(_S)) - before), ['GuiMock.d2s', 'GuiMocka.d2s'], 'second file, free name')
    # ---- crafter: a charm into the loaded character
    G.app.select_character('GuiMock', G.app.view.get())
    T.pump(10, 0.02)
    import mxl_char
    n0 = len(mxl_char.Character(os.path.join(_S, 'GuiMock.d2s'), G.app.data).items)
    page.lines.delete('1.0', 'end')
    page.lines.insert('end', 'aura thorns 5\nmana 1\n')
    G.boxes.clear()
    page.craft()
    T.pump(5, 0.02)
    T.check(any(x[0] == 'showerror' for x in G.boxes), 'full 40-charm inventory: an error, nothing added')
    T.eq(len(mxl_char.Character(os.path.join(_S, 'GuiMock.d2s'), G.app.data).items), n0, 'item count')
    room = None
    for f in sorted(os.listdir(_S)):
        c = mxl_char.Character(os.path.join(_S, f), G.app.data)
        if M.free_cell(c, G.app.data):
            room = (os.path.splitext(f)[0], len(c.items))
            break
    T.check(room is not None, 'a sample with a free inventory cell')
    if room:
        G.app.select_character(room[0], G.app.view.get())
        T.pump(10, 0.02)
        G.boxes.clear()
        page.craft()
        T.pump(5, 0.02)
        T.eq([x for x in G.boxes if x[0] == 'showerror'], [], 'no error')
        ch = mxl_char.Character(os.path.join(_S, room[0] + '.d2s'), G.app.data)
        T.eq(len(ch.items), room[1] + 1, 'the crafted charm is in the file')
        st = [(x['id'], x.get('param'), x['value']) for x in ch.items[-1].it['stats']]
        T.eq(st, [(151, 103, 5), (9, None, 1)], 'its stat lines, in the given order')
    G.app.select_character('clone-41', G.app.view.get())
    T.pump(10, 0.02)
    # ---- off again
    b.invoke()
    T.pump(10, 0.02)
    T.check('Mock' not in _tab_names(), 'Mock tab gone')
    T.eq(settings.get('mock_mode'), False, 'setting kept off')


T.main(globals())
