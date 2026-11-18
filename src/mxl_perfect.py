"""'Make perfect': every rolled value of an item set to the top of its range, from the right-click menu.

It replaces the collector's value sliders (the "Value editing" switch of the main bar is gone): the same
ranges the sliders used - mxl_edit.edit_groups: the item's affix / unique / set rolls, the Superior bonus,
the base defense, the runeword's rolls and the rolls of socketed jewels - are all raised to their maximum
in one write. The entry sits in 'Specific editing functions' and only shows for an item that has such
rolls.

Mystic orbs. An orb adds a fixed amount to a stat, on top of what the item rolled, so the stored value
can be above the roll's range. The orbs are not recorded on the item: they are told from the value itself.
For a value above its range, the orb amounts known for that stat (mysticorbs table, at most the allowed
number of each orb) are tried: the smallest orb total that brings the rest back into the range is taken as
the orb part, the rest as the roll. The roll goes to its maximum and the orb part is kept on top. When
several orb totals fit (a wide range and a small orb), the smallest is used - the result never invents
orb value and never lowers the stat. A value that no orb combination explains (a hand-edited stat) and a
value below its range are left exactly as they are, and counted in the status line.

Writes: a stash item is replaced at its place through mxl_save.edit_stash (verification, backup); a
character item keeps its place and size, so its bytes are swapped in the entry and the character is saved
by the character editor's own save.
"""
import mxl_edit
from mxl_save import read_file, item_blob, blob_item, edit_stash, set_stat, EditError
from mxl_format import FormatError
from mxl_lang import T

MAX_ORB_TOTALS = 4096          # guard for the subset sums of one stat (a handful of orbs in practice)


def _t(key, default, **fields):
    return T('pf.' + key, default, **fields)


# ---------------------------------------------------------------------------------------------- mystic orbs
def orb_amounts(cr):
    """{(stat id, param): [(amount, max orbs of that kind per item)]} from the mysticorbs table (fixed
    amounts only; an orb with a ranged effect cannot be told apart from a roll and is left out)."""
    cached = getattr(cr, '_perfect_orbs', None)
    if cached is not None:
        return cached
    from mxl_creator import Mod
    out = {}
    try:
        table = cr._orb_table()
    except Exception:
        table = {}
    for o in table.values():
        for prop, param, lo, hi in o['mods']:
            if lo != hi:
                continue
            try:
                stats = Mod('orb', prop, param, lo, hi, cr.data).stats(cr.data)
            except Exception:
                continue
            for s in stats:
                if isinstance(s, dict) and s.get('value'):
                    out.setdefault((s['id'], s.get('param')), []).append((s['value'], max(1, o['max'])))
    cr._perfect_orbs = out
    return out


def orb_part(value, lo, hi, amounts):
    """The smallest orb total T > 0 with lo <= value - T <= hi, or None when no orb combination fits."""
    totals = {0}
    for amount, count in amounts:
        if amount <= 0:
            continue
        step = set()
        for k in range(1, count + 1):
            step.update(t + amount * k for t in totals if t + amount * k <= value - lo)
        totals |= step
        if len(totals) > MAX_ORB_TOTALS:
            break
    fits = [t for t in totals if t > 0 and lo <= value - t <= hi]
    return min(fits) if fits else None


# ---------------------------------------------------------------------------------------------- the plan
def plan(it, data, cr, char=None):
    """What 'Make perfect' would do to the item `it` (a parsed item, socketed items included):
    dict(changes=[(field, new value)], perfect=n, orbs=n, skipped=n, total=n). total = number of rolls."""
    out = dict(changes=[], perfect=0, orbs=0, skipped=0, total=0)
    try:
        groups = mxl_edit.edit_groups(it, data, char) or []
    except Exception:              # an item the collector cannot describe: nothing offered
        return out
    orbs = None
    for g in groups:
        for f in g['fields']:
            lo, hi, v = f['lo'], f['hi'], f['value']
            if f.get('choices'):
                hi = max(f['choices'])
            out['total'] += 1
            if lo <= v <= hi:
                target = hi
            elif v > hi and f['edit'].get('kind') == 'stat':
                if orbs is None:
                    orbs = orb_amounts(cr)
                part = orb_part(v, lo, hi, orbs.get((f['edit'].get('stat'), f['edit'].get('param')), ()))
                if part is None:
                    out['skipped'] += 1
                    continue
                out['orbs'] += 1
                target = hi + part
            else:
                out['skipped'] += 1
                continue
            if target == v:
                out['perfect'] += 1
            else:
                out['changes'].append((f, target))
    return out


def _find(it, offset):
    for cand in [it] + list(it.get('socketed') or ()):
        if cand.get('_offset') == offset:
            return cand
    return None


