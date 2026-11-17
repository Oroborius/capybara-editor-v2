"""Advanced quest view: the Character window's "Quests+" page.

Per difficulty every one of the 48 quest words (layout: the table above mxl_char.ACTS) with its name, its raw
16-bit value, a reading of its state, and - for the selected word - the 16 bits as check boxes plus the actions
"Re-open", "Complete" and "File value". The NPC section is shown as read-only hex. Nothing is written until
SAVE: the page keeps pending values and apply() puts them into win.ch.

This page writes exactly the words the user changed: no reward points, no introduction / travel words, no
header progression (the plain Quests page does those). It is the one place where a quest state written by the
game can be changed, and only by an explicit click.

What the actions write, and why (samples: one character saved by the game at level 100 and twice at level 117):
  Re-open   0x0000 - every bit cleared. That is what a quest not yet begun looks like in the samples (e.g.
            Nightmare words 38-40 of the level-100 save, with act V already entered): the only "not done" state
            the game itself is known to accept as a starting point. Clearing only bit 0 / bit 12 would keep the
            quest-specific bits 5-11 (steps already taken, e.g. 13F5 -> 03F4), a state no sample shows.
  Complete  the word of the file when the file already holds a completed state (bit 0) - so Re-open followed by
            Complete gives back exactly what the game wrote - otherwise 0x1001 (bit 0 "completed" + bit 12
            "closed in the quest log"), the value the game holds for a plainly finished quest (words 1, 9, 17,
            20, 25, 27, 36 of the samples) and the one the Quests page writes.
  Introduction / travel words: Complete = 1, Re-open = 0 (the only two values the game shows there).
  Word 41: Complete = 0x8002 (what every difficulty the character entered holds), Re-open = 0 (a difficulty
            never entered). Its meaning is unproven (vanilla: stat / skill reset state).
"""
import struct
import tkinter as tk
from tkinter import ttk

import mxl_char as MC
from mxl_lang import T

QUEST_DONE = MC.QUEST_DONE
NPC_DATA = MC.NPC_OFF + 4               # '\\x01w' + u16 size, then 3 x u64 "introduced", 3 x u64 "congratulated"

# bit -> (short name, proven by the samples for Median XL?). The names are the vanilla 1.13 quest flags; only
# bit 0 is proven (every quest the game finished and rewarded has it). The samples agree with bits 1 / 13 / 15
# (2002 "goal done this game, reward pending" became 8022 in a later session) without proving them.
BITS = {0: ('completed, reward given', True), 1: ('reward pending', False), 2: ('quest given', False),
        3: ('left town', False), 4: ('entered quest area', False), 12: ('closed in quest log', False),
        13: ('goal done this game', False), 14: ('completed now', False), 15: ('completed before', False)}


def word_table():
    """[(group title, [(word, kind, text)])]: kind 'intro' / 'quest' / 'travel' / 'respec' / 'unused'; text is a
    string-table key for quests, a display text otherwise."""
    out = []
    acts = [a for a, _i, _q, _t in MC.ACTS]
    for n, (act, intro, quests, travel) in enumerate(MC.ACTS):
        rows = [(intro, 'intro', T('qp.intro', 'Introduction heard'))]
        rows += [(w, 'quest', key) for w, key in quests]
        if travel is not None:
            rows.append((travel, 'travel', T('qp.travel', 'Travelled to {act}', act=acts[n + 1])))
        out.append((act, rows))
    used = {w for _a, rows in out for w, _k, _t in rows}
    rest = []
    for w in range(48):
        if w in used:
            continue
        if w == MC.RESPEC_WORD:
            rest.append((w, 'respec', T('qp.word41', 'Word 41 (vanilla: stat / skill reset)')))
        else:
            rest.append((w, 'unused', T('qp.unused', 'unused')))
    out.append((T('qp.other', 'Other words'), rest))
    return out


