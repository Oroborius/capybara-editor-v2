"""The Character tab follows the character dropdown of the main window (personal edit).

The frozen app's select_character only moves the dropdown: an already-built Character tab keeps
showing the previous character's data until it is closed and reopened by hand. This patch makes
every select_character rebuild that tab through the normal CharacterWindow constructor, which now
rebuilds its tab itself when a different character was picked. Unsaved edits win: a window with
unsaved changes is left alone (its status bar says so).

install() is called from mxl_free.install(), right after the other personal-edit patches. Every
step is wrapped so an app build without the expected names cannot be broken by this module.

The dropdown's own handler calls open_view(), not select_character(), so that is the one that has
to drag the Character tab along; select_character is wrapped as well (the startup path)."""
import os


def install():
    try:
        import mxl_gui
        app_cls = mxl_gui.App
    except Exception as err:
        print('mxl_follow: mxl_gui.App unavailable:', err)
        return
    if getattr(app_cls, '_capy_follow', False):
        return
    for name in ('open_view', 'select_character'):
        original = getattr(app_cls, name, None)
        if original is None:
            continue

        def wrap(original):
            def patched(self, *a, **kw):
                r = original(self, *a, **kw)
                _follow(self)
                return r
            patched.original = original
            return patched

        setattr(app_cls, name, wrap(original))
    app_cls._capy_follow = True
    print('mxl_follow: the Character tab follows the character dropdown')


def _follow(app):
    """Rebuild the Character tab when it still shows a character other than the dropdown's."""
    try:
        import mxl_tabs
        import mxl_char_gui
        owner = mxl_tabs.built_owner('Character')
        if owner is None or getattr(owner, 'ch', None) is None or owner.dirty():
            return
        path = app.character_file()
        if not path or not os.path.exists(path):
            return
        if os.path.abspath(owner.ch.path) == os.path.abspath(path):
            return
        page = getattr(owner, 'tab', None)               # stay on the page the user was on
        sub = page.get() if page is not None and str(page.get()) in getattr(owner, 'pages', {}) else 'stats'
        mxl_char_gui.CharacterWindow(app, sub)           # rebuilds into the tab with the new data
    except Exception as err:
        print('mxl_follow: character tab refresh failed:', err)
