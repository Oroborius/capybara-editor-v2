"""Character window page "Counters": the Median XL extras of the character stats section.

What the game data shows (docs/SAVE_FORMAT.md section 4.1 has the sample evidence):
- stat 88 "achievement data": many entries [16-bit parameter ("layer")][32-bit value].
  * layer < 0x2000 = a kill counter. `monstats3.bin` has, per monster row, a u16 at +21: the layer a kill of that
    monster is counted in (0 = not counted). 131 layers for 479 monsters in 2.14.x; a layer is named after the
    monstats row with the same number (e.g. layer 956 "Cow Soldier" also counts Cow Honcho, Cow Ninja ...). All 27
    kill layers of the sample character are layers of that column.
  * layers 0x2000-0x200C = general counters. Only 0x200C has a proven meaning: play time in seconds (it moves with
    the save clock). The others have no name in the tables or string tables: they are shown raw.
  * anything else is "unknown" and shown raw.
- stat 185 / 186: the misc.bin rows of the Signet of Learning / Signet of Skill items give two stats each
  (4 = stat points + 185, 5 = skill points + 186) with a formula from itemscode.bin: min(n, 400 - stat185) and
  max(2 - stat186, 0). The cap is read from those formulas at run time, never hard-coded.

Edits are pending until SAVE (apply() -> Character.set_stat). The game leaves out a stat worth 0: a counter set to 0
is removed from the file.
"""
import os
import struct
import tkinter as tk
from tkinter import ttk

from mxl_lang import T

STAT_ACH, STAT_LEARN, STAT_SKILL = 88, 185, 186
GENERAL_BASE, GENERAL_LAST, PLAYTIME = 0x2000, 0x200C, 0x200C
VALUE_MAX = 0xFFFFFFFF
SIGNET_MAX = {STAT_LEARN: 4095, STAT_SKILL: 255}     # fallback widths (12 / 8 bits); the real ones come from the data
KINDS = ('monster', 'general', 'unknown')


# ---------------------------------------------------------------------------------------------- game data
def _clean(text):
    txt = str(text or '')
    while 'ÿc' in txt:
        i = txt.index('ÿc')
        txt = txt[:i] + txt[i + 3:]
    parts = [p.strip() for p in txt.split('\n') if p.strip()]
    return parts[-1] if parts else ''                # game strings list their lines bottom-up: the name is last


def _table(data, name):
    try:
        return data._rows(name)
    except Exception:
        return []


def layers(data):
    """{layer: [monstats rows counted in it]} from monstats3.bin (u16 at +21); {} when the table is missing."""
    cached = getattr(data, '_counter_layers', None)
    if cached is None:
        cached = {}
        for i, r in enumerate(_table(data, 'monstats3')):
            if len(r) >= 23:
                v = struct.unpack_from('<H', r, 21)[0]
                if v:
                    cached.setdefault(v, []).append(i)
        try:
            data._counter_layers = cached
        except Exception:
            pass
    return cached


def monster_name(data, mid):
    names = getattr(data, '_counter_mnames', None)
    if names is None:
        names = {}
        for i, r in enumerate(_table(data, 'monstats')):
            try:
                names[i] = _clean(data.s(struct.unpack_from('<H', r, 6)[0]))
            except Exception:
                names[i] = ''
        try:
            data._counter_mnames = names
        except Exception:
            pass
    return names.get(mid, '')


def kind(data, param):
    if param < GENERAL_BASE:
        return 'monster' if (param in layers(data) or monster_name(data, param)) else 'unknown'
    return 'general' if param <= GENERAL_LAST else 'unknown'


def members(data, param):
    """Names of the monsters counted in a kill layer (the layer's own monster first, no repeats)."""
    out = []
    for mid in [param] + layers(data).get(param, []):
        n = monster_name(data, mid)
        if n and n not in out:
            out.append(n)
    return out


