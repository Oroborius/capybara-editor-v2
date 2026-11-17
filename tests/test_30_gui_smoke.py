"""GUI smoke test: the application starts in both looks ('d2' dark Diablo, 'he' Hero Editor light) at 1280x720 and
at 800x600, every tab and page opens, nothing is reported on stderr or in capybara.log (the harness checks that
after every test and for the start-up), the status bar keeps its height, the toolbar overflows into "More".

Nothing is written here: the last test compares the save folder with the pristine sample."""
import os

import capytest as T

MODE = 'gui'
VARIANTS = {
    'd2-1280x720': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0'},
    'he-1280x720': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '1280x720+0+0'},
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
    'he-800x600': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0'},
}
G = T.G
WANT = tuple(int(v) for v in (os.environ.get('CAPY_GEOMETRY') or '1180x680+0+0').split('+')[0].split('x'))


def inside_root(widget, what, slack=2):
    """The widget lies inside the window (nothing pushed out at this size)."""
    root = G.root
    x, y = widget.winfo_rootx() - root.winfo_rootx(), widget.winfo_rooty() - root.winfo_rooty()
    T.check(widget.winfo_ismapped(), f'{what}: not shown')
    T.check(x >= -slack and y >= -slack and x + widget.winfo_width() <= root.winfo_width() + slack
            and y + widget.winfo_height() <= root.winfo_height() + slack,
            f'{what}: {widget.winfo_width()}x{widget.winfo_height()} at ({x}, {y}) does not fit the {root.winfo_width()}x{root.winfo_height()} window')


@T.test
def starts_in_the_requested_look_and_size():
    import mxl_d2_theme
    T.eq(mxl_d2_theme.theme(), os.environ.get('MXL_THEME'), 'look')
    T.eq(mxl_d2_theme.dark(), os.environ.get('MXL_THEME') == 'd2', 'dark')
    T.eq((G.root.winfo_width(), G.root.winfo_height()), WANT, 'window size')
    T.eq(T.tab_names(), ['Stash', 'Character', 'Creator'], 'tabs')
    T.check('Capybara' in G.root.title(), f'window title {G.root.title()!r}')
    T.check(G.app.path and os.path.realpath(G.app.path).startswith(os.path.realpath(G.save_dir)), f'open stash {G.app.path!r} is not in the test copy')
    T.check(len(G.app.items) > 100, f'{len(G.app.items)} stash items loaded')
    T.check(G.app.inventory.ch is not None, f'no character in the panel: {G.app.inventory.error!r}')


@T.test
def stash_tab_and_its_pages():
    app = G.app
    T.select_tab('Stash')
    T.settle(0.3)
    inside_root(app.canvas, 'stash grid')
    inside_root(app.status, 'status bar')
    T.check(app.cell >= 10, f'stash cell size {app.cell}')
    for page in range(len(app.notebook.tabs())):
        app.notebook.select(page)
        T.pump(3)
        T.eq(app.page(), page, 'stash page shown')
    app.notebook.select(0)
    T.pump(3)
    it = next(i for i in app.items if i['page'] == 0)
    e = T.stash_ev(0, it['x'], it['y'])
    for name in ('<Button-1>', '<ButtonRelease-1>'):
        app.canvas.event_generate(name, x=e.x, y=e.y, rootx=e.x_root, rooty=e.y_root)
        T.pump(3)
    T.check(app.selected is not None and (app.selected['x'], app.selected['y']) == (it['x'], it['y']), 'a click on a stash item did not select it')
    app.canvas.event_generate('<Motion>', x=e.x, y=e.y, rootx=e.x_root, rooty=e.y_root)
    T.settle(0.3)
    app.selected = None
    app.draw_grid()
    T.pump()


@T.test
def character_panel_of_the_stash_tab():
    inv = G.app.inventory
    T.select_tab('Stash')
    T.settle(0.2)
    T.check(inv.doll.winfo_ismapped() and inv.canvas.winfo_ismapped(), 'equipment / inventory panel not shown')
    T.check(inv.cell >= 8, f'panel cell size {inv.cell}')
    if inv.ch.merc_hired:
        inv.merc.set(True)
        inv.on_view()
        T.pump(4)
        T.check(len(inv.visible_boxes()) >= 3, f'mercenary slots shown: {inv.visible_boxes()}')
        inv.merc.set(False)
        inv.on_view()
    slot = next(iter(inv.ch.equipped(False)))
    e = T.panel_ev(('slot', slot))
    inv.on_press(e)
    T.pump(3)
    T.check(inv.selected is not None and inv.selected.it['equipped'] == slot, 'a click on a worn item did not select it')
    inv.drag = None
    inv.deselect()
    inv.show_detail()
    T.pump()


