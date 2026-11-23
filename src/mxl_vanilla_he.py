"""Hero Editor 1.04 presentation for the vanilla character editor."""
from functools import lru_cache
from struct import error as StructError
import tkinter as tk
from tkinter import ttk

FORM = '#f5f5f5'
PEACH = '#ffe0c0'
WHITE = '#ffffff'
BLACK = '#000000'
EDGE = '#a6a6a6'
FRAME_EDGE = '#9e9e9e'
INSET = '#6a6a6a'
LIGHT = '#e3e3e3'
READONLY = '#c0c0c0'
SELECT = '#3096fa'
DESCRIPTION = '#707070'
SET_GREEN = '#00c800'
HEX_TITLE = '#0000c0'
FONT = ('Tahoma', 8)
SMALL_FONT = ('Tahoma', 7)
LEGEND_FONT = ('Tahoma', 8, 'italic')
DOC_FONT = ('Tahoma', 10)
TABS = (
    ('splash', 'Splash'), ('stats', 'Stats'), ('inventory', 'Inventory'),
    ('waypoints', 'Waypoints'), ('skills', 'Skills'), ('quests', 'Quests'),
    ('merc', 'Mercenary'), ('introductions', 'Introductions'), ('options', 'Options'),
    ('info', 'Info'), ('about', 'About'),
)
ACTIONS = ('OPEN', 'SAVE', 'RELOAD', 'EXTRAS', 'CLOSE')


def active():
    import mxl_profile
    return not mxl_profile.is_median()


def font(spec=FONT):
    from mxl_he_theme import families
    installed = families()
    family = next((name for name in ('Tahoma', 'MS Sans Serif', 'Liberation Sans', 'DejaVu Sans')
                   if name.lower() in installed), spec[0])
    return (family, *spec[1:])


def style(root):
    st = ttk.Style(root)
    st.theme_use('clam')
    st.configure('.', background=FORM, foreground=BLACK, fieldbackground=WHITE, selectbackground=SELECT,
                 selectforeground=WHITE, bordercolor=EDGE, lightcolor=WHITE, darkcolor=INSET, font=font())
    st.map('.', foreground=[('disabled', DESCRIPTION)])
    st.configure('TButton', padding=(5, 1), relief='raised')
    st.configure('TNotebook.Tab', padding=(6, 1))
    st.map('TNotebook.Tab', background=[('selected', FORM), ('!selected', LIGHT)])
    st.configure('TNotebook', tabmargins=(0, 0, 0, 0))
    st.layout('CharacterHost.TNotebook.Tab', [('null', {'sticky': 'nswe'})])
    st.configure('CharacterHost.TNotebook.Tab', padding=0)
    st.layout('CharacterHost.TNotebook', [('Notebook.client', {'sticky': 'nswe'})])
    st.configure('Extras.TNotebook', tabposition='sw')
    st.configure('Extras.TNotebook.Tab', padding=(9, 2))
    st.map('Extras.TNotebook.Tab', font=[('selected', (*font(), 'bold'))])
    st.configure('TScrollbar', arrowsize=12, width=12, troughcolor=LIGHT)
    st.configure('Treeview', rowheight=16)
    st.map('Treeview', background=[('selected', SELECT)], foreground=[('selected', WHITE)])
    st.map('TCombobox', fieldbackground=[('readonly', WHITE)])
    st.configure('Peach.TFrame', background=PEACH)
    st.configure('TLabelframe.Label', font=font(LEGEND_FONT))
    st.configure('TEntry', padding=1)
    st.configure('TCombobox', padding=1, arrowsize=12)
    st.configure('TSpinbox', padding=1, arrowsize=12)
    for kind in ('TProgressbar', 'Horizontal.TProgressbar', 'Vertical.TProgressbar'):
        st.configure(kind, background=SELECT)
    root.option_add('*TCombobox*Listbox.font', font())
    root.option_add('*TCombobox*Listbox.selectBackground', SELECT)
    root.option_add('*TCombobox*Listbox.selectForeground', WHITE)
    return st


