"""Stock LoD 1.14d character and item checks.

A finding describes a rule violation or a fingerprint collision in the current
snapshot. An empty result establishes only that these checks passed.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..binfmt import bin2txt
from ..binfmt.txt2bin import read_txt
from ..lint.savescan import SaveTables, parse_d2s
from ..tooltip.data import Table, to_int
from ..tooltip.item import ItemTables, Stats, V, apply_property
from .data import game_tables, runeword_strings


# One-time rewards per difficulty. The scroll from Anya grants resistance.
STAT_REWARDS = {17: 5}  # Lam Esen's Tome
SKILL_REWARDS = {1: 1, 9: 1, 25: 2}  # Den of Evil, Radament, Izual


@dataclass(frozen=True)
class Finding:
    item: str
    rule: str
    detail: str
    severity: str = 'impossible'


def affix_level(ilvl, qlvl, magic_level):
    """Clamp ilvl to 99 and raise it to qlvl. A magic level adds directly.

    Otherwise subtract floor(qlvl/2) below 99 - floor(qlvl/2), and use
    2 * effective ilvl - 99 at or above that threshold. Cap the result at 99.
    """
    level = max(min(ilvl, 99), qlvl)
    if magic_level:
        return min(99, level + magic_level)
    half = qlvl // 2
    return level - half if level < 99 - half else 2 * level - 99


def properties(row, pattern, ids):
    for i in ids:
        keys = [col.format(i) for col in pattern.split()]
        if row.get(keys[0]):
            yield tuple(row.get(key, '') for key in keys)


def set_item_properties(row, slot):
    """Yield the item-local properties stored under one set mask bit."""
    pairs = (f'{slot + 1}a', f'{slot + 1}b')
    yield from properties(row, 'aprop{} apar{} amin{} amax{}', pairs)


def allowed(types, row):
    included = {v for k, v in row.items() if k.startswith('itype') and v}
    excluded = {v for k, v in row.items() if k.startswith('etype') and v}
    return bool(types & included) and not types & excluded


def flatten(items):
    for item in items:
        yield item
        yield from flatten(item.children)


def stock_dir():
    for root in Path(__file__).resolve().parents:
        stock = root / 'ref' / 'patches' / 'patch114d_bins'
        if (stock / 'magicprefix.txt').is_file():
            return stock
    raise FileNotFoundError('stock LoD tables (ref/patches/patch114d_bins) are unavailable')


@lru_cache(maxsize=8)
def _validator(directory):
    return Validator(directory)


def stock_validator(game=None):
    return _validator(game_tables(game) if game else stock_dir())


def report_lines(findings, *, verdict=False):
    """Keep the full-info summary and the standalone verdict concise."""
    count = len(findings)
    if verdict:
        return [f'Not legit ({count} {"reason" if count == 1 else "reasons"})' if count else 'Legit']
    return ['Legit: ok' if not count else f'Legit: {count} {"issue" if count == 1 else "issues"}']


class Validator:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.save_tables = SaveTables(directory, median=False)
        self.context = bin2txt.Context(bin_dir=str(directory), version='114d')
        self.tables = {}
        self.bases = {}
        for name in ('weapons', 'armor', 'misc'):
            for row in self.rows(name):
                if row.get('code'):
                    self.bases[row['code']] = (name, row)
        self.item_types = {r['code']: r for r in self.rows('itemtypes') if r.get('code')}
        # The save uses one-based IDs within each compiled affix table.
        # The TXT loader drops Expansion separators and retains blank rows.
        self.affixes = {}
        for name in ('magicsuffix', 'magicprefix', 'automagic'):
            self.affixes.update({(name, 1 + i): (name, row) for i, row in enumerate(self.rows(name))})
        self.rare_suffixes = self.rows('raresuffix')
        self.rare_prefixes = self.rows('rareprefix')
        self.uniques = self.rows('uniqueitems')
        self.set_items = self.rows('setitems')
        self.sets = {r['index']: r for r in self.rows('sets')}
        self.set_sizes = Counter(r['set'] for r in self.set_items if r.get('set'))
        self.superior = self._optional_rows('qualityitems')
        self.low = self._optional_rows('lowqualityitems')
        self.item_tables = ItemTables(self)
        self.characters = self.rows('charstats')
        self.experience = {r['level']: r for r in self.rows('experience')}
        self.crafts = [r for r in self.rows('cubemain') if r.get('enabled') == '1'
                       and ',crf' in r.get('output', '')]
        strings = runeword_strings(self.directory)
        self.runewords = {strings[row['name']]: row for row in self.rows('runes')
                          if row.get('complete') == '1' and row['name'] in strings}
        self.gems = {row['code']: row for row in self.rows('gems') if row.get('code')}

    def table(self, name):
        if name not in self.tables:
            path = self.directory / f'{name}.txt'
            if path.exists():
                raw_headers, raw_rows = read_txt(path)
                headers = [cell.decode('latin-1') for cell in raw_headers]
                rows = [[cell.decode('latin-1').strip('"') for cell in row] for row in raw_rows]
            else:
                data = (self.directory / f'{name}.bin').read_bytes()
                headers, rows = bin2txt.convert(data, name, '114d', self.context)
            self.tables[name] = Table(headers, rows)
        return self.tables[name]

    def rows(self, name):
        table = self.table(name)
        return [{k.lower(): v.strip() for k, v in table.row(i).items()}
                for i in range(len(table))]

    def _optional_rows(self, name):
        # The stock reference dump has the patch archive alone. These two
        # tables are inherited from d2exp.mpq in a complete installation.
        if any((self.directory / f'{name}.{ext}').is_file() for ext in ('txt', 'bin')):
            return self.rows(name)
        return None

    def parse(self, path):
        return parse_d2s(path, self.save_tables)

    def _bounds(self, mods):
        bounds = Stats()
        random = {}
        for code, param, low, high in mods:
            if code == 'randclassskill':
                props = self.item_tables.props
                bonus = to_int(props.get(props.find(code, 'code'), 'val1'))
                random.update({(83, cls): V(bonus) for cls in range(to_int(low), to_int(high) + 1)})
            elif code == 'skill-rand':
                random.update({(107, skill): V(to_int(param))
                               for skill in range(to_int(low), to_int(high) + 1)
                               if skill not in (42, 50, 60)})
            elif code == 'charged' and min(to_int(low), to_int(high)) < 0:
                # Negative charge parameters are scaling controls. Retain the
                # skill and fixed fields and use the packed widths for scaled fields.
                skill = self.item_tables.skill_index(param)
                if skill >= 0:
                    level = to_int(high)
                    levels = range(1, 64) if level < 0 else (level,)
                    capacity = to_int(low)
                    lo_capacity, hi_capacity = (1, 255) if capacity < 0 else (capacity, capacity)
                    for level in levels:
                        bounds.add(204, (skill << 6) | level,
                                   V(lo_capacity << 8, (hi_capacity << 8) | hi_capacity))
            elif code == 'ignore-ac':
                bounds.add(115, 0, V(to_int(low), to_int(high)))
            elif code == 'indestruct':
                bounds.add(152, 0, V(1))
            elif code == 'sock' and not low and not high:
                bounds.add(194, 0, V(to_int(param)))
            else:
                # Chance/level columns can be reversed in CubeMain; the
                # Properties function gives them their meaning.
                apply_property(self.item_tables, bounds, code, param, low, high, 1)
        for (sid, layer), value in random.items():
            bounds.add(sid, layer, value)
        return bounds.vals

    def _stat_findings(self, label, values, candidates, types=()):
        if not values:
            return []
        best = None
        for mods in candidates:
            limits = self._bounds(mods)
            failures = []
            for code, sid in (('randclassskill', 83), ('skill-rand', 107)):
                if any(prop[0] == code for prop in mods) and sum(s == sid for s, _, _ in values) > 1:
                    failures.append(Finding(label, 'stat', 'random skill property rolls one bonus'))
            seen = set()
            for sid, layer, value in values:
                stat = self.item_tables.s(sid, 'stat') or f'stat {sid}'
                key = (sid, layer)
                if key in seen:
                    failures.append(Finding(label, 'stat', f'repeated {stat} [{layer}]'))
                    continue
                seen.add(key)
                interval = limits.get(key)
                if sid == 107 and self._staffmod(types, layer):
                    base = interval or V(0)
                    interval = V(base.lo if key in limits else 1, base.hi + 3)
                if interval is None:
                    failures.append(Finding(label, 'stat', f'{stat} {value} has no allowed source'))
                    continue
                lo, hi = sorted((interval.lo, interval.hi))
                if sid == 204:   # remaining charges can be spent independently of capacity
                    lo &= ~255
                if not lo <= value <= hi or (sid == 204 and value & 255 > value >> 8):
                    failures.append(Finding(label, 'stat', f'{stat} {value} outside {lo}..{hi}'))
            if best is None or len(failures) < len(best):
                best = failures
        return best or []

    def _staffmod(self, types, skill):
        cls = self.item_tables.skills.get(skill, 'charclass').strip()
        return bool(cls) and any(self.item_types.get(t, {}).get('staffmods') == cls for t in types)

    def _craft_mods(self, item, base, types):
        for row in self.crafts:
            source, *flags = row['input 1'].split(',')
            target, *_ = row['output'].split(',')
            if target not in ('usetype', 'useitem', item.code):
                continue
            family = {item.code} | types
            if 'upg' in flags:
                family.update(base.get(key) for key in ('normcode', 'ubercode', 'ultracode'))
            if source in family:
                normalized = {key.replace(' ', '_'): value for key, value in row.items()}
                yield list(properties(normalized, 'mod_{} mod_{}_param mod_{}_min mod_{}_max', range(1, 6)))

    def validate_item(self, item):
        if item.code not in self.bases:
            return [Finding(item.code, 'base', 'unknown stock base')]
        kind, base = self.bases[item.code]
        types = self.save_tables.ancestors(base.get('type')) | self.save_tables.ancestors(base.get('type2'))
        label = base.get('name') or item.code
        q = item.quality
        findings = []
        mods = []
        superior_mods = [[]]
        legacy_mods = None

        def report(rule, detail, severity='impossible'):
            findings.append(Finding(label, rule, detail, severity))

        if not 1 <= item.ilvl <= 99:
            report('item-level', f'invalid item level {item.ilvl}')
        base_type = self.item_types.get(base.get('type'), {})
        if q == 9 or (q >= 4 and base_type.get('normal') == '1'):
            report('quality', 'quality cannot spawn on this base')
        if q == 1 and self.low is not None:
            if item.quality_id is None or not 0 <= item.quality_id < len(self.low):
                report('quality', 'unknown low quality variant')
        if q == 3:
            if self.superior is None:
                report('quality', 'superior variant table unavailable in the stock reference', 'suspicious')
            elif item.quality_id is None or not 0 <= item.quality_id < len(self.superior):
                report('quality', 'unknown superior variant')
            else:
                categories = {'shld': 'shield', 'thro': 'thrown', 'scep': 'scepter',
                              'wand': 'wand', 'staf': 'staff', 'bow': 'bow',
                              'boot': 'boots', 'glov': 'gloves', 'belt': 'belt'}
                column = next((col for type_, col in categories.items() if type_ in types),
                              {'armor': 'armor', 'weapons': 'weapon'}.get(kind))
                # Validate saved bonuses against one complete superior roll.
                rolls = [list(properties(row, 'mod{}code mod{}param mod{}min mod{}max',
                                         range(1, 3)))
                         for row in self.superior if row.get(column) == '1']
                if rolls:
                    superior_mods = rolls
                else:
                    report('quality', 'superior variant cannot spawn on this base')

        if q in (5, 7):
            rows = self.set_items if q == 5 else self.uniques
            index = item.quality_id
            if index is None or not 0 <= index < len(rows):
                report('identity', 'unknown set or unique ID')
            else:
                row = rows[index]
                label = row['index']
                expected = row.get('item' if q == 5 else 'code')
                upgraded = q == 7 and expected in self.bases and (
                    base.get('normcode') and self.bases[expected][1].get('normcode') == base['normcode'] and
                    item.code in {self.bases[expected][1].get('ubercode'), self.bases[expected][1].get('ultracode')})
                if expected != item.code and not upgraded:
                    report('identity', f'wrong base {item.code} (expected {expected})')
                if q == 7 and row.get('enabled') != '1':
                    report('identity', 'disabled unique row')
                mods.extend(properties(row, 'prop{} par{} min{} max{}', range(1, 13)))
                if upgraded:
                    tier = self.bases[expected][1]
                    penalty = 5 if item.code == tier.get('ubercode') else 7
                    if item.code == tier.get('ultracode') and expected == tier.get('normcode'):
                        penalty += 5
                    mods.append(('levelreq', '', str(penalty), str(penalty)))
                if label == 'Hellfire Torch':
                    # Torches generated before 1.13 retain their original 25% proc.
                    legacy_mods = [('hit-skill', param, '25', high)
                                   if code == 'hit-skill' and low == '5'
                                   else (code, param, low, high)
                                   for code, param, low, high in mods]
                if q == 5:
                    set_name = row.get('set')
                    set_row = self.sets.get(set_name)
                    if set_row is None:
                        report('identity', 'set item references an unknown set')
                    for slot, stats in item.set_stats.items():
                        extra = list(set_item_properties(row, slot))
                        candidates = [extra]
                        pieces = slot + 2
                        if set_row and pieces <= self.set_sizes[set_name]:
                            partial = list(properties(set_row, 'pcode{} pparam{} pmin{} pmax{}',
                                                      (f'{pieces}a', f'{pieces}b')))
                            candidates += [partial, extra + partial]
                            if pieces == self.set_sizes[set_name]:
                                full = list(properties(set_row, 'fcode{} fparam{} fmin{} fmax{}', range(1, 9)))
                                candidates += [full, extra + full, partial + full, extra + partial + full]
                        findings.extend(self._stat_findings(label, stats, candidates))

        if item.rare_name:
            suffix_count = len(self.rare_suffixes)
            pre, suf = item.rare_name
            for name_id, rows, offset in ((pre, self.rare_prefixes, suffix_count + 1),
                                          (suf, self.rare_suffixes, 1)):
                if offset == 1 and name_id == 0:
                    continue  # A rare name may omit its second fragment.
                index = name_id - offset
                if not 0 <= index < len(rows) or not allowed(types, rows[index]):
                    report('rare-name', f'rare name fragment {name_id} is unavailable on this base')

        alvl = affix_level(item.ilvl, to_int(base.get('level')), to_int(base.get('magic lvl')))
        active = [(table, i) for table, i in item.affixes if i]
        counts = Counter(table for table, _ in active)
        limit = {4: 1, 6: 3, 8: 3}.get(q, 0)
        if max(counts.values(), default=0) > limit or len(active) > 2 * limit:
            report('affix-count', f'{len(active)} affixes exceed quality limits')
        if q == 8:
            minimum = 4 if item.ilvl >= 71 else 3 if item.ilvl >= 51 else 2 if item.ilvl >= 31 else 1
            if not minimum <= len(active) <= 4:
                report('craft-affix-count', f'{len(active)} crafted affixes, expected {minimum}..4')
        if q == 4 and not active:
            report('affix-count', 'magic item has no affix')
        groups = set()
        for table, index in active + ([('automagic', item.automagic)] if item.automagic else []):
            found = self.affixes.get((table, index))
            if not found or found[0] != table or not found[1].get('name'):
                report('affix-id', f'unknown {table} ID {index}')
                continue
            row = found[1]
            name = row['name']
            if not allowed(types, row) or (table == 'automagic' and
                                           row.get('group') != base.get('auto prefix')):
                report('affix-type', f'{name} cannot spawn on {item.code}')
            if row.get('spawnable') != '1' or (q in (6, 8) and row.get('rare') != '1'):
                report('affix-quality', f'{name} cannot spawn at this quality')
            high = to_int(row.get('maxlevel'))
            if alvl < to_int(row.get('level')) or (high and alvl > high):
                report('affix-level', f'{name} unavailable at affix level {alvl}')
            group = to_int(row.get('group'))
            if group and table != 'automagic':
                if group in groups:
                    report('affix-group', f'{name} repeats affix group {group}')
                groups.add(group)
            mods.extend(properties(row, 'mod{}code mod{}param mod{}min mod{}max', range(1, 4)))

        staffmods = [skill for sid, skill, _ in item.stats if sid == 107
                     and self._staffmod(types, skill)]
        authored = {layer for sid, layer in self._bounds(mods) if sid == 107}
        if sum(skill not in authored for skill in staffmods) > 3:
            report('staffmods', 'more than three native skill bonuses')

        variants = [mods + superior for superior in superior_mods]
        if legacy_mods is not None:
            variants.append(legacy_mods)
        auto_group = base.get('auto prefix')
        if auto_group and auto_group != '0' and not item.automagic and q <= 3:
            # A saved base can retain its native bonus without an automagic ID.
            # Each candidate still has to fit one authored roll for its class.
            auto_rolls = [list(properties(row, 'mod{}code mod{}param mod{}min mod{}max',
                                          range(1, 4)))
                          for table, row in self.affixes.values()
                          if table == 'automagic' and row.get('group') == auto_group
                          and row.get('spawnable') == '1' and allowed(types, row)
                          and to_int(row.get('level')) <= alvl
                          and (not to_int(row.get('maxlevel')) or alvl <= to_int(row['maxlevel']))]
            variants += [candidate + roll for candidate in variants for roll in auto_rolls]
        if q == 8:
            crafts = list(self._craft_mods(item, base, types))
            if not crafts:
                report('craft', 'no enabled crafted recipe for this base')
            else:
                variants = [mods + fixed for fixed in crafts]

        sock_col = 'maxsock1' if item.ilvl <= 25 else 'maxsock25' if item.ilvl <= 40 else 'maxsock40'
        max_sockets = min(to_int(base.get('gemsockets')),
                          to_int(self.item_types.get(base.get('type'), {}).get(sock_col)))
        if q in (4, 5, 6, 7, 8):
            added = max(self._bounds(v).get((194, 0), V(0)).hi for v in variants)
            quest_limit = 2 if q == 4 else 1
            max_sockets = min(max_sockets, max(quest_limit, added))
        if len(item.children) > item.sockets or item.sockets > max_sockets:
            report('sockets', f'{len(item.children)} filled, {item.sockets} total, max {max_sockets}')

        if any(child.sockets or child.children for child in item.children):
            report('sockets', 'socket filler has sockets of its own')
        if item.runeword is not None:
            runes = [child.code for child in item.children]
            row = self.runewords.get(item.runeword)
            recipe = [row[f'rune{i}'] for i in range(1, 7) if row.get(f'rune{i}')] if row else []
            if not row or runes != recipe or len(recipe) != item.sockets or q not in (2, 3) or not allowed(types, row):
                report('runeword', 'ID, ordered runes, quality, base or socket count mismatches recipe')
            else:
                label = row['rune name']
                rwmods = list(properties(row, 't1code{} t1param{} t1min{} t1max{}', range(1, 8)))
                slot = 'weapon' if kind == 'weapons' else 'shield' if 'shld' in types else 'helm'
                pattern = ' '.join(f'{slot}mod{{}}{field}' for field in ('code', 'param', 'min', 'max'))
                rune_mods = [mod for rune in runes
                             for mod in properties(self.gems.get(rune, {}), pattern, range(1, 4))]
                findings.extend(self._stat_findings(label, item.runeword_stats, [rwmods, rwmods + rune_mods]))

        ethereal = bool(item.flags & (1 << 22))
        if ethereal and (kind == 'misc' or base.get('nodurability') == '1' or
                         (q == 5) or (q == 7 and any(m[0] == 'indestruct' for m in mods)
                                     and not any(m[0] == 'ethereal' for m in mods))):
            report('ethereal', 'base or quality cannot be ethereal')
        if any(m[0] == 'ethereal' for m in mods) and not ethereal:
            report('ethereal', 'unique requires the ethereal flag')
        if item.defense is not None:
            lo, hi = to_int(base.get('minac')), to_int(base.get('maxac'))
            if q == 1:
                lo //= 2
            if q == 3 or any(sid == 16 for sid, _, _ in item.stats + item.runeword_stats):
                hi += 1
            if ethereal:
                lo, hi = lo * 3 // 2, hi * 3 // 2
                if item.sockets:
                    hi = hi * 3 // 2  # 1.14d cube socketing can reapply the ethereal bonus
            if not lo <= item.defense <= hi:
                report('defense', f'base defense {item.defense} outside {lo}..{hi}', 'suspicious')
        if q != 3 or self.superior is not None:
            findings.extend(self._stat_findings(label, item.stats, variants, types))
        return findings

    def _character_findings(self, char):
        if not 0 <= char.cls < len(self.characters):
            yield Finding(char.name, 'class', 'unknown character class')
            return
        row = self.characters[char.cls]
        stats = char.stats
        exp = stats.get(13, 0)
        level = char.level
        cls = row['class'].lower()
        if (not 1 <= level <= 99 or stats.get(12) != level or
                not to_int(self.experience.get(str(level - 1), {}).get(cls)) <= exp <=
                to_int(self.experience.get(str(level), {}).get(cls)) or
                (level < 99 and exp == to_int(self.experience.get(str(level), {}).get(cls)))):
            yield Finding(char.name, 'experience', f'level {level} inconsistent with {exp} experience')
        attributes = [stats.get(sid, 0) - to_int(row.get(col))
                      for sid, col in enumerate(('str', 'int', 'dex', 'vit'))]
        stat_budget = (level - 1) * 5 + sum(
            reward for diff in char.quests for quest, reward in STAT_REWARDS.items() if diff[quest] & 1)
        used = stats.get(4, 0) + sum(attributes)
        if used > stat_budget or min(attributes) < 0:
            yield Finding(char.name, 'stat-points', f'{used} stat points against budget {stat_budget}')
        skill_budget = level - 1 + sum(
            reward for diff in char.quests for quest, reward in SKILL_REWARDS.items() if diff[quest] & 1)
        used = stats.get(5, 0) + sum(char.skills)
        if used > skill_budget or max(char.skills, default=0) > 20:
            yield Finding(char.name, 'skill-points', f'{used} skill points against budget {skill_budget}, max 20 per skill')

    def validate(self, character, peers=()):
        findings = list(self._character_findings(character))
        # The serialized 32-bit item GUID is the fingerprint available in
        # a d2s. The server's transient unit ID is not preserved across loads.
        fingerprints = defaultdict(list)
        for owner in (character, *peers):
            for item in flatten(owner.items):
                if item.seed is not None and item.seed != 0:
                    fingerprints[(item.seed, item.code)].append(owner.name)
        for item in flatten(character.items):
            findings.extend(self.validate_item(item))
            owners = fingerprints.get((item.seed, item.code), ())
            if len(owners) > 1:
                name = self.bases.get(item.code, ('', {}))[1].get('name', item.code)
                findings.append(Finding(name, 'duplicate', f'saved item ID repeats on {", ".join(owners)}',
                                        'suspicious'))
        return findings
