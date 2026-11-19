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
        self.head = bytearray(0x150)
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
    checked = present = 0
    for which in (1, 2):
        try:
            folder = T.fresh_saves(which)
        except T.Skip:
            continue
        present += 1
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
        T.eq((d['min'], d['max']) > (0, 0) and d['name'] is not None, True, f'sample {which}: armed, not a dash')
        checked += 1
    if not checked:
        T.skip('no sample character holds a two-handed crossbow-class weapon in the active set')
    T.eq(checked, present, 'every sample folder checked (both XBone samples hold a crossbow in slot 4 of set I)')


class _Win:
    """What StatScreen.derived / game_value read of the character window: the character, its totals, the data."""
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


def _page(E, ch, tot):
    import mxl_statscreen as SS
    page = object.__new__(SS.StatScreen)          # no canvas: only the value code of the pages
    page.win = _Win(E, ch, tot)
    return page


def _check_pages_agree(E, page, what):
    """Page 2's Attack Rating row shows the items' flat attack rating (stat 19) and their attack rating % - the parts
    page 1's boxes are made of - and its Weapon Damage min / max show the weapon damage."""
    import mxl_statscreen as SS
    rows = {(el['type'], el['stat']): el for el in SS.screen_table(E.data) if el['page'] == 1}
    ar_row, pct_row = rows.get((SS.T_STAT, 19)), rows.get((SS.T_STAT, 119))
    if ar_row is None or pct_row is None:
        T.skip('the game table has no Attack Rating row on page 2')
    # page 1's boxes add the skill on their mouse button (its attack rating %, its share of the weapon damage);
    # page 2's rows are the skill-free numbers underneath
    ar, flat, pct = page.attack_rating()
    for n in (1, 2):
        _sid, _lvl, sk = page.button_skill('attack_rating_%d' % n)
        T.eq(page.derived('attack_rating_%d' % n)[0], str(page.attack_rating(sk[2] if sk else 0)[0]),
             f'{what}: page 1 attack rating box {n}')
        dmg = page.weapon_damage()
        shown = SS.skill_damage(dmg, sk)
        T.eq(page.derived('damage_%d' % n)[0], f"{shown['min']}-{shown['max']}", f'{what}: page 1 damage box {n}')
    T.eq(page.game_value(ar_row)[0], str(flat), f'{what}: page 2 attack rating = the items\' flat attack rating')
    T.eq(page.game_value(pct_row)[0], f'{pct}%', f'{what}: page 2 attack rating % = the % inside page 1')
    dmg = page.weapon_damage()
    lo, hi = (page.game_value(rows[(SS.T_LABEL, s)])[0] for s in SS.WEAPON_DAMAGE_ROWS)
    T.eq(f'{lo}-{hi}', f"{dmg['min']}-{dmg['max']}", f'{what}: page 2 weapon damage = the weapon damage')
    return ar, flat, pct


@T.test
def totals_page_attack_rating_row_shows_the_items():
    """Page 2 "Attack Rating" row (stat 19 | stat 119 % in the game's table): the items' flat attack rating, then
    their attack rating % (in game, test-druid: "0 | 1,173%" while page 1 shows 60,671 / 53,338; an earlier version
    showed page 1's total here, wrongly). Page 1's boxes are still the full attack rating. Both XBone samples, and a
    level-1 character holding a weapon."""
    E = T.engine()
    import mxl_char
    import mxl_statscreen as SS
    checked = 0
    for which in (1, 2):
        try:
            folder = T.fresh_saves(which)
        except T.Skip:
            continue
        ch = mxl_char.Character(sorted(glob.glob(os.path.join(folder, '*.d2s')))[0], E.data)
        tot = SS.char_totals(ch, E.data)
        T.eq(tot['error'], None, f'sample {which}: totals')
        T.eq(SS.active_weapon(ch, E.data) is not None, True, f'sample {which}: holds a weapon')
        ar, flat, _pct = _check_pages_agree(E, _page(E, ch, tot), f'sample {which}')
        T.eq(ar > flat, True, f'sample {which}: page 1 shows more than the items\' flat attack rating')
        checked += 1
    name, cls, st, dx, code, _dmg, ar1 = LEVEL1[5]
    try:
        E.data.base(code)
    except Exception:
        T.skip(f'no weapon {code!r} in the game tables')
    ch = _Char({4: {'code': code, 'quality': 'normal'}})
    ch.cls, ch.level, ch.stats = cls, 1, [(0, None, st), (2, None, dx)]
    page = _page(E, ch, _no_totals())
    page.attr_total = lambda sid: {0: st, 2: dx}.get(sid, 0)
    T.eq(_check_pages_agree(E, page, name)[0], ar1, f'{name}: attack rating of the screenshot')
    if not checked:
        T.skip('no sample character')


