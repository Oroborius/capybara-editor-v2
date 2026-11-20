"""Readable stat labels and skill params for the editors.

The game's own string tables hold 'FLYING POLAR BUFFALO ERROR' placeholders for many of Median XL's
internal / unused stats: the editors show a neutral '(stat #N)' or '(hidden stat #N)' for those instead.

Also knows which stats carry a skill (or a class) in their param and how to decode / encode it, so the
editors can show the skill's name in a dropdown and type the chance separately:
- the CHANCE_TO_CAST stats (195 - 203), e.g. '%d%% Chance to cast level %d %s on Striking':
  param = (skill id << 6) | level shown;
- the SINGLE_SKILL stats (97, 107), e.g. 'to %s': param = skill id;
- the class skill stat (83), e.g. 'to %s Skill Levels': param = class index.

What the param of EVERY stat with param bits means comes from the generated table mxl_statparams.PARAMS
(tools/gen_statparams.py): param_spec() / param_kind() / param_choices() / param_name() / param_value() /
param_title() / param_text() below turn it into names for the editors:
- 'skill'      skill << 6 | level (chance to cast, charges, the hidden procs): a skill name + a level;
- 'skill_only' a skill id (oskills, cooldown, the per-skill modifier slots, the worn aura);
- 'class'      a class index;
- 'named'      one value picked by name: state, monster, mystic orb, monster group, or - for a packed param of
               two small enumerations (innate elemental damage: element | attribute << 8) - their combination;
- None         a plain number (unknown meaning, string index, no param).
A value without a name is shown and accepted as '#N', so raw numbers stay possible everywhere.
"""
import re
import struct

CHANCE_TO_CAST = list(range(195, 204))
SINGLE_SKILLS = (97, 107)
CLASS_SKILLS = 83
SHORT_LIST = 40              # up to this many names: a plain dropdown; more: the searchable list
_RAW = re.compile(r'^\s*#?\s*(\d+)\s*$')
_RAW_TAIL = re.compile(r'#(\d+)\)?\s*$')


def param_spec(sid):
    """The generated entry of a stat with param bits (see mxl_statparams), or None."""
    try:
        import mxl_statparams
        return mxl_statparams.PARAMS.get(sid)
    except Exception:
        return None


def stat_text(data, sid, param=None, value=1, desc=None):
    """The stat's own game text (plain, no colour codes); '' when the game shows none for it
    (hidden stat, or the buffalo placeholder of the mod's unused stats)."""
    try:
        from mxl_rules import stat_label
        from mxl_creator import _plain
        txt = _plain(stat_label(dict(id=sid, param=param, value=value, desc=desc), data))
    except Exception:
        return ''
    if not txt or 'OLAR BUFFALO' in txt.upper():
        txt = ''
    spec = param_spec(sid)
    if spec is not None and param is not None and value is not None:
        line = rendered_line(data, sid, param, value)    # what the item shows on hover, word for word
        if line:
            return line
    if spec is not None:                  # the stat's string needs its param: the game's line for this param
        kinds = [f[1] for f in spec.get('fields') or ()]
        if kinds in (['element', 'attribute'], ['number', 'class']) or '%s' in txt \
                or (not txt and kinds == ['string'] and param):
            alt = param_text(data, sid, param, value=value if kinds == ['element', 'attribute'] else None)
            if alt:
                return alt
    return txt


def rendered_line(data, sid, param, value):
    """The line the item tooltip shows for one stored stat (stat id, param, value) - the text of the hover
    display, plain; '' when the tooltip shows nothing for it (hidden stats) or only a placeholder."""
    try:
        from mxl_stat_text import stat_lines
        out = []
        for ln in stat_lines([dict(id=sid, param=param or None, value=value)], data):
            text = str(ln[1])
            for seg in (ln[2] if len(ln) > 2 else ()) or ():
                text += str(seg[1] if isinstance(seg, (tuple, list)) else seg)
            out.append(re.sub(r'\xffc.', '', text).replace('\n', ' / ').strip())
        txt = ' / '.join(t for t in out if t)
    except Exception:
        return ''
    if not txt or BUFFALO in txt.upper() or '%s' in txt or '%d' in txt:
        return ''
    return txt


