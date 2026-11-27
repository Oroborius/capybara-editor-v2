"""Property rolls and v96 save fields."""


def skill_tab_layer(parameter):
    """ItemMods.cpp:3642 ITEMMODS_PropertyFunc10. Property: param."""
    player_class, tab = divmod(parameter, 3)
    return (player_class << 3) | tab


def skill_layer(skill, level):
    """ItemMods.cpp:3851 ITEMMODS_PropertyFunc19.
    Proc/charge property: param identifies the skill and max supplies level.
    """
    return (skill << 6) | (level & 63)


def proc_level(ilvl, required, max_skill, maximum):
    """ItemMods.cpp:3697 ITEMMODS_PropertyFunc11. Chance-to-cast level, fixed by ilvl when max <= 0."""
    if maximum > 0:
        return maximum
    if maximum == 0:
        return min(max(1, (ilvl - required) // 4 + 1), max_skill if max_skill > 0 else 20)
    divisor = max(1, -(max(1, 99 - required) // maximum))
    return max(1, (ilvl - required) // divisor)


def charged_level_capacity(ilvl, required, max_skill, minimum, maximum):
    """ItemMods.cpp:3851 ITEMMODS_PropertyFunc19 (level at :3873-:3912, capacity at :3914-:3947).
    Skills: reqlevel, maxlvl. Charged property: min (charges), max (level).
    Only the roll of the current charges is random; level and capacity are fixed by ilvl.
    """
    if maximum > 0:
        level = maximum
    elif maximum == 0:
        level = min(max(1, (ilvl - required) // 4 + 1), max_skill if max_skill > 0 else 20)
    else:
        divisor = max(1, max(1, 99 - required) // -maximum)
        level = max(1, (ilvl - required) // divisor)
    capacity = minimum if minimum >= 0 else level * -minimum // 8 - minimum
    capacity = min(255, max(1, capacity)) if minimum else 5
    return level, capacity


def charged_skill(skill, ilvl, required, max_skill, minimum, maximum, roll):
    """ItemMods.cpp:3851 ITEMMODS_PropertyFunc19. Return layer and packed charges at creation."""
    level, capacity = charged_level_capacity(ilvl, required, max_skill, minimum, maximum)
    floor = capacity // 8
    current = floor + 1 + roll(capacity - floor)
    return skill_layer(skill, level), (capacity << 8) | current


def charges_in_bounds(value, low, high):
    """ItemMods.cpp:617 ITEMMODS_UpdateItemWithSkillCharges.
    The charged property sets capacity; the low byte changes with use.
    """
    return (low & ~255) <= value <= high and (value & 255) <= value >> 8


def random_skill_options(low, high):
    """ItemMods.cpp:4261 ITEMMODS_PropertyFunc12, stock skill-rand eligibility.
    skill-rand: min/max skill IDs. The stock book skills are excluded.
    """
    return tuple(skill for skill in range(low, high + 1) if skill not in (42, 50, 60))


def staffmod_class_matches(item_types, skill_class):
    """Items.cpp:2771 ITEMS_AssignStaffModsForFormat; D2Common Items.cpp:2997.
    ItemTypes: StaffMods. Skills: charclass. Call with the primary type row.
    """
    return bool(skill_class) and item_types.get('staffmods') == skill_class


def staffmod_count(chance, drop_level=0):
    """Items.cpp:2799 ITEMS_AssignModernStaffMods. Uses the flagged drop level."""
    chance += drop_level
    return 3 if chance > 90 else 2 if chance > 70 else int(chance > 30 or bool(drop_level))


def staffmod_tier(ilvl, chance, quality):
    """Items.cpp:2821 ITEMS_AssignModernStaffMods. No direct Excel reads."""
    tier = 1 + sum(ilvl > threshold for threshold in (11, 18, 24, 36))
    offset = 1 if chance > 80 else 0 if chance > 30 else -1 if chance > 10 else -2
    tier = max(1, tier + offset)
    return min(4, tier) if quality == 1 else tier


def staffmods(class_first_skill, ilvl, quality, roll, compatible, *, drop_level=0):
    """Items.cpp:2799 ITEMS_AssignModernStaffMods, format 100.
    ItemTypes: StaffMods; Skills: first five-skill blocks and itypea1.
    compatible(skill_id) tests the first skill item-type requirement.
    """
    accepted = set()
    bonuses = {}
    for _ in range(staffmod_count(roll(100), drop_level)):
        tier = staffmod_tier(ilvl, roll(100), quality)
        for _ in range(6):
            skill = class_first_skill + 5 * (tier - 1) + roll(5)
            if skill not in accepted and compatible(skill):
                accepted.add(skill)
                break
        chance = drop_level // 2 + roll(100) if quality != 1 else 0
        bonuses[skill] = 3 if chance >= 90 else 2 if chance >= 60 else 1
    return bonuses


def roll_range(low, high, roll):
    """ItemMods.cpp:2854 ITEMMODS_RollRandomValueInRange.
    Property min/max are interchangeable and both endpoints are inclusive.
    """
    low, high = sorted((low, high))
    return low + roll(high - low + 1) if low != high else low


def raw_save_fields(layer, value, bits, add, param_bits, *, shift=0):
    """Items.cpp:6325 ITEMS_ReadStatFromItemBitstream (inverse, format 96).
    ItemStatCost: Save Bits, Save Add, Save Param Bits, ValShift.
    Input is the engine value, including any internal fixed-point shift.
    """
    encoded = (value >> shift) + add
    if not 0 <= encoded < 1 << bits or not 0 <= layer < 1 << param_bits:
        raise ValueError('stat cannot be represented in its save fields')
    return layer, encoded


def decode_save_value(raw, add, *, shift=0):
    """Items.cpp:6325 ITEMS_ReadStatFromItemBitstream.
    ItemStatCost: Save Add and ValShift. ParsedItem uses shift=0.
    """
    return (raw - add) << shift


def per_level_value(coefficient, character_level):
    """D2Common ItemMods.cpp:4070 ITEMMODS_PropertyFunc17 stores the raw param.
    ItemStatCost op=2/4 uses op param 3 for stock per-level item properties.
    """
    return coefficient * character_level >> 3


def random_skill_bonus(parameter, low, high, roll):
    """ItemMods.cpp:4261 ITEMMODS_PropertyFunc12, stock skill-rand semantics.
    Authored param is the bonus; min/max delimit eligible skill IDs.
    """
    choices = random_skill_options(*sorted((low, high)))
    return (choices[roll(len(choices))], parameter) if choices else None


def random_class_bonus(bonus, low, high, roll):
    """ItemMods.cpp:4200 ITEMMODS_PropertyFunc36, stock randclassskill.
    Properties.val1 supplies the bonus; min/max delimit player class IDs.
    """
    return roll_range(low, high, roll), bonus


def stat_save_fields(row):
    """Items.cpp:6325 ITEMS_ReadStatFromItemBitstream.
    ItemStatCost: Save Bits, Save Add, Save Param Bits, ValShift.
    """
    fields = ('save bits', 'save add', 'save param bits', 'valshift')
    return tuple(int(row.get(field) or 0) for field in fields)
