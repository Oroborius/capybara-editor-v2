"""The Character tab's Stats page drawn like the game's own character screen (Median XL Sigma stat-screen panel),
with the stored values editable in place.

Parts:
- StatEditMixin: the editing controller of CharacterWindow. Every edit of a stat-screen value is an operation
  replayed on a scratch copy of the character (what the page shows) and, on SAVE, on the character itself
  through mxl_char's field engine. Used by the art page and by the grey Hero-Editor page alike.
- char_totals: sums of the item stats that count in game (equipped items with sockets, charms in the inventory,
  partial set bonuses); screen_table: the game's own definition of its stat screen (statscreen table).
- GameText: text in the game's own fonts (in memory, baseline kept).
- StatScreen: a canvas showing 512 x 704 panels composed from the game art and scaled to the space of the tab,
  two side by side (an open book) when the width allows. Pages: the game's page 1 (coordinates measured on game
  screenshots), the game's two list pages (drawn from the statscreen table on the art's own second and third
  panel; no screenshot of them exists, see docs/statscreen-ref/notes.md), "All item attributes" (every summed
  stat, read-only) and "Saved values" (the editor's own page: what the save stores and the game screen does not
  show). The arrow buttons walk the page list one page at a time (as an open book too: 1-2, 2-3, 3-4, 4-5, so
  both page numbers count up without a gap and the last page is reached).
"""
import copy
import os
import struct
import tkinter as tk

import mxl_char as MC
from mxl_char import CharError
from mxl_lang import T

PANEL_W, PANEL_H = 512, 704
GOLD = (199, 179, 119)
WHITE = (230, 230, 230)
DIM = (128, 120, 104)            # values the game computes / the editor only sums
SUM = (150, 170, 200)            # the editor's own sums of item stats (not the game's final number)
RED = (255, 77, 77)
BLUE = (105, 105, 255)
YELLOW = (255, 255, 100)
GREEN = (0, 255, 0)
ORANGE = (240, 196, 23)
D2_COLORS = {0: WHITE, 1: RED, 2: GREEN, 3: BLUE, 4: GOLD, 5: (105, 105, 105), 6: (0, 0, 0), 7: (208, 194, 125),
             8: (255, 168, 0), 9: YELLOW, 10: (0, 128, 0), 11: (174, 0, 255), 12: (0, 200, 0)}
SS_COLORS = dict(D2_COLORS)       # the stat-screen table's colour numbers, as measured on page 1
SS_COLORS.update({5: (140, 140, 140), 8: ORANGE, 13: WHITE})
MIN_K = 0.6                      # below this the game fonts are unreadable: the page scrolls instead
TEXT_BOOST = float(os.environ.get('MXL_SS_BOOST', 1.2))   # how much less than the art the texts shrink
SHARPEN = int(os.environ.get('MXL_SS_SHARP', 60))
SPREAD_LOSS = 0.85               # two pages side by side when that costs at most this much of the scale
MAX_K = 2.0
ATTRS = ('strength', 'dexterity', 'vitality', 'energy')
# stats that describe one item, not the character: left out of the totals
ITEM_LOCAL = frozenset({16, 17, 18, 72, 73, 75, 91, 92, 152, 194, 204, 252, 253, 372, 410, 411, 443, 497})
RES_IDS = {'fire_res': 39, 'light_res': 41, 'cold_res': 43, 'poison_res': 45, 'phys_res': 36, 'magic_res': 37}
ATTR_IDS = {'strength': 0, 'energy': 1, 'dexterity': 2, 'vitality': 3}
TEXT_KEYS = ('name', 'copy_as')


# ====================================================================================== controller
class StatEditMixin:
    """Stat-screen editing of CharacterWindow: operations on a scratch copy, applied to the character on SAVE."""

    # ------------------------------------------------------------------ state
    def st_reset(self):
        self.st_ops = []
        self.st_name = None
        self.st_rebuild()

    def st_rebuild(self):
        """The scratch character = the character as loaded + the pending operations."""
        ch = self.ch
        sim = copy.copy(ch)
        sim.head = bytearray(ch.head)
        sim.stats = [list(s) for s in ch.stats]
        kept = []
        for op in getattr(self, 'st_ops', []):
            try:
                self._st_apply(sim, op)
                kept.append(op)
            except CharError:
                pass                      # no longer possible on the reloaded character: dropped
        self.st_ops = kept
        self.st_sim = sim
        self._st_totals = None

    @staticmethod
    def _st_apply(target, op):
        kind = op[0]
        if kind == 'field':
            target.set_field(op[1], op[2])
        elif kind == 'levelup':
            target.set_level(op[1])
        elif kind == 'flag':
            target.set_flag(op[1], op[2])
        elif kind == 'done':
            target.set_difficulties_done(op[1])
        elif kind == 'prog':
            target.set_progression(op[1])
        elif kind == 'matchexp':
            target.match_exp_to_level()
        else:
            raise CharError(str(kind))

    def st_do(self, *op):
        """Applies one operation to the scratch character; False (and the reason in the status line) when the
        engine refuses it."""
        try:
            self._st_apply(self.st_sim, op)
        except CharError as e:
            self.set_bar(str(e), error=True)
            return False
        self.st_ops.append(op)
        self.st_changed()
        return True

    def st_commit(self, ch):
        """Replays the pending operations on the real character (raises CharError)."""
        for op in self.st_ops:
            self._st_apply(ch, op)

    def st_dirty(self):
        sim = getattr(self, 'st_sim', None)
        if sim is None:
            return False
        return bool(self.st_name) or bytes(sim.head) != bytes(self.ch.head) or sim.stats != self.ch.stats

    def st_changed(self):
        scr = getattr(self, 'statscreen', None)
        if scr is not None:
            scr.redraw()
        fn = getattr(self, '_refresh_stats_grey', None)
        if fn is not None and getattr(self, 'sv', None):
            fn()
        self.update_dirty()

    # ------------------------------------------------------------------ values
    def st_cls(self):
        p = getattr(self, 'pending_cls', None)
        return self.ch.cls if p is None else p

    def st_value(self, key):
        sim = self.st_sim
        if key == 'name':
            return self.st_name or self.ch.name
        if key == 'copy_as':
            return self.copy_name.get()
        if key == 'progression':
            return sim.progression
        if key == 'levelup':
            return sim.level
        return sim.field(key)

    def st_range(self, key):
        if key == 'progression':
            return 0, 255
        if key == 'levelup':
            return self.st_sim.level, MC.max_level(self.data, self.st_sim.cls)
        fd = self.st_sim.stat_field(key)
        return fd.min, fd.max

    def st_parse(self, key, text):
        """The typed text as a storable value: (value, None) or (None, message)."""
        text = str(text).strip()
        if key in TEXT_KEYS:
            if key == 'copy_as' and not text:
                return '', None
            try:
                MC.check_name(text)
            except CharError as e:
                return None, str(e)
            return text, None
        label = self.st_label(key)
        try:
            v = int(text.replace(',', '').replace(' ', '').replace(' ', ''))
        except ValueError:
            return None, T('ss.err.number', '{label}: a whole number is expected', label=label)
        lo, hi = self.st_range(key)
        if not lo <= v <= hi:
            return None, T('ss.err.range', '{label}: {lo} to {hi}', label=label, lo=lo, hi=hi)
        return v, None

    def st_label(self, key):
        if key == 'name':
            return T('he.name', 'Name')
        if key == 'copy_as':
            return T('he.copy_as', 'Copy as')
        if key == 'progression':
            return T('ss.progression', 'Progression')
        if key == 'levelup':
            return T('ss.levelup', 'Level up like the game')
        return self.st_sim.stat_field(key).label

    def st_set(self, key, text):
        """Commits a typed value. True when stored (or unchanged), False when refused (status line says why)."""
        v, err = self.st_parse(key, text)
        if err:
            self.set_bar(err, error=True)
            return False
        if key == 'name':
            if v == self.ch.name:
                self.st_name = None
            else:
                folder = os.path.dirname(self.ch.path)
                old = os.path.splitext(os.path.basename(self.ch.path))[0]
                if v.lower() != old.lower() and os.path.exists(os.path.join(folder, v + '.d2s')):
                    self.set_bar(T('ch.err.exists', '{name} already exists', name=v), error=True)
                    return False
                self.st_name = v
            self.st_changed()
            return True
        if key == 'copy_as':
            self.copy_name.set(v)
            self.st_changed()
            return True
        if v == self.st_value(key):
            return True
        if key == 'progression':
            return self.st_do('prog', v)
        if key == 'levelup':
            return self.st_do('levelup', v)
        return self.st_do('field', key, v)

    def st_plus(self, key, n=1, take=False, free=False, everything=False):
        """The + button of an attribute. Like the game: +n to the attribute, -n stat points (everything: all
        the points). free: the stat points are left alone. take: the reverse (a point back)."""
        sim = self.st_sim
        cur, pts = sim.field(key), sim.field('stat_points')
        lo, hi = self.st_range(key)
        plo, phi = self.st_range('stat_points')
        if take:
            n = min(n, cur - lo) if not everything else cur - lo
            if not free:
                n = min(n, phi - pts)
            if n <= 0:
                return False
            ok = self.st_do('field', key, cur - n)
            if ok and not free:
                self.st_do('field', 'stat_points', pts + n)
            return ok
        if not free:
            if pts <= 0:
                self.set_bar(T('ss.no_points', 'No stat points left: Alt+click adds a point anyway, or type the value.'))
                return False
            n = pts if everything else min(n, pts)
        n = min(n, hi - cur)
        if n <= 0:
            return False
        ok = self.st_do('field', key, cur + n)
        if ok and not free:
            self.st_do('field', 'stat_points', pts - n)
        return ok

    def st_flag(self, key, on=None):
        cur = self.st_sim.flags()[key]
        return self.st_do('flag', key, (not cur) if on is None else bool(on))

    def st_done(self, n):
        return self.st_do('done', int(n))

    def st_match_exp(self):
        lo, hi = self.st_sim.exp_range()
        if lo <= self.st_sim.field('experience') <= hi:
            self.set_bar(T('ss.exp_ok', 'The experience already matches level {level}.', level=self.st_sim.level))
            return True
        return self.st_do('matchexp')

    def st_totals(self):
        if getattr(self, '_st_totals', None) is None or self._st_totals[0] is not self.ch.items:
            self._st_totals = (self.ch.items, gear_totals(self.ch, self.data))
        return self._st_totals[1]