def generic_label(sid):
    """The stat's label for the pickers when the game's own string bakes ONE param value into it ('to Amazon
    Skill Levels', 'Innate Fire Damage', '+%d to Javelin and Spear Skills'), else None."""
    return (param_spec(sid) or {}).get('label')


_NAMED = ('state', 'monster', 'orb', 'montype', 'element', 'attribute', 'string')
STRING_IDS = range(10000, 20000)    # the orange texts (description function 31) are patchstring.tbl entries


def param_kind(sid):
    """How the editors show the stat's param: 'skill' (a skill + a level), 'skill_only', 'class', 'named' (one
    name out of a list: state, monster, orb, element / attribute...) or None (a plain number / no param)."""
    spec = param_spec(sid)
    if spec is None:
        if sid in CHANCE_TO_CAST:
            return 'skill'
        if sid in SINGLE_SKILLS:
            return 'skill_only'
        if sid == CLASS_SKILLS:
            return 'class'
        return None
    kinds = [f[1] for f in spec.get('fields') or ()]
    if kinds == ['number', 'skill'] and spec['fields'][0][0] == 'level':
        return 'skill'
    if kinds == ['skill']:
        return 'skill_only'
    if kinds == ['class']:
        return 'class'
    if kinds and all(k in _NAMED for k in kinds):
        if len(kinds) == 1 and kinds[0] in ('montype', 'element') and not spec.get('enums'):
            return None                                  # no value of it has a known name: a plain number
        return 'named'
    return None


def param_title(sid):
    """What the param names, for column / popup titles: 'Skill', 'Class', 'State', 'Element / attribute'..."""
    from mxl_lang import T
    spec = param_spec(sid) or {}
    names = {'skill': T('sn.kind.skill', 'Skill'), 'class': T('sn.kind.class', 'Class'),
             'state': T('sn.kind.state', 'State'), 'monster': T('sn.kind.monster', 'Monster'),
             'orb': T('sn.kind.orb', 'Mystic orb'), 'montype': T('sn.kind.montype', 'Monster group'),
             'element': T('sn.kind.element', 'Element'), 'attribute': T('sn.kind.attribute', 'Attribute'),
             'string': T('sn.kind.string', 'Text'), 'number': T('sn.kind.number', 'Param')}
    kinds = [f[1] for f in spec.get('fields') or () if f[0] != 'level']
    if not kinds:
        return {'skill': names['skill'], 'skill_only': names['skill'],
                'class': names['class']}.get(param_kind(sid), names['number'])
    return ' / '.join(names.get(k, k) for k in kinds)


def _classes():
    from mxl_rules import CLASSES
    return CLASSES


def _uniq(pairs):
    """[(name, value)] with every name unique: a name shared by several values gets ' (#value)'."""
    count = {}
    for n, _v in pairs:
        count[n] = count.get(n, 0) + 1
    return [(n if count[n] == 1 else f'{n} (#{v})', v) for n, v in pairs]


def _orb_names(data):
    """[(orb name, row)] of mysticorbs.bin (the mystic orb counter's param is the orb's row)."""
    try:
        import mxl_creator
        cr = data.__dict__.get('_sn_creator')
        if cr is None:
            cr = data.__dict__['_sn_creator'] = mxl_creator.Creator(data)
        out = []
        for i, (code, o) in enumerate(cr._orb_table().items()):
            n = re.sub(r'^MO - ', '', o.get('name') or '') or str(code).strip()
            try:
                shown = cr.display_name(code).split(' - ')[0].strip()
            except Exception:
                shown = ''
            if shown and shown.lower() not in n.lower() and 'mystic orb' not in shown.lower():
                n = f'{shown} [{n}]'
            out.append((n, i))
        return out
    except Exception:
        return []


