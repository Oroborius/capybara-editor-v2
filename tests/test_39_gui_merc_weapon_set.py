"""The weapon-set switch (I / II) on the mercenary view. A mercenary has one weapon set: his slots are
mxl_char.MERC_SLOTS (the game's inventory.bin "Hireling" rows), set II's slots 11 / 12 are not among them, so
everything dropped or pasted there was refused.

Was a BUG: the switch was offered on the mercenary view in every look - the game-art tabs (base-game character
screen in the light look, Median XL's panel in the dark look), the radio buttons of the plain panel and of the
Character tab - and with set II chosen the mercenary's weapon boxes pointed at slots 11 / 12 (or vanished). Now the
mercenary view always shows his own weapon slots 4 / 5, without a switch (tabs painted out / not drawn, buttons
disabled); the character keeps the switch and the set chosen for him."""
import capytest as T

MODE = 'gui'
RESET = True
ISOLATE = True                          # the plain-panel test turns the game-art panel off for its process
VARIANTS = {'d2': {'MXL_THEME': 'd2'}, 'he': {'MXL_THEME': 'he'}}
G = T.G
WEAPONS = (4, 5)


def hired(ch):
    if ch is None or not ch.merc_hired:
        T.skip('the sample character has no mercenary')


def panel_view(inv, merc):
    inv.merc.set(merc)
    inv.on_view()
    T.pump(4)


def buttons_state(rbs):
    return ['disabled' if rb.instate(['disabled']) else 'normal' for rb in rbs]


def tab_points(inv):
    """Centres of the I / II tabs on the paperdoll canvas of a game-art panel (canvas pixels)."""
    import mxl_d2look as D2
    k = inv.k
    if inv.sigma:
        ox, oy = inv.org
        _a, _b, tw, th = D2.WSET_TAB
        return [((tx - ox + tw * f) * k, (ty - oy + th / 2) * k) for tx, ty in D2.WSET_TABS for f in (0.25, 0.75)]
    tw, th = D2.WSET_TAB_D2
    return [((tx + tw / 2) * k, (ty + th / 2) * k) for tabs in D2.WSET_TABS_D2.values() for tx, ty in tabs]


def drawn_at(cv, x, y):
    """Canvas items over (x, y) except the panel image (the first item)."""
    first = cv.find_all()[:1]
    return [i for i in cv.find_overlapping(x - 1, y - 1, x + 1, y + 1) if i not in first]


def check_panel(inv, what):
    """Character on set II, then the mercenary view, then the character again."""
    hired(inv.ch)
    panel_view(inv, False)
    inv.wset.set(2)
    inv.redraw()
    T.pump(2)
    T.eq([inv.slot_of(b) for b in WEAPONS], [11, 12], f'{what}: character on set II: weapon boxes')
    rbs = getattr(inv, 'wset_rbs', [])
    if not inv.d2:
        T.check(rbs and buttons_state(rbs) == ['normal', 'normal'], f'{what}: character view: switch {buttons_state(rbs)}')
    panel_view(inv, True)
    T.eq([inv.slot_of(b) for b in WEAPONS], list(WEAPONS), f'{what}: mercenary view: weapon boxes point at')
    for b in WEAPONS:
        T.check(b in inv.visible_boxes(), f'{what}: mercenary view: weapon box {b} not shown')
    worn = inv.ch.equipped(True)
    for b in WEAPONS:                    # what the mercenary wears there is what the box gives
        ev = T.panel_ev(('slot', b))
        T.eq(inv.doll_slot(ev.x, ev.y), b, f'{what}: mercenary weapon box {b}: slot under the pointer')
        e, merc = inv.entry_at(inv.doll, ev.x, ev.y)
        T.check(e is worn.get(b), f'{what}: mercenary weapon box {b}: entry {e and e.it["code"]} vs worn {worn.get(b) and worn[b].it["code"]}')
    if inv.d2:
        for x, y in tab_points(inv):
            T.eq(inv.wset_tab_at(x, y), None, f'{what}: mercenary view: a weapon-set tab answers at ({x:.0f}, {y:.0f})')
            T.eq(drawn_at(inv.doll, x, y), [], f'{what}: mercenary view: something drawn on the tab at ({x:.0f}, {y:.0f})')
            inv.on_press(T.ev(inv.doll, x, y))
            inv.on_release(T.ev(inv.doll, x, y))
            T.pump(2)
            T.eq(inv.wset.get(), 2, f'{what}: a click on the tab place changed the weapon set')
    else:
        T.check(rbs and buttons_state(rbs) == ['disabled', 'disabled'], f'{what}: mercenary view: switch {buttons_state(rbs)}')
    panel_view(inv, False)
    T.eq(inv.wset.get(), 2, f'{what}: back on the character: the set chosen for him')
    T.eq([inv.slot_of(b) for b in WEAPONS], [11, 12], f'{what}: back on the character: weapon boxes')
    if inv.d2:
        T.check(any(inv.wset_tab_at(x, y) is not None for x, y in tab_points(inv)), f'{what}: character view: no tab answers')
    else:
        T.check(buttons_state(rbs) == ['normal', 'normal'], f'{what}: back on the character: switch {buttons_state(rbs)}')
    inv.wset.set(1)
    inv.redraw()