def paint(widget):
    cls = widget.winfo_class()
    if cls == 'Menu':
        return
    if cls not in ('Frame', 'Toplevel', 'Tk', 'Labelframe', 'Label', 'Menubutton', 'Button',
                   'Checkbutton', 'Radiobutton', 'Entry', 'Spinbox', 'Listbox', 'Text', 'Scale'):
        return
    role = getattr(widget, '_vanilla_he_role', '')
    if role == 'art' or (getattr(widget, '_vanilla_he_font', None) is None
                         and cls in ('Label', 'Text', 'Entry') and str(widget.cget('font')) == 'TkFixedFont'):
        return
    surface = PEACH if role == 'peach' else '#ffffe1' if role == 'hint' else FORM
    opts = {'background': surface}
    if cls not in ('Frame', 'Toplevel', 'Tk'):
        opts.update(foreground=BLACK, font=font(LEGEND_FONT if cls == 'Labelframe' else FONT))
    if cls in ('Button', 'Menubutton', 'Checkbutton', 'Radiobutton', 'Scale'):
        opts.update(activebackground=LIGHT if cls == 'Button' else surface)
    if cls in ('Button', 'Menubutton', 'Checkbutton', 'Radiobutton'):
        opts.update(activeforeground=BLACK, disabledforeground=DESCRIPTION)
    if cls in ('Checkbutton', 'Radiobutton'):
        opts['selectcolor'] = WHITE
    if cls in ('Entry', 'Spinbox', 'Listbox', 'Text'):
        opts.update(background=WHITE, selectbackground=SELECT, selectforeground=WHITE)
    if cls in ('Entry', 'Spinbox'):
        opts.update(insertbackground=BLACK, readonlybackground=READONLY if role == 'name' else WHITE)
    if role == 'name':
        opts['background'] = READONLY
    if role == 'description':
        opts.update(background=DESCRIPTION, foreground=BLACK, font=font(SMALL_FONT))
    if role == 'document':
        opts.update(background=PEACH, font=font(DOC_FONT))
    if role == 'menu':
        opts.update(background=WHITE, activebackground=SELECT, activeforeground=WHITE)
    if role == 'tab':
        opts.update(selectcolor=FORM, background=LIGHT, activebackground=FORM)
    changed = {key: value for key, value in opts.items()
               if key != 'font' and str(widget.cget(key)).lower() != value.lower()}
    if 'font' in opts and getattr(widget, '_vanilla_he_font', None) != opts['font']:
        changed['font'] = opts['font']
    if changed:
        widget.configure(**changed)
        if 'font' in changed:
            widget._vanilla_he_font = changed['font']


def bitmap_font(size):
    from PIL import ImageFont

    for name in ('DejaVuSans.ttf', 'tahoma.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def role(widget, name):
    widget._vanilla_he_role = name
    paint(widget)
    return widget


def set_tab(win, key):
    win.tab.set(key)
    win.show_tab()


def choose_character(win):
    """Use the collector's character list and selection handler."""
    from tkinter import messagebox

    choices = win.app.char_combo.cget('values')
    if not choices:
        return
    dialog = tk.Toplevel(win.top)
    dialog.title('Open')
    dialog.transient(win.app.root)
    ttk.Label(dialog, text='Diablo II Saved Game File (*.d2s)').pack(anchor='w', padx=8, pady=6)
    names = tk.Listbox(dialog, width=40, height=min(12, len(choices)), exportselection=False)
    names.pack(fill='both', expand=True, padx=8)
    for name in choices:
        names.insert('end', name)
    names.selection_set(0)

    def open_selected(_event=None):
        selection = names.curselection()
        if not selection:
            return
        if win.dirty() and not messagebox.askyesno('Open', 'Discard unsaved changes?', parent=dialog):
            return
        name = names.get(selection[0])
        dialog.destroy()
        if name == win.app.char_combo.get():
            win.discard()
            return
        if win.dirty():
            win.discard()
        win.app.char_combo.set(name)
        win.app.select_character(name, win.app.view.get())
        from mxl_char_gui import CharacterWindow
        CharacterWindow(win.app)

    buttons = ttk.Frame(dialog)
    buttons.pack(fill='x', padx=8, pady=6)
    ttk.Button(buttons, text='Open', command=open_selected).pack(side='right')
    ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='right', padx=4)
    names.bind('<Double-Button-1>', open_selected)
    dialog.bind('<Return>', open_selected)
    dialog.bind('<Escape>', lambda _event: dialog.destroy())
    names.focus_set()


