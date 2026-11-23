"""Dark Diablo look for every window: Median XL's own menu style (theme "Tartarus": slate stone, bronze trim,
red leather buttons, gold text) instead of the Hero-Editor light grey.

Which look is used: setting `ui_theme` ('d2' = this one, the default; 'he' = the Hero-Editor look of mxl_he_theme /
mxl_he_grid), or the environment variable MXL_THEME for one start. The "Dark D2 theme" box in the top bar switches
the setting; it is applied at the next start (every window caches its colours when it is built).

What this module does in the 'd2' look:
- the collector's own dark grids and item texts stay as they are (mxl_he_grid is simply not installed; only its
  font repair is done here);
- ttk widgets: the 'clam' theme repainted in the stone / bronze / gold palette, and ttk buttons drawn with the
  game's own menu button (data\\global\\themes\\<theme>\\menus\\buttons\\short-btn.dc6: normal / pressed, a
  brightened copy for hover and a dimmed one for disabled) when the game folder is known - flat stone otherwise;
- plain tk widgets: repainted by mxl_he_theme's walker, whose palette constants are replaced by the dark ones
  (it leaves canvases and whatever is already dark alone, and keeps repairing missing font families);
- the Character window starts in its own dark (stone + gold) variant unless the user chose otherwise.

Colours come from the game art: STONE is the plain area of the Tartarus stash panel, FIELD its grid, GOLD the
game's text gold (the collector's own #c7b377), LEATHER the button's red."""
import os
import tkinter as tk
from tkinter import ttk

SETTING = 'ui_theme'
STONE = '#26282a'          # window / panel background (stash panel's plain stone)
STONE_HI = '#34373a'       # raised stone: tabs, scrollbar thumb, hover
STONE_LO = '#1b1c1e'       # recessed stone: troughs, unselected tabs
FIELD = '#141112'          # entries / lists (the stash grid's red-black)
BRONZE = '#6f5a3a'         # trim lines
BRONZE_HI = '#9a7f52'
GOLD = '#c7b377'           # text
GOLD_HI = '#f2dc9c'        # hover / selected text
DIM = '#6a624f'            # disabled text
LEATHER = '#4a1712'        # button face / selection (the menu button's red)
LEATHER_HI = '#6a231a'

_state = {'theme': None, 'images': [], 'elements': False}


def theme():
    """'d2' or 'he' (read once per run: the look cannot change while windows exist)."""
    import mxl_vanilla_he
    if mxl_vanilla_he.active():
        return 'he'
    if _state['theme'] is None:
        t = (os.environ.get('MXL_THEME') or '').strip().lower()
        if t not in ('d2', 'he'):
            try:
                import settings
                t = settings.get(SETTING)
            except Exception:
                t = None
        _state['theme'] = t if t in ('d2', 'he') else 'd2'
    return _state['theme']


def dark():
    return theme() == 'd2'


# ---------------------------------------------------------------------------------------------- game art
def _art():
    """The game's UI art (mxl_d2look_art), or None: game folder unknown or files missing -> flat colours."""
    try:
        import settings, paths
        import mxl_d2look_art as A
        gd = settings.get('game_dir')
        if not gd or not os.path.isdir(gd):
            return None
        return A.get_art(gd, settings.get('d2_theme') or A.THEMES[0], os.path.join(paths.USER_DIR, 'ui_art'))
    except Exception as e:
        print('D2 theme: no game art,', e)
        return None


def _button_images(root):
    """(normal, hover, pressed, disabled) PhotoImages of the game's short menu button, or None."""
    a = _art()
    if a is None:
        return None
    try:
        from PIL import Image, ImageTk               # no ImageEnhance: the Windows exe's Pillow has no such module
        normal = Image.open(a.menu_frame('buttons\\short-btn', 0)).convert('RGBA')
        pressed = Image.open(a.menu_frame('buttons\\short-btn', 1)).convert('RGBA')
        alpha = normal.getchannel('A')

        def toward(flat, im, k):                     # ImageEnhance's own formula: flat + (im - flat) * k, clipped
            flat = flat.convert('RGBA')
            flat.putalpha(alpha)
            return Image.blend(flat, im, k)
        black = Image.new('RGBA', normal.size, (0, 0, 0, 255))
        hover = toward(black, normal, 1.35)          # brighter
        grey = toward(normal.convert('L'), normal, 0.15)     # nearly colourless
        disabled = toward(black, grey, 0.6)          # and darker
        out = tuple(ImageTk.PhotoImage(im, master=root) for im in (normal, hover, pressed, disabled))
        _state['images'].extend(out)                 # Tk only keeps a name: the objects must stay alive
        return out
    except Exception as e:
        print('D2 theme: flat buttons,', e)
        return None