@T.test
def game_art_panel():
    inv = G.app.inventory
    if not inv.d2:
        T.skip('no game-art panel in this look (game folder / art missing)')
    check_panel(inv, 'Sigma panel' if inv.sigma else 'base-game panel')


@T.test
def base_game_panel_tabs_painted_out():
    """Light look: the I / II tabs are part of the base game's panel art; the mercenary's panel has them painted
    over with stone (like the ring frames), his other frames untouched."""
    from PIL import Image, ImageStat
    import mxl_d2look as D2
    inv = G.app.inventory
    if not inv.d2 or inv.sigma:
        T.skip('the base-game character screen is not shown in this look')
    hired(inv.ch)

    def shown():
        items = inv.doll.find_all()
        name = inv.doll.itemcget(items[0], 'image') if items else ''
        return next((key[0] for key, ph in D2._photos.items() if str(ph) == name), None)

    def spread(path, box):
        im = Image.open(path).convert('L').crop(box)
        return ImageStat.Stat(im).stddev[0]

    panel_view(inv, False)
    char_panel = shown()
    panel_view(inv, True)
    merc_panel = shown()
    T.check(merc_panel and merc_panel != char_panel, f'the mercenary view shows the character panel: {merc_panel}')
    if not merc_panel:
        return
    a, b = Image.open(char_panel).convert('L'), Image.open(merc_panel).convert('L')
    tw, th = D2.WSET_TAB_D2
    for n, tabs in D2.WSET_TABS_D2.items():
        for tx, ty in tabs:
            box = (tx + 4, ty + 4, tx + tw - 4, ty + th - 4)
            diff = sum(abs(p - q) for p, q in zip(a.crop(box).getdata(), b.crop(box).getdata())) / ((tw - 8) * (th - 8))
            T.check(diff > 8, f'tab {n} at ({tx}, {ty}): still in the mercenary panel (mean difference {diff:.1f})')
    for box in (1, 3, 4, 5):                     # his own frames (helm, body, weapons): untouched inside
        x, y, w, h = D2.GEAR_D2[box]
        inner = (x + 8, y + 8, x + w - 8, y + h - 8)
        T.eq(list(a.crop(inner).getdata()) == list(b.crop(inner).getdata()), True, f'box {box} changed on the mercenary panel')


