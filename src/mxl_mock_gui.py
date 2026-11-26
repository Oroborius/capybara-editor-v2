"""Mock Mode in the main window (folder profiles only, e.g. vanilla Diablo II 1.14d; Median XL looks as before).

A small "Mock Mode" toggle at the very right of the top bar switches the mode (kept in the settings as
'mock_mode'). While it is on, a "Mock" tab offers three sub tabs:
- Generator: preset + name + a big Generate button; every user-changeable stat as a prefilled field (spin boxes,
  check boxes, combo boxes) in groups (tabs on the left, each a scroll area): Mana / TK, Life / regen, Auras (with
  the source count next to each aura), Damage, Stun / Delirium, Defenses, Speeds, NV / switch. Check (and
  Generate) validates the form, shows problems next to their fields and fills the summary panel on the right.
  Generate writes a NEW .d2s in the profile's save folder without a question (never overwrites: a free name);
- Analyzer: the checks and the same summary panel for the loaded character;
The summary panel (SummaryPanel) shows ONE weapon switch (A / B, weapon slots I / II): the other switch's items
count nothing. The engine is mxl_mock (no GUI there)."""
import os
import tkinter as tk
from tkinter import messagebox, ttk

import mxl_mock as M
import mxl_scroll
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


class _Tip:
    """A small hover hint (unit and range of a field)."""

    def __init__(self, w, text):
        self.w, self.text, self.top = w, text, None
        if text:
            w.bind('<Enter>', self.show, add='+')
            w.bind('<Leave>', self.hide, add='+')

    def show(self, _e=None):
        if self.top is not None:
            return
        self.top = t = tk.Toplevel(self.w)
        t.wm_overrideredirect(True)
        t.wm_geometry(f'+{self.w.winfo_rootx() + 12}+{self.w.winfo_rooty() + self.w.winfo_height() + 2}')
        tk.Label(t, text=self.text, background='#ffffe0', foreground='#000000', relief='solid', borderwidth=1,
                 wraplength=260, justify='left').pack()

    def hide(self, _e=None):
        if self.top is not None:
            self.top.destroy()
            self.top = None


def _int(s, what):
    s = str(s).strip().replace(' ', '').replace(',', '')
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        raise M.PlanError(T('mock.err.number', '{what}: a whole number', what=what))


SECTION_ORDER = ('Defense targets', 'Checks', 'Caps', 'Auras', 'Defenses', 'Speeds', 'Damage', 'Life / mana', 'Skills / states',
                 'Clone profile')
SIDE_LABEL = {'A': 'A (weapon I)', 'B': 'B (weapon II)'}


def _bg(w):
    try:
        return ttk.Style(w).lookup('TFrame', 'background') or None
    except tk.TclError:
        return None