def chrome(win, bottom, actions):
    """Build the character action strip, status cells and tools menu."""
    import mxl_profile

    commands = (lambda: choose_character(win), win.save_progress, win.discard,
                lambda: extras(win), win.close)
    actions.configure(height=45, bg='#292621')
    actions.pack_configure(padx=0, pady=0)
    actions.pack_propagate(False)
    for text, command in zip(ACTIONS, commands):
        button = role(tk.Button(actions, text=text, command=command, font=font(),
                                bg='#d6b36c', fg='#251c0e', activebackground='#eed294',
                                activeforeground='#251c0e', bd=1, padx=12, pady=3), 'art')
        closing = text == 'CLOSE'
        button.pack(side='right' if closing else 'left', padx=(8, 8 if closing else 0), pady=7)
    status = tk.Frame(bottom, bg=FORM)
    status.pack(fill='x')
    version = (mxl_profile.active() or {}).get('version') or ''
    for label in ('Capybara Editor', f'Diablo II {version}'.rstrip()):
        tk.Label(status, text=label, anchor='w', bd=1, relief='sunken',
                 font=font(), bg=FORM, padx=6).pack(side='left', ipady=2)
    win.bar_status = role(tk.Label(status, text='Character Open: ' + win.ch.path, anchor='w',
                              bd=1, relief='sunken', font=font(), bg=FORM), 'art')
    win.bar_status.pack(side='left', fill='x', expand=True, ipady=2)
    bar = role(tk.Frame(win.top, bg=WHITE), 'art')
    bar.pack(side='top', fill='x')
    entry = role(tk.Menubutton(bar, text='Menu', underline=0, font=font(), bd=0,
                              bg=WHITE, activebackground=SELECT, activeforeground=WHITE), 'menu')
    entry.pack(side='left', padx=5)
    menu = win.he_menu = tk.Menu(entry, tearoff=False)
    entry.configure(menu=menu)
    for text, command in zip(ACTIONS, commands):
        menu.add_command(label=text.title(), underline=0, command=command)

    import mxl_mock_gui
    import mxl_tabs

    menu.add_separator()
    for name in ('Stash', 'Creator', 'Library', 'Bit editor'):
        menu.add_command(label=mxl_tabs.tab_label(name),
                         command=lambda key=name: win.top.master.select(mxl_tabs._state['pages'][key]))
    mock_mode = mxl_mock_gui._state['var']
    if mock_mode is not None:
        menu.add_checkbutton(label='Mock Mode', variable=mock_mode,
                             command=lambda: mxl_mock_gui.set_mode(mock_mode.get()))
        menu.add_command(label='Open Mock Tools', command=lambda: mxl_tabs.focus_existing(mxl_mock_gui.TAB))
        mock_tools_index = menu.index('end')
        menu.configure(postcommand=lambda: menu.entryconfigure(
            mock_tools_index, state='normal' if mock_mode.get() else 'disabled'))


