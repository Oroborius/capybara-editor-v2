"""Character tab, Waypoints / Quests: a mode or act box with only part of its rows ticked shows the "partly ticked"
box (a filled square), not the tick of a fully ticked one - it looked fully ticked (docs/review/gui.md finding
11). Clicking a partly ticked box ticks everything under it (the locked rows stay as they are); the edit is
pending (nothing written before SAVE). Both looks."""
import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {'d2': {'MXL_THEME': 'd2'}, 'he': {'MXL_THEME': 'he'}}
G = T.G


def page(name):
    import mxl_char_gui
    cw = T.chartab()
    if cw is None or getattr(cw, 'ch', None) is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    if cw is None:
        raise T.Failed('no Character tab')
    T.select_tab('Character')
    (getattr(cw, 'discard', None) or cw.reload)()
    T.pump(4)
    cw = T.chartab()
    cw.tab.set(name)
    cw.show_tab()
    T.settle(0.3)
    return cw


def pixels(im):
    return [[im.get(x, y) for x in range(15)] for y in range(13)]


def state(tree, iid):
    vals = [tree.value[l] for l in tree.leaves(iid)]
    return 'on' if vals and all(vals) else ('part' if any(vals) else 'off')


def shown(tree, iid):
    img = str(tree.tv.item(iid, 'image')[0]) if tree.tv.item(iid, 'image') else ''
    return next((k for k, im in tree.img.items() if str(im) == img), img)


def partly(tree):
    """A mode / act row with part of its leaves ticked (and some of them clickable), else None."""
    todo = list(tree.tv.get_children(''))
    while todo:
        iid = todo.pop(0)
        if iid in tree.keys:
            continue
        if state(tree, iid) == 'part' and any(l not in tree.locked and not tree.value[l] for l in tree.leaves(iid)):
            return iid
        todo += list(tree.tv.get_children(iid))
    return None


def click_box(tree, iid):
    tv = tree.tv
    p = tv.parent(iid)
    while p:
        tv.item(p, open=True)
        p = tv.parent(p)
    tv.see(iid)
    T.pump(4)
    x, y, w, h = tv.bbox(iid)
    px = next((i for i in range(x, x + w) if 'image' in str(tv.identify_element(i, y + h // 2))), None)
    if px is None:
        raise T.Failed('no tick box found')
    tv.event_generate('<ButtonPress-1>', x=px + 2, y=y + h // 2)
    tv.event_generate('<ButtonRelease-1>', x=px + 2, y=y + h // 2)
    T.pump(4)


@T.test
def partly_ticked_box_looks_different():
    cw = page('waypoints')
    tree = cw.wp_trees[0]
    on, part = pixels(tree.img['on']), pixels(tree.img['part'])
    T.check(on != part, 'the partly ticked box is drawn like the ticked one')
    T.check(part[6][6] != part[2][2] and part[5][3] == part[2][2],
            'the partly ticked box has no filled square in its middle (or still has the tick)')


@T.test
def waypoints_partial_box_and_click_ticks_all():
    cw = page('waypoints')
    path = cw.ch.path
    before = T.read(path)
    found = False
    for k, tree in enumerate(cw.wp_trees):
        for iid in tree.tv.get_children(''):
            T.check(shown(tree, iid) == state(tree, iid), f'waypoints {k}: mode box shows {shown(tree, iid)!r}, '
                    f'its rows are {state(tree, iid)!r}')
        iid = partly(tree)
        if iid is None:
            continue
        found = True
        T.eq(shown(tree, iid), 'part', f'waypoints {k}: partly ticked box {tree.tv.item(iid, "text")!r}')
        click_box(tree, iid)
        T.check(all(tree.value[l] for l in tree.leaves(iid)), f'waypoints {k}: a click on a partly ticked box '
                'left rows unticked')
        T.eq(shown(tree, iid), 'on', f'waypoints {k}: box after the click')
        T.check(cw.dirty(), 'the click made no pending edit')
        break
    if not found:
        T.skip('the sample character has no partly ticked waypoint box')
    T.eq(T.read(path), before, 'the character file changed before SAVE')


@T.test
def quests_boxes_show_their_state():
    cw = page('quests')
    n = 0
    for k, tree in enumerate(cw.q_trees):
        todo = list(tree.tv.get_children(''))
        while todo:
            iid = todo.pop(0)
            if iid in tree.keys:
                continue
            n += state(tree, iid) == 'part'
            T.check(shown(tree, iid) == state(tree, iid), f'quests {k}: box {tree.tv.item(iid, "text")!r} shows '
                    f'{shown(tree, iid)!r}, its rows are {state(tree, iid)!r}')
            todo += list(tree.tv.get_children(iid))
    T.check(n > 0, 'the sample character has no partly done act / difficulty: nothing checked')


T.main(globals())
