"""Readable stat labels and skill params for the editors.

The game's own string tables hold 'FLYING POLAR BUFFALO ERROR' placeholders for many of Median XL's
internal / unused stats: the editors show a neutral '(stat #N)' or '(hidden stat #N)' for those instead.

Also knows which stats carry a skill (or a class) in their param and how to decode / encode it, so the
editors can show the skill's name in a dropdown and type the chance separately:
- the CHANCE_TO_CAST stats (195 - 203), e.g. '%d%% Chance to cast level %d %s on Striking':
  param = (skill id << 6) | level shown;
- the SINGLE_SKILL stats (97, 107), e.g. 'to %s': param = skill id;
- the class skill stat (83), e.g. 'to %s Skill Levels': param = class index.
"""
import re
import struct

CHANCE_TO_CAST = list(range(195, 204))
SINGLE_SKILLS = (97, 107)
CLASS_SKILLS = 83


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
        return ''
    return txt


def param_kind(sid):
    """What kind of param the stat carries: 'skill' (+ level), 'skill_only', 'class' or None."""
    if sid in CHANCE_TO_CAST:
        return 'skill'
    if sid in SINGLE_SKILLS:
        return 'skill_only'
    if sid == CLASS_SKILLS:
        return 'class'
    return None


def _classes():
    from mxl_rules import CLASSES
    return CLASSES


def decode_param(data, sid, param):
    """Human name of the param the row stored: ('Arrow', 16) for a chance-to-cast stat, ('Tantrum', None),
    ('Necromancer', None) for the class skill stat; None when the stat has no such param."""
    kind = param_kind(sid)
    if param is None or kind is None:
        return None
    try:
        if kind == 'skill':
            sk, lv = param >> 6, param & 63
            return (skill_label(data, sk) or f'skill #{sk}', lv)
        if kind == 'skill_only':
            return (skill_label(data, param) or f'skill #{param}', None)
        cl = _classes()
        if kind == 'class':
            return (cl[param] if isinstance(param, int) and 0 <= param < len(cl) else f'class #{param}', None)
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
        if kind == 'class':
            cl = _classes()
            return cl.index(name) if name in cl else None
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
    """False when the game would roll this skill id out of the stat's param field: the game's own
    param arithmetic works on 16 bits (the editor's own saves never hold a bigger param), so a skill
    id that needs a 17th bit - like Median XL's late skills (OHMAN is #1697) - comes out rolled to
    another skill. Storing it would corrupt the attribute instead of setting it."""
    kind = param_kind(sid)
    if kind == 'class':
        cl = _classes()
        return isinstance(skill_id, int) and 0 <= skill_id < len(cl)
    if kind is None:
        return False
    bits = min(param_bits(data, sid), 16)
    if bits <= 0:
        return False
    if kind == 'skill':
        return isinstance(skill_id, int) and 0 <= skill_id < (1 << (bits - 6))
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
    game writes under the buff icon of the state."""
    m = getattr(data, '_sn_state_icons', None)
    if m is None:
        m = {}
        try:
            for r in data._rows('stateicons'):
                st, _a, _icon, si = struct.unpack_from('<4H', r, 0)
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
            what = next((icons[v] for v in states if v in icons), '')
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
                missiles = [v for v in struct.unpack_from('<4H', r, 0x46) + struct.unpack_from('<4H', r, 0xE8)
                            if 0 < v < 0xFFFF]
                if states:
                    what = 'Unnamed effect'
                elif missiles:
                    what = 'Unnamed missile skill'
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


def encode_skill_param(data, sid, name, level=None):
    """param of a chosen skill name for stat sid: (param, None) on success, else (None, reason) with
    reason 'unknown' (no skill of this name), 'rolled' (its id does not fit the param field: the game
    would roll it to another skill) or 'level' (bad cast level). The plain encode_param keeps its
    behaviour (None) for existing callers."""
    kind = param_kind(sid)
    if kind is None:
        return None, 'unknown'
    if kind == 'class':
        from mxl_rules import CLASSES
        try:
            ci = list(CLASSES).index(name)
        except (ValueError, TypeError):
            return None, 'unknown'
        return (ci, None) if skill_fits(data, sid, ci) else (None, 'rolled')
    sk = skill_id(data, name)
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


def skill_names_sorted(data, sid=None):
    """[(skill name, skill id)] sorted by name for the dropdowns. With sid: only the skills that fit
    into the stat's param field (see skill_fits) - the others would roll in the game."""
    out = [(skill_label(data, k), k) for k in data.skill_names if _own_name(data, k)]
    if sid is not None:
        out = [(n, k) for n, k in out if skill_fits(data, sid, k)]
    return sorted(out, key=lambda x: x[0].lower())


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
    return ' / '.join(names[:3]) or None


def state_names_sorted(data):
    """[(state name, state id)] sorted by name, for the state stat's (98) param dropdown."""
    out = []
    for sid in sorted(set(_state_skills(data)) | set(_state_icon_names(data))):
        n = state_name(data, sid)
        if n:
            out.append((n, sid))
    return sorted(out, key=lambda x: x[0].lower())
