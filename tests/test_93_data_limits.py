"""Item limits come from the selected game folder's tables (CLAUDE.md "Limits come from the selected game folder"),
checked in both profiles: the defense range of a base (armor minac / maxac), the stack size of a quiver / throwing
weapon (maxstack, capped by the 9-bit quantity field), sockets by item level (gemsockets capped by the itemtype's
MaxSock1 / 25 / 40), durability (the base's durability, set x2 / unique x3 capped by the ItemStatCost save field)
and the save-format widths. Each value is read from the raw table rows here and compared with what the creator
offers / validates / builds. Variant 'vanilla' needs only the 1.14d install (MXL_TEST_VANILLA_GAME)."""
import os
import struct
import sys

import capytest as T

MODE = 'engine'
NEEDS = ()
VARIANTS = {'median': {}, 'vanilla': {'CAPY93_VANILLA': '1'}}
VANILLA = bool(os.environ.get('CAPY93_VANILLA'))
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')
_E = None


def _vanilla_engine():
    if not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        T.skip(f'no vanilla 1.14d install ({GAME})')
    user = T.guard(os.path.join(T.tmp(), 'v93user'), 'user folder')
    saves = T.guard(os.path.join(T.tmp(), 'v93saves'), 'save folder')
    os.makedirs(user, exist_ok=True)
    os.makedirs(saves, exist_ok=True)
    os.environ.update(MXL_USER_DIR=user, MXL_SAVE_DIR=saves, MXL_GAME='vanilla', MXL_GAME_DIR=GAME)
    os.environ.setdefault('LOCALAPPDATA', T.tmp())
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import paths
    T.guard(paths.USER_DIR, 'paths.USER_DIR')
    out = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        import mxl_free
        import mxl_format_fix
        mxl_free.install()
        mxl_format_fix.install()
        import mxl_profile
        mxl_profile.install()
    finally:
        sys.stdout = out
    import mxl_data
    import mxl_creator
    d = mxl_data.Data(paths.DATA_DIR)
    return T.NS(data=d, C=mxl_creator, cr=mxl_creator.Creator(d))


def engine():
    global _E
    if _E is None:
        _E = _vanilla_engine() if VANILLA else T.engine()
        import mxl_profile
        T.eq(mxl_profile.is_median(), not VANILLA, 'profile of the variant')
    return _E


def rows(E, kind):
    """{code: raw row} of a weapons / armor / misc table (first row of a code wins, as the game)."""
    out = {}
    for r in E.C._rows(E.data, kind):
        out.setdefault(r[128:132].decode('latin1'), r)
    return out


def ac(r):
    return struct.unpack_from('<i', r, 0xCC)[0], struct.unpack_from('<i', r, 0xD0)[0]


def maxsock(E, code):
    """(MaxSock1, MaxSock25, MaxSock40) of the base's itemtype, from the raw itemtypes row."""
    t = E.data.base(code).type
    r = E.C._rows(E.data, 'itemtypes')[t]
    return r[0x1A], r[0x1B], r[0x1C]


def spec(E, q, code, row=None, **kw):
    """A creator spec with the base's innate (automagic) affix chosen when the game requires one (Median XL)."""
    s = E.cr.new_spec(q, code, row)
    s.update(kw)
    autos = E.cr.auto_choices(s['code'], s['ilvl']) if s.get('code') else []
    if autos and s.get('auto') is None:
        s['auto'] = autos[0][0]
    return s


@T.test
def save_format_widths():
    E = engine()
    C = E.C
    T.eq((C.MAX_ILVL, C.MAX_QUANTITY, C.SOCKET_FIELD_MAX, C.MAX_SOCKETED), (127, 511, 15, 7), 'item record widths')
    import mxl_socket_menu as SM
    import mxl_socket_insert as SI
    T.eq((SM.MAX_COUNT, SM.FIELD_MAX, SI.MAX_COUNT), (C.MAX_SOCKETED, C.SOCKET_FIELD_MAX, C.MAX_SOCKETED),
         'socket menus use the format widths')


