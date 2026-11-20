"""Item Creator / Editor window for the MXL Item Collector (added to the main window by install()).

- Create: choose a unique, set item, runeword or base item (normal, superior, magic, rare), its options and the
  value of every variable mod (always inside the game's own ranges), preview it with the collector's tooltip, and
  write it into the stash shown in the main window (first free place of the chosen page).
- Edit: the selected stash item is loaded into the same window; "Replace item" writes the new version in its place.
- Delete: removes the selected stash item (and its socketed items).
- The collector's in-place value sliders are switched off (app.editing = False): see mxl_perfect ("Make perfect").
Every write goes through mxl_save.edit_stash (verification after writing, .bak backup; the game-closed check is removed by mxl_free - see DEVELOPER_NOTES).
"""
import os
import re
import sys
import random
import time
import tkinter as tk
from tkinter import ttk, messagebox

import settings
import mxl_save
from mxl_save import edit_stash, parse_stash, free_spot, blob_item, EditError, STASH_PAGES
import mxl_scroll
from mxl_format import FormatError, STAT_GROUPS
from mxl_rules import stat_label, stat_hidden, mods_stats
from mxl_statnames import (stat_text, param_kind, decode_param, encode_param, encode_skill_param,
                           skill_fits, skill_names_sorted, CHANCE_TO_CAST, SINGLE_SKILLS, CLASS_SKILLS,
                           STATE_STAT, state_names_sorted, skilldesc_name, param_choices, param_short,
                           param_title, rendered_line)
from mxl_gui_detail import DetailHost, DetailPanel, setup_detail_tags
from mxl_creator import Creator, CreateError, MAX_ILVL, CRAFTED_AFFIXES
from mxl_lang import T
import mxl_d2look as D2
import mxl_attr_picker as AP
import mxl_attr_slots as AS

QUALITY_KEYS = [('Unique', 'unique'), ('Set item', 'set'), ('Runeword', 'runeword'), ('Angelic', 'angelic'), ('Rare', 'rare'),
                ('Crafted', 'crafted'), ('Honorific', 'tempered'), ('Magic', 'magic'), ('Superior', 'superior'), ('Normal', 'normal')]
LONG_LIST = 25                 # option lists longer than this get the searchable picker instead of a dropdown
FILTER_KEYS = [('All', None), ('Weapon', 'weapons'), ('Armor', 'armor'), ('Misc', 'misc'), ('Mystic Orb', 'orb'),
               ('Mystic Dye', 'dye')]


def qualities():
    """[(label in the chosen language, quality key)] of the item type list."""
    return [(T(f'cr.quality.{k}', lab), k) for lab, k in QUALITY_KEYS]


def filters():
    return [(T(f'cr.filter.{k or "all"}', lab), k) for lab, k in FILTER_KEYS]


def bind_typeahead(cb, values):
    """Type-ahead for a long picker list: every letter jumps to the first entry starting with it
    (pressing it again goes to the next), Up / Down walk the list, and Enter commits what is
    typed: the exact entry, else the closest prefix, else a substring match."""
    typed = {'q': ''}

    def on_key(e):
        ks = e.keysym
        vals = list(values() if callable(values) else values)
        if ks in ('Return', 'KP_Enter'):
            text = cb.get().strip().lower()
            if text:
                i = next((i for i, v in enumerate(vals) if v.lower() == text), -1)
                if i < 0:
                    i = next((i for i, v in enumerate(vals) if v.lower().startswith(text)), -1)
                if i < 0:
                    i = next((i for i, v in enumerate(vals) if text in v.lower()), -1)
                if i >= 0:
                    cb.set(vals[i])
            return 'break'
        if ks == 'Escape':
            cb.set('')
            typed['q'] = ''
            return 'break'
        ch = (e.char or '').lower()
        if len(ch) == 1 and ch.isalpha():
            if typed['q'] == ch:
                i = next((i for i, v in enumerate(vals) if v.lower().startswith(ch)
                          and i > (cb.current() or -1)), -1)
                if i < 0:
                    i = next((i for i, v in enumerate(vals) if v.lower().startswith(ch)), -1)
            else:
                typed['q'] = ch
                i = next((i for i, v in enumerate(vals) if v.lower().startswith(ch)), -1)
            if i >= 0:
                cb.current(i)
            return 'break'
        typed['q'] = ch if len(ch) == 1 else ''
        return None

    cb.bind('<KeyRelease>', on_key)
    cb._typeahead_on_key = on_key
    return on_key