def _field_choices(data, spec, field):
    """[(name, value)] of one field of a param, by the field's kind; [] when its values have no names."""
    name, kind, _shift, bits = field
    enum = (spec.get('enums') or {}).get(name)
    if enum:
        return [(str(n), v) for v, n in sorted(enum.items())]
    if kind == 'class':
        return list((n, i) for i, n in enumerate(_classes()))
    if kind == 'state':
        return state_names_sorted(data)
    if kind == 'monster':
        names = getattr(data, 'monster_names', None) or []
        return [(str(n).replace('\n', ' ').strip(), i) for i, n in enumerate(names)
                if n and BUFFALO not in str(n).upper() and i < (1 << bits)]
    if kind == 'orb':
        return _orb_names(data)
    if kind == 'string':
        return _string_names(data, bits)
    return []


def _string_names(data, bits):
    """[(text, string id)] for a param that IS a string index (the orange-text stats 375 / 377 / 378 / 385):
    every non-empty entry of the patchstring range (where Median keeps all of them), one line per text."""
    cache = data.__dict__.setdefault('_sn_string_names', {})
    if bits in cache:
        return cache[bits]
    out = []
    for i in STRING_IDS:
        if i >= 1 << bits:
            break
        t = data.strings.get(i)
        text = _clean(t[1] if isinstance(t, tuple) and len(t) > 1 else t or '')
        lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        if lines:
            n = ' / '.join(lines)
            out.append((n if len(n) <= 120 else n[:117] + '...', i))
    cache[bits] = out
    return out


def param_choices(data, sid):
    """[(name, value)] the stat's param can be picked from, names unique, sorted for the lists: skills (value
    = skill id; the level of a 'skill' stat is typed separately), classes, states, monsters, orbs, or the
    combinations of a packed param of small enumerations ('Lightning / Dexterity'). [] for plain numbers."""
    kind = param_kind(sid)
    if kind is None:
        return []
    cache = data.__dict__.setdefault('_sn_param_choices', {})
    if sid in cache:
        return cache[sid]
    spec = param_spec(sid) or {}
    if kind in ('skill', 'skill_only'):
        out = skill_names_sorted(data, sid, hidden=True)     # every skill row: named first, then derived
    elif kind == 'class':
        out = [(n, i) for i, n in enumerate(_classes())]
    else:
        fields = spec['fields']
        if len(fields) == 1:
            out = _uniq(_field_choices(data, spec, fields[0]))
            if fields[0][1] not in ('orb', 'class', 'element', 'attribute', 'montype'):
                out.sort(key=lambda x: x[0].lower())
        else:                                            # a packed param: every combination, first field first
            out = [('', 0)]
            for f in fields:
                ch = _field_choices(data, spec, f)
                out = [((a + ' / ' if a else '') + n, v0 | (v << f[2])) for a, v0 in out for n, v in ch]
    cache[sid] = out
    return out


def param_short(data, sid):
    """True when the stat's param list is short enough for a plain dropdown (classes, elements...)."""
    return param_kind(sid) in ('class', 'named') and len(param_choices(data, sid)) <= SHORT_LIST


def _field_name(data, spec, field, v):
    n = next((n for n, val in _field_choices(data, spec, field) if val == v), None)
    if n is None and field[1] == 'state':
        n = state_name(data, v)
    return n


def param_name(data, sid, param):
    """The name of a 'class' / 'named' param value ('Lightning / Dexterity', 'Undead Marksman'), exactly as
    param_choices lists it; '#N' when the value has no name (param_value takes that back)."""
    param = param or 0
    for n, v in param_choices(data, sid):
        if v == param:
            return n
    spec = param_spec(sid) or {}
    fields = spec.get('fields') or ()
    if len(fields) > 1:                                  # name the parts that have one
        parts = []
        for f in fields:
            v = (param >> f[2]) & ((1 << f[3]) - 1)
            parts.append(_field_name(data, spec, f, v) or f'{f[0]} {v}')
        return ' / '.join(parts) + f' (#{param})'
    if fields and fields[0][1] == 'state':
        n = state_name(data, param)
        if n:
            return f'{n} (#{param})'
    return f'#{param}'


