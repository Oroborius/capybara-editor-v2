"""Right-click "Change item quality" entries that ask a question first (rare / crafted / tempered names, "Which set /
unique item?"): the small pick window opens (it raised a TclError before - Listbox activestyle 'dotselect' - so these
quality changes silently did nothing), it belongs to the editor window (not to the menu), sits over the editor, has
the first entry selected, closes on Escape, and Enter twice turns the item rare in the stash file; on the Character
tab the same window opens for a worn item."""
import tkinter as tk

import capytest as T

MODE = 'gui'
RESET = True
G = T.G


def pick_windows():
    """Mapped Toplevels that hold a Listbox (the pick window), anywhere under the root - menus included."""
    out = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Toplevel) and c.winfo_exists():
                if any(isinstance(k, tk.Listbox) for k in c.winfo_children()):
                    out.append(c)
            walk(c)
    walk(G.root)
    return out


def listbox(top):
    return next(k for k in top.winfo_children() if isinstance(k, tk.Listbox))


def stash_unique():
    """(page, x, y) of a stash item whose quality menu offers 'rare...'."""
    for it in sorted(G.app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        if it.get('quality') not in ('unique', 'set', 'magic', 'normal'):
            continue
        m = T.stash_menu(it['page'], it['x'], it['y'])
        if any(lab == 'rare...' and st != 'disabled' for _d, lab, st, _m, _i in T.menu_entries(m)):
            return (it['page'], it['x'], it['y']), m
    T.skip('no stash item offers "rare..."')


@T.test
def rare_asks_for_the_names_and_writes_the_item():
    import mxl_save
    key, m = stash_unique()
    before = T.stash_snap(G.app.path, G.app.data)
    T.invoke(m, 'rare', under='Change item quality')
    T.settle(0.3)
    wins = pick_windows()
    T.eq(len(wins), 1, 'pick windows open after "rare..."')
    if not wins:
        return
    w = wins[0]
    T.check(w.winfo_ismapped(), 'the pick window is not shown')
    T.check(not isinstance(w.master, tk.Menu), f'the pick window is a child of the menu {w.master}, not of the editor')
    rx, ry = G.root.winfo_rootx(), G.root.winfo_rooty()
    T.check(w.winfo_rootx() > rx and w.winfo_rooty() > ry,
            f'the pick window sits at ({w.winfo_rootx()}, {w.winfo_rooty()}), the top left corner, not over the editor')
    T.check(w.winfo_rootx() + w.winfo_width() <= w.winfo_screenwidth() and
            w.winfo_rooty() + w.winfo_height() <= w.winfo_screenheight(), 'the pick window leaves the screen')
    lb = listbox(w)
    T.eq(lb.curselection(), (0,), 'selection in the first-name list')
    lb.focus_force()
    T.pump(3)
    lb.event_generate('<Return>')
    T.settle(0.3)
    wins = pick_windows()
    T.eq(len(wins), 1, 'pick windows open after the first name (the second-name list)')
    if not wins:
        return
    lb = listbox(wins[0])
    lb.focus_force()
    T.pump(3)
    lb.event_generate('<Return>')
    T.settle(0.5)
    T.eq(pick_windows(), [], 'pick windows left open')
    after = T.stash_snap(G.app.path, G.app.data)
    T.only_changed(before, after, chg=[key], what='quality -> rare')
    it = next(i for i in G.app.items if (i['page'], i['x'], i['y']) == key)
    rec = T.rec_of(mxl_save.item_blob(T.read(G.app.path), it))
    T.eq(rec['quality'], 'rare', 'quality in the stash file')


@T.test
def escape_closes_the_pick_window_and_changes_nothing():
    key, m = stash_unique()
    raw = T.read(G.app.path)
    T.invoke(m, 'rare', under='Change item quality')
    T.settle(0.3)
    wins = pick_windows()
    T.eq(len(wins), 1, 'pick windows open after "rare..."')
    if not wins:
        return
    lb = listbox(wins[0])
    lb.focus_force()
    T.pump(3)
    lb.event_generate('<Escape>')
    T.settle(0.3)
    T.eq(pick_windows(), [], 'pick windows left open after Escape')
    T.check(T.read(G.app.path) == raw, 'the stash file changed although the pick was cancelled')


@T.test
def character_tab_item_opens_the_pick_window():
    cw = T.chartab()
    T.select_tab('Character')
    cw.tab.set('inventory')
    cw.show_tab()
    T.settle(0.3)
    raw = T.read(cw.ch.path)
    for slot in sorted(cw.ch.equipped(False)):
        m = T.chartab_menu(('slot', slot))
        if any(lab == 'rare...' and st != 'disabled' for _d, lab, st, _m, _i in T.menu_entries(m)):
            break
    else:
        T.skip('no worn item offers "rare..."')
    T.invoke(m, 'rare', under='Change item quality')
    T.settle(0.3)
    wins = pick_windows()
    T.eq(len(wins), 1, 'pick windows open after "rare..." on the Character tab')
    for w in wins:
        w.destroy()
    T.pump()
    T.check(T.read(cw.ch.path) == raw, 'the character file changed although nothing was picked')
    cw.tab.set('stats')
    cw.show_tab()
    T.select_tab('Stash')


@T.test
def buttons_under_the_list():
    """OK / Cancel sat beside the list, at its top right (the bar was packed after the list)."""
    key, m = stash_unique()
    T.invoke(m, 'rare', under='Change item quality')
    T.settle(0.3)
    wins = pick_windows()
    T.eq(len(wins), 1, 'pick windows open')
    for w in wins:
        lb = listbox(w)
        buttons = [b for f in w.winfo_children() if isinstance(f, tk.Frame) for b in f.winfo_children()
                   if isinstance(b, tk.Button)]
        T.eq(len(buttons), 2, 'buttons of the pick window')
        for b in buttons:
            T.check(b.winfo_rooty() >= lb.winfo_rooty() + lb.winfo_height() - 2,
                    f'button {b.cget("text")!r} at y {b.winfo_rooty()} is not under the list (list ends at '
                    f'{lb.winfo_rooty() + lb.winfo_height()})')
        w.destroy()
    T.pump()


@T.test
def superior_bonus_choices_say_what_they_give():
    """The superior pick listed "Bonus #1", "Bonus #2"...: now the bonus and its range, like the Creator."""
    import re
    for it in sorted(G.app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        m = T.stash_menu(it['page'], it['x'], it['y'])
        if any(lab == 'superior...' and st != 'disabled' for _d, lab, st, _m, _i in T.menu_entries(m)):
            break
    else:
        T.skip('no stash item offers "superior..." with several bonuses')
    T.invoke(m, 'superior', under='Change item quality')
    T.settle(0.3)
    wins = pick_windows()
    T.eq(len(wins), 1, 'pick windows open after "superior..."')
    for w in wins:
        rows = list(listbox(w).get(0, 'end'))
        T.check(len(rows) >= 2, f'superior choices {rows}')
        T.eq([r for r in rows if re.match(r'Bonus #\d+$', r)], [], 'choices that only give a number')
        T.eq([r for r in rows if not re.search(r'\d+-\d+', r)], [], 'choices without a range')
        w.destroy()
    T.pump()


T.main(globals())
