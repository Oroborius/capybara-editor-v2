"""Item Creator / Editor window for the MXL Item Collector (added to the main window by install()).

- Create: choose a unique, set item, runeword or base item (normal, superior, magic, rare), its options and the
  value of every variable mod (always inside the game's own ranges), preview it with the collector's tooltip, and
  write it into the stash shown in the main window (first free place of the chosen page).
- Edit: the selected stash item is loaded into the same window; "Replace item" writes the new version in its place.
- Delete: removes the selected stash item (and its socketed items).
- "Value editing" toggles the collector's built-in in-place sliders (setting editing_enabled).
Every write goes through mxl_save.edit_stash (verification after writing, .bak backup; the game-closed check is removed by mxl_free - see DEVELOPER_NOTES).
"""
import os
import re
import sys
import random
import tkinter as tk
from tkinter import ttk, messagebox

import settings
import mxl_save
from mxl_save import edit_stash, parse_stash, free_spot, blob_item, EditError, STASH_PAGES
from mxl_format import FormatError, STAT_GROUPS
from mxl_rules import stat_label, stat_hidden, mods_stats
from mxl_statnames import (stat_text, param_kind, decode_param, encode_param, encode_skill_param,
                           skill_fits, skill_names_sorted, CHANCE_TO_CAST, SINGLE_SKILLS, CLASS_SKILLS,
                           STATE_STAT, state_names_sorted, skilldesc_name)
from mxl_gui_detail import DetailHost, DetailPanel, setup_detail_tags
from mxl_creator import Creator, CreateError, MAX_ILVL, CRAFTED_AFFIXES
from mxl_lang import T
import mxl_d2look as D2

QUALITY_KEYS = [('Unique', 'unique'), ('Set item', 'set'), ('Runeword', 'runeword'), ('Angelic', 'angelic'), ('Rare', 'rare'),
                ('Crafted', 'crafted'), ('Magic', 'magic'), ('Superior', 'superior'), ('Normal', 'normal')]
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


def bind_stat_picker(cb, get_labels, on_pick):
    """The attribute picker of the stat rows: type to autofill, Enter commits the closest stat, and a
    letter / digit key jumps to the first entry starting with it (pressing it again goes to the next).
    - while typing, the entry completes to the first match of the typed text (the completed part is
      selected, so just keep typing to narrow it down);
    - a single key pressed again cycles through the entries starting with it;
    - Enter picks the closest stat: prefix match first, then a substring match, else the current one;
    - Up / Down walk the whole list.
    on_pick(label) commits the picked stat (resolving the label back to the stat id is the caller's)."""
    st = {'q': '', 'i': -1}

    def labels():
        vals = get_labels() if callable(get_labels) else get_labels
        return list(vals)

    def first_match(text, start=0):
        text = text.lower()
        vals = labels()
        n = len(vals)
        for i in list(range(start, n)) + list(range(0, min(start, n))):
            if vals[i].lower().startswith(text):
                return i
        return -1

    def complete_to(i, typed_len=None):
        vals = labels()
        if not 0 <= i < len(vals):
            return
        st['i'] = i
        cb.set(vals[i])
        try:
            cb.icursor(typed_len if typed_len is not None else len(vals[i]))
            if typed_len is not None and typed_len < len(vals[i]):
                cb.selection_range(typed_len, 'end')
        except Exception:
            pass

    def on_key(e):
        ks = e.keysym
        if ks in ('Return', 'KP_Enter'):
            text = cb.get().strip().lower()
            vals = labels()
            i = -1
            if text:
                i = first_match(text)
                if i < 0:
                    i = next((k for k, v in enumerate(vals) if text in v.lower()), -1)
            if i < 0:
                try:
                    i = cb.current()
                except Exception:
                    i = -1
            if i >= 0:
                on_pick(vals[i])
            return 'break'
        if ks == 'Escape':
            cb.set('')
            st['q'], st['i'] = '', -1
            return 'break'
        if ks == 'Down':
            i = first_match(st['q']) if st['q'] else max(st['i'], 0)
            complete_to(i + 1 if 0 <= i + 1 < len(labels()) else i, len(st['q']) or None)
            return 'break'
        if ks == 'Up':
            i = first_match(st['q']) if st['q'] else max(st['i'], 0)
            complete_to(max(i - 1, 0), len(st['q']) or None)
            return 'break'
        if ks in ('BackSpace',):
            st['q'] = st['q'][:-1]
            i = first_match(st['q']) if st['q'] else -1
            if i >= 0:
                complete_to(i, len(st['q']) or None)
            else:
                cb.set(st['q'])
                cb.icursor(len(st['q']))
            return 'break'
        if ks in ('Delete', 'Home', 'End', 'Left', 'Right', 'Tab', 'space'):
            return None
        ch = (e.char or '').lower()
        if len(ch) == 1 and (ch.isalpha() or ch.isdigit()):
            vals = labels()
            if not vals:
                return 'break'
            if st['q'] == ch and st['i'] >= 0:
                # the same single key again: the next entry starting with it (wrapping around)
                i = first_match(ch, st['i'] + 1)
                if i >= 0:
                    complete_to(i, 1)
                return 'break'
            q = st['q'] + ch
            i = first_match(q)
            if i < 0 and st['q']:
                q = ch                                     # restart with the new key
                i = first_match(q)
            if i < 0:
                return 'break'                             # nothing matches: keep what is there
            st['q'] = q
            complete_to(i, len(q))
            return 'break'
        return None

    cb.bind('<KeyRelease>', on_key)
    cb._stat_picker_on_key = on_key        # headless tests drive it directly (synthetic events need a mapped window)
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


