"""Skill tooltips (mxl_skilldesc, drawn by the Skills page): the lines the game shows.

The expectations of `lines_read_off_the_game` were read off in-game hover screenshots of level 1 characters without
skill points (the seven classes, 470 tooltips compared line by line; these are the lines whose numbers needed a rule
of their own). The tooltip is built for the same state: no skill learned, character level 1, the class's starting
strength / dexterity / energy / vitality, life 50 + vitality, mana = energy, no items.

Not verifiable from the screenshots and therefore not covered: tooltips at higher skill levels (only "no exception"
and the amount of lines the editor cannot compute, shown as grey raw lines)."""
import struct

import capytest as T

MODE = 'engine'
NEEDS = ('user',)

LEVELS = (0, 1, 20, 50)

# (skill id, name, lines of its tooltip at level 0) - as the game shows them, upper / lower case and runs of blanks
# aside (the game font has capitals only)
GAME_LINES = [
    (1343, 'Devouring Cloud', [
        'Poison Damage: 14-21',
        'over 1 second',
        'Mana Cost: 13',
        'Energy: +11% Increased Damage',
    ]),
    (1387, 'Angel of Death', [
        'Cooldown: 5 seconds',
        'Attack Rating: +30%',
        'Poison Damage: 4-6',
        'over 0.4 seconds',
        '+10% Increased Poison Duration per Base Level',
    ]),
    (356, 'Harvest', [
        'Restores +5% Life in 1 second',
        'Poison Damage: 9-14',
        'over 4 seconds',
        'Devouring Cloud: +10% Poison Duration per Base Level',
    ]),
    (357, 'Infected Roots', ['Poison Damage: 4-6', 'over 0.9 seconds']),
    (355, 'Rain of Fire', ['Fire Damage: 3-5']),
    (1299, 'Armageddon', ['Fire Damage: 6-7']),
    (354, 'Hunting Banshee', ['Cold Damage: 3-4']),
    (1300, 'Frigid Domain', ['Activation Delay: 25 frames', 'Cold Damage: 4-6']),
    (1609, 'Overheat', [
        'sacrifices heat equal to : +1.20 % of your mana regenerated per second',
        'Fire Damage: 31',
        'Activation Frequency Multiplier: 40%',
    ]),
    (1587, 'Crystalline Barrier', ['Cold Damage: 7']),
    (1589, 'Glacial Torrent', ['Cold Damage: 2']),
    (418, 'Tempest', ['Releases 5 bolts', '+1 Bolt per 10 Skill Levels (Max 9)']),
    (1396, 'Night Hawks', ['Max Hawks: 5', 'Damage: 19-27', 'Attack Rating: 200']),       # mnar: 0 without points
    (377, 'Blood Skeleton', ['Attack Rating: 200']),
    (1213, 'Guardian Spirit', ['Attack Rating: 100']),
    (1503, 'Absolution', ['Magic Damage: 2', 'Physical Damage: +2']),       # pdmx of the two Vessels (no points)
    (1528, 'Sentence', ['Magic Damage: 3', 'Physical Damage: +3']),
    (1101, 'Paragon of Fate', ['Unlockable Skill', "Upgrade Paragon's Hammer with a Mark of Fate"]),   # pass: 0
    (1102, 'Paragon of Sanctity', ['Unlockable Skill', "Upgrade Paragon's Hammer with a Mark of Sanctity"]),
    (1437, 'Terror', ['Movement Speed: -60%']),
    (1481, 'Solar Flare', ['Enemy Weapon Physical Damage and Attack Rating: -20%']),
    (392, 'Annihilation', ['Area of Effect: 2.6 yards', 'Wyrms Fire Damage: 19-28']),
    (353, 'Ember Spirit', ['Average Fire Damage: 20-24 per second']),
    (1306, 'Wildfire', ['Average Fire Damage: 28-35 per second']),
    (1125, 'Incineration Trap', [
        'Range: 8 yards',
        'Fire Damage: 8 per second',
        '+0.6 Yards Range per 2 Base Levels',
        'Activation Frequency Multiplier: 100%',
    ]),
    (1127, 'Shockwave Trap', ['+4% Lightning Resistance Pierce per Base Level']),
    (1480, 'Colosseum', ['Enemy Physical Resistance: -10%']),
    (372, 'Widowmaker', ['Converts 70% Physical Damage to Magic']),
    (371, 'Catapult Shot', ['Converts 100% Physical Damage to Fire']),
    (1134, 'Blink', ['Range: 12 yards']),
    (1614, 'Emberstep', ['Range: 16.6 yards']),
    (1218, 'Spirit Walk', ['Restores 1 life on use (based on Max Life)', 'Range: 13.3 yards']),
    (1199, 'Earthquake', ['Magic Damage: 0', '+15% Bonus Magic Damage per Base Level']),
    (1236, 'Iron Spiral', ['Lightning Damage: 0']),
    (1333, 'Charged Talons', ['Lightning Damage: 0-0', '+30% Lightning Damage per Base Level']),
    (1403, 'Soulbond', ['Disables Soulchain', 'Max this Skill: Doubled Dirge Chance to Cast Spell on Death']),
    (1227, 'Stampede', ['Converts 50% Physical Damage to Magic', '+1 Projectile per 9 Base Levels (Max 3)']),
    (1160, 'Cognition', [
        'Cognition',
        'Reach 50 Cognition',
        'Pinnacle: adds 200% of Cognition as Stamina Recovery Bonus',
        '+1 Cognition per Base Level in Mind Skills',
    ]),
    (1163, 'Pneumatic Burst', ['Fires shrapnel at: 3 targets']),
    (1206, 'Snake Stance', [
        'Slows Target by 5%',
        'Poison Damage to Weapon: 2-3',
        'over 1 second',
        '+10% Poison damage per character level above 120',
        '+35% Poison Damage per Base Level',
    ]),
    (1323, 'Survival Instinct', ['(Current Value: 5)']),
    (1138, 'Psionic Storm', ['Magic Feedback Damage: 8% of Total Energy']),
    (250, 'Pestilence', ['Poison Damage: 15-18', 'over 1.6 seconds']),
    (419, 'Lorenado', ['Poison Damage: 14-18', 'over 2.4 seconds']),
    (1037, 'Hyena Strike', ['Poison Damage: 31-35', 'over 10 seconds']),
    (1449, 'Torment', ['Poison Damage: 1']),
    (1042, 'Fire Elementals', ['Damage: 7-17']),
    (351, 'Cascade', ['Duration: 3 seconds']),
    (1248, 'Spirit Reave', [
        'Deals 94% of Combined Spirits Physical Damage per second as Magic',
        'Duration: 6 seconds',
    ]),
    (1135, 'Queen of Blades', ['Time Between Attacks: 1.2 seconds']),
    (1391, 'Death Pact', ['bonuses unlock after putting points into the other trees']),
    (1133, 'Way of the Spider', [
        'Poison Spell Damage: +208%',
        '+2% Poison Spell Damage per Character Level under 100',
    ]),
    (1153, 'Execution', [
        'upgrade - adds magic damage to Broadside after backstabbing',
        'requires Broadside',
        'Adds Magic Damage to Broadside',
    ]),
    (1438, 'Dark Gathering', ['Extra Totems: +0', '+1 Extra Totems per 5 Base Levels']),
    (1246, 'Bloodthirst', [
        'Snake: 150% of your Life Steal added as Poison Pierce',
        'Eagle: 100% of your Life Steal added as Lightning Pierce',
        'Wolf: 25% of your Life Steal added as Critical Strike chance',
    ]),
    (1244, "Hunter's Mark", ['Physical Damage']),
    (1341, 'Ancestral Force', ['Activation Frequency Multiplier: 75%']),
    (1157, 'Deadly Constructs', ['+6% Additional Resistance Pierce per Base Level']),
    (422, 'Arcane Torrent', [
        'Deals Magic Damage based on your Maximum Mana',
        'Deals Feedback Damage based on your Current Mana',
        'Physical Damage: 1-2',
        'Magic Damage: 1-2',
    ]),
    (1580, 'Antimass', ['60% of Mana restored as Life', '21 life restored']),
    (1597, 'Inoculation', ['(Current heal: +32)']),
    (1520, 'Dragonbone Armor', ['(Current Value: 22)']),
    (1117, 'Laserblade', ['Bonus Defense: 15%', '+4% Bonus Defense per Base Level']),
]

