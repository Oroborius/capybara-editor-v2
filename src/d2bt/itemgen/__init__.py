"""LoD 1.14d creation decisions over lower-case Excel row mappings.

Random decisions take a roll(bound) callback returning an integer in [0, bound).
A nonpositive bound returns zero without consuming RNG, as in D2 seed helpers.
Quality and row IDs are the integers used by the save reader.
"""


def number(value):
    """Read an Excel integer, treating a blank cell as zero."""
    return int(value or 0)


def base_candidates(rows, level, roll, *, act=0, item_type=None,
                    ignore_rarity=False, allow_body_parts=False):
    """ItemMode.cpp:6199/6251/6303 ITEMMODE_SelectRandom*ItemId.
    Weapons/Armor/Misc columns: spawnable, quest, level, rarity, type.
    """
    candidates = []
    for row in rows:
        if (row.get('spawnable') == '1' and not number(row.get('quest'))
                and number(row.get('level')) <= max(1, level)
                and (allow_body_parts or row.get('type') != 'body')):
            if not ignore_rarity and roll(number(row.get('rarity')) - act):
                continue
            if item_type is None or row.get('type') == item_type:
                candidates.append(row)
                if len(candidates) == 1023:
                    break
    return candidates


def pick_base(candidates, roll):
    """ItemMode.cpp:6234 ITEMMODE_SelectRandomArmorItemId, also weapon/misc.
    Select uniformly after the individual Weapons/Armor/Misc rarity tests.
    """
    return candidates[roll(len(candidates))] if candidates else None


def item_level(level):
    """Items.cpp:879/1656 item creation and source level.
    MonStats: monster Level by difficulty. Weapons/Armor/Misc level has
    no effect on this value. The level-110 Uber sources exceed player cap.
    """
    return max(1, level)


def saved_item_level(level):
    """D2Common Items.cpp:6887 write path. Seven bits, no Excel columns."""
    return min(127, item_level(level))


