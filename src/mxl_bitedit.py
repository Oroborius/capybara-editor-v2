"""Bit editor main tab, modelled on UdieToo's binary editor: an item's bits, edited one by one.

Right-click an item -> "Open in Bit editor" (or the Library tab's "Inspect in Bit editor") shows the item's bits in
stream order: LSB first, continuous from one field to the next, so a field reads left to right as the save stores
it (the lowest bit first). The fields come from mxl_inspect.layout (mxlsave's own parser with every read logged);
each field has an alternating colour, each section (header, quality-specific fields, stats, runeword / set lists,
socketed items) a palette of its own. Rulers: the byte offset of each row on the left, byte / bit within the row on
top.

Keys on the grid: arrows move; Space toggles; 0 / 1 set (and move on); Insert switches insert / overwrite (thin /
wide cursor); Delete / BackSpace remove bits (insert mode only). The status line shows the position (byte.bit), the
field and its value with its meaning (flag names, quality, codes, stat / skill names...); clicking the value asks
a new one (decimal, 0x hex, 0b bits or a name) and writes the field's bits.

Every change is decoded again (mxlsave + the editor's own reader): bits that do not parse turn the state red and
the last valid decode stays shown. Apply writes the item back in place through the editor's writer (edit_stash:
verified write, backup, mxlsave check of the file), refused when the bits do not parse or the item on disk is no
longer the one opened (another write since); it is undoable (Ctrl+Z). Items of the character / library open read
only (Apply is for stash items).
"""
import tkinter as tk
from tkinter import ttk

from mxl_lang import T

COLS = 64                     # bits per row (8 bytes)
TAB_KEY = 'Bit editor'

HEADER = {'JM', 'flags', 'version', 'location', 'equipped', 'x', 'y', 'panel', 'code[0]', 'code[1]', 'code[2]',
          'code[3]', 'socketed count', 'item id', 'item level', 'quality', 'has picture', 'picture',
          'has auto affix', 'auto affix'}

PALETTE = {   # section: (dark pair, light pair)
    'header': (('#4a3a1c', '#5e4a24'), ('#ffe9b0', '#ffd27a')),
    'quality': (('#1d3a4c', '#285068'), ('#cde8ff', '#9fd0ff')),
    'stats': (('#1f4224', '#2c5a32'), ('#d4f5d4', '#a8e6a8')),
    'lists': (('#45244a', '#5c3063'), ('#f2d4f7', '#ddb0ea')),
    'socketed': (('#4c2f1c', '#663f26'), ('#f7dcc8', '#eebc98')),
    'pad': (('#2c2c2c', '#383838'), ('#e6e6e6', '#d0d0d0')),
    'bad': (('#5a1414', '#5a1414'), ('#ffb0b0', '#ffb0b0')),
}


def tr(key, default, **kw):
    return T('bit.' + key, default, **kw)


def _dark():
    try:
        import mxl_d2_theme as D
        return D.dark()
    except Exception:
        return False


# ------------------------------------------------------------------ bits <-> bytes, decoding
def unpack(blob):
    return [(b >> k) & 1 for b in bytes(blob) for k in range(8)]


def pack(bits):
    out = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            out[i >> 3] |= 1 << (i & 7)
    return bytes(out)


def section_of(label, child):
    if child:
        return 'socketed'
    if label == 'padding':
        return 'pad'
    if label in HEADER:
        return 'header'
    if label.startswith('stats '):
        return 'stats'
    if label.startswith(('set list', 'runeword ')) and label != 'runeword id':
        return 'lists'
    return 'quality'


class Decoded:
    """One valid decode of an item blob: fields [(bit offset, width, label, value, item index)], items (mxlsave),
    host (the editor's own reading, blob_item)."""

    def __init__(self, blob, fields, items, host):
        self.blob, self.fields, self.items, self.host = blob, fields, items, host


def decode(blob, data):
    """Decoded, or raises with the reason: the item and its socketed items must use every byte, mxlsave must
    re-encode each to its bytes and the editor's reader must read the whole blob."""
    import mxl_inspect
    import mxl_savecheck
    from mxlsave import items as MI
    tb = mxl_savecheck.tables()
    blob = bytes(blob)
    fields, items = [], []
    pos, k, want = 0, 0, 1
    while pos < len(blob) and k < want:
        it, f = mxl_inspect.layout(blob, pos)
        if it.to_bytes(tb) != blob[pos:pos + it.size]:
            raise ValueError(tr('err.reencode', 'item {k}: mxlsave does not re-encode it to these bits', k=k + 1))
        fields += [(off, n, lab, v, k) for off, n, lab, v in f]
        items.append(it)
        if k == 0:
            want = 1 + (it.socketed_count if it.flag(MI.FLAG_SOCKETED) else 0)
        pos += it.size
        k += 1
    if k < want:
        raise ValueError(tr('err.short', '{n} socketed item(s) missing', n=want - k))
    if pos != len(blob):
        raise ValueError(tr('err.len', '{n} byte(s) left over after the item', n=len(blob) - pos))
    from mxl_save import blob_item
    host = blob_item(blob, data)
    return Decoded(blob, fields, items, host)


# ------------------------------------------------------------------ meanings
def _stat_of(label):
    parts = label.split()
    try:
        return int(parts[-2])
    except (ValueError, IndexError):
        return None


def meaning(dec, field, cursor, data):
    """Human text of the field under the cursor."""
    import mxl_inspect as I
    import mxl_savecheck
    from mxlsave import items as MI
    tb = mxl_savecheck.tables()
    off, n, lab, v, k = field
    it = dec.items[k] if k < len(dec.items) else None
    try:
        if lab == 'flags':
            b = cursor - off
            return f'bit {b} = {v >> b & 1}: {MI.FLAG_NAMES.get(b, "unknown")}'
        if lab == 'quality':
            return MI.QUALITY.get(v, '?')
        if lab == 'location':
            return MI.LOCATION.get(v, '?')
        if lab == 'panel':
            return MI.PANEL.get(v, '?')
        if lab.startswith('code['):
            return repr(chr(v))
        if lab == 'unique id':
            return I._name_of_row(data, data.uniques, v)
        if lab == 'set id':
            return I._name_of_row(data, data.set_items, v)
        if lab == 'runeword id':
            return tb.string(v) or ''
        if lab.endswith('stat id'):
            return 'end of list' if v == I.STAT_END else I._stat_name(data, tb, v)
        if lab.endswith(' param'):
            sid = _stat_of(lab)
            return f'{I._stat_name(data, tb, sid)}: {I._param_text(data, sid, v)}'
        if lab.endswith(' value'):
            sid = _stat_of(lab)
            add = tb.stats[sid].save_add
            return f'{I._stat_name(data, tb, sid)} = {v - add}' + (f' (raw {v} - {add})' if add else '')
        if lab == 'defense':
            return f'{v - tb.stats[31].save_add}'
        if lab in ('has picture', 'has auto affix', 'realm bit') or lab.endswith('present'):
            return 'yes' if v else 'no'
        if lab.startswith('name[') and v:
            return repr(chr(v))
        if lab == 'socketed count' and it is not None:
            return f'{v} socketed item(s)'
    except Exception:
        pass
    return ''


