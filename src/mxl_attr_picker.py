"""Hero-Editor-style attribute picker: categories on the left, the stats of the chosen category on the right,
one filter box on top that searches every category at once.

Hero Editor 1.04 filled its attribute tree at run time (its forms hold no category names), so the categories
here are derived from the stat data itself with deterministic rules on stat ids / display functions / label
words (categorize()): every stat the save format can hold lands in exactly one category, the ones no rule
knows in 'Misc' (shown by the game) or 'Internal / hidden' (no game text).

Small API, meant for the Item stats tab now and the Item Creator later:

    palette()                         colours of the active look (dark Diablo or light Hero Editor)
    metrics(widget)                   fonts and font-relative sizes (row height, character width)
    build_index(data, choices=None)   [(stat id, label, category key)]
    AttrPicker(parent, data, on_pick=f(sid), on_cancel=f(), choices=None)     the embeddable pane (a tk.Frame)
    ChoiceList(parent, on_pick=f(name), on_cancel=f())                        filter + plain name list (skills...)
    popup(parent, data, on_pick, anchor=None, choices=None)                   the pane in a small window
    popup_choices(parent, names, on_pick, anchor=None, current=None)          the name list in a small window
    closest(text, labels)             index of the label Enter would pick for a typed text (None: nothing close)

Matching of a typed text (the Find boxes): exact name, prefix, start of a word, substring, every typed word
somewhere in the name (any order); only when none of these finds anything, the closest spellings (difflib).

The last used category and a short 'Recent' list are kept with the host's settings module
(keys 'attr_picker_cat', 'attr_picker_recent').
"""
import re
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk

try:
    import settings
except Exception:                         # outside the editor (tests): nothing is remembered
    settings = None
from mxl_lang import T

RECENT_MAX = 12
KEY_CAT = 'attr_picker_cat'
KEY_RECENT = 'attr_picker_recent'

# (key, English name) in display order; 'recent' and 'all' are virtual
CATEGORIES = [
    ('recent', 'Recent'),
    ('all', 'All stats'),
    ('attr', 'Attributes'),
    ('life', 'Life / Mana'),
    ('res', 'Resistances'),
    ('absorb', 'Absorb / Reduction'),
    ('dmg', 'Damage'),
    ('elem', 'Elemental / Spell'),
    ('atkdef', 'Attack / Defense'),
    ('speed', 'Speed'),
    ('onhit', 'On hit / Attacker'),
    ('skills', 'Skills'),
    ('proc', 'Cast / Charges'),
    ('minion', 'Minions'),
    ('find', 'Find / Gold / Exp'),
    ('item', 'Item / Requirements'),
    ('level', 'Per level / By time'),
    ('misc', 'Misc'),
    ('internal', 'Internal / hidden'),
]
_CAT_NAMES = dict(CATEGORIES)

# stats whose label says too little for the word rules
_BY_ID = {
    83: 'skills', 97: 'skills', 107: 'skills', 126: 'skills', 127: 'skills', 188: 'skills', 228: 'skills',
    309: 'skills', 409: 'skills', 449: 'skills', 479: 'skills', 473: 'skills', 474: 'skills',
    204: 'proc', 259: 'proc', 324: 'proc', 427: 'proc', 192: 'proc',
    206: 'internal', 375: 'internal', 377: 'internal', 378: 'internal', 385: 'internal', 456: 'internal',
    155: 'minion', 261: 'minion',
    111: 'dmg', 137: 'dmg', 141: 'dmg', 135: 'dmg', 136: 'dmg',
    89: 'item', 90: 'item', 152: 'item', 125: 'item', 253: 'item', 254: 'item', 294: 'item', 372: 'item',
    410: 'item', 411: 'item', 466: 'item', 276: 'item', 501: 'item',
    31: 'atkdef', 16: 'atkdef', 19: 'atkdef', 20: 'atkdef',
}

