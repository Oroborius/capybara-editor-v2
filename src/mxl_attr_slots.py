"""Hero Editor v1.04-style attribute slot list: the widget shared by the "Item stats" tab (mxl_he_stats) and
the Item Creator / Editor (mxl_creator_gui).

A numbered list of slots on a canvas, columns  x | # | Attribute | Value | Lvl | Skill / param : the used slots
in the order the owner gives them, then "(empty)" slots. The widget only draws, selects and edits in place; what
a change MEANS is the owner's business. The owner hands over display rows (see slot_row / section_rows) with
set_rows() and gets these calls (all optional, see _Owner for the defaults):

    slot_selected(n)                  a slot was selected (status text, closing a name list...)
    slot_pick(n, text)                the attribute chooser is wanted for slot n (text: a typed first letter)
    slot_names(n)                     the skill / class / named-param list is wanted for slot n
    slot_value(n, v, how)             a number was typed into the value cell (how: 'save' = Enter, 'next' = Tab,
                                      'up' / 'down', 'keep' = the focus left)
    slot_param(n, level=, raw=)       a cast level / a raw param number was typed; False = refused
    slot_delete(n)                    the x of the row was clicked / Delete was pressed on a used slot
    slot_save()                       Ctrl+S
    slot_pending(row)                 a typed value not written yet (drawn 'N *'), or None
    slot_say(text, error=False)       a message for the owner's status line

Keys: Up / Down / PgUp / PgDn / Home / End move; Enter opens the chooser; Delete clears; a digit (or F2) edits the
value in place; Right / Left walk the row's cells; a letter starts the chooser's search. Mouse: the x clears, the
value / level / param cells edit, the name cell lists the names; the chooser opens on a double-click of the
attribute (click_opens=False, the Item stats tab) or on a single click (click_opens=True, the creator: click the
next empty slot and the chooser opens).
"""
import tkinter as tk
import tkinter.ttk as ttk

from mxl_rules import stat_hidden
from mxl_lang import T
from mxl_statnames import stat_text, param_kind, decode_param, param_bits, param_title, param_spec, param_name
import mxl_attr_picker as AP

SLOTS_MIN = 30          # Hero Editor showed 30 magic attribute slots
SLOTS_SPARE = 4         # empty slots always left after the used ones


def he(key, default, **fields):
    """The list's strings: keys 'he.stats.*' (they were the Item stats tab's own)."""
    return T('he.stats.' + key, default, **fields)


def stat_info(data, sid):
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
    info = stat_info(data, sid)
    if info is None or not info['bits']:
        return None
    return -info['add'], (1 << info['bits']) - 1 - info['add']


def row_label(data, s):
    """Label of one stored stat entry: the game text when the game shows that stat itself, the editor's own
    name or '(stat #N)' for the internal ones (and for the mod's 'FLYING POLAR BUFFALO' placeholder strings).
    Clean Hero-Editor labels: no stat ids, bit counts or param numbers (the status bar shows those)."""
    sid, param = s['id'], s.get('param')
    c = stat_info(data, sid)
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


def row_info_text(data, s):
    """The technical line for the status bar when a slot is selected: stat id, param, save bits, value range."""
    sid, param = s['id'], s.get('param')
    c = stat_info(data, sid)
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


