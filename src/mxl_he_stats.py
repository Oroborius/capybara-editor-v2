"""Hero Editor v1.04-style flat stat table for the item selected in the main window.

The collector's own editing only offers value sliders for the stats with in-game variance (the detail panel's
"Edition" section, values clamped by the affix ranges), and "Edit item" opens the whole Item Creator. This window
is the flat Hero Editor way instead, in the Hero Editor's own grey look:

- one row per stored stat: its label (the game's own stat text, plus a `[stat #id, bits]` reference), the value
  typed in a plain number box, and a x button to delete the row;
- "Stat to add": Hero-Editor-like picker - a filter box and the list of every stat the save format holds
  (browse, click, type the value and the param, "Add this stat");
- "Save changes" writes changed values in place through mxl_save.apply_edits - one file write, verification,
  .bak backup, the game may stay open; linked stats (the groups the game keeps together, like enhanced damage
  base + average) are written with the collector's own set_stat logic, so the links stay consistent;
- an added or deleted row rewrites the item's bytes through a lossless decode -> encode round trip (verified
  byte-identical on all the items of a real stash) via mxl_save.edit_stash, at the item's own place - its
  socketed items follow; the main window is reloaded then, as offsets shift;
- the value can be anything the save format stores (ItemStatCost save bits / add): the game's affix ranges are
  ignored on purpose (unrestricted build). A value the format cannot store is refused, never written;
- a stat stored by an auto-affix tier can only take one of its possible tier values (the game's own format);
  the status bar says so when it is refused;
- stash items only for now (equipment / inventory items are written through the character file: open them in
  the Item Creator).

Everything goes through the collector's own safe writers (verification, backups), never direct file writes.
"""
import os

import tkinter as tk
import tkinter.ttk as ttk

import settings
import mxl_save
from mxl_save import edit_stash, apply_edits, EditError
from mxl_format import FormatError
from mxl_rules import stat_hidden
from mxl_lang import T
from mxl_creator import decode_blob, build_blob
from mxl_statnames import stat_text, param_kind, decode_param, encode_param, skill_names_sorted, CHANCE_TO_CAST


def he(key, default, **fields):
    """The window's own strings: keys 'he.stats.*' (the character window has plain 'he.*' keys already)."""
    return T('he.stats.' + key, default, **fields)


# Hero Editor look (same palette as the character window's light/dark modes)
HE_BG = '#f0f0f0'
HE_BTN = '#e1e1e1'
HE_GOLD = '#d8c27a'
HE_FONT = ('Times New Roman', 11)
HE_FONT_I = ('Times New Roman', 11, 'italic')
HE_FONT_S = ('Times New Roman', 10)
HE_FONT_B = ('Times New Roman', 13, 'bold')


def _theme(dark=False):
    """The character window's own light / dark palette; Hero Editor grey when it cannot be imported."""
    try:
        from mxl_char_gui import THEMES
        return THEMES[bool(dark)]
    except Exception:
        return (dict(bg='#f0f0f0', fg='#000000', entry='#ffffff', entry_fg='#000000', btn='#e1e1e1',
                     frame_fg='#000000', pane='#ffffff', pane_fg='#000000')
                if not dark else
                dict(bg='#1e1e1e', fg='#d6d6d6', entry='#2b2b2b', entry_fg='#ececec', btn='#3a3a3a',
                     frame_fg='#d8c27a', pane='#252526', pane_fg='#e0e0e0'))


def _stat_info(data, sid):
    try:
        c = data.isc[sid]
    except (IndexError, KeyError, TypeError):
        return None
    return {'bits': c.get('bits') or 0, 'param': c.get('param') or 0, 'desc': c.get('desc')}


