"""Vanilla item commands and persistent magic-attribute favorites."""
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import tkinter as tk
from tkinter import messagebox, simpledialog

import stat_ids as S
from mxl_creator import (
    CreateError, FLAG_ETHEREAL, FLAG_PERSONALIZED, FLAG_RUNEWORD, FLAG_SIMPLE,
    FLAG_SOCKETED, decode_item, encode_item,
)
from mxl_format import FormatError
from mxl_format_fix import body_kind
from mxl_char import CharError, blob_item
from mxl_save import EditError
from mxl_socket_menu import SocketError
from mxl_socket_insert import InsertError

FLAG_STARTER = 1 << 17
ITEM_ERRORS = (CharError, CreateError, EditError, FormatError, OSError, ValueError, OverflowError, KeyError, IndexError, SocketError, InsertError)


def special_sections(ch):
    """Return each vanilla corpse item list and the optional Iron Golem record."""
    from mxl_char import Entry, read_item_list

    from mxl_early_save import ClassicData
    from mxl_v109 import Data109

    if ch.version == 71:
        data = ClassicData(ch.data)
    elif ch.old:
        data = Data109(ch.data, ch.version)
    else:
        data = ch.data

    def entry(item, content):
        if ch.old:
            return ch._entry_old(item, content)
        start = item['_offset']
        return Entry(item, content[start:start + ch._full_size(item)])

    sections = []
    pos = 4
    for _ in range(int.from_bytes(ch.corpse[2:4], 'little')):
        start = pos + 14  # corpse metadata and the item list's JM marker
        count = int.from_bytes(ch.corpse[start:start + 2], 'little')
        items, pos = read_item_list(ch.corpse, start + 2, count, data)
        entries = [entry(it, ch.corpse) for it in items]
        sections.append(('corpse', start, pos, entries))
    if not ch.early and ch.tail.startswith(b'kf\x01JM'):
        items, end = read_item_list(ch.tail, 3, 1, data)
        sections.append(('tail', 2, end, [entry(items[0], ch.tail)]))
    return sections


def write_special_sections(ch, sections):
    for name, start, end, entries in reversed(sections):
        content = getattr(ch, name)
        count = bytes([len(entries)]) if name == 'tail' else struct.pack('<H', len(entries))
        setattr(ch, name, content[:start] + count + b''.join(ch._old_blob(e) if ch.old else e.blob for e in entries) + content[end:])


@dataclass
class SocketChild:
    parent: object
    owner: object
    index: int


def socket_parts(blob, data):
    from mxl_socket_insert import children

    _record, parts = children(blob, data)
    return blob[:len(blob) - sum(map(len, parts))], parts


def extras_entries(ch, *, include_socketed=False):
    entries = [(entry, merc) for merc in (False, True) for entry in ch.entries(merc)]
    for section, (name, _, _, items) in enumerate(special_sections(ch)):
        entries.extend((entry, (name, section, index)) for index, entry in enumerate(items))
    if not include_socketed:
        return entries
    from mxl_char import Entry

    expanded = []
    for entry, owner in entries:
        expanded.append((entry, owner))
        if not entry.it.get('socketed'):
            continue
        try:
            _, parts = socket_parts(entry.blob, ch.data)
            expanded.extend((Entry(item, blob), SocketChild(entry, owner, index))
                            for index, (item, blob) in enumerate(zip(entry.it['socketed'], parts)))
        except ITEM_ERRORS:
            pass
    return expanded


def current_extras_entry(win, entry, owner):
    if isinstance(owner, SocketChild):
        from mxl_char import Entry

        parent = current_extras_entry(win, owner.parent, owner.owner)
        if parent is not None:
            _, parts = socket_parts(parent.blob, win.data)
            index = owner.index
            if index < len(parts) and parts[index] == entry.blob:
                return Entry(parent.it['socketed'][index], parts[index])
        return None
    if not isinstance(owner, tuple):
        return win.current_entry(entry, owner)
    name, section, index = owner
    sections = special_sections(win.ch)
    if section < len(sections) and sections[section][0] == name:
        items = sections[section][3]
        if index < len(items) and items[index].blob == entry.blob:
            return items[index]
    return None


