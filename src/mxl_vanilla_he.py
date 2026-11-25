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
ART_FOLDER = 'vanilla_he_folder'
ITEM_LEVEL = 'vanilla_he_item_level'
CENTER_MOUSE = 'vanilla_he_center_mouse'


def active():
    import mxl_profile
    return not mxl_profile.is_median()


def ui_scale(widget):
    """Use Tk's DPI, including the editor's UI-scale override applied at startup."""
    return max(0.5, round(widget.winfo_fpixels('1i') / 96 * 4) / 4)


def pixels(widget, *values):
    scale = ui_scale(widget)
    return tuple(round(value * scale) for value in values)


def screen_point(event):
    """Translate widget-local Tk pixels into the same pixel space used to post menus."""
    return event.widget.winfo_rootx() + event.x, event.widget.winfo_rooty() + event.y


MENU_GAP = 8


def popup(menu, event):
    x, y = screen_point(event)
    menu.update_idletasks()
    w, h = menu.winfo_reqwidth(), menu.winfo_reqheight()
    if x + MENU_GAP + w <= menu.winfo_screenwidth():
        x += MENU_GAP
    else:
        x = max(0, x - w - MENU_GAP)
    if y + MENU_GAP + h <= menu.winfo_screenheight():
        y += MENU_GAP
    else:
        y = max(0, y - h - MENU_GAP)

    root = event.widget.winfo_toplevel()
    if not getattr(menu, '_he_crossings', False):
        def leave(_event):
            px, py = menu.winfo_pointerxy()
            left, top = menu.winfo_rootx(), menu.winfo_rooty()
            if left <= px < left + menu.winfo_width() and top <= py < top + menu.winfo_height():
                return 'break'

        def unmap(_event):
            if getattr(root, '_he_posted_menu', None) is menu:
                root._he_posted_menu = None

        menu.bind('<Leave>', leave, add='+')
        menu.bind('<Unmap>', unmap, add='+')
        menu._he_crossings = True

    root._he_posted_menu = menu
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()


def picture(key):
    import settings
    from mxl_vanilla_he_assets import load

    return load(settings.get(ART_FOLDER)).get(key)


def photo(widget, artwork, size):
    from PIL import Image, ImageTk

    return ImageTk.PhotoImage(artwork.resize(size, Image.Resampling.LANCZOS), master=widget)


def choose_art_folder(win):
    from tkinter import filedialog, messagebox
    import settings
    from mxl_vanilla_he_assets import load

    current = settings.get(ART_FOLDER)
    folder = filedialog.askdirectory(parent=win.top, title='Hero Editor folder...', initialdir=current or None)
    if folder:
        if not {'splash', 'about', 'person'} <= load(folder).keys():
            messagebox.showerror('Hero Editor artwork', 'Choose a folder containing Hero Editor 1.04.',
                                 parent=win.top)
            return
        set_art_folder(win, folder)


def set_art_folder(win, folder):
    import settings
    from mxl_char import INV_W, INV_H

    settings.put(ART_FOLDER, folder)
    for button in win.he_action_buttons:
        caption = button.cget('text')
        button.images = [action_plaque(button, caption, shade) for shade in (0, 12, -5)]
        button.configure(image=button.images[0])
    for key, panel in win.he_covers.items():
        draw_cover(panel, key)
    win.he_refresh_quest()
    merc = win.extra.get('merc')
    if merc is not None:
        merc.refresh_portrait()
    win.he_portrait._he_class = None
    refresh_stats(win)
    win.he_inventory_art = inventory_images(win.inv, INV_W, INV_H, win.cell, win.he_footer_height)
    page = win.extra.get('containers')
    if page is not None:
        page._sig = None
        page.refresh()
    win.redraw()


def font(spec=FONT):
    from mxl_he_theme import families
    installed = families()
    family = next((name for name in ('Tahoma', 'MS Sans Serif', 'Liberation Sans', 'DejaVu Sans')
                   if name.lower() in installed), spec[0])
    return (family, *spec[1:])


def style(root):
    px = lambda n: pixels(root, n)[0]
    st = ttk.Style(root)
    st.theme_use('clam')
    st.configure('.', background=FORM, foreground=BLACK, fieldbackground=WHITE, selectbackground=SELECT,
                 selectforeground=WHITE, bordercolor=EDGE, lightcolor=WHITE, darkcolor=INSET, font=font())
    st.map('.', foreground=[('disabled', DESCRIPTION)])
    st.configure('TButton', padding=pixels(root, 5, 1), relief='raised')
    st.configure('Inventory.TButton', padding=pixels(root, 3, 0))
    st.configure('TNotebook.Tab', padding=pixels(root, 6, 1))
    st.map('TNotebook.Tab', background=[('selected', FORM), ('!selected', LIGHT)])
    st.configure('TNotebook', tabmargins=(0, 0, 0, 0))
    st.layout('CharacterHost.TNotebook.Tab', [('null', {'sticky': 'nswe'})])
    st.configure('CharacterHost.TNotebook.Tab', padding=0)
    st.layout('CharacterHost.TNotebook', [('Notebook.client', {'sticky': 'nswe'})])
    st.configure('Extras.TNotebook', tabposition='sw')
    st.configure('Extras.TNotebook.Tab', padding=pixels(root, 9, 2), width=23)
    st.map('Extras.TNotebook.Tab', font=[('selected', (*font(), 'bold'))])
    st.configure('TScrollbar', arrowsize=px(12), width=px(12), troughcolor=LIGHT)
    st.configure('Treeview', rowheight=px(16))
    st.map('Treeview', background=[('selected', SELECT)], foreground=[('selected', WHITE)])
    st.map('TCombobox', fieldbackground=[('readonly', WHITE)])
    st.configure('Peach.TFrame', background=PEACH)
    st.configure('Peach.TLabel', background=PEACH)
    st.configure('HexTitle.TLabel', background=PEACH, foreground=HEX_TITLE)
    st.configure('Peach.TLabelframe', background=PEACH)
    st.configure('Peach.TLabelframe.Label', background=PEACH, font=font(LEGEND_FONT))
    st.configure('TLabelframe.Label', font=font(LEGEND_FONT))
    st.configure('TEntry', padding=px(1))
    st.configure('TCombobox', padding=px(1), arrowsize=px(12))
    st.configure('TSpinbox', padding=px(1), arrowsize=px(12))
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
        previous = win.app.char_combo.get()
        if name == previous:
            dialog.destroy()
            win.discard()
            report_open_issues(win)
            return
        win.app.char_combo.set(name)
        if not check_open_version(win, win.app.character_file()):
            win.app.char_combo.set(previous)
            return
        dialog.destroy()
        if win.dirty():
            win.discard()
        win.app.select_character(name, win.app.view.get())
        from mxl_char_gui import CharacterWindow
        from mxl_tabs import built_owner

        CharacterWindow(win.app)
        opened = built_owner('Character')
        if opened is not None and hasattr(opened, 'ch'):
            report_open_issues(opened)

    buttons = ttk.Frame(dialog)
    buttons.pack(fill='x', padx=8, pady=6)
    ttk.Button(buttons, text='Open', command=open_selected).pack(side='right')
    ttk.Button(buttons, text='Cancel', command=dialog.destroy).pack(side='right', padx=4)
    names.bind('<Double-Button-1>', open_selected)
    dialog.bind('<Return>', open_selected)
    dialog.bind('<Escape>', lambda _event: dialog.destroy())
    names.focus_set()
    center_mouse(dialog)


def check_open_version(win, path):
    import struct
    from mxl_char import MAGIC
    from mxl_newchar import SAVE_VERSIONS
    from tkinter import messagebox

    if not path:
        return True
    try:
        with open(path, 'rb') as file:
            signature, version = struct.unpack('<II', file.read(8))
    except (OSError, struct.error):
        return True
    if signature != MAGIC or version in SAVE_VERSIONS:
        return True
    text = f'This character uses unsupported save version {version}.'
    if option('version_warning', 'show') == 'show':
        messagebox.showwarning('Save version', text, parent=win.top)
    win.set_status(text, True)
    return False


