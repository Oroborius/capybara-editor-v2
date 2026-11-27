"""'Convert to Strict Legit': the closest item the game can really make, found with the dev kit validator's own tables
(mxl_legit, package d2bt, never modified). Impossible affixes become the allowed row with the same stat kinds and the
closest ranges (or are dropped), stat values are clamped into their legal range, extra sockets / ethereal / item level /
defense / rare-name fragments are fixed. Identity, runeword and craft problems are never guessed: they are reported.
The result is applied only when it removes impossible findings. No Tk except in the menu helpers."""
import re
from dataclasses import dataclass, field

import mxl_legit

LABEL = 'Convert to Strict Legit'
_RANGE = re.compile(r'^(.*) (-?\d+) outside (-?\d+)\.\.(-?\d+)$')
_NONE = re.compile(r'^(.*) (-?\d+) has no allowed source$')
_REPEAT = re.compile(r'^repeated (.*) \[(-?\d+)\]$')
_SOCK = re.compile(r'max (\d+)$')
_DEF = re.compile(r'outside (-?\d+)\.\.(-?\d+)$')


@dataclass
class Result:
    blob: bytes
    changes: list = field(default_factory=list)
    remaining: list = field(default_factory=list)       # impossible findings left
    before: int = 0
    after: int = 0

    @property
    def applied(self):
        return self.blob is not None


def _parsed(blob):
    """-> (first parsed item, findings) read by the dev kit's own item reader."""
    from d2bt.lint.savescan import Usage, _item
    v = mxl_legit._validator()
    buf, items, pos = bytes(blob), [], 0
    pos, flags, nsock = _item(buf, pos, v.save_tables, Usage(''), items)
    for _ in range(nsock if flags >> 11 & 1 else 0):
        pos, _f, _n = _item(buf, pos, v.save_tables, Usage(''), items[-1].children)
    return items[0], list(v.validate_item(items[0]))


def findings_of(blob):
    try:
        return mxl_legit.check_item(blob)
    except mxl_legit.Unavailable:
        return []


def needs_conversion(blob):
    """Legit mode on and the item has impossible findings."""
    if not mxl_legit.enabled():
        return False
    try:
        return bool(_fixable(findings_of(blob)))
    except Exception:
        return False


def _fixable(found):
    """Findings Convert works on: every impossible one, and the base defense outside its range (suspicious: an
    ethereal item stored without its x1.5 - old editors)."""
    return [f for f in found if f.severity == mxl_legit.IMPOSSIBLE or f.rule == 'defense']


def _where(v, row):
    for k, t in row.items():
        if k.startswith('itype') and t:
            return v.item_types.get(t, {}).get('itemtype') or t
    return '?'


def _mods(row):
    from d2bt.legit import properties
    return list(properties(row, 'mod{}code mod{}param mod{}min mod{}max', range(1, 4)))


def _sig(v, row):
    return frozenset(v._bounds(_mods(row)))


def _stat_name(v, sid):
    return v.item_tables.s(sid, 'stat') or f'stat {sid}'


def _value(rec):
    out = {}
    for s in rec.get('stats', ()):
        key = (s['id'], s.get('param') or 0)
        out[key] = out.get(key, 0) + s['value']
    return out


def _slots(rec):
    """[(table, get, set)] of the affix fields of a record."""
    out = []
    q = rec['quality']
    if q == 'magic':
        for field_, table in (('prefix', 'magicprefix'), ('suffix', 'magicsuffix')):
            out.append((table, lambda f=field_: rec.get(f) or 0, lambda x, f=field_: rec.__setitem__(f, x)))
    elif q in ('rare', 'crafted'):
        for k in range(6):
            table = 'magicprefix' if k % 2 == 0 else 'magicsuffix'
            out.append((table, lambda k=k: rec['rare_affixes'][k] or 0,
                        lambda x, k=k: rec['rare_affixes'].__setitem__(k, x or None)))
    return out