# ordered (category, regular expression on the lower-case label): the first match wins
_RULES = [(c, re.compile(p)) for c, p in (
    ('proc', r'chance to cast|charges'),
    ('level', r'perlevel|per level|bytime|by time|based on character level'),
    ('minion', r'summon|minion|totem|edyrem|reanimate|vessel|shamanic'),
    ('skills', r'skill level|to all skills|\[oskill\]|\[class_skill\]|cooldown|skills\b'),
    ('find', r'gold find|magic find|experience|vendor|find gems'),
    ('elem', r'enemy .*resist|pierce (cold|fire|ltng|pois)|spell damage|spell focus'),
    ('res', r'resist'),
    ('absorb', r'absorb|damage taken reduced|damage reduction|avoid'),
    ('onhit', r'attacker|target|knockback|freez|blind|flee|stun|slow|monster|rest in peace'),
    ('elem', r'fire|cold|lightning|poison|magic damage|burning|elemental|pois|ltng'),
    ('attr', r'\bto (strength|dexterity|vitality|energy)\b|vitality bonus|^item (strength|dexterity|vitality|energy)'),
    ('speed', r'speed|hit recovery|run walk'),
    ('life', r'\blife\b|\bmana\b|manarecovery|stamina|regenerat|potion|heal'),
    ('atkdef', r'defense|block|attack rating|tohit|\bac\b'),
    ('dmg', r'damage|crushing|deadly|open wounds|critical|crush|pierc|magic arrows|explosive'),
    ('item', r'requirement|required|durability|indestructible|levelreq|quantity|stack|socket|light radius'
             r'|repairs|replenish|rune'),
)]

_PRINTF = ((re.compile(r'%[+]?d%%'), '#%'), (re.compile(r'%[+]?\.?\d*[dgfi]'), '#'), (re.compile(r'%s'), '[..]'),
           (re.compile(r'%%'), '%'))


_CTC = re.compile(r'^#% Chance to cast level # \[\.\.\] (.*)$')      # the trigger first: it tells them apart


def clean_label(label):
    """A stat label without the game's printf marks ('%d%% Chance to cast level %d %s' -> '#% Chance to
    cast level # [..]')."""
    out = str(label)
    if '%' in out:
        for rx, rep in _PRINTF:
            out = rx.sub(rep, out)
    return out


def categorize(sid, label, has_text=True, isc=None):
    """The one category key of a stat (see CATEGORIES). has_text: the game itself shows a text for it."""
    if sid in _BY_ID:
        return _BY_ID[sid]
    c = isc or {}
    low = str(label).lower()
    if c.get('func') == 15:
        return 'proc'
    if c.get('func') in (6, 7, 8):
        return 'level'
    for cat, rx in _RULES:
        if rx.search(low):
            return cat
    return 'misc' if has_text else 'internal'


def build_index(data, choices=None):
    """[(stat id, clean label, category key)] of every stat the save format can hold, sorted by label.
    choices: [(sid, label)] as mxl_creator.Creator.stat_choices() gives them (built here when None)."""
    if choices is None:
        import mxl_creator
        choices = mxl_creator.Creator(data).stat_choices()
    try:
        from mxl_statnames import stat_text
    except Exception:
        stat_text = None
    out = []
    for sid, label in choices:
        try:
            c = data.isc[sid]
        except (IndexError, KeyError, TypeError):
            c = {}
        has = True
        if stat_text is not None:
            try:
                has = bool(stat_text(data, sid, None, value=1, desc=(c or {}).get('desc')))
            except Exception:
                has = True
        lab = _CTC.sub(r'Chance to cast \1', clean_label(label))
        out.append((sid, lab, categorize(sid, lab, has, c)))
    out.sort(key=lambda x: (x[1].lower(), x[0]))
    return out


def category_name(key):
    return T('ap.cat.' + key, _CAT_NAMES.get(key, key))


