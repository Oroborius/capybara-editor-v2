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
        with patch.object(look.tk, 'Canvas') as canvas, patch('PIL.ImageTk.PhotoImage') as photo:
            canvas.return_value.winfo_fpixels.side_effect = parent.winfo_fpixels
            look.character_portrait(parent)
            look.action_plaque(parent, 'OPEN', 0)
        T.eq((canvas.call_args.kwargs['width'], canvas.call_args.kwargs['height']),
             (round(207 * scale), round(431 * scale)), 'portrait canvas')
        T.eq(photo.call_args.args[0].size, (round(96 * scale), round(34 * scale)), 'action plaque')


T.main(globals())
