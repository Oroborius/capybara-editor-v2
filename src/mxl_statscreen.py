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
K_SPLIT = 0.7                    # the smallest scale of the split layout (pages at the edges, the scene between)
MIN_SCENE = 200                  # the narrowest scene between the two pages (px at UI scale 1)
OFFSETS_SETTING = 'statscreen_page_offsets'   # how far each page was moved from its edge (page pixels)
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


def char_totals(ch, data, exclude=()):
    """Sums of the stats of everything the character wears or carries that counts in game:
    - 'equip': the equipped items of the active weapon set, with their runeword and socketed items;
    - 'charms': the charms lying in the inventory (Median XL charms work from there);
    - 'sets': the set bonuses: the lists the set items carry themselves (list n counts with n + 2 pieces worn;
      no set item of Median XL Sigma has one) and the partial (2 to 5 pieces) and full bonuses of the game's sets
      table.
    {'stats': {(id, param): stat dict, value summed over the sources}, 'by': {source: {(id, param): value}},
     'n': {stat id: number of item stats summed}, 'defense': defense of the armour pieces,
     'items' / 'charms' / 'set_pieces': counts, 'error': str or None}."""
    out = {'stats': {}, 'by': {k: {} for k in SOURCES}, 'n': {}, 'defense': 0, 'items': 0, 'charms': 0,
           'set_pieces': 0, 'set_skipped': 0, 'error': None, 'per_item': []}
    plmap = per_level_map(data)

    def keep_levels(src, stats):
        """The per-level stats of one item: the game rounds value x level >> shift item by item."""
        mine = {}
        for st in stats:
            if st.get('id') in plmap and isinstance(st.get('value'), int):
                mine[st['id']] = mine.get(st['id'], 0) + st['value']
        if mine:
            out['per_item'].append((src, mine))

    def add(src, s, scale=1):
        sid, val = s.get('id'), s.get('value')
        if not isinstance(val, int) or sid in ITEM_LOCAL:
            return
        k = (sid, s.get('param'))
        out['by'][src][k] = out['by'][src].get(k, 0) + val * scale
        if scale == 1:
            out['n'][sid] = out['n'].get(sid, 0) + 1
        if k in out['stats']:
            out['stats'][k]['value'] += val * scale
        elif scale == 1:
            out['stats'][k] = dict(s)

    try:
        import mxl_tooltip
        active2 = struct.unpack_from('<I', ch.head, 0x10)[0] == 1
        skip = (4, 5) if active2 else (11, 12)
        worn = [e.it for slot, e in sorted(ch.equipped().items()) if slot not in skip and slot not in exclude]
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
            its = mxl_tooltip.all_stats(it, data)
            keep_levels('equip', its)
            for s in its:
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
                its = mxl_tooltip.all_stats(e.it, data)
                keep_levels('charms', its)
                for s in its:
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


ISC_OP = 84                           # itemstatcost record: op, op param, op base (u16), op stat 1-3 (u16)
LEVEL_STAT = 12


def per_level_map(data):
    """{per-level stat: (target stats, shift)} read from the game's itemstatcost table: every stat whose op is 2 or 4
    (value x op base >> op param added to the op stats) with the character level (stat 12) as op base - e.g. 218
    "+max damage per level" feeds 22, 24 and 160. PER_LEVEL (one target each) when the table cannot be read."""
    hit = getattr(data, '_mxl_per_level', None)
    if hit is not None:
        return hit
    out = {}
    try:
        for sid, r in enumerate(data._rows('itemstatcost')):
            if len(r) < ISC_OP + 10 or r[ISC_OP] not in (2, 4):
                continue
            base = struct.unpack_from('<H', r, ISC_OP + 2)[0]
            targets = tuple(t for t in struct.unpack_from('<3H', r, ISC_OP + 4) if t != 0xFFFF)
            if base == LEVEL_STAT and targets:
                out[sid] = (targets, r[ISC_OP + 1])
    except Exception:
        out = {}
    if not out:
        out = {pl: ((t,), int((data.isc.get(pl) or {}).get('op_param') or 0)) for pl, t in PER_LEVEL.items()}
    try:
        data._mxl_per_level = out
    except Exception:
        pass
    return out


def item_sum(tot, data, sid, level, param=None, src=None):
    """total_of + the "per character level" stats that feed this stat, at this level."""
    v = total_of(tot, sid, param, src)
    per_item = tot.get('per_item')
    for pl, (targets, shift) in per_level_map(data).items():
        if sid in targets:
            if per_item is not None and src in (None, 'equip', 'charms'):
                # item by item, as the game rounds (test-druid: 16, 9, 9, 8 x 81 >> 5 = 104, not 42 x 81 >> 5 = 106)
                v += sum(m[pl] * level >> shift for s, m in per_item if pl in m and src in (None, s))
                if src is None:
                    raw = total_of(tot, pl, None, 'sets')
                    v += raw * level >> shift if raw else 0
                continue
            raw = total_of(tot, pl, None, src)
            if raw:
                v += raw * level >> shift
    return v


def attribute_total(ch, data, tot, sid):
    """An attribute (0 strength, 1 energy, 2 dexterity, 3 vitality) as the stat screen totals it: (stored + the
    items' sum, per-level stats included) raised by the items' "+x %". The Stats page and the status bar use this."""
    parts = sum(item_sum(tot, data, sid, ch.level, None, src) for src in SOURCES)
    return (char_stat(ch, sid) + parts) * (100 + total_of(tot, PCT_OF[sid])) // 100


def char_stat(ch, sid, param=None):
    """A stat stored in the character's own stat list (life / mana / stamina in whole points)."""
    v = sum(s[2] for s in ch.stats if s[0] == sid and (param is None or s[1] == param))
    return v >> 8 if sid in FIXED else v


ETH_PCT = 125                         # ethereal weapon base damage, % (Median XL; the base game has 150)
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
        if getattr(b, 'kind', None) == 'weapons' and d:
            # a weapon without a damage of its own (Crystal Sword: 0-0, its damage is innate): still the weapon,
            # not unarmed (in game: test-druid's Crystal Sword (Sacred) - Attack 1287-2043 with base 0-0)
            return slot, e.it, b
    return None


# the items' per-point damage bonuses: (value x attribute) >> 8 % added to "Weapon Physical Damage" (stat 25) - op 2,
# op param 8, op base strength (0) or dexterity (2) in the game's itemstatcost table
STR_BONUS = (299, 442)                # "Current Strength Damage Bonus", "Additional Strength Damage Bonus"
DEX_BONUS = (300,)                    # "Additional Dexterity Damage Bonus"