# lines the game does NOT show for a character without skill points
GAME_ABSENT = [
    (1227, 'Stampede', '+10% Bonus Damage per Base Level'),                 # 76: second condition met
    (1227, 'Stampede', '+2% Snake Stance Damage Multiplier per Base Level'),
    (1160, 'Cognition', 'Reach 75 Cognition'),
    (1403, 'Soulbond', 'Disabled by Soulchain'),
    (1230, 'Thundergod', 'Lightning Damage: 0'),                            # no damage at all: no line
    (1230, 'Thundergod', '[11]'),                                           # function 11 without text or number
    (1218, 'Spirit Walk', 'SynergiesSpirit Walk'),                          # the second text of a heading
]

# own skill at the level, nothing else learned: (skills without a grey line, grey lines) must not get worse
COVERAGE = {0: (493, 14), 1: (487, 52), 20: (487, 52), 50: (487, 52)}


def SD():
    T.engine()
    import mxl_skilldesc
    return mxl_skilldesc


def class_skills(t):
    return [s for s in range(len(t.sk)) if t.field(s, 0xc, '<I') < 7 and t.desc_index(s) is not None]


def start_stats(t, cls):
    """What a new character of the class has (charstats.bin), in the units of the save (life / mana * 256)."""
    r = t._rows('charstats')[cls]
    st = {0: r[0x30], 2: r[0x31], 1: r[0x32], 3: r[0x33], 12: 1}
    st[6] = st[7] = (50 + r[0x33]) << 8
    st[8] = st[9] = r[0x32] << 8
    return st