def art_tabs(path):
    """The I / II tabs of both sides measured in the base-game panel art: [(x0, x1)] of the four tabs (gold border
    columns, inclusive) from left to right, and (y0, y1) of their top / bottom border rows."""
    from PIL import Image
    im = Image.open(path).convert('RGB')

    def gold(x, y):
        r, _g, b = im.getpixel((x, y))
        return r > 100 and r - b > 25

    def runs(xs):
        out = []
        for x in xs:
            if out and x == out[-1][1] + 1:
                out[-1][1] = x
            else:
                out.append([x, x])
        return out
    tabs = []
    for lo, hi in ((10, 140), (380, 510)):                 # the stone above the left / right weapon frame
        r = runs([x for x in range(lo, hi) if gold(x, 55)])
        T.eq(len(r), 4, f'gold borders of the two tabs in row 55, x {lo}..{hi}: {r}')
        if len(r) == 4:
            tabs += [(r[0][0], r[1][1]), (r[2][0], r[3][1])]
    x = (tabs[1][0] + tabs[1][1]) // 2 if len(tabs) > 1 else 105   # the middle of a (raised) II tab
    ys = runs([y for y in range(20, 80) if gold(x, y)])
    return tabs, (ys[0][0], ys[1][1]) if len(ys) >= 2 else (0, 0)


@T.test
def base_game_tabs_where_the_art_has_them():
    """The light look's character screen (base-game art): the gold marker of the active weapon set is drawn on the
    art's own I / II tab, and a click on a tab chooses that set. WSET_TABS_D2 put set I at x 38-83 (it reached
    into the II tab, x 82-130) and the right side's I at 408-453: the marker sat 12 px off, half on the II tab,
    and a click on the left part of an I tab did nothing."""
    import mxl_d2look as D2
    inv = G.app.inventory
    if not inv.d2 or inv.sigma:
        T.skip('the base-game character screen is not shown in this look')
    panel_view(inv, False)
    a = D2.char_art()
    tabs, (y0, y1) = art_tabs(a.char_panel_d2())
    if len(tabs) != 4:
        return
    T.check(y1 - y0 > 20, f'tab rows {y0}..{y1}')
    want = {1: [tabs[0], tabs[2]], 2: [tabs[1], tabs[3]]}         # set -> its tab on the left / right side
    tw, th = D2.WSET_TAB_D2
    for n, rects in D2.WSET_TABS_D2.items():
        for (tx, ty), (ax0, ax1) in zip(rects, want[n]):
            T.check(abs(tx - ax0) <= 2 and abs(tx + tw - 1 - ax1) <= 2 and abs(ty - y0) <= 2 and abs(ty + th - 1 - y1) <= 3,
                    f'set {n}: tab rectangle x {tx}..{tx + tw - 1}, y {ty}..{ty + th - 1}; '
                    f'in the art x {ax0}..{ax1}, y {y0}..{y1}')
    k = inv.k
    gold = '#%02x%02x%02x' % D2.GOLD_TXT
    for n in (1, 2):
        inv.wset.set(n)
        inv.redraw()
        T.pump(2)
        marks = sorted(tuple(round(c / k) for c in inv.doll.coords(i)) for i in inv.doll.find_all()
                       if inv.doll.type(i) == 'rectangle' and inv.doll.itemcget(i, 'outline') == gold)
        T.eq(len(marks), 2, f'set {n}: gold tab markers {marks}')
        for (mx0, my0, mx1, my1), (ax0, ax1) in zip(marks, want[n]):
            T.check(abs(mx0 - ax0) <= 3 and abs(mx1 - ax1) <= 3 and abs(my0 - y0) <= 3 and abs(my1 - y1) <= 3,
                    f'set {n}: marker x {mx0}..{mx1}, y {my0}..{my1}; the tab in the art x {ax0}..{ax1}, y {y0}..{y1}')
        if n == 2:
            shot(inv, 'set2')
    for n, rects in want.items():                  # clicks on the art's tabs: near both ends and in the middle
        for ax0, ax1 in rects:
            for x in (ax0 + 3, (ax0 + ax1) / 2, ax1 - 3):
                inv.wset.set(3 - n)
                inv.redraw()
                y = (y0 + y1) / 2
                inv.on_press(T.ev(inv.doll, x * k, y * k))
                inv.on_release(T.ev(inv.doll, x * k, y * k))
                T.pump(2)
                T.eq(inv.wset.get(), n, f'click at panel ({x:.0f}, {y:.0f}) on the tab of set {n} (x {ax0}..{ax1})')
    gap = (tabs[0][1] + tabs[1][0]) / 2                    # between the I and II tab: neither
    T.eq(inv.wset_tab_at(gap * k, (y0 + y1) / 2 * k), None, f'click between the tabs (x {gap:.0f})')
    inv.wset.set(1)
    inv.redraw()
    shot(inv, 'set1')