def param_value(data, sid, name):
    """The param value of a name given by param_choices / param_name, or of a typed number ('505', '#505');
    None when it is neither or does not fit the stat's param bits."""
    name = str(name or '').strip()
    v = next((v for n, v in param_choices(data, sid) if n == name), None)
    if v is None:
        low = name.lower()
        v = next((v for n, v in param_choices(data, sid) if n.lower() == low), None)
    if v is None:
        m = _RAW.match(name) or _RAW_TAIL.search(name)
        if m:
            v = int(m.group(1))
    bits = min(param_bits(data, sid), 32)
    if v is None or not 0 <= v < (1 << bits):
        return None
    return v


def param_text(data, sid, param, numbers='#', value=None):
    """The game's own line for a stat + param where the stat's string needs the param to make sense, with
    `numbers` in place of the values: 'Innate Lightning Damage: # (#% of Dexterity)', "Jitan's Gate Cooldown
    Reduced by #", 'Split Arrow: +8 Projectiles' (the orange texts). '' when there is no such line."""
    spec = param_spec(sid)
    if spec is None:
        return ''
    try:
        ic = data.isc[sid]
        func = ic.get('func')
        desc = _clean(ic.get('desc'))
        param = param or 0
        kinds = [f[1] for f in spec['fields']]
        if kinds == ['element', 'attribute']:
            el, at = param & 0xFF, param >> 8
            enums = spec.get('enums') or {}
            ename = (enums.get('element') or {}).get(el)
            aname = (enums.get('attribute') or {}).get(at) or f'attribute {at}'
            if ename is None:
                return ''
            if value is not None and value != 1:         # the tooltip's form: the damage needs the character
                return f'Innate {ename} Damage: ({float(value):.1f}% of {aname})'
            return f'Innate {ename} Damage: {numbers} ({numbers}% of {aname})'
        if kinds == ['string']:
            t = data.strings.get(param)
            text = _clean(t[1] if t else '')
            lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
            return ' / '.join(lines) if lines else ''
        if kinds == ['skill'] and func in (33, 37) and '%s' in desc and param:
            sk = skill_name(data, param) or f'skill #{param}'
            txt = desc.replace('%s', sk)
            return re.sub(r'%[+]?\.?\d*[dgfi]', numbers, txt).replace('%%', '%')
        if kinds == ['number', 'class'] and func == 14:           # skill tab: class * 8 + tab
            cl = _classes()
            c, tab = param >> 3, param & 7
            cname = cl[c] if 0 <= c < len(cl) else f'class {c}'
            return f'+{numbers} to {cname} Skills (skill tab {tab})'
    except Exception:
        return ''
    return ''


def _clean(text):
    text = re.sub(r'\xffc.', '', str(text or ''))
    return '' if BUFFALO in text.upper() else text


def decode_param(data, sid, param):
    """Human name of the param the row stored: ('Arrow', 16) for a chance-to-cast stat, ('Tantrum', None),
    ('Necromancer', None) for the class skill stat, ('Lightning / Dexterity', None) for a named param; None
    when the stat has no such param."""
    kind = param_kind(sid)
    if kind is None:
        return None
    if kind in ('class', 'named'):                       # value 0 (stored as no param) is a value of its own
        try:
            return (param_name(data, sid, param), None)
        except Exception:
            return None
    if param is None:
        return None
    try:
        if kind == 'skill':
            sk, lv = param >> 6, param & 63
            return (skill_label(data, sk) or f'skill #{sk}', lv)
        if kind == 'skill_only':
            return (skill_label(data, param) or f'skill #{param}', None)
    except Exception:
        return None
    return None


def encode_param(data, sid, name, level=None):
    """param value from a chosen skill (or class) name and, for the chance-to-cast stats, its level;
    None if the name is not known."""
    kind = param_kind(sid)
    if kind is None:
        return None
    try:
        if kind == 'skill':
            sk = skill_id(data, name)
            if sk is None:
                return None
            return (sk << 6) | (int(level or 0) & 63) if level is not None else sk << 6
        if kind == 'skill_only':
            return skill_id(data, name)
        if kind in ('class', 'named'):
            return param_value(data, sid, name)
    except Exception:
        return None
    return None


