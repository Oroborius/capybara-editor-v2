"""More menu -> "New character...": writes a NEW level-N character (.d2s) into the current game's save folder, so
the user does not have to create it in game first.

The file is built from a clean skeleton of the header, quest / waypoint / NPC sections, an empty item list, no
corpse, no mercenary and no golem (the layout of the mock generator in mxl_mock.py and of the Median XL sample
XBone, docs/SAVE_FORMAT.md 1-5), then parsed by mxl_char.Character and finished with its own writers (stats,
skills, quests, waypoints; size and checksum by Character.build). Profile differences: Median XL writes 0x5F at
header 0x2A (vanilla 0x1E) and always has the expansion flag; the skill count (30 / 95) and the stat widths come
from the profile's tables. Starting values: charstats (strength, energy, dexterity, vitality, stamina, life =
vitality + hpadd, mana = energy), then per level gained the editor's level-up rule (Character.set_level: stat
points, 1 skill point, life / mana / stamina per level); experience from the profile's experience table (vanilla
levels 100-127, beyond the table, keep the table's last experience). No items.
Every file is checked by the independent parser (mxlsave) and re-read by Character before it is written; the
write is an exclusive create and refuses a name any file of the folder already uses (companion files included).
"""
import os
import random
import struct
import time

from mxl_lang import T

VANILLA_TOP = 127                      # vanilla: stat 12 has 7 bits (mock characters use 100-127)


class NewCharError(Exception):
    pass


def _median():
    try:
        import mxl_profile
        return mxl_profile.is_median()
    except Exception:
        return True


def top_level(data, cls, median):
    import mxl_char as MC
    top = MC.max_level(data, cls)
    return top if median else max(top, VANILLA_TOP)


def skeleton(data, cls, median, expansion=True):
    """The bytes of an empty level-1 character of the class (name, stats and checksum filled in later)."""
    import mxl_char as MC
    h = bytearray(0x14F)
    struct.pack_into('<IIIII', h, 0, MC.MAGIC, 96, 0, 0, 0)
    h[0x24] = 0x20 if (median or expansion) else 0
    h[0x28] = cls
    h[0x29], h[0x2A], h[0x2B] = 0x10, (0x5F if median else 0x1E), 1
    struct.pack_into('<III', h, 0x2C, 0, int(time.time()) & 0xFFFFFFFF, 0xFFFFFFFF)
    struct.pack_into('<16I', h, 0x38, *([0xFFFF] * 16))         # no hotkeys; mouse skills 0 = Attack
    h[0x88:0xA8] = b'\xff' * 32                                 # appearance: nothing worn
    h[0xA8:0xAB] = b'\x80\x00\x00'                              # last in Normal, act I
    struct.pack_into('<I', h, 0xAB, random.getrandbits(32) | 1)  # map seed of the "last game"
    out = bytes(h)
    out += b'Woo!' + struct.pack('<IH', 6, 298) + bytes(288)
    out += b'WS' + struct.pack('<IH', 1, 80) + (b'\x02\x01' + bytes(22)) * 3
    out += b'\x01w' + struct.pack('<H', 52) + bytes(48)
    out += b'gf\xff\x01'                                        # empty stat list (0x1FF), set below
    out += b'if' + bytes(MC.class_skill_count(data, cls))
    out += b'JM\x00\x00' + b'JM\x00\x00'                        # no items, no corpse
    if median or expansion:
        out += b'jf' + b'kf\x00'                                # no mercenary (id 0), no iron golem
    return out


def _charstats_row(data, cls):
    r = data._rows('charstats')[cls]
    return dict(str=r[0x30], dex=r[0x31], ene=r[0x32], vit=r[0x33], stamina=r[0x34], hpadd=r[0x35])


