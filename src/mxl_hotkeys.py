"""Character window page "Hotkeys": the 16 skill hotkeys and the four mouse-button skills of the save header.

Header layout (docs/SAVE_FORMAT.md; checked on the XBone samples, see the notes below):
    0x38  16 x u32   skill hotkeys: skill id, + 0x8000 when the key puts the skill on the LEFT button,
                     0x0000FFFF = empty slot
    0x78  u32        left mouse skill          0x7C  u32  right mouse skill
    0x80  u32        left skill, weapon set II 0x84  u32  right skill, weapon set II
What the samples show: an empty slot is 0x0000FFFF (never 0xFFFFFFFF); the high word is always 0; the only
two hotkeys carrying 0x8000 (372 Widowmaker, 1751 Tantrum) are the two skills found on the left button in the
three states, while another left-capable skill (377) sits on a hotkey without it: the bit is the hand of the
assignment, not a property of the skill. Skills granted by items (oskill stat 97: 1751 from the equipped
weapon, 551 from an inventory charm) and the innate Town Portal (1638) are stored as plain skill ids like class
skills. Not seen in a sample, taken from vanilla Diablo II: charge skills (stat 204) stored the same way, that
a mouse slot always holds a skill (0 = Attack), and that the game drops skills the character cannot use.

Engine (plain functions on a mxl_char.Character, through its header_u32 accessors):
    hotkey(ch, i) -> (skill id or None, left)       set_hotkey(ch, i, sid, left=False)   (sid None: empty)
    mouse_skill(ch, k) -> skill id                   set_mouse_skill(ch, k, sid)          (k: index into MOUSE)
    left_ok(data, sid) / passive(data, sid)          the skills table's 'leftskill' / 'passive' bits
    usable_skills(ch, data, levels=None)             {skill id: source text} the character can use
    key_names(path)                                  the keys bound to the 16 hotkeys in <name>.key ('' = none)
The page keeps its edits pending ({header offset: u32}) until SAVE calls apply().
"""
import os
import struct
import tkinter as tk

import mxl_char as MC
from mxl_lang import T

HOTKEY_OFF = 0x38
HOTKEYS = 16
EMPTY = 0xFFFF
LEFT_FLAG = 0x8000
MOUSE = (0x78, 0x7C, 0x80, 0x84)          # left, right, left of weapon set II, right of weapon set II
MOUSE_LEFT = (True, False, True, False)
ATTACK = 0
TOWN_PORTAL = 1638                         # innate in Median XL (on a hotkey of the samples, granted by no item)
STAT_OSKILL, STAT_CHARGES = 97, 204
# <name>.key: the key functions of "skill 1" .. "skill 16" (vanilla order; 14-21 hold F1-F8 in the samples,
# 46-53 are unbound there: taken as skills 9-16 like in vanilla 1.10+)
KEY_FUNCTIONS = tuple(range(14, 22)) + tuple(range(46, 54))
ICON = 36


# ============================================================================================ engine
def _u32(ch, off):
    return ch.header_u32(off)


def decode_hotkey(raw):
    """(skill id or None, left-button flag) of a hotkey dword."""
    if raw & 0xFFFF == EMPTY:
        return None, False
    return raw & 0x7FFF, bool(raw & LEFT_FLAG)


def encode_hotkey(sid, left=False):
    if sid is None:
        return EMPTY
    if not 0 <= sid < LEFT_FLAG - 1:
        raise MC.CharError(T('hk.err.id', 'skill id {id} does not fit into a hotkey', id=sid))
    return sid | (LEFT_FLAG if left else 0)


def hotkey(ch, i):
    return decode_hotkey(_u32(ch, HOTKEY_OFF + 4 * i))


def set_hotkey(ch, i, sid, left=False):
    if not 0 <= i < HOTKEYS:
        raise MC.CharError(T('hk.err.slot', 'no such hotkey: {n}', n=i + 1))
    ch.set_header_u32(HOTKEY_OFF + 4 * i, encode_hotkey(sid, left))


def mouse_skill(ch, k):
    return _u32(ch, MOUSE[k])


def set_mouse_skill(ch, k, sid):
    if not 0 <= sid <= 0xFFFF:
        raise MC.CharError(T('hk.err.id', 'skill id {id} does not fit into a hotkey', id=sid))
    ch.set_header_u32(MOUSE[k], sid)