# ====================================================================================== item sums
SOURCES = ('equip', 'charms', 'sets')
# "per character level" item stats -> the stat they feed (value * level >> the stat's op_param)
PER_LEVEL = {216: 7, 217: 9, 225: 119, 230: 43, 231: 39, 232: 41, 233: 45, 239: 79, 240: 80, 247: 136, 214: 31,
             203: 25, 404: 329, 405: 330, 406: 331, 407: 332}
PCT_OF = {0: 359, 2: 360, 1: 361, 3: 362, 7: 76, 9: 77}       # "+x %" stats of the attributes, life and mana
FIXED = (6, 7, 8, 9, 10, 11)                                    # character stats stored with 8 fractional bits


def char_totals(ch, data):
    """Sums of the stats of everything the character wears or carries that counts in game:
    - 'equip': the equipped items of the active weapon set, with their runeword and socketed items;
    - 'charms': the charms lying in the inventory (Median XL charms work from there);
    - 'sets': the set bonuses: the lists the set items carry themselves (list n counts with n + 2 pieces worn;
      no set item of Median XL Sigma has one) and the partial (2 to 5 pieces) and full bonuses of the game's sets
      table.
    {'stats': {(id, param): stat dict, value summed over the sources}, 'by': {source: {(id, param): value}},
     'defense': defense of the armour pieces, 'items' / 'charms' / 'set_pieces': counts, 'error': str or None}."""
    out = {'stats': {}, 'by': {k: {} for k in SOURCES}, 'defense': 0, 'items': 0, 'charms': 0, 'set_pieces': 0,
           'set_skipped': 0, 'error': None}

    def add(src, s, scale=1):
        sid, val = s.get('id'), s.get('value')
        if not isinstance(val, int) or sid in ITEM_LOCAL:
            return
        k = (sid, s.get('param'))
        out['by'][src][k] = out['by'][src].get(k, 0) + val * scale
        if k in out['stats']:
            out['stats'][k]['value'] += val * scale
        elif scale == 1:
            out['stats'][k] = dict(s)

    try:
        import mxl_tooltip
        active2 = struct.unpack_from('<I', ch.head, 0x10)[0] == 1
        skip = (4, 5) if active2 else (11, 12)
        worn = [e.it for slot, e in sorted(ch.equipped().items()) if slot not in skip]
        sets = {}
        for it in worn:
            sid = _set_of(it, data)
            if sid is not None:
                sets[sid] = sets.get(sid, 0) + 1
        out['set_pieces'] = sum(sets.values())
        for it in worn:
            out['items'] += 1
            ed = flat = 0
            mine = []
            for s in mxl_tooltip.all_stats(it, data):
                val = s.get('value')
                if isinstance(val, int):
                    if s.get('id') == 16:
                        ed += val
                    elif s.get('id') == 31:
                        flat += val
                        mine.append(s)
                add('equip', s)
            base = it.get('defense') if 'defense' in it else None
            if isinstance(base, int):
                out['defense'] += base * (100 + ed) // 100 + flat
                for s in mine:                    # the flat defense is inside the piece's own number already
                    add('equip', s, -1)
            n = sets.get(_set_of(it, data), 0)
            for i in range(5):
                if n >= i + 2:
                    for s in it.get('set_stats_%d' % i) or ():
                        add('sets', s)
        for sid, n in sorted(sets.items()):
            stats, skipped = set_bonuses(data, sid, n)
            out['set_skipped'] += skipped
            for s in stats:
                add('sets', s)
        charm = next((i for i, t in enumerate(data.itypes) if t and t[0] == 'char'), None)
        for e in ch.inventory():
            try:
                kind = data.base(e.it['code']).type
            except Exception:
                continue
            if charm is not None and charm in data.type_ancestors(kind):
                out['charms'] += 1
                for s in mxl_tooltip.all_stats(e.it, data):
                    add('charms', s)
    except Exception as e:                       # an item the host cannot describe: no sums rather than wrong ones
        out['error'] = str(e)
    return out


gear_totals = char_totals


def _set_of(it, data):
    if it.get('quality') != 'set':
        return None
    try:
        return data.set_items[it['set_unique_id']]['set_id']
    except Exception:
        return None


