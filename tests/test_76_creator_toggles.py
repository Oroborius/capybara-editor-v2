"""Toggles / upgrades: the cube recipes that change an item in place (output 'useitem'). Lookup by the item's
unique row, plain-words condition and changes, the condition test on the item's stats, and applying a toggle and
its paired reverse to a built item (the same delta rows / dropped keys the Item Editor's Apply uses)."""
import capytest as T

MODE = 'engine'
NEEDS = ('user',)

VIAL = 57              # unique row of Vial of Elder Blood (ebx); the cube input holds row + 1
STATE, TEXT = (98, 505), (377, 12431)


def _stats(E, spec):
    _blob, rec = E.cr.build(spec)
    return {(s['id'], s.get('param') or None): s['value'] for s in rec['stats']}


def _apply(E, spec, rec):
    """What the Item Editor's Apply does: new totals through the delta rows, a stat that ends at 0 dropped."""
    old = _stats(E, spec)
    new = E.cr.recipe_result(rec, old)
    made = {}
    for m in E.cr.mods(spec):
        for x in m.stats(E.data):
            made[(x['id'], x.get('param'))] = made.get((x['id'], x.get('param')), 0) + x['value']
    for key in set(old) | set(new):
        if old.get(key, 0) == new.get(key, 0):
            continue
        spec['extra'] = [e for e in spec['extra'] if (e['id'], e.get('param')) != key]
        if key in new:
            spec.setdefault('_drop', set()).discard(key)
            if new[key] != made.get(key, 0):
                spec['extra'].append(dict(id=key[0], param=key[1], value=new[key] - made.get(key, 0)))
        else:
            spec.setdefault('_drop', set()).add(key)
    return new


@T.test
def vial_of_elder_blood_toggles():
    E = T.engine()
    cr = E.cr
    T.check(len(cr.inplace_recipes()) > 1000, f'{len(cr.inplace_recipes())} in-place recipes')
    recs = {r['row']: r for r in cr.inplace_for('ebx ', 'unique', VIAL)}
    T.check(4742 in recs and 4743 in recs, f'Vial recipes: {sorted(recs)}')
    T.check(4742 not in [r['row'] for r in cr.inplace_for('ebx ', 'unique', 82)], 'the other Vial row is not matched')
    off, on = recs[4742], recs[4743]
    T.eq(off['conds'], [(15, 98, 505, 1)], 'toggle off: state 505 >= 1 (layer from cubemainext)')
    T.eq(on['conds'], [(18, 377, 12431, 1)], 'toggle on: the text = 1')
    tx = cr.recipe_texts(off)
    T.check(tx['inputs'] and 'toggled off' in ' '.join(tx['changes']), f'texts: {tx}')
    T.check('>= 1' in tx['conds'][0] and 'stat 98' in tx['conds'][0], f'condition text: {tx["conds"]}')

    spec = cr.new_spec('unique', row=VIAL)
    spec['extra'] = [dict(id=98, param=505, value=1)]          # voidtouched (what the char-condition recipe gives)
    st = _stats(E, spec)
    T.eq(st.get(STATE), 1, 'state 505 on the built item')
    T.check(cr.recipe_applies(off, st) and not cr.recipe_applies(on, st), 'only the off toggle applies')
    _apply(E, spec, off)
    st = _stats(E, spec)
    T.check(STATE not in st and st.get(TEXT) == 1, f'after off: {st}')
    T.check(cr.recipe_applies(on, st) and not cr.recipe_applies(off, st), 'now only the reverse applies')
    _apply(E, spec, on)
    st = _stats(E, spec)
    T.check(st.get(STATE) == 1 and TEXT not in st, f'after on: {st}')


@T.test
def nephalem_key_charges():
    E = T.engine()
    cr = E.cr
    row = next(i for i, u in enumerate(E.data.uniques) if u['code'] == 'ebw '
               and 'Nephalem' in (E.data.key(u['name']) or ''))
    recs = cr.inplace_for('ebw ', 'unique', row)
    use = [r for r in recs if r['conds'] and r['conds'][0][:2] == (15, 259)]
    T.check(recs and use, f'Nephalem key recipes: {[r["row"] for r in recs]}')
    rec = use[0]
    T.check(not cr.recipe_applies(rec, {}), 'no charges: the recipe does not apply')
    T.check(cr.recipe_applies(rec, {(259, None): 3}), '3 charges: it applies')
    T.eq(cr.recipe_result(rec, {(259, None): 3}).get((259, None)), 2, 'one charge used')
    T.check(cr.recipe_texts(rec)['changes'], 'changes described')


@T.test
def type_names_and_mod_chances():
    """An item-type input is named ("any Shield (shie)", not "any shie"); a mod with a chance column below 100
    says so ("(20% chance)")."""
    E = T.engine()
    cr = E.cr
    import mxl_rownames
    shie = next(i for i, t in enumerate(E.data.itypes) if str(t[0]).strip() == 'shie')
    T.eq(cr.type_name(shie), 'Shield (shie)', 'vanilla type name')
    T.eq(mxl_rownames.itemtype_name(E.data, shie), 'Shield', 'rownames')
    recs = cr.inplace_recipes()
    typed = [x for x in recs if x['first'][0] & 2 or any(i[0] & 2 for i in x['inputs'])]
    named = [t for x in typed for t in cr.recipe_texts(x)['inputs'] if t.startswith('any ')]
    T.check(named and sum('(' in t for t in named) * 2 >= len(named), f'type inputs named: {sorted(set(named))[:8]}')
    chancy = [x for x in recs if any(0 < c < 100 for c in x.get('chances') or ())]
    T.check(chancy, 'recipes with a mod chance')
    for x in chancy[:20]:
        T.check(any('% chance)' in c for c in cr.recipe_texts(x)['changes']), f"recipe {x['row']}: {cr.recipe_texts(x)}")
    T.check(all(len(x['chances']) == len(x['mods']) for x in recs), 'one chance per mod')


T.main(globals())
