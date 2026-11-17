"""The Hero-Editor look for every window: the collector's main window, the Item Creator / Editor, the
import and equipment windows - everything that the self-styled windows (mxl_char_gui, mxl_he_stats)
leave in the collector's "modern" look.

What it does, without opening anything of its own:
- ttk widgets get the 'clam' theme repainted in the Hero-Editor palette (grey windows, white entries,
  black text, stone-grey buttons) - that covers the main window and the creator's ttk widgets;
- every plain tk widget is repainted in the same palette - except what is already dark (the black /
  gold chrome of the Hero-Editor windows, the stone D2 buttons, the item preview and the dark item
  lists stay as they are);
- missing font families are repaired (Palatino Linotype / Times New Roman / Segoe UI do not exist on
  every Linux system, which showed glyph boxes - they fall back to DejaVu / Liberation), on window
  chrome as well as inside the drawing canvases;
- newly built windows and late-built widgets (the creator rebuilds its lists constantly) are picked
  up: every Toplevel is themed once when it opens, and a light idle timer re-walks the app.

The raid grid / item art is never repainted: canvases only get their text fonts fixed, their colours
are untouched (the item grid and the D2 panels stay as they are).
"""
import tkinter as tk
from tkinter import ttk, font as tkfont

HE_BG = '#f0f0f0'          # Hero-Editor grey window
HE_BTN = '#e1e1e1'         # plain buttons of the HE windows
HE_ENTRY = '#ffffff'
HE_FG = '#000000'
HE_GOLD = '#d8c27a'
SELECT_BG = '#3a5f8a'      # the list selection the item list already uses

FALLBACKS = {              # families that may not exist (esp. on Linux) -> what usually does
    'palatino linotype': ('Palatino Linotype', 'Book Antiqua', 'Palatino', 'Times New Roman',
                          'DejaVu Serif', 'Liberation Serif'),
    'times new roman': ('Times New Roman', 'Liberation Serif', 'DejaVu Serif'),
    'segoe ui': ('Segoe UI', 'DejaVu Sans', 'Liberation Sans', 'Noto Sans'),
}
_SERIF = ('Palatino Linotype', 'Book Antiqua', 'Times New Roman', 'DejaVu Serif', 'Liberation Serif')
_SANS = ('Segoe UI', 'DejaVu Sans', 'Liberation Sans', 'Noto Sans')

_state = {'families': None, 'hooked': False, 'tick': 2500}


# ---------------------------------------------------------------------------------------------- fonts
def families(root=None):
    """Lowercased set of the font families this system actually has."""
    if _state['families'] is None or not _state['families']:
        try:
            _state['families'] = {f.lower() for f in tkfont.families(root)}
        except Exception:
            _state['families'] = set()
    return _state['families']


def _default_family():
    try:
        return tkfont.nametofont('TkDefaultFont').actual('family')
    except Exception:
        return 'TkDefaultFont'


_SERIF_HINTS = ('palatino', 'times', 'georgia', 'garamond', 'serif', 'book', 'century', 'roman', 'cambria')


def safe_family(fam):
    """fam or the first family of its fallback chain (or the server default) that is installed."""
    fam = str(fam)
    fams = families()
    if fam.lower() in fams:
        return fam
    for cand in FALLBACKS.get(fam.lower(), ()):
        if cand.lower() in fams:
            return cand
    chain = _SERIF if any(h in fam.lower() for h in _SERIF_HINTS) else _SANS
    for cand in chain:
        if cand.lower() in fams:
            return cand
    if not fams:                     # family probe failed: better unknown than wrong
        return fam
    return _default_family()


def _parse_font(font):
    """fam, size, styles of a raw font spec (tuple / string / Font): the tokens as given, because a
    Font built from a spec with a missing family gets normalized (family and styles may be lost)."""
    if isinstance(font, tkfont.Font):
        font = str(font)
    if isinstance(font, str):
        toks = font.split()
    elif isinstance(font, (tuple, list)):
        toks = [str(t) for t in font]
    else:
        toks = []
    fam, size, styles, base = [], None, [], False
    for wrd in toks:
        low = wrd.lower()
        if low in ('bold', 'italic'):
            styles.append(low)
        elif low in ('underline', 'overstrike'):
            styles.append(low)
        elif wrd.lstrip('-').isdigit() and not base:
            size = int(wrd)
        elif low in ('normal', 'roman') and not base:
            pass
        else:
            fam.append(wrd)
    if not size:
        try:
            size = tkfont.nametofont('TkDefaultFont').actual('size')
        except (tk.TclError, KeyError):
            size = 10
    return ' '.join(fam), size, styles