def golem_menu(win, control, event=None):
    from mxl_rc_menu import _record_char_write
    from mxl_vanilla_he_extras import put_picked_up

    win.sync_file()
    try:
        index, section = next(((index, section) for index, section in enumerate(special_sections(win.ch))
                               if section[0] == 'tail'), (None, None))
    except ITEM_ERRORS as error:
        win.set_status(str(error), True)
        return
    if section is None:
        return
    name, _, _, (entry,) = section
    owner = (name, index, 0)
    if event is None:
        edit_item(win, owner)
        return

    def remove():
        if not messagebox.askyesno('Iron Golem', 'Delete the Iron Golem item?', parent=win.top):
            return
        win.sync_file()
        ch = win.ch
        if current_extras_entry(win, entry, owner) is None:
            win.set_status('The Iron Golem item has changed.', True)
            return
        name, start, end, _ = special_sections(ch)[index]
        before, tail = bytes(ch.raw), ch.tail
        write_special_sections(ch, [(name, start, end, [])])
        if win.save('Iron Golem item deleted.'):
            _record_char_write(win, ch.path, before, 'Iron Golem item deleted')
        else:
            ch.tail = tail

    menu = tk.Menu(control, tearoff=False)
    menu.add_command(label='Edit Iron Golem item…', command=lambda: edit_item(win, owner))
    menu.add_command(label='Copy into Picked Up', command=lambda: put_picked_up(win, entry.blob))
    menu.add_command(label='Delete Iron Golem item', command=remove)
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


def edit_item(win, entry, group='Basic1'):
    from mxl_vanilla_he import extras

    return extras(win, entry=entry, group=group)


def replace_item(win, entry, before, blob, caption, owner=None, *, allow_type_change=False, commit=True):
    """Verify a replacement and preserve its position, including belt items."""
    import mxl_profile
    from mxl_rc_menu import _record_char_write

    if mxl_profile.is_median():
        raise CharError('This command requires a vanilla character.')
    original = win.ch
    if commit:
        win.sync_file()
    if original.path != win.ch.path:
        raise CharError('The selected character has changed.')
    if owner is None:
        current = win.current_entry(entry, False) or win.current_entry(entry, True)
    else:
        current = current_extras_entry(win, entry, owner)
    if current is None or bytes(current.blob) != before:
        raise CharError('The selected item has changed.')
    from mxl_socket_insert import children

    _record, used = decode_item(blob, win.data)
    _record, socketed = children(blob, win.data)
    if used + sum(map(len, socketed)) != len(blob):
        raise CharError('The bytes do not form one complete item and its socketed items.')
    item = blob_item(blob, win.data)
    if item['code'] != current.it['code']:
        if not allow_type_change:
            raise CharError('The replacement changes the item type.')
        validate_replacement_size(win, current, item, owner)
    position = ('location', 'equipped', 'x', 'y', 'panel')
    if any(item.get(key) != current.it.get(key) for key in position):
        raise CharError('The replacement changes the item location.')
    if isinstance(owner, SocketChild):
        from mxl_char import Entry

        if socketed:
            raise CharError('A socket filler must be a single item record.')
        parent = current_extras_entry(win, owner.parent, owner.owner)
        header, parts = socket_parts(parent.blob, win.data)
        parts[owner.index] = blob
        updated = header + b''.join(parts)
        replace_item(win, parent, bytes(parent.blob), updated, caption, owner.owner, commit=commit)
        actual = current_extras_entry(win, Entry(parent.it, updated), owner.owner)
        if commit:
            owner.parent = actual
        return actual
    ch = win.ch
    snapshot = bytes(ch.raw)
    corpse, tail = ch.corpse, ch.tail
    old_item = current.it
    if win.ch.old:
        from mxl_char import Entry

        # Validate against the original layout before replacing the normalized record.
        win.ch._old_blob(Entry(item, blob, current.classic))
    current.blob, current.it = blob, item
    try:
        if isinstance(owner, tuple):
            _, section, index = owner
            part = special_sections(ch)[section]
            part[3][index] = current
            write_special_sections(ch, [part])
        if commit and not win.save(caption):
            raise CharError('The item could not be saved.')
    except ITEM_ERRORS:
        current.blob, current.it = before, old_item
        ch.corpse, ch.tail = corpse, tail
        raise
    if commit:
        _record_char_write(win, original.path, snapshot, caption)


