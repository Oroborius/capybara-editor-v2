"""Hero Editor v1.04-style "Magic Attributes" list for one item (the "Item stats" tab).

Left: the item's attribute slots, one compact numbered row per stored stat (the game's own stat text, the
value, and - where the stat carries one - the cast level and the skill / class by NAME), followed by
"(empty)" slots (the save format ends a stat list with a marker and has no fixed slot count: the used slots
plus empty ones are shown, at least SLOTS_MIN). Right: the attribute picker of mxl_attr_picker (categories |
stats, one filter over all categories); it turns into a skill / class name list while a row's skill is chosen.

Keys in the slot list: Up / Down / PgUp / PgDn / Home / End move; Enter or a double-click opens the picker
for the slot (pick = replace the slot's stat, or fill an empty slot); Delete clears the slot; typing a number
(or F2) edits the value in place; Right / Left walk the row's editable cells; typing letters starts the
picker's filter; Ctrl+S saves. In a value box: Enter writes, Tab goes to the row's next cell, Up / Down keep
the typed value and move, Escape gives up.

The engine is the one of the former flat table:
- "Save changes" (or Enter in a value box) writes changed values of a stash item in place through
  mxl_save.apply_edits - one file write, verification, .bak backup; linked stats (the groups the game keeps
  together, like enhanced damage base + average) are written with the collector's own set_stat logic;
- an added, replaced or cleared slot (and a changed skill / level / param) rewrites the item's bytes through
  a lossless decode -> encode round trip via mxl_save.edit_stash, at the item's own place - its socketed
  items follow; the main window is reloaded then, as offsets shift;
- a character's item (equipment, mercenary, inventory) is re-encoded in the character's entry and saved
  through the character window;
- values: anything the save format stores (ItemStatCost save bits / add); the game's affix ranges are ignored
  on purpose (unrestricted build). A value the format cannot store is capped to what it can, never written
  wrong; a stat stored by an auto-affix tier can only take one of its tier values (the status bar says so).

Everything goes through the collector's own safe writers (verification, backups), never direct file writes.
"""
import os

import tkinter as tk
import tkinter.ttk as ttk

import mxl_save
from mxl_save import edit_stash, apply_edits, EditError
from mxl_format import FormatError
from mxl_rules import stat_hidden
from mxl_lang import T
from mxl_creator import decode_blob, build_blob
from mxl_statnames import (stat_text, param_kind, decode_param, encode_skill_param, skill_names_sorted,
                           param_bits, param_choices, param_title, param_spec, param_name)
import mxl_attr_picker as AP

SLOTS_MIN = 30          # Hero Editor showed 30 magic attribute slots
SLOTS_SPARE = 4         # empty slots always left after the used ones
TAB_KEY = 'Item stats'


def he(key, default, **fields):
    """The window's own strings: keys 'he.stats.*' (the character window has plain 'he.*' keys already)."""
    return T('he.stats.' + key, default, **fields)


def _stat_info(data, sid):
    try:
        c = data.isc[sid]
    except (IndexError, KeyError, TypeError):
        return None
    return {'bits': c.get('bits') or 0, 'param': c.get('param') or 0, 'desc': c.get('desc'),
            'add': c.get('add') or 0}


def info_bits(c):
    return bool((c or {}).get('param'))


def value_range(data, sid):
    """(lowest, highest) value the save format stores for the stat: 'bits' save bits, biased by 'add'."""
    info = _stat_info(data, sid)
    if info is None or not info['bits']:
        return None
    return -info['add'], (1 << info['bits']) - 1 - info['add']


def _row_label(data, s):
    """Label of one stored stat entry: the game text when the game shows that stat itself, the editor's own
    name or '(stat #N)' for the internal ones (and for the mod's 'FLYING POLAR BUFFALO' placeholder strings).
    Clean Hero-Editor labels: no stat ids, bit counts or param numbers (the status bar shows those)."""
    sid, param = s['id'], s.get('param')
    c = _stat_info(data, sid)
    if c is None:
        return f'stat #{sid}'
    try:
        hidden = bool(stat_hidden(sid, data, float(s.get('value') or 0)))
    except Exception:
        hidden = False
    txt = ''
    if not hidden:
        shown = s.get('value') if param_kind(sid) == 'skill' else 1      # '5% Chance to cast level 3 ...'
        if param_spec(sid) is not None:         # a stat with a param: the line the item shows on hover
            shown = s.get('value')
            if param is None and param_kind(sid) in ('class', 'named'):
                param = 0                       # value 0 is stored as "no param"
        txt = stat_text(data, sid, param, value=shown if shown is not None else 1, desc=c.get('desc'))
    if not txt:
        import mxl_statnames_ext
        txt = mxl_statnames_ext.fallback_label(sid)
    return AP.clean_label(txt) if txt else f'(stat #{sid})'


def _row_info_text(data, s):
    """The technical line for the status bar when a slot is selected: stat id, param, save bits, value range."""
    sid, param = s['id'], s.get('param')
    c = _stat_info(data, sid)
    bits = (c or {}).get('bits') or 0
    par = f', param {param}' if param is not None else ''
    spec = param_spec(sid)
    if spec is not None and info_bits(c):
        try:
            if param_kind(sid) in ('class', 'named'):
                par = f', param {param or 0} = {param_title(sid)}: {param_name(data, sid, param)}'
            elif param_kind(sid) and param is not None:
                parts = decode_param(data, sid, param) or ('?', None)
                par += f' = {param_title(sid)}: {parts[0]}' + (f', level {parts[1]}' if parts[1] is not None else '')
            if spec.get('conf') and spec.get('kind') != 'number':
                par += f' [{spec["kind"]}, {spec["conf"]}]'
        except Exception:
            pass
    rng = value_range(data, sid)
    lim = f', {rng[0]}..{rng[1]}' if rng else ''
    return f'stat #{sid}{par}, {bits} bits{lim}, value {s.get("value")}'


