"""Creator / Item Editor title: "name - base" only when the base is not already in the name ("Belt (Angelic) - Belt
(Angelic)", "(Druid Challenge Item) Caoi Dulra Fruit - Caoi Dulra Fruit" before), and a long title wraps inside
the middle column instead of being cut at 800x600 (docs/review/gui.md finding 16). Both looks."""
import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
    'he-800x600': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0'},
}
G = T.G


@T.test
def rule():
    import mxl_creator_gui as CG
    T.eq(CG.title_text('Belt (Angelic)', 'Belt (Angelic)'), 'Belt (Angelic)', 'same name')
    T.eq(CG.title_text('(Druid Challenge Item) Caoi Dulra Fruit', 'Caoi Dulra Fruit'),
         '(Druid Challenge Item) Caoi Dulra Fruit', 'base inside the name')
    T.eq(CG.title_text('Absolute Zero', 'Battle Staff (Sacred)'), 'Absolute Zero - Battle Staff (Sacred)', 'other base')
    T.eq(CG.title_text('Victory', ''), 'Victory', 'no base name')


@T.test
def title_inside_the_column():
    import mxl_creator_gui as CG
    import mxl_tabs
    CG.CreatorWindow(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    T.select_tab('Creator')
    T.settle(0.3)
    seen = 0
    for key in ('runeword', 'unique', 'angelic'):
        w.search.set('')
        w.quality.set(dict((k, lab) for lab, k in CG.qualities())[key])
        w.on_quality()
        T.pump()
        for i in range(min(40, len(w.entries))):
            w.listbox.selection_clear(0, 'end')
            w.listbox.selection_set(i)
            w.on_pick()
            T.pump(3)
            if w.spec is None:
                continue
            t = str(w.title.cget('text'))
            parts = t.split(' - ')
            T.check(len(parts) < 2 or parts[-1] != parts[-2], f'{key}: title repeats a name: {t!r}')
            seen += 1
        T.settle(0.3)
        mid = w._mid
        r, mr = w.title.winfo_rootx() + w.title.winfo_width(), mid.winfo_rootx() + mid.winfo_width()
        T.check(w.title.winfo_ismapped() and r <= mr + 1, f'{key}: title ends at x {r}, its column at {mr} '
                f'({w.title.cget("text")!r})')
        T.check(w.title.winfo_reqwidth() <= mid.winfo_width(), f'{key}: title asks for {w.title.winfo_reqwidth()} px, '
                f'the column is {mid.winfo_width()} px')
    T.check(seen > 0, 'no item shown')


T.main(globals())
