"""Walk the real editor after first-launch Skip with no game tables or saves."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import capytest as T

MODE = 'gui'
NEEDS = ()
EMPTY_GUI = True
ENV = {'MXL_FIRSTRUN_CHOICE': 'skip', 'MXL_FIRSTRUN_FOLDER': '', 'MXL_THEME': 'd2'}


def walk_pages(widget):
    if isinstance(widget, ttk.Notebook):
        for tab in widget.tabs():
            if str(widget.tab(tab, 'state')) == 'disabled':
                continue
            widget.select(tab)
            T.pump()
            walk_pages(widget.nametowidget(tab))
    else:
        for child in widget.winfo_children():
            if child.winfo_ismapped():
                walk_pages(child)


def post_menu(menu):
    """Post the menu and its cascades through Tcl, bypassing the dialog stubs."""
    menu.tk.call(menu._w, 'post', 1, 1)
    try:
        T.pump()
        for depth, _, state, owner, index in T.menu_entries(menu):
            if depth == 0 and state != 'disabled' and owner.type(index) == 'cascade':
                post_menu(owner.nametowidget(owner.entrycget(index, 'menu')))
    finally:
        menu.unpost()


@T.test
def skip_walks_empty_pages_and_menus():
    import mxl_tabs

    app = T.G.app
    T.check(app.data.empty, 'the app loaded game tables')
    T.check(not app.character_file(), 'the app opened a save')
    log = Path(T.G.user_dir, 'capybara.log').read_text()
    T.check('first launch dialog shown' in log, 'the Skip dialog never opened')
    T.check('no game folder saved' in log, 'the app found a game folder')
    T.eq(T.tab_names(), ['Stash', 'Character', 'Creator', 'Library', 'Bit editor'], 'top-level tabs')
    walk_pages(T.G.root)
    T.check(mxl_tabs.built_owner('Library') is not None, 'Library did not open')

    T.select_tab('Creator')
    creator = mxl_tabs.built_owner('Creator')
    T.check(any('No game folder chosen' in child.cget('text')
                for child in creator.top.winfo_children() if isinstance(child, ttk.Label)),
            'Creator did not explain why its catalog is unavailable')

    T.select_tab('Stash')
    for page in app.notebook.tabs():
        app.notebook.select(page)
        T.pump()
    app.toolbar.post()
    T.check(bool(T.menu_entries(T.G.menu)), 'More menu was empty')
    post_menu(T.G.menu)
    full = tk.Menu(T.G.root, tearoff=False)
    app.toolbar.populate_menu(full)
    post_menu(full)
    for command in ('Game profile', 'New character'):
        before = set(T.G.root.winfo_children())
        T.invoke(full, command)
        opened = [w for w in T.G.root.winfo_children() if w not in before and isinstance(w, tk.Toplevel)]
        T.eq(len(opened), 1, f'{command} dialog')
        for dialog in opened:
            walk_pages(dialog)
            dialog.destroy()
    T.invoke(full, 'Game folder')
    full.destroy()

    T.G.menu = None
    app.canvas.event_generate('<ButtonRelease-3>', x=5, y=5)
    T.pump()
    T.check(bool(T.menu_entries(T.G.menu)), 'empty stash context menu was empty')
    if T.G.menu is not None:
        post_menu(T.G.menu)
        T.invoke(T.G.menu, 'Import item')
        T.invoke(T.G.menu, 'Item Creator')


T.main(globals())