def safe_font(font):
    """A font spec (tuple / string / Font) in a family this system has; unchanged when it is."""
    try:
        fam, size, styles = _parse_font(font)
        f = tkfont.Font(font=font)
        if not fam:                              # e.g. 'TkDefaultFont': the named-font's own family
            fam, size, *_ = f.actual('family'), f.actual('size')
        good = safe_family(fam)
        if good == fam:
            return font                          # already fine: leave tuples and strings as they were
        return tuple(map(str, (good, size, *styles)))
    except (tk.TclError, ValueError, TypeError):
        return font


# ---------------------------------------------------------------------------------------------- colours
def _dark_bg(w):
    """True when the widget is already drawn dark (black / gold HE chrome, stone buttons, item lists):
    those are left alone."""
    try:
        rgb = w.winfo_rgb(str(w.cget('bg')))
        return sum(v for v in rgb) / (3 * 257) < 96
    except (tk.TclError, KeyError, AttributeError):
        return False


# ---------------------------------------------------------------------------------------------- walking
def _fix_canvas_fonts(cv):
    """Text items in families this system lacks -> a family it has (colour and geometry untouched)."""
    fams = families()
    if not fams:
        return
    for it in cv.find('all'):
        if cv.type(it) != 'text':
            continue
        try:
            spec = cv.itemcget(it, 'font')
            new = safe_font(spec)
            if new != spec:
                cv.itemconfigure(it, font=new)
        except tk.TclError:
            pass


def _walk(w):
    """Repaint one widget tree in the Hero-Editor palette; canvases keep their colours."""
    if getattr(w, '_he_exempt', False):
        return
    cls = w.winfo_class()
    if cls == 'Canvas':
        _fix_canvas_fonts(w)
        for c in w.winfo_children():
            _walk(c)
        return
    try:
        if cls in ('Frame', 'Toplevel', 'Tk'):
            if not _dark_bg(w):
                w.configure(bg=HE_BG)
        elif cls == 'Labelframe':
            if not _dark_bg(w):
                w.configure(bg=HE_BG, fg=HE_FG)
        elif cls in ('Label', 'Menubutton'):
            if not _dark_bg(w):
                w.configure(bg=HE_BG, fg=HE_FG)
        elif cls == 'Button':
            if not _dark_bg(w):
                w.configure(bg=HE_BTN, fg=HE_FG, activebackground=HE_BTN, activeforeground=HE_FG,
                            disabledforeground='#999999')
        elif cls in ('Checkbutton', 'Radiobutton'):
            if not _dark_bg(w):
                w.configure(bg=HE_BG, fg=HE_FG, activebackground=HE_BG, activeforeground=HE_FG,
                            disabledforeground='#999999')
        elif cls in ('Entry', 'Spinbox'):
            if not _dark_bg(w):
                w.configure(bg=HE_ENTRY, fg=HE_FG, insertbackground=HE_FG,
                            readonlybackground=HE_ENTRY)
        elif cls == 'Listbox':
            if not _dark_bg(w):
                w.configure(bg=HE_ENTRY, fg=HE_FG, selectbackground=SELECT_BG, selectforeground='#ffffff')
        elif cls == 'Menu':
            w.configure(bg=HE_BG, fg=HE_FG, activebackground='#000000',
                        activeforeground=HE_GOLD, disabledforeground='#999999')
    except (tk.TclError, AttributeError):
        pass
    if cls != 'Menu':
        for c in w.winfo_children():
            _walk(c)


def _theme_top(top):
    try:
        _walk(top)
    except (tk.TclError, RuntimeError, AttributeError):
        pass