# ---------------------------------------------------------------------------------------------- look
def palette():
    """Colours of the active look, taken from its theme module: dark Diablo (mxl_d2_theme) or the light
    Hero Editor one (mxl_he_theme)."""
    try:
        import mxl_d2_theme as D
        if D.dark():
            return dict(bg=D.STONE, field=D.FIELD, fg=D.GOLD, fg_hi=D.GOLD_HI, dim=D.DIM, sel=D.LEATHER,
                        sel_fg=D.GOLD_HI, line=D.BRONZE, head=D.STONE_HI, alt=D.STONE_LO, btn=D.LEATHER,
                        btn_hi=D.LEATHER_HI, bar=D.STONE_LO, bar_fg=D.GOLD_HI, changed='#e8a33c',
                        error='#ff8a7a', sel_dim=D.STONE_HI, dark=True)
    except Exception:
        pass
    try:
        import mxl_he_theme as H
        bg, btn, field, fg, sel, gold = H.HE_BG, H.HE_BTN, H.HE_ENTRY, H.HE_FG, H.SELECT_BG, H.HE_GOLD
    except Exception:
        bg, btn, field, fg, sel, gold = '#f0f0f0', '#e1e1e1', '#ffffff', '#000000', '#3a5f8a', '#d8c27a'
    return dict(bg=bg, field=field, fg=fg, fg_hi=fg, dim='#8a8a8a', sel=sel, sel_fg='#ffffff', line='#a8a8a8',
                head=btn, alt='#f5f5f0', btn=btn, btn_hi='#d0d0d0', bar='#000000', bar_fg=gold,
                changed='#b05a00', error='#ff9a9a', sel_dim='#c5d5ea', dark=False)


def exempt(w):
    """The widget styles itself: the theme walker leaves it (and its subtree) alone."""
    try:
        import mxl_he_theme
        mxl_he_theme.exempt(w)
    except Exception:
        w._he_exempt = True
    return w


_metrics = {}


def metrics(widget):
    """Fonts and font-relative sizes: dict(font, bold, small, row (list row height in px), ch (width of '0'),
    line (linespace)). Everything in the picker and the slot list is sized from these, never in fixed pixels."""
    if _metrics:
        return _metrics
    try:
        base = tkfont.nametofont('TkDefaultFont', root=widget).actual()
        fam, size = base.get('family') or 'TkDefaultFont', int(base.get('size') or 9)
    except Exception:
        fam, size = 'TkDefaultFont', 9
    try:
        import mxl_he_theme
        fam = mxl_he_theme.safe_family(fam)
    except Exception:
        pass
    if size < 0:                                  # pixel size: keep it as it is
        size = -max(10, -size)
    else:
        size = max(8, min(size, 11))
    font = tkfont.Font(root=widget, family=fam, size=size)
    bold = tkfont.Font(root=widget, family=fam, size=size, weight='bold')
    line = font.metrics('linespace')
    _metrics.update(font=font, bold=bold, line=line, row=line + 4, ch=max(5, font.measure('0')))
    return _metrics


def button(parent, text, command, pal=None, m=None, **kw):
    """A compact plain button in the active look (the art buttons of the dark look are too tall here)."""
    pal = pal or palette()
    m = m or metrics(parent)
    b = tk.Button(parent, text=text, command=command, font=m['font'], bg=pal['btn'], fg=pal['fg_hi'],
                  activebackground=pal['btn_hi'], activeforeground=pal['fg_hi'], disabledforeground=pal['dim'],
                  bd=1, relief='raised', padx=6, pady=0, highlightthickness=0, takefocus=0, **kw)
    return b


def _listbox(parent, pal, m, **kw):
    lb = tk.Listbox(parent, font=m['font'], bg=pal['field'], fg=pal['fg'], selectbackground=pal['sel'],
                    selectforeground=pal['sel_fg'], bd=0, highlightthickness=1, highlightbackground=pal['line'],
                    highlightcolor=pal['fg_hi'], activestyle='none', exportselection=False, relief='flat', **kw)
    return lb