def clamp_window(top, pad=12, min_h=200, size=None):
    """Keeps a Toplevel fully on the screen and never bigger than it: the editor windows used to open
    with their lower / right part outside the screen (nothing to drag them back with in a tiling WM).
    size: the wanted (w, h) when the window has an explicit size of its own (it must not shrink to the
    not-yet-mapped required size)."""
    if top is None:
        return
    try:
        top.update_idletasks()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        w = min(max(top.winfo_reqwidth(), min_h), sw - 2 * pad)
        h = min(max(top.winfo_reqheight(), min_h), sh - 2 * pad)
        if size:
            w = min(size[0], sw - 2 * pad)
            h = min(size[1], sh - 2 * pad)
        x, y = top.winfo_x(), top.winfo_y()
        if top.winfo_rootx() == 0 and top.winfo_rooty() == 0 and not top.winfo_ismapped():
            x = max(pad, (sw - w) // 2)               # never placed yet: centre it
            y = max(pad, (sh - h) // 3)
        x = max(pad, min(x, sw - w - pad))
        y = max(pad, min(y, sh - h - pad))
        top.geometry(f'{w}x{h}+{x}+{y}')
    except (tk.TclError, AttributeError):
        pass


def none_label():
    return T('cr.none', '(none)')


def empty_label():
    return T('cr.empty', '(empty)')


def kind_label(kind):
    return T(f'cr.kind.{kind}', {'weapons': 'Weapon', 'armor': 'Armor', 'misc': 'Misc'}.get(kind, ''))


class PreviewPanel(DetailPanel):
    """Collector's detail panel without its edit / transfer sections (tooltip only)."""

    def write_edit(self, it):
        return None

    def write_transfer(self, it):
        return None


class PreviewHost(DetailHost):
    """Read-only host of the preview panel."""

    def __init__(self, app):
        self.app = app
        self.saved_priorities = {}
        self.editing = False

    @property
    def data(self):
        return self.app.data

    @property
    def char(self):
        return self.app.char


def clean(name):
    """One-line display name (multi-line game strings joined, colour codes removed)."""
    txt = str(name).replace('\\n', '\n')
    while 'ÿc' in txt:
        i = txt.index('ÿc')
        txt = txt[:i] + txt[i + 3:]
    return ' '.join(part.strip() for part in txt.split('\n') if part.strip())


def title_text(name, base):
    """Creator / Item Editor title: "name - base", only the name when it already says the base (a plain item's
    name is its base: "Belt (Angelic) - Belt (Angelic)" before)."""
    words = set(name.casefold().split())
    if not base or all(x in words for x in base.casefold().split()):
        return name
    return f'{name} - {base}'


STRETCH_CHARS = 12          # what a combobox that fills its column asks for (it gets the column's width)


def wide_popdown(cb):
    """The list of a read-only combobox opens as wide as its longest entry (at least as wide as the box, at most
    the screen): a box narrowed to a small window's column keeps whole entries in its list."""
    def widen():
        try:
            pd = cb.tk.call('ttk::combobox::PopdownWindow', str(cb))
            if not cb.tk.call('winfo', 'ismapped', pd):
                return
            from tkinter import font as tkfont
            try:
                f = tkfont.Font(root=cb, font=cb.tk.call(f'{pd}.f.l', 'cget', '-font'))
            except tk.TclError:
                f = tkfont.nametofont('TkDefaultFont')
            vals = cb.cget('values')
            vals = cb.tk.splitlist(vals) if isinstance(vals, str) else vals
            need = max((f.measure(str(v)) for v in vals), default=0) + f.measure('0') * 2 + 24   # + scrollbar
            w, h = int(cb.tk.call('winfo', 'width', pd)), int(cb.tk.call('winfo', 'height', pd))
            x, y = int(cb.tk.call('winfo', 'rootx', pd)), int(cb.tk.call('winfo', 'rooty', pd))
            sw = cb.winfo_screenwidth()
            need = min(need, sw)
            if need > w:
                x = max(0, min(x, sw - need))
                cb.tk.call('wm', 'geometry', pd, f'{need}x{h}+{x}+{y}')
        except (tk.TclError, ValueError):
            pass
    # (a timer, not an idle callback: ttk's Post runs `update idletasks` between -postcommand and placing the list)
    cb.configure(postcommand=lambda: cb.after(1, widen))


class ScrollFrame(ttk.Frame):
    """Vertical scroll area; the mouse wheel scrolls it anywhere over its content (comboboxes included: the wheel
    never changes their value by accident)."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        bg = ttk.Style().lookup('TFrame', 'background') or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, bg=bg, width=120, height=80)   # asks for
        # little: in a narrow column the scrollbar beside it must not be the part that is cut off
        self.sb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.hsb = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self._hsb_on = False
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', self._fit_width)
        self.canvas.bind('<Configure>', self._fit_width)
        self.canvas.configure(yscrollcommand=self.sb.set, xscrollcommand=self.hsb.set)
        self.sb.pack(side='right', fill='y')              # first: the canvas is what gives way
        self.canvas.pack(side='left', fill='both', expand=True)
        self.bind('<Enter>', lambda e: self._grab(True))
        self.bind('<Leave>', lambda e: self._grab(self._inside(e)))

    def _fit_width(self, _e=None, exact=False):
        """The content is as wide as the column; when it needs more (a narrow window), it keeps its own width and
        a horizontal scrollbar appears, so nothing at the right end is out of reach."""
        try:
            cw, need = self.canvas.winfo_width(), self.inner.winfo_reqwidth()
            # hysteresis: the content's own width depends on this decision (labels are re-wrapped to the column),
            # so near the limit the bar switched on and off for ever (100 % CPU at 1280x720). Once on, it stays
            # until the content clearly fits - in the same column: when the column has grown clearly since the bar
            # came on, or the content is new (refit) the plain rule decides (the bar stayed under content that
            # fitted: on since the column was narrow while the window was built). After a few switches in a row
            # the state is kept as it is (and decided once more a second later).
            if self._hsb_on and not exact and cw < getattr(self, '_hsb_cw', 0) + 16:
                over = need > cw - 16
            else:
                over = need > cw + 2
            over = over and cw > 20
            if over != self._hsb_on:
                import time
                now = time.monotonic()
                flips = [t for t in getattr(self, '_hsb_flips', []) if now - t < 1.0]
                if len(flips) >= 4:
                    over = self._hsb_on
                    self._recheck()                  # held: decided once more when things have calmed down
                else:
                    self._hsb_flips = flips + [now]
            self.canvas.itemconfigure(self.win, width=max(cw, need) if over else cw)
            if over != self._hsb_on:
                self._hsb_on = over
                self._hsb_cw = cw
                if over:
                    self.hsb.pack(side='bottom', fill='x', before=self.canvas)
                else:
                    self.hsb.pack_forget()
                    self.canvas.xview_moveto(0)
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        except tk.TclError:
            pass

    def _recheck(self):
        """One more _fit_width a little later (twice at most until the next refit): a held decision is not kept
        for ever."""
        if getattr(self, '_recheck_job', None) is None and getattr(self, '_rechecks', 0) < 2:
            self._rechecks = getattr(self, '_rechecks', 0) + 1     # (again only after the next refit)

            def run():
                self._recheck_job = None
                self._fit_width(exact=True)
            self._recheck_job = self.after(1100, run)

    def refit(self, fresh=True):
        """The content was rebuilt (fresh) or re-fitted to the column: its width is checked again (the content
        frame has the column's width set from outside, so a narrower or wider content alone sends no <Configure>:
        the scrollbar stayed)."""
        if fresh:
            self._rechecks = 0
        if getattr(self, '_refit_job', None) is None:
            def run():
                self._refit_job = None
                self._fit_width(exact=True)
            # a moment later, not at idle: the geometry managers compute the new requested width at idle too,
            # possibly after this check (which then saw the old width, and nothing asked again)
            self._refit_job = self.after(40, run)

    def _inside(self, e):
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, KeyError):
            return False
        return w is not None and str(w).startswith(str(self))

    def _grab(self, on):
        try:
            if on:
                mxl_scroll.bind_wheel_all(self, self._wheel)
            else:
                mxl_scroll.unbind_wheel_all(self)
        except tk.TclError:
            pass

    @property
    def _wheel(self):
        """The area's wheel handler (mxl_scroll.WheelHandler: whole notches, touchpad deltas added up)."""
        h = self.__dict__.get('_wheel_h')
        if h is None:
            h = self.__dict__['_wheel_h'] = mxl_scroll.WheelHandler(self._wheel_v, self._wheel_x)
        return h

    def _wheel_v(self, n, e):
        if not self._inside(e):
            return None
        top, bottom = self.canvas.yview()
        if top > 0 or bottom < 1:
            self.canvas.yview_scroll(n, 'units')
        return 'break'

    def _wheel_x(self, n, e):
        if not self._inside(e):
            return None
        if self._hsb_on:
            self.canvas.xview_scroll(n, 'units')
        return 'break'

    def no_wheel(self, widget):
        """The wheel over this widget scrolls the area instead of changing the widget's value (also when the
        widget is outside the area: the number of copies spun with the wheel)."""
        h = self.__dict__.get('_wheel_keep')
        if h is None:
            h = self.__dict__['_wheel_keep'] = mxl_scroll.WheelHandler(
                lambda n, e: self._wheel_v(n, e) or 'break', lambda n, e: self._wheel_x(n, e) or 'break')
        mxl_scroll.bind_wheel(widget, h)

    def scroll_top(self):
        self.canvas.yview_moveto(0)


BONUS_CACHE = 'creator-bonus-text'


def _bonus_disk_key(cr):
    """Key of the on-disk bonus-text index (mxl_diskcache): the game tables, the editor's code, the language."""
    try:
        import mxl_diskcache
        import settings
        return mxl_diskcache.key(folders=[cr.data.folder],
                                 modules=('mxl_catalog_tooltip', 'mxl_stat_text', 'mxl_rules', 'mxl_data', 'stat_ids'),
                                 extra=['bonus_text', settings.get('language') or ''])
    except Exception:
        return None


def _bonus_disk_load(k):
    import mxl_diskcache
    v = mxl_diskcache.load(BONUS_CACHE, k)
    try:
        return {(q, int(row)): text for q, row, text in v} if isinstance(v, list) else None
    except (TypeError, ValueError):
        return None


def _bonus_disk_save(k, cache):
    import mxl_diskcache
    mxl_diskcache.save(BONUS_CACHE, k, [[q, row, text] for (q, row), text in cache.items()])


class CreatorWindow:
    """Toplevel of the creator. edit_item: item of the open stash to edit (None: create a new item)."""

    def __init__(self, app, edit_item=None, target=None, target_label=None):
        self.app = app
        self.target = target              # callable(blob) -> message: writes somewhere else than the stash
        self.target_label = target_label
        self.data = app.data
        self.cr = getattr(app, '_creator', None)
        if self.cr is None or self.cr.data is not app.data:
            self.cr = app._creator = Creator(app.data)
        self.edit_item = edit_item
        self.spec = None
        self.entries = []
        self.mod_vars = {}
        self._edit_sel = None
        import mxl_tabs
        self.top = mxl_tabs.host_window(app, 'Creator', owner=self, replace=True)
        self._spins = {}                   # spinbox -> [setter, last committed text]: pending-edit tracking
        self.top.bind('<Button-1>', self._press_commit_spin, add='+')
        self.top.title(T('cr.title.editor', 'Item Editor') if edit_item else T('cr.title.creator', 'Item Creator'))
        sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        w, h = min(1750, max(900, sw - 60)), min(1080, max(560, sh - 110))
        w, h = min(w, sw), min(h, sh)
        self.top.geometry(f'{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}')
        self.top.minsize(min(900, sw), min(540, sh))
        self._build()
        self.top.after_idle(self._place_sashes)
        self._bonus_warm()
        if edit_item is not None:
            try:
                spec = self.cr.spec_from_item(edit_item)
            except CreateError as e:
                messagebox.showerror(T('cr.title.editor', 'Item Editor'),
                                     T('cr.err.not_editable', 'This item cannot be edited here:\n{error}', error=e),
                                     parent=self.top)
                self.top.destroy()
                return
            self.load_spec(spec)
        else:
            self.quality.set(qualities()[0][0])
            self.on_quality()

    # ------------------------------------------------------------------ layout
    def _build(self):
        top = self.top
        # three resizable columns: catalog list | options and values | preview (drag the separators)
        self.paned = ttk.Panedwindow(top, orient='horizontal')
        self.paned.pack(fill='both', expand=True)
        self._sash_user = False
        self.paned.bind('<B1-Motion>', lambda e: setattr(self, '_sash_user', True), add='+')
        self.paned.bind('<Configure>', self._resashed, add='+')
        left = ttk.Frame(self.paned, padding=3)
        self.paned.add(left, weight=1)
        ttk.Label(left, text=T('cr.item_type', 'Item type')).pack(anchor='w')
        self.quality = tk.StringVar()
        cb = ttk.Combobox(left, state='readonly', values=[q for q, _ in qualities()], textvariable=self.quality, width=20)
        cb.pack(fill='x')
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_quality())
        self.kind_filter = tk.StringVar(value=filters()[0][0])
        kf = ttk.Combobox(left, state='readonly', values=[lab for lab, _ in filters()],
                          textvariable=self.kind_filter, width=20)
        kf.pack(fill='x', pady=(2, 0))
        kf.bind('<<ComboboxSelected>>', lambda e: self.fill_list())
        ttk.Label(left, text=T('cr.search', 'Search')).pack(anchor='w', pady=(2, 0))
        self.search = tk.StringVar()
        ent = ttk.Entry(left, textvariable=self.search)
        ent.pack(fill='x')
        self.search.trace_add('write', lambda *a: self.fill_list())
        lf = ttk.Frame(left)
        lf.pack(fill='both', expand=True, pady=(2, 0))
        self.listbox = tk.Listbox(lf, width=20, height=6, exportselection=False, activestyle='none',
                                  bg=self.app.detail.cget('bg'), fg=self.app.detail.cget('fg'),
                                  selectbackground='#3a5f8a', selectforeground='white', highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(lf, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='left', fill='y')
        self.listbox.bind('<<ListboxSelect>>', lambda e: self.on_pick())
        self.count = ttk.Label(left, text='')
        self.count.pack(anchor='w')

        mid = self._mid = ttk.Frame(self.paned, padding=3)
        self.paned.add(mid, weight=4)
        self.title = ttk.Label(mid, text='', font=('Segoe UI', 12, 'bold'), justify='left')
        # wrapped at the column's width: a long name takes two lines instead of being cut (and never makes the
        # column ask for more room)
        self.title.bind('<Configure>', lambda e: self._title_wrap(), add='+')
        mid.bind('<Configure>', lambda e: self._title_wrap(), add='+')
        self.header = None
        if D2.CREATOR_ART and D2.active():                # D2 look: the game's stone, fonts and gear frame
            try:
                self.header = D2.CreatorHeader(mid, T('cr.title.editor', 'Item Editor') if self.edit_item else
                                               T('cr.title.creator', 'Item Creator'), getattr(self.app, 'cell', 32))
            except Exception as e:
                print('D2 look (creator header) disabled:', e)
                self.header = None
        if self.header is None:
            self.title.pack(side='top', anchor='w')

        bottom = ttk.Frame(mid)                          # packed before the scroll area: never pushed out of sight
        bottom.pack(side='bottom', fill='x', pady=(2, 0))
        self.status = ttk.Label(bottom, text='', wraplength=520, justify='left')
        self.status.pack(side='top', anchor='w', fill='x')
        self.status.bind('<Configure>', lambda e: self.status.configure(wraplength=max(200, e.width - 8)))
        outer = ttk.Frame(bottom)
        outer.pack(fill='x', pady=(2, 0))
        row = ttk.Frame(outer)                           # copies / stash page
        rowc, rowp = ttk.Frame(row), ttk.Frame(row)      # (side by side, or one above the other: too narrow)
        rowc.grid(row=0, column=0, sticky='w')
        rowp.grid(row=0, column=1, sticky='w')
        rowb = ttk.Frame(outer)                          # unrestricted / destination
        rowr = ttk.Frame(outer)                          # Close, Create
        # one line when the column is wide enough, else the buttons go under, else every group on its own line

        def fold(_e=None, st=[None], flips=[]):
            try:
                W = outer.winfo_width()
                a = rowc.winfo_reqwidth() + rowp.winfo_reqwidth()       # side by side: not what row asks now
                b, c = rowb.winfo_reqwidth(), rowr.winfo_reqwidth()
            except tk.TclError:
                return
            def need(W):
                return 1 if (W <= 1 or a + b + c + 8 <= W) else (2 if a + b <= W else (3 if a <= W else 4))
            lines = need(W)
            # Folding changes the width this column asks for, and the paned window answers by moving its
            # separators - which can unfold the row again: at 1280x720 the two layouts alternated for ever
            # (100 % CPU). So unfolding needs clearly more room than folding, and after a few switches within
            # a second the row stays as it is.
            if st[0] is not None and lines < st[0] and W > 1:
                lines = min(st[0], need(W - 48))
            if lines != st[0] and st[0] is not None:
                import time
                now = time.monotonic()
                flips[:] = [t for t in flips if now - t < 1.0]
                if len(flips) >= 3:
                    lines = st[0]
                else:
                    flips.append(now)
            if lines != st[0]:
                st[0] = lines
                rowp.grid(row=1 if lines == 4 else 0, column=0 if lines == 4 else 1, sticky='w')
                lines = min(lines, 3)
                for i in range(3):
                    outer.columnconfigure(i, weight=0)
                outer.columnconfigure(1 if lines < 3 else 0, weight=1)
                row.grid(row=0, column=0, sticky='w')
                rowb.grid(row=0 if lines < 3 else 1, column=1 if lines < 3 else 0, sticky='w')
                rowr.grid(row=lines - 1, column=2 if lines == 1 else (1 if lines == 2 else 0), sticky='e',
                          columnspan=1 if lines != 2 else 1, pady=(2, 0) if lines > 1 else 0)
                if lines == 2:
                    rowr.grid(row=1, column=0, columnspan=3, sticky='e')
        fold()
        for w in (outer, rowc, rowp, rowb):
            w.bind('<Configure>', fold)
        self.btn_ok = D2.button(rowr, T('cr.btn.replace', 'Replace item') if self.edit_item else
                                (T('cr.btn.create', 'Create') if self.target else T('cr.btn.create_stash', 'Create in stash')),
                                self.commit)
        self.btn_ok.pack(side='right')            # packed first: never squeezed out of the window
        D2.button(rowr, T('cr.btn.close', 'Close'), self.top.destroy).pack(side='right', padx=4)
        # bulk add: write N copies into the first N free spots (plain stash-create mode only)
        self.copies = tk.IntVar(value=1)
        self._copies_widgets = []
        if self.edit_item is None and self.target is None:
            ttk.Label(rowc, text=T('cr.copies', 'copies')).pack(side='left', padx=(2, 2))
            self.copies_spin = ttk.Spinbox(rowc, from_=1, to=100, textvariable=self.copies, width=4)
            self.copies_spin.pack(side='left')
            self._copies_widgets = [self.copies_spin]
            D2.button(rowc, T('cr.btn.fill_containers', 'All containers'), self.fill_containers).pack(side='left', padx=(6, 0))
        ttk.Label(rowp, text=T('cr.stash_page', 'Stash page')).pack(side='left', padx=(4, 0))
        self.page_current, self.page_first = T('cr.page.current', 'Current page'), T('cr.page.first_free', 'First free')
        self.page = tk.StringVar(value=self.page_current)
        ttk.Combobox(rowp, state='readonly', width=14, textvariable=self.page,
                     values=[self.page_current, self.page_first] + [str(i + 1) for i in range(STASH_PAGES)]).pack(side='left', padx=4)
        if settings.get('capy_unrestricted') is None:          # first start: unrestricted on (this build's point)
            settings.put('capy_unrestricted', True)
        self.unrestricted = tk.BooleanVar(value=bool(settings.get('capy_unrestricted')))
        ttk.Checkbutton(rowb, text=T('cr.unrestricted', 'Unrestricted'), variable=self.unrestricted,
                        command=self.set_unrestricted).pack(side='left', padx=(6, 0))
        self.dest = ttk.Label(rowb, text='')
        self.dest.pack(side='left', padx=4)

        self.scroll = ScrollFrame(mid)
        self.scroll.pack(side='top', fill='both', expand=True, pady=(2, 0))
        try:
            self.scroll.no_wheel(self.copies_spin)     # (self.scroll exists only from here on)
        except (AttributeError, KeyError):
            pass
        body = self.scroll.inner
        body.columnconfigure(0, weight=1)
        self.scroll.canvas.bind('<Configure>', self._rewrap, add='+')
        body.bind('<Configure>', self._rewrap, add='+')     # new content: built with the width known by then
        self.opts = ttk.Frame(body)
        self.opts.grid(row=0, column=0, sticky='we', pady=(0, 2))
        self.opts.columnconfigure(1, weight=1)
        bar = ttk.Frame(body)
        bar.grid(row=1, column=0, sticky='we', pady=(2, 0))
        self._vv_head = ttk.Label(bar, text=T('cr.variable_values', 'Variable values'), font=('Segoe UI', 10, 'bold'))
        self._vv_head.grid(row=0, column=0, sticky='w')
        # at the left, right after the heading (under it when the column is too narrow: _fit_opts)
        self._vv_btns = ttk.Frame(bar)
        self._vv_btns.grid(row=0, column=1, sticky='w')
        self._vv_under = False
        for t, how in ((T('cr.btn.min', 'Min'), 'min'), (T('cr.btn.random', 'Random'), 'random'), (T('cr.btn.max', 'Max'), 'max')):
            D2.button(self._vv_btns, t, lambda h=how: self.reroll(h), 6).pack(side='left', padx=(4, 0))

        class _Mods:
            pass
        self.mods_frame = _Mods()
        self.mods_frame.inner = ttk.Frame(body)
        self.mods_frame.inner.grid(row=2, column=0, sticky='we', pady=(4, 0))
        self.mods_frame.inner.columnconfigure(1, weight=1)

        right = ttk.Frame(self.paned, padding=3)
        self.paned.add(right, weight=1)
        app_detail = self.app.detail
        self.preview = tk.Text(right, width=20, wrap='word', bg=app_detail.cget('bg'),
                               fg=app_detail.cget('fg'), bd=0, padx=int(str(app_detail.cget('padx'))), pady=8,
                               font=app_detail.cget('font'), cursor='arrow', highlightthickness=0)
        psb = ttk.Scrollbar(right, orient='vertical', command=self.preview.yview)
        self.preview.configure(yscrollcommand=psb.set)
        psb.pack(side='right', fill='y')
        self.preview.pack(side='left', fill='both', expand=True)
        setup_detail_tags(self.preview)
        self.panel = PreviewPanel(self.preview, PreviewHost(self.app))
        self.update_dest()

    def _place_sashes(self):
        """Columns: list ~22 %, options ~50 %, preview ~28 % of the window (at least what the preview needs)."""
        if getattr(self, '_sash_busy', False):       # update_idletasks below runs other idle callbacks, this one
            return                                   # included: never nested (it spun at 100 % CPU at 1280x720)
        self._sash_busy = True
        try:
            self.top.update_idletasks()
            w = self.paned.winfo_width()
            if w < 50:
                return
            try:
                from tkinter import font as tkfont
                ch = tkfont.Font(font=self.preview.cget('font')).measure('0')
            except tk.TclError:
                ch = 7
            pw = max(26 * ch, min(int(w * 0.28), 66 * ch))
            lw = max(24 * ch, min(int(w * 0.22), 52 * ch))
            self._sash_w = w
            self.paned.sashpos(0, lw)
            self.paned.sashpos(1, max(lw + 30 * ch, w - pw))
        except tk.TclError:
            pass
        finally:
            self._sash_busy = False

    def _wrap_w(self):
        """Wrap width of the notes in the options column: the column's own width (520 before it is on screen)."""
        try:
            w = self.scroll.canvas.winfo_width()
            return max(200, w - 16) if w > 50 else 520
        except (tk.TclError, AttributeError):
            return 520

    def _rewrap(self, _e=None):
        """The options column changed width: its wrapped notes follow."""
        w = self._wrap_w()

        def walk(x):
            for c in x.winfo_children():
                try:
                    if getattr(c, '_wrap_less', False):
                        getattr(c, '_fit', lambda: None)()
                        continue                         # a value row's text: fitted by its own row
                    if c.winfo_class() == 'TLabel' and int(str(c.cget('wraplength')) or 0) not in (0, w):
                        c.configure(wraplength=w)
                except (tk.TclError, ValueError):
                    pass
                walk(c)
        try:
            walk(self.scroll.inner)
            self._slots_fit()
            self._fit_opts()
        except tk.TclError:
            pass
        self.scroll.refit(fresh=False)                   # re-fitted content may need the scrollbar no more

    def _title_wrap(self):
        try:
            w = max(120, self._mid.winfo_width() - 10)
            if int(str(self.title.cget('wraplength')) or 0) != w:
                self.title.configure(wraplength=w)
        except (tk.TclError, ValueError, AttributeError):
            pass

    def _fit_opts(self):
        """The options grid at the column's width: a row whose label and field do not fit side by side gets its
        field on a line of its own under the label (a small window, big fonts: 800x600 with the Xft fonts users
        get), and the Min / Random / Max buttons go under their heading. Decided from the column's width and
        the widgets' requested widths only - neither depends on this layout (the column's scroll area asks for
        a fixed width; its content is a canvas window) - so a second call changes nothing: no layout loop."""
        try:
            W = self.scroll.canvas.winfo_width()
        except (tk.TclError, AttributeError):
            return
        if W <= 50:                                      # not on screen yet: side by side (fitted on <Configure>)
            W = 1 << 20
        try:
            under = self._vv_head.winfo_reqwidth() + self._vv_btns.winfo_reqwidth() + 4 > W
            if under != self._vv_under:
                self._vv_under = under
                self._vv_btns.grid(row=1 if under else 0, column=0 if under else 1, sticky='w',
                                   padx=(8, 0) if under else 0)
        except (tk.TclError, AttributeError):
            pass

        def pad(info):
            p = info.get('padx', 0)
            p = p if isinstance(p, (tuple, list)) else str(p).split()
            return sum(int(float(x)) for x in p) if isinstance(p, (tuple, list)) else int(float(p or 0))
        rows = {}                                        # logical row -> [label or None, [fields]]
        for c in self.opts.grid_slaves():
            info = getattr(c, '_cr_grid', None)
            if info is None:                             # as render_options put it (logical row numbers)
                info = c._cr_grid = {k: v for k, v in c.grid_info().items() if k != 'in'}
                c._cr_stacked = None
            ent = rows.setdefault(int(info['row']), [None, []])
            if int(info['column']) == 0 and int(info.get('columnspan', 1)) == 1:
                ent[0] = c
            else:
                ent[1].append(c)
        if not rows:
            return
        need = {r: sum(f.winfo_reqwidth() + pad(f._cr_grid) for f in fs) for r, (_l, fs) in rows.items()}
        labw = {r: (l.winfo_reqwidth() + pad(l._cr_grid)) if l is not None else 0 for r, (l, _f) in rows.items()}
        stacked = set()
        for _ in range(3):                               # the label column is as wide as its widest label
            col0 = max([labw[r] for r in rows if r not in stacked and rows[r][1]] or [0])
            now = {r for r, (l, fs) in rows.items() if l is not None and fs and col0 + need[r] > W}
            if now == stacked:
                break
            stacked = now
        for r, (l, fs) in rows.items():
            st = r in stacked
            for c in ([l] if l is not None else []) + fs:
                if c._cr_stacked is st:
                    continue
                c._cr_stacked = st
                info = dict(c._cr_grid)
                info['row'] = 2 * r
                if st and c is l:
                    info['columnspan'] = 2
                elif st:                                 # indented under its label when there is room
                    info.update(row=2 * r + 1, column=0, columnspan=2,
                                padx=(12, 0) if need[r] - pad(c._cr_grid) + 12 <= W else 0)
                c.grid(**info)

    def _resashed(self, e):
        """The window changed width: the columns keep their shares (until a separator is dragged by hand)."""
        if e.widget is self.paned and not self._sash_user and abs(e.width - getattr(self, '_sash_w', 0)) > 8:
            self._sash_w = e.width
            if getattr(self, '_sash_job', None) is None:     # one pending placement, however many events arrive
                def run():
                    self._sash_job = None
                    self._place_sashes()
                self._sash_job = self.top.after(60, run)
            if os.environ.get('MXL_DEBUG_LAYOUT'):
                print('creator paned width', e.width, flush=True)

    def update_dest(self):
        if self.target is not None:
            self.dest.configure(text=f'-> {self.target_label}')
            return
        path = self.app.path
        self.dest.configure(text=f'-> {os.path.basename(path)}' if path else T('cr.no_stash', '-> (no stash open)'))

    # ------------------------------------------------------------------ catalog list
    def qkey(self):
        return dict(qualities()).get(self.quality.get(), getattr(self, '_q_override', 'unique'))

    def on_quality(self):
        self.fill_list()
        self.spec = None
        self.render_options()

    def _rw_has_base(self, i):
        cache = self.__dict__.setdefault('_rw_base_ok', {})
        if i not in cache:
            cache[i] = bool(self.cr.runeword_bases(i))
        return cache[i]

    def _bonus_warm(self):
        """Fills Creator.bonus_text for every unique / set item / runeword in short slices between events (the
        whole index takes ~2.5 s of tooltip building: done in one go it would freeze the first search). Started
        when the window opens, so it is normally complete before anything is typed; kept on the Creator."""
        cr = self.cr
        if getattr(cr, '_bonus_done', False) or getattr(self, '_bonus_job', None):
            return
        keys = [(kind, i) for kind, rows in (('unique', cr.uniques()), ('set', cr.set_items()), ('runeword', cr.runewords()))
                for i, _name, _x in rows]
        keys.sort(key=lambda k: k[0] != self.qkey())         # the list on screen first
        disk = _bonus_disk_key(cr)
        if disk is not None:                                 # the index of an earlier start (same tables, same
            got = _bonus_disk_load(disk)                     # editor files, same language): nothing to build
            if got is not None:
                cache = cr.__dict__.setdefault('_bonus_text', {})
                for k, v in got.items():
                    cache.setdefault(k, v)
                if all(k in cache for k in keys):
                    cr._bonus_done = True
                    if self.search.get().strip():
                        self.fill_list(only_if_changed=True)
                    return
        todo = iter(keys)

        def step():
            self._bonus_job = None
            try:
                if not self.top.winfo_exists():
                    return
                t0 = time.perf_counter()
                for key in todo:
                    cr.bonus_text(*key)
                    if time.perf_counter() - t0 > 0.012:
                        self._bonus_job = self.top.after(15, step)
                        return
                cr._bonus_done = True
                if disk is not None:
                    _bonus_disk_save(disk, cr.__dict__.get('_bonus_text', {}))
                if self.search.get().strip():
                    self.fill_list(only_if_changed=True)
            except tk.TclError:                              # window closed meanwhile: the next one goes on
                pass
        self._bonus_job = self.top.after(200, step)

    def fill_list(self, only_if_changed=False):
        q = self.qkey()
        s = self.search.get().strip().lower()
        fk = dict(filters()).get(self.kind_filter.get())
        orbs_only = fk == 'orb'
        dyes_only = fk == 'dye'
        kind = {'orb': 'misc', 'dye': 'misc'}.get(fk, fk)
        cr, d = self.cr, self.data
        rows = []
        if q in ('unique', 'set'):
            labels = cr.catalog_labels(q)
            for i, name, u in (cr.uniques() if q == 'unique' else cr.set_items()):
                b = d.base(u['code'])
                if kind and b.kind != kind or orbs_only and cr.orb_effects(u['code']) is None or dyes_only:
                    continue
                label = labels[i]                               # told apart where rows share a name
                rows.append((label, i))
            if q == 'unique':                                    # the relics by skill (their table order is none)
                rows.sort(key=lambda r: r[0].lower())
        elif q == 'angelic':
            for b in cr.angelic_bases():
                if kind and b.kind != kind:
                    continue
                rows.append((f"{clean(b.name)} [{kind_label(b.kind)}]", b.code))
        elif q == 'runeword':
            for i, name, runes in cr.runewords():
                if not self._rw_has_base(i):
                    continue                                 # no base can hold it (Secret Jewelwords...)
                label = f"{clean(name)} - {' '.join(clean(d.base(r).name).replace(' Rune', '') for r in runes)}"
                rows.append((label, i))
        else:
            picked = []
            for b in (self._craft_bases() if q == 'crafted' else self._honorific_bases() if q == 'tempered'
                      else self._bases()):
                if kind and b.kind != kind:
                    continue
                if q != 'normal' and b.kind == 'misc' and not cr.can_have_quality(b.code, q):
                    continue
                if q == 'superior' and not cr.superior_choices(b.code):
                    continue
                if q != 'normal' and not cr.can_have_quality(b.code, q):
                    continue
                if q in ('magic', 'rare') and b.kind == 'misc' and not cr.can_roll_affixes(b.code, q):
                    continue                                 # no affix can spawn on it (quest items, relics...)
                if b.code == 'gld ':
                    continue                                 # gold is not an item (character / stash gold)
                if orbs_only and cr.orb_effects(b.code) is None or dyes_only and cr.display_name(b.code) != 'Mystic Dye':
                    continue
                picked.append(b)
            rows = cr.base_list_rows(picked, kind_label)     # same names told apart: description, picture, code
            rows.sort(key=lambda r: r[0].lower())
        if s and q in ('unique', 'set', 'runeword'):
            # also by the bonuses the item comes with ("stormlord" -> Arrogance): name matches first, then the
            # rows whose bonus text matches, as far as the background index got (it refills the list at its end)
            bonus = cr.__dict__.get('_bonus_text', {})
            rows = ([r for r in rows if s in r[0].lower()]
                    + [r for r in rows if s not in r[0].lower() and s in bonus.get((q, r[1]), '')])
            self._bonus_warm()
        elif s:
            rows = [r for r in rows if s in r[0].lower()]
        if only_if_changed and rows == self.entries:
            return                                           # nothing new: the list and its selection stay
        self.entries = rows
        self.listbox.delete(0, 'end')
        if rows:
            self.listbox.insert('end', *[label for label, _ in rows])   # one call: typing stays instant
        self.count.configure(text=T('cr.entries', '{n} entries', n=len(rows)))

    def _bases(self):
        if not hasattr(self.cr, '_good_bases'):
            out = []
            for b in self.cr.bases():
                t = self.cr.t.item.get(b.code, {})
                name = clean(b.name)
                if not t.get('spawnable') or not name or name.lower() in ('unused', 'dummy'):
                    continue
                out.append(b)
            self.cr._good_bases = out
        return self.cr._good_bases

    def _honorific_bases(self):
        """Bases the honorific recipe takes (cube: magic / rare weapon or armor + Mark of Infusion): weapons and
        armor its input item type covers, which can carry a rare-style name."""
        if not hasattr(self.cr, '_honorific_bases'):
            out = []
            for b in self._bases():
                if b.kind not in ('weapons', 'armor') or not self.cr.honorific_stats(b.code):
                    continue
                names = self.cr.rare_name_choices(b.code)
                if names['rareprefix'] and names['raresuffix']:
                    out.append(b)
            self.cr._honorific_bases = out
        return self.cr._honorific_bases

    def _honorific_roll(self, how='max'):
        """A created honorific item's recipe stats (stat 289 = 2 'Orb Effects ... Doubled', Physical Resist 0-1%
        on armor, the weapon bonus) at their min / max / a random value, in the item's own stat list; stats
        added by hand stay as they are."""
        spec = self.spec
        lo = {(x['id'], x.get('param')): x['value'] for x in self.cr.honorific_stats(spec['code'], 'min')}
        hi = {(x['id'], x.get('param')): x['value'] for x in self.cr.honorific_stats(spec['code'], 'max')}
        extra = spec.setdefault('extra', [])
        for k, top in hi.items():
            a, b = sorted((lo.get(k, top), top))
            v = b if how == 'max' else a if how == 'min' else random.randint(a, b)
            e = next((e for e in extra if (e['id'], e.get('param')) == k), None)
            if e is None:
                extra.append(dict(id=k[0], param=k[1], value=v))
            else:
                e['value'] = v

    def _craft_bases(self):
        """Bases a crafting recipe takes (Angelic bases included, they are not in the drop pool)."""
        if not hasattr(self.cr, '_craft_bases'):
            out = []
            for b in self.cr.bases():
                name = clean(b.name)
                if not name or name.lower() in ('unused', 'dummy'):
                    continue
                if self.cr.craft_rows(b.code):
                    out.append(b)
            self.cr._craft_bases = out
        return self.cr._craft_bases

    def on_pick(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        key = self.entries[sel[0]][1]
        q = self.qkey()
        cr = self.cr
        if q in ('unique', 'set'):
            spec = cr.new_spec(q, row=key)
        elif q == 'runeword':
            bases = cr.runeword_bases(key)
            if not bases:
                self.set_status(T('cr.no_rw_base', 'No base item can hold this runeword.'), error=True)
                return
            spec = cr.new_spec('runeword', bases[0].code, key)
            spec['sockets'] = len(self.data.runewords[key][1])
        elif q == 'angelic':
            spec = cr.new_spec('rare', key)                # Angelic items are rares on the Angelic bases
        else:
            spec = cr.new_spec(q, key)
        spec['ilvl'] = max(spec['ilvl'], min(99, MAX_ILVL))
        spec['max_sockets'] = q in ('unique', 'set', 'crafted', 'tempered')   # as the game gives them (Sacred gear)
        if q == 'tempered':                    # the cube recipe's output: a blank item, a rare-style name, the
            spec['extra'] = []                 # maximum sockets and the recipe's own stats (in its stat list)
            spec['_new_flag'] = True           # header flag 0x2000, as on the real sample (XBone's Eagle Pelt)
            self.spec, old = spec, self.spec
            try:
                self._honorific_roll('max')
            finally:
                self.spec = old
        self.prepare_defaults(spec)
        if q == 'crafted':                     # one roll, as the cube gives it: name, affixes, values
            cr.reroll_crafted(spec)
        else:
            cr.roll(spec, 'max')
        self.spec = spec
        self.render_options()

    def prepare_defaults(self, spec):
        """Picks the first legit option wherever one is required (innate affix, superior bonus, names...)."""
        cr, code, q, ilvl = self.cr, spec['code'], spec['quality'], spec['ilvl']
        autos = cr.auto_choices(code, ilvl)              # every quality has its base's innate affix (Sigma)
        ids = [a for a, _, _ in autos]
        keep_none = bool(spec.get('extra')) and not spec.get('auto')   # edited item without one
        if ids and spec.get('auto') not in ids and not keep_none:
            spec['auto'] = ids[-1]
        if not ids:
            spec['auto'] = None
        if keep_none:
            spec['auto'] = None
        if q == 'superior' and spec.get('superior') not in cr.superior_choices(code):
            ch = cr.superior_choices(code)
            spec['superior'] = ch[-1] if ch else None
        if q == 'runeword' and spec.get('superior') is not None and spec['superior'] not in cr.superior_choices(code):
            spec['superior'] = None
        if q == 'magic':
            for kind, key in (('magicprefix', 'prefix'), ('magicsuffix', 'suffix')):
                ok = {i for i, _, _ in cr.affix_choices(kind, code, ilvl)}
                if spec.get(key) not in ok:
                    spec[key] = None
            if not spec.get('prefix') and not spec.get('suffix'):
                ch = cr.affix_choices('magicprefix', code, ilvl) or []
                if ch:
                    spec['prefix'] = ch[-1][0]
                else:
                    ch = cr.affix_choices('magicsuffix', code, ilvl)
                    spec['suffix'] = ch[-1][0] if ch else None
        if q == 'crafted':
            rows = cr.craft_rows(code)
            if spec.get('craft') not in rows and not (spec.get('extra') and not rows):
                spec['craft'] = rows[0] if rows else None
            names = cr.rare_name_choices(code)
            rn = spec.get('rare_names')
            if not rn or rn[0] not in [i for i, _ in names['rareprefix']] or rn[1] not in [i for i, _ in names['raresuffix']]:
                spec['rare_names'] = (names['rareprefix'][0][0] if names['rareprefix'] else 0,
                                      names['raresuffix'][0][0] if names['raresuffix'] else 0)
            for kind, key in (('magicprefix', 'rare_prefixes'), ('magicsuffix', 'rare_suffixes')):
                ok = {i for i, _, _ in cr.affix_choices(kind, code, ilvl, rare=True)}
                spec[key] = [x for x in (spec.get(key) or []) if x in ok]
        if q in ('rare', 'tempered'):
            names = cr.rare_name_choices(code)
            rn = spec.get('rare_names')
            if not rn or rn[0] not in [i for i, _ in names['rareprefix']] or rn[1] not in [i for i, _ in names['raresuffix']]:
                spec['rare_names'] = (names['rareprefix'][0][0] if names['rareprefix'] else 0,
                                      names['raresuffix'][0][0] if names['raresuffix'] else 0)
        if q == 'rare':
            for kind, key in (('magicprefix', 'rare_prefixes'), ('magicsuffix', 'rare_suffixes')):
                ok = {i for i, _, _ in cr.affix_choices(kind, code, ilvl, rare=True)}
                spec[key] = [x for x in (spec.get(key) or []) if x in ok]
            if not spec['rare_prefixes'] or not spec['rare_suffixes'] or len(spec['rare_prefixes']) + len(spec['rare_suffixes']) < 3:
                for kind, key, n in (('magicprefix', 'rare_prefixes', 2), ('magicsuffix', 'rare_suffixes', 2)):
                    groups = {self.data.affixes[kind][x - 1]['group'] for x in spec[key]}
                    for i, _, a in reversed(cr.affix_choices(kind, code, ilvl, rare=True)):
                        if len(spec[key]) >= n:
                            break
                        if a['group'] not in groups:
                            spec[key].append(i)
                            groups.add(a['group'])
        ms = cr.max_sockets(code, ilvl)
        if q != 'runeword':
            spec['sockets'] = ms if spec.get('max_sockets') else min(spec.get('sockets') or 0, ms)
            spec['sockets'] = max(spec['sockets'], cr.innate_sockets(spec))   # the innate's sockets (Angelic...)
            kept = spec.get('_kept')
            if kept:                                     # an edited item's jewels...: they take sockets too
                picks = [c for c in spec.get('socketed', []) if c][:spec['sockets']]
                spec['_kept'] = kept[:max(0, spec['sockets'] - len(picks))]
                spec['socketed'] = picks[:spec['sockets'] - len(spec['_kept'])]
            else:
                spec['socketed'] = spec.get('socketed', [])[:spec['sockets']]
        b = self.data.base(code)
        if b.stack_max is not None and not spec.get('quantity'):
            spec['quantity'] = b.stack_max
        if spec.get('ethereal') and (q == 'set' or b.kind not in ('weapons', 'armor')):
            spec['ethereal'] = False
        n_img = cr.image_count(code)
        if n_img and spec.get('image') is None:
            spec['image'] = 0
        if not n_img:
            spec['image'] = None

    def load_spec(self, spec):
        q = spec['quality']
        if q == 'rare' and spec.get('code') and self.cr.is_angelic(spec['code']):
            q = 'angelic'
        self._q_override = q
        self.quality.set(next((l for l, k in qualities() if k == q), T(f'cr.quality.{q}', q.capitalize())))
        self.fill_list()
        self.spec = spec
        if not spec.get('_from_item'):        # an edited item opens exactly as it is (even outside the rules)
            self.prepare_defaults(spec)
        self.render_options()

    # ------------------------------------------------------------------ options
    def render_options(self):
        for w in self.opts.winfo_children():
            w.destroy()
        self.scroll.refit()
        self._clear_mods()
        self.mod_vars = {}
        self.number_rows = {}                # roll source (or 'defense') -> its number field
        self._spins = {w: rec for w, rec in self._spins.items() if w.winfo_exists()}
        spec = self.spec
        if spec is None:
            self._slots_drop()
            self.title.configure(text=T('cr.choose', 'Choose an item in the list'))
            self._header(None)
            self.panel.show(None)
            self.set_status('')
            self.btn_ok.state(['disabled'])
            return
        cr, d, q, code = self.cr, self.data, spec['quality'], spec['code']
        spec['unrestricted'] = bool(self.unrestricted.get())     # free values: used by mods() / validate() / build()
        b = d.base(code)
        self.title.configure(text=title_text(clean(cr.describe(spec)), clean(b.name)))
        f = self.opts
        r = 0
        NONE = none_label()

        def row(label):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky='nw', padx=(0, 8), pady=2)
            r += 1
            return r - 1

        def combo(label, values, current, on_change, width=40, stretch=True, search=True, tail=None):
            """Read-only combobox; on_change(index in values). Each call keeps its own list (no shared variable).
            tail(frame): widgets right of the field (the field then sits in a frame of its own, left)."""
            rr = row(label)
            values = list(values)
            var = tk.StringVar(value=current)
            host = f
            if tail is not None:
                host = ttk.Frame(f)
                host.grid(row=rr, column=1, sticky='we' if stretch else 'w', pady=2)
            if search and len(values) > LONG_LIST:       # affixes, socket fillers...: type to search
                c = self._name_field(host, values, var, lambda: on_change(values.index(var.get()))
                                     if var.get() in values else None, 12 if stretch else min(width, 24),
                                     label.strip(), clip=stretch)
                if tail is not None:
                    c.pack(side='left', fill='x' if stretch else None, expand=stretch)
                    tail(host)
                else:
                    c.grid(row=rr, column=1, sticky='we' if stretch else 'w', pady=2)
                return c, rr
            # stretched: it asks for little and takes the column's width (40 characters asked for made the column
            # wider than an 800x600 window had room for); its list opens as wide as its longest entry
            c = ttk.Combobox(host, state='readonly', values=values, textvariable=var,
                             width=STRETCH_CHARS if stretch else width)
            if stretch:
                wide_popdown(c)
            if tail is not None:
                c.pack(side='left', fill='x' if stretch else None, expand=stretch)
                tail(host)
            else:
                c.grid(row=rr, column=1, sticky='we' if stretch else 'w', pady=2)
            self.scroll.no_wheel(c)

            def picked(_e, var=var, values=values, on_change=on_change):
                v = var.get()
                if v in values:
                    on_change(values.index(v))
            c.bind('<<ComboboxSelected>>', picked)
            return c, rr

        def spin(label, lo, hi, cur, on_change):
            vals = [str(v) for v in range(lo, hi + 1)]
            return combo(label, vals, str(cur), lambda i, vals=vals: on_change(int(vals[i])), 8, False, False)

        if q == 'runeword':
            bases = cr.runeword_bases(spec['row'])
            labels = [f"{clean(x.name)} [{kind_label(x.kind)}]" for x in bases]
            cur = next((labels[i] for i, x in enumerate(bases) if x.code == code), '')
            combo(T('cr.base_item', 'Base item'), labels, cur, lambda i, bases=bases: self.set_base(bases[i].code))
            sup = cr.superior_choices(code)
            vals = [NONE] + [self.sup_label(i) for i in sup]
            combo(T('cr.superior', 'Superior'), vals, self.sup_label(spec['superior']) if spec.get('superior') is not None else NONE,
                  lambda i, sup=sup: self.set_field('superior', None if i == 0 else sup[i - 1]))
        spin(T('cr.item_level', 'Item level'), cr.min_ilvl(spec), MAX_ILVL, spec['ilvl'], lambda v: self.set_field('ilvl', v))
        if b.kind in ('weapons', 'armor') and q != 'set':
            rr = row(T('cr.ethereal', 'Ethereal'))
            ev = tk.BooleanVar(value=spec['ethereal'])
            ttk.Checkbutton(f, variable=ev, command=lambda ev=ev: self.set_field('ethereal', ev.get())).grid(row=rr, column=1, sticky='w')
        ms = cr.max_sockets(code, spec['ilvl'])
        if q == 'runeword':
            rr = row(T('cr.sockets', 'Sockets'))
            ttk.Label(f, text=T('cr.rw_sockets', '{n} (runes socketed automatically)', n=spec['sockets'])).grid(row=rr, column=1, sticky='w')
            filled = cr.fillers(spec)                    # an edited runeword's jewels...: each can be taken out
            for x in filled:
                rr = row(T('cr.socket_n', '  Socket {n}', n=x['index'] + 1))
                host = ttk.Frame(f)
                host.grid(row=rr, column=1, sticky='w', pady=2)
                ttk.Label(host, text=clean(x['name'])).pack(side='left')
                self._filler_x(host, filled.index(x))
        elif ms:
            rr = row(T('cr.sockets', 'Sockets'))
            box = ttk.Frame(f)
            box.grid(row=rr, column=1, sticky='w', pady=2)
            inn = cr.innate_sockets(spec)                    # given by the innate affix: never fewer
            c2 = ttk.Combobox(box, state='readonly', width=6, values=[str(v) for v in range(inn, ms + 1)])
            c2.set(str(spec['sockets']))
            c2.pack(side='left')
            self.scroll.no_wheel(c2)
            c2.bind('<<ComboboxSelected>>', lambda e, c2=c2: self.set_sockets(int(c2.get())))
            mv = tk.BooleanVar(value=bool(spec.get('max_sockets')))
            ttk.Checkbutton(box, text=T('cr.max_sockets', 'Max sockets ({n})', n=ms), variable=mv,
                            command=lambda mv=mv: self.set_max_sockets(mv.get())).pack(side='left', padx=(10, 0))
            filled = cr.fillers(spec)
            if filled:
                ttk.Button(box, text=T('cr.sockets_clear', 'Empty sockets'),
                           command=self.clear_fillers).pack(side='left', padx=(10, 0))
            fill = cr.sockets_fillers()
            EMPTY = empty_label()
            kept = [x for x in filled if x['kind'] == 'item']
            n_pick = max(0, spec['sockets'] - len(kept))
            for k in range(n_pick):
                cur = spec['socketed'][k] if k < len(spec['socketed']) else None
                opts = list(fill)
                if cur and all(c_ != cur for c_, _n in fill):      # a socketed item outside the list (Mystic Orb...)
                    opts.append((cur, d.base(cur).name if cur in d.bases else cur.strip()))
                vals = [EMPTY] + [clean(n) for _, n in opts]
                curl = next((clean(n) for c_, n in opts if c_ == cur), EMPTY)
                n = next((j for j, x in enumerate(filled) if x['kind'] == 'pick' and x['slot'] == k), None)
                combo(T('cr.socket_n', '  Socket {n}', n=k + 1), vals, curl,
                      lambda i, k=k, opts=opts: self.set_socket(k, None if i == 0 else opts[i - 1][0]),
                      tail=None if n is None else (lambda host, n=n: self._filler_x(host, n)))
            for k, x in enumerate(kept):
                rr = row(T('cr.socket_n', '  Socket {n}', n=n_pick + k + 1))
                host = ttk.Frame(f)
                host.grid(row=rr, column=1, sticky='w', pady=2)
                ttk.Label(host, text=clean(x['name'])).pack(side='left')
                self._filler_x(host, filled.index(x))
        n_img = cr.image_count(code)
        if n_img > 1:
            spin(T('cr.picture', 'Picture'), 1, n_img, (spec.get('image') or 0) + 1, lambda v: self.set_field('image', v - 1))
        if b.stack_max is not None:
            spin(T('cr.quantity', 'Quantity'), 1, min(b.stack_max, 511), spec.get('quantity') or 1, lambda v: self.set_field('quantity', v))
        if True:
            autos = cr.auto_choices(code, spec['ilvl'])
            if autos:
                vals = [lab for _, lab, _ in autos]
                cur = next((lab for i, lab, _ in autos if i == spec.get('auto')), vals[-1])
                combo(T('cr.innate', 'Innate affix'), vals, cur, lambda i, autos=autos: self.set_field('auto', autos[i][0]))
        if q == 'superior':
            sup = cr.superior_choices(code)
            vals = [self.sup_label(i) for i in sup]
            combo(T('cr.superior_bonus', 'Superior bonus'), vals, self.sup_label(spec['superior']),
                  lambda i, sup=sup: self.set_field('superior', sup[i]))
        if q == 'magic':
            for kind, key, lab in (('magicprefix', 'prefix', T('cr.prefix', 'Prefix')), ('magicsuffix', 'suffix', T('cr.suffix', 'Suffix'))):
                ch = cr.affix_choices(kind, code, spec['ilvl'])
                vals = [NONE] + [l for _, l, _ in ch]
                cur = next((l for i, l, _ in ch if i == spec.get(key)), NONE)
                combo(lab, vals, cur, lambda i, key=key, ch=ch: self.set_field(key, None if i == 0 else ch[i - 1][0]))
        if q == 'crafted':
            ch = cr.craft_choices(code)
            vals = [lab for _, lab in ch]
            cur = next((lab for i, lab in ch if i == spec.get('craft')), NONE)
            combo(T('cr.recipe', 'Shrine / recipe'), vals or [NONE], cur,
                  lambda i, ch=ch: self.set_craft(ch[i][0]) if ch else None)
            if ch:
                rr = row('')
                D2.button(f, T('cr.btn.reroll', 'Reroll item'), self.reroll_crafted).grid(row=rr, column=1, sticky='w', pady=2)
        if q in ('rare', 'crafted', 'tempered'):
            names = cr.rare_name_choices(code)
            rn = spec['rare_names']
            for n, kind, lab in ((0, 'rareprefix', T('cr.name1', 'Name (1st word)')), (1, 'raresuffix', T('cr.name2', 'Name (2nd word)'))):
                lst = names[kind]
                vals = [clean(t) for _, t in lst]
                cur = next((clean(t) for i, t in lst if i == rn[n]), vals[0] if vals else '')
                combo(lab, vals, cur, lambda i, n=n, lst=lst: self.set_rare_name(n, lst[i][0]))
            for kind, key, lab in ((('magicprefix', 'rare_prefixes', T('cr.prefix', 'Prefix')), ('magicsuffix', 'rare_suffixes', T('cr.suffix', 'Suffix')))
                                   if q != 'tempered' else ()):
                ch = cr.affix_choices(kind, code, spec['ilvl'], rare=True)
                for k in range(3):
                    cur_id = spec[key][k] if k < len(spec[key]) else None
                    taken = {}                                    # group -> slot name of the other chosen affixes
                    for j, sid in enumerate(spec[key]):
                        if j != k:
                            g = d.affixes[kind][sid - 1]['group']
                            if g:
                                taken[g] = f'{lab} {j + 1}'
                    vals = [NONE]
                    for i, l, a in ch:
                        if a['group'] in taken and i != cur_id:
                            l = f"{l}   ! {T('cr.same_group_mark', 'same group as {slot}', slot=taken[a['group']])}"
                        vals.append(l)
                    cur = next((vals[n + 1] for n, (i, _, _) in enumerate(ch) if i == cur_id), NONE)
                    combo(f'{lab} {k + 1}', vals, cur, lambda i, key=key, k=k, ch=ch:
                          self.set_rare_affix(key, k, None if i == 0 else ch[i - 1][0]))
        corr = cr.corrupt_choices(spec)
        if corr or spec.get('corrupt') is not None:
            vals = [T('cr.cor.none', '(not corrupted)')] + [lab for _, _, _, lab in corr]
            cur = next((lab for rw, _, _, lab in corr if rw == spec.get('corrupt')), vals[0])
            rr = row(T('cr.corruption', 'Corruption'))
            box = ttk.Frame(f)
            box.grid(row=rr, column=1, sticky='we', pady=2)
            box.columnconfigure(0, weight=1)
            var = tk.StringVar(value=cur)
            # (asks for less than the other boxes: the button beside it has to fit too - it takes the rest)
            c = ttk.Combobox(box, state='readonly', values=vals, textvariable=var, width=STRETCH_CHARS - 4)
            c.grid(row=0, column=0, sticky='we')
            wide_popdown(c)
            self.scroll.no_wheel(c)

            def corrupt_picked(_e, var=var, vals=vals, corr=corr):
                v = var.get()
                if v in vals:
                    i = vals.index(v)
                    self.set_corrupt(None if i == 0 else corr[i - 1][0])
            c.bind('<<ComboboxSelected>>', corrupt_picked)
            if corr:
                D2.button(box, T('cr.btn.corrupt_roll', 'Roll like the cube'), self.roll_corrupt).grid(
                    row=0, column=1, padx=(6, 0))
        if b.kind == 'armor':
            lo, hi = cr.defense_range(spec)
            if lo != hi or spec.get('_defense_raw'):
                if spec.get('defense') is None or not lo <= spec['defense'] <= hi and not spec.get('_defense_raw'):
                    spec['defense'] = hi
                cur = spec['defense']
                self.number_rows['defense'] = self.number_row(
                    self.opts, r, T('cr.base_defense', 'Base defense'), min(lo, cur), max(hi, cur), cur,
                    lambda v: self.set_field('defense', v, False), option=True)
                r += 1
            else:
                rr = row(T('cr.base_defense', 'Base defense'))
                ttk.Label(f, text=T('cr.def_fixed', '{v} (fixed: Enhanced Defense)', v=lo)).grid(row=rr, column=1, sticky='w')
        self._fit_opts()
        self.render_mods()
        self.refresh()

    def sup_label(self, i):
        if i is None:
            return none_label()
        txt = []
        for m in self.data.quality_mods[i]:
            lo, hi = sorted((m['min'], m['max']))
            st = mods_stats([(m['prop'], m['param'], m['min'], m['max'])], self.data)
            desc = next((self.data.isc[x['id']]['desc'] for x in st if self.data.isc[x['id']]['desc']), '?')
            txt.append(f"{desc.replace('%d%%', '').replace('%d', '').strip()} {lo}-{hi}")
        return f"[{i}] " + '; '.join(txt)

    def number_row(self, parent, r, label, lo, hi, cur, on_change, fmt=str, range_w=0, field_w=0, option=False):
        """One compact row per rollable value: a typed number field, the range as [min-max] and the value's text
        (field first: it stays in sight however narrow the column is).
        Digits only; a number inside the range is applied (and previewed) while typing, Return / leaving the
        field / pressing any button clamps what is typed to the range. Up / Down step by 1, Page Up / Down by
        10; the mouse wheel steps the field that has the keyboard focus (over any other field it scrolls the
        page, so scrolling never changes a value by accident). on_change(value) is what the slider's release
        called. fmt: the name of a value that stands for a skill / monster, shown under the text.
        range_w / field_w: common widths (characters) of a block of rows, so their fields line up.
        option: a row of the options grid above (label column | field and range).
        Returns the entry (.set_value(v) / .step(d) for tests)."""
        box = ttk.Frame(parent)
        if option:
            ttk.Label(parent, text=label).grid(row=r, column=0, sticky='nw', padx=(0, 8), pady=2)
            box.grid(row=r, column=1, sticky='w', pady=1)
            label = ''
        else:
            box.grid(row=r, column=0, columnspan=2, sticky='we', pady=1)
        box.columnconfigure(2, weight=1)
        rng = T('cr.range_box', '[{lo}-{hi}]', lo=lo, hi=hi) if lo >= 0 else \
            T('cr.range_box_neg', '[{lo} to {hi}]', lo=lo, hi=hi)
        digits = max(len(str(lo)), len(str(hi)), 4, field_w - 1) + 1
        lab = ttk.Label(box, text=label, justify='left')
        lab._wrap_less = True                    # _rewrap: this label shares its line with the field and the range
        lab.grid(row=0, column=2, sticky='w', padx=(4, 0))
        var = tk.StringVar(value=str(cur))
        ent = ttk.Entry(box, textvariable=var, width=digits, justify='right')
        ent.grid(row=0, column=0, sticky='w', padx=(0, 2))
        rl = ttk.Label(box, text=rng, width=max(range_w, len(rng)), anchor='w')
        rl.grid(row=0, column=1, sticky='w')
        name = None
        if fmt is not str:
            name = ttk.Label(box, text=fmt(cur), justify='left')
            name.grid(row=1, column=0, columnspan=3, sticky='w', padx=(12, 0))
            name._wrap_less = True
        st = {'v': cur, 'job': None}
        try:
            normal_fg = str(ent.cget('foreground')) or ''
        except tk.TclError:
            normal_fg = ''

        def fit(_e=None):
            try:
                w = self._wrap_w() - ent.winfo_reqwidth() - rl.winfo_reqwidth() - 12
                if w > 60 and int(str(lab.cget('wraplength')) or 0) != w:
                    lab.configure(wraplength=w)
            except (tk.TclError, ValueError):
                pass
        box.bind('<Configure>', fit)
        lab._fit = fit

        def parsed():
            try:
                return int(var.get().strip())
            except (ValueError, tk.TclError):
                return None

        def apply(v):
            st['job'] = None
            if v == st['v']:
                return
            st['v'] = v
            if name is not None:
                try:
                    name.configure(text=fmt(v))
                except tk.TclError:
                    pass
            on_change(v)

        def typed(*_a):
            """While typing: a number inside the range is previewed shortly after the last key."""
            v = parsed()
            ok = v is not None and lo <= v <= hi
            try:
                ent.configure(foreground=normal_fg if ok else '#e05a4a')
                if st['job'] is not None:
                    ent.after_cancel(st['job'])
                    st['job'] = None
                if ok and v != st['v']:
                    st['job'] = ent.after(250, lambda: apply(v))
            except tk.TclError:
                pass

        def commit(_e=None):
            """Return / focus out / a button press: what is typed, clamped to the range (nothing typed: as it was)."""
            v = parsed()
            v = st['v'] if v is None else max(lo, min(hi, v))
            try:
                if st['job'] is not None:
                    ent.after_cancel(st['job'])
                    st['job'] = None
                if var.get() != str(v):
                    var.set(str(v))
                ent.configure(foreground=normal_fg)
            except tk.TclError:
                pass
            apply(v)

        def step(d):
            v = parsed()
            v = st['v'] if v is None else v
            var.set(str(max(lo, min(hi, v + d))))
            commit()
            try:
                ent.icursor('end')
            except tk.TclError:
                pass
            return 'break'

        def wheel_v(n, e):
            try:
                focused = ent.focus_get() is ent
            except (KeyError, tk.TclError):
                focused = False
            if not focused:
                return self.scroll._wheel_v(n, e)
            return step(-n)                       # one step per notch; up = more

        def wheel_x(n, e):
            return self.scroll._wheel_x(n, e)

        def key_ok(text):
            return text in ('', '-') or bool(re.fullmatch(r'-?\d{1,11}', text)) and (lo < 0 or text[0] != '-')
        ent.configure(validate='key', validatecommand=(ent.register(key_ok), '%P'))
        var.trace_add('write', typed)
        ent.bind('<Return>', commit)
        ent.bind('<KP_Enter>', commit)
        ent.bind('<FocusOut>', commit)
        ent.bind('<Up>', lambda e: step(1))
        ent.bind('<Down>', lambda e: step(-1))
        ent.bind('<Prior>', lambda e: step(10))
        ent.bind('<Next>', lambda e: step(-10))
        mxl_scroll.bind_wheel(ent, wheel_v, wheel_x)
        self._spins[ent] = [commit, None]        # a number still being typed is committed before any button runs
        ent.set_value = lambda v: (var.set(str(v)), commit())[-1]
        ent.step = step
        ent.value_range = (lo, hi)
        return ent

    def value_format(self, m):
        """Display of a rolled value: monster or skill name for the 'random skill / monster' properties."""
        d = self.data
        if d.prop_func[m.prop] != 12:
            return str
        sid = next((x for x in d.props[m.prop] if x >= 0), None)
        desc = (d.isc[sid]['desc'] if sid is not None else '') or ''
        if 'eanimate' in desc and getattr(d, 'monster_names', None):
            return lambda v: clean(d.monster_names[v]) if 0 <= v < len(d.monster_names) and d.monster_names[v] else str(v)
        return lambda v: clean(d.skill(v))

    def mod_label(self, m):
        d = self.data
        stats = m.stats(d)
        for s in stats:
            if stat_hidden(s['id'], d, s['value']):
                continue
            try:
                txt = clean(stat_label(dict(s, desc=d.isc[s['id']]['desc']), d))
            except Exception:
                txt = ''
            if txt and 'BUFFALO' not in txt:
                return txt
        return T('cr.hidden_stat', '(hidden stat {id})', id=stats[0]['id']) if stats else '?'

    def render_mods(self):
        inner = self.mods_frame.inner
        self.scroll.refit()
        self._clear_mods()
        unr = self.unrestricted.get()          # the spec flag itself is set in render_options / current_blob
        mods = [m for m in self.cr.mods(self.spec) if m.variable]
        raw_extra = [x for x in self.spec.get('extra') or [] if self.cr._visible(x)]
        table = self.edit_item is not None and (unr or raw_extra)
        if not mods and not raw_extra and not unr and not table:
            self._slots_drop()
            ttk.Label(inner, text=T('cr.no_variable', 'No variable values: everything on this item is fixed.'),
                      wraplength=self._wrap_w(), justify='left').grid(row=0, column=0, sticky='w')
            return
        r = 0
        if raw_extra and not unr and not table:
            from mxl_tooltip import stat_lines
            try:
                lines = [str(x[1]).strip() for x in stat_lines(raw_extra, self.data, None) if str(x[1]).strip()]
            except Exception:
                lines = [f"stat {x['id']}: {x['value']}" for x in raw_extra]
            made = self.spec.get('quality') == 'tempered' and not self.spec.get('_from_item')
            ttk.Label(inner, text=(T('cr.honorific_list', 'Honorific recipe (Min / Random / Max roll it): {lines}',
                                     lines='; '.join(lines)) if made else
                                   T('cr.kept_list', 'Kept as they are on the item (not from its affixes or its recipe): {lines}',
                                     lines='; '.join(lines))), wraplength=self._wrap_w(), justify='left').grid(row=r, column=0, columnspan=2, sticky='w')
            r += 1
        elif unr:
            note = (T('cr.slots.note_edit', 'Unrestricted: the item\'s own stat list is below as attribute slots; '
                      'a value the format cannot store is capped.')
                    if table else
                    T('cr.slots.note', 'Unrestricted: the values below can go anywhere the save format holds (a '
                      'value the format cannot store is warned about, never written). Any other attribute goes '
                      'into the slots under them.'))
            ttk.Label(inner, text=note, wraplength=self._wrap_w(), justify='left').grid(
                row=r, column=0, columnspan=2, sticky='w')
            r += 1
        rows = []
        for m in mods:
            lo, hi = m.min, m.max
            if unr and m.variable:                       # free value: the whole storable range of its stat
                rng = self.cr.storage_range(m)
                if rng:
                    lo, hi = min(m.min, rng[0]), max(m.max, rng[1])
            rows.append((m, lo, hi))
        range_w = max([len(f'[{lo}-{hi}]') if lo >= 0 else len(f'[{lo} to {hi}]') for _m, lo, hi in rows] or [0])
        range_w = min(range_w, 14)                       # one column of fields; a huge free range may stick out
        field_w = min(max([len(str(v)) for _m, lo, hi in rows for v in (lo, hi)] or [0]) + 1, 8)
        for m, lo, hi in rows:
            label = f"{T('cr.mod.' + m.label.lower(), m.label) + ': ' if m.label else ''}{self.mod_label(m)}"
            self.number_rows[m.source] = self.number_row(
                inner, r, label, lo, hi, m.value, lambda v, src=m.source: self.set_roll(src, v),
                self.value_format(m), range_w, field_w)
            r += 1
        if unr or table:
            # the attribute slots: an edited item's own stats as the game shows them (table), else the raw
            # stats added to the created item; a runeword's own list is a section of the same slot list
            r = self._slots_place(inner, r, table)
            r = self._orange_text(inner, r)               # unique orange text (display + hidden effect)
        else:
            self._slots_drop()

    def _spin_commit(self, spin, setter):
        """Commits a spinbox / entry on Return, focus out and the arrows (keeping the keyboard focus).
        The toplevel <Button-1> handler commits it before a button's command runs, too: a ttk button
        does not take the focus when clicked (on X11), so a number typed right before clicking
        Replace used to stay uncommitted and the item was written with the old value."""
        def run(_e=None):
            try:
                setter()
            except Exception as e:
                print('spin commit:', e)
            rec = self._spins.get(spin)
            if rec is not None:
                try:
                    rec[1] = spin.get()
                except Exception:
                    pass
        spin.bind('<Return>', run)
        spin.bind('<FocusOut>', run)
        spin.bind('<<Increment>>', run)
        spin.bind('<<Decrement>>', run)
        try:
            self._spins[spin] = [setter, spin.get()]
        except Exception:
            self._spins[spin] = [setter, None]

    def _press_commit_spin(self, _e=None):
        """Commits the spinbox the user is still typing in on the press of any button (before the
        release that runs the button's command - see _spin_commit)."""
        try:
            w = self.top.focus_get()
        except (KeyError, tk.TclError):
            return
        if self._slots_alive() and self.slots._ed is not None and \
                getattr(_e, 'widget', None) not in (self.slots.cv, self.slots.ed):
            self.slots._ed_done('keep')        # a number still open in a slot's value box: taken first
        rec = self._spins.get(w) if w is not None else None
        if rec is None:
            return
        try:
            if w.get() != rec[1]:
                rec[0]()
                rec[1] = w.get()
        except Exception as e:
            print('spin commit:', e)

    # --------------------------------------------------------------- searchable pickers (mxl_attr_picker)
    def _stat_labels(self):
        """{stat id: label} of every stat the save format holds, as the categorised picker lists them."""
        cache = self.cr.__dict__.get('_ap_labels')
        if cache is None:
            cache = self.cr._ap_labels = {sid: lab for sid, lab, _c in
                                          AP.build_index(self.data, self.cr.stat_choices())}
        return cache

    def _pick_field(self, parent, text, opener, chars=26, clip=False):
        """A field that shows the current choice and opens its picker: a click, Enter / Space, or simply
        typing (the typed letter starts the search). opener(typed text or None). .show(text) sets it.
        clip: the field is stretched by its grid cell (chars is only its least width), a long text is cut
        by the field's edge instead of after `chars` characters."""
        pal, m = AP.palette(), AP.metrics(parent)
        b = tk.Button(parent, anchor='w', width=chars, font=m['font'], bg=pal['field'], fg=pal['fg_hi'],
                      activebackground=pal['sel'], activeforeground=pal['sel_fg'], bd=1, relief='sunken',
                      padx=3, pady=0, highlightthickness=1, highlightbackground=pal['line'],
                      highlightcolor=pal['fg_hi'], takefocus=1, cursor='hand2')
        AP.exempt(b)

        def show(t):
            t = str(t)
            b.full_text = t
            b.configure(text=t if clip or len(t) <= chars else t[:chars - 2] + '..')

        def key(e):
            ch = e.char
            if ch and ch.isprintable() and not ch.isspace() and not (e.state & 0x4):
                b.open(ch)
                return 'break'
            return None
        b.show, b.open = show, opener            # .open may be set after the field exists (it is its anchor)
        show(text)
        b.configure(command=lambda: b.open(None))
        b.bind('<Key>', key)
        b.bind('<Return>', lambda _e: (b.open(None), 'break')[1])
        return b

    def _close_popup(self):
        top, self._popup = getattr(self, '_popup', None), None
        if top is not None:
            try:
                top.destroy()
            except tk.TclError:
                pass

    def _popup_closed(self, top):
        """A picker popup of the slot list went away: the keyboard is back in the list (or its value box)."""
        def back(e):
            if e.widget is top and self._slots_alive() and self.slots._ed is None:
                self._slots_focus()
        top.bind('<Destroy>', back, add='+')

    def _stat_popup(self, anchor, on_pick, typed=None, current=None, parent=None, title=None):
        """The categorised stat picker (categories | stats, Recent, Find over all categories) under `anchor`.
        Enter / Tab / double-click pick the highlighted (= closest) stat and close it: on_pick(stat id)."""
        self._close_popup()
        top = self._popup = AP.popup(parent or anchor, self.data, on_pick, anchor=anchor,
                                     choices=self.cr.stat_choices(),
                                     title=title or T('cr.pick.stat', 'Stat - type to search, Enter takes the first match'))
        if parent is not None:
            self._popup_closed(top)
        if typed:
            top.picker.focus_filter(typed)
        elif current is not None:
            top.picker.select_stat(current)
            top.picker.focus_filter()
        return top

    def _name_popup(self, anchor, names, on_pick, typed=None, current=None, title=None, numbers=False,
                    parent=None):
        """A searchable name list (skills, states, texts) under `anchor`: on_pick(name). numbers: a typed
        number is offered as '#N' (the raw value of a param)."""
        self._close_popup()
        top = self._popup = AP.popup_choices(parent or anchor, names, on_pick, anchor=anchor, current=current,
                                             title=title, numbers=numbers)
        if parent is not None:
            self._popup_closed(top)
        if typed:
            top.picker.var.set(typed)
            top.picker.entry.icursor('end')
        return top

    def _name_field(self, parent, names, var, on_change=None, chars=20, title=None, clip=False, numbers=False):
        """Pick field over a long name list; var (StringVar) holds the chosen name, on_change() follows a pick."""
        def opener(typed=None):
            def picked(name):
                var.set(name)
                try:
                    f.show(name)
                    f.focus_set()
                except tk.TclError:
                    pass
                if on_change:
                    on_change()
            self._name_popup(f, list(names() if callable(names) else names), picked, typed, var.get(), title,
                             numbers)
        f = self._pick_field(parent, var.get(), opener, chars, clip)
        return f

    # --------------------------------------------------------------- the attribute slots (mxl_attr_slots)
    # Hero Editor's "Magic Attributes": a numbered slot list instead of rows + an add row. The widget is the one
    # of the Item stats tab; here its owner calls change the spec (nothing is written until Create / Replace).
    # Lists: 'extra' / 'extra_rw' = the spec's raw entries themselves (row['e']); 'edit' = an edited item's own
    # list, one slot per (stat, param) with its final value (row['key']; see route_target / set_extra_delta).
    def _clear_mods(self):
        """Empties the values pane; the slot list's frame is only taken off the grid (it keeps its selection,
        scroll position and focus over the many re-renders of the pane)."""
        box = getattr(self, '_slots_box', None)
        for w in self.mods_frame.inner.winfo_children():
            if w is box:
                w.grid_forget()
            else:
                w.destroy()
        self._slots_on = False

    def _slots_alive(self):
        s = getattr(self, 'slots', None)
        return s is not None and s.alive()

    def _slots_drop(self):
        """The slot list is not part of this render (restricted mode, no item): its frame goes."""
        box, self._slots_box, self.slots = getattr(self, '_slots_box', None), None, None
        self._slots_on = False
        if box is not None:
            try:
                box.destroy()
            except tk.TclError:
                pass

    def _slots_place(self, parent, r, table):
        """Puts the slot list at grid row r of the values pane (creating it the first time) and fills it.
        table: an edited item - the slots are the item's own stats (final values), not the raw extra rows."""
        pal, m = AP.palette(), AP.metrics(parent)
        if not self._slots_alive() or getattr(self, '_slots_box', None) is None:
            box = self._slots_box = tk.Frame(parent, bg=pal['bg'])
            AP.exempt(box)
            box.columnconfigure(0, weight=1)
            self._slots_title = tk.Label(box, text=T('cr.slots.title', "Magic Attributes (the item's own stat list)"),
                                         font=m['bold'], bg=pal['bg'], fg=pal['fg_hi'], anchor='w', justify='left')
            self._slots_title.grid(row=0, column=0, sticky='we')
            lf = tk.Frame(box, bg=pal['bg'])
            lf.grid(row=1, column=0, sticky='we')
            try:
                pane_h = self.scroll.canvas.winfo_height()
            except (AttributeError, tk.TclError):
                pane_h = 0
            shown = max(7, min(12, pane_h // m['row'] - 5)) if pane_h > 50 else 10
            self.slots = AS.AttrSlots(lf, self.data, self, click_opens=True, rows_shown=shown, chars=20,
                                      wheel_pass=True)
            hint = self._slots_hint = tk.Label(
                box, font=m['font'], bg=pal['bg'], fg=pal['dim'], anchor='w', justify='left',
                text=T('cr.slots.hint', 'Click an empty slot to add an attribute, a name to change it, a number to '
                       'edit it; x or Delete clears the slot. Shown in the order you added them - the game saves '
                       "an item's stats sorted by stat id."))
            hint.grid(row=2, column=0, sticky='we')
            self._slots_fit()
            self._slots_spec = None
        self._slots_box.grid(row=r, column=0, columnspan=2, sticky='w', pady=(6, 2))
        self._slots_on, self._slots_table = True, bool(table)
        fresh = self._slots_spec is not self.spec
        if fresh:                                        # another item: no order, selection or scroll kept
            self._slots_spec = self.spec
            self._edit_order = []
            self.slots._close_editor()
            self.slots.sel = None
            try:
                self.slots.cv.yview_moveto(0)
            except tk.TclError:
                pass
        self._slots_sync()
        if self.slots.sel is None or self.slots.row() is None or self.slots.row()['kind'] != 'slot':
            own = 'edit' if table else 'extra'
            self.slots.sel = next((n for n, x in enumerate(self.slots.rows)
                                   if x['kind'] == 'slot' and x['list'] == own), self.slots.first_slot())
            self.slots.draw()
        return r + 1

    def _slots_fit(self):
        """The slot list is as wide as the pane it is in - not as wide as the pane's widest row, which a narrow
        window scrolls sideways: every column of the list stays in sight."""
        if not self._slots_alive():
            return
        w = self._wrap_w()
        try:
            self._slots_hint.configure(wraplength=w)
            self._slots_title.configure(wraplength=w)
            self.slots.cv.configure(width=max(self.slots.m['ch'] * 20, w - self.slots.sb.winfo_reqwidth() - 4))
        except tk.TclError:
            pass

    def _edit_keys(self):
        """([(stat id, param)] of an edited item's own stats in display order, {key: final value}): what its
        mods give plus the delta rows, without the deleted ones and without those that end at 0 (they are not
        written - unless the item itself carried the 0). Display order: as loaded, then as the user added them
        (a replaced attribute keeps its slot); the save format itself sorts a stat list by stat id."""
        spec, cr = self.spec, self.cr
        made = self._edit_made()
        extra = {(e['id'], e.get('param')): e['value'] for e in spec.get('extra') or []}
        drop = spec.get('_drop') or set()
        keep0 = spec.get('_keep_zero') or set()
        vals, keys = {}, []
        for k in list(made) + [k for k in extra if k not in made]:
            if k in drop or k in vals:
                continue
            v = made.get(k, 0) + extra.get(k, 0)
            rng = cr.stat_bounds(k[0])
            v = max(rng[0], min(rng[1], v)) if rng else v
            if not v and k not in keep0:
                continue
            vals[k] = v
            keys.append(k)
        order = [k for k in getattr(self, '_edit_order', []) if k in vals]
        order += [k for k in keys if k not in order]
        self._edit_order = order
        return order, vals

    def _slots_sync(self):
        """The slot list's rows from the spec (called by every refresh: the list follows the number rows, Min /
        Random / Max and its own changes alike)."""
        if not getattr(self, '_slots_on', False) or not self._slots_alive() or self.spec is None:
            return
        d, spec = self.data, self.spec
        rows = []
        rw = spec.get('quality') == 'runeword'
        if rw:
            ents = spec.setdefault('extra_rw', [])
            rows += AS.section_rows(d, 'extra_rw', [AS.slot_row(d, 'extra_rw', i, e, e=e) for i, e in enumerate(ents)],
                                    T('cr.raw.rw', "Raw stats (the runeword's list)"), 3)
        if self._slots_table:
            keys, vals = self._edit_keys()
            own = [AS.slot_row(d, 'edit', i, dict(id=k[0], param=k[1], value=vals[k]), key=k)
                   for i, k in enumerate(keys)]
            rows += AS.section_rows(d, 'edit', own, T('cr.item_stats', "Item stats (the item's own list)") if rw else None)
        else:
            ents = spec.setdefault('extra', [])
            own = [AS.slot_row(d, 'extra', i, e, e=e) for i, e in enumerate(ents)]
            rows += AS.section_rows(d, 'extra', own, T('cr.raw.stats', "Raw stats (the item's own list)") if rw else None)
        self.slots.set_rows(rows)

    def _slot_find(self, lst, e=None, key=None):
        """Row index of a used slot by what it stands for (the rows are rebuilt on every change)."""
        for n, x in enumerate(self.slots.rows):
            if x['kind'] == 'slot' and x['s'] is not None and x['list'] == lst:
                if (e is not None and x.get('e') is e) or (key is not None and x.get('key') == key):
                    return n
        return None

    def _default_param(self, sid, taken=()):
        """The param a freshly picked stat starts with: its first skill (cast level 1) / class / name whose
        (stat, param) is not in `taken`, None for a stat without a named param."""
        d = self.data
        kind = param_kind(sid)
        if not kind:
            return None
        first = None
        for nm, _v in list(param_choices(d, sid))[:600]:
            p, _why = encode_skill_param(d, sid, nm, 1 if kind == 'skill' else None)
            if p is None:
                continue
            p = p or None                                # value 0 is stored as "no param"
            if first is None:
                first = (p,)
            if (sid, p) not in taken:
                return p
        return first[0] if first else None

    def slot_say(self, text, error=False):
        self.set_status(text, error=error)

    def slot_selected(self, n):
        r = self.slots.row(n)
        if r is None:
            return
        if r['s'] is not None:
            self.set_status(AS.row_info_text(self.data, r['s']))
        else:
            self.set_status(T('cr.slots.empty', 'Empty slot {n}: click it (or press Enter) and choose the attribute.',
                              n=r['n']))

    def slot_pick(self, n, text=None):
        """The attribute chooser under slot n: fills the empty slot / replaces the slot's attribute."""
        r = self.slots.row(n)
        if r is None or r['kind'] != 'slot':
            return
        used = r['s'] is not None
        title = (T('cr.slots.replace', 'Slot {n}: replace attribute - type to search, Enter takes the first match', n=r['n'])
                 if used else
                 T('cr.slots.add', 'Slot {n}: add attribute - type to search, Enter takes the first match', n=r['n']))
        self._stat_popup(self.slots.anchor(n), lambda sid, r=r: self._slot_picked(r, sid), text,
                         r['s']['id'] if used else None, parent=self.slots.cv, title=title)

    def _slot_picked(self, r, sid):
        d, cr, spec = self.data, self.cr, self.spec
        rng = cr.stat_bounds(sid)
        if rng is None:
            self.set_status(T('cr.slots.no_bits', 'stat #{sid}: the save format has no storage for it', sid=sid),
                            error=True)
            return
        lst, used = r['list'], r['s'] is not None
        if used and r['s']['id'] == sid:
            self._slots_focus()
            return

        def clamp(v):
            return max(rng[0], min(rng[1], v))
        e = key = None
        if lst == 'edit':
            keys, vals = self._edit_keys()
            old = r.get('key')
            key = (sid, self._default_param(sid, set(keys)))
            if key in vals:                              # this very attribute is on the item: go there
                n = self._slot_find('edit', key=key)
                self.slots.select(n)
                self.set_status(T('cr.slots.have', 'This attribute is on the item already (slot {n}).',
                                  n=self.slots.row(n)['n'] if n is not None else '?'), error=True)
                self._slots_focus()
                return
            made = self._edit_made()
            if used:
                val = clamp(vals.get(old, 0)) or clamp(1)
                self._edit_cancel_key(old)
                (spec.get('_keep_zero') or set()).discard(old)
                self._edit_order = [key if k == old else k for k in self._edit_order]
            else:
                val = clamp(1)
            self.set_extra_delta(key, val - made.get(key, 0))
            self._take_over(key)
        else:
            entries = spec.setdefault(lst, [])
            if used:
                e = r['e']
                e['id'], e['param'] = sid, self._default_param(sid)
                e['value'] = clamp(e.get('value') or 1)
            else:
                e = dict(id=sid, param=self._default_param(sid), value=clamp(1))
                entries.append(e)
            self._take_over((sid, e.get('param')))
        self.refresh()
        n = self._slot_find(lst, e=e, key=key)
        if n is None:
            self._slots_focus()
            return
        self.slots.select(n)
        if param_kind(sid):
            self.slot_names(n)                           # its skill / class / name first, then the value
        else:
            self._slot_edit_value(n)

    def _slots_focus(self):
        if self._slots_alive():
            try:
                self.slots.cv.focus_force()
            except tk.TclError:
                pass

    def _slot_edit_value(self, n):
        self.slots.sel = n
        self.slots.edit_cell('value')
        try:
            self.slots.ed.focus_force()
        except tk.TclError:
            pass

    def slot_names(self, n):
        """The searchable name list (skills, classes, states...) under the slot's name cell."""
        r = self.slots.row(n)
        if r is None or 'name' not in self.slots.fields(r):
            return
        sid = r['s']['id']
        names = [nm for nm, _v in param_choices(self.data, sid)]
        self._name_popup(self.slots.anchor(n, 'name'), names, lambda name, r=r: self._slot_named(r, name), None,
                         r['name'], T('cr.slots.param', 'Slot {n}: {what}', n=r['n'], what=param_title(sid).lower()),
                         numbers=True, parent=self.slots.cv)

    def _slot_named(self, r, name):
        new = self._slot_set_param(r, name=name)
        if new is None:
            self._slots_focus()
            return
        n = self._slot_find(r['list'], e=r.get('e'), key=new)
        if n is not None:
            self.slots.select(n)
            self._slot_edit_value(n)

    def _slot_set_param(self, r, name=None, level=None, raw=None):
        """Changes a slot's param (name, cast level or raw number). Returns the slot's (stat, param) key, or
        None when it was refused (the status line says why)."""
        d, spec = self.data, self.spec
        if r is None or r['s'] is None:
            return None
        sid, oldp = r['s']['id'], r['s'].get('param') or None
        if raw is not None:
            bits = min(AS.param_bits(d, sid), 32)
            if not 0 <= raw < (1 << bits):
                self.set_status(T('cr.slots.param_range', 'param out of range (0..{m})', m=(1 << bits) - 1), error=True)
                return None
            newp = raw or None
        else:
            nm = name if name is not None else r['name']
            lv = None
            if r['pk'] == 'skill':
                lv = level if level is not None else (int(r['level']) if r['level'] != '' else 1)
            newp, why = encode_skill_param(d, sid, nm, lv)
            if newp is None:
                self._skill_status(why, nm, sid)
                return None
            newp = newp or None                          # value 0 is stored as "no param", like the game's rows
        new = (sid, newp)
        if newp == oldp:
            return new
        if r['list'] == 'edit':
            old = r['key']
            if new in self._edit_keys()[1]:
                self.set_status(T('cr.slots.have_param', 'Another slot holds this attribute with that very {what}.',
                                  what=param_title(sid).lower() if param_kind(sid) else 'param'), error=True)
                return None
            self._edit_order = [new if k == old else k for k in self._edit_order]
            (spec.get('_keep_zero') or set()).discard(old)
            self._edit_set_param(old, newp)              # (re-renders the pane and the preview)
        else:
            r['e']['param'] = newp
            self._take_over(new)
            self.refresh()
        return new

    def slot_param(self, n, level=None, raw=None):
        return self._slot_set_param(self.slots.row(n), level=level, raw=raw) is not None

    def slot_value(self, n, v, how):
        """A number typed into a slot's value cell: into the spec at once (capped to what the format stores)."""
        r = self.slots.row(n)
        if r is None or r['s'] is None:
            return
        sid = r['s']['id']
        rng = self.cr.stat_bounds(sid)
        note = None
        if rng and not rng[0] <= v <= rng[1]:
            note = T('cr.raw.clamped', 'raw stat #{sid}: {v} cannot be stored, {lo} to {hi}', sid=sid, v=v,
                     lo=rng[0], hi=rng[1])
            v = max(rng[0], min(rng[1], v))
        if r['list'] == 'edit':
            if self.route_target(r['key'], v) == 'roll':
                self.render_mods()                       # the value went into a number row above: show it there
        else:
            e = r['e']
            e['value'] = v
            self._take_over((sid, e.get('param')))
            drop = self.spec.get('_drop')
            if drop is not None:
                drop.discard((sid, e.get('param')))
        self.refresh()
        if note:
            self.set_status(note, error=True)

    def slot_delete(self, n):
        """The slot is cleared; the slots after it move up (their order stays)."""
        r = self.slots.row(n)
        if r is None or r['s'] is None:
            return
        self.slots._close_editor()
        if r['list'] == 'edit':
            self._edit_delete(r['key'])                  # (the stat's whole save group; re-renders)
        else:
            try:
                self.spec.setdefault(r['list'], []).remove(r['e'])
            except ValueError:
                pass
            self.refresh()
        self.set_status(T('cr.slots.cleared', 'slot {n} cleared: {label}', n=r['n'], label=r['label']))
        self._slots_focus()

    # --------------------------------------------------------------- unique orange text
    def _orange_text(self, parent, r):
        """The orange text the game draws on items, with its hidden effect: a display dropdown (the text
        as it shows up in game) and a hidden-effect dropdown that follows it (the marker stats the game's
        own sources write alongside that exact text, or the skill proc it names - like the skill ctcs'
        dropdowns). One Add writes the display entry (and the chosen hidden marker, if any) into the
        item's own stat list."""
        cr, d = self.cr, self.data
        texts = cr.orange_texts()
        if not texts:
            return r
        ttk.Label(parent, text=T('cr.orange.title', 'Unique orange text (display + hidden)'), justify='left',
                  wraplength=self._wrap_w(), font=('Segoe UI', 10, 'bold')).grid(row=r, column=0, columnspan=2, sticky='w', pady=(8, 0))
        r += 1
        labels = [t['label'] for t in texts]
        st = {'i': 0}

        # the hidden-effect dropdown: the correlated option first, then (for the skill-proc texts)
        # every skilldesc name - the param of those stats indexes the skilldesc table directly
        sd_rows = []
        try:
            sd_rows = d._rows('skilldesc')
        except Exception:
            pass
        sd_names = []
        for i in range(len(sd_rows)):
            sd_names.append(skilldesc_name(d, i) or f'skilldesc #{i}')

        def hidden_choices(i):
            t = texts[i]
            if t['skilldesc']:
                return [f'{sk}  (param {i2})' for i2, sk in enumerate(sd_names) if sk]
            return [T('cr.orange.no_hidden', '(no hidden stat - the text is the whole effect)')] \
                + [h['label'] for h in t['hidden']]

        box = ttk.Frame(parent)
        box.grid(row=r, column=0, columnspan=2, sticky='we', pady=1)
        box.columnconfigure(1, weight=1)                 # the fields take the column's width, asking for little
        ttk.Label(box, text=T('cr.orange.display', 'display')).grid(row=0, column=0, sticky='w')
        dvar, hvar = tk.StringVar(value=labels[0]), tk.StringVar()
        hid = {'choices': []}
        cb = self._name_field(box, labels, dvar, lambda: sync(), 16, T('cr.orange.title', 'Unique orange text (display + hidden)'),
                              clip=True)
        cb.grid(row=0, column=1, sticky='we', padx=(4, 2))
        ttk.Label(box, text=T('cr.orange.hidden', 'hidden')).grid(row=1, column=0, sticky='w')
        hb = self._name_field(box, lambda: hid['choices'], hvar, None, 16, T('cr.orange.hidden', 'hidden'), clip=True)
        hb.grid(row=1, column=1, sticky='we', padx=(4, 2))
        # the paired effects: the other attributes the game's own source row writes with this text
        # (the counter / oskill grant / companion block that make it true). Multi-select; every
        # selected entry is written into the item's stat list next to the text, where it shows up
        # as its own editable row.
        ttk.Label(box, text=T('cr.orange.effect', 'effect')).grid(row=2, column=0, sticky='w')
        eff = tk.Listbox(box, selectmode='extended', height=3, exportselection=False,
                         activestyle='none')
        eff.grid(row=2, column=1, sticky='we', padx=(4, 2))
        eff.configure(width=16)
        self.scroll.no_wheel(eff)
        rng = cr.stat_bounds(texts[0]['display']['id']) or (0, 1)
        vv = tk.IntVar(value=texts[0]['display']['value'])
        ttk.Label(box, text=T('cr.orange.value', 'value')).grid(row=3, column=0, sticky='w')
        last = ttk.Frame(box)                          # the value and the Add button: one compact line
        last.grid(row=3, column=1, sticky='w', padx=(4, 2), pady=(1, 0))
        sv = ttk.Spinbox(last, from_=min(0, rng[0]), to=max(rng[1], 1), textvariable=vv, width=8)
        sv.pack(side='left')
        self.scroll.no_wheel(sv)

        def sync(_e=None):
            lab = dvar.get()
            i = labels.index(lab) if lab in labels else st['i']
            st['i'] = i
            dvar.set(labels[i])
            cb.show(labels[i])
            ch = hid['choices'] = hidden_choices(i)
            t = texts[i]
            if t['skilldesc'] and t['display']['param'] < len(sd_names):
                hvar.set(f"{sd_names[t['display']['param']]}  (param {t['display']['param']})")   # the game's own pairing
            else:
                hvar.set(ch[1 if t['hidden'] else 0])
            hb.show(hvar.get())
            eff.delete(0, 'end')
            for fx in t['effects']:
                eff.insert('end', fx['label'])
            if len(t['effects']) <= 8:
                eff.select_set(0, 'end')               # small package: everything rides along by default
            rng2 = cr.stat_bounds(t['display']['id']) or (0, 1)
            sv.configure(from_=min(0, rng2[0]), to=max(rng2[1], 1))
            vv.set(t['display']['value'])

        def add(*_a):
            t = texts[st['i']]
            value = vv.get()
            param = t['display']['param']
            if t['skilldesc']:
                m = re.search(r'\(param (\d+)\)', hvar.get())
                if m:
                    param = int(m.group(1))          # a skill picked in the hidden dropdown overrides
            entries = self.spec.setdefault('extra', [])
            entries.append(dict(id=t['display']['id'], param=param, value=value))
            if not t['skilldesc']:
                idx = hid['choices'].index(hvar.get()) if hvar.get() in hid['choices'] else 0
                if idx >= 1 and idx - 1 < len(t['hidden']):
                    h = t['hidden'][idx - 1]         # (no hidden stat) sits at index 0
                    entries.append(dict(id=h['id'], param=h['param'], value=h['value']))
            made = self._edit_made()                 # stats the item already carries: never doubled
            have = {(e['id'], e.get('param')) for e in entries} | set(made)
            n_fx = 0
            for sel in eff.curselection():
                fx = t['effects'][int(sel)]
                if (fx['id'], fx['param']) in have:
                    continue
                entries.append(dict(id=fx['id'], param=fx['param'], value=fx['value']))
                self._take_over((fx['id'], fx['param']))
                n_fx += 1
            self._take_over((t['display']['id'], param))
            self.set_status(T('cr.orange.added', 'orange text added: {lab}', lab=t['label'][:60])
                            + (T('cr.orange.effects', ' + {n} effect stat(s)', n=n_fx) if n_fx else ''))
            self.render_options()
        sync()
        # under the value: beside it the row was wider than the column at 800x600 (Xft fonts, scale 1.25)
        D2.button(box, T('cr.orange.add', '+ Add orange text'), add, 8).grid(row=4, column=1, sticky='w', padx=(4, 2),
                                                                             pady=(2, 0))
        return r + 1

    # ----------------------------------------------- the item's own stats (edit mode)
    def _edit_made(self):
        """{(stat id, param): value} the spec's own mods produce in the item's stat list (not the runeword's)."""
        made = {}
        for m in self.cr.mods(self.spec):
            if m.source.startswith('rw:'):
                continue
            for x in m.stats(self.data):
                k = (x['id'], x.get('param'))
                made[k] = made.get(k, 0) + x['value']
        return made

    def _edit_extra(self, key):
        return next((e for e in self.spec.get('extra') or [] if (e['id'], e.get('param')) == key), None)

    def set_extra_delta(self, key, delta):
        """spec['extra'] holds one delta row per (stat, param): the item's final value is the mods' total
        plus the delta. A zero delta is kept when there is no row yet only if it is asked for explicitly."""
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            return
        drop = self.spec.get('_drop')
        if drop is not None:
            drop.discard(key)                  # setting the stat again brings the attribute back
        e = self._edit_extra(key)
        if e is None:
            if delta:
                self.spec.setdefault('extra', []).append(dict(id=key[0], param=key[1], value=delta))
        else:
            e['value'] = delta

    def _take_over(self, key):
        """The user set this stat's value or param themselves: it is no longer one of the item's own
        kept stats (the status line stops reporting it)."""
        kept = self.spec.get('_extra_kept')
        if kept is not None:
            kept.discard(key)

    def _kept_count(self):
        """How many of the item's own kept stats (beyond what its mods give) are still on it: the
        bookkeeping delta rows of values the user edited do not count, and neither do stats that ended
        at 0 or show no tooltip line of their own."""
        made = self._edit_made()
        seen, n = set(), 0
        for k in self.spec.get('_extra_kept') or ():
            e = self._edit_extra(k)
            val = made.get(k, 0) + (e['value'] if e else 0)
            if not val or k[0] in seen:
                continue
            seen.add(k[0])
            if self.cr._visible(dict(id=k[0], param=k[1], value=val)):
                n += 1
        return n

    def _skill_status(self, why, name, sid=None):
        """Why a skill (or class, state, element...) param could not be encoded."""
        if why not in ('rolled', 'level') and sid is not None and param_kind(sid) in ('class', 'named'):
            self.set_status(T('cr.raw.unknown_param', 'unknown {what}: {name}', what=param_title(sid).lower(),
                              name=name), error=True)
            return
        if why == 'rolled':
            self.set_status(T('cr.raw.rolled_skill',
                              '{name}: skill id too large for this stat\'s param field - the game would '
                              'roll it to another skill, so it cannot be stored', name=name), error=True)
        elif why == 'level':
            self.set_status(T('cr.raw.bad_level', 'the cast level must be 0 to 63'), error=True)
        else:
            self.set_status(T('cr.raw.unknown_skill', 'unknown skill: {name}', name=name), error=True)

    def _edit_clamp(self, sid, v):
        """A value within what the save format holds for one stat (ItemStatCost bits / add)."""
        rng = self.cr.stat_bounds(sid)
        try:
            v = int(v)
        except (TypeError, ValueError):
            return v
        return max(rng[0], min(rng[1], v)) if rng else v

    def route_target(self, key, target):
        """Make the item's own total of one (stat, param) key read `target`: through the single variable mod
        that produces exactly this stat when there is one and no delta row yet, else through the raw delta
        row. Returns 'roll' or 'extra', or None when nothing was changed (no storage / a bad number)."""
        d, cr = self.data, self.cr
        try:
            target = int(target)
        except (TypeError, ValueError):
            return None
        rng = cr.stat_bounds(key[0])
        if rng:
            target = max(rng[0], min(rng[1], target))
        mod = None
        if self._edit_extra(key) is None:
            prod = [m for m in self.cr.mods(self.spec) if not m.source.startswith('rw:') and m.variable
                    and m.stat_ids(d) == [key[0]]
                    and key in {(x['id'], x.get('param')) for x in m.stats(d)}
                    and m.min <= target <= m.max]
            if len(prod) == 1:
                mod = prod[0]
        if mod is not None:
            self.spec['rolls'][mod.source] = target
            drop = self.spec.get('_drop')
            if drop is not None:
                drop.discard(key)              # setting the stat again brings the attribute back
            self._take_over(key)
            return 'roll'
        self.set_extra_delta(key, target - self._edit_made().get(key, 0))
        self._take_over(key)
        return 'extra'

    def _edit_cancel_key(self, key):
        """The stat disappears from the item: the delta row cancels what the mods still produce (a zero row
        that the item itself had is kept, like the spec builder keeps originals); a delta-only row goes."""
        made = self._edit_made().get(key, 0)
        e = self._edit_extra(key)
        if e is None:
            if made:
                self.set_extra_delta(key, -made)
            return
        if made:
            e['value'] = -made
        else:
            self.spec['extra'].remove(e)
            keep = self.spec.get('_keep_zero')
            if keep is not None:
                keep.discard(key)

    def _edit_set_param(self, key, newp):
        """Change the skill (or class) in one row's param: the old key is cancelled, the row's value moves
        to the new one going through the delta rows (never through the mod rolls)."""
        newp = newp if newp else None
        if newp == key[1]:
            return
        made = self._edit_made()
        e = self._edit_extra(key)
        val = made.get(key, 0) + (e['value'] if e else 0)
        rng = self.cr.stat_bounds(key[0])
        val = max(0, min(rng[1], val)) if rng else max(0, val)
        self._edit_cancel_key(key)
        self.set_extra_delta((key[0], newp), val - made.get((key[0], newp), 0))
        self._take_over((key[0], newp))
        self._edit_sel = (key[0], newp)
        self.render_mods()
        self.refresh()

    def _edit_delete(self, key):
        """The attribute leaves the item. The save format writes a stat group's members with their lead
        (the min / max pairs 17+18, 54+55+56...): deleting one alone would put it back as a 0, so the
        whole group goes (that is what the game shows as one attribute). The keys are marked in
        spec['_drop'] (build leaves them out), their delta rows are removed."""
        made = self._edit_made()
        extra_keys = [(e['id'], e.get('param')) for e in self.spec.get('extra') or []]
        group = {key[0]} | set(STAT_GROUPS.get(key[0], []))
        for lead in [l for l, g in STAT_GROUPS.items() if key[0] in g]:
            group.add(lead)                          # the lead and its other followers (co-followers) go too
            group.update(STAT_GROUPS[lead])
        drop = self.spec.setdefault('_drop', set())
        for sid in sorted(group):
            # the picked attribute itself goes alone: another line of the same stat with another param (a
            # second orange text 377, a second skill) is its own attribute and stays; group members go whole
            keys = {k for k in list(made) + extra_keys if k[0] == sid
                    and (sid != key[0] or k == key or not (k[1] or key[1]))}
            for k in keys:
                drop.add(k)
                e = self._edit_extra(k)
                if e is not None:
                    self.spec['extra'].remove(e)
                self._take_over(k)
        if self._edit_sel in drop:
            self._edit_sel = None
        self.render_mods()
        self.refresh()

    # ------------------------------------------------------------------ changes
    def _int(self, var, lo, hi):
        try:
            v = int(var.get())
        except (tk.TclError, ValueError):
            v = lo
        v = max(lo, min(hi, v))
        var.set(v)
        return v

    def set_unrestricted(self):
        """Unrestricted mode (remembered): values are only bounded by the save format (ItemStatCost bits),
        and the raw stat rows below the value sliders can add / edit / delete any stat on any item."""
        settings.put('capy_unrestricted', bool(self.unrestricted.get()))
        if self.spec is not None:
            self.render_options()

    def set_field(self, key, value, rerender=True):
        if self.spec is None or self.spec.get(key) == value:
            return
        self.spec[key] = value
        if key in ('ilvl', 'superior', 'auto', 'prefix', 'suffix', 'ethereal', 'sockets'):
            self.prepare_defaults(self.spec)
            self.fill_new_rolls()
        if rerender:
            self.render_options()
        else:
            self.refresh()

    def set_base(self, code):
        self.spec['code'] = code
        self.spec['defense'] = None
        self.spec['image'] = None
        self.spec['ilvl'] = max(self.spec['ilvl'], self.cr.min_ilvl(self.spec))
        self.prepare_defaults(self.spec)
        self.fill_new_rolls()
        self.render_options()

    def set_socket(self, k, code):
        s = list(self.spec['socketed'])
        while len(s) <= k:
            s.append(None)
        s[k] = code
        self.spec['socketed'] = s
        self.refresh()

    def _filler_x(self, host, n):
        """The x button that takes socket filler n (Creator.fillers) out of its socket, right of its field."""
        ttk.Button(host, text='x', width=2, command=lambda n=n: self.remove_filler(n)).pack(side='left', padx=(4, 0))

    def filler_rows(self):
        """The filled sockets of the item being made / edited (Creator.fillers)."""
        return self.cr.fillers(self.spec) if self.spec is not None else []

    def remove_filler(self, n):
        if self.spec is None:
            return
        self.cr.remove_filler(self.spec, n)
        self.render_options()

    def clear_fillers(self):
        if self.spec is None:
            return
        self.cr.clear_fillers(self.spec)
        self.render_options()

    def set_rare_name(self, n, i):
        rn = list(self.spec['rare_names'])
        rn[n] = i
        self.spec['rare_names'] = tuple(rn)
        self.refresh()

    def set_rare_affix(self, key, k, sid):
        spec = self.spec
        kind = 'magicprefix' if key == 'rare_prefixes' else 'magicsuffix'
        slot = T('cr.prefix', 'Prefix') if kind == 'magicprefix' else T('cr.suffix', 'Suffix')
        lst = list(spec[key])
        old = lst[k] if k < len(lst) else None
        if sid == old:
            return
        if sid is not None:
            g = self.data.affixes[kind][sid - 1]['group']
            other = next((j for j, x in enumerate(lst) if j != k and g and self.data.affixes[kind][x - 1]['group'] == g), None)
            if other is not None:
                lab = lambda i: self.cr.affix_label(kind, i).split('   [')[0]
                if not messagebox.askyesno(
                        T('cr.title.creator', 'Item Creator'),
                        T('cr.ask.same_group', '"{new}" is in the same affix group as "{old}" ({slot}).\n\nThe game never '
                          'puts two affixes of one group on an item, so this item could not exist.\n\nReplace {slot} '
                          'with "{new}"?', new=lab(sid), old=lab(lst[other]), slot=f'{slot} {other + 1}'),
                        parent=self.top):
                    self.render_options()                       # the list shows the affix that stays
                    return
                lst[other] = sid                                 # the new affix takes the other one's place
                spec[key] = lst
                self.fill_new_rolls()
                self.render_options()
                return
        if sid is None:
            if k < len(lst):
                lst.pop(k)
        elif k < len(lst):
            lst[k] = sid
        else:
            lst.append(sid)
        if spec['quality'] == 'crafted' and sid is not None and old is None:
            n = len(lst) + len(spec['rare_suffixes' if key == 'rare_prefixes' else 'rare_prefixes'])
            if n > CRAFTED_AFFIXES and not spec.get('extra'):
                messagebox.showwarning(
                    T('cr.title.creator', 'Item Creator'),
                    T('cr.warn.crafted_full', 'A crafted item has exactly {n} affixes (1-3 prefixes, 1-3 suffixes): '
                      'set one of the other affixes to (none) first, or choose this one in its place.', n=CRAFTED_AFFIXES),
                    parent=self.top)
                self.render_options()
                return
        spec[key] = lst
        self.fill_new_rolls()
        self.render_options()

    def set_sockets(self, n):
        if self.spec is None:
            return
        ms = self.cr.max_sockets(self.spec['code'], self.spec['ilvl'])
        self.spec['max_sockets'] = bool(ms) and n == ms
        self.set_field('sockets', n)

    def set_max_sockets(self, on):
        if self.spec is None:
            return
        self.spec['max_sockets'] = bool(on)
        if on:
            self.spec['sockets'] = self.cr.max_sockets(self.spec['code'], self.spec['ilvl'])
        self.prepare_defaults(self.spec)
        self.fill_new_rolls()
        self.render_options()

    def set_corrupt(self, row):
        if self.spec is None:
            return
        self.spec['corrupt'] = row
        kind = next((k for r, k, _p, _l in self.cr.corrupt_choices(self.spec) if r == row), None)
        if kind == 'pending' and not self.spec.get('corrupt_roll'):
            self.spec['corrupt_roll'] = random.randint(1, 10000)
        self.render_options()

    def roll_corrupt(self):
        """A corruption as the game gives it: the Corrupted Crystal's outcome, then (if not revealed) the Oil of
        Craft's, each with the game's chances."""
        if self.spec is None:
            return
        ch = self.cr.corrupt_choices(self.spec)
        step = [(r, k, p) for r, k, p, _l in ch if k != 'reveal']
        if not step:
            return
        r, k, _p = random.choices(step, weights=[p for _r, _k, p in step])[0]
        if k == 'pending':
            rev = [(rr, p) for rr, kk, p, _l in ch if kk == 'reveal']
            if rev:
                r = random.choices(rev, weights=[p for _r, p in rev])[0][0]
            else:
                self.spec['corrupt_roll'] = random.randint(1, 10000)
        self.spec['corrupt'] = r
        self.render_options()

    def set_craft(self, row):
        if self.spec is None or self.spec.get('craft') == row:
            return
        self.spec['craft'] = row
        for m in self.cr.mods(self.spec):                     # the new recipe's values: one roll
            if m.variable and m.source.startswith('craft:') and m.source not in self.spec['rolls']:
                self.spec['rolls'][m.source] = random.randint(m.min, m.max)
        self.render_options()

    def reroll_crafted(self):
        if self.spec is None:
            return
        self.spec['extra'] = []
        for k in ('extra_rw', '_from_item', '_keep_zero', '_keep_zero_rw', '_drop', '_defense_raw', '_warning'):
            self.spec.pop(k, None)               # a new roll: a normal, legit item
        self.cr.reroll_crafted(self.spec)
        self.render_options()

    def set_roll(self, src, v):
        self.spec['rolls'][src] = v
        self.refresh()

    def fill_new_rolls(self):
        for m in self.cr.mods(self.spec):
            if m.variable and m.source not in self.spec['rolls']:
                self.spec['rolls'][m.source] = m.max

    def reroll(self, how):
        if self.spec is None:
            return
        self.cr.roll(self.spec, how)
        if self.spec['quality'] == 'tempered' and not self.spec.get('_from_item'):
            self._honorific_roll(how)
        if how == 'max' and self.spec['code'] and self.data.base(self.spec['code']).kind == 'armor':
            self.spec['defense'] = self.cr.defense_range(self.spec)[1]
        self.render_options()

    # ------------------------------------------------------------------ preview / write
    def current_blob(self):
        spec = dict(self.spec)
        spec['unrestricted'] = bool(self.unrestricted.get())
        spec['socketed'] = [c for c in spec.get('socketed', []) if c]
        return self.cr.build(spec)

    def refresh(self):
        try:
            blob, rec = self.current_blob()
            it = blob_item(blob, self.data)
        except (CreateError, FormatError, KeyError, ValueError) as e:
            self.panel.show(None)
            msg = T('cr.not_possible', 'Not possible: {error}', error=e)
            try:                                  # the preview says why it is empty (the item did not vanish)
                st = self.preview.cget('state')
                self.preview.configure(state='normal')
                self.preview.delete('1.0', 'end')
                self.preview.insert('end', msg + '\n\n' + T('cr.fix_hint', 'Change the option above (or choose (none)) '
                                                                       'to get the item back.'))
                self.preview.configure(state=st)
            except tk.TclError:
                pass
            self.set_status(msg, error=True)
            self.btn_ok.state(['disabled'])
            self._header(None)
            return None
        self._slots_sync()
        self.panel.show(it)
        self._header(it)
        self.show_orb(it['code'])
        if self.spec.get('_warning'):
            probs = [T('cr.warn.rules', "outside the game's rules ({error}), kept as it is", error=self.spec['_warning'])]
        else:
            probs = []
        if self.spec.get('quality') == 'crafted':
            probs += self.cr._crafted_problems(it, self.spec)
            kept = {x['id'] for x in self.spec.get('extra') or []}
            if kept:
                probs = [t for t in probs if getattr(t, 'sid', None) not in kept]
                n = self._kept_count()
                if n:
                    probs.append(T('cr.warn.kept_crafted', '{n} stat(s) kept as they were on the item (shrine blessing, '
                                   'corruption, other upgrades or an imported copy)', n=n))
        else:
            probs += self.cr.check_legit(self._without_corruption(it))
            n = self._kept_count()
            if n:
                probs.append(T('cr.warn.kept', "{n} stat(s) kept as they were on the item (outside the game's ranges "
                               'or from upgrades the editor does not model)', n=n))
        if probs:
            self.set_status(T('cr.warning', 'Warning: {text}', text='; '.join(str(p) for p in probs)), error=True)
        else:
            w, h = self.data.base(it['code']).size
            self.set_status(T('cr.legit', "Legit: every value is within the game's ranges. Size {w}x{h}.", w=w, h=h))
        self.btn_ok.state(['!disabled'])
        return blob

    def _header(self, it):
        """D2 look: the item (icon in a gear frame, name in its colour) at the top of the window."""
        if self.header is None:
            return
        try:
            if self.spec is None:
                self.header.show()
                return
            b = self.data.base(self.spec['code'])
            name = clean(self.cr.describe(self.spec))
            sub = clean(b.name) if clean(b.name) != name else ''
            if it is None:
                self.header.show(None, None, name, sub)
                return
            from mxl_gui_detail import item_color
            try:
                name = clean(self.app.full_name(it)) or name
                sub = clean(b.name) if clean(b.name) not in name else ''
            except Exception:
                pass
            layers = None
            try:
                layers = self.app.icon(it, D2.CELL_BG)
            except Exception:
                layers = None
            self.header.show(b.size, layers, name, sub, item_color(it, self.data))
        except Exception as e:
            print('D2 look header:', e)

    def _without_corruption(self, it):
        """The item's stats without what its corruption added (checked against the item's own ranges)."""
        if self.spec.get('corrupt') is None:
            return it
        cs = self.cr._corrupt_stats(self.spec)
        stats = []
        for x in it.get('stats') or []:
            k = (x['id'], x.get('param'))
            v = x['value'] - cs.pop(k, 0)
            if v or k not in self.cr._corrupt_stats(self.spec):
                stats.append(dict(x, value=v))
        return dict(it, stats=stats)

    def set_status(self, text, error=False):
        self.status.configure(text=text, foreground='#e06060' if error else '')

    def show_orb(self, code):
        """Mystic orbs keep their effect in the game's mysticorbs table, not on the item: shown under the tooltip."""
        orb = self.cr.orb_effects(code)
        t = self.preview
        if not orb:
            desc = self.cr.item_desc(code)
            if desc and self.data.base(code).kind == 'misc':
                t.configure(state='normal')
                t.insert('end', '\n' + T('cr.item_desc', 'Item description'), 'section')
                t.insert('end', '\n' + '\n'.join(desc) + '\n', 'dim')
                t.configure(state='disabled')
            return
        lines, most = orb
        try:
            from mxl_theme import GAME_COLORS
            blue = self.panel.color_tag(GAME_COLORS['3'])
        except Exception:
            blue = ''
        t.configure(state='normal')
        t.insert('end', '\n' + T('cr.orb_effect', 'Mystic orb effect'), 'section')
        t.insert('end', '\n' + (T('cr.orb_note_max', '(added to the item it is cubed into; up to {n} of this orb per item)', n=most)
                                if most else T('cr.orb_note', '(added to the item it is cubed into)')) + '\n', 'dim')
        for line in lines or [T('cr.orb_none', '(no effect listed)')]:
            t.insert('end', line + '\n', blue)
        t.configure(state='disabled')

    def commit(self):
        app = self.app
        if getattr(self, '_busy', False):
            return                                  # a click while the previous write runs: ignore it
        self._busy = True
        try:
            self._commit(app)
        finally:
            self._busy = False

    def _commit(self, app):
        if self.target is not None:
            blob = self.refresh()
            if blob is None:
                return
            try:
                msg = self.target(blob)
            except Exception as e:                       # CharError, EditError, FormatError, OSError...
                messagebox.showerror(T('cr.title.creator', 'Item Creator'), str(e), parent=self.top)
                return
            self.set_status(msg or T('cr.saved', 'Saved.'))
            app.status.configure(text=msg or '')
            if self.edit_item is not None:
                self.top.destroy()
            return
        if not app.path:
            messagebox.showerror(T('cr.title.creator', 'Item Creator'), T('cr.open_stash', 'Open a stash in the main window first.'),
                                 parent=self.top)
            return
        blob = self.refresh()
        if blob is None:
            return
        try:
            items = parse_stash(app.path, self.data)
            new = blob_item(blob, self.data)
            remove = []
            spots = None
            if self.edit_item is not None:
                cur = next((i for i in items if i['_offset'] == self.edit_item['_offset']
                            and i['code'] == self.edit_item['code']), None)
                if cur is None:
                    raise EditError(T('cr.err.changed', 'the item changed on disk since it was opened: reopen it'))
                remove = [cur['_offset']]
                old_blob = bytes(mxl_save.item_blob(open(app.path, 'rb').read(), cur))  # capture BEFORE the write below
                rest = [i for i in items if i is not cur]
                spot = None
                if mxl_save.placement_error(rest, new, cur['page'], cur['x'], cur['y'], self.data) is None:
                    spot = (cur['page'], cur['x'], cur['y'])
                if spot is None:
                    spot = free_spot(rest, new, self.data, self._pages(cur['page']))
            else:
                # bulk add: write N copies into the first N free spots (the copies field resets to 1)
                n = max(1, min(100, self.copies.get() if hasattr(self, 'copies') else 1))
                try:
                    self.copies.set(1)
                except (tk.TclError, ValueError):
                    pass
                spots = []
                rest = list(items)
                for _i in range(n):
                    spot = free_spot(rest, new, self.data, self._pages(app.page()))
                    if spot is None:
                        break
                    spots.append(spot)
                    placed = blob_item(blob, self.data)          # re-parse: free_spot must see it placed
                    placed['page'], placed['x'], placed['y'] = spot
                    rest.append(placed)
                if not spots:
                    spot = None
                else:
                    spot = spots[0]
            if spot is None:
                # no modal here: spamming Create must never stack blocking dialog boxes
                # (each one runs its own event loop while the next queued click fires into it)
                msg = T('cr.err.no_space', 'no free place in the stash for this item')
                self.set_status(msg, error=True)
                app.status.configure(text=msg)
                return
            insert = [(s[0], s[1], s[2], blob) for s in (spots or [spot])]
            page, x, y = spot
            bak = edit_stash(app.path, self.data, remove=remove, insert=insert,
                             backup=app.needs_backup(app.path))
            if spots:
                import mxl_undo
                mxl_undo.record(app, 'create', spots=spots)
            elif remove:
                import mxl_undo
                old = items and next(i for i in items if i['_offset'] == remove[0])
                if old is not None:
                    mxl_undo.record(app, 'replace', blob=old_blob,
                                    page=spot[0], x=spot[1], y=spot[2],
                                    old_page=old['page'], old_x=old['x'], old_y=old['y'],
                                    name=clean(self.cr.describe(self.spec)))
        except (EditError, FormatError, OSError, CreateError) as e:
            messagebox.showerror(T('cr.title.creator', 'Item Creator'), str(e), parent=self.top)
            return
        app.backup_made(app.path, bak)
        _reload_main(app, (page, x, y))
        try:
            app.notebook.select(page)
        except tk.TclError:
            pass
        msg = (T('cr.replaced', '{name} replaced: page {page} ({x}, {y})', name=clean(self.cr.describe(self.spec)), page=page + 1, x=x, y=y)
               if self.edit_item else
               T('cr.created', '{name} created: page {page} ({x}, {y})', name=clean(self.cr.describe(self.spec)), page=page + 1, x=x, y=y))
        if spots and len(spots) > 1:
            msg += T('cr.copies_made', ' - {n} copies written', n=len(spots))
        if bak:
            msg += T('cr.backup', ' - backup: {file}', file=os.path.basename(bak))
        app.status.configure(text=msg)
        self.set_status(msg)
        if self.edit_item is not None:
            self.edit_item = app.selected
            if self.edit_item is None:
                self.top.destroy()

    def fill_containers(self, *_a):
        """One of every container / cluster / barrel / crate / vessel (Quantity 1000) on the next adjacent
        empty stash pages - written only when such a run of empty pages exists; undoable like a create."""
        app = self.app
        title = T('cr.title.creator', 'Item Creator')
        if not app.path:
            messagebox.showerror(title, T('cr.open_stash', 'Open a stash in the main window first.'), parent=self.top)
            return
        try:
            from mxl_creator import plan_container_fill
            plan = plan_container_fill(self.cr, parse_stash(app.path, self.data), mxl_save.STASH_PAGES)
            if plan is None:
                messagebox.showinfo(title, T('cr.fill.no_pages', 'Not enough adjacent empty stash pages for all '
                                                                 'containers: nothing was added.'), parent=self.top)
                return
            bak = edit_stash(app.path, self.data, insert=plan, backup=app.needs_backup(app.path))
            import mxl_undo
            mxl_undo.record(app, 'create', spots=[(p, x, y) for p, x, y, _b in plan])
        except (EditError, FormatError, OSError, CreateError) as e:
            messagebox.showerror(title, str(e), parent=self.top)
            return
        app.backup_made(app.path, bak)
        page, x, y = plan[0][:3]
        _reload_main(app, (page, x, y))
        try:
            app.notebook.select(page)
        except tk.TclError:
            pass
        pages = sorted({p for p, _x, _y, _b in plan})
        msg = T('cr.fill.done', '{n} containers added on page(s) {first}-{last}', n=len(plan),
                first=pages[0] + 1, last=pages[-1] + 1)
        if bak:
            msg += T('cr.backup', ' - backup: {file}', file=os.path.basename(bak))
        app.status.configure(text=msg)
        self.set_status(msg)

    def _pages(self, first):
        p = self.page.get()
        if p == self.page_current:
            return [first] + [i for i in range(STASH_PAGES) if i != first]
        if p == self.page_first:
            return list(range(STASH_PAGES))
        return [int(p) - 1]


# ---------------------------------------------------------------------------------------- main window hooks

def _reload_main(app, sel_key=None):
    """The stash changed on disk (a create / replace / delete): refresh the main window's grid without
    the full reload. The icons are fingerprint-keyed (a new item's icon is built on the fly) and the
    character file is untouched, so only the stash is re-parsed - the full reload re-reads it too and
    rebuilds every icon (~90 ms). The watcher's files_seen tuple is kept in the same shape, else the
    next watch tick would do a full reload right after. Any problem: the full load() as before."""
    import mxl_gui
    try:
        items = parse_stash(app.path, app.data)
        app.items = items
        app.files_seen = (mxl_gui.file_signature(app.path), mxl_gui.file_signature(app.char_file))
        if sel_key is None:
            app.selected = None
        else:
            app.selected = next((i for i in items if (i['page'], i['x'], i['y']) == tuple(sel_key)), None)
        app.draw_grid()
        app.set_detail(app.selected)
    except Exception:
        app.load(app.path, keep_selection=False)
        return
    try:                                   # the item counters of the status bar ("Stash: n items", "Page p: n") are
        text = app.status.cget('text')     # written by show_status() only, which the full load() calls: without it
        app.show_status()                  # they showed the numbers of before this write until the next reload
        app.status.configure(text=text)    # (show_status also puts its hint into the status line: kept as it was)
    except Exception as e:
        print('status bar counters not refreshed:', e)


def delete_selected(app):
    """Delete the selected item at once (no prompt): Ctrl+Z - or the Undo button - puts it back."""
    it = app.selected
    if it is None or not app.path:
        messagebox.showinfo(T('cr.delete', 'Delete item'), T('cr.select_first', 'Select an item of the stash first.'))
        return
    try:
        import mxl_undo
        mxl_undo.delete_item(app, it)
    except Exception as e:
        messagebox.showerror(T('cr.delete', 'Delete item'), str(e))


def edit_selected(app):
    it = app.selected
    inv = getattr(app, 'inventory', None)
    if it is None and inv is not None and inv.selected is not None:
        inv.edit()                       # an item of the character / mercenary / inventory panel: edited in place
        return
    if it is None or not app.path:
        messagebox.showinfo(T('cr.edit', 'Edit item'), T('cr.select_first', 'Select an item of the stash first.'))
        return
    CreatorWindow(app, edit_item=it)


def install(App):
    """Adds the Creator / Edit / Delete buttons to the collector's main window."""
    original = App._build

    def _build(self):
        original(self)
        top = self.btn_library.master
        bar = ttk.Frame(top)
        bar.pack(side='left', padx=(12, 0))
        ttk.Button(bar, text=T('cr.title.creator', 'Item Creator'), command=lambda: CreatorWindow(self)).pack(side='left', padx=2)
        ttk.Button(bar, text=T('cr.edit', 'Edit item'), command=lambda: edit_selected(self)).pack(side='left', padx=2)
        try:
            import mxl_he_stats
            ttk.Button(bar, text=T('he.title', 'Item stats'), command=lambda: mxl_he_stats.open_item_stats(self)).pack(side='left', padx=2)
        except Exception:          # mxl_he_stats without its dependencies: stay silent
            pass
        ttk.Button(bar, text=T('cr.delete', 'Delete item'), command=lambda: delete_selected(self)).pack(side='left', padx=2)
        # no value sliders in the detail panel any more: the right-click menu's 'Make perfect' (mxl_perfect)
        # raises every roll at once, 'Item stats' edits single values
        self.editing = False
        self._creator = None

    App._build = _build


class _NoLibrary:
    """Replaces the collector's library (collection of found uniques / sets): nothing is tracked or written."""
    readonly = False

    def __init__(self, *a, **k):
        pass

    def release(self):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


class _NoLibraryUI:
    window = None

    def __init__(self, app):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


def remove_library(mxl_gui):
    """No library in this build: no library.json, no Library button, no 'transfer to the library' button."""
    mxl_gui.Library = _NoLibrary
    mxl_gui.LibraryUI = _NoLibraryUI
    mxl_gui.catalog = lambda data: []
    App = mxl_gui.App
    App.can_transfer = lambda self, it: False
    original = App._build

    def _build(self):
        original(self)
        self.btn_library.pack_forget()

    App._build = _build


APP_NAME = 'Median XL Capybara Editor V2'


def rename_app(mxl_gui):
    """Window title: "Median XL Capybara Editor - <file>" (the collector's titles start with "Median XL")."""
    tr = mxl_gui.tr

    def tr2(key, *a, **k):
        text = tr(key, *a, **k)
        if key in ('app.title', 'app.title_file') and isinstance(text, str):
            if text.startswith('Median XL') and not text.startswith(APP_NAME):
                text = APP_NAME + text[len('Median XL'):]
            elif APP_NAME not in text:
                text = f'{APP_NAME} - {text}'
        return text
    mxl_gui.tr = tr2


def run():
    import mxl_userdir                    # own settings folder; the launcher did it already (splash process too)
    mxl_userdir.setup()
    import mxl_splash                    # the loading screen: its own process (the exe again with --capy-splash)
    if mxl_splash.FLAG_ARG in sys.argv:
        mxl_splash.main()
        sys.exit(0)
    mxl_splash.start()
    import mxl_log                        # capybara.log in the settings folder: saves, backups, imports, errors
    mxl_log.install()
    import mxl_explode                    # faster implode decoder for the collector's MPQ reader (game art, tables)
    mxl_explode.install()
    import mxl_free                      # no "the game must be closed" checks: editing works while the game is open
    mxl_free.install()
    import mxl_format_fix                # Sigma item layouts the collector's reader did not know (before anything reads)
    mxl_format_fix.install()
    import mxl_speed                  # free place search in one pass over the stash (same answer, ~300x faster)
    mxl_speed.install()
    import mxl_profile                    # game profile: Median XL (nothing changes) or another D2 game folder
    mxl_profile.install()                 # (its own data folder; before mxl_gui copies paths.DATA_DIR)
    mxl_profile.install_menu()
    import mxl_gui
    rename_app(mxl_gui)
    import mxl_d2_theme                   # which look: dark Diablo ('d2', default) or Hero-Editor light ('he')
    dark = mxl_d2_theme.dark()
    import mxl_d2look                     # dark look: Median XL's own stash / inventory panels (game art);
    if dark:                              # innermost wrapper, plain dark grids when the game folder is unknown
        mxl_d2look.install(mxl_gui.App)
    else:
        mxl_d2look.disable()              # light look: the Hero-Editor grids
    import mxl_tabs                       # every editor window becomes a tab of the main window (tiling WM)
    mxl_tabs.install(mxl_gui.App)
    import mxl_hover                      # item stats follow the mouse hover (no click needed)
    mxl_hover.install(mxl_gui.App)
    if dark:
        mxl_d2_theme.install(mxl_gui.App)  # stone / bronze / gold: the collector's dark grids stay
    else:
        import mxl_he_grid                # the collector's dark constants -> Hero-Editor light palette
        mxl_he_grid.install(mxl_gui.App)  # (innermost: before any window is built)
    import mxl_char_gui
    remove_library(mxl_gui)
    install(mxl_gui.App)
    import mxl_counters; mxl_counters.install(mxl_gui.App)   # Character page "Counters": signets, stat 88
    import mxl_status_attr; mxl_status_attr.install(mxl_gui.App)   # status bar Str / Dex = the Stats page's
    mxl_char_gui.install(mxl_gui.App)
    import mxl_char_view; mxl_char_view.install()   # Stats page: the animated character (game DCC art)
    mxl_speed.install_windows()          # stat screen / skill tree art caches kept across Character window rebuilds
    import mxl_hotkeys                     # Character page "Hotkeys": skill hotkeys and mouse-button skills
    mxl_hotkeys.install(mxl_gui.App)
    import mxl_merc; mxl_merc.install()   # Character window page "Mercenary"
    import mxl_quests; mxl_quests.install(mxl_gui.App)   # Character window page "Quests+": raw quest words
    import mxl_rc_menu                     # Hero-Editor-style right-click menus on items (stash + character)
    mxl_rc_menu.install(mxl_gui.App)
    mxl_rc_menu.install_char()
    import mxl_hover
    mxl_hover.install_char()              # hover on the character window's canvases (after rc_menu's wrapper)
    import mxl_undo                        # instant delete (Delete key on hover / menu) + Ctrl+Z multi-undo
    mxl_undo.install(mxl_gui.App)
    import mxl_import
    mxl_import.install(mxl_gui.App)
    import mxl_inv_gui
    mxl_inv_gui.install(mxl_gui.App)
    import mxl_ingame; mxl_ingame.install(mxl_gui.App)   # character in a game: live reload, warning, confirm
    import mxl_fit                         # stash / inventory cell size from the window's size, on every resize
    mxl_fit.install(mxl_gui.App)
    import mxl_he_theme                    # the Hero-Editor look for every window - outermost (walks what others build)
    mxl_he_theme.install(mxl_gui.App)      # (in the dark look it repaints with mxl_d2_theme's palette)
    mxl_d2_theme.install_toggle(mxl_gui.App)
    import mxl_itemlib; mxl_itemlib.install()   # More » Item library... (+ right-click Add to library...)
    import mxl_toolbar                     # the top bar at every width: what does not fit goes into "More"
    mxl_toolbar.install(mxl_gui.App)
    import mxl_lang; mxl_lang.install(mxl_gui.App)   # live language switch: the editor's own texts follow
    import mxl_app_icon
    mxl_app_icon.install(mxl_gui.App)
    mxl_splash.install(mxl_gui.App)       # last: outermost, closes the splash once everything is built
    mxl_log.wrap_saves()                  # writers bound by name in the modules imported since install()
    import mxl_savecheck                  # every file is read by the independent mxlsave before it is written
    mxl_savecheck.install()               # (after every module that wraps or binds the writers)
    try:
        mxl_gui.main()
    finally:
        mxl_splash.close()
