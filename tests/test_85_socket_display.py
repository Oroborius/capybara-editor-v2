"""Mock items get their sockets from the save's socket field PLUS item_numsockets (194) lines (field 3 + 194 = 4:
7 jewels in game). The editor drew and printed only the field ("Socketed (3)" with 7 jewels in it); it now shows
field + 194, display only (the item dict and the save keep the field). Copies of the clone samples only."""
import os
import shutil
import types

import capytest as T

MODE = 'gui'
G = T.G
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')
SRC = os.path.join(T.REPO, '.cache', 'samples', 'mock', 'clones2', 'clone-99.d2s')


def _saves():
    if not os.path.isfile(SRC) or not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        return None
    dst = T.guard(os.path.join(T.tmp(), 'socksaves'), 'socket save copies')
    if not os.path.isdir(dst):
        os.makedirs(dst)
        shutil.copy(SRC, dst)
    return dst


_S = _saves()
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': GAME, **({'MXL_SAVE_DIR': _S} if _S else {})}
WAIT_TABS = True


@T.test
def socket_count_is_field_plus_numsockets():
    if _S is None:
        T.skip('no vanilla install / clone samples')
    import mxl_format_fix as F
    import mxl_tooltip
    G.app.select_character('clone-99', G.app.view.get())
    G.app.open_view(keep_page=True)
    T.pump(20, 0.02)
    cw = T.chartab()
    T.check(cw is not None and cw.ch is not None, 'clone opened')
    seen = 0
    shot = os.environ.get('CAPY_SHOT_DIR')
    for e in cw.ch.items:
        it = e.it
        if not it.get('has_sockets') or not it.get('socketed'):
            continue
        extra = sum(s['value'] for s in it.get('stats') or () if s['id'] == 194)
        if not extra:
            continue
        seen += 1
        field = it['sockets']
        T.eq(F.shown_sockets(it), field + extra, f'{it["code"]}: field {field} + 194')
        T.check(F.shown_sockets(it) >= len(it['socketed']), f'{it["code"]}: room for its {len(it["socketed"])} jewels')
        lines = mxl_tooltip.section_sockets(types.SimpleNamespace(it=it, data=cw.data))
        txt = ' '.join(t for L in lines for _c, t in L)
        T.check(f'({field + extra})' in txt, f'{it["code"]} tooltip: {txt!r}')
        T.eq(it['sockets'], field, 'the item keeps its save field')
        import mxl_gui
        img = mxl_gui.icon_layers(it, cw.data, '#000000', mxl_gui.ICONS_DIR)
        T.check(img is not None, f'{it["code"]} icon drawn')
        if shot and hasattr(img, 'save'):
            img.save(os.path.join(shot, f'v85_{it["code"].strip()}_{seen}.png'))
    T.check(seen >= 3, f'socketed items with 194 lines: {seen}')
    # the item editor keeps the jewels and the 194 line: a no-op edit and an item level change
    import mxl_creator
    cr = getattr(G.app, '_creator', None) or mxl_creator.Creator(G.app.data)
    for e in cw.ch.items:
        it = e.it
        n_kids = len(it.get('socketed') or [])
        if n_kids <= (it.get('sockets') or 0):
            continue
        for change in (None, 'ilvl'):
            spec = cr.spec_from_item(it)
            if change:
                spec['ilvl'] = 85
            out = cr.build(spec)
            raw = bytes(out[0])
            rec = mxl_creator.decode_item(raw, cw.data)[0]
            T.eq(rec.get('socketed_count'), n_kids, f'{it["code"]} edit {change}: socketed count')
            want = [x for x in T.stats_of(it) if x[0] == 194]
            T.eq([x for x in T.stats_of(rec) if x[0] == 194], want, f'{it["code"]} edit {change}: 194 line kept')
            T.eq(rec.get('sockets'), it['sockets'], f'{it["code"]} edit {change}: socket field')
        break
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        os.system(f'import -window root {os.path.join(shot, "v85.png")} 2>/dev/null')


T.main(globals())