def extras(win):
    from mxl_toolbar import EXTRA
    from mxl_creator_gui import CreatorWindow, clean
    from mxl_rc_menu import _inspect_char
    from mxl_he_stats import open_char_item_stats
    from mxl_itemlib import open_library

    top = tk.Toplevel(win.top)
    top.title('Extras')
    top.geometry('681x371')
    entries = [(entry, merc) for merc in (False, True) for entry in win.ch.entries(merc)]
    header = ttk.Frame(top, padding=5)
    header.pack(fill='x')
    ttk.Label(header, text=f'Total items: {len(entries)}    Character: {win.ch.name}').pack(side='left')
    ttk.Button(header, text='Close', command=top.destroy).pack(side='right')
    ttk.Separator(top).pack(fill='x')
    notebook = ttk.Notebook(top, style='Extras.TNotebook')
    notebook.pack(fill='both', expand=True, padx=8, pady=(6, 0))
    for caption in ('Character Hex', 'Item Binary Compare/Edit', 'Item Edit', 'Item/Character Create'):
        page = ttk.Frame(notebook, style='Peach.TFrame', padding=6)
        notebook.add(page, text=caption)
        if caption == 'Character Hex':
            title = ttk.Label(page, text='Character Hex', background=PEACH, foreground=HEX_TITLE)
            title.pack(anchor='w')
            view = tk.Text(page, font='TkFixedFont', width=65, height=10, relief='sunken', wrap='none')
            scroll = ttk.Scrollbar(page, command=view.yview)
            view.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y')
            view.pack(fill='both', expand=True)
            raw = win.ch.raw
            view.insert('1.0', '\n'.join(f'{i:08X}  {bytes(raw[i:i + 16]).hex(" ").upper()}'
                                        for i in range(0, len(raw), 16)))
            view.configure(state='disabled')
        elif caption in ('Item Binary Compare/Edit', 'Item Edit'):
            items = tk.Listbox(page, width=38, exportselection=False)
            items.pack(side='left', fill='both', expand=True)
            for entry, _merc in entries:
                items.insert('end', clean(entry.it.get('name') or entry.it['code']))
            if entries:
                items.selection_set(0)
            edit = _inspect_char if caption == 'Item Binary Compare/Edit' else open_char_item_stats

            def open_item(_event=None, items=items, edit=edit):
                selection = items.curselection()
                if selection:
                    entry, merc = entries[selection[0]]
                    entry = win.current_entry(entry, merc)
                    if entry is not None:
                        edit(win, entry)
                        top.destroy()

            items.bind('<Double-Button-1>', open_item)
            ttk.Button(page, text='Open item', command=open_item).pack(side='left', anchor='n', padx=5)
        else:
            def run(command):
                top.destroy()
                command()

            ttk.Button(page, text='Item Creator', command=lambda: run(lambda: CreatorWindow(win.app))).pack(anchor='w')
            ttk.Button(page, text='Item Library', command=lambda: run(lambda: open_library(win.app))).pack(anchor='w')
            for title, command in EXTRA:
                if command is not open_library:
                    ttk.Button(page, text=title(), command=lambda command=command: run(
                        lambda: command(win.app))).pack(anchor='w')

    menu = tk.Menu(top, tearoff=False)
    top.configure(menu=menu)
    pages = tk.Menu(menu, tearoff=False)
    menu.add_cascade(label='Character', menu=pages)
    reference = dict(TABS)
    for button in win.tab_buttons:
        key = button.cget('value')
        if key not in reference:
            pages.add_command(label=button.cget('text'), command=lambda key=key: run(lambda: set_tab(win, key)))


def build_reference_pages(win):
    """Add the informational pages and expose existing settings commands."""
    from PIL import Image, ImageTk
    artwork = splash_image()
    for key in ('splash', 'about'):
        panel = tk.Canvas(win.pages[key], width=638, height=430, bg=BLACK,
                          highlightthickness=1, highlightbackground=EDGE)
        panel.pack(fill='both', expand=True)
        if artwork is not None:
            panel.artwork = ImageTk.PhotoImage(artwork.resize((638, 430), Image.LANCZOS), master=panel)
            panel.create_image(0, 0, anchor='nw', image=panel.artwork)
        else:
            panel.create_text(24, 142, text='Diablo II', fill='#c89b52', anchor='w',
                              font=('Times New Roman', 34, 'bold'))
        panel.create_text(24, 187, text='Capybara Editor', fill='#e2bd74', anchor='w',
                          font=('Times New Roman', 25, 'bold'))
        panel.create_text(26, 226, text='Diablo II · Lord of Destruction', fill='#bdd8e0',
                          anchor='w', font=font(LEGEND_FONT))
        if key == 'about':
            panel.create_text(24, 38, text='Layout inspiration: Hero Editor by ZonFire99 and Mastadex',
                              fill=WHITE, anchor='w', font=font())
    page = win.pages['info']
    info = role(tk.Text(page, wrap='word', width=65, height=22, bg=PEACH,
                        font=font(DOC_FONT), relief='sunken', bd=2), 'document')
    scroll = ttk.Scrollbar(page, command=info.yview)
    scroll.pack(side='right', fill='y')
    info.configure(yscrollcommand=scroll.set)
    info.pack(side='left', fill='both', expand=True)
    info.insert('1.0', 'Open a Diablo II character to view or edit its stats, inventory, skills, '
                       'waypoints, quests and mercenary.\n\n'
                       'Use Save to write pending character changes and Reload to read the character again. '
                       'Finish a field with Enter. Up and Down step the selected value. '
                       'Hold Shift to step by ten. The plus buttons spend available stat points.\n\n'
                       'Right-click inventory items for editing and clipboard commands.')
    info.configure(state='disabled')
    options(win)
    introductions(win)


