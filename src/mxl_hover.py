"""Item stats on hover: the detail panel follows the item under the mouse, instantly.

The stats panel at the right of the main window (and the preview panel of the character window)
used to update only when an item was clicked. It now follows the mouse with no delay at all:
hovering an item shows its stats the moment the cursor reaches it, moving onto empty space falls
back to the selected item. Clicks keep working exactly as before (the hover bindings are added
next to the existing ones). The work per motion event is one cheap grid lookup; the panel is only
re-rendered when the item under the cursor actually changed.
"""
import types

DELAY_MS = 0


def install(App):
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            _install_stash_hover(self)
        except Exception as e:
            print('item hover (stash) disabled:', e)
        try:
            _one_line_status(self)
        except Exception as e:
            print('one-line status bar disabled:', e)

    App._build = _build


def _one_line_status(app):
    """The status bar stays one line high. Hovering an item whose name has several lines (mystic orbs,
    caches, relics...) put those lines into the bar: it grew upwards, the tab above lost height and the
    grids were re-fitted (mxl_fit) at every such hover. Line breaks become ' / ' before the text is set."""
    st = app.status
    o_configure = st.configure

    def flat(v):
        return ' / '.join(part.strip() for part in v.splitlines() if part.strip()) if isinstance(v, str) and '\n' in v else v

    def configure(cnf=None, **kw):
        if isinstance(cnf, dict) and 'text' in cnf:
            cnf = dict(cnf, text=flat(cnf['text']))
        if 'text' in kw:
            kw['text'] = flat(kw['text'])
        return o_configure(cnf, **kw)
    st.configure = st.config = configure


def install_char():
    """Hover on the character window's doll / inventory canvases."""
    from mxl_char_gui import CharacterWindow
    o_build = CharacterWindow._build_equipment

    def _build_equipment(self):
        o_build(self)
        if getattr(self, 'vanilla_he', False):
            return
        try:
            _install_char_hover(self)
        except Exception as e:
            print('item hover (character) disabled:', e)

    CharacterWindow._build_equipment = _build_equipment


def _install_stash_hover(app):
    canvas = app.canvas
    st = {'it': 'unset', 'job': None}

    def show():
        st['job'] = None
        if getattr(app, 'drag', None):
            return
        px, py = canvas.winfo_pointerx(), canvas.winfo_pointery()
        x, y = px - canvas.winfo_rootx(), py - canvas.winfo_rooty()
        it = None
        if 0 <= x < canvas.winfo_width() and 0 <= y < canvas.winfo_height():
            try:
                it = app.item_at(types.SimpleNamespace(x=x, y=y))
            except Exception:
                it = None
        try:
            app.set_detail(it or app.selected)
        except Exception:
            pass

    def on_motion(ev):
        if getattr(app, 'drag', None):
            return
        try:
            it = app.item_at(ev)
        except Exception:
            it = None
        if it is st['it']:
            return
        st['it'] = it
        show()                                     # instant: no visible delay of any kind

    canvas.bind('<Motion>', on_motion, add='+')       # next to the drag/status Motion binding


def _install_char_hover(win):
    st = {'e': 'unset', 'job': None}

    def entry_now():
        for cv in (win.doll, win.inv):
            px, py = cv.winfo_pointerx(), cv.winfo_pointery()
            x, y = px - cv.winfo_rootx(), py - cv.winfo_rooty()
            if 0 <= x < cv.winfo_width() and 0 <= y < cv.winfo_height():
                try:
                    return win.entry_at(cv, types.SimpleNamespace(x=x, y=y))[0]
                except Exception:
                    return None
        return None

    def show():
        st['job'] = None
        if getattr(win, 'drag', None):
            return
        e = entry_now()
        try:
            win.panel.show(e.it if e is not None else (win.selected.it if win.selected else None))
        except Exception:
            pass

    def on_motion(ev):
        if getattr(win, 'drag', None):
            return
        try:
            e, _slot = win.entry_at(ev.widget, ev)
        except Exception:
            e = None
        if e is st['e']:
            return
        st['e'] = e
        show()                                     # instant: no visible delay of any kind

    for cv in (win.doll, win.inv):
        cv.bind('<Motion>', on_motion, add='+')
