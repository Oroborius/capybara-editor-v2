"""Stat and parameter vocabulary of stock LoD 1.14d, for item editors.

Everything is read from the stock MPQ stack (Patch_D2 > d2exp > d2data, whole-file
override) through d2bt.legit.data.game_tables. Strings come from the .tbl files
with patchstring > expansionstring > string priority (GameData.text). Line
rendering reuses d2bt.tooltip.item (stat_text / stat_lines), the descfunc
reconstruction the item tooltips already use.
"""
from functools import lru_cache
from pathlib import Path

from ..tooltip.data import GameData, to_int
from ..tooltip.item import ItemTables, Stats, V, stat_lines

EXTRA_TABLES = ('montype', 'monstats', 'states')
SCHEMA = 1
MOO = 'ref/D2MOO/source/D2Common/src/'
MODS = MOO + 'Items/ItemMods.cpp'
ITEMS = MOO + 'Items/Items.cpp'
STATLIST = MOO + 'D2StatList.cpp'
TOOLTIP = 'd2bt/tooltip/item.py'

# Property function -> (name, inputs read, decomp source). par is Properties-row param (pProperty->nLayer in the
# decomp), min/max the authored range, val the properties.txt valN column (nLayer argument of
# ITEMMODS_AddPropertyToItemStatList for func 21, the bonus for func 36), shared = reuses the value
# rolled by the property's first stat when one exists (nValue argument).
FUNCS = {
    1: ('plain', 'min max', 'ItemMods.cpp:2879 PropertyFunc01: roll(min,max), layer 0'),
    2: ('plain', 'min max', 'ItemMods.cpp:2976 PropertyFunc02: roll(min,max), layer 0'),
    3: ('shared', 'min max', 'ItemMods.cpp:3026 PropertyFunc03: first stat rolls, later stats reuse it'),
    4: ('shared', 'min max', 'ItemMods.cpp:3080 PropertyFunc04: like 3 (unused by stock properties)'),
    5: ('damage_min', 'min max', 'ItemMods.cpp:3134 PropertyFunc05: mindamage, secondary and throw minimum'),
    6: ('damage_max', 'min max', 'ItemMods.cpp:3257 PropertyFunc06: maxdamage, secondary and throw maximum'),
    7: ('damage_percent', 'min max', 'ItemMods.cpp:3386 PropertyFunc07: min and max damage percent'),
    8: ('shared', 'min max', 'ItemMods.cpp:3485 PropertyFunc08: speed stats, layer 0'),
    9: ('shared', 'par min max', 'ItemMods.cpp:3534 PropertyFunc09: param is the layer, validated as a skill id'),
    10: ('skilltab', 'par min max', 'ItemMods.cpp:3642 PropertyFunc10: layer = param%3 + 8*(param//3)'),
    11: ('chance_skill', 'par min max', 'ItemMods.cpp:3697 PropertyFunc11: min chance, max skill level'),
    12: ('skill_rand', 'par min max', 'ItemMods.cpp:4261 PropertyFunc12: rolled skill id in [min,max] is the layer, param the bonus'),
    13: ('durability_percent', 'min max', 'ItemMods.cpp:4306 PropertyFunc13: max durability percent, raises durability'),
    14: ('sockets', 'min max', 'ItemMods.cpp:3766 PropertyFunc14: sockets (min/max or the param)'),
    15: ('min_part', 'min', 'ItemMods.cpp:4028 PropertyFunc15: authored min only'),
    16: ('max_part', 'max', 'ItemMods.cpp:4049 PropertyFunc16: authored max only'),
    17: ('per_level', 'par min max', 'ItemMods.cpp:4070 PropertyFunc17: param is the coefficient; min/max roll when param is 0'),
    18: ('by_time', 'par min max', 'ItemMods.cpp:3963 PropertyFunc18: param period 0-3, min/max stored +256, clamped 0-1023'),
    19: ('charged', 'par min max', 'ItemMods.cpp:3851 PropertyFunc19: min charges, max skill level (0 auto, negative scaled)'),
    20: ('flag', '', 'ItemMods.cpp:4135 PropertyFunc20: sets item_indestructible, no inputs'),
    21: ('layer_from_val', 'min max val', 'ItemMods.cpp:4154 PropertyFunc21: roll(min,max), layer = properties valN'),
    22: ('layer_from_param', 'par min max', 'ItemMods.cpp:4216 PropertyFunc22: layer = param (skill, montype, monster, state)'),
    23: ('flag', '', 'ItemMods.cpp:4370 PropertyFunc23: ethereal flag, no inputs'),
    24: ('layer_from_param', 'par min max', 'ItemMods.cpp:3593 PropertyFunc24: layer = param, roll(min,max)'),
    36: ('rand_class', 'min max val', 'ItemMods.cpp:4200 PropertyFunc36: class in [min,max] is the layer, val the bonus'),
}

