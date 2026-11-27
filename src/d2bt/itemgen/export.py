"""Stock-table adapter and compact, lossless ilvl buckets."""

from collections import defaultdict

from . import (
    affix_candidates, affix_level, allowed, allowed_qualities, class_compatible,
    craft_recipes, identity_candidates, number, properties, quest_sockets,
    runeword_runes, saved_socket_limit, socket_affix_allowed, socket_limit, superior_candidates, unique_upgrade,
)


def _mods(row, pattern, count):
    return list(properties(row, pattern, range(1, count + 1)))


def build_export(data, *, ladder=True):
    """Export candidate IDs with a shared catalog of authored property ranges."""
    affix_rows = defaultdict(list)
    affix_catalog = defaultdict(dict)
    for (side, index), (_, row) in data.affixes.items():
        affix_rows[side].append((index, row))
        affix_catalog[side][index] = {
            'name': row.get('name'), 'group': number(row.get('group')),
            'frequency': number(row.get('frequency')), 'level': number(row.get('level')),
            'mods': _mods(row, 'mod{}code mod{}param mod{}min mod{}max', 3),
        }
    identities = {}
    for key, rows in (('sets', data.set_items), ('uniques', data.uniques)):
        identities[key] = {
            index: {'name': row['index'], 'level': number(row.get('lvl')),
                    'mods': _mods(row, 'prop{} par{} min{} max{}', 12)}
            for index, row in enumerate(rows) if row.get('item' if key == 'sets' else 'code')
        }
    runewords = {
        index: {'name': row['rune name'], 'runes': runeword_runes(row),
                'mods': _mods(row, 't1code{} t1param{} t1min{} t1max{}', 7)}
        for index, row in data.runewords.items()
    }
    bases = {}
    for code, (kind, base) in sorted(data.bases.items()):
        primary = base.get('type', '')
        types = data.save_tables.ancestors(primary) | data.save_tables.ancestors(base.get('type2'))
        item_type = data.item_types.get(primary, {})
        qlvl = number(base.get('level'))
        magic_level = number(base.get('magic lvl'))
        auto_group = number(base.get('auto prefix'))
        superior = superior_candidates(data.superior or [], types, primary,
                                       no_durability=base.get('nodurability') == '1',
                                       throwable=item_type.get('throwable') == '1')
        applicable = {
            side: [(index, row) for index, row in rows
                   if allowed(types, row) and class_compatible(item_type, row)]
            for side, rows in affix_rows.items()
        }
        crafted = list(craft_recipes(data.crafts, code, base, types))
        recipes = [(index, len(runewords[index]['runes'])) for index, row in data.runewords.items()
                   if allowed(types, row) and not number(base.get('quest'))]
        sets = [(index, weight, number(data.set_items[index]['lvl']))
                for index, weight in identity_candidates(data.set_items, code, 110, cow=True)]
        uniques = [(index, weight, number(data.uniques[index]['lvl']))
                   for index, weight in identity_candidates(data.uniques, code, 110, unique=True, ladder=ladder)]
        upgrades = []
        for index, row in enumerate(data.uniques):
            source = row.get('code')
            if row.get('enabled') == '1' and source in data.bases:
                penalty = unique_upgrade(source, code, data.bases[source][1])
                if penalty:
                    upgrades.append([index, penalty, number(row.get('lvl'))])
        buckets = []
        by_alvl = {}
        for ilvl in range(1, 111):
            alvl = affix_level(ilvl, qlvl, magic_level)
            maximum = socket_limit(base, item_type, ilvl)
            key = alvl, socket_affix_allowed(base, maximum)
            if key not in by_alvl:
                by_alvl[key] = {}
                for quality in (2, 4, 6, 8):
                    sides = {}
                    for side in ('magicprefix', 'magicsuffix', 'automagic'):
                        if side == 'automagic' and not auto_group or side != 'automagic' and quality == 2:
                            continue
                        candidates = affix_candidates(
                            applicable[side], types, item_type, alvl, quality,
                            auto_group=auto_group if side == 'automagic' else 0,
                            socketable=key[1],
                        )
                        candidates = list(candidates)
                        sides[side] = [index for index, row in candidates[:-1]
                                       if not magic_level or number(row.get('level'))]
                        if candidates:
                            sides[side].append(candidates[-1][0])
                    by_alvl[key][quality] = sides
            eligible_sets = [[i, w] for i, w, lvl in sets if lvl <= ilvl]
            eligible_uniques = [[i, w] for i, w, lvl in uniques if lvl <= ilvl]
            qualities = allowed_qualities(
                base, item_type, equipment=kind != 'misc', superior=superior,
                crafted=crafted, sets=eligible_sets, uniques=eligible_uniques,
                magic=any(by_alvl[key][4].get(side) for side in ('magicprefix', 'magicsuffix')),
            )
            affixes = {q: by_alvl[key][2 if q <= 3 else q] for q in qualities if q not in (5, 7)}
            socket_bonuses = {}
            for q, sides in list(affixes.items()):
                prefixes = sides.get('magicprefix', [])
                socket_ids = [index for index in prefixes
                              if affix_catalog['magicprefix'][index]['mods']
                              and affix_catalog['magicprefix'][index]['mods'][0][0] == 'sock']
                if socket_ids:
                    socket_bonuses[q] = max(
                        number(high or param) for index in socket_ids
                        for prop, param, _, high in affix_catalog['magicprefix'][index]['mods']
                        if prop == 'sock'
                    )
            for catalog, q, eligible in (('sets', 5, eligible_sets), ('uniques', 7, eligible_uniques)):
                socket_bonuses[q] = max(
                    (number(high or param) for index, _ in eligible
                     for prop, param, _, high in identities[catalog][index]['mods'] if prop == 'sock'),
                    default=0,
                )
            snapshot = {
                'qualities': qualities, 'affixes': affixes, 'base_socket_max': maximum,
                'quest_socket_max': {q: max(quest_sockets(maximum, q), default=0) for q in qualities},
                'socket_max': {q: saved_socket_limit(maximum, q, socket_bonuses.get(q, 0))
                               for q in qualities},
                'sets': eligible_sets, 'uniques': eligible_uniques,
                'unique_upgrades': [[i, penalty] for i, penalty, lvl in upgrades if lvl <= ilvl],
                'runewords': [i for i, count in recipes if count <= maximum and {2, 3}.intersection(qualities)],
            }
            if buckets and buckets[-1]['rules'] == snapshot:
                buckets[-1]['max_ilvl'] = ilvl
            else:
                buckets.append({'min_ilvl': ilvl, 'max_ilvl': ilvl, 'rules': snapshot})
        bases[code] = {'qlvl': qlvl, 'magic_level': magic_level, 'superior_rows': superior, 'buckets': buckets}
    return {'version': '1.14d', 'schema': 1, 'ladder_uniques': ladder,
            'affixes': affix_catalog, 'runewords': runewords, **identities, 'bases': bases}
