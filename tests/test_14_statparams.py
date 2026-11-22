"""Stat parameters: the generated table mxl_statparams.PARAMS against the game's stat table, and the name <->
value functions of mxl_statnames built on it."""
import capytest as T

MODE = 'engine'
NEEDS = ('user',)
KINDS = {'skill', 'class', 'state', 'monster', 'montype', 'element', 'orb', 'string', 'packed', 'number', 'unknown'}


@T.test
def every_stat_with_param_bits_has_an_entry():
    E = T.engine()
    import mxl_statparams as SP
    with_bits = {sid: ic['param'] for sid, ic in E.data.isc.items() if ic.get('param')}
    T.check(len(with_bits) >= 40, f'only {len(with_bits)} stats with param bits in itemstatcost')
    T.eq(sorted(set(with_bits) - set(SP.PARAMS)), [], 'stats with param bits but no PARAMS entry')
    T.eq(sorted(set(SP.PARAMS) - set(with_bits)), [], 'PARAMS entries for stats without param bits')
    for sid, spec in SP.PARAMS.items():
        T.eq(spec.get('bits'), with_bits.get(sid), f'stat {sid}: param bits in PARAMS vs itemstatcost')


@T.test
def entries_are_well_formed():
    import mxl_statparams as SP
    for sid, spec in SP.PARAMS.items():
        T.check(spec.get('kind') in KINDS, f'stat {sid}: kind {spec.get("kind")!r}')
        T.check(spec.get('conf') in ('proven', 'inferred', 'unknown'), f'stat {sid}: conf {spec.get("conf")!r}')
        fields = spec.get('fields') or []
        T.check(fields, f'stat {sid}: no fields')
        used = 0
        for name, kind, first, bits in fields:
            T.check(bits > 0 and first >= 0, f'stat {sid} field {name}: bits {bits} at {first}')
            mask = ((1 << bits) - 1) << first
            T.check(not used & mask, f'stat {sid}: field {name} overlaps another field')
            used |= mask
        if spec.get('bits'):
            top = max(first + bits for _n, _k, first, bits in fields)
            T.check(top <= max(spec['bits'], 16), f'stat {sid}: fields reach bit {top}, the param has {spec["bits"]}')
        for fname, enum in (spec.get('enums') or {}).items():
            T.check(any(f[0] == fname for f in fields), f'stat {sid}: enum for unknown field {fname!r}')
            T.check(enum and all(isinstance(k, int) and isinstance(v, str) and v for k, v in enum.items()),
                    f'stat {sid}: enum {fname!r} malformed')
    T.eq(SP.GAME_DATA and isinstance(SP.GAME_DATA, str), True, 'GAME_DATA version text')


@T.test
def stat_415_element_and_attribute_resolve():
    """Innate elemental damage: param = element | attribute << 8."""
    E = T.engine()
    import mxl_statnames as SN
    import mxl_statparams as SP
    enums = SP.PARAMS[415]['enums']
    T.eq(enums['element'], {0: 'Fire', 1: 'Lightning', 2: 'Cold', 3: 'Poison', 4: 'Magic', 5: 'Tri-Elemental'}, 'elements')
    T.eq([enums['attribute'][i] for i in range(4)], ['Strength', 'Energy', 'Dexterity', 'Vitality'], 'attributes 0-3')
    T.check(4 in enums['attribute'], 'attribute 4 (higher of Strength / Dexterity) missing')
    choices = SN.param_choices(E.data, 415)
    T.eq(len(choices), len(enums['element']) * len(enums['attribute']), 'number of choices')
    for name, value in choices:
        T.eq(SN.param_name(E.data, 415, value), name, f'param_name(415, {value})')
        T.eq(SN.param_value(E.data, 415, name), value, f'param_value(415, {name!r})')
        el, at = value & 0xFF, value >> 8
        T.check(name.startswith(enums['element'][el]) and enums['attribute'][at] in name,
                f'{value} = element {el} | attribute {at} << 8 is named {name!r}')
    T.eq(SN.param_value(E.data, 415, 'Cold / Vitality'), 2 | 3 << 8, 'Cold / Vitality')
    text = SN.param_text(E.data, 415, 1 | 2 << 8)
    T.check('Lightning' in text and 'Dexterity' in text, f'param_text(415, 513) = {text!r}')