def build(data, name, cls, level, hardcore=False, expansion=True, unlocked=False, median=None):
    """(bytes, Character) of a new character. Raises NewCharError / mxl_char.CharError."""
    import mxl_char as MC
    median = _median() if median is None else median
    expansion = True if median else bool(expansion)
    MC.check_name(name)
    if not 0 <= cls < 7 or (not expansion and cls >= 5):
        raise NewCharError(T('nc.err.class', 'Druid and Assassin need the expansion.'))
    top = top_level(data, cls, median)
    if not 1 <= level <= top:
        raise NewCharError(T('nc.err.level', 'Level: 1 to {top}', top=top))
    raw = skeleton(data, cls, median, expansion)
    ch = MC.Character.__new__(MC.Character)
    ch.path, ch.data, ch.raw = None, data, raw
    ch.parse(raw)
    ch.set_name(name)
    if hardcore:
        ch.head[0x24] |= 0x04
    b = _charstats_row(data, cls)
    for sid, v in ((0, b['str']), (1, b['ene']), (2, b['dex']), (3, b['vit']),
                   (6, (b['vit'] + b['hpadd']) << 8), (7, (b['vit'] + b['hpadd']) << 8),
                   (8, b['ene'] << 8), (9, b['ene'] << 8), (10, b['stamina'] << 8), (11, b['stamina'] << 8),
                   (12, 1)):
        ch.set_stat(sid, v)
    table_top = MC.max_level(data, cls)
    ch.set_level(min(level, table_top))
    if level > table_top:                          # vanilla 100-127: same rule, experience stays at the top
        cs = MC._charstats(data)[cls]
        n = level - table_top
        ch.head[0x2B] = level
        ch.set_stat(12, level)
        ch.set_stat(4, ch.stat(4) + cs['stats'] * n)
        ch.set_stat(5, ch.stat(5) + n)
        for cur, mx, per in ((6, 7, cs['life']), (8, 9, cs['mana']), (10, 11, cs['stamina'])):
            if per:
                ch.set_stat(mx, ch.stat(mx) + (per << 6) * n)
                ch.set_stat(cur, ch.stat(mx))
    ch.set_waypoints(0, {0})
    if unlocked:
        last = {6, 14, 22, 26} | ({MC.LAST_QUEST_WORD} if expansion else set())
        for d in range(3):
            ch.set_quests(d, last)
            ids = MC.waypoint_ids(d)
            if not median:
                ids = [n for n in ids if n <= (38 if expansion else 29)]
            ch.set_waypoints(d, set(ids))
        ch.head[0x25] = 15 if expansion else 12    # every difficulty finished (expansion 5 / classic 4 each)
    out = ch.build()
    check(out, data)
    return out, ch


def check(raw, data):
    """Refuses bytes the independent parser or the editor's own reader do not accept."""
    import mxl_char as MC
    try:
        import mxl_savecheck
        mxl_savecheck.lib()
        from mxlsave.check import check_bytes
        _obj, problems = check_bytes(raw, 'd2s', mxl_savecheck.tables())
    except ImportError:
        problems = []
    if problems:
        raise NewCharError(T('nc.err.check', 'The new file failed the save check: {p}', p='; '.join(problems[:3])))
    ch = MC.Character.__new__(MC.Character)
    ch.path, ch.data, ch.raw = None, data, raw
    ch.parse(raw)
    if ch.build() != raw:
        raise NewCharError(T('nc.err.reread', 'The new file does not read back identically.'))


def name_taken(folder, name):
    low = name.lower()
    try:
        return any(f.lower().split('.')[0] == low for f in os.listdir(folder))
    except OSError:
        return False


def write(raw, folder, name):
    """Writes <folder>/<name>.d2s (exclusive create; refused when any file of the folder has that name)."""
    os.makedirs(folder, exist_ok=True)
    if name_taken(folder, name):
        raise NewCharError(T('nc.err.exists', 'A character or file named {name} already exists.', name=name))
    path = os.path.join(folder, name + '.d2s')
    with open(path, 'xb') as f:
        f.write(raw)
    return path


def save_folder(app):
    folder = getattr(app, 'save_dir', None)
    if not folder:
        try:
            import mxl_gui
            folder = getattr(mxl_gui, 'SAVE_DIR', None)
        except Exception:
            folder = None
    return folder or os.environ.get('MXL_SAVE_DIR')


