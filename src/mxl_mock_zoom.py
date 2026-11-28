"""Mock Mode window zoom (vanilla only): dragging the window bigger scales the whole UI with it - the Hero Editor
pages (their placed layout and fonts) and the Mock tab (fonts, so the grid grows) - by one factor, so nothing gets
extra padding. Back to 1x when the window shrinks to its natural size or Mock Mode is switched off.

Text size (Menu > Text size, setting 'text_size', every profile): the same scaling at a fixed factor on every page
(doc #9: bigger text for those who need it). While it is above 100 % the window drag does not zoom."""
import tkinter as tk
from tkinter import font as tkfont, ttk

STEP = 0.1                      # zoom steps (no relayout on every pixel of a drag)
MAX = 3.0
SKIP = {'TkMenuFont'}               # menus pop up at their normal size
SIZES = (1.0, 1.15, 1.3, 1.5, 1.75, 2.0)
_ZOOM = [None]                      # the window's Zoom (one main window)


def text_size():
    try:
        import settings
        v = float(settings.get('text_size') or 1.0)
    except Exception:
        v = 1.0
    return min(SIZES[-1], max(1.0, v))


def set_text_size(v):
    import settings
    settings.put('text_size', float(v))
    z = _ZOOM[0]
    if z is not None:
        z.apply()


def text_size_menu(parent):
    """A menu of the sizes (radio entries; the setting changes at once)."""
    m = tk.Menu(parent, tearoff=False)
    var = tk.DoubleVar(master=parent, value=text_size())
    m._var = var
    for v in SIZES:
        m.add_radiobutton(label=f'{round(v * 100)} %', value=v, variable=var, command=lambda v=v: set_text_size(v))
    m.configure(postcommand=lambda: var.set(text_size()))
    return m


def install(App):
    """Every profile: a Zoom on the main window (Mock Mode makes one already) and the saved text size applied;
    "Text size" in the More menu."""
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            if _ZOOM[0] is None:
                Zoom(self.root, lambda: False)
            if text_size() != 1.0:
                self.root.after_idle(_ZOOM[0].apply)
        except Exception as e:
            print('text size disabled:', type(e).__name__, e)

    App._build = _build
    try:
        import mxl_toolbar

        def pick(app):
            m = text_size_menu(app.root)
            try:
                m.tk_popup(app.root.winfo_pointerx(), app.root.winfo_pointery())
            finally:
                m.grab_release()
        mxl_toolbar.add_entry(lambda: 'Text size...', pick)
    except Exception as e:
        print('text size menu entry disabled:', e)