def complete_value(kind, file_value):
    """What "Complete" writes for a word of this kind whose value in the file is file_value."""
    if kind == 'quest':
        return file_value if file_value & 1 else QUEST_DONE
    if kind == 'respec':
        return 0x8002
    if kind in ('intro', 'travel'):
        return 1
    return None                          # unused words: raw editing only


def reopen_value(kind):
    """What "Re-open" writes: the untouched state (all bits clear); None for unused words."""
    return None if kind == 'unused' else 0


def describe(kind, v):
    """One-line reading of a word's value."""
    if kind == 'unused':
        return '' if not v else T('qp.s.set', 'set (not used by the game?)')
    if kind in ('intro', 'travel'):
        return T('qp.s.yes', 'yes') if v == 1 else (T('qp.s.no', 'no') if not v else T('qp.s.odd', 'unusual value'))
    if kind == 'respec':
        return {0: T('qp.s.never', 'difficulty not entered'), 0x8002: T('qp.s.game', 'as the game writes it')}.get(
            v, T('qp.s.odd', 'unusual value'))
    if not v:
        return T('qp.s.new', 'not started')
    if v & 1:
        return T('qp.s.done', 'completed')
    if v & 2:
        return T('qp.s.pending', 'goal done, reward pending')
    return T('qp.s.progress', 'in progress')