def options(win):
    import mxl_mock_gui
    import mxl_profile

    page = win.pages['options']
    ttk.Label(page, text='Choose the game folder and editing options.').grid(
        row=0, column=0, columnspan=2, sticky='w', pady=(0, 4))
    for column in range(2):
        page.columnconfigure(column, weight=1, uniform='options')
    game = ttk.LabelFrame(page, text='Diablo II game folder', padding=6)
    game.grid(row=1, column=0, sticky='nsew', padx=(0, 4))
    ttk.Button(game, text='Game folder…', command=lambda: mxl_profile.open_dialog(win.app)).pack(anchor='w')

    editing = ttk.LabelFrame(page, text='Character editing', padding=6)
    editing.grid(row=1, column=1, sticky='nsew')
    mock_mode = mxl_mock_gui._state['var']
    if mock_mode is not None:
        ttk.Checkbutton(editing, text='Mock Mode', variable=mock_mode,
                        command=lambda: mxl_mock_gui.set_mode(mock_mode.get(), select=False)).pack(anchor='w')
    if 'quests_adv' in win.pages:
        ttk.Button(editing, text='Advanced quest words…',
                   command=lambda: set_tab(win, 'quests_adv')).pack(anchor='w')

    tools = ttk.LabelFrame(page, text='Item and character tools', padding=6)
    tools.grid(row=2, column=0, columnspan=2, sticky='ew', pady=4)
    ttk.Button(tools, text='Extras…', command=lambda: extras(win)).pack(anchor='w')


def introductions(win):
    """Read the saved introduction and act-travel words for each difficulty."""
    from mxl_char import difficulty_name

    def refresh():
        for tree, diff, title, use_travel in trees:
            tree.delete(*tree.get_children())
            root = tree.insert('', 'end', text=title, open=True)
            for act, intro, _quests, travel in win.ch.quest_acts():
                word = travel if use_travel else intro
                if word is not None:
                    value = '☑' if win.ch.quest_word(diff, word) else '☐'
                    tree.insert(root, 'end', text=f'{value} {act}')

    page = win.pages['introductions']
    trees = []
    for title, travel in (('Introductions', False), ('Travelled to the next act', True)):
        group = ttk.LabelFrame(page, text=title, padding=3)
        group.pack(fill='both', expand=True, pady=(0, 4))
        for diff in range(3):
            frame = ttk.LabelFrame(group, text=difficulty_name(diff), padding=3)
            frame.pack(side='left', fill='both', expand=True, padx=2)
            tree = ttk.Treeview(frame, show='tree', height=8)
            tree.column('#0', width=182, minwidth=100)
            tree.pack(fill='both', expand=True)
            trees.append((tree, diff, title, travel))
    page.bind('<Map>', lambda _event: refresh())



CLASS_ART = (('amazon', 'AM'), ('sorceress', 'SO'), ('necromancer', 'NE'), ('paladin', 'PA'),
             ('barbarian', 'BA'), ('druid', 'DZ'), ('assassin', 'AS'))


def game_art():
    """Read optional art from the active game folder."""
    import os
    from mxl_profile import active as profile
    from mxl_d2look_art import get_art

    game = profile()
    if game and game.get('game_dir') and game.get('root'):
        return get_art(game['game_dir'], 'classic_sigma', os.path.join(game['root'], 'ui_art'))


@lru_cache(maxsize=24)
def native_frames(art, path, palette=None):
    from mxl_d2look_art import ArtError
    from mxl_d2ui_dc6 import dc6_frames, palette as decode_palette

    try:
        data = art.read_base('data\\global\\ui\\' + path)
        pal = decode_palette(art.read_base(f'data\\global\\palette\\{palette}\\pal.dat')) if palette else art.pal()
        return dc6_frames(data), pal
    except (ArtError, OSError, ValueError, IndexError, OverflowError, StructError):
        return (), None


def character_image(cls):
    from PIL import Image
    from mxl_d2ui_dc6 import to_rgba

    art = game_art()
    if art is None or not 0 <= cls < len(CLASS_ART):
        return None
    folder, code = CLASS_ART[cls]
    frames, pal = native_frames(art, f'FrontEnd\\{folder}\\{code}NU1.dc6', 'fechar')
    if not frames:
        return None
    width, height, rgba = to_rgba(frames[0], pal)
    return Image.frombytes('RGBA', (width, height), bytes(art._bright(rgba)))