def entry_name(data, param):
    k = kind(data, param)
    if k == 'monster':
        names = members(data, param)
        if not names:
            return f'monster {param}'
        return names[0] + (f' +{len(names) - 1}' if len(names) > 1 else '')
    if param == PLAYTIME:
        return T('cnt.playtime', 'Play time (h:mm:ss)')
    if k == 'general':
        return T('cnt.general_n', 'Counter 0x{param:04X}', param=param)
    return f'0x{param:04X}'


def _eval(code, pos, used):
    """Runs one compiled item formula (RPN byte code of itemscode.bin) with the counter stat worth `used`.
    Only the tokens the signet formulas use are known; anything else -> None (the cap is then "not found")."""
    st = []
    try:
        while True:
            op = code[pos]
            if op == 0x00:
                return st[-1] if len(st) == 1 else None
            if op == 0x07:
                st.append(code[pos + 1])
                pos += 2
            elif op == 0x08:
                st.append(struct.unpack_from('<H', code, pos + 1)[0])
                pos += 3
            elif op == 0x01:
                fn = code[pos + 1]
                pos += 2
                b, a = st.pop(), st.pop()
                if fn == 3:                          # stat(id, 0)
                    st.append(used)
                elif fn == 0:
                    st.append(min(a, b))
                elif fn == 1:
                    st.append(max(a, b))
                else:
                    return None
            elif op == 0x11:
                b, a = st.pop(), st.pop()
                st.append(a - b)
                pos += 1
            elif op == 0x13:                         # '*' or '/': only read when the operand is 1 (same either way)
                b, a = st.pop(), st.pop()
                if b != 1:
                    return None
                st.append(a)
                pos += 1
            else:
                return None
    except (IndexError, struct.error):
        return None


def signet_caps(data):
    """{185: [(cap, points per use, item name), ...], 186: [...]} read from misc.bin + itemscode.bin: every item
    whose two stats are (4, 185) / (5, 186). cap = the counter value at which the item's formula gives nothing."""
    cached = getattr(data, '_counter_caps', None)
    if cached is not None:
        return cached
    out = {STAT_LEARN: [], STAT_SKILL: []}
    try:
        with open(os.path.join(data.folder, 'itemscode.bin'), 'rb') as f:
            code = f.read()
    except OSError:
        code = b''
    for r in _table(data, 'misc'):
        if len(r) < 248 or not code:
            continue
        s1, s2 = struct.unpack_from('<HH', r, 158)
        if (s1, s2) not in ((4, STAT_LEARN), (5, STAT_SKILL)):
            continue
        pos = struct.unpack_from('<I', r, 168)[0]    # the formula of the counter stat itself
        if pos >= len(code):
            continue
        first = _eval(code, pos, 0)
        if first is None or first <= 0:
            continue
        cap = next((u for u in range(1, 4097) if (_eval(code, pos, u) or 0) <= 0), None)
        if cap is None:
            continue
        try:
            name = _clean(data.s(struct.unpack_from('<H', r, 244)[0]))
        except Exception:
            name = ''
        if not any(c == cap and n == name for c, _p, n in out[s2]):
            out[s2].append((cap, first, name))
    try:
        data._counter_caps = out
    except Exception:
        pass
    return out


def cap_text(data, sid):
    """One line: the cap(s) the item formulas state, or "not found"."""
    found = signet_caps(data).get(sid) or []
    if not found:
        return T('cnt.cap_none', 'game cap: not found')
    base = min(c for c, _p, _n in found)
    txt = T('cnt.cap', 'game cap {cap} (from game data)', cap=base)
    more = sorted({(c, n) for c, _p, n in found if c > base})
    if more:
        txt += '; ' + ', '.join(T('cnt.cap_more', '{cap} with {item}', cap=c, item=n or '?') for c, n in more)
    return txt


def stat_max(data, sid):
    try:
        import mxl_char
        return (1 << mxl_char._csv(data)[sid][1]) - 1
    except Exception:
        return SIGNET_MAX.get(sid, VALUE_MAX)


# ---------------------------------------------------------------------------------------------- values
def fmt_time(seconds):
    s = max(0, int(seconds))
    return f'{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}'