@T.test
def stat_83_classes_resolve():
    E = T.engine()
    import mxl_statnames as SN
    names = ['Amazon', 'Sorceress', 'Necromancer', 'Paladin', 'Barbarian', 'Druid', 'Assassin']
    T.eq(SN.param_choices(E.data, 83), [(n, i) for i, n in enumerate(names)], 'class choices of stat 83')
    for i, n in enumerate(names):
        T.eq(SN.param_name(E.data, 83, i), n, f'param_name(83, {i})')
        T.eq(SN.param_value(E.data, 83, n), i, f'param_value(83, {n!r})')
    T.eq(SN.param_kind(83), 'class', 'kind of stat 83')


@T.test
def chance_to_cast_packs_skill_and_level():
    """Chance-to-cast stats: param = skill << 6 | level."""
    E = T.engine()
    import mxl_statnames as SN
    for sid in SN.CHANCE_TO_CAST:
        for skill, level in ((457, 40), (36, 1), (100, 63)):
            name, lv = SN.decode_param(E.data, sid, skill << 6 | level)
            T.eq(lv, level, f'stat {sid}: level of {skill << 6 | level}')
            T.check(isinstance(name, str) and name and not name.startswith('skill #'), f'stat {sid}: skill {skill} has no name ({name!r})')
            T.eq(SN.encode_param(E.data, sid, name, level), skill << 6 | level, f'stat {sid}: encode_param({name!r}, {level})')


def offered(E, sid):
    import mxl_statnames as SN
    out, seen = [], set()
    for name, value in SN.param_choices(E.data, sid) or ():
        if name not in seen:                    # same label for two values: the first one is what a name picks
            seen.add(name)
            out.append((name, value))
    return out


@T.test
def every_enumeration_round_trips():
    """For every stat whose param the editor offers by name: name -> value gives the offered value (for the
    values the stat's param bits can hold; the others are the next test)."""
    E = T.engine()
    import mxl_statnames as SN
    import mxl_statparams as SP
    n = 0
    for sid in sorted(SP.PARAMS):
        bits = E.data.isc[sid]['param']
        for name, value in offered(E, sid):
            if 0 <= value < (1 << bits):
                T.eq(SN.param_value(E.data, sid, name), value, f'stat {sid}: param_value({name!r})')
                n += 1
    T.check(n > 2000, f'only {n} names checked')


# Was a bug until 2026-11: the pick list of stat 98 (state, 11 param bits) offered "Dragon's Blessing (#65535)".
# 0xFFFF is the "no state" marker of two stateicons.bin rows (icons no state uses), not a state.
@T.test
def offered_choices_fit_the_param_bits():
    E = T.engine()
    import mxl_statparams as SP
    for sid in sorted(SP.PARAMS):
        bits = E.data.isc[sid]['param']
        for name, value in offered(E, sid):
            T.check(0 <= value < (1 << bits), f'stat {sid} ({bits} param bits) offers {name!r} = {value}')