def parse_value(text, dec, field, cursor, data):
    """The raw bits value (and the bit range) a typed value means: (offset, width, raw)."""
    import mxl_inspect as I
    import mxl_savecheck
    from mxlsave import items as MI
    tb = mxl_savecheck.tables()
    off, n, lab, _v, _k = field
    s = text.strip()
    low = s.lower()
    if lab == 'flags':                             # one flag bit: the one under the cursor
        off, n = cursor, 1
    num = None
    try:
        if low.startswith('0x'):
            num = int(low, 16)
        elif low.startswith('0b'):
            num = int(low, 2)
        elif low.lstrip('-').isdigit():
            num = int(low)
    except ValueError:
        num = None
    if num is None:
        if low in ('yes', 'true', 'on'):
            num = 1
        elif low in ('no', 'false', 'off'):
            num = 0
        elif lab == 'quality':
            num = next((q for q, nm in MI.QUALITY.items() if nm == low), None)
        elif lab == 'location':
            num = next((q for q, nm in MI.LOCATION.items() if nm == low), None)
        elif lab == 'panel':
            num = next((q for q, nm in MI.PANEL.items() if nm == low), None)
        elif (lab.startswith('code[') or lab.startswith('name[')) and len(s) == 1:
            num = ord(s)
        elif lab.endswith('stat id'):
            for sid in range(len(tb.stats)):
                try:
                    if I._stat_name(data, tb, sid).lower() == low:
                        num = sid
                        break
                except Exception:
                    continue
        if num is None:
            raise ValueError(tr('err.value', 'not a value for {field}: {text}', field=lab, text=s))
    elif lab.endswith(' value'):                   # a stat's value as shown: stored with its save_add
        num += tb.stats[_stat_of(lab)].save_add
    elif lab == 'defense':
        num += tb.stats[31].save_add
    if not 0 <= num < (1 << n):
        raise ValueError(tr('err.range', '{num} does not fit in {n} bit(s) (0..{max})', num=num, n=n,
                            max=(1 << n) - 1))
    return off, n, num


