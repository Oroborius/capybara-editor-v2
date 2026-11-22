"""Vanilla 1.14d fixes (user report 2026-11-21): no Median-only Counters page (signets / achievement counters), the
library lists only this game's items, Edit item keeps up to 7 sockets and the socketed jewels (Item Editor), the
hover panel shows the totals with the jewels (aura levels added), by-time stats read like the game, no "(J: ...)"
source breakdowns. Copies of two clone samples only; skipped without the vanilla install."""
import os
import shutil

import capytest as T

MODE = 'gui'
G = T.G
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')
CLONES = os.path.join(T.REPO, '.cache', 'samples', 'mock', 'clones2')
NAMES = ('clone-99', 'clone-02')


def _saves():
    if not all(os.path.isfile(os.path.join(CLONES, n + '.d2s')) for n in NAMES) or \
            not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        return None
    dst = T.guard(os.path.join(T.tmp(), 'v86saves'), 'clone save copies')
    if not os.path.isdir(dst):
        os.makedirs(dst)
        for n in NAMES:
            shutil.copy(os.path.join(CLONES, n + '.d2s'), dst)
    return dst


_S = _saves()
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': GAME, **({'MXL_SAVE_DIR': _S} if _S else {})}
WAIT_TABS = True


def _open(name):
    if _S is None:
        T.skip('no vanilla install / clone samples')
    G.app.select_character(name, G.app.view.get())
    G.app.open_view(keep_page=True)
    T.pump(20, 0.02)
    cw = T.chartab()
    T.check(cw is not None and cw.ch is not None and os.path.basename(cw.ch.path) == name + '.d2s', f'{name} opened')
    return cw


def _tip(it, data):
    import mxl_tooltip
    return [''.join(t for _c, t in L) for L in mxl_tooltip.item_tooltip(it, data, None)]


@T.test
def no_signets_or_counters_in_vanilla():
    cw = _open('clone-99')
    import mxl_char_gui
    import mxl_statnames_ext
    T.check('counters' not in [k for k, _t, _f in mxl_char_gui.EXTRA_PAGES], 'no Counters page registered')
    T.check('counters' not in (getattr(cw, 'extra', None) or {}), 'no Counters page built')
    for sid in (88, 185, 186):
        T.eq(mxl_statnames_ext.fallback_label(sid), None, f'no Median-only name for stat {sid}')


@T.test
def library_lists_this_game_only():
    cw = _open('clone-99')
    import json
    import mxl_itemlib as L
    import mxl_creator
    cr = mxl_creator.Creator(cw.data)
    blob, _rec = cr.build(cr.new_spec('normal', 'rin '))
    e = L.add(bytes(blob), 'T86/Vanilla ring', cw.data)
    T.eq(e.get('game'), L.game_tag(), 'a new entry records its game')
    T.check(L.game_tag().startswith('d2-1.14'), f'vanilla tag: {L.game_tag()}')
    p = os.path.join(L.folder(), L.INDEX)
    with open(p, encoding='utf-8') as f:
        doc = json.load(f)
    doc['items'] += [dict(file=e['file'], name='Untagged (Median)', folder='T86', code='rin '),
                     dict(file=e['file'], name='Essence of Cheat', folder='T86', code='rin ', game='median'),
                     dict(file=e['file'], name='Unknown base', folder='T86', code='zz9 ', game=L.game_tag())]
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(doc, f)
    try:
        names = [x['name'] for x in L.for_game(L.load(), cw.data) if x.get('folder') == 'T86']
        T.eq(names, ['Vanilla ring'], 'entries of this game')
        T.eq(sorted(x['name'] for x in L.for_game(L.load(), None, tag='median') if x.get('folder') == 'T86'),
             ['Essence of Cheat', 'Untagged (Median)'], 'Median entries: tagged + untagged')
        w = L.open_library(G.app)
        T.pump(6)
        shown = sorted(x['name'] for x in w.rows.values() if x.get('folder') == 'T86')
        T.eq(shown, ['Vanilla ring'], 'Library tab rows')
    finally:                                              # leave the copy as it was (other tests use the library)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(dict(doc, items=[x for x in doc['items'] if x.get('folder') != 'T86']), f)
        os.remove(os.path.join(L.folder(), e['file']))


def _ring(slot=None):
    import mxl_char as MC
    inv = G.app.inventory
    inv.merc.set(False)
    inv.on_view()
    T.pump(4)
    for e in inv.ch.entries(False):
        if e.it['code'] == 'rin ' and e.it['location'] == MC.LOC_EQUIPPED and len(e.it.get('socketed') or []) == 7 \
                and slot in (None, e.it['equipped']):
            return e
    raise T.Failed('no equipped ring with 7 jewels')


def _edit(e, change=None):
    import mxl_tabs
    inv = G.app.inventory
    inv.selected, inv.sel_merc = e, False
    inv.edit()
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    T.check(w is not None and w.edit_item is not None and w.spec is not None, 'Item Editor opened on the ring')
    rows = len(w.filler_rows())
    if change:
        change(w)
        T.pump(4)
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        os.system(f'import -window root {os.path.join(shot, "v86_editor_%d.png" % rows)} 2>/dev/null')
    w.commit()
    T.pump(8)
    for kind, title, msg in G.boxes:
        if kind == 'showerror':
            raise T.Failed(f'error box {title!r}: {msg[:200]}')
    return rows


