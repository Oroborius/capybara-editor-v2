"""Vanilla Extras, using the character writer and game-specific item codec."""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from mxl_vanilla_he import allows
from mxl_char import CharError, blob_item
from mxl_creator import (
    FLAG_EAR, FLAG_IDENTIFIED, FLAG_RUNEWORD, FLAG_SIMPLE, NUM_SOCKETS, build_blob, decode_blob, decode_item,
)
from mxl_vanilla_he_items import (
    ITEM_ERRORS, SocketChild, current_extras_entry, extras_entries, replace_item,
    special_sections, write_special_sections,
)

TABS = ('Character Hex', 'Item Binary Compare/Edit', 'Item Edit', 'Item/Character Create')
CHARGED_SKILL = 204
BASIC_FLAGS = {
    'unknown_1': (0, 4), 'identified': (4, 1), 'unknown_2': (5, 6), 'socketed': (11, 1),
    'unknown_3': (12, 1), 'picked_up': (13, 1), 'unknown_4': (14, 2), 'ear': (16, 1),
    'starter': (17, 1), 'unknown_5': (18, 3), 'simple': (21, 1), 'ethereal': (22, 1),
    'unknown_6': (23, 1), 'personalized': (24, 1), 'unknown_7': (25, 1), 'runeword': (26, 1),
    'unknown_8': (27, 5),
}
STRUCTURAL_FLAGS = {'socketed', 'ear', 'simple', 'personalized', 'runeword'}


HEADER_FIELDS = (
    (0, 4, 'Char File Header'), (4, 4, 'Version Number'), (8, 4, 'File Size'), (12, 4, 'Checksum'),
    (16, 4, 'Weapon Slot'), (20, 16, 'Char Name'), (36, 1, 'Char Status'), (37, 1, 'Char Title'),
    (38, 2, 'Unknown (00 00) at 38–39'), (40, 1, 'Char Class'), (41, 1, 'Unknown skills byte (10)'),
    (42, 1, 'Unknown inventory byte (1E)'), (43, 1, 'Char Initial Displayed Level'),
    (44, 4, 'Unknown at 44–47'), (48, 4, 'Timestamp'), (52, 4, 'Unknown (FF FF FF FF) at 52–55'),
    (56, 64, 'Skill IDs for hotkeys'), (120, 4, 'Left Mouse Skill'), (124, 4, 'Right Mouse Skill'),
    (128, 4, 'Alternate Left Mouse Skill'), (132, 4, 'Alternate Right Mouse Skill'),
    (136, 16, 'Equipment appearance'), (152, 16, 'Equipment colors'), (168, 3, 'Difficulty and Starting Act'),
    (171, 4, 'Map ID'), (175, 2, 'Unknown (00 00) at 175–176'), (177, 2, 'Mercenary Status'),
    (179, 4, 'Mercenary ID'), (183, 2, 'Mercenary Name'), (185, 2, 'Mercenary Code'),
    (187, 4, 'Mercenary Experience'), (191, 144, 'Unknown at 191–334'),
)
EARLY_HEADER_FIELDS = (
    (0, 4, 'Char File Header'), (4, 4, 'Version Number'), (8, 16, 'Char Name'),
    (24, 4, 'Char Status and Title'), (28, 6, 'Unknown at 28–33'), (34, 2, 'Char Class'),
    (36, 2, 'Char Initial Displayed Level'), (38, 16, 'Equipment appearance'), (54, 16, 'Equipment colors'),
    (70, 16, 'Skill IDs and sides for F1–F8'), (86, 2, 'Left and Right Mouse Skill'),
    (88, 1, 'Difficulty and Starting Act'), (89, 37, 'Unknown at 89–125'), (126, 4, 'Map ID'),
)


def header_catalog(ch):
    from mxl_char import QUEST_OFF
    from mxl_early_save import HEADER_END

    gf, skills, items = ch.offsets
    quest = HEADER_END if ch.early else QUEST_OFF
    waypoint = quest + 298
    npc = waypoint + 80
    catalog = list(EARLY_HEADER_FIELDS if ch.early else HEADER_FIELDS)
    catalog.extend(((quest, 4, 'Quest Header Woo!'), (quest + 4, 6, 'Quest version and length')))
    difficulties = ('Normal', 'Nightmare', 'Hell')
    catalog.extend((quest + 10 + 96 * index, 96, f'{difficulty} Quest Data')
                   for index, difficulty in enumerate(difficulties))
    catalog.extend(((waypoint, 2, 'Waypoint Header WS'), (waypoint + 2, 6, 'Waypoint version and length')))
    for index, difficulty in enumerate(difficulties):
        start = waypoint + 8 + 24 * index
        catalog.extend(((start, 2, 'Unknown waypoint bytes (02 01)'),
                        (start + 2, 5, f'{difficulty} Waypoints'),
                        (start + 7, 17 + int(index == 2), 'Unknown waypoint bytes')))
    catalog.extend(((npc + 1, 51, 'NPC Introductions'), (gf, 2, 'Character Stats Header gf'),
                    (gf + 2, skills - gf - 2, 'Character Stats'),
                    (skills, 2, 'Character Skills Header if'), (skills + 2, items - skills - 2, 'Character Skills'),
                    (items, 4, 'Character Item List Header JM')))

    def add_records(entries, origin, location):
        for entry in entries:
            for index, item in enumerate((entry.it, *entry.it.get('socketed', ()))):
                label = f'{location} Socket {index}' if index else location
                catalog.append((origin + item['_offset'], item['_size'], f'{label}: {item["name"]}'))

    add_records(ch.items, 0, 'Character')
    offset = items + 4 + sum(ch._full_size(entry.it) for entry in ch.items)
    catalog.append((offset, 4, 'Corpse List Header JM'))
    special = special_sections(ch)
    for name, _start, _end, entries in special:
        if name == 'corpse':
            add_records(entries, offset, 'Corpse')
    offset += len(ch.corpse)
    if ch.has_jf:
        catalog.append((offset, 2, 'Hireling Header jf'))
        offset += 2
        if ch.merc_items is not None:
            catalog.append((offset, 4, 'Mercenary Item List Header JM'))
            add_records(ch.merc_items, 0, 'Mercenary')
            offset += 4 + sum(ch._full_size(entry.it) for entry in ch.merc_items)
    if ch.tail.startswith(b'kf'):
        catalog.append((offset, 2, 'Iron Golem Header kf'))
        for name, _start, _end, entries in special:
            if name == 'tail':
                add_records(entries, offset, 'Iron Golem')
    elif ch.early and ch.version == 71 and ch.tail.startswith(b'JM'):
        catalog.append((offset, 8, 'Classic Final Signature JM'))
    return catalog