class ScrollFrame(ttk.Frame):
    """Vertical scroll area; the mouse wheel scrolls it anywhere over its content (comboboxes included: the wheel
    never changes their value by accident)."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        bg = ttk.Style().lookup('TFrame', 'background') or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, bg=bg)
        self.sb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.sb.pack(side='left', fill='y')
        self.bind('<Enter>', lambda e: self._grab(True))
        self.bind('<Leave>', lambda e: self._grab(self._inside(e)))

    def _inside(self, e):
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, KeyError):
            return False
        return w is not None and str(w).startswith(str(self))

    def _grab(self, on):
        try:
            if on:
                self.bind_all('<MouseWheel>', self._wheel)
                self.bind_all('<Button-4>', self._wheel)
                self.bind_all('<Button-5>', self._wheel)
            else:
                for ev in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                    self.unbind_all(ev)
        except tk.TclError:
            pass

    def _wheel(self, e):
        if not self._inside(e):
            return None
        if getattr(e, 'num', None) in (4, 5):
            step = -1 if e.num == 4 else 1
        else:
            step = int(-e.delta / 120) or (-1 if e.delta > 0 else 1)
        top, bottom = self.canvas.yview()
        if top > 0 or bottom < 1:
            self.canvas.yview_scroll(step, 'units')
        return 'break'

    def no_wheel(self, widget):
        """The wheel over this widget scrolls the area instead of changing the widget's value."""
        for ev in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            widget.bind(ev, self._wheel)

    def scroll_top(self):
        self.canvas.yview_moveto(0)


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
        left = ttk.Frame(self.paned, padding=6)
        self.paned.add(left, weight=1)
        ttk.Label(left, text=T('cr.item_type', 'Item type')).pack(anchor='w')
        self.quality = tk.StringVar()
        cb = ttk.Combobox(left, state='readonly', values=[q for q, _ in qualities()], textvariable=self.quality, width=34)
        cb.pack(fill='x')
        cb.bind('<<ComboboxSelected>>', lambda e: self.on_quality())
        self.kind_filter = tk.StringVar(value=filters()[0][0])
        kf = ttk.Combobox(left, state='readonly', values=[lab for lab, _ in filters()],
                          textvariable=self.kind_filter, width=34)
        kf.pack(fill='x', pady=(4, 0))
        kf.bind('<<ComboboxSelected>>', lambda e: self.fill_list())
        ttk.Label(left, text=T('cr.search', 'Search')).pack(anchor='w', pady=(6, 0))
        self.search = tk.StringVar()
        ent = ttk.Entry(left, textvariable=self.search)
        ent.pack(fill='x')
        self.search.trace_add('write', lambda *a: self.fill_list())
        lf = ttk.Frame(left)
        lf.pack(fill='both', expand=True, pady=(4, 0))
        self.listbox = tk.Listbox(lf, width=34, height=10, exportselection=False, activestyle='none',
                                  bg=self.app.detail.cget('bg'), fg=self.app.detail.cget('fg'),
                                  selectbackground='#3a5f8a', selectforeground='white', highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(lf, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='left', fill='y')
        self.listbox.bind('<<ListboxSelect>>', lambda e: self.on_pick())
        self.count = ttk.Label(left, text='')
        self.count.pack(anchor='w')

        mid = self._mid = ttk.Frame(self.paned, padding=6)
        self.paned.add(mid, weight=4)
        self.title = ttk.Label(mid, text='', font=('Segoe UI', 12, 'bold'))
        self.header = None
        if D2.active():                                   # D2 look: the game's stone, fonts and gear frame
            try:
                self.header = D2.CreatorHeader(mid, T('cr.title.editor', 'Item Editor') if self.edit_item else
                                               T('cr.title.creator', 'Item Creator'), getattr(self.app, 'cell', 32))
            except Exception as e:
                print('D2 look (creator header) disabled:', e)
                self.header = None
        if self.header is None:
            self.title.pack(side='top', anchor='w')

        bottom = ttk.Frame(mid)                          # packed before the scroll area: never pushed out of sight
        bottom.pack(side='bottom', fill='x', pady=(6, 0))
        self.status = ttk.Label(bottom, text='', wraplength=520, justify='left')
        self.status.pack(side='top', anchor='w', fill='x')
        self.status.bind('<Configure>', lambda e: self.status.configure(wraplength=max(200, e.width - 8)))
        row = ttk.Frame(bottom)
        row.pack(fill='x', pady=(4, 0))
        self.btn_ok = D2.button(row, T('cr.btn.replace', 'Replace item') if self.edit_item else
                                (T('cr.btn.create', 'Create') if self.target else T('cr.btn.create_stash', 'Create in stash')),
                                self.commit)
        self.btn_ok.pack(side='right')            # packed first: never squeezed out of the window
        D2.button(row, T('cr.btn.close', 'Close'), self.top.destroy).pack(side='right', padx=6)
        # bulk add: write N copies into the first N free spots (plain stash-create mode only)
        self.copies = tk.IntVar(value=1)
        self._copies_widgets = []
        if self.edit_item is None and self.target is None:
            ttk.Label(row, text=T('cr.copies', 'copies')).pack(side='left', padx=(10, 2))
            self.copies_spin = ttk.Spinbox(row, from_=1, to=100, textvariable=self.copies, width=4)
            self.copies_spin.pack(side='left')
            self._copies_widgets = [self.copies_spin]
        ttk.Label(row, text=T('cr.stash_page', 'Stash page')).pack(side='left')
        self.page_current, self.page_first = T('cr.page.current', 'Current page'), T('cr.page.first_free', 'First free')
        self.page = tk.StringVar(value=self.page_current)
        ttk.Combobox(row, state='readonly', width=14, textvariable=self.page,
                     values=[self.page_current, self.page_first] + [str(i + 1) for i in range(STASH_PAGES)]).pack(side='left', padx=4)
        if settings.get('capy_unrestricted') is None:          # first start: unrestricted on (this build's point)
            settings.put('capy_unrestricted', True)
        self.unrestricted = tk.BooleanVar(value=bool(settings.get('capy_unrestricted')))
        ttk.Checkbutton(row, text=T('cr.unrestricted', 'Unrestricted'), variable=self.unrestricted,
                        command=self.set_unrestricted).pack(side='left', padx=(8, 0))
        self.dest = ttk.Label(row, text='')
        self.dest.pack(side='left', padx=6)

        self.scroll = ScrollFrame(mid)
        self.scroll.pack(side='top', fill='both', expand=True, pady=(4, 0))
        try:
            self.scroll.no_wheel(self.copies_spin)     # (self.scroll exists only from here on)
        except (AttributeError, KeyError):
            pass
        body = self.scroll.inner
        body.columnconfigure(0, weight=1)
        self.opts = ttk.Frame(body)
        self.opts.grid(row=0, column=0, sticky='we', pady=(0, 4))
        self.opts.columnconfigure(1, weight=1)
        bar = ttk.Frame(body)
        bar.grid(row=1, column=0, sticky='we', pady=(6, 0))
        ttk.Label(bar, text=T('cr.variable_values', 'Variable values'), font=('Segoe UI', 10, 'bold')).pack(side='left')
        for t, how in ((T('cr.btn.max', 'Max'), 'max'), (T('cr.btn.random', 'Random'), 'random'), (T('cr.btn.min', 'Min'), 'min')):
            D2.button(bar, t, lambda h=how: self.reroll(h), 8).pack(side='right', padx=2)

        class _Mods:
            pass
        self.mods_frame = _Mods()
        self.mods_frame.inner = ttk.Frame(body)
        self.mods_frame.inner.grid(row=2, column=0, sticky='we', pady=(4, 0))
        self.mods_frame.inner.columnconfigure(1, weight=1)

        right = ttk.Frame(self.paned, padding=6)
        self.paned.add(right, weight=1)
        app_detail = self.app.detail
        self.preview = tk.Text(right, width=int(app_detail.cget('width')), wrap='word', bg=app_detail.cget('bg'),
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
        try:
            self.top.update_idletasks()
            w = self.paned.winfo_width()
            if w < 50:
                return
            pw = max(300, min(int(w * 0.28), 460))
            lw = max(220, min(int(w * 0.22), 360))
            self.paned.sashpos(0, lw)
            self.paned.sashpos(1, max(lw + 300, w - pw))
        except tk.TclError:
            pass

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

    def fill_list(self):
        q = self.qkey()
        s = self.search.get().strip().lower()
        fk = dict(filters()).get(self.kind_filter.get())
        orbs_only = fk == 'orb'
        dyes_only = fk == 'dye'
        kind = {'orb': 'misc', 'dye': 'misc'}.get(fk, fk)
        cr, d = self.cr, self.data
        rows = []
        if q in ('unique', 'set'):
            for i, name, u in (cr.uniques() if q == 'unique' else cr.set_items()):
                b = d.base(u['code'])
                if kind and b.kind != kind or orbs_only and cr.orb_effects(u['code']) is None or dyes_only:
                    continue
                label = f"{clean(name)} - {clean(b.name)}"
                if clean(name) == clean(b.name):                 # "Relic - Relic" x200: the granted skill instead
                    skills = cr.granted_skills(u)
                    if skills:
                        label = f"{clean(name)} - {' / '.join(skills)}"
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
            for b in (self._craft_bases() if q == 'crafted' else self._bases()):
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
                orb = cr.orb_effects(b.code)
                if orbs_only and orb is None or dyes_only and cr.display_name(b.code) != 'Mystic Dye':
                    continue
                label = cr.display_name(b.code)
                if ' / ' in label:                                # long multi-line names: the top line only
                    label = label.split(' - ')[0]
                if orb and orb[0]:                                  # mystic orbs: their effect tells them apart
                    label += ': ' + '; '.join(orb[0])
                rows.append((f"{label} [{kind_label(b.kind)}]", b.code))
            seen = {}
            for label, _ in rows:
                seen[label] = seen.get(label, 0) + 1
            named = []
            for label, code in rows:                          # same name: the description tells them apart
                if seen[label] > 1 and label.endswith(']'):
                    summary = cr.desc_summary(code)
                    if not summary:                           # no description: the picture's name (e.g. dye-rainbow)
                        inv = (d.base(code).inv_file or '').lower()
                        if 'dye' in inv and 'rainbow' in inv:
                            summary = 'Color: Rainbow'
                        else:
                            inv = inv.replace('_', ' ').replace('-', ' ').strip()
                            summary = f'({inv})' if inv else ''
                    if summary:
                        head, tail = label.rsplit(' [', 1)
                        label = f"{head}: {summary} [{tail}"
                named.append((label, code))
            seen = {}
            for label, _ in named:
                seen[label] = seen.get(label, 0) + 1
            rows = [(f"{label[:-1]}, {code.strip()}]" if seen[label] > 1 and label.endswith(']') else label, code)
                    for label, code in named]
            rows.sort(key=lambda r: r[0].lower())
        if s:
            rows = [r for r in rows if s in r[0].lower()]
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
        spec['max_sockets'] = q in ('unique', 'set', 'crafted')     # as the game gives them (Sacred gear)
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
        if q == 'rare':
            names = cr.rare_name_choices(code)
            rn = spec.get('rare_names')
            if not rn or rn[0] not in [i for i, _ in names['rareprefix']] or rn[1] not in [i for i, _ in names['raresuffix']]:
                spec['rare_names'] = (names['rareprefix'][0][0] if names['rareprefix'] else 0,
                                      names['raresuffix'][0][0] if names['raresuffix'] else 0)
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
        for w in self.mods_frame.inner.winfo_children():
            w.destroy()
        self.mod_vars = {}
        spec = self.spec
        if spec is None:
            self.title.configure(text=T('cr.choose', 'Choose an item in the list'))
            self._header(None)
            self.panel.show(None)
            self.set_status('')
            self.btn_ok.state(['disabled'])
            return
        cr, d, q, code = self.cr, self.data, spec['quality'], spec['code']
        spec['unrestricted'] = bool(self.unrestricted.get())     # free values: used by mods() / validate() / build()
        b = d.base(code)
        self.title.configure(text=f"{clean(cr.describe(spec))} - {clean(b.name)}")
        f = self.opts
        r = 0
        NONE = none_label()

        def row(label):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky='nw', padx=(0, 8), pady=2)
            r += 1
            return r - 1

        def combo(label, values, current, on_change, width=40, stretch=True):
            """Read-only combobox; on_change(index in values). Each call keeps its own list (no shared variable)."""
            rr = row(label)
            values = list(values)
            var = tk.StringVar(value=current)
            c = ttk.Combobox(f, state='readonly', values=values, textvariable=var, width=width)
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
            return combo(label, vals, str(cur), lambda i, vals=vals: on_change(int(vals[i])), 8, False)

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
            fill = cr.sockets_fillers()
            EMPTY = empty_label()
            vals = [EMPTY] + [clean(n) for _, n in fill]
            for k in range(spec['sockets']):
                cur = spec['socketed'][k] if k < len(spec['socketed']) else None
                curl = next((clean(n) for c_, n in fill if c_ == cur), EMPTY)
                combo(T('cr.socket_n', '  Socket {n}', n=k + 1), vals, curl,
                      lambda i, k=k, fill=fill: self.set_socket(k, None if i == 0 else fill[i - 1][0]), 30, False)
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
                combo(lab, vals, cur, lambda i, n=n, lst=lst: self.set_rare_name(n, lst[i][0]), 30, False)
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
            c = ttk.Combobox(box, state='readonly', values=vals, textvariable=var, width=40)
            c.grid(row=0, column=0, sticky='we')
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
                self.slider(self.opts, r, T('cr.base_defense', 'Base defense'), min(lo, cur), max(hi, cur), cur,
                            lambda v: self.set_field('defense', v, False))
                r += 1
            else:
                rr = row(T('cr.base_defense', 'Base defense'))
                ttk.Label(f, text=T('cr.def_fixed', '{v} (fixed: Enhanced Defense)', v=lo)).grid(row=rr, column=1, sticky='w')
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

    def slider(self, parent, r, label, lo, hi, cur, on_release, fmt=str):
        """Label on its own line, then the slider, its value and its range; saving on release."""
        box = ttk.Frame(parent)
        box.grid(row=r, column=0, columnspan=2, sticky='we', pady=(4, 0))
        ttk.Label(box, text=label).pack(anchor='w')
        fr = ttk.Frame(box)
        fr.pack(fill='x')
        var = tk.IntVar(value=cur)
        val = ttk.Label(fr, text=fmt(cur), width=22)

        def moved(x):
            v = int(round(float(x)))
            if v != var.get():
                var.set(v)
            val.configure(text=fmt(var.get()))

        sc = ttk.Scale(fr, from_=lo, to=hi, orient='horizontal', length=300, command=moved)
        sc.set(cur)
        sc.pack(side='left', padx=(12, 0))
        val.pack(side='left', padx=8)
        ttk.Label(fr, text=T('cr.range_fmt', '{lo} to {hi}', lo=fmt(lo), hi=fmt(hi)) if fmt is not str else
                  T('cr.range', '({lo} to {hi})', lo=lo, hi=hi)).pack(side='left')
        sc.bind('<ButtonRelease-1>', lambda e: on_release(var.get()))
        for key, dv in (('<Left>', -1), ('<Right>', 1)):
            sc.bind(key, lambda e, dv=dv: (sc.set(max(lo, min(hi, var.get() + dv))), on_release(var.get()), 'break')[-1])
        return var

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
        for w in inner.winfo_children():
            w.destroy()
        unr = self.unrestricted.get()          # the spec flag itself is set in render_options / current_blob
        mods = [m for m in self.cr.mods(self.spec) if m.variable]
        raw_extra = [x for x in self.spec.get('extra') or [] if self.cr._visible(x)]
        table = self.edit_item is not None and (unr or raw_extra)
        if not mods and not raw_extra and not unr and not table:
            ttk.Label(inner, text=T('cr.no_variable', 'No variable values: everything on this item is fixed.')).grid(row=0, column=0, sticky='w')
            return
        r = 0
        if raw_extra and not unr and not table:
            from mxl_tooltip import stat_lines
            try:
                lines = [str(x[1]).strip() for x in stat_lines(raw_extra, self.data, None) if str(x[1]).strip()]
            except Exception:
                lines = [f"stat {x['id']}: {x['value']}" for x in raw_extra]
            ttk.Label(inner, text=T('cr.kept_list', 'Kept as they are on the item (not from its affixes or its recipe): {lines}',
                                    lines='; '.join(lines)), wraplength=520, justify='left').grid(row=r, column=0, columnspan=2, sticky='w')
            r += 1
        elif unr:
            note = (T('cr.edit_note', 'Unrestricted: the item\'s own stat list is below - click a stat to select '
                      'it, add, replace or delete rows; a value the format cannot store is capped.')
                    if table else
                    T('cr.unrestricted_note', 'Unrestricted: the values below can go anywhere the save format '
                      'holds (a value the format cannot store is warned about, never written). Raw stats to add, '
                      'edit or delete by stat id are at the bottom.'))
            ttk.Label(inner, text=note, wraplength=520, justify='left').grid(
                row=r, column=0, columnspan=2, sticky='w')
            r += 1
        for m in mods:
            lo, hi = m.min, m.max
            if unr and m.variable:                       # free slider: the whole storable range of its stat
                rng = self.cr.storage_range(m)
                if rng:
                    lo, hi = min(m.min, rng[0]), max(m.max, rng[1])
            label = f"{T('cr.mod.' + m.label.lower(), m.label) + ': ' if m.label else ''}{self.mod_label(m)}"
            self.slider(inner, r, label, lo, hi, m.value, lambda v, src=m.source: self.set_roll(src, v),
                        self.value_format(m))
            r += 1
        if unr or table:
            if table:
                r = self.render_edit_stats(inner, r)      # the item's own stats as the game shows them
            else:
                r = self._raw_stats(inner, r, 'extra', T('cr.raw.stats', "Raw stats (the item's own list)"))
            r = self._orange_text(inner, r)               # unique orange text (display + hidden effect)
            if self.spec.get('quality') == 'runeword':
                r = self._raw_stats(inner, r, 'extra_rw', T('cr.raw.rw', "Raw stats (the runeword's list)"))

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
        rec = self._spins.get(w) if w is not None else None
        if rec is None:
            return
        try:
            if w.get() != rec[1]:
                rec[0]()
                rec[1] = w.get()
        except Exception as e:
            print('spin commit:', e)

    def _stat_choices_labels(self):
        choices = self.cr.stat_choices()
        return choices, [lab for _sid, lab in choices], {lab: sid for sid, lab in choices}

    def _raw_stat_commit(self, e, var, sid, value=True):
        """Commits one raw stat entry (value or param), clamped by the save format's bounds."""
        cr = self.cr
        rng = cr.stat_bounds(sid)
        try:
            v = int(var.get())
        except (tk.TclError, ValueError):
            v = None
        if v is None:
            v = 0 if value else 0
        if rng:
            clamped = max(rng[0], min(rng[1], v))
            if clamped != v:
                self.set_status(T('cr.raw.clamped', 'raw stat #{sid}: {v} cannot be stored, {lo} to {hi}',
                                  sid=sid, v=v, lo=rng[0], hi=rng[1]))
            v = clamped
            var.set(v)
        if value:
            e['value'] = v
            self._take_over((sid, e.get('param')))
            drop = self.spec.get('_drop')
            if drop is not None:
                drop.discard((sid, e.get('param')))
        else:
            e['param'] = v if v else None
            self._take_over((sid, e.get('param')))
        self.refresh()

    def _raw_stats(self, parent, r, key, title):
        """The unrestricted raw stat rows of spec[key] (['extra'] = the item's own list, ['extra_rw'] = the
        runeword's): per row the stat id (every stat the save format holds), its param and its free value,
        with a delete button, and an add button. Same (stat, param) entries add up when the item is written,
        like the game's own stat lists."""
        spec, d, cr = self.spec, self.data, self.cr
        entries = spec.setdefault(key, [])
        ttk.Label(parent, text=title, font=('Segoe UI', 10, 'bold')).grid(
            row=r, column=0, columnspan=2, sticky='w', pady=(8, 0))
        r += 1
        choices, labels, by_label = self._stat_choices_labels()
        for e in entries:
            e_local = e
            sid = e_local['id']
            cur = next((lab for s, lab in choices if s == sid), f'(unknown stat #{sid})')
            box = ttk.Frame(parent)
            box.grid(row=r, column=0, columnspan=2, sticky='we', pady=1)
            c = ttk.Combobox(box, values=labels, width=44)     # not readonly: typing autofills (Enter commits)
            c.set(cur)
            c.grid(row=0, column=0, sticky='w')
            self.scroll.no_wheel(c)

            def id_picked(_e, e=e_local, cb=c):
                i = cb.current()
                if i < 0:
                    lab = cb.get().strip().lower()             # typed text: resolve it back to the stat
                    i = next((k for k, (_s, l) in enumerate(choices) if l.lower() == lab), -1)
                if i < 0 or i >= len(choices):
                    return
                e['id'] = sid = choices[i][0]
                pbits = (d.isc[sid]['param'] or 0) if 0 <= sid < len(d.isc) else 0
                if not pbits:
                    e['param'] = None
                rng = cr.stat_bounds(sid)
                e['value'] = max(rng[0], min(rng[1], e.get('value') or 1))
                self.set_status(T('cr.raw.statinfo', 'stat #{sid}, {pb} param bits, save range {lo} to {hi}',
                                  sid=sid, pb=pbits, lo=rng[0], hi=rng[1]))
                self.render_options()
            c.bind('<<ComboboxSelected>>', id_picked)
            bind_stat_picker(c, labels, lambda lab, e=e_local, cb=c: id_picked(None, e, cb))
            try:
                pbits = d.isc[sid]['param'] or 0
            except (IndexError, KeyError, TypeError):
                pbits = 0
            kind = param_kind(sid)
            if kind in ('skill', 'skill_only', 'class'):
                if kind == 'class':
                    from mxl_rules import CLASSES
                    names = list(CLASSES)
                else:
                    names = [n for n, _sk in skill_names_sorted(d, sid)]
                parts = decode_param(d, sid, e_local.get('param'))
                nm = tk.StringVar(value=(parts or ('',))[0] or (names[0] if names else ''))
                cb = ttk.Combobox(box, values=names, textvariable=nm, width=22)
                cb.grid(row=0, column=1, sticky='w', padx=(6, 2))
                self.scroll.no_wheel(cb)
                bind_typeahead(cb, names)
                lv = None
                if kind == 'skill':
                    lv = tk.IntVar(value=(parts or ('', 1))[1] if parts and parts[1] is not None else 1)
                    sl = ttk.Spinbox(box, from_=1, to=63, textvariable=lv, width=4)
                    sl.grid(row=0, column=2, sticky='w', padx=(2, 2))
                    self.scroll.no_wheel(sl)

                    def commit_param(_e=None, nm=nm, lv=lv):
                        newp, why = encode_skill_param(d, e_local['id'], nm.get(),
                                                       int(lv.get()) if lv is not None else None)
                        if newp is None:
                            self._skill_status(why, nm.get())
                            return
                        e_local['param'] = newp
                        self._take_over((e_local['id'], newp))
                        self.refresh()
                else:
                    def commit_param(_e=None, nm=nm):
                        newp, why = encode_skill_param(d, e_local['id'], nm.get(), None)
                        if newp is None:
                            self._skill_status(why, nm.get())
                            return
                        e_local['param'] = newp
                        self._take_over((e_local['id'], newp))
                        self.refresh()
                cb.bind('<<ComboboxSelected>>', commit_param)
                if lv is not None:
                    self._spin_commit(sl, commit_param)
            elif sid == STATE_STAT and pbits:
                # the state stat (98): param = state id - a dropdown of the states the skills set,
                # named after the skills that set them (the states table carries no names)
                snames = state_names_sorted(d)
                cur = next((n for n, v in snames if v == e_local.get('param')), None)
                nm = tk.StringVar(value=cur or (snames[0][0] if snames else ''))
                cb = ttk.Combobox(box, values=[n for n, _v in snames], textvariable=nm, width=22)
                cb.grid(row=0, column=1, sticky='w', padx=(6, 2))
                self.scroll.no_wheel(cb)
                bind_typeahead(cb, [n for n, _v in snames])

                def commit_state(_e=None, nm=nm, e=e_local, snames=snames):
                    v = next((v for n, v in snames if n == nm.get()), None)
                    if v is None:
                        return
                    e['param'] = v
                    self._take_over((e['id'], v))
                    self.refresh()
                cb.bind('<<ComboboxSelected>>', commit_state)
            elif pbits:
                pv = tk.IntVar(value=max(0, e.get('param') or 0))
                sp = ttk.Spinbox(box, from_=0, to=(1 << pbits) - 1, textvariable=pv, width=8)
                sp.grid(row=0, column=1, sticky='w', padx=(6, 2))
                self._spin_commit(sp, lambda pv=pv, e=e_local, sid=sid: self._raw_stat_commit(e, pv, sid, value=False))
            else:
                ttk.Label(box, text=' - ').grid(row=0, column=1, padx=(6, 2))
            rng = cr.stat_bounds(sid) or (0, 0)
            vc = 3 if kind == 'skill' else 2          # skill rows keep a slot for the cast level at col 2
            vv = tk.IntVar(value=max(rng[0], min(rng[1], e.get('value') or 0)))
            sv = ttk.Spinbox(box, from_=rng[0], to=rng[1], textvariable=vv, width=10)
            sv.grid(row=0, column=vc, sticky='w', padx=(6, 2))
            self._spin_commit(sv, lambda vv=vv, e=e_local, sid=sid: self._raw_stat_commit(e, vv, sid))

            def remove(e=e_local):
                try:
                    entries.remove(e)
                except ValueError:
                    pass
                self.render_options()
            D2.button(box, 'x', remove, 2).grid(row=0, column=vc + 1, padx=(6, 0))
            r += 1
        add_entries = entries

        def add(*_a):
            sid = choices[0][0] if choices else 0
            add_entries.append(dict(id=sid, param=None, value=1))
            self.render_options()
        D2.button(parent, T('cr.raw.add', '+ Add stat'), add, 8).grid(row=r, column=0, columnspan=2, sticky='w', pady=(4, 2))
        return r + 1

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
        ttk.Label(parent, text=T('cr.orange.title', 'Unique orange text (display + hidden)'),
                  font=('Segoe UI', 10, 'bold')).grid(row=r, column=0, columnspan=2, sticky='w', pady=(8, 0))
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
        ttk.Label(box, text=T('cr.orange.display', 'display')).grid(row=0, column=0, sticky='w')
        cb = ttk.Combobox(box, values=labels, width=46)      # typing autofills (Enter commits)
        cb.grid(row=0, column=1, sticky='w', padx=(4, 2))
        self.scroll.no_wheel(cb)
        ttk.Label(box, text=T('cr.orange.hidden', 'hidden')).grid(row=1, column=0, sticky='w')
        hb = ttk.Combobox(box, state='readonly', width=46)
        hb.grid(row=1, column=1, sticky='w', padx=(4, 2))
        self.scroll.no_wheel(hb)
        # the paired effects: the other attributes the game's own source row writes with this text
        # (the counter / oskill grant / companion block that make it true). Multi-select; every
        # selected entry is written into the item's stat list next to the text, where it shows up
        # as its own editable row.
        ttk.Label(box, text=T('cr.orange.effect', 'effect')).grid(row=2, column=0, sticky='w')
        eff = tk.Listbox(box, selectmode='extended', height=4, exportselection=False,
                         activestyle='none')
        eff.grid(row=2, column=1, sticky='we', padx=(4, 2))
        eff.configure(width=48)
        self.scroll.no_wheel(eff)
        rng = cr.stat_bounds(texts[0]['display']['id']) or (0, 1)
        vv = tk.IntVar(value=texts[0]['display']['value'])
        ttk.Label(box, text=T('cr.orange.value', 'value')).grid(row=3, column=0, sticky='w')
        sv = ttk.Spinbox(box, from_=min(0, rng[0]), to=max(rng[1], 1), textvariable=vv, width=10)
        sv.grid(row=3, column=1, sticky='w', padx=(4, 2))
        self.scroll.no_wheel(sv)

        def sync(_e=None):
            lab = cb.get().strip().lower()
            i = next((k for k, t in enumerate(texts) if t['label'].lower() == lab), -1)
            if i < 0:
                i = next((k for k, t in enumerate(texts) if t['label'].lower().startswith(lab)), -1)
            if i < 0:
                i = st['i']
            st['i'] = i
            cb.set(labels[i])
            ch = hidden_choices(i)
            hb.configure(values=ch)
            t = texts[i]
            if t['skilldesc'] and t['display']['param'] < len(sd_names):
                hb.set(f"{sd_names[t['display']['param']]}  (param {t['display']['param']})")   # the game's own pairing
            else:
                hb.current(1 if t['hidden'] else 0)
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
                m = re.search(r'\(param (\d+)\)', hb.get())
                if m:
                    param = int(m.group(1))          # a skill picked in the hidden dropdown overrides
            entries = self.spec.setdefault('extra', [])
            entries.append(dict(id=t['display']['id'], param=param, value=value))
            if not t['skilldesc']:
                idx = 0
                try:
                    idx = hb.current()
                except Exception:
                    idx = 0
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
        cb.bind('<<ComboboxSelected>>', sync)
        bind_stat_picker(cb, labels, lambda _lab: sync())
        D2.button(parent, T('cr.orange.add', '+ Add orange text'), add, 8).grid(
            row=r + 1, column=0, columnspan=2, sticky='w', pady=(4, 2))
        return r + 2

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

    def _skill_status(self, why, name):
        """Why a skill (or class) param could not be encoded."""
        if why == 'rolled':
            self.set_status(T('cr.raw.rolled_skill',
                              '{name}: skill id too large for this stat\'s param field - the game would '
                              'roll it to another skill, so it cannot be stored', name=name), error=True)
        elif why == 'level':
            self.set_status(T('cr.raw.bad_level', 'the cast level must be 0 to 63'), error=True)
        else:
            self.set_status(T('cr.raw.unknown_skill', 'unknown skill: {name}', name=name), error=True)

    def _edit_row_label(self, key, val):
        d = self.data
        sid, param = key
        try:
            hidden = stat_hidden(sid, d, val)
        except Exception:
            hidden = False
        txt = ''
        if not hidden:
            try:
                txt = stat_text(d, sid, param, value=val,
                                desc=(d.isc[sid]['desc'] if 0 <= sid < len(d.isc) else None))
            except Exception:
                txt = ''
        if not txt:
            import mxl_statnames_ext
            txt = mxl_statnames_ext.fallback_label(sid)
        if not txt:
            txt = f'(stat #{sid})'
        if param_kind(sid) in ('skill', 'skill_only', 'class'):
            parts = decode_param(d, sid, param)     # the skill's name is usually already in the game text
            if parts and (not txt or str(parts[0]).lower() not in txt.lower()):
                txt += f'  [{parts[0]}]'
        elif param is not None:
            txt += f' - param {param}'
        return txt

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

    def render_edit_stats(self, parent, r):
        """The item's own stat list as the game shows it (not deltas): one row per (stat, param) with its
        final value (the mods' total plus its delta). Editing routes through a mod roll when one mod owns
        the stat alone, else through the raw delta rows that are hidden here. A click selects a row for
        'Replace selected'; every skill-stat row has a skill dropdown (+ cast level), the chance box and a
        delete button."""
        d, cr = self.data, self.cr
        made = self._edit_made()
        extra_keys = {(e['id'], e.get('param')) for e in self.spec.get('extra') or []}
        drop = self.spec.get('_drop') or set()
        keys = list(dict.fromkeys(list(made) + [k for k in extra_keys if k not in made]))
        keys = [k for k in keys if k not in drop]      # attributes the user deleted stay off the table
        ttk.Label(parent, text=T('cr.item_stats', 'Item stats (the item\'s own list)'), font=('Segoe UI', 10, 'bold')
                  ).grid(row=r, column=0, columnspan=2, sticky='w', pady=(8, 0))
        r += 1
        self._edit_rows = {}
        if not keys:
            ttk.Label(parent, text=T('cr.item_stats.none', '(no stat stored)')).grid(
                row=r, column=0, sticky='w')
            r += 1
        for k in keys:
            sid, param = k
            e = self._edit_extra(k)
            val = made.get(k, 0) + (e['value'] if e else 0)
            rng = cr.stat_bounds(sid)
            cur = max(rng[0], min(rng[1], val)) if rng else val
            kind = param_kind(sid)
            lab = ttk.Label(parent, text='', cursor='hand2')
            parts = decode_param(d, sid, param) if kind else None

            def mark_key(k=k):
                e2 = self._edit_extra(k)
                self._edit_sel = k
                lbl = ('* ' if True else '') + self._edit_row_label(k, made.get(k, 0) + (e2['value'] if e2 else 0))
                for kk, lb in self._edit_rows.items():
                    if self._edit_rows[kk] is lab:
                        lb.configure(text=lbl)
                    else:
                        e3 = self._edit_extra(kk)
                        t3 = self._edit_row_label(kk, made.get(kk, 0) + (e3['value'] if e3 else 0))
                        if lb.cget('text').startswith('* '):
                            lb.configure(text=t3)
                self.set_status(T('cr.edit.selected', 'Selected: {label}',
                                  label=self._edit_row_label(k, made.get(k, 0) + (e2['value'] if e2 else 0))))

            def lab0(kk):
                e2 = self._edit_extra(kk)
                return self._edit_row_label(kk, made.get(kk, 0) + (e2['value'] if e2 else 0))

            lab.configure(text=('* ' if self._edit_sel == k else '') + lab0(k))
            lab.grid(row=r, column=0, sticky='we', pady=1)
            lab.bind('<Button-1>', lambda _e, fn=mark_key: fn())
            self._edit_rows[k] = lab
            vvar = tk.IntVar(value=cur)

            def commit_value(k=k, var=vvar, rng=rng):
                if rng:
                    self._int(var, rng[0], rng[1])
                    self.route_target(k, var.get())
                self.refresh()

            sv = ttk.Spinbox(parent, from_=rng[0], to=rng[1], textvariable=vvar, width=10)
            self.scroll.no_wheel(sv)
            sv.grid(row=r, column=1, sticky='w', pady=1)
            self._spin_commit(sv, commit_value)
            if kind:
                if kind == 'class':
                    from mxl_rules import CLASSES
                    names = list(CLASSES)
                else:
                    names = [n for n, _sk in skill_names_sorted(d, sid)]
                nm = tk.StringVar(value=(parts or ('',))[0] or (names[0] if names else ''))
                cb = ttk.Combobox(parent, values=names, textvariable=nm, width=22)
                cb.grid(row=r, column=2, sticky='w', padx=(4, 2), pady=1)
                self.scroll.no_wheel(cb)
                bind_typeahead(cb, names)
                lv = None
                lc = 3
                if kind == 'skill':
                    ttk.Label(parent, text=T('cr.edit.level', 'lvl'), width=4).grid(row=r, column=3, sticky='e')
                    lv = tk.IntVar(value=(parts or ('', 1))[1] if parts and parts[1] is not None else 1)
                    sl = ttk.Spinbox(parent, from_=1, to=63, textvariable=lv, width=4)
                    sl.grid(row=r, column=3, sticky='w', padx=(2, 0))
                    lc = 4

                    def commit_param(_e=None, nm=nm, lv=lv, k=k, cb_=cb):
                        newp, why = encode_skill_param(d, k[0], nm.get(), int(lv.get()))
                        if newp is None:
                            self._skill_status(why, nm.get())
                            return
                        self._edit_set_param(k, newp)
                else:
                    def commit_param(_e=None, nm=nm, lv=None, k=k):
                        newp, why = encode_skill_param(d, k[0], nm.get(), None)
                        if newp is None:
                            self._skill_status(why, nm.get())
                            return
                        self._edit_set_param(k, newp)
                cb.bind('<<ComboboxSelected>>', commit_param)
                if lv is not None:
                    self._spin_commit(sl, commit_param)
                bcol = lc + 1
            else:
                bcol = 2
            b = D2.button(parent, 'x', (lambda k=k: self._edit_delete(k)), 2)
            b.grid(row=r, column=bcol, padx=(4, 0), pady=1)
            r += 1
        r = self._edit_build_pick(parent, r)
        return r

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
            keys = {k for k in list(made) + extra_keys if k[0] == sid}
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

    def _edit_pick_param_zone(self, pf, pick):
        """The param widgets of the picked stat in the add/replace row: a skill dropdown (+ cast level),
        a class dropdown, or a plain param box. Rebuilt on every pick."""
        d = self.data
        for w in pf.winfo_children():
            w.destroy()
        kind = param_kind(pick['sid'])
        self._ep = {k: v for k, v in getattr(self, '_ep', {}).items() if k in ('sid',)}
        self._ep['sid'] = pick['sid']
        names = None
        if kind in ('skill', 'skill_only'):
            names = [n for n, _k in skill_names_sorted(d, pick['sid'])]
            ttk.Label(pf, text=T('cr.edit.skill', 'skill')).grid(row=0, column=0)
        elif kind == 'class':
            from mxl_rules import CLASSES
            names = list(CLASSES)
            ttk.Label(pf, text=T('cr.edit.class', 'class')).grid(row=0, column=0)
        elif pick['sid'] == STATE_STAT and pick['sid'] < len(d.isc) and (d.isc[pick['sid']]['param'] or 0):
            # the state stat (98): param = state id, named after the skills that set it
            snames = state_names_sorted(d)
            ttk.Label(pf, text=T('cr.edit.state', 'state')).grid(row=0, column=0)
            nm = tk.StringVar(value=snames[0][0] if snames else '')
            cb = ttk.Combobox(pf, state='readonly', values=[n for n, _v in snames], textvariable=nm, width=24)
            cb.grid(row=0, column=1, padx=(4, 2))
            self.scroll.no_wheel(cb)
            bind_typeahead(cb, [n for n, _v in snames])
            self._ep['name'] = nm
            self._ep['state_names'] = snames
            return
        elif (d.isc[pick['sid']]['param'] or 0) if 0 <= pick['sid'] < len(d.isc) else 0:
            ttk.Label(pf, text=T('cr.edit.param', 'param')).grid(row=0, column=0)
            pv = tk.IntVar(value=0)
            sp = ttk.Spinbox(pf, from_=0, to=(1 << (d.isc[pick['sid']]['param'] or 1)) - 1, textvariable=pv, width=8)
            sp.grid(row=0, column=1, padx=(4, 0))
            self._ep['param'] = pv
            return
        else:
            return
        nm = tk.StringVar(value=names[0] if names else '')
        cb = ttk.Combobox(pf, state='readonly', values=names, textvariable=nm, width=24)
        cb.grid(row=0, column=1, padx=(4, 2))
        self.scroll.no_wheel(cb)
        bind_typeahead(cb, names)
        self._ep['name'] = nm
        if kind == 'skill':
            ttk.Label(pf, text=T('cr.edit.level', 'level')).grid(row=0, column=2, padx=(8, 0))
            lv = tk.IntVar(value=1)
            ttk.Spinbox(pf, from_=1, to=63, textvariable=lv, width=4).grid(row=0, column=3, padx=(2, 0))
            self._ep['level'] = lv

    def _edit_picked_param(self, pick):
        """(param, why) of the picked stat's param widgets: (param, None) on success, else (None, reason)
        (see encode_skill_param; a plain param box only clamps itself, so reason is always None there)."""
        p = getattr(self, '_ep', {})
        sid = pick['sid']
        kind = param_kind(sid)
        if kind in ('skill', 'skill_only', 'class'):
            name = str(p.get('name') and p['name'].get() or '')
            try:
                lvl = int(p['level'].get()) if kind == 'skill' else None
            except (AttributeError, ValueError, tk.TclError):
                lvl = 1
            return encode_skill_param(self.data, sid, name, lvl)
        if sid == STATE_STAT and 'state_names' in p:
            name = str(p.get('name') and p['name'].get() or '')
            v = next((v for n, v in p['state_names'] if n == name), None)
            return (v, None) if v is not None else (None, 'unknown')
        try:
            return (int(p['param'].get()) if 'param' in p else None), None
        except (AttributeError, ValueError, tk.TclError):
            return None, None

    def _edit_build_pick(self, parent, r):
        """The add / replace row of the item-stats table: pick a stat (whole list), its skill or param, a
        value; '+ Add stat' appends it, 'Replace selected' turns the clicked row's stat into this one."""
        d = self.data
        choices, labels, _m = self._stat_choices_labels()
        pick = {'sid': choices[0][0] if choices else 0}
        box = ttk.Frame(parent)
        box.grid(row=r, column=0, columnspan=2, sticky='we', pady=(4, 2))
        ttk.Label(box, text=T('cr.edit.add_stat', 'Add stat:')).grid(row=0, column=0, sticky='w')
        c = ttk.Combobox(box, values=labels, width=44)     # not readonly: typing autofills (Enter commits)
        if labels:
            c.set(labels[0])
        c.grid(row=0, column=1, sticky='w', padx=(6, 2))
        self.scroll.no_wheel(c)

        def pick_by_label(lab):
            i = next((k for k, (_s, l) in enumerate(choices) if l == lab), -1)
            if i >= 0:
                pick['sid'] = choices[i][0]
                picked()
        pf = ttk.Frame(box)
        pf.grid(row=0, column=2, sticky='w')
        self._edit_pick_param_zone(pf, pick)
        rng = self.cr.stat_bounds(pick['sid']) or (0, 0)
        vvar = tk.IntVar(value=max(rng[0], min(rng[1], 1)))
        sv = ttk.Spinbox(box, from_=rng[0], to=rng[1], textvariable=vvar, width=10)
        sv.grid(row=0, column=3, sticky='w', padx=(6, 2))
        self.scroll.no_wheel(sv)

        def picked(_e=None):
            i = c.current()
            if 0 <= i < len(choices):
                pick['sid'] = choices[i][0]
                sid = pick['sid']
                pb = (d.isc[sid]['param'] or 0) if 0 <= sid < len(d.isc) else 0
                self.set_status(T('cr.raw.statinfo', 'stat #{sid}, {pb} param bits, save range {lo} to {hi}',
                                  sid=sid, pb=pb, lo=self.cr.stat_bounds(sid)[0],
                                  hi=self.cr.stat_bounds(sid)[1]))
            self._edit_pick_param_zone(pf, pick)
            rng2 = self.cr.stat_bounds(pick['sid']) or (0, 0)
            sv.configure(from_=rng2[0], to=rng2[1])
            vvar.set(max(rng2[0], min(rng2[1], vvar.get() or rng2[1])))
        c.bind('<<ComboboxSelected>>', picked)
        bind_stat_picker(c, labels, pick_by_label)

        def picked_param():
            """(sid, param, v, why) of the picked stat: why is not None only when a skill pick was
            refused (encode_skill_param); a stat without a param field comes back as (sid, None, v, None)."""
            sid = pick['sid']
            param, why = self._edit_picked_param(pick)
            if param is None and why is not None:
                name = str(getattr(self, '_ep', {}).get('name') and self._ep['name'].get() or '')
                self._skill_status(why, name)
            rng2 = self.cr.stat_bounds(sid) or (0, 0)
            try:
                v = max(rng2[0], min(rng2[1], int(vvar.get())))
            except (ValueError, tk.TclError):
                v = rng2[1]
            return sid, param, v, why

        def add(*_a):
            sid, param, v, why = picked_param()
            if why is not None:
                return                      # refused skill pick: the status bar says why
            key = (sid, param)
            self.set_extra_delta(key, v - self._edit_made().get(key, 0))
            self._take_over(key)
            self._edit_sel = key
            self.render_mods()
            self.refresh()

        def replace(*_a):
            if not getattr(self, '_edit_sel', None):
                self.set_status(T('cr.edit.no_sel', 'Click a stat row first: the picked stat replaces it.'))
                return
            sid, param, _v, why = picked_param()
            if why is not None:
                return
            made = self._edit_made()
            old = self._edit_sel
            e = self._edit_extra(old)
            val = self._edit_clamp(sid, made.get(old, 0) + (e['value'] if e else 0))
            self._edit_cancel_key(old)
            key = (sid, param)
            self.set_extra_delta(key, val - made.get(key, 0))
            self._take_over(key)
            self._edit_sel = key
            self.render_mods()
            self.refresh()

        D2.button(box, T('cr.edit.replace', 'Replace selected'), replace, 15).grid(row=0, column=5, padx=(2, 0))
        D2.button(box, T('cr.edit.add', '+ Add stat'), add, 10).grid(row=0, column=4, padx=(2, 0))
        return r + 1

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
    if it is None or not app.path:
        messagebox.showinfo(T('cr.edit', 'Edit item'), T('cr.select_first', 'Select an item of the stash first.'))
        return
    CreatorWindow(app, edit_item=it)


def toggle_editing(app, var):
    app.editing = bool(var.get())
    settings.put('editing_enabled', app.editing)
    app.set_detail(app.selected)


def install(App):
    """Adds the Creator / Edit / Delete buttons and the value-editing switch to the collector's main window."""
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
        var = tk.BooleanVar(value=bool(self.editing))
        ttk.Checkbutton(bar, text=T('cr.value_editing', 'Value editing'), variable=var,
                        command=lambda: toggle_editing(self, var)).pack(side='left', padx=(8, 2))
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
    import mxl_free                      # no "the game must be closed" checks: editing works while the game is open
    mxl_free.install()
    import mxl_format_fix                # Sigma item layouts the collector's reader did not know (before anything reads)
    mxl_format_fix.install()
    import mxl_gui
    rename_app(mxl_gui)
    import mxl_d2look                     # no game-art panels: the plain Hero-Editor grids replace them
    mxl_d2look.disable()
    import mxl_tabs                       # every editor window becomes a tab of the main window (tiling WM)
    mxl_tabs.install(mxl_gui.App)
    import mxl_hover                      # item stats follow the mouse hover (no click needed)
    mxl_hover.install(mxl_gui.App)
    import mxl_he_grid                    # the collector's dark constants -> Hero-Editor light palette
    mxl_he_grid.install(mxl_gui.App)      # (innermost: before any window is built)
    import mxl_char_gui
    remove_library(mxl_gui)
    install(mxl_gui.App)
    mxl_char_gui.install(mxl_gui.App)
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
    import mxl_he_theme                    # the Hero-Editor look for every window - outermost (walks what others build)
    mxl_he_theme.install(mxl_gui.App)
    import mxl_app_icon
    mxl_app_icon.install(mxl_gui.App)
    mxl_splash.install(mxl_gui.App)       # last: outermost, closes the splash once everything is built
    mxl_log.wrap_saves()                  # writers bound by name in the modules imported since install()
    try:
        mxl_gui.main()
    finally:
        mxl_splash.close()