@T.test
def offered_states_are_rows_of_the_states_table():
    """Stat 98: every offered state is a row of states.bin, none is the 0xFFFF "no state" marker of the icon
    table, and a name the marker row shared with a real state is no longer numbered."""
    E = T.engine()
    import mxl_statnames as SN
    n = len(E.data._rows('states'))
    states = SN.state_names_sorted(E.data)
    T.check(len(states) > 300, f'only {len(states)} named states')
    for name, value in states:
        T.check(0 < value < n, f'state {name!r} = {value}: not a row of the states table ({n} rows)')
    T.eq(SN.state_names_sorted(E.data), SN.param_choices(E.data, 98), 'choices of stat 98 = the named states')
    T.eq(SN.state_name(E.data, 0xFFFF), None, 'name of state 65535')
    T.check(any(v == 505 for _n, v in states), 'state 505 (voidtouched, set by a cube recipe) is not listed')
    T.eq(SN.state_name(E.data, 505), 'voidtouched', 'name of state 505 (its overlay)')
    T.eq(SN.param_value(E.data, 98, "Dragon's Blessing (#65535)"), None, 'the marker row cannot be picked by name')
    marker = [st for st in SN._state_icon_names(E.data) if st >= n]
    T.eq(marker, [], 'icon rows of states that do not exist')
    for name, value in states:                         # "(#N)" only where two states really share the name
        if name.endswith(f'(#{value})'):
            base = name[:name.rindex(' (#')]
            T.check(sum(1 for nm, _v in states if nm.startswith(base + ' (#')) > 1, f'{name!r}: numbered but alone')


@T.test
def every_state_and_skill_row_is_named():
    """Stat 98 offers every state and the skill stats every skill row, named by the D2-Development-Kit chain
    (vanilla key, linked rows, users) - the kit's dump names ~875 of 967 states and ~2600 of 3018 skills;
    only the rest get a description of the row itself ('aura state', 'Druid skill, func 17/0')."""
    E = T.engine()
    import mxl_statnames as SN
    import mxl_rownames as RN
    n_states = len(E.data._rows('states'))
    states = SN.state_names_sorted(E.data)
    T.eq(len(states), n_states - 1, 'states offered (every row but 0)')
    T.check(not any(n.startswith('State ') for n, _v in states), 'a state is still named "State N"')
    import mxl_profile
    if mxl_profile.is_median():                     # Median keeps to its own data: no 1.14d keys (test below)
        T.eq(RN.vanilla_names(E.data, 'states'), {}, 'no vanilla state keys in Median mode')
    else:
        T.check(len(RN.vanilla_names(E.data, 'states')) > 100, 'vanilla state keys')
    if not mxl_profile.is_median():
        T.eq(SN.state_name(E.data, 1), 'freeze', 'state 1: its vanilla key')
    plain = [v for n, v in states if n.split(' (#')[0] == RN.state_fallback(E.data, v)]
    T.check(len(plain) < (200 if mxl_profile.is_median() else 130), f'{len(plain)} states named only by their flags')
    n_skills = len(E.data._rows('skills'))
    skills = SN.skill_names_sorted(E.data, hidden=True)
    T.check(len(skills) >= n_skills - 2, f'{len(skills)} of {n_skills} skills offered')
    T.check(len({n for n, _k in skills}) == len(skills), 'skill names are unique')
    plain = [k for n, k in skills if ' skill, func ' in n]
    T.check(len(plain) < (1600 if mxl_profile.is_median() else 600), f'{len(plain)} skills named only by their row')   # Median: by what they do, else the row kind (mostly monster skills) - never vanilla / file names
    T.check(len(SN.param_choices(E.data, 197)) > 2000, 'stat 197 offers the hidden skills too')
    for n, k in skills[::97]:
        T.eq(SN.skill_id(E.data, n), k, f'skill name {n!r} round trip')


@T.test
def orange_text_params_are_picked_by_text():
    """The orange-text stats (description function 31: the param IS a string index) offer the texts of the
    patchstring range by name; a picked text stores its string id and names it back."""
    E = T.engine()
    import mxl_statnames as SN
    for sid in (375, 377, 378):
        T.eq(SN.param_kind(sid), 'named', f'stat {sid}: param kind')
        ch = SN.param_choices(E.data, sid)
        T.check(len(ch) > 1000, f'stat {sid}: only {len(ch)} texts offered')
        name = next(n for n, v in ch if v == 11861)
        T.check('Tenacity' in name, f'string 11861 offered as {name!r}')
        T.eq(SN.param_value(E.data, sid, name), 11861, 'picked text -> string id')
        T.eq(SN.param_name(E.data, sid, 11861), name, 'string id -> text')
    import mxl_creator
    mxl_creator.Creator(E.data)                          # registers what each text does
    E.data.__dict__.pop('_sn_param_choices', None)
    E.data.__dict__.pop('_sn_string_names', None)
    names = [n for n, _v in SN.param_choices(E.data, 375)]
    fx = [n for n in names if n.startswith('[effect: ')]
    T.check(len(fx) > 5, f'only {len(fx)} orange texts tagged with their effect')
    T.check(any(n.startswith('[display only] ') for n in names), 'no orange text tagged display only')
    print('  e.g.', fx[0][:110])