def _entry(parent, pal, m, var, **kw):
    return tk.Entry(parent, textvariable=var, font=m['font'], bg=pal['field'], fg=pal['fg_hi'],
                    insertbackground=pal['fg_hi'], selectbackground=pal['sel'], selectforeground=pal['sel_fg'],
                    bd=0, relief='flat', highlightthickness=1, highlightbackground=pal['line'],
                    highlightcolor=pal['fg_hi'], **kw)


def _rank(pat, low):
    """Sort rank of a label for a filter text: 0 the name itself, 1 prefix, 2 a word starts with it, 3 substring,
    4 every typed word is in it (any order: 'move speed' finds 'Movement Speed'); None no match."""
    i = low.find(pat)
    if i < 0:
        words = pat.split()
        if len(words) > 1 and all(w in low for w in words):
            return 4
        return None
    if i == 0:
        return 0 if len(low) == len(pat) else 1
    return 2 if not low[i - 1].isalnum() else 3


def _fuzzy(pat, lows, n=30):
    """Indexes of the closest spellings in lows (lower-case labels) for a text nothing matched: a typo, a
    missing letter. Whole labels first, then labels with a word close to a typed word."""
    import difflib
    if len(pat) < 3:
        return []
    out = [i for _r, i in sorted(((difflib.SequenceMatcher(None, pat, low).ratio(), i)
                                  for i, low in enumerate(lows)
                                  if abs(len(low) - len(pat)) <= max(4, len(pat))), key=lambda x: (-x[0], x[1]))
           if _r >= 0.72][:n]
    if len(out) < n:
        words = [w for w in pat.split() if len(w) >= 3]
        scored = []
        for i, low in enumerate(lows):
            if i in out or not words:
                continue
            lw = low.replace('/', ' ').replace('-', ' ').split()
            sc = [max((difflib.SequenceMatcher(None, w, x[:len(w) + 1]).ratio() for x in lw), default=0)
                  for w in words]
            if min(sc) >= 0.74:
                scored.append((-sum(sc) / len(sc), i))
        out += [i for _s, i in sorted(scored)][:n - len(out)]
    return out


def search(pat, lows):
    """Indexes into lows (lower-case labels) for a typed text, best match first (see _rank; the closest
    spellings when nothing matches). An empty text: everything, in order."""
    pat = ' '.join(pat.lower().split())
    if not pat:
        return list(range(len(lows)))
    hits = sorted((r, len(low), i) for i, low in enumerate(lows) for r in (_rank(pat, low),) if r is not None)
    if hits:
        return [i for _r, _n, i in hits]                 # same rank: the shorter (closer) name first
    return _fuzzy(pat, lows)


def closest(text, labels):
    """Index of the label a typed text stands for (what Enter picks), or None."""
    hits = search(text, [str(x).lower() for x in labels]) if str(text).strip() else []
    return hits[0] if hits else None