class Zoom:
    def __init__(self, top, enabled):
        self.top, self.enabled = top, enabled
        self.z, self.base, self.job = 1.0, None, None
        self.named = {}
        self.rowheight = None
        self.styles = {}                                      # ttk style -> its own font at 1x (None: none set)
        self.seen = {'.', 'Treeview.Heading', 'TNotebook.Tab', 'TLabelframe.Label'}
        top.bind('<Configure>', self._configure, add='+')
        top.bind_all('<Map>', self._mapped, add='+')      # pages and dialogs built later catch up
        _ZOOM[0] = self

    def _mapped(self, _event=None):
        if self.z == 1.0 and text_size() == 1.0:
            return
        if self.job is None:
            try:
                self.job = self.top.after(60, self.apply)
            except tk.TclError:
                pass

    def _configure(self, event):
        if event.widget is not self.top:
            return
        if self.job is not None:
            self.top.after_cancel(self.job)
        self.job = self.top.after(150, self.apply)

    def target(self):
        user = text_size()
        if user != 1.0:                                  # Text size: a fixed factor, no drag zoom
            return user
        if not self.enabled():
            return 1.0
        if self.base is None:
            if self.z != 1.0:
                return self.z
            self.top.update_idletasks()
            self.base = (max(1, self.top.winfo_reqwidth()), max(1, self.top.winfo_reqheight()))
        w, h = self.top.winfo_width(), self.top.winfo_height()
        z = min(w / self.base[0], h / self.base[1])
        return max(1.0, min(MAX, int(z / STEP) * STEP))

    def apply(self):
        self.job = None
        try:
            z = round(self.target(), 2)
            if abs(z - self.z) < 1e-6:
                self._walk(self.top, z, only_new=True)      # widgets built since (page refreshes) catch up
                self._styles(z)
                return
            self.z = z
            self._named(z)
            self._walk(self.top, z)
            self._styles(z)
        except tk.TclError:
            pass

    def _named(self, z):
        for name in tkfont.names(self.top):                 # Tk's and the app's own named fonts (ttk styles use them)
            if name in SKIP:
                continue
            try:
                f = tkfont.nametofont(name)
            except tk.TclError:
                continue
            size = self.named.setdefault(name, f.cget('size'))
            f.configure(size=_scaled(size, z))
        st = ttk.Style(self.top)
        if self.rowheight is None:
            try:
                self.rowheight = int(st.lookup('Treeview', 'rowheight') or 0)
            except (tk.TclError, ValueError):
                self.rowheight = 0
        if self.rowheight:
            st.configure('Treeview', rowheight=round(self.rowheight * z))

    def _styles(self, z):
        st = ttk.Style(self.top)
        for name in sorted(self.seen):
            if name not in self.styles:
                spec = st.configure(name, 'font')
                if spec and str(spec) not in tkfont.names(self.top):   # named ones are scaled already
                    a = tkfont.Font(root=self.top, font=spec).actual()
                    self.styles[name] = (a['family'], a['size'], a['weight'], a['slant'])
                else:
                    self.styles[name] = None
            orig = self.styles[name]
            if orig is not None:
                family, size, weight, slant = orig
                st.configure(name, font=(family, _scaled(size, z), weight, slant))

    def _walk(self, w, z, only_new=False):
        for child in w.winfo_children():
            if isinstance(child, tk.Menu):
                continue
            fresh = not hasattr(child, '_zoom_orig')
            if fresh and isinstance(child, ttk.Widget):
                try:
                    self.seen.add(str(child.cget('style')) or child.winfo_class())
                except tk.TclError:
                    pass
            if fresh or not only_new or self._font_changed(child):
                self._one(child, z, fresh)
            self._walk(child, z, only_new)

    @staticmethod
    def _font_changed(w):
        """The app gave the widget another font since it was scaled (a theme applied after the page was built):
        that font is its new 1x size."""
        orig = getattr(w, '_zoom_orig', None)
        if orig is None:
            return False
        try:
            spec = w.cget('font')
        except tk.TclError:
            return False
        cur = str(spec)
        if not spec or cur in tkfont.names(w) or cur == orig.get('font_set'):
            return False
        a = tkfont.Font(root=w, font=spec).actual()
        orig['font'] = (a['family'], a['size'], a['weight'], a['slant'])
        return True

    def _one(self, w, z, fresh):
        if fresh:
            orig = {}
            if w.winfo_manager() == 'place':
                info = w.place_info()
                orig['place'] = {k: int(info[k]) for k in ('x', 'y', 'width', 'height')
                                 if str(info.get(k, '')).lstrip('-').isdigit()}
            if w.winfo_class() in ('Frame', 'Labelframe', 'TFrame', 'TLabelframe'):
                size = {}
                for k in ('width', 'height'):
                    try:
                        v = int(str(w.cget(k)) or 0)
                    except (tk.TclError, ValueError):
                        v = 0
                    if v > 0:
                        size[k] = v
                if size:
                    orig['size'] = size                       # fixed-size page frames grow with their content
            if w.winfo_class() == 'Treeview':                 # column widths and tag fonts (section rows)
                cols = ('#0',) + tuple(w.cget('columns') or ())
                orig['cols'] = {c: int(w.column(c, 'width')) for c in cols}
                tags = {}
                for tag in w.tk.splitlist(w.tk.call(w, 'tag', 'names')):
                    spec = w.tag_configure(tag, 'font')
                    if spec and str(spec) not in tkfont.names(w):
                        a = tkfont.Font(root=w, font=spec).actual()
                        tags[tag] = (a['family'], a['size'], a['weight'], a['slant'])
                orig['tags'] = tags
            try:
                spec = w.cget('font')
            except tk.TclError:
                spec = None
            if spec and str(spec) not in tkfont.names(w):      # named fonts are scaled once, globally
                a = tkfont.Font(root=w, font=spec).actual()
                orig['font'] = (a['family'], a['size'], a['weight'], a['slant'])
            w._zoom_orig = orig
            if z == 1.0:                                      # built at 1x: nothing to change
                if 'font' in orig:
                    orig['font_set'] = str(w.cget('font'))
                return
        orig = w._zoom_orig
        if orig.get('place'):
            keep = ('width', 'height') if isinstance(w, tk.Canvas) else ()   # artwork stays crisp at 1x size
            w.place_configure(**{k: (v if k in keep else round(v * z)) for k, v in orig['place'].items()})
        if orig.get('size'):
            w.configure(**{k: round(v * z) for k, v in orig['size'].items()})
        for c, v in orig.get('cols', {}).items():
            w.column(c, width=round(v * z))
        for tag, (family, size, weight, slant) in orig.get('tags', {}).items():
            w.tag_configure(tag, font=(family, _scaled(size, z), weight, slant))
        if 'font' in orig:
            family, size, weight, slant = orig['font']
            w.configure(font=(family, _scaled(size, z), weight, slant))
            orig['font_set'] = str(w.cget('font'))


def _scaled(size, z):
    s = round(abs(size) * z) or 1
    return -s if size < 0 else s
