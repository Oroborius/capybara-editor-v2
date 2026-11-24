"""Geometry and navigation checks for the vanilla character workspace."""
import os
from pathlib import Path
import shutil
import subprocess

import capytest as T

MODE = 'gui'
GEOMETRY = '760x620+0+0'
VARIANTS = {
    '100': {'MXL_UI_SCALE': '1.0'},
    '125': {'MXL_UI_SCALE': '1.25'},
    '150': {'MXL_UI_SCALE': '1.5'},
}
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
    if T.VARIANT != '100':
        T.skip('workspace behavior is covered at 100%')
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
    import mxl_toolbar

    menu = cw.he_menu
    menu.tk.call(menu.cget('postcommand'))
    art_folder = REPO / '.cache/heroed/app'
    if (art_folder / 'Hero Editor.exe').is_file():
        from unittest.mock import patch
        import settings

        with patch('tkinter.filedialog.askdirectory', return_value=str(art_folder)):
            menu.invoke('Hero Editor folder...')
        T.eq(settings.get(V.ART_FOLDER), str(art_folder), 'menu remembers the selected artwork folder')
        T.check(V.picture('person') is not None, 'selected artwork supplies the inventory panel')
    labels = [menu.entrycget(i, 'label') for i in range(menu.index('end') + 1)
              if menu.type(i) in ('command', 'cascade')]
    cascades = [menu.nametowidget(menu.entrycget(i, 'menu')) for i in range(menu.index('end') + 1)
                if menu.type(i) == 'cascade']
    choices = [tuple(sub.entrycget(i, 'label')[2:].strip() for i in range(sub.index('end') + 1))
               for sub in cascades if sub.index('end') is not None
               and all(sub.type(i) == 'command' for i in range(sub.index('end') + 1))]
    for item in app.toolbar._leaves():
        widget = item.w
        if widget.winfo_class() in ('TButton', 'TCheckbutton'):
            label = str(widget.cget('text')).strip()
            T.check(any(entry == label or entry.endswith('] ' + label) for entry in labels),
                    f'{label} is reachable from the HE Menu')
        elif widget.winfo_class() == 'TCombobox':
            T.check(tuple(map(str, widget.cget('values'))) in choices,
                    f'all choices for {widget} are reachable from the HE Menu')
    from mxl_lang import T as tr

    more = menu.nametowidget(menu.entrycget(tr('bar.more', 'More'), 'menu'))
    T.eq([more.entrycget(i, 'label') for i in range(more.index('end') + 1)],
         [label() for label, _command in mxl_toolbar.EXTRA], 'all registered More commands')
    T.eq([button.cget('text') for button in cw.tab_buttons if button.winfo_ismapped()],
         [text for _key, text in V.TABS], 'visible bottom tabs')
    tab = cw.tab_buttons[0].master
    actions, status = tab.master.pack_slaves()[1:]
    shown = sorted((b for b in actions.winfo_children() if b.winfo_class() == 'Button'), key=lambda b: b.winfo_x())
    T.eq([b.cget('text') for b in shown], list(V.ACTIONS), 'file actions (left to right)')
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
        if key in ('stats', 'inventory', 'skills') and (T.G.root.winfo_width(), T.G.root.winfo_height()) == (656, 558):
            viewport, inner = cw.scroll, cw.scroll.inner
            T.check(not any(viewport._shown),
                    f'{key} requests {inner.winfo_reqwidth()}x{inner.winfo_reqheight()} in the '
                    f'{viewport.winfo_width()}x{viewport.winfo_height()} reference viewport')
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
                if view in ('stash', 'cube') and container in cw.extra['containers'].arts:
                    artwork = cw.extra['containers'].arts[container]['bg']
                    T.eq(artwork.winfo_rootx(), cw.inv_canvas_column.winfo_rootx(),
                         f'{view} artwork sits at the left edge of the inventory')
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
    for index, tab_id in enumerate(notebook.tabs()):
        notebook.select(tab_id)
        T.pump(3)
        T.check(notebook.nametowidget(tab_id).winfo_ismapped(), f'Extras page {index + 1} is visible')
        shot(f'extras-{index + 1}', extras)
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


