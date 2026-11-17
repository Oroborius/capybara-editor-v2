"""The top bar at every window width: what does not fit moves into a "More" menu.

The bar is built by the collector and filled by several modules (Item Creator / Edit / Item stats / Delete,
Character, Undo, Import character, the theme box; on the right the game version, Game folder and Language). Side
by side they need far more than a small window has, and pack simply cuts off what is left over. Here the bar is
laid out again whenever its width changes: the items are packed as before while they fit, and the rest - the
least used first (theme box, Language, Game folder, version, Import character, then the buttons from the right) -
is reached through a "More" button whose menu does exactly what the hidden widgets do (it invokes them).
The character selector always stays."""
import tkinter as tk
from tkinter import ttk

from mxl_lang import T

GAP = 6            # largest horizontal gap kept between two items


def _pad(v):
    """padx of pack_info as (left, right)."""
    try:
        if isinstance(v, (tuple, list)):
            return int(str(v[0])), int(str(v[-1]))
        parts = str(v).split()
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        return int(parts[0]), int(parts[0])
    except (ValueError, IndexError, tk.TclError):
        return 0, 0


class Item:
    def __init__(self, w, parent=None):
        self.w = w
        self.parent = parent                 # the Item of the frame it sits in, or None (directly in the bar)
        info = w.pack_info()
        left, right = _pad(info.get('padx', 0))
        self.opts = {'side': info.get('side', 'left'), 'padx': (min(left, GAP), min(right, GAP)),
                     'pady': info.get('pady', 0), 'anchor': info.get('anchor', 'center'),
                     'fill': info.get('fill', 'none'), 'expand': info.get('expand', 0)}
        self.children = []
        self.partner = None                  # a label that belongs to this widget (hidden and shown with it)
        self.shown = True

    @property
    def cost(self):
        return self.w.winfo_reqwidth() + sum(self.opts['padx'])


