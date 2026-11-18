"""The mercenary view of the Stash tab's equipment panel in the light look, where the panel is the base game's own
character screen (invchar6.dc6 with every equipment frame in the art). The mercenary has no ring slots (the game's
hireling inventory has no ring boxes, see mxl_char.MERC_SLOTS), so his view must not show ring frames that cannot
take an item: they used to stay in the art, inert to clicks and right-clicks."""
import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'he': {'MXL_THEME': 'he'}}
G = T.G
RINGS = (6, 7)


def panel():
    inv = G.app.inventory
    if not inv.d2 or inv.sigma:
        T.skip('the base-game character screen is not shown (game folder / art missing)')
    if inv.ch is None or not inv.ch.merc_hired:
        T.skip('the sample character has no mercenary')
    return inv


def view(inv, merc):
    inv.merc.set(merc)
    inv.on_view()
    T.pump(4)


def shown_panel(inv):
    """File name of the panel image the paperdoll canvas shows."""
    import mxl_d2look as D2
    items = inv.doll.find_all()             # the panel is drawn first, under everything
    T.check(items and inv.doll.type(items[0]) == 'image', 'no panel image under the paperdoll')
    name = inv.doll.itemcget(items[0], 'image') if items else ''
    return next((key[0] for key, ph in D2._photos.items() if str(ph) == name), None)


def box_mean(path, box):
    """Mean brightness inside an equipment box of a panel PNG (the frames' inside is near black)."""
    from PIL import Image, ImageStat
    import mxl_d2look as D2
    x, y, w, h = D2.GEAR_D2[box]
    im = Image.open(path).convert('L').crop((x + 8, y + 8, x + w - 8, y + h - 8))
    return ImageStat.Stat(im).mean[0]


def ring_centre(inv, box):
    import mxl_d2look as D2
    x, y, w, h = D2.GEAR_D2[box]
    return T.ev(inv.doll, (x + w / 2) * inv.k, (y + h / 2) * inv.k)


@T.test
def mercenary_view_has_no_ring_frames():
    import mxl_d2look as D2
    inv = panel()
    view(inv, False)
    char_panel = shown_panel(inv)
    T.eq(char_panel, D2.char_art().char_panel_d2(), 'the character view shows the game panel as it is')
    for b in RINGS:
        T.check(b in inv.visible_boxes(), f'ring box {b} missing on the character view')
    worn = inv.ch.equipped(True)
    view(inv, True)
    merc_panel = shown_panel(inv)
    T.check(merc_panel is not None and merc_panel != char_panel, f'the mercenary view shows the same panel: {merc_panel}')
    for b in RINGS:
        if b in worn:                       # a ring he really wears stays reachable (shown, with its frame)
            continue
        T.check(b not in inv.visible_boxes(), f'ring box {b} is a slot on the mercenary view')
        if merc_panel:
            dark, now = box_mean(char_panel, b), box_mean(merc_panel, b)
            T.check(now > dark + 30, f'ring box {b}: frame still drawn on the mercenary view (brightness {dark:.0f} -> {now:.0f})')
        G.menu = None
        inv.on_menu(ring_centre(inv, b))
        T.pump(2)
        T.check(G.menu is None, f'a menu opened on the hidden ring box {b}')
    for b in (1, 3):                        # his own frames are untouched
        if merc_panel:
            T.check(abs(box_mean(merc_panel, b) - box_mean(char_panel, b)) < 1, f'box {b} changed on the mercenary panel')
    view(inv, False)
    T.eq(shown_panel(inv), char_panel, 'back on the character view: the full panel')


T.main(globals())