def slot_row(data, stat_list, i, s, **more):
    """The display row of one used slot. s: dict(id, param, value). more: the owner's own fields."""
    sid = s['id']
    kind = param_kind(sid)
    row = dict(kind='slot', list=stat_list, i=i, n=i + 1, s=s, label=row_label(data, s), pk=kind,
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
    row.update(more)
    return row


def section_rows(data, stat_list, entries, title=None, spare=None):
    """The rows of one stat list: [its title] + a used slot per entry (in the order given) + empty slots
    (spare: how many; None = up to SLOTS_MIN slots in all, at least SLOTS_SPARE empty ones)."""
    rows = []
    if title:
        rows.append(dict(kind='head', text=title))
    for i, s in enumerate(entries):
        rows.append(s if s.get('kind') == 'slot' else slot_row(data, stat_list, i, s))
    if spare is None:
        spare = max(SLOTS_SPARE, SLOTS_MIN - len(entries))
    for k in range(spare):
        rows.append(dict(kind='slot', list=stat_list, i=None, n=len(entries) + k + 1, s=None))
    return rows


class Anchor:
    """A screen rectangle with the widget calls the picker popups place themselves by; around: the screen
    rectangle (x, y, w, h) of the list the popup must not cover (mxl_attr_picker.place)."""

    def __init__(self, x, y, h, w=1, around=None):
        self.x, self.y, self.h, self.w, self.around = x, y, h, w, around

    def winfo_width(self):
        return self.w

    def winfo_rootx(self):
        return self.x

    def winfo_rooty(self):
        return self.y

    def winfo_height(self):
        return self.h


class _Owner:
    def slot_selected(self, n): pass
    def slot_pick(self, n, text=None): pass
    def slot_names(self, n): pass
    def slot_value(self, n, v, how): pass
    def slot_param(self, n, level=None, raw=None): return False
    def slot_delete(self, n): pass
    def slot_save(self): pass
    def slot_pending(self, row): return None
    def slot_say(self, text, error=False): pass


class AttrSlots:
    """The slot list. parent: an empty frame the list fills (header, canvas, scrollbar). owner: see the module
    text. rows_shown / chars: the size the canvas asks for. wheel_pass: at the list's end the mouse wheel goes on
    to the page around it."""

    def __init__(self, parent, data, owner, click_opens=False, rows_shown=6, chars=40, wheel_pass=False):
        self.data = data
        self.owner = owner
        self.click_opens = click_opens
        self.wheel_pass = wheel_pass
        self.pal = pal = AP.palette()
        self.m = m = AP.metrics(parent)
        self.rows = []                        # display rows: dict(kind='head'|'slot', ...)
        self.sel = None                       # index into self.rows
        self._ed = None                       # (row index, field) of the open inline box
        self._busy = False
        self._fit = {}
        self.parent = parent
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.hdr = tk.Canvas(parent, height=m['row'], bg=pal['head'], highlightthickness=0, bd=0, width=10)
        self.hdr.grid(row=0, column=0, sticky='we')
        self.cv = cv = tk.Canvas(parent, bg=pal['field'], highlightthickness=1, highlightbackground=pal['line'],
                                 highlightcolor=pal['fg_hi'], bd=0, takefocus=1, yscrollincrement=m['row'],
                                 width=m['ch'] * chars, height=m['row'] * rows_shown)
        cv.grid(row=1, column=0, sticky='nsew')
        self.sb = sb = ttk.Scrollbar(parent, orient='vertical', command=cv.yview)
        sb.grid(row=1, column=1, sticky='ns')
        cv.configure(yscrollcommand=sb.set)
        self.ed_var = tk.StringVar()
        self.ed = ed = tk.Entry(cv, textvariable=self.ed_var, font=m['font'], bg=pal['field'], fg=pal['fg_hi'],
                                insertbackground=pal['fg_hi'], selectbackground=pal['sel'],
                                selectforeground=pal['sel_fg'], bd=0, relief='flat', highlightthickness=1,
                                highlightbackground=pal['fg_hi'], highlightcolor=pal['fg_hi'], justify='right')

        cv.bind('<Configure>', lambda _e: self.draw())
        cv.bind('<Button-1>', self._click)
        cv.bind('<Double-Button-1>', self._double)
        for seq, d in (('<Up>', -1), ('<Down>', 1), ('<Prior>', -10), ('<Next>', 10), ('<Home>', -9999),
                       ('<End>', 9999)):
            cv.bind(seq, lambda _e, d=d: self.move(d))
        cv.bind('<Return>', lambda _e: self.pick())
        cv.bind('<KP_Enter>', lambda _e: self.pick())
        cv.bind('<Delete>', lambda _e: self.delete_selected())
        cv.bind('<F2>', lambda _e: self.edit_cell('value'))
        cv.bind('<Right>', lambda _e: self._walk_cells(1))
        cv.bind('<Left>', lambda _e: self._walk_cells(-1))
        cv.bind('<Control-s>', lambda _e: self._call('slot_save'))
        cv.bind('<Key>', self._key)
        import mxl_scroll                 # whole notches under Tk 8.6 and 9, touchpad deltas added up
        mxl_scroll.bind_wheel(cv, lambda n, _e: self._wheel(n))
        cv.bind('<FocusIn>', lambda _e: self.draw())
        cv.bind('<FocusOut>', lambda _e: self.draw())
        ed.bind('<Return>', lambda _e: self._ed_done('save'))
        ed.bind('<KP_Enter>', lambda _e: self._ed_done('save'))
        ed.bind('<Tab>', lambda _e: self._ed_done('next'))
        ed.bind('<Up>', lambda _e: self._ed_done('up'))
        ed.bind('<Down>', lambda _e: self._ed_done('down'))
        ed.bind('<Escape>', lambda _e: self._ed_done('cancel'))
        ed.bind('<FocusOut>', self._ed_focus_out)
        ed.bind('<Control-s>', lambda _e: self._ed_done('save'))

    def _call(self, name, *a, **k):
        fn = getattr(self.owner, name, None)
        if fn is None:
            fn = getattr(_Owner, name).__get__(self.owner)
        return fn(*a, **k)

    def alive(self):
        try:
            return bool(self.cv.winfo_exists())
        except tk.TclError:
            return False

    # ------------------------------------------------------------ rows
    def set_rows(self, rows):
        """New display rows (the selection is kept by index, an open value box stays where it is)."""
        self.rows = rows
        if self.sel is not None and self.sel >= len(rows):
            self.sel = len(rows) - 1
        if self._ed is not None and self.row(self._ed[0]) is None:
            self._close_editor()
        self.draw()

    def first_slot(self):
        return next((n for n, r in enumerate(self.rows) if r['kind'] == 'slot'), None)

    def find_slot(self, stat_list, i):
        """Row index of slot i of a list (i None: its first empty slot)."""
        return next((n for n, r in enumerate(self.rows)
                     if r['kind'] == 'slot' and r['list'] == stat_list and r['i'] == i), None)

    def row(self, n=None):
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
        if w < ch * 52:                           # a narrow list (the creator at 800x600): the text keeps more
            w_val, w_lvl, w_name = ch * 6, ch * 4, ch * 9
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
            pend = self._call('slot_pending', r)
            if pend is not None:
                cv.create_text(c['lvl'] - 3, ym, text=f'{pend} *', anchor='e', font=fb,
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
                  'param': (c['name'], c['w']), 'name': (c['name'], c['w']),
                  'text': (c['num'], c['val'])}[field]
        return x0 + 1, n * rh, x1 - x0 - 1, rh

    def anchor(self, n=None, field='text'):
        """Where a popup for slot n belongs on the screen: the slot's cell, and the list around it (header +
        rows), which the popup keeps clear of where the screen has room."""
        n = self.sel if n is None else n
        x, y, w, h = self._cell_box(n or 0, field)
        try:
            cv, hd = self.cv, self.hdr
            top = min(cv.winfo_rooty(), hd.winfo_rooty()) if hd.winfo_ismapped() else cv.winfo_rooty()
            left, right, bot = cv.winfo_rootx(), cv.winfo_rootx() + cv.winfo_width(), cv.winfo_rooty() + cv.winfo_height()
            p = cv.master                                 # only the part shown (a scrolled pane cuts it) counts
            while p is not None:
                px, py = p.winfo_rootx(), p.winfo_rooty()
                left, right = max(left, px), min(right, px + p.winfo_width())
                top, bot = max(top, py), min(bot, py + p.winfo_height())
                if p is cv.winfo_toplevel():
                    break
                p = p.master
            around = (left, top, max(1, right - left), max(1, bot - top))
            return Anchor(cv.winfo_rootx() + x, cv.winfo_rooty() + int(y - cv.canvasy(0)), h, max(1, w), around)
        except tk.TclError:
            return None

    def fields(self, r):
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
            self.see(n)
        self._call('slot_selected', n)

    def see(self, n):
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
        if self.wheel_pass:
            top, bottom = self.cv.yview()
            if (d < 0 and top <= 0) or (d > 0 and bottom >= 1):
                return None                       # at the end: the page around the list scrolls on
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
        r = self.row(n)
        if r is None:
            return 'break'
        c = self._cols()
        x = ev.x
        fields = self.fields(r)
        if r['s'] is None:
            if self.click_opens and x >= c['dele']:       # the empty slot: the chooser fills it
                self.pick()
        elif x < c['dele']:                    # the row's x: clear the slot (same as Delete)
            self._call('slot_delete', n)
        elif x >= c['name']:
            if 'name' in fields:
                self._call('slot_names', n)
            elif 'param' in fields:
                self.edit_cell('param')
        elif x >= c['lvl']:
            if 'level' in fields:
                self.edit_cell('level')
        elif x >= c['val']:
            if fields:
                self.edit_cell('value')
        elif self.click_opens:                 # the attribute's name: the chooser replaces it
            self.pick()
        return 'break'

    def _double(self, ev):
        n = self._row_at(ev)
        if n is None or self.rows[n]['kind'] != 'slot' or self.click_opens:
            return 'break'
        c = self._cols()
        if c['dele'] <= ev.x < c['val'] or (self.rows[n]['s'] is None and ev.x >= c['dele']):
            self.pick()
        return 'break'

    def pick(self, text=None):
        if self.row() is not None and self.row()['kind'] == 'slot':
            self._call('slot_pick', self.sel, text)
        return 'break'

    def delete_selected(self):
        r = self.row()
        if r is not None and r['kind'] == 'slot' and r['s'] is not None:
            self._call('slot_delete', self.sel)
        return 'break'

    def _key(self, ev):
        ch = ev.char
        if not ch or (ev.state & 0x4) or not ch.isprintable():
            return None
        r = self.row()
        if ch.isdigit() or ch == '-':
            if r is not None and r['kind'] == 'slot' and r['s'] is not None:
                self.edit_cell('value', start=ch)
            return 'break'
        if ch.isalpha() or ch == '#':
            self.pick(text=ch)
            return 'break'
        return None

    def _walk_cells(self, d):
        fields = self.fields(self.row())
        if not fields:
            return 'break'
        f = fields[0] if d > 0 else fields[-1]
        if f == 'name':
            self._call('slot_names', self.sel)
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
        r = self.row()
        if r is None or field not in self.fields(r):
            return 'break'
        self._close_editor()
        n = self.sel
        self.see(n)
        pend = self._call('slot_pending', r)
        cur = {'value': str(pend if pend is not None else r['s']['value']), 'level': r['level'],
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

    def take_open_value(self):
        """Closes an open VALUE box without the usual callbacks and returns (row index, typed int) - None
        when no value box is open or its text is not a number (the box is closed all the same)."""
        if self._ed is None or self._ed[1] != 'value':
            return None
        self._busy = True
        try:
            n, _f = self._ed
            try:
                out = (n, int(self.ed_var.get().strip()))
            except ValueError:
                out = None
            self._close_editor()
        finally:
            self._busy = False
        return out

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
        r = self.row(n)
        if how not in ('keep', 'next'):
            self.focus_list()
        if r is None or r['s'] is None or how == 'cancel':
            self.draw()
            return 'break'
        try:
            v = int(text)
        except ValueError:
            if text:
                self._call('slot_say', he('err.number', 'not a number: {text}', text=text), error=True)
            self.draw()
            return 'break'
        ok = True
        if field == 'value':
            self._call('slot_value', n, v, how)
        elif field == 'level':
            ok = self._call('slot_param', n, level=v)
        else:
            ok = self._call('slot_param', n, raw=v)
        if not self.alive():
            return 'break'
        if how == 'next':
            now = self.row(n)                     # (the owner may have rebuilt the rows: still the same slot?)
            same = now is not None and now['s'] is not None and now['s']['id'] == r['s']['id']
            fields = self.fields(now) if same else []
            if ok and field in fields and fields.index(field) + 1 < len(fields):
                nxt = fields[fields.index(field) + 1]
                self.sel = n
                self._call('slot_names', n) if nxt == 'name' else self.edit_cell(nxt)
            else:
                self.focus_list()
        elif how in ('up', 'down'):
            self.move(-1 if how == 'up' else 1)
        return 'break'
