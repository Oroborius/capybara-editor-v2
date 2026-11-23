"""All the editor's windows as tabs at the top of the main window.

Tiling window managers make a desktop of separate windows (character editor, item creator...)
awkward: every editor window opened its own Toplevel and the editor scattered over the tiles.
Here the same window classes build into pages of a notebook instead: they keep their code and
simply ask host_window() for their "window" - a page that answers the few Toplevel calls the
classes make (title, geometry, protocol, icons, grabs) as friendly no-ops. The stash grid and
its detail panel become the first tab; the Character button opens or focuses the Character tab
and every Creator / Item Editor opens as its own tab (reusing the Creator tab).

The fixed tabs (Stash, Character, Creator, Library, Bit editor) exist from the start: an empty page shows a hint
until its window builds into it. In vanilla, Character is the startup workspace. Its menu opens the tool pages,
which show the notebook strip and the collector's controls.

install() wraps App._build as the FIRST of the install chain, so its wrapper runs after every
other module has built the main window; it then turns the built layout into
[top bar] [tabs: Stash | Character | Creator] [bottom bar] by moving the built body (grid, character
panel, detail panel) into the Stash page (pack in_ - the widgets keep their bindings). The body
stays a child of the root window, so it is also raised above the notebook in the stacking order:
created after it, the notebook would otherwise cover it with its own background (an empty tab).
"""
import os
import tkinter as tk
from tkinter import ttk

_state = {'nb': None, 'pages': {}}


def tab_label(key):
    """Shown text of a tab: the three fixed tabs in the chosen language (the registry key stays English: code
    and tests find the tabs by it), any other tab (an item's name) as it is."""
    from mxl_lang import T
    if key == 'Stash':
        return T('tab.stash', 'Stash')
    if key == 'Character':
        return T('tab.character', 'Character')
    if key == 'Creator':
        return T('tab.creator', 'Creator')
    if key == 'Library':
        return T('tab.library', 'Library')
    if key == 'Bit editor':
        return T('tab.bitedit', 'Bit editor')
    return key


FIXED = ('Stash', 'Character', 'Creator', 'Library', 'Bit editor')


def install(App):
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            _make_host(self)
        except Exception as e:
            print('window tabs disabled:', e)

    App._build = _build


def _make_host(app):
    nb = ttk.Notebook(app.root)
    nb.pack(side='top', fill='both', expand=True)
    _state['nb'] = nb
    _state['app'] = app
    stash = TabPage(nb, 'Stash')
    body = app.canvas.master.master          # the grid + character panel + detail panel frame
    body.pack(in_=stash, fill='both', expand=True)
    try:
        body.lift(nb)                        # a child of the root as well: the notebook was created
    except tk.TclError:                      # after it and would cover it with its own background
        pass
    stash.built = True
    for name in FIXED[1:]:                   # the tabs exist from the start, empty until used
        TabPage(nb, name, fixed_name=True).placeholder()
    nb.select(stash)
    import mxl_vanilla_he
    if mxl_vanilla_he.active():
        app.root.after_idle(lambda: _vanilla_host(app, nb))
    app.root.after_idle(lambda: _autoload_later(app))


def _vanilla_host(app, nb):
    # Save the collector chrome after all App._build wrappers have added their controls.
    root = app.root
    if app.character_file():
        from mxl_vanilla_he import pixels

        width, height = pixels(root, 760, 620)
        root.geometry(f'{min(width, root.winfo_screenwidth() - 24)}x'
                      f'{min(height, root.winfo_screenheight() - 48)}')
    chrome = []
    before_notebook = True
    for widget in root.pack_slaves():
        if widget is nb:
            before_notebook = False
        else:
            layout = widget.pack_info()
            layout.pop('in', None)
            chrome.append((widget, layout, before_notebook))

    character = str(_state['pages']['Character'])

    def update(_event=None):
        editing = nb.select() == character
        nb.configure(style='CharacterHost.TNotebook' if editing else 'TNotebook')
        trailing = nb
        for widget, layout, before in chrome:
            if editing:
                widget.pack_forget()
            elif before:
                widget.pack(before=nb, **layout)
            else:
                widget.pack(after=trailing, **layout)
                trailing = widget

    nb.bind('<<NotebookTabChanged>>', update, add='+')
    update()


