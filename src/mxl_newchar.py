"""Create a playable character in the selected profile and save format."""
import os
import random
import struct
import time

import mxl_early_save as early_save
import mxl_v109
from mxl_lang import T

SAVE_VERSIONS = {96: "1.14d", 92: "1.09d", 89: "1.08", 87: "1.07", 71: "Classic 1.00–1.06"}

VANILLA_TOP = 127                      # vanilla: stat 12 has 7 bits (mock characters use 100-127)


class NewCharError(Exception):
    pass


def _median():
    try:
        import mxl_profile
        return mxl_profile.is_median()
    except Exception:
        return True


def _vanilla(median):
    if median:
        return False
    import mxl_profile
    profile = mxl_profile.active()
    return profile is not None and profile['kind'] == 'd2' and not profile['mods']


def top_level(data, cls, median):
    import mxl_char as MC
    top = MC.max_level(data, cls)
    return top if median else max(top, VANILLA_TOP)


def _starter_items(data, row, version, original):
    import mxl_creator as C

    tables = C.Tables(data).item
    codec = mxl_v109.Data109(data, version) if version < 96 and version != 71 else data
    items = []
    for off in range(0x5C, 0xAC, 8):
        code = row[off:off + 4].decode('latin1')
        loc, count = row[off + 4:off + 6]
        if not count:
            continue
        base, fields = data.base(code), tables[code]
        for i in range(count):
            rec = dict(code=code, equipped=loc, location=1, x=0, y=0, panel=0,
                       simple=bool(fields['compact']), version=101 if version == 96 else 100)
            if code == 'hp1 ':
                rec.update(location=2, x=i)
            elif not loc:
                rec.update(location=0, x=9, y=3 - sum(item['panel'] == 1 for item in items), panel=1)
            if not rec['simple'] or original:
                rec.update(id=random.getrandbits(31), seed=random.getrandbits(31), ilvl=1, quality='normal')
            dur = 0 if fields['nodur'] else fields['dur']
            if code == 'jav ' and version < 96:
                # Historical first-save values predate the selected 1.14d tables.
                dur = 14 if version == 71 else 2
                rec['quantity'] = (38 if original else 39) if version == 71 else 60
            elif base.stack_max is not None:
                rec['quantity'] = base.stack_max
            if base.kind in ('armor', 'weapons'):
                rec['max_durability'] = dur + codec.isc[73]['add']
                rec['durability'] = dur if version == 71 else dur + codec.isc[72]['add']
            if base.kind == 'armor':
                lo, hi = base.def_range
                rec['defense'] = {87: lo, 89: min(lo + 1, hi)}.get(version, random.randint(lo, hi))
            if off == 0x5C and (skill := struct.unpack_from('<h', row, 0xAC)[0]) > 0:
                rec['stats'] = [{'id': 107, 'param': skill, 'value': 1}]
            rec['flags'] = 0x822010 | (C.FLAG_SIMPLE if rec['simple'] else 0)
            items.append(rec)
    items.sort(key=lambda r: (bool(r['equipped']), r['equipped']))
    if version == 71:
        return [early_save.classic_starter_item(r, data, original) for r in items]
    return [C.encode_item(r, codec) for r in items]


def skeleton(data, cls, median, expansion=True, version=96, classic_100=False):
    """First-save framing, with character stats and final checksum filled in by Character.build."""
    import mxl_char as MC

    early = version in early_save.VERSIONS
    vanilla = _vanilla(median)
    h = bytearray(MC.QUEST_OFF)
    struct.pack_into('<II', h, 0, MC.MAGIC, version)
    h[0x24] = 0x20 if (median or expansion) else 0
    h[0x28] = cls
    h[0x29], h[0x2A], h[0x2B] = 0x10, (0x5F if median else 0x1E), 1
    struct.pack_into('<III', h, 0x2C, 0, int(time.time()), 0xFFFFFFFF)
    struct.pack_into('<16I', h, 0x38, *([0xFFFF] * 16))
    h[0x88:0xA8] = b'\xff' * 32
    h[0xA8:0xAB] = b'\x80\x00\x00'
    seed = random.getrandbits(31) | 1
    struct.pack_into('<I', h, 0xAB, seed)
    items = []
    if vanilla:
        row = data._rows('charstats')[cls]
        items = _starter_items(data, row, version, classic_100)
        # Tokens for the starting weapons in the original game appearance tables.
        weapon = (0x1B, 0x25, 0x09, 0x11, 0x04, 0x0C, 0x2D)[cls]
        if version == 71:
            weapon = (0x43, 0x12, 0x04, 0x30, 0x01)[cls]
        shield = (0x1B if version == 71 else 0x4F) if row[0x64:0x68] == b'buc ' else 0xFF
        if early:
            h = early_save.starter_header(MC.MAGIC, version, cls, expansion, weapon, shield, seed)
        else:
            h[0x8D], h[0x8F] = weapon, shield
    out = bytes(h)
    out += b'Woo!' + struct.pack('<IH', 6, 298) + bytes(288)
    wp = b'\x02\x01' + bytes((int(vanilla),)) + bytes(21)
    out += b'WS' + struct.pack('<IH', 1, 80) + wp * 3
    out += b'\x01w' + struct.pack('<H', 52) + bytes(48)
    stats = [(12, None, 1)] if early else []
    out += b'gf'
    if version < 96:
        mask = mxl_v109.build_stats(stats)
        out += mask[:2] + b'\0' + mask[2:] if early else mask
    else:
        out += b'\xff\x01'
    out += b'if' + bytes(MC.class_skill_count(data, cls))
    records = b''.join(items)
    corpse = b'JM\0\0'
    out += b'JM' + struct.pack('<H', len(items)) + records + corpse
    if early:
        out += early_save.starter_tail(version, records, corpse)
    elif median or expansion:
        out += b'jfkf\0'
    return out