# Layer bit splits in the item save, as (name, shift, bits). Widths are the stock save param bits.
SPLITS = {
    'skilltab': ((('tab', 0, 3), ('class', 3, 3)), 'ItemMods.cpp:3642; Items.cpp:6325'),
    'chance_skill': ((('skill_level', 0, 6), ('skill', 6, 10)), 'ItemMods.cpp:3697/3851'),
    'charged': ((('skill_level', 0, 6), ('skill', 6, 10)), 'ItemMods.cpp:3851'),
    'skill': ((('skill', 0, 9),), 'Items.cpp:6325 (stock Save Param Bits 9)'),
    'class': ((('class', 0, 3),), 'Items.cpp:6325 (Save Param Bits 3)'),
    'elem': ((('elem', 0, 3),), 'Items.cpp:6325 (Save Param Bits 3)'),
    'montype': ((('montype', 0, 10),), 'Items.cpp:6325 (Save Param Bits 10)'),
    'monster': ((('monster', 0, 10),), 'Items.cpp:6325 (Save Param Bits 10)'),
    'state': ((('state', 0, 8),), 'Items.cpp:6325 (Save Param Bits 8)'),
}
CHARGE_SPLIT = (('charges', 0, 8), ('capacity', 8, 8))
BYTIME_SPLIT = (('period', 0, 2), ('min_plus_256', 2, 10), ('max_plus_256', 12, 10))
OPS = {
    1: 'adds op_stat percent of the owner item value (D2StatList.cpp:213)',
    2: 'adds (value * op_base) >> op_param to op_stat 1 (D2StatList.cpp:233)',
    3: 'like 2, base read through the total stat (D2StatList.cpp:261)',
    4: 'adds (value * op_base) >> op_param, summed as percent (D2StatList.cpp:290)',
    5: 'like 4, total stat base (D2StatList.cpp:313)',
    6: 'by-time bonus of op_stat (D2StatList.cpp:337)',
    7: 'by-time percent of the accumulated value (D2StatList.cpp:349)',
    8: 'energy to mana (charstats ManaPerMagic) (D2StatList.cpp:361)',
    9: 'vitality to life/stamina (charstats per-vitality) (D2StatList.cpp:381)',
    11: 'percent of op_stat (D2StatList.cpp:408)',
    13: 'percent of op_stat on item (D2StatList.cpp:418)',
}


def _split_doc(kind):
    return [{'name': n, 'shift': s, 'bits': b} for n, s, b in SPLITS[kind][0]]


