"""Mystic orbs applied to an item (Item Editor "Apply Mystic Orb", engine: Creator.orbs_for / orb_deltas /
orb_result). What the game records, from the saves: each orb's property stats (added), +Required Level (stat 92,
mysticorbs.bin @32 per orb) and the counter stat 290 (param = the orb's row, value = how many), capped at the
orb's per-item max (@43). Checked on a built base, through a character save and back, and against real saved
items (the sample folders that have orbed items; skipped when none is there)."""
import glob
import os

import capytest as T

MODE = 'engine'
NEEDS = ('user',)

WORMTONGUE = 690                     # unique row (base '858 ', armor): test-druid wears one with orbs


def _tot(stats):
    out = {}
    for s in stats:
        k = (s['id'], s.get('param') or None)
        out[k] = out.get(k, 0) + s['value']
    return out


def _orb(cr, name):
    return next(c for c, o in cr._orb_table().items() if o['name'] == name)


def _apply(E, spec, new):
    """What the Item Editor's Apply does: the new totals written as delta rows over the spec's own mods."""
    made = {}
    for m in E.cr.mods(spec):
        for x in m.stats(E.data):
            k = (x['id'], x.get('param') or None)
            made[k] = made.get(k, 0) + x['value']
    spec['extra'] = [dict(id=k[0], param=k[1], value=v - made.get(k, 0)) for k, v in new.items()
                     if v != made.get(k, 0)]


@T.test
def orbs_on_a_base():
    E = T.engine()
    cr = E.cr
    strength, mdmg = _orb(cr, 'MO - Strength'), _orb(cr, 'MO - Max Dmg Armor')
    T.eq(cr._orb_table()[strength]['row'], 0, 'MO - Strength is row 0 (counter param 0)')
    spec = cr.new_spec('unique', row=WORMTONGUE)
    _blob, rec = cr.build(spec)
    old = _tot(rec['stats'])
    names = [o['name'] for _c, o in cr.orbs_for(spec['code'], 'unique')]
    T.check('MO - Strength' in names and not any(n.startswith('Rare MO') for n in names), f'unique armor: {names}')
    body = [o['name'] for _c, o in cr.orbs_for('fld ', 'rare')]
    T.check('Rare MO - Max Life' in body and 'Rare MO - Block Up' not in body, 'rare body armor: Max Life, no Block')
    T.check(not any(o['name'].startswith('Rare MO') for _c, o in cr.orbs_for('fld ', 'unique')), 'unique: no rare orbs')
    T.eq(cr.orb_room(strength, old), 5, 'room: 5 Strength orbs')
    new = cr.orb_result(strength, 5, old, spec['code'])
    new = cr.orb_result(mdmg, 3, new, spec['code'])
    T.eq(new.get((0, None), 0) - old.get((0, None), 0), 25, '+25 Strength')
    for sid in (22, 24, 160):
        T.eq(new.get((sid, None), 0) - old.get((sid, None), 0), 6, f'+6 to stat {sid} (armor: every damage kind)')
    T.eq(new.get((92, None), 0) - old.get((92, None), 0), 32, 'Required Level +4 per orb')
    T.eq((new.get((290, None)), new.get((290, 37))), (5, 3), 'counters: row 0 x5, row 37 x3')
    T.eq((cr.orb_room(strength, new), cr.orb_room(mdmg, new)), (0, 2), 'room left')
    try:
        cr.orb_result(strength, 1, new, spec['code'])
        T.check(False, 'a 6th Strength orb is refused')
    except E.C.CreateError:
        pass
    # weapon: max damage only to the damage kinds the base has (a dagger: one-hand)
    ks = {(s, p) for s, p, _v in cr.orb_deltas(_orb(cr, 'MO - Max Damage'), 2, '483 ')}
    T.check((22, None) in ks and (24, None) not in ks and (160, None) not in ks, f'dagger max damage: {ks}')

    # built item and a character save round trip
    _apply(E, spec, new)
    blob, rec = cr.build(spec)
    got = _tot(rec['stats'])
    for k in ((0, None), (92, None), (290, None), (290, 37), (22, None)):
        T.eq(got.get(k), new.get(k), f'built item: stat {k}')
    raw = [s for s in E.C.decode_item(blob, E.data)[0]['stats'] if s['id'] == 290]
    T.eq(sorted((s['param'] or 0, s['value']) for s in raw), [(0, 5), (37, 3)], 'stat 290 in the bytes')
    saves = os.environ['MXL_SAVE_DIR']
    src = sorted(glob.glob(os.path.join(saves, '*.d2s')))[0]
    path = os.path.join(T.tmp(), 'orbs_rt.d2s')
    with open(src, 'rb') as f, open(path, 'wb') as g:
        g.write(f.read())
    ch = E.MC.Character(path, E.data)
    free = next((x, y) for y in range(8) for x in range(10) if not ch.inventory_error(rec, x, y))
    ch.place(blob, ('inv',) + free)
    with open(path, 'wb') as g:
        g.write(ch.build())
    import mxl_savecheck
    mxl_savecheck.lib()
    from mxlsave.check import check_bytes
    _obj, problems = check_bytes(T.read(path), 'd2s', mxl_savecheck.tables())
    T.eq(problems, [], 'independent mxlsave check of the saved character')
    ch2 = E.MC.Character(path, E.data)
    T.eq(ch2.build(), T.read(path), 're-opened file rebuilds byte for byte')
    back = [e for e in ch2.entries(False) if E.C.decode_item(bytes(e.blob), E.data)[0]['code'] == spec['code']
            and cr.orbs_applied(_tot(E.C.decode_item(bytes(e.blob), E.data)[0]['stats']))]
    T.eq(len(back), 1, 'the orbed item is in the saved character')
    t2 = _tot(E.C.decode_item(bytes(back[0].blob), E.data)[0]['stats'])
    T.eq(cr.orbs_applied(t2), {strength: 5, mdmg: 3}, 'orbs read back from the save')
    T.eq(cr.orb_room(strength, t2), 0, 'the cap holds after the round trip')


