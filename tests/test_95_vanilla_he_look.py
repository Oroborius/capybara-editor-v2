"""Hero Editor 1.04 reference values and the pre-change Median look."""
import sys
from unittest.mock import Mock, patch

import capytest as T

MODE = 'engine'
NEEDS = ()

MEDIAN_D2 = (
    '#26282a', '#34373a', '#1b1c1e', '#141112', '#6f5a3a', '#9a7f52',
    '#c7b377', '#f2dc9c', '#6a624f', '#4a1712', '#6a231a',
)
MEDIAN_HE = ('#f0f0f0', '#e1e1e1', '#ffffff', '#000000', '#d8c27a', '#3a5f8a')
MEDIAN_GRID = ('#f0f0f0', '#e2dfd3', '#c4c0b1', '#d8c27a', '#dde8f2', '#f4dede', '#f0f0f0', '#000000')


@T.test
def median_look_values_preserved():
    sys.path.insert(0, T.APP)
    import mxl_d2_theme as d2
    import mxl_attr_picker
    import mxl_he_theme as he
    import mxl_he_grid as grid
    import mxl_profile

    d2_keys = 'STONE STONE_HI STONE_LO FIELD BRONZE BRONZE_HI GOLD GOLD_HI DIM LEATHER LEATHER_HI'
    he_keys = 'HE_BG HE_BTN HE_ENTRY HE_FG HE_GOLD SELECT_BG'
    grid_keys = 'HE_BG HE_EMPTY HE_GRID HE_SEL HE_OK HE_KO HE_DETAIL_BG HE_DETAIL_FG'
    for module, keys, snapshot in ((d2, d2_keys, MEDIAN_D2), (he, he_keys, MEDIAN_HE),
                                   (grid, grid_keys, MEDIAN_GRID)):
        T.eq(tuple(getattr(module, key) for key in keys.split()), snapshot, module.__name__)
    with patch.object(mxl_profile, 'is_median', return_value=True):
        for choice, colors in (('d2', ('#26282a', '#141112', '#4a1712')),
                               ('he', ('#f0f0f0', '#ffffff', '#3a5f8a'))):
            with patch.dict(d2._state, theme=choice):
                T.eq(d2.theme(), choice, 'Median retains its selected theme')
                palette = mxl_attr_picker.palette()
                T.eq(tuple(palette[key] for key in ('bg', 'field', 'sel')), colors, 'Median picker colors')



@T.test
def vanilla_theme_and_reference_values():
    sys.path.insert(0, T.APP)
    import mxl_d2_theme as d2
    import mxl_he_theme
    import mxl_profile
    import mxl_vanilla_he as look

    with patch.object(mxl_profile, 'is_median', return_value=False), patch.dict(d2._state, theme='d2'):
        T.check(look.active() and not d2.dark(), 'vanilla uses Hero Editor even with a saved Median dark setting')
        with patch.object(look, 'style', return_value='vanilla') as style:
            T.eq(mxl_he_theme._style(None), 'vanilla', 'installed widget theme dispatch')
            style.assert_called_once_with(None)
    T.eq((look.FORM, look.PEACH, look.WHITE, look.BLACK, look.EDGE, look.FRAME_EDGE, look.INSET,
          look.LIGHT, look.READONLY, look.SELECT, look.DESCRIPTION, look.SET_GREEN, look.HEX_TITLE),
         ('#f5f5f5', '#ffe0c0', '#ffffff', '#000000', '#a6a6a6', '#9e9e9e', '#6a6a6a',
          '#e3e3e3', '#c0c0c0', '#3096fa', '#707070', '#00c800', '#0000c0'), 'LOOK.md palette')
    T.eq((look.FONT, look.SMALL_FONT, look.LEGEND_FONT, look.DOC_FONT),
         (('Tahoma', 8), ('Tahoma', 7), ('Tahoma', 8, 'italic'), ('Tahoma', 10)), 'LOOK.md typography')
    T.eq(tuple(label for _key, label in look.TABS),
         ('Splash', 'Stats', 'Inventory', 'Waypoints', 'Skills', 'Quests', 'Mercenary',
          'Introductions', 'Options', 'Info', 'About'), 'LOOK.md tab order')
    T.eq(look.ACTIONS, ('OPEN', 'SAVE', 'RELOAD', 'EXTRAS', 'CLOSE'), 'LOOK.md action order')