@T.test
def vanilla_inventory_hover_follows_visible_grids():
    if T.VARIANT != '100' or not AVAILABLE:
        T.skip('requires the vanilla fixture at 100%')
    import mxl_vanilla_he as V

    cw = T.chartab()
    V.set_tab(cw, 'inventory')
    T.pump(4)

    def hover(canvas, x, y):
        canvas.event_generate('<Motion>', x=int(x), y=int(y), warp=True)
        T.pump(4)
        return cw.preview.get('1.0', 'end').strip()

    entry = next(iter(cw.ch.inventory()))
    cw.panel.show(None)
    T.check(hover(cw.inv, (entry.it['x'] + .5) * cw.cell, (entry.it['y'] + .5) * cw.cell),
            'bag hover renders item properties without a click')
    T.check(any(w.winfo_class() == 'Toplevel' and w.winfo_ismapped() for w in cw.top.winfo_children()),
            'bag hover opens the controls hint')
    box = next(b for b in cw.visible_boxes() if cw.slot_of(b) in cw.ch.equipped(False))
    x, y, width, height = cw.doll_layout[box]
    cw.panel.show(None)
    T.check(hover(cw.doll, (x + width / 2) * cw.cell, (y + height / 2) * cw.cell),
            'equipped-item hover renders properties without a click')
    cw._show_inventory('stash')
    T.pump(4)
    page = cw.extra['containers']
    x, y, _w, _h, _entry = page.hits['stash'][0]
    cw.panel.show(None)
    T.check(hover(page.canvases['stash'], (x + .5) * page.cell, (y + .5) * page.cell),
            'stash hover renders properties from the visible container')
    cw.preview.configure(state='normal')
    cw.preview.insert('end', '\n' * 120)
    cw.preview.configure(state='disabled')
    cw.preview.yview_moveto(0)
    canvas = page.canvases['stash']
    canvas.focus_force()
    T.pump(2)
    canvas.event_generate('<KeyPress-Down>')
    T.pump(2)
    T.check(cw.preview.yview()[0] > 0, 'Down scrolls the description while hovering an item')
    V.set_tab(cw, 'stats')
    T.pump(4)
    T.check(not any(w.winfo_class() == 'Toplevel' and w.winfo_ismapped() for w in cw.top.winfo_children()),
            'leaving inventory closes the controls hint')


@T.test
def vanilla_inventory_draws_socket_contents():
    if T.VARIANT != '100' or not AVAILABLE:
        T.skip('requires the vanilla fixture at 100%')
    from PIL import ImageTk
    from mxl_format_fix import shown_sockets
    from mxl_gfx import ICON_CELL, socket_positions
    from mxl_tooltip import section_sockets
    from mxl_vanilla_he import description_item
    from types import SimpleNamespace

    cw = T.chartab()
    page = cw.extra['containers']
    item = next(e.it for e in cw.ch.items if e.it.get('socketed'))
    empty = dict(item, socketed=[])
    lines = section_sockets(SimpleNamespace(it=description_item(item), data=cw.data))
    text = ' '.join(part for line in lines for _color, part in line)
    T.check(f'({len(item["socketed"])}/{shown_sockets(item)})' in text,
            'description shows filled and total sockets')
    bg = '#1c2a40'
    layers = cw.icon(item, bg)
    T.check(layers and layers.get(3), 'socket fillers have an image layer')
    before = page._icon(empty, bg)
    after = page._icon(item, bg)
    T.check(before is not None and after is not None, 'both container icons render')
    if before is not None and after is not None:
        T.check(ImageTk.getimage(before).tobytes() != ImageTk.getimage(after).tobytes(),
                'filled sockets change the visible container icon')

    armor = next(e.it for e in cw.ch.items if cw.data.base(e.it['code']).size == (2, 3))
    jewels = [item['socketed'][0]] * 7
    filled = dict(armor, has_sockets=True, sockets=6, socketed=jewels[:6], stats=[])
    overflow = dict(filled, socketed=jewels, stats=[dict(id=194, param=None, value=1)])
    T.eq(socket_positions(2, 3, 7, ICON_CELL), socket_positions(2, 3, 6, ICON_CELL),
         'oversized socket count uses the native six-cell layout')
    small = socket_positions(2, 2, 3, ICON_CELL)
    T.check(len(small) == 3 and all(0 <= x <= ICON_CELL and 0 <= y <= ICON_CELL for x, y in small),
            'three sockets stay inside a two-by-two icon')
    six = ImageTk.getimage(cw.icon(filled, bg)[3])
    seven = ImageTk.getimage(cw.icon(overflow, bg)[3])
    T.check(seven.tobytes() == six.tobytes(), 'only six fillers are painted')
    lines = section_sockets(SimpleNamespace(it=description_item(overflow), data=cw.data))
    text = ' '.join(part for line in lines for _color, part in line)
    T.check('(7/7)' in text and len(overflow['socketed']) == 7, 'description and item retain all seven fillers')