def perfect_blob(blob, data, cr, char=None):
    """(new bytes, plan) for the bytes of one item and its socketed items; sizes never change. The item is
    read again after each value, so every write starts from what is really stored (linked stats follow
    through the collector's own set_stat)."""
    buf = bytearray(blob)
    first = plan(blob_item(bytes(buf), data), data, cr, char)
    defense = None
    for f, target in first['changes']:
        ed = f['edit']
        it = blob_item(bytes(buf), data)
        tgt = _find(it, ed.get('offset'))
        if tgt is None:
            raise EditError(_t('err.lost', 'the item changed while it was being rewritten'))
        if ed.get('kind') == 'defense':
            defense = (ed.get('offset'), target)
            continue
        set_stat(buf, tgt, ed['stat'], target, data, True, ed.get('stat_list') or 'stats', ed.get('param'))
    if defense is not None:
        buf = _set_defense(buf, data, *defense)
    return bytes(buf), first


def _set_defense(buf, data, offset, value):
    """Base defense through the item's own decode -> encode (same size: the field has a fixed width)."""
    from mxl_creator import decode_item, encode_item
    rec, size = decode_item(bytes(buf[offset:]), data)
    rec['defense'] = value
    new = encode_item(rec, data)
    if len(new) != size:
        raise EditError(_t('err.size', 'the defense value does not fit'))
    buf[offset:offset + size] = new
    return buf


# ---------------------------------------------------------------------------------------------- the menu
def _summary(p):
    bits = [_t('done', '{n} value(s) raised to the maximum', n=len(p['changes']))]
    if p['orbs']:
        bits.append(_t('done.orbs', '{n} with a mystic orb bonus kept on top', n=p['orbs']))
    if p['skipped']:
        bits.append(_t('done.skipped', '{n} outside its range left as it is', n=p['skipped']))
    return ', '.join(bits)


def add_menu(sp, holder, it=None, win=None, e=None, name=''):
    """Adds 'Make perfect' to the 'Specific editing functions' submenu `sp` when the item has rolls.
    Stash: holder = the app, it = the item. Character window: win, e = its entry."""
    app = getattr(holder, 'app', holder)
    data = holder.data
    try:
        import mxl_rc_menu as RC
        cr = RC._creator_for(holder)
        blob = item_blob(read_file(holder.path), it) if win is None else e.blob
        p = plan(blob_item(bytes(blob), data), data, cr)
    except Exception:              # the menu must open whatever the item is
        return
    if not p['total']:
        return
    if not p['changes']:
        label = _t('menu.already', 'Make perfect (already perfect)') if not p['skipped'] else \
            _t('menu.nothing', 'Make perfect (nothing to raise: {n} value(s) outside their range)', n=p['skipped'])
        sp.add_separator()
        sp.add_command(label=label, state='disabled')
        return
    sp.add_separator()
    sp.add_command(label=_t('menu', 'Make perfect ({n} of {m} rolls below the maximum)',
                            n=len(p['changes']), m=p['total']),
                   command=lambda: make_perfect(holder, it, win, e, name))


def make_perfect(holder, it=None, win=None, e=None, name=''):
    """Writes the item with every roll at its maximum. True when something was written."""
    import mxl_rc_menu as RC
    data = holder.data
    cr = RC._creator_for(holder)
    if win is None:
        app = holder
        try:
            blob = RC._now(app, it)[2]         # the item as the file holds it (refused from an out-of-date view)
            new, p = perfect_blob(blob, data, cr)
            if not p['changes']:
                return False
            bak = edit_stash(app.path, data, remove=[it['_offset']],
                             insert=[(it['page'], it['x'], it['y'], new)], backup=app.needs_backup(app.path))
        except (EditError, FormatError, OSError, ValueError, KeyError) as err:
            RC._status(app, str(err), True)
            return False
        RC._record_stash_replace(app, it, blob, name or RC._item_name(app, it, None))     # Ctrl+Z
        app.backup_made(app.path, bak)
        RC._selected(app, it['page'], it['x'], it['y'])
        RC._status(app, f'{name}: {_summary(p)}' if name else _summary(p))
        return True
    from mxl_char import CharError
    path, before = win.ch.path, bytes(win.ch.raw)     # what is on disk: save() refuses anything else
    try:
        # same size, same place: the entry's own bytes are swapped (no remove -> place, whose slot rules
        # would refuse some items that are already worn, e.g. a mercenary's gloves / belt / boots)
        new, p = perfect_blob(bytes(e.blob), data, cr)
        if not p['changes']:
            return False
        e.blob = new
        fresh = blob_item(new, data)           # the entry's parsed copy shows the new values at the next redraw
        for dst, src in [(e.it, fresh)] + list(zip(e.it.get('socketed') or (), fresh.get('socketed') or ())):
            for k in ('stats', 'stats_runeword', 'defense'):
                if k in src and dst is not None:
                    dst[k] = src[k]
    except (CharError, EditError, FormatError, OSError, ValueError, KeyError) as err:
        win.set_status(str(err), True)
        win.reload()
        return False
    msg = f'{name}: {_summary(p)}' if name else _summary(p)
    if not win.save(msg):
        win.set_status(T('ch.err.not_saved', 'character not saved'), True)
        win.reload()
        return False
    RC._record_char_write(win, path, before, name or RC._item_name(win, None, e))     # Ctrl+Z
    return True