# ---- game-data review (docs/review/game-data.md): per-level stats, 442, poison units, resistances, table caps
def _totals(stats):
    """A totals dict as char_totals makes it, every stat from one equipped item: {stat id: value}."""
    tot = {'stats': {}, 'by': {'equip': {}, 'charms': {}, 'sets': {}}, 'n': {}, 'error': None}
    for sid, v in stats.items():
        tot['stats'][(sid, None)] = {'id': sid, 'param': None, 'value': v}
        tot['by']['equip'][(sid, None)] = v
        tot['n'][sid] = 1
    return tot


def _isc_op(E, sid):
    """(op, op param, op base, op stats) of a stat, read straight from the itemstatcost record (offset 84)."""
    import struct
    r = E.data._rows('itemstatcost')[sid]
    return r[84], r[85], struct.unpack_from('<H', r, 86)[0], [t for t in struct.unpack_from('<3H', r, 88) if t != 0xFFFF]


@T.test
def per_level_stats_come_from_the_game_table():
    """218 "+max damage per level" (op 4, level >> 5 -> 22 / 24 / 160) and 203 "Weapon Physical Damage per level"
    (-> 25) were not counted in the damage; the per-level map is now read from itemstatcost."""
    E = T.engine()
    import mxl_statscreen as SS
    T.eq(_isc_op(E, 218), (4, 5, 12, [22, 24, 160]), 'itemstatcost 218')
    T.eq(_isc_op(E, 203), (2, 5, 12, [25]), 'itemstatcost 203')
    m = SS.per_level_map(E.data)
    T.eq(m.get(218), ((22, 24, 160), 5), '218 in the map')
    for pl, target in SS.PER_LEVEL.items():
        T.eq(target in m.get(pl, ((), 0))[0], True, f'per-level stat {pl} -> {target} still there')
    tot = _totals({218: 64, 22: 7})
    T.eq(SS.item_sum(tot, E.data, 22, 80), 7 + (64 * 80 >> 5), 'item_sum of max damage at level 80')
    T.eq(SS.item_sum(tot, E.data, 24, 80), 64 * 80 >> 5, 'two-hand max damage gets it too')


def _dagger(E):
    """A one-handed weapon whose type has a dexterity bonus and no strength bonus (the Druid's dagger class)."""
    for code, b in sorted(E.data.bases.items()):
        d = getattr(b, 'damage', None) or {}
        if any(d.get('one_hand') or ()) and not any(d.get('two_hand') or ()) and not any(d.get('throw') or ()) \
                and tuple(b.dmg_bonus or (0, 0)) == (0, 11):
            return code, b
    T.skip('no one-handed weapon with a 0 / 11 damage bonus')