# ---------------------------------------------------------------------------------------------- plain name list
class ChoiceList(tk.Frame):
    """A filter box over a list of names (skills, classes): Enter / double-click picks, Escape cancels."""

    def __init__(self, parent, on_pick=None, on_cancel=None, title=''):
        pal = self.pal = palette()
        m = self.m = metrics(parent)
        super().__init__(parent, bg=pal['bg'])
        exempt(self)
        self.on_pick, self.on_cancel = on_pick, on_cancel
        self.names, self.shown = [], []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.title = tk.Label(self, text=title, font=m['bold'], bg=pal['bg'], fg=pal['fg_hi'], anchor='w')
        self.title.grid(row=0, column=0, columnspan=2, sticky='we')
        self.var = tk.StringVar()
        self.entry = _entry(self, pal, m, self.var)
        self.entry.grid(row=1, column=0, columnspan=2, sticky='we', pady=(0, 2))
        self.lb = _listbox(self, pal, m, width=10, height=4)
        self.lb.grid(row=2, column=0, sticky='nsew')
        sb = ttk.Scrollbar(self, orient='vertical', command=self.lb.yview)
        sb.grid(row=2, column=1, sticky='ns')
        self.lb.configure(yscrollcommand=sb.set)
        self.var.trace_add('write', lambda *_a: self.fill())
        for w in (self.entry, self.lb):
            w.bind('<Return>', self._pick)
            w.bind('<KP_Enter>', self._pick)
            w.bind('<Escape>', self._cancel)
        self.entry.bind('<Down>', lambda _e: self._move(1))
        self.entry.bind('<Up>', lambda _e: self._move(-1))
        self.entry.bind('<Next>', lambda _e: self._move(10))
        self.entry.bind('<Prior>', lambda _e: self._move(-10))
        self.lb.bind('<Double-Button-1>', self._pick)

    def set(self, names, current=None, title=None):
        self.names = [(n, n.lower()) for n in names]
        if title is not None:
            self.title.configure(text=title)
        self.var.set('')
        self.fill()
        if current in self.shown:
            self._select(self.shown.index(current))

    def fill(self):
        pat = self.var.get().strip().lower()
        if pat:
            self.shown = [self.names[i][0] for i in search(pat, [low for _n, low in self.names])]
        else:
            self.shown = [n for n, _l in self.names]
        self.lb.delete(0, 'end')
        if self.shown:
            self.lb.insert('end', *self.shown)
            self._select(0)

    def _select(self, i):
        self.lb.selection_clear(0, 'end')
        if 0 <= i < len(self.shown):
            self.lb.selection_set(i)
            self.lb.activate(i)
            self.lb.see(i)

    def _move(self, d):
        cur = self.lb.curselection()
        i = (cur[0] if cur else -1) + d
        self._select(max(0, min(len(self.shown) - 1, i)))
        return 'break'

    def current(self):
        cur = self.lb.curselection()
        return self.shown[cur[0]] if cur and cur[0] < len(self.shown) else None

    def _pick(self, _e=None):
        name = self.current()
        if name is not None and self.on_pick:
            self.on_pick(name)
        return 'break'

    def _cancel(self, _e=None):
        if self.on_cancel:
            self.on_cancel()
        return 'break'

    def focus_filter(self):
        self.entry.focus_set()
        self.entry.selection_range(0, 'end')