def _ring_on_disk(slot):
    import mxl_char as MC
    import mxl_creator as C
    d = G.app.data
    ch = MC.Character(G.app.character_file(), d)
    e = next(x for x in ch.entries(False) if x.it['code'] == 'rin ' and x.it['location'] == MC.LOC_EQUIPPED
             and x.it['equipped'] == slot)
    return C.decode_blob(bytes(e.blob), d)


def _kid_view(kids):
    return [(k.get('code'), k.get('quality'), T.stats_of(k), T.stats_of(k, 'stats_runeword')) for k in kids]


@T.test
def item_editor_keeps_seven_jewels():
    _open('clone-99')
    e = _ring()
    slot = e.it['equipped']
    rec0, kids0 = _ring_on_disk(slot)
    n194 = sum(v for s, _p, v in T.stats_of(rec0) if s == 194)
    T.eq((rec0.get('sockets') or 0) + n194, 7, 'sample ring: field + 194 = 7')
    T.eq(_edit(e), 7, 'the editor lists the 7 jewels')
    rec, kids = _ring_on_disk(slot)
    T.eq(len(kids), 7, 'no-op edit: 7 jewels on disk')
    T.eq(_kid_view(kids), _kid_view(kids0), 'jewels as they were')
    T.eq([x for x in T.stats_of(rec) if x[0] == 194], [x for x in T.stats_of(rec0) if x[0] == 194], '194 kept')
    T.eq(rec.get('sockets'), rec0.get('sockets'), 'socket field kept')
    e = _ring(slot)
    _edit(e, lambda w: w.set_sockets(5))
    rec, kids = _ring_on_disk(slot)
    T.eq(len(kids), 5, '5 sockets: 5 jewels kept')
    T.eq((rec.get('sockets') or 0) + sum(v for s, _p, v in T.stats_of(rec) if s == 194), 5, '5 sockets: field + 194')
    T.eq(rec.get('socketed_count'), 5, 'socketed count')


@T.test
def hover_panel_shows_jewel_totals():
    cw = _open('clone-02')
    import mxl_format_fix as F
    seen = 0
    for e in cw.ch.items:
        it = e.it
        kids = it.get('socketed') or []
        auras = {}
        for src in [it.get('stats') or []] + [k.get(n) or [] for k in kids for n in ('stats', 'stats_runeword')]:
            for s in src:
                if s['id'] == 151:
                    auras[s.get('param')] = auras.get(s.get('param'), 0) + s['value']
        if not kids or not auras.get(99) or auras[99] <= 31:
            continue
        seen += 1
        cw.panel.show(it)
        T.pump(3)
        txt = cw.panel.detail.get('1.0', 'end')
        T.check(f'Level {auras[99]} Prayer' in txt, f'{it["code"]}: Prayer level {auras[99]} (parent + jewels): '
                                                   f'{txt[:300]!r}')
        T.check(f'({F.shown_sockets(it)})' in txt, f'{it["code"]}: socket count field + 194 in the panel')
        T.check(not any(x in txt for x in ('J:', 'R:', 'G:')), f'{it["code"]}: no socket sources: {txt[:400]!r}')
        if seen >= 3:
            break
    T.check(seen >= 1, f'socketed items with jewel auras: {seen}')
    shot = os.environ.get('CAPY_SHOT_DIR')
    if shot:
        os.system(f'import -window root {os.path.join(shot, "v86_hover.png")} 2>/dev/null')


@T.test
def by_time_and_per_level_stats_read_like_the_game():
    cw = _open('clone-02')
    import mxl_format_fix as F
    T.eq(F.bytime_parts(4194303), (3, 767, 767), 'all bits set: dawn, 767 to 767 (fields carry +256)')
    T.eq(F.bytime_parts(256 << 2 | 356 << 12 | 1), (1, 0, 100), 'dusk, 0 to 100')
    T.eq(F.bytime_parts(0), (0, -256, -256), 'zero bits: -256')
    seen = 0
    for e in cw.ch.items:
        it = e.it
        own = {s['id']: s['value'] for s in it.get('stats') or []}
        if 288 not in own:
            continue
        seen += 1
        txt = '\n'.join(_tip(it, cw.data))
        T.check(str(own[288]) not in txt, f'no raw by-time value: {txt[:300]!r}')
        T.check('(Increases Near Dawn)' in txt, f'by-time period shown: {txt[:300]!r}')
        if own[288] == 4194303:
            T.check('+767' in txt and '+1023' not in txt, f'by-time value less the 256 offset: {txt[:300]!r}')
        if 234 in own:
            T.check('Absorbs Cold Damage (Based on Character Level)' in txt, 'per-level absorb line')
        break
    T.check(seen, 'an item with stat 288')


T.main(globals())
