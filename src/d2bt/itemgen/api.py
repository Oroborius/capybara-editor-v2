"""Editor-facing queries over a legit Validator: legal affixes and runeword stats."""
from . import (
    affix_level, affix_level_matches, allowed, class_compatible, number, properties,
)

_KIND = {'magicprefix': 'prefix', 'magicsuffix': 'suffix', 'automagic': 'automagic'}
_MOD = 'mod{}code mod{}param mod{}min mod{}max'


def _base_context(validator, code):
    kind, base = validator.bases[code]
    types = (validator.save_tables.ancestors(base.get('type'))
             | validator.save_tables.ancestors(base.get('type2')))
    return kind, base, types, validator.item_types.get(base.get('type'), {})


def legal_affixes(validator, code, ilvl, quality):
    """Affix rows validate_item accepts on base `code` at ilvl and quality.

    Returns {'prefix': [...], 'suffix': [...], 'automagic': [...]}; each entry is
    {table, id (1-based per table, as saved), name, group, level, maxlevel,
    frequency, mods [(code, param, min, max)]}. Mirrors the per-affix rules of
    Validator.validate_item (type, class, spawnable, rare, frequency, level)."""
    _, base, types, base_type = _base_context(validator, code)
    alvl = affix_level(ilvl, number(base.get('level')), number(base.get('magic lvl')))
    auto_group = base.get('auto prefix')
    out = {'prefix': [], 'suffix': [], 'automagic': []}
    for (table, index), (_, row) in sorted(validator.affixes.items(), key=lambda kv: kv[0][1]):
        if not row.get('name') or not allowed(types, row) or not class_compatible(base_type, row):
            continue
        if table == 'automagic' and row.get('group') != auto_group:
            continue
        if (row.get('spawnable') != '1' or (quality in (6, 8) and row.get('rare') != '1')
                or number(row.get('frequency')) <= 0 or not affix_level_matches(row, alvl)):
            continue
        out[_KIND[table]].append({
            'table': table, 'id': index, 'name': row['name'], 'group': number(row.get('group')),
            'level': number(row.get('level')), 'maxlevel': number(row.get('maxlevel')),
            'frequency': number(row.get('frequency')),
            'mods': list(properties(row, _MOD, range(1, 4))),
        })
    return out


def runeword_stats(validator, runeword_key, code, ilvl=0):
    """Every stat the game applies for a runeword on base `code`.

    runeword_key: key of validator.runewords (the saved runeword id). Returns
    [(stat_id, param, min, max, source)]; source is 'runeword' or the rune code.
    Rune mods use the gems.txt weapon/shield/helm column the validator applies:
    weapons, then shield-type, else helm. Text: statvocab.display(stat, param, (lo, hi))."""
    kind, _, types, _ = _base_context(validator, code)
    row = validator.runewords[runeword_key]
    slot = 'weapon' if kind == 'weapons' else 'shield' if 'shld' in types else 'helm'
    pattern = ' '.join(f'{slot}mod{{}}{field}' for field in ('code', 'param', 'min', 'max'))
    sources = [('runeword', list(properties(row, 't1code{} t1param{} t1min{} t1max{}', range(1, 8))))]
    for rune in (row.get(f'rune{i}') for i in range(1, 7)):
        if rune:
            sources.append((rune, list(properties(validator.gems.get(rune, {}), pattern, range(1, 4)))))
    stats = []
    for source, mods in sources:
        for mod in mods:
            for (sid, layer), value in validator._bounds([mod], ilvl).items():
                stats.append((sid, layer, value.lo, value.hi, source))
    return stats


MAX_ITEM_LEVEL = 110   # Uber Tristram / Pandemonium sources (mlvl 110); the validator accepts 1..110


def ilvl_range(validator, code, quality, row=None):
    """Legal item-level range the validator accepts for an item.

    General: 1..110 (item_level(); the level-110 Uber sources exceed the player cap).
    Set/unique: the row's `lvl` column is the minimum (legit 'identity-level' rule), so
    rows like Hellfire Torch / Annihilus (lvl 110) only exist at ilvl 110.
    """
    lo = 1
    if row is not None and quality in (5, 7):
        lo = max(lo, int(row.get('lvl') or 0))
    return (lo, MAX_ITEM_LEVEL) if lo <= MAX_ITEM_LEVEL else None
