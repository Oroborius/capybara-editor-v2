"""Legit mode (vanilla profile): exclusive with Mock Mode, same rules as the dev kit's server validator
(the dev kit validator, vendored unchanged as src/d2bt), refuses hacked characters / items and lets them through with the mode off.

Fixtures: the vanilla install (MXL_TEST_VANILLA_GAME), the vanilla sample character and, read only, the dev kit's
legit_*.d2s files (skipped when the dev kit is not at its usual path)."""
import os
from pathlib import Path
import shutil

import capytest as T

MODE = 'gui'
GEOMETRY = '760x620+0+0'
REPO = Path(T.REPO)
GAME = Path(os.environ.get('MXL_TEST_VANILLA_GAME') or REPO / '.cache/ingame/game')
SOURCE = next((c for c in (REPO / '.cache/samples/vanilla',
                           Path(os.environ.get('MXL_TEST_SAVE_DIR', '/nonexistent')).parent / 'vanilla')
               if (c / 'complex.d2s').is_file()), REPO / '.cache/samples/vanilla')
DEVKIT = Path('/home/ps5/Downloads/D2-Development-Kit/tests')
SAVES = Path(T.guard(os.path.join(T.tmp(), 'legit102-saves')))
AVAILABLE = (GAME / 'd2data.mpq').is_file() and (SOURCE / 'complex.d2s').is_file()
SAVES.mkdir(exist_ok=True)
if AVAILABLE:
    shutil.copy2(SOURCE / 'complex.d2s', SAVES)
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': str(GAME), 'MXL_SAVE_DIR': str(SAVES)}


def need():
    if not AVAILABLE:
        T.skip('no 1.14d game data or sample character')


@T.test
def toggles_are_exclusive():
    need()
    import mxl_legit
    import mxl_mock_gui as G
    import settings
    T.chartab()
    T.pump(5)
    T.check(G._state['lvar'] is not None, 'the Legit Mode checkbox exists next to Mock Mode')
    G.set_mode(False)
    G.set_legit(True)
    T.check(G._state['lvar'].get() and not G._state['var'].get(), 'legit on, mock off')
    T.check(mxl_legit.enabled() and settings.get('legit_mode') is True, 'legit setting saved')
    T.check(G._state['llabel'].winfo_manager() == 'pack', 'the "checked against the server rules" label shows')
    G.set_mode(True)
    T.check(G._state['var'].get() and not G._state['lvar'].get(), 'mock on turns legit off')
    T.check(not mxl_legit.enabled() and not settings.get('legit_mode'), 'legit setting cleared')
    G.set_legit(True)
    T.check(G._state['lvar'].get() and not G._state['var'].get(), 'legit on turns mock off')
    T.check(not settings.get('mock_mode'), 'mock setting cleared')
    G.set_legit(False)
    T.check(not mxl_legit.enabled(), 'legit off')


@T.test
def devkit_legit_saves_validate_clean():
    need()
    starter = DEVKIT / 'legit_starter.d2s'
    if not starter.is_file():
        T.skip('dev kit fixtures not found')
    import mxl_legit
    import mxl_mock_gui as G
    import mxl_char
    T.chartab()
    G.set_legit(True)
    for name in ('starter', 'level_up', 'level_down'):
        raw = (DEVKIT / f'legit_{name}.d2s').read_bytes()
        T.eq(mxl_legit.check_character(raw), [], f'{name}: dev kit bytes')
        path = SAVES / f'fx_{name}.d2s'
        path.write_bytes(raw)
        ch = mxl_char.Character(str(path), T.G.app.data)
        T.eq(mxl_legit.check_character(ch.build()), [], f'{name}: the editor\'s own bytes')
    bad = mxl_legit.check_character((DEVKIT / 'legit_mockhighd.d2s').read_bytes())
    T.check({'experience', 'stat-points', 'skill-points'} <= {f.rule for f in bad}, 'mock clone is not legit')
    G.set_legit(False)


@T.test
def hacked_character_refused_only_in_legit_mode():
    need()
    starter = DEVKIT / 'legit_starter.d2s'
    if not starter.is_file():
        T.skip('dev kit fixtures not found')
    import mxl_char
    import mxl_legit
    import mxl_mock_gui as G
    T.chartab()
    path = SAVES / 'hack.d2s'
    path.write_bytes(starter.read_bytes())
    before = path.read_bytes()
    ch = mxl_char.Character(str(path), T.G.app.data)
    ch.set_stat(0, 500)                                  # strength way over the stat point budget
    G.set_legit(True)
    try:
        ch.save(backup=False)
    except mxl_char.CharError as e:
        T.check(isinstance(e, mxl_legit.LegitError) and 'stat-points' in str(e), f'refused with the rule: {e}')
    else:
        T.check(False, 'the hacked character was written in Legit mode')
    T.check(path.read_bytes() == before, 'file unchanged after the refusal')
    G.set_legit(False)
    ch = mxl_char.Character(str(path), T.G.app.data)
    ch.set_stat(0, 500)
    ch.save(backup=False)
    T.check(path.read_bytes() != before, 'written with Legit mode off')


@T.test
def hacked_item_refused_only_in_legit_mode():
    need()
    import mxl_legit
    import mxl_mock_gui as G
    from mxl_creator import CreateError, Creator
    T.chartab()
    cr = Creator(T.G.app.data)
    spec = None
    for i, _name, u in cr.uniques():
        if T.G.app.data.base(u['code']).kind == 'armor' and T.G.app.data.base(u['code']).size == (2, 2):
            spec = cr.new_spec('unique', None, i)
            break
    T.check(spec is not None, 'a unique armor to build')
    cr.roll(spec, 'max')
    autos = cr.auto_choices(spec['code'], spec['ilvl'])
    if autos:
        spec['auto'] = autos[0][0]
    G.set_legit(False)
    ok, _rec = cr.build(dict(spec))                        # the item as the game makes it
    G.set_legit(True)
    T.eq(mxl_legit.impossible(mxl_legit.check_item(ok)), [], 'a rolled unique passes the item rules')
    spec['unrestricted'] = True
    spec['sockets'] = 7                                    # no unique takes seven sockets
    G.set_legit(False)
    hacked, _rec = cr.build(dict(spec))
    T.check(hacked, 'built with Legit mode off')
    G.set_legit(True)
    try:
        cr.build(dict(spec))
    except CreateError as e:
        T.check('sockets' in str(e), f'refused with the rule: {e}')
    else:
        T.check(False, '7 sockets on a unique built in Legit mode')
    G.set_legit(False)