# ---------------------------------------------------------------------------------------------- attribute picker
class AttrPicker(tk.Frame):
    """Categories | stats of the category, with a filter over all categories on top.

    on_pick(sid) is called for Enter / double-click on a stat (and Enter in the filter box: the selected,
    i.e. first, match); on_cancel() for Escape. on_select(sid) (optional) follows the highlighted stat."""

    def __init__(self, parent, data, on_pick=None, on_cancel=None, choices=None, on_select=None, title=None):
        pal = self.pal = palette()
        m = self.m = metrics(parent)
        super().__init__(parent, bg=pal['bg'])
        exempt(self)
        self.data, self.on_pick, self.on_cancel, self.on_select = data, on_pick, on_cancel, on_select
        self.index = build_index(data, choices)
        self._low = [(sid, lab, cat, lab.lower()) for sid, lab, cat in self.index]
        self._labels = {sid: lab for sid, lab, _c in self.index}
        self.counts = {}
        for _sid, _lab, cat in self.index:
            self.counts[cat] = self.counts.get(cat, 0) + 1
        self.recent = [s for s in self._setting(KEY_RECENT, []) if s in self._labels][:RECENT_MAX]
        self.cats = [k for k, _n in CATEGORIES if k in ('recent', 'all') or self.counts.get(k)]
        cat = self._setting(KEY_CAT, 'all')
        self.cat = cat if cat in self.cats else 'all'
        self.shown = []

        ch = m['ch']
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        self.title = tk.Label(self, text=title or T('ap.title', 'Attribute'), font=m['bold'], bg=pal['bg'],
                              fg=pal['fg_hi'], anchor='w')
        self.title.grid(row=0, column=0, columnspan=3, sticky='we')
        top = tk.Frame(self, bg=pal['bg'])
        top.grid(row=1, column=0, columnspan=3, sticky='we', pady=(0, 2))
        top.columnconfigure(1, weight=1)
        tk.Label(top, text=T('ap.filter', 'Find:'), font=m['font'], bg=pal['bg'], fg=pal['fg']).grid(
            row=0, column=0, padx=(0, 3))
        self.var = tk.StringVar()
        self.entry = _entry(top, pal, m, self.var)
        self.entry.grid(row=0, column=1, sticky='we')
        self.cat_lb = _listbox(self, pal, m, width=1, height=4)
        self.cat_lb.grid(row=2, column=0, sticky='nsew', padx=(0, 2))
        self.columnconfigure(0, minsize=self._cat_width() + ch)
        self.lb = _listbox(self, pal, m, width=10, height=4)
        self.lb.grid(row=2, column=1, sticky='nsew')
        sb = ttk.Scrollbar(self, orient='vertical', command=self.lb.yview)
        sb.grid(row=2, column=2, sticky='ns')
        self.lb.configure(yscrollcommand=sb.set)
        self.info = tk.Label(self, text='', font=m['font'], bg=pal['bg'], fg=pal['dim'], anchor='w')
        self.info.grid(row=3, column=0, columnspan=3, sticky='we')

        self._fill_cats()
        self.fill()
        self.var.trace_add('write', lambda *_a: self.fill())
        e = self.entry
        e.bind('<Down>', lambda _e: self._move(1))
        e.bind('<Up>', lambda _e: self._move(-1))
        e.bind('<Next>', lambda _e: self._move(10))
        e.bind('<Prior>', lambda _e: self._move(-10))
        for w in (e, self.lb):
            w.bind('<Return>', self._pick)
            w.bind('<KP_Enter>', self._pick)
        for w in (e, self.lb, self.cat_lb):
            w.bind('<Escape>', self._cancel)
        self.lb.bind('<Double-Button-1>', self._pick)
        self.lb.bind('<<ListboxSelect>>', self._selected)
        self.lb.bind('<Left>', lambda _e: (self.cat_lb.focus_set(), 'break')[1])
        self.lb.bind('<Key>', self._type_ahead)
        self.cat_lb.bind('<<ListboxSelect>>', self._cat_clicked)
        self.cat_lb.bind('<Right>', lambda _e: (self.lb.focus_set(), 'break')[1])
        self.cat_lb.bind('<Return>', lambda _e: (self.lb.focus_set(), 'break')[1])
        self.cat_lb.bind('<Key>', self._type_ahead)

    # ---- settings
    @staticmethod
    def _setting(key, default):
        try:
            v = settings.get(key)
        except Exception:
            v = None
        return default if v is None else v

    @staticmethod
    def _store(key, value):
        try:
            settings.put(key, value)
        except Exception:
            pass

    # ---- categories
    def _cat_text(self, key):
        n = len(self.recent) if key == 'recent' else len(self.index) if key == 'all' else self.counts.get(key, 0)
        return f'{category_name(key)} ({n})'

    def _cat_width(self):
        f = self.m['font']
        return max(f.measure(self._cat_text(k)) for k in self.cats)

    def _fill_cats(self):
        self.cat_lb.delete(0, 'end')
        self.cat_lb.insert('end', *[self._cat_text(k) for k in self.cats])
        self._mark_cat()

    def _mark_cat(self):
        self.cat_lb.selection_clear(0, 'end')
        if not self.var.get().strip() and self.cat in self.cats:
            i = self.cats.index(self.cat)
            self.cat_lb.selection_set(i)
            self.cat_lb.activate(i)
            self.cat_lb.see(i)

    def _cat_clicked(self, _e=None):
        cur = self.cat_lb.curselection()
        if not cur:
            return
        self.set_category(self.cats[cur[0]], clear_filter=True)

    def set_category(self, key, clear_filter=False):
        if key not in self.cats:
            return
        self.cat = key
        if key != 'recent':
            self._store(KEY_CAT, key)
        if clear_filter and self.var.get():
            self.var.set('')                       # the trace refills
        else:
            self.fill()

    # ---- stats
    def fill(self):
        """The stats shown: the filter's matches over ALL categories (the name itself, prefix, word start,
        substring, all typed words - in that order, else the closest spellings; '#93' or '93' also finds the
        stat id), else the chosen category."""
        pat = self.var.get().strip().lower()
        if pat:
            hits = []
            num = pat.lstrip('#')
            pat = ' '.join(pat.split())
            for sid, lab, _cat, low in self._low:
                r = _rank(pat, low)
                if num.isdigit() and int(num) == sid:
                    r = -1
                if r is not None:
                    hits.append((r, len(low), low, sid, lab))   # same rank: the shorter (closer) name first
            hits.sort()
            self.shown = [(sid, lab) for _r, _n, _l, sid, lab in hits]
            if not hits:                           # nothing matches: the closest spellings (a typo)
                self.shown = [self._low[i][:2] for i in _fuzzy(pat, [x[3] for x in self._low])]
        elif self.cat == 'recent':
            self.shown = [(sid, self._labels[sid]) for sid in self.recent]
        elif self.cat == 'all':
            self.shown = [(sid, lab) for sid, lab, _c in self.index]
        else:
            self.shown = [(sid, lab) for sid, lab, c in self.index if c == self.cat]
        self.lb.delete(0, 'end')
        if self.shown:
            self.lb.insert('end', *[lab for _sid, lab in self.shown])
            self._select(0)
        else:
            self._selected()
        self._mark_cat()

    def _select(self, i):
        self.lb.selection_clear(0, 'end')
        if 0 <= i < len(self.shown):
            self.lb.selection_set(i)
            self.lb.activate(i)
            self.lb.see(i)
        self._selected()

    def _move(self, d):
        cur = self.lb.curselection()
        i = (cur[0] if cur else -1) + d
        self._select(max(0, min(len(self.shown) - 1, i)))
        return 'break'

    def current(self):
        """The highlighted stat id, or None."""
        cur = self.lb.curselection()
        return self.shown[cur[0]][0] if cur and cur[0] < len(self.shown) else None

    def label(self, sid):
        return self._labels.get(sid) or f'(stat #{sid})'

    def category_of(self, sid):
        return next((c for s, _l, c in self.index if s == sid), None)

    def _selected(self, _e=None):
        sid = self.current()
        if sid is None:
            txt = T('ap.none', 'no stat matches') if not self.shown else ''
        else:
            try:
                c = self.data.isc[sid]
                bits, pb = c.get('bits') or 0, c.get('param') or 0
            except Exception:
                bits = pb = 0
            txt = T('ap.info', 'stat #{sid}, {bits} bits', sid=sid, bits=bits)
            if pb:
                txt += T('ap.info_param', ', param {bits} bits', bits=pb)
            txt += '  -  ' + category_name(self.category_of(sid) or 'misc')
        self.info.configure(text=txt)
        if self.on_select:
            self.on_select(sid)

    def select_stat(self, sid):
        """Shows the stat in its own category (filter cleared) and highlights it. False: unknown stat."""
        cat = self.category_of(sid)
        if cat is None:
            return False
        self.cat = cat
        if self.var.get():
            self.var.set('')
        else:
            self.fill()
        i = next((n for n, (s, _l) in enumerate(self.shown) if s == sid), None)
        if i is not None:
            self._select(i)
        return True

    def remember(self, sid):
        """Puts the stat at the head of the Recent list (stored)."""
        self.recent = ([sid] + [s for s in self.recent if s != sid])[:RECENT_MAX]
        self._store(KEY_RECENT, list(self.recent))
        i = self.cats.index('recent')
        self.cat_lb.delete(i)
        self.cat_lb.insert(i, self._cat_text('recent'))
        self._mark_cat()

    def _pick(self, _e=None):
        sid = self.current()
        if sid is not None:
            self.remember(sid)
            if self.on_pick:
                self.on_pick(sid)
        return 'break'

    def _cancel(self, _e=None):
        if self.var.get():
            self.var.set('')                       # first Escape clears the filter
        elif self.on_cancel:
            self.on_cancel()
        return 'break'

    def _type_ahead(self, ev):
        """Typing in one of the lists goes on in the filter box."""
        ch = ev.char
        if ch and ch.isprintable() and not (ev.state & 0x4):
            self.entry.focus_set()
            self.entry.insert('end', ch)
            self.entry.icursor('end')
            return 'break'
        return None

    def focus_filter(self, text=None):
        self.entry.focus_set()
        if text is not None:
            self.var.set(text)
            self.entry.icursor('end')
        else:
            self.entry.selection_range(0, 'end')


