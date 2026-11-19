"""Stat screen of test-druid (MXL_TEST_SAVE_DIR3, a copy of the user's save) against the user's in-game screenshots of
the same save (2026-11-19, Druid level 81, unmorphed, Raid on the left button, Earth Talons on the right, Normal).

Numbers read off the game's pages:
  page 1: Strength 394, Dexterity 843, Vitality 16, Energy 27; Attack Rating 60,671 (Raid) / 53,338 (Earth Talons);
          resistances fire 76 / cold 76 / lightning 78 / poison 77 %, physical 5 %, magic 0 %;
          Defense 44,958, Block Chance 25 %, Grit 11 %
  page 2: Life 3,657 (0 %), Mana 963 (16 %), poison 75-125, Attack Rating row "0 | 1,173%"
  page 3: Bonus to Defense 456 %, Base Block Chance 2 %, mana Regeneration 424 %, Poison Length Red. 75 %,
          Curse Length Red. 155 %, Magic Find 2,589 %
Page 1 Damage is not checked here (still being worked out); it must not move with the passive skills."""
import glob
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves3')


class _Win:
    def __init__(self, E, ch, tot):
        self.st_sim, self.data, self._tot, self.class_names = ch, E.data, tot, []

    def st_totals(self):
        return self._tot

    def st_cls(self):
        return self.st_sim.cls

    def st_value(self, key):
        return 0

    def _sk_name(self, sid):
        return 'skill %d' % sid


def _owlie(E):
    import mxl_char
    import mxl_statscreen as SS
    path = os.path.join(T.fresh_saves(3), 'test-druid.d2s')
    if not os.path.isfile(path):
        T.skip('MXL_TEST_SAVE_DIR3 holds no test-druid.d2s')
    ch = mxl_char.Character(path, E.data)
    tot = SS.char_totals(ch, E.data)
    T.eq(tot['error'], None, 'totals')
    page = object.__new__(SS.StatScreen)
    page.win = _Win(E, ch, tot)
    return SS, ch, tot, page


def _rows(SS, E, page_no):
    out = {}
    for el in SS.screen_table(E.data):
        if el['page'] == page_no and el['type'] in SS.SS_VALUES and not el['flags'] & SS.F_BASE:
            out.setdefault(el['stat'], el)
    if not out:
        T.skip(f'the game table has no page {page_no + 1}')
    return out


@T.test
def page_one_matches_the_game():
    E = T.engine()
    SS, ch, tot, page = _owlie(E)
    T.eq([page.attr_total(s) for s in (0, 2, 3, 1)], [394, 843, 16, 27], 'Strength / Dexterity / Vitality / Energy')
    T.eq(page.derived('attack_rating_1')[0], '60671', 'Attack Rating, Raid')
    T.eq(page.derived('attack_rating_2')[0], '53338', 'Attack Rating, Earth Talons')
    for key, want in (('fire_res', '76%'), ('cold_res', '76%'), ('light_res', '78%'), ('poison_res', '77%'),
                      ('phys_res', '5%'), ('magic_res', '0%')):
        T.eq(page.derived(key)[0], want, key)
    T.eq(page.derived('defense')[0], '44958', 'Defense: (7876 + 843 / 4) x (100 + 456) / 100')
    T.eq(page.derived('block')[0], '25%', 'Block Chance: (0 + 2 + 3) x (843 - 15) / (2 x 81)')
    T.eq(page.derived('grit')[0], '11%', 'Grit: hidden skill 1358, 5 + strength 394 / 61')


@T.test
def page_two_matches_the_game():
    E = T.engine()
    SS, ch, tot, page = _owlie(E)
    rows = _rows(SS, E, 1)
    want = {7: '3657', 76: '0%', 9: '963', 77: '16%', 57: '75', 58: '125', 19: '0', 119: '1173%',
            0: '394', 359: '20%', 2: '843', 360: '85%'}
    for sid, text in want.items():
        T.eq(page.game_value(rows[sid])[0], text, f'page 2 stat {sid}')


@T.test
def page_three_matches_the_game():
    E = T.engine()
    SS, ch, tot, page = _owlie(E)
    rows = _rows(SS, E, 2)
    want = {171: '456%', 20: '2%', 213: '0%', 27: '424%', 110: '75%', 109: '155%', 80: '2589%', 79: '2589%',
            93: '40%', 105: '10%', 102: '421%', 99: '421%', 96: '451%', 60: '19%', 210: '40', 74: '0',
            39: '110%', 43: '120%', 41: '110%', 45: '120%', 36: '5%', 85: '5%', 89: '5'}
    for sid, text in want.items():
        T.eq(page.game_value(rows[sid])[0], text, f'page 3 stat {sid}')


@T.test
def passive_skills_found():
    """Barkskin (+396 % defense, +1440 life), Meditation (+16 % mana, +13 % mana regeneration), the hidden damage
    reduction skill (184 = 11); nothing that feeds the attributes or page 1's damage / attack rating."""
    E = T.engine()
    SS, ch, tot, page = _owlie(E)
    got = SS.skill_passives(ch, E.data, tot)
    for sid, v in ((171, 396), (7, 1440), (77, 16), (27, 13), (184, 11)):
        T.eq(got.get(sid), v, f'passive stat {sid}')
    T.eq(sorted(set(got) & SS.PASSIVE_SKIP), [], 'no attribute / damage / attack rating stat taken from skills')


@T.test
def damage_boxes_do_not_move_with_passive_skills():
    """Page 1 Damage / Attack Rating and page 2's weapon damage rows are the same with and without the passives."""
    E = T.engine()
    SS, ch, tot, page = _owlie(E)
    keys = ('damage_1', 'damage_2', 'attack_rating_1', 'attack_rating_2')
    rows = [el for el in SS.screen_table(E.data) if el['page'] == 1 and el['type'] == SS.T_LABEL
            and el['stat'] in SS.WEAPON_DAMAGE_ROWS]
    with_ = [page.derived(k)[0] for k in keys] + [page.game_value(el)[0] for el in rows]
    real = SS.skill_passives
    try:
        SS.skill_passives = lambda *a: {}
        page._passives = None
        without = [page.derived(k)[0] for k in keys] + [page.game_value(el)[0] for el in rows]
    finally:
        SS.skill_passives = real
    T.eq(with_, without, 'damage / attack rating with and without passive skills')


T.main(globals())