def _illegit_charm(cr):
    """A small charm (cm1) carrying a medium-charm life suffix, its life value far above any small charm's."""
    import mxl_legit
    from d2bt.legit import allowed
    v = mxl_legit._validator()
    types = v.save_tables.ancestors(v.bases['cm1'][1].get('type'))
    hp = [i for (t, i), (_t, r) in v.affixes.items()
          if t == 'magicsuffix' and r.get('name') and r.get('mod1code') == 'hp' and r.get('spawnable') == '1'
          and not allowed(types, r) and to_int(r.get('level')) <= 30]
    T.check(hp, 'a life suffix that small charms cannot take')
    spec = cr.new_spec('magic', 'cm1 ')
    spec['ilvl'] = 60
    spec['suffix'] = next(i for i, _l, a in cr.affix_choices('magicsuffix', 'cm1 ', 60)
                          if v.affixes[('magicsuffix', i)][1].get('mod1code') == 'hp')
    spec['prefix'] = None
    blob, rec = cr.build(spec)
    from mxl_creator import decode_blob, build_blob
    rec, kids = decode_blob(blob, T.G.app.data)
    rec['suffix'] = hp[0]
    for st in rec['stats']:
        if st['id'] == 7:                               # maximum life
            st['value'] = 400
    return build_blob(rec, kids, T.G.app.data, preserve_stat_order=True)


def to_int(x):
    from d2bt.tooltip.data import to_int as f
    return f(x)


@T.test
def convert_to_strict_legit_charm_and_sockets():
    need()
    import mxl_legit
    import mxl_legit_convert as C
    import mxl_mock_gui as G
    from mxl_creator import Creator, decode_blob, build_blob, FLAG_SOCKETED
    T.chartab()
    cr = Creator(T.G.app.data)
    G.set_legit(False)
    blob = _illegit_charm(cr)
    G.set_legit(True)
    bad = mxl_legit.impossible(mxl_legit.check_item(blob))
    T.check({f.rule for f in bad} >= {'affix-type'}, f'the charm is not legit: {[f.rule for f in bad]}')
    T.check(C.needs_conversion(blob), 'conversion is offered')
    res = C.convert(blob, T.G.app.data)
    T.check(res.blob is not None, f'converted: {C.report(res)} ;; {res.changes} ;; {[(f.rule, f.detail) for f in bad]}')
    T.eq(mxl_legit.impossible(mxl_legit.check_item(res.blob)), [], 'the converted charm is legit')
    kinds = lambda b: sorted({s['id'] for s in decode_blob(b, T.G.app.data)[0]['stats']})
    T.eq(kinds(res.blob), kinds(blob), 'same stat kinds kept')
    T.check(any('->' in c for c in res.changes), f'changes listed: {res.changes}')
    T.check(not C.needs_conversion(res.blob), 'nothing left to convert')
    # (b) too many sockets: a small charm cannot be socketed at all; use a body armor with 7
    G.set_legit(False)
    spec = None
    for code in ('plt ', 'ltp ', 'qui '):
        if code in T.G.app.data.bases:
            spec = cr.new_spec('normal', code)
            break
    spec['sockets'] = 3
    sblob, rec = cr.build(spec)
    rec, kids = decode_blob(sblob, T.G.app.data)
    rec['sockets'] = 7
    sblob = build_blob(rec, kids, T.G.app.data, preserve_stat_order=True)
    G.set_legit(True)
    T.check(any(f.rule == 'sockets' for f in mxl_legit.impossible(mxl_legit.check_item(sblob))),
            f'too many sockets: {[(f.rule, f.detail) for f in mxl_legit.check_item(sblob)]}')
    res = C.convert(sblob, T.G.app.data)
    T.check(res.blob is not None, f'sockets converted: {C.report(res)}')
    T.eq(mxl_legit.impossible(mxl_legit.check_item(res.blob)), [], 'legit after reducing sockets')
    rec, _k = decode_blob(res.blob, T.G.app.data)
    T.check(0 < rec.get('sockets', 0) <= 4, f"sockets reduced to the legal max: {rec.get('sockets')}")
    G.set_legit(False)


@T.test
def convert_menu_entry_only_for_illegit_items_in_legit_mode():
    need()
    import tkinter as tk
    import mxl_legit_convert as C
    import mxl_mock_gui as G
    from mxl_creator import Creator
    win = T.chartab()
    cr = Creator(T.G.app.data)
    G.set_legit(False)
    blob = _illegit_charm(cr)

    class E:
        pass
    e = E()
    e.blob = blob
    menu = tk.Menu(win.top, tearoff=False)
    T.check(not C.add_menu_entry(win, menu, e), 'hidden with Legit mode off')
    G.set_legit(True)
    T.check(C.add_menu_entry(win, menu, e), 'shown for an illegit item in Legit mode')
    T.eq(menu.entrycget(0, 'label'), C.LABEL, 'label')
    res = C.convert(blob, T.G.app.data)
    e.blob = res.blob
    menu2 = tk.Menu(win.top, tearoff=False)
    T.check(not C.add_menu_entry(win, menu2, e), 'hidden once the item passes')
    G.set_legit(False)


# impossible findings per private reference save (sorted order), as the dev kit's checker at the vendored commit
# reports them (None: unreadable = hacked). The saves are private (.cache/samples, never committed): skipped without.
REF_EXPECTED = {
    'legit-ref': [0, 69, 102, 135, 163, 93, 100, 96, 48, 48, 54, 27, 94, 106, 131, 131, 155, None, 66, 41, 93, 32, 100,
                  0, 93, 90, 91, 91, 29, 125, 133, 26, 69, 63, 54, 98],
    'lld-ref': [166, 167, 171, 171, 129, 171, 41],
}


@T.test
def legit_verdicts_match_the_dev_kit_on_the_references():
    import glob
    import mxl_legit
    root = Path(T.REPO) / '.cache' / 'samples'
    if not all((root / d).is_dir() for d in REF_EXPECTED) or not mxl_legit.prepare():
        T.skip('private reference saves or stock tables unavailable')
    for d, want in REF_EXPECTED.items():
        files = sorted(glob.glob(str(root / d / '**' / '*.d2s'), recursive=True))
        T.eq(len(files), len(want), f'{d}: file count')
        got = []
        for f in files:
            fs = mxl_legit.check_character(Path(f).read_bytes())
            got.append(None if any(x.rule in ('unreadable', 'stat') and x.item == 'character' for x in fs)
                       else len(mxl_legit.impossible(fs)))
        T.eq(got, want, f'{d}: impossible findings per save, as the dev kit')