def _autoload_later(app):
    """Builds the Character tab after the game archives are warm: the first window would otherwise
    freeze the UI while every MPQ index is read (~1s) on the main thread."""
    import threading

    def build():
        import sys
        old_switch = sys.getswitchinterval()
        # While this thread decodes art (pure Python), the main thread gives up the GIL on every Tk call and then
        # waits a whole switch interval (5 ms) to get it back: a redraw of ~500 Tk calls took 10x longer during a
        # first start. A short interval keeps the window responsive (the thread's own work is barely slower).
        sys.setswitchinterval(min(old_switch, 0.0005))
        try:
            import mxl_d2look_art
            import paths
            import settings
            gd = settings.get('game_dir')
            if gd:
                try:
                    import mxl_d2look
                    mxl_d2look_art.warm(gd, os.path.join(paths.USER_DIR, 'ui_art'),
                                        settings.get(mxl_d2look.THEME_SETTING))
                except Exception as e:
                    print('art warm-up failed:', e)
        finally:
            sys.setswitchinterval(old_switch)
            done.set()

    # The windows are built on the main thread only: the worker just sets an event that a timer of the main thread
    # polls. (It called root.after() itself before: Tk 8.6 / 9 refuse a call from another thread while the main
    # thread is not inside mainloop() - RuntimeError after a 1 s wait - and the fallback then built the Character
    # and Creator windows on the worker thread.)
    done = threading.Event()

    def poll():
        if done.is_set():
            _autoload(app)
            return
        try:
            app.root.after(POLL_MS, poll)
        except tk.TclError:                          # the window is gone
            pass

    threading.Thread(target=build, daemon=True).start()
    poll()


POLL_MS = 30


def _autoload(app):
    """Builds the Character and Creator windows into their tabs by themselves: the tabs are ready
    to use without a click (and they exist from the start either way)."""
    try:
        import mxl_char_gui
        if app.character_file() and os.path.exists(app.character_file()):
            mxl_char_gui.CharacterWindow(app, 'stats')
    except Exception as e:
        print('character tab autoload failed:', e)
    try:
        import mxl_creator_gui
        mxl_creator_gui.CreatorWindow(app)
    except Exception as e:
        print('creator tab autoload failed:', e)
    import mxl_vanilla_he
    if mxl_vanilla_he.active() and focus_existing('Character'):
        return
    try:
        _state['nb'].select(_state['pages']['Stash'])
    except (tk.TclError, KeyError, AttributeError):
        pass