def splash_image():
    from PIL import Image
    from mxl_d2ui_dc6 import compose

    art = game_art()
    if art is None:
        return None
    frames, pal = native_frames(art, r'FrontEnd\TitleScreen.dc6', 'Menu0')
    if not frames:
        return None
    width, height, rgba = compose(frames, pal, 4)
    return Image.frombytes('RGBA', (width, height), bytes(rgba))


def character_portrait(parent):
    panel = tk.Canvas(parent, width=207, height=431, bg=BLACK, bd=0, highlightthickness=0)
    panel.create_rectangle(1, 1, 206, 430, outline='#624824')
    panel.create_rectangle(5, 5, 202, 426, outline='#b3914d')
    panel.create_rectangle(8, 8, 199, 423, outline='#4c3620')
    for x in (18, 189):
        for y in (20, 411):
            panel.create_polygon(x - 10, y, x, y - 8, x + 10, y, x, y + 8, fill='#57411f', outline='#c7a564')
            panel.create_line(x, y - 12, x, y + 12, fill='#c7a564')
    return panel


def update_portrait(panel, cls, data):
    from PIL import Image, ImageTk
    from mxl_char import class_names

    if getattr(panel, '_he_class', None) == cls:
        return
    panel._he_class = cls
    panel.delete('portrait')
    portrait = character_image(cls)
    if portrait is not None:
        scale = min(185 / portrait.width, 345 / portrait.height)
        size = (round(portrait.width * scale), round(portrait.height * scale))
        panel._he_portrait = ImageTk.PhotoImage(portrait.resize(size, Image.LANCZOS), master=panel)
        panel.create_image(103, 210, image=panel._he_portrait, tags='portrait')
    names = class_names(data)
    if 0 <= cls < len(names):
        panel.create_text(103, 396, text=names[cls], fill='#d6b36c',
                          font=('Times New Roman', 13), tags='portrait')


def quest_details(win, parent):
    """Drive the character's pending quest selections from the selected tree node."""
    left = ttk.Frame(parent)
    left.pack(side='left', fill='y')
    details = ttk.LabelFrame(left, text='Selected Quest', padding=6)
    details.pack(fill='x')
    title = ttk.Label(details, text='Select a quest', width=44, wraplength=250)
    title.pack(anchor='w')
    value = tk.BooleanVar()
    selected = {}

    def apply():
        tree, iid = selected['tree'], selected['iid']
        if iid in tree.keys and iid not in tree.locked and tree.value[iid] != value.get():
            tree.toggle(iid)

    reward = ttk.Checkbutton(details, text='Quest completed', variable=value, command=apply)
    reward.pack(anchor='w', pady=(10, 0))
    reward.state(['disabled'])
    batch = ttk.LabelFrame(left, text='Batch', padding=6)
    batch.pack(fill='x', pady=5)
    mode = tk.BooleanVar(value=True)

    def change_group(scope):
        tree, iid = selected['tree'], selected['iid']
        if scope == 'all':
            group = tree.leaves('')
        else:
            group = tree.tv.parent(iid) if iid in tree.keys else iid
            if scope == 'mode':
                while tree.tv.parent(group):
                    group = tree.tv.parent(group)
            group = tree.leaves(group)
        want = mode.get()
        values = {}
        for leaf in group:
            if leaf not in tree.locked and tree.value[leaf] != want:
                key = tree.keys[leaf]
                values[key] = want
                win.on_tree_change(key, want)
        tree.set_values(values)
        refresh(tree)

    ttk.Radiobutton(batch, text='Complete', variable=mode, value=True).pack(anchor='w')
    ttk.Radiobutton(batch, text='Reopen pending changes', variable=mode, value=False).pack(anchor='w')
    buttons = []
    for scope, text in (('act', 'Current Act'), ('mode', 'Current Mode'), ('all', 'All Modes')):
        button = ttk.Button(batch, text=text, command=lambda scope=scope: change_group(scope))
        button.pack(fill='x', pady=2)
        button.state(['disabled'])
        buttons.append(button)

    def refresh(tree):
        selection = tree.tv.selection()
        iid = selection[0] if selection else ''
        selected.update(tree=tree, iid=iid)
        title.configure(text=tree.tv.item(iid, 'text').strip() if iid else 'Select a quest')
        value.set(tree.value.get(iid, False))
        reward.state(['!disabled'] if iid in tree.keys and iid not in tree.locked else ['disabled'])
        for button in buttons:
            button.state(['!disabled'] if iid else ['disabled'])

    return refresh