# ---------------------------------------------------------------------------------------------------- dialog
def open_dialog(app):
    import tkinter as tk
    from tkinter import ttk, messagebox
    import mxl_char as MC
    root = getattr(app, 'root', None) or tk._default_root
    data = app.data
    median = _median()
    w = tk.Toplevel(root)
    w.title(T('nc.title', 'New character'))
    w.transient(root)
    w.resizable(False, False)
    names = MC.class_names(data)
    name = tk.StringVar()
    cls = tk.StringVar(value=names[0])
    level = tk.StringVar(value='1')
    hc = tk.BooleanVar(value=False)
    exp = tk.BooleanVar(value=True)
    unl = tk.BooleanVar(value=False)
    f = ttk.Frame(w, padding=4)
    f.pack(fill='both', expand=True)
    ttk.Label(f, text=T('nc.name', 'Name')).grid(row=0, column=0, sticky='w', padx=2, pady=2)
    ent = ttk.Entry(f, textvariable=name, width=18)
    ent.grid(row=0, column=1, sticky='we', padx=2, pady=2)
    ttk.Label(f, text=T('nc.class', 'Class')).grid(row=1, column=0, sticky='w', padx=2, pady=2)
    ttk.Combobox(f, textvariable=cls, values=names, state='readonly', width=16).grid(
        row=1, column=1, sticky='we', padx=2, pady=2)
    top = max(top_level(data, c, median) for c in range(7))
    ttk.Label(f, text=T('nc.level', 'Level (1-{top})', top=top)).grid(row=2, column=0, sticky='w', padx=2, pady=2)
    ttk.Spinbox(f, textvariable=level, from_=1, to=top, width=6).grid(row=2, column=1, sticky='w', padx=2, pady=2)
    row = 3
    ttk.Checkbutton(f, text=T('nc.hardcore', 'Hardcore'), variable=hc).grid(
        row=row, column=0, columnspan=2, sticky='w', padx=2)
    row += 1
    if not median:
        ttk.Checkbutton(f, text=T('nc.expansion', 'Expansion (Lord of Destruction)'), variable=exp).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=2)
        row += 1
    ttk.Checkbutton(f, text=T('nc.unlocked', 'All difficulties, acts and waypoints unlocked'), variable=unl).grid(
        row=row, column=0, columnspan=2, sticky='w', padx=2)
    row += 1
    err = ttk.Label(f, text='', foreground='#d04040', wraplength=260)
    err.grid(row=row, column=0, columnspan=2, sticky='w', padx=2)
    row += 1

    def ok():
        n = name.get().strip()
        try:
            try:
                MC.check_name(n)
            except MC.CharError:
                raise NewCharError(T('mock.err.name', 'Name: 2 to 15 letters (A-Z), at most one - or _, not at the '
                                                      'start or the end'))
            try:
                lv = int(level.get())
            except ValueError:
                raise NewCharError(T('nc.err.level', 'Level: 1 to {top}', top=top))
            folder = save_folder(app)
            if not folder:
                raise NewCharError(T('mock.err.folder', 'No save folder.'))
            if name_taken(folder, n):
                raise NewCharError(T('nc.err.exists', 'A character or file named {name} already exists.', name=n))
            raw, _ch = build(data, n, names.index(cls.get()), lv, hardcore=hc.get(), expansion=exp.get(),
                             unlocked=unl.get(), median=median)
            path = write(raw, folder, n)
        except (NewCharError, MC.CharError, OSError) as e:
            err.configure(text=str(e))
            return
        w.destroy()
        try:
            app.select_character(os.path.splitext(os.path.basename(path))[0], app.view.get())
        except Exception as e:
            print('newchar: new character not selected:', e)
    b = ttk.Frame(f)
    b.grid(row=row, column=0, columnspan=2, sticky='e', pady=(4, 0))
    ttk.Button(b, text=T('nc.create', 'Create'), command=ok).pack(side='left', padx=2)
    ttk.Button(b, text=T('profile.cancel', 'Cancel'), command=w.destroy).pack(side='left', padx=2)
    w.bind('<Return>', lambda _e: ok())
    w.bind('<Escape>', lambda _e: w.destroy())
    ent.focus_set()
    w._capy_ok = ok                            # the tests press it
    return w


def install():
    try:
        import mxl_toolbar
        mxl_toolbar.add_entry(lambda: T('nc.menu', 'New character...'), open_dialog)
    except Exception:
        pass
