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
    st.configure('Extras.TNotebook.Tab', padding=(9, 2), width=23)
    st.map('Extras.TNotebook.Tab', font=[('selected', (*font(), 'bold'))])
    st.configure('TScrollbar', arrowsize=12, width=12, troughcolor=LIGHT)
    st.configure('Treeview', rowheight=16)
    st.map('Treeview', background=[('selected', SELECT)], foreground=[('selected', WHITE)])
    st.map('TCombobox', fieldbackground=[('readonly', WHITE)])
    st.configure('Peach.TFrame', background=PEACH)
    st.configure('Peach.TLabelframe', background=PEACH)
    st.configure('Peach.TLabelframe.Label', background=PEACH, font=font(LEGEND_FONT))
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


def action_plaque(parent, caption, shade):
    """Draw an original stone plaque with riveted brass trim."""
    import random
    from PIL import Image, ImageDraw, ImageFont, ImageTk

    rng = random.Random(104)
    im = Image.new('RGB', (96, 34), '#000000')
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((0, 0, 95, 33), radius=5, fill='#5e3f1e', outline='#b88c49')
    draw.rounded_rectangle((2, 2, 93, 31), radius=4, outline='#e3c17a')
    draw.rounded_rectangle((4, 4, 91, 29), radius=3, fill='#141312', outline='#392819')
    for y in range(6, 28):
        for x in range(6, 90):
            tone = 28 + shade + rng.randrange(12) + (28 - y) // 3
            draw.point((x, y), fill=(tone + 4, tone + 2, tone))
    for x in (9, 86):
        draw.ellipse((x - 3, 13, x + 3, 19), fill='#946530', outline='#4b3016')
        draw.point((x - 1, 14), fill='#f4d28c')
    try:
        face = ImageFont.truetype('DejaVuSans-Bold.ttf', 12)
    except OSError:
        face = ImageFont.load_default()
    draw.text((48, 18), caption, anchor='mm', font=face, fill='#0a0806')
    draw.text((48, 16), caption, anchor='mm', font=face, fill='#e5c178')
    return ImageTk.PhotoImage(im, master=parent)


