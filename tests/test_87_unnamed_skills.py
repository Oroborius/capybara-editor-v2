"""Vanilla 1.14d: item stats that carry a skill with no name (monster skills of skills.bin, on hacked clone items) -
+n to a skill (97), chance to cast (195-203), charges (204-213), aura (151) - are printed the way the game prints a
missing string ('an evil force' for the skill name), not dropped from the tooltip. Named-skill lines stay as they
were. Copies of three clone samples only; skipped without the vanilla install."""
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
    return sk is not None and P._is_skill_row(data, sk) and not data.skill_names.get(sk)


@T.test
def unit_lines():
    cw = _open('clone-101')
    import mxl_profile as P
    import mxl_stat_text as M
    d = cw.data
    evil = P.evil_force(d)
    T.eq(evil, 'an evil force', "the tables' missing-string text")

    def line(st):
        return [str(ln[1]) for ln in M.stat_lines([st], d)]
    T.eq(line({'id': 197, 'param': 293 << 6 | 60, 'value': 100}),
         [f'100% Chance to cast level 60 {evil} when you Die'], 'chance to cast, unnamed skill')
    T.eq(line({'id': 204, 'param': 310 << 6 | 63, 'value': 3 << 8 | 1}),
         [f'Level 63 {evil} (1/3 Charges)'], 'charges, unnamed skill')
    T.eq(line({'id': 97, 'param': 296, 'value': 63}), [f'+63 to {evil}'], '+n to an unnamed skill')
    T.eq(line({'id': 151, 'param': 298, 'value': 31}), [f'Level 31 {evil} Aura When Equipped'], 'unnamed aura')
    T.eq(line({'id': 195, 'param': 54 << 6 | 2, 'value': 100}), ['100% Chance to cast level 2 Teleport on attack'],
         'named skill unchanged')
    T.eq(line({'id': 97, 'param': 97, 'value': 63}), ['+63 to Smite'], 'named +skill unchanged')
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
            n = txt.count(' an evil force')
            T.check(n >= len({(s['id'], s.get('param')) for s in st}),
                    f'{name} {it.get("code")}: unnamed-skill lines shown ({n} for {len(st)} stats): {txt[:300]!r}')
            hits += 1
    T.check(hits >= 3, f'sample items with unnamed-skill stats: {hits}')


T.main(globals())