class Vocab:
    """Tables and string access for one game installation."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.gd = GameData(str(self.directory))
        self.it = ItemTables(self.gd)
        self.classes = [r for r in range(len(self.gd.table('playerclass')))
                        if self.gd.table('playerclass').get(r, 'Code').strip().lower() not in ('', 'expansion')]
        self.stat_names = {sid: self.it.s(sid, 'Stat') for sid in self.it.row_of}

    def text(self, key):
        return self.gd.text(key)

    def key_text(self, key):
        key = (key or '').strip()
        return {'key': key, 'text': self.gd.text(key) if key else ''}

    def stat_id(self, stat):
        if isinstance(stat, int):
            return stat
        return self.it.stat_id[str(stat).strip().lower()]

    def class_name(self, index):
        pc = self.gd.table('playerclass')
        rows = self.classes
        return pc.get(rows[index], 'Player Class') if 0 <= index < len(rows) else ''


def load(game_dir=None, tables=None):
    """A Vocab for a game install (default: the local LoD) or a directory of extracted tables."""
    if tables is not None:
        return _load_dir(str(Path(tables).resolve()))
    from ..legit.data import TABLES, game_tables
    if game_dir is None:
        import os
        game_dir = os.environ.get('D2BT_LEGIT_GAME') or (
            Path.home() / 'Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')
    return _load_dir(str(game_tables(game_dir, TABLES + EXTRA_TABLES)))


@lru_cache(maxsize=4)
def _load_dir(directory):
    return Vocab(directory)


# ------------------------------------------------------------------------------------ stats

def param_kind(v, sid):
    """(kind, role, layout-key, value-kind) of one itemstatcost row."""
    it = v.it
    fn, enc, pb = it.n(sid, 'descfunc'), it.n(sid, 'Encode'), it.n(sid, 'Save Param Bits')
    name = it.s(sid, 'Stat').strip()
    op = it.n(sid, 'op')
    if enc == 3 and fn == 24:
        return 'charged', None, 'charged', 'charges'
    if enc == 2 and fn == 15:
        return 'chance_skill', None, 'chance_skill', 'chance'
    if enc == 4:
        return 'bytime', None, None, 'bytime'
    if fn == 27:
        return 'skill', 'single_skill', 'skill', 'bonus'
    if fn == 28:
        return 'skill', 'oskill', 'skill', 'bonus'
    if fn == 16:
        return 'skill', 'aura', 'skill', 'level'
    if fn == 13:
        return 'class', None, 'class', 'bonus'
    if fn == 14:
        return 'skilltab', None, 'skilltab', 'bonus'
    if fn == 22:
        return 'montype', None, 'montype', 'bonus'
    if fn == 23:
        return 'monster', None, 'monster', 'bonus'
    if name == 'item_elemskill':
        return 'elem', None, 'elem', 'bonus'
    if name == 'state':
        return 'state', None, 'state', 'flag'
    if pb:
        return 'raw', None, None, 'plain'
    if 2 <= op <= 5 and it.s(sid, 'op base').strip().lower() == 'level':
        return 'none', None, None, 'per_level'
    return 'none', None, None, 'plain'


def stat_entry(v, sid):
    it = v.it
    n = lambda c: it.n(sid, c)
    kind, role, split, vkind = param_kind(v, sid)
    row = {
        'id': sid, 'name': it.s(sid, 'Stat').strip(),
        'signed': bool(n('Signed')), 'send_bits': n('Send Bits'), 'send_param_bits': n('Send Param Bits'),
        'saved': bool(n('Save Bits')), 'save_bits': n('Save Bits'), 'save_add': n('Save Add'),
        'save_param_bits': n('Save Param Bits'), 'val_shift': n('ValShift'), 'encode': n('Encode'),
        'descpriority': n('descpriority'), 'descfunc': n('descfunc'), 'descval': n('descval'),
        'descstrpos': v.key_text(it.s(sid, 'descstrpos')), 'descstrneg': v.key_text(it.s(sid, 'descstrneg')),
        'descstr2': v.key_text(it.s(sid, 'descstr2')),
        'dgrp': n('dgrp'), 'dgrpfunc': n('dgrpfunc'), 'dgrpval': n('dgrpval'),
        'dgrpstrpos': v.key_text(it.s(sid, 'dgrpstrpos')), 'dgrpstrneg': v.key_text(it.s(sid, 'dgrpstrneg')),
        'dgrpstr2': v.key_text(it.s(sid, 'dgrpstr2')),
        'op': n('op'), 'op_param': n('op param'), 'op_base': it.s(sid, 'op base').strip(),
        'op_stats': [s for s in (it.s(sid, 'op stat%d' % i).strip() for i in (1, 2, 3)) if s],
        'param_kind': kind, 'value_kind': vkind,
    }
    cite = [f'{ITEMS}:6325 ITEMS_ReadStatFromItemBitstream (save layout)']
    if role:
        row['param_role'] = role
    if split:
        row['param_layout'] = _split_doc(split)
        if split == 'skilltab':   # the class field takes the rest of the stock 16 save param bits
            row['param_layout'][1]['bits'] = row['save_param_bits'] - 3
        cite.append(f'{MODS if "ItemMods" in SPLITS[split][1] else ITEMS}: {SPLITS[split][1]}')
    if kind == 'charged':
        row['value_layout'] = [{'name': a, 'shift': b, 'bits': c} for a, b, c in CHARGE_SPLIT]
        row['value_note'] = 'value = charges | capacity << 8; layer = skill << 6 | skill level'
    elif kind == 'chance_skill':
        row['value_note'] = 'value = percent chance; layer = skill << 6 | skill level'
    elif kind == 'bytime':
        row['value_layout'] = [{'name': a, 'shift': b, 'bits': c} for a, b, c in BYTIME_SPLIT]
        row['value_note'] = 'saved value = period + 4 * (min + 256 + ((max + 256) << 10)); no layer'
        cite.append(f'{MODS}:3963 PropertyFunc18')
    elif kind == 'skilltab':
        row['value_note'] = 'layer = class << 3 | tab (tab 0-2)'
    if kind == 'skill' and role == 'aura':
        row['value_note'] = 'layer = aura skill id; value = aura level'
    if row['op'] in OPS:
        row['op_doc'] = OPS[row['op']]
        cite.append(f'{STATLIST}:208 switch (nOp)')
    if vkind == 'per_level':
        shift = row['op_param']
        row['per_level'] = {
            'base': 'character level', 'op_stat': row['op_stats'][0] if row['op_stats'] else '',
            'target': it.s(sid, 'op stat1').strip() or None, 'per_level_numerator': 1,
            'per_level_denominator': 1 << shift,
            'formula': f'floor(value * clvl / {1 << shift})',
            'stat_value_is': 'coefficient: value/%d added per character level' % (1 << shift),
        }
        cite.append(f'{MODS}:4070 PropertyFunc17 stores the raw coefficient')
    if row['descfunc']:
        cite.append(f'{TOOLTIP} stat_text descfunc {row["descfunc"]} (D2Client descfunc reconstruction)')
    row['sources'] = cite
    return row


def stats_section(v):
    return [stat_entry(v, sid) for sid in sorted(v.it.row_of)
            if v.it.s(sid, 'Stat').strip()]


# ------------------------------------------------------------------------------------ vocabularies

def classes_section(v):
    it = v.it
    out = []
    for index, row in enumerate(v.classes):
        out.append({
            'id': index, 'name': v.class_name(index), 'code': v.gd.table('playerclass').get(row, 'Code').strip(),
            'all_skills': it.charstat(index, 'StrAllSkills'), 'class_only': it.charstat(index, 'StrClassOnly'),
            'skilltab_strings': [it.charstat(index, 'StrSkillTab%d' % t) for t in (1, 2, 3)],
        })
    return out


def skill_tab_text(v, layer, value=1):
    """The line the game prints for item_addskill_tab (descfunc 14)."""
    cls, tab = layer >> 3, layer & 7
    if not 0 <= cls < len(v.classes) or not 0 <= tab <= 2:
        return ''
    return display(188, layer, value, vocab=v)


def skilltabs_section(v):
    it = v.it
    sk, sd = v.gd.table('skills'), v.gd.table('skilldesc')
    by_tab = {}
    for sid in range(len(sk)):
        desc = sd.find(sk.get(sid, 'skilldesc').strip()) if sk.get(sid, 'skilldesc').strip() else -1
        cls = it.skill_class(sid)
        if desc >= 0 and cls >= 0:
            page = to_int(sd.get(desc, 'SkillPage'))
            if 1 <= page <= 3:
                by_tab.setdefault((cls, page - 1), []).append(sid)
    out = []
    for cls in range(len(v.classes)):
        for tab in range(3):
            layer = (cls << 3) | tab
            out.append({
                'layer': layer, 'class': cls, 'tab': tab, 'property_param': cls * 3 + tab,
                'template': it.charstat(cls, 'StrSkillTab%d' % (tab + 1)),
                'class_only': it.charstat(cls, 'StrClassOnly'),
                'text_for_value_1': display(188, layer, 1, vocab=v),
                'text_for_value_2': display(188, layer, 2, vocab=v),
                'skills': by_tab.get((cls, tab), []),
            })
    return out


def stock_property_uses(v):
    """{(property code, lower param): count} over the stock tables that carry properties."""
    from . import properties as rows_properties
    uses = {}
    layouts = (
        ('magicprefix', 'mod{}code mod{}param mod{}min mod{}max', range(1, 4)),
        ('magicsuffix', 'mod{}code mod{}param mod{}min mod{}max', range(1, 4)),
        ('automagic', 'mod{}code mod{}param mod{}min mod{}max', range(1, 4)),
        ('uniqueitems', 'prop{} par{} min{} max{}', range(1, 13)),
        ('setitems', 'prop{} par{} min{} max{}', range(1, 10)),
        ('setitems', 'aprop{} apar{} amin{} amax{}',
         [f'{i}{s}' for i in range(1, 6) for s in 'ab']),
        ('runes', 't1code{} t1param{} t1min{} t1max{}', range(1, 8)),
    )
    for name, pattern, ids in layouts:
        table = v.gd.table(name)
        for r in range(len(table)):
            row = {k.lower(): s.strip() for k, s in table.row(r).items()}
            for code, param, _lo, _hi in rows_properties(row, pattern, ids):
                key = (code.lower(), param.lower())
                uses[key] = uses.get(key, 0) + 1
    return uses


def skills_section(v, uses):
    it = v.it
    sk = v.gd.table('skills')
    sd = v.gd.table('skilldesc')
    by_skill = {}
    for (code, param), count in uses.items():
        if code in ('oskill', 'aura', 'skill', 'att-skill', 'hit-skill', 'gethit-skill', 'kill-skill',
                    'death-skill', 'levelup-skill', 'charged'):
            index = it.skill_index(param)
            if index >= 0:
                by_skill.setdefault(index, {})[code] = by_skill.get(index, {}).get(code, 0) + count
    out = []
    for sid in range(len(sk)):
        name = sk.get(sid, 'skill').strip()
        if not name or name.lower() == 'expansion':
            continue
        desc = sk.get(sid, 'skilldesc').strip()
        drow = sd.find(desc) if desc else -1
        cls = it.skill_class(sid)
        out.append({
            'id': to_int(sk.get(sid, 'Id'), sid), 'row': sid, 'name': name, 'display_name': it.skill_name(sid),
            'name_key': sd.get(drow, 'str name') if drow >= 0 else '', 'charclass': sk.get(sid, 'charclass').strip(),
            'class': cls, 'class_name': v.class_name(cls) if cls >= 0 else '',
            'tab': to_int(sd.get(drow, 'SkillPage')) - 1 if drow >= 0 and to_int(sd.get(drow, 'SkillPage')) else None,
            'reqlevel': to_int(sk.get(sid, 'reqlevel')), 'maxlvl': to_int(sk.get(sid, 'maxlvl')),
            'passive': sk.get(sid, 'passive').strip() == '1',
            'aura': sk.get(sid, 'aura').strip() == '1',
            'can_aura': sk.get(sid, 'aura').strip() == '1',
            'can_oskill': bool(desc) and drow >= 0,
            'stock_uses': by_skill.get(sid, {}),
        })
    return out


def elem_section(v, uses):
    props = v.gd.table('properties')
    out = {'item_elemskill': [], 'damage_stats': []}
    for r in range(len(props)):
        for i in range(1, 8):
            stat = props.get(r, 'stat%d' % i).strip().lower()
            if stat == 'item_elemskill':
                out['item_elemskill'].append({
                    'property': props.get(r, 'code'), 'layer': to_int(props.get(r, 'val%d' % i)),
                    'line_for_value_1': display(126, to_int(props.get(r, 'val%d' % i)), 1, vocab=v),
                })
    for lo, hi, ln in ((48, 49, None), (54, 55, None), (50, 51, None), (52, 53, None), (57, 58, 59)):
        entry = {'min_stat': v.stat_names[lo], 'max_stat': v.stat_names[hi], 'min_id': lo, 'max_id': hi}
        if ln:
            entry.update(length_stat=v.stat_names[ln], length_id=ln)
        out['damage_stats'].append(entry)
    out['note'] = ('item_elemskill: descfunc 1 prints only the stat text; the layer (stock fireskill: 1) '
                   'is stored but does not select a different string')
    return out


def montypes_section(v):
    mt = v.gd.table('montype')
    out = []
    for r in range(len(mt)):
        code = mt.get(r, 'type').strip()
        if not code:
            continue
        out.append({'id': r, 'code': code, 'plural': v.key_text(mt.get(r, 'strplur')),
                    'singular': v.key_text(mt.get(r, 'strsing')),
                    'line_for_value_1': display(179, r, 1, vocab=v)})
    return out


def monsters_section(v):
    ms = v.gd.table('monstats')
    return [{'id': r, 'code': ms.get(r, 'Id').strip(), 'name': v.key_text(ms.get(r, 'NameStr'))}
            for r in range(len(ms)) if ms.get(r, 'Id').strip()]


def states_section(v):
    st = v.gd.table('states')
    return [{'id': to_int(st.get(r, 'id'), r), 'name': st.get(r, 'state').strip()}
            for r in range(len(st)) if st.get(r, 'state').strip() and st.get(r, 'state').strip().lower() != 'expansion']


def param_domains(v, stats):
    """Which stats take which parameter domain, with the property funcs that fill them."""
    out = {}
    for row in stats:
        if row['param_kind'] not in ('none', 'raw'):
            out.setdefault(row['param_kind'], []).append(
                {'id': row['id'], 'name': row['name'], 'role': row.get('param_role'), 'save_param_bits': row['save_param_bits']})
    return out


# ------------------------------------------------------------------------------------ properties

# Domain of each authored field per function; 'by_stat' takes the first stat's own param kind.
FUNC_DOMAINS = {
    9: {'par': 'skill'}, 10: {'par': 'skilltab_param'}, 11: {'par': 'skill'},
    12: {'par': 'bonus', 'min': 'skill', 'max': 'skill'}, 17: {'par': 'coefficient'},
    18: {'par': 'period'}, 19: {'par': 'skill'}, 21: {'val': 'by_stat'},
    22: {'par': 'by_stat'}, 24: {'par': 'by_stat'}, 36: {'val': 'bonus', 'min': 'class', 'max': 'class'},
}


def property_domains(v, stats):
    out = {}
    for slot in stats:
        for field, domain in FUNC_DOMAINS.get(slot['func'], {}).items():
            if domain == 'by_stat':
                sid = slot['stat_id']
                domain = param_kind(v, sid)[0] if sid is not None else 'none'
            out.setdefault(field, domain)
    return out


def properties_section(v):
    props = v.gd.table('properties')
    out = []
    for r in range(len(props)):
        code = props.get(r, 'code').strip()
        if not code:
            continue
        stats = []
        for i in range(1, 8):
            func = to_int(props.get(r, 'func%d' % i))
            stat = props.get(r, 'stat%d' % i).strip()
            if not func and not stat:
                continue
            sid = v.it.stat_id.get(stat.lower()) if stat else None
            info = FUNCS.get(func, ('unknown', '', ''))
            stats.append({
                'slot': i, 'func': func, 'func_name': info[0], 'stat': stat, 'stat_id': sid,
                'set': props.get(r, 'set%d' % i).strip(), 'val': props.get(r, 'val%d' % i).strip(),
                'uses': info[1].split(), 'source': info[2],
            })
        uses = sorted({u for s in stats for u in s['uses']})
        domains = property_domains(v, stats)
        out.append({
            'code': code, 'stats': stats, 'funcs': [s['func'] for s in stats], 'uses': uses,
            'domains': domains, 'param_kind': domains.get('par', 'none'),
        })
    return out


# ------------------------------------------------------------------------------------ display

def _strip(segments):
    return ''.join(text for text, _colour in segments)


def display_lines(entries, level=99, vocab=None):
    """Lines the game prints for [(stat, param, value)] together, in its order.

    stat is an id or an itemstatcost name; value an int or (low, high). Related stats combine
    (damage ranges, enhanced damage, poison, resist all) exactly as in the item tooltips."""
    v = vocab or load()
    st = Stats()
    for stat, param, value in entries:
        st.add(v.stat_id(stat), int(param), V(*value) if isinstance(value, tuple) else V(value))
    return [_strip(segments) for segments, _kind in stat_lines(v.it, st, level)]


def display(stat, param=0, value=0, *, level=99, vocab=None):
    """The line the game prints for one stat (value may be (low, high)); '' when it prints none."""
    lines = display_lines([(stat, param, value)], level, vocab)
    return '\n'.join(lines)


# ------------------------------------------------------------------------------------ top level

def build(game_dir=None, tables=None):
    v = load(game_dir, tables)
    stats = stats_section(v)
    uses = stock_property_uses(v)
    return {
        'version': '1.14d', 'schema': SCHEMA,
        'stats': stats,
        'vocabularies': {
            'classes': classes_section(v), 'skilltabs': skilltabs_section(v),
            'skills': skills_section(v, uses), 'elemental': elem_section(v, uses),
            'montypes': montypes_section(v), 'monsters': monsters_section(v), 'states': states_section(v),
            'param_domains': param_domains(v, stats),
            'op_codes': {str(k): s for k, s in OPS.items()},
            'param_splits': {k: {'fields': _split_doc(k), 'source': s[1]} for k, s in SPLITS.items()},
        },
        'properties': properties_section(v),
        'property_funcs': {str(f): {'name': i[0], 'reads': i[1].split(), 'source': i[2],
                               'domains': FUNC_DOMAINS.get(f, {})}
                           for f, i in FUNCS.items()},
    }
