"""Hero-Editor's plain light-grey item grids.

The collector draws the stash grid, the character window's paperdoll / inventory and the item texts
(detail panel) with its own near-black theme, defined once in mxl_theme and copied by value into the
window modules' namespaces at import. Because every drawing function reads its module's own globals
at draw time, replacing those copies here recolours all of it in the Hero-Editor palette: light-grey
panel, pale cells with grey lines, black text, gold selection - while the item icons, their layout
and the drawing code itself stay untouched (they are the collector's).

The D2 game-art panels (mxl_d2look) are switched off in this build: the plain grids replace them.

Installed in run() right after mxl_d2look.disable() - before any window is built - so every constant
is already the HE one when a widget or canvas item is created. The font of the grid rows (app's
cell_font) is rebuilt from the replaced FONT constant (a family this system actually has).
"""
import tkinter as tk
from tkinter import font as tkfont

HE_BG = '#f0f0f0'              # panel / canvas background
HE_EMPTY = '#e2dfd3'           # an empty cell
HE_GRID = '#c4c0b1'            # the cell outlines
HE_SEL = '#d8c27a'             # the selected item's outline (HE gold)
HE_OK = '#dde8f2'              # drop / equip highlight: the item fits
HE_KO = '#f4dede'              # drop / equip highlight: refused
HE_DETAIL_BG = '#f0f0f0'       # item text panel + tip
HE_DETAIL_FG = '#000000'

# the game text colours as they must look on light grey (mxl_theme.GAME_COLORS keys, and the named
# colours 'WHITE' ... 'PURPLE' are the same keys); darkness so it stays readable where the
# collector's dark-theme shades are geared to black backgrounds
_LIGHT_GAME = {
    '0': '#1e1e1e',   # white   -> near black (plain text)
    '1': '#c41d1d',   # red
    '2': '#0e7a0e',   # green
    '3': '#4444c8',   # blue
    '4': '#9d771c',   # gold (unique / artefact)
    '5': '#5e5e5e',   # grey
    '6': '#3e3e3e',   # dark grey
    '7': '#9d771c',   # gold / craft
    '8': '#b07c00',   # bright gold / orange
    '9': '#8a8200',   # yellow
    ':': '#0e7a0e',   # dark green
    ';': '#a40aa4',   # purple
}

_LIGHT = {
    'BG': HE_BG, 'GRID_LINE': HE_GRID, 'EMPTY': HE_EMPTY,
    'CELL_OK': HE_OK, 'CELL_KO': HE_KO,
    'TIP_BG': HE_DETAIL_BG, 'DETAIL_BG': HE_DETAIL_BG, 'DETAIL_FG': HE_DETAIL_FG,
    'SELECTION': HE_SEL,
    'DROP_OK': ((212, 194, 122, 90), HE_SEL),        # (rgba overlay, colour) like the collector's
    'DROP_KO': ((240, 80, 80, 110), '#e04040'),
    'GAME_COLORS': _LIGHT_GAME,
    'WHITE': '0', 'RED': '1', 'GREEN': '2', 'BLUE': '3', 'GOLD': '4',
    'GREY': '5', 'BRIGHT_GOLD': '8', 'YELLOW': '9', 'DARK_GREEN': ':', 'PURPLE': ';',
    'QUALITY': '#8a6410', 'FOUND_COLOR': '#9d771c', 'STORED_COLOR': '#0e7a0e',
    'DESTROY_COLOR': '#c41d1d', 'BAD': '#c43030', 'HIDDEN': '#606060',
    'SECTION': '#6a6a72',
}

# every module that holds a copy of the theme constants (the frozen ones included): the drawing
# functions read them from their own namespace, so each copy has to be replaced
_MODULES = ('mxl_theme', 'mxl_gui', 'mxl_gui_detail', 'mxl_tooltip', 'mxl_library_gui',
            'mxl_char_gui', 'mxl_creator_gui', 'mxl_inv_gui', 'mxl_import')


def apply(root=None):
    """Copies HE colour constants into the namespaces listed above (things already patched are left).

    When a Tk root exists the FONT constant is also replaced by a family this system actually has
    (the collector's 'Segoe UI' / HE's Times do not exist everywhere)."""
    import mxl_he_theme as TH
    fam = None
    if root is not None:
        TH.families(root)
        fam = TH.safe_family('Times New Roman')
    touched = {}
    for name in _MODULES:
        try:
            mod = __import__(name)
        except ImportError:
            continue
        for k, v in _LIGHT.items():
            if hasattr(mod, k):
                setattr(mod, k, v)
                touched[k] = True
        if fam and hasattr(mod, 'FONT'):
            setattr(mod, 'FONT', fam)
    return touched


def install(App):
    """Wraps App.__init__: after the app exists (and its root does), everything is patched, then the
    grid's own font (built from the old FONT inside __init__) is rebuilt in the HE family."""
    o_init = App.__init__

    def __init__(self, *a, **k):
        try:
            o_init(self, *a, **k)
            fam = apply(self.root)
            f = getattr(self, 'cell_font', None)
            if f is not None:
                d = f.actual()
                opts = dict(family=fam if fam else d.get('family'), size=d.get('size', 10))
                if d.get('weight') == 'bold':
                    opts['weight'] = 'bold'
                if d.get('slant') == 'italic':
                    opts['slant'] = 'italic'
                if d.get('underline'):
                    opts['underline'] = 1
                if d.get('overstrike'):
                    opts['overstrike'] = 1
                self.cell_font = tkfont.Font(**opts)
        except Exception as e:                        # the light grids are cosmetic: never a crash
            print('HE grid look disabled:', e)
    App.__init__ = __init__