def _flags(data, sid):
    rows = data._rows('skills')
    return struct.unpack_from('<I', rows[sid], 4)[0] if 0 <= sid < len(rows) else 0


def left_ok(data, sid):
    """skills table 'leftskill' (flag bit 30): the skill may sit on the left mouse button."""
    return bool(_flags(data, sid) >> 30 & 1)


def passive(data, sid):
    return bool(_flags(data, sid) >> 4 & 1)


def skill_name(data, sid):
    if sid == ATTACK:
        return T('hk.attack', 'Attack')
    nm = data.skill_names.get(sid) or ''
    if not nm or 'OLAR BUFFALO' in nm.upper():
        nm = T('skill.unknown', 'skill #{id}', id=sid)
    return nm


def usable_skills(ch, data, levels=None):
    """{skill id: source} - what the character can put on a key: Attack, Town Portal, the class skills with at
    least one point (levels: {sid: level}, default the saved ones) and the skills granted by items: oskills
    (stat 97) and charges (stat 204) of the equipped items (both weapon sets) and of the items in the
    inventory (charms). Passive skills are left out."""
    out = {ATTACK: '', TOWN_PORTAL: ''}
    if levels is None:
        levels = ch.skill_levels()
    for sid, lv in levels.items():
        if lv > 0 and not passive(data, sid):
            out[sid] = ''
    try:
        import mxl_tooltip
        for e in ch.items:
            it = e.it
            worn = it['location'] == MC.LOC_EQUIPPED
            if not worn and not (it['location'] == MC.LOC_STORED and it['panel'] == MC.PANEL_INVENTORY):
                continue
            src = T('hk.src.item', 'item') if worn else T('hk.src.charm', 'inventory')
            for s in mxl_tooltip.all_stats(it, data):
                if s.get('id') == STAT_OSKILL:
                    sid = s.get('param')
                elif s.get('id') == STAT_CHARGES:
                    sid = (s.get('param') or 0) >> 6
                    src = T('hk.src.charges', 'charges')
                else:
                    continue
                if isinstance(sid, int) and sid > 0 and sid not in out and not passive(data, sid):
                    out[sid] = src
    except Exception as e:
        print('hotkeys: item skills not listed:', e)
    return out


_VK = {0x08: 'Backspace', 0x09: 'Tab', 0x0D: 'Enter', 0x10: 'Shift', 0x11: 'Ctrl', 0x12: 'Alt', 0x14: 'Caps',
       0x1B: 'Esc', 0x20: 'Space', 0x21: 'PgUp', 0x22: 'PgDn', 0x23: 'End', 0x24: 'Home', 0x25: 'Left', 0x26: 'Up',
       0x27: 'Right', 0x28: 'Down', 0x2C: 'PrtSc', 0x2D: 'Ins', 0x2E: 'Del', 0xBA: ';', 0xBB: '=', 0xBC: ',',
       0xBD: '-', 0xBE: '.', 0xBF: '/', 0xC0: '`', 0xDB: '[', 0xDC: '\\', 0xDD: ']', 0xDE: "'",
       0x100: 'Mouse 3', 0x101: 'Mouse 4', 0x102: 'Mouse 5', 0x103: 'Wheel up', 0x104: 'Wheel down'}


def vk_name(vk):
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return 'Num ' + str(vk - 0x60)
    if 0x70 <= vk <= 0x87:
        return 'F' + str(vk - 0x6F)
    return _VK.get(vk) or f'key {vk:#x}'


def key_names(path):
    """The keys bound to skill 1-16 in the character's .key file (u16 version, 10-byte records: u32 function,
    u16 key, u32 slot), '' for an unbound one; None when there is no readable file."""
    try:
        with open(os.path.splitext(path)[0] + '.key', 'rb') as f:
            b = f.read()
    except OSError:
        return None
    body = 6 if b[:2] == b'WS' else 2
    if len(b) < body or (len(b) - body) % 10:
        return None
    keys = {}
    for o in range(body, len(b), 10):
        fn, vk, _slot = struct.unpack_from('<IHI', b, o)
        if vk != 0xFFFF:
            keys.setdefault(fn, []).append(vk_name(vk))
    return ['/'.join(keys.get(fn, [])) for fn in KEY_FUNCTIONS]