@T.test
def mpq_reads_work_without_os_pread():
    """Windows has no os.pread (tester: Legit mode "module 'os' has no attribute 'pread'"): the stand-in reads the
    game's archives the same way (the vendored reader's own fallback)."""
    import os
    from d2bt.mpq import MPQArchive
    mpq = next((p for p in GAME.glob('*.mpq') if p.name.lower() == 'patch_d2.mpq'), None)
    if mpq is None:
        T.skip('no patch_d2.mpq')
    name = r'data\global\excel\magicprefix.txt'
    want = MPQArchive(str(mpq)).read(name)
    real = os.pread
    try:
        del os.pread
        T.eq(MPQArchive(str(mpq)).read(name), want, 'same bytes without os.pread (the seek + read fallback)')
    finally:
        os.pread = real


@T.test
def illegit_items_get_a_red_border_in_legit_mode():
    """In Legit Mode an item the server would reject has a red box around it on the Character tab; none without
    the mode (user: they see at once what is not legit)."""
    need()
    import mxl_mock_gui as G
    win = T.chartab()
    T.pump(5)

    def boxes():
        n = 0
        stack = [win.top]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if w.winfo_class() == 'Canvas':
                n += len(w.find_withtag('illegit'))
        return n
    G.set_legit(False)
    T.pump(5)
    T.eq(boxes(), 0, 'no borders with Legit Mode off')
    G.set_legit(True)
    T.pump(10)
    shot = os.environ.get('LEGIT_SHOT')
    if shot:
        win.top.update_idletasks()
        os.system(f'import -window root {shot}')
    T.check(boxes() > 0, f'{boxes()} red borders on the sample character (it holds editor-made items)')
    G.set_legit(False)
    T.pump(5)
    T.eq(boxes(), 0, 'borders gone with the mode off')


@T.test
def dev_kit_item_vectors_give_their_expected_verdicts():
    """The dev kit's item-generation test vectors (tests/data/itemgen_vectors.json, vendored with d2bt): each item
    gets exactly the expected findings from the vendored validator, as in the dev kit's own itemgen_test."""
    import collections
    import json
    import mxl_legit
    from d2bt.lint.savescan import ParsedItem
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    v = mxl_legit._validator()

    def parsed_item(fields):
        fields = dict(fields)
        fields['children'] = [parsed_item(child) for child in fields.get('children', [])]
        fields['set_stats'] = {int(k): val for k, val in fields.get('set_stats', {}).items()}
        return ParsedItem(**fields)
    vectors = json.loads((Path(T.REPO) / 'tests' / 'data' / 'itemgen_vectors.json').read_text())
    bad = []
    required = getattr(v, 'check_required', None)
    v.check_required = False                     # the vectors carry partial stat lists (as in the dev kit's test)
    for vector in vectors:
        got = collections.Counter(f.rule for f in v.validate_item(parsed_item(vector['item'])))
        if got != collections.Counter(vector['rules']):
            bad.append(f"{vector['name']}: {sorted(got.elements())} != {sorted(vector['rules'])}")
    if required is not None:
        v.check_required = required
    T.check(len(vectors) >= 40, f'{len(vectors)} vectors')
    T.eq(bad, [], 'vectors with other findings than expected')
def creator_offers_only_what_the_server_accepts():
    """Every magic affix the item creator offers (one base per item type, a low and a high item level), built at its
    max roll, passes the server's checker; the rare offers are the same rows with the rare flag (user: the creator
    offered a 50% resist rare ring the game cannot drop)."""
    import collections
    import time
    import mxl_legit
    from mxl_rc_menu import _creator_for
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    win = T.chartab()
    cr = _creator_for(win)
    v = mxl_legit._validator()
    reps = {}
    for code, (kind, row) in v.bases.items():
        if row.get('spawnable') == '1' and row.get('type') not in reps and (code.ljust(4)) in win.data.bases:
            if cr.can_have_quality(code.ljust(4), 'magic'):
                reps[row.get('type')] = code.ljust(4)
    bad, built, t0 = collections.Counter(), 0, time.time()
    examples = []
    for code in reps.values():
        for ilvl in (30, 99):
            ilvl = max(ilvl, cr.min_ilvl(cr.new_spec('magic', code)))
            for kind, key in (('magicprefix', 'prefix'), ('magicsuffix', 'suffix')):
                for idx, label, _a in cr.affix_choices(kind, code, ilvl):
                    spec = cr.new_spec('magic', code)
                    spec['ilvl'] = ilvl
                    spec[key] = idx
                    autos = cr.auto_choices(code, ilvl, 'magic')
                    spec['auto'] = autos[-1][0] if autos else None
                    for m in cr.mods(spec):
                        if m.variable:
                            spec['rolls'][m.source] = m.max
                    try:
                        blob, _rec = cr.build(spec)
                    except Exception as e:
                        bad[('build', type(e).__name__)] += 1
                        if len(examples) < 3:
                            examples.append(f'{code} ilvl {ilvl} {label}: {e}')
                        continue
                    built += 1
                    for f in mxl_legit.impossible(mxl_legit.check_item(blob)):
                        bad[(f.rule, f.detail.split(' ')[0])] += 1
                        if len(examples) < 12:
                            examples.append(f'{code.strip()} ilvl {ilvl} {label}: {f.rule} {f.detail}')
    T.check(built > 1000, f'{built} items built over {len(reps)} item types in {time.time() - t0:.0f} s')
    T.eq(dict(bad), {}, 'creator offers the server rejects; e.g. ' + ' | '.join(examples))



class _Defaults:
    """The creator window's default logic (prepare_defaults, fill_new_rolls) without a window."""

    def __init__(self, cr):
        self.cr, self.data = cr, cr.data

    def make(self, spec, how='max', ilvl=99):
        import mxl_creator_gui as CG
        spec['ilvl'] = max(spec['ilvl'], ilvl)
        CG.CreatorWindow.prepare_defaults(self, spec)
        self.add_affixes(spec)
        self.cr.roll(spec, how)
        return spec

    def add_affixes(self, spec):
        """What a user adds to the empty magic / rare / crafted item the creator starts with."""
        cr, code, ilvl, q = self.cr, spec['code'], spec['ilvl'], spec['quality']
        if q == 'magic' and not (spec.get('prefix') or spec.get('suffix')):
            ch = cr.affix_choices('magicprefix', code, ilvl) or cr.affix_choices('magicsuffix', code, ilvl)
            spec['prefix' if cr.affix_choices('magicprefix', code, ilvl) else 'suffix'] = ch[-1][0]
        elif q == 'rare' and not (spec['rare_prefixes'] or spec['rare_suffixes']):
            for kind, key in (('magicprefix', 'rare_prefixes'), ('magicsuffix', 'rare_suffixes')):
                groups = set()
                for i, _l, a in reversed(cr.affix_choices(kind, code, ilvl, rare=True)):
                    if len(spec[key]) >= 2:
                        break
                    if a['group'] not in groups:
                        spec[key].append(i)
                        groups.add(a['group'])
        elif q == 'crafted' and not (spec['rare_prefixes'] or spec['rare_suffixes']):
            cr.reroll_crafted(spec)


