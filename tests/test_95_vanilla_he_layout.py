"""Geometry and navigation checks for the vanilla character workspace."""
import os
from pathlib import Path
import shutil
import subprocess

import capytest as T

MODE = 'gui'
GEOMETRY = '760x620+0+0'
REPO = Path(T.REPO)
GAME = Path(os.environ.get('MXL_TEST_VANILLA_GAME') or REPO / '.cache/ingame/game')
SOURCE = REPO / '.cache/samples/vanilla'
SAVES = Path(T.guard(os.path.join(T.tmp(), 'layout-saves')))
AVAILABLE = (GAME / 'd2data.mpq').is_file() and (SOURCE / 'complex.d2s').is_file()
SAVES.mkdir(exist_ok=True)
if AVAILABLE:
    shutil.copy2(SOURCE / 'complex.d2s', SAVES)
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': str(GAME), 'MXL_SAVE_DIR': str(SAVES)}


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def shot(name, window=None):
    folder = os.environ.get('CAPY_SHOT_DIR')
    if folder:
        root = window if window is not None else T.G.root
        geometry = f'{root.winfo_width()}x{root.winfo_height()}+{root.winfo_rootx()}+{root.winfo_rooty()}'
        subprocess.run(['import', '-window', 'root', '-crop', geometry,
                        str(Path(folder) / f'95-{name}.png')], check=True)


