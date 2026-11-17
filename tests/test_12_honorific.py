"""The honorific sample (quality 9 item on a character, MXL_TEST_SAVE_DIR2): parses, shows a tooltip, survives a
no-op character rebuild byte for byte. The upstream reader crashed on it ('JM' expected)."""
import glob
import os
import re

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves', 'saves2')
PLACEHOLDER = re.compile(r'skill #|stat #|class #|%\+?[ds]|\bNone\b|POLAR BUFFALO')


def sample():
    folder = T.fresh_saves(2)
    return sorted(glob.glob(os.path.join(folder, '*.d2s')))[0]


def honorifics(E, ch):
    return [e for merc in (False, True) if not merc or ch.merc_items is not None
            for e in ch.entries(merc) if e.it.get('quality') == 'tempered']


@T.test
def sample_parses_with_honorific_item():
    E = T.engine()
    p = sample()
    ch = E.MC.Character(p, E.data)
    hon = honorifics(E, ch)
    T.check(len(hon) >= 1, f'no quality 9 ("tempered") item among the {len(ch.items)} items of {os.path.basename(p)}')
    for e in hon:
        it = e.it
        T.check(isinstance(it.get('rare_names'), (list, tuple)) and len(it['rare_names']) == 2,
                f'{it["code"]!r}: honorific item without its two name words: {it.get("rare_names")!r}')
        ids = {s['id'] for s in it.get('stats') or ()}
        T.check(E.C.HONORIFIC_STAT in ids, f'{it["code"]!r}: stat {E.C.HONORIFIC_STAT} (orb effects doubled) missing: {sorted(ids)}')
        T.check(E.rules.rare_name(it, E.data), f'{it["code"]!r}: no name')


@T.test
def honorific_tooltip_renders():
    E = T.engine()
    ch = E.MC.Character(sample(), E.data)
    hon = honorifics(E, ch)
    T.check(hon, 'no honorific item')
    for e in hon:
        lines = [''.join(t for _c, t in line) for line in E.tip.item_tooltip(e.it, E.data)]
        T.check(len(lines) >= 3, f'tooltip has {len(lines)} lines')
        T.check(lines and lines[0].strip(), 'tooltip starts with an empty line')
        for ln in lines:
            T.check(not PLACEHOLDER.search(ln), f'placeholder in the tooltip line {ln.strip()[:80]!r}')


@T.test
def honorific_noop_rebuild_identical():
    E = T.engine()
    p = sample()
    raw = T.read(p)
    ch = E.MC.Character(p, E.data)
    T.check(ch.build() == raw, 'no-op build of the honorific sample differs')
    ch.save(backup=False)
    T.check(T.read(p) == raw, 'no-op save of the honorific sample changed the file')
    for problem in T.d2s_header_ok(raw):
        T.check(False, f'sample file: {problem}')


@T.test
def honorific_item_reencodes_identically():
    E = T.engine()
    ch = E.MC.Character(sample(), E.data)
    for e in honorifics(E, ch):
        blob = bytes(e.blob)
        rec, size = E.C.decode_item(blob, E.data)
        T.check(E.C.encode_item(rec, E.data) == blob[:size], 'decode -> encode of the honorific item differs')
        spec = E.cr.spec_from_item(e.it)
        T.eq(spec['quality'], 'tempered', 'quality of the edit spec')
        rec2 = E.C.decode_item(bytes(E.cr.build(spec)[0]), E.data)[0]
        T.eq(T.stats_of(rec2), T.stats_of(rec), 'stats after spec_from_item -> build')
        T.eq(rec2.get('rare_names'), rec.get('rare_names'), 'name words after spec_from_item -> build')


# BUG (known, WORKLOG W14 "no-op Replace through the creator's edit mode"): the creator rebuilds an edited item
# from a spec, and the spec does not carry everything. On the game's own honorific sample the no-op edit path
# repairs the item (durability 166 -> 183) and drops header flag 0x2000 (FLAG_NEW).
@T.test
def honorific_noop_edit_keeps_every_field():
    E = T.engine()
    ch = E.MC.Character(sample(), E.data)
    hon = honorifics(E, ch)
    T.check(hon, 'no honorific item')
    where = ('id', 'image', 'x', 'y', 'panel', 'location', 'equipped')      # a rebuilt item is placed anew
    for e in hon:
        rec = E.C.decode_item(bytes(e.blob), E.data)[0]
        rec2 = E.C.decode_item(bytes(E.cr.build(E.cr.spec_from_item(e.it))[0]), E.data)[0]
        for k in sorted(set(rec) | set(rec2)):
            if k in where or k == 'stats' and T.stats_of(rec) == T.stats_of(rec2):
                continue
            T.eq(rec2.get(k), rec.get(k), f'field {k!r} after a no-op edit')


@T.test
def every_sample2_file_reads():
    """All the files of the second sample: stashes parse, every character (backups too) rebuilds identically."""
    E = T.engine()
    folder = os.path.dirname(sample())
    n = 0
    for p in sorted(glob.glob(os.path.join(folder, '*'))):
        name = os.path.basename(p)
        if '.d2s' in name:
            T.check(E.MC.Character(p, E.data).build() == T.read(p), f'{name}: no-op build differs')
            n += 1
        elif '.stash' in name or name.endswith('.shared'):
            E.save.parse_stash(p, E.data)
            n += 1
    T.check(n >= 2, f'only {n} files read')


T.main(globals())