def _example(examples, key, text):
    """examples: list of texts, one per (tag, rule) key."""
    seen = examples.__dict__.setdefault('k', set()) if hasattr(examples, '__dict__') else None
    if seen is not None and key not in seen:
        seen.add(key)
        examples.append(text)


class _Ex(list):
    pass


def _problems(cr, spec, tag, bad, examples, v=None):
    import mxl_legit
    try:
        blob, _rec = cr.build(spec)
    except Exception as e:
        bad[(tag, 'build')] += 1
        _example(examples, (tag, 'build'), f'{tag} {spec["code"].strip()}: {type(e).__name__} {str(e)[:100]}')
        return None
    for f in mxl_legit.impossible(mxl_legit.check_item(blob)):
        bad[(tag, f.rule)] += 1
        _example(examples, (tag, f.rule), f'{tag} {spec["code"].strip()} {f.item}: {f.rule} {f.detail}')
    return blob


@T.test
def creator_default_items_are_legit():
    """Everything the creator builds by default in vanilla passes the server's checker: rare / crafted names and
    affixes, innate (automagic) affixes, every set and unique row, superior and low quality, the defense at its max,
    the creator's socket maximum, ethereal where offered."""
    import collections
    import time
    import mxl_legit
    from mxl_rc_menu import _creator_for
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    win = T.chartab()
    cr = _creator_for(win)
    d = win.data
    v = mxl_legit._validator()
    dflt = _Defaults(cr)
    bad, examples, built, t0 = collections.Counter(), _Ex(), collections.Counter(), time.time()

    def go(spec, tag, how='max', ilvl=99):
        try:
            dflt.make(spec, how, ilvl)
        except Exception as e:
            bad[(tag, 'defaults')] += 1
            _example(examples, (tag, 'defaults'), f'{tag} {spec["code"]}: defaults {type(e).__name__} {e}')
            return
        if spec['code'] in d.bases and d.base(spec['code']).kind == 'armor':
            spec['defense'] = cr.defense_range(spec)[1]
        n = cr.creator_socket_limit(spec)
        spec['sockets'] = max(n, cr.innate_sockets(spec))
        if cr.ethereal_ok(spec):
            spec['ethereal'] = True
        if _problems(cr, spec, tag, bad, examples, v) is not None:
            built[tag] += 1

    reps = {}
    for code, (kind, row) in v.bases.items():
        c = code.ljust(4)
        if row.get('spawnable') == '1' and c in d.bases:
            reps.setdefault(row.get('type'), []).append(c)
    one = {t: cs[0] for t, cs in reps.items()}
    for t, c in sorted(one.items()):
        for ilvl in (30, 99):
            for q in ('normal', 'superior', 'low', 'magic', 'rare', 'crafted'):
                if c == 'gld ' or not (cr.can_have_quality(c, q if q != 'low' else 'normal') and
                                       (q not in ('magic', 'rare') or cr.can_roll_affixes(c, q))):
                    continue
                if q == 'crafted' and not cr.craft_rows(c):
                    continue
                spec = cr.new_spec(q, c)
                spec['ilvl'] = max(ilvl, cr.min_ilvl(spec))
                go(spec, q, ilvl=ilvl)
    for t, c in sorted(one.items()):
        if cr.can_have_quality(c, 'superior') and d.base(c).kind in ('weapons', 'armor'):
            for sup in cr.superior_choices(c):
                spec = cr.new_spec('superior', c)
                spec['superior'] = sup
                go(spec, 'superior-variant')
    # a rare / crafted item with each single rare-eligible affix, and every innate affix
    for t, c in sorted(one.items()):
        if not (cr.can_have_quality(c, 'rare') and cr.can_roll_affixes(c, 'rare')):
            continue
        for kind, key in (('magicprefix', 'rare_prefixes'), ('magicsuffix', 'rare_suffixes')):
            for i, _l, _a in cr.affix_choices(kind, c, 99, rare=True):
                spec = cr.new_spec('rare', c)
                spec[key] = [i]
                go(spec, 'rare-affix')
    for c in sorted({x for cs in reps.values() for x in cs} - {'gld '}):
        for i, _l, _a in cr.auto_choices(c, 99):
            spec = cr.new_spec('normal', c)
            spec['ilvl'], spec['auto'] = 99, i
            go(spec, 'auto')
    for kind, rows, q in (('uniqueitems', d.uniques, 'unique'), ('setitems', d.set_items, 'set')):
        for row in range(len(rows)):
            if q == 'unique' and not cr.unique_enabled(row):
                continue
            if not rows[row].get('code') or rows[row]['code'] not in d.bases:
                continue
            go(cr.new_spec(q, None, row), q)
    for k, n in sorted(bad.items()):
        print('BAD', k, n)
    T.check(sum(built.values()) > 1000, f'{dict(built)} items built in {time.time() - t0:.0f} s')
    bad = +bad
    T.eq(dict(bad), {}, 'default creator items the server rejects: ' + ' | '.join(examples[:25]))



@T.test
def creator_starts_new_affix_items_empty():
    """Vanilla: a new magic / rare / crafted item has no affixes (the user adds them); the rare name keeps its
    default fragments."""
    import mxl_legit
    import mxl_creator_gui as CG
    from mxl_rc_menu import _creator_for
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    win = T.chartab()
    cr = _creator_for(win)
    dflt = _Defaults(cr)
    seen = set()
    for code in ('hax ', 'rin ', 'cap '):
        for q in ('magic', 'rare', 'crafted'):
            if not cr.can_have_quality(code, q) or (q == 'crafted' and not cr.craft_rows(code)):
                continue
            spec = cr.new_spec(q, code)
            spec['ilvl'] = 99
            CG.CreatorWindow.prepare_defaults(dflt, spec)
            T.check(not (spec.get('prefix') or spec.get('suffix') or spec['rare_prefixes'] or spec['rare_suffixes']),
                    f'{q} {code}: starts without affixes: {spec}')
            if q != 'magic':
                T.check(spec['rare_names'] is not None, f'{q} {code}: has a default name')
            seen.add(q)
    T.check({'magic', 'rare'} <= seen, f'qualities checked: {seen}')


def _open_creator(win, **kw):
    import mxl_creator_gui as CG
    w = CG.CreatorWindow(win.app, data=win.data, **kw)
    T.pump(10)
    return w