def chrome(win, bottom, actions):
    """Build the character action strip, status cells and tools menu."""
    commands = (lambda: choose_character(win), win.save_progress, win.discard,
                lambda: extras(win), win.close)
    actions.configure(height=45, bg=BLACK)
    actions.pack_configure(padx=0, pady=0)
    actions.pack_propagate(False)
    for text, command in zip(ACTIONS, commands):
        images = [action_plaque(actions, text, shade) for shade in (0, 12, -5)]
        button = role(tk.Button(actions, text=text, image=images[0], command=command, bd=0,
                                bg=BLACK, activebackground=BLACK, highlightthickness=0,
                                padx=0, pady=0, cursor='hand2'), 'art')
        button.images = images
        button.bind('<Enter>', lambda event: event.widget.configure(image=event.widget.images[1]))
        button.bind('<Leave>', lambda event: event.widget.configure(image=event.widget.images[0]))
        button.bind('<ButtonPress-1>', lambda event: event.widget.configure(image=event.widget.images[2]))
        button.bind('<ButtonRelease-1>', lambda event: event.widget.configure(image=event.widget.images[1]))
        closing = text == 'CLOSE'
        button.pack(side='right' if closing else 'left', padx=(72 if text == 'EXTRAS' else 8, 8 if closing else 0),
                    pady=(6, 5))
    status = tk.Frame(bottom, bg=FORM)
    status.pack(fill='x')
    for label, width in (('Hero Editor', 70), ('Version 1.04', 108)):
        cell = tk.Frame(status, width=width, height=19)
        cell.pack(side='left')
        cell.pack_propagate(False)
        tk.Label(cell, text=label, anchor='w', bd=1, relief='sunken',
                 font=font(), bg=FORM, padx=1).pack(fill='both', expand=True)
    win.bar_status = role(tk.Label(status, text='Character Open: ' + win.ch.path, anchor='w',
                              bd=1, relief='sunken', font=font(), bg=FORM), 'art')
    win.bar_status.pack(side='left', fill='x', expand=True, ipady=2)
    bar = role(tk.Frame(win.top, bg=WHITE), 'art')
    bar.pack(side='top', fill='x')
    entry = role(tk.Menubutton(bar, text='Menu', underline=0, font=font(), bd=0,
                              bg=WHITE, activebackground=SELECT, activeforeground=WHITE), 'menu')
    entry.pack(side='left', padx=3, ipady=1)
    menu = win.he_menu = tk.Menu(entry, tearoff=False)
    entry.configure(menu=menu)
    for text, command in zip(ACTIONS, commands):
        menu.add_command(label=text.title(), underline=0, command=command)

    import mxl_mock_gui
    import mxl_tabs

    from tkinter import simpledialog

    def ask(caption, value, limits=None):
        if limits is None:
            name = simpledialog.askstring(caption, 'Character name', parent=win.top)
            if name:
                win.copy_name.set(name)
                win.copy_char()
            return
        lo, hi = limits
        if lo > hi:
            win.set_bar('The character is at the maximum level.')
            return
        number = simpledialog.askinteger(caption, caption, initialvalue=value, minvalue=lo, maxvalue=hi,
                                         parent=win.top)
        if number is not None:
            win.st_set('levelup' if caption == 'Level up to' else 'skill_points', number)

    tools = tk.Menu(menu, tearoff=False)
    menu.add_cascade(label='Character tools', menu=tools)
    tools.add_command(label='Copy as…', command=lambda: ask('Copy as', None))
    tools.add_command(label='Match experience to level', command=win.st_match_exp)
    tools.add_command(label='Level up to…', command=lambda: ask('Level up to', win.st_sim.level + 1,
                           (win.st_sim.level + 1, win.st_range('levelup')[1])))
    tools.add_command(label='Skill Points Left…', command=lambda: ask('Skill Points Left',
                           win.st_value('skill_points'), win.st_range('skill_points')))
    tools.add_command(label='Mark Hell finished', command=lambda: win.st_done(3))
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
    header = ttk.Frame(top, padding=(8, 3))
    header.pack(fill='x')
    total = sum(1 + len(entry.it.get('socketed', ())) for entry, _merc in entries)
    ttk.Label(header, text=f'Total items: {total}').grid(row=0, column=0, padx=(0, 18), sticky='w')
    ttk.Label(header, text=f'Save version: {win.ch.version}').grid(row=0, column=1, sticky='w')
    ttk.Label(header, text=f'Character Name: {win.ch.name}').grid(row=1, column=0, columnspan=2, sticky='w')
    header.columnconfigure(2, weight=1)
    ttk.Button(header, text='Close', command=top.destroy).grid(row=0, column=3, rowspan=2)
    ttk.Separator(top).pack(fill='x')
    notebook = ttk.Notebook(top, style='Extras.TNotebook')
    notebook.pack(fill='both', expand=True, padx=8, pady=(6, 0))
    for caption in ('Character Hex', 'Item Binary Compare/Edit', 'Item Edit', 'Item/Character Create'):
        page = ttk.Frame(notebook, style='Peach.TFrame', padding=6)
        notebook.add(page, text=caption)
        if caption == 'Item Edit':
            notebook.select(page)
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
            item_panel = ttk.LabelFrame(page, text='Character Items', padding=3, style='Peach.TLabelframe')
            item_panel.pack(side='left', fill='y')
            items = tk.Listbox(item_panel, width=30, exportselection=False)
            scrollbar = ttk.Scrollbar(item_panel, command=items.yview)
            items.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side='right', fill='y')
            items.pack(side='left', fill='both', expand=True)
            content = ttk.Frame(page, style='Peach.TFrame', padding=(5, 0))
            content.pack(side='right', fill='both', expand=True)
            binary = caption == 'Item Binary Compare/Edit'
            fields = ttk.Treeview(content, show='tree', height=9, selectmode='browse')
            field_groups = {
                'Basic': ('code', 'ilvl', 'identified', 'ethereal', 'socketed_count'),
                'Location': ('location', 'equipped', 'panel', 'x', 'y'),
                'Quality': ('quality', 'unique_id', 'set_id', 'personalized'),
                'Magic Attributes': (),
            }
            if not binary:
                fields.column('#0', width=124, minwidth=96)
                for label in field_groups:
                    fields.insert('', 'end', iid=label, text=label)
                fields.selection_set('Basic')
                fields.pack(side='left', fill='y', padx=(0, 4))
            pane = ttk.Frame(content, style='Peach.TFrame')
            pane.pack(side='left', fill='both', expand=True)
            inspector = tk.Text(pane, width=28, height=8, wrap='word', relief='sunken', bd=2,
                                font='TkFixedFont' if binary else font())
            inspector.pack(fill='both', expand=True)

            def preview(_event=None, items=items, inspector=inspector, fields=fields, binary=binary):
                selection = items.curselection()
                inspector.configure(state='normal')
                inspector.delete('1.0', 'end')
                if selection:
                    entry, merc = entries[selection[0]]
                    entry = win.current_entry(entry, merc)
                    if entry is not None:
                        if binary:
                            text = ' '.join(f'{byte:08b}' for byte in entry.blob)
                        else:
                            group = next(iter(fields.selection()), 'Basic')
                            if group == 'Magic Attributes':
                                from mxl_statnames import stat_text
                                text = '\n'.join(filter(None, (stat_text(win.data, stat['id'], stat.get('param'),
                                                    stat.get('value', 1)) for stat in entry.it.get('stats', ()))))
                            else:
                                text = '\n'.join(f'{key.replace("_", " ").title()}: {entry.it[key]}'
                                                 for key in field_groups[group] if key in entry.it)
                        inspector.insert('1.0', text)
                inspector.configure(state='disabled')

            items.bind('<<ListboxSelect>>', preview)
            fields.bind('<<TreeviewSelect>>', preview)
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
            ttk.Button(pane, text='Open Item Editor' if caption == 'Item Edit' else 'Open Bit Editor',
                       command=open_item).pack(anchor='e', pady=3)
            preview()
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