def character_report(win):
    from pathlib import Path
    from mxl_char import LOC_BELT, LOC_EQUIPPED, LOC_STORED, PANEL_CUBE, PANEL_INVENTORY, class_names, slot_name
    from mxl_creator import FLAG_ETHEREAL, PANEL_STASH
    from mxl_creator import decode_blob, merge_stats
    from mxl_rc_menu import clean_name
    from mxl_statnames import stat_text
    from mxl_vanilla_he import ITEM_DECODE_VERSIONS, character_title, decode_version

    ch, data = win.ch, win.data
    version = ITEM_DECODE_VERSIONS[decode_version(ch.version)]
    expansion = 'LOD' if ch.flags()['expansion'] else 'NOX'
    title = character_title(ch)
    lines = [Path(ch.path).name, f'Version: {version}, {expansion}',
             f'Title: {title}', f'Type: {class_names(data)[ch.cls]}',
             f'File Size: {len(ch.raw)} bytes', '', 'Character Stats:']
    lines.extend((f'  Level = {ch.stat(12)}', f'  Experience = {ch.stat(13)}'))
    for name, sid in (('Life', 6), ('Mana', 8), ('Stamina', 10)):
        whole, fraction = divmod(ch.stat(sid + 1), 256)
        lines.extend((f'  Current {name} = {ch.stat(sid) // 256}', f'  Max {name} = {whole}',
                      f'  Max {name} Fraction = {fraction}'))
    for name, sid in (('Strength', 0), ('Energy', 1), ('Dexterity', 2), ('Vitality', 3)):
        lines.append(f'  {name} = {ch.stat(sid)}')
    lines.extend(('', 'Skills:'))
    lines.extend(f'  {data.skill_names.get(sid, sid)} = {level}' for sid, level in ch.skill_levels().items())
    entries = extras_entries(ch)
    lines.extend(('', 'Items (SUMMARY follows the individual item list):', f' Number of Items = {len(entries)}'))
    non_weapons = 'Charms in Inventory + Equipped (not in hands)'
    sections = {non_weapons: []}
    weapon_names = {4: 'Right Hand', 5: 'Left Hand', 11: 'Alternate Right Hand', 12: 'Alternate Left Hand'}
    magic_lists = {'stats': 'Normal Magic', **{f'set_stats_{i}': f'Set{i + 1} Magic' for i in range(5)},
                   'stats_runeword': 'Runeword Magic'}

    def stat_line(stat):
        return stat_text(data, stat['id'], stat.get('param'), stat['value'])

    def area(entry, owner):
        it = entry.it
        if isinstance(owner, tuple):
            return 'Corpse' if owner[0] == 'corpse' else 'Iron Golem'
        if it['location'] == LOC_EQUIPPED:
            return ('Mercenary ' if owner else '') + slot_name(it['equipped'], 'Equipped')
        if it['location'] == LOC_BELT:
            return f'Belt({it["x"] % 4 + 1},{it["x"] // 4 + 1})'
        panel = {PANEL_INVENTORY: 'Inv', PANEL_STASH: 'Stash', PANEL_CUBE: 'Cube'}.get(it.get('panel'))
        return f'{panel}({it["x"] + 1},{it["y"] + 1})' if panel else 'Character'

    for entry, owner in entries:
        name = clean_name(win, entry)
        details = f'{len(entry.blob)} {area(entry, owner)}: {name}'
        lines.extend(('', details))
        try:
            record, children = decode_blob(entry.blob, data)
        except ITEM_ERRORS:
            continue
        combined = []
        for index, part in enumerate((record, *children)):
            base = data.base(part['code'])
            lines.append(f'  Socket {index}: {base.name}' if index else name)
            if 'ilvl' in part:
                lines.append(f'  Item level = {part["ilvl"]}')
            damage = getattr(base, 'damage', None) or {}
            for key, label in (('one_hand', 'One-Handed Damage'), ('two_hand', 'Two-Handed Damage'),
                               ('throw', 'Throw Damage')):
                low, high = damage.get(key) or (0, 0)
                if low or high:
                    lines.append(f'  {label}: {low} to {high}')
            for key, label in (('defense', 'Defense'), ('quantity', 'Quantity')):
                if key in part:
                    lines.append(f'  {label} = {part[key]}')
            if part['flags'] & FLAG_ETHEREAL:
                lines.append('  Ethereal')
            for key, label in magic_lists.items():
                if key in part:
                    lines.append(f'    {label}')
                    lines.extend(f'      {stat_line(stat)}' for stat in part[key])
                    combined.extend(part[key])
        if owner is False:
            slot = record.get('equipped') if record.get('location') == LOC_EQUIPPED else None
            if slot in weapon_names:
                sections[weapon_names[slot]] = combined
            elif slot is not None or (record.get('location') == LOC_STORED
                                     and record.get('panel') == PANEL_INVENTORY
                                     and record['code'] in ('cm1 ', 'cm2 ', 'cm3 ')):
                sections[non_weapons].extend(combined)

    for title, rows in sections.items():
        lines.extend(('', f'SUMMARY of {title}:'))
        lines.extend(f'  {stat_line(stat)}' for stat in merge_stats(rows))
    return '\n'.join(lines) + '\n'