def _walk(widget):
    for c in widget.winfo_children():
        yield c
        yield from _walk(c)


@T.test
def creator_rare_names_are_dropdowns():
    """Both parts of a rare / crafted name are read-only dropdowns (ttk.Combobox) with the full lists."""
    from tkinter import ttk
    import mxl_creator_gui as CG
    need()
    win = T.chartab()
    w = _open_creator(win, target=lambda blob: 'ok', target_label='x')
    cr = w.cr
    code = next(c for c in ('hax ', 'rin ', 'cap ') if cr.can_have_quality(c, 'rare'))
    for q in ('rare', 'crafted'):
        if q == 'crafted' and not cr.craft_rows(code):
            continue
        spec = cr.new_spec(q, code)
        spec['ilvl'] = 99
        w.spec = spec
        w.load_spec(spec)
        T.pump(5)
        names = cr.rare_name_choices(code)
        combos = [c for c in _walk(w.opts) if isinstance(c, ttk.Combobox)]
        for kind in ('rareprefix', 'raresuffix'):
            want = [CG.clean(t) for _, t in names[kind]]
            T.check(want, f'{kind}: a list')
            hit = [c for c in combos if list(c.cget('values')) == want]
            T.check(hit and str(hit[0].cget('state')) == 'readonly', f'{q} {kind}: a readonly dropdown holds the list')
    w.top.destroy()


@T.test
def creator_in_the_hero_editor_layout_creates_into_the_item_buffer():
    need()
    win = T.chartab()
    win.app._capy_clip = None
    w = _open_creator(win)
    spec = w.cr.new_spec('normal', 'hax ')
    w.spec = spec
    w.load_spec(spec)
    w.commit()
    T.pump(5)
    clip = getattr(win.app, '_capy_clip', None)
    T.check(clip is not None, 'the item is in the item buffer')
    T.check('item buffer' in str(win.app.status.cget('text')), f'status: {win.app.status.cget("text")!r}')
    from mxl_creator import decode_blob
    T.eq(decode_blob(bytes(clip[0]), win.data)[0]['code'].strip(), 'hax', 'the buffered item is the one made')
    w.top.destroy()
    win.app._capy_clip = None


@T.test
def creator_vanilla_has_no_shared_stash_target():
    """1.14d has no shared stash: the creator's button creates into the item buffer, nothing offers a stash file."""
    need()
    win = T.chartab()
    w = _open_creator(win)
    T.check('stash' not in str(w.btn_ok.cget('text')).lower(), f'button: {w.btn_ok.cget("text")!r}')
    T.check('shared' not in str(w.dest.cget('text')).lower() and 'stash' not in str(w.dest.cget('text')).lower(),
            f'destination: {w.dest.cget("text")!r}')
    w.top.destroy()


@T.test
def creator_diadem_and_hand_axe_offers():
    """A diadem (ci3) is offered the skill-tab prefixes and the class-skill affixes the server accepts (magic and
    rare, ilvl 99), each passing at max roll; a hand axe gets no Sorceress / Barbarian-only tab prefixes of the
    caster kind (their item types do not include axes)."""
    import mxl_legit
    from mxl_rc_menu import _creator_for
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    win = T.chartab()
    cr = _creator_for(win)
    v = mxl_legit._validator()
    from d2bt.legit import allowed
    types = v.save_tables.ancestors('circ') | v.save_tables.ancestors(v.bases['ci3'][1].get('type2'))
    tab, cls = 0, 0
    for kind, key, rkey in (('magicprefix', 'prefix', 'rare_prefixes'), ('magicsuffix', 'suffix', 'rare_suffixes')):
        for rare in (False, True):
            offered = {i for i, _l, _a in cr.affix_choices(kind, 'ci3 ', 99, rare=rare)}
            for (t, i), (_t, row) in v.affixes.items():
                if t != kind or not allowed(v.save_tables.ancestors(v.bases['ci3'][1]['type']), row):
                    continue
                if row.get('mod1code') not in ('skilltab', 'ama', 'sor', 'nec', 'pal', 'bar', 'dru', 'ass'):
                    continue
                ok = row.get('spawnable') == '1' and int(row.get('frequency') or 0) > 0 and (not rare or row.get('rare') == '1')
                lvl = int(row.get('level') or 0)
                if ok and lvl <= cr.affix_level('ci3 ', 99) and (not row.get('maxlevel') or lvl <= 99):
                    T.check(i in offered, f'diadem {kind} {i} {row["name"]} ({row["mod1code"]}) offered (rare={rare})')
                    if row['mod1code'] == 'skilltab':
                        tab += 1
                    else:
                        cls += 1
            for i in offered:
                spec = cr.new_spec('rare' if rare else 'magic', 'ci3 ')
                spec['ilvl'] = 99
                autos = cr.auto_choices('ci3 ', 99, spec['quality'])
                spec['auto'] = autos[-1][0] if autos else None
                if rare:
                    names = cr.rare_name_choices('ci3 ')
                    spec['rare_names'] = (names['rareprefix'][0][0], names['raresuffix'][0][0])
                    spec[rkey] = [i]
                else:
                    spec[key] = i
                for m in cr.mods(spec):
                    if m.variable:
                        spec['rolls'][m.source] = m.max
                if v.affixes[(kind, i)][1].get('mod1code') in ('skilltab', 'ama', 'sor', 'nec', 'pal', 'bar', 'dru', 'ass'):
                    blob, _r = cr.build(spec)
                    T.eq(mxl_legit.impossible(mxl_legit.check_item(blob)), [], f'diadem {kind} {i} built')
    T.check(tab > 0 and cls > 0, f'diadem tab {tab} / class {cls} affixes checked')
    caster = {'sor', 'amul'}
    for kind in ('magicprefix', 'magicsuffix'):
        for i, _l, a in cr.affix_choices(kind, 'hax ', 99):
            row = v.affixes[(kind, i)][1]
            T.check(not (row.get('mod1code') == 'skilltab' and row.get('classspecific') == 'sor'),
                    f'hand axe is offered a Sorceress tab affix: {row["name"]}')