class SummaryPanel:
    """Total stats of ONE weapon switch (the other switch's items count nothing): caps (mana band / off-screen,
    regen, smite, aura damage, file size, lines per list), every active aura with its level, number of sources
    and the sources themselves, the category totals and the clone-profile check. Used by the Generator (the
    plan, no file) and the Analyzer (the loaded character)."""

    def __init__(self, parent, on_change=None, title=None):
        self.on_change = on_change
        self.model, self.role, self.extra = None, None, None
        f = self.frame = ttk.LabelFrame(parent, text=title or T('mock.sum', 'Summary'), padding=2)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        top = ttk.Frame(f)
        top.grid(row=0, column=0, columnspan=2, sticky='ew')
        ttk.Label(top, text=T('mock.switch', 'Switch')).pack(side='left')
        self.side = tk.StringVar(value='A')
        self.side_btn = {}
        for s in ('A', 'B'):
            b = ttk.Radiobutton(top, text=SIDE_LABEL[s], value=s, variable=self.side, command=self.render)
            b.pack(side='left', padx=(2, 0))
            self.side_btn[s] = b
        # the clones' convention: mana / life are tuned with Battle Orders cast
        self.bo = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text=T('mock.bocast', 'BO cast'), variable=self.bo, command=self.render).pack(
            side='left', padx=(6, 0))
        self.tree = ttk.Treeview(f, columns=('value',), show='tree', height=12, selectmode='browse')
        self.tree.column('#0', width=175, stretch=False)
        self.tree.column('value', width=220, stretch=True)
        self.tree.grid(row=1, column=0, sticky='nsew')
        sb = ttk.Scrollbar(f, orient='vertical', command=self.tree.yview)
        sb.grid(row=1, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=sb.set)
        for st, col in COLORS.items():
            if col:
                self.tree.tag_configure(st, foreground=col)
        self.tree.tag_configure('section', font=('TkDefaultFont', 9, 'bold'))

    def show(self, model, role=None, extra=None, side=None):
        """model: mxl_mock model; extra(side, bo) -> [(section, label, text, status)] shown first (the analyzer's
        checks)."""
        self.model, self.role, self.extra = model, role, extra
        if side:
            self.side.set(side)
        act = 'B' if model and model.get('active_weapon') else 'A'
        for s, b in self.side_btn.items():
            b.configure(text=SIDE_LABEL[s] + (' *' if s == act else ''))
        self.render()

    def rows(self):
        if self.model is None:
            return []
        side, bo = self.side.get(), self.bo.get()
        out = list(self.extra(side, bo)) if self.extra else []
        return out + M.summary_rows(self.model, side, bo=bo, role=self.role)

    def render(self):
        t = self.tree
        t.delete(*t.get_children())
        rows = self.rows()
        heads = {}
        for sec in SECTION_ORDER + tuple(r[0] for r in rows):
            if sec in heads or not any(r[0] == sec for r in rows):
                continue
            n = sum(1 for r in rows if r[0] == sec)
            heads[sec] = t.insert('', 'end', text=T(f'mock.sec.{sec}', sec), values=(f'{n}',), open=True,
                                  tags=('section',))
        for r in rows:
            sec, label, text, st = r[:4]
            mark = {M.GOOD: '✔ ', M.WARN: '! ', M.BAD: '✖ '}.get(st, '  ')
            i = t.insert(heads[sec], 'end', text=mark + label, values=(text,), tags=(st,))
            for g, names in (r[4] if len(r) > 4 else ()):      # every active source, by item (folded)
                t.insert(i, 'end', text='   ' + g, values=(names,))
        if self.on_change:
            self.on_change(self.side.get(), self.bo.get())
        return rows


