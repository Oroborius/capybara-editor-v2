"""Vanilla Hero Editor commands and save-format regression checks."""
import os
from pathlib import Path
import shutil

import capytest as T

MODE = 'gui'
REPO = Path(T.REPO)
GAME = Path(os.environ.get('MXL_TEST_VANILLA_GAME') or REPO / '.cache/ingame/game')
SOURCE = REPO / '.cache/samples/vanilla/complex.d2s'
SAVES = Path(T.guard(os.path.join(T.tmp(), 'parity-saves')))
SAVES.mkdir(exist_ok=True)
AVAILABLE = (GAME / 'd2data.mpq').is_file() and SOURCE.is_file()
if AVAILABLE:
    shutil.copy2(SOURCE, SAVES)
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': str(GAME), 'MXL_SAVE_DIR': str(SAVES)}


def menu_labels(menu):
    return [menu.entrycget(i, 'label') for i in range(menu.index('end') + 1)
            if menu.type(i) != 'separator']


def select_menu(menu, label):
    return menu.nametowidget(menu.entrycget(label, 'menu'))


@T.test
def vanilla_item_commands_and_save_round_trip():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import tkinter as tk
    from mxl_char import Character
    from mxl_creator import decode_item
    from mxl_rc_menu import _vanilla_char_commands
    from mxl_vanilla_he_items import FLAG_STARTER

    win = T.chartab()
    entry = next(e for e in win.ch.entries() if e.it.get('quality') in ('set', 5))
    record, _ = decode_item(entry.blob, win.data)
    original = bytes(entry.blob)
    menu = tk.Menu(win.top, tearoff=False)
    _vanilla_char_commands(win, menu, entry, None)
    T.eq(menu_labels(menu)[:14], [
        'General Edit of Item (in Extras Window)', 'Specific Editing Functions…', 'FAVORITE Item Attributes…',
        'Add All Item Magic Attributes TO Buffer', 'VIEW what is in Buffer', 'DELETE Buffer',
        'Export Item to File…', 'Import Item from File…', 'Cut Item (move to Picked Up)',
        'Copy Item (copy into Picked Up)', 'Paste Item (copy of Picked Up)',
        'Fill Item Sockets (copy of Picked Up)', 'Delete Item (remove)',
        'Save Character Information to Text file',
    ], 'reference menu order')
    specific = select_menu(menu, 'Specific Editing Functions…')
    T.eq(menu_labels(specific), [
        'MAGIC Attribute Editing', 'SET Magic Editing…', 'RUNEWORD Magic Editing',
        'SOCKETING (if possible)…', "Change the Item's QUALITY…", 'STARTING Item…',
        'PERSONALIZE (if possible)…', 'ETHEREAL…', 'DEFENSE (if available)…',
        'DURABILITY (if available)…', 'QUANTITY (e.g. arrows)…', 'DELETE ALL magic attributes',
    ], 'specific menu order')
    sets = select_menu(specific, 'SET Magic Editing…')
    T.eq(menu_labels(sets), ['REMOVE ALL Set Magic Attributes',
                             *(f'EDIT SET{i} Magic Attributes' for i in range(1, 6))], 'set lists')
    for title, expected in {
        'SOCKETING (if possible)…': ['Make Item Socketed', 'Remove Sockets (and socketed items)'],
        "Change the Item's QUALITY…": ['Low', 'Normal', 'Superior', 'Magically Enhanced',
                                      'Part of a Set', 'Rare', 'Unique', 'Crafted'],
        'PERSONALIZE (if possible)…': ['Personalize Item', 'Remove Personalize'],
        'ETHEREAL…': ['Make Item Ethereal', 'Make Item NOT Ethereal'],
        'DEFENSE (if available)…': ['Set to Max Defense', 'Change Defense'],
        'DURABILITY (if available)…': ['Make Indestructible', 'Change Durability'],
        'QUANTITY (e.g. arrows)…': ['Set to Max Quantity', 'Change Quantity'],
    }.items():
        T.eq(menu_labels(select_menu(specific, title)), expected, title)

    menu.invoke('Add All Item Magic Attributes TO Buffer')
    first = tuple(win.app._capy_he_buffer)
    T.check(bool(first), 'set item attributes are captured')
    menu.invoke('Add All Item Magic Attributes TO Buffer')
    T.eq(tuple(win.app._capy_he_buffer), first, 'capture is additive and deduplicated')
    menu.invoke('DELETE Buffer')
    T.eq(win.app._capy_he_buffer, [], 'buffer can be cleared')
    menu.invoke('Copy Item (copy into Picked Up)')
    T.check(bool(win.app._capy_clip), 'copy populates Picked Up')
    starters = select_menu(specific, 'STARTING Item…')
    starters.invoke('Make item NOT a Starting Item' if record['flags'] & FLAG_STARTER
                    else 'Make item a STARTING Item')
    saved = Character(win.ch.path, win.data)
    index = next(i for i, e in enumerate(saved.entries()) if e.it['code'] == entry.it['code']
                 and e.it.get('equipped') == entry.it.get('equipped') and e.it.get('x') == entry.it.get('x')
                 and e.it.get('y') == entry.it.get('y') and e.it.get('panel') == entry.it.get('panel'))
    new, _ = decode_item(saved.entries()[index].blob, win.data)
    T.eq(new['flags'], record['flags'] ^ FLAG_STARTER, 'only the starter bit changed')
    T.eq(saved.build(), saved.raw, 'edited save round-trips')
    T.check(saved.entries()[index].blob != original, 'starter bit is persisted')
    menu.destroy()