def param_bits(data, sid):
    """Bits the save format gives the stat's param field (0 when it has none)."""
    try:
        return data.isc[sid].get('param') or 0
    except (IndexError, KeyError, TypeError):
        return 0


def skill_fits(data, sid, skill_id):
    """Whether the stat's param field can store this skill id. The width is the stat's own Save Param Bits
    (ItemStatCost): Sigma gives the chance-to-cast stats and the hidden procs 17 bits (vanilla: 16), so
    skill << 6 | level holds skill ids 0-2047; the charges stat (204) has 16 bits: ids 0-1023. An id above
    that cannot be written at all (the encoder refuses a param wider than the field).

    Until 2026-11 this function capped every field at 16 bits and refused the ids 1024-2047 for the 17-bit
    stats. What the tables show: the game's own rows hold such params (magic suffix rows 943-945, 948, 1013:
    skills 1319, 1563, 1642, 1700, 1746 on stats 197 / 199), but none of those rows is spawnable - on every
    obtainable row (uniques, sets, runewords, spawnable affixes) the proc skills stay at or below id 853.
    So the save format takes them; how the game treats a proc skill id of 1024 or more is not confirmed."""
    kind = param_kind(sid)
    if kind == 'class':
        cl = _classes()
        return isinstance(skill_id, int) and 0 <= skill_id < len(cl)
    if kind is None:
        return False
    bits = min(param_bits(data, sid), 32)
    if bits <= 0:
        return False
    if kind == 'skill':
        return isinstance(skill_id, int) and bits > 6 and 0 <= skill_id < (1 << (bits - 6))
    return isinstance(skill_id, int) and 0 <= skill_id < (1 << bits)


BUFFALO = 'POLAR BUFFALO'
_ID_SUFFIX = re.compile(r'#(\d+)\)$')


def _own_name(data, sk):
    """The skill's own display name (its skilldesc string), or None: no skilldesc (1952 of Median XL Sigma's
    3018 skills: hidden passives, monster skills, proc helpers) or only the buffalo placeholder."""
    n = data.skill_names.get(sk)
    if not n or BUFFALO in n.upper():
        return None
    return n


def _skill_rows(data):
    rows = getattr(data, '_sn_skill_rows', None)
    if rows is None:
        try:
            rows = data._rows('skills')
        except Exception:
            rows = []
        data._sn_skill_rows = rows
    return rows


def _state_icon_names(data):
    """{state id: name} from stateicons.bin (8-byte rows: u16 state, u16 -, u16 icon, u16 string): the name the
    game writes under the buff icon of the state. A row whose state is 0xFFFF is an icon no state uses (the
    table's "none" marker: 2 rows in 2.14.6, one of them a second "Dragon's Blessing" beside state 471): it is
    no state, and so is any id past the end of states.bin."""
    m = getattr(data, '_sn_state_icons', None)
    if m is None:
        m = {}
        try:
            try:
                n_states = len(data._rows('states'))
            except Exception:
                n_states = 0xFFFF
            for r in data._rows('stateicons'):
                st, _a, _icon, si = struct.unpack_from('<4H', r, 0)
                if st >= min(n_states, 0xFFFF):
                    continue
                n = (data.s(si) or '').replace('\n', ' ').strip()
                if n and BUFFALO not in n.upper():
                    m.setdefault(st, n)
        except Exception:
            m = {}
        data._sn_state_icons = m
    return m


def _short_stat(data, sid):
    """A stat's label without the value placeholders: 'Maximum Stamina'."""
    try:
        txt = stat_text(data, sid, None, 1, data.isc[sid].get('desc'))
    except Exception:
        txt = ''
    if not txt:
        try:
            import mxl_statnames_ext
            txt = mxl_statnames_ext.fallback_label(sid) or ''
        except Exception:
            txt = ''
    txt = re.sub(r'%\+?d|%s|#', '', txt).replace('%%', '%')
    txt = re.sub(r'^[\s+%:-]+|[\s+:-]+$', '', re.sub(r'\s+', ' ', txt))
    return re.sub(r'^to ', '', txt)


