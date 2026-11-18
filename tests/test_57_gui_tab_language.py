"""The main tabs Stash / Character / Creator follow the language (docs/review/gui.md finding 13: they had no T()
at all): at start in the chosen language and on a live switch (mxl_lang.retranslate). The registry keys stay
English (code and tests find the tabs by them)."""
import capytest as T

MODE = 'gui'
G = T.G


def switch(code):
    i = next((i for i, x in enumerate(G.app.languages) if x[0] == code), None)
    if i is None:
        T.skip(f'no language {code!r} offered')
    G.app.lang_combo.current(i)
    G.app.change_language()
    T.settle(0.3)


def expected():
    import mxl_lang
    return [mxl_lang.T('tab.stash', 'Stash'), mxl_lang.T('tab.character', 'Character'),
            mxl_lang.T('tab.creator', 'Creator')]


@T.test
def main_tabs_follow_the_language():
    import mxl_tabs
    T.eq(T.tab_names()[:3], ['Stash', 'Character', 'Creator'], 'English tabs')
    for code in ('fr', 'vi'):
        switch(code)
        want = expected()
        T.check(want[0] != 'Stash' and want[1] != 'Character', f'{code}: no translation of the tab names {want}')
        T.eq(T.tab_names()[:3], want, f'tabs in {code}')
        T.eq(sorted(mxl_tabs._state['pages'])[:3], ['Character', 'Creator', 'Stash'], 'registry keys stay')
    switch('en')
    T.eq(T.tab_names()[:3], ['Stash', 'Character', 'Creator'], 'English tabs again')


@T.test
def emptied_tab_takes_the_current_language():
    """A tab closed while French is chosen gets its French name back (TabPage.destroy)."""
    import mxl_tabs
    switch('fr')
    try:
        page = mxl_tabs._state['pages']['Character']
        page.destroy()
        T.pump(4)
        T.eq(mxl_tabs._state['nb'].tab(page, 'text'), expected()[1], 'emptied Character tab')
    finally:
        switch('en')


T.main(globals())