@T.test
def vanilla_widget_palette_is_applied():
    sys.path.insert(0, T.APP)
    import mxl_he_theme
    import mxl_profile
    import mxl_vanilla_he as look

    with patch.object(mxl_profile, 'is_median', return_value=False), patch.object(
            mxl_he_theme, 'families', return_value={'tahoma'}):
        description = Mock()
        description.winfo_class.return_value = 'Text'
        look.role(description, 'description')
        options = description.configure.call_args.kwargs
        T.eq((options['background'], options['foreground'], options['font']),
             ('#707070', '#000000', ('Tahoma', 7)), 'item description')

        menu = Mock(_vanilla_he_menu=False)
        mxl_he_theme._menu_colours(menu)
        options = menu.configure.call_args.kwargs
        T.eq((options['bg'], options['activebackground'], options['activeforeground'],
              options['disabledforeground']),
             ('#ffffff', '#3096fa', '#ffffff', '#707070'), 'popup selection and disabled ink')

        with patch.object(look.ttk, 'Style') as make_style:
            look.style(Mock(winfo_fpixels=lambda _unit: 96))
            style = make_style.return_value
            style.theme_use.assert_called_once_with('clam')
            style.configure.assert_any_call('Peach.TFrame', background='#ffe0c0')
            style.configure.assert_any_call('Treeview', rowheight=16)


@T.test
def hero_editor_menu_reaches_every_toolbar_command():
    from types import SimpleNamespace

    sys.path.insert(0, T.APP)
    import mxl_toolbar
    import mxl_vanilla_he as look

    def widget(kind, text, values=()):
        w = Mock()
        w.winfo_class.return_value = kind
        w.instate.return_value = False
        w.cget.side_effect = {'text': text, 'values': values}.__getitem__
        w.get.return_value = values[0] if values else ''
        return w

    char = widget('TCombobox', '', ('Hero', 'Other Hero'))
    folder = widget('TButton', 'Game folder...')
    language = widget('TCombobox', '', ('English', 'German'))
    toggle = widget('TCheckbutton', 'Theme')
    partner = Mock(w=widget('TLabel', 'Language'))
    leaves = [Mock(w=w, partner=partner if w is language else None)
              for w in (char, folder, language, toggle)]
    toolbar = mxl_toolbar.Toolbar.__new__(mxl_toolbar.Toolbar)
    toolbar.app = SimpleNamespace(char_combo=char, toolbar=toolbar)
    toolbar.items = leaves
    toolbar.order = leaves[1:]
    for leaf in leaves:
        leaf.children = []
    # The entire toolbar is hidden in the HE host regardless of its own overflow state.
    toolbar.hidden = set()
    menu = Mock(index=Mock(return_value=4), cget=Mock(return_value=''), winfo_children=Mock(return_value=[]))
    profile = Mock()
    updates = Mock()
    diagnostics = Mock()

    with patch.object(mxl_toolbar, 'EXTRA', [(lambda: 'Game profile...', profile),
                                            (lambda: 'Check for updates...', updates),
                                            (lambda: 'Export diagnostics ZIP...', diagnostics)]), patch(
            'tkinter.Menu', side_effect=lambda *_args, **_kwargs: Mock(index=Mock(return_value=2))), patch.object(
            look, 'font', return_value=look.FONT):
        look.add_toolbar_menu(toolbar.app, menu)

    commands = {call.kwargs['label']: call.kwargs['command'] for call in menu.add_command.call_args_list}
    T.eq(set(commands), {'Game folder...', '[  ] Theme'}, 'hidden buttons')
    commands['Game folder...']()
    commands['[  ] Theme']()
    folder.invoke.assert_called_once_with()
    toggle.invoke.assert_called_once_with()
    cascades = {call.kwargs['label']: call.kwargs['menu'] for call in menu.add_cascade.call_args_list}
    for label, w, choice in (('Character: Hero', char, 'Other Hero'), ('Language: English', language, 'German')):
        choices = cascades[label].add_command.call_args_list
        T.eq(len(choices), 2, label)
        choices[1].kwargs['command']()
        w.set.assert_called_once_with(choice)
        w.event_generate.assert_called_once_with('<<ComboboxSelected>>')
    extras = cascades['More']
    T.eq(len(extras.add_command.call_args_list), 3, 'all More entries')
    for call, action in zip(extras.add_command.call_args_list, (profile, updates, diagnostics)):
        call.kwargs['command']()
        action.assert_called_once_with(toolbar.app)


@T.test
def hero_editor_fixed_geometry_follows_ui_scale():
    sys.path.insert(0, T.APP)
    import mxl_vanilla_he as look

    for scale in (1.0, 1.25, 1.5):
        parent = Mock(winfo_fpixels=lambda _unit: 96 * scale)
        with patch.object(look.tk, 'Canvas') as canvas, patch('PIL.ImageTk.PhotoImage') as photo, patch.object(
                look, 'picture', return_value=None):
            canvas.return_value.winfo_fpixels.side_effect = parent.winfo_fpixels
            look.character_portrait(parent)
            look.action_plaque(parent, 'OPEN', 0)
        T.eq((canvas.call_args.kwargs['width'], canvas.call_args.kwargs['height']),
             (round(207 * scale), round(431 * scale)), 'portrait canvas')
        T.eq(photo.call_args.args[0].size, (round(96 * scale), round(34 * scale)), 'action plaque')


