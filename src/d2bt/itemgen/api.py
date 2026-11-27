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


_RANDOM = {'randclassskill': 83, 'skill-rand': 107}
_UNSAVED = {194}   # item_numsockets: the socket count is in the item header
_DAMAGE = {21: 'one', 22: 'one', 23: 'two', 24: 'two', 159: 'throw', 160: 'throw'}


class RequiredStats(list):
    """required_stats result; `.optional` maps set mask bit -> partial-bonus entries."""
    optional = None


def _saved_range(validator, sid, lo, hi):
    """(lo, hi, never_zero) after the Save Bits mask of the item write path (1-bit Last Wish)."""
    bits = number(validator.item_tables.s(sid, 'save bits'))
    add = number(validator.item_tables.s(sid, 'save add'))
    if not bits:
        return None
    if 0 < bits < 31 and (hi + add > (1 << bits) - 1 or lo + add < 0):
        mask = (1 << bits) - 1
        if hi - lo >= mask:
            return lo, hi, False
        saved = {((x + add) & mask) - add for x in range(lo, hi + 1)}
        return lo, hi, 0 not in saved
    return lo, hi, not lo <= 0 <= hi


def _mod_entries(validator, mods, ilvl, source, weapon=None):
    """Always-present stats of authored mods, merged per (stat, param) as the game sums them."""
    merged = {}
    for mod in mods:
        src = source(mod) if callable(source) else source
        if mod[0] in _RANDOM:
            sid = _RANDOM[mod[0]]
            if mod[0] == 'randclassskill':
                props = validator.item_tables.props
                lo = hi = number(props.get(props.find(mod[0], 'code'), 'val1'))
            else:
                lo = hi = number(mod[1])
            merged.setdefault((sid, None), [0, 0, []])
            entry = merged[(sid, None)]
            entry[0] += lo
            entry[1] += hi
            entry[2].append(src)
            continue
        for (sid, layer), value in validator._bounds([mod], ilvl).items():
            if sid in _UNSAVED:
                continue
            kind = _DAMAGE.get(sid)
            if weapon is not None and kind and kind not in weapon:
                continue
            entry = merged.setdefault((sid, layer), [0, 0, []])
            entry[0] += value.lo
            entry[1] += value.hi
            entry[2].append(src)
    return merged


def _finish(validator, merged):
    try:
        from . import statvocab
        vocab = statvocab.load(tables=validator.directory)
    except Exception:  # noqa: BLE001 - display text is optional
        vocab = None
    out = RequiredStats()
    for (sid, layer), (lo, hi, sources) in sorted(merged.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        if layer is not None:
            saved = _saved_range(validator, sid, lo, hi)
            if saved is None or not saved[2]:
                continue
        try:
            text = statvocab.display(sid, layer or 0, (lo, hi) if lo != hi else lo, vocab=vocab) if vocab else ''
        except Exception:  # noqa: BLE001
            text = ''
        out.append((sid, layer, lo, hi, '+'.join(dict.fromkeys(sources)), text))
    return out


def _weapon_shapes(validator, code):
    """Damage stat families a base carries: one-hand, two-hand, throw."""
    kind, base = validator.bases.get(code, ('', {}))
    if kind != 'weapons':
        # Armor with dmg-norm (Wartraveler) saves the one- and two-hand pairs, never throw.
        return {'one', 'two'} if code else None
    item_type = validator.item_types.get(base.get('type'), {})
    shapes = set()
    if base.get('2handed') == '1':
        shapes.add('two')
    else:
        shapes.add('one')
    if base.get('1or2handed') == '1':
        shapes.add('two')
    if item_type.get('throwable') == '1' or base.get('type') in ('jave', 'ajav'):
        shapes.add('throw')
    return shapes


def required_stats(validator, quality, row_or_key, code='', ilvl=0):
    """Every stat the game ALWAYS puts on an item: [(stat_id, param, min, max, source, display)].

    quality: 7 unique (row_or_key = uniques index), 5 set (set_items index), 'runeword'
    (validator.runewords key; `code` is the base), 4/6/8 magic/rare/crafted (row_or_key =
    iterable of (affix table, 1-based id)). Superior and automagic extras are excluded.
    Properties expand as the validator does (all-stats, res-all, damage families by base,
    per-level, charged with packed capacity, skill params); equal stat ids are summed.
    param is None and min/max are the bonus for random-class / random-skill properties
    (one of several layers is present). Set items return RequiredStats whose `.optional`
    maps each set mask bit to the item-local plus partial/full set bonus entries."""
    weapon = _weapon_shapes(validator, code) if code else None
    optional = None
    if quality == 'runeword':
        entries = _runeword_entries(validator, row_or_key, code, ilvl)
        merged = _merge_all(validator, [e for e in entries if e[0] == 'runeword'], weapon)
        # Saves keep only the T1 mods on the item; each rune's slot mods live on the rune.
        optional = {}
        for rune in dict.fromkeys(e[0] for e in entries if e[0] != 'runeword'):
            optional[rune] = list(_finish(validator, _merge_all(validator, [e for e in entries if e[0] == rune])))
    elif quality in (5, 7):
        row = (validator.set_items if quality == 5 else validator.uniques)[row_or_key]
        mods = list(properties(row, 'prop{} par{} min{} max{}', range(1, 13)))
        merged = _mod_entries(validator, mods, ilvl, lambda m: m[0], weapon)
        if quality == 5:
            optional = _set_optional(validator, row, ilvl, weapon)
    else:
        mods = []
        for table, index in row_or_key:
            if table == 'automagic':
                continue
            found = validator.affixes.get((table, index))
            if found:
                mods.extend(properties(found[1], _MOD, range(1, 4)))
        merged = _mod_entries(validator, mods, ilvl, lambda m: m[0], weapon)
    out = _finish(validator, merged)
    out.optional = optional
    return out


def _runeword_entries(validator, key, code, ilvl):
    return [(src, (sid, layer), lo, hi) for sid, layer, lo, hi, src in runeword_stats(validator, key, code, ilvl)]


def _merge_all(validator, entries, weapon=None):
    merged = {}
    for src, key, lo, hi in entries:
        kind = _DAMAGE.get(key[0])
        if weapon is not None and kind and kind not in weapon:
            continue
        entry = merged.setdefault(key, [0, 0, []])
        entry[0] += lo
        entry[1] += hi
        entry[2].append(src)
    return merged


def _set_optional(validator, row, ilvl, weapon):
    set_row = validator.sets.get(row.get('set'))
    size = validator.set_sizes[row.get('set')]
    out = {}
    for bit in range(5):
        extra = list(properties(row, 'aprop{} apar{} amin{} amax{}', (f'{bit + 1}a', f'{bit + 1}b')))
        mods = [(m, 'item') for m in extra]
        pieces = bit + 2
        if set_row and pieces <= size:
            mods += [(m, 'set') for m in properties(
                set_row, 'pcode{} pparam{} pmin{} pmax{}', (f'{pieces}a', f'{pieces}b'))]
            if pieces == size:
                mods += [(m, 'set') for m in properties(
                    set_row, 'fcode{} fparam{} fmin{} fmax{}', range(1, 9))]
        if mods:
            origin = {id(m): s for m, s in mods}
            merged = _mod_entries(validator, [m for m, _ in mods], ilvl,
                                  lambda m: f'{origin[id(m)]}:{m[0]}', weapon)
            out[bit] = list(_finish(validator, merged))
    return out