def hand_weapons(ch, data):
    """[(slot, item, base)] of the weapons in the hands of the active weapon set (right hand first); a shield or
    quiver does not count, a weapon with 0-0 damage of its own (Crystal Sword) does."""
    try:
        active2 = struct.unpack_from('<I', ch.head, 0x10)[0] == 1
        eq = ch.equipped()
    except Exception:
        return []
    out = []
    for slot in ((11, 12) if active2 else (4, 5)):
        e = eq.get(slot)
        if e is None:
            continue
        try:
            b = data.base(e.it['code'])
        except Exception:
            continue
        d = getattr(b, 'damage', None) or {}
        if any(d.get('one_hand') or ()) or any(d.get('two_hand') or ()) or (getattr(b, 'kind', None) == 'weapons'
                                                                             and d):
            out.append((slot, e.it, b))
    return out


def weapon_part(it, b, data):
    """(base lo, hi, (ED min %, max %), stat pair, str/dex bonus, name, ethereal, weapon lo, hi) of one weapon:
    weapon lo / hi = base (ethereal +25 %) x (100 + its own enhanced damage, sockets included) / 100."""
    import mxl_tooltip
    d = b.damage
    oh, th = tuple(d.get('one_hand') or (0, 0)), tuple(d.get('two_hand') or (0, 0))
    min2 = not any(oh)
    max2 = min2 or (bool(b.two_handed) and any(th))
    blo, bhi = (th if min2 else oh)[0], (th if max2 else oh)[1]
    pair = (23 if min2 else 21, 24 if max2 else 22)
    emin = emax = 0
    for st in mxl_tooltip.all_stats(it, data):
        if isinstance(st.get('value'), int):
            emin += st['value'] if st.get('id') == 18 else 0
            emax += st['value'] if st.get('id') == 17 else 0
    eth = bool(it.get('ethereal'))
    if eth:                                 # Median XL: +25 % base damage (in game: Dirk 18-20 -> 22-25)
        blo, bhi = blo * ETH_PCT // 100, bhi * ETH_PCT // 100
    bonus = tuple(getattr(b, 'dmg_bonus', None) or (0, 0))
    return (blo, bhi, (emin, emax), pair, bonus, b.name, eth,
            blo * (100 + emin) // 100, bhi * (100 + emax) // 100)


DUAL_WIELD_CLASSES = (4, 6)           # Barbarian, Assassin


def skill_descdam(data, sid):
    """skilldesc.txt descdam of a skill (record +0x12; the skills row's u16 at 404 is its skilldesc row): 1 = the
    Attack path, 5 = weapon skills; None when unknown."""
    try:
        rows = data._capy_descdam
    except AttributeError:
        rows = {}
        try:
            data._capy_descdam = rows
        except Exception:
            pass
    if sid in rows:
        return rows[sid]
    val = None
    try:
        import mxl_skilldesc as SD
        t = SD.tables(data)
        sd = struct.unpack_from('<H', t.sk[sid], 404)[0]
        if (0 < sd or sid == 0) and sd < len(t.sd):     # row 0 is Attack's own (sd0), "none" for the others
            val = t.sd[sd][0x12]
    except Exception:
        val = None
    rows[sid] = val
    return val


def damage_text(lo, hi):
    """The Damage box text as the game draws it: numbers of 10000 and more as N K."""
    def one(v):
        return f'{v // 1000}K' if v >= 10000 else str(v)
    return f'{one(lo)}-{one(hi)}'


def weapon_damage(ch, data, tot, strength, dexterity, level=None, slot=None, both=False):
    """Physical damage of a normal attack with the active weapon, the way the game's stat screen shows it:
    weapon damage = base x (100 + the weapon's own enhanced damage, sockets included) / 100 + the +min / +max
    damage of every equipped item (with the "per character level" ones: 218 max damage per level); then x (100 +
    "Weapon Physical Damage" % (with 203, per level) + the strength / dexterity bonus of the weapon type (weapons
    table, % per 100 points) + the items' per-point bonuses (stats 299 / 442 strength, 300 dexterity)) / 100.
    level: the character level for the per-level stats (default: ch.level).
    Which pair: the minimum from the one-hand damage when the weapon has one, the maximum from the two-hand damage
    of a two-handed weapon (matches the seven level-1 screenshots, among them a Claymore shown 5-8).
    slot: only the weapon in that slot (dual wield, Attack: one range per hand); both: the two hands' weapons added
    (dual wield, weapon skills).
    {'min', 'max', 'base': (lo, hi), 'ed': (min %, max %), 'flat': (lo, hi), 'pct', 'name'} or None (no totals)."""
    if tot.get('error'):
        return None
    hands = hand_weapons(ch, data)
    if slot is not None:
        hands = [h for h in hands if h[0] == slot]
    elif not both:
        hands = hands[:1]
    if not hands:
        (blo, bhi), ed, pair, bonus, name, eth = UNARMED, (0, 0), (21, 22), (0, 0), None, False
        wlo, whi = blo, bhi
    else:
        parts = [weapon_part(it, b, data) for _s, it, b in hands]
        blo, bhi, ed, pair, bonus, name, eth = parts[0][:7]
        # dual wield on a weapon skill (descdam 5): the unit's 21/22 hold both hands' damage;
        # the strength / dexterity bonus and the one / two hand choice come from the primary weapon
        wlo, whi = sum(pt[7] for pt in parts), sum(pt[8] for pt in parts)
        if len(parts) > 1:
            name = ' + '.join(pt[5] for pt in parts)
    if level is None:
        level = getattr(ch, 'level', 1) or 1
    flat = (item_sum(tot, data, pair[0], level), item_sum(tot, data, pair[1], level))
    lo = wlo + flat[0]
    hi = whi + flat[1]
    wpd = item_sum(tot, data, 25, level)
    pct = (wpd + bonus[0] * strength // 100 + bonus[1] * dexterity // 100
           + (sum(total_of(tot, s) for s in STR_BONUS) * strength >> 8)
           + (sum(total_of(tot, s) for s in DEX_BONUS) * dexterity >> 8))
    pre = (lo, hi)
    ele = elemental_damage(tot)
    innate = innate_damage(ch, data, tot)
    ele = (ele[0] + innate, ele[1] + innate)
    plo, phi = max(lo * (100 + pct) // 100, 1), hi * (100 + pct) // 100
    lo, hi = plo + ele[0], phi + ele[1]
    if hi <= lo:
        hi = lo + 1
    return {'min': lo, 'max': hi, 'base': (blo, bhi), 'ed': ed, 'flat': flat, 'pct': pct, 'wpd': wpd, 'name': name,
            'pre': pre, 'phys': (plo, phi), 'ele': ele, 'eth': eth, 'innate': innate}


ELEMENTS = ((48, 49), (50, 51), (52, 53), (54, 55))     # fire, lightning, magic, cold: min / max damage
INNATE, INNATE_PCT = 415, 484
INNATE_MASTERY = {0: 329, 1: 330, 2: 331}   # element byte 0 fire, 1 lightning, 2 cold (3 poison, 4 magic, 5 tri)          # "Innate <element> Damage: (x % of <attribute>)", "Innate Elemental Damage" %


def innate_damage(ch, data, tot):
    """The weapons' innate elemental damage (stat 415: value = % of an attribute, param = attribute << 8 | element
    (0 str, 1 energy, 2 dex, 3 vit; element 1 lightning, 2 cold, 5 tri-elemental ...)), one fixed number added to
    both min and max: attribute x % / 100, then x (100 + Innate Elemental Damage %) / 100. In game (test-druid,
    Crystal Sword (Sacred), 49 % of Dexterity 843, +22 %): 413 -> 503, in both Damage boxes. Tri-elemental counted
    once (not seen in game)."""
    pct = total_of(tot, INNATE_PCT)
    out = 0
    for (sid, param), st in tot['stats'].items():
        if sid != INNATE or not st.get('value') or param is None:
            continue
        attr = (param >> 8) & 0xFF
        if attr == 4:                    # "whichever is higher" of strength and dexterity (the tooltip code)
            v = max(attribute_total(ch, data, tot, 0), attribute_total(ch, data, tot, 2))
        elif attr in (0, 1, 2, 3):
            v = attribute_total(ch, data, tot, attr)
        else:
            continue
        v = v * st['value'] // 100 * (100 + pct) // 100
        m = INNATE_MASTERY.get(param & 0xFF)       # it lands in that element's stats, which get the mastery
        out += v * (100 + total_of(tot, m)) // 100 if m else v
    return out


MASTERY = {(48, 49): 329, (50, 51): 330, (54, 55): 331}   # fire / lightning / cold mastery %; magic has none


def elemental_damage(tot):
    """(min, max) of the items' elemental damage as page 1's Damage boxes add it: fire,
    lightning, cold each x (100 + their mastery %) / 100, magic as is, + poison over its whole length (raw x frames
    >> 8, frames = stat 101 when set, else stat 59 / stat 326). Page 2 shows poison per second (half at 2 s).
    In game (test-druid, Attack): 130-260 + 330-660 + 230-385 + 150-250 = 840-1555 on top of the physical 249-671."""
    lo = hi = 0
    for a, b in ELEMENTS:
        m = 100 + total_of(tot, MASTERY[(a, b)]) if (a, b) in MASTERY else 100
        lo += total_of(tot, a) * m // 100
        hi += total_of(tot, b) * m // 100
    plo, phi, length = (total_of(tot, s) for s in POISON)
    if plo or phi:
        frames = total_of(tot, 101) or length // max(total_of(tot, 326), (tot.get('n') or {}).get(59, 0), 1)
        lo += plo * frames >> 8
        hi += phi * frames >> 8
    return lo, hi


def mouse_skill(ch, side):
    """Skill id on the left (0x78) or right (0x7C) mouse button as the save stores it, or None."""
    try:
        return struct.unpack_from('<I', ch.head, 0x78 if side == 'left' else 0x7C)[0]
    except Exception:
        return None


def skill_level(ch, data, tot, sid):
    """Effective level of a skill: hard points + the items' "+all skills" (127), "+class skills" (83, the skill's
    class) and "+single skill" (107); an oskill (97) counts with or without hard points. Not included: the
    "+skill tab" stat (188) and skills/buffs that raise other skills."""
    try:
        hard = int(ch.skill_levels().get(sid, 0))
    except Exception:
        hard = 0
    osk = total_of(tot, 97, sid)
    if hard <= 0:
        return osk
    cls = data.skill_class.get(sid)
    return hard + total_of(tot, 127) + (total_of(tot, 83, cls) if cls not in (None, 255) else 0) \
        + total_of(tot, 107, sid) + osk


def skill_attack(data, sid, lvl, levels=None, bonus=0, ulvl=1):
    """(source weapon damage in 128ths, (skill min, max physical damage), attack rating %, (min, max elemental
    damage)) of a skill at a level, from skills.bin (srcdam, mindam / maxdam, tohit, emin / emax with their per-level
    steps and formulas; levels / bonus / ulvl: the character's hard points, + all skills and level, for the formulas
    that read other skills - Earth Talons' lightning comes from Charged Talons). None for no skill or a skill that
    uses no weapon damage (srcdam 0)."""
    if not sid:
        return None
    import mxl_skilldesc as SD
    try:
        t = SD.tables(data)
        src = t.sk[sid][0x1a5]
    except Exception:
        return None
    if not src:
        return None
    lv = dict(levels or {})
    lv.setdefault(sid, lvl)
    c = SD.Calc(t, lv, ulvl, bonus=bonus)
    c._self, c._blvl = sid, None
    phys, toht, elem = (0, 0), 0, (0, 0)
    if lvl > 0:
        try:
            phys = (c.phys(sid, lvl), c.phys(sid, lvl, True))
            toht = c.code('toht', sid, lvl)
        except Exception:
            pass
        try:
            elem = (max(c.elem(sid, lvl), 0), max(c.elem(sid, lvl, True), 0))
        except Exception:
            pass
    return src, phys, int(toht or 0), elem


def skill_damage(dmg, sk):
    """Page 1's Damage box for the skill on a mouse button (weapon_damage's dict; sk from skill_attack). The game
    (skilldesc descdam 5): (physical + elemental + poison, as
    for Attack) x srcdam / 128, + a second copy of the weapon damage (unit stats 21/22, before any %) x srcdam / 128
    (the weapon counted once more), + the skill's own physical and elemental damage.
    In game (test-druid): Raid 1089 x 90/128 + 110 x 90/128 + 8 = 850, 2226 -> 1781; Earth Talons 1089 + 110 + 101
    = 1300, 2226 + 296 + 202 = 2724; with the Crystal Sword 1287 + 40 + 101 = 1428. dmg unchanged when sk is None."""
    if dmg is None or sk is None:
        return dmg
    src, (slo, shi), _toht, (elo, ehi) = sk
    lo = dmg['min'] * src // 128 + dmg['pre'][0] * src // 128 + slo + elo
    hi = dmg['max'] * src // 128 + dmg['pre'][1] * src // 128 + shi + ehi
    return dict(dmg, min=max(lo, 1), max=max(hi, lo + 1), src=src)


def attack_rating(data, cls, tot, dexterity, level=1):
    """Attack rating as the stat screen shows it: (5 x dexterity - 35 + the class's ToHitFactor (charstats) + the
    items' flat attack rating) x (100 + the items' attack rating %) / 100. Base part checked on the seven level-1
    screenshots (dexterity 20 / 25 / 35 -> 75 / 100 / 150)."""
    return attack_rating_parts(data, cls, tot, dexterity, level)[0]


def attack_rating_parts(data, cls, tot, dexterity, level=1, skill_pct=0):
    """(attack rating, the items' flat attack rating (stat 19), the items' attack rating % (stat 119)): the one
    computation behind page 1's two Attack Rating boxes and the Attack Rating row of the game's page 2."""
    tohit = 10
    try:
        r = data._rows('charstats')[cls]
        if len(r) == 196:
            tohit = struct.unpack_from('<i', r, 0x3C)[0]
    except Exception:
        pass
    flat = item_sum(tot, data, 19, level)
    pct = item_sum(tot, data, 119, level)
    return (5 * dexterity - 35 + tohit + flat) * (100 + pct + skill_pct) // 100, flat, pct


MAX_RES = {39: 40, 41: 42, 43: 44, 45: 46}     # resistance -> its "maximum resist" stat
RES_CAP, RES_HARD_CAP = 75, 95                  # the engine's resistance cap and the cap of cap + maximum resist


def difficulty_of(ch):
    """The difficulty the character was last in (save header 0xA8: one byte per difficulty, 0x80 = last in this
    one), None when no byte says so."""
    try:
        for k in range(3):
            if ch.head[0xA8 + k] & 0x80:
                return k
    except Exception:
        pass
    return None


def resist_penalty(data, diff):
    """The difficulty's resistance penalty (first field of the difficultylevels table: 0 / -30 / -70 in Sigma)."""
    if diff is None:
        return 0
    try:
        r = data._rows('difficultylevels')[diff]
        return struct.unpack_from('<i', r, 0)[0] if len(r) >= 4 else 0
    except Exception:
        return 0


def resistance(data, ch, sid, total, maxres):
    """(shown value, penalty, cap) of an elemental resistance as the game's page 1 shows it: the sum of the
    character and the items + the penalty of the difficulty the character was last in, capped at 75 + the items'
    "maximum resist" (at most 95)."""
    pen = resist_penalty(data, difficulty_of(ch))
    cap = min(RES_CAP + maxres, RES_HARD_CAP)
    return min(total + pen, cap), pen, cap


POISON = (57, 58, 59)                # min / max poison damage (256ths of a point per frame), length in frames
FPS = 25


def poison_damage(tot):
    """(min, max, frames, (raw min, raw max)) of the items' poison damage as the game's page 2 shows it: raw x frames
    / 512, with the lengths of several items averaged (the engine's poison count, stat 326); None without poison
    damage. In game (test-druid): raw 768-1280 over 50 frames -> 75-125 on page 2, half of what the item tooltip
    states ("Adds 150-250 Poison Damage over 2 seconds" = raw x frames / 256). One item at 50 frames cannot tell
    x frames / 512 from x 25 / 256 (the damage of one second); x frames / 512 is taken."""
    lo, hi, length = (total_of(tot, s) for s in POISON)
    if not (lo or hi):
        return None
    n = max((tot.get('n') or {}).get(59, 0), 1)
    frames = length // n
    return lo * frames // 512, hi * frames // 512, frames, (lo, hi)


# ---- passive skills: the "passive stats" of skills.bin (0x98: five stats, their formulas at 0xA4)
PASSIVE_SKIP = frozenset((0, 1, 2, 3, 359, 360, 361, 362, 17, 18, 19, 21, 22, 23, 24, 25, 119, 299, 300, 442,
                          83, 97, 107, 127))
# ^ not taken from skills: the attributes and what feeds page 1's Damage / Attack Rating (still worked out without
#   skills), and the skill levels themselves


class _CalcStats(dict):
    """The character's stats as skill formulas read them (stat('n'.accr)): attributes as the stat screen totals
    them, other stats stored + items (life / mana / stamina in 256ths, as the engine keeps them)."""
    def __init__(self, ch, data, tot):
        super().__init__()
        self.ch, self.data, self.tot = ch, data, tot

    def __bool__(self):                  # Calc takes `stats or {}`: never empty for it
        return True

    def get(self, sid, default=0):
        if sid not in self:
            ch, data, tot = self.ch, self.data, self.tot
            if sid in ATTR_IDS.values():
                v = attribute_total(ch, data, tot, sid)
            else:
                v = char_stat(ch, sid) + item_sum(tot, data, sid, ch.level)
                if sid in FIXED:
                    v <<= 8
            self[sid] = v
        return dict.get(self, sid, default)


def skill_passives(ch, data, tot):
    """{stat id: value} of the passive stats of the skills the character has hard points in (life / mana / stamina
    in whole points), e.g. Druid: Barkskin +x % Bonus to Defense and +life, Meditation +x % Maximum Mana and mana
    regeneration, the hidden "damage reduction from all sources" skill's stat 184 (Grit on page 1). The aura / form
    stats (0x54) are left out (only while the form or aura is on); passives gated on a form (Ferocity, Steel
    Wings: clc1 = skill('Wereowl Form'.aura)) come out 0, as unmorphed in game. Formulas: mxl_skilldesc.Calc with
    blvl = hard points and lvl = skill_level (items' + skills included). A passive restricted to an item type
    (0x96) counts when an equipped item of the active set is of that type. Checked on test-druid (level 81): life
    2217 -> 3657, mana % 0 -> 16, Bonus to Defense 60 -> 456 %, mana regeneration 411 -> 424 %, Grit 11 %."""
    out = {}
    try:
        import mxl_skilldesc as SD
        t = SD.tables(data)
        hard = {s: int(v) for s, v in ch.skill_levels().items() if int(v or 0) > 0}
    except Exception:
        return out
    stats = _CalcStats(ch, data, tot)
    worn = None
    for sid in sorted(hard):
        try:
            r = t.sk[sid]
            pst = struct.unpack_from('<5H', r, 0x98)
            itype = struct.unpack_from('<H', r, 0x96)[0]
        except Exception:
            continue
        if all(s in (0, 0xFFFF) for s in pst):
            continue
        if itype:
            if worn is None:
                try:
                    active2 = struct.unpack_from('<I', ch.head, 0x10)[0] == 1
                    worn = [data.type_ancestors(data.base(e.it['code']).type) for slot, e in ch.equipped().items()
                            if slot not in ((4, 5) if active2 else (11, 12))]
                except Exception:
                    worn = []
            if not any(itype in anc for anc in worn):
                continue
        cls = data.skill_class.get(sid)
        bonus = total_of(tot, 127) + (total_of(tot, 83, cls) if cls not in (None, 255) else 0)
        calc = SD.Calc(t, hard, ch.level, stats, bonus)
        lvl = skill_level(ch, data, tot, sid)
        for i, s in enumerate(pst):
            if s in (0, 0xFFFF) or s in PASSIVE_SKIP:
                continue
            try:
                v = int(calc.eval(t.code, t.field(sid, 0xa4 + 4 * i), sid, lvl) or 0)
            except Exception:
                continue
            if s in FIXED:
                v >>= 8
            if v:
                out[s] = out.get(s, 0) + v
    return out


def defense_total(armour, flat, dexterity, pct):
    """Page 1 Defense: (the worn armour pieces' defense + other flat defense + dexterity / 4) x (100 + the total
    "Bonus to Defense" %, items and skills: page 3's row) / 100. test-druid: (7876 + 843 / 4) x 556 / 100 = 44958, the
    game's number (the saved defense of an ethereal piece already holds its +50 %)."""
    return (armour + flat + dexterity // 4) * (100 + pct) // 100


BLOCK_CAP = 50                        # "Max Block Chance: extends the maximum block chance above 50%" (stat 213)


def block_factor(data, cls):
    """The class's BlockFactor (charstats 0x49, next to class_factors' fields), None when unreadable."""
    try:
        r = data._rows('charstats')[cls]
        if len(r) == 196:
            return r[0x49]
    except Exception:
        pass
    return None


def has_shield(ch, data):
    """The shield of the active weapon set as (item, base), None without one."""
    try:
        active2 = struct.unpack_from('<I', ch.head, 0x10)[0] == 1
        eq = ch.equipped()
        shield = next((i for i, t in enumerate(data.itypes) if t and t[0] == 'shld'), None)
    except Exception:
        return None
    if shield is None:
        return None
    for slot in ((11, 12) if active2 else (4, 5)):
        e = eq.get(slot)
        try:
            b = data.base(e.it['code'])
            if shield in data.type_ancestors(b.type):
                return e.it, b
        except Exception:
            continue
    return None


def block_chance(data, ch, base_block, dexterity, max_block=0):
    """Page 1 Block Chance with a shield in the active set, the base game's rule: (the shield's block + "Base Block
    Chance" (stat 20) + the class's BlockFactor) x (dexterity - 15) / (2 x level), at most 50 + "Max Block Chance".
    test-druid (Druid, BlockFactor 3, Buckler block 0, base block 2, dexterity 843, level 81): 5 x 828 / 162 = 25, the
    game's 25 %. None without a shield or without the class's factor."""
    sh = has_shield(ch, data)
    fac = block_factor(data, ch.cls)
    if sh is None or fac is None:
        return None
    try:
        own = int(getattr(sh[1], 'block', 0) or 0)
    except Exception:
        own = 0
    v = (own + base_block + fac) * max(dexterity - 15, 0) // (2 * max(ch.level, 1))
    return max(0, min(v, BLOCK_CAP + max_block))


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
AR_ROW = (19, 119)                    # page 2 "Attack Rating": total attack rating | the items' attack rating %
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


def grouped(text, tx=None, font=None):
    """A value as the game draws it: a single number of four digits or more with thousands commas ("3,657",
    "44,958", "1,173%"); ranges ("850-1781"), several numbers and other texts as they are. Only for drawing: the
    values (derived / game_value) keep plain digits."""
    import re
    m = re.fullmatch(r'(-?)(\d{4,})(%?)', text or '')
    if not m or (tx is not None and not tx.has(',', font)):
        return text
    return m.group(1) + f'{int(m.group(2)):,}' + m.group(3)


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
        self.split = False                # the two pages at the left and right edges, the scene (char view) between
        self.offsets = self._load_offsets()   # split: how far page A / B was moved from its edge (page pixels)
        self._fit_wh = None
        self._drag = None                 # (slot, pointer x at the press, offset at the press)
        self._min_saved = None            # the toplevel's minsize before the split layout raised it
        self._slot_regs = []
        self._photos = []
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
        self._items = [self._item, self.cv.create_image(0, 0, anchor='nw')]
        cv = self.cv
        cv.bind('<B1-Motion>', self.on_drag)
        cv.bind('<Double-Button-1>', self.on_double)
        self._watch_shown()
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
        hit = icons.get(sid)
        if hit is None and sid is not None and ('other', sid) not in icons:
            icons[('other', sid)] = None
            hit = icons[('other', sid)] = self._other_icon(sid)
        return hit if hit is not None else icons.get(('other', sid))

    def _other_icon(self, sid):
        """Icon of a skill outside the class's trees (Attack, oskills from items, another class's skill): its
        skilldesc cel (u16 at 22) in icons-shared.dc6, or in icons-<class>.dc6 of the skill's own class."""
        try:
            import mxl_d2ui_dc6 as DC6
            from PIL import Image
            data = self.win.data
            srows, sd_rows = data._rows('skills'), data._rows('skilldesc')
            sd = struct.unpack_from('<H', srows[sid], 404)[0]
            if not (sid == 0 or 0 < sd < len(sd_rows)):
                return None
            cel = struct.unpack_from('<H', sd_rows[sd], 22)[0]
            owner = data.skill_class.get(sid, 255)
            sheet = data._rows('playerclass')[owner][:4].decode('latin1').strip() if owner < 7 else 'shared'
            key = ('sheet', sheet)
            if key not in self._pil:
                self._pil[key] = DC6.dc6_frames(self.art.read(
                    'data\\global\\themes\\classic_sigma\\game\\skills\\icons-' + sheet + '.dc6'))
            cels = self._pil[key]
            if cel >= len(cels):
                return None
            w, h, rgba = DC6.to_rgba(cels[cel], self.art.pal())
            return Image.frombytes('RGBA', (w, h), bytes(self.art._bright(rgba)))
        except Exception as e:
            print('stat screen: no icon for skill', sid, e)
            return None

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
        self._fit_wh = (W, H)
        k1 = min(W / PANEL_W, max(H / PANEL_H, MIN_K), MAX_K)
        k2 = min(W / (2 * PANEL_W), max(H / PANEL_H, MIN_K), MAX_K)
        ks = min((W - self.min_scene()) / (2 * PANEL_W), H / PANEL_H, MAX_K)
        split = len(self.pages) > 1 and ks >= K_SPLIT      # the split layout: pages at the edges, the scene between
        spread = 2 if split or (len(self.pages) > 1 and k2 >= k1 * SPREAD_LOSS) else 1
        k = ks if split else (k2 if spread == 2 else k1)
        k = max(0.5, int(k * 64) / 64)
        width = W if split else round(PANEL_W * k) * spread
        if (abs(k - self.k) > 1e-6 or spread != self.spread or split != self.split or self._photo is None
                or (split and int(self.cv.cget('width')) != width)):
            self.k = k
            self.spread = spread
            self.split = split
            self.cancel_edit()
            self._layout()
            self.cv.configure(width=width if split else round(PANEL_W * k) * len(self.shown), height=round(PANEL_H * k))
            self.redraw()
        else:
            try:
                self.frame.event_generate('<<ScenePlaced>>')   # the space changed: the character view follows
            except tk.TclError:
                pass
        self._apply_minsize()

    # ------------------------------------------------------------------ split layout
    def min_scene(self):
        try:
            ui = max(0.5, self.cv.winfo_fpixels('1i') / 96.0)
        except tk.TclError:
            ui = 1.0
        return round(MIN_SCENE * ui)

    def min_size(self):
        """The smallest (width, height) of the space fit() gets that still holds the split layout."""
        return (2 * round(PANEL_W * K_SPLIT) + self.min_scene() + 2, round(PANEL_H * K_SPLIT) + 2)

    def _apply_minsize(self):
        """The toplevel's minsize: never narrower than two pages + the scene, while the Stats page shows the split
        layout. Only when the window already holds it (a small screen, 800x600, keeps the single page and no
        minsize); the old minsize comes back when the page is hidden."""
        try:
            top = self.cv.winfo_toplevel()
            if not self.split or self._fit_wh is None or not self.frame.winfo_viewable():
                self._restore_minsize()
                return
            W, H = self._fit_wh
            nw, nh = self.min_size()
            mw = top.winfo_width() - W + nw
            mh = top.winfo_height() - H + nh
            if mw > top.winfo_width() or mh > top.winfo_height():
                return
            if self._min_saved is None:
                self._min_saved = tuple(top.minsize())
            want = (max(mw, self._min_saved[0]), max(mh, self._min_saved[1]))
            if tuple(top.minsize()) != want:
                top.minsize(*want)
        except (tk.TclError, TypeError, ValueError):
            pass

    def _watch_shown(self):
        """The minsize follows whether the page can be seen: <Map> / <Unmap> of the frame and of every parent up to
        the toplevel (a hidden Character sub-page or main tab unmaps a parent, not the frame itself)."""
        def changed(_e=None):
            try:
                self.frame.after_idle(self._apply_minsize)
            except tk.TclError:
                pass
        w = self.frame
        while w is not None:
            if w.winfo_toplevel() is w:
                break
            w.bind('<Map>', changed, add='+')
            w.bind('<Unmap>', changed, add='+')
            w = w.master

    def _restore_minsize(self):
        if self._min_saved is None:
            return
        try:
            self.cv.winfo_toplevel().minsize(*self._min_saved)
        except tk.TclError:
            pass
        self._min_saved = None

    def _load_offsets(self):
        try:
            import settings
            v = settings.get(OFFSETS_SETTING)
            return [max(0.0, float(v[0])), max(0.0, float(v[1]))]
        except Exception:
            return [0.0, 0.0]

    def _save_offsets(self):
        try:
            import settings
            settings.put(OFFSETS_SETTING, [round(self.offsets[0], 1), round(self.offsets[1], 1)])
        except Exception:
            pass

    def max_offset(self):
        """How far (page pixels) a page may move from its edge: up to the middle, the scene keeping its minimum."""
        try:
            W = int(self.cv.cget('width'))
        except tk.TclError:
            return 0
        pw = round(PANEL_W * self.k)
        return max(0, (W - 2 * pw - self.min_scene()) // 2) / self.k

    def slot_x(self, slot):
        """Canvas x of a shown page (slot 0 left, 1 right)."""
        pw = round(PANEL_W * self.k)
        if not self.split:
            return slot * pw
        m = self.max_offset()
        off = round(min(self.offsets[slot], m) * self.k)
        if slot == 0:
            return off
        return int(self.cv.cget('width')) - pw - off

    def scene_box(self):
        """The scene between the two pages: (x, y, w, h) in the canvas, or None outside the split layout."""
        if not self.split or len(self.shown) < 2:
            return None
        pw, ph = round(PANEL_W * self.k), round(PANEL_H * self.k)
        x0 = self.slot_x(0) + pw
        return x0, 0, self.slot_x(1) - x0, ph

    def _place_slots(self):
        """Puts the page images where they belong and their click regions with them."""
        regions = []
        for slot, item in enumerate(self._items):
            if slot < len(self._photos):
                x = self.slot_x(slot)
                self.cv.coords(item, x, 0)
                self.cv.itemconfigure(item, image=self._photos[slot], state='normal')
            else:
                self.cv.itemconfigure(item, image='', state='hidden')
        for slot, (reg, page) in enumerate(self._slot_regs):
            dx = self.slot_x(slot) / self.k
            regions += [(kind, key, (x + dx, y, w, h), page) for kind, key, (x, y, w, h) in reg]
        self._regions = regions
        try:
            self.frame.event_generate('<<ScenePlaced>>')
        except tk.TclError:
            pass

    def move_page(self, slot, offset, save=True):
        self.offsets[slot] = max(0.0, min(float(offset), self.max_offset()))
        self._place_slots()
        if save:
            self._save_offsets()

    def _slot_at(self, x):
        pw = round(PANEL_W * self.k)
        for slot in range(len(self.shown)):
            if self.slot_x(slot) <= x < self.slot_x(slot) + pw:
                return slot
        return None

    def on_drag(self, ev):
        d = self._drag
        if d is None:
            return
        slot, x0, off0 = d
        dx = (ev.x - x0) / self.k
        self.move_page(slot, off0 + (dx if slot == 0 else -dx), save=False)

    def on_double(self, ev):
        """Double click on a page's empty part: the page back at its edge. Anywhere else the second click of a
        double click is a click (<Double-Button-1> takes the place of <ButtonPress-1>: quick clicks on + count)."""
        kind, _key, _box = self._at(ev)
        slot = self._slot_at(ev.x) if self.split else None
        if kind is None and slot is not None:
            self._drag = None
            self.move_page(slot, 0)
            return
        return self.on_press(ev)

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
            slot_regs, photos = [], []
            for slot, page in enumerate(self.shown):
                reg = []
                boost = min(1 / self.k, TEXT_BOOST) if self.k < 1 else 1
                # (the game's pages only: their texts have room in their cells; the editor's lists fill theirs)
                texts = [] if boost > 1 and (page == 'main' or page.startswith('game')) else None
                img = self.compose(page, reg, texts)
                slot_regs.append((reg, page))
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
                photos.append(ImageTk.PhotoImage(img, master=self.cv))
            self._slot_regs = slot_regs
        except Exception as e:                    # never a dead tab: the reason on the status line
            import traceback
            traceback.print_exc()
            self.win.set_bar(str(e), error=True)
            return
        self._photos = photos
        self._photo = photos[0] if photos else None
        self._place_slots()

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
                font = 'font6' if small and key in RES_IDS else 'font16'
                tx.draw(out, grouped(val, tx, font), cx, cy, font, WHITE)
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

    def passive(self, sid):
        """The passive skills' share of a stat (skill_passives; whole points), cached per character state."""
        win = self.win
        sim, tot = win.st_sim, win.st_totals()
        try:
            key = (id(tot), sim.level, tuple(sorted(sim.skill_levels().items())),
                   tuple(char_stat(sim, a) for a in range(4)))
        except Exception:
            return 0
        hit = getattr(self, '_passives', None)
        if hit is None or hit[0] != key:
            hit = self._passives = (key, skill_passives(sim, win.data, tot))
        return hit[1].get(sid, 0)

    def attr_total(self, sid):
        """An attribute as the game totals it: (stored + items) raised by the items' "+x %"."""
        return attribute_total(self.win.st_sim, self.win.data, self.win.st_totals(), sid)

    def derived(self, key):
        """(text or None, tooltip) of a value of page 1 the game computes."""
        win = self.win
        tot = win.st_totals()
        if tot['error']:
            return None, tot['error']
        rest = T('ss.tip.rest3', 'Not included: skills, buffs, difficulty penalty and caps of the game.')
        if key in RES_IDS:
            sid = RES_IDS[key]
            own, parts = self._split(sid)
            total = own + sum(parts.values()) + self.passive(sid)
            if sid not in MAX_RES:
                return f'{total}%', self._where(own, parts) + '\n' + rest
            mo, mparts = self._split(MAX_RES[sid])
            shown, pen, cap = resistance(win.data, win.st_sim, sid, total,
                                         mo + sum(mparts.values()) + self.passive(MAX_RES[sid]))
            diff = difficulty_of(win.st_sim)
            return f'{shown}%', self._where(own, parts) + '\n' + T(
                'ss.tip.res_cap', 'Sum {total} %, {pen:+d} % in {diff}, capped at {cap} % (75 + maximum resist, '
                'at most 95).', total=total, pen=pen, cap=cap,
                diff=T('ch.diff.%d' % diff, ('Normal', 'Nightmare', 'Hell')[diff]) if diff is not None
                else T('ss.tip.no_diff', 'no difficulty marked in the save')) + '\n' + T(
                'ss.tip.rest5', 'Not included: skills, buffs and quest rewards.')
        if key == 'defense':
            own, parts = self._split(31)
            armour = tot['defense']
            flat = own + sum(parts.values()) + self.passive(31)
            dex = self.attr_total(2)
            pct = self._bonus_total(171)
            return str(defense_total(armour, flat, dex, pct)), T(
                'ss.tip.defense3', '(Defense of the worn armour {armour} + other flat defense {flat} + dexterity '
                '{dex} / 4) x (100 + {pct} % Bonus to Defense of items and skills) / 100.', armour=armour, flat=flat,
                dex=dex, pct=pct) + '\n' + T('ss.tip.defense4', 'Not included: auras, forms and buffs.')
        if key == 'block':
            base = self._bonus_total(20)
            v = block_chance(win.data, win.st_sim, base, self.attr_total(2), self._bonus_total(213))
            if v is None:
                return None, T('ss.tip.block0', 'Block chance: no shield in the active weapon set.')
            return f'{v}%', T('ss.tip.block', '(Base Block Chance {base} % + shield + class factor) x (dexterity - 15) '
                              '/ (2 x level), at most 50 % + Max Block Chance.', base=base)
        if key == 'grit':
            v = self._bonus_total(184)
            return f'{v}%', T('ss.tip.grit', 'Grit (damage reduction from all sources): items and passive skills.')
        if key.startswith('damage'):
            dmg = self.weapon_damage()
            if dmg is None:
                return None, T('ss.tip.game', 'computed by the game')
            sid, lvl, sk = self.button_skill(key)
            forms = '\n' + T('ss.tip.dmg_forms2', 'Not included: auras and buffs.')
            dd = skill_descdam(win.data, sid or 0)
            hands = hand_weapons(win.st_sim, win.data)
            dual = len(hands) > 1 and win.st_sim.cls in DUAL_WIELD_CLASSES
            if sk is not None and dd != 1:          # weapon skill path (descdam 5): both hands added when dual
                if dual:
                    dmg = self.weapon_damage(both=True) or dmg
                shown = skill_damage(dmg, sk)
                return damage_text(shown['min'], shown['max']), self.damage_tip(dmg) + '\n' + \
                    self.skill_note(sid, lvl, sk) + forms
            if dual:                                 # Attack path, dual wield: one range per hand
                per = [self.hand_damage(sl) for sl, _it, _b in hands]
                if all(per):
                    if sk is not None:
                        per = [skill_damage(dict(p, pre=(0, 0)), sk) for p in per]
                    return ' '.join(damage_text(p['min'], p['max']) for p in per), '\n'.join(
                        self.damage_tip(p) for p in per) + '\n' + T(
                        'ss.tip.dual', 'Dual wield: one range per weapon, the other hand\'s item switched off.') + forms
            shown = skill_damage(dict(dmg, pre=(0, 0)), sk) if sk is not None else dmg
            return damage_text(shown['min'], shown['max']), self.damage_tip(dmg) + '\n' + \
                self.skill_note(sid, lvl, sk) + forms
        if key.startswith('attack_rating'):
            sid, lvl, sk = self.button_skill(key)
            ar, flat, pct = self.attack_rating(sk[2] if sk else 0)
            tip = self.ar_tip(flat, pct)
            if sk and sk[2]:
                tip += '\n' + T('ss.tip.ar_sk', '{skill} (level {lvl}): attack rating {pct:+d} % included.',
                                 skill=self.win._sk_name(sid), lvl=lvl, pct=sk[2])
            return str(ar), tip
        return None, T('ss.tip.game', 'computed by the game')

    def _bonus_total(self, sid):
        """Stored + items (per-level stats included) + passive skills of one stat."""
        own, parts = self._split(sid)
        return own + sum(parts.values()) + self.passive(sid)

    def attack_rating(self, skill_pct=0):
        """(attack rating, items' flat, items' %) of page 1 and of the Attack Rating row of the game's page 2;
        skill_pct: the attack rating % of the skill on the mouse button (page 1 only), added to the items' %."""
        win = self.win
        sim = win.st_sim
        return attack_rating_parts(win.data, sim.cls, win.st_totals(), self.attr_total(2), sim.level, skill_pct)

    def button_skill(self, key):
        """(skill id, effective level, skill_attack tuple or None) of the mouse button of a page-1 box
        ('..._1' = left, '..._2' = right)."""
        win = self.win
        sim = win.st_sim
        sid = mouse_skill(sim, 'left' if key.endswith('_1') else 'right')
        if not sid:
            return sid, 0, None
        tot = win.st_totals()
        lvl = skill_level(sim, win.data, tot, sid)
        try:
            hard = {k: v for k, v in sim.skill_levels().items() if v}
        except Exception:
            hard = {}
        cls = win.data.skill_class.get(sid)
        bonus = total_of(tot, 127) + (total_of(tot, 83, cls) if cls not in (None, 255) else 0)
        return sid, lvl, skill_attack(win.data, sid, lvl, hard, bonus, getattr(sim, 'level', 1) or 1)

    def skill_note(self, sid, lvl, sk):
        if not sid:
            return T('ss.tip.dmg_attack', 'Normal attack.')
        name = self.win._sk_name(sid)
        if sk is None:
            return T('ss.tip.dmg_noweap', '{skill} uses no weapon damage: the plain weapon damage is shown.', skill=name)
        return T('ss.tip.dmg_sk4', '{skill} (level {lvl}): {pct} % of the damage, + {pct} % of the weapon damage once '
                 'more, + its own {lo}-{hi} physical and {elo}-{ehi} elemental damage.', skill=name, lvl=lvl,
                 pct=sk[0] * 100 // 128, lo=sk[1][0], hi=sk[1][1], elo=sk[3][0], ehi=sk[3][1])

    def ar_tip(self, flat, pct):
        return T('ss.tip.ar', 'Attack rating: 5 x dexterity - 35 + class bonus, + items {flat}, then {pct:+d} % from '
                 'items.', flat=flat, pct=pct) + '\n' + T('ss.tip.ar_skill', 'Not included: skills and buffs.')

    def weapon_damage(self):
        win = self.win
        sim = win.st_sim
        return weapon_damage(sim, win.data, win.st_totals(), self.attr_total(0), self.attr_total(2), sim.level)

    def hand_damage(self, slot):
        """Attack damage of one hand of a dual-wielding character: the other hand's item switched off (its stats
        and its share of the attributes), as the game's per-hand lines do."""
        win = self.win
        sim, data = win.st_sim, win.data
        other = {4: 5, 5: 4, 11: 12, 12: 11}.get(slot)
        key = (id(win.st_totals()), slot)
        hit = getattr(self, '_hand_tot', None)
        if hit is None or hit[0] != key:
            hit = self._hand_tot = (key, char_totals(sim, data, exclude=(other,)))
        tot = hit[1]
        return weapon_damage(sim, data, tot, attribute_total(sim, data, tot, 0), attribute_total(sim, data, tot, 2),
                             sim.level, slot=slot)

    def damage_tip(self, dmg):
        return T('ss.tip.dmg2', '{weapon}: base {lo}-{hi}{eth}, enhanced damage +{ed} %, +{flo} / +{fhi} damage from '
                 'the equipped items, then {pct:+d} % (weapon physical damage, strength / dexterity bonus) = physical '
                 '{plo}-{phi}; + elemental damage of the items {elo}-{ehi}.',
                 weapon=dmg['name'] or T('ss.unarmed', 'Unarmed'), lo=dmg['base'][0], hi=dmg['base'][1],
                 eth=T('ss.tip.eth', ' (ethereal +25 %)') if dmg.get('eth') else '',
                 ed=dmg['ed'][1], flo=dmg['flat'][0], fhi=dmg['flat'][1], pct=dmg['pct'],
                 plo=dmg['phys'][0], phi=dmg['phys'][1], elo=dmg['ele'][0], ehi=dmg['ele'][1])

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
            return str(dmg['phys'][0 if sid == 21 else 1]), self.damage_tip(dmg), None
        if kind == T_STAT and sid in AR_ROW and not flags & F_BASE:
            # the Attack Rating row: the items' flat attack rating (stat 19) | the items' attack rating % (in game,
            # test-druid: "0 | 1,173%" while page 1 shows 60,671 / 53,338)
            if tot['error']:
                return None, tot['error'], None
            ar, flat, pct = self.attack_rating()
            return (str(flat) if sid == 19 else f'{pct}%'), self.ar_tip(flat, pct), None
        if kind == T_STAT and sid in POISON[:2] and not flags & F_BASE:
            if tot['error']:
                return None, tot['error'], None
            p = poison_damage(tot)
            if p is None:
                return '0', T('ss.tip.poison0', 'No poison damage on the items.'), None
            return str(p[0 if sid == 57 else 1]), T(
                'ss.tip.poison2', 'Poison damage of the items as the game\'s page 2 shows it: {lo}-{hi} (raw '
                '{rlo}-{rhi} x {frames} frames / 512; {sec} seconds, the lengths of {n} items averaged).', lo=p[0], hi=p[1],
                sec=f'{p[2] / FPS:g}', rlo=p[3][0], rhi=p[3][1], frames=p[2],
                n=max((tot.get('n') or {}).get(59, 0), 1)) + '\n' + T(
                'ss.tip.rest4', 'Not included: skills, buffs and the caps of the game.'), None
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
        skills = self.passive(sid) if param is None and sid not in PASSIVE_SKIP else 0
        v = own + items + skills
        extra = T('ss.tip.skills', 'passive skills {n:+d}', n=skills) if skills else ''
        if sid in (0, 1, 2, 3):
            pct = total_of(tot, PCT_OF[sid])
            v = v * (100 + pct) // 100
            extra = T('ss.tip.pct', 'then {pct:+d} % from items', pct=pct)
            # (+ skills: none here, attributes are not taken from skills, see PASSIVE_SKIP)
        elif sid in (7, 9, 11):
            fac = class_factors(data, sim.cls)
            attr = 3 if sid in (7, 11) else 1
            more = self.attr_total(attr) - char_stat(sim, attr)
            if fac:
                per = fac[{7: 0, 9: 1, 11: 2}[sid]]
                v += more * per // 4
                extra += (', ' if extra else '') + T(
                    'ss.tip.per_attr', '{more:+d} {attr} from items x {per}/4', more=more, per=per,
                    attr=T('ss.vitality', 'Vitality') if attr == 3 else T('ss.energy', 'Energy'))
            if sid in PCT_OF:
                pct = total_of(tot, PCT_OF[sid]) + self.passive(PCT_OF[sid])
                v = v * (100 + pct) // 100
                extra += (', ' if extra else '') + T('ss.tip.pct', 'then {pct:+d} % from items', pct=pct)
        elif kind == T_STAT_BONUS:
            isc = data.isc.get(sid) or {}
            base = {299: 0, 300: 2}.get(sid, isc.get('op_base'))
            w = active_weapon(sim, data) if sid in (299, 300) else None
            per100 = (getattr(w[2], 'dmg_bonus', None) or (0, 0))[sid - 299] if w else 0
            if sid == 299:                     # 442 "Additional Strength Damage Bonus" feeds stat 25 the same way
                items += sum(total_of(tot, x) for x in STR_BONUS if x != 299)
            if (not items and w is None) or base not in (0, 2):     # with a weapon: its bonus, 0 % included
                return None, T('ss.tip.class_rule', '{name} computed by the game from the class and the attribute.',
                               name=name), None
            attr = self.attr_total(base)
            v = (items * attr >> int(isc.get('op_param') or 0)) + per100 * attr // 100
            extra = T('ss.tip.per_point2', 'weapon {per100} % per 100 points, items {items}/256 % per point, '
                      'x {attr}', per100=per100, items=items, attr=attr)
        tip = name + ': ' + self._where(own, parts) + (' (' + extra + ')' if extra else '')
        cap = el.get('cap') or 0
        if kind == T_RESIST and not cap:       # page 3 Poison Length Red.: items 155 %, the game shows 75 %
            cap = RES_CAP
        if cap and v > cap:                    # the table's own maximum (absorb %: 40)
            tip += '\n' + T('ss.tip.cap', 'Sum {v}{s}, capped at {cap}{s} by the game\'s table.', v=v, cap=cap, s=suffix)
            v = cap
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
        text = grouped(text, tx, font)
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
            if key in P1_DERIVED:
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
        elif kind is None and self.split:
            slot = self._slot_at(ev.x)              # the empty part of a page: drag it left / right
            if slot is not None:
                self._drag = (slot, ev.x, min(self.offsets[slot], self.max_offset()))

    def on_release(self, ev):
        if self._drag is not None:
            self._drag = None
            self._save_offsets()
            return
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