@T.test
def vanilla_workspace_pages_and_tools():
    if not AVAILABLE:
        T.skip('no 1.14d game data or sample character')
    import mxl_tabs
    import mxl_vanilla_he as V

    cw = T.chartab()
    app = T.G.app
    nb = mxl_tabs._state['nb']
    T.eq(nb.select(), str(cw.top), 'character editor opens first')
    T.check(cw.top.winfo_rooty() - nb.winfo_rooty() <= 2, 'no space taken by a host tab strip')
    T.check(nb.identify(12, 8) != 'label', 'host tab labels are hidden')
    T.check(not app.char_combo.master.winfo_ismapped(), 'collector toolbar is hidden')
    T.eq([button.cget('text') for button in cw.tab_buttons if button.winfo_ismapped()],
         [text for _key, text in V.TABS], 'visible bottom tabs')
    tab = cw.tab_buttons[0].master
    actions, status = tab.master.pack_slaves()[1:]
    T.eq([b.cget('text') for b in actions.pack_slaves()], list(V.ACTIONS), 'file actions')
    T.check(tab.winfo_rooty() < actions.winfo_rooty() < status.winfo_rooty(), 'bottom chrome order')

    expectations = {
        'splash': ('Canvas',), 'stats': ('Canvas', 'Entry'),
        'inventory': ('Canvas', 'Text'), 'waypoints': ('Treeview',),
        'skills': ('Canvas', 'Scale'), 'quests': ('Treeview', 'TButton'),
        'merc': ('Treeview', 'TCombobox'), 'introductions': ('Treeview',),
        'options': ('TLabelframe', 'TButton'), 'info': ('Text',), 'about': ('Canvas',),
    }
    for key, _caption in V.TABS:
        V.set_tab(cw, key)
        T.pump(5)
        page = cw.pages[key]
        T.check(page.winfo_ismapped(), f'{key} page is visible')
        types = {w.winfo_class() for w in descendants(page) if w.winfo_ismapped()}
        T.check(set(expectations[key]) <= types, f'{key} controls are visible: {types}')
        T.check(page.winfo_rooty() < tab.winfo_rooty(), f'{key} is above the tab strip')
        if key in ('stats', 'skills') and (T.G.root.winfo_width(), T.G.root.winfo_height()) == (656, 558):
            T.check(not any(cw.scroll._shown), f'{key} fits the reference viewport without scrollbars')
        shot(key)
        if key == 'stats':
            T.check(cw.he_portrait.winfo_rootx() < cw.sv['name'].winfo_rootx(), 'portrait left of the form')
            for field in ('level', 'experience', 'strength', 'checksum', 'map_id', 'timestamp'):
                control = cw.sv[field]
                T.check(control.winfo_rooty() + control.winfo_height() < tab.winfo_rooty(),
                        f'{field} fits above the bottom tabs')
        if key == 'skills':
            icons = {index for _tab, _title, cells in cw.sktree.trees for _y, _x, _sid, index in cells}
            T.check(len(icons) > 10, 'the character skill tiles have distinct icon indices')
            T.check(len(cw.sktree.photos) > 10, 'the game supplies art for the character skill tiles')
        if key == 'inventory':
            T.check(cw.doll.winfo_rooty() < cw.inv.winfo_rooty(), 'equipment above the bag')
            for view in ('stash', 'cube', 'merc', 'person'):
                cw._show_inventory(view)
                T.pump(4)
                T.eq(cw.inv_view.get(), view, 'inventory subpage selected')
                container = {'stash': 'stash', 'cube': 'cube', 'merc': 'belt'}.get(view)
                canvas = cw.extra['containers'].canvases[container] if container else cw.inv
                T.check(canvas.winfo_ismapped(), f'{view} grid is visible')
                if container:
                    shot(f"inventory-{view}")
            box = next(b for b in cw.visible_boxes() if cw.slot_of(b) in cw.ch.equipped(False))
            x, y, width, height = cw.doll_layout[box]
            event = T.ev(cw.doll, (x + width / 2) * cw.cell, (y + height / 2) * cw.cell)
            import mxl_rc_menu
            T.G.menu = None
            mxl_rc_menu._char_menu(cw, cw.doll, event)
            menu = T.G.menu
            T.check(menu is not None, 'item context menu')
            T.eq(cw.preview.tag_cget('tip', 'background'), V.DESCRIPTION, 'item text uses the description surface')
            if menu is not None and os.environ.get('CAPY_SHOT_DIR'):
                from mxl_he_theme import _theme_menu
                _theme_menu(menu)
                # The test harness stubs Python's post method to capture menu commands.
                menu.tk.call(menu._w, 'post', cw.doll.winfo_rootx() + 140, cw.doll.winfo_rooty() + 32)
                T.pump(3)
                T.check(menu.winfo_ismapped(), 'context menu is posted for the screenshot')
                shot('context')
                menu.unpost()

    for name in ('Stash', 'Creator', 'Library', 'Bit editor'):
        cw.he_menu.invoke(mxl_tabs.tab_label(name))
        T.pump(5)
        T.eq(nb.select(), str(mxl_tabs._state['pages'][name]), f'{name} reachable from Menu')
        T.check(app.char_combo.master.winfo_ismapped(), f'{name} workspace toolbar restored')
        T.select_tab('Character')
    V.extras(cw)
    T.pump(5)
    extras = next(w for w in cw.top.winfo_children() if w.winfo_class() == 'Toplevel')
    notebook = next(w for w in extras.winfo_children() if w.winfo_class() == 'TNotebook')
    T.eq(len(notebook.tabs()), 4, 'Extras pages available')
    shot('extras', extras)
    extras.destroy()

    # Verify the new vanilla controls write through the normal Save action.
    from mxl_char import Character
    V.set_tab(cw, 'stats')
    difficulty = (cw.ch.start_location()[0] + 1) % 3
    radios = [control for control in descendants(cw.st_tab)
              if control.winfo_class() == 'Radiobutton']
    radios[difficulty].invoke()
    cw.he_town.current(1)
    cw.he_town.event_generate('<<ComboboxSelected>>')
    fraction = cw.sv['life_frac']
    fraction.delete(0, 'end')
    fraction.insert(0, '42')
    T.check(cw._grey_commit('life_frac'), 'life fraction accepted')
    V.set_tab(cw, 'quests')
    difficulty0, word = next(iter(cw.he_quest_names))
    quest = cw.q_trees[difficulty0]
    quest.tv.selection_set(quest.iids['q', difficulty0, word])
    T.pump(2)
    looking = next(control for control in descendants(cw.q_tab)
                   if control.winfo_class() == 'TRadiobutton' and control.cget('text') == 'Looking For')
    looking.invoke()
    cw.save_progress()
    T.pump(3)
    saved = Character(cw.ch.path, cw.data)
    T.eq(saved.start_location(), (difficulty, 1), 'starting difficulty and town')
    T.eq(saved.stat(7) & 255, 42, 'base life fraction')
    T.eq(saved.quest_word(difficulty0, word), V.QUEST_STAGE_WORDS[1], 'looking for quest')
    T.check(not cw.dirty(), 'saved values reloaded without pending changes')


T.main(globals())
