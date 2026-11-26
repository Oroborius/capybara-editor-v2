"""Mercenary editor: the mercenary record of a character file and the Character window's "Mercenary" page.

Record (file header, all little endian; located in the samples, names as in vanilla Diablo II):
    0xB1 u16  dead (non-zero = dead, must be resurrected)
    0xB3 u32  id / control seed; 0 = no mercenary (then 'jf' is not followed by an item list)
    0xB7 u16  name: offset into the name strings of the hireling type (first name string + this number)
    0xB9 u16  type: the Id column of hireling.bin
    0xBB u32  experience
Game table hireling.bin (280-byte rows, vanilla layout): +0x04 Id, +0x08 monster class, +0x0C act, +0x10 difficulty
(1-3), +0x1C base level of the row, +0x20 experience per level, +0xD2 description (row of hiredescext.bin: string
index of the variant's name, "Ranger", "Priestess"...), +0xD3 / +0xF3 string keys of the first / last name.
Several rows share an Id (one per level bracket); they agree on everything used here.
Level: the highest L with  exp_per_level * L * L * (L + 1) <= experience  (vanilla formula; the samples agree:
1 010 150 on a level-100 character is level 100, whose threshold is 1 010 000).

The engine functions work on a mxl_char.Character; nothing is written until Character.save()."""
import random
import struct
import tkinter as tk
from tkinter import font as tkfont, ttk

from mxl_char import CharError
from mxl_lang import T