@T.test
def weapon_damage_counts_per_level_and_strength_bonus_items():
    """Weapon damage with every item stat that feeds it, numbers written out by hand:
    max damage 218 = 64 at level 80 -> +160; W. physical damage 25 = 10 + 203 = 32 at level 80 (+80) -> 90 %;
    442 = 256 with strength 300 -> +300 %; 300 = 128 with dexterity 500 -> +250 %; the dagger's 11 % per 100
    dexterity -> +55 %. Total +695 %."""
    E = T.engine()
    import mxl_statscreen as SS
    T.eq(_isc_op(E, 442), (2, 8, 0, [25]), 'itemstatcost 442: (value x strength) >> 8 into stat 25')
    T.eq(_isc_op(E, 300), (2, 8, 2, [25]), 'itemstatcost 300: (value x dexterity) >> 8 into stat 25')
    code, b = _dagger(E)
    blo, bhi = b.damage['one_hand']
    ch = _Char({4: {'code': code, 'quality': 'normal'}})
    tot = _totals({218: 64, 25: 10, 203: 32, 442: 256, 300: 128})
    d = SS.weapon_damage(ch, E.data, tot, 300, 500, level=80)
    T.eq(d['pct'], 695, 'damage %')
    T.eq(d['flat'], (0, 160), '+min / +max')
    T.eq((d['min'], d['max']), (blo * 795 // 100, (bhi + 160) * 795 // 100), 'damage')
    T.eq(d['wpd'], 90, 'weapon physical damage with the per-level part')
    ch.level = 80                                  # the default level is the character's
    T.eq(SS.weapon_damage(ch, E.data, tot, 300, 500)['flat'], (0, 160), 'level from the character')


def _row(E, page, kind, stat):
    import mxl_statscreen as SS
    for el in SS.screen_table(E.data):
        if el['page'] == page and el['type'] == kind and el['stat'] == stat and not el['flags'] & SS.F_BASE:
            return el
    T.skip(f'no row for stat {stat} on page {page + 1}')


@T.test
def page_two_strength_bonus_row_counts_442():
    """Page 2 "Str. Damage Bonus" (stat 299 in the table): 442 "Additional Strength Damage Bonus" counts like 299."""
    E = T.engine()
    import mxl_statscreen as SS
    code, _b = _dagger(E)
    ch = _Char({4: {'code': code, 'quality': 'normal'}})
    ch.cls, ch.level, ch.stats = 5, 81, []
    page = _page(E, ch, _totals({442: 64}))
    page.attr_total = lambda sid: {0: 400, 2: 843}.get(sid, 0)
    T.eq(page.game_value(_row(E, 1, SS.T_STAT_BONUS, 299))[0], f'{64 * 400 >> 8}%', 'Str. Damage Bonus')
    T.eq(page.game_value(_row(E, 1, SS.T_STAT_BONUS, 300))[0], f'{11 * 843 // 100}%', 'Dex. Damage Bonus (dagger)')


@T.test
def poison_damage_is_shown_in_points_not_256ths():
    """Page 2 poison row: 768-1280 (raw 256ths of a point per frame, the user's screenshot) is shown the way the item
    game's page 2 shows it: raw x frames / 512 (in game, test-druid: raw 768-1280 over 50 frames -> 75-125, half of the
    item tooltip's raw x frames / 256), lengths of the poison items averaged (two items 100 + 150 frames -> 125):
    768 x 125 / 512 = 187, 1280 x 125 / 512 = 312."""
    E = T.engine()
    import mxl_statscreen as SS
    tot = _totals({57: 768, 58: 1280, 59: 250})
    tot['n'][59] = 2
    T.eq(SS.poison_damage(tot), (187, 312, 125, (768, 1280)), 'poison_damage')
    ch = _Char({})
    ch.cls, ch.level, ch.stats = 5, 81, []
    page = _page(E, ch, tot)
    T.eq(page.game_value(_row(E, 1, SS.T_STAT, 57))[0], '187', 'page 2 min poison')
    T.eq(page.game_value(_row(E, 1, SS.T_STAT, 58))[0], '312', 'page 2 max poison')
    T.eq(SS.poison_damage(_totals({})), None, 'no poison')


@T.test
def resistances_get_the_difficulty_penalty_and_the_cap():
    """Page 1 resistances: sum + the penalty of the difficulty the save was last in (header 0xA8, 0x80 bit;
    difficultylevels.bin first field: 0 / -30 / -70 in Sigma), capped at 75 + maximum resist (at most 95).
    Before: the raw sum (110 % / 120 % on the user's screenshot)."""
    E = T.engine()
    import struct
    import mxl_statscreen as SS
    pens = [struct.unpack_from('<i', r, 0)[0] for r in E.data._rows('difficultylevels')]
    T.eq(pens, [0, -30, -70], 'difficultylevels.bin resistance penalties')
    ch = _Char({})
    ch.cls, ch.level, ch.stats = 5, 81, []
    T.eq(SS.difficulty_of(ch), None, 'no difficulty byte set')
    ch.head[0xA8 + 2] = 0x80
    T.eq(SS.difficulty_of(ch), 2, 'Hell')
    page = _page(E, ch, _totals({39: 110, 43: 120, 40: 5, 41: 50, 45: 300, 46: 30}))
    T.eq(page.derived('fire_res')[0], '40%', 'fire 110 - 70')
    T.eq(page.derived('cold_res')[0], '50%', 'cold 120 - 70')
    T.eq(page.derived('light_res')[0], '-20%', 'lightning 50 - 70')
    T.eq(page.derived('poison_res')[0], '95%', 'poison 300 - 70 capped at 75 + 30 -> 95')
    ch.head[0xA8 + 2] = 0
    ch.head[0xA8] = 0x80
    T.eq(page.derived('fire_res')[0], '80%', 'Normal: 110 capped at 75 + 5')
    T.eq(page.derived('cold_res')[0], '75%', 'Normal: 120 capped at 75')


@T.test
def table_caps_are_applied():
    """Rows of the game's table with a cap (absorb %: 40) do not show more than the cap."""
    E = T.engine()
    import mxl_statscreen as SS
    rows = [el for el in SS.screen_table(E.data) if el['cap'] and el['type'] == SS.T_STAT]
    if not rows:
        T.skip('no row with a cap')
    el = rows[0]
    ch = _Char({})
    ch.cls, ch.level, ch.stats = 5, 81, []
    page = _page(E, ch, _totals({el['stat']: el['cap'] + 15}))
    T.eq(page.game_value(el)[0], f"{el['cap']}%", 'capped')
    page = _page(E, ch, _totals({el['stat']: el['cap'] - 1}))
    T.eq(page.game_value(el)[0], f"{el['cap'] - 1}%", 'below the cap')


@T.test
def page1_boxes_use_the_skill_on_each_mouse_button():
    """Page 1's left / right Damage and Attack Rating boxes apply the skill on that button (skills.bin): Raid (350,
    srcdam 90 = 70 % weapon damage (its own 8-8 is not added: in game Raid's box is exactly 90/128 of
    Earth Talons'), +105 % attack rating at level 20 - the numbers of the
    in-game Raid tooltip) and Earth Talons (1295, srcdam 128, no physical damage of its own: the weapon damage).
    A druid (class 5) with 20 hard points in both and an unarmed set, so the weapon damage is the plain 1-2 + items."""
    E = T.engine()
    import struct
    import mxl_statscreen as SS
    T.eq(SS.skill_attack(E.data, 350, 20), (90, (8, 8), 105), 'Raid at level 20')
    T.eq(SS.skill_attack(E.data, 1295, 20), (128, (0, 0), 0), 'Earth Talons at level 20')
    T.eq(SS.skill_attack(E.data, 0, 20), None, 'no skill')
    ch = _Char({})
    ch.cls, ch.level, ch.stats = 5, 81, []
    ch.skill_levels = lambda: {350: 18, 1295: 20}
    struct.pack_into('<II', ch.head, 0x78, 350, 1295)
    tot = _totals({21: 219, 22: 638})                       # unarmed 1-2 + 219-638 = 220-640 before the skill
    page = _page(E, ch, tot)
    base = SS.weapon_damage(ch, E.data, tot, page.attr_total(0), page.attr_total(2), ch.level)
    T.eq((base['min'], base['max']), (220, 640), 'weapon damage')
    T.eq(SS.skill_level(ch, E.data, _totals({127: 2}), 350), 20, 'hard 18 + 2 all skills')
    T.eq(SS.skill_level(ch, E.data, _totals({127: 2}), 1773), 0, 'no hard points: +all skills do not count')
    tot2 = _totals({21: 219, 22: 638, 127: 2, 2: 500})        # 500 dexterity: a positive attack rating
    page = _page(E, ch, tot2)
    T.eq(page.derived('damage_1')[0], f'{220 * 90 // 128}-{640 * 90 // 128}', 'Raid: 70 %, its own 8-8 not added')
    T.eq(page.derived('damage_2')[0], '220-640', 'Earth Talons: the weapon damage')
    ar, _flat, pct = page.attack_rating()
    T.eq(pct, 0, 'no item attack rating %')
    T.eq(page.derived('attack_rating_2')[0], str(ar), 'Earth Talons: no attack rating bonus')
    T.eq(page.derived('attack_rating_1')[0], str(page.attack_rating(105)[0]), 'Raid: +105 %')
    T.check(page.attack_rating(105)[0] > ar, 'Raid raises the attack rating')
    struct.pack_into('<I', ch.head, 0x78, 0)
    T.eq(page.derived('damage_1')[0], '220-640', 'Attack: the weapon damage')


T.main(globals())