# ------------------------------------------------------------------ the tab
class BitEditor:
    def __init__(self, app, blob, name, source=None, reason=None):
        self.app = app
        self.data = app.data
        self.name = name
        self.source = dict(source) if source else None     # stash item: page, x, y, code, _offset
        self.reason = reason
        self.orig = bytes(blob)
        self.bits = unpack(blob)
        self.cur = 0
        self.insert = False
        self.dec = None
        self.valid = False
        self.error = ''
        self.dark = _dark()
        self.cols = COLS
        self.gap = 3                                         # px between bytes
        self.udie = None                                     # the dark look's game-art layout (UdieLook)
        self.colour_mode = 'udie'                            # dark look: 'udie' red / white fields, 'sections'
        top = None
        try:
            import mxl_tabs
            if mxl_tabs._state.get('nb') is not None:
                top = mxl_tabs.host_window(app, TAB_KEY, owner=self, replace=True)
        except Exception:
            top = None
        if top is None:
            top = tk.Toplevel(app.root if hasattr(app, 'root') else app.canvas)
        self.top = top
        top.title(TAB_KEY)
        self._build()
        self.redecode()

    # ---- widgets
    def _build(self):
        art = None
        if self.dark:
            try:
                import mxl_d2look as D2
                art = D2.art()
            except Exception:
                art = None
        if art is not None:
            try:
                self.udie = UdieLook(self, art)
            except Exception as e:                       # plain layout, never a broken tab
                print('Bit editor: plain layout,', e)
                self.udie = None
                for w in self.top.winfo_children():
                    w.destroy()
        if self.udie is None:
            self._build_plain()
        self._bind_keys()

    def _build_plain(self):
        top = self.top
        dark = self.dark
        self.bg = '#141112' if dark else 'white'
        self.fg = '#d8cca0' if dark else 'black'
        self.font = 'TkFixedFont'
        bar = tk.Frame(top)
        bar.pack(side='bottom', fill='x', padx=2, pady=2)
        self.b_revert = tk.Button(bar, text=tr('revert', 'Revert'), command=self.revert)
        self.b_apply = tk.Button(bar, text=tr('apply', 'Apply'), command=self.apply)
        self.b_hex = tk.Button(bar, text=tr('copyhex', 'Copy hex'), command=self.copy_hex)
        self.b_dump = tk.Button(bar, text=tr('copydump', 'Copy text dump'), command=self.copy_dump)
        self.b_view = tk.Button(bar, text=tr('textview', 'Text dump'), command=self.toggle_view)
        for b in (self.b_revert, self.b_apply, self.b_hex, self.b_dump, self.b_view):
            b.pack(side='left', padx=2)
        self.mode = tk.Label(bar, text='', font=self.font)
        self.mode.pack(side='right', padx=4)
        self.state = tk.Label(top, text='', anchor='w', justify='left', wraplength=700)
        self.state.pack(side='bottom', fill='x', padx=4)
        self.state.bind('<Configure>', lambda e: self.state.configure(wraplength=max(200, e.width - 8)))
        line = tk.Frame(top)
        line.pack(side='bottom', fill='x', padx=4)
        self.pos_l = tk.Label(line, text='', font=self.font, anchor='w')
        self.pos_l.pack(side='left')
        self.val_l = tk.Label(line, text='', font=self.font, anchor='w', cursor='hand2',
                              fg='#4fa0ff' if not dark else '#8fc8ff')
        self.val_l.pack(side='left', fill='x', expand=True)
        self.val_l.bind('<Button-1>', lambda _e: self.edit_value())
        self.title_l = tk.Label(top, text='', anchor='w')
        self.title_l.pack(side='top', fill='x', padx=4)
        self.body = tk.Frame(top)
        self.body.pack(fill='both', expand=True)
        sy = tk.Scrollbar(self.body, orient='vertical')
        sx = tk.Scrollbar(self.body, orient='horizontal')
        self.cv = tk.Canvas(self.body, bg=self.bg, highlightthickness=1, takefocus=1,
                            yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.configure(command=self.cv.yview)
        sx.configure(command=self.cv.xview)
        sy.pack(side='right', fill='y')
        sx.pack(side='bottom', fill='x')
        self.cv.pack(fill='both', expand=True)
        self.text = tk.Text(self.body, wrap='none', font=self.font, bg=self.bg, fg=self.fg)
        self.text_shown = False
        import tkinter.font as tkfont
        f = tkfont.nametofont('TkFixedFont')
        self.cw = max(8, f.measure('0') + 3)
        self.ch = f.metrics('linespace') + 3
        self.left = f.measure('00000') + 8
        self.top_h = 2 * self.ch

    def _bind_keys(self):
        cv = self.cv
        cv.bind('<Button-1>', self.on_click)
        for key, fn in (('<Left>', lambda: self.move(-1)), ('<Right>', lambda: self.move(1)),
                        ('<Up>', lambda: self.move(-self.cols)), ('<Down>', lambda: self.move(self.cols)),
                        ('<Home>', lambda: self.move(-self.cur)), ('<End>', lambda: self.move(len(self.bits))),
                        ('<space>', self.toggle), ('<Key-0>', lambda: self.set_bit(0)),
                        ('<Key-1>', lambda: self.set_bit(1)), ('<Insert>', self.toggle_mode),
                        ('<Delete>', lambda: self.remove(False)), ('<BackSpace>', lambda: self.remove(True))):
            cv.bind(key, lambda _e, fn=fn: (fn(), 'break')[1])

    # ---- decode
    def redecode(self):
        try:
            self.dec = decode(pack(self.bits), self.data)
            self.valid = True
            self.error = ''
        except Exception as e:
            self.valid = False
            self.error = str(e) or type(e).__name__
        self._field_map()
        if self.udie is not None:
            self.udie.refresh_item()
        self.draw()
        self.show_status()

    def _field_map(self):
        """Per bit: the index of its field in the last valid decode (None past its end / in a 0-bit field)."""
        self.fmap = [None] * len(self.bits)
        if self.dec is None:
            return
        for i, (off, n, _lab, _v, _k) in enumerate(self.dec.fields):
            for b in range(off, min(off + n, len(self.bits))):
                self.fmap[b] = i

    def field_at(self, i):
        if self.dec is None or i >= len(self.fmap) or self.fmap[i] is None:
            return None
        return self.dec.fields[self.fmap[i]]

    # ---- drawing
    def _xy(self, i):
        C = self.cols
        return self.left + (i % C) * self.cw + (i % C) // 8 * self.gap, self.top_h + (i // C) * self.ch

    def draw(self):
        cv = self.cv
        cv.delete('all')
        dark = 0 if self.dark else 1
        udie = self.udie is not None and self.colour_mode == 'udie'
        fields = self.dec.fields if self.dec else []
        par = {}
        k_sec = {}
        for i, (off, n, lab, v, k) in enumerate(fields):     # alternate colours inside each section
            sec = section_of(lab, k)
            k_sec[sec] = k_sec.get(sec, -1) + 1
            par[i] = (sec, k_sec[sec] % 2)
        C = self.cols
        rule = '#7a6a48' if self.udie is not None else '#888888'
        if self.top_h:
            for c in range(C):
                x, _y = self._xy(c)
                if c % 8 == 0:
                    cv.create_text(x, 2, text=f'+{c // 8}', anchor='nw', fill=self.fg, font=self.font)
                cv.create_text(x + self.cw // 2, self.ch, text=str(c % 8), anchor='n', fill=rule, font=self.font)
        rows = (len(self.bits) + C) // C
        for r in range(rows):
            cv.create_text(2, self.top_h + r * self.ch + 1, text=f'{r * C // 8:>4}', anchor='nw',
                           fill=rule, font=self.font)
        for i, b in enumerate(self.bits):
            x, y = self._xy(i)
            fi = self.fmap[i]
            bad = fi is None or not self.valid and self.dec is None
            if udie:                                         # UdieToo: fields alternate red / white on black
                if bad:
                    cv.create_rectangle(x, y, x + self.cw, y + self.ch, fill=PALETTE['bad'][0][0], outline='')
                cv.create_text(x + self.cw // 2, y + self.ch // 2, text=str(b), font=self.udie.bitfont,
                               fill=UDIE_WHITE if bad or fi % 2 else UDIE_RED)
                continue
            if bad:
                col = PALETTE['bad'][dark][0]
            else:
                sec, alt = par[fi]
                col = PALETTE[sec][dark][alt]
            cv.create_rectangle(x, y, x + self.cw, y + self.ch, fill=col, outline='')
            cv.create_text(x + self.cw // 2, y + 1, text=str(b), anchor='n', fill=self.fg, font=self.font)
        x, y = self._xy(min(self.cur, max(0, len(self.bits))))
        curcol = '#ff4040' if not self.valid else ('#ffffff' if self.dark else '#000000')
        if udie and self.valid:
            curcol = '#f0d070'
        if self.insert:
            cv.create_rectangle(x - 1, y, x + 1, y + self.ch, fill=curcol, outline='', tags='cursor')
        else:
            cv.create_rectangle(x, y, x + self.cw, y + self.ch, outline=curcol, width=2, tags='cursor')
        w = self.left + C * self.cw + self.gap * (C // 8) + 4
        h = self.top_h + rows * self.ch + 4
        if self.udie is None:
            cv.configure(scrollregion=(0, 0, w, h), width=min(w, 740), height=min(h, 360))
        else:
            cv.configure(scrollregion=(0, 0, w, h))
        self._see()

    def _see(self):
        try:
            _x, y = self._xy(self.cur)
            h = float(self.cv.cget('scrollregion').split()[3])
            top, bot = self.cv.yview()
            if y < top * h or y + self.ch > bot * h:
                self.cv.yview_moveto(max(0.0, (y - self.ch * 2) / h))
        except (tk.TclError, ValueError, IndexError, ZeroDivisionError):
            pass

    # ---- status
    def show_status(self):
        i = self.cur
        f = self.field_at(i)
        m = ''
        if f is None:
            self.val_l.configure(text=tr('nofield', '(no field)'))
        else:
            off, n, lab, v, k = f
            who = '' if k == 0 else f'[socketed {k}] '
            m = meaning(self.dec, f, i, self.data)
            if self.udie is None:
                self.val_l.configure(text=f'{who}{lab} ({n} bit{"s" if n != 1 else ""} @ {(off) // 8}.{off % 8}) = '
                                          f'{v}{" (0x%X)" % v if v > 9 else ""}{"  " + m if m else ""}')
        if self.udie is None:
            self.pos_l.configure(text=f'{i // 8}.{i % 8} (bit {i})  ')
        else:
            self.udie.show_field(f, m)
        self.mode.configure(text=tr('mode.ins', 'INS') if self.insert else tr('mode.ovr', 'OVR'))
        changed = sum(1 for a, b in zip(unpack(self.orig), self.bits) if a != b) + abs(len(self.bits) - len(self.orig) * 8)
        if self.valid:
            h = self.dec.host
            txt = tr('ok', 'parses: {name} [{code}], {q}, {n} bytes, {ch} bit(s) changed',
                     name=_clean(h.get('name') or ''), code=h.get('code', '').strip(),
                     q=self.dec.items[0].quality_name if not self.dec.items[0].simple else 'simple',
                     n=len(self.dec.blob), ch=changed)
            self.state.configure(text=txt, fg='#3cb043' if self.dark else '#106010')
        else:
            self.state.configure(text=tr('bad', 'does not parse: {err} - the last valid decode stays shown '
                                                '({ch} bit(s) changed)', err=self.error, ch=changed), fg='#e03030')
        if self.source is None:
            self.b_apply.configure(state='disabled')
        else:
            self.b_apply.configure(state='normal' if self.valid else 'disabled')
        ro = '' if self.source is not None else '  - ' + (self.reason or tr('ro', 'read only (not a stash item)'))
        self.title_l.configure(text=f'{self.name}{ro}')

    # ---- editing
    def on_click(self, ev):
        self.cv.focus_set()
        x, y = self.cv.canvasx(ev.x), self.cv.canvasy(ev.y)
        r = int((y - self.top_h) // self.ch)
        if r < 0:
            return
        best = min(range(self.cols), key=lambda c: abs(self._xy(c)[0] + self.cw / 2 - x))   # nearest cell (gaps too)
        if x < self.left - 2:
            return
        self.cur = max(0, min(r * self.cols + best, len(self.bits) - (0 if self.insert else 1)))
        self.draw()
        self.show_status()

    def move(self, d):
        hi = len(self.bits) if self.insert else len(self.bits) - 1
        self.cur = max(0, min(self.cur + d, hi))
        self.draw()
        self.show_status()

    def toggle(self):
        if self.cur < len(self.bits):
            self.bits[self.cur] ^= 1
            self.redecode()

    def set_bit(self, v):
        if self.insert:
            self.bits.insert(self.cur, v)
            self.cur += 1
        elif self.cur < len(self.bits):
            self.bits[self.cur] = v
            self.cur = min(self.cur + 1, len(self.bits) - 1)
        self.redecode()

    def toggle_mode(self):
        self.insert = not self.insert
        if not self.insert:
            self.cur = min(self.cur, len(self.bits) - 1)
        self.draw()
        self.show_status()

    def remove(self, back):
        if not self.insert:
            self.state.configure(text=tr('delins', 'Delete / BackSpace work in insert mode only (Insert key)'),
                                 fg='#e03030')
            return
        if back:
            if self.cur > 0:
                del self.bits[self.cur - 1]
                self.cur -= 1
        elif self.cur < len(self.bits):
            del self.bits[self.cur]
        self.redecode()

    def write_field(self, off, n, raw):
        for j in range(n):
            if off + j < len(self.bits):
                self.bits[off + j] = raw >> j & 1
        self.redecode()

    def edit_value(self):
        from tkinter import simpledialog, messagebox
        f = self.field_at(self.cur)
        if f is None:
            return
        text = simpledialog.askstring(tr('val.title', 'Field value'),
                                      tr('val.ask', '{field}: new value (decimal, 0x hex, 0b bits or a name)',
                                         field=f[2]), initialvalue=str(f[3] if f[2] != 'flags' else
                                                                       f[3] >> (self.cur - f[0]) & 1),
                                      parent=self.top)
        if text is None or not text.strip():
            return
        try:
            off, n, raw = parse_value(text, self.dec, f, self.cur, self.data)
        except (ValueError, KeyError, IndexError) as e:
            messagebox.showerror(tr('val.title', 'Field value'), str(e), parent=self.top)
            return
        self.write_field(off, n, raw)

    def revert(self):
        self.bits = unpack(self.orig)
        self.cur = min(self.cur, len(self.bits) - 1)
        self.redecode()

    # ---- copy / text view
    def copy_hex(self):
        self.top.clipboard_clear()
        self.top.clipboard_append(pack(self.bits).hex(' ').upper())

    def dump_text(self):
        import mxl_inspect
        blob = self.dec.blob if self.dec is not None else self.orig
        return mxl_inspect.dump(blob, self.data, self.name)

    def copy_dump(self):
        self.top.clipboard_clear()
        self.top.clipboard_append(self.dump_text())

    def toggle_view(self):
        if self.text_shown:
            self.text.pack_forget()
            self.cv.pack(fill='both', expand=True)
            self.b_view.configure(text=tr('textview', 'Text dump'))
        else:
            self.text.configure(state='normal')
            self.text.delete('1.0', 'end')
            try:
                self.text.insert('1.0', self.dump_text())
            except Exception as e:
                self.text.insert('1.0', str(e))
            self.text.configure(state='disabled')
            self.cv.pack_forget()
            self.text.pack(fill='both', expand=True)
            self.b_view.configure(text=tr('bitview', 'Bits'))
        self.text_shown = not self.text_shown

    # ---- write back
    def _say(self, msg, error=False):
        self.state.configure(text=msg, fg='#e03030' if error else ('#3cb043' if self.dark else '#106010'))
        try:
            self.app.show_status(msg)
        except Exception:
            pass

    def apply(self):
        """Writes the edited bits in place of the item opened (stash items). False when refused."""
        import mxl_save
        import mxl_stash_order as SO
        from mxl_save import EditError
        from mxl_format import FormatError
        if self.source is None:
            self._say(tr('err.ro', 'not written: read only here ({why})',
                         why=self.reason or tr('ro', 'read only (not a stash item)')), True)
            return False
        try:                                   # decoded again right here: the state shown must not be trusted
            new = decode(pack(self.bits), self.data).blob
        except Exception as e:
            self.valid = False
            self._say(tr('err.parse', 'not written: the bits do not parse ({err})', err=e), True)
            return False
        if new == self.orig:
            self._say(tr('same', 'nothing to write: the bits are the item as it is'))
            return False
        app, s = self.app, self.source
        path = app.path
        key = (s['page'], s['x'], s['y'], s['code'])
        try:
            buf = bytes(mxl_save.read_file(path))
            items = SO.cached_parse_stash(path, self.data, buf)
            cur = next((i for i in items if (i['page'], i['x'], i['y'], i['code']) == key), None)
            if cur is None or bytes(mxl_save.item_blob(buf, cur)) != self.orig:
                try:
                    app.load(path, keep_selection=True)
                except Exception:
                    pass
                self._say(tr('err.stale', 'not written: the item changed on disk since it was opened (the game, '
                                          'another window or an undo wrote the stash) - open it again'), True)
                return False
            at = SO.page_index(path, self.data, cur['_offset'])
            bak = mxl_save.edit_stash(path, self.data, remove=[cur['_offset']],
                                      insert=[(s['page'], s['x'], s['y'], new)], backup=app.needs_backup(path))
        except (EditError, FormatError, OSError, ValueError) as e:
            self._say(tr('err.write', 'not written: {err}', err=e), True)
            return False
        app.backup_made(path, bak)
        buf = bytes(mxl_save.read_file(path))
        items = mxl_save.parse_stash(path, self.data)
        now = next((i for i in items if (i['page'], i['x'], i['y']) == key[:3]), None)
        after = bytes(mxl_save.item_blob(buf, now)) if now is not None else new
        try:
            import mxl_undo
            kw = dict(blob=self.orig, after=after, page=key[0], x=key[1], y=key[2], old_page=key[0],
                      old_x=key[1], old_y=key[2], name=self.name)
            if at is not None and at[0] == key[0]:
                kw['index'] = at[1]
            mxl_undo.record(app, 'replace', **kw)
        except Exception:
            pass
        try:
            from mxl_creator_gui import _reload_main
            _reload_main(app, key[:3])
        except Exception:
            pass
        self.orig = after
        if now is not None:
            self.source.update(code=now['code'], _offset=now['_offset'])
        self.bits = unpack(after)
        self.cur = min(self.cur, len(self.bits) - 1)
        self.redecode()
        self._say(tr('written', '{name} written (page {page}, {x}, {y}){bak} - Ctrl+Z undoes it', name=self.name,
                     page=key[0] + 1, x=key[1], y=key[2],
                     bak=(' - backup ' + __import__('os').path.basename(bak) if bak else '')))
        return True



# ------------------------------------------------------------------ the dark look: UdieToo's item editor
UDIE_RED = '#c8463c'
UDIE_WHITE = '#e8e4dc'
GOLD = '#c7b377'
GOLD_HI = '#f2dc9c'
BOX_FILL = '#0b0a09'
SECTIONS = ('header', 'quality', 'stats', 'lists', 'socketed', 'pad')
SECTION_NAMES = {'header': 'Header', 'quality': 'Quality', 'stats': 'Stats', 'lists': 'Set / runeword lists',
                 'socketed': 'Socketed items', 'pad': 'Padding'}


class _StoneButton(ttk.Button):
    """The theme's stone ttk button; cget('state') gives a plain string like tk.Button's."""

    def cget(self, key):
        v = super().cget(key)
        return str(v) if key == 'state' else v


class UdieLook:
    """The Bit editor in the dark look, laid out like UdieToo's item editor: the game's stone, a gold title
    banner, the item in a gear frame, boxes for the field's name / value (bits) / meaning, the framed "Item"
    panel with the bit stream (fields alternating red / white), the status bar, stone buttons and on the right
    the framed "Properties" list of the decoded fields (a click moves the cursor to the field)."""
    STONE = ('stash', (60, 566, 452, 642))       # plain stone under the stash grid (as mxl_d2look.CreatorHeader)
    M = 6

    def __init__(self, ed, art):
        import tkinter.font as tkfont
        import mxl_d2look as D2
        try:
            import mxl_he_theme as TH
            fam = TH.safe_family('Palatino Linotype')
        except Exception:
            fam = 'TkDefaultFont'
        self.ed, self.art, self.D2 = ed, art, D2
        self.F, self.FB = (fam, 10), (fam, 10, 'bold')
        self.filter = None
        self.rows = []
        self.layers = None
        self.item_size = None
        self._bg_key = None
        top = ed.top
        ed.bg, ed.fg = '#000000', '#d8cca0'
        ed.font = 'TkFixedFont'
        fixed = tkfont.nametofont('TkFixedFont')
        self.lh = tkfont.Font(root=top, font=self.F).metrics('linespace')
        cv = self.bgcv = tk.Canvas(top, bg='#141210', highlightthickness=0, bd=0)
        cv.pack(fill='both', expand=True)
        lab = dict(bg=BOX_FILL, bd=0, highlightthickness=0, font=self.F)
        ed.title_l = tk.Label(cv, fg=GOLD_HI, anchor='w', **lab)
        self.name_l = tk.Label(cv, fg=UDIE_WHITE, anchor='center', **lab)
        self.bits_l = tk.Label(cv, fg=UDIE_WHITE, anchor='center', justify='center', cursor='hand2', **lab)
        ed.val_l = tk.Label(cv, fg='#8fc8ff', anchor='center', cursor='hand2', **lab)
        for w in (self.bits_l, ed.val_l):
            w.bind('<Button-1>', lambda _e: ed.edit_value())
        ed.pos_l = tk.Label(cv, fg=UDIE_WHITE, anchor='w', **lab)
        ed.mode = tk.Label(cv, fg=GOLD, anchor='e', **lab)
        ed.state = tk.Label(cv, fg='#3cb043', anchor='nw', justify='left', **lab)
        # the "Item" panel: the bit stream (scrolled) or the text dump
        ed.body = tk.Frame(cv, bg='#000000', bd=0, highlightthickness=0)
        sy = ttk.Scrollbar(ed.body, orient='vertical')
        sy.pack(side='right', fill='y')
        ed.cv = tk.Canvas(ed.body, bg='#000000', highlightthickness=0, takefocus=1, yscrollcommand=sy.set)
        sy.configure(command=self._yview)
        ed.cv.pack(fill='both', expand=True)
        ed.text = tk.Text(ed.body, wrap='none', font=ed.font, bg='#000000', fg=ed.fg, insertbackground=GOLD)
        ed.text_shown = False
        fx = fixed.actual()
        self.bitfont = tkfont.Font(root=top, family=fx['family'], size=fx['size'], weight='bold')
        ed.cw = self.bitfont.measure('0') + 2
        ed.ch = self.bitfont.metrics('linespace') + 2
        ed.gap = 0                                        # one continuous stream, as UdieToo
        ed.left = fixed.measure('0000') + 8
        ed.top_h = 0
        # stone buttons (the theme's ttk buttons are the game's short menu button)
        ed.b_apply = _StoneButton(cv, text='\u2714 ' + tr('apply', 'Apply'), command=ed.apply)
        ed.b_revert = _StoneButton(cv, text='\u2298 ' + tr('revert', 'Revert'), command=ed.revert)
        ed.b_hex = _StoneButton(cv, text=tr('copyhex', 'Copy hex'), command=ed.copy_hex)
        ed.b_dump = _StoneButton(cv, text=tr('copydump', 'Copy text dump'), command=ed.copy_dump)
        ed.b_view = _StoneButton(cv, text=tr('textview', 'Text dump'), command=ed.toggle_view)
        self.b_colours = _StoneButton(cv, text=tr('colours.sections', 'Sections'), command=self.toggle_colours)
        self.buttons = (ed.b_apply, ed.b_revert, ed.b_hex, ed.b_dump, ed.b_view, self.b_colours)
        # the "Properties" panel: list selector row + the decoded fields
        self.filt = []
        for sec in (None,) + SECTIONS:
            col = '#e0c060' if sec is None else PALETTE[sec][0][1]
            b = tk.Label(cv, text='★' if sec is None else '', bg=col, fg='#201808', width=2,
                         font=(self.F[0], 7, 'bold'), bd=1, relief='raised', cursor='hand2',
                         highlightthickness=1, highlightbackground='#8a7a4a')
            b.bind('<Button-1>', lambda _e, s=sec: self.set_filter(s))
            self.filt.append((sec, b))
        self.pframe = tk.Frame(cv, bg=BOX_FILL)
        psy = ttk.Scrollbar(self.pframe, orient='vertical')
        psy.pack(side='right', fill='y')
        self.props = tk.Listbox(self.pframe, bg=BOX_FILL, fg='#d8d0c0', selectbackground='#4a3a14',
                                selectforeground=GOLD_HI, font=self.F, activestyle='none', highlightthickness=0,
                                bd=0, exportselection=False, yscrollcommand=psy.set)
        psy.configure(command=self.props.yview)
        self.props.pack(fill='both', expand=True)
        self.props.bind('<<ListboxSelect>>', self.on_pick)
        self.win = {}
        for key, w in (('title', ed.title_l), ('name', self.name_l), ('bits', self.bits_l), ('val', ed.val_l),
                       ('body', ed.body), ('pos', ed.pos_l), ('mode', ed.mode), ('state', ed.state),
                       ('props', self.pframe)):
            self.win[key] = cv.create_window(0, 0, window=w, anchor='nw')
        for i, b in enumerate(self.buttons):
            self.win['b%d' % i] = cv.create_window(0, 0, window=b, anchor='nw')
        for i, (_s, b) in enumerate(self.filt):
            self.win['f%d' % i] = cv.create_window(0, 0, window=b, anchor='nw')
        cv.bind('<Configure>', lambda e: self.layout())

    def _yview(self, *a):
        self.ed.cv.yview(*a)

    # ---- art
    def _stone(self, W, H):
        """The stone texture filling W x H (mirror-tiled: no seams), as a tk image."""
        if self._bg_key == (W, H):
            return self._bg
        from PIL import Image, ImageTk
        name, box = self.STONE
        src = Image.open(self.art.panel(name)).convert('RGB').crop(box)
        tw, th = src.size
        out = Image.new('RGB', (W, H))
        for y in range(0, H, th):
            for x in range(0, W, tw):
                t = src
                if (y // th) % 2:
                    t = t.transpose(Image.FLIP_TOP_BOTTOM)
                if (x // tw) % 2:
                    t = t.transpose(Image.FLIP_LEFT_RIGHT)
                out.paste(t, (x, y))
        self._bg = ImageTk.PhotoImage(out, master=self.bgcv)
        self._bg_key = (W, H)
        return self._bg

    def _box(self, x0, y0, x1, y1, fill=BOX_FILL):
        """UdieToo's framed box: dark inside, a bronze frame with a thin gold line."""
        cv = self.bgcv
        cv.create_rectangle(x0 - 3, y0 - 3, x1 + 3, y1 + 3, outline='#2a2214', width=1, tags='art')
        cv.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline='#6e5a32', width=2, tags='art')
        cv.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline='#c8ac68', width=1, fill=fill, tags='art')

    def _heading(self, x0, y0, x1, y1, text):
        """A header strip ("Item", "Properties") in the game's font, centred, like UdieToo."""
        self._box(x0, y0, x1, y1, fill='#1a1610')
        cy = (y0 + y1) // 2
        for x in (x0 + 10, x1 - 10):
            self.bgcv.create_oval(x - 3, cy - 3, x + 3, cy + 3, fill='#c8ac68', outline='#6e5a32', tags='art')
        self.D2.draw_text(self.bgcv, (x0 + x1) // 2, cy, text, font='font16', tags=('art',))

    # ---- layout
    def layout(self):
        ed, cv, M = self.ed, self.bgcv, self.M
        W, H = max(cv.winfo_width(), 300), max(cv.winfo_height(), 300)
        cv.delete('art')
        cv.create_image(0, 0, anchor='nw', image=self._stone(W, H), tags='art')
        lh = self.lh
        # title banner
        TB = 34
        cv.create_rectangle(0, 0, W, TB, fill='#16130f', outline='', tags='art')
        cv.create_line(0, TB, W, TB, fill='#6e5a32', width=2, tags='art')
        cv.create_line(0, TB + 2, W, TB + 2, fill='#c8ac68', width=1, tags='art')
        self.D2.draw_text(cv, W // 2, TB // 2 + 1, tr('title', 'Capybara Bit Editor'), font='font30',
                          tags=('art',))
        RW = max(220, min(360, int(W * 0.34)))
        LW = W - RW - 3 * M
        rx = LW + 2 * M
        # buttons row and the decorative strip at the very bottom
        bh = max(b.winfo_reqheight() for b in self.buttons)
        need = TB + 4 * lh + 40 + 22 + 8 * ed.ch + 2 * lh + 14 + bh + 6 * M     # with 8 rows of bits
        strip = 0
        if H - need >= round(104 * self.STRIP_K) + 8:
            strip = round(104 * self.STRIP_K)
            self._strip(H - strip, W, strip)
        yb = H - strip - M - bh
        x = M + 4
        for i, b in enumerate(self.buttons):
            cv.coords(self.win['b%d' % i], x, yb)
            x += b.winfo_reqwidth() + (8 if i == 1 else 3)
        # left column, top: the item picture, the item name, the field boxes
        y = TB + M + 4
        boxes_h = lh + 4 + 3 * (lh + 6) + lh + 3 * 8
        w_cells, h_cells = self.item_size or (2, 2)
        c = max(12, min(26, (boxes_h - 12) // max(2, h_cells)))
        iw, ih = max(2, w_cells) * c + 12, max(2, h_cells) * c + 12
        ix = M + 4
        try:
            frame = 23 if (w_cells, h_cells) != (1, 1) else 19
            if h_cells >= 3:
                frame = 14 if h_cells >= 4 else 15
            cv.create_image(ix, y, anchor='nw', tags='art',
                            image=self.D2.photo(self.art.frame(self.D2.GEAR_FILE, frame), (iw, ih), tag='bitedit'))
        except Exception:
            self._box(ix, y, ix + iw, y + ih)
        for k in (1, 2, 3):
            img = (self.layers or {}).get(k)
            if img is not None:
                cv.create_image(ix + iw / 2, y + ih / 2, image=img, tags='art')
        bx0, bx1 = ix + iw + 3 * M, LW
        cv.coords(self.win['title'], bx0, y)
        cv.itemconfigure(self.win['title'], width=bx1 - bx0, height=lh + 2)
        ty = y + lh + 10
        for key, n in (('name', 1), ('bits', 2), ('val', 1)):
            h = n * lh + 4
            self._box(bx0, ty, bx1, ty + h)
            cv.coords(self.win[key], bx0 + 2, ty + 2)
            cv.itemconfigure(self.win[key], width=bx1 - bx0 - 4, height=h - 4)
            ty += h + 8
        y = max(y + ih, ty) + M
        # the "Item" panel
        self._heading(M + 3, y, LW, y + 18, tr('panel.item', 'Item'))
        y += 18 + 8
        sh = 2 * lh + 10                                 # status bar: position line + parse state
        by1 = yb - M - sh - 8
        self._box(M + 3, y, LW, by1)
        cv.coords(self.win['body'], M + 3, y)
        cv.itemconfigure(self.win['body'], width=LW - M - 3, height=max(20, by1 - y))
        sy0 = by1 + 8
        self._box(M + 3, sy0, LW, sy0 + sh)
        mw = ed.mode.winfo_reqwidth() + 6
        cv.coords(self.win['pos'], M + 6, sy0 + 2)
        cv.itemconfigure(self.win['pos'], width=LW - M - 9 - mw, height=lh + 2)
        cv.coords(self.win['mode'], LW - mw, sy0 + 2)
        cv.itemconfigure(self.win['mode'], width=mw - 2, height=lh + 2)
        cv.coords(self.win['state'], M + 6, sy0 + lh + 6)
        cv.itemconfigure(self.win['state'], width=LW - M - 9, height=sh - lh - 8)
        ed.state.configure(wraplength=LW - M - 12)
        # bits per row: whole bytes that fit the panel
        avail = LW - M - 3 - 20 - ed.left
        cols = max(8, int(avail // (ed.cw * 8)) * 8)
        if cols != ed.cols:
            ed.cols = cols
            ed.draw()
        # right column: "List" selector, "Properties"
        y = TB + M + 4
        self._box(rx, y, W - M - 3, y + 18, fill='#1a1610')
        self.D2.draw_text(cv, rx + 8, y + 9, tr('panel.list', 'List'), font='font16', anchor='w', tags=('art',))
        fx = rx + 52
        for i, (_s, b) in enumerate(self.filt):
            cv.coords(self.win['f%d' % i], fx, y)
            cv.itemconfigure(self.win['f%d' % i], width=18, height=18)
            fx += 21
        y += 18 + 10
        self._heading(rx, y, W - M - 3, y + 18, tr('panel.props', 'Properties'))
        y += 18 + 8
        self._box(rx, y, W - M - 3, yb - M)
        cv.coords(self.win['props'], rx, y)
        cv.itemconfigure(self.win['props'], width=W - M - 3 - rx, height=max(20, yb - M - y))
        cv.tag_lower('art')

    STRIP_K = 0.7                                    # the control panel art (104 px high) at 70 %

    def _strip(self, y0, W, h):
        """The bottom edge as in the game: the control panel with the life / mana orbs and the belt (base-game
        art 800ctrlpnl7 / hlthmana / overlap; decoration only). Flat circles when the art is missing."""
        cv, k = self.bgcv, self.STRIP_K
        cv.create_rectangle(0, y0, W, y0 + h, fill='#0e0c0a', outline='', tags='art')

        def put(name, idx, x, y, anchor='nw'):
            p = self.art.base_frame(name, idx)
            from PIL import Image
            with Image.open(p) as im:
                iw, ih = im.size
            img = self.D2.photo(p, (max(1, round(iw * k)), max(1, round(ih * k))), tag='bitedit')
            cv.create_image(x, y, image=img, anchor=anchor, tags='art')
            return round(iw * k)

        try:
            bottom = y0 + h
            mid = [1, 2, 3, 4]
            mw = sum(round(w * k) for w in (128, 128, 128, 86))
            x = (W - mw) // 2
            for i in mid:
                x += put('800ctrlpnl7.dc6', i, x, bottom, 'sw')
            for side, orb in ((0, 0), (1, 1)):
                hx = 0 if side == 0 else W
                put('800ctrlpnl7.dc6', 0 if side == 0 else 5, hx, bottom, 'sw' if side == 0 else 'se')
                cx = hx + (round(64 * k) if side == 0 else -round(64 * k))
                cy = bottom - round(52 * k)
                put('hlthmana.dc6', orb, cx, cy, 'center')
                put('overlap.dc6', orb, cx, cy, 'center')
            return
        except Exception:
            pass
        r = h // 2 - 4
        for cx, col in ((r + 14, '#7a0c0c'), (W - r - 14, '#0c0c7a')):
            cy = y0 + h // 2
            cv.create_oval(cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3, fill='#2a2214', outline='#6e5a32',
                           width=2, tags='art')
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline='', tags='art')

    # ---- content
    def refresh_item(self):
        """The item's picture and the Properties list, after a decode."""
        ed = self.ed
        size, layers = self.item_size, self.layers
        if ed.dec is not None and ed.valid:
            h = ed.dec.host
            try:
                size = ed.data.base(h.get('code', '').strip()).size
            except Exception:
                size = None
            try:
                layers = ed.app.icon(h, self.D2.CELL_BG)
            except Exception:
                layers = None
        changed = (size, layers) != (self.item_size, self.layers)
        self.item_size, self.layers = size, layers
        self.fill_props()
        if changed and self.bgcv.winfo_width() > 1:
            self.layout()

    def fill_props(self):
        ed = self.ed
        lb = self.props
        lb.delete(0, 'end')
        self.rows = []
        if ed.dec is None:
            return
        last = None
        for i, f in enumerate(ed.dec.fields):
            off, n, lab, v, k = f
            sec = section_of(lab, k)
            if self.filter is not None and sec != self.filter:
                continue
            if sec != last:
                lb.insert('end', tr('sec.' + sec, SECTION_NAMES[sec]).upper())
                lb.itemconfigure('end', fg=GOLD_HI, selectforeground=GOLD_HI, selectbackground=BOX_FILL)
                self.rows.append(None)
                last = sec
            try:
                m = '' if lab == 'flags' else meaning(ed.dec, f, off, ed.data)
            except Exception:
                m = ''
            who = '' if k == 0 else f'[{k}] '
            lb.insert('end', f'  {who}{lab} = {v}' + (f'  {m}' if m else ''))
            self.rows.append(i)

    def set_filter(self, sec):
        self.filter = sec
        for s, b in self.filt:
            b.configure(relief='sunken' if s == sec else 'raised')
        self.fill_props()
        self.show_field(self.ed.field_at(self.ed.cur), None)

    def on_pick(self, _e=None):
        sel = self.props.curselection()
        if not sel or sel[0] >= len(self.rows) or self.rows[sel[0]] is None:
            return
        ed = self.ed
        ed.cur = ed.dec.fields[self.rows[sel[0]]][0]
        ed.draw()
        ed.show_status()
        ed.cv.focus_set()

    def toggle_colours(self):
        ed = self.ed
        ed.colour_mode = 'sections' if ed.colour_mode == 'udie' else 'udie'
        self.b_colours.configure(text=tr('colours.sections', 'Sections') if ed.colour_mode == 'udie'
                                 else tr('colours.udie', 'Red / white'))
        ed.draw()

    def show_field(self, f, m):
        """The boxes and the status bar for the field under the cursor (UdieToo: Pos <bit> (<total>)
        Selection[<a> - <b>] <n> bits)."""
        ed = self.ed
        i, total = ed.cur, len(ed.bits)
        if f is None:
            self.name_l.configure(text=tr('nofield', '(no field)'))
            self.bits_l.configure(text='')
            ed.val_l.configure(text=tr('nofield', '(no field)'))
            ed.pos_l.configure(text=tr('udie.pos0', 'Pos {i} ({total}) Selection[{i} - {i}] 0 bits', i=i,
                                       total=total))
            return
        off, n, lab, v, k = f
        if m is None:
            m = meaning(ed.dec, f, i, ed.data)
        who = '' if k == 0 else f'[socketed {k}] '
        self.name_l.configure(text=f'{who}{lab}')
        self.bits_l.configure(text=f'{v}' + (' (0x%X)' % v if v > 9 else '') +
                              '\n(' + tr('udie.nbits', '{n} bits', n=n) + f' @ {off // 8}.{off % 8})')
        ed.val_l.configure(text=m or f'= {v}')
        ed.pos_l.configure(text=tr('udie.pos', 'Pos {i} ({total}) Selection[{a} - {b}] {n} bits', i=i, total=total,
                                   a=off, b=off + n - 1, n=n) + f'   {who}{lab}' + (f': {m}' if m else ''))
        try:
            fi = ed.dec.fields.index(f)
            row = self.rows.index(fi)
        except ValueError:
            return
        self.props.selection_clear(0, 'end')
        self.props.selection_set(row)
        self.props.see(row)


def _clean(name):
    try:
        from mxl_creator_gui import clean
        return clean(name)
    except Exception:
        return str(name)


def open_item(app, blob, name, source=None, reason=None):
    """Opens the item (its bytes, socketed items included) in the Bit editor tab. source: the stash item (dict with
    page, x, y, code, _offset) Apply writes back to; None = read only (reason says why)."""
    try:
        return BitEditor(app, blob, name, source, reason)
    except Exception as e:
        try:
            app.show_status(str(e))
        except Exception:
            pass
        import traceback
        traceback.print_exc()
        return None