@T.test
def scaled_popup_and_inventory_clipboard_use_canvas_pixels():
    from types import SimpleNamespace
    import mxl_rc_menu as rc
    import mxl_vanilla_he as look

    for scale in (1.0, 1.25, 1.5):
        cv = Mock(winfo_fpixels=lambda _unit: 96 * scale)
        cv.winfo_class.return_value = 'Canvas'
        cv.winfo_rootx.return_value, cv.winfo_rooty.return_value = 600, 260
        pitch, = look.pixels(cv, 29)
        cv.winfo_width.return_value, cv.winfo_height.return_value = 10 * pitch, 4 * pitch
        x, y = 7 * pitch + 2, 3 * pitch + 2
        expected = (600 + x, 260 + y)
        reported_root = tuple(round(value / scale) for value in expected)
        event = SimpleNamespace(widget=cv, x=x, y=y, x_root=reported_root[0], y_root=reported_root[1])
        menu = Mock()
        look.popup(menu, event)
        menu.tk_popup.assert_called_once_with(*expected)
        menu.grab_release.assert_called_once_with()

        entry = object()
        clip = (b'copied item', 'Copied item')
        win = Mock(inv=cv, he_pointer=(cv, look.screen_point(event)), cell=pitch, vanilla_he=False)
        win.app._capy_clip = clip
        win.entry_at.side_effect = ((entry, None), (None, None))
        win.is_merc.return_value = False
        root = SimpleNamespace(_he_window=lambda: win)
        with patch.object(rc, '_sync'), patch.object(rc, '_char_copy') as copy:
            T.eq(look.inventory_clipboard(root, event, False), 'break', 'vanilla consumes Ctrl+C')
            copy.assert_called_once_with(win, entry)
            T.eq(look.inventory_clipboard(root, event, True), 'break', 'vanilla consumes Ctrl+V')
        win.ch.place.assert_called_once_with(clip[0], ('inv', 7, 3), False)

        cv.winfo_rootx.return_value += pitch
        T.eq(look.clipboard_point(win.he_pointer), (x - pitch, y), 'pointer rebased after scrolling')


@T.test
def scaled_original_cover_fills_its_frame():
    from PIL import Image
    import mxl_vanilla_he as look

    for scale in (1.0, 1.25, 1.5):
        width, height = round(640 * scale), round(435 * scale)
        edge = round(scale)
        panel = Mock(winfo_width=lambda: width, winfo_height=lambda: height,
                     winfo_fpixels=lambda _unit: 96 * scale)
        art = Image.new('RGB', (638, 433), 'red')
        with patch.object(look, 'picture', return_value=art), patch('PIL.ImageTk.PhotoImage') as photo:
            look.draw_cover(panel, 'splash')
        T.eq(photo.call_args.args[0].size, (width - 2 * edge, height - 2 * edge), 'cover fills frame')
        T.eq(panel.create_image.call_args.args, (edge, edge), 'cover starts inside frame')
        panel.create_text.assert_not_called()


@T.test
def original_hero_editor_art_is_read_on_demand():
    from io import BytesIO
    from pathlib import Path
    import struct

    from PIL import Image
    from mxl_vanilla_he_assets import extract, load

    with BytesIO() as stream:
        Image.new('RGB', (94, 32), '#345678').save(stream, format='BMP')
        plaque = stream.getvalue().ljust(9144, b'\0')
    marker = b'lt\0\0'
    record = marker + struct.pack('<I', len(plaque)) + plaque
    invalid = marker + struct.pack('<I', len(plaque)) + b'x' * len(plaque)
    data = b'MZ' + invalid + record + marker + struct.pack('<I', len(plaque))
    pictures = extract(data)
    T.eq(list(pictures), ['button_EXTRAS_0'], 'valid VB6 picture survives malformed records')
    T.eq(pictures['button_EXTRAS_0'].getpixel((0, 0)), (52, 86, 120), 'original pixel')
    T.eq(load(None), {}, 'art is opt-in')
    T.eq(load(T.tmp()), {}, 'missing executable uses fallback')

    folder = Path(T.REPO) / '.cache' / 'heroed' / 'app'
    if (folder / 'Hero Editor.exe').is_file():
        originals = load(folder)
        T.eq(originals['splash'].size, (638, 433), '1.04 splash')
        T.eq(originals['stash'].size, (320, 432), '1.04 stash')
        T.eq(sum(key.startswith('button_') for key in originals), 15, '1.04 plaque states')


T.main(globals())