class QuestPage:
    def __init__(self, win, frame):
        import mxl_char_gui as G
        self.G, self.win, self.frame = G, win, frame
        self.pend = {}                   # (difficulty, word) -> pending value
        self.diff = tk.IntVar(value=0)
        self.sel = None                  # selected word
        self.kind = {}
        self.rows = {}                   # word -> tree iid
        try:
            from mxl_creator_gui import clean
        except Exception:
            def clean(s):
                return s
        self.table = []
        for title, rows in word_table():
            named = []
            for w, kind, text in rows:
                if kind == 'quest':
                    try:
                        text = clean(win.data.key(text))
                    except Exception:
                        pass
                self.kind[w] = kind
                named.append((w, kind, text))
            self.table.append((title, named))
        self.names = {w: text for _t, rows in self.table for w, _k, text in rows}
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ widgets
    def _build(self):
        G, f = self.G, self.frame
        from tkinter import font as tkfont
        fs = tkfont.Font(font=G.HE_FONT_S)
        em = max(6, fs.measure('0'))
        top = tk.Frame(f)
        top.pack(fill='x', padx=2, pady=(2, 0))
        self.diff_buttons = []
        for k, name in enumerate(MC.DIFFICULTIES):
            rb = tk.Radiobutton(top, text=T('diff.' + name.lower(), name), value=k, variable=self.diff, indicatoron=0,
                                font=G.HE_FONT, bd=1, padx=8, pady=0, command=self.show)
            rb.pack(side='left')
            self.diff_buttons.append(rb)
        self.changed = tk.Label(top, text='', font=G.HE_FONT_S)
        self.changed.pack(side='left', padx=8)
        tk.Button(top, text=T('qp.revert_all', 'Undo all changes'), font=G.HE_FONT_S, pady=0, bd=1,
                  command=self.revert_all).pack(side='right')

        mid = tk.Frame(f)
        mid.pack(fill='both', expand=True, padx=2, pady=2)
        # -- right: the selected word
        det = tk.LabelFrame(mid, text=T('qp.word', 'Selected word'), font=G.HE_FONT_I, bd=2, relief='groove', padx=3, pady=1)
        det.pack(side='right', fill='y', padx=(2, 0))
        self.det = det
        self.title = tk.Label(det, text='', font=G.HE_FONT, anchor='w', justify='left', wraplength=36 * em)
        self.title.grid(row=0, column=0, columnspan=4, sticky='w')
        tk.Label(det, text=T('qp.value', 'Value (hex)'), font=G.HE_FONT_S).grid(row=1, column=0, sticky='w')
        self.hexvar = tk.StringVar()
        self.hex = tk.Entry(det, textvariable=self.hexvar, width=6, font=('Courier', 10), bd=1)
        self.hex.grid(row=1, column=1, sticky='w', padx=2)
        self.hex.bind('<Return>', self.on_hex)
        self.hex.bind('<FocusOut>', self.on_hex)
        self.fileval = tk.Label(det, text='', font=G.HE_FONT_S, anchor='w')
        self.fileval.grid(row=1, column=2, columnspan=2, sticky='w')
        self.bitvars, self.bitboxes = [], []
        for b in range(16):
            name, proven = BITS.get(b, (T('qp.bit.custom', 'quest specific'), False))
            if b in BITS:
                name = T('qp.bit.%d' % b, name)
            v = tk.IntVar()
            cb = tk.Checkbutton(det, text=f'{b:2d} {name}' + (' *' if proven else ''), variable=v, font=G.HE_FONT_S,
                                anchor='w', bd=0, pady=0, padx=0, highlightthickness=0,
                                command=lambda b=b: self.on_bit(b))
            cb.grid(row=2 + b % 8, column=(b // 8) * 2, columnspan=2, sticky='w', padx=(0, 4))
            self.bitvars.append(v)
            self.bitboxes.append(cb)
        act = tk.Frame(det)
        act.grid(row=10, column=0, columnspan=4, sticky='w', pady=(2, 0))
        self.b_reopen = tk.Button(act, text=T('qp.reopen', 'Re-open'), font=G.HE_FONT_S, pady=0, bd=1, command=self.reopen)
        self.b_complete = tk.Button(act, text=T('qp.complete', 'Complete'), font=G.HE_FONT_S, pady=0, bd=1, command=self.complete)
        self.b_revert = tk.Button(act, text=T('qp.revert', 'File value'), font=G.HE_FONT_S, pady=0, bd=1, command=self.revert)
        for b in (self.b_reopen, self.b_complete, self.b_revert):
            b.pack(side='left', padx=(0, 3))
        self.hint = tk.Label(act, text='', font=G.HE_FONT_S, anchor='w')
        self.hint.pack(side='left')
        tk.Label(det, font=G.HE_FONT_S, anchor='w', justify='left', wraplength=36 * em, text=T(
            'qp.note', 'Bit names: original game; only * is confirmed for Median XL. Re-open clears the word: the '
            'quest and its reward can be done again in game. Only this word changes - no reward points, no '
            'unlocks (the Quests page does those).')).grid(row=11, column=0, columnspan=4, sticky='w')
        # -- left: all words of the difficulty
        left = tk.Frame(mid)
        left.pack(side='left', fill='both', expand=True)
        self.style = ttk.Style()
        row_h = max(15, fs.metrics('linespace') + 2)
        self.style.configure('MQ.Treeview', font=G.HE_FONT_S, rowheight=row_h, borderwidth=0, indent=10)
        self.style.configure('MQ.Treeview.Heading', font=G.HE_FONT_S, padding=0)
        tv = ttk.Treeview(left, style='MQ.Treeview', columns=('w', 'hex', 'state'), selectmode='browse', height=8)
        self.tv = tv
        tv.heading('#0', text=T('qp.col.name', 'Word'), anchor='w')
        tv.heading('w', text='#')
        tv.heading('hex', text=T('qp.col.hex', 'Hex'))
        tv.heading('state', text=T('qp.col.state', 'State'), anchor='w')
        tv.column('#0', width=15 * em, minwidth=10 * em, stretch=True)
        tv.column('w', width=3 * em + 6, minwidth=3 * em, stretch=False, anchor='e')
        tv.column('hex', width=6 * em, minwidth=5 * em, stretch=False, anchor='center')
        tv.column('state', width=10 * em, minwidth=8 * em, stretch=True)
        sb = ttk.Scrollbar(left, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        tv.pack(side='left', fill='both', expand=True)
        for title, rows in self.table:
            g = tv.insert('', 'end', text=title, open=True, tags=('group',))
            for w, _kind, text in rows:
                self.rows[w] = tv.insert(g, 'end', text=text, values=(w, '', ''))
        self.iid_word = {iid: w for w, iid in self.rows.items()}
        tv.bind('<<TreeviewSelect>>', self.on_select)
        # -- bottom: the NPC section, read only
        self.npc = tk.Label(f, text='', font=('Courier', 9), anchor='w', justify='left')
        self.npc.pack(fill='x', padx=4, pady=(0, 2))
        tv.selection_set(self.rows[1])

    def set_theme(self, dark):
        G = self.G
        t = G.THEMES[bool(dark)]
        self.theme = t
        chg = '#ff9a4a' if dark else '#b03000'

        def walk(w):
            cls = w.winfo_class()
            try:
                if cls == 'Frame':
                    w.configure(bg=t['bg'])
                elif cls == 'Labelframe':
                    w.configure(bg=t['bg'], fg=t['frame_fg'])
                elif cls == 'Label':
                    w.configure(bg=t['bg'], fg=t['fg'])
                elif cls == 'Checkbutton':
                    w.configure(bg=t['bg'], fg=t['fg'], activebackground=t['bg'], activeforeground=t['fg'],
                                selectcolor=t['entry'])
                elif cls == 'Radiobutton':
                    w.configure(bg=t['tab'], fg=t['tab_fg'], selectcolor=t['tab_sel'], activebackground=t['tab_sel'],
                                activeforeground=t['tab_fg'])
                elif cls == 'Button':
                    w.configure(bg=t['btn'], fg=t['fg'], activebackground=t['btn'], activeforeground=t['fg'],
                                disabledforeground=t['box_mid'], highlightbackground=t['bg'])
                elif cls == 'Entry':
                    w.configure(bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg'])
            except tk.TclError:
                pass
            for c in w.winfo_children():
                walk(c)
        walk(self.frame)
        self.changed.configure(fg=chg)
        sel_bg = t['tab_sel']
        self.style.configure('MQ.Treeview', background=t['pane'], fieldbackground=t['pane'], foreground=t['pane_fg'])
        self.style.map('MQ.Treeview', background=[('selected', sel_bg)], foreground=[('selected', t['pane_fg'])])
        self.style.configure('MQ.Treeview.Heading', background=t['btn'], foreground=t['fg'])
        self.style.map('MQ.Treeview.Heading', background=[('active', t['btn'])])
        self.tv.tag_configure('group', foreground=t['frame_fg'] if dark else '#000080')
        self.tv.tag_configure('chg', foreground=chg)

    # ------------------------------------------------------------------ state
    def file_value(self, k, w):
        return self.win.ch.quest_word(k, w)

    def value(self, k, w):
        return self.pend.get((k, w), self.file_value(k, w))

    def set_value(self, w, v):
        k = self.diff.get()
        v &= 0xFFFF
        if v == self.file_value(k, w):
            self.pend.pop((k, w), None)
        else:
            self.pend[(k, w)] = v
        self.paint_row(w)
        self.show_word()
        self.win.update_dirty()

    def dirty(self):
        return any(self.file_value(k, w) != v for (k, w), v in self.pend.items())

    def apply(self):
        """Writes the pending words into the character. The Quests page's own ticks for the same quests follow
        the new bit 0, so its set_quests() neither completes a quest re-opened here nor rewards it again."""
        win, ch = self.win, self.win.ch
        for (k, w), v in sorted(self.pend.items()):
            if ch.quest_word(k, w) == v:
                continue
            ch.set_quest_word(k, w, v)
            if self.kind.get(w) == 'quest':
                for state in (getattr(win, 'q0', None), getattr(win, 'qstate', None)):
                    if state is not None:
                        (state[k].add if v & 1 else state[k].discard)(w)
        self.pend.clear()

    def refresh(self):
        self.pend.clear()
        self.show()

    # ------------------------------------------------------------------ display
    def show(self):
        for w in self.rows:
            self.paint_row(w)
        self.show_word()
        self.show_npc()

    def paint_row(self, w):
        k = self.diff.get()
        v = self.value(k, w)
        self.tv.item(self.rows[w], values=(w, f'{v:04X}', describe(self.kind[w], v)),
                     tags=('chg',) if (k, w) in self.pend else ())
        n = [sum(1 for (d, _w) in self.pend if d == i) for i in range(3)]
        self.changed.configure(text=T('qp.changed', 'Changed words: {n}', n=' / '.join(map(str, n))) if any(n) else '')

    def show_word(self):
        w, k = self.sel, self.diff.get()
        if w is None:
            return
        kind = self.kind[w]
        v, fv = self.value(k, w), self.file_value(k, w)
        off = MC.QUEST_DATA + 96 * k + 2 * w
        self.title.configure(text=T('qp.title', '{name}\n{diff}, word {w} (file offset 0x{off:03X})',
                                    name=self.names[w], diff=MC.DIFFICULTIES[k], w=w, off=off))
        self.hexvar.set(f'{v:04X}')
        self.fileval.configure(text=T('qp.infile', 'in file: {v}', v=f'{fv:04X}'))
        for b, var in enumerate(self.bitvars):
            var.set(v >> b & 1)
        cv, rv = complete_value(kind, fv), reopen_value(kind)
        self.b_complete.configure(state='normal' if cv is not None and cv != v else 'disabled',
                                  text=T('qp.complete', 'Complete') if kind == 'quest' else
                                  T('qp.set', 'Set {v}', v=f'{cv:04X}' if cv is not None else ''))
        self.b_reopen.configure(state='normal' if rv is not None and rv != v else 'disabled',
                                text=T('qp.reopen', 'Re-open') if kind == 'quest' else T('qp.clear', 'Clear'))
        self.b_revert.configure(state='normal' if v != fv else 'disabled')
        self.hint.configure(text={'respec': T('qp.h.respec', 'unproven: test in game'),
                                  'unused': T('qp.h.unused', 'in no sample')}.get(kind, ''))

    def show_npc(self):
        head = self.win.ch.head
        try:
            vals = struct.unpack_from('<6Q', head, NPC_DATA)
        except struct.error:
            self.npc.configure(text='')
            return
        k = self.diff.get()
        self.npc.configure(text=T('qp.npc', 'NPC section (read only, {diff}): introduced {a}   congratulated {b}',
                                  diff=MC.DIFFICULTIES[k], a=f'{vals[k]:016X}', b=f'{vals[3 + k]:016X}'))

    # ------------------------------------------------------------------ events
    def on_select(self, _e=None):
        sel = self.tv.selection()
        w = self.iid_word.get(sel[0]) if sel else None
        if w is None:
            return
        self.sel = w
        self.show_word()

    def on_hex(self, _e=None):
        if self.sel is None:
            return
        try:
            v = int(self.hexvar.get().strip() or '0', 16)
            if not 0 <= v <= 0xFFFF:
                raise ValueError
        except ValueError:
            self.win.set_status(T('qp.badhex', 'A quest word is 4 hex digits (0000 - FFFF).'), error=True)
            self.show_word()
            return
        if v != self.value(self.diff.get(), self.sel):
            self.set_value(self.sel, v)

    def on_bit(self, b):
        if self.sel is None:
            return
        v = self.value(self.diff.get(), self.sel)
        self.set_value(self.sel, v | 1 << b if self.bitvars[b].get() else v & ~(1 << b))

    def reopen(self):
        v = reopen_value(self.kind[self.sel])
        if v is not None:
            self.set_value(self.sel, v)

    def complete(self):
        v = complete_value(self.kind[self.sel], self.file_value(self.diff.get(), self.sel))
        if v is not None:
            self.set_value(self.sel, v)

    def revert(self):
        self.set_value(self.sel, self.file_value(self.diff.get(), self.sel))

    def revert_all(self):
        self.pend.clear()
        self.show()
        self.win.update_dirty()


def install(_App=None):
    import mxl_char_gui
    mxl_char_gui.register_page('quests_adv', T('ch.tab.quests_adv', 'Quests+'), QuestPage)