@T.test
def character_tab_every_page():
    cw = T.chartab()
    T.check(cw is not None, 'no Character tab')
    T.select_tab('Character')
    T.settle(0.3)
    T.eq(sorted(cw.pages), sorted(['stats', 'inventory', 'skills', 'waypoints', 'quests']), 'pages of the Character tab')
    for key in ('stats', 'inventory', 'skills', 'waypoints', 'quests'):
        cw.tab.set(key)
        cw.show_tab()
        T.settle(0.25)
        T.check(cw.pages[key].winfo_ismapped(), f'page {key!r} not shown')
        T.check(cw.pages[key].winfo_width() > 100 and cw.pages[key].winfo_height() > 50, f'page {key!r}: {cw.pages[key].winfo_width()}x{cw.pages[key].winfo_height()}')
    T.check(not cw.dirty(), 'the Character tab reports unsaved changes after only looking at its pages')
    cw.tab.set('inventory')
    cw.show_tab()
    T.pump(4)
    cw.merc.set(True)
    cw.on_view()
    T.pump(4)
    cw.merc.set(False)
    cw.on_view()
    cw.tab.set('stats')
    cw.show_tab()
    T.pump(4)


@T.test
def creator_tab_every_quality():
    import mxl_creator_gui as CG
    import mxl_tabs
    w = mxl_tabs.built_owner('Creator')
    T.check(w is not None, 'no Creator tab')
    T.select_tab('Creator')
    T.settle(0.3)
    inside_root(w.listbox, 'creator list')
    for label, key in CG.qualities():
        w.quality.set(label)
        w.on_quality()
        T.pump(2)
        T.check(len(w.entries) > 0, f'{key}: empty list')
        i = min(12, len(w.entries) - 1)
        w.listbox.selection_clear(0, 'end')
        w.listbox.selection_set(i)
        w.listbox.event_generate('<<ListboxSelect>>')
        T.settle(0.15)
        T.check(w.spec is not None, f'{key}: picking {w.entries[i][0]!r} built no item')
        if w.spec is not None:
            T.check(w.refresh() is not None, f'{key}: no preview for {w.entries[i][0]!r} ({w.status.cget("text")!r})')
    inside_root(w.btn_ok, 'Create button')
    w.quality.set(CG.qualities()[0][0])
    w.on_quality()
    T.pump()


@T.test
def item_editor_and_item_stats_tabs():
    import mxl_creator_gui as CG
    import mxl_he_stats as H
    import mxl_tabs
    app = G.app
    T.select_tab('Stash')
    it = next(i for i in app.items if i.get('quality') in ('unique', 'rare') and len(i.get('stats') or ()) >= 3)
    app.notebook.select(it['page'])
    app.selected = it
    app.draw_grid()
    app.set_detail(it)
    T.pump(4)
    w = H.open_item_stats(app)
    T.settle(0.3)
    T.check(w is not None and mxl_tabs.built_owner(H.TAB_KEY) is w, 'the Item stats tab did not open')
    T.eq(len(T.tab_names()), 4, f'tabs with Item stats open: {T.tab_names()}')
    T.check(sum(1 for r in w.rows if r['kind'] == 'slot' and r['s'] is not None) >= 3, 'Item stats lists fewer stats than the item has')
    inside_root(w.cv, 'Item stats list')
    w.select(w._find_slot('stats', 0))
    w.open_picker()
    T.pump(4)
    w.close()
    T.pump(4)
    T.check(mxl_tabs.built_owner(H.TAB_KEY) is None, 'the Item stats tab still holds its window after Close')
    T.eq(len(T.tab_names()), 4, 'tabs after closing Item stats (the tab stays, empty)')
    app.selected = next(i for i in app.items if (i['page'], i['x'], i['y']) == (it['page'], it['x'], it['y']))
    CG.edit_selected(app)
    T.settle(0.4)
    ed = mxl_tabs.built_owner('Creator')
    T.check(ed is not None and ed.edit_item is not None and ed.spec is not None, 'the Item Editor did not open on the selected item')
    T.check(ed.refresh() is not None, 'the Item Editor shows no preview')
    CG.CreatorWindow(app)                                # back to the plain Creator
    T.pump(8)
    app.notebook.select(0)
    T.select_tab('Stash')