def set_bonuses(data, set_id, worn):
    """([stat dicts], number of bonuses left out) of a set with `worn` pieces on: the partial bonuses for 2, 3, 4
    and 5 pieces and, with every piece, the full-set bonuses (sets table, the base game's 296-byte records).
    Each property becomes stats the way an item's own mods do (mxl_rules.mods_stats, the translator of the item
    creator: max damage +n -> stats 22 / 24 / 160, "reanimate as" and state properties with their parameter ...);
    a range is taken at its low end. A property that gives no stat is counted as left out."""
    out, skipped = [], 0
    try:
        import mxl_rules
        r = data._rows('sets')[set_id]
        if len(r) != 296 or struct.unpack_from('<H', r, 0)[0] != set_id:
            return out, skipped
        size = sum(1 for s in data.set_items if s.get('set_id') == set_id)
    except Exception as e:
        print('stat screen: set bonuses:', e)
        return out, skipped
    for i in range(16):
        code, par, lo, hi = struct.unpack_from('<iiii', r, 0x10 + 16 * i)
        if code < 0 or code >= len(data.props):
            continue
        if worn < (2 + i // 2 if i < 8 else max(size, 2)):
            continue
        try:
            got = [s for s in mxl_rules.mods_stats([(code, par, lo, hi)], data, 'min')
                   if isinstance(s.get('value'), int) and s.get('id', -1) >= 0]
        except Exception as e:                   # one property the translator refuses: the others still count
            print('stat screen: set bonus', set_id, i, e)
            got = []
        for s in got:
            isc = data.isc.get(s['id']) or {}
            out.append({'id': s['id'], 'param': s.get('param'), 'value': s['value'], 'desc': isc.get('desc')})
        skipped += 0 if got else 1
    return out, skipped


def total_of(tot, sid, param=None, src=None):
    """Sum of one stat (every parameter, or one) over all the sources or one of them."""
    if src is None:
        return sum(s['value'] for (i, p), s in tot['stats'].items() if i == sid and (param is None or p == param))
    return sum(v for (i, p), v in tot['by'][src].items() if i == sid and (param is None or p == param))


def item_sum(tot, data, sid, level, param=None, src=None):
    """total_of + the "per character level" stats that feed this stat, at this level."""
    v = total_of(tot, sid, param, src)
    for pl, target in PER_LEVEL.items():
        if target == sid:
            raw = total_of(tot, pl, None, src)
            if raw:
                v += raw * level >> int((data.isc.get(pl) or {}).get('op_param') or 0)
    return v


def char_stat(ch, sid, param=None):
    """A stat stored in the character's own stat list (life / mana / stamina in whole points)."""
    v = sum(s[2] for s in ch.stats if s[0] == sid and (param is None or s[1] == param))
    return v >> 8 if sid in FIXED else v


UNARMED = (1, 2)                      # damage without a weapon (the base game's rule; not seen on a screenshot)


def active_weapon(ch, data):
    """(slot, item, base) of the weapon in the hands of the active weapon set (right hand first), None unarmed.
    A quiver or shield has no base damage and does not count."""
    try:
        active2 = struct.unpack_from('<I', ch.head, 0x10)[0] == 1
        eq = ch.equipped()
    except Exception:
        return None
    for slot in ((11, 12) if active2 else (4, 5)):
        e = eq.get(slot)
        if e is None:
            continue
        try:
            b = data.base(e.it['code'])
        except Exception:
            continue
        d = getattr(b, 'damage', None) or {}
        if any(d.get('one_hand') or ()) or any(d.get('two_hand') or ()):
            return slot, e.it, b
    return None


def weapon_damage(ch, data, tot, strength, dexterity):
    """Physical damage of a normal attack with the active weapon, the way the game's stat screen shows it:
    weapon damage = base x (100 + the weapon's own enhanced damage, sockets included) / 100 + the +min / +max
    damage of every equipped item; then x (100 + "Weapon Physical Damage" % + the strength / dexterity bonus of the
    weapon type (weapons table, % per 100 points) + the items' per-point bonuses (stats 299 / 300)) / 100.
    Which pair: the minimum from the one-hand damage when the weapon has one, the maximum from the two-hand damage
    of a two-handed weapon (matches the seven level-1 screenshots, among them a Claymore shown 5-8).
    {'min', 'max', 'base': (lo, hi), 'ed': (min %, max %), 'flat': (lo, hi), 'pct', 'name'} or None (no totals)."""
    if tot.get('error'):
        return None
    w = active_weapon(ch, data)
    if w is None:
        (blo, bhi), ed, pair, bonus, name = UNARMED, (0, 0), (21, 22), (0, 0), None
    else:
        _slot, it, b = w
        import mxl_tooltip
        d = b.damage
        oh, th = tuple(d.get('one_hand') or (0, 0)), tuple(d.get('two_hand') or (0, 0))
        min2 = not any(oh)
        max2 = min2 or (bool(b.two_handed) and any(th))
        blo, bhi = (th if min2 else oh)[0], (th if max2 else oh)[1]
        pair = (23 if min2 else 21, 24 if max2 else 22)
        emin = emax = 0
        for s in mxl_tooltip.all_stats(it, data):
            if isinstance(s.get('value'), int):
                emin += s['value'] if s.get('id') == 18 else 0
                emax += s['value'] if s.get('id') == 17 else 0
        ed = (emin, emax)
        bonus = tuple(getattr(b, 'dmg_bonus', None) or (0, 0))
        name = b.name
    flat = (total_of(tot, pair[0]), total_of(tot, pair[1]))
    lo = blo * (100 + ed[0]) // 100 + flat[0]
    hi = bhi * (100 + ed[1]) // 100 + flat[1]
    pct = (total_of(tot, 25) + bonus[0] * strength // 100 + bonus[1] * dexterity // 100
           + (total_of(tot, 299) * strength >> 8) + (total_of(tot, 300) * dexterity >> 8))
    lo, hi = max(lo * (100 + pct) // 100, 1), hi * (100 + pct) // 100
    if hi <= lo:
        hi = lo + 1
    return {'min': lo, 'max': hi, 'base': (blo, bhi), 'ed': ed, 'flat': flat, 'pct': pct, 'name': name}


def attack_rating(data, cls, tot, dexterity, level=1):
    """Attack rating as the stat screen shows it: (5 x dexterity - 35 + the class's ToHitFactor (charstats) + the
    items' flat attack rating) x (100 + the items' attack rating %) / 100. Base part checked on the seven level-1
    screenshots (dexterity 20 / 25 / 35 -> 75 / 100 / 150)."""
    tohit = 10
    try:
        r = data._rows('charstats')[cls]
        if len(r) == 196:
            tohit = struct.unpack_from('<i', r, 0x3C)[0]
    except Exception:
        pass
    flat = item_sum(tot, data, 19, level)
    pct = item_sum(tot, data, 119, level)
    return (5 * dexterity - 35 + tohit + flat) * (100 + pct) // 100


def class_factors(data, cls):
    """(life per vitality, mana per energy, stamina per vitality) of the class in quarter points
    (charstats, the base game's record layout); None when the table does not look like it."""
    try:
        r = data._rows('charstats')[cls]
        if len(r) == 196 and 0 < r[0x46] <= 64 and r[0x47] <= 64 and r[0x48] <= 64:
            return r[0x46], r[0x48], r[0x47]
    except Exception:
        pass
    return None


# ---- the game's own definition of its stat screen (statscreen table of the mod: 33-byte records)
SS_FONTS = {0: 'font8', 1: 'font16', 2: 'font30', 3: 'font42', 4: 'fontformal10', 5: 'fontformal12', 6: 'font6',
            7: 'font24', 8: 'fontformal11', 9: 'fontexocet10', 10: 'fontridiculous', 11: 'fontexocet8',
            13: 'fontingamechat'}
SS_NONE = 5382                        # string index the table uses for "no text"
T_LABEL, T_STAT, T_RESIST, T_CLASS_SKILLS, T_REGEN, T_STAT_BONUS, T_AVOID = 1, 2, 4, 18, 21, 23, 25
WEAPON_DAMAGE_ROWS = (21, 22)          # label rows '-' of page 2 that stand for the weapon's min / max damage
SS_VALUES = (T_STAT, T_RESIST, T_CLASS_SKILLS, T_REGEN, T_STAT_BONUS, T_AVOID)
F_PERCENT, F_BASE = 256, 1
A_RIGHT, A_CENTER, A_LEFT = 0, 1, 2


def screen_table(data):
    """The rows of the game's stat-screen table: [{'n', 'page', 'type', 'x', 'y', 'text', 'color', 'font', 'stat',
    'flags', 'align', 'tip', 'cap'}], [] when the game data has no such table."""
    hit = getattr(data, '_mxl_statscreen', None)
    if hit is not None:
        return hit
    rows = []
    try:
        def text(i):
            if i in (SS_NONE, 0xFFFF):
                return None
            v = data.strings.get(i)
            return str(v[1]) if v else None
        for n, r in enumerate(data._rows('statscreen')):
            if len(r) != 33:
                rows = []
                break
            page, kind, x, y, sid, color, font, stat, _u, flags, align, _s2, tip, _u2, _u3, cap = \
                struct.unpack_from('<BIHHHBBhhhhHHHHB', r, 0)
            rows.append({'n': n, 'page': page, 'type': kind, 'x': x, 'y': y, 'text': text(sid), 'color': color,
                         'font': SS_FONTS.get(font, 'font6'), 'stat': stat, 'flags': flags, 'align': align,
                         'tip': text(tip), 'cap': cap})
    except Exception as e:
        print('stat screen: no statscreen table:', e)
        rows = []
    try:
        data._mxl_statscreen = rows
    except Exception:
        pass
    return rows


def total_lines(tot, data, char=None):
    """[(colour, text)] of the summed stats, in the game's own wording and order (the tooltip code of the host)."""
    try:
        import mxl_tooltip
        stats = sorted(tot['stats'].values(), key=lambda s: (s['id'], s.get('param') or 0))
        return [(ln[0], mxl_tooltip.strip_colors(ln[1]) if '\xff' in str(ln[1]) else str(ln[1]))
                for ln in mxl_tooltip.stat_lines(stats, data, char)]
    except Exception as e:
        return [(1, str(e))]


# ====================================================================================== game fonts
class GameText:
    """Lines of text in the game's fonts as PIL images; the glyph cells keep the font's baseline, so captions
    and values sit on the same line whatever letters they hold."""

    def __init__(self, art):
        self.art = art
        self._fonts = {}
        self._lines = {}
        self.defer = None                 # (image the texts are collected for, [(line image, cap, x, y, align)])

    def _font(self, name):
        f = self._fonts.get(name)
        if f is None:
            glyphs, _lh = self.art.font(name)
            top = max([g[2][1] - g[2][3] for g in glyphs.values()] + [1])
            bottom = max([g[2][3] for g in glyphs.values()] + [0])
            f = self._fonts[name] = {'glyphs': glyphs, 'top': top, 'h': top + bottom, 'cells': {}, 'cap': None}
            ref = self._cell(f, ord('0')) or self._cell(f, ord('H'))
            box = ref[1].getbbox() if ref else None
            f['cap'] = (box[1] + box[3]) / 2 + ref[3] if box else f['h'] / 2
            f['rise'] = (box[3] - box[1]) / 2 if box else f['h'] / 4      # baseline to the middle of a capital
        return f

    def _cell(self, f, code):
        """(advance, 'L' image of the glyph's brightness, x offset, y offset in the line)."""
        if code in f['cells']:
            return f['cells'][code]
        from PIL import Image
        g = f['glyphs'].get(code) or f['glyphs'].get(ord('?'))
        cell = None
        if g:
            adv, _h, fr = g
            fw, fh, ox, oy, px, mask = fr
            pal = self.art.pal()
            buf = bytes((max(1, max(pal[px[i]])) if mask[i] else 0) for i in range(fw * fh))
            cell = (adv, Image.frombytes('L', (fw, fh), buf), ox, f['top'] - (fh - oy))
        f['cells'][code] = cell
        return cell

    def has(self, text, font):
        g = self._font(font)['glyphs']
        return all(ord(c) in g for c in text)

    def line(self, text, font='font16', color=WHITE):
        """(RGBA image trimmed to the ink sideways, y of the middle of a capital letter in it)."""
        key = (text, font, color)
        hit = self._lines.get(key)
        if hit is not None:
            return hit
        from PIL import Image
        f = self._font(font)
        cells = [c for c in (self._cell(f, ord(ch)) for ch in text) if c]
        W = max(1, sum(c[0] for c in cells) + 16)
        lum = Image.new('L', (W, f['h'] + 4), 0)
        x = 0
        for adv, im, ox, y0 in cells:
            lum.paste(im, (x + ox, y0), im.point(lambda v: 255 if v else 0))
            x += adv
        box = lum.getbbox()
        if box:
            lum = lum.crop((box[0], 0, box[2], lum.height))
        else:
            lum = lum.crop((0, 0, 1, lum.height))
        lut = self.art._lut
        chans = [lum.point([lut[min(255, color[i] * v // 255)] for v in range(256)]) for i in range(3)]
        img = Image.merge('RGBA', chans + [lum.point(lambda v: 255 if v else 0)])
        if len(self._lines) > 4000:
            self._lines.clear()
        self._lines[key] = (img, f['cap'])
        return self._lines[key]

    def draw(self, dst, text, cx, cy, font='font16', color=WHITE, align='center'):
        """Pastes the text with its capital-letter middle at cy; cx is the centre (or the left / right end)."""
        img, cap = self.line(text, font, color)
        if self.defer is not None and self.defer[0] is dst:
            self.defer[1].append((img, cap, cx, cy, align))
            return img.width
        x = cx - img.width / 2 if align == 'center' else (cx if align == 'left' else cx - img.width)
        dst.alpha_composite(img, (int(round(x)), int(round(cy - cap))))
        return img.width

    def width(self, text, font='font16'):
        return self.line(text, font, WHITE)[0].width

    def rise(self, font):
        return self._font(font)['rise']


# ====================================================================================== page 1 (measured)
# Coordinates of the game's page 1 in the 512 x 704 panel art (docs/statscreen-ref/layout.json).
P1_BOX = {'name': (108, 58, 240, 26), 'level': (378, 67, 45, 16),
          'strength': (74, 161, 90, 18), 'dexterity': (74, 222, 90, 18),
          'vitality': (350, 161, 90, 18), 'energy': (350, 222, 90, 18), 'stat_points': (240, 154, 36, 22)}
P1_PLUS = {'strength': (29, 147), 'dexterity': (29, 208), 'vitality': (439, 147), 'energy': (439, 208)}
PLUS_SIZE = (44, 44)
ARROWS = {'prev': (379, 654, 6), 'next': (425, 654, 8)}
ARROW_SIZE = (41, 36)
CLOSE = (484, 8, 22, 22)
PORTRAIT = (35, 49)                   # where the game draws the 71 x 74 class portrait, over the art
P1_CAPTIONS = (                       # text key, default, centre x, centre y, font, colour
    ('ss.level', 'Level', 400.5, 61.5, 'font6', GOLD),
    ('ss.strength', 'Strength', 119, 153.5, 'font16', GOLD),
    ('ss.dexterity', 'Dexterity', 119, 214.5, 'font16', GOLD),
    ('ss.vitality', 'Vitality', 395, 153.5, 'font16', GOLD),
    ('ss.energy', 'Energy', 395, 214.5, 'font16', GOLD),
    ('ss.stat_points', 'Stat Points', 256.5, 209.5, 'font16', GOLD),
    ('ss.damage', 'Damage', 256, 364, 'font6', GOLD),
    ('ss.attack_rating', 'Attack Rating', 256.5, 389.5, 'font6', GOLD),
    ('ss.defense', 'Defense', 257, 547, 'font6', GOLD),
)
P1_TWO_LINES = (                      # text key, default, centre x, centre y of the box, colour
    ('ss.fire_res', 'Fire\nResistance', 154, 482.5, RED),
    ('ss.cold_res', 'Cold\nResistance', 154, 509.5, BLUE),
    ('ss.light_res', 'Lightning\nResistance', 154, 536.5, YELLOW),
    ('ss.poison_res', 'Poison\nResistance', 154, 563.5, GREEN),
    ('ss.phys_res', 'Physical\nResistance', 360, 482.5, GOLD),
    ('ss.magic_res', 'Magic\nResistance', 360, 509.5, ORANGE),
    ('ss.block', 'Block Chance', 360, 536.5, WHITE),
    ('ss.grit', 'Grit', 360, 563.5, WHITE),
)
P1_DERIVED = {                        # key -> value box
    'damage_1': (92, 352, 96, 20), 'damage_2': (323, 352, 96, 20),
    'attack_rating_1': (92, 379, 96, 20), 'attack_rating_2': (323, 379, 96, 20),
    'fire_res': (65, 472, 43, 21), 'cold_res': (65, 499, 43, 21), 'light_res': (65, 526, 43, 21),
    'poison_res': (65, 553, 43, 21), 'phys_res': (405, 472, 43, 21), 'magic_res': (405, 499, 43, 21),
    'block': (405, 526, 43, 21), 'grit': (405, 553, 43, 21), 'defense': (207, 552, 98, 22)}
SKILL_ICONS = {'left': (115, 289), 'right': (351, 289)}
SS_DX = 5.5                           # table x -> panel x (measured on page 1: 3 to 7 px, mean 5.5)
P1_ORDER = ('name', 'level', 'strength', 'dexterity', 'vitality', 'energy', 'stat_points')

# ---- the editor's own pages: boxes cut from the same art, on the panel's stone
BLANK = (14, 136, 498, 612)           # the part of the panel replaced with plain stone
STONE_SRC = (206, 292, 306, 344)      # clean stone of the art (between the two skill frames)
BOX_SRC = (109, 471, 199, 494)        # an engraved box of the art (a resistance caption box), 9-sliced
ROW_H = 21
ROW_PITCH = 26
SV_Y0 = 186
SV_L = (34, 104, 140, 104)            # left column: caption box x, w; value box x, w
SV_R = (268, 80, 350, 62, 414, 62)    # right column: caption x, w; current x, w; maximum x, w
SV_LEFT = ('experience', None, 'skill_points', 'gold', 'gold_stash', 'class', 'levelup', 'copy_as')
SV_RIGHT = (None, 'life', 'mana', 'stamina')
SV_FLAGS = ('expansion', 'ladder', 'hardcore', 'died')
SV_FLAGS_Y0 = 432
SV_ORDER = ('name', 'level', 'experience', 'skill_points', 'gold', 'gold_stash', 'levelup', 'copy_as',
            'life_cur', 'life_max', 'mana_cur', 'mana_max', 'stamina_cur', 'stamina_max', 'progression')
LIST_BOX = (34, 186, 444, 418)        # the totals list: x, y, w, h
LIST_PITCH = 16


class StatScreen:
    """The canvas of the art page. win: the CharacterWindow (StatEditMixin); art: mxl_d2look_art.Art."""

    def __init__(self, parent, win, art):
        self.win = win
        self.art = art
        self.text = GameText(art)
        self.k = 1.0
        self._pil = {}
        self.spread = 1                   # panels side by side (2: an open book)
        table = screen_table(win.data)
        self.table = {}                   # game page number -> its rows
        for el in table:
            self.table.setdefault(el['page'], []).append(el)
        game = [f'game{n}' for n in sorted(self.table) if 0 < n < 255 and n < self._variants()]
        self.pages = ['main'] + game + ['totals', 'saved']
        self.page = 'main'                # the (left) page shown
        self.shown = ['main']
        self.pressed = None
        self.edit = None                  # (key, entry widget, canvas item)
        self.scroll_at = 0
        self._list_top = None             # the highest scroll_at of the totals list (known once it was drawn)
        self._redraw_job = None
        self._bg = {}
        self._pil = {}
        self._photo = None
        self._regions = []
        self._lines = None
        self._tip = None
        self._closing = False
        self.frame = tk.Frame(parent, bg='#000000')
        self.cv = tk.Canvas(self.frame, bg='#000000', highlightthickness=0, bd=0, width=PANEL_W, height=PANEL_H,
                            takefocus=1)
        self.cv.pack(expand=True)
        self._item = self.cv.create_image(0, 0, anchor='nw')
        cv = self.cv
        cv.bind('<ButtonPress-1>', self.on_press)
        cv.bind('<ButtonRelease-1>', self.on_release)
        cv.bind('<ButtonPress-3>', self.on_right)
        cv.bind('<Motion>', self.on_motion)
        cv.bind('<Leave>', lambda e: self._leave_tip())
        import mxl_scroll
        mxl_scroll.bind_wheel(cv, self.on_wheel)
        cv.bind('<Prior>', lambda e: self.turn(-1))
        cv.bind('<Next>', lambda e: self.turn(1))

    # ------------------------------------------------------------------ art pieces
    def _open(self, path):
        im = self._pil.get(path)
        if im is None:
            from PIL import Image
            im = self._pil[path] = Image.open(path).convert('RGBA')
        return im

    def _frame(self, rel, i):
        return self._open(self.art.frame(rel, i))

    def _panel(self, variant=0):
        return self._open(self.art.panel('stat-screen', variant))

    def _variants(self):
        """How many 512 x 704 pages the stat-screen art holds (6 tiles each)."""
        n = self._pil.get('variants')
        if n is None:
            try:
                n = self.art.panel_variants('stat-screen')
            except Exception:
                n = 1
            self._pil['variants'] = n
        return n

    def _cell_at(self, variant, x, y):
        """The engraved (see-through) cell of a game page's art around a point: (x, y, w, h) or None."""
        key = ('alpha', variant)
        a = self._pil.get(key)
        if a is None:
            a = self._pil[key] = self._panel(variant).getchannel('A').tobytes()
        x = int(round(x))
        for yy in (int(round(y)), int(round(y)) - 4, int(round(y)) + 4):
            if not (0 <= x < PANEL_W and 0 <= yy < PANEL_H) or a[yy * PANEL_W + x]:
                continue
            x0 = x1 = x
            while x0 > 0 and not a[yy * PANEL_W + x0 - 1]:
                x0 -= 1
            while x1 < PANEL_W - 1 and not a[yy * PANEL_W + x1 + 1]:
                x1 += 1
            y0 = y1 = yy
            while y0 > 0 and not a[(y0 - 1) * PANEL_W + x]:
                y0 -= 1
            while y1 < PANEL_H - 1 and not a[(y1 + 1) * PANEL_W + x]:
                y1 += 1
            return x0, y0, x1 - x0 + 1, y1 - y0 + 1
        return None

    def _box(self, w, h):
        """An engraved box of any size: the art's own box, corners kept, edges and middle stretched."""
        key = ('box', w, h)
        im = self._pil.get(key)
        if im is None:
            from PIL import Image
            src = self._panel().crop(BOX_SRC)
            m = 4
            sw, sh = src.size
            im = Image.new('RGBA', (w, h))
            xs = ((0, m, 0, m), (m, sw - m, m, w - m), (sw - m, sw, w - m, w))
            ys = ((0, m, 0, m), (m, sh - m, m, h - m), (sh - m, sh, h - m, h))
            flat = src.crop((m, m, sw - m, sh - m)).resize((1, 1), Image.BOX).getpixel((0, 0)) if h > 2 * sh else None
            for sx0, sx1, dx0, dx1 in xs:
                for sy0, sy1, dy0, dy1 in ys:
                    if flat and sx0 == m and sy0 == m:
                        im.paste(flat, (dx0, dy0, dx1, dy1))
                    elif dx1 > dx0 and dy1 > dy0:
                        im.paste(src.crop((sx0, sy0, sx1, sy1)).resize((dx1 - dx0, dy1 - dy0), Image.BILINEAR), (dx0, dy0))
            self._pil[key] = im
        return im

    def _button(self, w, h, down=False):
        """A text button in the stone of the art: the engraved box, lighter, with a bronze rim."""
        key = ('btn', w, h, down)
        im = self._pil.get(key)
        if im is None:
            from PIL import Image, ImageDraw
            f = 0.9 if down else 1.9              # brightness by hand: the Windows build has no PIL.ImageEnhance
            r, g, b, a = self._box(w, h).split()
            im = Image.merge('RGBA', [c.point(lambda v: min(255, int(v * f))) for c in (r, g, b)] + [a])
            d = ImageDraw.Draw(im)
            d.rectangle((0, 0, w - 1, h - 1), outline=(111, 90, 58, 255))
            d.rectangle((1, 1, w - 2, h - 2), outline=(40, 32, 20, 255) if not down else (154, 127, 82, 255))
            self._pil[key] = im
        return im

    def _checkbox(self, on):
        """A toggle in the panel's own style: a small engraved box, a gold X when set."""
        key = ('cb', bool(on))
        im = self._pil.get(key)
        if im is None:
            from PIL import ImageDraw
            im = self._box(15, 15).copy()
            ImageDraw.Draw(im).rectangle((0, 0, 14, 14), outline=(111, 90, 58, 255))
            if on:
                self.text.draw(im, 'X', 7.5, 7.5, 'font6', (242, 220, 156))
            self._pil[key] = im
        return im

    def _portrait(self, cls):
        key = ('portrait', cls)
        if key not in self._pil:
            try:
                self._pil[key] = self._frame('panel-elements\\stat-screen-portrait', cls)
            except Exception:
                self._pil[key] = None              # no portrait art: the window stays empty
        return self._pil[key]

    def _skill_icon(self, cls, sid):
        """The 48 x 48 icon of one of the class's skills (None for any other skill: nothing is drawn)."""
        key = ('skills', cls)
        icons = self._pil.get(key)
        if icons is None:
            icons = self._pil[key] = {}
            try:
                import mxl_d2ui_dc6 as DC6
                from PIL import Image
                data = self.win.data
                code = data._rows('playerclass')[cls][:4].decode('latin1').strip()
                base = 'data\\global\\themes\\classic_sigma\\game\\skills\\icons-'
                cels = DC6.dc6_frames(self.art.read(base + code + '.dc6'))
                pal = self.art.pal()
                for _tab, _name, cells in (MC.skill_trees(data).get(cls) or []):
                    for _row, _col, s, cel in cells:
                        if cel < len(cels):
                            w, h, rgba = DC6.to_rgba(cels[cel], pal)
                            icons[s] = Image.frombytes('RGBA', (w, h), bytes(self.art._bright(rgba)))
            except Exception as e:
                print('stat screen: no skill icons:', e)
        return icons.get(sid)

    def _background(self, kind):
        """'game': the panel art as it is. 'blank': the same frame and header, the middle replaced with the
        art's own stone (for the editor's pages)."""
        bg = self._bg.get(kind)
        if bg is not None:
            return bg
        from PIL import Image
        panel = self._panel()
        if kind == 'game':
            bg = panel
        elif kind.startswith('game'):
            bg = self._panel(int(kind[4:]))
        else:
            x0, y0, x1, y1 = BLANK
            tile = panel.crop(STONE_SRC)
            tw, th = tile.size
            stone = Image.new('RGBA', (x1 - x0, y1 - y0))
            for j, ty in enumerate(range(0, stone.height, th)):
                for i, tx in enumerate(range(0, stone.width, tw)):
                    t = tile
                    if i % 2:
                        t = t.transpose(Image.FLIP_LEFT_RIGHT)
                    if j % 2:
                        t = t.transpose(Image.FLIP_TOP_BOTTOM)
                    stone.paste(t, (tx, ty))
            mask = Image.new('L', stone.size, 255)             # soft upper / lower edge: no seam with the art
            f = 10
            for i in range(f):
                v = round(255 * (i + 1) / (f + 1))
                mask.paste(v, (0, i, stone.width, i + 1))
                mask.paste(v, (0, stone.height - 1 - i, stone.width, stone.height - i))
            bg = panel.copy()
            bg.paste(stone, (x0, y0), mask)
        self._bg[kind] = bg
        return bg

    # ------------------------------------------------------------------ size
    def fit(self, W, H):
        """Scale and number of panels from the space of the tab: the whole panel height whenever the text stays
        readable (down to MIN_K, then the page scrolls), and two pages side by side, like an open book, when the
        width allows it without making them much smaller."""
        k1 = min(W / PANEL_W, max(H / PANEL_H, MIN_K), MAX_K)
        k2 = min(W / (2 * PANEL_W), max(H / PANEL_H, MIN_K), MAX_K)
        spread = 2 if len(self.pages) > 1 and k2 >= k1 * SPREAD_LOSS else 1
        k = k2 if spread == 2 else k1
        k = max(0.5, int(k * 64) / 64)
        if abs(k - self.k) > 1e-6 or spread != self.spread or self._photo is None:
            self.k = k
            self.spread = spread
            self.cancel_edit()
            self._layout()
            self.cv.configure(width=round(PANEL_W * k) * len(self.shown), height=round(PANEL_H * k))
            self.redraw()

    def _starts(self):
        """Indexes of the pages a view can start at: every page, but a book never runs past the last page.
        (A book turned by pairs before: with 5 pages it showed 1-2, 3-4, 4-5 - the left page number went 1, 3, 4,
        skipping 2 and never reaching 5.)"""
        n = len(self.pages)
        return list(range(max(1, n - max(1, self.spread) + 1)))

    def page_label(self, page):
        """The page number under the arrows: "3 / 5"; as an open book the pages of the spread on both panels,
        "4-5 / 5" (each panel showing only its own number, the one on the left - next to the arrows the user
        clicks - never read 5)."""
        n = len(self.pages)
        if len(self.shown) > 1 and page in self.shown:
            a, b = self.pages.index(self.shown[0]) + 1, self.pages.index(self.shown[-1]) + 1
            return f'{a}-{b} / {n}'
        return f'{self.pages.index(page) + 1} / {n}'

    def _layout(self):
        """The pages on screen from the current page: the page itself, or the pair of the book holding it."""
        i = self.pages.index(self.page) if self.page in self.pages else 0
        start = min(i, self._starts()[-1])
        self.shown = self.pages[start:start + self.spread]
        self.page = self.shown[0]

    # ------------------------------------------------------------------ drawing
    def redraw(self):
        from PIL import Image, ImageFilter, ImageTk
        if self._redraw_job is not None:          # drawn now: a redraw still waiting would only repeat it
            try:
                self.cv.after_cancel(self._redraw_job)
            except tk.TclError:
                pass
            self._redraw_job = None
        pw, ph = round(PANEL_W * self.k), round(PANEL_H * self.k)
        try:
            regions = []
            sheet = Image.new('RGBA', (pw * len(self.shown), ph), (0, 0, 0, 255))
            for slot, page in enumerate(self.shown):
                reg = []
                boost = min(1 / self.k, TEXT_BOOST) if self.k < 1 else 1
                # (the game's pages only: their texts have room in their cells; the editor's lists fill theirs)
                texts = [] if boost > 1 and (page == 'main' or page.startswith('game')) else None
                img = self.compose(page, reg, texts)
                dx = slot * PANEL_W
                regions += [(kind, key, (x + dx, y, w, h), page) for kind, key, (x, y, w, h) in reg]
                if (pw, ph) != img.size:
                    img = img.resize((pw, ph), Image.LANCZOS)
                for line, cap, cx, cy, align in texts or ():
                    # a small page: its texts shrink less than its art (the bitmap glyphs stay readable longer)
                    ks = self.k * (boost if align == 'center' else 1)     # "value / cap" pairs keep their gap
                    w, h = max(1, round(line.width * ks)), max(1, round(line.height * ks))
                    line = line.resize((w, h), Image.LANCZOS)
                    x = cx * self.k - (w / 2 if align == 'center' else (0 if align == 'left' else w))
                    img.alpha_composite(line, (max(0, int(round(x))), max(0, int(round(cy * self.k - cap * ks)))))
                if self.k < 1:
                    img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=SHARPEN, threshold=0))
                sheet.paste(img, (slot * pw, 0))
            self._regions = regions
        except Exception as e:                    # never a dead tab: the reason on the status line
            import traceback
            traceback.print_exc()
            self.win.set_bar(str(e), error=True)
            return
        self._photo = ImageTk.PhotoImage(sheet, master=self.cv)
        self.cv.itemconfigure(self._item, image=self._photo)

    def compose(self, page=None, reg=None, texts=None):
        """One 512 x 704 page as an image; reg collects its click regions (kind, key, box in page pixels).
        texts: a list that receives the page's texts instead of the image (drawn by the caller at its own scale)."""
        from PIL import Image
        page = page or self.page
        reg = [] if reg is None else reg
        out = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 255))
        self.text.defer = None if texts is None else (out, texts)
        try:
            self._compose(out, page, reg)
        finally:
            self.text.defer = None
        return out

    def _compose(self, out, page, reg):
        win = self.win
        game = page.startswith('game')
        out.alpha_composite(self._background(page if game else ('game' if page == 'main' else 'blank')))
        tx = self.text
        if not game:                              # header: portrait, name plate and level (not on the game's lists)
            cls = win.st_cls()
            por = self._portrait(cls) if cls < 7 else None
            if por is not None:                   # the class portrait, drawn by the game over the art's window
                out.alpha_composite(por, PORTRAIT)
            name = str(win.st_value('name'))
            tx.draw(out, name if tx.has(name, 'font16') else name.encode('ascii', 'replace').decode(), 124, 73, 'font16', GOLD, 'left')
            tx.draw(out, T('ss.level', 'Level'), 400.5, 61.5, 'font6', GOLD)
            tx.draw(out, str(win.st_value('level')), 400.5, 75, 'font16', WHITE)
            reg.append(('edit', 'name', P1_BOX['name']))
            reg.append(('edit', 'level', P1_BOX['level']))
        try:
            cl = self._frame('buttons\\close', 1 if self.pressed == ('close', None) else 0)
            out.alpha_composite(cl, (CLOSE[0], CLOSE[1]))
        except Exception:
            pass
        reg.append(('close', None, CLOSE))
        for which, (x, y, fr) in ARROWS.items():
            out.alpha_composite(self._frame('buttons\\stat-screen', fr + (1 if self.pressed == ('page', which) else 0)), (x, y))
            reg.append(('page', which, (x, y) + ARROW_SIZE))
        tx.draw(out, self.page_label(page), 370, 672, 'font6', GOLD, 'right')
        if game:
            self._page_game(out, reg, int(page[4:]))
        else:
            getattr(self, '_page_' + page)(out, reg)

    def _dash(self, out, cx, cy):
        """The dimmed dash of a value only the game can compute."""
        from PIL import ImageDraw
        ImageDraw.Draw(out).rectangle((round(cx) - 6, round(cy) - 1, round(cx) + 6, round(cy)), fill=DIM + (255,))

    def _page_main(self, out, reg):
        win, tx = self.win, self.text
        sim = win.st_sim
        for key, default, cx, cy, font, color in P1_CAPTIONS[1:]:
            tx.draw(out, T(key, default), cx, cy, font, color)
        for key, default, cx, cy, color in P1_TWO_LINES:
            parts = T(key, default).split('\n')
            for i, part in enumerate(parts):              # measured: lines 11 px apart, a single line 1.5 px low
                tx.draw(out, part, cx, cy + (i * 11 - 5 if len(parts) > 1 else 1.5), 'font6', color)
        for key in ATTRS + ('stat_points',):
            x, y, w, h = P1_BOX[key]
            tx.draw(out, str(win.st_value(key)), x + w / 2 + (0.5 if key == 'stat_points' else 0), y + h / 2 + (0 if key == 'stat_points' else 0), 'font16', WHITE)
            reg.append(('edit', key, P1_BOX[key]))
        pts = sim.field('stat_points')
        for key, (x, y) in P1_PLUS.items():
            if self.pressed == ('plus', key):
                fr = 3 if pts > 0 else 1
            else:
                fr = 2 if pts > 0 else 0
            out.alpha_composite(self._frame('buttons\\stat-screen', fr), (x, y))
            reg.append(('plus', key, (x, y) + PLUS_SIZE))
        # the two attack blocks: the skills on the mouse buttons as the save names them
        cls = sim.cls
        for side, off in (('left', 0x78), ('right', 0x7C)):
            sid = struct.unpack_from('<I', sim.head, off)[0]
            ic = self._skill_icon(cls, sid) if cls < 7 else None
            x, y = SKILL_ICONS[side]
            if ic is not None:
                out.alpha_composite(ic, (x + (48 - ic.width) // 2, y + (48 - ic.height) // 2))
            reg.append(('info', 'skill_' + side, (x, y, 48, 48)))
        vals = {key: self.derived(key)[0] for key in P1_DERIVED}
        small = any(v and tx.width(v, 'font16') > 40 for k, v in vals.items() if k in RES_IDS)   # all alike
        for key, (x, y, w, h) in P1_DERIVED.items():
            cx, cy = x + w / 2 + (1.5 if w == 43 else 0), y + h / 2
            val = vals[key]
            if val is None:
                self._dash(out, cx, cy)
            else:
                tx.draw(out, val, cx, cy, 'font6' if small and key in RES_IDS else 'font16', WHITE)
            reg.append(('info', key, (x, y, w, h)))

    # ------------------------------------------------------------------ values summed by the editor
    def _split(self, sid, param=None):
        """(character's own stored value, {source: sum of the items' stat}) of one stat."""
        win = self.win
        sim, tot = win.st_sim, win.st_totals()
        return char_stat(sim, sid, param), {src: item_sum(tot, win.data, sid, sim.level, param, src) for src in SOURCES}

    def _where(self, own, parts, own_label=None):
        """The tooltip line saying what a sum is made of."""
        return T('ss.tip.parts', '{own_label} {own}, equipped items {equip}, charms {charms}, set bonuses {sets}',
                 own_label=own_label or T('ss.tip.own', 'Character'), own=own, **{k: f'{v:+d}' for k, v in parts.items()})

    def attr_total(self, sid):
        """An attribute as the game totals it: (stored + items) raised by the items' "+x %"."""
        own, parts = self._split(sid)
        pct = total_of(self.win.st_totals(), PCT_OF[sid])
        return (own + sum(parts.values())) * (100 + pct) // 100

    def derived(self, key):
        """(text or None, tooltip) of a value of page 1 the game computes."""
        win = self.win
        tot = win.st_totals()
        if tot['error']:
            return None, tot['error']
        rest = T('ss.tip.rest3', 'Not included: skills, buffs, difficulty penalty and caps of the game.')
        if key in RES_IDS:
            own, parts = self._split(RES_IDS[key])
            return f'{own + sum(parts.values())}%', self._where(own, parts) + '\n' + rest
        if key == 'defense':
            own, parts = self._split(31)
            armour = tot['defense']
            return str(armour + own + sum(parts.values())), T(
                'ss.tip.defense', 'Defense of the worn armour {armour} + other flat defense: equipped {equip}, '
                'charms {charms}, set bonuses {sets}.', armour=armour, **parts) + '\n' + T(
                'ss.tip.defense2', 'Not included: dexterity, the total "Bonus to Defense" %, skills.')
        if key.startswith('damage'):
            dmg = self.weapon_damage()
            if dmg is None:
                return None, T('ss.tip.game', 'computed by the game')
            return f"{dmg['min']}-{dmg['max']}", self.damage_tip(dmg) + '\n' + T(
                'ss.tip.dmg_skill', 'Normal attack: the bonuses of the skill on this mouse button are not included.')
        if key.startswith('attack_rating'):
            sim = win.st_sim
            return str(attack_rating(win.data, sim.cls, tot, self.attr_total(2), sim.level)), T(
                'ss.tip.ar', 'Attack rating: 5 x dexterity - 35 + class bonus, + items {flat}, then {pct:+d} % from '
                'items.', flat=item_sum(tot, win.data, 19, sim.level),
                pct=item_sum(tot, win.data, 119, sim.level)) + '\n' + T(
                'ss.tip.ar_skill', 'Not included: skills and buffs.')
        return None, T('ss.tip.game', 'computed by the game')

    def weapon_damage(self):
        win = self.win
        return weapon_damage(win.st_sim, win.data, win.st_totals(), self.attr_total(0), self.attr_total(2))

    def damage_tip(self, dmg):
        return T('ss.tip.dmg', '{weapon}: base {lo}-{hi}, enhanced damage +{ed} %, +{flo} / +{fhi} damage from the '
                 'equipped items, then {pct:+d} % (weapon physical damage, strength / dexterity bonus).',
                 weapon=dmg['name'] or T('ss.unarmed', 'Unarmed'), lo=dmg['base'][0], hi=dmg['base'][1],
                 ed=dmg['ed'][1], flo=dmg['flat'][0], fhi=dmg['flat'][1], pct=dmg['pct'])

    # ------------------------------------------------------------------ the game's list pages (statscreen table)
    BASE_KEYS = {0: 'strength', 1: 'energy', 2: 'dexterity', 3: 'vitality', 7: 'life_max', 9: 'mana_max',
                 11: 'stamina_max'}

    def game_value(self, el):
        """(text or None, tooltip, edit key or None) of one value row of the game's table."""
        win = self.win
        sim, tot, data = win.st_sim, win.st_totals(), win.data
        sid, kind, flags = el['stat'], el['type'], el['flags']
        if kind == T_LABEL and sid in WEAPON_DAMAGE_ROWS:
            dmg = self.weapon_damage()
            if dmg is None:
                return None, tot['error'] or T('ss.tip.game', 'computed by the game'), None
            return str(dmg['min' if sid == 21 else 'max']), self.damage_tip(dmg), None
        suffix = '%' if flags & F_PERCENT else ''
        name = str((data.isc.get(sid) or {}).get('desc') or sid)
        if name.startswith('FLYING'):
            name = T('ss.stat_n', 'Stat {n}', n=sid)
        if kind == T_CLASS_SKILLS:
            cls = win.st_cls()
            name = T('ss.class_skills', '{cls} skill levels',
                     cls=win.class_names[cls] if cls < len(win.class_names) else cls)
        if flags & F_BASE:
            key = self.BASE_KEYS.get(sid)
            v = win.st_value(key) if key else char_stat(sim, sid)
            return f'{v}{suffix}', T('ss.tip.base', '{name}: the base value stored in the save (click to edit).', name=name), key
        if tot['error']:
            return None, tot['error'], None
        param = win.st_cls() if kind == T_CLASS_SKILLS else None
        own, parts = self._split(sid, param)
        items = sum(parts.values())
        v = own + items
        extra = ''
        if sid in (0, 1, 2, 3):
            pct = total_of(tot, PCT_OF[sid])
            v = v * (100 + pct) // 100
            extra = T('ss.tip.pct', 'then {pct:+d} % from items', pct=pct)
        elif sid in (7, 9, 11):
            fac = class_factors(data, sim.cls)
            attr = 3 if sid in (7, 11) else 1
            more = self.attr_total(attr) - char_stat(sim, attr)
            if fac:
                per = fac[{7: 0, 9: 1, 11: 2}[sid]]
                v += more * per // 4
                extra = T('ss.tip.per_attr', '{more:+d} {attr} from items x {per}/4', more=more, per=per,
                          attr=T('ss.vitality', 'Vitality') if attr == 3 else T('ss.energy', 'Energy'))
            if sid in PCT_OF:
                pct = total_of(tot, PCT_OF[sid])
                v = v * (100 + pct) // 100
                extra += (', ' if extra else '') + T('ss.tip.pct', 'then {pct:+d} % from items', pct=pct)
        elif kind == T_STAT_BONUS:
            isc = data.isc.get(sid) or {}
            base = {299: 0, 300: 2}.get(sid, isc.get('op_base'))
            w = active_weapon(sim, data) if sid in (299, 300) else None
            per100 = (getattr(w[2], 'dmg_bonus', None) or (0, 0))[sid - 299] if w else 0
            if (not items and w is None) or base not in (0, 2):     # with a weapon: its bonus, 0 % included
                return None, T('ss.tip.class_rule', '{name} computed by the game from the class and the attribute.',
                               name=name), None
            attr = self.attr_total(base)
            v = (items * attr >> int(isc.get('op_param') or 0)) + per100 * attr // 100
            extra = T('ss.tip.per_point2', 'weapon {per100} % per 100 points, items {items}/256 % per point, '
                      'x {attr}', per100=per100, items=items, attr=attr)
        tip = name + ': ' + self._where(own, parts) + (' (' + extra + ')' if extra else '')
        tip += '\n' + T('ss.tip.rest4', 'Not included: skills, buffs and the caps of the game.')
        return f'{v}{suffix}', tip, None

    def _ss_draw(self, out, el, text, color=None):
        """A text of the game's table at its place; the box of the ink (x, y, w, h)."""
        tx = self.text
        font = el['font']
        try:
            tx._font(font)
        except Exception:
            font = 'font6'
        text = ''.join(c if c == '\n' or tx.has(c, font) else '?' for c in text)
        col = color or SS_COLORS.get(el['color'], WHITE)
        mode = {A_CENTER: 'center', A_LEFT: 'left'}.get(el['align'], 'right')
        rise = tx.rise(font)
        x = el['x'] + SS_DX
        parts = text.split('\n')[::-1]             # the game stores several lines last line first
        if len(parts) > 1:
            ys = [el['y'] + 1 + rise + 11 * i for i in range(len(parts))]
        else:
            ys = [el['y'] - 1 - rise]
        x0 = x1 = None
        for part, cy in zip(parts, ys):
            w = tx.draw(out, part, x, cy, font, col, mode)
            left = x - w / 2 if mode == 'center' else (x if mode == 'left' else x - w)
            x0 = left if x0 is None else min(x0, left)
            x1 = left + w if x1 is None else max(x1, left + w)
        return (int(x0) - 2, int(ys[0] - rise) - 3, int(x1 - x0) + 5, int(ys[-1] - ys[0] + 2 * rise) + 6)

    def _page_game(self, out, reg, n):
        from PIL import ImageDraw
        for el in self.table.get(n, ()):
            kind = el['type']
            if kind == T_LABEL and el['stat'] in WEAPON_DAMAGE_ROWS:
                text, _tip, _key = self.game_value(el)       # the weapon's min / max in place of the '-'
                box = self._ss_draw(out, el, text or el['text'] or '-')
                reg.append(('gval', el['n'], box))
            elif kind == T_LABEL:
                if el['text']:
                    box = self._ss_draw(out, el, el['text'])
                    if el['tip']:
                        reg.append(('glabel', el['n'], self._cell_at(n, el['x'] + SS_DX, el['y'] - 6) or box))
            elif kind in SS_VALUES:
                text, _tip, key = self.game_value(el)
                if text is None:
                    cx = el['x'] + SS_DX + {A_CENTER: 0, A_LEFT: 7}.get(el['align'], -7)
                    cy = el['y'] - 1 - self.text.rise(el['font'])
                    ImageDraw.Draw(out).rectangle((round(cx) - 5, round(cy), round(cx) + 5, round(cy)), fill=DIM + (255,))
                    box = (round(cx) - 9, round(cy) - 7, 18, 14)
                else:
                    box = self._ss_draw(out, el, text)
                if key:
                    reg.append(('edit', key, self._cell_at(n, el['x'] + SS_DX, el['y'] - 6) or box))
                else:
                    reg.append(('gval', el['n'], box))

    def _title(self, out, title, note):
        tx = self.text
        tx.draw(out, title, 256, 152, 'font16', GOLD)
        for i, part in enumerate(note.split('\n')):
            tx.draw(out, part, 256, 167 + 10 * i, 'font6', DIM)

    def _lines_of(self):
        """The totals list, wrapped to the list box: [(colour, text)]."""
        win = self.win
        tot = win.st_totals()
        key = (tot, self.win.st_sim.level)
        if self._lines is None or self._lines[0][0] is not tot or self._lines[0][1] != key[1]:
            maxw = LIST_BOX[2] - 30
            rows = []
            if tot['error']:
                rows.append((RED, tot['error'][:60]))
            base = [(GOLD, T('ss.tot.sources', 'Equipped items: {n}   Charms: {c}   Set pieces: {s}', n=tot['items'],
                              c=tot['charms'], s=tot['set_pieces'])),
                    (WHITE, T('ss.tot.defense', 'Defense of the items: {n}', n=tot['defense']))]
            for col, text in base + [(D2_COLORS.get(int(c), WHITE) if str(c).isdigit() else WHITE, t)
                                     for c, t in total_lines(tot, win.data, getattr(win.app, 'char', None))]:
                text = ''.join(ch if self.text.has(ch, 'font16') else '?' for ch in text)
                words, cur = text.split(' '), ''
                for wd in words:
                    trial = (cur + ' ' + wd) if cur else wd
                    if cur and self.text.width(trial, 'font16') > maxw:
                        rows.append((col, cur))
                        cur = '  ' + wd
                    else:
                        cur = trial
                rows.append((col, cur))
            self._lines = (key, rows)
        return self._lines[1]

    def _page_totals(self, out, reg):
        from PIL import ImageDraw
        tx = self.text
        self._title(out, T('ss.totals2', 'All Item Attributes'),
                    T('ss.totals_note2', "The editor's own list: every stat summed over the equipped items (active weapon\n"
                      'set, with sockets), the charms in the inventory and the set bonuses.'))
        x, y, w, h = LIST_BOX
        out.alpha_composite(self._box(w, h), (x, y))
        rows = self._lines_of()
        shown = (h - 10) // LIST_PITCH
        top = max(0, len(rows) - shown)
        self.scroll_at = max(0, min(self.scroll_at, top))
        self._list_top = top
        for i, (col, text) in enumerate(rows[self.scroll_at:self.scroll_at + shown]):
            tx.draw(out, text, x + 10, y + 5 + LIST_PITCH * i + LIST_PITCH / 2, 'font16', col, 'left')
        if top:                                    # the place in the list: a thumb on the right edge
            d = ImageDraw.Draw(out)
            th = max(16, (h - 8) * shown // len(rows))
            ty = y + 4 + (h - 8 - th) * self.scroll_at // top
            d.rectangle((x + w - 9, y + 4, x + w - 5, y + h - 5), fill=(20, 18, 16, 255))
            d.rectangle((x + w - 9, ty, x + w - 5, ty + th), fill=(111, 90, 58, 255))
        reg.append(('list', None, LIST_BOX))

    def _value_box(self, out, reg, key, x, y, w, text=None, kind='edit', color=WHITE):
        out.alpha_composite(self._box(w, ROW_H), (x, y))
        if text is None:
            text = str(self.win.st_value(key))
        if text:
            font = 'font16' if self.text.width(text, 'font16') <= w - 6 else 'font6'
            self.text.draw(out, text, x + w / 2, y + ROW_H / 2, font, color)
        reg.append((kind, key, (x, y, w, ROW_H)))

    def _caption_box(self, out, x, y, w, text, color=GOLD):
        out.alpha_composite(self._box(w, ROW_H), (x, y))
        parts = text.split('\n')
        for i, part in enumerate(parts):
            self.text.draw(out, part, x + w / 2, y + ROW_H / 2 + (i - (len(parts) - 1) / 2) * 10, 'font6', color)

    def _text_button(self, out, reg, key, x, y, w, text):
        down = self.pressed == ('button', key)
        out.alpha_composite(self._button(w, ROW_H, down), (x, y))
        self.text.draw(out, text, x + w / 2, y + ROW_H / 2 + (1 if down else 0), 'font6', GOLD)
        reg.append(('button', key, (x, y, w, ROW_H)))

    def _page_saved(self, out, reg):
        win, tx = self.win, self.text
        sim = win.st_sim
        self._title(out, T('ss.saved', 'Saved Values'),
                    T('ss.saved_note', "The editor's own page:\nwhat the save stores and the game's screen does not show."))
        lx, lw, vx, vw = SV_L
        names = {'experience': T('ss.experience', 'Experience'), 'skill_points': T('ss.skill_points', 'Skill Points'),
                 'gold': T('ss.gold', 'Gold'), 'gold_stash': T('ss.gold_stash', 'Gold in Stash'),
                 'class': T('ss.class', 'Class'), 'levelup': T('ss.levelup2', 'Level up\nlike the game'),
                 'copy_as': T('ss.copy_as', 'Copy as')}
        for r, key in enumerate(SV_LEFT):
            y = SV_Y0 + ROW_PITCH * r
            if key is None:                         # under the experience: its range in the game table + the fix
                lo, hi = sim.exp_range() if sim.cls < 7 else (0, MC.EXP_MAX)
                ok = lo <= sim.field('experience') <= hi
                tx.draw(out, T('ss.exp_range', 'level {level}: {lo}', level=sim.level, lo=lo), lx + lw + 2, y + 5.5, 'font6',
                        DIM if ok else RED, 'right')
                tx.draw(out, T('ss.exp_to', 'to {hi}', hi=hi), lx + lw + 2, y + 15.5, 'font6', DIM if ok else RED, 'right')
                self._text_button(out, reg, 'match_exp', vx, y, vw, T('ss.match', 'Match to level'))
                continue
            self._caption_box(out, lx, y, lw, names[key])
            if key == 'class':
                cls = win.st_cls()
                nm = win.class_names[cls] if cls < len(win.class_names) else str(cls)
                self._value_box(out, reg, 'class', vx, y, vw, nm, kind='class',
                                color=WHITE if getattr(win, 'pending_cls', None) is None else YELLOW)
            elif key == 'levelup':
                self._value_box(out, reg, key, vx, y, vw, T('ss.levelup_to', 'to level ...'), color=DIM)
            elif key == 'copy_as':
                self._value_box(out, reg, key, vx, y, vw, win.copy_name.get() or T('ss.new_name', 'new name ...'),
                                color=WHITE if win.copy_name.get() else DIM)
            else:
                self._value_box(out, reg, key, vx, y, vw)
        cx, cw, ax, aw, bx, bw = SV_R
        tx.draw(out, T('ss.current', 'Current'), ax + aw / 2, SV_Y0 + ROW_H / 2, 'font6', GOLD)
        tx.draw(out, T('ss.maximum', 'Maximum'), bx + bw / 2, SV_Y0 + ROW_H / 2, 'font6', GOLD)
        for r, key in enumerate(SV_RIGHT):
            if key is None:
                continue
            y = SV_Y0 + ROW_PITCH * r
            self._caption_box(out, cx, y, cw, {'life': T('ss.life', 'Life'), 'mana': T('ss.mana', 'Mana'),
                                               'stamina': T('ss.stamina', 'Stamina')}[key],
                              {'life': RED, 'mana': BLUE, 'stamina': YELLOW}[key])
            self._value_box(out, reg, key + '_cur', ax, y, aw)
            self._value_box(out, reg, key + '_max', bx, y, bw)
        y = SV_Y0 + ROW_PITCH * 5
        self._caption_box(out, cx, y, cw + 2 + aw, T('ss.progression', 'Progression'))
        self._value_box(out, reg, 'progression', bx, y, bw)
        self._text_button(out, reg, 'copy', vx + vw + 6, SV_Y0 + ROW_PITCH * 7, 56, T('he.copy', 'Copy'))
        # toggles: character type (left), difficulties finished (right)
        y0 = SV_FLAGS_Y0
        tx.draw(out, T('ss.char_type', 'Character Type'), lx + (vx + vw - lx) / 2, y0 - 16, 'font16', GOLD)
        tx.draw(out, T('ss.difficulty', 'Difficulty'), cx + (bx + bw - cx) / 2, y0 - 16, 'font16', GOLD)
        flags = sim.flags()
        fl_names = {'expansion': T('he.expansion', 'Expansion'), 'ladder': T('he.ladder', 'Ladder'),
                    'hardcore': T('he.hardcore', 'Hardcore'), 'died': T('he.dead', 'You were Dead')}
        for r, key in enumerate(SV_FLAGS):
            y = y0 + ROW_PITCH * r
            w = vx + vw - lx
            out.alpha_composite(self._box(w, ROW_H), (lx, y))
            out.alpha_composite(self._checkbox(flags[key]), (lx + 6, y + 3))
            tx.draw(out, fl_names[key], lx + 30, y + ROW_H / 2, 'font6', WHITE if flags[key] else GOLD, 'left')
            reg.append(('flag', key, (lx, y, w, ROW_H)))
        done = sim.difficulties_done
        d_names = [MC.difficulty_name(i) for i in range(3)] + [T('ss.hell_done', 'Hell finished')]
        for n in range(4):
            y = y0 + ROW_PITCH * n
            w = bx + bw - cx
            out.alpha_composite(self._box(w, ROW_H), (cx, y))
            out.alpha_composite(self._checkbox(done == n), (cx + 6, y + 3))
            text = d_names[n] if n == 3 else T('ss.diff_open', '{mode} is the highest open', mode=d_names[n])
            tx.draw(out, text, cx + 30, y + ROW_H / 2, 'font6', WHITE if done == n else GOLD, 'left')
            reg.append(('done', n, (cx, y, w, ROW_H)))
        # file
        ch = win.ch
        y = y0 + ROW_PITCH * 4 + 14
        info = (T('ss.file', 'File: {name}', name=os.path.basename(ch.path)),
                T('ss.file_size', 'Size: {size} bytes    Version: {version}', size=f'{len(ch.raw):,}',
                  version=struct.unpack_from('<I', ch.raw, 4)[0]))
        for i, text in enumerate(info):
            text = ''.join(c if tx.has(c, 'font6') else '?' for c in text)
            tx.draw(out, text, 256, y + 12 * i, 'font6', DIM)

    # ------------------------------------------------------------------ pointer
    def _at(self, ev):
        x, y = ev.x / self.k, ev.y / self.k
        for kind, key, (bx, by, bw, bh), _page in reversed(self._regions):
            if bx <= x < bx + bw and by <= y < by + bh:
                return kind, key, (bx, by, bw, bh)
        return None, None, None

    def tip_of(self, kind, key):
        win = self.win
        if kind == 'edit':
            if key in ATTRS:
                own, parts = self._split(ATTR_IDS[key])
                return T('ss.tip.attr2', '{label}: base value stored in the save. The game shows the total: {total}',
                         label=win.st_label(key), total=self.attr_total(ATTR_IDS[key])) + '\n(' + self._where(
                             own, parts, T('ss.tip.base_word', 'base')) + ')'
            if key == 'level':
                return T('ss.tip.level', 'Level: written as typed, nothing else changes.\n'
                         'The game-like level-up is on the "Saved values" page.')
            if key == 'levelup':
                return T('he.level_note', 'Raising the level works like the game: experience, 5 stat points\n'
                         'and 1 skill point per level, life / mana / stamina per level.')
            if key == 'name':
                return T('ss.tip.name', 'Name: SAVE renames the character and its files.')
            if key == 'copy_as':
                return T('ss.tip.copy', 'Name of the copy: type it, then click Copy.')
            try:
                lo, hi = win.st_range(key)
                return f'{win.st_label(key)}: {lo} - {hi}'
            except CharError:
                return None
        if kind == 'plus':
            return T('ss.tip.plus', 'Click: +1 (Shift +10, Ctrl all the stat points).\nRight click: one point back.\n'
                     'Alt: without touching the stat points.')
        if kind == 'class':
            return T('he.class_note', 'Changing the class resets the skill levels\n(the save keeps one skill list per class).')
        if kind in ('gval', 'glabel'):
            el = next((e for rows in self.table.values() for e in rows if e['n'] == key), None)
            if el is None:
                return None
            if kind == 'gval':
                return self.game_value(el)[1]
            try:
                import mxl_tooltip
                return mxl_tooltip.strip_colors(el['tip']).strip()
            except Exception:
                return el['tip']
        if kind == 'info':
            if key in P1_DERIVED and key not in ('block', 'grit'):
                return self.derived(key)[1]
            if key.startswith('skill_'):
                sim = win.st_sim
                sid = struct.unpack_from('<I', sim.head, 0x78 if key == 'skill_left' else 0x7C)[0]
                return win._sk_name(sid)
            return T('ss.tip.game', 'computed by the game')
        if kind == 'page':
            return T('ss.tip.page2', "Other pages: the game's two lists of totals, all item attributes, saved values")
        return None

    def _show_tip(self, text):
        self._tip = text
        try:
            self.win._sk_tip(text or '', self.cv)      # same text: the tip only follows the pointer
        except Exception:
            pass

    def _leave_tip(self):
        """<Leave>: the tip goes a moment later unless the pointer is still on the screen (mxl_floattip)."""
        try:
            self.win._sk_tip_leave(self.cv)
        except Exception:
            pass
        self._tip = None

    def on_motion(self, ev):
        kind, key, _box = self._at(ev)
        cur = {'edit': 'xterm', 'plus': 'hand2', 'page': 'hand2', 'close': 'hand2', 'button': 'hand2',
               'flag': 'hand2', 'done': 'hand2', 'class': 'hand2'}.get(kind, '')
        if self.cv.cget('cursor') != cur:
            self.cv.configure(cursor=cur)
        self._show_tip(self.tip_of(kind, key) if kind else None)

    def on_press(self, ev):
        self.cv.focus_set()
        if self.edit is not None and not self.commit_edit():
            return
        kind, key, box = self._at(ev)
        if kind in ('plus', 'page', 'close', 'button'):
            self.pressed = (kind, key)
            self.redraw()
        elif kind == 'edit':
            self.start_edit(key, box)
        elif kind == 'flag':
            self.win.st_flag(key)
        elif kind == 'done':
            self.win.st_done(key)
        elif kind == 'class':
            self.class_menu(ev)
        elif kind == 'list':
            x, y, w, h = box
            self.scroll((1 if ev.y / self.k > y + h / 2 else -1) * ((h - 10) // LIST_PITCH - 1))

    def on_release(self, ev):
        if self.pressed is None:
            return
        pressed, self.pressed = self.pressed, None
        kind, key, _box = self._at(ev)
        if (kind, key) != pressed:
            self.redraw()
            return
        self.activate(kind, key, ev.state)

    def activate(self, kind, key, state=0):
        """What a click on a button does (state: the event's modifier bits)."""
        win = self.win
        shift, ctrl, alt = bool(state & 0x1), bool(state & 0x4), bool(state & 0x8)
        if kind == 'plus':
            win.st_plus(key, 10 if shift else 1, free=alt, everything=ctrl and not alt)
        elif kind == 'page':
            self.turn(-1 if key == 'prev' else 1)
            return
        elif kind == 'close':
            self.redraw()
            win.close()
            return
        elif kind == 'button':
            if key == 'match_exp':
                win.st_match_exp()
            elif key == 'copy':
                win.copy_char()
        self.redraw()

    def on_right(self, ev):
        kind, key, _box = self._at(ev)
        if kind == 'plus':
            if self.edit is not None and not self.commit_edit():
                return
            self.win.st_plus(key, 10 if ev.state & 0x1 else 1, take=True, free=bool(ev.state & 0x8))

    def on_wheel(self, n, _ev=None):
        """n notches (mxl_scroll.WheelHandler; positive = down): 3 rows of the totals list each. At the list's
        end (or on a page without the list) the notch is not taken, the page around scrolls when it can."""
        if 'totals' not in self.shown:
            return None
        top = self._list_top
        if (n < 0 and self.scroll_at <= 0) or (n > 0 and top is not None and self.scroll_at >= top):
            return None
        self.scroll(n * 3)
        return 'break'

    def scroll(self, n):
        """Moves the totals list; drawn once the pending input is handled (a redraw of the panels takes 60-100 ms:
        a quick turn of the wheel or a touchpad swipe queued one redraw per notch and the list crawled on for
        seconds after the hand had stopped)."""
        top = self._list_top
        self.scroll_at = max(0, self.scroll_at + n)
        if top is not None:
            self.scroll_at = min(self.scroll_at, top)
        self.redraw_later()

    def redraw_later(self):
        if self._redraw_job is not None:
            return
        try:
            self._redraw_job = self.cv.after_idle(self._redraw_now)
        except tk.TclError:
            self._redraw_job = None

    def _redraw_now(self):
        self._redraw_job = None
        try:
            if self.cv.winfo_exists():
                self.redraw()
        except tk.TclError:
            pass

    def turn(self, step):
        if self.edit is not None and not self.commit_edit():
            return
        st = self._starts()
        cur = min(self.pages.index(self.page), st[-1])
        self.show_page(self.pages[st[(st.index(cur) + step) % len(st)]], exact=True)

    def show_page(self, page, exact=False):
        """Shows a page (in a book: the pair holding it; exact: the pair starting with it)."""
        if page in self.pages:
            self.cancel_edit()
            self.page = page
            if exact and self.spread > 1:
                i = min(self.pages.index(page), self._starts()[-1])    # always a full book
                self.shown = self.pages[i:i + self.spread]
                self.page = self.shown[0]
            else:
                self._layout()
            self.redraw()

    def class_menu(self, ev):
        win = self.win
        m = tk.Menu(self.cv, tearoff=0)
        for name in win.class_names:
            m.add_command(label=name, command=lambda n=name: (win.new_class.set(n), win.on_class_change(), self.redraw()))
        try:
            m.tk_popup(ev.x_root, ev.y_root)
        finally:
            m.grab_release()

    # ------------------------------------------------------------------ editing in place
    def order(self):
        """The fields Tab walks through: those of the pages on screen, each once."""
        out = []
        for kind, key, _box, _page in self._regions:
            if kind == 'edit' and key not in out:
                out.append(key)
        rank = {k: i for i, k in enumerate(P1_ORDER + SV_ORDER)}
        return tuple(sorted(out, key=lambda k: rank.get(k, 99)))

    def box_of(self, key, page=None):
        return next((box for kind, k, box, pg in self._regions if kind == 'edit' and k == key and page in (None, pg)), None)

    def start_edit(self, key, box=None):
        """An entry exactly over the value box, in the box's colours."""
        self.cancel_edit()
        box = box or self.box_of(key)
        if box is None:
            return None
        x, y, w, h = box
        k = self.k
        if key == 'name':
            x, w = x + 12, w - 16
        px = max(9, round((11 if h < 20 else 12) * k * 1.25))
        e = tk.Entry(self.cv, font=('Times New Roman', -px, 'bold'), bd=0, relief='flat', bg='#0d0c0b',
                     fg='#c7b377' if key == 'name' else '#e6e6e6', insertbackground='#e6e6e6',
                     selectbackground='#4a1712', selectforeground='#ffffff',
                     highlightthickness=1, highlightbackground='#6f5a3a', highlightcolor='#c7b377',
                     justify='left' if key == 'name' else 'center')
        text = '' if key == 'copy_as' and not self.win.copy_name.get() else str(self.win.st_value(key))
        e.insert(0, text)
        e.select_range(0, 'end')
        item = self.cv.create_window(round(x * k), round(y * k), anchor='nw', window=e,
                                     width=max(20, round(w * k)), height=max(14, round(h * k)))
        self.edit = (key, e, item)
        e.bind('<Return>', lambda _e: (self.commit_edit(), 'break')[1])
        e.bind('<KP_Enter>', lambda _e: (self.commit_edit(), 'break')[1])
        e.bind('<Escape>', lambda _e: (self.cancel_edit(), self.win.update_dirty(), 'break')[2])
        e.bind('<FocusOut>', lambda _e: self.commit_edit(leaving=True))
        e.bind('<Tab>', lambda _e: (self.next_edit(1), 'break')[1])
        e.bind('<ISO_Left_Tab>', lambda _e: (self.next_edit(-1), 'break')[1])
        e.bind('<Shift-Tab>', lambda _e: (self.next_edit(-1), 'break')[1])
        if key not in TEXT_KEYS:
            e.bind('<Up>', lambda ev: (self.step_edit(10 if ev.state & 1 else 1), 'break')[1])
            e.bind('<Down>', lambda ev: (self.step_edit(-10 if ev.state & 1 else -1), 'break')[1])
        e.focus_set()
        return e

    def step_edit(self, n):
        if self.edit is None:
            return
        key, e, _item = self.edit
        try:
            v = int(e.get().replace(',', '').replace(' ', ''))
        except ValueError:
            v = self.win.st_value(key)
        lo, hi = self.win.st_range(key)
        e.delete(0, 'end')
        e.insert(0, str(max(lo, min(hi, v + n))))
        e.select_range(0, 'end')

    def commit_edit(self, leaving=False):
        """Stores the typed value. Refused input: the entry stays (Enter / Tab) or is dropped (focus left)."""
        if self.edit is None or self._closing:
            return True
        key, e, _item = self.edit
        ok = self.win.st_set(key, e.get())
        if ok or leaving:
            self.cancel_edit()
            if ok and key == 'copy_as':
                pass
            return ok
        try:
            e.select_range(0, 'end')
            e.focus_set()
        except tk.TclError:
            pass
        return False

    def cancel_edit(self):
        if self.edit is None:
            return
        _key, e, item = self.edit
        self.edit = None
        self._closing = True
        try:
            self.cv.delete(item)
            e.destroy()
        except tk.TclError:
            pass
        self._closing = False

    def next_edit(self, step):
        if self.edit is None:
            return
        key = self.edit[0]
        if not self.commit_edit():
            return
        order = self.order()
        i = order.index(key) if key in order else -1
        self.start_edit(order[(i + step) % len(order)])