def validate_replacement_size(win, current, item, owner):
    from mxl_char import LOC_BELT, LOC_EQUIPPED, LOC_STORED, PANEL_INVENTORY

    if isinstance(owner, (tuple, SocketChild)):
        return
    ch = win.ch
    location = current.it.get('location')
    if location == LOC_EQUIPPED:
        error = ch.slot_error(item, current.it['equipped'], bool(owner), current)
    elif location == LOC_STORED:
        x, y, panel = (current.it[key] for key in ('x', 'y', 'panel'))
        error = (ch.inventory_error(item, x, y, current) if panel == PANEL_INVENTORY
                 else ch.stored_error(item, panel, x, y, current))
    elif location == LOC_BELT:
        error = None if ch.data.base(item['code']).size == (1, 1) else 'The item does not fit in the belt.'
    else:
        error = None
    if error:
        raise CharError(error)


def mutate(win, entry, caption, update):
    try:
        before = bytes(entry.blob)
        record, size = decode_item(before, win.data)
        update(record)
        replace_item(win, entry, before, encode_item(record, win.data) + before[size:], caption)
    except ITEM_ERRORS as error:
        win.set_status(str(error), True)


def fill_count(win, entry, clip):
    from mxl_socket_insert import blob_socketable, free_sockets

    if not clip or not blob_socketable(win.app, clip[0]) or win.ch.old:
        return 0
    try:
        return free_sockets(entry.blob, win.data)
    except ITEM_ERRORS:
        return 0


def fill(win, entry, clip):
    from mxl_socket_insert import insert_child

    try:
        original = bytes(entry.blob)
        updated = original
        count = fill_count(win, entry, clip)
        if not count:
            return
        for _ in range(count):
            updated = insert_child(updated, clip[0], win.data)
        replace_item(win, entry, original, updated, f'Filled {count} sockets.')
    except ITEM_ERRORS as error:
        win.set_status(str(error), True)


def cut_item(win, entry):
    from mxl_rc_menu import _record_char_write
    from mxl_vanilla_he import allows
    from mxl_vanilla_he_extras import put_picked_up

    if not allows(win, 'transfer'):
        return
    win.sync_file()
    mercenary = win.is_merc()
    current = win.current_entry(entry, mercenary)
    if current is None:
        win.set_status('The selected item has changed.', True)
        return
    try:
        ch = win.ch
        before = bytes(ch.raw)
        clip = ch.stash_blob(current)
        ch.remove(current, mercenary)
        if win.save('Moved item into Picked Up.', operation='transfer'):
            put_picked_up(win, clip)
            _record_char_write(win, ch.path, before, 'Cut Item')
    except ITEM_ERRORS as error:
        win.set_status(str(error), True)


def move_over(win, source, target, *, record_undo=True):
    from mxl_char import where_of
    from mxl_rc_menu import _record_char_write
    from mxl_vanilla_he import allows
    from mxl_vanilla_he_extras import put_picked_up

    if not allows(win, 'transfer'):
        return False
    if not messagebox.askyesno('Move Item', f'Replace {target.it["name"]}?', parent=win.top):
        return False
    ch = win.ch
    mercenary = win.is_merc()
    items = ch.entries(mercenary)
    previous = items[:]
    try:
        original = bytes(ch.raw)
        clip = ch.stash_blob(source)
        where = where_of(target)
        ch.remove(target, mercenary)
        ch.move(source, where, mercenary)
        if win.save('Moved item onto the selected target.', operation='transfer'):
            put_picked_up(win, clip)
            if record_undo:
                _record_char_write(win, ch.path, original, 'Move Item')
            return True
    except ITEM_ERRORS as error:
        items[:] = previous
        win.set_status(str(error), True)
    return False


