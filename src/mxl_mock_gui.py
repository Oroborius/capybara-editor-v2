"""Mock Mode in the main window (folder profiles only, e.g. vanilla Diablo II 1.14d; Median XL looks as before).

A small "Mock Mode" toggle at the very right of the top bar switches the mode (kept in the settings as
'mock_mode'). While it is on, a "Mock" tab offers:
- Generator: preset + name + Generate (optional overrides: mana, TK, class, level, position, Stun <-> Stability,
  damage target, life, aura plan). The result is a NEW .d2s in the profile's save folder (asked first, never
  overwrites; a free name is chosen);
- Analyzer: the computed values of the loaded character with colour-coded checks (per weapon side);
- Item crafter: a small charm / jewel with arbitrary stat lines added to the loaded character's inventory
  (asked first; the editor's safe writer with a backup).
The engine is mxl_mock (no GUI there)."""
import os
import tkinter as tk
from tkinter import messagebox, ttk

import mxl_mock as M
from mxl_lang import T

TAB = 'Mock'
SETTING = 'mock_mode'
COLORS = {M.GOOD: '#3fa34d', M.WARN: '#d9a520', M.BAD: '#e0524a', M.INFO: ''}
_state = {'app': None, 'var': None, 'button': None, 'page': None}


def _setting(default=False):
    try:
        import settings
        v = settings.get(SETTING)
        return bool(v) if v is not None else default
    except Exception:
        return default


def _put(value):
    try:
        import settings
        settings.put(SETTING, bool(value))
    except Exception as e:
        print('mock mode setting not saved:', e)


def enabled():
    """True when the profile is not Median XL (the only place the toggle exists)."""
    try:
        import mxl_profile
        return not mxl_profile.is_median()
    except Exception:
        return False


def install(App):
    """The toggle in the top bar (after mxl_toolbar: it stays at the right end, the bar counts its width)."""
    o_build = App._build

    def _build(self):
        o_build(self)
        if not enabled():
            return
        try:
            _make_toggle(self)
        except Exception as e:
            print('mock mode disabled:', type(e).__name__, e)

    App._build = _build


def _make_toggle(app):
    bar = app.char_combo.master
    var = tk.BooleanVar(value=_setting())
    b = ttk.Checkbutton(bar, text=T('mock.toggle', 'Mock Mode'), variable=var, style='Toolbutton',
                        command=lambda: set_mode(var.get()), takefocus=False)
    first = (bar.pack_slaves() or [None])[0]
    b.pack(side='right', padx=(2, 4), **({'before': first} if first is not None else {}))
    _state.update(app=app, var=var, button=b)
    tb = getattr(app, 'toolbar', None)
    if tb is not None and hasattr(tb, '_needed'):            # the bar's layout leaves room for the toggle
        o_needed = tb._needed
        tb._needed = lambda hidden: o_needed(hidden) + b.winfo_reqwidth() + 6
        tb.state = None
        try:
            tb.layout()
        except Exception:
            pass
    if var.get():
        app.root.after_idle(lambda: set_mode(True, select=False))


def set_mode(on, select=True):
    """Switches Mock Mode: the Mock tab appears / goes; the choice is kept in the settings."""
    app = _state['app']
    if app is None or not enabled():                     # Median XL: no Mock Mode at all
        return
    if _state['var'] is not None and _state['var'].get() != bool(on):
        _state['var'].set(bool(on))
    _put(on)
    if app is None:
        return
    import mxl_tabs
    nb = mxl_tabs._state.get('nb')
    if on:
        if _state['page'] is not None:
            return
        prev = None
        try:
            prev = nb.select() if nb is not None else None
        except tk.TclError:
            pass
        host = mxl_tabs.host_window(app, TAB)
        if host is None:
            return
        _state['page'] = MockPage(app, host)
        if not select and prev:
            try:
                nb.select(prev)
            except tk.TclError:
                pass
    else:
        page = _state['page']
        _state['page'] = None
        if page is None:
            return
        host = page.host
        try:
            if nb is not None and str(host) in nb.tabs():
                nb.forget(host)
        except tk.TclError:
            pass
        mxl_tabs._state['pages'].pop(TAB, None)
        try:
            host.destroy()
        except tk.TclError:
            pass


def _int(s, what):
    s = str(s).strip().replace(' ', '').replace(',', '')
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        raise M.PlanError(T('mock.err.number', '{what}: a whole number', what=what))