def norm(s):
    return ' '.join(s.lower().split())


def lines_of(tip):
    return [(norm(''.join(x for x, _c in segs)), kind) for segs, kind in tip.lines if kind != 'blank']


def new_character_tip(sd, data, sid):
    t = sd.tables(data)
    return sd.tooltip(data, sid, {}, 1, start_stats(t, t.field(sid, 0xc, '<I')))


@T.test
def lines_read_off_the_game():
    sd = SD()
    data = T.engine().data
    t = sd.tables(data)
    n = 0
    for sid, name, expected in GAME_LINES:
        T.eq(norm(sd.split_colours(t.name(sid))[0][0][0]), norm(name), f'skill {sid} is not the skill the test means')
        got = lines_of(new_character_tip(sd, data, sid))
        shown = [text for text, kind in got if kind != 'raw']
        for line in expected:
            T.check(norm(line) in shown, f'{name} ({sid}): the game shows {line!r}; the tooltip has {shown}')
            n += 1
    T.check(n >= 100, f'only {n} lines checked')


@T.test
def lines_the_game_leaves_out():
    sd = SD()
    data = T.engine().data
    for sid, name, line in GAME_ABSENT:
        got = [text for text, _k in lines_of(new_character_tip(sd, data, sid))]
        T.check(not any(norm(line) in text for text in got), f'{name} ({sid}) shows {line!r}, the game does not')