def paste_one(win, entry, clip, overwrite):
    from mxl_socket_insert import insert_child

    if fill_count(win, entry, clip):
        try:
            before = bytes(entry.blob)
            after = insert_child(before, clip[0], win.data)
            replace_item(win, entry, before, after, 'Item socketed.')
        except ITEM_ERRORS as error:
            win.set_status(str(error), True)
    elif messagebox.askyesno('Paste Item', 'Overwrite the item at this location?', parent=win.top):
        overwrite()


def set_flag(record, flag, enabled):
    if enabled:
        record['flags'] |= flag
    else:
        record['flags'] &= ~flag


def add_specific(win, menu, entry):
    from mxl_rc_menu import (_ask_personalize, _ask_value, _creator_for, _quality_ok)
    from mxl_socket_menu import add_to, max_sockets, remove_sockets

    try:
        record, _ = decode_item(entry.blob, win.data)
    except ITEM_ERRORS:
        record = {}
    code = entry.it['code']
    data = win.data
    cr = _creator_for(win)
    flags = record.get('flags', 0)
    editable = bool(record) and not win.ch.old
    extended = editable and not flags & FLAG_SIMPLE
    base = data.base(code)
    kind = body_kind(data, code)
    specific = submenu(menu, 'Specific Editing Functions…', editable)

    def change(target, label, update, enabled=True):
        command(target, label, lambda: mutate(win, entry, label, update), enabled)

    def field(target, label, key, lo, hi):
        command(target, label, lambda: _ask_value(
            target, label, label, record[key], lo, hi,
            lambda value: mutate(win, entry, label, lambda rec: rec.update({key: value}))))

    command(specific, 'MAGIC Attribute Editing', lambda: edit_item(win, entry, 'Magic'), extended)
    is_set = extended and record.get('quality') == 'set'
    sets = submenu(specific, 'SET Magic Editing…', is_set)
    change(sets, 'REMOVE ALL Set Magic Attributes', lambda rec: rec.update(set_mask=0), is_set)
    for index in range(1, 6):
        caption = f'Set{index} Magic'
        command(sets, f'EDIT SET{index} Magic Attributes', lambda group=caption: edit_item(win, entry, group), is_set)
    command(specific, 'RUNEWORD Magic Editing', lambda: edit_item(win, entry, 'Runeword Magic'),
            extended and bool(flags & FLAG_RUNEWORD))

    cap = max_sockets(cr, code, record) if extended else 0
    sockets = submenu(specific, 'SOCKETING (if possible)…', bool(cap or flags & FLAG_SOCKETED))
    label = 'Make Item Socketed'
    low = max(1, record.get('socketed_count', 0))
    command(sockets, label, lambda: _ask_value(
        sockets, label, 'Number of sockets', min(cap, max(low, record.get('sockets', 0))), low, cap,
        lambda value: mutate(win, entry, label, lambda rec: add_to(rec, cr, data, code, value))),
        bool(cap >= low) and not flags & FLAG_RUNEWORD)
    command(sockets, 'Remove Sockets (and socketed items)', lambda: remove_sockets(win, win=win, e=entry),
            extended and bool(flags & FLAG_SOCKETED))

    quality = submenu(specific, "Change the Item's QUALITY…", extended)
    for name, label in (('low', 'Low'), ('normal', 'Normal'), ('superior', 'Superior'),
                        ('magic', 'Magically Enhanced'), ('set', 'Part of a Set'), ('rare', 'Rare'),
                        ('unique', 'Unique'), ('crafted', 'Crafted')):
        allowed = extended and (_quality_ok(cr, code, name) if name != 'low' else kind in ('armor', 'weapons'))
        command(quality, label, lambda q=name: edit_item(win, entry, 'Quality:' + q), allowed)

    starter = submenu(specific, 'STARTING Item…', editable)
    change(starter, 'Make item a STARTING Item', lambda rec: set_flag(rec, FLAG_STARTER, True))
    change(starter, 'Make item NOT a Starting Item', lambda rec: set_flag(rec, FLAG_STARTER, False))
    personal = submenu(specific, 'PERSONALIZE (if possible)…', extended)
    command(personal, 'Personalize Item', lambda: _ask_personalize(
        personal, lambda name: mutate(win, entry, 'Personalize Item',
                                      lambda rec: rec.update(flags=rec['flags'] | FLAG_PERSONALIZED,
                                                             personalized_name=name))))
    change(personal, 'Remove Personalize', lambda rec: set_flag(rec, FLAG_PERSONALIZED, False),
           bool(flags & FLAG_PERSONALIZED))
    ethereal = submenu(specific, 'ETHEREAL…', editable)
    change(ethereal, 'Make Item Ethereal', lambda rec: set_flag(rec, FLAG_ETHEREAL, True))
    change(ethereal, 'Make Item NOT Ethereal', lambda rec: set_flag(rec, FLAG_ETHEREAL, False))

    has_defense = extended and 'defense' in record
    defense = submenu(specific, 'DEFENSE (if available)…', has_defense)
    if has_defense:
        isc = data.isc[S.DEFENSE]
        limit = (1 << isc['bits']) - 1 - isc['add']
        change(defense, 'Set to Max Defense', lambda rec: rec.update(defense=limit))
        field(defense, 'Change Defense', 'defense', 0, limit)
    else:
        command(defense, 'Set to Max Defense', None, False)
        command(defense, 'Change Defense', None, False)

    durability = submenu(specific, 'DURABILITY (if available)…', extended and 'max_durability' in record)
    if extended and 'max_durability' in record:
        offset = data.isc[S.MAX_DURABILITY]['add']
        change(durability, 'Make Indestructible', lambda rec: rec.update(max_durability=offset))
        if 'durability' in record:
            field(durability, 'Change Durability', 'durability', 0,
                  record['max_durability'] - offset)
        else:
            command(durability, 'Change Durability', None, False)
    else:
        command(durability, 'Make Indestructible', None, False)
        command(durability, 'Change Durability', None, False)
    stackable = extended and 'quantity' in record
    quantity = submenu(specific, 'QUANTITY (e.g. arrows)…', stackable)
    if stackable:
        change(quantity, 'Set to Max Quantity', lambda rec: rec.update(quantity=base.stack_max))
        field(quantity, 'Change Quantity', 'quantity', 0, base.stack_max)
    else:
        command(quantity, 'Set to Max Quantity', None, False)
        command(quantity, 'Change Quantity', None, False)
    change(specific, 'DELETE ALL magic attributes', lambda rec: rec.update(stats=[]), extended)