@T.test
def saved_items_match_the_table():
    """Every orb counted on a real saved item fits that item, and its stats / Required Level are on it."""
    E = T.engine()
    cr = E.cr
    dirs = [d for d in (T.SRC_SAVES, T.SRC_SAVES2, T.SRC_SAVES3,
                        os.path.join(T.REPO, '.cache', 'samples-orig')) if d and os.path.isdir(d)]
    n = 0
    for f in sorted({p for d in dirs for p in glob.glob(os.path.join(d, '**', '*.d2s'), recursive=True)}):
        try:
            ch = E.MC.Character(f, E.data)
        except Exception:
            continue
        for e in ch.entries(False):
            it = E.C.decode_item(bytes(e.blob), E.data)[0]
            tot = _tot(it.get('stats') or [])
            ap = cr.orbs_applied(tot)
            if not ap or tot.get((497, None)):          # corrupted: the corruption changes Required Level too
                continue
            acc = {}
            for orb, cnt in ap.items():
                T.check(cr.orb_fits(orb, it['code'], it.get('quality')) and cnt <= cr._orb_table()[orb]['max'],
                        f'{os.path.basename(f)} {it["code"]}: {orb} x{cnt} fits')
                for sid, pa, v in cr.orb_deltas(orb, cnt, it['code']):
                    acc[(sid, pa)] = acc.get((sid, pa), 0) + v
            for k, v in acc.items():
                have = tot.get(k, 0)
                ok = have == v if k[0] in (92, 290) else (have >= v if v > 0 else have <= v)
                T.check(ok, f'{os.path.basename(f)} {it["code"]}: stat {k} {have} vs orbs {v}')
            n += 1
    if not n:
        T.skip('no sample save with orbed items')


@T.test
def doubled_and_quadrupled_items():
    """Stat 289 "Orb Effects Applied to this Item are Doubled / Quadrupled" holds the factor (2 / 4): the orb's own
    stats are multiplied, Required Level and the counter are not (samples: a sash with 289 = 2 and five +5 Energy
    orbs holds +50 Energy; 25 orbs -> Required Level 100)."""
    E = T.engine()
    cr = E.cr
    strength = _orb(cr, 'MO - Strength')
    spec = cr.new_spec('unique', row=WORMTONGUE)
    _blob, rec = cr.build(spec)
    base = _tot(rec['stats'])
    for mult in (1, 2, 4):
        old = dict(base)
        if mult > 1:
            old[(289, None)] = mult
        new = cr.orb_result(strength, 5, old, spec['code'])
        T.eq(new.get((0, None), 0) - old.get((0, None), 0), 25 * mult, f'x{mult}: Strength')
        T.eq(new.get((92, None), 0) - old.get((92, None), 0), 20, f'x{mult}: Required Level not multiplied')
        T.eq(new.get((290, None), 0) - old.get((290, None), 0), 5, f'x{mult}: counter not multiplied')


T.main(globals())
