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
            look.style(Mock())
            style = make_style.return_value
            style.theme_use.assert_called_once_with('clam')
            style.configure.assert_any_call('Peach.TFrame', background='#ffe0c0')
            style.configure.assert_any_call('Treeview', rowheight=16)


T.main(globals())