OFF_DEAD, OFF_ID, OFF_NAME, OFF_TYPE, OFF_EXP = 0xB1, 0xB3, 0xB7, 0xB9, 0xBB
RECORD = slice(0xB1, 0xBF)
MAX_EXP = 0xFFFFFFFF
ACT_ROMAN = {1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V'}
ACT_CLASS = {1: 'Rogue', 2: 'Desert Guard', 3: 'Iron Wolf', 5: 'Barbarian'}     # when the game has no usable name


# ---------------------------------------------------------------------------------------------- game table
class Hireling:
    """One mercenary type (an Id of hireling.bin)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def label(self):
        from mxl_char import difficulty_name
        diff = difficulty_name(self.diff - 1) if 1 <= self.diff <= 3 else str(self.diff)
        return T('merc.type_label', '{variant} - {cls}, act {act}, {diff}', variant=self.variant, cls=self.cls_name,
                 act=ACT_ROMAN.get(self.act, self.act), diff=diff)


def _clean(s):
    try:
        from mxl_data import strip_colors
        return strip_colors(s)
    except Exception:
        return s


def _key_index(data, key):
    """String index the game resolves a key to (the same text data.key() gives), or None."""
    if not hasattr(data, '_merc_keys'):
        m = {}
        for i, e in data.strings.items():
            m.setdefault(e[0], []).append(i)
        data._merc_keys = m
    hits = data._merc_keys.get(key, [])
    if not hits:
        return None
    text = data.key(key)
    return next((i for i in hits if data.strings[i][1] == text), hits[0])


def hirelings(data):
    """{type id: Hireling} from the game's hireling table (cached on the data object)."""
    if hasattr(data, '_hirelings'):
        return data._hirelings
    out = {}
    try:
        desc = data._rows('hiredescext')
    except Exception:
        desc = []
    try:
        rows = data._rows('hireling')
    except (FileNotFoundError, struct.error, ZeroDivisionError):
        rows = []
    rows = [r for r in rows if len(r) >= 0xD3]
    vanilla = False
    try:
        import mxl_profile
        if not mxl_profile.is_median():
            vanilla = True
            # vanilla: classic (version 0) and expansion (version 100) rows share the ids; a 1.10+ save names
            # the expansion row. hiredesc.bin holds the variant names there (Median: hiredescext.bin)
            if any(struct.unpack_from('<H', r, 0)[0] >= 100 for r in rows):
                rows = [r for r in rows if struct.unpack_from('<H', r, 0)[0] >= 100]
            if not desc:
                try:
                    desc = data._rows('hiredesc')
                except Exception:
                    desc = []
    except Exception:
        pass
    brackets = {}
    for r in rows:
        brackets.setdefault(struct.unpack_from('<I', r, 4)[0], []).append(struct.unpack_from('<I', r, 0x1C)[0:1] +
                                                                           struct.unpack_from('<17I', r, 0x24))
    for r in rows:
        hid, cls, act, diff = struct.unpack_from('<4I', r, 4)
        if hid in out:
            continue
        level, xpl = struct.unpack_from('<2I', r, 0x1C)
        k1 = r[0xD3:0xF3].split(b'\0')[0].decode('latin1')
        k2 = r[0xF3:0x113].split(b'\0')[0].decode('latin1')
        first, last = _key_index(data, k1), _key_index(data, k2)
        names = []
        if first is not None and last is not None and first <= last < first + 1000:
            names = [_clean(data.strings[i][1]) if i in data.strings else f'#{i - first}' for i in range(first, last + 1)]
        variant = ''
        hd = r[0xD2]
        if hd < len(desc) and len(desc[hd]) >= 2:
            variant = _clean(data.strings.get(struct.unpack_from('<H', desc[hd], 0)[0], ('', ''))[1])
        cls_name = ''
        try:
            cls_name = _clean(data.monster_names[cls])
        except Exception:
            pass
        if not cls_name or 'BUFFALO' in cls_name:
            cls_name = T(f'merc.class.{act}', ACT_CLASS.get(act, f'class {cls}'))
        if vanilla:                     # vanilla rows: no variant / class strings; the row's skills tell them apart
            if 'an evil force' in cls_name.lower():
                cls_name = T(f'merc.class.{act}', ACT_CLASS.get(act, f'class {cls}'))
            sk = []
            for sid in struct.unpack_from('<6I', r, 120):
                nm = data.skill_names.get(sid) if isinstance(data.skill_names, dict) else None
                if sid and nm and nm not in sk:
                    sk.append(_clean(nm if isinstance(nm, str) else str(nm)))
            if sk:
                variant = ' / '.join(sk)
        if not variant or 'BUFFALO' in variant or 'an evil force' in variant.lower():
            variant = cls_name
        out[hid] = Hireling(id=hid, cls=cls, act=act, diff=diff, level=level, exp_per_level=max(1, xpl),
                            names=names, variant=variant, cls_name=cls_name,
                            brackets=sorted(brackets[hid]))
    data._hirelings = out
    return out


def exp_for_level(xpl, level):
    """Least experience of a mercenary level."""
    return min(MAX_EXP, xpl * level * level * (level + 1))


def level_for_exp(xpl, exp):
    lv = max(0, int(round((exp / xpl) ** (1 / 3))) - 2)
    while xpl * (lv + 1) ** 2 * (lv + 2) <= exp:
        lv += 1
    return lv


def base_stats(h, lv):
    """The mercenary's own stats at a level, worked out from the hireling table (the save does not store them):
    the row of the highest bracket whose level is not above lv, value + (lv - row level) * per-level / 8.
    Row fields from 0x24: hp, hp/lvl, def, def/lvl, str, str/lvl, dex, dex/lvl, ar, ar/lvl, share, dmg min, dmg max,
    dmg/lvl, resist, resist/lvl. None without table rows."""
    if h is None or not getattr(h, 'brackets', None):
        return None
    row = next((b for b in reversed(h.brackets) if b[0] <= lv), h.brackets[0])
    n = lv - row[0]
    g = lambda i: row[1 + i]

    def grow(base, per):
        return base + n * per // 8
    return dict(level=lv, life=grow(g(0), g(1)), defense=grow(g(2), g(3)), strength=grow(g(4), g(5)),
                dexterity=grow(g(6), g(7)), attack=grow(g(8), g(9)), dmg_min=grow(g(11), g(13)),
                dmg_max=grow(g(12), g(13)), resist=grow(g(14), g(15)))


def max_level(xpl):
    return level_for_exp(xpl, MAX_EXP)


# ---------------------------------------------------------------------------------------------- the record
def record(ch):
    """The mercenary record of the character's header as a dict (dead, id, name, type, exp)."""
    dead, mid, name, typ, exp = struct.unpack_from('<HIHHI', ch.head, OFF_DEAD)
    return dict(dead=dead, id=mid, name=name, type=typ, exp=exp)


def set_record(ch, dead=None, id=None, name=None, type=None, exp=None):
    """Writes the given fields of the record (others are kept). Values are range-checked, not judged."""
    for off, fmt, v, top in ((OFF_DEAD, '<H', dead, 0xFFFF), (OFF_ID, '<I', id, MAX_EXP), (OFF_NAME, '<H', name, 0xFFFF),
                             (OFF_TYPE, '<H', type, 0xFFFF), (OFF_EXP, '<I', exp, MAX_EXP)):
        if v is None:
            continue
        v = int(v)
        if not 0 <= v <= top:
            raise CharError(T('merc.err.range', 'mercenary value out of range: {value}', value=v))
        struct.pack_into(fmt, ch.head, off, v)


def hired(ch):
    return record(ch)['id'] != 0


def level(ch):
    """Mercenary level from the experience and the type's row (None when the type is unknown)."""
    rec = record(ch)
    h = hirelings(ch.data).get(rec['type'])
    return None if h is None else level_for_exp(h.exp_per_level, rec['exp'])


def new_seed():
    return random.randrange(1, MAX_EXP + 1)


def hire(ch, type_id, name=0, exp=None, seed=None):
    """Gives the character a mercenary: a record with a non-zero id and an empty item list after 'jf'."""
    h = hirelings(ch.data).get(type_id)
    if h is None:
        raise CharError(T('merc.err.type', 'unknown mercenary type {n}', n=type_id))
    if not ch.has_jf:
        raise CharError(T('merc.err.no_jf', 'this character file has no mercenary section'))
    if exp is None:
        exp = exp_for_level(h.exp_per_level, max(1, min(ch.level, max_level(h.exp_per_level))))
    set_record(ch, dead=0, id=seed or new_seed(), name=name, type=type_id, exp=exp)
    if ch.merc_items is None:
        ch.merc_items = []


def dismiss(ch):
    """Removes the mercenary: record zeroed, no item list (what a character that never hired looks like in the
    documented format). Refused while the mercenary still wears items."""
    if ch.merc_items:
        raise CharError(T('merc.err.items', 'the mercenary still wears {n} item(s): move them to the character or '
                          'the stash first', n=len(ch.merc_items)))
    ch.head[RECORD] = bytes(RECORD.stop - RECORD.start)
    ch.merc_items = None


# ---------------------------------------------------------------------------------------------- the page
class MercPage:
    """Character window page: edits are held in the widgets until SAVE (apply() writes them into win.ch)."""

    def __init__(self, win, frame):
        from mxl_char_gui import HE_FONT, HE_FONT_S, HE_FONT_I
        self.win, self.frame = win, frame
        self.vanilla_he = getattr(win, 'vanilla_he', False)
        self.types = hirelings(win.data)
        self.ids = sorted(self.types)
        self.busy = False
        self.v_hired = tk.BooleanVar()
        self.v_dead = tk.BooleanVar()
        self.v_type = tk.StringVar()
        self.v_name = tk.StringVar()
        self.v_level = tk.StringVar()
        self.v_exp = tk.StringVar()
        self.v_seed = tk.StringVar()
        self.v_adv = tk.BooleanVar(value=False)
        box = tk.LabelFrame(frame, text=' ' + T('merc.title', 'Mercenary'), font=HE_FONT_I, bd=2, relief='groove',
                            padx=6, pady=3)
        if self.vanilla_he:
            box.pack(side='left', fill='y', anchor='nw', padx=(0, 4))
        else:
            box.pack(anchor='nw', padx=4, pady=4)
        self.box = box
        r = 0
        self.cb_hired = tk.Checkbutton(box, text=T('merc.hired', 'Hired'), variable=self.v_hired, font=HE_FONT,
                                       command=self.on_hired, anchor='w')
        self.cb_hired.grid(row=r, column=1, sticky='w')
        self.cb_dead = tk.Checkbutton(box, text=T('merc.dead', 'Dead (untick to resurrect)'), variable=self.v_dead,
                                      font=HE_FONT, command=self.changed, anchor='w')
        self.cb_dead.grid(row=r, column=2, columnspan=3, sticky='w')
        r += 1
        tk.Label(box, text=T('merc.type_c', 'Type:'), font=HE_FONT).grid(row=r, column=0, sticky='e', padx=(0, 4), pady=1)
        self.labels = {i: self.types[i].label() for i in self.ids}
        self.type_box = ttk.Combobox(box, state='readonly', textvariable=self.v_type, values=[self.labels[i] for i in self.ids],
                                     width=34 if self.vanilla_he else max([len(s) for s in self.labels.values()] + [20]), height=16)
        self.type_box.grid(row=r, column=1, columnspan=4, sticky='w', pady=1)
        self.type_box.bind('<<ComboboxSelected>>', lambda _e: self.on_type())
        r += 1
        tk.Label(box, text=T('merc.name_c', 'Name:'), font=HE_FONT).grid(row=r, column=0, sticky='e', padx=(0, 4), pady=1)
        self.name_box = ttk.Combobox(box, state='readonly', textvariable=self.v_name, width=18, height=16)
        self.name_box.grid(row=r, column=1, columnspan=2, sticky='w', pady=1)
        self.name_box.bind('<<ComboboxSelected>>', lambda _e: self.changed())
        r += 1
        tk.Label(box, text=T('merc.level_c', 'Level:'), font=HE_FONT).grid(row=r, column=0, sticky='e', padx=(0, 4), pady=1)
        self.e_level = tk.Spinbox(box, from_=1, to=999, width=5, textvariable=self.v_level, font=HE_FONT,
                                  command=self.on_level, justify='right')
        self.e_level.grid(row=r, column=1, sticky='w', pady=1)
        self.e_level.bind('<KeyRelease>', lambda _e: self.on_level())
        tk.Label(box, text=T('merc.exp_c', 'Experience:'), font=HE_FONT).grid(row=r, column=2, sticky='e', padx=(8, 4))
        self.e_exp = tk.Entry(box, width=11, textvariable=self.v_exp, font=HE_FONT, justify='right', relief='sunken', bd=2)
        self.e_exp.grid(row=r, column=3, sticky='w')
        self.e_exp.bind('<KeyRelease>', lambda _e: self.on_exp())
        self.b_match = tk.Button(box, text=T('merc.match', 'Character level'), font=HE_FONT_S, command=self.match_level,
                                 padx=3, pady=0)
        self.b_match.grid(row=r, column=4, sticky='w', padx=(6, 0))
        r += 1
        self.cb_adv = tk.Checkbutton(box, text=T('merc.advanced', 'Advanced'), variable=self.v_adv, font=HE_FONT_S,
                                     command=self.show_adv, anchor='w')
        self.cb_adv.grid(row=r, column=1, sticky='w')
        r += 1
        self.adv = tk.Frame(box)
        self.adv_row = r
        tk.Label(self.adv, text=T('merc.seed_c', 'Id / control seed (hex):'), font=HE_FONT).pack(side='left', padx=(0, 4))
        self.e_seed = tk.Entry(self.adv, width=9, textvariable=self.v_seed, font=HE_FONT, relief='sunken', bd=2)
        self.e_seed.pack(side='left')
        self.e_seed.bind('<KeyRelease>', lambda _e: self.changed())
        self.b_seed = tk.Button(self.adv, text=T('merc.new_seed', 'New'), font=HE_FONT_S, padx=3, pady=0,
                                command=lambda: (self.v_seed.set(f'{new_seed():08X}'), self.changed()))
        self.b_seed.pack(side='left', padx=(6, 0))
        r += 1
        self.info = tk.Label(box, text='', font=HE_FONT_S, justify='left', anchor='w', wraplength=460)
        self.info.grid(row=r, column=0, columnspan=5, sticky='w', pady=(3, 0))
        r += 1
        tk.Label(box, font=HE_FONT_S, justify='left', anchor='w', wraplength=460,
                 text=T('merc.note', 'Changes are written with SAVE. Level = experience by the game\'s own table; '
                        'the game does not let a mercenary outlevel the character. Not tested in the running game: '
                        'keep the backup.')).grid(row=r, column=0, columnspan=5, sticky='w')
        if self.vanilla_he:
            self._vanilla_controls()
        frame.bind('<Configure>', self._wrap, add='+')
        self.refresh()

    def _vanilla_controls(self):
        from mxl_char import difficulty_name
        from mxl_vanilla_he import font, pixels

        self.box.configure(text='', bd=0, padx=0, pady=0)
        for widget in self.box.grid_slaves():
            widget.grid_forget()
        self.box.pack_configure(fill='both', expand=True, padx=0)
        self.box.configure(width=pixels(self.box, 642)[0], height=pixels(self.box, 435)[0])
        self.box.pack_propagate(False)

        OX, OY = 4, 22                      # reference frame -> page origin

        def place(widget, x, y, width, height):
            x, y, width, height = pixels(self.box, x - OX, y - OY, width, height)
            widget.place(x=x, y=y, width=width, height=height)

        def group(text, x, y, width, height):
            box = ttk.LabelFrame(self.box, text=text, padding=2)
            place(box, x, y, width, height)
            return box

        def label(text, x, y, width, height, **kw):
            item = ttk.Label(self.box, text=text, **kw)
            place(item, x, y, width, height)
            return item

        def field(x, y, width, height, variable=None, readonly=True):
            item = tk.Entry(self.box, textvariable=variable, justify='center', relief='sunken', bd=2,
                            font=font(), readonlybackground='#ffffff' if readonly else '#ffffff',
                            state='readonly' if readonly else 'normal', takefocus=0)
            place(item, x, y, width, height)
            return item

        group('Level', 9, 21, 119, 34)
        group('Experience', 9, 64, 119, 34)
        for control, y in ((self.e_level, 37), (self.e_exp, 80)):
            place(control, 17, y, 103, 16)
            control.lift()
        self.e_level.configure(justify='center', relief='sunken', bd=2)
        self.e_exp.configure(justify='center')
        self.b_match.configure(text='Match Character')
        place(self.b_match, 9, 340, 119, 20)

        life = group('Mercenary Life', 9, 103, 119, 74)
        life.configure(padding=(2, 0, 2, 0))
        self.v_life = tk.StringVar()
        self.life_buttons = []
        for text in ('Dead', 'Alive', 'Not Hired'):
            radio = ttk.Radiobutton(life, text=text, value=text, variable=self.v_life, command=self._change_life,
                                    padding=0)
            radio.pack(anchor='w', pady=0, ipady=0)
            self.life_buttons.append(radio)

        portrait = group('Portrait', 133, 20, 102, 113)
        self.vanilla_portrait = tk.Label(portrait, relief='flat', wraplength=pixels(portrait, 85)[0])
        self.vanilla_portrait.pack(fill='both', expand=True)
        self.vanilla_seed = ttk.Button(self.box, text='Create New\nMercenary ID', command=self.b_seed.invoke)
        place(self.vanilla_seed, 137, 140, 95, 36)

        self.facts = {}
        for index, caption in enumerate(('ID', 'Name ID', 'Code', 'Name', 'Attributes', 'Difficulty')):
            y = 189 + index * 24
            label(caption + ':', 16, y, 64, 17)
            self.facts[caption] = field(81, y, 103, 18, readonly=caption not in self.EDITABLE_FACTS)
            if caption in self.EDITABLE_FACTS:
                self.facts[caption].bind('<KeyRelease>', lambda _e, c=caption: self.fact_typed(c))
        group('', 9, 177, 183, 156).lower()

        group('Base Stats', 246, 20, 170, 176)
        label('Derived from game data', 248, 37, 166, 15, anchor='center')
        self.base_stats = {}
        for index, caption in enumerate(('Strength', 'Dexterity', 'Life', 'Damage', 'Defense', 'Resists')):
            y = 53 + index * 24
            label(caption + ':', 248, y, 62, 17)
            self.base_stats[caption] = field(313, y, 95, 20)
        big = tkfont.Font(family=font()[0], size=-18)
        small = tkfont.Font(family=font()[0], size=-14)
        for text, y, face in (('Experience and\nAbove Stats Only\nPartly Completed', 208, big),
                              ('Items Can Be Edited\nUnder The Inventory Tab', 282, small)):
            item = tk.Label(self.box, text=text, font=face, justify='center')
            place(item, 246, y, 170, 50 if face is big else 34)
        self.info.configure(wraplength=pixels(self.box, 160)[0])
        place(self.info, 246, 372, 170, 40)

        label('Mercenary Name', 432, 22, 188, 15)
        self.name_box.configure(font=font())
        place(self.name_box, 432, 37, 208, 22)
        classes = group('Class', 425, 70, 223, 385)
        self.class_tree = tree = ttk.Treeview(classes, show='tree', height=18)
        tree.column('#0', width=174, minwidth=140)
        scroll = ttk.Scrollbar(classes, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        tree.pack(fill='both', expand=True)
        root = tree.insert('', 'end', text='Mercenary', open=True)
        modes = {k: tree.insert(root, 'end', text=difficulty_name(k - 1)) for k in range(1, 4)}
        for key, kind in self.types.items():
            tree.insert(modes.get(kind.diff, root), 'end', iid=f'type-{key}',
                        text=f'{kind.cls_name} · {kind.variant}')
        self.type_box.configure(font=font())
        place(self.type_box, 9, 372, 230, 22)
        place(self.cb_adv, 9, 398, 115, 22)

        def choose(_event):
            selected = tree.selection()
            if selected and selected[0].startswith('type-') and self.v_hired.get():
                key = int(selected[0].partition('-')[2])
                if self.v_type.get() != self.labels[key]:
                    self.v_type.set(self.labels[key])
                    self.on_type()

        tree.bind('<<TreeviewSelect>>', choose)

    EDITABLE_FACTS = ('ID', 'Name ID', 'Code')

    def fact_typed(self, caption):
        """A typed ID (hex) / Name ID / Code box: sets the matching control (the page's values) at once."""
        if self.busy or not self.v_hired.get():
            return
        text = self.facts[caption].get()
        if caption == 'ID':
            self.v_seed.set(text.strip().upper())
        elif caption == 'Name ID':
            n = self._int(text)
            if n is None or not 0 <= n <= 0xFFFF:
                return
            self._fill_names(n)
        else:
            n = self._int(text)
            if n is None or not 0 <= n <= 0xFFFF:
                return
            name = self.cur_name()
            self.raw_type = n
            self.v_type.set(self.labels[n] if n in self.labels else T('merc.type_unknown', 'unknown type {n}', n=n))
            self._fill_names(name if n not in self.types or name < len(self.types[n].names) else 0)
            self.on_level()
            return
        self.changed()

    def _wrap(self, e):
        if self.vanilla_he:
            return
        w = max(240, min(560, e.width - 40))
        for lab in self.box.grid_slaves():
            if isinstance(lab, tk.Label) and lab.cget('wraplength'):
                lab.configure(wraplength=w)

    # ---- widgets <-> values
    def cur_type(self):
        s = self.v_type.get()
        return next((i for i in self.ids if self.labels[i] == s), self.raw_type)

    def cur_name(self):
        h = self.types.get(self.cur_type())
        s = self.v_name.get()
        if h is not None and s in h.names:
            i = self.name_box.current()
            return i if 0 <= i < len(h.names) and h.names[i] == s else h.names.index(s)
        try:
            return int(s.lstrip('#'))
        except ValueError:
            return self.rec['name']

    def xpl(self):
        h = self.types.get(self.cur_type())
        return h.exp_per_level if h is not None else 1

    @staticmethod
    def _int(s, base=10):
        try:
            return int(s.strip().replace(' ', ''), base)
        except ValueError:
            return None

    def values(self):
        """The record the widgets describe, or None while a box holds something unusable."""
        if not self.v_hired.get():
            return dict(dead=0, id=0, name=0, type=0, exp=0)
        exp, seed = self._int(self.v_exp.get()), self._int(self.v_seed.get(), 16)
        if exp is None or not 0 <= exp <= MAX_EXP or seed is None or not 0 < seed <= MAX_EXP:
            return None
        dead = self.v_dead.get()
        return dict(dead=(self.rec['dead'] or 1) if dead else 0, id=seed, name=self.cur_name(), type=self.cur_type(), exp=exp)

    def _fill_names(self, name):
        h = self.types.get(self.cur_type())
        names = h.names if h is not None else []
        self.name_box.configure(values=names)
        if 0 <= name < len(names):
            self.name_box.current(name)
        else:
            self.v_name.set(f'#{name}')

    def refresh(self):
        """Shows win.ch again; pending edits are forgotten."""
        ch = self.win.ch
        self.rec = rec = record(ch)
        self.was_hired = rec['id'] != 0
        self.raw_type = rec['type']
        self.busy = True
        self.v_hired.set(self.was_hired)
        self.v_dead.set(bool(rec['dead']))
        if self.was_hired:
            self._show(rec)
        else:
            self._defaults()
        self.busy = False
        self._state()

    def rebase(self):
        """win.ch was written / read again without this page's edits (see mxl_char_gui.EXTRA_PAGES): the boxes
        keep what was typed, the record of the file is the new reference."""
        self.rec = record(self.win.ch)
        self.was_hired = self.rec['id'] != 0
        self._state()

    def _show(self, rec):
        h = self.types.get(rec['type'])
        self.v_type.set(self.labels[rec['type']] if h is not None else T('merc.type_unknown', 'unknown type {n}', n=rec['type']))
        self._fill_names(rec['name'])
        self.v_exp.set(str(rec['exp']))
        self.v_level.set(str(level_for_exp(self.xpl(), rec['exp'])))
        self.v_seed.set(f"{rec['id']:08X}")

    def _defaults(self):
        """What "Hired" starts from on a character without a mercenary: the first type, at the character's level."""
        if not self.ids:
            return
        self.raw_type = self.ids[0]
        h = self.types[self.raw_type]
        lv = max(1, min(self.win.ch.level, max_level(h.exp_per_level)))
        self._show(dict(dead=0, id=new_seed(), name=0, type=self.raw_type, exp=exp_for_level(h.exp_per_level, lv)))

    def _state(self):
        on = self.v_hired.get()
        for w in (self.cb_dead, self.e_level, self.e_exp, self.b_match, self.e_seed, self.b_seed):
            w.configure(state='normal' if on else 'disabled')
        for w in (self.type_box, self.name_box):
            w.configure(state='readonly' if on else 'disabled')
        self.cb_hired.configure(state='normal' if self.ids and self.win.ch.has_jf else 'disabled')
        ch = self.win.ch
        n = len(ch.merc_items or [])
        if not self.ids:
            text = T('merc.no_table', 'The game table "hireling" was not found: the mercenary cannot be edited.')
        elif not on and self.was_hired:
            text = T('merc.will_dismiss', 'SAVE dismisses the mercenary.') + (
                ' ' + T('merc.err.items', 'the mercenary still wears {n} item(s): move them to the character or '
                        'the stash first', n=n) if n else '')
        elif not on:
            text = T('merc.none', 'This character has no mercenary. Tick "Hired" to give it one.')
        elif not self.was_hired:
            text = T('merc.will_hire', 'SAVE hires this mercenary (no equipment).')
        else:
            v = self.values()
            lv = level_for_exp(self.xpl(), v['exp']) if v else None
            text = T('merc.summary', 'Wears {n} item(s). Character level {cl}.', n=n, cl=ch.level)
            if lv is not None and lv > ch.level:
                text += ' ' + T('merc.above', 'Level {lv} is above the character\'s.', lv=lv)
        self.info.configure(text=text)
        if self.vanilla_he:
            from mxl_char import difficulty_name

            self.v_life.set(('Dead' if self.v_dead.get() else 'Alive') if on else 'Not Hired')
            for button in self.life_buttons:
                button.state(['!disabled'] if self.ids and ch.has_jf else ['disabled'])
            if self.ids and ch.has_jf and not on:
                text = 'Select Alive to hire a mercenary.'
                self.info.configure(text=text)
            kind = self.types.get(self.cur_type())
            self.vanilla_seed.state(['!disabled'] if on else ['disabled'])
            self.refresh_portrait()
            mode = difficulty_name(kind.diff - 1) if kind is not None and 1 <= kind.diff <= 3 else ''
            code = self.cur_type() if on else ''
            values = {'ID': self.v_seed.get(), 'Name ID': str(self.cur_name()), 'Code': str(code),
                      'Name': self.v_name.get(), 'Attributes': kind.variant if kind is not None else '',
                      'Difficulty': mode} if on else {}
            focus = self.facts_focus()
            for caption, entry in self.facts.items():
                if caption in self.EDITABLE_FACTS:
                    entry.configure(state='normal' if on else 'disabled')
                    if entry is focus:                      # being typed in: leave the text alone
                        continue
                    entry.configure(state='normal')
                else:
                    entry.configure(state='normal')
                entry.delete(0, 'end')
                entry.insert(0, values.get(caption, ''))
                entry.configure(state='normal' if caption in self.EDITABLE_FACTS and on else 'readonly')
            lv = self._int(self.v_level.get())
            stats = base_stats(kind, lv) if on and kind is not None and lv is not None else None
            shown = {} if stats is None else {
                'Strength': stats['strength'], 'Dexterity': stats['dexterity'], 'Life': stats['life'],
                'Damage': f"{stats['dmg_min']}-{stats['dmg_max']}", 'Defense': stats['defense'],
                'Resists': f"{stats['resist']}%"}
            for caption, entry in self.base_stats.items():
                entry.configure(state='normal')
                entry.delete(0, 'end')
                entry.insert(0, str(shown.get(caption, '')))
                entry.configure(state='readonly')

    def facts_focus(self):
        try:
            return self.box.focus_get()
        except Exception:
            return None

    def refresh_portrait(self):
        from mxl_vanilla_he import photo, picture, pixels

        kind = self.types.get(self.cur_type()) if self.v_hired.get() else None
        offset = {1: 0, 2: 270, 3: 180, 5: 90}.get(kind.act) if kind is not None else None
        artwork = picture('merc_portraits') if offset is not None else None
        view = self.vanilla_portrait
        signature = artwork, offset, kind.cls_name if kind is not None else ''
        if getattr(view, 'art_signature', None) == signature:
            return
        view.art_signature = signature
        view.image = (photo(view, artwork.crop((offset, 0, offset + 90, 90)), pixels(view, 90, 90))
                      if artwork is not None else None)
        view.configure(image=view.image or '', text='' if view.image else signature[2])

    def _change_life(self):
        life = self.v_life.get()
        self.v_hired.set(life != 'Not Hired')
        self.v_dead.set(life == 'Dead')
        self.on_hired()

    def show_adv(self):
        if self.vanilla_he:
            from mxl_vanilla_he import pixels

            if self.v_adv.get():
                x, y = pixels(self.box, 5, 402)
                self.adv.place(x=x, y=y)
            else:
                self.adv.place_forget()
            return
        if self.v_adv.get():
            self.adv.grid(row=self.adv_row, column=1, columnspan=4, sticky='w', pady=1)
        else:
            self.adv.grid_forget()

    # ---- edits
    def changed(self):
        if self.busy:
            return
        self._state()
        self.win.update_dirty()

    def on_hired(self):
        if self.v_hired.get() and not self.was_hired and not self.v_type.get():
            self._defaults()
        self.changed()

    def on_type(self):
        """Another type: the name number is kept when the new type has it, the level is kept (its experience)."""
        self.raw_type = self.cur_type()
        name = self.rec['name'] if self.was_hired else 0
        h = self.types.get(self.raw_type)
        cur = self.name_box.current()
        if cur >= 0:
            name = cur
        self._fill_names(name if h is None or name < len(h.names) else 0)
        self.on_level()

    def on_level(self):
        if self.busy:
            return
        lv, exp = self._int(self.v_level.get()), self._int(self.v_exp.get())
        if lv is not None and 1 <= lv <= max_level(self.xpl()):
            if exp is None or level_for_exp(self.xpl(), exp) != lv:      # experience inside the level is kept
                self.v_exp.set(str(exp_for_level(self.xpl(), lv)))
        self.changed()

    def on_exp(self):
        if self.busy:
            return
        exp = self._int(self.v_exp.get())
        if exp is not None and 0 <= exp <= MAX_EXP:
            self.v_level.set(str(level_for_exp(self.xpl(), exp)))
        self.changed()

    def match_level(self):
        self.v_level.set(str(max(1, min(self.win.ch.level, max_level(self.xpl())))))
        self.on_level()

    # ---- the window's page interface
    def dirty(self):
        v = self.values()
        if v is None:
            return True
        if not self.was_hired:
            return bool(self.v_hired.get())
        return v != self.rec

    def apply(self):
        if not self.dirty():
            return
        ch = self.win.ch
        v = self.values()
        if v is None:
            raise CharError(T('merc.err.typed', 'Mercenary: the experience must be a number up to 4294967295 and the '
                              'id a non-zero hexadecimal number of up to 8 digits'))
        if not v['id']:
            if self.was_hired:
                dismiss(ch)
        elif not self.was_hired:
            hire(ch, v['type'], v['name'], v['exp'], v['id'])
        else:
            set_record(ch, **v)

    def set_theme(self, dark):
        from mxl_char_gui import THEMES
        t = THEMES[bool(dark)]

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
                                selectcolor=t['entry'], highlightthickness=0)
                elif cls == 'Button':
                    w.configure(bg=t['btn'], fg=t['fg'], activebackground=t['btn'], activeforeground=t['fg'])
                elif cls in ('Entry', 'Spinbox'):
                    w.configure(bg=t['entry'], fg=t['entry_fg'], insertbackground=t['entry_fg'],
                                disabledbackground=t['bg'], disabledforeground=t['box_mid'])
                    if cls == 'Spinbox':
                        w.configure(buttonbackground=t['btn'], readonlybackground=t['entry'])
            except tk.TclError:
                pass
            for c in w.winfo_children():
                walk(c)
        walk(self.frame)


def install():
    """Registers the page (before the Character window is built)."""
    import mxl_char_gui
    mxl_char_gui.register_page('merc', T('merc.title', 'Mercenary'), MercPage)
