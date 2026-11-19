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
        cv = self.cv
        cv.bind('<Button-1>', self.on_click)
        for key, fn in (('<Left>', lambda: self.move(-1)), ('<Right>', lambda: self.move(1)),
                        ('<Up>', lambda: self.move(-COLS)), ('<Down>', lambda: self.move(COLS)),
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
        return self.left + (i % COLS) * self.cw + (i % COLS) // 8 * 3, self.top_h + (i // COLS) * self.ch

    def draw(self):
        cv = self.cv
        cv.delete('all')
        dark = 0 if self.dark else 1
        fields = self.dec.fields if self.dec else []
        par = {}
        k_sec = {}
        for i, (off, n, lab, v, k) in enumerate(fields):     # alternate colours inside each section
            sec = section_of(lab, k)
            k_sec[sec] = k_sec.get(sec, -1) + 1
            par[i] = (sec, k_sec[sec] % 2)
        for c in range(COLS):
            x, _y = self._xy(c)
            if c % 8 == 0:
                cv.create_text(x, 2, text=f'+{c // 8}', anchor='nw', fill=self.fg, font=self.font)
            cv.create_text(x + self.cw // 2, self.ch, text=str(c % 8), anchor='n', fill='#888888', font=self.font)
        rows = (len(self.bits) + COLS) // COLS
        for r in range(rows):
            cv.create_text(2, self.top_h + r * self.ch + 1, text=f'{r * COLS // 8:>4}', anchor='nw',
                           fill='#888888', font=self.font)
        for i, b in enumerate(self.bits):
            x, y = self._xy(i)
            fi = self.fmap[i]
            if fi is None or not self.valid and self.dec is None:
                col = PALETTE['bad'][dark][0]
            else:
                sec, alt = par[fi]
                col = PALETTE[sec][dark][alt]
            cv.create_rectangle(x, y, x + self.cw, y + self.ch, fill=col, outline='')
            cv.create_text(x + self.cw // 2, y + 1, text=str(b), anchor='n', fill=self.fg, font=self.font)
        x, y = self._xy(min(self.cur, max(0, len(self.bits))))
        curcol = '#ff4040' if not self.valid else ('#ffffff' if self.dark else '#000000')
        if self.insert:
            cv.create_rectangle(x - 1, y, x + 1, y + self.ch, fill=curcol, outline='', tags='cursor')
        else:
            cv.create_rectangle(x, y, x + self.cw, y + self.ch, outline=curcol, width=2, tags='cursor')
        w = self.left + COLS * self.cw + 3 * 8 + 4
        h = self.top_h + rows * self.ch + 4
        cv.configure(scrollregion=(0, 0, w, h), width=min(w, 740), height=min(h, 360))
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
        self.pos_l.configure(text=f'{i // 8}.{i % 8} (bit {i})  ')
        f = self.field_at(i)
        if f is None:
            self.val_l.configure(text=tr('nofield', '(no field)'))
        else:
            off, n, lab, v, k = f
            who = '' if k == 0 else f'[socketed {k}] '
            m = meaning(self.dec, f, i, self.data)
            self.val_l.configure(text=f'{who}{lab} ({n} bit{"s" if n != 1 else ""} @ {(off) // 8}.{off % 8}) = {v}'
                                      f'{" (0x%X)" % v if v > 9 else ""}{"  " + m if m else ""}')
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
        best = min(range(COLS), key=lambda c: abs(self._xy(c)[0] + self.cw / 2 - x))   # nearest cell (gaps too)
        if x < self.left - 2:
            return
        self.cur = max(0, min(r * COLS + best, len(self.bits) - (0 if self.insert else 1)))
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