class InventoryTabs(tk.Canvas):
    """Clockwise inventory tabs with the same command for mouse and keyboard."""
    def __init__(self, parent, variable, command):
        from PIL import Image, ImageDraw, ImageTk

        super().__init__(parent, width=21, height=409, bg=FORM, bd=0, highlightthickness=0, takefocus=True)
        self.variable = variable
        self.command = command
        self.tabs = []
        self.images = []
        face = bitmap_font(11)
        y = 0
        for key, label in (('person', '(1) Person'), ('stash', '(2) Stash'), ('cube', '(3) Cube'),
                           ('merc', '(4) Merc / Belt'), ('transfer', 'Transfer')):
            length = face.getbbox(label)[2] + 13
            rasters = []
            for surface in (LIGHT, FORM):
                paper = Image.new('RGB', (length, 21), surface)
                draw = ImageDraw.Draw(paper)
                draw.rectangle((0, 0, length - 1, 20), outline=EDGE)
                draw.line((1, 1, length - 2, 1), fill=WHITE)
                draw.text((length // 2, 10), label, font=face, fill=BLACK, anchor='mm')
                rasters.append(ImageTk.PhotoImage(paper.transpose(Image.Transpose.ROTATE_270), master=self))
            image = self.create_image(0, y, anchor='nw', image=rasters[0])
            self.images.extend(rasters)
            self.tabs.append((key, y, y + length, image, rasters))
            y += length
        self.bind('<Button-1>', self._click)
        self.bind('<Up>', lambda _event: self._step(-1))
        self.bind('<Down>', lambda _event: self._step(1))
        self.trace = self.variable.trace_add('write', self.refresh)
        self.bind('<Destroy>', lambda _event: self.variable.trace_remove('write', self.trace))
        self.refresh()

    def refresh(self, *_args):
        for key, _start, _end, image, rasters in self.tabs:
            self.itemconfigure(image, image=rasters[key == self.variable.get()])

    def _click(self, event):
        self.focus_set()
        for key, start, end, _image, _rasters in self.tabs:
            if start <= event.y < end:
                self.command(key)
                return

    def _step(self, step):
        keys = [tab[0] for tab in self.tabs]
        self.command(keys[(keys.index(self.variable.get()) + step) % len(keys)])
        return 'break'


def item_hint(owner):
    from mxl_floattip import FloatTip

    def build(body):
        role(body, 'hint')
        role(tk.Label(body, text='Drag to move · Right-click for item actions',
                      padx=3, pady=1, font=font()), 'hint').pack()

    return FloatTip(owner, build=build, bg='#ffffe1', edge=EDGE)


def inventory_images(grid):
    """Use the native panel at one pixel per pixel, shared with the stash-side inventory."""
    from mxl_d2look import char_art, photo
    from mxl_d2look_art import ArtError
    from mxl_vanilla_pages import NATIVE_GRID, NATIVE_PANEL, _NativeArt

    art = char_art()
    if art is None:
        return {}
    try:
        path = _NativeArt(art).char_panel_d2()
        width = int(grid.cget('width')) - 1
        height = int(grid.cget('height')) - 1
        x, y = NATIVE_GRID
        panel_width, panel_height = NATIVE_PANEL
        if x + width > panel_width or y + height >= panel_height:
            return {}
        return dict(doll=photo(path, crop=(0, 0, panel_width, y)),
                    grid=photo(path, crop=(x, y, x + width, y + height)),
                    footer=photo(path, crop=(0, y + height, panel_width, panel_height)))
    except (ArtError, OSError, ValueError, IndexError, StructError):
        return {}


def weapon_tabs(win, event=None):
    from mxl_d2look import WSET_TAB_D2, WSET_TABS_D2
    from mxl_vanilla_pages import _n

    width, height = map(_n, WSET_TAB_D2)
    for weapon_set, positions in WSET_TABS_D2.items():
        for x, y in positions:
            x, y = _n(x), _n(y)
            if event is None:
                if win.wset.get() == weapon_set:
                    win.doll.create_rectangle(x, y, x + width - 1, y + height - 1, outline='#d4b062')
            elif x <= event.x < x + width and y <= event.y < y + height:
                return weapon_set
    return None
