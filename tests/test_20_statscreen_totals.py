"""Stat screen totals (mxl_statscreen.char_totals / set_bonuses): the item sums of a character wearing set items.

The sample character (MXL_TEST_SAVE_DIR) wears four pieces of Achilios' set (set 53 of the game's sets table, four
pieces: Eagle Eye, Refuge, Sledgehammer, Stealth), so the partial bonuses for 2 and 3 pieces and the eight full-set
bonuses count. The expected numbers are the set's row in sets.bin, written out by hand here (not translated by the
code under test):
  2 pieces: +50 strength (prop 80), +20 max damage (prop 77 "dmg-max": stats 22, 24, 160)
  3 pieces: +50 all resistances (39, 41, 43, 45), +2 to class skills (83, class 2)
  full:     +50 % strength (359), +15 % damage reduction (36), +55-70 damage (21/23/159 min, 22/24/160 max),
            +10 crushing blow (136), +45 all resistances, reanimate as monster 3375 at 2 % (155),
            +50 % attack speed (93), state 175 (98)
Max damage 22 = 20 + 70, all resistances 95 = 50 + 45. These three were left out before (properties with
functions 6 and 24): max damage +20, the reanimate property and the state."""
import glob
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')

SET_ID = 53
FULL = {(0, None): 50, (39, None): 95, (41, None): 95, (43, None): 95, (45, None): 95, (83, 2): 2,
        (359, None): 50, (36, None): 15, (21, None): 55, (23, None): 55, (159, None): 55,
        (22, None): 90, (24, None): 90, (160, None): 90, (136, None): 10, (155, 3375): 2, (93, None): 50,
        (98, 175): 1}


def character(E):
    import mxl_char
    path = sorted(glob.glob(os.path.join(T.fresh_saves(1), '*.d2s')))[0]
    return mxl_char.Character(path, E.data)


def set_pieces(E, ch, SS):
    return [e.it for e in ch.equipped().values() if SS._set_of(e.it, E.data) == SET_ID]


@T.test
def set_bonuses_of_a_worn_set_are_summed():
    E = T.engine()
    import mxl_statscreen as SS
    ch = character(E)
    if len(set_pieces(E, ch, SS)) != 4:
        T.skip(f'the sample character does not wear the four pieces of set {SET_ID}')
    tot = SS.char_totals(ch, E.data)
    T.eq(tot['error'], None, 'no error')
    T.eq(tot['set_pieces'], 4, 'set pieces counted')
    T.eq(tot['set_skipped'], 0, 'no set bonus left out')
    T.eq(dict(tot['by']['sets']), FULL, 'set bonus sums (sets.bin row of the set)')
    # the set bonuses are part of the totals the pages show
    for k, v in FULL.items():
        T.eq(SS.total_of(tot, k[0], k[1]), SS.total_of(tot, k[0], k[1], 'equip')
             + SS.total_of(tot, k[0], k[1], 'charms') + v, f'total of stat {k}')


@T.test
def partial_set_bonuses_by_pieces_worn():
    E = T.engine()
    import mxl_statscreen as SS
    if len(E.data._rows('sets')) <= SET_ID:
        T.skip('no sets table')

    def sums(worn):
        st, skipped = SS.set_bonuses(E.data, SET_ID, worn)
        T.eq(skipped, 0, f'{worn} pieces: nothing left out')
        out = {}
        for s in st:
            k = (s['id'], s['param'])
            out[k] = out.get(k, 0) + s['value']
        return out
    T.eq(sums(1), {}, 'one piece: no bonus')
    T.eq(sums(2), {(0, None): 50, (22, None): 20, (24, None): 20, (160, None): 20}, 'two pieces')
    T.eq(sums(3), {(0, None): 50, (22, None): 20, (24, None): 20, (160, None): 20, (39, None): 50, (41, None): 50,
                   (43, None): 50, (45, None): 50, (83, 2): 2}, 'three pieces')
    T.eq(sums(4), FULL, 'every piece: the full-set bonuses as well')


@T.test
def no_set_bonus_of_the_game_is_left_out():
    E = T.engine()
    import mxl_statscreen as SS
    rows = E.data._rows('sets')
    if not rows:
        T.skip('no sets table')
    left = [(sid, SS.set_bonuses(E.data, sid, 99)[1]) for sid in range(len(rows))]
    T.eq([x for x in left if x[1]], [], 'sets with full-set bonuses that give no stat')


T.main(globals())