def shot(inv, name):
    import os
    import subprocess
    folder = os.environ.get('CAPY_SHOTS')
    if not folder:
        return
    os.makedirs(folder, exist_ok=True)
    G.root.update()
    try:
        subprocess.run(['import', '-window', str(inv.doll.winfo_id()), os.path.join(folder, f'wset-{T.VARIANT}-{name}.png')],
                       timeout=30, capture_output=True)
    except Exception:
        pass


@T.test
def plain_panel():
    """The panel without game art (art missing, or failed): the I / II radio buttons."""
    inv = G.app.inventory
    hired(inv.ch)
    if inv.d2:                                   # the panel's own fallback: drawing the art fails once
        def broken():
            raise RuntimeError('test: no art')
        inv.redraw_d2 = broken
        inv.redraw()
        T.pump(4)
        del inv.redraw_d2
    T.check(not inv.d2, 'the panel did not fall back to the plain layout')
    check_panel(inv, 'plain panel')


@T.test
def character_tab():
    import mxl_char_gui
    cw = T.chartab()
    if cw is None:
        mxl_char_gui.CharacterWindow(G.app, 'inventory')
        cw = T.chartab()
    T.select_tab('Character')
    if cw.tab.get() != 'inventory':
        cw.tab.set('inventory')
        cw.show_tab()
    T.pump(6)
    hired(cw.ch)
    rbs = getattr(cw, 'wset_rbs', [])
    T.check(len(rbs) == 2, f'Character tab: weapon-set buttons {rbs}')
    cw.merc.set(False)
    cw.on_view()
    cw.wset.set(2)
    cw.redraw()
    T.pump(2)
    T.eq([cw.slot_of(b) for b in WEAPONS], [11, 12], 'Character tab, character on set II: weapon boxes')
    T.eq(buttons_state(rbs), ['normal', 'normal'], 'Character tab, character view: switch')
    cw.merc.set(True)
    cw.on_view()
    T.pump(4)
    T.eq([cw.slot_of(b) for b in WEAPONS], list(WEAPONS), 'Character tab, mercenary view: weapon boxes point at')
    T.eq(buttons_state(rbs), ['disabled', 'disabled'], 'Character tab, mercenary view: switch')
    texts = [cw.doll.itemcget(i, 'text') for i in cw.doll.find_all() if cw.doll.type(i) == 'text']
    T.check('II' not in texts, f'Character tab, mercenary view: "II" drawn in a weapon box ({texts})')
    worn = cw.ch.equipped(True)
    for b in WEAPONS:
        e, slot = cw.entry_at(cw.doll, T.chartab_ev(('slot', b)))
        T.eq(slot, b, f'Character tab, mercenary weapon box {b}: slot')
        T.check(e is worn.get(b), f'Character tab, mercenary weapon box {b}: not the item he wears there')
    cw.merc.set(False)
    cw.on_view()
    T.pump(2)
    T.eq(cw.wset.get(), 2, 'Character tab, back on the character: the set chosen for him')
    T.eq(buttons_state(rbs), ['normal', 'normal'], 'Character tab, back on the character: switch')
    cw.wset.set(1)
    cw.redraw()


T.main(globals())