# ---------------------------------------------------------------------------------------------- ttk
def _style(root):
    import mxl_he_theme as TH
    st = ttk.Style(root)
    try:
        st.theme_use('clam')
    except tk.TclError:
        pass
    fam = TH.safe_family('Palatino Linotype')
    F, F_B = (fam, 10), (fam, 10, 'bold')
    st.configure('.', background=STONE, foreground=GOLD, fieldbackground=FIELD, selectbackground=LEATHER,
                 selectforeground=GOLD_HI, bordercolor=BRONZE, lightcolor=STONE_HI, darkcolor=STONE_LO,
                 troughcolor=STONE_LO, insertcolor=GOLD, focuscolor=BRONZE, font=F)
    st.map('.', background=[('disabled', STONE)], foreground=[('disabled', DIM)])
    for name in ('TFrame', 'TPanedwindow'):
        st.configure(name, background=STONE)
    st.configure('TLabel', background=STONE, foreground=GOLD)
    st.configure('TLabelframe', background=STONE, foreground=GOLD, bordercolor=BRONZE)
    st.configure('TLabelframe.Label', background=STONE, foreground=GOLD_HI, font=F_B)
    st.configure('TSeparator', background=BRONZE)
    st.configure('TButton', background=LEATHER, foreground=GOLD_HI, bordercolor=BRONZE, lightcolor=BRONZE_HI,
                 darkcolor=STONE_LO, relief='raised', font=F_B, padding=(6, 1), anchor='center')
    st.map('TButton', background=[('disabled', STONE_HI), ('pressed', '#33100c'), ('active', LEATHER_HI)],
           foreground=[('disabled', DIM), ('pressed', GOLD_HI), ('active', GOLD_HI)])
    imgs = _button_images(root)
    if imgs:
        try:
            if not _state['elements']:
                st.element_create('D2.Button.face', 'image', imgs[0], ('disabled', imgs[3]), ('pressed', imgs[2]),
                                  ('active', imgs[1]), border=(16, 6, 16, 6), padding=(12, 1, 12, 1), sticky='nsew',
                                  width=40, height=20)   # minimum size: else the image's own 135 px
                _state['elements'] = True
            st.layout('TButton', [('D2.Button.face', {'sticky': 'nsew', 'children': [
                ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})])
            st.configure('TButton', padding=(3, 1))
        except tk.TclError as e:
            print('D2 theme: flat buttons,', e)
    for name in ('TRadiobutton', 'TCheckbutton'):
        st.configure(name, background=STONE, foreground=GOLD, focuscolor=STONE, indicatorbackground=FIELD,
                     indicatorforeground=GOLD_HI, upperbordercolor=BRONZE, lowerbordercolor=BRONZE)
        st.map(name, background=[('active', STONE)], foreground=[('disabled', DIM), ('active', GOLD_HI)],
               indicatorbackground=[('selected', LEATHER), ('pressed', LEATHER_HI)])
    st.configure('TEntry', fieldbackground=FIELD, foreground=GOLD_HI, insertcolor=GOLD_HI, bordercolor=BRONZE)
    st.configure('TSpinbox', fieldbackground=FIELD, foreground=GOLD_HI, arrowcolor=GOLD, background=STONE_HI,
                 insertcolor=GOLD_HI, bordercolor=BRONZE)
    st.configure('TCombobox', fieldbackground=FIELD, foreground=GOLD_HI, background=STONE_HI, arrowcolor=GOLD,
                 insertcolor=GOLD_HI, bordercolor=BRONZE)
    st.map('TCombobox', fieldbackground=[('readonly', FIELD), ('disabled', STONE)],
           background=[('readonly', STONE_HI), ('active', LEATHER)], foreground=[('disabled', DIM)],
           selectbackground=[('!focus', FIELD)], selectforeground=[('!focus', GOLD_HI)])
    for opt, val in (('background', FIELD), ('foreground', GOLD), ('selectBackground', LEATHER),
                     ('selectForeground', GOLD_HI)):
        root.option_add('*TCombobox*Listbox.' + opt, val)
    root.option_add('*TCombobox*Listbox.font', F)
    st.configure('TNotebook', background=STONE, bordercolor=BRONZE, lightcolor=STONE, darkcolor=STONE_LO,
                 tabmargins=[2, 2, 2, 0])
    st.configure('TNotebook.Tab', background=STONE_LO, foreground=GOLD, bordercolor=BRONZE, lightcolor=STONE_HI,
                 padding=[8, 2], font=F_B)
    st.configure('Pages.TNotebook.Tab', padding=[5, 1])       # the stash's page tabs 1..10
    st.configure('Pages.TNotebook', tabmargins=[0, 2, 0, 0])
    st.configure('Toolbutton', background=STONE_LO, foreground=GOLD, bordercolor=BRONZE, lightcolor=STONE_HI,
                 darkcolor=STONE_LO, relief='raised', padding=(6, 1), font=F)   # Character stash / Shared stash
    st.map('Toolbutton', background=[('selected', LEATHER), ('active', STONE_HI)],
           foreground=[('selected', GOLD_HI), ('disabled', DIM)], relief=[('selected', 'sunken')])
    st.map('TNotebook.Tab', background=[('selected', LEATHER), ('active', STONE_HI)],
           foreground=[('selected', GOLD_HI), ('disabled', DIM)], lightcolor=[('selected', BRONZE_HI)])
    for name in ('TScrollbar', 'Vertical.TScrollbar', 'Horizontal.TScrollbar'):
        st.configure(name, background=STONE_HI, arrowcolor=GOLD, bordercolor=BRONZE, lightcolor=STONE_HI,
                     darkcolor=STONE_LO, troughcolor=STONE_LO, gripcount=0)
        st.map(name, background=[('active', LEATHER), ('disabled', STONE)], arrowcolor=[('disabled', DIM)])
    st.configure('TScale', background=STONE_HI, troughcolor=STONE_LO, bordercolor=BRONZE)
    for name in ('Horizontal.TProgressbar', 'Vertical.TProgressbar'):
        st.configure(name, background=LEATHER_HI, troughcolor=STONE_LO, bordercolor=BRONZE, lightcolor=LEATHER_HI,
                     darkcolor=LEATHER)
    st.configure('Treeview', background=FIELD, fieldbackground=FIELD, foreground=GOLD, bordercolor=BRONZE)
    st.configure('Treeview.Heading', background=STONE_HI, foreground=GOLD_HI, font=F_B)
    st.map('Treeview', background=[('selected', LEATHER)], foreground=[('selected', GOLD_HI)])
    return st


# ---------------------------------------------------------------------------------------------- tk widgets
def _tk_defaults(root):
    """Colours of the plain tk widgets created from now on (menus, message boxes, the creator's widgets)."""
    for opt, val in (('background', STONE), ('foreground', GOLD), ('activeBackground', LEATHER),
                     ('activeForeground', GOLD_HI), ('selectBackground', LEATHER), ('selectForeground', GOLD_HI),
                     ('disabledForeground', DIM), ('insertBackground', GOLD_HI), ('highlightBackground', STONE),
                     ('highlightColor', BRONZE), ('troughColor', STONE_LO)):
        root.option_add('*' + opt, val, 'startupFile')       # lowest priority: explicit colours still win
    for cls in ('Entry', 'Listbox', 'Text', 'Spinbox'):
        root.option_add(f'*{cls}.background', FIELD, 'startupFile')
        root.option_add(f'*{cls}.foreground', GOLD_HI, 'startupFile')
    root.option_add('*Checkbutton.selectColor', FIELD, 'startupFile')
    root.option_add('*Radiobutton.selectColor', FIELD, 'startupFile')
    root.option_add('*Menu.selectColor', GOLD_HI, 'startupFile')
    try:
        root.configure(bg=STONE)
    except tk.TclError:
        pass


def _walk_extra(w):
    """What mxl_he_theme's walker cannot express with its few palette constants: the tick boxes' inner colour
    and the stone-and-bronze edge of plain tk buttons."""
    try:
        cls = w.winfo_class()
        if cls in ('Checkbutton', 'Radiobutton'):
            w.configure(selectcolor=FIELD)
        elif cls == 'Button' and not str(w.cget('image')):
            w.configure(relief='ridge', bd=2, highlightthickness=0, activebackground=LEATHER_HI,
                        activeforeground=GOLD_HI, disabledforeground=DIM)
        elif cls in ('Entry', 'Spinbox'):
            w.configure(disabledbackground=STONE, disabledforeground=DIM, highlightbackground=BRONZE,
                        highlightthickness=1, relief='flat')
    except (tk.TclError, AttributeError):
        pass
    if w.winfo_class() != 'Menu':
        for c in w.winfo_children():
            _walk_extra(c)


def _repalette():
    """mxl_he_theme's walker repaints with its module constants: give it the dark ones."""
    import mxl_he_theme as TH
    TH.HE_BG, TH.HE_BTN, TH.HE_ENTRY, TH.HE_FG, TH.HE_GOLD, TH.SELECT_BG = STONE, LEATHER, FIELD, GOLD, GOLD_HI, LEATHER
    TH._style = _style
    o_top = TH._theme_top
    if getattr(o_top, '_d2', False):
        return

    def _theme_top(top):
        o_top(top)
        try:
            _walk_extra(top)
        except (tk.TclError, RuntimeError, AttributeError):
            pass
    _theme_top._d2 = True
    TH._theme_top = _theme_top


def _fix_fonts(app):
    """The font repair mxl_he_grid does in the light look: FONT of the window modules in a family that exists."""
    import mxl_he_theme as TH
    from tkinter import font as tkfont
    TH.families(app.root)
    fam = TH.safe_family('Segoe UI')
    for name in ('mxl_theme', 'mxl_gui', 'mxl_gui_detail', 'mxl_tooltip', 'mxl_char_gui', 'mxl_creator_gui',
                 'mxl_inv_gui', 'mxl_import'):
        try:
            mod = __import__(name)
        except ImportError:
            continue
        if hasattr(mod, 'FONT'):
            mod.FONT = fam
    f = getattr(app, 'cell_font', None)
    if f is not None:
        d = f.actual()
        app.cell_font = tkfont.Font(family=fam, size=d.get('size', 10), weight=d.get('weight', 'normal'))


# ---------------------------------------------------------------------------------------------- install
def _add_toggle(app):
    """"Dark D2 theme" box in the top bar, for both looks (applied at the next start)."""
    from tkinter import messagebox
    from mxl_lang import T
    import settings
    try:
        bar = app.char_combo.master
    except AttributeError:
        return
    var = tk.BooleanVar(value=dark())

    def changed():
        settings.put(SETTING, 'd2' if var.get() else 'he')
        messagebox.showinfo(T('theme.title', 'Theme'),
                            T('theme.restart', 'The new look is used the next time the editor starts.'),
                            parent=app.root)
    ttk.Checkbutton(bar, text=T('theme.toggle', 'Dark D2 theme'), variable=var, command=changed).pack(
        side='left', padx=(6, 2))


def install_toggle(App):
    from mxl_vanilla_he import active
    if active():
        return
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            _add_toggle(self)
        except Exception as e:                       # a missing box never keeps the editor from starting
            print('theme toggle:', e)
    App._build = _build


def install(App):
    """Dark look: palette for mxl_he_theme's machinery (installed right after, as the outermost wrapper), option
    database defaults before any widget exists, font repair once the app is built."""
    _repalette()
    o_init = App.__init__

    def __init__(self, root, *a, **k):
        try:
            _tk_defaults(root)
        except Exception as e:
            print('D2 theme (defaults):', e)
        o_init(self, root, *a, **k)
        try:
            _fix_fonts(self)
        except Exception as e:
            print('D2 theme (fonts):', e)
    App.__init__ = __init__