def _fix_affixes(v, rec, base, changes):
    from d2bt.itemgen import legal_affixes
    from d2bt.tooltip.data import to_int
    q = {'magic': 4, 'rare': 6, 'crafted': 8}.get(rec['quality'], 2)
    legal = legal_affixes(v, rec['code'].strip(), rec['ilvl'], q)
    legal_ids = {('magicprefix', r['id']) for r in legal['prefix']} | {('magicsuffix', r['id']) for r in legal['suffix']} \
        | {('automagic', r['id']) for r in legal['automagic']}

    def ok(table, row, group_used=(), idx=None):
        if not row or (table, idx) not in legal_ids:
            return False
        g = to_int(row.get('group'))
        return not (g and table != 'automagic' and g in group_used)

    slots = _slots(rec)
    if rec.get('auto_affix') is not None:
        slots.append(('automagic', lambda: rec.get('auto_affix') or 0,
                      lambda x: rec.__setitem__('auto_affix', x or None)))
    seen, bad = set(), []
    for table, get, set_ in slots:
        idx = get()
        if not idx:
            continue
        row = (v.affixes.get((table, idx)) or (None, None))[1]
        if row is not None and ok(table, row, seen, idx):
            g = to_int(row.get('group'))
            if g and table != 'automagic':
                seen.add(g)
        else:
            bad.append((table, get, set_, idx, row))
    current = _value(rec)
    for table, get, set_, idx, row in bad:
        want = _sig(v, row) if row else frozenset()
        best = None
        if want:
            for (t, i), (_t, cand) in v.affixes.items():
                if t != table or not ok(table, cand, seen, i) or _sig(v, cand) != want:
                    continue
                dist = 0
                for key, iv in v._bounds(_mods(cand)).items():
                    lo, hi = sorted((iv.lo, iv.hi))
                    val = current.get(key, 0)
                    dist += max(0, lo - val, val - hi)
                score = (cand.get('name') != (row or {}).get('name'), dist, abs(to_int(cand.get('level')) - to_int((row or {}).get('level'))), -i)
                if best is None or score < best[0]:
                    best = (score, i, cand)
        old = row['name'] if row and row.get('name') else f'#{idx}'
        old_where = _where(v, row) if row else '?'
        if best:
            set_(best[1])
            g = to_int(best[2].get('group'))
            if g and table != 'automagic':
                seen.add(g)
            changes.append(f"{old} ({old_where}) -> {best[2]['name']} ({_where(v, best[2])})")
        else:
            set_(0)
            changes.append(f'{old} ({old_where}) dropped (no allowed row has its stats)')


def _fix_rare_name(v, rec, base, changes):
    from d2bt.legit import allowed
    types = v.save_tables.ancestors(base.get('type')) | v.save_tables.ancestors(base.get('type2'))
    suffix_count = len(v.rare_suffixes)
    names = list(rec['rare_names'])
    for pos, (rows, offset) in enumerate(((v.rare_prefixes, suffix_count + 1), (v.rare_suffixes, 1))):
        cur = names[pos]
        if pos == 1 and cur == 0:
            continue
        i = cur - offset
        if 0 <= i < len(rows) and allowed(types, rows[i]):
            continue
        okay = [j + offset for j, r in enumerate(rows) if allowed(types, r) and j + offset <= 255]
        if okay:
            new = min(okay, key=lambda x: abs(x - cur))
            names[pos] = new
            changes.append(f'rare name fragment {cur} -> {new}')
    rec['rare_names'] = tuple(names)


def _entries(rec):
    for key in ('stats', 'stats_runeword', *(f'set_stats_{i}' for i in range(5))):
        for s in rec.get(key, ()):
            yield key, s