class TabPage(tk.Frame):
    """A tk.Frame standing in for a Toplevel: the window classes build into it unchanged."""

    def __init__(self, nb, name, owner=None, fixed_name=False):
        super().__init__(nb)
        self._key = name                      # registry key, and the tab text when it is empty again
        self._name = name
        self._owner = owner
        self._fixed_name = fixed_name         # auto-loaded tabs keep Stash / Character / Creator
        self._on_close = None
        self.built = False
        nb.add(self, text=tab_label(name))
        _state['pages'][name] = self

    def placeholder(self):
        """A short hint shown in an empty tab (removed again when the window builds into it)."""
        from mxl_lang import T
        if self._key == 'Bit editor':
            text = T('tab.bitedit.empty', 'Bit editor: right-click an item -> "Open in Bit editor".')
        else:
            text = T('tab.empty', '{name}: empty - use the matching button in the toolbar above.',
                     name=tab_label(self._key))
        ttk.Label(self, text='  ' + text + '  ', padding=24).pack(expand=True)
        if self._key == 'Library':                # built on first view (cheap: reads the library index)
            self.bind_all_once()

    def bind_all_once(self):
        def on_map(_e=None):
            if not self.built and _state.get('app') is not None:
                try:
                    import mxl_itemlib
                    mxl_itemlib.open_library(_state['app'])
                except Exception as e:
                    print('library tab failed:', e)
        tk.Frame.bind(self, '<Map>', on_map)

    def clear(self):
        """Removes everything built into the page (a hint or a previous window's widgets)."""
        for w in self.winfo_children():
            w.destroy()

    # ---- the Toplevel calls the window classes use
    def title(self, text=None):
        if text and not self._fixed_name:
            self._name = text
            try:
                self.master.tab(self, text=text)
            except tk.TclError:
                pass

    wm_title = title

    def geometry(self, spec=None):
        return ''

    wm_geometry = geometry

    def minsize(self, *a, **k):
        pass

    def resizable(self, *a, **k):
        pass

    def protocol(self, name=None, func=None):
        if name == 'WM_DELETE_WINDOW':
            self._on_close = func
            return
        return None

    wm_protocol = protocol

    def iconbitmap(self, *a, **k):
        pass

    wm_iconbitmap = iconbitmap

    def iconphoto(self, *a, **k):
        pass

    def transient(self, *a, **k):
        pass

    def grab_set(self, *a, **k):
        pass

    def grab_release(self, *a, **k):
        pass

    def state(self, *a, **k):
        return 'normal'

    def deiconify(self, *a, **k):
        pass

    def lift(self, *a, **k):
        try:
            self.master.select(self)
        except tk.TclError:
            pass

    def focus_set(self, *a, **k):
        # a page is never "the focused window": leave the focus wherever it is
        pass

    focus_force = focus_set

    def bind(self, seq=None, func=None, add=None):
        # window-level key bindings must be on the root window: they fire for whatever
        # widget has the focus (the pages themselves never take it)
        if seq is not None and seq.startswith('<'):
            return self.winfo_toplevel().bind(seq, func, add)
        return super().bind(seq, func, add)

    def destroy(self):
        """The editor window was closed (Close button / window's own close): its widgets go away
        and the tab itself stays, empty again with its hint - the tabs never disappear."""
        try:
            self.clear()
            self.built = False
            self._name = self._key
            try:
                self.master.tab(self, text=tab_label(self._key))
            except tk.TclError:
                pass
            self.placeholder()
            stash = _state['pages'].get('Stash')
            if stash is not None and stash is not self and stash.built:
                try:
                    self.master.select(stash)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass


def host_window(app, name, owner=None, replace=False):
    """The "Toplevel" of a new editor window: a notebook page when the tabs are installed,
    a real Toplevel otherwise (tabs not enabled / host not built yet).
    Returns None when the page is already showing a built window (the caller just focuses it,
    see focus_existing). replace=True rebuilds into the same tab, keeping its position."""
    nb = _state['nb']
    if nb is None:
        return tk.Toplevel(app.root)
    page = _state['pages'].get(name)
    if page is not None:
        if not replace and page.built:
            try:
                nb.select(page)
            except tk.TclError:
                pass
            return None
        page.clear()                          # an empty hint or the previous window's widgets
        if owner is not None:
            page._owner = owner               # the tab exists from the start with owner None
    else:
        page = TabPage(nb, name, owner)
    page.built = True
    try:
        nb.select(page)
    except tk.TclError:
        pass
    return page


def focus_existing(name):
    """True when a tab with this name is already showing its window: it is just selected."""
    page = _state['pages'].get(name)
    if page is None or not page.built:
        return False
    try:
        _state['nb'].select(page)
    except tk.TclError:
        pass
    return True


def built_owner(name):
    """The window object currently built into the named tab, or None when the tab is empty."""
    page = _state['pages'].get(name)
    if page is None or not page.built:
        return None
    return page._owner
