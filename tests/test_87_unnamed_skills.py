"""Vanilla stats use readable game-table names when translated text is missing."""
import os
import shutil

import capytest as T

MODE = 'gui'
G = T.G
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')
MOCK = os.path.join(T.REPO, '.cache', 'samples', 'mock')
FILES = {'clone-101': 'clones', 'clone-41': 'clones', 'clone-74': 'clones2'}


def _saves():
    src = {n: os.path.join(MOCK, d, n + '.d2s') for n, d in FILES.items()}
    if not all(os.path.isfile(p) for p in src.values()) or not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        return None
    dst = T.guard(os.path.join(T.tmp(), 'v87saves'), 'clone save copies')
    if not os.path.isdir(dst):
        os.makedirs(dst)
        for p in src.values():
            shutil.copy(p, dst)
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


def _all(cw):
    for e in cw.ch.items:
        yield e.it
        yield from e.it.get('socketed') or ()


def _unnamed(data, st):
    import mxl_profile as P
    sk = P._stat_skill(st)
    return sk is not None and sk in data.skill_class and not data.skill_names.get(sk)


@T.test
def unit_lines():
    cw = _open('clone-101')
    import mxl_profile as P
    import mxl_stat_text as M
    d = cw.data

    def line(st):
        return [str(ln[1]) for ln in M.stat_lines([st], d)]
    T.eq(line({'id': 197, 'param': 293 << 6 | 60, 'value': 100}),
         [f'100% Chance to cast level 60 {P.vanilla_skill_name(d, 293)} when you Die'], 'chance to cast, unnamed skill')
    T.eq(line({'id': 204, 'param': 310 << 6 | 63, 'value': 3 << 8 | 1}),
         [f'Level 63 {P.vanilla_skill_name(d, 310)} (1/3 Charges)'], 'charges, unnamed skill')
    T.eq(line({'id': 97, 'param': 296, 'value': 63}), [f'+63 to {P.vanilla_skill_name(d, 296)}'], '+n to an unnamed skill')
    T.eq(line({'id': 151, 'param': 298, 'value': 31}), [f'Level 31 {P.vanilla_skill_name(d, 298)} Aura When Equipped'], 'unnamed aura')
    T.eq(line({'id': 195, 'param': 54 << 6 | 2, 'value': 100}), ['100% Chance to cast level 2 Teleport on attack'],
         'named skill unchanged')
    T.eq(line({'id': 97, 'param': 97, 'value': 63}), ['+63 to Smite'], 'named +skill unchanged')
    T.eq(line({'id': 97, 'param': 0, 'value': 1}),
         [f'+1 to {P.vanilla_skill_name(d, 0)}'], 'skill zero keeps its name')
    T.eq(line({'id': 56, 'value': 75}), ['Cold duration: 75'], 'missing ItemStatCost description')
    poison = [str(entry[1]) for entry in M.stat_lines([
        {'id': 57, 'param': None, 'value': 256},
        {'id': 58, 'param': None, 'value': 512},
        {'id': 59, 'param': None, 'value': 75},
    ], d)]
    T.check(any('poison damage over 3 seconds' in text.casefold() for text in poison), 'poison range keeps its duration')
    T.check('Poison duration: 75' in poison, 'poison duration also has a readable stored value')
    two = line({'id': 97, 'param': 176, 'value': 63}) + line({'id': 97, 'param': 180, 'value': 63})
    both = [str(ln[1]) for ln in M.stat_lines([{'id': 97, 'param': 176, 'value': 63},
                                                {'id': 97, 'param': 180, 'value': 63}], d)]
    T.eq(both, two, 'two unnamed skills: two lines, like the game')


@T.test
def sample_items_keep_their_lines():
    hits = 0
    for name in FILES:
        cw = _open(name)
        for it in _all(cw):
            st = [s for s in it.get('stats') or () if _unnamed(cw.data, s) and s['id'] != 151]
            if not st:
                continue
            txt = '\n'.join(_tip(it, cw.data))
            import mxl_profile as P

            T.check('an evil force' not in txt.casefold(), 'placeholder removed')
            for stat in st:
                skill = P.vanilla_skill_name(cw.data, P._stat_skill(stat))
                T.check(skill in txt, f'{skill} appears in the item tooltip')
            hits += 1
    T.check(hits >= 3, f'sample items with unnamed-skill stats: {hits}')


@T.test
def vanilla_item_text_combines_duplicate_values_and_groups():
    cw = _open('clone-101')
    import mxl_stat_text as text
    from mxl_vanilla_he_extras import pack_time_values

    def render(entries, ranges=None):
        stats = [dict(id=sid, param=param, value=value) for sid, param, value in entries]
        return text.stat_lines(stats, cw.data, ranges=ranges)

    sources = {text.range_key(sid, None): [(461, None, 'B')] * 2 for sid in (17, 18)}
    damage = render([(17, None, 461), (18, None, 461)] * 2, sources)
    T.eq([(line[1], line[2], line[3]) for line in damage], [('+922% Enhanced Damage', [], [])],
         'duplicate enhanced damage has one total with no source labels')
    defense = render([(16, None, 30), (16, None, 40)],
                     {text.range_key(16, None): [(30, (25, 35), 'B'), (40, (35, 45), 'RW')]})
    T.eq([(line[1], [part.strip() for _color, part in line[2] + line[3]]) for line in defense],
         [('+70% Enhanced Defense', ['[60-80]'])], 'real roll ranges still combine')

    attributes = render([(sid, None, 5) for sid in (0, 1, 2, 3)] * 2)
    T.eq([line[1] for line in attributes], ['+10 to all Attributes'], 'ItemStatCost description group')
    repair = render([(252, None, 2), (252, None, 3)])
    T.eq([line[1] for line in repair], ['Repairs 1 durability in 20 seconds'], 'special stats also sum')

    teleport, packed = 54 << 6 | 2, 200 << 8 | 200
    charges = render([(204, teleport, packed)] * 2)
    T.eq([line[1] for line in charges], ['Level 2 Teleport (400/400 Charges)'], 'charge bytes sum separately')
    timed = render([(288, None, pack_time_values(3, 700, 700))] * 2
                   + [(288, None, pack_time_values(0, 20, 20))])
    T.check(len(timed) == 2 and any('+1400%' in line[1] and 'Dawn' in line[1] for line in timed)
            and any('+20%' in line[1] and 'Daytime' in line[1] for line in timed),
            'timed values add without overflowing or combining different periods')


T.main(globals())