def hidden_skill_name(data, sk):
    """Name for a skill of skills.bin that has no display name of its own, from what the row does: the buff
    icon text of its state, the stats its passive / aura gives, the monster it summons; always marked
    '(hidden #id)', which also keeps every name unique. None when sk is not a row of the skills table.
    (The table's internal 'skill' column - 'Dream Aura' - exists only in the mod's .txt sources: the compiled
    skills.bin the game ships holds no name, so it cannot be shown.)"""
    cache = data.__dict__.setdefault('_sn_hidden_names', {})
    if sk in cache:
        return cache[sk]
    rows = _skill_rows(data)
    name = None
    if isinstance(sk, int) and 0 <= sk < len(rows):
        r = rows[sk]
        what = ''
        try:
            states = [v for v in (struct.unpack_from('<H', r, off)[0] for off in STATE_COLS) if 0 < v < 0xFFFF]
            icons = _state_icon_names(data)
            import mxl_rownames as RN
            what = RN.vanilla_names(data, 'skills').get(sk) or next((icons[v] for v in states if v in icons), '')
            what = what or RN.skill_derived(data, sk) or ''
            if not what:
                passive = [v for v in struct.unpack_from('<5h', r, 0x98) if v >= 0]
                aura = [v for v in struct.unpack_from('<6h', r, 0x54) if v >= 0]
                for kind, sids in (('Passive', passive), ('Aura', aura)):
                    labels = []
                    for v in sids:
                        t = _short_stat(data, v)
                        if t and t not in labels:
                            labels.append(t)
                    if labels:
                        what = f"{kind}: {', '.join(labels[:3])}" + (', ...' if len(labels) > 3 else '')
                        break
            if not what:
                mon = struct.unpack_from('<H', r, 0xBC)[0]
                names = getattr(data, 'monster_names', None) or []
                if mon < len(names) and names[mon] and BUFFALO not in str(names[mon]).upper():
                    what = 'Summon: ' + str(names[mon]).replace('\n', ' ').strip()
            if not what:                     # nothing nameable: at least what kind of row it is
                what = RN.skill_fallback(data, sk) or ''
        except Exception:
            what = ''
        name = f"{what or 'Unnamed skill'} (hidden #{sk})"
    cache[sk] = name
    return name


def _first_ids(data):
    """{name: lowest skill id with this display name}: Median XL has 171 names shared by several skills
    (Flamefront x22, Thunderstone x12...)."""
    m = getattr(data, '_sn_first_ids', None)
    if m is None:
        m = {}
        for k in sorted(data.skill_names):
            n = _own_name(data, k)
            if n:
                m.setdefault(n, k)
        data._sn_first_ids = m
    return m


def skill_label(data, sk):
    """The one name the editors show for a skill id, and skill_id() turns back into exactly this id:
    its own name ('Tantrum'); 'Flamefront (#1650)' for a later skill of an already used name (picking it by
    the bare name would silently store the first one); a derived '... (hidden #2064)' name for a skill without
    a name of its own. None only when the id is not in the skills table."""
    n = _own_name(data, sk)
    if n is None:
        return hidden_skill_name(data, sk)
    return n if _first_ids(data).get(n) == sk else f'{n} (#{sk})'


def skill_name(data, sk):
    """Display name of a skill id for texts (tooltips, labels): its own name, else the hidden-skill name."""
    return _own_name(data, sk) or hidden_skill_name(data, sk)


def skill_id(data, name):
    """The skill id of a name given by skill_label (or a plain skill name: its first id); None if unknown."""
    if not name:
        return None
    m = _ID_SUFFIX.search(name)
    if m:
        sk = int(m.group(1))
        if skill_label(data, sk) == name:
            return sk
    sk = _first_ids(data).get(name)
    if sk is not None:
        return sk
    return next((k for k, n in data.skill_names.items() if n == name), None)