def reverse_bits(blob):
    return ' '.join(f'{byte:08b}' for byte in reversed(blob))


def read_bits(value):
    bits = ''.join(value.split())
    if len(bits) % 8 or set(bits) - {'0', '1'}:
        raise ValueError('Enter a whole number of bytes using ones and zeroes.')
    return bytes(int(bits[index:index + 8], 2) for index in range(len(bits) - 8, -1, -8))


def bind_overwrite(entry, variable, alphabet, changed=None):
    """Overwrite one digit at the cursor, stepping over byte separators."""
    def overwrite(event):
        if entry.instate(['readonly']):
            return
        text = variable.get()
        if event.keysym in ('Left', 'Right') and not event.state & 0x5:
            delta = -1 if event.keysym == 'Left' else 1
            cursor = entry.index(tk.INSERT)
            cursor = max(0, min(len(text), cursor + delta))
            if text[cursor:cursor + 1] == ' ':
                cursor += delta
            entry.selection_clear()
            entry.icursor(cursor)
            return 'break'
        if event.keysym in ('BackSpace', 'Delete') or event.state & 0x4 and event.keysym.lower() in ('v', 'x'):
            return 'break'
        digit = event.char.upper()
        if not digit or event.state & 0xC or event.keysym in ('Return', 'KP_Enter', 'Tab', 'Escape'):
            return
        if digit not in alphabet:
            return 'break'
        begin = entry.index(tk.SEL_FIRST) if entry.selection_present() else entry.index(tk.INSERT)
        position = next((i for i in range(begin, len(text)) if text[i] != ' '), None)
        if position is not None:
            updated = text[:position] + digit + text[position + 1:]
            if changed is None or changed(updated, position):
                variable.set(updated)
                entry.selection_clear()
                end = position + 1
                entry.icursor(end + int(text[end:end + 1] == ' '))
        return 'break'

    entry.bind('<KeyPress>', overwrite, add='+')
    entry.bind('<<Paste>>', lambda _event: 'break')
    entry.bind('<<Cut>>', lambda _event: 'break')


def put_picked_up(win, blob):
    from mxl_creator_gui import clean
    from mxl_vanilla_he import draw_pickup

    item = blob_item(blob, win.data)
    win.app._capy_clip = blob, clean(item.get('name') or item['code'])
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
    entries = extras_entries(win.ch, include_socketed=True)
    total = sum(1 + len(e.it.get('socketed', ())) for e, owner in entries if not isinstance(owner, SocketChild))
    ttk.Label(header, text=f'Total Number of Items (including in sockets)  {total}').grid(row=0, column=0)
    offset = tk.StringVar(value='?')
    ttk.Label(header, text='Item Edit Bit Offset').grid(row=0, column=1, padx=5)
    ttk.Label(header, textvariable=offset).grid(row=0, column=2)
    from mxl_vanilla_he import ITEM_DECODE_VERSIONS, decode_version

    selected_decode = getattr(win, 'he_decode_version', decode_version(win.ch.version))
    ttk.Label(header, text=f'{ITEM_DECODE_VERSIONS[selected_decode]} Items').grid(row=1, column=0, sticky='w')
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


def apply_character_header(ch, edits):
    """Apply pending bytes using the file's physical header offsets."""
    if ch.early:
        from mxl_char import QUEST_OFF
        from mxl_early_save import HEADER_END, read_header

        raw = bytearray(ch.build())
        for offset, value in edits.items():
            raw[offset] = value
        updated = read_header(raw, QUEST_OFF)
        updated[0x2B] = ch.head[0x2B]
        ch._early_header = bytes(raw[:HEADER_END])
        ch.head[:] = updated
    else:
        for offset, value in edits.items():
            ch.head[offset] = value