class MockPage:
    """The Mock tab: Generator | Analyzer, Item crafter below the analyzer."""

    def __init__(self, app, host):
        self.app, self.host = app, host
        try:
            host.title(TAB)
        except Exception:
            pass
        outer = ttk.Frame(host, padding=4)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)
        self._generator(ttk.LabelFrame(outer, text=T('mock.gen', 'Generator'), padding=4))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky='nsew', padx=(4, 0))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self._analyzer(ttk.LabelFrame(right, text=T('mock.ana', 'Analyzer'), padding=4))
        self._crafter(ttk.LabelFrame(right, text=T('mock.craft', 'Item crafter'), padding=4))
        host.bind('<Map>', lambda e: self.analyze() if e.widget is host else None, add='+')

    # ------------------------------------------------------------------ generator
    def _generator(self, f):
        f.grid(row=0, column=0, sticky='nsw')
        self.labels = {M.PRESETS[k]['label']: k for k in M.PRESET_ORDER}
        self.preset = tk.StringVar(value=M.PRESETS['mock_high']['label'])
        self.name = tk.StringVar(value='MockHigh')
        r = 0
        ttk.Label(f, text=T('mock.preset', 'Preset')).grid(row=r, column=0, sticky='w')
        cb = ttk.Combobox(f, textvariable=self.preset, values=list(self.labels), state='readonly', width=18)
        cb.grid(row=r, column=1, sticky='ew', pady=1)
        cb.bind('<<ComboboxSelected>>', lambda e: self._preset_changed())
        r += 1
        ttk.Label(f, text=T('mock.name', 'Name')).grid(row=r, column=0, sticky='w')
        ttk.Entry(f, textvariable=self.name, width=18).grid(row=r, column=1, sticky='ew', pady=1)
        r += 1
        self.gen_btn = ttk.Button(f, text=T('mock.generate', 'Generate'), command=self.generate)
        self.gen_btn.grid(row=r, column=0, columnspan=2, sticky='ew', pady=(2, 4))
        r += 1
        self.note = ttk.Label(f, text='', wraplength=260, justify='left')
        self.note.grid(row=r, column=0, columnspan=2, sticky='w')
        r += 1
        o = ttk.LabelFrame(f, text=T('mock.over', 'Overrides (empty = preset)'), padding=3)
        o.grid(row=r + 1, column=0, columnspan=2, sticky='ew', pady=(4, 0))
        self.ov = {}
        rows = (('mana', T('mock.o.mana', 'Target mana')), ('tk', T('mock.o.tk', 'Telekinesis level')),
                ('level', T('mock.o.level', 'Character level')), ('damage', T('mock.o.damage', 'Damage (PvP)')),
                ('life', T('mock.o.life', 'Life')), ('hf_sources', T('mock.o.hf', 'Holy Freeze sources (3-7)')),
                ('hf_level', T('mock.o.hflvl', 'Holy Freeze level')), ('thorns', T('mock.o.thorns', 'Thorns level')),
                ('barbs', T('mock.o.barbs', 'Barbs level')))
        for i, (k, lab) in enumerate(rows):
            ttk.Label(o, text=lab).grid(row=i, column=0, sticky='w')
            v = tk.StringVar()
            ttk.Entry(o, textvariable=v, width=10).grid(row=i, column=1, sticky='ew', pady=1)
            self.ov[k] = v
        i = len(rows)
        ttk.Label(o, text=T('mock.o.class', 'Class')).grid(row=i, column=0, sticky='w')
        self.cls = tk.StringVar(value=M.CLASSES[1])
        ttk.Combobox(o, textvariable=self.cls, values=list(M.CLASSES), state='readonly', width=10).grid(
            row=i, column=1, sticky='ew', pady=1)
        i += 1
        ttk.Label(o, text=T('mock.o.pos', 'Position')).grid(row=i, column=0, sticky='w')
        self.pos = tk.StringVar(value=M.DEFAULTS['position'])
        ttk.Combobox(o, textvariable=self.pos, values=list(M.POSITIONS), state='readonly', width=10).grid(
            row=i, column=1, sticky='ew', pady=1)
        i += 1
        # TK31 mana by the expected enemy aura (high aura -> low mana, low -> high, none / PT -> 1572863)
        ttk.Label(o, text=T('mock.o.enemy', 'Enemy aura')).grid(row=i, column=0, sticky='w')
        self.enemy = tk.StringVar(value='preset')
        ttk.Combobox(o, textvariable=self.enemy, values=['preset'] + list(M.ENEMY_AURA_MANA), state='readonly',
                     width=10).grid(row=i, column=1, sticky='ew', pady=1)
        i += 1
        ttk.Label(o, text=T('mock.o.stun', 'Stability <-> Stun')).grid(row=i, column=0, sticky='w')
        self.stun = tk.IntVar(value=-1)
        self.stun_lbl = ttk.Label(o, text=T('mock.o.stun_auto', 'preset'))
        sc = ttk.Scale(o, from_=0, to=100, orient='horizontal', command=self._stun_moved)
        sc.grid(row=i, column=1, sticky='ew')
        self.stun_scale = sc
        self.stun_lbl.grid(row=i + 1, column=1, sticky='w')
        i += 2
        ttk.Label(o, text=T('mock.o.auras', 'Prayer 31 on every list, sources on the 40 charms; Holy Freeze '
                                           'sources on gear jewels; one Meditation (highest without regen '
                                           'roll-over), one Thorns, Oak Sage on the rest; NV Dopplezon on a charm.'),
                  wraplength=250, justify='left').grid(row=i, column=0, columnspan=2, sticky='w', pady=(3, 0))
        self.result = tk.Text(f, width=36, height=5, wrap='word', relief='flat', borderwidth=1)
        self.result.grid(row=r, column=0, columnspan=2, sticky='ew', pady=(4, 0))
        self._preset_changed()

    def _stun_moved(self, v):
        n = int(float(v))
        self.stun.set(n)
        self.stun_lbl.configure(text=T('mock.o.stun_val', '{n}: stun {pct}% per line', n=n,
                                       pct=M._stun_from_slider(n)))

    def _preset_changed(self):
        k = self.labels.get(self.preset.get(), 'mock_high')
        p = M.PRESETS[k]
        self.note.configure(text=p.get('note', ''))
        cur = self.name.get()
        if not cur or cur == getattr(self, '_auto_name', None) or cur == 'MockHigh':
            self._auto_name = ''.join(c for c in p['label'] if c.isalpha())[:15]     # the preset's name
            self.name.set(self._auto_name)
        self.stun.set(-1)
        self.stun_lbl.configure(text=T('mock.o.stun_auto', 'preset'))

    def overrides(self):
        o = {}
        for k, v in self.ov.items():
            n = _int(v.get(), k)
            if n is not None:
                o[k] = n
        if 'damage' in o:
            o['damage'] = min(o['damage'], int(M.DMG_CAP_PVP))
        o['cls'] = M.CLASSES.index(self.cls.get()) if self.cls.get() in M.CLASSES else 1
        o['position'] = self.pos.get() or None
        if self.enemy.get() in M.ENEMY_AURA_MANA:
            o['enemy_aura'] = self.enemy.get()
        if self.stun.get() >= 0:
            o['stun'] = self.stun.get()
        return o

    def generate(self):
        root = self.app.root
        key = self.labels.get(self.preset.get(), 'mock_high')
        name = self.name.get().strip()
        try:
            if not M.valid_name(name):
                raise M.PlanError(T('mock.err.name', 'Name: 2 to 15 letters (A-Z), at most one - or _, not at the '
                                                     'start or the end'))
            raw, P = M.generate(key, name, **self.overrides())
            folder = getattr(self.app, 'save_dir', None) or os.environ.get('MXL_SAVE_DIR')
            if not folder:
                raise M.PlanError(T('mock.err.folder', 'No save folder.'))
            free = M.free_name(folder, name)
            if not messagebox.askyesno(T('mock.title', 'Mock Mode'),
                                       T('mock.ask', 'Write the NEW character {file} into\n{folder}?\n'
                                                     '(Nothing is overwritten.)', file=free + '.d2s', folder=folder),
                                       parent=root):
                return
            path = M.write_new(raw, folder, free)
        except (M.PlanError, OSError) as e:
            messagebox.showerror(T('mock.title', 'Mock Mode'), str(e), parent=root)
            return
        self.last = path
        txt = [T('mock.written', 'Written: {file}', file=os.path.basename(path))] + M.summary(P, raw)
        self.result.delete('1.0', 'end')
        self.result.insert('end', '\n'.join(txt))
        try:
            self.app.select_character(os.path.splitext(os.path.basename(path))[0], self.app.view.get())
        except Exception as e:
            print('mock: new character not selected:', e)
        self.analyze()

    # ------------------------------------------------------------------ analyzer
    def _analyzer(self, f):
        f.grid(row=0, column=0, sticky='nsew')
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky='ew')
        ttk.Button(top, text=T('mock.analyze', 'Analyze'), command=self.analyze).pack(side='left')
        self.side = tk.StringVar(value='')
        self.side_box = ttk.Combobox(top, textvariable=self.side, values=[], state='readonly', width=12)
        self.side_box.pack(side='left', padx=4)
        self.side_box.bind('<<ComboboxSelected>>', lambda e: self.analyze(keep_side=True))
        self.who = ttk.Label(top, text='')
        self.who.pack(side='left', padx=4)
        self.tree = ttk.Treeview(f, columns=('value',), show='tree headings', height=14)
        self.tree.heading('#0', text=T('mock.check', 'Check'))
        self.tree.heading('value', text=T('mock.value', 'Value'))
        self.tree.column('#0', width=200, stretch=False)
        self.tree.column('value', width=420, stretch=True)
        self.tree.grid(row=1, column=0, sticky='nsew')
        sb = ttk.Scrollbar(f, orient='vertical', command=self.tree.yview)
        sb.grid(row=1, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=sb.set)
        for st, col in COLORS.items():
            if col:
                self.tree.tag_configure(st, foreground=col)

    def _character(self):
        try:
            path = self.app.character_file()
        except Exception:
            path = None
        if not path or not os.path.isfile(path):
            return None, None
        import mxl_char
        return path, mxl_char.Character(path, self.app.data)

    def analyze(self, keep_side=False):
        self.tree.delete(*self.tree.get_children())
        try:
            path, ch = self._character()
        except Exception as e:
            self.who.configure(text=f'{type(e).__name__}: {e}')
            return None
        if ch is None:
            self.who.configure(text=T('mock.nochar', 'no character loaded'))
            return None
        m = M.model_from_character(ch)
        sides = M.sides(m)
        labels = [T('mock.side', 'side {s}', s=s) + (' *' if i == 0 else '') for i, s in enumerate(sides)]
        self.side_box.configure(values=labels)
        side = sides[0]
        if keep_side and self.side.get() in labels:
            side = sides[labels.index(self.side.get())]
        self.side.set(labels[sides.index(side)])
        a = M.analyze(m, side)
        self.who.configure(text=f'{ch.name} ({os.path.basename(path)})')
        for key, label, text, st in a['checks']:
            mark = {M.GOOD: '✔ ', M.WARN: '! ', M.BAD: '✖ '}.get(st, '  ')
            self.tree.insert('', 'end', text=mark + label, values=(text,), tags=(st,))
        self.report = a
        return a

    # ------------------------------------------------------------------ item crafter
    def _crafter(self, f):
        f.grid(row=1, column=0, sticky='ew', pady=(4, 0))
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text=T('mock.c.base', 'Item')).grid(row=0, column=0, sticky='w')
        self.base = tk.StringVar(value='charm')
        ttk.Combobox(f, textvariable=self.base, values=list(M.CRAFT_BASES), state='readonly', width=8).grid(
            row=0, column=1, sticky='w')
        ttk.Button(f, text=T('mock.c.add', 'Add to the loaded character'), command=self.craft).grid(
            row=0, column=2, sticky='e')
        self.lines = tk.Text(f, width=40, height=5, wrap='none', relief='flat', borderwidth=1)
        self.lines.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(2, 0))
        self.lines.insert('end', 'aura prayer 31\nmana 223\nmana% 53\ndr 63\n')
        ttk.Label(f, text=T('mock.c.help', "One line per stat: 'stat [param] value', 'mana 223', 'aura prayer 31', "
                                           "'ctc_attack stun 63 10', 'skill smite 63'; '--' starts the jewel's "
                                           "second list."), wraplength=480, justify='left').grid(
            row=2, column=0, columnspan=3, sticky='w')

    def craft(self):
        root = self.app.root
        try:
            path, ch = self._character()
            if ch is None:
                raise M.PlanError(T('mock.nochar', 'no character loaded'))
            isc = M.isc_from_data(self.app.data)
            lists = M.parse_lines(self.lines.get('1.0', 'end'), isc)
            cell = M.free_cell(ch, self.app.data)
            if cell is None:
                raise M.PlanError(T('mock.c.full', 'The inventory has no free cell.'))
            blob = M.craft_item(self.base.get(), lists, *cell, isc=isc)
            if not messagebox.askyesno(T('mock.title', 'Mock Mode'),
                                       T('mock.c.ask', 'Add the {item} to {name} (inventory cell {x},{y})?\n'
                                                       'A backup of the file is made.', item=self.base.get(),
                                         name=ch.name, x=cell[0], y=cell[1]), parent=root):
                return
            import mxl_char
            ch.items.append(mxl_char.Entry(None, blob))
            ch.reload_items()
            ch.save(backup=True)
        except Exception as e:
            messagebox.showerror(T('mock.title', 'Mock Mode'), f'{e}', parent=root)
            return
        try:
            self.app.select_character(ch.name, self.app.view.get())
        except Exception:
            pass
        self.analyze()
