#!/usr/bin/env python3
"""Works out what the PARAMETER of every stat with save-param bits means and writes src/mxl_statparams.py.

    APP=dist/linux/AppDir
    $APP/opt/python/bin/python3.10 tools/gen_statparams.py --app $APP/opt/capybara \\
        --user-dir <copy of the editor's user folder> [--save-dir <copy of a save folder>]... \\
        [--out src/mxl_statparams.py] [--report report.txt]

Read-only on the game data (the user folder must be a COPY: the host's `paths` may create sub-folders in it).
Re-run it after a game patch; the report lists every stat with its evidence, `git diff src/mxl_statparams.py`
shows what moved.

Evidence, in this order:
A. RENDERED TEXT - the line the editor's item display (the host's tooltip renderer, mxl_stat_text.stat_lines:
   what shows when the mouse is over an item) prints for the stat, for every param value that occurs in the
   tables / saves and for a sweep of values per field (0..15 for small fields, a sample of existing ids for
   skills / monsters / states). Where the lines differ by param in a way that names the values, the differing
   part IS the name of the value and the common part the stat's neutral name: the mapping is 'proven' and
   'by' = 'rendered'. The host's own lines are used (not the two this editor completes, see
   mxl_statnames._install_param_texts).
B. TABLES - where the renderer shows nothing (hidden stats), a placeholder, or the same text for every param:
   the rules below, checked against the tables ('by' = 'tables'), or only the rule ('by' = 'rule').

How a stat's param kind is decided (first rule that applies):
1. the stat's description function in itemstatcost (what the game prints for it):
   13 class, 14 skill tab, 15 chance to cast (skill << 6 | level), 24 charges (skill << 6 | level),
   23 monster, 27 / 28 skill, 33 / 37 skill ('%s' of the description string), 31 / 34 string-table text,
   35 innate elemental damage (element | attribute << 8; the element strings follow the stat's own string);
2. the function of the properties that set it: 11 (the 'on event' property: skill << 6 | level), 22 with a
   skill parameter;
3. what the tables show for the stats without any text (BY_DATA below, each with the check that proves it).
Everything else is 'unknown' and lists the values seen.

Confidence:
  proven   - seen with at least two distinct param values AND the data shows what they mean (the check of the
             kind passed for two values: the skill named by the param is named in the item's own orange text,
             the game string of the value exists, the property row gives the fields separately, ...);
  inferred - the rule applies (description function / vanilla semantics / one example) but the tables do not
             show two values;
  unknown  - no rule; observed values are listed.
"""
import argparse
import collections
import glob
import os
import pprint
import re
import struct
import sys

# stats without a description: what the tables show (kind, note). Checked below like every other stat.
BY_DATA = {
    98: ('state', 'vanilla "state" stat: property 19 (func 24) passes its parameter through'),
    126: ('element', 'vanilla item_elemskill: param = element type (elemtypes row); no row of 2.14 sets it'),
    151: ('skill', 'vanilla item_aura: the skill runs as an aura while the item is worn (value = level)'),
    179: ('montype', 'vanilla attack-rating-vs-monster-type; no row of 2.14 sets it'),
    180: ('montype', 'damage vs. a monster group; the one row that sets it (Klaatu Barada Nikto) has the '
                     'orange text "30% Enhanced Damage vs. Necrobots"'),
    290: ('orb', 'counter of mystic orbs used on the item: param = row of mysticorbs.bin, value = how many'),
    382: ('skill', 'per-skill modifier slot: the skill named by the param reads the value in its own formula'),
    383: ('skill', 'per-skill modifier slot: the skill named by the param reads the value in its own formula'),
    393: ('skill', 'per-skill modifier slot: the skill named by the param reads the value in its own formula'),
    396: ('skill', 'per-skill modifier slot: the skill named by the param reads the value in its own formula'),
    397: ('skill', 'per-skill modifier slot: the skill named by the param reads the value in its own formula'),
    399: ('skill', 'per-skill modifier slot: the skill named by the param reads the value in its own formula'),
    400: ('skill', 'same layout as the per-skill modifier slots 382 - 399; no row of 2.14 sets it'),
}
# values whose name only an item text gives (stat -> {value: (name, where it is written)})
TEXT_ENUMS = {
    180: {505: ('Necrobots', 'unique "Klaatu Barada Nikto": orange text "30% Enhanced Damage vs. Necrobots"')},
}
# stat 415, attribute byte 4: no stat of that id is an attribute; the Enhanced Rune that gives it says which
ATTR_HIGHER = 'Strength or Dexterity (the higher)'
# picker labels that replace a label baking ONE param value into the name (the game's string for value 0)
LABELS = {
    83: '+# to [Class] Skill Levels',
    155: '#% Reanimate as: [Monster]',
    188: '+# to [Class skill tab] Skills',
    204: 'Level # [Skill] (#/# Charges)',
    415: 'Innate Elemental Damage: # (#% of [Attribute])',
}
DLL = {
    88: 'character-only stat (achievement data); the meaning of its 16 param bits is in the game code',
    126: 'which element ids the code accepts',
    179: 'which table the monster-group id indexes',
    180: 'which table the monster-group id indexes (505 is beyond montype.bin\'s 64 rows)',
    188: 'whether the tab index is still class * 8 + tab with Sigma\'s eight tabs per class',
    206: 'which event triggers the hidden skill',
    400: 'whether the slot is read at all',
    415: 'the text printed for attribute 4, and whether attribute 1 (Energy) is accepted',
    417: 'the meaning of the 5-bit param (no row sets the stat)',
    427: 'the meaning of the 5-bit param (always 0 in the tables)',
}
SKILL_LEVEL = [('level', 'number', 0, 6), ('skill', 'skill', 6, None)]