# ---------------------------------------------------------------------------------------------- ttk
def _style(root):
    """ttk widgets in the Hero-Editor palette (the collector's main window is mostly ttk)."""
    st = ttk.Style(root)
    try:
        st.theme_use('clam')
    except tk.TclError:
        pass
    fam = safe_family('Palatino Linotype')
    F = (fam, 10)
    F_B = (fam, 10, 'bold')
    st.configure('.', background=HE_BG, foreground=HE_FG, fieldbackground=HE_ENTRY,
                 selectbackground=SELECT_BG, selectforeground='#ffffff', bordercolor='#a8a493',
                 lightcolor='#e9e7dd', darkcolor='#c9c5b6', font=F)
    st.map('.', background=[('disabled', '#d4d4d4')], foreground=[('disabled', '#888888')])
    st.configure('TFrame', background=HE_BG)
    st.configure('TLabel', background=HE_BG, foreground=HE_FG)
    st.configure('TLabelframe', background=HE_BG, foreground=HE_FG)
    st.configure('TLabelframe.Label', background=HE_BG, foreground=HE_FG, font=F)
    st.configure('TButton', background=HE_BTN, foreground=HE_FG, relief='raised', font=F, padding=(6, 1))
    st.map('TButton', background=[('disabled', '#d4d4d4'), ('pressed', '#c8c4b5'), ('active', '#e9e7dd')],
           foreground=[('disabled', '#888888')])
    st.configure('TRadiobutton', background=HE_BG, foreground=HE_FG, focuscolor=HE_BG)
    st.map('TRadiobutton', background=[('active', HE_BG)], foreground=[('disabled', '#888888')])
    st.configure('TCheckbutton', background=HE_BG, foreground=HE_FG, focuscolor=HE_BG)
    st.map('TCheckbutton', background=[('active', HE_BG)], foreground=[('disabled', '#888888')])
    st.configure('TEntry', fieldbackground=HE_ENTRY, foreground=HE_FG)
    st.configure('TSpinbox', fieldbackground=HE_ENTRY, foreground=HE_FG, arrowcolor=HE_FG,
                 background=HE_ENTRY)
    st.configure('TCombobox', fieldbackground=HE_ENTRY, foreground=HE_FG, background=HE_BTN,
                 arrowcolor=HE_FG)
    st.map('TCombobox', fieldbackground=[('readonly', HE_ENTRY)], background=[('readonly', HE_BTN)],
           foreground=[('disabled', '#888888')])
    st.configure('TCombobox.Listbox', background=HE_ENTRY, foreground=HE_FG,
                 selectbackground=SELECT_BG, selectforeground='#ffffff', font=F)
    st.configure('TNotebook', background=HE_BG, bordercolor='#a8a493', tabmargins=[2, 2, 2, 0])
    st.configure('TNotebook.Tab', background=HE_BTN, foreground=HE_FG, padding=[8, 2], font=F_B)
    st.configure('Pages.TNotebook.Tab', padding=[5, 1])       # the stash's page tabs 1..10
    st.configure('Pages.TNotebook', tabmargins=[0, 2, 0, 0])
    st.configure('Toolbutton', background=HE_BTN, foreground=HE_FG, relief='raised', padding=(6, 1), font=F)
    st.map('Toolbutton', background=[('selected', '#d8d4c5'), ('active', '#e9e7dd')],
           relief=[('selected', 'sunken')])                  # Character stash / Shared stash
    st.map('TNotebook.Tab', background=[('selected', '#d8d4c5')], foreground=[('disabled', '#888888')])
    st.configure('TPanedwindow', background=HE_BG)
    st.configure('TScrollbar', background='#d8d4c5', arrowcolor='#404040', bordercolor='#a8a493',
                 lightcolor=HE_BG, darkcolor='#b8b4a5', troughcolor=HE_BG)
    st.map('TScrollbar', background=[('active', '#e2ded1')])
    for extra in ('Horizontal.TProgressbar', 'Vertical.TProgressbar'):
        st.configure(extra, background=HE_GOLD, troughcolor=HE_BG, bordercolor='#a8a493',
                     lightcolor=HE_GOLD, darkcolor=HE_GOLD)
    return st


# ---------------------------------------------------------------------------------------------- install
def _tick(root):
    """Re-walk the app every _state['tick'] ms: late-built widgets (the creator's lists are rebuilt
    constantly) also end up in the Hero-Editor look."""
    try:
        if root.winfo_exists():
            _theme_top(root)
            root.after(_state['tick'], _tick, root)
    except (tk.TclError, RuntimeError, AttributeError):
        pass


def _start(root):
    try:
        families(root)
        _style(root)
    except (tk.TclError, RuntimeError) as e:
        print('HE theme (style) disabled:', e)
    _theme_top(root)
    try:
        root.after(_state['tick'], _tick, root)
    except tk.TclError:
        pass


def install(App):
    """Outermost look wrapper: themes whatever the app and the other wrappers build, as windows open."""
    o_build = App._build

    def _build(self):
        try:
            o_build(self)
        finally:
            try:
                self.root.after_idle(_start, self.root)
            except (tk.TclError, AttributeError):
                pass
    App._build = _build

    if not _state['hooked']:
        _state['hooked'] = True
        o_init = tk.Toplevel.__init__

        def top_init(self, *a, **k):
            o_init(self, *a, **k)
            try:
                self.after_idle(_theme_top, self)
            except (tk.TclError, RuntimeError):
                pass
        tk.Toplevel.__init__ = top_init


def exempt(w):
    """Optional: mark one widget (and its subtree) as self-styled so the walk leaves it alone."""
    w._he_exempt = True
    return w