def command(menu, caption, action, enabled=True):
    menu.add_command(label=caption, command=action, state='normal' if enabled else 'disabled')


def submenu(menu, caption, enabled=True):
    child = tk.Menu(menu, tearoff=False)
    menu.add_cascade(label=caption, menu=child, state='normal' if enabled else 'disabled')
    return child


ATTRIBUTE_SLOTS = 30


def append_attributes(existing, incoming, *, match_value=False):
    """Fill the reference editor's available slots, keeping existing attributes."""
    def key(stat):
        return (stat['id'], stat.get('param'), stat['value']) if match_value else stat['id']

    rows = list(existing)
    known = {key(stat) for stat in rows}
    for stat in incoming:
        if len(rows) >= ATTRIBUTE_SLOTS:
            break
        identity = key(stat)
        if identity not in known:
            known.add(identity)
            rows.append(dict(stat))
    return rows


def buffer_attributes(win, entry):
    try:
        record, _ = decode_item(entry.blob, win.data)
        groups = [record.get('stats', ()), *(record.get(f'set_stats_{i}', ()) for i in range(5)),
                  record.get('stats_runeword', ())]
        incoming = (rows[index] for index in range(max(map(len, groups)))
                    for rows in groups if index < len(rows))
        win.app._capy_he_buffer = append_attributes(getattr(win.app, '_capy_he_buffer', ()),
                                                   incoming, match_value=True)
        win.set_status(f'{len(win.app._capy_he_buffer)} magic attributes in Buffer.')
    except ITEM_ERRORS as error:
        win.set_status(str(error), True)


def paste_attributes(record, values):
    if record['flags'] & FLAG_SIMPLE:
        raise CharError('A simple item cannot store magic attributes.')
    record['stats'] = append_attributes(record.get('stats', ()), values)