def _charstats_row(data, cls):
    r = data._rows('charstats')[cls]
    return dict(str=r[0x30], dex=r[0x31], ene=r[0x32], vit=r[0x33], stamina=r[0x34], hpadd=r[0x35])


def build(data, name, cls, level, hardcore=False, expansion=True, unlocked=False, median=None,
          version=96, classic_100=False):
    """(bytes, Character) of a new character. Raises NewCharError / mxl_char.CharError."""
    import mxl_char as MC
    median = _median() if median is None else median
    if version not in SAVE_VERSIONS or (version != 96 and not _vanilla(median)):
        raise NewCharError(T('nc.err.version', 'Unsupported save version for this profile.'))
    expansion = median or (version != 71 and bool(expansion))
    MC.check_name(name)
    if not 0 <= cls < 7 or (not expansion and cls >= 5):
        raise NewCharError(T('nc.err.class', 'Druid and Assassin need the expansion.'))
    top = top_level(data, cls, median)
    if not 1 <= level <= top:
        raise NewCharError(T('nc.err.level', 'Level: 1 to {top}', top=top))
    raw = skeleton(data, cls, median, expansion, version, classic_100)
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
    # The independent parser supports version 96. Use the editor's
    # legacy readers for the remaining formats.
    if raw[4] == 96:
        try:
            import mxl_savecheck
            mxl_savecheck.lib()
            from mxlsave.check import check_bytes
            _obj, problems = check_bytes(raw, 'd2s', mxl_savecheck.tables())
        except ImportError:
            problems = []
        if problems:
            raise NewCharError(T('nc.err.check', 'The new file failed the save check: {p}',
                                 p='; '.join(problems[:3])))
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
    version = tk.StringVar(value=SAVE_VERSIONS[96])
    classic_100 = tk.BooleanVar(value=False)
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
    classes = ttk.Combobox(f, textvariable=cls, values=names, state='readonly', width=16)
    classes.grid(
        row=1, column=1, sticky='we', padx=2, pady=2)
    top = max(top_level(data, c, median) for c in range(7))
    ttk.Label(f, text=T('nc.level', 'Level (1-{top})', top=top)).grid(row=2, column=0, sticky='w', padx=2, pady=2)
    ttk.Spinbox(f, textvariable=level, from_=1, to=top, width=6).grid(row=2, column=1, sticky='w', padx=2, pady=2)
    row = 3
    ttk.Checkbutton(f, text=T('nc.hardcore', 'Hardcore'), variable=hc).grid(
        row=row, column=0, columnspan=2, sticky='w', padx=2)
    row += 1
    if _vanilla(median):
        ttk.Label(f, text=T('nc.version', 'Save version')).grid(row=row, column=0, sticky='w', padx=2)
        versions = ttk.Combobox(f, textvariable=version, values=tuple(SAVE_VERSIONS.values()), state='readonly')
        versions.grid(row=row, column=1, sticky='we', padx=2)
        row += 1
        expansion_toggle = ttk.Checkbutton(f, text=T('nc.expansion', 'Expansion (Lord of Destruction)'),
                                           variable=exp)
        expansion_toggle.grid(row=row, column=0, columnspan=2, sticky='w', padx=2)
        original_toggle = ttk.Checkbutton(f, text=T('nc.classic_100', 'Use 1.00 item format'),
                                          variable=classic_100)
        original_toggle.grid(row=row, column=0, columnspan=2, sticky='w', padx=2)
        original_toggle.grid_remove()
        row += 1

        def update_classes(*_args):
            classic = version.get() == SAVE_VERSIONS[71]
            available = names if not classic and exp.get() else names[:5]
            classes.configure(values=available)
            if cls.get() not in available:
                cls.set(available[0])
            if classic:
                expansion_toggle.grid_remove()
                original_toggle.grid()
            else:
                original_toggle.grid_remove()
                expansion_toggle.grid()

        version.trace_add('write', update_classes)
        exp.trace_add('write', update_classes)
    elif not median:
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
                             unlocked=unl.get(), median=median,
                             version=next(v for v, label in SAVE_VERSIONS.items() if label == version.get()),
                             classic_100=classic_100.get())
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
