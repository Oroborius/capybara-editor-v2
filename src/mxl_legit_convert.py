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


def _add_required(v, item, rec, data, changes):
    """Completeness: the stats the game always puts on a unique / set item / runeword (d2bt required_stats) that
    the item lacks are added at the top of their range - to the runeword list for a runeword (its T1 mods), else
    to the item's own list (items from older editors: Enigma without its defense, Spirit without FHR...)."""
    try:
        from d2bt.itemgen import required_stats
        if item.runeword is not None:
            req, target = required_stats(v, 'runeword', item.runeword, item.code, item.ilvl), 'stats_runeword'
        elif item.quality in (5, 7):
            req, target = required_stats(v, item.quality, item.quality_id, item.code, item.ilvl), 'stats'
        else:
            return
    except Exception:
        return
    stats = list(rec.get(target) or [])
    have = {(s['id'], s.get('param')) for s in stats}
    ids = {s['id'] for s in stats}
    for sid, param, lo, hi, source, display in req:
        if sid >= len(data.isc) or not data.isc[sid]['bits']:
            continue
        c = data.isc[sid]
        key_param = param if c['param'] else None
        if (sid, key_param) in have or (param is None and sid in ids):     # random class / skill: any layer
            continue
        value = ((max(lo, hi) + c['add']) & ((1 << c['bits']) - 1)) - c['add']
        stats.append(dict(id=sid, param=key_param, value=value))
        have.add((sid, key_param))
        ids.add(sid)
        changes.append(f'added {display or sid}')
    rec[target] = stats


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
    cache = {}

    def legal_at(lv):
        if lv not in cache:
            legal = legal_affixes(v, rec['code'].strip(), lv, q)
            cache[lv] = {('magicprefix', r['id']) for r in legal['prefix']} \
                | {('magicsuffix', r['id']) for r in legal['suffix']} | {('automagic', r['id']) for r in legal['automagic']}
        return cache[lv]

    legal_ids = legal_at(rec['ilvl'])

    def ok(table, row, group_used=(), idx=None, ids=None):
        if not row or (table, idx) not in (legal_ids if ids is None else ids):
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
    have = set(current)
    unexplained = set(have)                         # stats no good affix of the item accounts for
    for table, get, set_ in slots:
        idx = get()
        if idx and not any(idx == b[3] and table == b[0] for b in bad):
            row = (v.affixes.get((table, idx)) or (None, None))[1]
            if row is not None:
                unexplained -= set(_sig(v, row))
    def covering(table, row, others):
        """The allowed row of `table` that carries most of the item's unexplained stats (not those another bad
        slot stands for), at the item's level first, else at the lowest level it rolls at (the item level is
        raised to it). None when no row carries any."""
        nonlocal legal_ids
        best = None
        for (t, i), (_t, cand) in v.affixes.items():
            if t != table or not ok(table, cand, seen, i, legal_at(99)):
                continue
            keys = set(_sig(v, cand))
            covered = keys & (unexplained - others)
            if not covered or not keys <= have:
                continue
            dist = 0
            for key, iv in v._bounds(_mods(cand)).items():
                lo, hi = sorted((iv.lo, iv.hi))
                val = current.get(key, 0)
                dist += max(0, lo - val, val - hi)
            needs = 0 if (t, i) in legal_ids else 1
            score = (-len(covered), needs, cand.get('name') != (row or {}).get('name'), dist,
                     abs(to_int(cand.get('level')) - to_int((row or {}).get('level'))), -i)
            if best is None or score < best[0]:
                best = (score, i, cand)
        if best and (table, best[1]) not in legal_ids:   # the item level it rolls at (a 5% all-res charm: 44+)
            lv = next((lv for lv in range(rec['ilvl'] + 1, 100) if (table, best[1]) in legal_at(lv)), None)
            if lv is None:
                return None
            changes.append(f"item level {rec['ilvl']} -> {lv}")
            rec['ilvl'] = lv
            legal_ids = legal_at(lv)
        return best

    for table, get, set_, idx, row in bad:
        want = _sig(v, row) if row else frozenset()
        # first: the allowed row that carries the item's own stats (a charm's four 5% resists under a fire-resist
        # row are the all-resistances affix, not fire resist plus three stats to drop)
        others = set()
        for b in bad:
            if b[3] != idx or b[0] != table:
                others |= set(_sig(v, b[4])) if b[4] else set()
        best = covering(table, row, others)
        if best:
            unexplained -= set(_sig(v, best[2]))
        elif want:
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

    if rec['quality'] in ('magic', 'rare', 'crafted') and unexplained:
        for table, get, set_ in slots:              # empty affix slots: rows for the stats nothing explains
            if not unexplained:
                break
            if table == 'automagic' or get():
                continue
            best = covering(table, None, set())
            if best:
                set_(best[1])
                g = to_int(best[2].get('group'))
                if g:
                    seen.add(g)
                unexplained -= set(_sig(v, best[2]))
                changes.append(f"{best[2]['name']} ({_where(v, best[2])}) added for its stats")


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


def _fix_superior(v, rec, kids, data, changes):
    """A superior variant the base cannot have (other editors write 0 on any base): the variant of this base whose
    stats the item carries, else normal quality (a runeword on a normal base)."""
    from mxl_creator import build_blob
    old = rec.get('subquality')
    best = None
    for q in range(len(v.superior or ())):
        rec['subquality'] = q
        try:
            found = findings_of(build_blob(rec, kids, data, preserve_stat_order=True))
        except Exception:
            continue
        bad = mxl_legit.impossible(found)
        if not any(f.rule == 'quality' for f in bad) and (best is None or len(bad) < best[0]):
            best = (len(bad), q)
    if best is not None and best[0] == 0:
        rec['subquality'] = best[1]
        changes.append(f'superior variant {old} -> {best[1]}')
        return
    rec['subquality'] = old
    rec['quality'] = 'normal'
    rec.pop('subquality', None)
    changes.append('superior -> normal (no superior variant of this base fits)')


def _entries(rec):
    for key in ('stats', 'stats_runeword', *(f'set_stats_{i}' for i in range(5))):
        for s in rec.get(key, ()):
            yield key, s


def _fix_stats(v, rec, findings, changes, repacked=None):
    for f in findings:
        if f.rule != 'stat':
            continue
        m = _RANGE.match(f.detail)
        if m and m.group(1) == 'item_charged_skill':     # charges / capacity the row fixes: full at that capacity
            val, hi = int(m.group(2)), int(m.group(4))
            hit = next((s for _k, s in _entries(rec) if s['id'] == 204 and s['value'] == val), None)
            if hit is not None:
                hit['value'] = hi
                changes.append(f'charges {val >> 8}/{val & 255} -> {hi >> 8}/{hi & 255}')
            continue
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
    if rules & {'affix-type', 'affix-level', 'affix-quality', 'affix-group', 'affix-id', 'affix-count'} or 'item-level' in rules:
        _fix_affixes(v, rec, base, changes)
    if rec['quality'] == 'superior' and any(f.rule == 'quality' and 'superior variant cannot spawn' in f.detail
                                            for f in before):
        _fix_superior(v, rec, kids, data, changes)
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
    if 'missing-stat' in rules:                      # after the repack: present stats are compared as stored
        _add_required(v, item, rec, data, changes)
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