def popup(parent, data, on_pick, anchor=None, choices=None, title=None):
    """The picker in a small window of its own, placed under `anchor` (a widget) and kept on the screen;
    closes on pick or Escape. Returns the Toplevel (its .picker is the AttrPicker)."""
    m = metrics(parent)
    pal = palette()
    top = tk.Toplevel(parent)
    exempt(top)
    top.configure(bg=pal['bg'], padx=3, pady=3)
    top.title(title or T('ap.title', 'Attribute'))
    try:
        top.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass

    def done(sid=None):
        try:
            top.destroy()
        except tk.TclError:
            pass
        if sid is not None:
            on_pick(sid)

    top.picker = AttrPicker(top, data, on_pick=done, on_cancel=done, choices=choices, title=title)
    top.picker.pack(fill='both', expand=True)
    w, h = m['ch'] * 78, m['row'] * 22
    sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
    w, h = min(w, sw - 16), min(h, sh - 48)
    try:
        x = anchor.winfo_rootx() if anchor is not None else (sw - w) // 2
        y = anchor.winfo_rooty() + anchor.winfo_height() if anchor is not None else (sh - h) // 3
    except tk.TclError:
        x, y = (sw - w) // 2, (sh - h) // 3
    top.geometry(f'{w}x{h}+{max(0, min(x, sw - w))}+{max(0, min(y, sh - h - 32))}')
    top.protocol('WM_DELETE_WINDOW', done)
    top.picker.entry.bind('<Tab>', top.picker._pick)       # Tab completes like Enter (the caller moves on)
    top.picker.focus_filter()
    return top