def add_favorites(win, menu, entry):
    from mxl_itemlib import game_tag
    from mxl_statnames import stat_text
    import paths

    path = Path(paths.USER_DIR) / 'hero-editor-favorites.json'
    tag = game_tag()

    def load():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}

    def save(index, update):
        try:
            content = load()
            slots = content.setdefault(tag, {})
            value = update(slots.get(index, {}))
            if value is None:
                slots.pop(index, None)
            else:
                slots[index] = value
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(content, indent=2), encoding='utf-8')
            temporary.replace(path)
        except (OSError, ValueError) as error:
            win.set_status(str(error), True)

    def rename(index, default):
        name = simpledialog.askstring('Renaming Favorites', f'Name for Favorite {index}',
                                      initialvalue=default, parent=win.top)
        if name:
            save(index, lambda slot: dict(slot, name=name))

    def capture(index):
        try:
            record, _ = decode_item(entry.blob, win.data)
            stats = (*record.get('stats', ()), *record.get('stats_runeword', ()))
            save(index, lambda slot: dict(slot, stats=append_attributes(slot.get('stats', ()), stats)))
        except ITEM_ERRORS as error:
            win.set_status(str(error), True)

    favorites = submenu(menu, 'FAVORITE Item Attributes…')
    try:
        slots = load().get(tag, {})
    except (OSError, ValueError) as error:
        win.set_status(str(error), True)
        slots = {}
    free = next((str(i) for i in range(1, 10) if str(i) not in slots), None)
    command(favorites, 'ADD Favorite', lambda: save(free, lambda _: {'name': f'none{free}'}),
            free is not None)
    for index, slot in sorted(slots.items()):
        name = slot['name']
        stats = slot.get('stats')
        child = submenu(favorites, f'V1.10-V1.12 Item Attributes {index}: {name}')
        command(child, f'Change NAME of Favorite {index}', lambda i=index, n=name: rename(i, n))
        command(child, f'Add Item Magic Attributes TO Favorite {index}', lambda i=index: capture(i))
        command(child, f'Paste Item Magic Attributes FROM Favorite {index}',
                lambda values=stats: mutate(win, entry, 'Paste Favorite',
                                           lambda rec: paste_attributes(rec, values)), bool(stats))
        command(child, f'VIEW what is in Favorite {index}', lambda n=name, values=stats: messagebox.showinfo(
            n, '\n'.join(stat_text(win.data, s['id'], s.get('param'), s['value']) for s in values),
            parent=win.top), bool(stats))
        command(child, f'DELETE Favorite {index}', lambda i=index: save(i, lambda _: None))


def delete_inventory(win, target):
    from mxl_char import LOC_BELT, LOC_EQUIPPED, LOC_STORED, PANEL_CUBE, PANEL_INVENTORY
    from mxl_creator import PANEL_STASH
    from mxl_rc_menu import _clear_char_clip, _record_char_write

    from mxl_vanilla_he import allows

    if not allows(win, 'item'):
        return
    if not messagebox.askyesno('Item Deletion', f'Delete {target} items?', parent=win.top):
        return
    win.sync_file()
    ch = win.ch
    before = bytes(ch.raw)
    items = ch.items[:]
    mercenary = None if ch.merc_items is None else ch.merc_items[:]
    corpse, tail = ch.corpse, ch.tail
    opaque = getattr(ch, '_read_only_items', None)
    panels = {'Person': PANEL_INVENTORY, 'Stash': PANEL_STASH, 'Cube': PANEL_CUBE}

    def chosen(entry):
        loc = entry.it.get('location')
        return (target == 'ALL' or target == 'Person' and loc == LOC_EQUIPPED
                or target == 'Belt' and loc == LOC_BELT
                or target in panels and loc == LOC_STORED and entry.it.get('panel') == panels[target])

    try:
        if target == 'ALL':
            ch.items.clear()
            if opaque is not None:
                ch._read_only_items = ()
        else:
            for item in items:
                if chosen(item):
                    ch.remove(item)
        if target in ('ALL', 'Merc') and mercenary is not None:
            for item in mercenary:
                ch.remove(item, True)
        if target == 'ALL':
            write_special_sections(ch, [(name, start, end, []) for name, start, end, _ in special_sections(ch)])
        if not win.save(f'Deleted {target} items.'):
            raise CharError('The character could not be saved.')
    except ITEM_ERRORS as error:
        ch.items, ch.merc_items = items, mercenary
        ch.corpse, ch.tail = corpse, tail
        if opaque is not None:
            ch._read_only_items = opaque
        win.set_status(str(error), True)
        return
    if target in ('ALL', 'Person'):
        _clear_char_clip(win)
    _record_char_write(win, ch.path, before, 'Item Deletion')