@T.test
def vanilla_extras_tools_and_binary_order():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from mxl_vanilla_he import extras
    from mxl_vanilla_he_extras import TABS, ear_blob, read_bits, reverse_bits

    win = T.chartab()
    top = extras(win)
    nb = next(child for child in top.winfo_children() if child.winfo_class() == 'TNotebook')
    T.eq(tuple(nb.tab(tab, 'text') for tab in nb.tabs()), TABS, 'reference tab order')

    def labels(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == 'TButton':
                yield str(child.cget('text'))
            yield from labels(child)

    for caption in ('Save Header Bytes', 'Incr Both', 'Decr Both', 'Remove Bits', 'Insert Bits',
                    'Save Binary Item', 'Save Modified Item', 'Test Item for Errors',
                    'Copy Item to "Picked Up"', 'Remove socketed Item to "Picked Up"',
                    'Delete Magic Attribute - ALL ITEMS', 'Save New Item To PickedUp',
                    'V1.03', 'V1.07', 'V1.09D', 'V1.10s beta', 'V1.10/V1.11/V1.12/V1.13', 'V1.12 Clone'):
        T.check(caption in set(labels(top)), f'Extras exposes {caption}')
    create = top.nametowidget(nb.tabs()[3])
    selector = next(child for child in create.winfo_children() if child.winfo_class() == 'Treeview')
    T.check(selector.exists('base:hp1 '), 'vanilla potion is in the create tree')
    if selector.exists('base:hp1 '):
        selector.selection_set('base:hp1 ')
        selector.event_generate('<<TreeviewSelect>>')
        T.pump(3)
        options = next(child for child in create.winfo_children() if child.winfo_class() == 'TFrame')
        save = next(child for child in options.winfo_children()
                    if child.winfo_class() == 'TButton' and child.cget('text') == 'Save New Item To PickedUp')
        save.invoke()
        from mxl_char import blob_item
        T.eq(blob_item(win.app._capy_clip[0], win.data)['code'].strip(), 'hp1',
             'create stores a parseable vanilla item in Picked Up')
    T.eq(reverse_bits(b'JM'), '01001101 01001010', 'byte order matches Hero Editor binary comparison')
    for e in win.ch.entries():
        T.eq(read_bits(reverse_bits(e.blob)), e.blob, 'binary editor round-trips sample item')
    from mxl_char import blob_item
    from mxl_creator import decode_item, encode_item

    ear = ear_blob(win, 'Example', 4, 24)
    record, end = decode_item(ear, win.data)
    T.eq((record['ear_name'], record['ear_class'], record['ear_level']), ('Example', 4, 24), 'ear fields')
    T.eq((encode_item(record, win.data), end), (ear, len(ear)), 'ear record is byte-identical')
    T.eq(blob_item(ear, win.data).ear, (4, 24, 'Example'), 'the character parser reads the same ear')
    top.destroy()


@T.test
def every_inventory_entry_has_an_implementation_or_an_explicit_gap():
    import ast
    import re

    inventory = REPO / '.cache/heroed/FEATURES.md'
    if not inventory.is_file():
        T.skip('reference inventory is stored with the local Hero Editor fixtures')
    references = {}
    seen = set()
    for line in inventory.read_text(encoding='utf-8').splitlines():
        if not line.startswith('| ') or line.startswith('| Reference'):
            continue
        _, caption, state, description, _ = (field.strip() for field in line.split('|'))
        T.check(caption not in seen, f'duplicate inventory entry: {caption}')
        seen.add(caption)
        T.check(state in ('Existing', 'Added', 'MISSING'), f'{caption} has an explicit status')
        T.check(bool(description), f'{caption} has a route or a gap')
        if state == 'MISSING':
            continue
        routes = re.findall(r'(mxl_[a-z_]+\.py):([A-Za-z_][\w.]*)', description)
        T.check(bool(routes), f'{caption} has an implementation route')
        for file, symbol in routes:
            if file not in references:
                references[file] = ast.parse((REPO / 'src' / file).read_text(encoding='utf-8')).body
            body = references[file]
            for part in symbol.split('.'):
                node = next((candidate for candidate in body if getattr(candidate, 'name', None) == part), None)
                if not T.check(node is not None, f'{caption} has an existing {file}:{symbol}'):
                    break
                body = node.body
    T.check(len(seen) >= 150, 'inventory includes the full set of audited controls')


@T.test
def vanilla_special_records_keep_their_sections_and_undo():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from mxl_creator import Creator, decode_item, encode_item
    from mxl_undo import undo
    from mxl_vanilla_he_items import FLAG_STARTER, extras_entries, replace_item

    win = T.chartab()
    creator = Creator(win.data)
    potion, _ = creator.build(creator.new_spec('normal', 'hp1 '))
    win.ch.corpse = b'JM\x01\x00' + bytes(12) + b'JM\x01\x00' + potion
    win.ch.tail = b'kf\x01' + potion
    T.check(win.save('Special item fixtures'), 'special item sections saved')
    before = bytes(win.ch.raw)
    for section in ('corpse', 'tail'):
        entry, owner = next((entry, owner) for entry, owner in extras_entries(win.ch)
                            if isinstance(owner, tuple) and owner[0] == section)
        offsets = {}
        record, _ = decode_item(entry.blob, win.data, offsets=offsets)
        T.eq(offsets['flags'], 16, 'the flags follow the JM signature')
        edited = encode_item(dict(record, flags=record['flags'] ^ FLAG_STARTER), win.data)
        replace_item(win, entry, potion, edited, 'Edited special item', owner)
        entries = {owner[0]: entry.blob for entry, owner in extras_entries(win.ch) if isinstance(owner, tuple)}
        T.eq(entries[section], edited, f'{section} item was replaced in place')
        T.eq(entries['tail' if section == 'corpse' else 'corpse'], potion, 'the other section is unchanged')
        undo(win.app)
        T.pump(4)
        win.sync_file()
        T.eq(bytes(win.ch.raw), before, 'the item edit can be undone byte for byte')


@T.test
def vanilla_beta_character_round_trip():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from mxl_char import Character, blob_item
    from mxl_creator import (
        Creator, FLAG_ALWAYS, FLAG_IDENTIFIED, FLAG_SIMPLE, FLAG_SOCKETED, LOC_SOCKETED, decode_blob, decode_item,
        encode_item,
    )
    from mxl_format import FormatError
    from mxl_newchar import build, write
    from mxl_save import load_character
    from unittest.mock import patch
    from mxl_vanilla_he_extras import ItemEdit, open_extras
    from mxl_vanilla_he_items import SocketChild, character_report, extras_entries

    win = T.chartab()
    data = win.data
    raw, _ = build(data, 'BetaExample', 0, 1, version=95)
    path = write(raw, SAVES, 'BetaExample')
    ch = Character(path, data)
    T.eq((ch.version, ch.cls, ch.level, len(ch.items)), (95, 0, 1, 0), 'beta Amazon template')
    T.eq(ch.build(), raw, 'empty beta file reads back byte for byte')
    creator = Creator(ch.data)
    blob, _ = creator.build(creator.new_spec('normal', 'hax '))
    record, _ = decode_item(blob, ch.data)
    stamp = 0x123456789ABCDEF123456789
    record.update(realm_bit=1, realm_stamp=stamp, durability=175)
    record.update(flags=record['flags'] | FLAG_SOCKETED, sockets=1, socketed_count=1)
    filler = encode_item(dict(code='r01 ', flags=FLAG_ALWAYS | FLAG_IDENTIFIED | FLAG_SIMPLE,
                              location=LOC_SOCKETED), ch.data)
    inventory_blob = encode_item(record, ch.data) + filler
    entry = ch.place(inventory_blob, ('inv', 0, 0))
    try:
        blob_item(ch.stash_blob(entry), data)
    except FormatError:
        pass
    else:
        T.check(False, 'beta clipboard bytes must be rejected by the standard stash reader')
    ch.set_stat(14, 7)
    ch.save(backup=False)
    T.eq(load_character(path, data)['items'][0]['durability'], 175, 'collector opens a populated beta save')

    old_path = win.ch.path
    extras = None
    try:
        win.ch.path = path
        win.reload(keep=False)
        T.eq(win.ch.build(), Path(path).read_bytes(), 'populated beta file reads back byte for byte')
        entry = win.ch.items[0]
        win.ch.move(entry, ('inv', 2, 0))
        T.check(win.save('Moved beta item'), 'inventory move saves in the beta layout')
        editors = []

        def capture_editor(*args):
            editors.append(ItemEdit(*args))

        with patch('mxl_vanilla_he_extras.ItemEdit', side_effect=capture_editor):
            extras = open_extras(win, win.ch.items[0], 'Other:durability')
        edit, = editors
        edit.stage_field('durability', 180)
        edit.save()
        saved = Character(path, data)
        parsed, children = decode_blob(saved.items[0].blob, saved.data, exact=True)
        T.eq((saved.stat(14), parsed['x'], parsed['durability'], parsed['realm_stamp']),
             (7, 2, 180, stamp), 'Extras preserves beta fields and item framing')
        T.eq([child['code'] for child in children], ['r01 '], 'Extras preserves native socket fillers')
        T.check(any(isinstance(owner, SocketChild) for _, owner in extras_entries(saved, include_socketed=True)),
                'Extras lists the individual beta socket filler')
        T.check('Durability = 180/' in character_report(win), 'report uses the beta item layout')
    finally:
        if extras:
            extras.destroy()
        win.ch.path = old_path
        win.reload(keep=False)


@T.test
def vanilla_options_apply_access_and_display_prefs():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import settings
    from mxl_vanilla_he import allows, description_item, picture_item

    win = T.chartab()
    saved = {key: settings.get('vanilla_he_' + key) for key in
             ('item_access', 'character_access', 'set_attributes', 'unique_pictures')}
    try:
        settings.put('vanilla_he_item_access', 'transfer')
        settings.put('vanilla_he_character_access', 'stats')
        T.check(allows(win, 'transfer') and not allows(win, 'item'), 'transfer-only item access')
        T.check(allows(win, 'character') and not allows(win, 'header'), 'stats-only character access')
        settings.put('vanilla_he_character_access', 'view')
        previous = win.ch.raw
        win.save_progress()
        T.eq(win.ch.raw, previous, 'view-only mode preserves the file')
        item = {'quality': 'unique', 'set_unique_id': 4, 'set_stats_0': [{'id': 0}]}
        settings.put('vanilla_he_unique_pictures', 'hide')
        settings.put('vanilla_he_set_attributes', 'hide')
        T.check('set_unique_id' not in picture_item(item), 'base picture preference')
        T.check('set_stats_0' not in description_item(item), 'set attributes can be hidden')
        T.check('set_unique_id' in item and 'set_stats_0' in item, 'display options preserve the item')
    finally:
        for key, value in saved.items():
            settings.put('vanilla_he_' + key, value)


@T.test
def vanilla_reference_clone_and_legacy_corpse():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import struct
    from mxl_char import Character, checksum
    from mxl_newchar import build, create_reference_clone
    from mxl_save import load_character
    from mxl_vanilla_he_items import special_sections, write_special_sections

    win = T.chartab()
    clone = Path(create_reference_clone(win.app))
    try:
        character = Character(clone, win.data)
        raw = clone.read_bytes()
        T.eq((len(raw), checksum(raw)), (8075, 0x87B4672B), 'example payload with a neutral name')
        T.eq((character.name, character.level, len(character.items)), ('HeroExample', 99, 50), 'clone details')
        T.eq(character.build(), raw, 'opaque clone items survive a round trip')
        T.eq(load_character(str(clone), win.data)['name'], character.name, 'the collector can open the example')
    finally:
        clone.unlink()

    raw, old = build(win.data, 'LegacyCorpse', 0, 1, version=92)
    item = old.items[0]
    old.corpse = b'JM' + struct.pack('<H', 1) + bytes(12) + b'JM' + struct.pack('<H', 1) + old._old_blob(item)
    old.parse(old.build())
    name, start, end, entries = special_sections(old)[0]
    T.eq((name, len(entries), entries[0].it['code']), ('corpse', 1, item.it['code']), 'legacy corpse decodes')
    write_special_sections(old, [(name, start, end, [])])
    old.parse(old.build())
    T.eq(special_sections(old)[0][3], [], 'legacy corpse can be cleared with its metadata intact')


@T.test
def vanilla_extended_pickers_and_socket_child_replacement():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from mxl_creator import Creator, decode_item, encode_item
    from mxl_vanilla_he import QUEST_NOTES, next_decode_version
    from mxl_vanilla_he_extras import (
        BASIC_FLAGS, attribute_groups, create_item_blob, header_catalog, move_attribute, pack_time_values,
        skill_tab_choices, time_values,
    )
    from mxl_vanilla_he_items import SocketChild, character_report, extras_entries, replace_item, report_summary

    win = T.chartab()
    versions = [96]
    for _ in range(5):
        versions.append(next_decode_version(versions[-1]))
    T.eq(versions, [96, 71, 87, 92, 95, 96], 'reference decode cycle')
    T.eq(time_values(pack_time_values(3, -7, 8)), (3, -7, 8), 'time and signed min/max values')
    grouped = [{'id': sid} for sid in (54, 55, 56, 31)]
    T.eq(list(attribute_groups(grouped)), [(0, 3), (3, 4)], 'picker uses one row for grouped cold damage')
    T.eq(move_attribute(grouped, 1, 1), 2, 'moving a component moves its group')
    T.eq([row['id'] for row in grouped], [31, 54, 55, 56], 'cold components stay together')
    T.eq(BASIC_FLAGS['identified'], (4, 1), 'identified bit')
    fields = header_catalog(win.ch)
    T.check((56, 64, 'Skill IDs for hotkeys') in fields, 'reference header field length')
    T.check(any(start == win.ch.offsets[2] and length == 4 for start, length, _ in fields),
            'hex catalog includes the detected item list offset')
    T.eq(QUEST_NOTES[4][1][0], 10, 'cow level note bit')
    T.eq(len(skill_tab_choices(win.data)), 21, 'vanilla skill tabs have named class and tree fields')
    made, _ = decode_item(create_item_blob(Creator(win.data), 'hax '), win.data)
    T.eq((made['quality'], made['subquality'], made['ilvl']), ('superior', 1, 90), 'creation defaults')
    report = character_report(win)
    T.check(all(section in report for section in ('Character Stats:', 'Skills:', 'Normal Magic', 'SUMMARY of')),
            'report includes individual and combined attributes')
    charges = list(report_summary(win.data, [
        dict(id=204, param=(36 << 6) | 1, value=(160 << 8) | 150),
        dict(id=204, param=(36 << 6) | 1, value=(160 << 8) | 150),
    ]))
    T.eq(len(charges), 1, 'report combines charges for the same skill and level')
    T.check('300/320 charges' in charges[0], 'current charges cannot carry into maximum charges')
    child, owner = next((entry, owner) for entry, owner in extras_entries(win.ch, include_socketed=True)
                        if isinstance(owner, SocketChild))
    original = bytes(win.ch.raw)
    record, _ = decode_item(child.blob, win.data)
    updated = encode_item(dict(record, flags=record['flags'] ^ (1 << 17)), win.data)
    try:
        replace_item(win, child, child.blob, updated, 'Edited socket child', owner)
        T.check(any(entry.blob == updated for entry, owner in extras_entries(win.ch, include_socketed=True)
                    if isinstance(owner, SocketChild)), 'socket edit survives reloading')
    finally:
        Path(win.ch.path).write_bytes(original)
        win.reload()


@T.test
def vanilla_item_editor_clears_stale_selection_on_opaque_record():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import tkinter as tk
    from unittest.mock import patch
    from mxl_vanilla_he_extras import ItemEdit
    from mxl_vanilla_he_items import extras_entries

    win = T.chartab()
    page = tk.Frame(win.top)
    entries = extras_entries(win.ch)
    editor = ItemEdit(page, win, entries, None, 'Basic1', tk.StringVar(page))
    T.check(bool(editor.record), 'first item has editable properties')
    editor.items.selection_clear(0, 'end')
    editor.items.selection_set(1)
    try:
        with patch('mxl_vanilla_he_extras.decode_blob', side_effect=ValueError('Opaque legacy record')):
            editor.load()
        T.eq(editor.selection, 1, 'selection follows the opaque item')
        T.eq(editor.record, {}, 'the previous item is no longer editable through this selection')
        T.eq(editor.decode_error, 'Opaque legacy record', 'the editor displays the decode reason')
        with patch('mxl_vanilla_he_extras.put_picked_up') as pickup:
            editor.copy()
            T.check(not pickup.called, 'the previous item cannot be copied through this selection')
    finally:
        page.destroy()


@T.test
def vanilla_hex_nibbles_stage_before_saving():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import tkinter as tk
    from mxl_vanilla_he import extras

    win = T.chartab()
    top = extras(win)
    nb = next(child for child in top.winfo_children() if child.winfo_class() == 'TNotebook')
    tab = top.nametowidget(nb.tabs()[0])
    nb.select(tab)
    T.pump(3)
    entry = next(child for child in tab.winfo_children() if child.winfo_class() == 'TEntry')
    shell = next(child for child in tab.winfo_children() if child.winfo_class() == 'TFrame')
    fields = next(child for child in shell.winfo_children() if isinstance(child, tk.Listbox))
    index = fields.get(0, 'end').index('1 Char Initial Displayed Level')
    fields.selection_set(index)
    fields.event_generate('<<ListboxSelect>>')
    T.pump(2)
    initial = win.ch.head[43]
    digit = '5' if initial >> 4 != 5 else '6'
    entry.focus_force()
    entry.icursor(0)
    entry.event_generate('<KeyPress>', keysym=digit)
    T.pump(2)
    T.eq(win.he_header_bytes.get(43), int(digit, 16) << 4 | initial & 15, 'one nibble stages immediately')
    T.eq(win.ch.head[43], initial, 'the live save still has the original header')
    top.destroy()
    win.discard()
    T.eq(win.he_header_bytes, {}, 'Reload abandons staged header bytes')


@T.test
def vanilla_mouse_belt_and_weapon_supplement():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from mxl_char import LOC_BELT, blob_item
    from mxl_creator import Creator
    from mxl_vanilla_he import weapon_bonus_ranges
    from mxl_vanilla_he_extras import create_item_blob
    from mxl_vanilla_he_items import belt_item

    win = T.chartab()
    creator = Creator(win.data)
    potion = create_item_blob(creator, 'hp1 ')
    initial = win.ch.items[:]
    try:
        belt_item(win, potion, 3)
        placed = win.ch.items[-1].it
        T.eq((placed['code'], placed['location'], placed['x']), ('hp1 ', LOC_BELT, 3), 'belt paste uses the clicked slot')
    finally:
        win.ch.items[:] = initial
    axe = blob_item(create_item_blob(creator, 'hax '), win.data)
    axe['equipped'] = 4
    without = weapon_bonus_ranges(axe, win.data, 1, 0, 0)[0]
    with_bonus = weapon_bonus_ranges(axe, win.data, 1, 0, 0, extra=5)[0]
    T.eq(without[1], with_bonus[1], 'supplement does not change the stored item bonus')
    T.eq(tuple(b - a for a, b in zip(without[2], with_bonus[2])), (5, 5), 'manual damage adds to each endpoint')


@T.test
def vanilla_binary_bits_stage_on_character_save():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from mxl_creator import decode_item, encode_item
    from mxl_vanilla_he_extras import reverse_bits, stage_binary

    win = T.chartab()
    entry = win.ch.items[0]
    record, size = decode_item(entry.blob, win.data)
    record['flags'] ^= 1 << 17
    blob = encode_item(record, win.data) + entry.blob[size:]
    original = bytes(win.ch.raw)
    try:
        stage_binary(win, entry, False, reverse_bits(blob).replace(' ', ''))
        T.check(win.dirty() and win.he_binary_edits, 'bit editing stages a character change')
        T.eq(Path(win.ch.path).read_bytes(), original, 'the staged bits wait for Save')
        win.save_progress()
        T.check(any(item.blob == blob for item in win.ch.items), 'character Save commits the staged bits')
        T.eq(win.he_binary_edits, {}, 'successful Save clears the binary changes')
    finally:
        Path(win.ch.path).write_bytes(original)
        win.reload(keep=False)


@T.test
def vanilla_beta_item_preview_honors_durability_and_timestamp():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from types import SimpleNamespace
    from mxl_creator import BetaItemData, Creator, decode_item, encode_item
    from mxl_vanilla_he import decoded_item

    win = T.chartab()
    data = win.data
    creator = Creator(data)
    raw, _ = creator.build(creator.new_spec('normal', 'hax '))
    record, _ = decode_item(raw, data)
    record.update(realm_bit=1, realm_stamp=0x123456789ABCDEF123456789)
    beta = BetaItemData(data)
    beta_raw = encode_item(record, beta)
    native_offsets, beta_offsets = {}, {}
    parsed, size = decode_item(beta_raw, beta, offsets=beta_offsets)
    decode_item(raw, data, offsets=native_offsets)
    T.eq(size, len(beta_raw), 'beta item consumes the complete record')
    T.eq(parsed['realm_stamp'], record['realm_stamp'], 'beta timestamp is preserved')
    T.eq(beta_offsets['stats'] - native_offsets['stats'], 95, 'timestamp and durability change the stat offset')
    preview = decoded_item(SimpleNamespace(ch=SimpleNamespace(version=96, old=False),
                                           data=data, he_decode_version=95, set_status=win.set_status),
                           SimpleNamespace(blob=beta_raw))
    T.check(preview is not None and preview['code'] == record['code'], 'beta preview shows the item')


@T.test
def vanilla_cancelled_drag_uses_pickup_and_belt_accepts_potions():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from types import SimpleNamespace
    from mxl_char import LOC_BELT, blob_item
    from mxl_creator import Creator
    from mxl_vanilla_he import set_tab
    from mxl_vanilla_he_extras import create_item_blob

    win = T.chartab()
    potion = create_item_blob(Creator(win.data), 'hp1 ')
    before = bytes(win.ch.raw)
    previous_clip = getattr(win.app, '_capy_clip', None)
    try:
        source = next(iter(win.ch.inventory()))
        spot = (source.it['x'], source.it['y'])
        win.ch.remove(source)
        win.ch.items[:] = [entry for entry in win.ch.items if entry.it['location'] != LOC_BELT]
        win.ch.place(potion, ('inv', *spot))
        T.check(win.save('Added potion for drag check'), 'drag fixture saved')
        set_tab(win, 'containers')
        T.pump(4)
        page = win.extra['containers']
        cols = int(page.canvases['belt'].cget('width')) // page.cell
        rows = int(page.canvases['belt'].cget('height')) // page.cell
        cells = [(x, y) for y in range(rows) for x in range(cols)]
        target = next(cell for cell in cells if page.entry_at('belt', *(c * page.cell + 1 for c in cell)) is None)

        def event(key, cell):
            return T.ev(page.canvases[key], *(c * page.cell + 1 for c in cell))

        page.on_press('inv', event('inv', spot))
        page.on_drag(None)
        page.on_release(event('belt', target))
        potion_on_belt = page.entry_at('belt', *(c * page.cell + 1 for c in target))
        T.check(potion_on_belt is not None and potion_on_belt.it['location'] == LOC_BELT,
                'dragging a potion to the belt writes it in the target slot')
        page.on_press('belt', event('belt', target))
        page.on_drag(None)
        page.on_release(SimpleNamespace(x_root=-10, y_root=-10))
        T.check(page.entry_at('belt', *(c * page.cell + 1 for c in target)) is None,
                'cancelled belt drag frees its original slot')
        T.eq(blob_item(win.app._capy_clip[0], win.data)['code'], 'hp1 ', 'cancelled drag puts the potion in Picked Up')
    finally:
        Path(win.ch.path).write_bytes(before)
        win.app._capy_clip = previous_clip
        win.reload(keep=False)


@T.test
def vanilla_open_obeys_version_and_decode_policies():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import struct
    from unittest.mock import patch
    import settings
    from mxl_vanilla_he import check_open_version, report_open_issues

    win = T.chartab()
    original = win.ch.raw
    unsupported = SAVES / 'unknown-version.bin'
    unsupported.write_bytes(original[:4] + struct.pack('<I', 98))
    keys = ('vanilla_he_version_warning', 'vanilla_he_decode_check', 'vanilla_he_error_response',
            'vanilla_he_header_checks')
    saved = {key: settings.get(key) for key in keys}
    try:
        with patch('tkinter.messagebox.showwarning') as warning:
            settings.put(keys[0], 'hide')
            T.check(not check_open_version(win, unsupported), 'unsupported save is refused quietly')
            T.check(not warning.called, 'version warning is suppressed')
            settings.put(keys[0], 'show')
            T.check(not check_open_version(win, unsupported) and warning.called, 'version warning is shown')
        with patch('mxl_creator.decode_blob', side_effect=ValueError('bad item')) as decode:
            settings.put(keys[1], 'basic')
            report_open_issues(win)
            T.check(not decode.called, 'basic Open skips item-codec validation')
            settings.put(keys[1], 'complete')
            settings.put(keys[2], 'status')
            report_open_issues(win)
            T.check(decode.called, 'complete Open checks item bytes')
        settings.put(keys[1], 'basic')
        settings.put(keys[2], 'normal')
        corrupt = bytearray(original)
        struct.pack_into('<I', corrupt, 8, len(original) + 1)
        win.ch.raw = bytes(corrupt)
        with patch('tkinter.messagebox.showwarning') as warning:
            settings.put(keys[3], 'verify')
            report_open_issues(win)
            T.check(warning.called, 'header warning reports bad size or checksum')
            warning.reset_mock()
            settings.put(keys[3], 'ignore')
            report_open_issues(win)
            T.check(not warning.called, 'header warning can be suppressed independently')
    finally:
        win.ch.raw = original
        unsupported.unlink()
        for key, value in saved.items():
            settings.put(key, value)


@T.test
def vanilla_extras_quality_picker_and_quest_note_write():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import tkinter as tk
    from mxl_creator import FLAG_PERSONALIZED
    from mxl_vanilla_he_extras import ItemEdit
    from mxl_vanilla_he_items import extras_entries

    win = T.chartab()
    entries = extras_entries(win.ch)
    entry = next(e for e, owner in entries if owner is False and e.it.get('quality') == 'set')
    top = tk.Toplevel(win.top)
    editor = ItemEdit(top, win, entries, entry, 'Quality:magic', tk.StringVar(top))
    try:
        T.eq(editor.record['quality'], 'magic', 'conversion is staged')
        T.eq(editor.tree.selection(), ('Quality:prefix',), 'magic conversion selects the prefix control')
        editor.stage_structural_flag('personalized', True)
        T.check(editor.record['flags'] & FLAG_PERSONALIZED, 'Personalized control sets the flag')
        T.eq(editor.record['personalized_name'], win.ch.name, 'personalization starts with the character name')
    finally:
        top.destroy()

    original = bytes(win.ch.raw)
    word = win.ch.quest_word(0, 1)
    try:
        win.he_quest_notes[0, 1, 4] = not bool(word & 16)
        win.save_progress()
        T.eq(win.ch.quest_word(0, 1), word ^ 16, 'saving a note changes only its bit')
    finally:
        Path(win.ch.path).write_bytes(original)
        win.reload(keep=False)



@T.test
def any_socketable_base_can_become_a_runeword_by_name():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import mxl_legit
    import mxl_rc_menu as RC
    from mxl_creator import FLAG_ETHEREAL, FLAG_RUNEWORD, decode_blob

    win = T.chartab()
    cr = RC._creator_for(win)
    code = 'crs '
    if code not in win.data.bases:
        T.skip('no Crystal Sword in these tables')
    rows = dict((name, row) for row, name in RC._runeword_rows(cr, code))
    T.check('Spirit' in rows, f'Spirit offered for a Crystal Sword: {sorted(rows)[:8]}')
    T.check(not RC._runeword_rows(cr, 'rin '), 'a ring carries no runeword')
    T.check('Insight' not in rows, 'Insight is for polearms and staves, not swords')
    for name in ('Spirit',):
        T.check(name in rows, f'{name} offered')
        rec = {'flags': FLAG_ETHEREAL, 'ilvl': 40}
        blob = RC._runeword_blob(cr, rec, code, rows[name])
        made = decode_blob(blob, win.data)[0]
        T.check(made['flags'] & FLAG_RUNEWORD, f'{name}: runeword flag')
        T.eq(made['code'], code, f'{name}: same base')
        T.check(cr.data.key(cr.data.runewords[rows[name]][0]) == name, f'{name}: name')
        T.eq(made['runeword_id'], cr.rw_string_id(rows[name]), f'{name}: runeword id')
        T.eq(mxl_legit.impossible(mxl_legit.check_item(blob)), [], f'{name}: legit')


@T.test
def any_base_can_become_any_set_item_by_name():
    """Tester: an elite Breast Plate could not be made a set item (the picker was stuck on a number). Like Hero
    Editor 1.04 the picker lists every set item by name, whatever the base."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import tkinter as tk
    from mxl_rc_menu import _creator_for
    from mxl_vanilla_he_extras import ItemEdit
    from mxl_vanilla_he_items import extras_entries

    win = T.chartab()
    cr = _creator_for(win)
    set_codes = {row['code'] for _k, _l, row in cr.set_items()}
    entries = extras_entries(win.ch)
    entry = next((e for e, owner in entries if owner is False and e.it.get('defense') is not None
                  and e.it.get('code') not in set_codes), None)
    if entry is None:
        T.skip('no armor piece whose base no set item uses')
    top = tk.Toplevel(win.top)
    editor = ItemEdit(top, win, entries, entry, 'Quality:set', tk.StringVar(top))
    try:
        T.eq(editor.record['quality'], 'set', 'a base without a set item still becomes a set item')
        labels = [label for _key, label in editor.field_choices('set_unique_id')]
        T.eq(len(labels), len(cr.set_items()), 'every set item is offered')
        T.check(any("Sigon's Shelter" in label for label in labels), f'listed by name: {labels[:3]}')
    finally:
        top.destroy()


@T.test
def changing_the_base_keeps_quality_and_sockets():
    """Tester: Choose Base Type refused socketed items and turned a Sigon's set piece into a plain item. Like Hero
    Editor 1.04 only the code changes: quality, set row, sockets and their items stay."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import tkinter as tk
    from unittest.mock import patch
    from mxl_vanilla_he_extras import ItemEdit
    from mxl_vanilla_he_items import extras_entries

    win = T.chartab()
    entries = extras_entries(win.ch)
    armor = [e for e, owner in entries if owner is False and e.it.get('defense') is not None]
    entry = next((e for e in armor if e.it.get('socketed_count')), armor[0] if armor else None)   # socketed first
    if entry is None:
        T.skip('no armor piece')
    top = tk.Toplevel(win.top)
    editor = ItemEdit(top, win, entries, entry, 'Quality:set', tk.StringVar(top))
    try:
        before, kids = dict(editor.record), len(editor.children)
        target = 'uea' if before['code'].strip() != 'uea' else 'xea'
        with patch('mxl_rc_menu._ask_pick', lambda _p, _t, _opts, on_pick: on_pick(target.ljust(4))):
            editor.select_base()
        rec = editor.record
        T.eq(rec['code'].strip(), target, 'the base changed')
        for field in ('quality', 'set_unique_id', 'stats', 'sockets', 'ilvl', 'id'):
            T.eq(rec.get(field), before.get(field), f'{field} kept')
        T.eq(len(editor.children), kids, f'socketed items kept ({kids})')
    finally:
        top.destroy()


@T.test
def delete_gear_and_inventory_separately():
    """Item Deletion: "Gear" removes only the equipped items, "Inventory" only the inventory grid."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from unittest.mock import patch
    from mxl_char import LOC_EQUIPPED, LOC_STORED, PANEL_INVENTORY
    from mxl_vanilla_he_items import delete_inventory

    win = T.chartab()
    original = bytes(win.ch.raw)

    def where(ch):
        gear = sum(1 for e in ch.items if e.it.get('location') == LOC_EQUIPPED)
        inv = sum(1 for e in ch.items if e.it.get('location') == LOC_STORED and e.it.get('panel') == PANEL_INVENTORY)
        return gear, inv, len(ch.items)

    try:
        gear, inv, total = where(win.ch)
        if not gear or not inv:
            T.skip('the sample needs gear and inventory items')
        with patch('mxl_vanilla_he_items.messagebox.askyesno', return_value=True):
            delete_inventory(win, 'Gear')
            T.eq(where(win.ch), (0, inv, total - gear), 'Gear: only the equipped items are gone')
            delete_inventory(win, 'Inventory')
            T.eq(where(win.ch), (0, 0, total - gear - inv), 'Inventory: only the inventory grid is emptied')
    finally:
        Path(win.ch.path).write_bytes(original)
        win.reload(keep=False)


@T.test
def unique_picture_larger_than_its_base_is_drawn_whole():
    """Tester: a Gnasher (1x3 picture) made on a 1x1 item shows its whole picture in game; the editor drew none."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import copy
    import mxl_gfx
    import paths
    from mxl_rc_menu import _creator_for

    win = T.chartab()
    gnasher = next((key for key, label, _row in _creator_for(win).uniques() if 'Gnasher' in label), None)
    small = next((e for e in win.ch.items if win.data.base(e.it['code']).size == (1, 1)), None)
    if gnasher is None or small is None:
        T.skip('no Gnasher row or no 1x1 item in the sample')
    it = copy.copy(small.it)
    it['quality'] = 'unique'
    it['set_unique_id'] = gnasher
    layers = mxl_gfx.icon_layers(it, win.data, (0, 0, 0), paths.ICONS_DIR)
    T.check(layers is not None and layers[1] is not None, 'a picture is drawn')
    T.check(layers[1].height >= 3 * mxl_gfx.ICON_CELL, f'the whole 1x3 picture: {layers[1].size}')
    T.eq(win.data.base(it['code']).size, (1, 1), 'the item itself stays 1x1')


@T.test
def item_creator_offers_only_the_sockets_the_game_generates():
    """Tester: a new Andariel's Visage came with 7 sockets. The creator offers what the game generates (none on a
    unique; the base's own on a normal item); 7 stays a hand edit (Specific item edit > Socketing)."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from mxl_rc_menu import _creator_for

    win = T.chartab()
    cr = _creator_for(win)
    row = next((key for key, label, _r in cr.uniques() if "Andariel" in label), None)
    if row is None:
        T.skip("no Andariel's Visage row")
    spec = cr.new_spec('unique', row=row)
    spec['ilvl'] = 99
    T.eq(cr.creator_socket_limit(spec), 1, "a unique: up to Larzuk's 1 socket")
    T.eq(spec.get('sockets') or 0, 0, 'a new unique starts with none')
    normal = cr.new_spec('normal', code=spec['code'])
    normal['ilvl'] = 99
    T.eq(cr.creator_socket_limit(normal), cr.max_sockets(spec['code'], 99), "a normal helm: the base's own")
    T.check(cr.creator_socket_limit(normal) < 7, 'not the 7 of a hand edit')
    T.eq(cr.socket_limit(spec['code'], 99), 7, 'Specific item edit > Socketing still allows 7')


@T.test
def tab_buttons_right_of_the_menu_open_their_tabs():
    """Testers could not find the Stash / Creator tabs in the Hero Editor layout: they are buttons next to Menu."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import os
    import mxl_tabs
    win = T.chartab()
    T.pump(3)
    buttons = win.he_tab_buttons
    T.check({mxl_tabs.tab_label(n) for n in ('Stash', 'Creator', 'Library', 'Bit editor')} <= set(buttons),
            f'buttons: {sorted(buttons)}')
    shot = os.environ.get('HE_TABS_SHOT')
    if shot:
        win.top.update_idletasks()
        os.system(f'import -window root {shot}')
    for name in ('Creator', 'Stash'):
        buttons[mxl_tabs.tab_label(name)].invoke()
        T.pump(3)
        page = win.he_embed.pages[name]
        T.eq(win.he_embed.current, page, f'{name} button shows its page inside the Hero Editor')
        T.eq(win.top.master.select(), str(win.top), f'{name} does not leave the Character tab')


def _descends_from(widget, top):
    """True when the widget is a child of top, or is packed into one (pack in_)."""
    while widget is not None:
        if widget == top:
            return True
        try:
            inside = widget.pack_info().get('in')
        except Exception:
            inside = None
        widget = inside if inside is not None else widget.master
    return False


@T.test
def tab_buttons_embed_each_page_in_the_hero_editor_window():
    """Stash / Creator / Library / Bit editor open as pages inside the Hero Editor window: no new toplevel, the
    page is a descendant of the window, and the character view comes back from its own tabs."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import mxl_tabs
    import tkinter as tk
    win = T.chartab()
    T.pump(3)
    top, root = win.top, win.top.winfo_toplevel()

    def toplevels():
        found, stack = [], [root]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if w.winfo_class() == 'Toplevel':
                found.append(w)
        return found

    win.he_embed.leave()
    before = toplevels()
    shots = os.environ.get('HE_TABS_SHOTS')
    for name in ('Stash', 'Creator', 'Library', 'Bit editor'):
        button = win.he_tab_buttons[mxl_tabs.tab_label(name)]
        button.invoke()
        T.pump(5)
        page = win.he_embed.pages[name]
        T.eq(win.he_embed.current, page, f'{name}: its page is showing')
        T.check(page.winfo_parent().startswith(str(top)), f'{name}: the page is a child widget of the Hero Editor')
        T.check(_descends_from(page, top), f'{name}: the page is inside the Hero Editor window')
        T.eq(win.he_embed.page_var.get(), name, f'{name}: its button shows as selected')
        T.eq(top.master.select(), str(top), f'{name}: the notebook still shows the Hero Editor')
        T.eq(toplevels(), before, f'{name}: no new toplevel')
        T.check(not win.scroll.winfo_ismapped(), f'{name}: the character view is hidden')
        owner = mxl_tabs.built_owner(name)
        if name in ('Creator', 'Library'):
            T.check(owner is not None, f'{name}: its window is built')
            T.check(_descends_from(getattr(owner, 'top', page), top), f'{name}: the built window is inside')
        if shots:
            top.update_idletasks()
            os.system(f'import -window root "{shots}/hetabs-{name.replace(" ", "")}.png"')
        button.invoke()                                # the active button again goes back
        T.pump(3)
        T.eq(win.he_embed.current, None, f'{name}: clicking the active button closes the page')
        T.check(win.scroll.winfo_ismapped(), f'{name}: the character view is back')
        button.invoke()
        T.pump(3)
        win.tab_buttons[0].invoke()                    # the character view's own tab
        T.pump(3)
        T.eq(win.he_embed.current, None, f'{name}: the character view\'s own tab brings it back')
        T.check(win.scroll.winfo_ismapped(), f'{name}: the character view is shown again')
        T.eq(win.he_embed.page_var.get(), '', f'{name}: no tab button is selected')
    T.eq(toplevels(), before, 'no toplevel was created')


@T.test
def delete_key_keeps_working_after_the_focus_was_in_a_field():
    """Tester: Del deleted one inventory item, then never another, whatever was clicked: a text field kept the
    focus (Del is ignored there) and clicking items did not take it. A click on the items takes the focus."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from pathlib import Path
    import tkinter as tk
    win = T.chartab()
    T.pump(3)
    original = bytes(win.ch.raw)
    cv = win.inv
    import mxl_vanilla_he as V
    V.set_tab(win, 'inventory')
    win.top.update()
    T.pump(5)
    try:
        items = [e for e in win.ch.inventory()]
        if len(items) < 2:
            T.skip('the sample needs two inventory items')
        entries = []
        stack = [win.top]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if w.winfo_class() in ('Entry', 'TEntry') and w.winfo_ismapped():
                entries.append(w)
        c = win.cell
        for e in items[:2]:
            if entries:
                entries[0].focus_force()                       # the focus sits in a field, as after an edit
                T.pump(2)
            x, y = int((e.it['x'] + 0.5) * c), int((e.it['y'] + 0.5) * c)
            cv.event_generate('<Motion>', warp=True, x=x, y=y)
            cv.event_generate('<Button-1>', x=x, y=y)
            cv.event_generate('<ButtonRelease-1>', x=x, y=y)
            T.pump(3)
            n = len(win.ch.inventory())
            win.top.event_generate('<Delete>')
            T.pump(5)
            T.eq(len(win.ch.inventory()), n - 1, 'Del removed the clicked item')
    finally:
        Path(win.ch.path).write_bytes(original)
        win.reload(keep=False)


@T.test
def clicking_an_item_grid_takes_the_focus_for_the_shortcuts():
    """Ctrl+C / Ctrl+V / Del are ignored while a text field has the focus; a click on any item grid (inventory, the
    belt of the Stash / Cube / Belt page) takes it (tester: copy / paste did not work on the belt)."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    win = T.chartab()
    T.pump(3)
    field = None
    stack = [win.top]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if w.winfo_class() in ('Entry', 'TEntry') and w.winfo_ismapped():
            field = w
            break
    grids = [win.inv]
    page = win.extra.get('containers')
    if page is not None and 'belt' in page.canvases:
        grids.append(page.canvases['belt'])
    import mxl_vanilla_he as V
    for cv in grids:
        V.set_tab(win, 'inventory' if cv is win.inv else 'containers')
        win.top.update()
        T.pump(3)
        if field is not None:
            field.focus_force()
            T.pump(2)
        else:
            win.top.winfo_toplevel().focus_force()      # the test display has no window manager to give focus
            T.pump(2)
        T.check('HEItemFocus' in cv.bindtags() or cv is win.inv, f'{cv} has the focus bind tag')
        if not cv.winfo_viewable():                    # focus only moves to a shown widget (page not on screen)
            continue
        cv.event_generate('<ButtonPress-1>', x=5, y=5)
        cv.event_generate('<ButtonRelease-1>', x=5, y=5)
        T.pump(2)
        T.eq(str(cv.focus_get()), str(cv), f'a click on {cv} takes the focus')


@T.test
def menu_autosave_and_auto_reload_toggles():
    """Menu > Autosave / Auto-reload (both on by default). Autosave off: an item action waits for SAVE."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from pathlib import Path
    import settings
    win = T.chartab()
    T.pump(3)
    labels = [win.he_menu.entrycget(i, 'label') for i in range(win.he_menu.index('end') + 1)
              if win.he_menu.type(i) == 'checkbutton']
    T.check({'Autosave', 'Auto-reload'} <= set(labels), f'menu toggles: {labels}')
    T.check(win.he_autosave_var.get() and win.he_auto_reload_var.get(), 'both on by default')
    before = Path(win.ch.path).read_bytes()
    try:
        win.he_autosave_var.set(False)
        settings.put('autosave', False)
        win.ch.remove(win.ch.items[0], False)
        T.check(win.save('deleted', operation='item'), 'item action accepted')
        T.eq(Path(win.ch.path).read_bytes(), before, 'Autosave off: the file is not written')
        T.check(win.dirty(), 'the edit waits for SAVE')
    finally:
        settings.put('autosave', True)
        Path(win.ch.path).write_bytes(before)
        win.reload(keep=False)



@T.test
def character_name_warning_and_save_anyway():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from tkinter import messagebox

    import mxl_char as MC
    import mxl_import
    import mxl_mock as mock
    import mxl_newchar as newchar

    for name in ('Ab', 'First-Last', 'First_Last', 'Abcdefghijklmno'):
        T.eq(MC.check_name(name), name, 'accepted game name')
    for name in ('A', 'A1', 'A--b', '_Ab', 'Ab-', 'Abcdefghijklmnop', 'Café'):
        T.check(MC.name_warning(name), 'invalid game name is flagged')
    for name in ('', '../Ab', 'A/B', 'A\\B', 'A\0B', 'Abcdefghijklmnop', '名'):
        try:
            MC.check_save_name(name, allow_invalid_name=True)
        except MC.CharError:
            continue
        T.check(False, 'unsafe or unencodable name was accepted')

    win = T.chartab()
    original = Path(win.ch.path)
    before = original.read_bytes()
    invalid = 'Test--Name'
    destination = original.with_name(invalid + '.d2s')
    entry = win.sv['name']
    entry.clipboard_clear()
    entry.clipboard_append(invalid)
    entry.select_range(0, 'end')
    entry.event_generate('<<Paste>>')
    win.top.update_idletasks()
    T.check('2 to 15' in win.bar_status.cget('text'), 'name warning appears while editing')
    T.check(win.st_set('name', invalid), 'invalid but writable name can be staged')
    prompts = []
    ask = messagebox.askyesno
    try:
        messagebox.askyesno = lambda *args, **kwargs: prompts.append(args[1]) or False
        win.save_progress()
        T.eq(original.read_bytes(), before, 'decline preserves original save')
        T.check(not destination.exists(), 'decline creates no save')
        T.eq(win.st_name, invalid, 'decline keeps the staged edit')
        T.check('Save anyway?' in prompts[-1] and '2 to 15' in prompts[-1], 'confirmation explains the rule')

        messagebox.askyesno = lambda *args, **kwargs: True
        win.save_progress()
        T.eq(MC.Character(destination, win.data).name, invalid, 'confirmed rename round trips')
        T.check(not original.exists(), 'rename removes old save')
        edits = MC.Character(destination, win.data)
        old_gold = edits.field('gold')
        win.st_set('gold', str(old_gold + 1))
        messagebox.askyesno = lambda *args, **kwargs: False
        win.save_progress()
        T.eq(MC.Character(destination, win.data).field('gold'), old_gold, 'existing bad name also prompts')
        messagebox.askyesno = lambda *args, **kwargs: True
        win.save_progress()
        T.eq(MC.Character(destination, win.data).field('gold'), old_gold + 1, 'existing bad name can be saved')
    finally:
        messagebox.askyesno = ask

    raw, _ = newchar.build(win.data, 'Fresh1', 0, 1, median=False, allow_invalid_name=True)
    path = newchar.write(raw, SAVES, 'Fresh1', allow_invalid_name=True)
    T.eq(MC.Character(path, win.data).name, 'Fresh1', 'new character retains confirmed name')
    copied = MC.copy_character(path, 'Copy2', win.data, allow_invalid_name=True)
    T.eq(MC.Character(copied, win.data).name, 'Copy2', 'copy retains confirmed name')
    imported = mxl_import.new_character(path, 'Café', 'Amazon', win.data, allow_invalid_name=True)
    T.eq(imported.name, 'Café', 'import template preserves the confirmed name')
    raw, _ = mock.generate(name='Mock3', allow_invalid_name=True)
    path = mock.write_new(raw, SAVES, 'Mock3', allow_invalid_name=True)
    T.eq(MC.Character(path, win.data).name, 'Mock3', 'mock retains confirmed name')


@T.test
def report_counts_children_even_when_the_socket_field_is_zero():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    from mxl_char import Entry
    from mxl_creator import decode_blob, encode_item
    from mxl_vanilla_he_items import character_report

    win = T.chartab()
    original = win.ch.items
    parent = next(entry for entry in original if entry.it.get('socketed'))
    record, children = decode_blob(parent.blob, win.data, exact=True)
    record['sockets'] = 0
    record['stats'] = [stat for stat in record.get('stats', []) if stat['id'] != 194]
    count = len(children)
    try:
        for bonus in (0, count):
            if bonus:
                record['stats'].append(dict(id=194, param=None, value=bonus))
            blob = encode_item(record, win.data) + b''.join(encode_item(child, win.data) for child in children)
            win.ch.items = [Entry(parent.it, blob)]
            T.check(f'Sockets = {count}/{bonus}' in character_report(win),
                    'report shows the filled sockets and the effective capacity')
    finally:
        win.ch.items = original


@T.test
def picked_up_item_is_editable_and_stays_out_of_the_character():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import tkinter as tk
    from mxl_vanilla_he_extras import open_extras, put_picked_up
    from mxl_vanilla_he_items import PICKED, picked_entry, replace_item

    win = T.chartab()
    entry = next(e for e in win.ch.entries() if e.it.get('quality') in ('set', 5))
    put_picked_up(win, bytes(entry.blob))
    before_char = bytes(win.ch.build())
    T.G.menu = None
    win.he_pickup.event_generate('<Button-3>', x=10, y=10)
    T.pump(3)
    T.check(T.G.menu is not None and 'General Edit of Item (in Extras Window)' in menu_labels(T.G.menu),
         'Picked Up right-click offers General Edit')
    top = open_extras(win, PICKED)
    T.pump(3)

    def boxes(widget):
        found = [widget] if isinstance(widget, tk.Listbox) else []
        for child in widget.winfo_children():
            found += boxes(child)
        return found

    lists = [box.get(0, 'end') for box in boxes(top)]
    T.check(any(row.split(': ', 1)[0].endswith('Picked Up') for rows in lists for row in rows),
         'Extras lists the Picked Up item')
    top.destroy()
    picked = picked_entry(win)
    blob = bytearray(picked.blob)
    replace_item(win, picked, bytes(picked.blob), bytes(blob), 'Modified item saved.', PICKED)
    T.eq(len(win.app._capy_clip[0]), len(blob), 'edit goes back into Picked Up')
    T.eq(picked_entry(win).it['code'], picked.it['code'], 'same item after the round trip')
    T.eq(bytes(win.ch.build()), before_char, 'character untouched')


@T.test
def library_add_refreshes_and_shows_sockets():
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import mxl_itemlib
    import mxl_tabs

    win = T.chartab()
    entry = next(e for e in win.ch.entries() if e.it.get('socketed'))
    T.select_tab('Library')
    lib = mxl_tabs.built_owner('Library')
    if lib is None:
        import mxl_itemlib as L
        lib = L.open_library(win.app)
    T.pump(3)
    count = len(lib.rows)
    added = mxl_itemlib.add(bytes(entry.blob), 'Socket probe', win.data)
    try:
        T.pump(3)
        T.eq(len(lib.rows), count + 1, 'list refreshed without a manual refresh')
        iid = next(i for i, e in lib.rows.items() if e['file'] == added['file'])
        lib.tree.selection_set(iid)
        T.pump(3)
        text = lib.detail.get('1.0', 'end')
        T.check('Socket' in text, 'tooltip shows the sockets')
        T.check(lib._icon(added) is not None, 'icon drawn')
    finally:
        mxl_itemlib.delete(added)



@T.test
def library_place_a_copy_goes_into_the_inventory_in_legit_mode_too():
    """xsiv: "Place a copy" / double-click placed nothing visible: the item went into the inventory, then the
    Library page broke writing "page {inv + 1}" (TypeError). Both modes: one more item, the page says where."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import mxl_itemlib, mxl_tabs, mxl_legit, mxl_char
    try:
        for legit in (False, True):
            win = T.chartab()
            mxl_legit.set_enabled(legit)
            small = min(win.ch.inventory(), key=lambda e: len(e.blob))
            entry = mxl_itemlib.add(bytes(small.blob), 'Place probe', win.data)
            try:
                win.ch.items.remove(small)
                T.check(win.save('room'), 'room made')
                T.select_tab('Library')
                T.pump(3)
                lib = mxl_tabs.built_owner('Library') or mxl_itemlib.open_library(win.app)
                T.pump(3)
                iid = next(i for i, e in lib.rows.items() if e['file'] == entry['file'])
                lib.tree.selection_set(iid)
                T.pump(2)
                before = len(mxl_char.Character(win.ch.path, win.data).items)
                lib.place()
                T.pump(5)
                T.eq(len(mxl_char.Character(win.ch.path, win.data).items), before + 1, f'placed (legit={legit})')
                T.check('inventory' in lib.status.cget('text'), lib.status.cget('text'))
            finally:
                mxl_itemlib.delete(entry)
    finally:
        mxl_legit.set_enabled(False)


@T.test
def set_row_without_its_own_picture_draws_the_items_own_base():
    """master86: on the "V1.12 Clone" (Sigon rows on other bases) the gloves slot showed boots and the boots slot a
    shield. The game draws the row's own invfile, else the item's OWN base (Sigon rows have none: gloves, boots)."""
    if not AVAILABLE:
        T.skip('vanilla game data or sample character is unavailable')
    import json
    from pathlib import Path
    import mxl_char as MC, mxl_newchar, mxl_gfx

    win = T.chartab()
    t = json.loads(Path(mxl_newchar.__file__).with_name('mxl_he_clone.json').read_text(encoding='utf-8'))
    raw = bytes.fromhex(''.join(t['bytes']))
    ch = MC.Character.__new__(MC.Character)
    ch.path, ch.data, ch.raw = None, win.data, raw
    ch.parse(raw)
    worn = {e.it['equipped']: e.it for e in ch.items if e.it['location'] == 1}
    T.eq((worn[10]['code'], worn[9]['code']), ('lgl ', 'mbt '), 'the example wears leather gloves and mesh boots')
    T.eq(mxl_gfx.icon_name(worn[10], win.data), 'invlgl', 'gloves slot: the gloves picture')
    T.eq(mxl_gfx.icon_name(worn[9], win.data), 'invmbt', 'boots slot: the boots picture')

T.main(globals())
