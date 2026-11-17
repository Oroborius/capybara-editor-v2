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
            return (data.skill_names.get(sk, f'skill #{sk}'), lv)
        if kind == 'skill_only':
            return (data.skill_names.get(param, f'skill #{param}'), None)
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
            sk = next((k for k, n in data.skill_names.items() if n == name), None)
            if sk is None:
                return None
            return (sk << 6) | (int(level or 0) & 63) if level is not None else sk << 6
        if kind == 'skill_only':
            return next((k for k, n in data.skill_names.items() if n == name), None)
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


def skill_id(data, name):
    """The skill's id, or None when no skill has this exact name."""
    return next((k for k, n in data.skill_names.items() if n == name), None)


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
    out = [(n, k) for k, n in data.skill_names.items() if n]
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
    for sid in sorted(_state_skills(data)):
        n = state_name(data, sid)
        if n:
            out.append((n, sid))
    return sorted(out, key=lambda x: x[0].lower())