@T.test
def named_choices_name_real_rows():
    """The other enumerations taken from tables: monsters are rows of the monster table, mystic orbs rows of
    mysticorbs.bin, skills rows of the skills table that fit the stat's skill field."""
    E = T.engine()
    import mxl_statnames as SN
    import mxl_statparams as SP
    n_skills = len(E.data._rows('skills'))
    for sid in sorted(SP.PARAMS):
        kind = SN.param_kind(sid)
        fields = SP.PARAMS[sid].get('fields') or ()
        for name, value in offered(E, sid):
            T.check(isinstance(name, str) and name.strip(), f'stat {sid}: empty name for {value}')
            if kind in ('skill', 'skill_only'):
                T.check(0 <= value < n_skills and SN.skill_fits(E.data, sid, value), f'stat {sid}: skill {name!r} = {value}')
            elif len(fields) == 1 and fields[0][1] == 'monster':
                T.check(0 <= value < len(E.data.monster_names), f'stat {sid}: monster {name!r} = {value}')
            elif len(fields) == 1 and fields[0][1] == 'orb':
                T.check(0 <= value < len(E.cr._orb_table()), f'stat {sid}: orb {name!r} = {value}')


@T.test
def median_lists_carry_no_vanilla_names():
    """Median XL mode keeps to Median data (user): the skill lists (proc skills, oskills, hidden skills) carry no
    1.14d skill name taken from a vanilla row of the same number ("BattleCry: aura" for a Median skill)."""
    E = T.engine()
    import mxl_profile
    if not mxl_profile.is_median():
        T.skip('not the Median XL profile')
    import mxl_rownames as RN
    import mxl_statnames as SN
    T.eq(RN.vanilla_names(E.data, 'skills'), {}, 'no vanilla skill names in Median mode')
    van = RN._vanilla().get('skills') or {}
    keys = {n.lower() for n in van.get('names') or [] if len(n) > 3}
    own = {n.lower() for n in (E.data.skill_names.values() if isinstance(E.data.skill_names, dict) else []) if n}
    for r in E.data._rows('missiles'):                 # and its own missiles' graphics names ("UnholyBolt")
        try:
            own.add(RN._cstr(r, RN.MI_CELFILE).strip().lower())
        except Exception:
            pass
    for tbl in ('skills', 'states', 'missiles', 'monstats', 'overlay'):
        T.eq(RN.vanilla_names(E.data, tbl), {}, f'no vanilla {tbl} names in Median mode')
    for _i, ent in E.data.strings.items():             # names Median's own string tables carry are its own data
        try:
            own.add(str(ent[1]).strip().lower())
        except Exception:
            pass
    bad = []
    for name, sk in SN.skill_names_sorted(E.data, hidden=True):
        if '(hidden #' not in name:
            continue
        head = name.split(':')[0].split(' (hidden')[0].strip().lower()
        if head in keys and head not in own:
            bad.append(name)
    T.eq(bad[:5], [], f'hidden skills named after 1.14d rows: {len(bad)}')


@T.test
def mock_mode_is_vanilla_only():
    """Mock PI / Mock Mode is a vanilla LoD thing (the user): in the Median XL profile its toggle and tab do not
    exist."""
    T.engine()
    import mxl_profile
    import mxl_mock_gui
    if mxl_profile.is_median():
        T.eq(mxl_mock_gui.enabled(), False, 'Mock Mode in Median XL')
    else:
        T.eq(mxl_mock_gui.enabled(), True, 'Mock Mode in a vanilla profile')


T.main(globals())