class MockPage:
    """The Mock tab: Generator | Analyzer (a notebook of its own: fits 800 x 600)."""

    def __init__(self, app, host):
        self.app, self.host = app, host
        self.last = None
        self.defense_targets = None
        if getattr(app, 'data', None) is not None:
            M.set_data(app.data)                    # the skills tables of the selected game (aura damage)
        try:
            host.title(TAB)
        except Exception:
            pass
        nb = self.nb = ttk.Notebook(host)
        nb.pack(fill='both', expand=True, padx=2, pady=2)
        g, a = (ttk.Frame(nb, padding=2) for _ in range(2))
        nb.add(g, text=T('mock.gen', 'Generator'))
        nb.add(a, text=T('mock.ana', 'Analyzer'))
        self._analyzer(a)
        self._generator(g)
        host.bind('<Map>', lambda e: self.analyze() if e.widget is host else None, add='+')

    # ------------------------------------------------------------------ generator
    def _generator(self, f):
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        pw = ttk.PanedWindow(f, orient='horizontal')
        pw.grid(row=0, column=0, sticky='nsew')
        left = ttk.Frame(pw)
        right = ttk.Frame(pw)
        pw.add(left, weight=1)
        pw.add(right, weight=1)
        left.columnconfigure(1, weight=1)
        left.rowconfigure(6, weight=1)
        self.labels = {M.PRESETS[k]['label']: k for k in M.PRESET_ORDER}
        self.preset = tk.StringVar(value=M.PRESETS['mock_high']['label'])
        self.name = tk.StringVar(value='MockHigh')
        ttk.Label(left, text=T('mock.preset', 'Preset')).grid(row=0, column=0, sticky='w')
        cb = ttk.Combobox(left, textvariable=self.preset, values=list(self.labels), state='readonly', width=16)
        cb.grid(row=0, column=1, sticky='ew', pady=1)
        cb.bind('<<ComboboxSelected>>', lambda e: self._preset_changed())
        ttk.Label(left, text=T('mock.name', 'Name')).grid(row=1, column=0, sticky='w')
        ttk.Entry(left, textvariable=self.name, width=16).grid(row=1, column=1, sticky='ew', pady=1)
        self.gen_btn = ttk.Button(left, text=T('mock.generate', 'Generate'), command=self.generate)
        self.gen_btn.grid(row=0, column=2, rowspan=2, sticky='nsew', padx=(4, 0), ipadx=10, ipady=4)
        self.calc_btn = ttk.Button(left, text=T('mock.calc_all', 'Calc all'), command=self.calc)
        self.calc_btn.grid(row=2, column=2, sticky='ew', padx=(4, 0))
        # read-only: the game cannot save the clone (gaining xp at level 127 resets it to 99); the editor keeps
        # the flag when it saves
        bar = ttk.Frame(left)
        bar.grid(row=2, column=0, columnspan=2, sticky='ew')
        self.read_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text=T('mock.readonly', 'Read-only'), variable=self.read_only).pack(side='left')
        _Tip(bar.winfo_children()[0], T('mock.h.readonly', 'keeps level 127: the game cannot save the clone'))
        ttk.Button(bar, text=T('mock.check', 'Check'), command=self.check).pack(side='right')
        ttk.Button(bar, text=T('mock.reset2', 'Reset'), command=self.reset_fields).pack(side='right', padx=(0, 2))
        self.note = ttk.Label(left, text='', wraplength=360, justify='left')
        self.note.grid(row=3, column=0, columnspan=3, sticky='w')
        self.status = ttk.Label(left, text='', wraplength=360, justify='left')
        self.status.grid(row=4, column=0, columnspan=3, sticky='w')
        from mxl_char import watch_name

        name_hint = ttk.Label(left, foreground=COLORS[M.BAD], wraplength=280)
        name_hint.grid(row=5, column=0, columnspan=3, sticky='w')
        watch_name(self.name, lambda text: name_hint.configure(text=text))
        # the two text lines wrap at the pane's width (800 x 600: about 280 px)
        left.bind('<Configure>', lambda e: [w.configure(wraplength=max(150, e.width - 8))
                                            for w in (self.note, self.status, name_hint)], add='+')
        # the fields: one tab per group (tabs on the left side), each a scroll area
        st = ttk.Style(left)
        try:
            st.configure('Mock.TNotebook', tabposition='wn')
        except tk.TclError:
            pass
        gnb = self.groups = ttk.Notebook(left, style='Mock.TNotebook')
        gnb.grid(row=6, column=0, columnspan=3, sticky='nsew', pady=(2, 0))
        self.ov, self.pre, self.err, self.src = {}, {}, {}, {}
        self.touched, self._filling = set(), False        # the fields the user changed (the rest stay solved)
        self.field_tab, self.dyn_choice = {}, {}
        bg = _bg(left)
        for gi, (group, fields) in enumerate(M.FIELDS):
            sc = mxl_scroll.Scrolled(gnb, bg=bg, horizontal=False)
            gnb.add(sc, text=T(f'mock.g{gi}', group))
            box = ttk.Frame(sc.inner, padding=2)
            box.pack(fill='both', expand=True)
            box.columnconfigure(2, weight=1)
            if group in M.CALC_GROUPS:                          # Calc: this group's solver fills its boxes
                cb = ttk.Button(box, text=T('mock.calc', 'Calc'), width=6,
                                command=lambda g=group: self.calc(g))
                cb.grid(row=len(fields), column=0, sticky='w', pady=(4, 0))
                _Tip(cb, T('mock.calc.tip', 'Solve this group the most efficient way and put the values in the boxes '
                                           '(they then count as your values)'))
            for i, (k, lab, kind, extra) in enumerate(fields):
                hint = T(f'mock.h.{k}', M.HINTS.get(k, ''))
                if kind == 'bool':
                    v = tk.BooleanVar()
                    w = ttk.Checkbutton(box, text=T(f'mock.f.{k}', lab), variable=v)
                    w.grid(row=i, column=0, columnspan=2, sticky='w', pady=1)
                else:
                    ttk.Label(box, text=T(f'mock.f.{k}', lab)).grid(row=i, column=0, sticky='w')
                    v = tk.StringVar()
                    if kind == 'choice':
                        vals = extra(data=getattr(self.app, 'data', None)) if callable(extra) else extra
                        w = ttk.Combobox(box, textvariable=v, values=list(vals), state='readonly',
                                         width=22 if callable(extra) else 9)
                        if callable(extra):                 # e.g. the shield bases: per class, from the tables
                            self.dyn_choice[k] = (w, extra)
                    else:
                        w = ttk.Spinbox(box, textvariable=v, from_=extra[0], to=extra[1], increment=1, width=9)
                    w.grid(row=i, column=1, sticky='w', pady=1, padx=(2, 2))
                _Tip(w, hint)
                e = ttk.Label(box, text='', foreground=COLORS[M.BAD], wraplength=170, justify='left')
                e.grid(row=i, column=2, sticky='w')
                self.ov[k], self.err[k] = v, e
                self.field_tab[k] = gi
                v.trace_add('write', lambda *_a, k=k: self._touch(k))
                if kind != 'bool':                  # Enter / leaving the field re-solves the untouched fields at once
                    w.bind('<Return>', lambda _e: self._live(0), add='+')
                    w.bind('<FocusOut>', lambda _e: self._live(0), add='+')
        self.summary = SummaryPanel(right, title=T('mock.sum.plan', 'Summary of the plan'))
        self.summary.frame.pack(fill='both', expand=True)
        self._preset_changed()

    def key(self):
        return self.labels.get(self.preset.get(), 'mock_high')

    def _preset_changed(self):
        p = M.PRESETS[self.key()]
        self.note.configure(text=p.get('note', ''))
        cur = self.name.get()
        if not cur or cur == getattr(self, '_auto_name', None) or cur == 'MockHigh':
            self._auto_name = ''.join(c for c in p['label'] if c.isalpha())[:15]     # the preset's name
            self.name.set(self._auto_name)
        self.reset_fields()

    def _touch(self, k):
        if not self._filling:
            self.touched.add(k)
            self._live(700)                                 # a short debounce, then the solved fields follow
        if k == 'cls' and self.dyn_choice:                  # the shields that class may use
            c = self.ov['cls'].get()
            cls = M.CLASSES.index(c) if c in M.CLASSES else 1
            for w, fn in self.dyn_choice.values():
                try:
                    w.configure(values=list(fn(cls, data=getattr(self.app, 'data', None))))
                except tk.TclError:
                    pass

    def calc(self, group=None):
        """Calc / Calc all: the solved values of a group (or every group) replace the boxes; they become the
        user's values (touched) and stay."""
        try:
            vals = (M.calc_group(self.key(), group, self.form(), self.pre) if group
                    else M.calc_all(self.key(), self.form(), self.pre))
        except M.PlanError as e:
            self._show_errors({getattr(e, 'key', None) or '': str(e)})
            return
        self._fill(vals, [k for k in vals if k in self.ov])
        self.touched.update(k for k in vals if k in self.ov)
        self.check()

    def _live(self, ms):
        """Re-check (re-solving Meditation, Oak, regen ... that the user did not touch) after a pause."""
        job = getattr(self, '_live_job', None)
        if job:
            try:
                self.host.after_cancel(job)
            except Exception:
                pass
            self._live_job = None
        if self._filling:
            return
        self._live_job = self.host.after(ms, self._live_run) if ms else None
        if not ms:
            self._live_run()

    def _live_run(self):
        self._live_job = None
        if self.touched and not self._filling:
            self.check()

    def _fill(self, values, keys):
        self._filling = True
        try:
            for key in keys:
                v = self.ov[key]
                v.set(values[key] if isinstance(v, tk.BooleanVar) else str(values[key]))
        finally:
            self._filling = False

    def reset_fields(self):
        """Every field back to the preset's values (then a Check)."""
        try:
            self.pre = M.prefill(self.key())
        except M.PlanError as e:
            self._show_errors({'': str(e)})
            return
        self.touched.clear()
        self._fill(self.pre, self.ov)
        self.check()

    def form(self):
        """The fields the user changed (the others are solved by the plan and repainted after a Check)."""
        return {k: v.get() for k, v in self.ov.items() if k in self.touched}

    def _show_errors(self, errs):
        for k, e in self.err.items():
            e.configure(text=errs.get(k, ''))
        if errs:
            k = next(iter(errs))
            if k in self.field_tab:                         # the first problem's group comes to the front
                try:
                    self.groups.select(self.field_tab[k])
                except tk.TclError:
                    pass
            lab = next((f[1] for _, fs in M.FIELDS for f in fs if f[0] == k), '')
            self.status.configure(text=(f'{lab}: ' if lab else '') + errs[k], foreground=COLORS[M.BAD])

    def check(self):
        """The plan of the fields as they are: problems next to their fields, the summary on the right (not
        recomputed on every key stroke)."""
        over, raw, P, errs = M.validate(self.key(), self.form(), self.pre)
        self._show_errors(errs)
        self.defense_targets = M.defense_targets(P) if P is not None else None
        if errs:
            return None
        self.over = over
        if over:                    # the solved fields follow the edits (Meditation / Oak after a mana change ...)
            try:
                self._fill(M.prefill(self.key(), **over), [k for k in self.ov if k not in self.touched])
            except M.PlanError:
                pass
        for k, n in M.sources_of(P).items():               # the source count next to each aura field
            if not self.err[k].cget('text'):
                self.err[k].configure(text=T('mock.src', '{n} source(s)', n=n), foreground='')
        self.status.configure(text=M.plan_line(P, raw), foreground='')
        side = 'A' if not P.get('side_b') else self.summary.side.get()
        self.summary.show(M.model_from_plan(P, raw), M.PRESET_ROLE[self.key()], side=side)
        return raw, P

    def overrides(self):
        return M.edited(self.form(), self.pre)

    def generate(self):
        """Write a new save under an unused name."""
        from mxl_char import confirm_save_name

        name = self.name.get()
        if not confirm_save_name(self.host, name):
            return None
        r = self.check()
        if r is None:
            return None
        key = self.key()
        try:
            raw, P = M.generate(key, name, allow_invalid_name=True, **self.over)
            folder = getattr(self.app, 'save_dir', None) or os.environ.get('MXL_SAVE_DIR')
            if not folder:
                raise M.PlanError(T('mock.err.folder', 'No save folder.'))
            path = M.write_new(raw, folder, name, read_only=self.read_only.get(), allow_invalid_name=True)
        except (M.PlanError, OSError) as e:
            self._show_errors({'': str(e)})
            return None
        self.last = path
        self.defense_targets = M.defense_targets(P)
        self.status.configure(text=T('mock.written', 'Written: {file}', file=os.path.basename(path)) + '  '
                              + M.plan_line(P, raw), foreground=COLORS[M.GOOD])
        self.summary.show(M.model_from_plan(P, raw), M.PRESET_ROLE[key])
        try:
            self.app.select_character(os.path.splitext(os.path.basename(path))[0], self.app.view.get())
        except Exception as e:
            print('mock: new character not selected:', e)
        self.analyze()
        return path

    # ------------------------------------------------------------------ analyzer
    def _analyzer(self, f):
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky='ew')
        ttk.Button(top, text=T('mock.analyze', 'Analyze'), command=self.analyze).pack(side='left')
        self.role = tk.StringVar(value='mock')
        ttk.Label(top, text=T('mock.role', 'Compare with')).pack(side='left', padx=(6, 2))
        rb = ttk.Combobox(top, textvariable=self.role, values=list(M.CLONE_PROFILE), state='readonly', width=6)
        rb.pack(side='left')
        rb.bind('<<ComboboxSelected>>', lambda e: self.analyze(keep_side=True))
        self.who = ttk.Label(top, text='')
        self.who.pack(side='left', padx=4)
        self.target_note = ttk.Label(top, text='')
        self.target_note.pack(side='right', padx=4)
        self.ana = SummaryPanel(f, title=T('mock.sum.char', 'Loaded character'))
        self.ana.frame.grid(row=1, column=0, sticky='nsew')
        self.tree = self.ana.tree

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
        try:
            path, ch = self._character()
        except Exception as e:
            self.who.configure(text=f'{type(e).__name__}: {e}')
            return None
        if ch is None:
            self.who.configure(text=T('mock.nochar', 'no character loaded'))
            return None
        m = M.model_from_character(ch)
        side = self.ana.side.get() if keep_side else M.sides(m)[0]
        self.who.configure(text=f'{ch.name} ({os.path.basename(path)})')
        self.target_note.configure(
            text=T('mock.target.generator', 'Targets from Generator') if self.defense_targets is not None else '')

        def checks(sd, bo):
            a = M.analyze(m, sd, bo=bo, targets=self.defense_targets)
            self.report = a
            return [('Defense targets' if key.startswith('target_') else 'Checks', lab, txt, st)
                    for key, lab, txt, st in a['checks']]

        self.ana.show(m, self.role.get(), extra=checks, side=side)
        return self.report
