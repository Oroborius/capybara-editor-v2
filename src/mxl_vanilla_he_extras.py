"""Vanilla Extras, using the character writer and game-specific item codec."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from mxl_char import CharError, blob_item
from mxl_creator import (
    FLAG_EAR, FLAG_IDENTIFIED, FLAG_RUNEWORD, FLAG_SIMPLE, NUM_SOCKETS, build_blob, decode_blob, decode_item,
)
from mxl_vanilla_he_items import (
    FLAG_STARTER, ITEM_ERRORS, current_extras_entry, extras_entries, replace_item,
    special_sections, write_special_sections,
)

TABS = ('Character Hex', 'Item Binary Compare/Edit', 'Item Edit', 'Item/Character Create')
CHARGED_SKILL = 204
HEADER_FIELDS = (
    (0, 'Char File Header'), (4, 'Version Number'), (8, 'File Size'), (12, 'Checksum'),
    (16, 'Weapon Slot'), (20, 'Char Name'), (36, 'Char Status'), (37, 'Char Title'),
    (38, 'Reserved'), (40, 'Char Class'), (41, 'Reserved'), (43, 'Char Initial Displayed Level'),
    (44, 'Created'), (48, 'TimeStamp'), (52, 'Reserved'),
    (56, 'Hotkeys'), (120, 'Left Skill'), (124, 'Right Skill'),
    (128, 'Alternate Left Skill'), (132, 'Alternate Right Skill'), (136, 'Appearance'),
    (168, 'Starting Town'), (171, 'Map ID'), (175, 'Reserved'), (177, 'Mercenary Status'),
    (179, 'Mercenary ID'), (183, 'Mercenary Name'), (185, 'Mercenary Type'),
    (187, 'Mercenary Experience'), (191, 'Reserved'),
    (0x14F, 'Quest Data'), (0x279, 'Waypoint Data'), (0x2C9, 'NPC Introductions'),
    (0x2FD, 'Character Stats'),
)


def reverse_bits(blob):
    return ' '.join(f'{byte:08b}' for byte in reversed(blob))


def read_bits(value):
    bits = ''.join(value.split())
    if len(bits) % 8 or set(bits) - {'0', '1'}:
        raise ValueError('Enter a whole number of bytes using ones and zeroes.')
    return bytes(int(bits[index:index + 8], 2) for index in range(len(bits) - 8, -1, -8))


def bind_overwrite(entry, variable, alphabet):
    """Overwrite one digit at the cursor, stepping over byte separators."""
    def overwrite(event):
        digit = event.char.upper()
        if not digit or digit not in alphabet or event.state & 0xC:
            return
        text = variable.get()
        begin = entry.index(tk.SEL_FIRST) if entry.selection_present() else entry.index(tk.INSERT)
        position = next((i for i in range(begin, len(text)) if text[i] != ' '), None)
        if position is not None:
            variable.set(text[:position] + digit + text[position + 1:])
            entry.selection_clear()
            entry.icursor(position + 1)
        return 'break'

    entry.bind('<KeyPress>', overwrite, add='+')


def put_picked_up(win, blob):
    from mxl_creator_gui import clean
    from mxl_vanilla_he import draw_pickup

    item = blob_item(blob, win.data)
    win.app._capy_clip = bytes(blob), clean(item.get('name') or item['code'])
    draw_pickup(win)
    win.set_status('Item copied into Picked Up.')
    return 'Item copied into Picked Up.'


def encode_modified(record, children, data):
    """Keep explicit socket-count stats when writing an imported item."""
    snapshot = dict(record)
    for key in ('stats', 'stats_runeword'):
        snapshot[key] = [dict(stat, sockets=True) if stat['id'] == NUM_SOCKETS else stat
                         for stat in record.get(key, ())]
    return build_blob(snapshot, children, data, preserve_stat_order=True)


def open_extras(win, entry=None, group='Basic1'):
    win.sync_file()
    top = tk.Toplevel(win.top)
    top.title('Extras')
    top.geometry('681x371')
    header = ttk.Frame(top, padding=(8, 3))
    header.pack(fill='x')
    entries = extras_entries(win.ch)
    total = sum(1 + len(e.it.get('socketed', ())) for e, _merc in entries)
    ttk.Label(header, text=f'Total Number of Items (including in sockets)  {total}').grid(row=0, column=0)
    offset = tk.StringVar(value='?')
    ttk.Label(header, text='Item Edit Bit Offset').grid(row=0, column=1, padx=5)
    ttk.Label(header, textvariable=offset).grid(row=0, column=2)
    ttk.Label(header, text=f'Save version  {win.ch.version}').grid(row=1, column=0, sticky='w')
    ttk.Label(header, text=f'Character Name  {win.ch.name}').grid(row=1, column=1, columnspan=2)
    header.columnconfigure(3, weight=1)
    ttk.Button(header, text='Close', command=top.destroy).grid(row=0, column=4, rowspan=2)
    notebook = ttk.Notebook(top, style='Extras.TNotebook')
    notebook.pack(fill='both', expand=True, padx=8, pady=(6, 0))
    pages = [ttk.Frame(notebook, style='Peach.TFrame', padding=5) for _ in TABS]
    for page, caption in zip(pages, TABS):
        notebook.add(page, text=caption)
    character_hex(pages[0], win)
    binary_compare(pages[1], win, entries)
    ItemEdit(pages[2], win, entries, entry, group, offset)
    create_items(pages[3], win)
    notebook.select(pages[2])
    from mxl_vanilla_he import center_mouse

    center_mouse(top)
    return top


def character_hex(page, win):
    raw = win.ch.build()
    address, value = tk.StringVar(value='0'), tk.StringVar()
    displayed = tk.StringVar(value=str(win.ch.level))
    real = tk.StringVar(value=str(win.ch.field('level')))
    ttk.Label(page, text='Character Hex (Plus Items as initially loaded)').pack(anchor='w')
    row = ttk.Entry(page, textvariable=value, font='TkFixedFont')
    row.pack(fill='x')
    bind_overwrite(row, value, '0123456789ABCDEF')
    shell = ttk.Frame(page)
    shell.pack(fill='both', expand=True)
    controls = ttk.Frame(shell)
    controls.pack(side='left', fill='both', expand=True)
    fields = tk.Listbox(shell, width=27, exportselection=False)
    fields.pack(side='right', fill='y')
    for start, label in HEADER_FIELDS:
        fields.insert('end', f'{start:03X}  {label}')
    nav = ttk.Frame(controls)
    nav.pack(fill='x', pady=4)
    ttk.Label(nav, text='Left Byte Addr').pack(side='left')
    cursor = tk.StringVar(value='0')
    ttk.Label(nav, textvariable=cursor).pack(side='right')

    def show(start):
        start = max(0, min(start, len(raw) - 1))
        address.set(f'{start:X}')
        value.set(raw[start:start + 24].hex(' ').upper())
        cursor.set(f'Cursor Byte {start:X}')

    def navigate(step=0):
        try:
            show(int(address.get(), 16) + step)
        except ValueError:
            show(0)

    def write():
        nonlocal raw
        try:
            start = int(address.get(), 16)
            changed = bytes.fromhex(value.get())
            if not 0 <= start or raw[start:start + len(changed)] == changed:
                return
            end = start + len(changed)
            if len(changed) != len(raw[start:start + 24]):
                raise ValueError('Keep the same number of bytes in the row.')
            # Bytes past the fixed header are displayed for reference.
            if win.ch.early or end > len(win.ch.head):
                raise ValueError('Enter an address wholly inside the fixed character header.')
            if win.changed_on_disk() or win.ch.build() != raw:
                raise ValueError('The character changed. Reopen Extras to continue.')
            previous = bytes(win.ch.head)
            patched = bytearray(previous)
            patched[start:end] = changed
            if patched[:16] != previous[:16]:
                raise ValueError('Signature, version, file size and checksum are managed by the writer.')
            win.ch.head[:] = patched
            if not win.save('Character header saved.'):
                win.ch.head[:] = previous
                return
            raw = win.ch.build()
            displayed.set(str(win.ch.level))
            navigate()
        except ITEM_ERRORS as error:
            messagebox.showerror('Character Hex', str(error), parent=page)

    addr = ttk.Entry(nav, width=7, textvariable=address)
    addr.pack(side='left', padx=4)
    addr.bind('<Return>', lambda _event: navigate())
    for label, step in (('‹', -1), ('›', 1)):
        ttk.Button(nav, text=label, width=3, command=lambda delta=step: navigate(delta)).pack(side='left')
    ttk.Button(controls, text='Save Header Bytes', command=write).pack(anchor='w')
    def update_cursor(_event=None):
        try:
            cursor.set(f'Cursor Byte {int(address.get(), 16) + row.index(tk.INSERT) // 3:X}')
        except ValueError:
            cursor.set('Cursor Byte ?')

    row.bind('<KeyRelease>', update_cursor)
    row.bind('<ButtonRelease-1>', update_cursor)
    fields.bind('<<ListboxSelect>>', lambda _event: fields.curselection() and show(
        HEADER_FIELDS[fields.curselection()[0]][0]))
    for label, variable in (('Real Char Level', real), ('Initial "Displayed" Level', displayed)):
        ttk.Label(controls, text=label).pack(anchor='w')
        ttk.Entry(controls, width=5, textvariable=variable, state='readonly').pack(anchor='w')
    def refresh():
        nonlocal raw
        raw = win.ch.build()
        navigate()

    hotkey_controls(controls, win, refresh)
    show(0)


def hotkey_controls(parent, win, refresh):
    from mxl_hotkeys import hotkey, mouse_skill, set_hotkey, set_mouse_skill, skill_name

    controls = ttk.Frame(parent)
    controls.pack(anchor='w', pady=4)
    names = ['Left', 'Right', *(f'F{i}' for i in range(1, 9))]
    slots = ttk.Combobox(controls, values=names, state='readonly', width=5)
    skills = [(None, 'Unassigned'), *((sid, f'{sid} {skill_name(win.data, sid)}')
                                     for sid in sorted(win.data.skill_names))]
    skill = ttk.Combobox(controls, values=[label for _, label in skills], state='readonly', width=19)
    side = ttk.Combobox(controls, values=('Left', 'Right'), state='readonly', width=5)
    for label, widget in (('Hotkey', slots), ('Skill', skill), ('Side', side)):
        ttk.Label(controls, text=label).pack(side='left')
        widget.pack(side='left')

    def show(_event=None):
        index = slots.current()
        sid, left = (mouse_skill(win.ch, index), index == 0) if index < 2 else hotkey(win.ch, index - 2)
        side.current(0 if left else 1)
        side.configure(state='disabled' if index < 2 or win.ch.early else 'readonly')
        skill.set(next((label for key, label in skills if key == sid), str(sid)))

    def apply(_event=None):
        index = slots.current()
        chosen = skill.current()
        if chosen < 0 or win.ch.early:
            return
        if win.changed_on_disk():
            win.reload()
            show()
            return
        old = bytes(win.ch.head)
        sid = skills[chosen][0]
        try:
            if index < 2:
                set_mouse_skill(win.ch, index, sid if sid is not None else 0)
            else:
                set_hotkey(win.ch, index - 2, sid, side.current() == 0)
            if not win.save('Hotkey saved.'):
                win.ch.head[:] = old
        except ITEM_ERRORS as error:
            win.ch.head[:] = old
            messagebox.showerror('Character Hex', str(error), parent=parent)
        refresh()
        show()

    slots.current(0)
    slots.bind('<<ComboboxSelected>>', show)
    skill.bind('<<ComboboxSelected>>', apply)
    side.bind('<<ComboboxSelected>>', apply)
    if win.ch.early:
        skill.configure(state='disabled')
    else:
        show()


def item_list(parent, win, entries, height):
    from mxl_rc_menu import clean_name
    widget = tk.Listbox(parent, exportselection=False, width=29, height=height)
    for entry, owner in entries:
        if isinstance(owner, tuple):
            location = 'Iron Golem' if owner[0] == 'tail' else 'Corpse'
        else:
            location = 'Merc' if owner else str(entry.it.get('location', ''))
        widget.insert('end', f'{location}  {clean_name(win, entry)}')
    if entries:
        widget.selection_set(0)
    return widget


def binary_compare(page, win, entries):
    ttk.Label(page, text='Item "Reverse" Binary Comparison').grid(row=0, column=0, sticky='w')
    page.columnconfigure(0, weight=1)
    states = []
    for index in range(2):
        address, text = tk.StringVar(), tk.StringVar()
        items = item_list(page, win, entries, 4)
        items.grid(row=1 + 3 * index, column=1, rowspan=2, sticky='nsew')
        nav = ttk.Frame(page)
        nav.grid(row=1 + 3 * index, column=0, sticky='w')
        ttk.Label(nav, text='Left Byte Addr').pack(side='left')
        offset = ttk.Entry(nav, width=6, textvariable=address)
        offset.pack(side='left')
        row = ttk.Entry(page, textvariable=text, font='TkFixedFont',
                        state='readonly' if not index else 'normal')
        row.grid(row=3 + 3 * index, column=0, columnspan=2, sticky='ew', pady=4)

        def show(step=0, items=items, address=address, text=text, index=index):
            sel = items.curselection()
            if not sel:
                return
            entry, owner = entries[sel[0]]
            entry = current_extras_entry(win, entry, owner)
            if entry is None:
                text.set('')
                return
            try:
                start = max(1, min(int(address.get()) + step, len(entry.blob)))
            except ValueError:
                start = len(entry.blob)
            states[index] = sel[0], entry, start, bytes(entry.blob)
            address.set(str(start))
            text.set(reverse_bits(entry.blob[:start]))

        states.append(None)
        offset.bind('<Return>', lambda _event, redraw=show: redraw())
        for label, step in (('‹', -1), ('›', 1)):
            ttk.Button(nav, text=label, width=3, command=lambda d=step, redraw=show: redraw(d)).pack(side='left')
        items.bind('<<ListboxSelect>>', lambda _event, redraw=show: redraw())
        show()
        if not index:
            first = show
    controls = ttk.Frame(page)
    controls.grid(row=7, column=0, columnspan=2, sticky='w')
    for label, step in (('Incr Both', 1), ('Decr Both', -1)):
        ttk.Button(controls, text=label, command=lambda d=step: (first(d), show(d))).pack(side='left')
    count = tk.StringVar(value='0')
    ttk.Entry(controls, width=5, textvariable=count).pack(side='left', padx=3)
    cursor = tk.StringVar(value='Cursor Bit Loc’n 0')
    bind_overwrite(row, text, '01')
    row.bind('<KeyRelease>', lambda _event: cursor.set(
        f'Cursor Bit Loc’n {len("".join(text.get()[row.index(tk.INSERT):].split()))}'))
    ttk.Label(page, textvariable=cursor).grid(row=8, column=0, sticky='w')

    def shift(insert):
        try:
            amount = int(count.get())
            if amount < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror('Item Binary Compare/Edit', 'Enter a nonnegative bit count.', parent=page)
            return
        point = len(''.join(text.get()[:row.index(tk.INSERT)].split()))
        bits = ''.join(text.get().split())
        if insert:
            bits = bits[:point] + '0' * min(amount, 8 * 65536) + bits[point:]
        else:
            bits = bits[:max(0, point - amount)] + bits[point:]
        text.set(' '.join(bits[i:i + 8] for i in range(0, len(bits), 8)))

    def write():
        if states[1] is None:
            return
        index, entry, start, before = states[1]
        _, owner = entries[index]
        try:
            new = read_bits(text.get()) + before[start:]
            replace_item(win, entry, before, new, 'Binary item saved.', owner)
        except ITEM_ERRORS as error:
            messagebox.showerror('Item Binary Compare/Edit', str(error), parent=page)
            return
        # A newly saved item cannot be resolved by its former bytes.
        from mxl_char import Entry

        current = current_extras_entry(win, Entry(entry.it, new), owner)
        if current is not None:
            entries[index] = current, owner
        first()
        show()

    for label, callback in (('Remove Bits', lambda: shift(False)), ('Insert Bits', lambda: shift(True)),
                            ('Save Binary Item', write)):
        ttk.Button(controls, text=label, command=callback).pack(side='left', padx=2)


class ItemEdit:
    GROUPS = {
        'Basic1': ('flags', 'version'),
        'Location - View Only': ('location', 'equipped', 'x', 'y', 'panel'),
        'Item Code': ('code', 'ear_name', 'ear_class', 'ear_level'),
        'Basic2': ('id', 'ilvl', 'image', 'auto_affix'),
        'Quality': ('quality', 'subquality', 'prefix', 'suffix', 'set_unique_id', 'rare_names', 'rare_affixes'),
        'Other': ('runeword_id', 'personalized_name', 'defense', 'max_durability', 'durability',
                  'quantity', 'sockets', 'socketed_count', 'realm_bit', 'tome_bits'),
    }
    MAGIC = {'Magic': 'stats', 'Runeword Magic': 'stats_runeword',
             **{f'Set{i + 1} Magic': f'set_stats_{i}' for i in range(5)}}

    def __init__(self, page, win, entries, initial, group, offset):
        self.page, self.win, self.entries, self.offset = page, win, entries, offset
        self.record, self.children, self.entry = {}, [], None
        self.offsets = {}
        self.dirty = False
        self.removed = None
        self.selection = 0
        self.initial = group
        self.preview_image = None
        left = ttk.Frame(page)
        left.pack(side='left', fill='y')
        items_frame = ttk.Frame(left)
        items_frame.pack(fill='both', expand=True)
        self.items = item_list(items_frame, win, entries, 6)
        sb = ttk.Scrollbar(items_frame, orient='vertical', command=self.items.yview)
        self.items.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.items.pack(side='left', fill='both', expand=True)
        self.preview = ttk.Label(left)
        self.preview.pack(anchor='w')
        for caption, callback in (
            ('Copy Item to "Picked Up"', self.copy),
            ('Remove socketed Item to "Picked Up"', self.remove_child),
            ('Test Item for Errors', self.test),
            ('Delete Magic Attribute - ALL ITEMS', self.delete_all),
        ):
            ttk.Button(left, text=caption, command=callback).pack(fill='x')
        middle = ttk.Frame(page)
        middle.pack(side='left', fill='y', padx=4)
        self.tree = ttk.Treeview(middle, show='tree', selectmode='browse', height=9)
        self.tree.column('#0', width=145)
        self.tree.pack(fill='both', expand=True)
        ttk.Button(middle, text='Save Modified Item', command=self.save).pack(fill='x')
        moves = ttk.Frame(middle)
        moves.pack(fill='x')
        ttk.Button(moves, text='Move Attrib ↑', command=lambda: self.move(-1)).pack(side='left')
        ttk.Button(moves, text='↓', width=3, command=lambda: self.move(1)).pack(side='right')
        self.details = ttk.LabelFrame(page, text='Item Attributes')
        self.details.pack(side='left', fill='both', expand=True)
        self.items.bind('<<ListboxSelect>>', self.load)
        self.tree.bind('<<TreeviewSelect>>', self.display)
        if entries:
            self.selection = next((i for i, (entry, _merc) in enumerate(entries)
                                   if entry is initial or (
                                       isinstance(initial, tuple) and _merc == initial)), 0)
            self.items.selection_clear(0, 'end')
            self.items.selection_set(self.selection)
            self.items.see(self.selection)
        self.load()

    def error(self, error):
        messagebox.showerror('Item Edit', str(error), parent=self.page)

    def load(self, _event=None):
        selected = self.items.curselection()
        if not selected:
            return
        index = selected[0]
        if self.dirty and not messagebox.askyesno('Item Edit', 'Discard buffered item changes?', parent=self.page):
            self.items.selection_clear(0, 'end')
            self.items.selection_set(self.selection)
            return
        entry, owner = self.entries[index]
        entry = current_extras_entry(self.win, entry, owner)
        if entry is None:
            self.error('The selected item has changed.')
            return
        try:
            record, children = decode_blob(entry.blob, self.win.data)
        except ITEM_ERRORS as error:
            self.error(error)
            return
        self.selection, self.entry = index, entry
        self.original = bytes(entry.blob)
        self.record, self.children = record, children
        self.removed = None
        self.dirty = False
        self.render_icon(entry.it)
        self.rebuild(self.initial)
        self.initial = 'Basic1'

    def render_icon(self, item):
        layers = self.win.icon(item, '#404040') or {}
        self.preview_image = layers.get(1)
        self.preview.configure(image=self.preview_image or '', text=item['code'].strip())

    def rebuild(self, selected):
        self.tree.delete(*self.tree.get_children())
        for group in (*self.GROUPS, *self.MAGIC):
            self.tree.insert('', 'end', iid=group, text=group)
            key = self.MAGIC.get(group)
            fields = self.GROUPS.get(group, ())
            for field in fields:
                if field in self.record:
                    self.tree.insert(group, 'end', iid=f'{group}:{field}', text=field.replace('_', ' ').title())
            if key and self.magic_available(group):
                stats = self.record.get(key, ())
                for index in range(len(stats) + 1):
                    label = f'Magic Attribute {index + 1}'
                    self.tree.insert(group, 'end', iid=f'{group}:{index}', text=label)
        parent = selected.split(':')[0]
        self.tree.item(parent, open=True)
        if not self.tree.exists(selected):
            selected = parent
        self.tree.selection_set(selected)
        self.tree.see(selected)
        self.display()

    def magic_available(self, group):
        if self.record.get('flags', FLAG_SIMPLE) & (FLAG_SIMPLE | FLAG_EAR):
            return False
        if group.startswith('Set'):
            return self.record.get('quality') == 'set'
        if group == 'Runeword Magic':
            return bool(self.record['flags'] & FLAG_RUNEWORD)
        return True

    def display(self, _event=None):
        for widget in self.details.winfo_children():
            widget.destroy()
        selected = next(iter(self.tree.selection()), 'Basic1')
        group, _, field = selected.partition(':')
        self.details.configure(text=group)
        if not self.record:
            return
        self.offsets.clear()
        try:
            blob = encode_modified(self.record, self.children, self.win.data) if self.dirty else self.original
            decode_item(blob, self.win.data, offsets=self.offsets)
        except ITEM_ERRORS:
            self.offsets.clear()
        offset_key = self.MAGIC.get(group, field or self.GROUPS.get(group, ('',))[0])
        if group in self.MAGIC and field:
            offset_key += ':' + field
        self.offset.set(str(self.offsets.get(offset_key, '?')))
        if group in self.MAGIC:
            if field:
                self.magic_slot(group, int(field))
            else:
                from mxl_statnames import stat_text
                self.show_list(stat_text(self.win.data, s['id'], s.get('param'), s['value'])
                               for s in self.record.get(self.MAGIC[group], ()))
            return
        if not field:
            lines = [f'{key.replace("_", " ").title()}: {self.record[key]}'
                     for key in self.GROUPS[group] if key in self.record]
            self.show_list(lines)
            return
        value = self.record[field]
        if field in ('rare_names', 'rare_affixes'):
            self.rare_fields(field, value)
            return
        choices = self.field_choices(field)
        if choices:
            values = {f'{label} [{key if key is not None else "default"}]': key for key, label in choices}
            selector = ttk.Combobox(self.details, values=tuple(values), state='readonly', width=25)
            selector.set(next((label for label, key in values.items() if key == value), str(value)))
            selector.pack(fill='x')
            ttk.Button(self.details, text='Apply Selection', command=lambda: self.stage_field(
                field, values[selector.get()]) if selector.get() in values else None).pack(anchor='w')
        if group == 'Location - View Only' or field in ('quality', 'socketed_count', 'code') or (
                not isinstance(value, int) and field not in ('personalized_name', 'ear_name')):
            if not choices:
                ttk.Label(self.details, text=str(value)).pack(anchor='w')
            return
        field_value = tk.StringVar(value=str(value))
        ttk.Entry(self.details, textvariable=field_value, width=12).pack(anchor='w')

        def stage():
            try:
                text = field_value.get()
                if field in ('personalized_name', 'ear_name'):
                    if not (2 <= len(text) <= 15 and text.isascii() and text.isprintable()):
                        raise ValueError('Enter 2–15 printable ASCII characters.')
                    parsed = text
                else:
                    parsed = int(text, 0)
                self.stage_field(field, parsed)
            except ITEM_ERRORS as error:
                self.error(error)

        ttk.Button(self.details, text='Apply Value', command=stage).pack(anchor='w')

    def stage_field(self, field, value):
        record = dict(self.record, **{field: value})
        try:
            if field == 'flags' and (value ^ self.record[field]) & ~(FLAG_IDENTIFIED | FLAG_STARTER):
                raise ValueError('Use the specific editing commands to change structural item flags.')
            encode_modified(record, self.children, self.win.data)
        except ITEM_ERRORS as error:
            self.error(error)
            return
        self.record = record
        self.dirty = True
        self.display()

    def field_choices(self, field):
        if field == 'ear_class':
            from mxl_char import class_names

            return list(enumerate(class_names(self.win.data)))
        if field not in ('image', 'auto_affix', 'prefix', 'suffix', 'set_unique_id', 'runeword_id'):
            return []
        from mxl_rc_menu import _creator_for

        creator = _creator_for(self.win)
        code = self.record['code']
        if field == 'image':
            count = creator.image_count(code)
            return [(None, 'Default appearance'), *((i, f'Alternate {i + 1}') for i in range(count))] if count else []
        if field == 'set_unique_id':
            rows = creator.set_items() if self.record['quality'] == 'set' else creator.uniques()
            return [(key, label) for key, label, row in rows if row['code'] == code]
        if field == 'runeword_id':
            rows = ((creator.rw_string_id(key), label) for key, label, _ in creator.runewords())
            return [(key, label) for key, label in rows if key is not None]
        ilvl = self.record['ilvl']
        if field == 'auto_affix':
            return [(None, 'No auto affix'), *((key, label) for key, label, _ in creator.auto_choices(code, ilvl))]
        return [(0, 'No affix'), *((key, label) for key, label, _ in
                                  creator.affix_choices('magic' + field, code, ilvl))]

    def rare_fields(self, field, values):
        from mxl_rc_menu import _ask_pick, _creator_for

        creator = _creator_for(self.win)
        code = self.record['code']
        if field == 'rare_names':
            names = creator.rare_name_choices(code)
            offset = len(self.win.data.rare_suffix)
            choices = (
                [(key + offset, name) for key, name in names['rareprefix']],
                names['raresuffix'],
            )
        else:
            choices = tuple(
                [(None, 'No affix'), *((key, label) for key, label, _ in
                                      creator.affix_choices('magic' + kind, code, self.record['ilvl'], rare=True))]
                for kind in ('prefix', 'suffix')
            ) * 3

        def pick(index, options, caption):
            def apply(value):
                edited = list(values)
                edited[index] = value
                self.stage_field(field, edited)
            _ask_pick(self.details, caption, options, apply)

        for index, value in enumerate(values):
            options = choices[index]
            kind = 'Prefix' if index % 2 == 0 else 'Suffix'
            caption = kind if field == 'rare_names' else f'{kind} {index // 2 + 1}'
            name = dict(options).get(value, str(value))
            ttk.Button(self.details, text=f'{caption} · {name}',
                       command=lambda i=index, o=options, c=caption: pick(i, o, c)).pack(fill='x')

    def show_list(self, lines):
        view = tk.Listbox(self.details, width=28, height=8)
        scrollbar = ttk.Scrollbar(self.details, command=view.yview)
        view.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        view.pack(fill='both', expand=True)
        for line in lines:
            view.insert('end', line)

    def magic_slot(self, group, index):
        from mxl_attr_slots import value_range
        from mxl_rc_menu import _creator_for
        from mxl_statnames import encode_skill_param, param_bits, param_choices, param_kind

        data = self.win.data
        key = self.MAGIC[group]
        rows = self.record.setdefault(key, [])
        current = rows[index] if index < len(rows) else None
        choices = _creator_for(self.win).stat_choices()
        labels = [label for _sid, label in choices]
        attribute = ttk.Combobox(self.details, values=labels, state='readonly', width=25)
        attribute.pack(fill='x')
        value = ttk.Combobox(self.details, width=12)
        param = ttk.Combobox(self.details, width=25)
        params = {}
        skill_level = tk.StringVar(value='1')
        level = ttk.Entry(self.details, textvariable=skill_level, width=6)
        max_charges = tk.StringVar(value='0')
        charges_label = ttk.Label(self.details, text='Maximum charges')
        charges = ttk.Entry(self.details, textvariable=max_charges, width=6)

        def configure(_event=None):
            sid = choices[attribute.current()][0]
            lo, hi = value_range(data, sid)
            value.configure(values=tuple(range(lo, hi + 1)) if hi - lo <= 256 else ())
            same = current is not None and current['id'] == sid
            number = current['value'] if same else max(lo, min(hi, 0))
            if sid == CHARGED_SKILL:
                value.set(str(number & 255))
                max_charges.set(str(number >> 8))
                charges_label.pack(anchor='w', before=apply_button)
                charges.pack(anchor='w', before=apply_button)
            else:
                value.set(str(number))
                charges_label.pack_forget()
                charges.pack_forget()
            params.clear()
            bits = param_bits(data, sid)
            if bits:
                params.update(param_choices(data, sid))
            param.configure(values=tuple(params), state='normal' if bits else 'disabled')
            raw = (current.get('param') or 0) if same else 0
            skill = param_kind(sid) == 'skill'
            level.configure(state='normal' if skill else 'disabled')
            if skill:
                skill_level.set(str(max(1, raw & 63)))
                raw >>= 6
            param.set(next((name for name, val in params.items() if val == raw), str(raw)) if bits else 'Unused')

        def stage(remove=False):
            try:
                if remove:
                    if current is None:
                        return
                    del rows[index]
                else:
                    if attribute.current() < 0:
                        raise ValueError('Select a magic attribute.')
                    sid = choices[attribute.current()][0]
                    number = int(value.get())
                    if sid == CHARGED_SKILL:
                        maximum = int(max_charges.get())
                        if not 0 <= number <= maximum <= 255:
                            raise ValueError('Current and maximum charges must be 0–255, with current at most maximum.')
                        number |= maximum << 8
                    lo, hi = value_range(data, sid)
                    if not lo <= number <= hi:
                        raise ValueError(f'Value must be between {lo} and {hi}.')
                    raw = None
                    bits = param_bits(data, sid)
                    if bits:
                        raw = params[param.get()] if param.get() in params else int(param.get(), 0)
                        if param_kind(sid) == 'skill':
                            raw, why = encode_skill_param(data, sid, f'#{raw}', int(skill_level.get()))
                            if why:
                                raise ValueError(why)
                        if not 0 <= raw < 1 << bits:
                            raise ValueError('The parameter does not fit this attribute.')
                    rows[index:index + 1] = [dict(id=sid, param=raw, value=number)]
                if group.startswith('Set'):
                    bit = 1 << (int(group[3]) - 1)
                    if rows:
                        self.record['set_mask'] |= bit
                    else:
                        self.record['set_mask'] &= ~bit
                self.dirty = True
                self.rebuild(f'{group}:{index}')
            except ITEM_ERRORS as error:
                self.error(error)

        for title, widget in (('Value', value), ('Parameter', param), ('Skill Level', level)):
            ttk.Label(self.details, text=title).pack(anchor='w')
            widget.pack(fill='x')
        apply_button = ttk.Button(self.details, text='Apply Attribute', command=stage)
        apply_button.pack(anchor='w')
        ttk.Button(self.details, text='Clear Attribute', command=lambda: stage(True)).pack(anchor='w')
        attribute.bind('<<ComboboxSelected>>', configure)
        if current:
            match = next((i for i, (sid, _label) in enumerate(choices) if sid == current['id']), None)
            if match is not None:
                attribute.current(match)
                configure()

    def move(self, delta):
        selected = next(iter(self.tree.selection()), '')
        group, _, slot = selected.partition(':')
        if group not in self.MAGIC or not slot:
            return
        rows = self.record.get(self.MAGIC[group], [])
        index, other = int(slot), int(slot) + delta
        if 0 <= index < len(rows) and 0 <= other < len(rows):
            rows[index], rows[other] = rows[other], rows[index]
            self.dirty = True
            self.rebuild(f'{group}:{other}')

    def copy(self):
        if self.entry is not None:
            put_picked_up(self.win, self.original)

    def remove_child(self):
        from mxl_creator import encode_item
        from mxl_socket_menu import _drop_runeword

        if not self.children:
            return
        if self.removed is not None:
            self.error('Save the modified item before removing another socketed item.')
            return
        index = simpledialog.askinteger('Remove socketed Item', 'Socketed item number',
                                        minvalue=1, maxvalue=len(self.children), parent=self.page)
        if index is None:
            return
        try:
            child = dict(self.children[index - 1], location=0, equipped=0, x=0, y=0, panel=1)
            blob = encode_item(child, self.win.data)
            self.removed = blob
            self.children.pop(index - 1)
            self.record['socketed_count'] = len(self.children)
            _drop_runeword(self.record)
            self.dirty = True
            self.rebuild('Other')
        except ITEM_ERRORS as error:
            self.error(error)

    def test(self):
        from mxl_rc_menu import _creator_for
        from mxl_socket_insert import socket_total
        from mxl_socket_menu import max_sockets

        if self.entry is not None:
            try:
                data = self.win.data
                record = self.record
                blob = encode_modified(record, self.children, data)
                blob_item(blob, data)
                base = data.base(record['code'])
                warnings = []
                if 'quantity' in record and record['quantity'] > base.stack_max:
                    warnings.append(f'Quantity exceeds the base limit of {base.stack_max}.')
                if 'durability' in record:
                    import stat_ids as S

                    maximum = record['max_durability'] - data.isc[S.MAX_DURABILITY]['add']
                    if record['durability'] > maximum:
                        warnings.append(f'Current durability exceeds {maximum}.')
                total = socket_total(record)
                if record.get('sockets') and total > max_sockets(_creator_for(self.win), record['code'], record):
                    warnings.append('Socket count exceeds the limit for this item type and level.')
                if len(self.children) > total:
                    warnings.append('There are more socketed items than sockets.')
            except ITEM_ERRORS as error:
                self.error(error)
                return
            if warnings:
                messagebox.showwarning('Test Item for Errors', '\n'.join(warnings), parent=self.page)
            else:
                messagebox.showinfo('Test Item for Errors', 'The item decoded successfully.', parent=self.page)

    def save(self):
        if not self.dirty or self.entry is None:
            return
        from mxl_char import Entry

        _old, owner = self.entries[self.selection]
        try:
            blob = encode_modified(self.record, self.children, self.win.data)
            replace_item(self.win, self.entry, self.original, blob, 'Modified item saved.', owner)
        except ITEM_ERRORS as error:
            self.error(error)
            return
        entry = current_extras_entry(self.win, Entry(self.entry.it, blob), owner)
        if entry is None:
            return
        self.entries[self.selection] = entry, owner
        self.entry, self.original, self.dirty = entry, blob, False
        if self.removed is not None:
            put_picked_up(self.win, self.removed)
            self.removed = None

    def delete_all(self):
        from mxl_rc_menu import _ask_pick, _creator_for

        if self.dirty:
            self.error('Save or discard the buffered item changes first.')
            return
        _ask_pick(self.page, 'Delete Magic Attribute - ALL ITEMS',
                  _creator_for(self.win).stat_choices(), self.delete_attribute)

    def delete_attribute(self, stat_id):
        from mxl_char import Entry
        from mxl_rc_menu import _record_char_write

        win = self.win
        win.sync_file()
        if win.ch.old:
            self.error('This command requires a 1.10 or later save.')
            return
        if not messagebox.askyesno('Item Edit', f'Delete attribute {stat_id} from all editable items?',
                                   parent=self.page):
            return
        ch = win.ch
        before = bytes(ch.raw)
        corpse, tail = ch.corpse, ch.tail
        replacements = []
        previous = []
        try:
            sections = special_sections(ch)
            special = []
            groups = [*[(None, 0, 0, ch.entries(merc)) for merc in (False, True)], *sections]
            for name, start, end, items in groups:
                edited = list(items)
                for index, entry in enumerate(items):
                    blob = self.without_attribute(entry.blob, stat_id)
                    if blob is not None:
                        item = blob_item(blob, win.data)
                        if name:
                            edited[index] = Entry(item, blob)
                        else:
                            replacements.append((entry, blob, item))
                if name and edited != items:
                    special.append((name, start, end, edited))
            if not replacements and not special:
                win.set_status('No item has the selected attribute.')
                return
            previous = [(entry, entry.blob, entry.it) for entry, _, _ in replacements]
            for entry, blob, item in replacements:
                entry.blob, entry.it = blob, item
            write_special_sections(ch, special)
            if not win.save('Selected magic attribute removed.'):
                raise CharError('The character could not be saved.')
        except ITEM_ERRORS as error:
            for entry, blob, item in previous:
                entry.blob, entry.it = blob, item
            ch.corpse, ch.tail = corpse, tail
            self.error(error)
            return
        _record_char_write(win, win.ch.path, before, 'Delete Magic Attribute - ALL ITEMS')
        self.page.winfo_toplevel().destroy()

    def without_attribute(self, blob, stat_id):
        record, children = decode_blob(blob, self.win.data)
        changed = False
        for item in (record, *children):
            for key in self.MAGIC.values():
                rows = item.get(key, ())
                kept = [stat for stat in rows if stat['id'] != stat_id]
                if len(kept) != len(rows):
                    item[key] = kept
                    changed = True
        if changed:
            return encode_modified(record, children, self.win.data)


def create_items(page, win):
    import settings
    from mxl_creator_gui import CreatorWindow
    from mxl_newchar import open_dialog
    from mxl_rc_menu import _creator_for
    from mxl_vanilla_he import ITEM_LEVEL

    creator = _creator_for(win)
    tree = ttk.Treeview(page, show='tree', height=11, selectmode='browse')
    tree.column('#0', width=175)
    tree.pack(side='left', fill='y')
    tree.insert('', 'end', iid='all', text='All Items')
    groups = {'armor': 'Armor', 'weapons': 'Weapons', 'misc': 'Miscellaneous'}
    for group, label in groups.items():
        tree.insert('all', 'end', iid=group, text=label)
    by_code = {}
    for base in sorted(creator.bases(), key=lambda b: creator.display_name(b.code).casefold()):
        if base.kind in groups:
            iid = 'base:' + base.code
            tree.insert(base.kind, 'end', iid=iid, text=creator.display_name(base.code))
            by_code[base.code.strip()] = iid
    if 'ear ' in win.data.bases and 'ear' not in by_code:
        by_code['ear'] = 'base:ear '
        tree.insert('misc', 'end', iid='base:ear ', text=win.data.base('ear ').name)
    description = tk.Text(page, width=24, height=8, wrap='word', state='disabled')
    options = ttk.Frame(page)
    options.pack(side='right', fill='y', padx=(4, 0))
    description.pack(side='left', fill='both', expand=True, padx=(4, 0))
    code = tk.StringVar()
    ttk.Label(options, text='Type Code').pack(anchor='w')
    field = ttk.Entry(options, textvariable=code, width=9)
    field.pack(anchor='w')
    preview = ttk.Label(options)
    preview.pack(anchor='w')

    def build(item_code):
        spec = creator.new_spec('normal', item_code)
        level = settings.get(ITEM_LEVEL)
        if level in (90, 99):
            spec['ilvl'] = max(level, spec['ilvl'])
        return creator.build(spec)[0]

    def select(_event=None):
        chosen = next(iter(tree.selection()), '')
        if not chosen.startswith('base:'):
            return
        item_code = chosen[5:]
        code.set(item_code.strip())
        description.configure(state='normal')
        description.delete('1.0', 'end')
        detail = creator.item_desc(item_code) if item_code != 'ear ' else 'Name, class and level of the character.'
        description.insert('1.0', f'{tree.item(chosen, "text")}\n{detail or ""}')
        description.configure(state='disabled')
        try:
            blob = ear_blob(win, win.ch.name, win.ch.cls, win.ch.level) if item_code == 'ear ' else build(item_code)
            item = blob_item(blob, win.data)
            preview.image = (win.icon(item, '#404040') or {}).get(1)
        except ITEM_ERRORS:
            preview.image = None
        preview.configure(image=preview.image or '')

    def lookup(_event=None):
        iid = by_code.get(code.get().strip())
        if iid:
            tree.selection_set(iid)
            tree.see(iid)

    def save():
        iid = by_code.get(code.get().strip())
        if not iid:
            messagebox.showerror('Item Create', 'Select a base item or enter a valid type code.', parent=page)
            return
        if iid == 'base:ear ':
            create_ear(page, win)
            return
        try:
            put_picked_up(win, build(iid[5:]))
        except ITEM_ERRORS as error:
            messagebox.showerror('Item Create', str(error), parent=page)

    tree.bind('<<TreeviewSelect>>', select)
    field.bind('<Return>', lookup)
    ttk.Button(options, text='Save New Item To PickedUp', command=save).pack(fill='x', pady=4)
    ttk.Button(options, text='Item Creator', command=lambda: CreatorWindow(
        win.app, target=lambda blob: put_picked_up(win, blob), target_label='Picked Up')).pack(fill='x')
    new = ttk.LabelFrame(options, text='Create New Character')
    new.pack(fill='x', pady=4)
    for label, version, row, col in (
        ('V1.03', 71, 0, 0), ('V1.07', 87, 0, 1), ('V1.09D', 92, 1, 0),
        ('V1.10/V1.11/V1.12/V1.13', 96, 2, 0),
    ):
        ttk.Button(new, text=label, command=lambda v=version: open_dialog(win.app, initial_version=v)).grid(
            row=row, column=col, columnspan=2 if row == 2 else 1, sticky='ew')
    ttk.Button(new, text='V1.10s beta', state='disabled').grid(row=1, column=1, sticky='ew')
    ttk.Button(new, text='V1.12 Clone', state='disabled').grid(
        row=3, column=0, columnspan=2, sticky='ew')


def ear_blob(win, name, cls, level):
    from mxl_char import check_name
    from mxl_creator import FLAG_ALWAYS, encode_item

    check_name(name)
    return encode_item(dict(code='ear ', flags=FLAG_EAR | FLAG_SIMPLE | FLAG_IDENTIFIED | FLAG_ALWAYS,
                            ear_name=name, ear_class=cls, ear_level=level, panel=1), win.data)


def create_ear(page, win):
    from mxl_char import class_names, max_level

    top = tk.Toplevel(page)
    top.title('Create Ear')
    top.transient(page.winfo_toplevel())
    form = ttk.Frame(top, padding=8)
    form.pack(fill='both', expand=True)
    name = ttk.Entry(form)
    name.insert(0, win.ch.name)
    cls = ttk.Combobox(form, values=class_names(win.data), state='readonly')
    cls.current(win.ch.cls)
    level = ttk.Entry(form)
    level.insert(0, str(win.ch.level))
    for row, (label, control) in enumerate((('Name', name), ('Class', cls), ('Level', level))):
        ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', padx=(0, 6))
        control.grid(row=row, column=1, sticky='ew', pady=2)

    def save():
        try:
            actual = int(level.get())
            cap = max_level(win.data, cls.current())
            if not 1 <= actual <= cap:
                raise ValueError(f'Level must be from 1 to {cap}.')
            put_picked_up(win, ear_blob(win, name.get().strip(), cls.current(), actual))
        except ITEM_ERRORS as error:
            messagebox.showerror('Create Ear', str(error), parent=top)
            return
        top.destroy()

    ttk.Button(form, text='Save New Item To PickedUp', command=save).grid(row=3, column=1, sticky='e', pady=(4, 0))
    top.bind('<Escape>', lambda _event: top.destroy())
    name.focus_set()
