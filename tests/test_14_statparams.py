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
    T.eq(SN.param_value(E.data, 98, "Dragon's Blessing (#65535)"), None, 'the marker row cannot be picked by name')
    marker = [st for st in SN._state_icon_names(E.data) if st >= n]
    T.eq(marker, [], 'icon rows of states that do not exist')
    for name, value in states:                         # "(#N)" only where two states really share the name
        if name.endswith(f'(#{value})'):
            base = name[:name.rindex(' (#')]
            T.check(sum(1 for nm, _v in states if nm.startswith(base + ' (#')) > 1, f'{name!r}: numbered but alone')


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


T.main(globals())
