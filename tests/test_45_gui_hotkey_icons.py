"""Character tab, Hotkeys page: every cell that holds a skill shows an icon, including a skill of another class
than the character's (an oskill from an item: the sample Necromancer has the Assassin's Blink on Right II, which
showed a name without an icon). Needs the game art (settings.json game_dir), else skipped. Both looks."""
import os

import capytest as T

MODE = 'gui'
VARIANTS = {
    'd2': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0'},
    'he': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '1280x720+0+0'},
}
G = T.G


@T.test
def every_hotkey_skill_has_an_icon():
    import settings
    gd = settings.get('game_dir')
    if not gd or not os.path.isdir(gd):
        T.skip('no game folder (settings.json game_dir): no skill icons to load')
    cw = T.chartab()
    T.select_tab('Character')
    page = cw.extra.get('hotkeys')
    if page is None:
        T.skip('no Hotkeys page')
    cw.tab.set('hotkeys')
    cw.show_tab()
    T.settle(0.5)
    data = cw.data
    cells = [(off, c, page.skill_at(off)[0]) for off, c in page.cells.items()]
    cells = [(off, c, sid, data.skill_class.get(sid, 255)) for off, c, sid in cells if sid is not None]
    if not any(cls < 7 and cls != page.win.sktree.cls for _o, _c, _s, cls in cells):
        T.skip('the sample character has no skill of another class on a hotkey')
    for off, c, sid, cls in cells:
        img = str(c['icon'].cget('image'))
        T.check(img and img != str(page._blank), f'hotkey cell {c["title"]!r} ({c["text"]}, skill {sid}, class {cls}) shows no icon')
    cw.tab.set('stats')
    cw.show_tab()


T.main(globals())