def report_open_issues(win):
    import struct
    from mxl_char import checksum
    from mxl_creator import decode_blob
    from mxl_vanilla_he_items import ITEM_ERRORS, extras_entries
    from tkinter import messagebox

    issues = []
    raw = win.ch.raw
    response = option('error_response', 'normal')
    if option('header_checks', 'verify') == 'verify' and not win.ch.early:
        size, saved_checksum = struct.unpack_from('<II', raw, 8)
        if size != len(raw):
            issues.append(f'Recorded size is {size} bytes. The file contains {len(raw)} bytes.')
        if checksum(raw) != saved_checksum:
            issues.append('The character checksum does not match the file.')
    if option('decode_check', 'complete') == 'complete':
        for entry, _owner in extras_entries(win.ch):
            try:
                decode_blob(entry.blob, win.data)
            except ITEM_ERRORS as error:
                issues.append(f'{entry.it.get("code", "?").strip()} — {error}')
    if issues:
        win.set_status(f'Open found {len(issues)} issues.', True)
        if response == 'inspect':
            extras(win)
        elif response == 'normal':
            messagebox.showwarning('Open Character', '\n'.join(issues), parent=win.top)


def center_mouse(window):
    import settings

    if settings.get(CENTER_MOUSE):
        window.update_idletasks()
        window.event_generate('<Motion>', warp=True,
                              x=window.winfo_width() // 2, y=window.winfo_height() // 2)


def action_plaque(parent, caption, shade):
    """Draw an original stone plaque with riveted brass trim."""
    import random
    from PIL import Image, ImageDraw, ImageFont, ImageTk

    original = picture(f'button_{caption}_{shade}')
    if original is not None:
        im = Image.new('RGB', (96, 34), BLACK)
        im.paste(original, (1, 1))
        return photo(parent, im, pixels(parent, 96, 34))
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
    return ImageTk.PhotoImage(im.resize(pixels(parent, 96, 34), Image.Resampling.LANCZOS), master=parent)


def chrome(win, bottom, actions):
    """Build the character action strip, status cells and tools menu."""
    commands = (lambda: choose_character(win), win.save_progress, win.discard,
                lambda: extras(win), win.close)
    actions.pack_configure(padx=0, pady=0)
    buttons = []
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
        buttons.append(button)
    win.he_action_buttons = buttons
    wrap_buttons(actions, buttons, gap=4, pady=5, positions=(8, 112, 216, 384, 552))
    status = tk.Frame(bottom, bg=FORM, height=pixels(bottom, 22)[0])
    status.pack(fill='x')
    status.pack_propagate(False)
    for label, width in (('Hero Editor', 70), ('Version 1.04', 108)):
        cell = tk.Frame(status, width=pixels(status, width)[0])
        cell.pack(side='left', fill='y')
        cell.pack_propagate(False)
        tk.Label(cell, text=label, anchor='w', bd=1, relief='sunken',
                 font=font(), bg=FORM, padx=1).pack(fill='both', expand=True)
    win.bar_status = role(tk.Label(status, text='Character Open: ' + win.ch.path, anchor='w',
                              bd=1, relief='sunken', font=font(), bg=FORM), 'art')
    win.bar_status.pack(side='left', fill='both', expand=True)
    bar = role(tk.Frame(win.top, bg=WHITE, height=pixels(win.top, 20)[0]), 'art')
    bar.pack(side='top', fill='x')
    bar.pack_propagate(False)
    entry = role(tk.Menubutton(bar, text='Menu', underline=0, font=font(), bd=0,
                              bg=WHITE, activebackground=SELECT, activeforeground=WHITE), 'menu')
    entry.pack(side='left', padx=3, ipady=1)
    menu = win.he_menu = tk.Menu(entry, tearoff=False)
    entry.configure(menu=menu)
    from mxl_rc_menu import _vanilla_char_commands

    _vanilla_char_commands(win, menu, None, None, extensions=False)
    prefix = menu.index('end') + 1
    menu.add_separator()
    for text, command in zip(ACTIONS, commands):
        menu.add_command(label=text.title(), underline=0, command=command)

    import mxl_mock_gui
    import mxl_tabs

    from tkinter import simpledialog

    def ask(caption, value, limits=None):
        if limits is None:
            from mxl_char import ask_name

            name = ask_name(caption, 'Character name', parent=win.top)
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

    if mock_mode is not None:
        menu.configure(postcommand=lambda: menu.entryconfigure(
            mock_tools_index, state='normal' if mock_mode.get() else 'disabled'))
    menu.add_command(label='Hero Editor folder...', command=lambda: choose_art_folder(win))
    menu.add_command(label='Use drawn Hero Editor art', command=lambda: set_art_folder(win, ''))
    add_toolbar_menu(win.app, menu)

    previous = menu.cget('postcommand')
    template = tk.Menu(entry, tearoff=False)      # one scratch menu for the whole window: its commands stay alive

    def update_item_commands():
        if previous:
            menu.tk.call(previous)
        win.sync_file()
        selected = win.selected
        if selected is not None:
            selected = win.current_entry(selected, False) or win.current_entry(selected, True)
        old_children = list(template.winfo_children())
        old_commands = list(template._tclCommands or ())
        template.tk.call(str(template), 'delete', 0, 'end')    # raw: Tkinter's delete trips on an empty menu
        _vanilla_char_commands(win, template, selected, getattr(win.app, '_capy_clip', None), extensions=False)
        options = []
        for index in range(prefix):
            options.append((template.type(index),
                            {key: info[-1] for key, info in template.entryconfigure(index).items()}))
        menu.tk.call(str(menu), 'delete', 0, prefix - 1)
        for index, (kind, opts) in enumerate(options):
            menu.insert(index, kind, **opts)
        for child in old_children:               # the previous build: no entry points at it any more
            try:
                child.destroy()
            except tk.TclError:
                pass
        for name in old_commands:
            try:
                template.deletecommand(name)
            except (tk.TclError, ValueError):
                pass

    menu.configure(postcommand=update_item_commands)


def add_toolbar_menu(app, menu):
    toolbar = getattr(app, 'toolbar', None)
    if toolbar is None:
        return
    from mxl_lang import T

    menu.add_separator()
    # This suffix is rebuilt when posted so it reflects the live toolbar and its choices.
    first = menu.index('end') + 1
    previous = menu.cget('postcommand')
    fixed_children = set(menu.winfo_children())

    def refresh():
        if previous:
            menu.tk.call(previous)
        if menu.index('end') >= first:
            menu.delete(first, 'end')
        for child in menu.winfo_children():
            if child not in fixed_children:
                child.destroy()
        toolbar.populate_menu(menu, include_extra=False)
        more = tk.Menu(menu, tearoff=False, font=font())
        toolbar.populate_extra(more)
        if more.index('end') is not None:
            menu.add_cascade(label=T('bar.more', 'More'), menu=more)
        else:
            more.destroy()

    menu.configure(postcommand=refresh)
    refresh()


def wrap_buttons(bar, buttons, gap=0, pady=0, positions=()):
    """Wrap the bottom controls when the viewport is narrower than their requests."""
    gap, pady = pixels(bar, gap, pady)
    positions = pixels(bar, *positions)
    positioned_height = pixels(bar, 45)[0]
    rows = []
    current = None

    def layout(event):
        nonlocal current
        if event.width < 2:
            return
        if positions and event.width >= positions[-1] + buttons[-1].winfo_reqwidth():
            if current == positions:
                return
            for row in rows:
                row.destroy()
            rows.clear()
            for button, x in zip(buttons, positions):
                button.pack_forget()
                button.place(x=x, y=pady)
            current = positions
            bar.configure(height=positioned_height)
            return
        groups = [[]]
        used = 0
        for button in buttons:
            width = button.winfo_reqwidth() + 2 * gap
            if used + width > event.width and groups[-1]:
                groups.append([])
                used = 0
            groups[-1].append(button)
            used += width
        if groups == current:
            return
        current = groups
        for button in buttons:
            button.place_forget()
            button.pack_forget()
        for row in rows:
            row.destroy()
        rows.clear()
        for group in groups:
            row = role(tk.Frame(bar, bg=bar.cget('bg')), 'art')
            row.pack(anchor='w')
            rows.append(row)
            for button in group:
                button.pack(in_=row, side='left', padx=gap, pady=pady)
                button.lift(row)

    # Seed a request so a packed bar receives its first Configure event.
    bar.configure(height=positioned_height if positions else pixels(bar, 20)[0])
    bar.bind('<Configure>', layout, add='+')


def extras(win, entry=None, group='Basic1'):
    from mxl_vanilla_he_extras import open_extras

    if active():
        return open_extras(win, entry, group)


TOWNS = ('Rogue Encampment', 'Lut Gholein', 'Kurast Docks', 'Pandemonium Fortress', 'Harrogath')


def stats(win, page, entry):
    """Center the scaled stats form in its scrollable page."""
    page = tk.Frame(page)
    page.configure(width=pixels(page, 644)[0], height=pixels(page, 440)[0])
    page.pack(expand=True)

    def place(widget, *, x, y, width=None, height):
        x, y, w, h = pixels(page, x, y, width or 0, height)
        widget.place(x=x, y=y, width=w if width is not None else None, height=h)
    win.he_portrait = character_portrait(page)
    place(win.he_portrait, x=2, y=4, width=209, height=435)
    form = tk.Frame(page, bd=1, relief='sunken')
    place(form, x=218, y=4, width=424, height=435)

    def group(caption, x, y, w, h):
        frame = role(tk.LabelFrame(form, text=caption, bd=1, relief='groove'), '')
        place(frame, x=x, y=y, width=w, height=h)
        return frame

    def label(parent, text, x, y):
        place(role(tk.Label(parent, text=text, padx=0, pady=0), ''), x=x, y=y, height=18)

    def box(parent, key, x, y, w):
        control = entry(parent, key, 1)
        place(control, x=x, y=y, width=w, height=18)
        return control

    def button(parent, text, command, x, y, w):
        place(role(tk.Button(parent, text=text, command=command, pady=0, padx=0), ''),
            x=x, y=y, width=w, height=18)

    def rename():
        from mxl_char import ask_name

        name = ask_name('Rename Character', 'New name', initialvalue=win.st_value('name'), parent=win.top)
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
    place(cb, x=108, y=0, height=18)

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
    label(form, 'Checksum, sizes and title are worked out', 17, 300)

    fr = group('Class', 231, 0, 184, 44)
    win.class_box = ttk.Combobox(fr, state='readonly', textvariable=win.new_class, values=win.class_names,
                                font=font())
    place(win.class_box, x=7, y=2, width=168, height=21)
    win.class_box.bind('<<ComboboxSelected>>', lambda _event: win.on_class_change())

    from mxl_char import difficulty_name
    fr = group('Character Difficulty', 231, 46, 184, 35)
    win.sv_diff = tk.IntVar()
    for i, x in enumerate((5, 62, 135)):
        radio = role(tk.Radiobutton(fr, text=difficulty_name(i), value=i, variable=win.sv_diff, padx=0, pady=0,
                                   highlightthickness=0,
                                   command=lambda i=i: win.st_do('start_difficulty', i)), '')
        place(radio, x=x, y=-2, height=18)
        if win.ch.early:
            radio.configure(state='disabled')

    fr = group('Starting Town', 231, 83, 184, 42)
    win.he_town = ttk.Combobox(fr, state='disabled' if win.ch.early else 'readonly', values=TOWNS, font=font())
    place(win.he_town, x=7, y=0, width=168, height=21)
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
            control.bind('<Button-3>', lambda event, menu=menu: popup(menu, event))

    fr = group('Character Type', 231, 265, 184, 59)
    win.sv_type = {}
    for name, key, x, y in (('Hardcore', 'hardcore', 5, -2), ('You never died', 'died', 77, -2),
                             ('Ladder', 'ladder', 5, 17), ('Expansion', 'expansion', 77, 17)):
        var = win.sv_type[key] = tk.BooleanVar()
        place(role(tk.Checkbutton(fr, text=name, variable=var, padx=0, pady=0, highlightthickness=0,
                            command=lambda k=key, v=var: win.st_flag(k, v.get() != (k == 'died'))), ''),
            x=x, y=y, height=18)

    fr = group('Miscellaneous Info.', 7, 319, 408, 108)
    for x, rows in ((7, (('Checksum', 'checksum'), ('Version', 'version'),
                          ('Initial Actual File Size', 'size'), ('Recorded File Size', 'reported_size'))),
                    (215, (('Character', 'character'), ('Character Title', 'character_title'),
                           ('Map ID', 'map_id'), ('Time Stamp', 'timestamp')))):
        for y, (name, key) in zip((1, 21, 47, 67), rows):
            label(fr, name, x, y)
            box(fr, key, x + (113 if x == 7 else 104), y, 80)


def character_title(ch):
    flags = ch.flags()
    female = ch.cls in (0, 1, 6)
    if flags['expansion']:
        titles = ('<NONE>', 'Destroyer', 'Conqueror', 'Guardian') if flags['hardcore'] else (
            '<NONE>', 'Slayer', 'Champion', 'Matriarch' if female else 'Patriarch')
        rank = min(3, ch.progression // 5)
    else:
        titles = ('<NONE>', 'Countess', 'Duchess', 'Queen') if female else ('<NONE>', 'Count', 'Duke', 'King')
        if not flags['hardcore']:
            titles = ('<NONE>', 'Dame', 'Lady', 'Baroness') if female else ('<NONE>', 'Sir', 'Lord', 'Baron')
        rank = min(3, ch.progression // 4)
    return titles[rank]


def refresh_stats(win):
    import struct
    import mxl_early_save

    ch, sim = win.ch, win.st_sim
    vals = {key: win.st_value(key) for key in win.sv if win._grey_editable(key)}
    vals.update(size=len(ch.raw), version=mxl_early_save.VERSIONS.get(ch.version,
                '1.09' if ch.old else '1.10-1.13'), header_level=sim.head[0x2B], character=sim.progression)
    flags = sim.flags()
    vals['character_title'] = character_title(sim)
    if not ch.early:
        size, checksum = struct.unpack_from('<II', ch.raw, 8)
        vals.update(checksum=f'{checksum:08X}', reported_size=size,
                    map_id=win.st_value('map_id'), timestamp=win.st_value('timestamp'))
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
    win.he_covers = {}
    for key in ('splash', 'about'):
        width, height = pixels(win.top, 640, 435)
        panel = tk.Canvas(win.pages[key], width=width, height=height, bg=BLACK, bd=0, highlightthickness=0)
        panel.pack(expand=True)
        panel.bind('<Configure>', lambda event, key=key: draw_cover(event.widget, key))
        win.he_covers[key] = panel
        draw_cover(panel, key)
    bind_inventory(win)
    page = ttk.Frame(win.pages['info'])
    page.pack(fill='both', expand=True, padx=pixels(page, 4)[0], pady=pixels(page, 7)[0])
    info = role(tk.Text(page, wrap='word', width=65, height=22, bg=PEACH,
                        font=font(DOC_FONT), relief='sunken', bd=2, padx=1, pady=1), 'document')
    scroll = ttk.Scrollbar(page, command=info.yview)
    scroll.pack(side='right', fill='y')
    info.configure(yscrollcommand=scroll.set)
    info.pack(side='left', fill='both', expand=True)
    info.insert('1.0', 'Open a Diablo II character to view or edit its stats, inventory, skills, '
                       'waypoints, quests and mercenary.\n\n'
                       'Use Save to write pending character changes and Reload to read the character again. '
                       'Finish a field with Enter. Up and Down step the selected value. '
                       'Hold Shift to step by ten. Right-click a characteristic to spend or return a stat point.\n\n'
                       'Inventory: Right-click an item for editing, import, export and clipboard commands. '
                       'Switch between Person, Stash, Cube and Merc / Belt using the vertical tabs. '
                       'Use Up and Down to scroll a hovered item’s description.\n\n'
                       'Skills: Select a skill tile to edit one skill, or use Set Skills to change the group.\n\n'
                       'Waypoints and Quests: Expand a difficulty or act to see its entries. Select a quest '
                       'to view its flags or apply a status to an act or difficulty.\n\n'
                       'Extras: Inspect character bytes, compare item data, edit item attributes, and create '
                       'items or characters.\n\n'
                       'Use Menu → Hero Editor folder to load art from a local Hero Editor 1.04 installation.')
    info.configure(state='disabled')
    options(win)
    introductions(win)


def anchored_event(event):
    event.x_root, event.y_root = screen_point(event)
    return event


def bind_inventory(win):
    """Use canvas-local pointer events for vanilla menus, drags and shortcuts."""
    from weakref import ref
    import mxl_rc_menu as rc

    root = win.top.winfo_toplevel()
    root._he_window = ref(win)
    redraw = win.redraw

    def redraw_inventory():
        redraw()
        draw_mercenary_background(win)

    win.redraw = redraw_inventory
    if not getattr(root, '_he_clipboard_bound', False):
        for keys, paste in (('c', False), ('C', False), ('v', True), ('V', True)):
            sequence = f'<Control-KeyPress-{keys}>'
            previous = root.bind(sequence)
            root.bind(sequence, lambda event, paste=paste: inventory_clipboard(root, event, paste))
            # A vanilla canvas consumes the key before the shared, pointer-based shortcut.
            root.tk.call('bind', root._w, sequence, root.bind(sequence) + '\n' + previous)
        for key, caption in (
            ('<Control-g>', 'General Edit of Item (in Extras Window)'),
            ('<Control-a>', 'Add All Item Magic Attributes TO Buffer'),
            ('<Control-p>', 'VIEW what is in Buffer'),
            ('<Control-b>', 'DELETE Buffer'),
            ('<Control-e>', 'Export Item to File…'),
            ('<Control-i>', 'Import Item from File…'),
            ('<Control-x>', 'Cut Item (move to Picked Up)'),
            ('<Control-z>', 'Fill Item Sockets (copy of Picked Up)'),
            ('<F1>', 'Help'),
        ):
            previous = root.bind(key)
            root.bind(key, lambda event, caption=caption: inventory_shortcut(root, event, caption))
            root.tk.call('bind', root._w, key, root.bind(key) + '\n' + previous)
        for key, step in (('<Up>', -1), ('<Down>', 1)):
            previous = root.bind(key)
            root.bind(key, lambda event, step=step: scroll_hovered_description(root, event, step))
            root.tk.call('bind', root._w, key, root.bind(key) + '\n' + previous)
        root._he_clipboard_bound = True

    def remember(event):
        win.he_pointer = event.widget, screen_point(event)

    def forget(event):
        if (getattr(win, 'he_pointer', None) or (None,))[0] is event.widget:
            win.he_pointer = None

    hint = win.he_item_hint = item_hint(win.top)
    hovered = None

    def clear_hint(event):
        nonlocal hovered
        if hint.owner is event.widget:
            hint.hide()
            hint.owner = None
            hovered = None
            win.inventory_description(False)

    def track(cv, lookup, expanded=False, dragging=lambda: win.drag):
        def hover(event):
            nonlocal hovered
            menu = getattr(root, '_he_posted_menu', None)
            if menu is not None and menu.winfo_exists() and menu.winfo_ismapped():
                return
            remember(event)
            if dragging() is not None:
                return
            entry = lookup(event)
            if entry is None:
                clear_hint(event)
                return
            if hovered is not entry or hint.owner is not cv:
                item = decoded_item(win, entry)
                if item is None:
                    win.panel.show(None)
                    clear_hint(event)
                    return
                win.panel.show(description_item(item))
                win.inventory_description(expanded)
                hovered = entry
            hint.show(cv, key=id(entry))

        def leave(event):
            if not hint._pointer_in(cv):
                forget(event)
            if hint.owner is cv:
                hint.leave(cv)

        for sequence in ('<Enter>', '<Motion>'):
            cv.bind(sequence, hover)
        for sequence in ('<ButtonPress-1>', '<ButtonRelease-1>', '<ButtonRelease-3>'):
            cv.bind(sequence, remember, add='+')
        for sequence in ('<ButtonPress-1>', '<ButtonPress-3>', '<Unmap>'):
            cv.bind(sequence, clear_hint, add='+')
        cv.bind('<Leave>', leave, add='+')

    def hint_hidden():
        nonlocal hovered
        hovered = None
        win.inventory_description(False)

    hint.on_hide = hint_hidden
    bind_pickup(win)
    for cv in (win.inv, win.doll):
        cv.bind('<ButtonRelease-3>', lambda event: rc._char_menu(win, event.widget, anchored_event(event)))
        cv.bind('<ButtonRelease-1>', lambda event: win.on_release(anchored_event(event)))
        track(cv, lambda event: win.entry_at(event.widget, event)[0], expanded=cv is win.doll)

    page = win.extra.get('containers')
    if page is None:
        return
    build = page._build
    fallback = page._art_for

    def rebuild(boxes):
        build(boxes)
        for key, cv in page.canvases.items():
            cv.bind('<Button-1>', lambda event, key=key: page.on_press(key, anchored_event(event)))
            cv.bind('<ButtonRelease-1>', lambda event: page.on_release(anchored_event(event)))
            cv.bind('<ButtonRelease-3>', lambda event, key=key: page.on_menu(key, anchored_event(event)))
            track(cv, lambda event, key=key: page.entry_at(key, event.x, event.y),
                  expanded=key in ('stash', 'cube', 'belt'), dragging=lambda: page.drag)

    page._art_for = lambda key, columns, rows: container_picture(key, columns, rows) or fallback(key, columns, rows)
    page._build = rebuild
    page._sig = None
    page.refresh()


def scroll_hovered_description(root, event, step):
    win = root._he_window()
    if win is None or not win.preview.winfo_ismapped() or not win.he_item_hint.shown:
        return
    if event.widget.winfo_class() in ('Entry', 'Text', 'Spinbox', 'Combobox', 'TEntry', 'TCombobox', 'TSpinbox'):
        return
    win.preview.yview_scroll(step, 'units')
    return 'break'


def inventory_shortcut(root, event, caption):
    from types import SimpleNamespace
    from mxl_rc_menu import _vanilla_char_commands

    win = root._he_window()
    if win is None or not win.top.winfo_ismapped():
        return
    if event.widget.winfo_class() in ('Entry', 'Text', 'Spinbox', 'Combobox', 'TEntry', 'TCombobox', 'TSpinbox'):
        return
    pointer = getattr(win, 'he_pointer', None)
    if caption == 'Help':
        set_tab(win, 'info')
        return 'break'
    if pointer is None or not pointer[0].winfo_exists() or not pointer[0].winfo_ismapped():
        return
    if not allows(win, 'transfer'):
        return 'break'
    cv = pointer[0]
    xy = clipboard_point(pointer)
    if xy is None:
        return
    win.sync_file()
    if not cv.winfo_exists():
        return
    position = SimpleNamespace(widget=cv, x=xy[0], y=xy[1])
    owner = win
    delete = None
    if cv in (win.inv, win.doll):
        item, slot = win.entry_at(cv, position)
        win.sel_slot = slot
    else:
        containers = win.extra.get('containers')
        if containers is None:
            return
        owner = containers.as_win()
        item, _slot = owner.entry_at(cv, position)
        delete = lambda: containers.delete(item)
    win.selected = item
    menu = tk.Menu(win.top, tearoff=False)
    try:
        _vanilla_char_commands(owner, menu, item, getattr(win.app, '_capy_clip', None),
                               delete=delete, extensions=False)
        if menu.entrycget(caption, 'state') == 'normal':
            menu.invoke(caption)
            return 'break'
    finally:
        menu.destroy()


def clipboard_point(pointer):
    """Rebase the last observed pointer after a page or canvas moves."""
    cv, (sx, sy) = pointer
    x, y = sx - cv.winfo_rootx(), sy - cv.winfo_rooty()
    if 0 <= x < cv.winfo_width() and 0 <= y < cv.winfo_height():
        return x, y


def paste_at(win, canvas, xy, clip):
    from types import SimpleNamespace
    import mxl_rc_menu as rc
    from mxl_vanilla_he_items import paste_belt, paste_one

    if not allows(win, 'transfer'):
        return
    win.sync_file()
    if not canvas.winfo_exists():
        return
    point = SimpleNamespace(widget=canvas, x=xy[0], y=xy[1])
    if canvas in (win.inv, win.doll):
        entry, slot = win.entry_at(canvas, point)
        if entry is not None:
            paste_one(win, entry, clip, lambda: rc._char_paste_over(win, entry, clip))
        elif canvas is win.inv and not win.is_merc():
            rc._char_paste(win, point, clip)
        elif slot is not None:
            rc._char_paste_slot(win, slot, clip)
    else:
        page = win.extra.get('containers')
        if page is None:
            return
        key = next((key for key, candidate in page.canvases.items() if candidate is canvas), None)
        if key is None:
            return
        cell = tuple(value // page.cell for value in xy)
        if key == 'belt':
            paste_belt(win, cell, clip)
            return
        entry = page.entry_at(key, *xy)
        if entry is not None:
            paste_one(page.as_win(), entry, clip, lambda: page.paste_over(entry, clip))
        else:
            page.paste_here(key, cell, clip)


def bind_pickup(win):
    paper = win.he_pickup
    dragged = False

    def start(_event):
        nonlocal dragged
        dragged = False

    def motion(_event):
        nonlocal dragged
        if allows(win, 'transfer') and getattr(win.app, '_capy_clip', None):
            dragged = True
            paper.configure(cursor='fleur')

    def drop(event):
        paper.configure(cursor='')
        if not dragged:
            return
        clip = getattr(win.app, '_capy_clip', None)
        if clip is None:
            return
        page = win.extra.get('containers')
        grids = tuple(page.canvases.values()) if page is not None else ()
        for canvas in (win.doll, win.inv, *grids):
            if canvas.winfo_ismapped() and (point := clipboard_point((canvas, screen_point(event)))) is not None:
                paste_at(win, canvas, point, clip)
                return

    paper.bind('<ButtonPress-1>', start)
    paper.bind('<B1-Motion>', motion)
    paper.bind('<ButtonRelease-1>', drop)


def inventory_clipboard(root, event, paste):
    from types import SimpleNamespace
    import mxl_rc_menu as rc

    win = root._he_window()
    pointer = getattr(win, 'he_pointer', None)
    if pointer is None or not pointer[0].winfo_exists() or not pointer[0].winfo_ismapped():
        return
    cv = pointer[0]
    xy = clipboard_point(pointer)
    if xy is None:
        return
    if event.widget.winfo_class() in ('Entry', 'Text', 'Spinbox', 'Combobox', 'TEntry', 'TCombobox', 'TSpinbox'):
        return 'break'
    point = SimpleNamespace(widget=cv, x=xy[0], y=xy[1])
    rc._sync(win)
    if not cv.winfo_exists():
        return 'break'
    clip = getattr(win.app, '_capy_clip', None)
    if paste:
        if clip is not None:
            paste_at(win, cv, xy, clip)
        else:
            win.set_status(rc.rc('hot.noclip', 'the item clipboard is empty (copy an item first)'), True)
    elif cv in (win.inv, win.doll):
        entry, _slot = win.entry_at(cv, point)
        if entry is not None:
            win.selected = entry
            rc._char_copy(win, entry)
        else:
            win.set_status(rc.rc('hot.none', 'no item under the mouse cursor'), True)
    else:
        page = win.extra.get('containers')
        if page is not None:
            key = next((key for key, canvas in page.canvases.items() if canvas is cv), None)
            entry = page.entry_at(key, *xy) if key is not None else None
            if entry is not None:
                win.selected = entry
                rc._char_copy(page.as_win(), entry)
    return 'break'


def draw_mercenary_background(win):
    from mxl_vanilla_pages import NATIVE_GRID

    cv = win.doll
    original = picture('merc') if win.inv_view.get() == 'merc' else None
    if original is None:
        cv.configure(height=pixels(cv, NATIVE_GRID[1])[0])
        return
    top = 184
    size = pixels(cv, original.width, top)
    cv.configure(height=size[1])
    if getattr(cv, '_he_merc_source', None) is not original:
        cv._he_merc_source = original
        cv._he_merc_art = photo(cv, original.crop((0, 0, original.width, top)), size)
    if win.is_merc():
        for item in cv.find_all():
            if cv.type(item) == 'rectangle' and cv.itemcget(item, 'fill') == '#29231c':
                cv.itemconfigure(item, fill='', outline='' if cv.itemcget(item, 'width') == '1.0' else '#d4b062')
    else:
        cv.delete('all')
        win.inv.configure(height=1)
        win.he_inventory_footer.configure(height=1)
    cv.tag_lower(cv.create_image(0, 0, anchor='nw', image=cv._he_merc_art))


def container_picture(key, columns, rows):
    name, x, y, top, shape = {
        'stash': ('stash', 74, 83, 0, (6, 8)),
        'cube': ('cube', 117, 138, 0, (3, 4)),
        'belt': ('merc', 102, 253, 184, (4, 4)),
    }.get(key, (None, 0, 0, 0, (0, 0)))
    if key == 'belt' and columns == 4 and 1 <= rows <= 4:
        y += (4 - rows) * 29
    elif (columns, rows) != shape:
        return None
    from mxl_vanilla_he_assets import panel_source

    artwork = picture(name)
    if artwork is not None:
        return panel_source(artwork, top), (x, y - top), (artwork.width, artwork.height - top), 29


def draw_cover(panel, key):
    panel.delete('all')
    width = panel.winfo_width()
    height = panel.winfo_height()
    if width <= 1 or height <= 1:
        width, height = pixels(panel, 640, 435)
    edge = pixels(panel, 1)[0]
    panel.create_rectangle(0, 0, width - 1, height - 1, outline=EDGE, width=edge)
    original = picture(key)
    artwork = original if original is not None else splash_image()
    if artwork is not None:
        panel.artwork = photo(panel, artwork, (width - 2 * edge, height - 2 * edge))
        panel.create_image(edge, edge, anchor='nw', image=panel.artwork)
    else:
        panel.create_text(*pixels(panel, 24, 142), text='Diablo II', fill='#c89b52', anchor='w',
                          font=('Times New Roman', 34, 'bold'))
    if original is None:
        panel.create_text(*pixels(panel, 24, 187), text='Character Editor', fill='#e2bd74', anchor='w',
                          font=('Times New Roman', 25, 'bold'))
        panel.create_text(*pixels(panel, 26, 226), text='Diablo II · Lord of Destruction', fill='#bdd8e0',
                          anchor='w', font=font(LEGEND_FONT))
    if key == 'about':
        panel.create_rectangle(*pixels(panel, 8, 8, 324, 151), fill=BLACK, outline='')
        panel.create_text(*pixels(panel, 166, 20), anchor='n', justify='center', fill=WHITE, font=font(),
                          text='Diablo II Character Editor\n\nHero Editor 1.04\n'
                               'ZonFire99 and Mastadex\n\nDiablo II and Lord of Destruction\n'
                               'Blizzard Entertainment\n\nMXL Capybara Editor V2')


def option(key, default=None):
    import settings

    value = settings.get('vanilla_he_' + key)
    return default if value is None else value


def allows(win, operation):
    if not getattr(win, 'vanilla_he', False):
        return True
    if operation in ('character', 'header'):
        mode = option('character_access', 'all')
        return mode == 'all' or mode == 'stats' and operation == 'character'
    mode = option('item_access', 'all')
    return mode == 'all' or mode == 'transfer' and operation == 'transfer'


def description_item(item):
    if item is None or not active():
        return item
    bonuses = [stat for index in range(5) for stat in item.get(f'set_stats_{index}', ())]
    show_fill = bool(item.get('has_sockets'))
    if not bonuses and not show_fill:
        return item
    result = item.copy()
    if show_fill:
        result['_show_socket_fill'] = True
    if bonuses and option('set_attributes', 'show') == 'show':
        result['stats'] = [*item.get('stats', ()), *bonuses]
    for index in range(5):
        result.pop(f'set_stats_{index}', None)
    return result


def picture_item(item):
    if not active() or item.get('quality') not in ('unique', 7) or option('unique_pictures', 'show') == 'show':
        return item
    from copy import copy

    result = copy(item)
    result.pop('set_unique_id', None)
    return result


ITEM_DECODE_VERSIONS = {
    71: '1.03', 87: '1.07', 92: '1.09D', 95: '1.10s beta', 96: '1.10–1.13',
}


def decode_version(version):
    return 87 if version == 89 else version


def next_decode_version(version):
    versions = tuple(ITEM_DECODE_VERSIONS)
    return versions[(versions.index(decode_version(version)) + 1) % len(versions)]


def change_item_decode(win):
    from tkinter import messagebox

    if not getattr(win, 'he_decode_warned', False):
        messagebox.showwarning('Item Decode', 'Using a different layout can make items unreadable. '
                               'Reload the character to restore its detected item format.', parent=win.top)
        win.he_decode_warned = True
    current = getattr(win, 'he_decode_version', decode_version(win.ch.version))
    win.he_decode_version = next_decode_version(current)
    win.he_decode_label.set(ITEM_DECODE_VERSIONS[win.he_decode_version])
    win.redraw()


def decoded_item(win, entry):
    detected = decode_version(win.ch.version)
    selected = getattr(win, 'he_decode_version', detected)
    if selected == detected:
        return entry.it
    from mxl_early_save import ClassicData
    from mxl_v109 import Data109
    from mxl_char import blob_item
    from mxl_creator import BetaItemData, decode_blob
    from mxl_vanilla_he_items import ITEM_ERRORS

    data = win.app.data if detected == 95 else win.data
    if selected == 71:
        data = ClassicData(data)
    elif selected in (87, 92):
        data = Data109(data, selected)
    try:
        raw = win.ch._old_blob(entry) if win.ch.old else entry.blob
        if selected == 95:
            beta = BetaItemData(data)
            decode_blob(raw, beta, exact=True)
            data = beta
        return blob_item(raw, data)
    except ITEM_ERRORS as error:
        win.set_status(f'Item Decode {ITEM_DECODE_VERSIONS[selected]}: {error}', True)
        return None


def weapon_bonus_ranges(item, data, level, strength, dexterity, extra=0, *, version=96, cls=0):
    from collections import Counter
    from mxl_tooltip import all_stats
    from mxl_vanilla_he_extras import time_values

    if item is None or item.get('equipped') not in (4, 5, 9, 11, 12):
        return ()
    base = data.base(item['code'])
    damage = getattr(base, 'damage', None)
    special = None
    if not damage and base.kind == 'armor':
        types = {data.itypes[index][0] for index in data.type_ancestors(base.type)}
        special = 'kick' if 'boot' in types else 'smite' if 'shld' in types else None
        if special:
            code = base.code.encode('latin1')
            row = next((row for row in data._rows('armor') if row[128:132] == code), None)
            if row is not None:
                damage = {special: (row[0xFE], row[0xFF])}
    if not damage:
        return ()
    values = Counter()
    time_ranges = {'flat': [0, 0], 'percent': [0, 0], 'kick': [0, 0]}
    timed = {272: 'flat', 273: 'percent' if version >= 95 else 'flat', 302: 'kick'}
    for stat in all_stats(item, data):
        sid, amount = stat['id'], stat.get('value') or 0
        if sid in timed:
            _, lo, hi = time_values(amount)
            pair = time_ranges[timed[sid]]
            pair[0] += lo
            pair[1] += hi
        else:
            values[sid] += amount
    strength_pct, dexterity_pct = getattr(base, 'dmg_bonus', None) or (0, 0)
    raw_scale = (strength * strength_pct + dexterity * dexterity_pct) / 100
    overflow = 1 << 24
    if raw_scale >= overflow:
        raw_scale %= overflow
    percent = raw_scale + 100 + values[25] + (123 if cls == 4 else 0)

    def endpoint(total, flat):
        calculated = total * percent + flat * 100
        if version < 95:
            if calculated >= overflow:
                calculated %= overflow
            if calculated >= overflow // 2:
                return 0
        return calculated / (200 if special else 100)

    ranges = []
    for kind, minimum, maximum in (
        ('one_hand', 21, 22), ('two_hand', 23, 24), ('throw', 159, 160), ('smite', 21, 22), ('kick', 137, 137),
    ):
        low, high = damage.get(kind) or (0, 0)
        if not low and not high:
            continue
        enhance = (values[18] or values[17]) + time_ranges['percent'][0]
        enhanced = low * enhance / 100 + 2 if enhance else 0
        lo = enhanced + values[minimum] + time_ranges['flat'][0]
        hi = enhanced + values[maximum] + time_ranges['flat'][1]
        if kind == 'kick':
            kick = values[249] * level / 8
            lo += kick + time_ranges['kick'][0]
            hi += kick + time_ranges['kick'][1]
        hi += values[218] * level / 8 + high * values[219] * level / 800
        magic = values[111] if kind != 'throw' else 0
        actual_lo = endpoint(low + (lo % overflow if lo >= overflow else lo) + extra, magic)
        actual_hi = endpoint(high + (hi % overflow if hi >= overflow else hi) + extra, magic)
        if kind in ('one_hand', 'kick', 'smite') and 0.1 < actual_hi < actual_lo:
            actual_hi = actual_lo + 1
        ranges.append((kind, (round(lo), round(hi)), (round(actual_lo), round(actual_hi))))
    return ranges


def bonus_weapon_controls(parent, win):
    from tkinter import messagebox

    box = ttk.LabelFrame(parent, text='Bonus Weapon Damage', padding=2)
    bonus = tk.StringVar(box, value='0')
    ranges = tk.StringVar(box)
    real = tk.StringVar(box)
    summaries = []
    for row, text in enumerate((ranges, real)):
        label = ttk.Label(box, textvariable=text, wraplength=pixels(box, 198)[0])
        label.grid(row=row, column=0, columnspan=3, sticky='w')
        summaries.append(label)

    def redraw():
        selected = win.selected
        sim = getattr(win, 'st_sim', win.ch)
        rows = weapon_bonus_ranges(selected.it if selected else None, win.data, sim.level,
                                   sim.stat(0), sim.stat(2), int(bonus.get() or 0),
                                   version=sim.version, cls=sim.cls)
        labels = {'one_hand': '1-H', 'two_hand': '2-H', 'throw': 'Throw', 'kick': 'Kick', 'smite': 'Smite'}
        ranges.set('    '.join(f'{labels[kind]} Bonus {lo} to {hi}' for kind, (lo, hi), _ in rows[:2]))
        real.set('    '.join(f'{labels[kind]} Damage {lo} to {hi}' for kind, _, (lo, hi) in rows
                             if sim.version != 96 or kind not in ('kick', 'smite')))
        for label, line in zip(summaries, (ranges, real)):
            if line.get():
                label.grid()
            else:
                label.grid_remove()

    def edit(*_args):
        entered = bonus.get()
        if entered:
            try:
                bounded = str(min(256, max(0, int(entered))))
            except ValueError:
                bounded = '0'
            if bounded != entered:
                bonus.set(bounded)
        redraw()

    bonus.trace_add('write', edit)
    ttk.Label(box, text='Extra Bonus').grid(row=2, column=0)
    ttk.Entry(box, textvariable=bonus, width=4).grid(row=2, column=1, padx=2)
    ttk.Button(box, text='Calculate', width=9, style='Inventory.TButton', command=lambda: messagebox.showinfo(
        'Bonus Weapon Damage', 'Calculation is unfinished. Enter a bonus manually.', parent=box)).grid(row=2, column=2)
    return box, redraw


def options(win):
    import mxl_mock_gui
    import mxl_profile
    import settings

    page = win.pages['options']
    ttk.Label(page, text='These settings apply to the Diablo II character editor. Changes are saved immediately. '
                        'Use the game folder to select the tables and artwork for the version you are editing.',
              wraplength=pixels(page, 630)[0], justify='left').pack(anchor='w', padx=2, pady=(3, 5))
    body = ttk.Frame(page)
    body.pack(fill='both', expand=True)
    columns = [ttk.Frame(body), ttk.Frame(body)]
    for index, column in enumerate(columns):
        body.columnconfigure(index, weight=1, uniform='options')
        column.grid(row=0, column=index, sticky='nsew', padx=2)

    def group(column, caption):
        frame = ttk.LabelFrame(columns[column], text=caption, padding=(4, 0))
        frame.pack(fill='x', pady=(0, 2))
        return frame

    def radio_group(column, key, caption, choices, convert=str):
        frame = group(column, caption)
        values = dict(choices)
        saved = str(option(key, choices[0][0]))
        selected = tk.StringVar(frame, value=saved if saved in values else choices[0][0])
        for value, label in choices:
            tk.Radiobutton(frame, text=label, value=value, variable=selected, font=font(),
                           padx=0, pady=0, bd=0, highlightthickness=0,
                           command=lambda: settings.put('vanilla_he_' + key, convert(selected.get()))).pack(anchor='w')

    game = group(0, '1) Diablo II Game Folder')
    ttk.Button(game, text='Game folder…', command=lambda: mxl_profile.open_dialog(win.app)).pack(side='left')
    ttk.Button(game, text='Hero Editor folder...', command=lambda: choose_art_folder(win)).pack(side='left', padx=4)
    radio_group(0, 'error_response', '2) Error Reporting and Response',
                (('normal', 'Normal error response'), ('inspect', 'Show errors in Extras'),
                 ('status', 'Report errors in status bar')))
    mouse = group(0, '3) Mouse Cursor')
    center = tk.BooleanVar(page, value=bool(settings.get(CENTER_MOUSE)))
    for value, label in ((False, 'Leave the cursor where it is'), (True, 'Center the cursor on dialogs')):
        tk.Radiobutton(mouse, text=label, value=value, variable=center, font=font(),
                       padx=0, pady=0, bd=0, highlightthickness=0,
                       command=lambda: settings.put(CENTER_MOUSE, center.get())).pack(anchor='w')
    radio_group(0, 'item_access', '4) Item Edit Options',
                (('all', 'All editing, including binary'), ('transfer', 'Move, import and export'),
                 ('view', 'View only')))
    radio_group(0, 'decode_check', '5) Check Item Decode on Open',
                (('complete', 'Complete checking'), ('basic', 'Basic checking')))
    radio_group(1, 'character_access', '6) Character Edit Options',
                (('all', 'All editing, including hex'), ('stats', 'Attributes and stats'), ('view', 'View only')))
    radio_group(1, 'backups', '7) Character Backups',
                (('', 'Use app settings'), ('one', 'Keep one backup'), ('all', 'Keep all backups'),
                 ('off', 'Skip new backups')))
    radio_group(1, 'version_warning', '8) Version Warning Messages',
                (('show', 'Show version warnings'), ('hide', 'Hide version warnings')))

    levels = ('90', '10', '99')
    radio_group(1, 'item_level', '9) Default Item Level',
                tuple((value, value) for value in levels), convert=int)

    radio_group(1, 'set_attributes', '10) Display Set Magic Attributes',
                (('show', 'Show in Description'), ('hide', 'Hide in Description')))
    radio_group(1, 'unique_pictures', '11) Display Unique Item Pictures',
                (('show', 'Use unique pictures'), ('hide', 'Use base pictures')))
    radio_group(0, 'header_checks', 'Save Header Checks on Open',
                (('verify', 'Report checksum and file size issues'), ('ignore', 'Skip header warnings')))
    tools = group(0, 'Item and Character Tools')
    mock_mode = mxl_mock_gui._state['var']
    if mock_mode is not None:
        ttk.Checkbutton(tools, text='Mock Mode', variable=mock_mode,
                        command=lambda: mxl_mock_gui.set_mode(mock_mode.get(), select=False)).pack(side='left')
    if 'quests_adv' in win.pages:
        ttk.Button(tools, text='Quest words…', command=lambda: set_tab(win, 'quests_adv')).pack(side='left')


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
            offset = NPC_OFF + 4 + 8 * diff + 24 * returning
            bits = int.from_bytes(win.ch.head[offset:offset + 8], 'little')

            def checkbox(members):
                states = [bool(bits & (1 << bit)) != returning for bit, _name in members]
                return '☑' if states and all(states) else '◩' if any(states) else '☐'

            root = tree.insert('', 'end', text=f'{checkbox([npc for group in groups for npc in group])} '
                                               f'{difficulty_name(diff)} Mode {title}', open=True)
            for group, (act, _intro, _quests, _travel) in zip(groups, win.ch.quest_acts()):
                node = tree.insert(root, 'end', text=f'{checkbox(group)} {act}')
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
    panel = tk.Canvas(parent, width=pixels(parent, 207)[0], height=pixels(parent, 431)[0], bg=BLACK, bd=0, highlightthickness=0)
    panel.create_rectangle(*pixels(panel, 1, 1, 206, 430), outline='#624824')
    panel.create_rectangle(*pixels(panel, 5, 5, 202, 426), outline='#b3914d')
    panel.create_rectangle(*pixels(panel, 8, 8, 199, 423), outline='#4c3620')
    for x in (18, 189):
        for y in (20, 411):
            panel.create_polygon(*pixels(panel, x - 10, y, x, y - 8, x + 10, y, x, y + 8), fill='#57411f', outline='#c7a564')
            panel.create_line(*pixels(panel, x, y - 12, x, y + 12), fill='#c7a564')
    return panel


def update_portrait(panel, cls, data):
    from PIL import Image, ImageTk
    from mxl_char import class_names

    if getattr(panel, '_he_class', None) == cls:
        return
    panel._he_class = cls
    panel.delete('portrait')
    original = picture(f'portrait_{cls}')
    if original is not None:
        width, height = pixels(panel, 205, 405)
        panel._he_portrait = photo(panel, original, (width, height))
        panel.create_image(*pixels(panel, 2, 2), anchor='nw', image=panel._he_portrait, tags='portrait')
        if 0 <= cls < len(names := class_names(data)):
            panel.create_text(*pixels(panel, 103, 421), text=names[cls], fill='#d6b36c',
                              font=font(), tags='portrait')
        return
    portrait = character_image(cls)
    if portrait is not None:
        scale = min(185 / portrait.width, 345 / portrait.height)
        size = pixels(panel, portrait.width * scale, portrait.height * scale)
        panel._he_portrait = ImageTk.PhotoImage(portrait.resize(size, Image.LANCZOS), master=panel)
        panel.create_image(*pixels(panel, 103, 210), image=panel._he_portrait, tags='portrait')
    names = class_names(data)
    if 0 <= cls < len(names):
        panel.create_text(*pixels(panel, 103, 396), text=names[cls], fill='#d6b36c',
                          font=('Times New Roman', 13), tags='portrait')


QUEST_STAGES = ('Not Started', 'Looking For', 'Just Finished', 'Long Finished')
QUEST_STAGE_WORDS = (0, 0x0004, 0x2000)


QUEST_NOTES = {
    1: ((4, 'Entered the Den of Evil'),),
    2: ((4, 'Entered the Burial Grounds'),),
    3: ((6, 'Picked up the Horadric Malus'),),
    4: ((4, 'Entered Tristram'), (10, 'Completed the Secret Cow Level'), (14, 'The Rogues rescued Cain')),
    5: ((2, 'Read the Moldy Tome'), (6, 'Entered the Forgotten Tower')),
    9: ((4, 'Found Radament'),),
    10: ((4, 'Cain identified the Viper Amulet'), (5, 'Cain identified the Staff of Kings'),
         (10, 'Cain discussed the Horadric Staff'), (11, 'Assembled the Horadric Staff')),
    11: ((2, 'The sun went dark'), (3, 'Talked to Drognan about the sun')),
    14: ((3, 'Talked to Tyrael'), (4, 'Talked to Jerhyn'), (5, 'Killed Duriel'),
         *((bit, f'{npc} offered congratulations') for bit, npc in
           enumerate(('Atma', 'Warriv', 'Drognan', 'Lysander', 'Cain', 'Fara'), 6))),
    19: ((2, 'Picked up the Gidbinn'), (3, 'Hratli asked for the Gidbinn')),
    20: ((2, 'Cain discussed the Jade Figurine'), (4, 'Cain discussed the Golden Bird'),
         (5, 'Received the Potion of Life'), (6, 'Found the Jade Figurine')),
    35: ((3, 'Found Shenk'), (5, 'Larzuk offered to socket an item')),
    37: ((7, 'Read the Scroll of Resistance'), (8, 'Rescued Anya and talked to Malah')),
    38: ((4, 'Anya offered to personalize an item'),),
    40: tuple((bit, f'{npc} offered congratulations') for bit, npc in
              enumerate(('Larzuk', 'Cain', 'Malah', 'Tyrael', 'Qual-Kehk', 'Anya'), 4)),
}
ACT_NOTES = {0: 'Met Warriv', 8: 'Met Jerhyn', 16: 'Met Hratli', 24: 'Introduced to Act IV',
             32: 'Introduced to Act V by Cain'}


def quest_stage(word):
    return 3 if word & 1 else 2 if word & 0x2000 else int(bool(word))


def quest_details(win, parent):
    """Build quest details and keep the existing completion and reward rules."""
    width, height = pixels(parent, 336, 434)
    left = ttk.Frame(parent, width=width, height=height)
    left.pack(side='left', fill='y', padx=(2, 0))
    left.pack_propagate(False)
    details = ttk.LabelFrame(left, text='Quest', padding=6)
    details.pack(fill='both', expand=True)
    quest = ttk.Frame(details)
    quest.pack(side='left', fill='y')
    badge = ttk.Label(quest)
    badge.pack(pady=(5, 0))
    title = ttk.Label(quest, wraplength=pixels(parent, 100)[0], justify='center')
    title.pack(pady=(3, 4))
    notes = ttk.Label(quest, wraplength=pixels(parent, 100)[0], justify='left')
    notes.pack(anchor='w')
    flags = ttk.LabelFrame(details, text='Extra Notes', padding=2)
    flags.pack(side='left', fill='both', expand=True, anchor='n', padx=(6, 0))
    all_quests = (1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21, 22,
                  25, 26, 27, 35, 36, 37, 38, 39, 40)
    quest_index = {word: index for index, word in enumerate(all_quests)}

    def show_picture(word):
        sprites = picture('quests')
        if sprites is None:
            return
        x = 72 * quest_index.get(word, 27)
        badge.image = photo(badge, sprites.crop((x, 0, x + 72, 86)), pixels(badge, 72, 86))
        badge.configure(image=badge.image)

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

    status = ttk.Frame(quest)
    status.pack(side='bottom', fill='x')
    states = []
    for state, text in enumerate(QUEST_STAGES):
        radio = ttk.Radiobutton(status, text=text, variable=value, value=state, command=apply)
        radio.pack(anchor='w')
        states.append(radio)

    batch = ttk.LabelFrame(left, text='Batch', padding=3)
    batch.pack(side='bottom', fill='x', pady=(5, 0), before=details)

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
            ttk.Radiobutton(column, text=label, variable=mode, value=stage).pack(anchor='w', pady=1)
        button = ttk.Button(column, text='Batch', command=lambda scope=scope, mode=mode: change_group(scope, mode.get()))
        button.pack(fill='x', pady=(4, 2))
        buttons[scope] = button

    def show_flags(difficulty, word, options):
        raw = win.ch.quest_word(difficulty, word)
        for bit, caption in options:
            key = difficulty, word, bit
            saved = bool(raw & (1 << bit))
            checked = tk.BooleanVar(flags, value=getattr(win, 'he_quest_notes', {}).get(key, saved))

            def toggle(key=key, checked=checked, saved=saved):
                if checked.get() == saved:
                    win.he_quest_notes.pop(key, None)
                else:
                    win.he_quest_notes[key] = checked.get()
                win.update_dirty()

            button = ttk.Checkbutton(flags, text=caption, variable=checked, command=toggle)
            button.pack(anchor='w')
            if not allows(win, 'character'):
                button.state(['disabled'])

    def refresh(tree):
        for child in flags.winfo_children():
            child.destroy()
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
            show_picture(word)
            show_flags(difficulty, word, QUEST_NOTES.get(word, ()))
            if word == 1 and not win.ch.early:
                show_flags(difficulty, 41, ((0, 'Akara reset stat and skill points'),))
            value.set(3 if tree.value[iid] else win.he_quest_stages.get(
                (difficulty, word), 0 if saved_stage == 3 else saved_stage))
        else:
            details.configure(text='Quest')
            title.configure(text=tree.tv.item(iid, 'text') if iid else 'Select a quest')
            notes.configure(text='')
            show_picture(None)
            if iid in win.he_act_notes:
                difficulty, intro = win.he_act_notes[iid]
                show_flags(difficulty, intro, ((0, ACT_NOTES[intro]),))
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

        super().__init__(parent, width=pixels(parent, 21)[0], height=pixels(parent, 409)[0], bg=FORM, bd=0, highlightthickness=0, takefocus=True)
        self.variable = variable
        self.command = command
        self.tabs = []
        self.images = []
        face = bitmap_font(11)
        tab_width = pixels(self, 21)[0]
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
                rotated = paper.transpose(Image.Transpose.ROTATE_270)
                rotated = rotated.resize((tab_width, pixels(self, length)[0]), Image.Resampling.LANCZOS)
                rasters.append(ImageTk.PhotoImage(rotated, master=self))
            length = rasters[0].height()
            image = self.create_image(0, y, anchor='nw', image=rasters[0])
            self.images.extend(rasters)
            self.tabs.append((key, y, y + length, image, rasters))
            y += length
        self.configure(height=max(self.winfo_reqheight(), y))
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
    original = picture('pickup')
    if original is not None:
        paper.he_art = photo(paper, original, (int(paper.cget('width')), int(paper.cget('height'))))
        paper.create_image(0, 0, anchor='nw', image=paper.he_art)
    else:
        paper.create_rectangle(*pixels(paper, 4, 4, 72, 106), outline='#55442d')
    clip = getattr(win.app, '_capy_clip', None)
    if clip:
        try:
            item = blob_item(clip[0], win.data)
            win.draw_item(paper, item, *pixels(paper, 9, 9, 68, 102), False)
        except (CharError, FormatError, OSError):
            pass


def item_hint(owner):
    from mxl_floattip import FloatTip

    def build(body):
        role(body, 'hint')
        role(tk.Label(body, text='Drag to move · Right-click for actions · ↑/↓ to scroll item details',
                      padx=3, pady=1, font=font()), 'hint').pack()

    return FloatTip(owner, build=build, bg='#ffffe1', edge=EDGE)


def inventory_images(grid, columns, rows, cell, footer_height):
    """Use the native panel at one pixel per pixel, shared with the stash-side inventory."""
    from mxl_d2look import char_art, photo as game_photo
    from mxl_d2look_art import ArtError
    from mxl_vanilla_pages import NATIVE_GRID, NATIVE_PANEL, _NativeArt

    original = picture('person')
    if original is not None:
        x, y = NATIVE_GRID
        bottom = y + rows * 29
        width, height = original.size
        return dict(doll=photo(grid, original.crop((0, 0, width, y)), pixels(grid, width, y)),
                    grid=photo(grid, original.crop((x, y, x + columns * 29, bottom)),
                               (columns * cell, rows * cell)),
                    footer=photo(grid, original.crop((0, bottom, width, height)),
                                 (pixels(grid, width)[0], footer_height)))
    art = char_art()
    if art is None:
        return {}
    try:
        path = _NativeArt(art).char_panel_d2()
        width, height = columns * 29, rows * 29
        x, y = NATIVE_GRID
        panel_width, panel_height = NATIVE_PANEL
        if x + width > panel_width or y + height >= panel_height:
            return {}
        return dict(doll=game_photo(path, size=pixels(grid, panel_width, y), crop=(0, 0, panel_width, y)),
                    grid=game_photo(path, size=(columns * cell, rows * cell), crop=(x, y, x + width, y + height)),
                    footer=game_photo(path, size=(pixels(grid, panel_width)[0], footer_height),
                                 crop=(0, y + height, panel_width, panel_height)))
    except (ArtError, OSError, ValueError, IndexError, StructError):
        return {}


def weapon_tabs(win, event=None):
    from mxl_d2look import WSET_TAB_D2, WSET_TABS_D2
    from mxl_vanilla_pages import _n

    width, height = pixels(win.doll, *map(_n, WSET_TAB_D2))
    for weapon_set, positions in WSET_TABS_D2.items():
        for x, y in positions:
            x, y = pixels(win.doll, _n(x), _n(y))
            if event is None:
                if win.wset.get() == weapon_set:
                    win.doll.create_rectangle(x, y, x + width - 1, y + height - 1, outline='#d4b062')
            elif x <= event.x < x + width and y <= event.y < y + height:
                return weapon_set
    return None