def parse_time(text):
    """'h:mm:ss', 'm:ss' or plain seconds -> seconds; None when it is not a time."""
    parts = str(text).strip().split(':')
    if not 1 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total if total <= VALUE_MAX else None


def parse_param(data, text, taken=()):
    """What the add box holds -> a layer number: '0x2003', '8195', 'Name (961)' or a monster name (exact, or the
    only tracked one containing the text). None when nothing / more than one thing fits."""
    txt = str(text).strip()
    if not txt:
        return None
    if txt.endswith(')') and '(' in txt:
        inner = txt[txt.rindex('(') + 1:-1]
        if inner.isdigit():
            txt = inner
    try:
        p = int(txt, 16) if txt.lower().startswith('0x') else int(txt)
        return p if 0 <= p <= 0xFFFF else None
    except ValueError:
        pass
    low = txt.lower()
    exact, part = [], []
    for layer in sorted(layers(data)):
        names = [n.lower() for n in members(data, layer)]
        if names and names[0] == low:
            exact.append(layer)
        elif any(low in n for n in names):
            part.append(layer)
    for group in (exact, part):
        free = [p for p in group if p not in taken] or group
        if len(free) == 1:
            return free[0]
        if free:
            return None
    return None


def read(ch):
    """(signets {185: v, 186: v}, counters {layer: value}) of a Character."""
    sig = {STAT_LEARN: 0, STAT_SKILL: 0}
    cnt = {}
    for sid, param, value in ch.stats:
        if sid == STAT_ACH:
            cnt[param or 0] = value
        elif sid in sig:
            sig[sid] = value
    return sig, cnt


def write(ch, sig0, cnt0, sig, cnt):
    """Writes only what differs from (sig0, cnt0) into the Character; a counter worth 0 / deleted is left out."""
    for sid in (STAT_LEARN, STAT_SKILL):
        if sig[sid] != sig0[sid]:
            ch.set_stat(sid, sig[sid])
    for p in sorted(set(cnt0) | set(cnt)):
        new = cnt.get(p, 0)
        if new != cnt0.get(p, 0):
            ch.set_stat(STAT_ACH, new, p)


