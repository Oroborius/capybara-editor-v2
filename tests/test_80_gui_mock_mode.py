"""Mock Mode in the window (vanilla profile): the character Menu’s "Mock Mode" command turns
the Mock tab on / off and is kept in the settings; the analyzer lists colour-coded checks and the summary of the
loaded mock per weapon switch; the generator's fields are prefilled, an edited field reaches the plan, a bad value
is reported next to its field, the summary panel follows the switch selector; Generate writes a NEW save (no
question) that the analyzer scores without a bad check; the item crafter adds a
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


def _rows(tree):
    """(section, label, value, tag) of every row of a summary tree."""
    out = []
    for h in tree.get_children():
        sec = tree.item(h)['text']
        for i in tree.get_children(h):
            r = tree.item(i)
            out.append((sec, r['text'].strip('✔!✖ '), str(r['values'][0]) if r['values'] else '',
                        r['tags'][0] if r['tags'] else ''))
    return out


def _shot(name, geo):
    shot = os.environ.get('CAPY_SHOT_DIR')
    if not shot:
        return
    G.root.geometry(geo)
    T.pump(30, 0.03)
    w, h = (int(x) for x in geo.split('+')[0].split('x'))
    x, y = G.root.winfo_rootx(), G.root.winfo_rooty()
    os.system(f'import -window root -crop {w}x{h}+{x}+{y} {os.path.join(shot, name)} 2>/dev/null')


@T.test
def toggle_tab_analyzer_generator_crafter():
    if _S is None:
        T.skip('no vanilla install / mock samples')
    import mxl_mock_gui as MG
    import mxl_mock as M
    import settings
    cw = T.chartab()
    T.check(cw.top.winfo_ismapped(), 'Character is the landing view')
    T.check(not G.app.char_combo.master.winfo_ismapped(), 'collector toolbar is hidden on Character')
    T.check('Mock' not in _tab_names(), 'no Mock tab while off')
    cw.he_menu.invoke('Mock Mode')
    T.pump(10, 0.02)
    T.check('Mock' in _tab_names(), 'Mock tab after the toggle')
    T.eq(settings.get('mock_mode'), True, 'setting kept')
    page = MG._state['page']
    T.eq([page.nb.tab(t, 'text') for t in page.nb.tabs()], ['Generator', 'Analyzer', 'Item crafter'], 'sub tabs')
    # ---- analyzer: checks + summary of the loaded character, per switch
    G.app.select_character('clone-90', G.app.view.get())
    T.pump(10, 0.02)
    a = page.analyze()
    T.check(a is not None, 'analysis of the loaded character')
    rows = _rows(page.ana.tree)
    T.check(any(r[0] == 'Checks' and 'Mana' in r[1] and '1438452' in r[2] for r in rows), 'mana row of clone-90')
    page.ana.bo.set(False)                              # BO not cast: the saved mana
    page.ana.render()
    T.check(any(r[1] == 'Mana' and r[2].startswith('1438452') for r in _rows(page.ana.tree)), 'BO cast off')
    page.ana.bo.set(True)
    page.ana.render()
    T.check(any(r[3] == 'good' for r in rows), 'colour tags')
    T.check(any(r[0] == 'Auras' and r[1] == 'Holy Freeze' and 'source(s)' in r[2] for r in rows), 'aura sources')
    side0 = page.ana.side.get()
    other = 'A' if side0 == 'B' else 'B'
    page.ana.side.set(other)
    page.ana.render()
    rows2 = _rows(page.ana.tree)
    m0 = next(r[2] for r in rows if r[1] == 'Mana' and r[0] == 'Checks')
    m1 = next(r[2] for r in rows2 if r[1] == 'Mana' and r[0] == 'Checks')
    T.check(m0 != m1, f'switch selector: side {other} has its own mana ({m0[:12]} / {m1[:12]})')
    # ---- generator: every field prefilled, the summary of the plan on the right
    pre = M.prefill('mock_high')
    T.eq({k: page.ov[k].get() for k in ('thorns', 'ias', 'res_cold', 'hf_target')},
         {k: str(pre[k]) for k in ('thorns', 'ias', 'res_cold', 'hf_target')}, 'fields prefilled with the preset')
    T.eq(page.ov['dopplezon'].get(), True, 'check box prefilled')
    T.eq(page.err['hf_level'].cget('text'), '7 source(s)', 'source count next to the Holy Freeze field')
    srows = _rows(page.summary.tree)
    T.check({'Caps', 'Auras', 'Defenses', 'Speeds', 'Damage', 'Clone profile'} <= {r[0] for r in srows},
            'summary sections')
    T.check(any(r[0] == 'Clone profile' and r[3] == 'good' for r in srows), 'no clone category missing')
    # an edited field reaches plan() and the summary
    page.ov['ias'].set('-121')
    T.check(page.check() is not None, 'Check with an edited field')
    T.eq(page.over, {'ias': -121}, 'only the edited field is passed on')
    T.check(any(r[1] == 'IAS' and r[2].startswith('-121') for r in _rows(page.summary.tree)), 'IAS -121 in the summary')
    # a bad value: the message sits next to its field, nothing is generated
    page.ov['position'].set('Host')                     # a solved field follows the edit (DTM 500 on a Host)
    T.check(page.check() is not None, 'Check with Host')
    T.eq((page.ov['dtm'].get(), page.ov['ias'].get()), ('500', '-121'), 'DTM re-solved, the edited IAS kept')
    page.ov['position'].set('LPJ')
    page.ov['level'].set('140')
    T.check(page.check() is None, 'level 140 refused')
    T.check('99-127' in page.err['level'].cget('text'), f"message next to the field: {page.err['level'].cget('text')}")
    page.reset_fields()
    T.eq(page.err['level'].cget('text'), '', 'reset clears the message')
    # the switch selector: a balance switch shows its stun only on side A
    page.preset.set(M.PRESETS['balance_switch']['label'])
    page._preset_changed()
    T.pump(5, 0.02)
    page.summary.side.set('A')
    page.summary.render()
    ra = _rows(page.summary.tree)
    page.summary.side.set('B')
    page.summary.render()
    rb = _rows(page.summary.tree)
    sa = next(r[2] for r in ra if r[1] == 'Stun')
    sb = next(r[2] for r in rb if r[1] == 'Stun')
    T.check('att' in sa and sb.startswith('none'), f'stun on side A only ({sa} / {sb})')
    T.check(next(r[2] for r in ra if r[1] == 'Mana') != next(r[2] for r in rb if r[1] == 'Mana'), 'side B mana')
    import mxl_tabs
    mxl_tabs._state['nb'].select(page.host)
    _shot('v80-800x600.png', '800x600+0+0')
    _shot('v80-1280x800.png', '1280x800+0+0')
    G.root.geometry('1180x680+0+0')
    T.pump(10, 0.02)
    T.check(page.gen_btn.winfo_width() > 40, 'Generate button shown')
    # ---- Generate: no question, a NEW file, the analyzer has no bad check
    page.preset.set(M.PRESETS['funky']['label'])
    page._preset_changed()
    page.name.set('GuiMock')
    before = set(os.listdir(_S))
    G.boxes.clear()
    T.check(page.generate() is not None, 'generated')
    T.pump(10, 0.02)
    new = set(os.listdir(_S)) - before
    T.eq(sorted(new), ['GuiMock.d2s'], 'new file')
    T.eq([x for x in G.boxes if x[0] in ('askyesno', 'showerror')], [], 'no dialog')
    T.check('GuiMock.d2s' in page.status.cget('text'), 'written: shown in the status line')
    a = page.analyze()
    T.eq([c for c in a['checks'] if c[3] == 'bad'], [], 'generated funky: no bad check')
    T.check(a['values']['band']['funky'], 'generated funky: on the funky zero')
    page.generate()                                     # same name again: a free name, nothing overwritten
    T.eq(sorted(set(os.listdir(_S)) - before), ['GuiMock.d2s', 'GuiMocka.d2s'], 'second file, free name')
    page.name.set('9')
    T.check(page.generate() is None and 'Name' in page.status.cget('text'), 'bad name: message, no file')
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
    T.chartab().he_menu.invoke('Mock Mode')
    T.pump(10, 0.02)
    T.check('Mock' not in _tab_names(), 'Mock tab gone')
    T.eq(settings.get('mock_mode'), False, 'setting kept off')


T.main(globals())