def _row_label(data, s):
    """Label of one stored stat entry: the game text when the game shows that stat itself, '(stat #N)' for the
    internal ones (and for the mod's own 'FLYING POLAR BUFFALO' placeholder strings). Clean Hero-Editor
    labels: no stat ids, bit counts or param numbers (those go to the status bar when a row is clicked)."""
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
        txt = stat_text(data, sid, param, value=1, desc=c.get('desc'))
    if not txt:
        import mxl_statnames_ext
        txt = mxl_statnames_ext.fallback_label(sid)
    name = f'(stat #{sid})' if not txt else txt
    if param_kind(sid) in ('skill', 'skill_only', 'class'):
        parts = decode_param(data, sid, param)      # the skill's name is usually already in the game text
        if parts and (not txt or not str(parts[0]).lower() in name.lower()):
            name += f'  [{parts[0]}]'
    return name


def _row_info_text(data, s):
    """The technical line for the status bar when a stat row is clicked: stat id, param, save bits, value."""
    sid, param = s['id'], s.get('param')
    c = _stat_info(data, sid)
    bits = (c or {}).get('bits') or 0
    par = f', param {param}' if param is not None else ''
    return f'stat #{sid}{par}, {bits} bits, value {s.get("value")}'


class ItemStatsWindow:
    """The flat stat table (Toplevel) of one item of the stash grid of the main window, Hero Editor styled."""

    def __init__(self, app, it=None, chwin=None, entry=None):
        self.app = app
        self.chwin, self.entry = chwin, entry
        self.it = dict(it if it is not None else entry.it)
        self.cr = None
        self.dark = tk.BooleanVar(value=bool(settings.get('he_stats_dark')))
        self._bak = None
        self.selected_row = None
        self._row_params = {}

        self.top = tk.Toplevel()
        self.top.title(he('title', 'Item stats') + '  -  ' + self._name())
        top = self.top
        self._theme_d = self.dark.get()
        t = self._t = _theme(self._theme_d)
        top.configure(bg=t['bg'])
        try:
            top.geometry('+%d+%d' % (max(0, self.app.root.winfo_x() + 60),
                                     max(0, self.app.root.winfo_y() + 60)))
        except Exception:
            pass
        top.after_idle(lambda: clamp_window(top, size=(760, 640)))

        head = tk.Frame(top, bg=t['bg'])
        head.pack(fill='x', padx=8, pady=(6, 2))
        tk.Label(head, text=he('title', 'Item stats'), font=HE_FONT_B, bg=t['bg'], fg=t['frame_fg']).pack(side='left')
        tk.Label(head, text=self._name(), font=HE_FONT_I, bg=t['bg'], fg=t['fg']).pack(side='left', padx=8)
        tk.Checkbutton(head, text=he('dark', 'Dark mode'), variable=self.dark, command=self.apply_theme,
                       font=HE_FONT, bg=t['bg'], fg=t['fg'], activebackground=t['bg'],
                       activeforeground=t['fg'], highlightthickness=0, bd=0).pack(side='right')

        body = tk.Frame(top, bg=t['bg'])
        body.pack(fill='both', expand=True)
        canvas = tk.Canvas(body, highlightthickness=0, bg=t['bg'])
        sb = tk.Scrollbar(body, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        self.inner = tk.Frame(canvas, bg=t['bg'])
        canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        canvas.bind('<Button-4>', lambda e: canvas.yview_scroll(-1, 'units'))
        canvas.bind('<Button-5>', lambda e: canvas.yview_scroll(1, 'units'))
        self.canvas = canvas

        foot = tk.Frame(top, bg=t['bg'])
        foot.pack(fill='x', side='bottom')
        self.bar = tk.Label(foot, text='', font=HE_FONT, bg='#000000', fg=HE_GOLD, anchor='w')
        self.bar.pack(side='left', fill='x', expand=True, padx=4, pady=(2, 4))
        for txt, cmd, side in ((he('close', 'Close'), top.destroy, 'right'),
                               (he('save', 'Save changes'), self.save, 'right')):
            tk.Button(foot, text=txt, font=HE_FONT, command=cmd, bg=HE_BTN, fg=t['fg'],
                      activebackground=HE_BTN, activeforeground=t['fg'], width=12, bd=2, relief='raised'
                      ).pack(side=side, padx=4, pady=4)

        self.load_rows()
        self.apply_theme(save=False)
        self.top.protocol('WM_DELETE_WINDOW', self.top.destroy)

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
        the character's entry for one of its items."""
        if self.entry is not None:
            blob = self.entry.blob
        else:
            buf = open(self.app.path, 'rb').read()
            blob = mxl_save.item_blob(buf, self.it)
        self.rec, self.kids = decode_blob(blob, self.app.data)
        for node in list(self.inner.winfo_children()):
            node.destroy()
        self.lists = []                       # [(stat_list, [(entry as read, StringVar of the value, row label)])]
        self._row_params = {}
        t = self._t
        if self.rec.get('stats_runeword'):
            self._section(he('rw_stats', "The runeword's stats"), 'stats_runeword')
        self._section(he('own_stats', "The item's stats"), 'stats')
        self._original = {lst: [v.get() for _s, v, _l in rows] for lst, rows in self.lists}
        self.selected_row = None
        self._stat_picker(he('stat_to_add', 'Stat to add'))
        self.canvas.yview_moveto(0)

    def _section(self, text, stat_list):
        t = self._t
        sec = tk.LabelFrame(self.inner, text=text, font=HE_FONT_I, bg=t['bg'], fg=t['frame_fg'],
                            bd=2, relief='groove')
        sec.pack(fill='x', padx=8, pady=(6, 2))
        grid = tk.Frame(sec, bg=t['bg'])
        grid.pack(fill='x', padx=4, pady=2)
        entries = list(self.rec.get(stat_list) or [])
        rows = []
        for r, s in enumerate(entries):
            kind = param_kind(s['id'])
            lab = tk.Label(grid, text=_row_label(self.app.data, s), font=HE_FONT, bg=t['bg'], fg=t['fg'], anchor='w')
            lab.grid(row=r, column=0, sticky='we', padx=(2, 6), pady=1)
            lab._row_sel = (stat_list, r)
            lab.bind('<Button-1>', self._click_row)
            var = tk.StringVar(value=str(s['value']))
            e = tk.Entry(grid, textvariable=var, width=(9 if kind else 12), font=HE_FONT, relief='sunken', bd=2,
                         bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg'], justify='center')
            e.grid(row=r, column=1, pady=1)
            e._row_sel = (stat_list, r)
            e.bind('<Return>', self.save)
            e.bind('<Button-1>', self._click_row)
            if kind:                     # a skill / class in the param: a dropdown to change it
                self._row_skill_widgets(grid, r, s, stat_list, kind)
                bcol = 5 if kind == 'skill' else 3
            else:
                bcol = 2
            b = tk.Button(grid, text='x', font=HE_FONT_S,
                          command=lambda sl=stat_list, r=r: self.delete_row(sl, r), bg=HE_BTN, fg=t['fg'],
                          activebackground=HE_BTN, activeforeground=t['fg'], width=2, bd=1, relief='raised',
                          cursor='hand2')
            b.grid(row=r, column=bcol, padx=(4, 2), pady=1)
            rows.append((s, var, lab))
        if not entries:
            tk.Label(grid, text=he('none', '(no stat stored in this list)'), font=HE_FONT_I, bg=t['bg'],
                     fg=t['fg'], anchor='w').grid(row=0, column=0, sticky='w')
        self.lists.append((stat_list, rows))

    def _row_skill_widgets(self, grid, r, s, stat_list, kind):
        """A chance-to-cast / "+to skill" / class-skill row's dropdown (+ cast level): changing it rewrites
        the item at once (the param carries the skill, the number box beside it is the chance itself)."""
        from mxl_rules import CLASSES
        t = self._t
        self._row_params[(stat_list, r)] = dict(s=s)
        parts = decode_param(self.app.data, s['id'], s.get('param'))
        names = [n for n, _k in self._skill_names] if kind != 'class' else list(CLASSES)
        pvar = tk.StringVar(value=str((parts or ('',))[0]))
        self._row_params[(stat_list, r)]['name'] = pvar
        cb = ttk.Combobox(grid, textvariable=pvar, values=names, width=20, state='readonly')
        cb.grid(row=r, column=2, sticky='w', padx=(4, 0))
        cb.bind('<<ComboboxSelected>>', lambda _e, sl=stat_list, r0=r: self._row_param_commit(sl, r0))
        if kind == 'skill':
            tk.Label(grid, text=he('level_of', 'level'), font=HE_FONT_S, bg=t['bg'], fg=t['fg']).grid(
                row=r, column=3, sticky='e', padx=(4, 2))
            lvar = tk.StringVar(value=str((parts or ('', 1))[1] if parts and parts[1] is not None else 1))
            self._row_params[(stat_list, r)]['level'] = lvar
            le = tk.Entry(grid, textvariable=lvar, width=3, font=HE_FONT, relief='sunken', bd=2,
                          bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg'], justify='center')
            le.grid(row=r, column=4, sticky='w', padx=(2, 0))
            le._row_sel = (stat_list, r)
            le.bind('<Return>', lambda _e, sl=stat_list, r0=r: self._row_param_commit(sl, r0))
            self._paint_selection()

    def _row_param_commit(self, stat_list, r):
        info = self._row_params.get((stat_list, r))
        if not info:
            return
        s = info['s']
        kind = param_kind(s['id'])
        name = str(info['name'].get()).strip()
        lvl = None
        if kind == 'skill':
            try:
                lvl = int(info['level'].get())
            except (ValueError, KeyError):
                lvl = None
        newp = encode_param(self.app.data, s['id'], name, lvl if lvl is not None else 1)
        if newp is None:
            self._say(he('err.param', 'unknown {what}: {name}', name=name,
                         what=('class' if kind == 'class' else 'skill')), error=True)
            return
        if newp == s.get('param'):
            return
        s['param'] = newp
        if self._write():
            self.refresh_after_write()
            self.load_rows()
            self._say(he('skillset', '{label}', label=_row_label(self.app.data, s)))
        else:
            self.load_rows()

    def _stat_picker(self, text):
        """Hero-Editor-style stat picker: a filter box and a list of all the stats the save format holds."""
        t = self._t
        sec = tk.LabelFrame(self.inner, text=text, font=HE_FONT_I, bg=t['bg'], fg=t['frame_fg'],
                            bd=2, relief='groove')
        sec.pack(fill='x', padx=8, pady=(6, 6))
        self._choices = self._creator().stat_choices()          # [(sid, label)]
        self._choice_low = [(sid, label, label.lower()) for sid, label in self._choices]
        self.add_target = tk.StringVar(value=('stats_runeword' if self.rec.get('stats_runeword')
                                             else 'stats'))
        self._skill_names = skill_names_sorted(self.app.data)
        if self.rec.get('stats_runeword'):
            tgt = tk.Frame(sec, bg=t['bg'])
            tgt.pack(fill='x', padx=4, pady=(2, 0))
            tk.Label(tgt, text=he('add_into', 'Add into:'), font=HE_FONT, bg=t['bg'], fg=t['fg']).pack(side='left')
            tk.Radiobutton(tgt, text=he('into_item', 'the item'), value='stats', variable=self.add_target,
                           font=HE_FONT_S, bg=t['bg'], fg=t['fg'], activebackground=t['bg'],
                           activeforeground=t['fg'], highlightthickness=0, bd=0).pack(side='left')
            tk.Radiobutton(tgt, text=he('into_rw', "the runeword"), value='stats_runeword',
                           variable=self.add_target, font=HE_FONT_S, bg=t['bg'], fg=t['fg'],
                           activebackground=t['bg'], activeforeground=t['fg'],
                           highlightthickness=0, bd=0).pack(side='left')
        row1 = tk.Frame(sec, bg=t['bg'])
        row1.pack(fill='x', padx=4, pady=2)
        tk.Label(row1, text=he('filter', 'Filter:'), font=HE_FONT, bg=t['bg'], fg=t['fg']).pack(side='left')
        self.filter_var = tk.StringVar()
        f = tk.Entry(row1, textvariable=self.filter_var, width=24, font=HE_FONT, relief='sunken', bd=2,
                     bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg'])
        f.pack(side='left', padx=6)
        f.bind('<KeyRelease>', self._fill_list)
        self._param_row = tk.Frame(row1, bg=t['bg'])
        self._param_row.pack(side='left', padx=(8, 0))
        self.add_param = tk.StringVar(value='0')
        self._build_param_zone()
        tk.Button(row1, text=he('btn_add', 'Add this stat'), font=HE_FONT, command=self.add_row,
                  bg=HE_BTN, fg=t['fg'], activebackground=HE_BTN, activeforeground=t['fg'], width=13,
                  bd=2, relief='raised').pack(side='right', padx=2)
        tk.Button(row1, text=he('btn_replace', 'Replace selected row'), font=HE_FONT, command=self.replace_row,
                  bg=HE_BTN, fg=t['fg'], activebackground=HE_BTN, activeforeground=t['fg'], width=17,
                  bd=2, relief='raised').pack(side='right', padx=2)
        wrap = tk.Frame(sec, bg=t['entry'], bd=2, relief='sunken')
        wrap.pack(fill='x', padx=4, pady=(0, 4))
        self.listbox = tk.Listbox(wrap, height=6, font=HE_FONT, bg=t['entry'], fg=t['entry_fg'],
                                  activestyle='dotbox', bd=0, highlightthickness=0, selectbackground=t['entry'],
                                  selectforeground=t['frame_fg'], exportselection=False)
        self.listbox.pack(fill='x', side='left', expand=True)
        lbsb = tk.Scrollbar(wrap, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=lbsb.set)
        lbsb.pack(side='right', fill='y')
        self.listbox.bind('<<ListboxSelect>>', self._pick)
        self.listbox.bind('<Double-Button-1>', lambda _e: self.add_row())
        self._fill_list()

    def _build_param_zone(self):
        """The param widgets of the picked stat: a skill dropdown (+ the cast level) for the chance-to-cast /
        '+to skill' / class-skill stats, a plain number box for the rest. Rebuilt on every pick."""
        try:
            self._param_row.winfo_children()      # destroyed together with the window: nothing to rebuild
        except (AttributeError, tk.TclError):
            return
        t = self._t
        for w in self._param_row.winfo_children():
            w.destroy()
        sid = self._picked_sid()
        kind = param_kind(sid) if sid is not None else None
        if kind in ('skill', 'skill_only'):
            names = [n for n, _k in self._skill_names]
        elif kind == 'class':
            from mxl_rules import CLASSES
            names = list(CLASSES)
        else:
            names = None
        if names is None:
            tk.Label(self._param_row, text=he('param_of_add', 'param'), font=HE_FONT, bg=t['bg'],
                     fg=t['fg']).pack(side='left')
            self.add_param = tk.StringVar(value=self.add_param.get() if hasattr(self, 'add_param') else '0')
            tk.Entry(self._param_row, textvariable=self.add_param, width=7, font=HE_FONT, relief='sunken',
                     bd=2, bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg']).pack(side='left', padx=4)
            return
        tk.Label(self._param_row, text=he('skill_of_add', 'skill'), font=HE_FONT, bg=t['bg'],
                 fg=t['fg']).pack(side='left')
        self.add_skill = tk.StringVar(value=names[0])
        cb = ttk.Combobox(self._param_row, textvariable=self.add_skill, values=names, width=20, state='readonly')
        cb.pack(side='left', padx=4)
        if kind == 'skill':
            tk.Label(self._param_row, text=he('level_of_add', 'level'), font=HE_FONT, bg=t['bg'],
                     fg=t['fg']).pack(side='left')
            self.add_level = tk.StringVar(value='1')
            tk.Entry(self._param_row, textvariable=self.add_level, width=4, font=HE_FONT, relief='sunken',
                     bd=2, bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg']).pack(side='left', padx=4)

    def _picked_sid(self):
        try:
            i = self.listbox.curselection()[0]
            return self._shown[i][0]
        except (IndexError, AttributeError, tk.TclError):
            return None

    def _param_to_write(self, sid):
        """The param going into the item for the picked stat, from the skill dropdown (+ level) or the
        number box. None: no param (plain stat, or no skill chosen)."""
        kind = param_kind(sid)
        if kind in ('skill', 'skill_only', 'class'):
            try:
                name = self.add_skill.get().strip()
            except (AttributeError, tk.TclError):
                return None
            if not name:
                return None
            lvl = None
            if kind == 'skill':
                try:
                    lvl = int(self.add_level.get())
                except (ValueError, AttributeError, tk.TclError):
                    lvl = 1
            return encode_param(self.app.data, sid, name, lvl)
        try:
            return int(self.add_param.get())
        except (ValueError, AttributeError):
            return None

    def _fill_list(self, *_event):
        pat = self.filter_var.get().strip().lower()
        self._shown = [(sid, label) for sid, label, low in self._choice_low if not pat or pat in low][:300]
        self.listbox.delete(0, 'end')
        for _sid, label in self._shown:
            self.listbox.insert('end', label)
        self.picked_label = ''

    def _pick(self, _e=None):
        try:
            i = self.listbox.curselection()[0]
            self.picked_label = self._shown[i][1]
        except (IndexError, AttributeError):
            self.picked_label = ''
        self._build_param_zone()

    def _click_row(self, ev):
        """Selects the row the user clicked (highlight; 'Replace the selected row' works on it). The status
        bar shows the row's technical numbers (stat id, param, save bits, value)."""
        key = getattr(ev.widget, '_row_sel', None)
        if key is None:
            return
        self.selected_row = key
        self._paint_selection()
        try:
            entries = list(self.rec.get(key[0]) or [])
            if 0 <= key[1] < len(entries):
                self._say(_row_info_text(self.app.data, entries[key[1]]))
        except (IndexError, KeyError, TypeError):
            pass
        if isinstance(ev.widget, tk.Entry):
            ev.widget.focus_set()

    def _paint_selection(self, *_e):
        t = self._t
        sel = getattr(self, 'selected_row', None)
        sel_bg = '#ffe792' if not self.dark.get() else '#5a5030'
        for sl, rows in self.lists:
            for i, (_s, var, lab) in enumerate(rows):
                try:
                    lab.configure(bg=sel_bg if sel == (sl, i) else t['bg'])
                except tk.TclError:
                    pass

    def replace_row(self, *_e):
        """The Hero-Editor 'replace attribute': the picked stat takes the place of the selected row's stat
        (the value of the row's number box is kept - type the new one in it before replacing)."""
        sid = self._picked_sid()
        if sid is None:
            self._say(he('err.pick', 'Pick a stat in the list first (double-click adds it).'), error=True)
            return
        sel = getattr(self, 'selected_row', None)
        if sel is None:
            self._say(he('err.row', 'Click a stat row of the item first: the picked stat replaces it.'), error=True)
            return
        stat_list, r = sel
        info = _stat_info(self.app.data, sid)
        if info is None or not info['bits']:
            self._say(he('err.no_bits', 'stat #{sid}: the save format has no storage for it', sid=sid), error=True)
            return
        param = self._param_to_write(sid)
        entries = list(self.rec.get(stat_list) or [])
        if not 0 <= r < len(entries):
            self._say(he('err.row', 'Click a stat row of the item first: the picked stat replaces it.'), error=True)
            return
        # the value of the row's number box, when it is a number
        rows = next((rows for sl, rows in self.lists if sl == stat_list), None)
        val = None
        if rows is not None and r < len(rows):
            try:
                val = int(rows[r][1].get())
            except (ValueError, IndexError):
                val = None
        txt = stat_text(self.app.data, sid, param, desc=info.get('desc'))
        if not txt and param in (None, 0):
            self._say(he('err.no_bits', 'stat #{sid}: the game shows nothing for this stat here', sid=sid), error=True)
            return
        entries[r] = dict(id=sid, param=(param or None), value=(entries[r]['value'] if val is None else val))
        self.rec[stat_list] = entries
        if self._write():
            self.refresh_after_write()
            self.load_rows()
            label = txt or f'stat #{sid}'
            self._say(he('replaced', 'row {n}: now {label}', label=label, n=r + 1))
        else:
            self.load_rows()

    def add_row(self, *_event):
        sid = self._picked_sid()
        if sid is None:
            self._say(he('err.pick', 'Pick a stat in the list first (double-click adds it).'), error=True)
            return
        info = _stat_info(self.app.data, sid)
        if info is None or not info['bits']:
            self._say(he('err.no_bits', 'stat #{sid}: the save format has no storage for it', sid=sid), error=True)
            return
        param = self._param_to_write(sid)
        stat_list = self.add_target.get()
        self.rec[stat_list] = (self.rec.get(stat_list) or []) + [dict(id=sid, param=(param or None), value=0)]
        if self._write():
            self.refresh_after_write()
            self.load_rows()
            self._say(he('added', '{label} added', label=(stat_text(self.app.data, sid, param, desc=info.get('desc'))
                                                          or f'stat #{sid}')))
        else:
            self.load_rows()

    def delete_row(self, stat_list, row):
        entries = list(self.rec.get(stat_list) or [])
        try:
            gone = entries[row]
        except IndexError:
            return
        del entries[row]
        self.rec[stat_list] = entries
        if self._write():
            self.refresh_after_write()
            self.load_rows()
            self._say(he('deleted', 'row deleted (stat #{sid})', sid=gone['id']))
        else:
            self.load_rows()

    # ------------------------------------------------------------ writes
    def save(self, *args):
        """Changed values of kept rows. A stash item: in place through apply_edits (one write). A character
        item: one re-encode of the item's bytes + the character's own save. Added / deleted rows were written
        already at their own change. A value the save format cannot hold is capped at its maximum (shown in
        the box); the write itself still refuses what the game's own stat logic will not allow."""
        cap_note = ''
        typed = []                            # [(stat_list, row dict) per changed row, percentages kept apart]
        for stat_list, rows in self.lists:
            for s, var, _l in rows:
                try:
                    v = int(var.get())
                except ValueError:
                    continue
                if v == s['value']:
                    continue
                info = _stat_info(self.app.data, s['id'])
                bits = (info or {}).get('bits') or 0
                if not bits:
                    continue                  # the save format has no storage for this stat's value
                if v >= (1 << bits):
                    v, cap_note = (1 << bits) - 1, he('capped', "a value over the stat's maximum was capped "
                                                                '(stat {n} to {m})', n=s['id'], m=(1 << bits) - 1)
                    var.set(str(v))
                elif v < 0:
                    v, cap_note = 0, he('capped', "a value below zero was capped (stat {n} to 0)", n=s['id'])
                    var.set('0')
                typed.append((stat_list, dict(id=s['id'], param=s.get('param'), value=v)))
        if self.entry is None:                # stash item: apply the value edits in place
            if not typed:
                self._say(cap_note or he('nothing', 'nothing to write'))
                return
            edits = [dict(offset=self.it['_offset'], code=self.it['code'], kind='stat', stat_list=stat_list,
                          stat=row['id'], param=row.get('param'), value=row['value'])
                     for stat_list, row in typed]
            try:
                bak = apply_edits(self.app.path, edits, self.app.data,
                                  backup=self.app.needs_backup(self.app.path), force=True)
            except Exception as e:            # EditError / FormatError / StoreError / OSError
                self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
                return
            self.refresh_after_write()
            self.load_rows()
            self._say(he('saved', 'written{bak}', bak=(f' - backup {os.path.basename(bak)}' if bak else ''))
                      + ((' - ' + cap_note) if cap_note else ''))
            return
        # character item: write the typed values into the record, then re-encode the item's bytes once
        for stat_list, row in typed:
            for s, var, _l in next(rows for sl, rows in self.lists if sl == stat_list):
                if s['id'] == row['id'] and s.get('param') == row.get('param'):
                    s['value'] = row['value']
        if not typed:
            self._say(cap_note or he('nothing', 'nothing to write'))
            return
        if self._write_char():
            self.refresh_after_write()
            self.load_rows()
            self._say(he('saved', 'written') + ((' - ' + cap_note) if cap_note else ''))


    def _write(self):
        """Stash item: re-encodes its bytes (a row was added or deleted) and replaces it at its own place
        through edit_stash (verification, backup; socketed items follow). False: refused, nothing written."""
        if self.entry is not None:
            return self._write_char()
        page, x, y = self.it.get('page', 0), self.it.get('x', 0), self.it.get('y', 0)
        blb = build_blob(self.rec, self.kids, self.app.data)
        try:
            bak = edit_stash(self.app.path, self.app.data, remove=[self.it['_offset']],
                             insert=[(page, x, y, blb)], backup=self.app.needs_backup(self.app.path))
            self._bak = bak
        except (EditError, FormatError, OSError) as e:
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        except Exception as e:
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        return True

    def _write_char(self):
        """Character item: re-encodes the item's bytes in the character's entry and saves the character
        through the character window (its own verification, backup and status line)."""
        from mxl_char import CharError
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
            self._say(he('err.save', 'not written (the character window shows the error)'), error=True)
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
        self.bar.configure(text=txt, fg='#ff9a9a' if error else HE_GOLD)

    # ------------------------------------------------------------ theme
    def apply_theme(self, save=True):
        """Robot-walk over the whole window like the character window does (light Hero Editor grey, or dark)."""
        if save:
            settings.put('he_stats_dark', bool(self.dark.get()))
        try:
            self.dark.get()
        except tk.TclError:
            return
        self._theme_d = bool(self.dark.get())
        t = self._t = _theme(self._theme_d)
        self.top.configure(bg=t['bg'])
        try:
            self.top.title(he('title', 'Item stats') + '  -  ' + self._name())
        except tk.TclError:
            return

        def walk(w):
            cls = w.winfo_class()
            bg = dict(Frame=t['bg'], Canvas=t['bg'], Label=t['bg'], Labelframe=t['bg'], Checkbutton=t['bg'],
                      Radiobutton=t['bg'], Scale=t['bg'], Listbox=t['entry'])
            fg = dict(Label=t['fg'], Labelframe=t['frame_fg'], Checkbutton=t['fg'], Radiobutton=t['fg'])
            if cls == 'Scrollbar':
                pass
            else:
                try:
                    w.configure(bg=bg.get(cls, t['bg']))
                except tk.TclError:
                    pass
                if cls in fg:
                    try:
                        w.configure(fg=fg[cls])
                    except tk.TclError:
                        pass
                if cls == 'Button':
                    try:
                        w.configure(bg=t['btn'], fg=t['fg'], activebackground=t['btn'],
                                    activeforeground=t['fg'], disabledforeground=t['fg'])
                    except tk.TclError:
                        pass
                elif cls == 'Entry':
                    try:
                        w.configure(bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg'],
                                    readonlybackground=t['entry'])
                    except tk.TclError:
                        pass
                elif cls == 'Listbox':
                    try:
                        w.configure(selectbackground=t['entry'], selectforeground=t['frame_fg'])
                    except tk.TclError:
                        pass
            for c in w.winfo_children():
                walk(c)

        walk(self.top)
        self._paint_selection()          # the selected row keeps its highlight over the plain bg
        self._say(self.bar['text'] if self.bar else '')


def open_item_stats(app):
    """The unified item editor (the creator's edit mode): one window shows and edits every attribute,
    with the skill dropdowns, raw values and delete buttons - the old separate flat stats table is gone."""
    from mxl_creator_gui import edit_selected
    edit_selected(app)


def open_char_item_stats(chwin, entry):
    """The unified item editor for an item of the character window (equipment, mercenary or inventory)."""
    if entry is None:
        return
    chwin.selected = entry
    chwin.edit()