def character_hex(page, win):
    raw = win.ch.build()
    address, value = tk.StringVar(value='0'), tk.StringVar()
    displayed = tk.StringVar(value=str(win.ch.level))
    real = tk.StringVar(value=str(win.ch.field('level')))
    ttk.Label(page, text='Character Hex (Plus Items as initially loaded)').pack(anchor='w')
    row = ttk.Entry(page, textvariable=value, font='TkFixedFont')
    row.pack(fill='x')
    if not allows(win, 'header'):
        row.state(['readonly'])
    shell = ttk.Frame(page)
    shell.pack(fill='both', expand=True)
    controls = ttk.Frame(shell)
    controls.pack(side='left', fill='both', expand=True)
    fields = tk.Listbox(shell, width=27, exportselection=False)
    fields.pack(side='right', fill='y')
    catalog = header_catalog(win.ch)
    for _start, length, label in catalog:
        fields.insert('end', f'{length} {label}')
    nav = ttk.Frame(controls)
    nav.pack(fill='x', pady=4)
    ttk.Label(nav, text='Left Byte Addr').pack(side='left')
    cursor = tk.StringVar(value='0')
    ttk.Label(nav, textvariable=cursor).pack(side='right')

    def show(start):
        start = max(0, min(start, len(raw) - 1))
        address.set(str(start))
        pending = getattr(win, 'he_header_bytes', {})
        value.set(' '.join(f'{pending.get(pos, byte):02X}'
                           for pos, byte in enumerate(raw[start:start + 301], start)))
        cursor.set(f'Cursor Byte {start}')

    def navigate(step=0):
        try:
            show(int(address.get()) + step)
        except ValueError:
            show(0)

    def stage(text, position):
        if not allows(win, 'header'):
            return False
        try:
            start = int(address.get())
            index = start + position // 3
            changed = bytes.fromhex(text)[position // 3]
            first = 8 if win.ch.early else 16
            if not first <= index < win.ch.offsets[0]:
                raise ValueError('The address must be inside the editable character header.')
            if win.changed_on_disk() or win.ch.build() != raw:
                raise ValueError('The character changed. Reopen Extras to continue.')
        except ITEM_ERRORS as error:
            win.set_status(str(error), True)
            return False
        if changed == raw[index]:
            win.he_header_bytes.pop(index, None)
        else:
            win.he_header_bytes[index] = changed
        if not win.ch.early:
            displayed.set(str(win.he_header_bytes.get(0x2B, win.ch.level)))
        win.update_dirty()
        return True

    bind_overwrite(row, value, '0123456789ABCDEF', stage)

    def write():
        nonlocal raw
        if not allows(win, 'header') or not win.he_header_bytes:
            return
        if win.changed_on_disk() or win.ch.build() != raw:
            win.set_status('The character changed. Reopen Extras to continue.', True)
            return
        win.save_progress()
        raw = win.ch.build()
        if not win.ch.early:
            displayed.set(str(win.he_header_bytes.get(0x2B, win.ch.level)))
        navigate()

    addr = ttk.Entry(nav, width=7, textvariable=address)
    addr.pack(side='left', padx=4)
    addr.bind('<Return>', lambda _event: navigate())
    for label, step in (('‹', -1), ('›', 1)):
        ttk.Button(nav, text=label, width=3, command=lambda delta=step: navigate(delta)).pack(side='left')
    ttk.Button(controls, text='Save Header Bytes', command=write).pack(anchor='w')
    def update_cursor(_event=None):
        try:
            cursor.set(f'Cursor Byte {int(address.get()) + row.index(tk.INSERT) // 3}')
        except ValueError:
            cursor.set('Cursor Byte ?')

    row.bind('<Return>', lambda _event: navigate())
    row.bind('<KeyRelease>', update_cursor)
    row.bind('<ButtonRelease-1>', update_cursor)
    fields.bind('<<ListboxSelect>>', lambda _event: fields.curselection() and show(
        catalog[fields.curselection()[0]][0]))
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
        if chosen < 0 or win.ch.early or not allows(win, 'header'):
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
            if not win.save('Hotkey saved.', operation='header'):
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
    if win.ch.early or not allows(win, 'header'):
        skill.configure(state='disabled')
    else:
        show()


def item_list(parent, win, entries, height):
    from mxl_rc_menu import clean_name
    widget = tk.Listbox(parent, exportselection=False, width=29, height=height)
    for entry, owner in entries:
        if isinstance(owner, SocketChild):
            location = f'  Socket {owner.index + 1}'
        elif isinstance(owner, tuple):
            location = 'Iron Golem' if owner[0] == 'tail' else 'Corpse'
        else:
            location = 'Merc' if owner else str(entry.it.get('location', ''))
        widget.insert('end', f'{location}  {clean_name(win, entry)}')
    if entries:
        widget.selection_set(0)
    return widget


def binary_key(entry, owner):
    if isinstance(owner, SocketChild):
        return (*binary_key(owner.parent, owner.owner), owner.index, bytes(entry.blob))
    return owner, bytes(entry.blob)


def stage_binary(win, entry, owner, bits):
    from mxl_char import Entry

    key = binary_key(entry, owner)
    if bits == reverse_bits(entry.blob).replace(' ', ''):
        win.he_binary_edits.pop(key, None)
    else:
        snapshot = Entry(entry.it, bytes(entry.blob), entry.classic)
        if isinstance(owner, SocketChild):
            parent = owner.parent
            owner = SocketChild(Entry(parent.it, bytes(parent.blob), parent.classic), owner.owner, owner.index)
        win.he_binary_edits[key] = snapshot, owner, bits
    win.update_dirty()


def apply_staged_binary(win):
    if not allows(win, 'item'):
        raise CharError('Item binary editing is disabled in Options.')
    replacements = tuple(win.he_binary_edits.values())
    updated_parents = {}
    try:
        for entry, owner, bits in replacements:
            blob = read_bits(bits)
            if isinstance(owner, SocketChild):
                key = binary_key(owner.parent, owner.owner)
                if key in win.he_binary_edits:
                    raise CharError('Save the parent and socket filler binary edits separately.')
                parent = updated_parents.get(key, owner.parent)
                current = SocketChild(parent, owner.owner, owner.index)
                updated_parents[key] = replace_item(
                    win, entry, bytes(entry.blob), blob, 'Binary item saved.', current, commit=False)
            else:
                replace_item(win, entry, bytes(entry.blob), blob, 'Binary item saved.', owner, commit=False)
    except ITEM_ERRORS as error:
        raise CharError(str(error)) from error


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
                        state='readonly' if not index or not allows(win, 'item') else 'normal')
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
            edit = win.he_binary_edits.get(binary_key(entry, owner)) if index else None
            bits = edit[2] if edit else reverse_bits(entry.blob).replace(' ', '')
            length = (len(bits) + 7) // 8
            try:
                start = max(1, min(int(address.get()) + step, length))
            except ValueError:
                start = length
            states[index] = sel[0], entry, start, bytes(entry.blob)
            address.set(str(start))
            visible = bits[max(0, len(bits) - start * 8):]
            text.set(' '.join(visible[i:i + 8] for i in range(0, len(visible), 8)))

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
    def stage(text, _position=None):
        if states[1] is None or not allows(win, 'item'):
            return False
        index, entry, start, before = states[1]
        _, owner = entries[index]
        previous = win.he_binary_edits.get(binary_key(entry, owner))
        full = previous[2] if previous else reverse_bits(before).replace(' ', '')
        stage_binary(win, entry, owner, full[:max(0, len(full) - start * 8)] + ''.join(text.split()))
        return True

    bind_overwrite(row, text, '01', stage)
    row.bind('<KeyRelease>', lambda _event: cursor.set(
        f'Cursor Bit Loc’n {len("".join(text.get()[row.index(tk.INSERT):].split()))}'))
    ttk.Label(page, textvariable=cursor).grid(row=8, column=0, sticky='w')

    def shift(insert):
        if not allows(win, 'item'):
            return
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
        staged = ' '.join(bits[i:i + 8] for i in range(0, len(bits), 8))
        if stage(staged):
            address.set(str((len(bits) + 7) // 8))
            show()

    def write():
        if states[1] is None:
            return
        index, entry, _start, before = states[1]
        _, owner = entries[index]
        key = binary_key(entry, owner)
        edit = win.he_binary_edits.get(key)
        if edit is None:
            return
        try:
            new = read_bits(edit[2])
            replace_item(win, entry, before, new, 'Binary item saved.', owner)
        except ITEM_ERRORS as error:
            messagebox.showerror('Item Binary Compare/Edit', str(error), parent=page)
            return
        # A newly saved item cannot be resolved by its former bytes.
        from mxl_char import Entry

        current = current_extras_entry(win, Entry(entry.it, new), owner)
        if current is not None:
            entries[index] = current, owner
        win.he_binary_edits.pop(key, None)
        first()
        show()

    row.bind('<Return>', lambda _event: show())
    for label, callback in (('Remove Bits', lambda: shift(False)), ('Insert Bits', lambda: shift(True)),
                            ('Save Binary Item', write)):
        ttk.Button(controls, text=label, command=callback).pack(side='left', padx=2)


def browse_attributes(parent, choices, select):
    import json
    from pathlib import Path

    catalog = json.loads(Path(__file__).with_name('mxl_he_magic_tree.json').read_text(encoding='utf-8'))
    labels, children = catalog['labels'], catalog['children']
    names = dict(choices)
    shown = set()
    top = tk.Toplevel(parent)
    top.title('Magic Attributes')
    top.transient(parent.winfo_toplevel())
    tree = ttk.Treeview(top, show='tree', selectmode='browse')
    tree.pack(side='left', fill='both', expand=True)
    scroll = ttk.Scrollbar(top, command=tree.yview)
    scroll.pack(side='right', fill='y')
    tree.configure(yscrollcommand=scroll.set)
    root = tree.insert('', 'end', text='All Magic', open=True)
    items = {}

    def fill(node, members):
        for member in members:
            if isinstance(member, str):
                branch = tree.insert(node, 'end', text=labels[member])
                fill(branch, children.get(member, ()))
            elif member in names:
                item = tree.insert(node, 'end', text=names[member])
                items[item] = member
                shown.add(member)

    fill(root, children.get('AllMagic', ()))
    extra = [sid for sid in names if sid not in shown]
    if extra:
        fill(tree.insert(root, 'end', text='Other game attributes'), extra)

    def choose(_event=None):
        entry = next(iter(tree.selection()), None)
        if entry in items:
            select(items[entry])
            top.destroy()

    tree.bind('<Double-Button-1>', choose)
    tree.bind('<Return>', choose)
    top.bind('<Escape>', lambda _event: top.destroy())
    tree.focus_set()


def skill_tab_choices(data):
    from mxl_char import class_names, skill_trees

    names = class_names(data)
    return [(f'{names[cls]} — {name}', cls << 3 | (tab - 1))
            for cls, tabs in skill_trees(data).items() for tab, name, _skills in tabs if 1 <= tab <= 3]


def is_timed_stat(data, sid):
    return 268 <= sid <= 304 and data.isc[sid]['bits'] == 22 and not data.isc[sid]['param']


def time_values(number):
    return number & 3, (number >> 2 & 1023) - 256, (number >> 12 & 1023) - 256


def pack_time_values(time, minimum, maximum):
    if not (0 <= time < 4 and -256 <= minimum <= 767 and -256 <= maximum <= 767):
        raise ValueError('Time ranges accept values from -256 to 767.')
    return time | (minimum + 256) << 2 | (maximum + 256) << 12


def move_attribute(rows, index, delta):
    from mxl_format import STAT_GROUPS

    chunks = []
    cursor = 0
    while cursor < len(rows):
        start = cursor
        cursor += 1
        for follower in STAT_GROUPS.get(rows[start]['id'], ()):
            if cursor < len(rows) and rows[cursor]['id'] == follower:
                cursor += 1
        chunks.append((start, cursor))
    selected = next((i for i, (start, end) in enumerate(chunks) if start <= index < end), None)
    if selected is None or not 0 <= selected + delta < len(chunks):
        return None
    other = selected + delta
    start, _end = chunks[selected]
    chunks[selected], chunks[other] = chunks[other], chunks[selected]
    updated = [row for begin, end in chunks for row in rows[begin:end]]
    rows[:] = updated
    return sum(end - begin for begin, end in chunks[:other]) + index - start


class ItemEdit:
    GROUPS = {
        'Basic1': ('flags', *BASIC_FLAGS, 'version'),
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
        self.decode_error = ''
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
        self.selection, self.entry = index, entry
        self.original = bytes(entry.blob)
        self.removed = None
        self.dirty = False
        self.decode_error = ''
        try:
            self.record, self.children = decode_blob(entry.blob, self.win.data)
        except ITEM_ERRORS as error:
            self.record, self.children = {}, []
            self.decode_error = str(error)
        self.render_icon(entry.it)
        group, _, quality = self.initial.partition(':')
        self.initial = 'Basic1'
        self.rebuild(group)
        if self.record and group == 'Quality' and quality:
            self.stage_quality(quality)

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
                if field in self.record or field in BASIC_FLAGS and self.record:
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

    def stage_quality(self, quality):
        from mxl_rc_menu import _creator_for, _quality_to

        if not allows(self.win, 'item'):
            return
        creator = _creator_for(self.win)
        data = self.win.data
        code = self.record['code']
        pick = pick2 = None
        target = {'low': 'subquality', 'superior': 'subquality', 'magic': 'prefix',
                  'set': 'set_unique_id', 'unique': 'set_unique_id',
                  'rare': 'rare_names', 'crafted': 'rare_names'}.get(quality)
        if quality in ('set', 'unique'):
            rows = creator.set_items() if quality == 'set' else creator.uniques()
            pick = next(key for key, _label, row in rows if row['code'] == code)
        elif quality in ('rare', 'crafted'):
            names = creator.rare_name_choices(code)
            pick, pick2 = names['rareprefix'][0][0], names['raresuffix'][0][0]
        try:
            record = dict(self.record)
            _quality_to(record, creator, data, code, quality, pick, pick2)
            if quality == 'low':
                record['subquality'] = 0
            encode_modified(record, self.children, data)
        except ITEM_ERRORS as error:
            self.error(error)
            return
        self.record = record
        self.dirty = True
        self.rebuild(f'Quality:{target}' if target else 'Quality')

    def select_base(self):
        from mxl_creator import FLAG_PERSONALIZED, FLAG_SOCKETED
        from mxl_rc_menu import _ask_pick, _creator_for

        if not allows(self.win, 'item') or isinstance(self.entries[self.selection][1], SocketChild):
            return
        creator = _creator_for(self.win)
        data = self.win.data
        if self.children or self.record['flags'] & (FLAG_SOCKETED | FLAG_RUNEWORD):
            self.error('Remove sockets before changing the base type.')
            return

        def swap(code):
            if code == self.record['code']:
                return
            try:
                fresh, _ = creator.build(creator.new_spec('normal', code))
                record, _ = decode_item(fresh, data)
                for field in self.GROUPS['Location - View Only']:
                    record[field] = self.record[field]
                if not record['flags'] & FLAG_SIMPLE:
                    for field in ('id', 'ilvl', 'stats', 'personalized_name'):
                        if field in self.record:
                            record[field] = self.record[field]
                    if 'personalized_name' in record:
                        record['flags'] |= FLAG_PERSONALIZED
                encode_modified(record, [], data)
            except ITEM_ERRORS as error:
                self.error(error)
                return
            self.record, self.dirty = record, True
            self.rebuild('Item Code:code')

        _ask_pick(self.page, 'Base type', [(base.code, creator.display_name(base.code))
                                         for base in creator.bases() if base.code != 'ear '], swap)

    def display(self, _event=None):
        for widget in self.details.winfo_children():
            widget.destroy()
        selected = next(iter(self.tree.selection()), 'Basic1')
        group, _, field = selected.partition(':')
        self.details.configure(text=group)
        self.offsets.clear()
        if not self.record:
            self.offset.set('?')
            if self.decode_error:
                ttk.Label(self.details, text=self.decode_error, wraplength=200).pack(anchor='w')
            return
        try:
            blob = encode_modified(self.record, self.children, self.win.data) if self.dirty else self.original
            decode_item(blob, self.win.data, offsets=self.offsets)
        except ITEM_ERRORS:
            self.offsets.clear()
        offset_key = self.MAGIC.get(group, field or self.GROUPS.get(group, ('',))[0])
        if group in self.MAGIC and field:
            offset_key += ':' + field
        bit_offset = 16 + BASIC_FLAGS[field][0] if field in BASIC_FLAGS else self.offsets.get(offset_key, '?')
        self.offset.set(str(bit_offset))
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
        if field in BASIC_FLAGS:
            start, bits = BASIC_FLAGS[field]
            value = self.record['flags'] >> start & ((1 << bits) - 1)
            if field in STRUCTURAL_FLAGS:
                ttk.Label(self.details, text='Yes' if value else 'No').pack(anchor='w')
                ttk.Button(self.details, text='Clear Flag' if value else 'Set Flag',
                           command=lambda: self.stage_structural_flag(field, not value)).pack(anchor='w')
                return
            selected = tk.IntVar(self.details, value=value)

            def apply_flag():
                mask = ((1 << bits) - 1) << start
                self.stage_field('flags', self.record['flags'] & ~mask | selected.get() << start)

            if bits == 1:
                ttk.Checkbutton(self.details, text=field.replace('_', ' ').title(), variable=selected,
                                command=apply_flag).pack(anchor='w')
            else:
                ttk.Spinbox(self.details, textvariable=selected, from_=0, to=(1 << bits) - 1,
                            width=7, state='readonly', command=apply_flag).pack(anchor='w')
            return
        value = self.record[field]
        if field == 'code' and value != 'ear ':
            ttk.Button(self.details, text='Choose Base Type…', command=self.select_base).pack(anchor='w')
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

    def stage_structural_flag(self, field, enabled):
        from mxl_creator import FLAG_PERSONALIZED, FLAG_SOCKETED
        from mxl_rc_menu import _creator_for
        from mxl_socket_menu import _drop_runeword, max_sockets

        if not allows(self.win, 'item'):
            return
        if field == 'ear':
            messagebox.showinfo('Item Edit', 'Ear flag editing is unfinished.', parent=self.page)
            return
        record = dict(self.record)
        bit = 1 << BASIC_FLAGS[field][0]
        record['flags'] = record['flags'] | bit if enabled else record['flags'] & ~bit
        try:
            if field == 'socketed':
                if enabled:
                    if record['flags'] & (FLAG_SIMPLE | FLAG_EAR):
                        raise ValueError('This item layout has no socket count field.')
                    cap = max_sockets(_creator_for(self.win), record['code'], record)
                    if not cap:
                        raise ValueError('The base item has no sockets available.')
                    record.update(sockets=cap, socketed_count=0)
                elif self.children:
                    raise ValueError('Remove the socketed items before clearing the socketed flag.')
                else:
                    record.pop('sockets', None)
                    record['socketed_count'] = 0
            elif field == 'personalized':
                if enabled:
                    if record['flags'] & (FLAG_SIMPLE | FLAG_EAR):
                        raise ValueError('This item layout has no personalization field.')
                    record['personalized_name'] = self.win.ch.name
                else:
                    record.pop('personalized_name', None)
            elif field == 'runeword':
                if enabled:
                    if record['flags'] & (FLAG_SIMPLE | FLAG_EAR):
                        raise ValueError('This item layout has no runeword field.')
                    record['runeword_id'] = 0xFFFF
                    record['stats_runeword'] = []
                else:
                    record['flags'] |= FLAG_RUNEWORD
                    _drop_runeword(record)
            else:
                from random import getrandbits

                if record['flags'] & FLAG_EAR or enabled and record['flags'] & (
                        FLAG_SOCKETED | FLAG_RUNEWORD | FLAG_PERSONALIZED):
                    raise ValueError('Clear the structural flags before changing this layout.')
                if enabled and record.get('stats') and not messagebox.askyesno(
                        'Simple Item', 'The compact layout discards magic attributes. Continue?', parent=self.page):
                    return
                if not enabled and 'id' not in record:
                    creator = _creator_for(self.win)
                    code = record['code']
                    baseline, _ = creator.build(creator.new_spec('normal', code))
                    defaults, _ = decode_item(baseline, self.win.data)
                    defaults.update(record)
                    record = defaults
                    record.setdefault('id', getrandbits(32))
                    record.setdefault('ilvl', 1)
                    record.setdefault('quality', 'normal')
            encode_modified(record, self.children, self.win.data)
        except ITEM_ERRORS as error:
            self.error(error)
            return
        self.record, self.dirty = record, True
        self.rebuild(f'Basic1:{field}')

    def stage_field(self, field, value):
        if not allows(self.win, 'item'):
            return
        record = dict(self.record, **{field: value})
        try:
            if field == 'flags':
                structural = sum(1 << BASIC_FLAGS[key][0] for key in STRUCTURAL_FLAGS)
                if (value ^ self.record[field]) & structural:
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
        if field == 'subquality':
            if self.record['quality'] == 'low':
                return list(enumerate(('Crude', 'Cracked', 'Damaged', 'Low Quality')))
            from mxl_rc_menu import _creator_for, _sup_label

            return [(index, _sup_label(self.win, index))
                    for index in _creator_for(self.win).superior_choices(self.record['code'])]
        if field not in ('image', 'auto_affix', 'prefix', 'suffix', 'set_unique_id', 'runeword_id'):
            return []
        from mxl_rc_menu import _creator_for

        creator = _creator_for(self.win)
        code = self.record['code']
        if field == 'image':
            base = self.win.data.base(code)
            variants = self.win.data.itype_gfx[base.type]
            return [(None, 'Default appearance'), *((index, name) for index, name in enumerate(variants)
                                                     if name)] if variants else []
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
        from mxl_format import STAT_GROUPS
        from mxl_statnames import encode_skill_param, param_bits, param_choices, param_kind

        data = self.win.data
        key = self.MAGIC[group]
        rows = self.record.setdefault(key, [])
        current = rows[index] if index < len(rows) else None
        choices = _creator_for(self.win).stat_choices()
        labels = [label for _sid, label in choices]
        attribute = ttk.Combobox(self.details, values=labels, state='readonly', width=25)
        attribute.pack(fill='x')

        def pick(sid):
            attribute.current(next(index for index, (key, _label) in enumerate(choices) if key == sid))
            configure()

        ttk.Button(self.details, text='Browse Attributes…',
                   command=lambda: browse_attributes(self.details, choices, pick)).pack(anchor='w')
        value = ttk.Combobox(self.details, width=12)
        param = ttk.Combobox(self.details, width=25)
        params = {}
        skill_level = tk.StringVar(value='1')
        level = ttk.Entry(self.details, textvariable=skill_level, width=6)
        max_charges = tk.StringVar(value='0')
        charges_label = ttk.Label(self.details, text='Maximum charges')
        charges = ttk.Combobox(self.details, textvariable=max_charges, width=8)
        times = ('Daytime', 'Dusk', 'Nighttime', 'Dawn')
        span = ttk.Combobox(self.details, values=times, state='readonly', width=12)
        extra = ttk.Frame(self.details)
        components = []

        def configure(_event=None):
            sid = choices[attribute.current()][0]
            for child in extra.winfo_children():
                child.destroy()
            components.clear()
            span.pack_forget()
            lo, hi = value_range(data, sid)
            value.configure(values=tuple(range(lo, hi + 1)) if hi - lo <= 256 else ())
            same = current is not None and current['id'] == sid
            number = current['value'] if same else max(lo, min(hi, 0))
            if sid == CHARGED_SKILL:
                charges_label.configure(text='Maximum charges')
                value.configure(values=tuple(range(256)))
                charges.configure(values=tuple(range(256)))
                value.set(str(number & 255))
                max_charges.set(str(number >> 8))
                charges_label.pack(anchor='w', before=apply_button)
                charges.pack(anchor='w', before=apply_button)
            elif is_timed_stat(data, sid):
                time, minimum, maximum = time_values(number) if same else (0, 0, 0)
                value.configure(values=tuple(range(-256, 768)))
                charges.configure(values=tuple(range(-256, 768)))
                value.set(str(minimum))
                span.current(time)
                span.pack(anchor='w', before=apply_button)
                max_charges.set(str(maximum))
                charges_label.configure(text='Maximum')
                charges_label.pack(anchor='w', before=apply_button)
                charges.pack(anchor='w', before=apply_button)
            else:
                value.set(str(number))
                charges_label.pack_forget()
                charges.pack_forget()
            if sid in STAT_GROUPS:
                labels = {18: 'Minimum damage %', 49: 'Maximum fire damage', 51: 'Maximum lightning damage',
                          53: 'Maximum magic damage', 55: 'Maximum cold damage', 56: 'Cold duration',
                          58: 'Maximum poison damage', 59: 'Poison duration'}
                for offset, stat in enumerate(STAT_GROUPS[sid], 1):
                    lo, hi = value_range(data, stat)
                    existing = rows[index + offset] if same and index + offset < len(rows) else {}
                    default = existing['value'] if existing.get('id') == stat else max(lo, min(0, hi))
                    var = tk.StringVar(extra, value=str(default))
                    ttk.Label(extra, text=labels[stat]).pack(anchor='w')
                    ttk.Entry(extra, textvariable=var, width=8).pack(anchor='w')
                    components.append((stat, var))
            params.clear()
            bits = param_bits(data, sid)
            if bits:
                params.update(skill_tab_choices(data) if sid == 188 else param_choices(data, sid))
            param.configure(values=tuple(params), state='normal' if bits else 'disabled')
            raw = (current.get('param') or 0) if same else 0
            skill = sid != 188 and param_kind(sid) == 'skill'
            level.configure(state='normal' if skill else 'disabled')
            if skill:
                skill_level.set(str(raw & 63 if same else 1))
                raw >>= 6
            param.set(next((name for name, val in params.items() if val == raw), str(raw)) if bits else 'Unused')

        def stage(remove=False):
            if not allows(self.win, 'item'):
                return
            try:
                end = index + 1
                if current:
                    for sid in STAT_GROUPS.get(current['id'], ()):
                        if end < len(rows) and rows[end]['id'] == sid:
                            end += 1
                if remove:
                    if current is None:
                        return
                    del rows[index:end]
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
                    if is_timed_stat(data, sid):
                        number = pack_time_values(span.current(), number, int(max_charges.get()))
                    lo, hi = value_range(data, sid)
                    if not lo <= number <= hi:
                        raise ValueError(f'Value must be between {lo} and {hi}.')
                    raw = None
                    bits = param_bits(data, sid)
                    if bits:
                        raw = params[param.get()] if param.get() in params else int(param.get(), 0)
                        if sid != 188 and param_kind(sid) == 'skill':
                            raw, why = encode_skill_param(data, sid, f'#{raw}', int(skill_level.get()))
                            if why:
                                raise ValueError(why)
                        if not 0 <= raw < 1 << bits:
                            raise ValueError('The parameter does not fit this attribute.')
                    edited = [dict(id=sid, param=raw, value=number)]
                    for stat, var in components:
                        lo, hi = value_range(data, stat)
                        amount = int(var.get())
                        if not lo <= amount <= hi:
                            raise ValueError(f'Component {stat} must be between {lo} and {hi}.')
                        edited.append(dict(id=stat, param=None, value=amount))
                    rows[index:end] = edited
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
        extra.pack(fill='x')
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
        if group not in self.MAGIC or not slot or not allows(self.win, 'item'):
            return
        rows = self.record.get(self.MAGIC[group], [])
        moved = move_attribute(rows, int(slot), delta)
        if moved is not None:
            self.dirty = True
            self.rebuild(f'{group}:{moved}')

    def copy(self):
        if self.entry is not None and self.record:
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
        from mxl_creator import FLAG_PERSONALIZED, Tables
        from mxl_char import check_name
        from mxl_rc_menu import _creator_for
        from mxl_socket_insert import socket_total
        from mxl_socket_menu import max_sockets

        if self.decode_error:
            self.error(self.decode_error)
            return
        if self.entry is not None:
            try:
                data = self.win.data
                record = self.record
                blob = encode_modified(record, self.children, data)
                blob_item(blob, data)
                base = data.base(record['code'])
                warnings = []
                if not self.dirty and not self.original.startswith(b'JM'):
                    warnings.append('Item signature differs from JM.')
                elif not self.dirty:
                    original, used = decode_item(self.original, data)
                    expected = encode_modified(original, self.children, data)
                    if len(blob) != len(self.original) or expected[:used] != self.original[:used]:
                        warnings.append('The original item has trailing bits or a noncanonical layout.')
                if not record['flags'] & FLAG_IDENTIFIED:
                    warnings.append('The item is unidentified.')
                if not record['flags'] & FLAG_EAR:
                    compact = bool(Tables(data).item[record['code']]['compact'])
                    if bool(record['flags'] & FLAG_SIMPLE) != compact:
                        warnings.append('The simple flag differs from the base item layout.')
                if record['flags'] & FLAG_PERSONALIZED:
                    try:
                        check_name(record.get('personalized_name', ''))
                    except CharError as error:
                        warnings.append(f'Personalized name: {error}')
                if record['flags'] & FLAG_RUNEWORD and not record.get('stats_runeword'):
                    warnings.append('The runeword has no magic attributes.')
                for label, field in self.MAGIC.items():
                    rows = record.get(field, ())
                    keys = [(stat['id'], stat.get('param')) for stat in rows]
                    if len(keys) != len(set(keys)):
                        warnings.append(f'{label} contains duplicate attributes.')
                    if label.startswith('Set') and record.get('quality') == 'set':
                        index = int(label[3]) - 1
                        if bool(rows) != bool(record['set_mask'] & 1 << index):
                            warnings.append(f'{label} presence differs from the set list flags.')
                if 'quantity' in record and record['quantity'] > base.stack_max:
                    warnings.append(f'Quantity exceeds the base limit of {base.stack_max}.')
                if 'durability' in record:
                    import stat_ids as S

                    maximum = record['max_durability'] - data.isc[S.MAX_DURABILITY]['add']
                    current = record['durability'] - data.isc[S.DURABILITY]['add']
                    if current > maximum:
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
            replace_item(self.win, self.entry, self.original, blob, 'Modified item saved.', owner,
                         allow_type_change=self.record['code'] != self.entry.it['code'])
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
                    if (getattr(entry.blob, 'v109_raw', False) or getattr(entry.blob, 'read_only_reason', None)
                            or getattr(entry.blob, 'edit_reason', None)):
                        continue
                    blob = self.without_attribute(entry.blob, stat_id)
                    if blob is not None:
                        item = blob_item(blob, win.data)
                        replacement = Entry(item, blob, entry.classic)
                        if ch.old:
                            ch._old_blob(replacement)
                        if name:
                            edited[index] = replacement
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


def populate_item_tree(tree, creator):
    import json
    from pathlib import Path

    path = Path(__file__).with_name('mxl_he_item_tree.json')
    rows = json.loads(path.read_text(encoding='utf-8'))
    labels, children = rows['labels'], rows['children']
    by_code = {}

    def item(parent, code):
        iid = 'base:' + code
        tree.insert(parent, 'end', iid=iid, text=creator.display_name(code))
        by_code[code.strip()] = iid

    def group(parent, key):
        iid = 'category:' + key
        tree.insert(parent, 'end', iid=iid, text=labels[key])
        for member in children.get(key, ()):
            if member in labels:
                group(iid, member)
            elif member in creator.data.bases and member.strip() not in by_code:
                item(iid, member)

    for key in children['AllItems']:
        group('all', key)
    roots = {'armor': 'Armor', 'weapons': 'Weapons', 'misc': 'Misc'}
    for base in sorted(creator.bases(), key=lambda base: creator.display_name(base.code).casefold()):
        if base.kind in roots and base.code.strip() not in by_code:
            item('category:' + roots[base.kind], base.code)
    return by_code


def create_item_blob(creator, code):
    import settings
    from mxl_creator import FLAG_NEW, encode_item
    from mxl_vanilla_he import ITEM_LEVEL

    data = creator.data
    spec = creator.new_spec('normal', code)
    saved_level = settings.get(ITEM_LEVEL)
    level = saved_level if saved_level in (10, 90, 99) else 90
    spec['ilvl'] = max(level, spec['ilvl'])
    blob, _ = creator.build(spec)
    record, _ = decode_item(blob, data)
    record.update(flags=record['flags'] | FLAG_NEW, version=100, location=0, equipped=0, x=0, y=0, panel=0)
    if not record['flags'] & FLAG_SIMPLE:
        if code not in ('tbk ', 'ibk '):
            record.update(quality='superior', subquality=1)
        else:
            record['tome_bits'] = int(code == 'ibk ')
        if 'defense' in record:
            record['defense'] = 10
        if 'max_durability' in record:
            record['max_durability'] = data.isc[73]['add']
            record.pop('durability', None)
        if 'quantity' in record:
            record['quantity'] = min(10, data.base(code).stack_max)
        if creator.image_count(code):
            record['image'] = 0
    return encode_item(record, data)


def create_items(page, win):
    from mxl_creator_gui import CreatorWindow
    from mxl_newchar import NewCharError, create_reference_clone, open_dialog
    from mxl_rc_menu import _creator_for
    creator = _creator_for(win)
    tree = ttk.Treeview(page, show='tree', height=11, selectmode='browse')
    tree.column('#0', width=175)
    tree.pack(side='left', fill='y')
    tree.insert('', 'end', iid='all', text='All Items')
    by_code = populate_item_tree(tree, creator)
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
            blob = ear_blob(win, win.ch.name, win.ch.cls, 99) if item_code == 'ear ' else create_item_blob(creator, item_code)
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
            try:
                put_picked_up(win, ear_blob(win, win.ch.name, win.ch.cls, 99))
            except ITEM_ERRORS as error:
                messagebox.showerror('Item Create', str(error), parent=page)
            return
        try:
            put_picked_up(win, create_item_blob(creator, iid[5:]))
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
        ('V1.03', 71, 0, 0), ('V1.07', 87, 0, 1), ('V1.09D', 92, 1, 0), ('V1.10s beta', 95, 1, 1),
        ('V1.10/V1.11/V1.12/V1.13', 96, 2, 0),
    ):
        ttk.Button(new, text=label, command=lambda v=version: open_dialog(win.app, initial_version=v)).grid(
            row=row, column=col, columnspan=2 if row == 2 else 1, sticky='ew')
    def clone():
        try:
            path = create_reference_clone(win.app)
        except (NewCharError,) + ITEM_ERRORS as error:
            messagebox.showerror('V1.12 Clone', str(error), parent=page)
            return
        from pathlib import Path

        name = Path(path).stem
        page.winfo_toplevel().destroy()
        win.app.select_character(name, win.app.view.get())

    ttk.Button(new, text='V1.12 Clone', command=clone).grid(row=3, column=0, columnspan=2, sticky='ew')


def ear_blob(win, name, cls, level):
    from mxl_char import check_name
    from mxl_creator import FLAG_ALWAYS, encode_item

    check_name(name)
    return encode_item(dict(code='ear ', flags=FLAG_EAR | FLAG_SIMPLE | FLAG_IDENTIFIED | FLAG_ALWAYS,
                            ear_name=name, ear_class=cls, ear_level=level, panel=1), win.data)