def belt_item(win, blob, slot, replace=None):
    from mxl_char import Entry, LOC_BELT
    from mxl_rc_menu import _creator_for

    data = win.data
    item = blob_item(blob, data)
    if (win.ch.old or data.base(item['code']).size != (1, 1)
            or not {'poti', 'tpot'}.intersection(_creator_for(win).type_codes(item['code']))):
        raise CharError('This item cannot go in the belt.')
    positioned = Entry(item, blob).moved(data, location=LOC_BELT, equipped=0, x=slot, y=0, panel=0)
    new = Entry(blob_item(positioned, data), positioned)
    items = win.ch.items
    if replace is None:
        items.append(new)
    else:
        items[items.index(replace)] = new


def paste_belt(win, cell, clip):
    from mxl_rc_menu import _record_char_write
    from mxl_vanilla_pages import containers
    from mxl_vanilla_he import allows

    if not allows(win, 'transfer'):
        return
    win.sync_file()
    _, _, cols, rows, entries = next(row for row in containers(win.ch, win.data) if row[0] == 'belt')
    x, y = cell
    if not 0 <= x < cols or not 0 <= y < rows:
        return
    slot = x + cols * (rows - 1 - y)
    previous = next((entry for entry in entries if entry.it['x'] == slot), None)
    if previous is not None and not messagebox.askyesno('Paste Item', 'Replace the belt item?', parent=win.top):
        return
    try:
        raw = bytes(win.ch.raw)
        belt_item(win, clip[0], slot, previous)
        if win.save('Pasted item in belt.', operation='transfer'):
            _record_char_write(win, win.ch.path, raw, 'Paste into Belt')
    except ITEM_ERRORS as error:
        win.set_status(str(error), True)


def paste_all(win):
    from mxl_char import PANEL_CUBE
    from mxl_creator import PANEL_STASH
    from mxl_rc_menu import _record_char_write
    from mxl_vanilla_pages import CUBE_CODE, containers
    import mxl_profile

    clip = getattr(win.app, '_capy_clip', None)
    if not clip:
        win.set_status('Nothing in Picked Up.', True)
        return
    win.sync_file()
    ch = win.ch
    before, original = bytes(ch.raw), ch.items[:]
    key = win.inv_view.get()
    try:
        item = blob_item(clip[0], win.data)
        if key == 'person':
            grid = (mxl_profile.active() or {}).get('grids') or mxl_profile.grid_sizes(win.data.folder)
            cols, rows = grid['inv']
            for y in range(rows):
                for x in range(cols):
                    if not ch.inventory_error(item, x, y):
                        ch.place(clip[0], ('inv', x, y))
        else:
            key = 'belt' if key in ('merc', 'merc_belt') else key
            info = next((row for row in containers(ch, win.data) if row[0] == key), None)
            if info is None:
                raise CharError('Select a character container first.')
            _, _, cols, rows, entries = info
            if key == 'belt':
                used = {entry.it['x'] for entry in entries}
                for slot in range(cols * rows):
                    if slot not in used:
                        belt_item(win, clip[0], slot)
            else:
                panel = PANEL_STASH if key == 'stash' else PANEL_CUBE
                if key == 'cube' and not any(e.it['code'] == CUBE_CODE for e in ch.entries()):
                    raise CharError('The character has no Horadric Cube.')
                for y in range(rows):
                    for x in range(cols):
                        if not ch.stored_error(item, panel, x, y):
                            ch.place(clip[0], ('store', panel, x, y))
        count = len(ch.items) - len(original)
        if not count:
            win.set_status('No free space for this item.', True)
        elif win.save(f'Pasted {count} copies.', operation='transfer'):
            _record_char_write(win, ch.path, before, 'Paste All')
        else:
            ch.items = original
    except ITEM_ERRORS as error:
        ch.items = original
        win.set_status(str(error), True)