TOWNS = ('Rogue Encampment', 'Lut Gholein', 'Kurast Docks', 'Pandemonium Fortress', 'Harrogath')


def stats(win, page, entry):
    """Lay out the vanilla stats at their native pixel sizes."""
    page.configure(width=644, height=440)
    win.he_portrait = character_portrait(page)
    win.he_portrait.place(x=2, y=4, width=209, height=435)
    form = tk.Frame(page, bd=1, relief='sunken')
    form.place(x=218, y=4, width=424, height=435)

    def group(caption, x, y, w, h):
        frame = role(tk.LabelFrame(form, text=caption, bd=1, relief='groove'), '')
        frame.place(x=x, y=y, width=w, height=h)
        return frame

    def label(parent, text, x, y):
        role(tk.Label(parent, text=text, padx=0, pady=0), '').place(x=x, y=y, height=18)

    def box(parent, key, x, y, w):
        control = entry(parent, key, 1)
        control.place(x=x, y=y, width=w, height=18)
        return control

    def button(parent, text, command, x, y, w):
        role(tk.Button(parent, text=text, command=command, pady=0, padx=0), '').place(
            x=x, y=y, width=w, height=18)

    def rename():
        from tkinter.simpledialog import askstring

        name = askstring('Rename Character', 'New name', initialvalue=win.st_value('name'), parent=win.top)
        if name is not None:
            win.st_set('name', name)

    fr = group('Name', 7, 0, 215, 44)
    box(fr, 'name', 7, 2, 120)
    button(fr, 'Rename', rename, 135, 2, 73)

    fr = group('Level', 7, 45, 215, 39)
    box(fr, 'level', 4, 0, 92)
    win.he_over99 = tk.BooleanVar()
    win.he_level_character = None
    cb = role(tk.Checkbutton(fr, text='Level over 99', variable=win.he_over99, padx=0, pady=0, highlightthickness=0), '')
    cb.place(x=108, y=0, height=18)

    box(group('Experience', 7, 86, 104, 41), 'experience', 4, 1, 92)
    box(group('Masked Level', 119, 86, 103, 41), 'header_level', 6, 1, 88)

    fr = group('Constitution', 7, 127, 215, 97)
    for y, name in zip((1, 25, 57), ('Life', 'Mana', 'Stamina')):
        key = name.lower()
        label(fr, name + ':', 6, y)
        box(fr, key + '_cur', 46, y, 51)
        label(fr, '/', 100, y)
        box(fr, key + '_max', 106, y, 51)
        label(fr, '.', 159, y)
        box(fr, key + '_frac', 165, y, 20)
        label(fr, '/ ___', 187, y)

    fr = group('Gold', 7, 224, 215, 64)
    for y, name, key in ((1, 'Person:', 'gold'), (25, 'Stash:', 'gold_stash')):
        label(fr, name, 6, y)
        box(fr, key, 71, y, 96)
        button(fr, 'Max', lambda key=key: win.st_set(key, win.st_range(key)[1]), 175, y, 33)
    label(form, 'The following stats are READ ONLY', 17, 300)

    fr = group('Class', 231, 0, 184, 44)
    win.class_box = ttk.Combobox(fr, state='readonly', textvariable=win.new_class, values=win.class_names,
                                font=font())
    win.class_box.place(x=7, y=2, width=168, height=21)
    win.class_box.bind('<<ComboboxSelected>>', lambda _event: win.on_class_change())

    from mxl_char import difficulty_name
    fr = group('Character Difficulty', 231, 46, 184, 35)
    win.sv_diff = tk.IntVar()
    for i, x in enumerate((5, 62, 135)):
        radio = role(tk.Radiobutton(fr, text=difficulty_name(i), value=i, variable=win.sv_diff, padx=0, pady=0,
                                   highlightthickness=0,
                                   command=lambda i=i: win.st_do('start_difficulty', i)), '')
        radio.place(x=x, y=-2, height=18)
        if win.ch.early:
            radio.configure(state='disabled')

    fr = group('Starting Town', 231, 83, 184, 42)
    win.he_town = ttk.Combobox(fr, state='disabled' if win.ch.early else 'readonly', values=TOWNS, font=font())
    win.he_town.place(x=7, y=0, width=168, height=21)
    def change_town(_event):
        if not win.st_do('start_town', TOWNS.index(win.he_town.get())):
            refresh_stats(win)

    win.he_town.bind('<<ComboboxSelected>>', change_town)

    fr = group('Characteristics', 231, 125, 184, 140)
    for y, (name, key) in zip((1, 25, 49, 73, 100), (
            ('Strength', 'strength'), ('Dexterity', 'dexterity'), ('Vitality', 'vitality'),
            ('Energy', 'energy'), ('Stat Points Left', 'stat_points'))):
        label(fr, name + ':', 6, y)
        control = box(fr, key, 95, y, 80)
        if key != 'stat_points':
            menu = tk.Menu(control, tearoff=False)
            menu.add_command(label='Spend a stat point', command=lambda key=key: win.st_plus(key))
            menu.add_command(label='Return a stat point', command=lambda key=key: win.st_plus(key, take=True))
            control.bind('<Button-3>', lambda event, menu=menu: menu.tk_popup(event.x_root, event.y_root))

    fr = group('Character Type', 231, 265, 184, 59)
    win.sv_type = {}
    for name, key, x, y in (('Hardcore', 'hardcore', 5, -2), ('You never died', 'died', 77, -2),
                             ('Ladder', 'ladder', 5, 17), ('Expansion', 'expansion', 77, 17)):
        var = win.sv_type[key] = tk.BooleanVar()
        role(tk.Checkbutton(fr, text=name, variable=var, padx=0, pady=0, highlightthickness=0,
                            command=lambda k=key, v=var: win.st_flag(k, v.get() != (k == 'died'))), '').place(
            x=x, y=y, height=18)

    fr = group('Miscellaneous Info.', 7, 319, 408, 108)
    for x, rows in ((7, (('Checksum', 'checksum'), ('Version', 'version'),
                          ('Initial Actual File Size', 'size'), ('Recorded File Size', 'reported_size'))),
                    (215, (('Character', 'character'), ('Character Title', 'character_title'),
                           ('Map ID', 'map_id'), ('Time Stamp', 'timestamp')))):
        for y, (name, key) in zip((1, 21, 47, 67), rows):
            label(fr, name, x, y)
            box(fr, key, x + (113 if x == 7 else 104), y, 80)


