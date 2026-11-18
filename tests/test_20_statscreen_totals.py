"""Stat screen totals (mxl_statscreen.char_totals / set_bonuses): the item sums of a character wearing set items;
weapon damage and attack rating (weapon_damage / attack_rating, at the end of this file).

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


# ---- weapon damage and attack rating (page 1 Damage / Attack Rating boxes, page 2 "Weapon Damage" min / max)
# The seven level-1 screenshots listed in docs/statscreen-ref/notes.md (both mouse buttons on Attack, starting gear
# of charstats): class, strength, dexterity, starting weapon code -> damage and attack rating read off the screen.
LEVEL1 = (('Amazon', 0, 25, 25, '132 ', (5, 6), 100), ('Sorceress', 1, 10, 25, '151 ', (4, 5), 100),
          ('Necromancer', 2, 15, 25, '108 ', (5, 8), 100), ('Paladin', 3, 25, 20, '100 ', (4, 6), 75),
          ('Barbarian', 4, 30, 20, '119 ', (6, 7), 75), ('Druid', 5, 25, 20, '114 ', (4, 6), 75),
          ('Assassin', 6, 20, 35, 'j20 ', (4, 6), 150))


class _Equipped:
    def __init__(self, it):
        self.it = it


class _Char:
    """Just what weapon_damage / active_weapon read: the head (active weapon set) and the equipped items."""
    def __init__(self, items, set2=False):
        self.head = bytearray(0x80)
        self.head[0x10] = 1 if set2 else 0
        self._eq = {slot: _Equipped(it) for slot, it in items.items()}

    def equipped(self):
        return self._eq


def _no_totals():
    return {'stats': {}, 'by': {}, 'error': None}


@T.test
def level_one_damage_and_attack_rating_match_the_screenshots():
    E = T.engine()
    import mxl_statscreen as SS
    for name, cls, st, dx, code, dmg, ar in LEVEL1:
        try:
            E.data.base(code).damage['one_hand']
        except Exception:
            T.skip(f'no weapon {code!r} in the game tables')
        ch = _Char({4: {'code': code, 'quality': 'normal'}})
        d = SS.weapon_damage(ch, E.data, _no_totals(), st, dx)
        T.eq((d['min'], d['max']), dmg, f'{name}: damage with the starting weapon')
        T.eq(SS.attack_rating(E.data, cls, _no_totals(), dx), ar, f'{name}: attack rating')


@T.test
def the_inactive_weapon_set_and_a_quiver_do_not_count():
    E = T.engine()
    import mxl_statscreen as SS
    staff, quiver = {'code': '151 ', 'quality': 'normal'}, {'code': 'cqv ', 'quality': 'normal'}
    T.eq(SS.active_weapon(_Char({11: staff, 5: quiver}), E.data), None, 'set II weapon while set I is active')
    T.eq(SS.active_weapon(_Char({11: staff}, set2=True), E.data)[0], 11, 'set II weapon while set II is active')
    d = SS.weapon_damage(_Char({5: quiver}), E.data, _no_totals(), 100, 100)
    T.eq((d['base'], d['name']), (SS.UNARMED, None), 'quiver only: unarmed')


def _tooltip_damage(E, it):
    """(lo, hi) of the "... Damage: lo to hi" line of the host's own item tooltip (base, ED, the weapon's +dmg)."""
    import re
    import mxl_tooltip
    for ln in mxl_tooltip.item_tooltip(it, E.data):
        text = ''.join(x[1] if isinstance(x, tuple) else str(x) for x in (ln if isinstance(ln, list) else [ln]))
        m = re.match(r'(One|Two)-Hand Damage: (\d+) to (\d+)', text)
        if m:
            return m.group(1), int(m.group(2)), int(m.group(3))
    return None


@T.test
def weapon_damage_of_the_sample_characters():
    """XBone (both samples) holds a crossbow in slot 4 of set I, the active set: the boxes show numbers, not '—'.
    Expected: the weapon's own damage from the host's item tooltip + the +min / +max of every other source on the
    two-hand pair, then x (100 + "Weapon Physical Damage" + 16 % per 100 strength (crossbow class)) / 100."""
    E = T.engine()
    import mxl_char
    import mxl_tooltip
    import mxl_statscreen as SS
    checked = 0
    for which in (1, 2):
        try:
            folder = T.fresh_saves(which)
        except T.Skip:
            continue
        ch = mxl_char.Character(sorted(glob.glob(os.path.join(folder, '*.d2s')))[0], E.data)
        w = SS.active_weapon(ch, E.data)
        if w is None or w[0] not in (4, 5):
            continue
        slot, it, base = w
        hand = _tooltip_damage(E, it)
        if hand is None or hand[0] != 'Two' or base.dmg_bonus != (16, 0):
            continue
        tot = SS.char_totals(ch, E.data)
        own = {17: 0, 18: 0, 23: 0, 24: 0}
        for s in mxl_tooltip.all_stats(it, E.data):
            if s.get('id') in own and isinstance(s.get('value'), int):
                own[s['id']] += s['value']
        lo = hand[1] + SS.total_of(tot, 23) - own[23]
        hi = hand[2] + SS.total_of(tot, 24) - own[24]
        strength = (SS.char_stat(ch, 0) + SS.total_of(tot, 0)) * (100 + SS.total_of(tot, 359)) // 100
        pct = SS.total_of(tot, 25) + 16 * strength // 100
        d = SS.weapon_damage(ch, E.data, tot, strength, 0)
        T.eq((d['min'], d['max']), (lo * (100 + pct) // 100, hi * (100 + pct) // 100), f'sample {which}: damage')
        T.eq(d['ed'][1], own[17], f'sample {which}: enhanced damage of weapon + sockets')
        checked += 1
    if not checked:
        T.skip('no sample character holds a two-handed crossbow-class weapon in the active set')


T.main(globals())