def cube_level(row, clvl, ilvl):
    """PlrTrade.cpp:579 cube output generation. CubeMain: lvl, plvl, ilvl."""
    return min(99, item_level(number(row.get('lvl')) or (
        clvl * number(row.get('plvl')) // 100 + ilvl * number(row.get('ilvl')) // 100)))


def roll_quality(base, ratio, ilvl, roll, *, misc=False, forced=0, superior=False):
    """Items.cpp:436 ITEMS_RollItemQuality, format 100 ambient roll.
    Base: quest, level. ItemRatio: Unique/Rare/Set/Magic/HiQuality/Normal
    and their corresponding Divisor columns. Caller supplies selected ratio.
    """
    if forced:
        return forced
    if number(base.get('quest')):
        return 2
    delta = 1 if misc else max(1, ilvl - number(base.get('level')))
    for quality, key in ((7, 'unique'), (6, 'rare'), (5, 'set'), (4, 'magic'),
                         (3, 'hiquality'), (2, 'normal')):
        if not roll(number(ratio[key]) - delta // number(ratio[key + 'divisor'])):
            return quality
    return 3 if superior else 1


def coerced_quality(quality, base, item_type):
    """ItemMode.cpp:6435 ITEMMODE_AssignItemQualityAndProperties.
    Base: quest, unique. ItemTypes: Normal, Magic, Rare for primary type.
    """
    if item_type.get('normal') == '1':
        return 2
    if number(base.get('unique')) or (item_type.get('magic') == '1' and number(base.get('quest'))):
        return 7
    if (item_type.get('magic') == '1' and quality < 4
            or quality == 6 and item_type.get('rare') != '1'):
        return 4
    return quality


def allowed_qualities(base, item_type, *, equipment, superior, crafted, sets, uniques, magic=True):
    """ItemMode.cpp:6406 ITEMMODE_AssignItemQualityAndProperties and fallbacks.
    Base: Quest, Unique. ItemTypes: Normal, Magic, Rare. Other inputs resolve
    their respective tables and whether the base is armor or a weapon.
    """
    candidates = {2}
    if equipment:
        candidates.add(1)
    if superior:
        candidates.add(3)
    if magic:
        candidates.add(4)
    if sets:
        candidates.add(5)
    if magic and item_type.get('rare') == '1':
        candidates.add(6)
    if uniques or number(base.get('unique')):
        candidates.add(7)
    if crafted:
        candidates.add(8)
    return sorted({coerced_quality(q, base, item_type) for q in candidates})


def affix_level(ilvl, qlvl, magic_level):
    """ItemsMagic.cpp:134 ITEMS_ComputeCraftedMagicAffixLevel.
    Weapons/Armor/Misc: level (qlvl), magic lvl. Clamp the result to 1..99.
    """
    level = max(ilvl, qlvl)
    half = qlvl // 2
    if magic_level:
        return min(99, max(1, level + magic_level))
    return min(99, max(1, level - half if level < 99 - half else 2 * level - 99))


def listed_types(row, prefix):
    """ItemMods.cpp:2698 ITEMMODS_CanItemHaveMagicAffix type arrays.
    Affix/rare-name/runeword columns: contiguous itypeN and etypeN.
    """
    for index in range(1, 8):
        code = row.get(f'{prefix}{index}')
        if not code:
            return
        yield code


def allowed(types, row):
    """ItemMods.cpp:2698/2750 ITEMMODS_CanItemHaveMagic/RareAffix.
    itypeN/etypeN are matched against type and type2 plus ItemTypes Equiv1/2.
    """
    return not types.isdisjoint(listed_types(row, 'itype')) and types.isdisjoint(listed_types(row, 'etype'))


def class_compatible(item_type, row):
    """ItemsMagic.cpp:162 ITEMMODS_AffixPlayerClassisCompatible.
    ItemTypes: Class (primary type); MagicPrefix/Suffix/AutoMagic: classspecific.
    The separate affix class column affects requirements.
    """
    return not row.get('classspecific') or not item_type.get('class') or row['classspecific'] == item_type['class']


def affix_level_matches(row, level):
    """ItemsMagic.cpp:302 ITEMS_RollMagicAffixesNew. Affix: level, maxlevel."""
    maximum = number(row.get('maxlevel'))
    return number(row.get('level')) <= level and (not maximum or level <= maximum)


def affix_weight(row, magic_level):
    """ItemsMagic.cpp:197 ComputeAffixFrequency. Affix: frequency, level."""
    return number(row.get('frequency')) * (number(row.get('level')) if magic_level else 1)


def affix_candidates(rows, types, item_type, level, quality, *, groups=(),
                     auto_group=0, socketable=True):
    """ItemsMagic.cpp:235 ITEMS_RollMagicAffixesNew, expansion path.
    Affix: spawnable, rare, group, frequency, classspecific, level/maxlevel,
    itypeN/etypeN, mod1code. ItemTypes: Class. Base: Auto Prefix, hasinv,
    gemsockets for caller's socketability test. See ItemMods.cpp:2698.
    """
    for index, row in rows:
        group = number(row.get('group'))
        if (row.get('name') and (group == auto_group if auto_group else row.get('spawnable') == '1')
                and (quality not in (6, 8, 9) or row.get('rare') == '1')
                and number(row.get('frequency')) > 0 and group not in groups
                and (socketable or row.get('mod1code') != 'sock')
                and allowed(types, row) and class_compatible(item_type, row)
                and affix_level_matches(row, level)):
            yield index, row


def pick_affix(candidates, magic_level, roll, *, forced=True, preferred=0):
    """ItemsMagic.cpp:197/207/235 ComputeAffixFrequency/MagicItemRollAffix.
    Affix: frequency, level. An extra endpoint falls to the last stored row.
    """
    if not roll(2) and not forced:
        return None
    weighted = []
    for index, row in candidates:
        if index == preferred:
            return index
        weighted.append((index, affix_weight(row, magic_level)))
    if not weighted:
        return None
    ticket = roll(1 + sum(weight for _, weight in weighted))
    for index, weight in weighted[:511]:
        ticket -= weight
        if ticket < 0:
            return index
    return index


def magic_affixes(pick_prefix, pick_suffix):
    """Items.cpp:121 ITEMS_AssignDropMagicAffixes. No direct Excel reads.
    Call each picker with its force flag, after the prefix has been assigned.
    """
    prefix = pick_prefix(False)
    return prefix, pick_suffix(not prefix)


def rare_affix_target(roll, *, jewel=False):
    """ItemsMagic.cpp:441 D2GAME_RollRareItem_6FC53360. ItemTypes: jewl code."""
    return 3 + roll(2) if jewel else (3, 4, 4, 5, 5, 5, 6, 6)[roll(8)]


def craft_affix_minimum(ilvl):
    """ItemsMagic.cpp:755 ITEMS_RollCraftedItem. Stored/output ilvl, no Excel direct."""
    return 1 + sum(ilvl > threshold for threshold in (30, 50, 70))


def craft_affix_target(ilvl, roll):
    """ItemsMagic.cpp:755 ITEMS_RollCraftedItem. CubeMain: derived output ilvl."""
    return max(craft_affix_minimum(ilvl), roll(5))


def rare_name_candidates(rows, types, offset):
    """ItemsMagic.cpp:565 D2GAME_RollRareAffix; ItemsTbls.cpp:687 lookup.
    RarePrefix/RareSuffix: itypeN, etypeN. The suffix table precedes prefixes.
    """
    return [index for index, row in enumerate(rows, offset) if allowed(types, row)]


def properties(row, pattern, ids):
    """ItemMods.cpp:4386 D2COMMON_11292_ItemAssignProperty.
    Extract authored property code, param, min and max from a row.
    """
    for index in ids:
        keys = [column.format(index) for column in pattern.split()]
        if row.get(keys[0]):
            yield tuple(row.get(key, '') for key in keys)


def craft_recipes(rows, code, base, types):
    """PlrTrade.cpp:123 cube input match and :579 output dispatch.
    CubeMain: enabled, input 1 and output. Bases: normcode/ubercode/ultracode.
    Check the equipment identity for stock craft recipes.
    """
    for row in rows:
        target, *output_flags = row.get('output', '').split(',')
        if (row.get('enabled') != '1' or 'crf' not in output_flags
                or target not in ('usetype', 'useitem', code)):
            continue
        source, *flags = row['input 1'].split(',')
        family = {code} | types
        if 'upg' in flags:
            family.update(base.get(key) for key in ('normcode', 'ubercode', 'ultracode'))
        if source in family:
            yield row


def craft_properties(row):
    """PlrTrade.cpp:850 cube output modifiers. CubeMain: mod 1..5, param/min/max."""
    normalized = {key.replace(' ', '_'): value for key, value in row.items()}
    return list(properties(normalized, 'mod_{} mod_{}_param mod_{}_min mod_{}_max', range(1, 6)))


def identity_candidates(rows, code, ilvl, *, unique=False, ladder=True, cow=False):
    """ItemMode.cpp:6686 unique branch; ItemsMagic.cpp:826 ITEMS_RollSetItem.
    UniqueItems: enabled, ladder, code, lvl, rarity. SetItems: item, set, lvl,
    rarity. Cow King's set additionally requires the Hell Bovine drop flag.
    """
    for index, row in enumerate(rows):
        if (row.get('code' if unique else 'item') != code
                or ilvl < number(row.get('lvl'))):
            continue
        if unique:
            if row.get('enabled') != '1' or (not ladder and row.get('ladder') == '1'):
                continue
        elif not cow and row.get('set') == "Cow King's Leathers":
            continue
        yield index, max(1, number(row.get('rarity')))


def pick_identity(candidates, roll, preferred=None):
    """ItemsMagic.cpp:826 ITEMS_RollSetItem and ItemMode.cpp:6686 unique branch.
    SetItems/UniqueItems: rarity, with zero treated as one.
    """
    candidates = tuple(candidates)
    if any(index == preferred for index, _ in candidates):
        return preferred
    ticket = roll(sum(weight for _, weight in candidates))
    for index, weight in candidates:
        if ticket < weight:
            return index
        ticket -= weight
    return None


def unique_upgrade(source_code, target_code, source_base):
    """PlrTrade.cpp:405 cube item family upgrade path.
    Weapons/Armor: normcode, ubercode, ultracode; return cumulative level penalty.
    """
    tiers = [source_base.get(key) for key in ('normcode', 'ubercode', 'ultracode')]
    if source_code not in tiers or target_code not in tiers:
        return 0
    start, end = tiers.index(source_code), tiers.index(target_code)
    return sum((5, 7)[start:end]) if end > start else 0


def runeword_runes(row):
    """D2Common Items.cpp:3377 ITEMS_GetRunesTxtRecordFromItem. Runes: Rune1..6."""
    return tuple(listed_types(row, 'rune'))


def runeword_matches(row, types, quality, sockets, runes, *, quest=False):
    """D2Common Items.cpp:3377 ITEMS_GetRunesTxtRecordFromItem.
    Runes: complete, Rune1..6, itypeN/etypeN. Base: quest.
    """
    return (row.get('complete') == '1' and quality in (2, 3) and not quest
            and sockets == len(runes) and tuple(runes) == runeword_runes(row)
            and allowed(types, row))


def socket_limit(base, item_type, ilvl):
    """D2Common Items.cpp:3036 ITEMS_GetMaxSockets.
    Base: gemsockets. Primary ItemTypes: MaxSock1/25/40.
    """
    column = 'maxsock1' if ilvl <= 25 else 'maxsock25' if ilvl <= 40 else 'maxsock40'
    return min(number(base.get('gemsockets')), number(item_type.get(column)))


def quest_sockets(maximum, quality):
    """SUnitNpc.cpp:2188 Larzuk reward. Uses the base/type socket cap."""
    if quality == 4:
        return tuple(range(1, min(maximum, 2) + 1))
    return (min(maximum, 1) if quality > 4 else maximum,) if maximum else ()


def drop_sockets(maximum, quality, difficulty, chance, start_seed, *, stackable=False,
                 suppressed=False, forced=False):
    """Items.cpp:171 ITEMS_RollDropSockets, called by ItemMode.cpp:6357.
    Uses base stackable and the base/primary-type cap. Difficulty is 0..2.
    """
    maximum = min(maximum, (3, 4, 6)[difficulty])
    if quality not in (2, 3) or stackable or suppressed or not maximum:
        return 0
    return start_seed % maximum + 1 if forced or chance < 33 else 0


def saved_socket_limit(maximum, quality, authored):
    """SUnitNpc.cpp:2188 Larzuk plus ItemMods.cpp:3766 property func 14.
    Authored socket allowance comes from property mod param/min/max columns.
    """
    if quality < 4:
        return maximum
    return min(maximum, max(authored, *quest_sockets(maximum, quality), 0))


def low_quality_variant(rows, roll):
    """ItemsMagic.cpp:1033 ITEMS_ApplyLegacyLowQuality.
    LowQualityItems is sampled uniformly by row index.
    """
    return roll(len(rows)) if rows else None


def superior_candidates(rows, types, primary, *, no_durability=False, throwable=False):
    """ItemsMagic.cpp:969 ITEMS_RollSuperiorItem; ItemMods.cpp:2782
    ITEMMODS_CanItemBeHighQuality. QualityItems: armor/weapon and type flags.
    Base: type, NoDurability. ItemTypes: Throwable and type equivalences.
    """
    special_weapon = {'staf': 'staff', 'bow': 'bow', 'xbow': 'bow',
                      'scep': 'scepter', 'wand': 'wand'}
    special_armor = {'shie': 'shield', 'boot': 'boots', 'glov': 'gloves', 'belt': 'belt'}
    columns = [special_weapon.get(primary) or special_armor.get(primary)]
    if 'weap' in types and primary not in special_weapon:
        columns.append('weapon')
    if 'armo' in types and primary not in special_armor:
        columns.append('armor')
    return [index for index, row in enumerate(rows[:4] if throwable or no_durability else rows)
            if any(row.get(column) == '1' for column in columns)]


def socket_affix_allowed(base, maximum):
    """ItemMods.cpp:2698 and 1.14d Game.exe:0x65E650–0x65E698.
    Base hasinv plus the ilvl/type socket cap permit a socket property.
    """
    return base.get('hasinv') == '1' and maximum > 0


def defense_bounds(base, quality, *, ethereal=False, enhanced=False, cube_ethereal=False):
    """Items.cpp:674 base armor roll; ItemsMagic.cpp:1033 inferior reduction;
    ItemMods.cpp:2568 ethereality and property functions. Base: minac, maxac.
    """
    low, high = number(base.get('minac')), number(base.get('maxac'))
    if quality == 1:
        low, high = max(1, low * 75 // 100), max(1, high * 75 // 100)
    if enhanced:
        low = high = number(base.get('maxac')) + 1
    if ethereal:
        low, high = low * 3 // 2, high * 3 // 2
        if cube_ethereal:
            low, high = low * 3 // 2, high * 3 // 2
    return low, high


def durability(base, quality, roll, *, ethereal=False, indestructible=False):
    """Items.cpp:670 initial roll and :233 ethereality; ItemsMagic.cpp:1033
    inferior durability. Base: durability, nodurability. Return current/max.
    """
    if indestructible or base.get('nodurability') == '1':
        return 0, 0
    maximum = min(255, number(base.get('durability')))
    if quality == 1:
        maximum = max(1, maximum // 3)
    if ethereal:
        maximum = maximum // 2 + 1
        return maximum, maximum
    half = maximum // 2
    return max(int(quality == 1), half + roll(half)), maximum


def ethereal_allowed(kind, base, quality, *, indestructible=False, authored=False):
    """Items.cpp:233 ITEMS_MakeEthereal; ItemMods.cpp:4370 explicit property.
    Base: nodurability, quest. Unique/Set properties: ethereal and indestruct.
    """
    if kind == 'misc' or base.get('nodurability') == '1':
        return False
    return authored or (quality not in (1, 5) and not indestructible and not number(base.get('quest')))


def roll_ethereal(eligible, chance, *, forced=False):
    """Items.cpp:233 ITEMS_MakeEthereal. Uses durability/quality eligibility."""
    return eligible and (forced or chance < 5)


def quantity(base, ilvl, quality, roll, *, gold=False, quiver=False, weapon=False,
             override=0, stack_bonus=0):
    """Items.cpp:631 D2GAME_InitItemStats. Base: stackable, minstack,
    maxstack, spawnstack. ItemTypes: Quiver. Gold and overrides use source data.
    """
    if gold:
        return override or max(1, ilvl + roll(5 * ilvl))
    if not quiver and base.get('stackable') != '1':
        return None
    if not quiver and quality >= 4:
        return 1
    low = number(base.get('minstack'))
    cap = min(511, number(base.get('maxstack')) + stack_bonus)
    spawn = number(base.get('spawnstack'))
    if not weapon and not quiver and spawn and spawn >= low:
        cap = spawn
    return override or max(1, low + roll(cap - low))


def _truncate_divide(value, divisor):
    return value // divisor if value >= 0 else -(-value // divisor)


def roll_treasure_quality(base, item_type, ratio, ilvl, roll, *, magic_find=0,
                          modifiers=None, forced=0):
    """Items.cpp:2365 D2GAME_DropTC_6FC51360, expansion roll.
    Base level/unique/quest; ItemTypes Normal/Magic/Rare; ItemRatio quality,
    Divisor and Min; TreasureClassEx Unique/Set/Rare/Magic modifiers.
    """
    if forced:
        return forced
    fixed = coerced_quality(2, base, item_type)
    if item_type.get('normal') == '1' or fixed == 7:
        return fixed
    delta = ilvl - number(base.get('level'))
    modifiers = modifiers or {}
    if magic_find > -100:
        for quality, key, numerator, denominator in (
            (7, 'unique', 250, 250), (5, 'set', 500, 500),
            (6, 'rare', 600, 600), (4, 'magic', 0, 0),
        ):
            if quality == 6 and item_type.get('rare') != '1':
                continue
            if quality == 4 and item_type.get('magic') == '1':
                return 4
            divisor = 100 + magic_find
            if numerator and magic_find > 10:
                divisor = 100 + magic_find * numerator // (magic_find + denominator)
            base_chance = number(ratio[key]) - _truncate_divide(delta, number(ratio[key + 'divisor']))
            chance = max(_truncate_divide(12800 * base_chance, divisor), number(ratio.get(key + 'min')))
            chance -= _truncate_divide(chance * number(modifiers.get(key)), 1024)
            if chance <= 0 or roll(chance) < 128:
                return quality
    for quality, key in ((3, 'hiquality'), (2, 'normal')):
        chance = (number(ratio[key]) - _truncate_divide(delta, number(ratio[key + 'divisor']))) << 7
        if chance <= 0 or roll(chance) < 128:
            return quality
    return 1


def craft_mod_applies(chance, roll):
    """PlrTrade.cpp:850 cube output modifiers. CubeMain: mod N chance."""
    return not chance or chance >= 100 or roll(100) <= chance


def property_rolls(row, roll):
    """ItemMods.cpp:2854 random range and :4386 property dispatch.
    Returns authored mod1..3 code/param/min/max input tuples with a sampled
    range value. Properties-specific functions can interpret endpoints separately.
    """
    from .stats import roll_range

    for code, param, minimum, maximum in properties(
        row, 'mod{}code mod{}param mod{}min mod{}max', range(1, 4)
    ):
        yield code, param, roll_range(number(minimum), number(maximum), roll)


def item_ratio(rows, code, base, item_type, *, equipment, version=100):
    """ItemsTbls.cpp:1407 DATATBLS_GetItemRatioTxtRecord, Items.cpp:1237/3663
    in D2Common. ItemRatio: Version/Uber/Class Specific; base Code,
    UberCode/UltraCode, Quest, type; ItemTypes: Class. Difficulty is unused.
    """
    uber = (equipment and code in (base.get('ubercode'), base.get('ultracode'))
            and base.get('type') != 'tpot' and not number(base.get('quest')))
    class_specific = bool(item_type.get('class'))
    eligible = [row for row in rows if number(row.get('uber')) == uber
                and number(row.get('class specific')) == class_specific
                and number(row.get('version')) <= version]
    return sorted(eligible, key=lambda row: number(row.get('version')))[-1] if eligible else None


def treasure_entry(entries, no_drop, roll, *, fixed_index=None, effective_players=1):
    """Items.cpp:2142 D2GAME_DropTC_6FC51360. TreasureClassEx: Picks,
    NoDrop, Item1..10/Prob1..10. Entries are compiled (value, weight) pairs;
    caller walks nested TCs and supplies their effective player exponent.
    """
    entries = tuple(entries)
    total = sum(weight for _, weight in entries)
    if not total:
        return None
    if fixed_index is None:
        if no_drop and effective_players > 1:
            probability = (no_drop / (total + no_drop)) ** effective_players
            no_drop = int(total * probability / (1 - probability))
        ticket = roll(total + no_drop) - no_drop
    else:
        ticket = fixed_index
    if ticket < 0:
        return None
    return pick_identity(entries, lambda bound: ticket)


def assign_rare_affixes(target, roll, pick, *, crafted=False):
    """ItemsMagic.cpp:441/637/672 rare/craft assignment.
    Affix table eligibility arrives from pick(side, selected).
    Stop exhausted rare sides. Crafted attempts may fail and consume a slot.
    """
    selected = []
    counts = {'prefix': 0, 'suffix': 0}
    unavailable = set()
    for _ in range(target):
        if crafted:
            preferred = 'suffix' if roll(2) else 'prefix'
        elif 'suffix' in unavailable:
            preferred = 'prefix'
        else:
            preferred = 'suffix' if 'prefix' in unavailable or roll(2) else 'prefix'
        if len(unavailable) == 2:
            break
        other = 'prefix' if preferred == 'suffix' else 'suffix'
        if preferred in unavailable:
            preferred, other = other, preferred
        index = pick(preferred, selected)
        if not index and not crafted:
            unavailable.add(preferred)
            if other not in unavailable:
                preferred = other
                index = pick(preferred, selected)
                if not index:
                    unavailable.add(preferred)
        if index:
            selected.append((preferred, index))
            counts[preferred] += 1
            if counts[preferred] == 3:
                unavailable.add(preferred)
    return selected


def pick_rare_name(rows, types, offset, roll):
    """ItemsMagic.cpp:565 D2GAME_RollRareAffix_6FC53610.
    RarePrefix/RareSuffix: itypeN/etypeN. Return zero for an empty pool.
    """
    choices = rare_name_candidates(rows, types, offset)[:511]
    return choices[roll(len(choices))] if choices else 0


def unique_drop_allowed(index, row, dropped, *, quest=False):
    """Items.cpp:67 and ItemMode.cpp:6718 unique selection finalization.
    UniqueItems: nolimit, plus per-game dropped flags. The ordinary roll
    checks the drop flag before the nolimit path checks and sets it.
    """
    return (quest or index not in dropped) and (row.get('nolimit') == '1' or index <= 4096)


def affix_count_limits(quality, *, jewel=False):
    """Items.cpp:121 and ItemsMagic.cpp:441/672/755, format 100.
    ItemTypes: jewl. Return per-side and total limits on saved random IDs.
    """
    if quality == 4:
        return 1, 2
    if quality == 6:
        return 3, 4 if jewel else 6
    if quality == 8:
        return 3, 4
    return 0, 0


def pick_superior(candidates, count, roll):
    """ItemsMagic.cpp:969 ITEMS_RollSuperiorItem.
    QualityItems type flags determine candidates and the caller's row cap.
    Draw unseen rows until a compatible row is found.
    """
    if not candidates:
        return None
    seen = set()
    while len(seen) < count:
        index = roll(count)
        if index in candidates:
            return index
        seen.add(index)
    return None


def vocab(game_dir=None, *, tables=None):
    """Stat and parameter vocabulary of stock 1.14d; see d2bt.itemgen.statvocab."""
    from .statvocab import build
    return build(game_dir, tables)


from .api import (  # noqa: E402,F401
    MAX_ITEM_LEVEL, RequiredStats, ilvl_range, legal_affixes, possible, required_stats, runeword_stats,
    staffmod_options, staffmod_tiers,
)