# ---------------------------------------------------------------------------------------------- page
class CountersPage:
    COLS = 2

    def __init__(self, win, frame):
        self.win, self.frame = win, frame
        self.data = win.data
        self.dark = False
        self.sig0, self.cnt0 = {STAT_LEARN: 0, STAT_SKILL: 0}, {}
        self.sig, self.cnt = dict(self.sig0), {}
        self.rows = {}                                # layer -> (variable, editor widget)
        self._loading = False
        try:
            import mxl_char_gui
            self.font, self.font_s = mxl_char_gui.HE_FONT, mxl_char_gui.HE_FONT_S
        except Exception:
            self.font, self.font_s = ('Times New Roman', 11), ('Times New Roman', 10)
        self._build()
        self.refresh()

    # ---- widgets
    def _spin(self, parent, var, top, width):
        vcmd = (parent.register(lambda s, top=top: s == '' or (s.isdigit() and int(s) <= top)), '%P')
        sp = tk.Spinbox(parent, from_=0, to=top, textvariable=var, width=width, font=self.font, justify='right',
                        validate='key', validatecommand=vcmd, bd=1, highlightthickness=0)
        return sp

    def _build(self):
        f, d = self.frame, self.data
        box = tk.LabelFrame(f, text=T('cnt.signets', 'Signets'), font=self.font, padx=4, pady=2)
        box.pack(fill='x', padx=4, pady=(3, 2))
        self.sig_vars = {}
        labels = {STAT_LEARN: T('cnt.learn', 'Signets of Learning used'),
                  STAT_SKILL: T('cnt.skill', 'Signets of Skill used')}
        for r, sid in enumerate((STAT_LEARN, STAT_SKILL)):
            top = stat_max(d, sid)
            tk.Label(box, text=labels[sid], font=self.font, anchor='w').grid(row=r, column=0, sticky='w')
            var = tk.StringVar()
            var.trace_add('write', lambda *_a, sid=sid: self._on_signet(sid))
            self.sig_vars[sid] = var
            self._spin(box, var, top, 6).grid(row=r, column=1, padx=4, pady=1)
            tk.Label(box, text=T('cnt.range', '0 - {top} storable', top=top) + ';  ' + cap_text(d, sid),
                     font=self.font, anchor='w', justify='left', wraplength=340).grid(row=r, column=2, sticky='w')
        tk.Label(box, font=self.font_s, anchor='w', justify='left', wraplength=620, text=T(
            'cnt.sig_note', 'A signet adds points and raises its counter until the cap; a lower counter lets signets '
            'be used again. Only the counter is changed here, not the points.')).grid(row=2, column=0, columnspan=3, sticky='w')
        box.columnconfigure(2, weight=1)

        box = tk.LabelFrame(f, text=T('cnt.ach', 'Achievement counters (stat 88)'), font=self.font, padx=4, pady=2)
        box.pack(fill='both', expand=True, padx=4, pady=(0, 3))
        bar = tk.Frame(box)
        bar.pack(fill='x')
        tk.Label(bar, text=T('cnt.search', 'Search'), font=self.font).pack(side='left')
        self.search = tk.StringVar()
        self.search.trace_add('write', lambda *_a: self._rebuild())
        tk.Entry(bar, textvariable=self.search, width=14, font=self.font).pack(side='left', padx=(3, 10))
        tk.Label(bar, text=T('cnt.add', 'Add'), font=self.font).pack(side='left')
        self.add_var = tk.StringVar()
        self.add_box = ttk.Combobox(bar, textvariable=self.add_var, width=22, font=self.font)
        self.add_box.pack(side='left', padx=3)
        self.add_box.bind('<KeyRelease>', self._filter_add)
        self.add_box.bind('<Return>', lambda _e: self.add_entry())
        tk.Button(bar, text='+', font=self.font, padx=4, pady=0, command=self.add_entry).pack(side='left')
        tk.Label(bar, text=T('cnt.add_hint', 'name or layer (961, 0x2003)'),
                 font=self.font_s).pack(side='left', padx=6)
        self.grid = tk.Frame(box)
        self.grid.pack(fill='both', expand=True, pady=(2, 0))
        self.note = tk.Label(box, font=self.font_s, anchor='w', justify='left', wraplength=620, text=T(
            'cnt.note', 'A counter set to 0 is removed on save (the game stores no zero). Kill layers: monstats3 '
            'column of the game data. Counters 0x2000-0x200B have no name in the game data; nothing in the tables '
            'shows which entries the game tests.'))
        self.note.pack(fill='x')

    # ---- state
    def refresh(self):
        self.sig0, self.cnt0 = read(self.win.ch)
        self.sig, self.cnt = dict(self.sig0), dict(self.cnt0)
        self._loading = True
        for sid, var in self.sig_vars.items():
            var.set(str(self.sig[sid]))
        self._loading = False
        self._rebuild()

    def rebase(self):
        """win.ch was written / read again without this page's edits: the values typed here stay, the file's are
        the new reference (an entry the file gained meanwhile is taken over as it is)."""
        old_sig, old_cnt = self.sig0, self.cnt0
        self.sig0, self.cnt0 = read(self.win.ch)
        added = False
        for p, v in self.cnt0.items():
            if p not in self.cnt and p not in old_cnt:
                self.cnt[p] = v
                added = True
            elif p in self.cnt and self.cnt[p] == old_cnt.get(p) and v != self.cnt[p]:
                self.cnt[p] = v
                added = True
        for sid in self.sig:
            if self.sig[sid] == old_sig[sid] and self.sig0[sid] != self.sig[sid]:
                self.sig[sid] = self.sig0[sid]
                self._loading = True
                self.sig_vars[sid].set(str(self.sig[sid]))
                self._loading = False
        if added:
            self._rebuild()

    def dirty(self):
        return self.sig != self.sig0 or {p: v for p, v in self.cnt.items() if v} != self.cnt0

    def apply(self):
        write(self.win.ch, self.sig0, self.cnt0, self.sig, self.cnt)

    def _changed(self):
        try:
            self.win.update_dirty()
        except Exception:
            pass

    def _on_signet(self, sid):
        if self._loading:
            return
        txt = self.sig_vars[sid].get()
        self.sig[sid] = int(txt) if txt.isdigit() else 0
        self._changed()

    def _on_value(self, param):
        if self._loading or param not in self.rows:
            return
        txt = self.rows[param][0].get()
        if param == PLAYTIME:
            v = parse_time(txt)
            self.rows[param][1].configure(fg=self._colours()['entry_fg'] if v is not None else '#ff4040')
            if v is None:
                return
        else:
            v = int(txt) if txt.isdigit() else 0
        self.cnt[param] = v
        self._changed()

    def _step_time(self, delta):
        v = max(0, min(VALUE_MAX, self.cnt.get(PLAYTIME, 0) + delta))
        self.rows[PLAYTIME][0].set(fmt_time(v))
        return 'break'

    # ---- list
    def _matches(self, param, needle):
        if not needle:
            return True
        hay = [entry_name(self.data, param), f'0x{param:04x}', str(param)] + members(self.data, param)
        return any(needle in h.lower() for h in hay)

    def _describe(self, param):
        k = kind(self.data, param)
        head = T('cnt.layer', 'layer {param} (0x{param:04X})', param=param)
        if k == 'monster':
            names = members(self.data, param)
            return head + ': ' + T('cnt.kills_of', 'kills of {names}', names=', '.join(names) or '?')
        if param == PLAYTIME:
            return head + ': ' + T('cnt.playtime_d', 'play time in seconds ({sec})', sec=self.cnt.get(param, 0))
        if k == 'general':
            return head + ': ' + T('cnt.general_d', 'general counter, meaning not in the game data')
        return head + ': ' + T('cnt.unknown_d', 'unknown')

    def _rebuild(self):
        g = self.grid
        for w in g.winfo_children():
            w.destroy()
        self.rows = {}
        self._loading = True
        needle = self.search.get().strip().lower()
        titles = {'monster': T('cnt.g_monster', 'Monster kills'), 'general': T('cnt.g_general', 'General'),
                  'unknown': T('cnt.g_unknown', 'Unknown')}
        groups = {k: [] for k in KINDS}
        for p in sorted(self.cnt):
            groups[kind(self.data, p)].append(p)
        groups['monster'].sort(key=lambda p: (entry_name(self.data, p).lower(), p))
        row = 0
        for k in KINDS:
            shown = [p for p in groups[k] if self._matches(p, needle)]
            if not shown:
                continue
            tk.Label(g, text=f'{titles[k]} ({len(shown)}/{len(groups[k])})' if needle else
                     f'{titles[k]} ({len(groups[k])})', font=self.font + ('bold',), anchor='w').grid(
                row=row, column=0, columnspan=4 * self.COLS, sticky='w', pady=(2, 0))
            row += 1
            per = (len(shown) + self.COLS - 1) // self.COLS
            for i, p in enumerate(shown):                # filled column by column
                self._row(g, row + i % per, 4 * (i // per), p, k)
            row += per
        for c in range(self.COLS):
            g.columnconfigure(4 * c, weight=1, uniform='name')
        self._loading = False
        self._theme(self.grid)
        self._fill_add()
        try:
            self.win.scroll.refresh()
        except Exception:
            pass

    def _row(self, g, r, c, param, k):
        name = entry_name(self.data, param)
        if k != 'monster' and param != PLAYTIME:
            name = f'0x{param:04X}' if k == 'unknown' else name
        elif k == 'monster':
            name = f'{name}  [{param}]'
        lab = tk.Label(g, text=name, font=self.font, anchor='w', width=20)
        lab.grid(row=r, column=c, sticky='ew')
        lab.bind('<Enter>', lambda _e, p=param: self.win.set_status(self._describe(p)))
        var = tk.StringVar()
        if param == PLAYTIME:
            var.set(fmt_time(self.cnt[param]))
            ed = tk.Entry(g, textvariable=var, width=11, font=self.font, justify='right', bd=1, highlightthickness=0)
            ed.bind('<Up>', lambda _e: self._step_time(60))
            ed.bind('<Down>', lambda _e: self._step_time(-60))
        else:
            var.set(str(self.cnt[param]))
            ed = self._spin(g, var, VALUE_MAX, 10)
        var.trace_add('write', lambda *_a, p=param: self._on_value(p))
        ed.grid(row=r, column=c + 1, padx=2)
        tk.Button(g, text='x', font=self.font_s, padx=3, pady=0, bd=1, takefocus=0,
                  command=lambda p=param: self.delete_entry(p)).grid(row=r, column=c + 2, padx=(0, 10))
        self.rows[param] = (var, ed)

    # ---- add / delete
    def _candidates(self):
        return [f'{entry_name(self.data, p)} ({p})' for p in sorted(
            (p for p in layers(self.data) if p not in self.cnt), key=lambda p: entry_name(self.data, p).lower())]

    def _fill_add(self):
        try:
            self.add_box.configure(values=self._candidates())
        except tk.TclError:
            pass

    def _filter_add(self, ev=None):
        if ev is not None and ev.keysym in ('Up', 'Down', 'Return', 'Escape', 'Tab'):
            return
        low = self.add_var.get().strip().lower()
        allv = self._candidates()
        self.add_box.configure(values=[v for v in allv if low in v.lower()] if low else allv)

    def add_entry(self, text=None, value=1):
        p = parse_param(self.data, self.add_var.get() if text is None else text, taken=self.cnt)
        if p is None:
            self.win.set_status(T('cnt.add_bad', 'Add: pick one monster of the list or type a layer number '
                                  '(0 - 65535, 0x... for hex).'), True)
            return None
        if p in self.cnt:
            self.win.set_status(T('cnt.add_have', '{name} is already in the list.', name=entry_name(self.data, p)), True)
        else:
            self.cnt[p] = value
            self.win.set_status(T('cnt.added', 'Added: {what}', what=self._describe(p)))
        self._loading = True
        self.add_var.set('')
        self.search.set('')
        self._loading = False
        self._rebuild()
        if p in self.rows:
            self.rows[p][1].focus_set()
        self._changed()
        return p

    def delete_entry(self, param):
        if param in self.cnt:
            del self.cnt[param]
            self.win.set_status(T('cnt.deleted', 'Removed on save: {what}', what=self._describe(param)))
            self._rebuild()
            self._changed()

    def set_value(self, param, value):
        """Sets one counter (as typing would); play time takes seconds."""
        if param in self.rows:
            self.rows[param][0].set(fmt_time(value) if param == PLAYTIME else str(value))
        else:
            self.cnt[param] = value
            self._changed()

    # ---- looks
    def _colours(self):
        try:
            import mxl_char_gui
            return mxl_char_gui.THEMES[bool(self.dark)]
        except Exception:
            return {'bg': '#f0f0f0', 'fg': '#000000', 'entry': '#ffffff', 'entry_fg': '#000000', 'btn': '#e1e1e1',
                    'frame_fg': '#000000'}

    def _theme(self, w):
        t = self._colours()
        cls = w.winfo_class()
        try:
            if cls == 'Frame':
                w.configure(bg=t['bg'])
            elif cls == 'Labelframe':
                w.configure(bg=t['bg'], fg=t['frame_fg'])
            elif cls == 'Label':
                w.configure(bg=t['bg'], fg=t['fg'])
            elif cls == 'Button':
                w.configure(bg=t['btn'], fg=t['fg'], activebackground=t['btn'], activeforeground=t['fg'])
            elif cls == 'Entry':
                w.configure(bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg'])
            elif cls == 'Spinbox':
                w.configure(bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg'],
                            buttonbackground=t['btn'], readonlybackground=t['entry'])
        except tk.TclError:
            pass
        for c in w.winfo_children():
            self._theme(c)

    def set_theme(self, dark):
        self.dark = bool(dark)
        self._theme(self.frame)


def install(App=None):
    import mxl_char_gui
    mxl_char_gui.register_page('counters', T('ch.tab.counters', 'Counters'), CountersPage)