def install():
    """The host's Data.skill() (what its stat texts call for '+1 to <skill>') knows only the skills with a
    skilldesc string and says 'skill #2064' for the rest: it now falls back to hidden_skill_name."""
    import mxl_data
    cls = mxl_data.Data
    if getattr(cls, '_sn_skill_patch', False):
        return
    orig = cls.skill

    def skill(self, sid):
        try:
            own = _own_name(self, sid)
            if own:
                return own
            if self.strings and self.key(f'skillname{sid}') != f'skillname{sid}':
                return orig(self, sid)
            n = hidden_skill_name(self, sid)
            if n:
                return n
        except Exception:
            pass
        return orig(self, sid)
    cls.skill = skill
    cls._sn_skill_patch = True
    _install_param_texts()


def _install_param_texts():
    """Two tooltip lines the host leaves unfinished because they need the stat's param:
    - '%s Maximum Skill Level Increased by %d' (stat 449) keeps its placeholders;
    - innate elemental damage with attribute 4 reads '(33.0% of FLYING POLAR BUFFALO ERROR)': the host looks
      the attribute up as a stat, 4 is 'the higher of Strength and Dexterity' (see mxl_statparams, stat 415)."""
    try:
        import mxl_stat_text as st
    except Exception:
        return
    if getattr(st, '_sn_param_patch', False):
        return
    orig_text, orig_innate = st._stat_text, st._innate_damage_line
    st._sn_host_texts = (orig_text, orig_innate)         # tools/gen_statparams.py reads the host's own lines

    def _stat_text(s, c, v, p, s1, data, *rest):
        out = orig_text(s, c, v, p, s1, data, *rest)
        try:
            if isinstance(out, str) and '%s' in out and (c or {}).get('func') == 37 and p:
                sk = skill_name(data, p) or f'skill #{p}'
                return out.replace('%s', sk).replace('%d', str(v))
        except Exception:
            pass
        return out

    def _innate_damage_line(c, v, p, s1, data, *rest):
        out = orig_innate(c, v, p, s1, data, *rest)
        try:
            at = (p or 0) >> 8
            name = (((param_spec(415) or {}).get('enums') or {}).get('attribute') or {}).get(at)
            if name and at > 3:
                def fix(x):
                    if isinstance(x, str):
                        return re.sub(r'of (FLYING POLAR BUFFALO ERROR|\?)\)', f'of {name})', x)
                    if isinstance(x, tuple):
                        return tuple(fix(y) for y in x)
                    if isinstance(x, list):
                        return [fix(y) for y in x]
                    return x
                return fix(out)
        except Exception:
            pass
        return out
    st._stat_text = _stat_text
    st._innate_damage_line = _innate_damage_line
    st._sn_param_patch = True


def encode_skill_param(data, sid, name, level=None):
    """param of a chosen skill name for stat sid: (param, None) on success, else (None, reason) with
    reason 'unknown' (no skill of this name), 'rolled' (its id does not fit the param field: the game
    would roll it to another skill) or 'level' (bad cast level). The plain encode_param keeps its
    behaviour (None) for existing callers."""
    kind = param_kind(sid)
    if kind is None:
        return None, 'unknown'
    if kind in ('class', 'named'):                       # one name out of a list, or a typed '#N'
        v = param_value(data, sid, name)
        return (v, None) if v is not None else (None, 'unknown')
    sk = skill_id(data, name)
    if sk is None:
        m = _RAW.match(str(name or ''))                  # a typed skill number
        if m and skill_label(data, int(m.group(1))):
            sk = int(m.group(1))
    if sk is None:
        return None, 'unknown'
    if not skill_fits(data, sid, sk):
        return None, 'rolled'
    if kind == 'skill':
        try:
            lv = int(level)
        except (TypeError, ValueError):
            return None, 'level'
        if not 0 <= lv <= 63:
            return None, 'level'
        return (sk << 6) | lv, None
    return sk, None