def _fix_stats(v, rec, findings, changes, repacked=None):
    for f in findings:
        if f.rule != 'stat':
            continue
        m = _RANGE.match(f.detail)
        if m:
            name, val, lo, hi = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
            hit = next((s for _k, s in _entries(rec) if s['value'] == val and _stat_name(v, s['id']) == name
                        and s['id'] != 204), None)
            if hit is not None:
                hit['value'] = min(max(val, lo), hi)
                changes.append(f'{name} {val} -> {hit["value"]}')
            continue
        m = _NONE.match(f.detail)
        if m:
            name, val = m.group(1), int(m.group(2))
            if name == 'item_addskill_tab' and repacked is not None:
                hit = next((s for _k, s in _entries(rec) if s['id'] == 188 and s['value'] == val
                            and id(s) not in repacked and s.get('param') is not None), None)
                if hit is not None:                   # saved as the sheet's class * 3 + tab, not the layer class << 3 | tab
                    repacked.add(id(hit))
                    new_param = ((hit['param'] // 3) << 3) | (hit['param'] % 3)
                    changes.append(f'skill tab {hit["param"]} -> layer {new_param}')
                    hit['param'] = new_param
                    continue
            for key in ('stats', 'stats_runeword', *(f'set_stats_{i}' for i in range(5))):
                rows = rec.get(key) or []
                hit = next((s for s in rows if s['value'] == val and _stat_name(v, s['id']) == name), None)
                if hit is not None:
                    rows.remove(hit)
                    changes.append(f'{name} {val} removed (no allowed source)')
                    break
            continue
        m = _REPEAT.match(f.detail)
        if m:
            name, layer = m.group(1), int(m.group(2))
            for key in ('stats', 'stats_runeword', *(f'set_stats_{i}' for i in range(5))):
                rows = [s for s in rec.get(key) or [] if _stat_name(v, s['id']) == name
                        and (s.get('param') or 0) == layer]
                if len(rows) > 1:
                    rec[key].remove(rows[-1])
                    changes.append(f'repeated {name} removed')
                    break


def convert(blob, data):
    """-> Result. result.blob is the converted blob, or None when nothing could be improved."""
    from mxl_creator import (FLAG_ETHEREAL, FLAG_SOCKETED, build_blob, decode_blob)
    blob = bytes(blob)
    v = mxl_legit._validator()
    try:
        item, found = _parsed(blob)
        rec, kids = decode_blob(blob, data)       # (stats the editor does not know: hacked, left as they are)
    except Exception:
        return Result(None, [], [], 0, 0)
    before = mxl_legit.impossible(found)
    base = v.bases.get(rec['code'].strip(), (None, None))[1]
    if base is None or not _fixable(found):
        return Result(None, [], before, len(before), len(before))
    changes = []
    rules = {f.rule for f in before}

    need = [int(m.group(1)) for f in before if f.rule == 'identity-level'
            for m in [re.search(r'requires item level (\d+)', f.detail)] if m]
    top = max([rec['ilvl'], *need]) if need else rec['ilvl']
    if not 1 <= top <= 110 or top != rec['ilvl']:
        new_level = min(max(top, 1), 110)           # the dev kit's ilvl_range: 1..110, a set / unique row's lvl least
        changes.append(f"item level {rec['ilvl']} -> {new_level}")
        rec['ilvl'] = new_level
    if 'ethereal' in rules and rec['flags'] & FLAG_ETHEREAL and any(
            f.rule == 'ethereal' and 'cannot be ethereal' in f.detail for f in before):
        rec['flags'] &= ~FLAG_ETHEREAL
        changes.append('ethereal cleared')
    if 'rare-name' in rules and rec.get('rare_names') and rec['quality'] in ('rare', 'crafted'):
        _fix_rare_name(v, rec, base, changes)
    if rules & {'affix-type', 'affix-level', 'affix-quality', 'affix-group', 'affix-id'} or 'item-level' in rules:
        _fix_affixes(v, rec, base, changes)
    for f in before:
        m = f.rule == 'sockets' and _SOCK.search(f.detail)
        if m and rec.get('sockets', 0) > int(m.group(1)):
            top = int(m.group(1))
            changes.append(f"sockets {rec['sockets']} -> {top}")
            rec['sockets'] = top
            kids = kids[:top]
            rec['socketed_count'] = len(kids)
            if not top:
                rec['flags'] &= ~FLAG_SOCKETED
                rec.pop('sockets', None)
            break

    def rebuild():
        return build_blob(rec, kids, data, preserve_stat_order=True)

    new = rebuild()
    _item2, found = _parsed(new)
    seen_tabs = set()
    _fix_stats(v, rec, found, changes, seen_tabs)
    new = rebuild()
    _item2, found = _parsed(new)
    if seen_tabs:                                    # a repacked skill tab that is still refused: removed
        _fix_stats(v, rec, found, changes, seen_tabs)
        new = rebuild()
        _item2, found = _parsed(new)
    for f in found:
        m = f.rule == 'defense' and _DEF.search(f.detail)
        if m and rec.get('defense') is not None:
            lo, hi = int(m.group(1)), int(m.group(2))
            cur = rec['defense']
            fixed = cur
            if rec['flags'] & FLAG_ETHEREAL and cur < lo and lo <= cur * 3 // 2:
                fixed = cur * 3 // 2                     # ethereal stored without its x1.5 (old editors)
            rec['defense'] = min(max(fixed, lo), hi)
            changes.append(f"defense {cur} -> {rec['defense']}")
    new = rebuild()
    from mxl_creator import renew_item_ids
    new = bytes(renew_item_ids(new, data))               # a fresh item id: no copy of another item's id
    found_after = findings_of(new)
    after = mxl_legit.impossible(found_after)
    better = len(after) < len(before) or len(_fixable(found_after)) < len(_fixable(found))
    if len(after) > len(before) or not better or new == blob:
        return Result(None, [], after if len(after) < len(before) else before, len(before), len(after))
    return Result(new, changes, after, len(before), len(after))


def report(res):
    if res.blob is None:
        text = 'Nothing could be converted automatically.'
    else:
        text = 'Changed: ' + '; '.join(res.changes) + '.'
    if res.remaining:
        text += f'\n\nStill impossible ({len(res.remaining)}):\n' + mxl_legit.summary(res.remaining)
    elif res.blob is not None:
        text += '\n\nThe item is now legit.'
    return text


def convert_entry(win, entry):
    """Menu action: convert the character's item and save through the normal (guarded) path."""
    from tkinter import messagebox
    from mxl_vanilla_he_items import ITEM_ERRORS, replace_item
    try:
        before = bytes(entry.blob)
        res = convert(before, win.data)
        if res.blob is not None:
            replace_item(win, entry, before, res.blob, LABEL)
    except ITEM_ERRORS as error:
        win.set_status(str(error), True)
        return None
    messagebox.showinfo(LABEL, report(res), parent=win.top)
    return res


def add_menu_entry(win, menu, entry):
    """Adds the command when Legit mode is on and the item is impossible."""
    if entry is None or getattr(win.ch, 'old', False) or not mxl_legit.enabled():
        return False
    try:
        if not needs_conversion(bytes(entry.blob)):
            return False
    except Exception:
        return False
    menu.add_command(label=LABEL, command=lambda: convert_entry(win, entry))
    return True