class ItemStatsWindow:
    """The Magic Attributes list + attribute picker of one item: a tab of the main window (a Toplevel when the
    tabs are not installed). it: an item of the stash grid; chwin + entry: an item of the character window."""

    def __init__(self, app, it=None, chwin=None, entry=None):
        self.app = app
        self.chwin, self.entry = chwin, entry
        self.it = dict(it if it is not None else entry.it)
        self.cr = None
        self._bak = None
        self.pal = pal = AP.palette()
        self.m = m = AP.metrics(app.root)
        self.rows = []                        # display rows: dict(kind='head'|'slot', ...)
        self.lists = []                       # [(stat_list, [stored entries])]
        self.pending = {}                     # {(stat_list, index): typed value not written yet}
        self.sel = None                       # index into self.rows
        self._ed = None                       # (row index, field) of the open inline box
        self._busy = False
        self._fit = {}
        self._pick_mode = None                # (row index) while the right pane lists skill / class names

        try:
            import mxl_tabs
            top = mxl_tabs.host_window(app, TAB_KEY, owner=self, replace=True)
        except Exception:
            top = None
        if top is None:
            top = tk.Toplevel(app.root)
            ch, row = m['ch'], m['row']
            sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
            w, h = min(ch * 124, sw - 24), min(row * 36, sh - 64)
            top.geometry(f'{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}')
        self.top = top
        top.title(he('title', 'Item stats'))
        ch = m['ch']

        root = self.frame = tk.Frame(top, bg=pal['bg'])
        AP.exempt(root)
        root.pack(fill='both', expand=True, padx=3, pady=2)
        root.columnconfigure(0, weight=1, uniform='half')
        root.columnconfigure(1, weight=1, uniform='half')
        root.rowconfigure(1, weight=1)

        head = tk.Frame(root, bg=pal['bg'])
        head.grid(row=0, column=0, columnspan=2, sticky='we', pady=(0, 2))
        tk.Label(head, text=he('magic', 'Magic Attributes'), font=m['bold'], bg=pal['bg'], fg=pal['fg_hi']
                 ).pack(side='left')
        self.name_lab = tk.Label(head, text=self._name(), font=m['font'], bg=pal['bg'], fg=pal['fg'], anchor='w')
        self.name_lab.pack(side='left', padx=(ch, 0))
        for txt, cmd in ((he('close', 'Close'), self.close),
                         (he('clear', 'Clear slot'), self.delete_selected),
                         (he('pick', 'Pick...'), self.open_picker),
                         (he('save', 'Save changes'), self.save)):
            AP.button(head, txt, cmd, pal, m).pack(side='right', padx=(2, 0))

        # ---- the slot list
        left = tk.Frame(root, bg=pal['bg'])
        left.grid(row=1, column=0, sticky='nsew', padx=(0, 3))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        self.hdr = tk.Canvas(left, height=m['row'], bg=pal['head'], highlightthickness=0, bd=0)
        self.hdr.grid(row=0, column=0, sticky='we')
        self.cv = cv = tk.Canvas(left, bg=pal['field'], highlightthickness=1, highlightbackground=pal['line'],
                                 highlightcolor=pal['fg_hi'], bd=0, takefocus=1, yscrollincrement=m['row'],
                                 width=ch * 40, height=m['row'] * 6)
        cv.grid(row=1, column=0, sticky='nsew')
        sb = ttk.Scrollbar(left, orient='vertical', command=cv.yview)
        sb.grid(row=1, column=1, sticky='ns')
        cv.configure(yscrollcommand=sb.set)
        self.ed_var = tk.StringVar()
        self.ed = tk.Entry(cv, textvariable=self.ed_var, font=m['font'], bg=pal['field'], fg=pal['fg_hi'],
                           insertbackground=pal['fg_hi'], selectbackground=pal['sel'],
                           selectforeground=pal['sel_fg'], bd=0, relief='flat', highlightthickness=1,
                           highlightbackground=pal['fg_hi'], highlightcolor=pal['fg_hi'], justify='right')

        # ---- the right pane: attribute picker / name list, stacked
        right = self.right = tk.Frame(root, bg=pal['bg'])
        right.grid(row=1, column=1, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.picker = AP.AttrPicker(right, app.data, on_pick=self.picked, on_cancel=self.focus_list,
                                    choices=self._creator().stat_choices())
        self.picker.grid(row=0, column=0, sticky='nsew')
        self.names = AP.ChoiceList(right, on_pick=self._name_picked, on_cancel=self._name_cancel)
        self.names.grid(row=0, column=0, sticky='nsew')
        self.picker.tkraise()

        self.bar = tk.Label(root, text='', font=m['font'], bg=pal['bar'], fg=pal['bar_fg'], anchor='w', padx=4)
        self.bar.grid(row=2, column=0, columnspan=2, sticky='we', pady=(2, 0))

        cv.bind('<Configure>', lambda _e: self.draw())
        cv.bind('<Button-1>', self._click)
        cv.bind('<Double-Button-1>', self._double)
        for seq, d in (('<Up>', -1), ('<Down>', 1), ('<Prior>', -10), ('<Next>', 10), ('<Home>', -9999),
                       ('<End>', 9999)):
            cv.bind(seq, lambda _e, d=d: self.move(d))
        cv.bind('<Return>', lambda _e: self.open_picker())
        cv.bind('<KP_Enter>', lambda _e: self.open_picker())
        cv.bind('<Delete>', lambda _e: self.delete_selected())
        cv.bind('<F2>', lambda _e: self.edit_cell('value'))
        cv.bind('<Right>', lambda _e: self._walk_cells(1))
        cv.bind('<Left>', lambda _e: self._walk_cells(-1))
        cv.bind('<Control-s>', self.save)
        cv.bind('<Key>', self._key)
        cv.bind('<MouseWheel>', lambda e: self._wheel(-1 if e.delta > 0 else 1))
        cv.bind('<Button-4>', lambda _e: self._wheel(-1))
        cv.bind('<Button-5>', lambda _e: self._wheel(1))
        cv.bind('<FocusIn>', lambda _e: self.draw())
        cv.bind('<FocusOut>', lambda _e: self.draw())
        ed = self.ed
        ed.bind('<Return>', lambda _e: self._ed_done('save'))
        ed.bind('<KP_Enter>', lambda _e: self._ed_done('save'))
        ed.bind('<Tab>', lambda _e: self._ed_done('next'))
        ed.bind('<Up>', lambda _e: self._ed_done('up'))
        ed.bind('<Down>', lambda _e: self._ed_done('down'))
        ed.bind('<Escape>', lambda _e: self._ed_done('cancel'))
        ed.bind('<FocusOut>', self._ed_focus_out)
        ed.bind('<Control-s>', lambda _e: self._ed_done('save'))

        self.load_rows()
        self.select(self._first_slot())
        self._say(he('hint', 'Enter: pick attribute   Del: clear slot   0-9: edit value   letters: find'))
        top.protocol('WM_DELETE_WINDOW', self.close)
        try:
            cv.focus_set()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.top.destroy()
        except tk.TclError:
            pass

    def _name(self):
        try:
            return self.app.full_name(self.it)
        except Exception:
            return self.it.get('name') or self.it.get('code') or 'item'

    def _creator(self):
        if self.cr is None:
            import mxl_creator as m
            self.cr = m.Creator(self.app.data)
        return self.cr

    # ------------------------------------------------------------ rows
    def load_rows(self):
        """Reads the item's stats: from the stash file itself (exactly what is on disk) for a stash item, from
        the character's entry for one of its items. Typed values not written yet are dropped."""
        self._close_editor()
        if self.entry is not None:
            blob = self.entry.blob
        else:
            buf = open(self.app.path, 'rb').read()
            blob = mxl_save.item_blob(buf, self.it)
        self.rec, self.kids = decode_blob(blob, self.app.data)
        self.pending = {}
        self._build_rows()

    def _build_rows(self):
        """The display rows from self.rec: [runeword header + slots +] the item's slots + empty slots."""
        data = self.app.data
        rows, lists = [], []
        sections = []
        if self.rec.get('stats_runeword'):
            sections.append(('stats_runeword', he('rw_stats', "The runeword's stats")))
            sections.append(('stats', he('own_stats', "The item's stats")))
        else:
            sections.append(('stats', None))
        for stat_list, title in sections:
            entries = list(self.rec.get(stat_list) or [])
            lists.append((stat_list, entries))
            if title:
                rows.append(dict(kind='head', text=title))
            for i, s in enumerate(entries):
                rows.append(self._slot_row(data, stat_list, i, s))
            if stat_list == 'stats':
                spare = max(SLOTS_SPARE, SLOTS_MIN - len(entries))
            else:
                spare = 2
            for k in range(spare):
                rows.append(dict(kind='slot', list=stat_list, i=None, n=len(entries) + k + 1, s=None))
        self.rows, self.lists = rows, lists
        try:
            self.name_lab.configure(text=self._name())
        except tk.TclError:
            pass
        if self.sel is not None and self.sel >= len(rows):
            self.sel = len(rows) - 1
        self.draw()

    def _slot_row(self, data, stat_list, i, s):
        sid = s['id']
        kind = param_kind(sid)
        row = dict(kind='slot', list=stat_list, i=i, n=i + 1, s=s, label=_row_label(data, s), pk=kind,
                   name='', level='', raw=False)
        if kind:
            parts = decode_param(data, sid, s.get('param'))
            if parts:
                row['name'] = str(parts[0])
                if kind == 'skill':
                    row['level'] = str(parts[1] if parts[1] is not None else 0)
        elif param_bits(data, sid):
            row['raw'] = True
            row['name'] = str(s.get('param') or 0)
        return row

    def _first_slot(self):
        return next((n for n, r in enumerate(self.rows) if r['kind'] == 'slot'), None)

    def _find_slot(self, stat_list, i):
        """Row index of slot i of a list (i None: its first empty slot)."""
        return next((n for n, r in enumerate(self.rows)
                     if r['kind'] == 'slot' and r['list'] == stat_list and r['i'] == i), None)

    def _row(self, n=None):
        n = self.sel if n is None else n
        if n is None or not 0 <= n < len(self.rows):
            return None
        return self.rows[n]

    # ------------------------------------------------------------ drawing
    def _cols(self):
        """Column edges in pixels, from the list's width and the font: x (clear the slot) | number | text |
        value | level | name. The x column is the first one and has a fixed width: every x lines up."""
        ch = self.m['ch']
        w = max(self.cv.winfo_width(), ch * 30)
        x_del = int(ch * 2.2)
        x_num = x_del + int(ch * 3.2)
        w_val, w_lvl = ch * 7, int(ch * 4.5)
        w_name = int(max(ch * 11, min(ch * 24, w * 0.24)))
        x_name = w - w_name
        x_lvl = x_name - w_lvl
        x_val = x_lvl - w_val
        return dict(w=w, dele=x_del, num=x_num, text=x_num + ch, val=x_val, lvl=x_lvl, name=x_name)

    def _elide(self, text, width, font=None):
        font = font or self.m['font']
        key = (text, width, str(font))
        out = self._fit.get(key)
        if out is None:
            out = text
            if font.measure(text) > width:
                lo, hi = 0, len(text)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if font.measure(text[:mid] + '..') <= width:
                        lo = mid
                    else:
                        hi = mid - 1
                out = text[:lo].rstrip() + '..'
            if len(self._fit) > 4000:
                self._fit.clear()
            self._fit[key] = out
        return out

    def draw(self):
        cv, pal, m = self.cv, self.pal, self.m
        try:
            cv.delete('row')
        except tk.TclError:
            return
        c = self._cols()
        rh, ch, f, fb = m['row'], m['ch'], m['font'], m['bold']
        focused = False
        try:
            focused = cv.focus_get() in (cv, self.ed)
        except (KeyError, tk.TclError):
            pass
        hd = self.hdr
        hd.delete('all')
        ty = rh // 2
        hd.create_text(c['num'], ty, text='#', anchor='e', font=fb, fill=pal['fg'])
        hd.create_text(c['text'], ty, text=he('col.attr', 'Attribute'), anchor='w', font=fb, fill=pal['fg'])
        hd.create_text(c['lvl'] - 3, ty, text=he('col.value', 'Value'), anchor='e', font=fb, fill=pal['fg'])
        hd.create_text(c['name'] - 3, ty, text=he('col.level', 'Lvl'), anchor='e', font=fb, fill=pal['fg'])
        hd.create_text(c['name'] + 3, ty, text=he('col.param', 'Skill / param'), anchor='w', font=fb,
                       fill=pal['fg'])
        text_w = c['val'] - c['text'] - ch
        for n, r in enumerate(self.rows):
            y = n * rh
            ym = y + rh // 2
            if r['kind'] == 'head':
                cv.create_rectangle(0, y, c['w'], y + rh, fill=pal['head'], outline='', tags='row')
                cv.create_text(ch, ym, text=r['text'], anchor='w', font=fb, fill=pal['fg_hi'], tags='row')
                continue
            sel = n == self.sel
            if sel:
                cv.create_rectangle(0, y, c['w'], y + rh, fill=pal['sel'] if focused else pal['sel_dim'],
                                    outline=pal['line'], tags='row')
            elif n % 2:
                cv.create_rectangle(0, y, c['w'], y + rh, fill=pal['alt'], outline='', tags='row')
            fg = (pal['sel_fg'] if focused else pal['fg_hi']) if sel else pal['fg']
            dim = fg if sel else pal['dim']
            cv.create_text(c['num'], ym, text=str(r['n']), anchor='e', font=f, fill=dim, tags='row')
            if r['s'] is None:
                cv.create_text(c['text'], ym, text=he('empty', '(empty)'), anchor='w', font=f, fill=dim,
                               tags='row')
                continue
            cv.create_text(c['dele'] // 2 + 1, ym - 1, text='x', anchor='center', font=fb,
                           fill=fg if sel else pal['changed'], tags='row')
            cv.create_text(c['text'], ym, text=self._elide(r['label'], text_w), anchor='w', font=f, fill=fg,
                           tags='row')
            key = (r['list'], r['i'])
            if key in self.pending:
                cv.create_text(c['lvl'] - 3, ym, text=f'{self.pending[key]} *', anchor='e', font=fb,
                               fill=fg if sel and focused else pal['changed'], tags='row')
            else:
                cv.create_text(c['lvl'] - 3, ym, text=str(r['s']['value']), anchor='e', font=f, fill=fg,
                               tags='row')
            if r['level'] != '':
                cv.create_text(c['name'] - 3, ym, text=r['level'], anchor='e', font=f, fill=fg, tags='row')
            if r['name'] != '':
                cv.create_text(c['name'] + 3, ym, text=self._elide(r['name'], c['w'] - c['name'] - 6),
                               anchor='w', font=f, fill=fg, tags='row')
        for x in (c['dele'], c['val'], c['lvl'], c['name']):
            cv.create_line(x, 0, x, len(self.rows) * rh, fill=pal['alt'] if pal['dark'] else '#dcdcdc',
                           tags='row')
        cv.tag_lower('row')
        cv.configure(scrollregion=(0, 0, c['w'], len(self.rows) * rh))

    def _cell_box(self, n, field):
        c = self._cols()
        rh = self.m['row']
        x0, x1 = {'value': (c['val'], c['lvl']), 'level': (c['lvl'], c['name']),
                  'param': (c['name'], c['w'])}[field]
        return x0 + 1, n * rh, x1 - x0 - 1, rh

    def _fields(self, r):
        """The cells of a row that can be activated, left to right: value, level, name (picker) / param."""
        if r is None or r['kind'] != 'slot' or r['s'] is None:
            return []
        out = ['value']
        if r['pk'] == 'skill':
            out.append('level')
        if r['pk']:
            out.append('name')
        elif r['raw']:
            out.append('param')
        return out

    # ------------------------------------------------------------ selection / keys
    def select(self, n, see=True):
        if n is None or not 0 <= n < len(self.rows) or self.rows[n]['kind'] != 'slot':
            return
        self.sel = n
        self.draw()
        if see:
            self._see(n)
        r = self.rows[n]
        if r['s'] is not None:
            self._say(_row_info_text(self.app.data, r['s']))
        else:
            self._say(he('empty_hint', 'empty slot: Enter (or a double-click on a stat) puts an attribute here'))
        if self._pick_mode is not None and self._pick_mode != n:
            self._name_cancel(focus=False)

    def _see(self, n):
        rh = self.m['row']
        total = max(1, len(self.rows) * rh)
        if self.cv.winfo_height() <= 1:           # not laid out yet
            return
        h = max(rh, self.cv.winfo_height() - 2)
        top = self.cv.canvasy(0)
        if n > 0 and self.rows[n - 1]['kind'] == 'head':
            n -= 1                                # keep the section's title in view with its first slot
            if (n + 2) * rh > top + h:
                n += 1
        if n * rh < top:
            self.cv.yview_moveto(n * rh / total)
        elif (n + 1) * rh > top + h:
            self.cv.yview_moveto(max(0, (n + 1) * rh - h + rh - 1) // rh * rh / total)

    def move(self, d):
        if not self.rows:
            return 'break'
        n = self.sel if self.sel is not None else 0
        step = 1 if d > 0 else -1
        target = max(0, min(len(self.rows) - 1, n + d))
        while 0 <= target < len(self.rows) and self.rows[target]['kind'] != 'slot':
            target += step
        if not 0 <= target < len(self.rows):
            target = n
            for k in (range(len(self.rows) - 1, -1, -1) if d > 0 else range(len(self.rows))):
                if self.rows[k]['kind'] == 'slot':
                    target = k
                    break
        self.select(target)
        return 'break'

    def _wheel(self, d):
        self.cv.yview_scroll(d * 3, 'units')
        return 'break'

    def _row_at(self, ev):
        n = int(self.cv.canvasy(ev.y) // self.m['row'])
        return n if 0 <= n < len(self.rows) else None

    def _click(self, ev):
        self._ed_done('keep')
        self.cv.focus_set()
        n = self._row_at(ev)
        if n is None or self.rows[n]['kind'] != 'slot':
            return 'break'
        self.select(n, see=False)
        r = self.rows[n]
        c = self._cols()
        x = ev.x
        fields = self._fields(r)
        if x < c['dele']:                      # the row's x: clear the slot (same as Delete)
            if r['s'] is not None:
                self.delete_row(r['list'], r['i'])
        elif x >= c['name']:
            if 'name' in fields:
                self.open_names()
            elif 'param' in fields:
                self.edit_cell('param')
        elif x >= c['lvl']:
            if 'level' in fields:
                self.edit_cell('level')
        elif x >= c['val'] and fields:
            self.edit_cell('value')
        return 'break'

    def _double(self, ev):
        n = self._row_at(ev)
        if n is None or self.rows[n]['kind'] != 'slot':
            return 'break'
        c = self._cols()
        if c['dele'] <= ev.x < c['val'] or (self.rows[n]['s'] is None and ev.x >= c['dele']):
            self.open_picker()
        return 'break'

    def _key(self, ev):
        ch = ev.char
        if not ch or (ev.state & 0x4) or not ch.isprintable():
            return None
        r = self._row()
        if ch.isdigit() or ch == '-':
            if r is not None and r['kind'] == 'slot' and r['s'] is not None:
                self.edit_cell('value', start=ch)
            return 'break'
        if ch.isalpha() or ch == '#':
            self.open_picker(text=ch)
            return 'break'
        return None

    def _walk_cells(self, d):
        fields = self._fields(self._row())
        if not fields:
            return 'break'
        f = fields[0] if d > 0 else fields[-1]
        if f == 'name':
            self.open_names()
        else:
            self.edit_cell(f)
        return 'break'

    def focus_list(self):
        try:
            self.cv.focus_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ inline editing
    def edit_cell(self, field, start=None):
        """Opens the number box over a cell of the selected row ('value', 'level' or 'param')."""
        r = self._row()
        if r is None or field not in self._fields(r):
            return 'break'
        self._close_editor()
        n = self.sel
        self._see(n)
        key = (r['list'], r['i'])
        cur = {'value': str(self.pending.get(key, r['s']['value'])), 'level': r['level'],
               'param': r['name']}[field]
        x, y, w, h = self._cell_box(n, field)
        self.ed_var.set(cur if start is None else start)
        self.cv.create_window(x, y, window=self.ed, anchor='nw', width=w, height=h, tags='ed')
        self._ed = (n, field)
        self.ed.focus_set()
        if start is None:
            self.ed.selection_range(0, 'end')
        else:
            self.ed.selection_clear()
        self.ed.icursor('end')
        return 'break'

    def _close_editor(self):
        self._ed = None
        try:
            self.cv.delete('ed')
        except (tk.TclError, AttributeError):
            pass

    def _ed_focus_out(self, _e=None):
        try:
            if self.cv.focus_get() is self.ed:        # a late event of the box's previous use
                return None
        except (KeyError, tk.TclError):
            pass
        return self._ed_done('keep')

    def _ed_done(self, how):
        """Leaves the number box. how: 'save' (Enter: keep the value and write), 'next' (Tab: the row's next
        cell), 'up' / 'down' (keep and move), 'keep' (focus left), 'cancel' (Escape)."""
        if self._ed is None or self._busy:
            return 'break'
        n, field = self._ed
        text = self.ed_var.get().strip()
        self._close_editor()
        r = self._row(n)
        if how not in ('keep', 'next'):
            self.focus_list()
        if r is None or r['s'] is None or how == 'cancel':
            self.draw()
            return 'break'
        try:
            v = int(text)
        except ValueError:
            if text:
                self._say(he('err.number', 'not a number: {text}', text=text), error=True)
            self.draw()
            return 'break'
        ok = True
        if field == 'value':
            key = (r['list'], r['i'])
            if v != r['s']['value']:
                self.pending[key] = v
            else:
                self.pending.pop(key, None)
            self.draw()
            if how == 'save':
                self.save()
        elif field == 'level':
            ok = self._set_param(n, level=v)
        else:
            ok = self._set_param(n, raw=v)
        if how == 'next':
            fields = self._fields(self._row(n))
            if ok and field in fields and fields.index(field) + 1 < len(fields):
                nxt = fields[fields.index(field) + 1]
                self.sel = n
                self.open_names() if nxt == 'name' else self.edit_cell(nxt)
            else:
                self.focus_list()
        elif how in ('up', 'down'):
            self.move(-1 if how == 'up' else 1)
        return 'break'

    # ------------------------------------------------------------ the right pane
    def open_picker(self, text=None):
        """The attribute picker for the selected slot: a used slot shows its own stat in its category, an
        empty one the category used last. A pick replaces the slot's stat / fills the empty slot."""
        r = self._row()
        if r is None or r['kind'] != 'slot':
            return 'break'
        self._ed_done('keep')
        self._name_cancel(focus=False)
        if r['s'] is not None:
            title = he('pick_replace', 'Slot {n}: replace attribute', n=r['n'])
            if text is None:
                self.picker.select_stat(r['s']['id'])
        else:
            title = he('pick_add', 'Slot {n}: add attribute', n=r['n'])
        self.picker.title.configure(text=title)
        self.picker.tkraise()
        self.picker.focus_filter(text)
        return 'break'

    def picked(self, sid):
        """A stat was picked: it replaces the selected slot's stat (the value is kept when the new stat can
        store it) or fills the selected empty slot; then the skill list / the value box opens for it."""
        r = self._row()
        if r is None or r['kind'] != 'slot':
            self._say(he('err.row', 'Select a slot first: the picked attribute goes there.'), error=True)
            return
        data = self.app.data
        info = _stat_info(data, sid)
        if info is None or not info['bits']:
            self._say(he('err.no_bits', 'stat #{sid}: the save format has no storage for it', sid=sid), error=True)
            return
        if r['s'] is not None and r['s']['id'] == sid:
            self.focus_list()
            return
        if not self._flush_pending():
            return
        r = self._row()
        stat_list = r['list']
        entries = list(self.rec.get(stat_list) or [])
        kind = param_kind(sid)
        param = None
        if kind in ('skill', 'skill_only'):
            names = skill_names_sorted(data, sid)
            if names:
                param, _why = encode_skill_param(data, sid, names[0][0], 1)
        elif kind in ('class', 'named'):
            param = 0
        lo, hi = value_range(data, sid)
        if r['s'] is not None:
            i = r['i']
            val = max(lo, min(hi, int(r['s']['value'])))
            entries[i] = dict(id=sid, param=param, value=val)
            msg = he('replaced', 'slot {n}: now {label}', n=i + 1, label=self.picker.label(sid))
        else:
            i = len(entries)
            entries.append(dict(id=sid, param=param, value=max(lo, min(hi, 0))))
            msg = he('added', '{label} added', label=self.picker.label(sid))
        self.rec[stat_list] = entries
        ok = self._write()
        if ok:
            self.refresh_after_write()
        self.load_rows()
        self.focus_list()
        if not ok:
            return
        n = self._find_slot(stat_list, i)
        at = self._row(n) if n is not None else None
        if at is None or at['s'] is None or at['s']['id'] != sid:
            # the encoder keeps a stat list in the game's own order (by stat id): find the stat again
            hits = [k for k, x in enumerate(self.rows) if x['kind'] == 'slot' and x['list'] == stat_list
                    and x['s'] is not None and x['s']['id'] == sid]
            n = next((k for k in hits if (self.rows[k]['s'].get('param') or None) == (param or None)),
                     hits[0] if hits else n)
        self.select(n)
        self._say(msg)
        row = self._row()
        if row is not None and row['s'] is not None and row['s']['id'] == sid:
            if kind:
                self.open_names()
            else:
                self.edit_cell('value')

    def open_names(self):
        """The right pane lists the skills (classes) the selected row's stat can carry; a pick rewrites it."""
        r = self._row()
        if r is None or 'name' not in self._fields(r):
            return 'break'
        self._ed_done('keep')
        sid = r['s']['id']
        if r['pk'] == 'class':
            from mxl_rules import CLASSES
            names = list(CLASSES)
            title = he('pick_class', 'Slot {n}: class', n=r['n'])
        elif r['pk'] == 'named':                # state, monster, orb, element / attribute...: by name
            names = [nm for nm, _v in param_choices(self.app.data, sid)]
            title = he('pick_named', 'Slot {n}: {what}', n=r['n'], what=param_title(sid).lower())
        else:
            names = [nm for nm, _k in param_choices(self.app.data, sid)]
            title = he('pick_skill', 'Slot {n}: skill', n=r['n'])
        self.names.numbers = True               # a typed number is taken as the raw value ('#505')
        self._pick_mode = self.sel
        self.names.set(names, current=r['name'], title=title)
        self.names.tkraise()
        self.names.focus_filter()
        return 'break'

    def _name_cancel(self, focus=True):
        was = self._pick_mode is not None
        self._pick_mode = None
        try:
            self.picker.tkraise()
        except tk.TclError:
            return
        if focus and was:
            self.focus_list()

    def _name_picked(self, name):
        n = self._pick_mode
        self._name_cancel(focus=False)
        self.focus_list()
        if n is None:
            return
        if self._set_param(n, name=name):
            r = self._row(n)
            if r is not None and r['s'] is not None:
                self.sel = n
                self.edit_cell('value')

    def _set_param(self, n, name=None, level=None, raw=None):
        """Changes the param of row n (skill / class name, cast level, or the raw number) and rewrites the
        item at once. False: refused (the status bar says why), nothing written."""
        r = self._row(n)
        if r is None or r['s'] is None:
            return False
        data = self.app.data
        s = r['s']
        sid = s['id']
        if raw is not None:
            bits = min(param_bits(data, sid), 32)
            if not 0 <= raw < (1 << bits):
                self._say(he('err.param_range', 'param out of range (0..{m})', m=(1 << bits) - 1), error=True)
                return False
            newp = raw or None
        else:
            nm = name if name is not None else r['name']
            lv = level if level is not None else (int(r['level']) if r['level'] != '' else 1)
            newp, why = encode_skill_param(data, sid, nm, lv)
            if newp is None:
                txt = {'rolled': he('err.rolled', '{name}: its id does not fit this stat (the game would '
                                                  'show another skill)', name=nm),
                       'level': he('err.level', 'cast level must be 0..63')}.get(why)
                self._say(txt or he('err.param', 'unknown {what}: {name}', name=nm,
                                    what=param_title(sid).lower()), error=True)
                return False
        if (newp or None) == (s.get('param') or None):
            return True
        if not self._flush_pending():
            return False
        r = self._row(n)
        entries = list(self.rec.get(r['list']) or [])
        entries[r['i']] = dict(entries[r['i']], param=newp)
        self.rec[r['list']] = entries
        ok = self._write()
        if ok:
            self.refresh_after_write()
        self.load_rows()
        if ok:
            self.select(n)
            self._say(self._row(n)['label'] if self._row(n) and self._row(n)['s'] else '')
        return ok

    def delete_selected(self, *_e):
        r = self._row()
        if r is None or r['kind'] != 'slot' or r['s'] is None:
            return 'break'
        self.delete_row(r['list'], r['i'])
        return 'break'

    def delete_row(self, stat_list, row):
        if not self._flush_pending():
            return
        entries = list(self.rec.get(stat_list) or [])
        try:
            gone = entries[row]
        except IndexError:
            return
        label = _row_label(self.app.data, gone)
        del entries[row]
        self.rec[stat_list] = entries
        keep = self.sel
        if self._write():
            self.refresh_after_write()
            self.load_rows()
            self.select(keep if keep is not None and keep < len(self.rows) else self._first_slot())
            self._say(he('deleted', 'slot cleared: {label} (stat #{sid})', sid=gone['id'], label=label))
        else:
            self.load_rows()
        self.focus_list()

    def _flush_pending(self):
        """Typed values not written yet are written first (their own in-place path), so a following rewrite of
        the item cannot lose them. False: the write was refused - the caller stops."""
        if not self.pending:
            return True
        return self.save() is not False

    # ------------------------------------------------------------ writes
    def save(self, *args):
        """Changed values of kept rows. A stash item: in place through apply_edits (one write). A character
        item: one re-encode of the item's bytes + the character's own save. Added / cleared slots were written
        already at their own change. A value the save format cannot hold is capped to the nearest it can
        (shown in the status bar); the write itself still refuses what the game's own stat logic will not
        allow. Returns False when a write was refused."""
        if self._ed is not None and self._ed[1] == 'value':
            self._busy = True                 # take the open box's number along
            try:
                n, _f = self._ed
                r = self._row(n)
                try:
                    v = int(self.ed_var.get().strip())
                    if r is not None and r['s'] is not None and v != r['s']['value']:
                        self.pending[(r['list'], r['i'])] = v
                except ValueError:
                    pass
                self._close_editor()
            finally:
                self._busy = False
        cap_note = ''
        keep = self.sel
        typed = []                            # [(stat_list, index, row dict) per changed row]
        for stat_list, entries in self.lists:
            for i, s in enumerate(entries):
                if (stat_list, i) not in self.pending:
                    continue
                v = self.pending[(stat_list, i)]
                if v == s['value']:
                    continue
                rng = value_range(self.app.data, s['id'])
                if rng is None:
                    continue                  # the save format has no storage for this stat's value
                lo, hi = rng
                if not lo <= v <= hi:
                    v = max(lo, min(hi, v))
                    cap_note = he('capped', 'a value outside what the save format stores was capped '
                                            '(stat #{n} to {m})', n=s['id'], m=v)
                    self.pending[(stat_list, i)] = v
                typed.append((stat_list, i, dict(id=s['id'], param=s.get('param'), value=v)))
        if not typed:
            self.pending = {}
            self.draw()
            self._say(cap_note or he('nothing', 'nothing to write'))
            return None
        if self.entry is None:                # stash item: apply the value edits in place
            edits = [dict(offset=self.it['_offset'], code=self.it['code'], kind='stat', stat_list=stat_list,
                          stat=row['id'], param=row.get('param'), value=row['value'])
                     for stat_list, _i, row in typed]
            try:
                bak = apply_edits(self.app.path, edits, self.app.data,
                                  backup=self.app.needs_backup(self.app.path), force=True)
            except Exception as e:            # EditError / FormatError / StoreError / OSError
                self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
                return False
            self.refresh_after_write()
            self.load_rows()
            self.select(keep)
            self._say(he('saved', 'written{bak}', bak=(f' - backup {os.path.basename(bak)}' if bak else ''))
                      + ((' - ' + cap_note) if cap_note else ''))
            return True
        # character item: write the typed values into the record, then re-encode the item's bytes once
        for stat_list, i, row in typed:
            entries = list(self.rec.get(stat_list) or [])
            entries[i] = dict(entries[i], value=row['value'])
            self.rec[stat_list] = entries
        if self._write_char():
            self.refresh_after_write()
            self.load_rows()
            self.select(keep)
            self._say(he('saved', 'written{bak}', bak='') + ((' - ' + cap_note) if cap_note else ''))
            return True
        self.load_rows()
        return False

    def _write(self):
        """Stash item: re-encodes its bytes (a slot was added, replaced or cleared) and replaces it at its own
        place through edit_stash (verification, backup; socketed items follow). False: refused, nothing
        written."""
        if self.entry is not None:
            return self._write_char()
        page, x, y = self.it.get('page', 0), self.it.get('x', 0), self.it.get('y', 0)
        try:
            blb = build_blob(self.rec, self.kids, self.app.data)
            bak = edit_stash(self.app.path, self.app.data, remove=[self.it['_offset']],
                             insert=[(page, x, y, blb)], backup=self.app.needs_backup(self.app.path))
            self._bak = bak
        except (EditError, FormatError, OSError) as e:
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        except Exception as e:                # e.g. StoreError: the value does not fit the save bits
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        return True

    def _write_char(self):
        """Character item: re-encodes the item's bytes in the character's entry and saves the character
        through the character window (its own verification, backup and status line)."""
        try:
            self.entry.blob = build_blob(self.rec, self.kids, self.app.data)
            import mxl_char as MC
            self.entry.it = MC.blob_item(self.entry.blob, self.app.data)
        except (FormatError, OSError, ValueError) as e:
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        except Exception as e:                # e.g. StoreError: the value does not fit the save bits
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        if self.chwin.save(T('ch.replaced', '{item} replaced', item=self._name())) is False:
            self._say(he('err.save', 'not written: {err}', err=he('err.char', 'the character window shows the '
                                                                             'error')), error=True)
            return False
        return True

    def refresh_after_write(self):
        """Stash item: offsets shift as soon as an item changed size - reload from disk and point self.it at
        the item again (sender for the next edit), refresh the main window's grid. Character item: take the
        fresh entry (a save rebuilds the character's item list) and keep it selected."""
        if self.entry is not None:
            self.entry = self._refind_entry() or self.entry
            self.chwin.selected = self.entry
            try:
                self.chwin.redraw()
            except Exception:
                pass
            return
        try:
            self.app.load(self.app.path, keep_selection=False)
            page, x, y = self.it.get('page', 0), self.it.get('x', 0), self.it.get('y', 0)
            new = next((i for i in self.app.items or []
                        if (i.get('page'), i.get('x'), i.get('y')) == (page, x, y)), None)
            if new is not None:
                self.it = dict(new)
                self.app.selected = new
                try:
                    self.app.draw_grid()
                    self.app.set_detail(new)
                except Exception:
                    pass
        except Exception:
            pass

    def _refind_entry(self):
        """The character window's entry standing where the edited one stood (a save rebuilt the entries)."""
        ch = self.chwin.ch
        try:
            same = (self.it.get('location'), self.it.get('x'), self.it.get('y'), self.it.get('equipped'),
                    self.it.get('code'))
            for e in list(ch.items) + ([] if ch.merc_items is None else list(ch.merc_items)):
                t = e.it
                if (t.get('location'), t.get('x'), t.get('y'), t.get('equipped'), t.get('code')) == same:
                    self.it = dict(t)
                    return e
        except Exception:
            pass
        return None

    def _say(self, txt, error=False):
        try:
            self.bar.configure(text=txt, fg=self.pal['error'] if error else self.pal['bar_fg'])
        except tk.TclError:
            pass


def open_item_stats(app):
    """The Magic Attributes tab for the item selected in the stash grid of the main window."""
    it = app.selected
    if it is None or not app.path:
        from tkinter import messagebox
        messagebox.showinfo(he('title', 'Item stats'), T('cr.select_first', 'Select an item of the stash first.'))
        return None
    return ItemStatsWindow(app, it=it)


def open_char_item_stats(chwin, entry):
    """The Magic Attributes tab for an item of the character window (equipment, mercenary or inventory)."""
    if entry is None:
        return None
    chwin.selected = entry
    return ItemStatsWindow(chwin.app, chwin=chwin, entry=entry)