# ============================================================================================ page
class HotkeysPage:
    def __init__(self, win, frame):
        import mxl_attr_picker as AP
        self.AP = AP
        self.win, self.frame = win, frame
        self.pending = {}                  # header offset -> u32
        self.cells = {}                    # header offset -> widgets
        self._icons = {}
        self._shared = None
        self._blank = tk.PhotoImage(master=frame, width=ICON, height=ICON)
        self._press = None
        self._usable = None
        self._keys_of = None
        self.m = AP.metrics(frame)
        self.all_skills = tk.BooleanVar(master=frame, value=False)
        AP.exempt(frame)
        self.dark = bool(getattr(win, 'dark', None) and win.dark.get())
        self._build()
        self.set_theme(self.dark)
        self.refresh()

    # ------------------------------------------------------------------ values
    def value(self, off):
        return self.pending.get(off, self.win.ch.header_u32(off))

    def _set(self, off, raw):
        if raw == self.win.ch.header_u32(off):
            self.pending.pop(off, None)
        else:
            self.pending[off] = raw

    def skill_at(self, off):
        """(skill id or None, left) of a slot (a mouse slot: its own button)."""
        raw = self.value(off)
        if off in MOUSE:
            return raw, MOUSE_LEFT[MOUSE.index(off)]
        return decode_hotkey(raw)

    def dirty(self):
        ch = self.win.ch
        return any(ch.header_u32(off) != raw for off, raw in self.pending.items())

    def apply(self):
        ch = self.win.ch
        for off, raw in sorted(self.pending.items()):
            if off in MOUSE:
                set_mouse_skill(ch, MOUSE.index(off), raw)
            else:
                sid, left = decode_hotkey(raw)
                set_hotkey(ch, (off - HOTKEY_OFF) // 4, sid, left)

    def refresh(self):
        """The character was loaded, saved or RELOAD was pressed: nothing is pending."""
        self.pending = {}
        self._usable = None
        self._redraw()
        self.warn.configure(text='')

    def rebase(self):
        """win.ch was written / read again without this page's edits (an item action, see
        mxl_char_gui.EXTRA_PAGES): edits already in the file are forgotten, the others stay pending."""
        ch = self.win.ch
        self.pending = {off: raw for off, raw in self.pending.items() if ch.header_u32(off) != raw}
        self._usable = None
        self._redraw()
        if self.pending:
            self._after_idle_preview()

    # ------------------------------------------------------------------ widgets
    def _build(self):
        m, f = self.m, self.frame
        self.box = tk.Frame(f)
        self.box.pack(fill='x', anchor='n', padx=4, pady=2)
        for c in range(4):
            self.box.columnconfigure(c, weight=1, uniform='hk')
        self.heads = []
        h = tk.Label(self.box, text=T('hk.mouse', 'Mouse buttons (I, II: weapon set)'), font=m['bold'], anchor='w')
        h.grid(row=0, column=0, columnspan=4, sticky='we')
        self.heads.append(h)
        names = (T('hk.left', 'Left I'), T('hk.right', 'Right I'), T('hk.left2', 'Left II'), T('hk.right2', 'Right II'))
        for k, off in enumerate(MOUSE):
            self._cell(off, names[k], 1, k)
        h = tk.Label(self.box, text=T('hk.keys', 'Skill hotkeys'), font=m['bold'], anchor='w')
        h.grid(row=2, column=0, columnspan=4, sticky='we', pady=(3, 0))
        self.heads.append(h)
        for i in range(HOTKEYS):                       # column-wise: 1-4 under each other, like a list
            self._cell(HOTKEY_OFF + 4 * i, str(i + 1), 3 + i % 4, i // 4)
        bar = self.bar = tk.Frame(f)
        bar.pack(fill='x', anchor='n', padx=4, pady=(2, 0))
        self.chk = tk.Checkbutton(bar, text=T('hk.all', 'All skills in the list'), variable=self.all_skills,
                                  font=m['font'], bd=0, highlightthickness=0, padx=0, pady=0)
        self.chk.pack(side='left')
        self.buttons = [tk.Button(bar, text=T('hk.revert', 'Revert'), command=self.revert),
                        tk.Button(bar, text=T('hk.clear_all', 'Clear all hotkeys'), command=self.clear_all)]
        for b in self.buttons:
            b.configure(font=m['font'], bd=1, padx=6, pady=0, highlightthickness=0, takefocus=0)
            b.pack(side='right', padx=(4, 0))
        self.note = tk.Label(f, font=m['font'], anchor='w', justify='left',
                             text=T('hk.help', 'Click: choose a skill.  Right click: clear.  Drag onto another slot: '
                                    'swap.  L / R: the mouse button a hotkey puts its skill on.'))
        self.note.pack(fill='x', anchor='n', padx=4)
        self.keynote = tk.Label(f, font=m['font'], anchor='w', justify='left')
        self.keynote.pack(fill='x', anchor='n', padx=4)
        self.warn = tk.Label(f, font=m['font'], anchor='w', justify='left')
        self.warn.pack(fill='x', anchor='n', padx=4)
        for w in (self.note, self.keynote, self.warn):      # wrapped to the visible width, not to their own
            w.configure(wraplength=60 * m['ch'])
        try:
            self.win.scroll.canvas.bind('<Configure>', self._wrap, add='+')
        except Exception:
            pass

    def _wrap(self, ev=None):
        try:
            width = ev.width if ev is not None else self.win.scroll.canvas.winfo_width()
        except Exception:
            return
        if width > 200:
            for w in (self.note, self.keynote, self.warn):
                w.configure(wraplength=width - 12)

    def _cell(self, off, title, row, col):
        m = self.m
        fr = tk.Frame(self.box, bd=0, highlightthickness=1, cursor='hand2')
        fr.grid(row=row, column=col, sticky='we', padx=1, pady=1)
        fr.columnconfigure(1, weight=1)
        icon = tk.Label(fr, image=self._blank, bd=0, width=ICON, height=ICON)
        icon.grid(row=0, column=0, rowspan=2, padx=(1, 3), pady=1)
        head = tk.Label(fr, text=title, font=m['font'], anchor='w', bd=0, pady=0, width=6)
        head.grid(row=0, column=1, sticky='we')
        name = tk.Label(fr, text='', font=m['bold'], anchor='w', bd=0, pady=0, width=6)
        name.grid(row=1, column=1, sticky='we')
        hand = None
        if off not in MOUSE:
            hand = tk.Label(fr, text='', font=m['bold'], width=2, bd=1, relief='raised', cursor='hand2')
            hand.grid(row=0, column=2, rowspan=2, padx=(0, 2))
            hand.bind('<Button-1>', lambda _e, o=off: self.toggle_hand(o))
        ws = [fr, icon, head, name]
        for w in ws:
            w.bind('<ButtonPress-1>', lambda e, o=off: self._down(o))
            w.bind('<ButtonRelease-1>', lambda e, o=off: self._up(o, e))
            w.bind('<Button-3>', lambda e, o=off: self.clear(o))
            w.bind('<Enter>', lambda e, o=off: self._tip(o), add='+')
            w.bind('<Leave>', lambda e: self._tip(None), add='+')
            w._hk_off = off
        if hand is not None:
            hand._hk_off = off
        name.bind('<Configure>', lambda e, o=off: self._fit_name(o), add='+')
        self.cells[off] = dict(frame=fr, icon=icon, head=head, name=name, hand=hand, title=title, text='')

    def set_theme(self, dark):
        self.dark = dark = bool(dark)
        try:
            import mxl_char_gui
            t = mxl_char_gui.THEMES[dark]
        except Exception:
            t = dict(bg='#f0f0f0', fg='#000000', pane='#ffffff', pane_fg='#000000', btn='#e1e1e1', entry='#ffffff')
        self.t = t
        dim = '#8a7a4a' if dark else '#606060'
        self.colors = dict(line='#5a4a20' if dark else '#a0a0a0', hot='#d8c27a' if dark else '#3a5f8a', dim=dim,
                           changed='#e8a33c' if dark else '#b05a00', warn='#ff8a7a' if dark else '#b00000')
        self.frame.configure(bg=t['bg'])
        for w in (self.box, self.bar):
            w.configure(bg=t['bg'])
        for w in self.heads:
            w.configure(bg=t['bg'], fg=t['fg'])
        self.note.configure(bg=t['bg'], fg=dim)
        self.keynote.configure(bg=t['bg'], fg=dim)
        self.warn.configure(bg=t['bg'], fg=self.colors['warn'])
        self.chk.configure(bg=t['bg'], fg=t['fg'], activebackground=t['bg'], activeforeground=t['fg'],
                           selectcolor=t['entry'])
        for b in self.buttons:
            b.configure(bg=t['btn'], fg=t['fg'], activebackground=t['btn'], activeforeground=t['fg'])
        for c in self.cells.values():
            c['frame'].configure(bg=t['pane'], highlightbackground=self.colors['line'],
                                 highlightcolor=self.colors['line'])
            c['icon'].configure(bg=t['pane'])
            c['head'].configure(bg=t['pane'], fg=dim)
            c['name'].configure(bg=t['pane'])
            if c['hand'] is not None:
                c['hand'].configure(bg=t['btn'], fg=t['fg'])
        self._redraw()

    # ------------------------------------------------------------------ drawing
    def _shared_icon(self, sid):
        """Icon of a skill outside the class trees (oskills, Attack, Town Portal): its skilldesc cel in the
        game's icons-shared.dc6 (the Skills page's loader covers the class trees only)."""
        import settings
        import paths
        import mxl_d2look_art
        import mxl_d2ui_dc6 as DC6
        data = self.win.data
        if self._shared is None:
            gd = settings.get('game_dir')
            if not gd or not os.path.isdir(gd):
                self._shared = ()
            else:
                art = mxl_d2look_art.get_art(gd, 'classic_sigma', os.path.join(paths.USER_DIR, 'ui_art'))
                self._shared = (DC6.dc6_frames(art.read('data\\global\\themes\\classic_sigma\\game\\skills\\'
                                                        'icons-shared.dc6')), art.pal())
        if not self._shared:
            return None
        cels, pal = self._shared
        srows, sd_rows = data._rows('skills'), data._rows('skilldesc')
        sd = struct.unpack_from('<H', srows[sid], 404)[0]
        if not (sid == ATTACK or 0 < sd < len(sd_rows)):
            return None
        cel = struct.unpack_from('<H', sd_rows[sd], 22)[0]
        if cel >= len(cels):
            return None
        w, h, rgba = DC6.to_rgba(cels[cel], pal)
        return tk.PhotoImage(data=DC6.png(w, h, rgba), master=self.frame).zoom(3, 3).subsample(4, 4)

    def _icon(self, sid):
        """The skill's icon (36 px): from the Skills page's loader for a class skill, None when there is none."""
        if sid is None:
            return None
        if sid not in self._icons:
            img = None
            try:
                cls = self.win.data.skill_class.get(sid, 255)
                if cls < 7:                         # the Skills page's own icons (PIL, 48 px) of the class shown
                    tree = getattr(self.win, 'sktree', None)
                    big = tree.icon(self.win._theme_art(), sid) if tree is not None and tree.cls == cls else None
                    if big is not None:
                        from PIL import Image, ImageTk
                        img = ImageTk.PhotoImage(big.resize((ICON, ICON), Image.LANCZOS), master=self.frame)
                elif sid < len(self.win.data._rows('skills')):
                    img = self._shared_icon(sid)
            except Exception as e:
                print('hotkeys: no icon:', e)
            self._icons[sid] = img
        return self._icons[sid]

    def _keys(self):
        path = self.win.ch.path
        if self._keys_of is None or self._keys_of[0] != path:
            self._keys_of = (path, key_names(path))
        return self._keys_of[1]

    def _fit_name(self, off):
        """The skill name, cut to the label's width."""
        c = self.cells[off]
        text, lab, font = c['text'], c['name'], self.m['bold']
        w = lab.winfo_width() - 2
        if w > 20 and font.measure(text) > w:
            while len(text) > 1 and font.measure(text + '...') > w:
                text = text[:-1]
            text += '...'
        if lab.cget('text') != text:
            lab.configure(text=text)

    def _redraw(self):
        if not getattr(self, 't', None):
            return
        data, ch = self.win.data, self.win.ch
        keys = self._keys()
        self._wrap()
        for off, c in self.cells.items():
            sid, left = self.skill_at(off)
            changed = off in self.pending and self.pending[off] != ch.header_u32(off)
            title = c['title']
            if off not in MOUSE and keys:
                k = keys[(off - HOTKEY_OFF) // 4]
                if k:
                    title += '  ·  ' + k
            c['head'].configure(text=title)
            c['text'] = skill_name(data, sid) if sid is not None else T('hk.empty', '(empty)')
            c['name'].configure(fg=self.colors['changed'] if changed else
                                (self.colors['dim'] if sid is None else self.t['pane_fg']))
            c['name'].configure(text=c['text'])
            self._fit_name(off)
            c['icon'].configure(image=self._icon(sid) or self._blank)
            if c['hand'] is not None:
                c['hand'].configure(text='' if sid is None else ('L' if left else 'R'),
                                    relief='flat' if sid is None else 'raised',
                                    bg=self.t['pane'] if sid is None else self.t['btn'])
        if keys is None:
            note = ''
        else:
            note = T('hk.keynote', 'Keys: from {file} (the vanilla key file; Median XL Sigma may use its own key '
                     'settings instead).', file=os.path.basename(os.path.splitext(ch.path)[0] + '.key'))
        self.keynote.configure(text=note)

    def _tip(self, off):
        try:
            if off is None:
                self.win._sk_tip('')
                return
            sid, left = self.skill_at(off)
            if sid is None:
                self.win._sk_tip('')
                return
            data = self.win.data
            lines = [f'{skill_name(data, sid)}  (#{sid})']
            src = self._usable_now().get(sid)
            if src is None:
                lines.append(T('hk.tip.unusable', 'not among the skills the character can use'))
            elif src:
                lines.append(T('hk.tip.from', 'granted by: {src}', src=src))
            if off not in MOUSE:
                lines.append(T('hk.tip.left', 'goes to the left button') if left else
                             T('hk.tip.right', 'goes to the right button'))
            self.win._sk_tip('\n'.join(lines))
        except Exception:
            pass

    # ------------------------------------------------------------------ edits
    def _usable_now(self):
        if self._usable is None:
            win, levels = self.win, None
            try:                                   # the levels typed on the Skills page count already
                if getattr(win, 'pending_cls', None) is None and win.sk_vars:
                    levels = {sid: win._level_of(v) for sid, v in win.sk_vars.items()}
            except Exception:
                levels = None
            self._usable = usable_skills(win.ch, win.data, levels)
        return self._usable

    def _changed(self, off=None, warn=''):
        self._redraw()
        self._preview()
        self.win.update_dirty()
        if off is not None and not warn:
            warn = self.warning(off)
        self.warn.configure(text=warn)
        if warn:
            try:
                self.win.set_bar(warn, error=True)
            except Exception:
                pass

    def _preview(self):
        """The stat screen draws the mouse skills of the window's scratch character: it gets the pending
        values, so its two icons follow before SAVE (the scratch header differing from the file's is what
        the window already calls 'unsaved')."""
        win = self.win
        try:
            sim = win.st_sim
            for off in MOUSE + tuple(HOTKEY_OFF + 4 * i for i in range(HOTKEYS)):
                struct.pack_into('<I', sim.head, off, self.value(off))
            scr = getattr(win, 'statscreen', None)
            if scr is not None:
                scr.redraw()
        except Exception as e:
            print('hotkeys: stat screen not refreshed:', e)

    def _after_idle_preview(self):
        try:                                       # refresh() runs before the window rebuilds its scratch copy
            self.frame.after_idle(self._preview)
        except tk.TclError:
            pass

    def warning(self, off):
        """Why the game may not accept the slot as it is ('' = nothing to say)."""
        sid, left = self.skill_at(off)
        if sid is None:
            return ''
        data = self.win.data
        name = skill_name(data, sid)
        if passive(data, sid):
            return T('hk.warn.passive', '{skill} is a passive skill: the game does not put it on a button.', skill=name)
        if left and not left_ok(data, sid):
            return T('hk.warn.left', '{skill} cannot be used on the left mouse button in the game (right button '
                     'only): the game will probably drop it.', skill=name)
        if sid not in self._usable_now():
            return T('hk.warn.unusable', '{skill}: the character has no point in it and no item grants it - the '
                     'game will probably drop it.', skill=name)
        return ''

    def assign(self, off, sid, left=None):
        """Puts a skill on a slot (sid None: empties a hotkey / puts Attack on a mouse button)."""
        if off in MOUSE:
            self._set(off, ATTACK if sid is None else sid)
        else:
            if left is None:                       # the hand the slot had; a new one: right, the button every
                old, left = self.skill_at(off)     # skill is allowed on
                if old is None:
                    left = False
            self._set(off, encode_hotkey(sid, left and sid is not None))
        self._changed(off)

    def clear(self, off):
        self.assign(off, None)

    def toggle_hand(self, off):
        sid, left = self.skill_at(off)
        if sid is not None and off not in MOUSE:
            self.assign(off, sid, not left)
        return 'break'

    def swap(self, a, b):
        """Exchanges two slots. Between a hotkey and a mouse button the skill moves and the hotkey takes the
        button's hand; an empty hotkey leaves Attack on the button."""
        sa, la = self.skill_at(a)
        sb, lb = self.skill_at(b)
        for off, sid, left in ((a, sb, lb), (b, sa, la)):
            if off in MOUSE:
                self._set(off, ATTACK if sid is None else sid)
            else:
                self._set(off, encode_hotkey(sid, left and sid is not None))
        self._changed(warn=self.warning(a) or self.warning(b))

    def clear_all(self):
        for i in range(HOTKEYS):
            self._set(HOTKEY_OFF + 4 * i, EMPTY)
        self._changed()

    def revert(self):
        self.pending.clear()
        self._changed()

    # ------------------------------------------------------------------ mouse
    def _down(self, off):
        self._press = off

    def _up(self, off, ev):
        src, self._press = self._press, None
        if src is None:
            return
        try:
            w = self.frame.winfo_containing(ev.x_root, ev.y_root)
        except (tk.TclError, KeyError):
            w = None
        dst = getattr(w, '_hk_off', None)
        if dst is None or dst == src:
            if dst == src:
                self.pick(src)
        else:
            self.swap(src, dst)

    def choices(self, off):
        """[(list text, skill id)] for the picker of a slot."""
        data = self.win.data
        if self.all_skills.get():
            from mxl_statnames import skill_names_sorted
            out = [(f'{skill_name(data, ATTACK)}  #{ATTACK}', ATTACK)]
            out += [(f'{n}  #{k}', k) for n, k in skill_names_sorted(data) if k != ATTACK]
            return out
        use = dict(self._usable_now())
        for o in self.cells:                        # what is on a slot now stays choosable
            sid = self.skill_at(o)[0]
            if sid is not None and sid not in use:
                use[sid] = T('hk.src.assigned', 'assigned, not usable')
        rows = [(skill_name(data, sid), sid, src) for sid, src in use.items()]
        rows.sort(key=lambda r: (r[1] != ATTACK, r[0].lower(), r[1]))
        return [(f'{n}  #{sid}' + (f'  ({src})' if src else ''), sid) for n, sid, src in rows]

    def pick(self, off):
        self._tip(None)
        rows = self.choices(off)
        clear = T('hk.pick.clear', '(clear slot)')
        by_name = {n: sid for n, sid in rows}
        cur = self.skill_at(off)[0]
        current = next((n for n, sid in rows if sid == cur), None)
        c = self.cells[off]

        def done(name):
            if name == clear:
                self.clear(off)
            elif name in by_name:
                self.assign(off, by_name[name])
            elif name.startswith('#') and name[1:].isdigit():          # a typed number: that skill id
                sid = int(name[1:])
                if sid < len(self.win.data._rows('skills')):
                    self.assign(off, sid)

        title = T('hk.pick.title', 'Skill for {slot}', slot=c['head'].cget('text'))
        self.popup = self.AP.popup_choices(self.win.top, [clear] + [n for n, _s in rows], done, anchor=c['frame'],
                                           current=current, title=title, numbers=self.all_skills.get())
        return self.popup


def _factory(win, frame):
    return HotkeysPage(win, frame)


def install(App=None):
    import mxl_char_gui
    mxl_char_gui.register_page('hotkeys', T('hk.tab', 'Hotkeys'), _factory)