def popup_choices(parent, names, on_pick, anchor=None, current=None, title=None):
    """A ChoiceList (filter box over a list of names: skills, states, classes...) in a small window under
    `anchor`; closes on pick (Enter / Tab / double-click) or Escape. Returns the Toplevel (.picker)."""
    m = metrics(parent)
    pal = palette()
    top = tk.Toplevel(parent)
    exempt(top)
    top.configure(bg=pal['bg'], padx=3, pady=3)
    top.title(title or T('ap.choose', 'Choose'))
    try:
        top.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass

    def done(name=None):
        try:
            top.destroy()
        except tk.TclError:
            pass
        if name is not None:
            on_pick(name)

    top.picker = ChoiceList(top, on_pick=done, on_cancel=done, title=title or '')
    top.picker.pack(fill='both', expand=True)
    top.picker.set(names, current)
    longest = max([len(str(n)) for n in names] or [20])
    w, h = m['ch'] * max(30, min(longest + 6, 70)), m['row'] * (min(max(len(names), 6), 18) + 3)
    sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
    w, h = min(w, sw - 16), min(h, sh - 48)
    try:
        x = anchor.winfo_rootx() if anchor is not None else (sw - w) // 2
        y = anchor.winfo_rooty() + anchor.winfo_height() if anchor is not None else (sh - h) // 3
    except tk.TclError:
        x, y = (sw - w) // 2, (sh - h) // 3
    top.geometry(f'{w}x{h}+{max(0, min(x, sw - w))}+{max(0, min(y, sh - h - 32))}')
    top.protocol('WM_DELETE_WINDOW', done)
    top.picker.entry.bind('<Tab>', top.picker._pick)
    top.picker.focus_filter()
    return top