def refresh_stats(win):
    import struct
    import mxl_early_save

    ch, sim = win.ch, win.st_sim
    vals = {key: win.st_value(key) for key in win.sv if win._grey_editable(key)}
    vals.update(size=len(ch.raw), version=mxl_early_save.VERSIONS.get(ch.version,
                '1.09' if ch.old else '1.10-1.13'), header_level=sim.head[0x2B], character=sim.progression)
    flags = sim.flags()
    female = sim.cls in (0, 1, 6)
    if flags['expansion']:
        titles = ('<NONE>', 'Destroyer', 'Conqueror', 'Guardian') if flags['hardcore'] else (
            '<NONE>', 'Slayer', 'Champion', 'Matriarch' if female else 'Patriarch')
        rank = min(3, sim.progression // 5)
    else:
        titles = ('<NONE>', 'Countess', 'Duchess', 'Queen') if female else ('<NONE>', 'Count', 'Duke', 'King')
        if not flags['hardcore']:
            titles = ('<NONE>', 'Dame', 'Lady', 'Baroness') if female else ('<NONE>', 'Sir', 'Lord', 'Baron')
        rank = min(3, sim.progression // 4)
    vals['character_title'] = titles[rank]
    if not ch.early:
        size, checksum = struct.unpack_from('<II', ch.raw, 8)
        vals.update(checksum=f'{checksum:08X}', reported_size=size,
                    map_id=f'{struct.unpack_from("<I", ch.raw, 171)[0]:08X}',
                    timestamp=f'{struct.unpack_from("<I", ch.raw, 48)[0]:08X}')
    for key, control in win.sv.items():
        text = str(vals.get(key, ''))
        editable = win._grey_editable(key)
        if control.get() != text:
            control.configure(state='normal')
            control.delete(0, 'end')
            control.insert(0, text)
            if not editable:
                control.configure(state='readonly')
    win.he_town.configure(values=TOWNS if flags['expansion'] else TOWNS[:4])
    for key, var in win.sv_type.items():
        var.set(flags[key] != (key == 'died'))
    diff, town = sim.start_location()
    win.sv_diff.set(diff)
    if 0 <= town < (5 if flags['expansion'] else 4):
        win.he_town.current(town)
    else:
        win.he_town.set('')
    if win.he_level_character != ch.path:
        win.he_level_character = ch.path
        win.he_over99.set(sim.level > 99)
    update_portrait(win.he_portrait, sim.cls, win.data)


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
        panel.create_text(24, 187, text='Character Editor', fill='#e2bd74', anchor='w',
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
                       'Hold Shift to step by ten. Right-click a characteristic to spend or return a stat point.\n\n'
                       'Right-click inventory items for editing and clipboard commands.')
    info.configure(state='disabled')
    options(win)
    introductions(win)


def options(win):
    import mxl_mock_gui
    import mxl_profile

    page = win.pages['options']
    for column in range(2):
        page.columnconfigure(column, weight=1, uniform='options')
    game = ttk.LabelFrame(page, text='Diablo II game folder', padding=6)
    game.grid(row=1, column=0, sticky='nsew', padx=(0, 4))
    ttk.Button(game, text='Game folder…', command=lambda: mxl_profile.open_dialog(win.app)).pack(anchor='w')

    editing = ttk.LabelFrame(page, text='Character Editing', padding=6)
    editing.grid(row=1, column=1, sticky='nsew')
    mock_mode = mxl_mock_gui._state['var']
    if mock_mode is not None:
        ttk.Checkbutton(editing, text='Mock Mode', variable=mock_mode,
                        command=lambda: mxl_mock_gui.set_mode(mock_mode.get(), select=False)).pack(anchor='w')
    if 'quests_adv' in win.pages:
        ttk.Button(editing, text='Advanced quest words…',
                   command=lambda: set_tab(win, 'quests_adv')).pack(anchor='w')

    tools = ttk.LabelFrame(page, text='Item and Character Tools', padding=6)
    tools.grid(row=2, column=0, columnspan=2, sticky='ew', pady=4)
    ttk.Button(tools, text='Extras…', command=lambda: extras(win)).pack(anchor='w')


def introductions(win):
    """Display the NPC introduction and return-visit flags for each difficulty."""
    from mxl_char import NPC_OFF, difficulty_name

    groups = (
        ((1, 'Gheed'), (2, 'Akara'), (3, 'Kashya'), (4, 'Warriv'), (5, 'Charsi')),
        ((7, 'Warriv'), (9, 'Drognan'), (10, 'Fara'), (11, 'Lysander'), (12, 'Geglash'),
         (13, 'Meshif'), (14, 'Jerhyn'), (15, 'Greiz'), (16, 'Elzix')),
        ((18, 'Deckard Cain'), (21, 'Asheara'), (22, 'Hratli'), (23, 'Alkor'),
         (24, 'Ormus'), (27, 'Meshif'), (28, 'Natalya')),
        (),
        ((30, 'Anya'), (31, 'Malah'), (32, 'Nihlathak'), (33, 'Qual-Kehk'), (34, 'Deckard Cain')),
    )

    def refresh():
        for tree, diff, title, returning in trees:
            tree.delete(*tree.get_children())
            root = tree.insert('', 'end', text=title, open=True)
            offset = NPC_OFF + 4 + 8 * diff + 24 * returning
            bits = int.from_bytes(win.ch.head[offset:offset + 8], 'little')
            for group, (act, _intro, _quests, _travel) in zip(groups, win.ch.quest_acts()):
                node = tree.insert(root, 'end', text=act)
                for bit, name in group:
                    checked = bool(bits & (1 << bit)) != returning
                    tree.insert(node, 'end', text=f'{"☑" if checked else "☐"} {name}')

    page = win.pages['introductions']
    trees = []
    for title, travel in (('Introductions', False), ('Welcomed Back', True)):
        group = ttk.LabelFrame(page, text=title, padding=3)
        group.pack(fill='both', expand=True, pady=(0, 4))
        for diff in range(3):
            frame = ttk.LabelFrame(group, text=difficulty_name(diff), padding=3)
            frame.pack(side='left', fill='both', expand=True, padx=2)
            tree = ttk.Treeview(frame, show='tree', height=8)
            tree.column('#0', width=180, minwidth=100)
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
    frames, pal = native_frames(art, r'FrontEnd\TitleScreen.dc6', 'Sky')
    if not frames:
        return None
    width, height, rgba = compose(frames, pal, 4)
    return Image.frombytes('RGBA', (width, height), bytes(art._bright(rgba)))


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


QUEST_STAGES = ('Not Started', 'Looking For', 'Just Finished', 'Long Finished')
QUEST_STAGE_WORDS = (0, 0x0004, 0x2000)


def quest_stage(word):
    return 3 if word & 1 else 2 if word & 0x2000 else int(bool(word))


def quest_details(win, parent):
    """Build quest details and keep the existing completion and reward rules."""
    left = ttk.Frame(parent, width=336, height=434)
    left.pack(side='left', fill='y', padx=(2, 0))
    left.pack_propagate(False)
    details = ttk.LabelFrame(left, text='Quest', padding=6)
    details.pack(fill='both', expand=True)
    title = ttk.Label(details, wraplength=300, justify='left')
    title.pack(anchor='w', pady=(6, 8))
    notes = ttk.Label(details, wraplength=300, justify='left')
    notes.pack(anchor='w')
    selected = {}
    value = tk.IntVar()

    def apply():
        tree, iid = selected['tree'], selected['iid']
        if iid in tree.keys:
            apply_stage(tree, (iid,), value.get())

    def apply_stage(tree, leaves, stage):
        done = stage == 3
        updates = {}
        for leaf in leaves:
            if leaf in tree.locked:
                continue
            key = tree.keys[leaf]
            _, difficulty, word = key
            if tree.value[leaf] != done:
                win.on_tree_change(key, done)
                updates[key] = done
            raw = win.ch.quest_word(difficulty, word)
            if done or quest_stage(raw) == stage:
                win.he_quest_stages.pop((difficulty, word), None)
            else:
                win.he_quest_stages[difficulty, word] = stage
        if updates:
            tree.set_values(updates)
        win.update_dirty()
        refresh(tree)

    status = ttk.Frame(details)
    status.pack(side='bottom', fill='x')
    states = []
    for state, text in enumerate(QUEST_STAGES):
        radio = ttk.Radiobutton(status, text=text, variable=value, value=state, command=apply)
        radio.pack(anchor='w', pady=2)
        states.append(radio)

    batch = ttk.LabelFrame(left, text='Batch', padding=3)
    batch.pack(fill='x', pady=(5, 0))

    def group_root(tree, iid, scope):
        root = tree.tv.get_children()[0]
        if scope == 'all':
            return root
        if not iid or iid == root:
            return None
        node = tree.tv.parent(iid) if iid in tree.keys else iid
        parent = tree.tv.parent(node)
        if scope == 'act':
            return node if parent != root else None
        return node if parent == root else parent

    def change_group(scope, want):
        tree, iid = selected['tree'], selected['iid']
        root = group_root(tree, iid, scope)
        if root is not None:
            apply_stage(tree, tree.leaves(root), want)

    buttons = {}
    for scope, text in (('act', 'Current Act'), ('mode', 'Current Mode'), ('all', 'All Modes')):
        column = ttk.LabelFrame(batch, text=text, padding=3)
        column.pack(side='left', fill='both', expand=True, padx=1)
        mode = tk.IntVar(value=0)
        for stage, label in enumerate(QUEST_STAGES):
            ttk.Radiobutton(column, text=label, variable=mode, value=stage).pack(anchor='w', pady=3)
        button = ttk.Button(column, text='Batch', command=lambda scope=scope, mode=mode: change_group(scope, mode.get()))
        button.pack(fill='x', pady=(10, 2))
        buttons[scope] = button

    def refresh(tree):
        selection = tree.tv.selection()
        iid = selection[0] if selection else ''
        selected.update(tree=tree, iid=iid)
        key = tree.keys.get(iid)
        if key:
            _, difficulty, word = key
            act, name = win.he_quest_names[difficulty, word]
            details.configure(text=act)
            title.configure(text=name)
            raw = win.ch.quest_word(difficulty, word)
            saved_stage = quest_stage(raw)
            notes.configure(text=f'Saved status: {QUEST_STAGES[saved_stage]}')
            value.set(3 if tree.value[iid] else win.he_quest_stages.get(
                (difficulty, word), 0 if saved_stage == 3 else saved_stage))
        else:
            details.configure(text='Quest')
            title.configure(text=tree.tv.item(iid, 'text') if iid else 'Select a quest')
            notes.configure(text='')
            value.set(-1)
        for radio in states:
            radio.state(['!disabled'] if key and iid not in tree.locked else ['disabled'])
        for scope, button in buttons.items():
            button.state(['!disabled'] if group_root(tree, iid, scope) else ['disabled'])

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


def draw_pickup(win):
    from mxl_char import CharError, blob_item
    from mxl_format import FormatError

    paper = win.he_pickup
    paper.delete('all')
    paper.create_rectangle(4, 4, 72, 106, outline='#55442d')
    clip = getattr(win.app, '_capy_clip', None)
    if clip:
        try:
            item = blob_item(clip[0], win.data)
            win.draw_item(paper, item, 9, 9, 68, 102, False)
        except (CharError, FormatError, OSError):
            pass


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