def skill_names_sorted(data, sid=None, hidden=False):
    """[(skill name, skill id)] sorted by name for the dropdowns. With sid: only the skills that fit
    into the stat's param field (see skill_fits) - the others would roll in the game. hidden: the skills
    without a display name follow ('Aura: Movement Speed (hidden #1888)'), for the stats whose game rows use
    such skills (the worn aura, the hidden procs, the per-skill modifier slots)."""
    out = [(skill_label(data, k), k) for k in data.skill_names if _own_name(data, k)]
    if sid is not None:
        out = [(n, k) for n, k in out if skill_fits(data, sid, k)]
    out.sort(key=lambda x: x[0].lower())
    if hidden:
        more = []
        for k in range(1, len(_skill_rows(data))):
            if _own_name(data, k) or (sid is not None and not skill_fits(data, sid, k)):
                continue
            n = hidden_skill_name(data, k)
            if n:
                more.append((n, k))
        out += sorted(more, key=lambda x: x[0].lower())
    return out


def skilldesc_name(data, idx):
    """The display name of a skilldesc.bin entry (the skill-proc stats' param indexes this table
    directly, not the skills table). None when the index is out of range or the entry has no name."""
    if idx is None or idx < 0:
        return None
    cached = getattr(data, '_skilldesc_names', None)
    if cached is None:
        try:
            import struct
            cached = [(data.s(struct.unpack_from('<H', row, 8)[0]) or None)
                      for row in data._rows('skilldesc')]
        except Exception:
            cached = []
        data._skilldesc_names = cached
    return cached[idx] if idx < len(cached) else None


# the vanilla skills.bin columns that name a state: aurastate (+0x80), auratargetstate (+0x82),
# passivestate (+0x94); u16 indexes into states.bin, 0 / 0xFFFF = none
STATE_COLS = (0x080, 0x082, 0x094)
STATE_STAT = 98              # the vanilla 'state' stat: param = state id, value 1/2


def _state_skills(data):
    """{state id: [skill row indexes that set it]} from the skills table's state columns (cached)."""
    cached = getattr(data, '_state_skills', None)
    if cached is not None:
        return cached
    import struct
    m = {}
    try:
        for i, row in enumerate(data._rows('skills')):
            for off in STATE_COLS:
                v = struct.unpack_from('<H', row, off)[0]
                if 0 < v < 0xFFFF:
                    m.setdefault(v, []).append(i)
    except Exception:
        m = {}
    data._state_skills = m
    return m


def state_name(data, sid):
    """Display name of a state id: the names of the skills that set it (the states table carries no
    name strings, the skills that set the state do). None when no skill sets it."""
    if sid is None:
        return None
    icon = _state_icon_names(data).get(sid)          # the text under the state's buff icon, when it has one
    if icon:
        return icon
    names = []
    for i in _state_skills(data).get(sid) or []:
        try:
            n = data.skill_names.get(i) or skilldesc_name(data, i)
        except Exception:
            n = None
        if n and n not in names:
            names.append(n)
    return ' / '.join(names[:3]) or _state_row_name(data, sid)


def _state_row_names(data):
    """{state id: name} for every row of the states table except 0, for states no skill column and no buff icon
    names (e.g. 505 'voidtouched', set by a cube recipe): the naming chain of D2-Development-Kit (MIT) in
    mxl_rownames - vanilla key, the skills that use it, its own skill (+56), overlay (+2 / +10), missile (+58),
    the items / stats that use it, else its flags."""
    m = getattr(data, '_sn_state_rows', None)
    if m is not None:
        return m
    m = {}
    try:
        import mxl_rownames as RN
        for sid in range(1, len(RN.rows(data, 'states'))):
            m[sid] = RN.state_full(data, sid) or f'State {sid}'
    except Exception:
        m = {}
    data._sn_state_rows = m
    return m


def _state_row_name(data, sid):
    return _state_row_names(data).get(sid)


def state_names_sorted(data):
    """[(state name, state id)] sorted by name, for the state stat's (98) param dropdown: every state of
    the states table (named by its buff icon, the skills that set it, or its own row)."""
    out = []
    for sid in sorted(set(_state_skills(data)) | set(_state_icon_names(data)) | set(_state_row_names(data))):
        n = state_name(data, sid)
        if n:
            out.append((n, sid))
    return sorted(_uniq(out), key=lambda x: x[0].lower())
