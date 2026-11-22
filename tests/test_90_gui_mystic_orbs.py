"""Item Editor, "Apply Mystic Orb" (Median XL): the orbs that fit the edited item, a count capped at the orb's
per-item max minus the ones on it, and Apply putting the stats + Required Level + counter on the item (pending
until Replace item). Engine side: test_90_mystic_orbs."""
import os

import capytest as T

MODE = 'gui'
G = T.G


@T.test
def apply_orb_in_item_editor():
    import mxl_creator_gui as CG
    import mxl_tabs
    import mxl_creator
    cr = mxl_creator.Creator(G.app.data)
    pick = next((it for it in G.app.items if it.get('quality') not in (None, 'normal')
                 and cr.orbs_for(it['code'], it.get('quality'))), None)
    if pick is None:
        T.skip('no stash item a mystic orb fits')
    G.app.selected = pick
    CG.edit_selected(G.app)
    T.pump(12)
    w = mxl_tabs.built_owner('Creator')
    T.check(w is not None and w.edit_item is not None, 'the Item Editor did not open')
    T.check(getattr(w, '_orb_widgets', None) is not None, 'Apply Mystic Orb row built')
    cb, sp, _btn, info = w._orb_widgets
    tot = w._edit_totals()
    labels = list(cb.cget('values'))
    orbs = w.cr.orbs_for(w.spec['code'], w.spec['quality'])
    T.eq(len(labels), len(orbs), 'one entry per orb that fits')
    k = next((i for i, (c, _o) in enumerate(orbs) if w.cr.orb_room(c, tot) >= 2), None)
    if k is None:
        T.skip('every orb already at its max on this item')
    orb = orbs[k][0]
    room = w.cr.orb_room(orb, tot)
    cb.set(labels[k])
    sp.set(str(room + 7))
    T.pump(3)
    T.eq(sp.get(), str(room), 'count capped at what the item can still take')
    T.check('adds' in info.cget('text'), f'preview: {info.cget("text")!r}')
    sp.set('2')
    T.pump(3)
    w.apply_orb(orb, 2)
    T.pump(6)
    row = w.cr._orb_table()[orb]['row'] or None
    after = w._edit_totals()
    T.eq(after.get((290, row), 0) - tot.get((290, row), 0), 2, 'counter +2')
    T.eq(after, w.cr.orb_result(orb, 2, tot, w.spec['code']), 'item totals = the engine result')
    T.eq(w.cr.orb_room(orb, after), room - 2, 'room shrinks')
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        os.system(f'import -window root {os.path.join(shot, "v90.png")} 2>/dev/null')


T.main(globals())