class Toolbar:
    def __init__(self, app):
        self.app = app
        self.bar = bar = app.char_combo.master
        self.items = []                      # top level, in packing order
        self.order = []                      # leaves, first to hide first
        self.job = None
        self.state = None
        keep = set()
        slaves = bar.pack_slaves()
        for w in slaves:
            it = Item(w)
            self.items.append(it)
            if w.winfo_class() == 'TFrame':
                for c in w.pack_slaves():
                    it.children.append(Item(c, it))
        # the character selector (its label and the box) stays whatever the width
        for i, it in enumerate(self.items):
            if it.w is app.char_combo:
                keep.add(it)
                if i and self.items[i - 1].w.winfo_class() == 'TLabel':
                    keep.add(self.items[i - 1])
        # a label packed next to a combobox on the same side is its caption
        for i, it in enumerate(self.items):
            if it.w.winfo_class() == 'TCombobox' and it not in keep:
                for j in (i + 1, i - 1):
                    if 0 <= j < len(self.items) and self.items[j].w.winfo_class() == 'TLabel' \
                            and self.items[j] not in keep and self.items[j].opts['side'] == it.opts['side']:
                        it.partner = self.items[j]
                        break
        partners = {it.partner for it in self.items if it.partner is not None}
        leaves = []
        for it in self.items:
            if it in keep or it in partners:
                continue
            leaves.extend(it.children if it.children else [it])
        checks = [x for x in leaves if x.w.winfo_class() == 'TCheckbutton']
        right = [x for x in leaves if x.opts['side'] == 'right' and x not in checks]
        combos = [x for x in right if x.w.winfo_class() == 'TCombobox']
        others = [x for x in right if x not in combos]
        left = [x for x in leaves if x not in checks and x not in right]
        self.order = checks + combos + others + list(reversed(left))
        self.more = ttk.Button(bar, text=T('bar.more', 'More') + ' \u00bb', command=self.post, takefocus=False)
        self.menu = tk.Menu(bar, tearoff=0)
        bar.bind('<Configure>', self._configure, add='+')
        bar.bind('<<ThemeChanged>>', self._configure, add='+')     # other button sizes: lay out again
        self.layout()

    # ------------------------------------------------------------------ layout
    def _configure(self, ev):
        if ev.widget is self.bar and self.job is None:
            self.job = self.bar.after(30, self.layout)

    def _needed(self, hidden):
        total = 0
        for it in self.items:
            if it.children:
                inner = sum(c.cost for c in it.children if c not in hidden)
                if inner:
                    total += inner + sum(it.opts['padx'])
            elif it not in hidden:
                total += it.cost
        if hidden:
            total += self.more.winfo_reqwidth() + GAP
        return total + 8

    def layout(self, width=None):
        self.job = None
        try:
            W = width or self.bar.winfo_width()
            if W < 50:
                W = self.bar.winfo_reqwidth()
            hidden = set()
            for it in [None] + self.order:
                if it is not None:
                    hidden.add(it)
                    if it.partner is not None:
                        hidden.add(it.partner)
                if self._needed(hidden) <= W:
                    break
            state = (frozenset(hidden),)
            if state == self.state:
                return
            self.state = state
            self.hidden = hidden
            for it in self.items:
                for c in it.children:
                    c.w.pack_forget()
                it.w.pack_forget()
            self.more.pack_forget()
            if hidden:                           # at the right end, before the right-side items take their room
                self.more.pack(side='right', padx=(GAP // 2, GAP // 2))
            for it in self.items:
                if it.children:
                    vis = [c for c in it.children if c not in hidden]
                    if not vis:
                        continue
                    for c in vis:
                        c.w.pack(**c.opts)
                elif it in hidden:
                    continue
                it.w.pack(**it.opts)
        except tk.TclError as e:
            print('mxl_toolbar:', e)

    # ------------------------------------------------------------------ the menu
    def post(self):
        try:                                     # a new menu each time (Tk 9: no 'delete' on an empty menu)
            self.menu.destroy()
        except tk.TclError:
            pass
        m = self.menu = tk.Menu(self.bar, tearoff=0)
        hidden = getattr(self, 'hidden', set())
        partners = {it.partner for it in self.order if it.partner is not None}
        seen = [it for it in self._leaves() if it in hidden and it not in partners]
        for it in seen:
            w = it.w
            cls = w.winfo_class()
            try:
                text = str(w.cget('text')).strip() if cls != 'TCombobox' else ''
                disabled = cls != 'TLabel' and w.instate(['disabled'])
                if cls == 'TButton':
                    m.add_command(label=text, command=w.invoke, state='disabled' if disabled else 'normal')
                elif cls == 'TCheckbutton':
                    mark = '[x] ' if w.instate(['selected']) else '[  ] '
                    m.add_command(label=mark + text, command=w.invoke, state='disabled' if disabled else 'normal')
                elif cls == 'TCombobox':
                    sub = tk.Menu(m, tearoff=0)
                    cur = w.get()
                    for v in w.cget('values') or ():
                        sub.add_command(label=('* ' if v == cur else '   ') + str(v),
                                        command=lambda v=v, w=w: self._choose(w, v))
                    cap = str(it.partner.w.cget('text')).strip() if it.partner is not None else ''
                    m.add_cascade(label=(cap + ': ' if cap else '') + cur, menu=sub)
                elif cls == 'TLabel' and text:
                    m.add_command(label=text, state='disabled')
            except tk.TclError:
                continue
        try:
            import mxl_he_theme
            mxl_he_theme._walk(m)
        except Exception:
            pass
        b = self.more
        m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def _leaves(self):
        out = []
        for it in self.items:
            out.extend(it.children if it.children else [it])
        return out

    @staticmethod
    def _choose(w, v):
        w.set(v)
        w.event_generate('<<ComboboxSelected>>')


def install(App):
    """Installed last among the modules that add to the bar (after the theme box)."""
    o_build = App._build

    def _build(self):
        o_build(self)
        try:
            self.toolbar = Toolbar(self)
        except Exception as e:                   # the bar stays as it was built
            print('mxl_toolbar disabled:', type(e).__name__, e)

    App._build = _build
