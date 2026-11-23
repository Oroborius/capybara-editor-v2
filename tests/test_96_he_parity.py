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


T.main(globals())