@T.test
def defense_range_of_bases():
    E = engine()
    arm = rows(E, 'armor')
    picked = [c for c in (['qui ', 'cap ', 'lrg '] if VANILLA else sorted(arm)) if c in E.data.bases
              and ac(arm[c])[1] > ac(arm[c])[0] > 0 and E.data.base(c).kind == 'armor'][:3]
    T.check(len(picked) == 3, f'armor bases with a defense range: {picked}')
    if VANILLA:
        T.eq(ac(arm['qui ']), (8, 11), 'Quilted Armor 8-11 in 1.14d armor.txt')
    for c in picked:
        lo, hi = ac(arm[c])
        T.eq(E.cr.defense_range(spec(E, 'normal', c)), (lo, hi), f'{c.strip()} defense range')
        _blob, rec = E.cr.build(spec(E, 'normal', c, defense=hi))
        T.eq(rec['defense'], hi, f'{c.strip()} built at the table maximum')
        _blob, rec = E.cr.build(spec(E, 'normal', c, defense=hi + 50))
        T.eq(rec['defense'], hi, f'{c.strip()} clamped to the table maximum')
        _blob, rec = E.cr.build(spec(E, 'normal', c, defense=hi, ethereal=True))
        T.eq(rec['defense'], hi * 3 // 2, f'{c.strip()} ethereal (any item may be)')


@T.test
def stack_size_from_maxstack():
    E = engine()
    stacks = [c for c in E.data.bases if E.data.base(c).stack_max]
    want = [c for c in ('aqv ', 'cqv ', 'tkf ') if c in stacks] if VANILLA else sorted(stacks)[:3]
    T.check(len(want) >= 2, f'stackable bases: {want}')
    for c in want:
        b = E.data.base(c)
        n = min(b.stack_max, E.C.MAX_QUANTITY)
        T.eq(E.cr.quantity_max(c), n, f'{c.strip()} quantity max = maxstack {b.stack_max}')
        E.cr.validate(spec(E, 'normal', c, quantity=n))
        try:
            E.cr.validate(spec(E, 'normal', c, quantity=n + 1))
            T.check(False, f'{c.strip()} quantity {n + 1} refused')
        except E.C.CreateError as e:
            T.check(str(n) in str(e), f'{c.strip()} error names the max: {e}')
    T.eq(E.cr.quantity_max(next(c for c in E.data.bases if E.data.base(c).stack_max is None)), None,
         'no quantity on a base that does not stack')


@T.test
def sockets_by_item_level():
    E = engine()
    if VANILLA:
        T.eq(maxsock(E, 'crs '), (3, 4, 6), '1.14d itemtypes swor MaxSock1/25/40')
    cands = [c for c in sorted(E.data.bases) if E.data.base(c).kind in ('weapons', 'armor')
             and E.data.base(c).max_sockets >= 3 and E.data.base(c).type >= 0
             and len(set(maxsock(E, c))) > 1][:5] or \
        [c for c in sorted(E.data.bases) if E.data.base(c).kind in ('weapons', 'armor')
         and E.data.base(c).max_sockets >= 1 and E.data.base(c).type >= 0][:5]
    T.check(cands, 'socketable bases')
    for c in cands:
        gs, ms = E.data.base(c).max_sockets, maxsock(E, c)
        for ilvl, cap in ((10, ms[0]), (25, ms[0]), (26, ms[1]), (40, ms[1]), (41, ms[2]), (99, ms[2])):
            T.eq(E.cr.max_sockets(c, ilvl), min(gs, cap), f'{c.strip()} sockets at ilvl {ilvl}')
    if VANILLA:
        T.eq(E.cr.socket_limit('crs ', 30), 7, 'user rule: a 1.14d weapon takes up to 7')
        boots = next(c for c in sorted(E.data.bases) if 'boot' in E.cr.type_codes(c))
        T.eq(E.cr.socket_limit(boots, 99), E.cr.max_sockets(boots, 99), 'boots keep the table value')
    else:
        T.eq(E.cr.socket_limit(cands[0], 99), E.cr.max_sockets(cands[0], 99), 'Median: the table value only')


@T.test
def durability_from_the_base():
    E = engine()
    import stat_ids as S
    d, C = E.data, E.C
    mx, du = S.MAX_DURABILITY, S.DURABILITY
    cm = d.isc[mx]
    cap = C.durability_cap(d)
    T.eq(cap, min((1 << d.isc[mx]['bits']) - 1 - d.isc[mx]['add'], (1 << d.isc[du]['bits']) - 1 - d.isc[du]['add']),
         'durability cap from ItemStatCost')
    if VANILLA:
        T.eq(cap, 255, '1.14d: 8-bit durability')
    arm = rows(E, 'armor')
    c = 'qui ' if VANILLA else next(k for k in sorted(arm) if k in d.bases and arm[k][0x112] and not arm[k][0x113]
                                    and d.base(k).kind == 'armor')
    dur = arm[c][0x112]
    if VANILLA:
        T.eq(dur, 20, 'Quilted Armor durability 20 in 1.14d armor.txt')
    _b, rec = E.cr.build(spec(E, 'normal', c))
    T.eq(rec['max_durability'] - cm['add'], dur, f'{c.strip()} max durability = table durability')
    _b, rec = E.cr.build(spec(E, 'normal', c, ethereal=True))
    T.eq(rec['max_durability'] - cm['add'], dur // 2 + 1, f'{c.strip()} ethereal durability')
    for i, _name, u in E.cr.uniques():
        k = u['code']
        if k in arm and k in d.bases and arm[k][0x112] and not arm[k][0x113]:
            try:
                _b, rec = E.cr.build(spec(E, 'unique', None, i))
            except C.CreateError:
                continue
            T.eq(rec['max_durability'] - cm['add'], min(arm[k][0x112] * 3, cap), f'unique on {k.strip()}: x3, capped')
            break
    else:
        T.check(False, 'a unique armor with durability')


T.main(globals())