@T.test
def status_bar_keeps_its_height():
    """A multi-line status text (item names have several lines) must not make the bar grow: the tabs above would
    lose height and every grid would be fitted again."""
    app = G.app
    T.select_tab('Stash')
    app.status.configure(text='one line')
    T.settle(0.2)
    h0, body0 = app.status.winfo_height(), app.canvas.winfo_height()
    cell0 = app.cell
    app.status.configure(text='Mystic Orb\nfirst effect line\nsecond effect line\nthird')
    T.settle(0.3)
    T.eq(app.status.winfo_height(), h0, 'status bar height after a four-line text')
    T.check('\n' not in str(app.status.cget('text')), f'status text still has line breaks: {app.status.cget("text")!r}')
    T.check('Mystic Orb' in str(app.status.cget('text')) and 'third' in str(app.status.cget('text')), 'lines of the text were lost')
    T.eq((app.canvas.winfo_height(), app.cell), (body0, cell0), '(stash grid height, cell size) after the four-line text')
    app.status.config(text='a\nb')
    T.settle(0.1)
    T.eq(app.status.winfo_height(), h0, 'status bar height after status.config(text=...)')
    app.show_status()


@T.test
def toolbar_overflow_menu_at_800px():
    """At 800 px the top bar cannot show everything: the rest goes into the "More" menu; nothing is cut off."""
    app, root = G.app, G.root
    tb = app.toolbar
    T.select_tab('Stash')
    geo = root.geometry()
    try:
        root.geometry('800x600+0+0')
        T.settle(0.5)
        T.eq(root.winfo_width(), 800, 'window width')
        T.check(len(tb.hidden) > 0, 'nothing moved into the overflow menu at 800 px')
        T.check(tb.more.winfo_ismapped(), 'the "More" button is not shown at 800 px')
        T.check(tb._needed(tb.hidden) <= tb.bar.winfo_width(), f'the bar needs {tb._needed(tb.hidden)} px, has {tb.bar.winfo_width()}')
        inside_root(tb.more, '"More" button')
        for item in tb._leaves():
            if item not in tb.hidden and item.w.winfo_ismapped():
                inside_root(item.w, f'toolbar item {item.w.winfo_class()}')
        G.menu = None
        tb.post()
        T.pump(3)
        labels = T.menu_labels(G.menu)
        T.check(G.menu is not None and len(labels) > 0, 'the overflow menu is empty')
        hidden_buttons = [str(i.w.cget('text')).strip() for i in tb._leaves() if i in tb.hidden and i.w.winfo_class() == 'TButton']
        for text in hidden_buttons:
            T.check(text in labels, f'hidden button {text!r} is not in the overflow menu {labels}')
        n800 = len(tb.hidden)
        root.geometry('1280x720+0+0')
        T.settle(0.5)
        T.check(len(tb.hidden) < n800, f'{len(tb.hidden)} items still hidden at 1280 px ({n800} at 800 px)')
        T.eq(tb.more.winfo_ismapped(), bool(tb.hidden), '"More" shown exactly when something is hidden')
    finally:
        root.geometry(geo)
        T.settle(0.4)


@T.test
def narrow_window_keeps_working():
    """Down to 700x500 (a little above the measured minimum of the Stash tab) nothing raises."""
    root = G.root
    geo = root.geometry()
    try:
        for size in ('700x500+0+0', '1000x640+0+0'):
            root.geometry(size)
            T.settle(0.4)
            for name in ('Stash', 'Character', 'Creator'):
                T.select_tab(name)
                T.settle(0.15)
            T.select_tab('Stash')
            T.check(G.app.cell >= 8, f'{size}: stash cell size {G.app.cell}')
    finally:
        root.geometry(geo)
        T.settle(0.4)
        T.select_tab('Stash')


@T.test
def nothing_was_written():
    """Looking at every tab must not touch the save files."""
    src = T.SRC_SAVES
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if os.path.isfile(p):
            T.check(T.read(os.path.join(G.save_dir, name)) == T.read(p), f'{name} changed')
    extra = sorted(set(os.listdir(G.save_dir)) - set(os.listdir(src)))
    T.eq([n for n in extra if '.bak' in n or n.endswith('.tmp')], [], 'backup / temporary files written')


T.main(globals())