@T.test
def the_two_formerly_wrong_numbers():
    """Devouring Cloud showed 23-35 and Angel of Death 8-11: the standard spell scaling (character level and
    energy) of the skills flagged in skills2.bin was missing."""
    sd = SD()
    data = T.engine().data
    for sid, line in ((1343, 'poison damage: 14-21'), (1387, 'poison damage: 4-6')):
        got = [text for text, _k in lines_of(new_character_tip(sd, data, sid))]
        T.check(line in got, f'skill {sid}: {line!r} expected, tooltip has {got}')
    t = sd.tables(data)
    calc = sd.Calc(t, {}, 1, {1: 25})
    T.eq(calc.energy_factor(), 11, 'energy 25: "Energy: +11% Increased Damage"')
    T.eq(calc.spell_scale(), -39, 'spell scaling of a level 1 character with 25 energy')
    T.eq(sd.Calc(t, {}, 120, {1: 500}).spell_scale(), 1250 * (50 + 67) // 100 - 75, 'spell scaling at level 120')


@T.test
def signed_byte_constants():
    """A one-byte number of a compiled formula is signed (Terror: "Movement Speed: -60%", was +196%)."""
    sd = SD()
    T.eq(sd.tokens(bytes([7, 0xc4, 0]), 0), [(7, -60)], 'byte constant 0xc4')
    T.eq(sd.tokens(bytes([8, 0x82, 0, 0]), 0), [(8, 130)], 'word constant 130')


@T.test
def coverage_does_not_get_worse():
    sd = SD()
    data = T.engine().data
    t = sd.tables(data)
    ids = class_skills(t)
    T.check(len(ids) >= 500, f'only {len(ids)} class skills with a description')
    for lv in LEVELS:
        full = raw = 0
        for sid in ids:
            tip = sd.tooltip(data, sid, {sid: lv} if lv else {}, max(lv, 1), start_stats(t, t.field(sid, 0xc, '<I')))
            full += not tip.raw
            raw += tip.raw
            T.eq(len(tip.reasons), tip.raw, f'skill {sid}: one reason per grey line')
        want_full, want_raw = COVERAGE[lv]
        T.check(full >= want_full, f'level {lv}: {full} of {len(ids)} skills render completely, {want_full} before')
        T.check(raw <= want_raw, f'level {lv}: {raw} grey (raw) lines, {want_raw} before')


@T.test
def no_exception_for_any_skill_and_level():
    """Every class skill at levels 0, 1, 20, 50 - alone, and with every skill of the class at that level (the
    references between skills) - gives a tooltip; a line that cannot be computed is a grey line, not an error."""
    sd = SD()
    data = T.engine().data
    t = sd.tables(data)
    ids = class_skills(t)
    by_class = {}
    for sid in ids:
        by_class.setdefault(t.field(sid, 0xc, '<I'), []).append(sid)
    T.eq(sorted(by_class), list(range(7)), 'classes with skills')
    n = 0
    for cls, sids in sorted(by_class.items()):
        stats = start_stats(t, cls)
        for lv in LEVELS:
            for levels in ([{sid: lv} for sid in sids] if lv else [{}]) + [{s: lv for s in sids}]:
                for sid in (sids if len(levels) != 1 else list(levels)):
                    try:
                        tip = sd.tooltip(data, sid, levels, max(lv, 1), stats)
                    except Exception as e:
                        T.check(False, f'skill {sid} at level {lv} ({len(levels)} skills learned): {e!r}')
                    T.check(tip.lines and tip.name, f'skill {sid} at level {lv}: empty tooltip')
                    for segs, kind in tip.lines:
                        for text, _colour in segs:
                            T.check(isinstance(text, str), f'skill {sid}: a segment is not text')
                    n += 1
    T.check(n > 3500, f'only {n} tooltips built')


@T.test
def unknown_things_stay_raw():
    """What the tables do not explain is not guessed: minion life (mnhp), the Paragon marks once the hidden mark
    skill has a level (pass), a summon's attack rating with points (mnar), a skill's maximum level (maxe, once it
    has points), line function 31 (Exile)."""
    sd = SD()
    data = T.engine().data
    t = sd.tables(data)
    exile = next(s for s in class_skills(t) if norm(t.name(s)) == 'exile')
    for sid, levels, word in ((377, {}, 'mnhp'), (1101, {2049: 1}, 'pass'), (1396, {1396: 1}, 'mnar'),
                              (1403, {1403: 1}, 'maxe'), (exile, {}, 'line function 31')):
        tip = sd.tooltip(data, sid, levels, 1, start_stats(t, t.field(sid, 0xc, '<I')))
        T.check(tip.raw and any(word in r for r in tip.reasons),
                f'skill {sid}: a grey line because of {word} expected, got {tip.reasons}')


T.main(globals())