@T.test
def scaled_stats_fit_or_scroll_and_bottom_controls_stay_visible():
    if not AVAILABLE:
        T.skip('no 1.14d game data or sample character')
    import mxl_vanilla_he as V

    root = T.G.root
    cw = T.chartab()
    scale = float(os.environ.get('MXL_UI_SCALE', '1'))
    V.set_tab(cw, 'stats')
    root.geometry('1150x720+0+0')
    T.pump(5)
    form = cw.he_portrait.master
    T.eq((form.winfo_width(), form.winfo_height()), (round(644 * scale), round(440 * scale)),
         'scaled form dimensions')
    T.eq((cw.he_portrait.winfo_width(), cw.he_portrait.winfo_height()),
         (round(209 * scale), round(435 * scale)), 'scaled portrait')
    gap = form.winfo_rootx() - cw.st_tab.winfo_rootx()
    T.check(abs(2 * gap + form.winfo_width() - cw.st_tab.winfo_width()) <= 2, 'wide page centers the form')
    T.check(not cw.scroll._shown[1], 'no horizontal scrollbar in the wide viewport')

    root.geometry('550x460+0+0')
    T.pump(5)
    T.eq(cw.scroll._shown, (True, True), 'small viewport exposes both scrollbars')
    cw.scroll.canvas.xview_moveto(1)
    cw.scroll.canvas.yview_moveto(1)
    T.pump(2)
    field = cw.sv['timestamp']
    canvas = cw.scroll.canvas
    T.check(field.winfo_rootx() + field.winfo_width() <= canvas.winfo_rootx() + canvas.winfo_width()
            and field.winfo_rooty() + field.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height(),
            'the bottom-right field can scroll into view')
    tabbar = cw.tab_buttons[0].master
    actions = tabbar.master.pack_slaves()[1]
    buttons = [b for b in cw.tab_buttons if b.cget('value') in dict(V.TABS)]
    plaques = [b for b in actions.winfo_children() if b.winfo_class() == 'Button']
    for button in buttons + plaques:
        x = button.winfo_rootx() - root.winfo_rootx()
        T.check(button.winfo_ismapped() and x >= 0 and x + button.winfo_width() <= root.winfo_width(),
                f"{button.cget('text')} fits the narrow window")
    T.eq((plaques[0].images[0].width(), plaques[0].images[0].height()),
         (round(96 * scale), round(34 * scale)), 'scaled file actions')


@T.test
def vanilla_popups_survive_crossing_storms():
    if T.VARIANT != '100' or not AVAILABLE:
        T.skip('requires the vanilla fixture at 100%')
    import tkinter as tk
    import mxl_vanilla_he as look

    root = T.G.root
    top = tk.Toplevel(root)
    top.geometry('480x300+80+80')
    owner = tk.Canvas(top, width=400, height=230)
    owner.pack()
    tip = look.item_hint(top)
    owner.bind('<Enter>', lambda _event: tip.show(owner, key='same item'))
    owner.bind('<Leave>', lambda _event: tip.leave(owner))
    menu = tk.Menu(owner, tearoff=False)
    menu.add_command(label='Example', command=lambda: None)
    # Exercise the actual Tcl menu; the harness captures Python's usual tk_popup.
    menu.tk_popup = lambda x, y: menu.tk.call('tk_popup', menu._w, x, y)
    menu.grab_release = lambda: menu.tk.call('grab', 'release', menu._w)

    try:
        T.pump(3)
        owner.event_generate('<Motion>', x=60, y=60, warp=True)
        owner.focus_force()
        owner.event_generate('<Enter>')
        T.settle(.25)
        window = tip.win
        T.check(tip.shown and window.winfo_ismapped(), 'tooltip mapped')
        T.check(not window.overrideredirect(), 'vanilla X11 tooltip is managed')
        for _ in range(25):
            owner.event_generate('<Leave>')
            owner.event_generate('<Enter>')
        owner.event_generate('<Leave>')
        T.settle(.25)
        T.check(tip.shown and tip.win is window and tip.maps == 1, 'crossing storm kept one tooltip')
        T.eq(root.focus_get(), owner, 'tooltip leaves keyboard focus on owner')
        top.event_generate('<Motion>', x=470, y=285, warp=True)
        T.settle(.35)
        T.check(not tip.shown, 'real departure hides tooltip')
        look.popup(menu, T.ev(owner, 60, 60))
        T.pump(3)
        T.check(menu.winfo_ismapped(), 'context menu posted')
        T.eq(menu.tk.call('grab', 'status', menu._w), 'none', 'popup released its grab')
        T.check(menu.winfo_rootx() > owner.winfo_rootx() + 60, 'menu opens beside the click')
        menu.event_generate('<Motion>', x=12, y=9, warp=True)
        T.pump(3)
        menu.activate(0)
        for _ in range(25):
            menu.event_generate('<Leave>', x=12, y=9)
            menu.event_generate('<Enter>', x=12, y=9)
        T.settle(.25)
        T.check(menu.winfo_ismapped() and str(menu.tk.call(menu._w, 'index', 'active')) == '0', 'crossing storm kept menu and selection')
    finally:
        menu.tk.call('tk::MenuUnpost', menu._w)
        tip.destroy()
        top.destroy()


T.main(globals())
