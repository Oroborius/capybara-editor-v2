"""More » Language while the editor runs: the editor's own texts (toolbar buttons, Character page tabs, Creator
labels, ...) follow at once, not only the collector's (docs/review/gui.md finding 12: they stayed English until a
restart). Switched to French and back to English; texts the French file does not have stay English, which is
right. Unrelated texts (item names, numbers) are not touched."""
import capytest as T

MODE = 'gui'
G = T.G
KEYS = (('cr.title.creator', 'Item Creator'), ('cr.edit', 'Edit item'), ('ch.tab.inventory', 'Inventory'),
        ('ch.tab.waypoints', 'Waypoints'), ('cr.item_type', 'Item type'))


def texts():
    """Every widget text, notebook tab and menu label of the application."""
    out = []

    def walk(w):
        try:
            cls = w.winfo_class()
            if cls == 'Menu':
                last = w.index('end')
                for i in range(0 if last is None else last + 1):
                    if w.type(i) not in ('separator', 'tearoff'):
                        out.append(str(w.entrycget(i, 'label')))
            elif cls == 'TNotebook':
                out.extend(str(w.tab(t, 'text')) for t in w.tabs())
            else:
                out.append(str(w.cget('text')))
        except Exception:
            pass
        for c in w.winfo_children():
            walk(c)
    walk(G.root)
    return out


def switch(code):
    import i18n
    i = next((i for i, x in enumerate(G.app.languages) if x[0] == code), None)
    if i is None:
        T.skip(f'no language {code!r} offered')
    G.app.lang_combo.current(i)
    G.app.change_language()
    T.settle(0.3)
    return i18n


@T.test
def editor_texts_follow_the_language():
    import mxl_char_gui
    import mxl_lang
    if T.chartab() is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        T.pump(10)
    T.select_tab('Stash')
    before = texts()
    for _k, en in KEYS:
        T.check(en in before, f'{en!r} is not on screen before the switch')
    switch('fr')
    after = texts()
    changed = 0
    for key, en in KEYS:
        fr = mxl_lang.T(key, en)
        if fr == en:
            continue
        changed += 1
        T.check(fr in after, f'{key}: {fr!r} not on screen after switching to French')
        T.check(en not in after, f'{key}: {en!r} still on screen after switching to French')
    if not changed:
        T.skip('the French file translates none of the texts checked')
    switch('en')
    back = texts()
    for _k, en in KEYS:
        T.check(en in back, f'{en!r} not back after switching to English')
    T.eq(sorted(back), sorted(before), 'every text after French and back')


T.main(globals())