def plain(text):
    return re.sub(r'\xffc.', '', str(text or ''))


class Gen:
    def __init__(self, args):
        self.args = args
        import paths
        import mxl_data
        import mxl_format
        import mxl_format_fix
        mxl_format_fix.install()
        import mxl_creator
        import mxl_rules
        import mxl_statnames
        mxl_statnames.install()
        self.fmt, self.cm, self.rules, self.sn = mxl_format, mxl_creator, mxl_rules, mxl_statnames
        self.d = mxl_data.Data(paths.DATA_DIR)
        self.cr = mxl_creator.Creator(self.d)
        self.P = sorted(k for k, v in self.d.isc.items() if v.get('param') and v.get('bits'))
        # sid -> param -> [dict(src, prop, par, lo, hi, value, texts)]
        self.obs = collections.defaultdict(lambda: collections.defaultdict(list))
        self.saves = collections.defaultdict(lambda: collections.defaultdict(list))
        self.setters = collections.defaultdict(set)          # sid -> {(property, property func)}
        self._rd = {}

    # ------------------------------------------------------------------ collecting
    def sources(self):
        d = self.d

        def name(key):
            return plain(d.key(key)).replace('\n', ' ').strip()
        for i, u in enumerate(d.uniques):
            yield f'unique {i} "{name(u["name"])}"', u['mods']
        for i, u in enumerate(d.set_items):
            yield f'set item {i} "{name(u["name"])}"', u['mods']
        for i, m in enumerate(d.runeword_mods):
            yield f'runeword {i} "{name(d.runewords[i][0]) if i < len(d.runewords) else ""}"', m
        for k, rows in d.affixes.items():
            for i, a in enumerate(rows):
                yield f'{k} {i}', a['mods']
        for code, g in d.gems.items():
            for j, m in enumerate(g):
                yield f'socket filler {code.strip()} ({("weapon", "armor", "shield")[j] if j < 3 else j})', m
        for code, o in self.cr._orb_table().items():
            yield f'mystic orb "{o["name"]}"', o['mods']
        for i, r in enumerate(self.cm._rows(d, 'cubemain')):
            if len(r) < 0x4C + 0x54 or not r[0]:
                continue
            for o in range(3):
                base = 0x4C + 0x54 * o
                if base + 24 + 60 > len(r):
                    break
                mods = []
                for j in range(5):
                    p, pa, lo, hi, _ch = struct.unpack_from('<iHhhH', r, base + 24 + 12 * j)
                    if 0 <= p < len(d.props):
                        mods.append((p, pa, lo, hi))
                if mods:
                    yield f'cube recipe {i} output {o + 1}', mods

    def collect(self):
        d, P = self.d, set(self.P)
        for src, mods in self.sources():
            ms = [((m['prop'], m['param'], m['min'], m['max']) if isinstance(m, dict) else tuple(m[:4]))
                  for m in mods]
            ms = [m for m in ms if 0 <= m[0] < len(d.props)]
            per_mod = []
            for m in ms:
                seen = []
                for which in ('min', 'max'):
                    try:
                        for s in self.rules.mods_stats([m], d, which):
                            if s not in seen:
                                seen.append(s)
                    except Exception:
                        pass
                per_mod.append((m, seen))
            texts = []
            for _m, stats in per_mod:
                for s in stats:
                    if s['id'] in (375, 377, 378, 385):
                        t = d.strings.get(s.get('param'))
                        if t:
                            texts.append(plain(t[1]).replace('\n', ' / '))
            for m, stats in per_mod:
                for s in stats:
                    if s['id'] in P:
                        funcs = d.prop_funcs[m[0]]
                        idx = list(d.props[m[0]]).index(s['id']) if s['id'] in d.props[m[0]] else 0
                        self.setters[s['id']].add((m[0], funcs[idx]))
                        self.obs[s['id']][s.get('param') or 0].append(
                            dict(src=src, prop=m[0], par=m[1], lo=m[2], hi=m[3], value=s['value'], texts=texts))
        for folder in self.args.save_dir or ():
            for f in sorted(glob.glob(os.path.join(folder, '*'))):
                if not f.endswith(('.d2s', '.stash', '.shared')):
                    continue
                with open(f, 'rb') as fh:
                    b = fh.read()
                pos, done = 0, set()
                while True:
                    pos = b.find(b'JM', pos)
                    if pos < 0:
                        break
                    try:
                        n = struct.unpack_from('<H', b, pos + 2)[0]
                        items = self.fmt.read_item_list(b, pos + 4, n, d)[0] if 0 < n < 600 else []
                    except Exception:
                        items = []
                    for it in items:
                        for key in ('stats', 'stats_runeword'):
                            stats = it.get(key) or ()
                            for s in stats:
                                if isinstance(s, dict) and s['id'] in P:
                                    k = (pos, it.get('id'), key, s['id'], s.get('param'))
                                    if k in done:
                                        continue
                                    done.add(k)
                                    self.saves[s['id']][s.get('param') or 0].append(
                                        dict(file=os.path.basename(f), code=str(it.get('code')).strip(),
                                             value=s['value'], stats=stats))
                    pos += 2

    # ------------------------------------------------------------------ deciding
    def rule(self, sid):
        """(fields, why) by the description function / the setting properties / BY_DATA, or (None, None)."""
        ic = self.d.isc[sid]
        func = ic.get('func')
        desc = plain(ic.get('desc'))
        if 'POLAR BUFFALO' in desc.upper():
            desc = ''
        by_func = {
            13: ([('class', 'class', 0, None)], 'description function 13 (class skills)'),
            14: ([('tab', 'number', 0, 3), ('class', 'class', 3, None)],
                 'description function 14 (skill tab; vanilla layout class * 8 + tab)'),
            15: (SKILL_LEVEL, 'description function 15 (chance to cast): "%d%% ... level %d %s"'),
            24: (SKILL_LEVEL, 'description function 24 (charges): level and skill in the param'),
            23: ([('monster', 'monster', 0, None)], 'description function 23 (monster name appended)'),
            27: ([('skill', 'skill', 0, None)], 'description function 27 (class-only skill)'),
            28: ([('skill', 'skill', 0, None)], 'description function 28 (skill)'),
            31: ([('string', 'string', 0, None)], 'description function 31 (the text IS the string of that index)'),
            34: ([('string', 'string', 0, None)], 'description function 34 (the text IS the string of that index)'),
            35: ([('element', 'element', 0, 8), ('attribute', 'attribute', 8, 8)],
                 'description function 35: "Innate <element> Damage: %d (%.1f%% of <attribute>)"'),
        }
        if func in by_func:
            return by_func[func]
        if func in (33, 37) and '%s' in desc:
            return [('skill', 'skill', 0, None)], f'description function {func}: the "%s" of "{desc}" is a skill'
        pfuncs = {f for _p, f in self.setters.get(sid, ())}
        if 11 in pfuncs:
            return SKILL_LEVEL, 'set by an "on event" property (func 11: parameter = skill, max = level)'
        if sid in BY_DATA:
            kind, why = BY_DATA[sid]
            return [(kind, kind, 0, None)], why
        return None, None

    # ------------------------------------------------------------------ rendered text (the hover display)
    def render(self, sid, param, value):
        """The host's own tooltip line of one stat, plain; '' when it shows nothing."""
        import mxl_stat_text as st
        host = getattr(st, '_sn_host_texts', None)
        mine = (st._stat_text, st._innate_damage_line)
        if host:
            st._stat_text, st._innate_damage_line = host
        try:
            out = []
            for ln in st.stat_lines([dict(id=sid, param=param or None, value=value)], self.d):
                text = str(ln[1])
                for seg in (ln[2] if len(ln) > 2 else ()) or ():
                    text += str(seg[1] if isinstance(seg, (tuple, list)) else seg)
                out.append(plain(text).replace('\n', ' / ').strip())
            return ' / '.join(t for t in out if t)
        except Exception:
            return ''
        finally:
            st._stat_text, st._innate_damage_line = mine

    @staticmethod
    def meaningful(line):
        return bool(line) and 'POLAR BUFFALO' not in line.upper() and not re.search(r'%s|%d|skill #|\?\)', line)

    def sweep_values(self, sid, field, seen):
        name, kind, shift, bits = field
        top = (1 << bits) - 1
        vals = {(p >> shift) & top for p in seen}
        if kind == 'skill':
            own = sorted(k for k in self.d.skill_names if self.skill_own(k) and k <= top)
            vals |= set(own[::max(1, len(own) // 40)])
        elif kind == 'monster':
            ok = [i for i, n in enumerate(self.d.monster_names) if n and 'BUFFALO' not in str(n).upper() and i <= top]
            vals |= set(ok[::max(1, len(ok) // 40)])
        elif kind == 'state':
            vals |= {v for _n, v in self.sn.state_names_sorted(self.d)[:40]}
        elif kind == 'string':
            pass
        else:
            vals |= set(range(0, min(top, 15) + 1))
        return sorted(vals)[:600]

    def rendered(self, sid, fields, seen):
        """Per field: {value: line} of the sweep (other fields at their first observed / lowest value), the
        number of distinct meaningful lines and the names the differing part gives."""
        ic = self.d.isc[sid]
        hi = (1 << ic['bits']) - 1 - (ic.get('add') or 0)
        value = min(37, hi)
        base = seen[0] if seen else 0
        out = {}
        for f in fields:
            name, kind, shift, bits = f
            if name == 'level':
                continue
            mask = ((1 << bits) - 1) << shift
            lines = {}
            for v in self.sweep_values(sid, f, seen):
                rest = base & ~mask
                if kind == 'skill' and len(fields) > 1 and not rest:
                    rest = 1                                  # a cast level of 1
                line = self.render(sid, rest | (v << shift), value)
                lines[v] = re.sub(r'(?<![\d.])%d(\.0)?(?![\d.])' % value, '#', line)
            good = {v: ln for v, ln in lines.items() if self.meaningful(ln)}
            if len(good) > 2:                                 # lines of another shape (value 0, filler strings)
                first = collections.Counter(ln.split(' ')[0] for ln in good.values())
                if kind != 'string' and len(first) > 1:
                    word = first.most_common(1)[0][0]
                    if first[word] >= 2 and (kind in ('element', 'attribute', 'class', 'monster') or len(first) <= 3):
                        good = {v: ln for v, ln in good.items() if ln.split(' ')[0] == word}
            distinct = len(set(good.values()))
            names = {}
            if distinct >= 2:
                texts = list(good.values())
                pre = os.path.commonprefix(texts)
                suf = os.path.commonprefix([t[::-1] for t in texts])[::-1]
                while pre and pre[-1].isalnum():              # never cut inside a word
                    pre = pre[:-1]
                while suf and suf[0].isalnum():
                    suf = suf[1:]
                for v, t in good.items():
                    mid = t[len(pre):len(t) - len(suf) if suf else None].strip()
                    if mid:
                        names[v] = mid
                neutral = (pre + '[' + name + ']' + suf).strip()
            else:
                neutral = next(iter(good.values()), '')
            out[name] = dict(lines=lines, good=good, distinct=distinct, names=names, neutral=neutral)
        return out

    def skill_own(self, sk):
        return self.sn._own_name(self.d, sk)

    def check(self, sid, fields):
        """(number of distinct observed params whose meaning the data shows, evidence lines)."""
        d, sn = self.d, self.sn
        ev, good = [], set()
        obs, sav = self.obs.get(sid, {}), self.saves.get(sid, {})
        kinds = [f[1] for f in fields]

        def part(param, name):
            f = next(f for f in fields if f[0] == name)
            bits = f[3] if f[3] is not None else 32
            return (param >> f[2]) & ((1 << bits) - 1)

        if kinds == ['number', 'skill']:                     # skill << 6 | level
            for p, rows in obs.items():
                for o in rows:
                    if part(p, 'skill') == o['par'] and part(p, 'level') in (o['lo'], o['hi']) \
                            and self.sn.skill_label(d, o['par']):
                        good.add(p)
                        if len(ev) < 2:
                            ev.append(f'{o["src"]}: property {o["prop"]} parameter {o["par"]} '
                                      f'({sn.skill_label(d, o["par"])}), level {part(p, "level")} -> param {p}')
                        break
        elif kinds == ['skill']:
            named = set()
            for p, rows in obs.items():
                own = self.skill_own(p)
                if not own:
                    continue
                named.add(p)
                for o in rows:
                    hit = next((t for t in o['texts'] if own.lower().rstrip('s') in t.lower()), None)
                    if hit:
                        good.add(p)
                        if len(ev) < 3:
                            ev.append(f'{o["src"]}: param {p} = {own}; its orange text: "{hit[:90]}"')
                        break
            if d.isc[sid].get('func') in (27, 28, 33, 37) and len(named) >= 2:
                good |= named                                # the game's own string prints the skill's name
                for p in sorted(named)[:2]:
                    o = obs[p][0]
                    ev.append(f'{o["src"]}: param {p} = {self.skill_own(p)} (printed by the stat\'s own text)')
            ev.append(f'{len(named)} of {len(obs)} params are skills with a name of their own, '
                      f'{len(good)} confirmed by a text')
        elif kinds == ['class']:
            cl = list(self.rules.CLASSES)
            for p, rows in obs.items():
                if 0 <= p < len(cl):
                    good.add(p)
                    if len(ev) < 3:
                        ev.append(f'{rows[0]["src"]}: param {p} = {cl[p]}')
        elif kinds == ['monster']:
            for p, rows in obs.items():
                n = d.monster_names[p] if 0 <= p < len(d.monster_names) else ''
                if n and 'POLAR BUFFALO' not in n.upper():
                    good.add(p)
                    if len(ev) < 3:
                        ev.append(f'{rows[0]["src"]}: param {p} = {n}')
        elif kinds == ['state']:
            for p, rows in list(obs.items()) + [(p, [dict(src=f'saved item {r[0]["code"]} ({r[0]["file"]})')])
                                                for p, r in sav.items()]:
                n = sn.state_name(d, p)
                if n:
                    good.add(p)
                    if len(ev) < 3:
                        ev.append(f'{rows[0]["src"]}: param {p} = state "{n}"')
            ev.append(f'{len(good)} of {len(set(obs) | set(sav))} observed states have a name '
                      f'(a buff icon text or a named skill that sets them)')
        elif kinds == ['string']:
            for p, rows in obs.items():
                t = d.strings.get(p)
                if t and plain(t[1]).strip():
                    good.add(p)
                    if len(ev) < 2:
                        ev.append(f'{rows[0]["src"]}: param {p} = "{plain(t[1]).splitlines()[0][:70]}"')
        elif kinds == ['orb']:
            orbs = list(self.cr._orb_table().values())
            own = [p for p, rows in obs.items() if 0 <= p < len(orbs)
                   and any(o['src'] == f'mystic orb "{orbs[p]["name"]}"' for o in rows)]
            if own:
                ev.append(f'{len(own)} orb rows write the counter themselves, each with its own row index as param '
                          f'(e.g. row {own[0]} "{orbs[own[0]]["name"]}")')
            for p, rows in sav.items():
                if not 0 <= p < len(orbs):
                    continue
                for r in rows:
                    made = set()
                    for prop, par, lo, hi in orbs[p]['mods']:
                        try:
                            made |= {s['id'] for s in self.rules.mods_stats([(prop, par, lo, hi)], d, 'max')}
                        except Exception:
                            pass
                    have = {s['id'] for s in r['stats']}
                    if made and made <= have:
                        good.add(p)
                        if len(ev) < 3:
                            ev.append(f'saved item {r["code"]} ({r["file"]}): param {p} x{r["value"]} = orb '
                                      f'"{orbs[p]["name"]}", and the item carries that orb\'s stats {sorted(made)}')
                        break
        elif kinds == ['element', 'attribute']:
            els = self.elements(sid)
            attrs = self.attributes()
            seen_el, seen_at = set(), set()
            for p, rows in obs.items():
                el, at = part(p, 'element'), part(p, 'attribute')
                if el in els and rows[0]['par'] == at and rows[0]['lo'] == el:
                    good.add(p)
                    seen_el.add(el)
                    seen_at.add(at)
            base = self.string_index(d.isc[sid].get('desc'))
            ev.append(f'the stat\'s own string (#{base}) is followed by one string per element: '
                      + ', '.join(f'{k} {v}' for k, v in els.items()))
            ev.append(f'property 341 writes its parameter into bits 8-15 and its "min" into bits 0-7: '
                      f'elements seen {sorted(seen_el)}, attributes seen {sorted(seen_at)}')
            for p, rows in sorted(obs.items()):
                if part(p, 'attribute') == 4:
                    ev.append(f'{rows[0]["src"]} (attribute 4, element {part(p, "element")}, {rows[0]["hi"]}%): the '
                              f'Enhanced Rune text reads "1H: 33% of Strength/Dexterity added as Innate Fire Damage" '
                              f'under "Whichever attribute is higher"')
                    break
        elif kinds == ['montype']:
            for p, rows in obs.items():
                if p in TEXT_ENUMS.get(sid, {}):
                    ev.append(f'param {p}: {TEXT_ENUMS[sid][p][1]}')
        return good, ev

    def string_index(self, text):
        want = plain(text)
        for k, v in self.d.strings.items():
            if isinstance(k, int) and plain(v[1]) == want:
                return k
        return None

    def elements(self, sid):
        """{value: name} from the strings that follow the stat's own description string."""
        d = self.d
        base = self.string_index(d.isc[sid].get('desc'))
        out = {}
        if base is None:
            return out
        for i in range(16):
            t = d.strings.get(base + i)
            m = re.match(r'Innate (.+?) Damage', plain(t[1]) if t else '')
            if not m:
                break
            out[i] = m.group(1)
        return out

    def attributes(self):
        d = self.d
        out = {}
        for i in range(4):                       # the four attribute stats: 0 Strength 1 Energy 2 Dexterity 3 Vitality
            out[i] = re.sub(r'^to ', '', plain(d.isc[i].get('desc'))).strip()
        out[4] = ATTR_HIGHER
        return out

    # ------------------------------------------------------------------ output
    def build(self):
        d = self.d
        table, report = {}, []
        for sid in self.P:
            ic = d.isc[sid]
            pb = ic['param']
            obs, sav = self.obs.get(sid, {}), self.saves.get(sid, {})
            seen = sorted(set(obs) | set(sav))
            fields, why = self.rule(sid)
            e = dict(bits=pb, seen=len(seen))
            if len(seen) <= 12:
                e['values'] = seen
            notes = []
            if fields is None:
                e.update(kind='unknown', conf='unknown', fields=[('param', 'number', 0, pb)])
                if not seen:
                    notes.append('no table row and no saved item carries the stat')
                elif seen == [0]:
                    e['kind'] = 'number'
                    notes.append('always 0 where it is set (the property passes no parameter)')
            else:
                fl = []
                for name, kind, shift, bits in fields:
                    fl.append((name, kind, shift, bits if bits is not None else pb - shift))
                good, ev = self.check(sid, fl)
                e['fields'] = fl
                e['kind'] = 'packed' if len(fl) > 1 else fl[0][1]
                rd = self.rendered(sid, fl, seen)
                shown = {n: r for n, r in rd.items() if r['distinct'] >= 2 and len(r['names']) >= 2}
                if shown:                                    # A. the hover text names the values
                    e['by'] = 'rendered'
                    e['conf'] = 'proven'
                    for n, r in shown.items():
                        some = list(r['names'].items())
                        notes.append(f'rendered text names the {n}: "{r["neutral"]}" - '
                                     + ', '.join(f'{v} = {t}' for v, t in some[:6])
                                     + (f' ... ({len(some)} values rendered)' if len(some) > 6 else ''))
                        stop = [v for v, ln in sorted(r['lines'].items()) if v not in r['good']]
                        if stop and len(r['lines']) <= 20:
                            notes.append(f'the {n} text stops being meaningful at: {stop[:10]}')
                    e['rendered'] = next(iter(shown.values()))['neutral']
                else:                                        # B. the tables
                    e['by'] = 'tables' if len(good) >= 2 else 'rule'
                    e['conf'] = 'proven' if len(good) >= 2 else 'inferred'
                    one = next((ln for r in rd.values() for ln in r['good'].values()), '')
                    notes.append('rendered text: ' + (f'the same line for every param ("{one}")' if one else
                                                      'none (the item display hides the stat)'))
                self._rd[sid] = rd
                notes.append(why)
                notes += ev
                if len(fl) > 1:
                    e['layout'] = ' | '.join(f'{n}: bits {s}-{s + b - 1}' for n, _k, s, b in fl)
                enums = {}
                if e['kind'] == 'class':
                    enums['class'] = dict(enumerate(self.rules.CLASSES))
                if any(k == 'element' for _n, k, _s, _b in fl) and sid == 415:
                    enums['element'] = self.elements(sid)
                    enums['attribute'] = self.attributes()
                    for fn in ('element', 'attribute'):       # the rendered names must agree with the strings
                        got = rd.get(fn, {}).get('names', {})
                        diff = {v: (t, enums[fn][v]) for v, t in got.items() if v in enums[fn] and enums[fn][v] != t}
                        more = {v: t for v, t in got.items() if v not in enums[fn]}
                        notes.append(f'{fn} names from the rendered lines '
                                     + ('agree with the game strings' if not diff else f'DIFFER: {diff}'))
                        if more:
                            notes.append(f'the renderer reads the {fn} byte as a stat id and would also print '
                                         f'{more}: no game row uses these values, they are not listed')
                    notes.append('attributes 0-3 are the attribute stats themselves (0 Strength, 1 Energy, '
                                 '2 Dexterity, 3 Vitality: tables use 0, 2, 3); 4 is named by the rune text only')
                if sid in TEXT_ENUMS:
                    enums[fl[0][0]] = {k: v[0] for k, v in TEXT_ENUMS[sid].items()}
                if enums:
                    e['enums'] = enums
                if e['kind'] == 'skill' or e['kind'] == 'packed' and fl[-1][1] == 'skill':
                    sks = {(p >> fl[-1][2]) for p in seen}
                    if any(not self.skill_own(k) for k in sks):
                        e['hidden_skills'] = True          # its params name skills without a display name
            if sid in LABELS:
                e['label'] = LABELS[sid]
            if sid in DLL:
                e['dll'] = DLL[sid]
            e['note'] = '; '.join(notes)
            table[sid] = e
            lab = plain(ic.get('desc'))
            if 'POLAR BUFFALO' in lab.upper():
                import mxl_statnames_ext
                lab = '(no game text) ' + (mxl_statnames_ext.fallback_label(sid) or '')
            report.append(f'stat {sid}  [{e["kind"]}, {e["conf"]}]  {pb} param bits  "{lab}"')
            if e.get('by'):
                report.append(f'    settled by: {e["by"]}' + (f'; neutral line: "{e["rendered"]}"' if e.get('rendered') else ''))
            if e.get('layout'):
                report.append(f'    layout: {e["layout"]}')
            for k, en in (e.get('enums') or {}).items():
                report.append(f'    {k}: ' + ', '.join(f'{a} {b}' for a, b in en.items()))
            report.append(f'    observed: {len(obs)} distinct params in the tables, {len(sav)} on saved items'
                          + (f' {seen}' if 'values' in e and seen else ''))
            for n in notes:
                report.append(f'    - {n}')
            if e.get('dll'):
                report.append(f'    ? the game code would settle: {e["dll"]}')
        return table, report

    def write(self, table, report):
        kinds = collections.Counter(e['kind'] for e in table.values())
        confs = collections.Counter(e['conf'] for e in table.values())
        bys = collections.Counter(e.get('by') or 'nothing' for e in table.values())
        ver = ''
        try:
            import json
            with open(os.path.join(self.d.folder, 'install.json'), encoding='utf-8') as f:
                ver = str(json.load(f).get('version') or '')
        except Exception:
            pass
        head = [
            '"""What the PARAMETER of each stat with save-param bits means.',
            '',
            'GENERATED by tools/gen_statparams.py from the game\'s own tables - do not edit, re-run the tool after a',
            'game patch (its --report lists the evidence of every stat). Used through mxl_statnames (param_spec ...).',
            '',
            'PARAMS[stat id] = {',
            "  'kind':   skill | class | state | monster | montype | element | orb | string | packed | number | unknown,",
            "  'conf':   proven (two or more values whose meaning the data shows) | inferred (rule / one example) | unknown,",
            "  'by':     rendered (the item display's line names the values) | tables | rule; 'rendered': that line,",
            "  'bits':   param bits of the save format,",
            "  'fields': [(name, kind, first bit, bits)] - one entry, or the layout of a packed param,",
            "  'enums':  {field name: {value: name}} for the small enumerations the data names,",
            "  'label':  the stat's label when the game's own string bakes one param value into it,",
            "  'hidden_skills': the tables use skills without a display name for it,",
            "  'seen' / 'values': distinct params observed (tables + test saves) / the values when there are few,",
            "  'note':   the evidence, 'dll': what only the game code could settle}",
            '',
            f'{len(table)} stats: ' + ', '.join(f'{n} {k}' for k, n in sorted(kinds.items())) + '.',
            'Confidence: ' + ', '.join(f'{n} {k}' for k, n in sorted(confs.items())) + '.',
            'Settled by: ' + ', '.join(f'{n} {k}' for k, n in sorted(bys.items()))
            + ' (rendered = the item display\'s own line names the values).',
            '"""',
            '',
            f'GAME_DATA = {ver!r}',
            '',
            'PARAMS = ' + pprint.pformat(table, width=118, sort_dicts=False, compact=True),
            '',
        ]
        out = self.args.out
        with open(out, 'w', encoding='utf-8') as f:
            f.write('\n'.join(head))
        text = [f'{len(table)} stats with param bits', 'kinds: ' + ', '.join(f'{k} {n}' for k, n in sorted(kinds.items())),
                'confidence: ' + ', '.join(f'{k} {n}' for k, n in sorted(confs.items())),
                'settled by: ' + ', '.join(f'{k} {n}' for k, n in sorted(bys.items())), ''] + report
        if self.args.report:
            with open(self.args.report, 'w', encoding='utf-8') as f:
                f.write('\n'.join(text) + '\n')
        else:
            print('\n'.join(text[:4]))
        print('written:', out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--app', default=os.environ.get('MXL_APP_DIR'), help='folder of the built app\'s modules')
    ap.add_argument('--user-dir', default=os.environ.get('MXL_USER_DIR'), help='COPY of the editor\'s user folder')
    ap.add_argument('--save-dir', action='append', help='copy of a save folder (repeatable)')
    ap.add_argument('--out', default=os.path.join(here, '..', 'src', 'mxl_statparams.py'))
    ap.add_argument('--report', help='write the evidence report to this file')
    args = ap.parse_args()
    if not args.app or not args.user_dir:
        ap.error('--app and --user-dir are needed')
    os.environ['MXL_USER_DIR'] = args.user_dir
    os.environ.setdefault('MXL_SAVE_DIR', (args.save_dir or [args.user_dir])[0])
    sys.path.insert(0, args.app)
    g = Gen(args)
    g.collect()
    g.write(*g.build())


if __name__ == '__main__':
    main()