@T.test
def creator_rare_name_round_trip():
    """The chosen rare name fragments are what the item shows and what Edit item reads back."""
    import mxl_creator_gui as CG
    from mxl_creator import decode_blob
    from mxl_save import blob_item
    need()
    win = T.chartab()
    cr = _Defaults(win and __import__('mxl_rc_menu')._creator_for(win)).cr
    names = cr.rare_name_choices('hax ')
    pre, suf = names['rareprefix'][3], names['raresuffix'][5]
    spec = cr.new_spec('rare', 'hax ')
    spec['ilvl'] = 99
    spec['rare_names'] = (pre[0], suf[0])
    spec['rare_prefixes'], spec['rare_suffixes'] = [cr.affix_choices('magicprefix', 'hax ', 99, rare=True)[0][0]], \
        [cr.affix_choices('magicsuffix', 'hax ', 99, rare=True)[0][0]]
    cr.roll(spec, 'max')
    blob, _rec = cr.build(spec)
    back = cr.spec_from_item(blob_item(blob, win.data))
    T.eq(tuple(back['rare_names']), (pre[0], suf[0]), 'Edit item reads the same name rows')


@T.test
def creator_hellfire_torch_every_class_and_grand_charm_tabs():
    """Random class skills (property function 36): the sheet's 0..6 is the class, the stat's value is the property's
    own 3 - built for each class the torch passes the checker. A grand charm is offered the skill-tab prefixes of
    all seven classes."""
    import mxl_legit
    from mxl_rc_menu import _creator_for
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    win = T.chartab()
    cr = _creator_for(win)
    v = mxl_legit._validator()
    d = win.data
    row = next(i for i, r in enumerate(v.uniques) if r['index'] == 'Hellfire Torch')
    for cls in range(7):
        spec = cr.new_spec('unique', None, row)
        cr.roll(spec, 'max')
        for m in cr.mods(spec):
            if m.raw[0] == next(p for p in range(len(d.prop_func)) if d.prop_func[p] == 36):
                spec['rolls'][m.source] = cls
        blob, rec = cr.build(spec)
        T.eq(mxl_legit.impossible(mxl_legit.check_item(blob)), [], f'torch class {cls}')
        st = [x for x in rec['stats'] if x['id'] == 83]
        T.eq([(x['param'], x['value']) for x in st], [(cls, 3)], f'torch class {cls}: +3 to that class')
    classes = set()
    for kind in ('magicprefix', 'magicsuffix'):
        for i, _l, _a in cr.affix_choices(kind, 'cm3 ', 99):
            r = v.affixes[(kind, i)][1]
            if r.get('mod1code') == 'skilltab':
                classes.add(int(r['mod1param']) // 3)
    T.eq(classes, set(range(7)), 'grand charm skill-tab prefixes of all 7 classes')


@T.test
def copies_and_duplicates_get_a_new_item_id():
    need()
    import mxl_rc_menu as RC
    from mxl_creator import ClipItem, decode_blob, renew_item_ids
    win = T.chartab()
    cr = RC._creator_for(win)
    spec = cr.new_spec('normal', 'hax ')
    blob, _r = cr.build(spec)
    old = decode_blob(blob, win.data)[0]['id']
    new = renew_item_ids(blob, win.data)
    rec = decode_blob(new, win.data)[0]
    T.check(rec['id'] != old, 'the renewed copy has another id')
    T.eq((rec['code'], rec['ilvl'], rec['quality']), ('hax ', spec['ilvl'], 'normal'), 'the rest of the item is unchanged')
    clip = ClipItem(blob, 'x', win.data)
    a, b = decode_blob(clip[0], win.data)[0]['id'], decode_blob(clip[0], win.data)[0]['id']
    T.check(a != b and old not in (a, b), 'every paste of the clipboard item has its own id')
    T.eq(mxl_legit_impossible(new), [], 'a renewed copy is still a legit item')


def mxl_legit_impossible(blob):
    import mxl_legit
    return mxl_legit.impossible(mxl_legit.check_item(blob))


@T.test
def creator_runewords_and_defense_are_legit():
    """Every runeword in up to three of its bases (plain and ethereal where offered), defense at its max."""
    import collections
    import mxl_legit
    from mxl_rc_menu import _creator_for
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    win = T.chartab()
    cr = _creator_for(win)
    d = win.data
    bad, ex, n = collections.Counter(), _Ex(), 0
    for row, _name, _runes in cr.runewords():
        bases, seen = cr.runeword_bases(row), set()
        picks = [b for b in bases if not (b.type in seen or seen.add(b.type))][:3]
        for b in picks:
            for eth in (False, True):
                spec = cr.new_spec('runeword', b.code, row)
                spec['ilvl'] = 99
                spec['sockets'] = len(d.runewords[row][1])
                if eth and not cr.ethereal_ok(spec):
                    continue
                spec['ethereal'] = eth
                import mxl_creator_gui as CG
                CG.CreatorWindow.prepare_defaults(_Defaults(cr), spec)
                cr.roll(spec, 'max')
                if d.base(b.code).kind == 'armor':
                    spec['defense'] = cr.defense_range(spec)[1]
                n += 1
                _problems(cr, spec, 'runeword', bad, ex)
    T.check(n > 100, f'{n} runeword items built')
    T.eq(dict(+bad), {}, 'runeword items the server rejects: ' + ' | '.join(ex[:10]))


@T.test
def make_item_socketed_follows_the_servers_socket_rule_in_legit_mode():
    """A rare helm gets at most 1 socket through the socket menu in Legit Mode, up to the hand-edit limit without."""
    need()
    import mxl_mock_gui as G
    import mxl_socket_menu as SM
    from mxl_creator import decode_blob
    from mxl_rc_menu import _creator_for
    win = T.chartab()
    cr = _creator_for(win)
    code = next(c for c in ('cap ', 'skp ', 'ghm ') if c in win.data.bases and cr.can_have_quality(c, 'rare'))
    spec = cr.new_spec('rare', code)
    spec['ilvl'] = 99
    names = cr.rare_name_choices(code)
    spec['rare_names'] = (names['rareprefix'][0][0], names['raresuffix'][0][0])
    spec['rare_prefixes'] = [cr.affix_choices('magicprefix', code, 99, rare=True)[0][0]]
    spec['rare_suffixes'] = [cr.affix_choices('magicsuffix', code, 99, rare=True)[0][0]]
    cr.roll(spec, 'max')
    blob, _r = cr.build(spec)
    rec = decode_blob(blob, win.data)[0]
    try:
        G.set_legit(True)
        T.eq(SM.max_sockets(cr, code, rec), 1, 'rare helm, Legit Mode on')
        G.set_legit(False)
        T.check(SM.max_sockets(cr, code, rec) >= 4, f'Legit Mode off: {SM.max_sockets(cr, code, rec)}')
    finally:
        G.set_legit(False)



@T.test
def legit_save_judges_only_what_the_edit_adds():
    """User report: editing one item refused because of OTHER non-legit items on the character. A save is refused
    only for impossible findings the change adds; a new hacked value is still refused."""
    need()
    import shutil
    import mxl_char
    import mxl_legit
    import mxl_mock_gui as G
    T.chartab()
    path = SAVES / 'mixed.d2s'
    shutil.copy2(SOURCE / 'complex.d2s', path)                 # holds editor-made items (many findings)
    if not mxl_legit.prepare() or not mxl_legit.impossible(mxl_legit.check_character(path.read_bytes())):
        T.skip('stock tables unavailable or the sample has no findings')
    G.set_legit(True)
    try:
        ch = mxl_char.Character(str(path), T.G.app.data)
        ch.remove(ch.items[0], False)                         # an edit that adds nothing illegal
        ch.save(backup=False)
        T.check(len(mxl_char.Character(str(path), T.G.app.data).items) == len(ch.items), 'saved despite old findings')
        ch = mxl_char.Character(str(path), T.G.app.data)
        before = path.read_bytes()
        ch.set_stat(0, 1000)                                  # adds a stat-points finding
        try:
            ch.save(backup=False)
        except mxl_char.CharError as e:
            T.check(isinstance(e, mxl_legit.LegitError), f'new finding refused: {e}')
        else:
            T.check(False, 'a new hacked value was written in Legit mode')
        T.eq(path.read_bytes(), before, 'file unchanged after the refusal')
    finally:
        G.set_legit(False)


@T.test
def rare_name_storm_touch_round_trip():
    """Tester: a rare ring named "Storm Touch" showed as "Rune Finger". The game reads the ids 1-based over
    raresuffix + rareprefix (D2Common DATATBLS_GetRareAffixTxtRecord); written 169 / 97, shown "Storm Touch"."""
    need()
    import mxl_creator as C
    import mxl_legit
    import mxl_rules
    from mxl_rc_menu import _creator_for
    win = T.chartab()
    cr = _creator_for(win)
    d = win.data

    def row(lst, word):
        return next(k for k, x in enumerate(lst)
                    if word in str(x if isinstance(x, str) else getattr(x, 'get', lambda k: x)('name')).lower())
    stored = cr.rare_names_stored((row(d.rare_prefix, 'storm'), row(d.rare_suffix, 'touch')))
    T.eq(tuple(stored), (169, 97), 'written as the game numbers them')
    spec = cr.new_spec('rare', 'rin ')
    spec['ilvl'] = 99
    spec['rare_names'] = cr.rare_names_from_stored(stored)
    pre = cr.affix_choices('magicprefix', 'rin ', 99, rare=True)
    if pre:
        spec['rare_prefixes'] = [pre[0][0]]
    blob, _rec = cr.build(spec)
    it = C.decode_item(bytes(blob), d)[0]
    T.eq(tuple(it['rare_names']), (169, 97), 'the saved ids')
    T.check('storm touch' in str(mxl_rules.rare_name(it, d)).lower(), f'shown as {mxl_rules.rare_name(it, d)!r}')
    if mxl_legit.prepare():
        T.eq([f.rule for f in mxl_legit.check_item(blob) if f.rule == 'rare-name'], [], 'the server accepts the name')
def stat_params_use_the_dev_kit_vocabulary():
    """Skill-tab / class params are named by statvocab ('Combat Skills (Barbarian Only)'), stat lines come from
    statvocab.display."""
    need()
    import mxl_statnames as SN
    win = T.chartab()
    tabs = dict(SN.param_choices(win.data, 188))
    T.check('Combat Skills (Barbarian Only)' in tabs, f'skill tab names: {list(tabs)[:4]}')
    T.eq(tabs['Combat Skills (Barbarian Only)'], 4 << 3, 'the packed class << 3 | tab layer')
    T.check('Barbarian' in dict(SN.param_choices(win.data, 83)), 'class names')
    T.eq(SN.vanilla_stat_value(win.data, 188, 4 << 3, 2), '+2 to Combat Skills (Barbarian Only)', 'item line')
    from mxl_vanilla_he_extras import skill_tab_choices
    T.eq(dict(skill_tab_choices(win.data))['Combat Skills (Barbarian Only)'], 4 << 3, 'Item editor dropdown')


@T.test
def creator_affix_inference_compares_the_skill_tab_layer():
    """A skill-tab affix's stat carries the packed layer (class << 3 | tab), as the saved item does."""
    need()
    import mxl_legit
    import mxl_creator as MC
    from mxl_rc_menu import _creator_for
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    cr = _creator_for(T.chartab())
    found = 0
    for _i, _l, a in cr.affix_choices('magicprefix', 'cm3 ', 99):
        for m in a['mods']:
            if cr.data.prop_func[m['prop']] == 10:
                st = MC.layered_stats([(m['prop'], m['param'], m['min'], m['max'])], cr.data, 'max')
                T.eq([x['param'] for x in st], [((m['param'] // 3) << 3) | (m['param'] % 3)], 'packed layer')
                found += 1
    T.check(found >= 7, f'{found} skill-tab prefixes on a grand charm')


@T.test
def creator_targeted_writers_go_to_the_item_buffer():
    """create_here (character / inventory / containers page) in the Hero Editor layout: a new item lands in the
    item buffer, the target writer is not called."""
    need()
    win = T.chartab()
    win.app._capy_clip = None
    called = []
    w = _open_creator(win, target=lambda blob: called.append(1) or 'written', target_label='x')
    spec = w.cr.new_spec('normal', 'hax ')
    w.spec = spec
    w.load_spec(spec)
    w.commit()
    T.pump(5)
    T.check(getattr(win.app, '_capy_clip', None) is not None and not called, 'in the item buffer, target untouched')
    w.top.destroy()
    win.app._capy_clip = None


@T.test
def convert_remaps_retired_affix_rows_and_rare_name_fragments():
    """A rare ring made by an older editor: retired classic rows (prefix 78, suffix 91: frequency 0) and the rare name
    fragment 199 the base cannot have. Convert to Strict Legit maps the rows to the rolling twins that
    legal_affixes offers, replaces the fragment, clamps the rolls and leaves no impossible finding."""
    need()
    import mxl_legit
    import mxl_legit_convert as LC
    from mxl_creator import build_blob, decode_blob
    from mxl_rc_menu import _creator_for
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    win = T.chartab()
    cr = _creator_for(win)
    v = mxl_legit._validator()
    spec = cr.new_spec('rare', 'rin ')
    spec['ilvl'] = 80
    names = cr.rare_name_choices('rin ')
    spec['rare_names'] = (names['rareprefix'][0][0], names['raresuffix'][0][0])
    spec['rare_prefixes'] = [cr.affix_choices('magicprefix', 'rin ', 80, rare=True)[0][0]]
    spec['rare_suffixes'] = [cr.affix_choices('magicsuffix', 'rin ', 80, rare=True)[0][0]]
    cr.roll(spec, 'max')
    blob, _r = cr.build(spec)
    rec, kids = decode_blob(blob, win.data)
    rec['rare_affixes'][0], rec['rare_affixes'][1] = 78, 91
    old = build_blob(rec, kids, win.data, preserve_stat_order=True)
    found = mxl_legit.impossible(mxl_legit.check_item(old))
    T.check(any(f.rule == 'affix-quality' for f in found), f'the retired rows are refused: {[f.detail for f in found]}')
    res = LC.convert(old, win.data)
    T.check(res.blob is not None, f'converted: {res.changes} / {[f.detail for f in res.remaining]}')
    T.eq(mxl_legit.impossible(mxl_legit.check_item(res.blob)), [], 'no impossible finding left')
    new = decode_blob(res.blob, win.data)[0]['rare_affixes']
    twins = {v.affixes[('magicprefix', 78)][1]['name'], v.affixes[('magicsuffix', 91)][1]['name']}
    T.eq({v.affixes[('magicprefix', new[0])][1]['name'], v.affixes[('magicsuffix', new[1])][1]['name']}, twins,
         'same names, rolling rows')
    T.check(new[0] != 78 and new[1] != 91, f'rows replaced: {new[:2]}')
    # the fragment: a name the base cannot have
    rec2, kids2 = decode_blob(blob, win.data)
    rec2['rare_names'] = (199, rec2['rare_names'][1])
    bad = build_blob(rec2, kids2, win.data, preserve_stat_order=True)
    f2 = mxl_legit.impossible(mxl_legit.check_item(bad))
    if any(f.rule == 'rare-name' for f in f2):
        r2 = LC.convert(bad, win.data)
        T.check(r2.blob is not None and not mxl_legit.impossible(mxl_legit.check_item(r2.blob)),
                f'fragment replaced: {r2.changes}')



@T.test
def set_items_carry_their_partial_set_bonuses():
    """Tester: Trang-Oul's Claws lacked "+25% to Poison Skill Damage" - a partial set bonus (setitems aprop3a,
    3 items) the item stores in its own set lists. Every set item is built with them and passes the validator."""
    need()
    import mxl_creator as C
    import mxl_legit
    from mxl_rc_menu import _creator_for
    win = T.chartab()
    cr = _creator_for(win)
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    row = next(k for k, label, _r in cr.set_items() if 'Trang' in label and 'Claws' in label)
    spec = cr.new_spec('set', None, row)
    blob, _rec = cr.build(spec)
    it = C.decode_item(bytes(blob), win.data)[0]
    bonus = [s for k in range(5) for s in (it.get(f'set_stats_{k}') or [])]
    T.check(any(s['value'] == 25 for s in bonus), f'the 3-item bonus is there: {bonus} (mask {it.get("set_mask")})')
    T.eq(mxl_legit.impossible(mxl_legit.check_item(blob)), [], 'the server accepts it')
    bad = []
    for key, label, _r in cr.set_items():
        sp = cr.new_spec('set', None, key)
        try:
            autos = cr.auto_choices(sp['code'], sp['ilvl'], 'set')
        except TypeError:
            autos = cr.auto_choices(sp['code'], sp['ilvl'])
        if autos:
            sp['auto'] = autos[0][0]                         # class bases need their innate (the GUI default)
        try:
            b2, _ = cr.build(sp)
        except Exception as e:
            bad.append(f'{label}: {type(e).__name__} {e}')
            continue
        bad += [f'{label}: {f.rule} {f.detail}' for f in mxl_legit.impossible(mxl_legit.check_item(b2))]
    T.eq(bad, [], 'every set item with its bonuses passes')


@T.test
def convert_fixes_ethereal_base_defense_and_renews_the_id():
    """Old editors stored an ethereal item's base defense without its x1.5 (server: "base defense outside range",
    suspicious). Convert puts it in range and gives the item a fresh id (copies with one id: "duplicate")."""
    need()
    import mxl_creator as C
    import mxl_legit
    import mxl_legit_convert as LC
    from mxl_rc_menu import _creator_for
    win = T.chartab()
    cr = _creator_for(win)
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    spec = cr.new_spec('normal', 'uui ')
    spec['ilvl'] = 99
    spec['ethereal'] = True
    blob, _rec = cr.build(spec)
    rec, kids = C.decode_blob(bytes(blob), win.data)
    rec['defense'] = rec['defense'] * 2 // 3                # stored without the ethereal x1.5
    bad = C.build_blob(rec, kids, win.data, preserve_stat_order=True)
    T.check(any(f.rule == 'defense' for f in mxl_legit.check_item(bad)), 'the old value is out of range')
    res = LC.convert(bad, win.data)
    T.check(res.blob is not None, 'converted')
    T.eq([f.rule for f in mxl_legit.check_item(res.blob) if f.rule == 'defense'], [], 'defense in range')
    T.check(C.decode_blob(res.blob, win.data)[0]['id'] != rec['id'], 'a fresh item id')


@T.test
def convert_adds_missing_required_stats():
    """Tester characters from older releases: Spirit without its FHR, Enigma without its defense... Convert adds
    every stat the game always puts on the item (d2bt required_stats) at the top of its range."""
    need()
    import mxl_creator as C
    import mxl_legit
    import mxl_legit_convert as LC
    from mxl_rc_menu import _creator_for
    win = T.chartab()
    cr = _creator_for(win)
    if not mxl_legit.prepare():
        T.skip('stock tables unavailable')
    key = next(k for k, label, _r in cr.runewords() if 'Spirit' in label)
    spec = cr.new_spec('runeword', 'uit ', key)
    spec['ilvl'] = 99
    spec['sockets'] = 4
    blob, _rec = cr.build(spec)
    rec, kids = C.decode_blob(bytes(blob), win.data)
    rec['stats_runeword'] = [x for x in rec['stats_runeword'] if x['id'] != 99]      # FHR gone
    bad = C.build_blob(rec, kids, win.data, preserve_stat_order=True)
    T.check(any(f.rule == 'missing-stat' for f in mxl_legit.check_item(bad)), 'the missing FHR is found')
    res = LC.convert(bad, win.data)
    T.check(res.blob is not None, f'converted: {res.changes}')
    T.eq(mxl_legit.impossible(mxl_legit.check_item(res.blob)), [], 'complete again')
    fhr = [x['value'] for x in C.decode_blob(res.blob, win.data)[0]['stats_runeword'] if x['id'] == 99]
    T.eq(fhr, [55], 'FHR 55 back')

T.main(globals())
