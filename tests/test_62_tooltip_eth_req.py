"""Item tooltip: ethereal weapon damage and requirement colouring.

- Median XL gives ethereal weapons +25 % base damage before enhanced damage. In game an ethereal Dirk (base 18-20)
  with +220 % ED and +12 max reads "One-Hand Damage: 70 to 92"; the collector wrote "57 to 76"
  (src/mxl_dmg_text.py).
- The red "Required Strength / Dexterity" lines compared against the collector's low char['strength'] /
  ['dexterity']; they now use the stat screen totals of the character file (src/mxl_status_attr.py)."""
import glob
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')

def tip(it, data, char=None):
    from mxl_tooltip import item_tooltip
    return [(ln[0][0] if ln else None, ''.join(seg[1] for seg in ln)) for ln in item_tooltip(it, data, char)]


def built(E, spec):
    import types
    import mxl_creator_gui as G
    G.CreatorWindow.prepare_defaults(types.SimpleNamespace(cr=E.cr, data=E.data), spec)
    return E.save.blob_item(E.cr.build(spec)[0], E.data)


def dirk(E):
    """A normal Dirk (4) (base 18-20 one-hand) built by the creator."""
    cr = E.cr
    b = next((b for b in cr.bases() if b.name == 'Dirk (4)'), None)
    T.check(b is not None, 'no Dirk base')
    T.eq(tuple(E.data.base(b.code).damage['one_hand']), (18, 20), 'Dirk base damage')
    return built(E, cr.new_spec('normal', b.code))


@T.test
def ethereal_dirk_damage():
    E = T.engine()
    S = E.tip.S
    it = dirk(E)
    it['ethereal'] = True
    it['stats'] = [s for s in it.get('stats') or [] if s['id'] not in (17, 18, 22)] + [
        {'id': S.ENH_DAMAGE_MAX, 'value': 220, 'param': 0}, {'id': S.ENH_DAMAGE_MIN, 'value': 220, 'param': 0},
        {'id': S.MAX_DAMAGE, 'value': 12, 'param': 0}]
    lines = [t for _c, t in tip(it, E.data)]
    T.check(any(t.startswith('One-Hand Damage: 70 to 92') for t in lines), f'no "70 to 92": {lines}')
    it['ethereal'] = False
    lines = [t for _c, t in tip(it, E.data)]
    T.check(any(t.startswith('One-Hand Damage: 57 to 76') for t in lines), f'non-ethereal not 57-76: {lines}')


@T.test
def strength_requirement_uses_real_total():
    E = T.engine()
    import mxl_status_attr
    import mxl_tooltip as MT
    mxl_status_attr.install_tooltip()
    d2s = sorted(glob.glob(os.path.join(T.fresh_saves(1), '*.d2s')))[0]
    real = mxl_status_attr.totals(d2s, E.data)
    T.check(real is not None, 'no stat screen totals')
    # an item needing Strength / Dexterity: the first weapon base that has both
    b = next(b for b in E.cr.bases() if all(E.data.base(b.code).req_str_dex or (0, 0))
             and getattr(E.data.base(b.code), 'damage', None))
    rs, rd = E.data.base(b.code).req_str_dex
    T.check(real[0] >= rs and real[1] >= rd, f'sample totals {real} below {rs}/{rd}')
    it = built(E, E.cr.new_spec('normal', b.code))
    low = {'name': 'X', 'cls': 0, 'level': 120, 'strength': 0, 'dexterity': 0}
    unmet = dict(MT.requirements(it, E.data, low))
    T.check(any(v for v in unmet.values()), f'no unmet line without a path: {unmet}')
    char = dict(low, path=d2s)
    req = MT.requirements(it, E.data, char)
    T.check(not any(u for _t, u in req), f'requirement unmet with real totals {real}: {req}')
    T.check(not MT.requirements_unmet(it, E.data, char), 'requirements_unmet still true')
    reds = [t for c, t in tip(it, E.data, char) if c == MT.RED and 'Required' in t]
    T.check(not reds, f'red requirement lines: {reds}')
    T.eq(char['strength'], 0, 'char dict left as it was')


T.main(globals())
