"""Item tooltips from uniqueitems / setitems / runes (runeword) rows (txt tables, no Tk).

What the game does (D2Client item description, see THIRD-PARTY-NOTICES: facts from the MIT-licensed
fredivivus reconstruction and the D2MOO property functions; Median's extra descfuncs from our names DB):
- every property code (properties.txt) gives up to seven stats through its func (1/2/8 value, 3 the previous
  value, 5/6/7 the damage stats, 10 skill tab, 11 skill on event, 15/16/17 min / max / param, 19 charges,
  21 layer = val, 22 layer = skill ...);
- the stats with a descfunc are written in descpriority order (highest first); a dgrp group whose stats all
  have the same value gets one line (dgrpfunc / dgrpstrpos: "+2 to all Attributes", "All Resistances +20");
- min / max pairs combine ("Adds 1-12 lightning damage", "+250% Enhanced Damage", poison over N seconds);
- op 2-5 stats are scaled by op base (character level: (level * value) >> op param), then >> valshift;
- descfunc 1-28 format the number with descstrpos / descstrneg / descstr2 by descval (0 text only, 1 number
  first, 2 number last).
Previews show rolled values as "min-max". What is not understood (a Median descfunc the tooltip does not
know, an unknown property code) comes out as a grey 'raw' line, never guessed.

Lines: [(segments [(text, colour code)], kind)], top to bottom; kinds: name, base, info, req, prop, set
(green partial-set bonus), raw, blank."""
import re

from ..itemgen.stats import proc_level, skill_layer, skill_tab_layer
from .data import GameData, to_int
from .skill import split_colours

SPACE, PERCENT, PLUS, TO = 3995, 4001, 4002, 4003
COMBINED = {48: (3612, 3613), 54: (3614, 3615), 50: (3616, 3617), 52: (3618, 3619)}   # min stat: (one, range)
COMBINED_MAX = {48: 49, 54: 55, 50: 51, 52: 53}
POISON = (57, 58, 59, 3620, 3621)
DMG_RANGE = 3623
ED_TEXT = 10023
QUALITY_COLOUR = {'unique': '4', 'set': '2', 'runeword': '4'}


class V:
    """A stat value that may be a range (preview of min-max rolls)."""
    __slots__ = ('lo', 'hi')

    def __init__(self, lo, hi=None):
        hi = lo if hi is None else hi
        self.lo, self.hi = min(lo, hi), max(lo, hi)

    def map(self, f):
        return V(f(self.lo), f(self.hi))

    def __eq__(self, o):
        return isinstance(o, V) and (self.lo, self.hi) == (o.lo, o.hi)

    def __hash__(self):
        return hash((self.lo, self.hi))

    def __bool__(self):
        return bool(self.lo or self.hi)

    def __repr__(self):
        return self.num()

    def num(self):
        if self.lo == self.hi:
            return str(self.lo)
        return ('%d-%d' if self.lo >= 0 else '%d to %d') % (self.lo, self.hi)

    def pos(self):
        return self.lo >= 0 and self.hi > 0 if self.lo != self.hi else self.lo > 0


def cformat(fmt, args):
    """The game's sprintf for %d / %s / %u / %+d / %%; args may be V (ranges) or str."""
    it = iter(args)

    def rep(m):
        if m.group(0) == '%%':
            return '%'
        try:
            a = next(it)
        except StopIteration:
            return m.group(0)
        if isinstance(a, V):
            s = a.num()
            return ('+' + s) if '+' in m.group(0) and a.lo >= 0 else s
        return str(a)
    return re.sub(r'%%|%[+-]?\d*(?:l)?[dsuiS]', rep, fmt)


class ItemTables:
    def __init__(self, gd):
        self.gd = gd
        self.isc = gd.table('itemstatcost')
        self.props = gd.table('properties')
        self.skills = gd.table('skills')
        self.sd = gd.table('skilldesc')
        self.cs = gd.table('charstats')
        self.cs_rows = [r for r in range(len(self.cs)) if self.cs.get(r, 'class').strip().lower()
                        not in ('', 'expansion')]
        self.stat_id = {}
        has_id = self.isc.has('ID')
        for r in range(len(self.isc)):
            nm = self.isc.get(r, 'Stat').strip().lower()
            sid = to_int(self.isc.get(r, 'ID'), r) if has_id else r
            if nm:
                self.stat_id.setdefault(nm, sid)
        self.row_of = {}
        for r in range(len(self.isc)):
            sid = to_int(self.isc.get(r, 'ID'), r) if has_id else r
            self.row_of.setdefault(sid, r)

    def s(self, sid, col):
        r = self.row_of.get(sid, -1)
        return self.isc.get(r, col) if r >= 0 else ''

    def n(self, sid, col):
        return to_int(self.s(sid, col))

    def text(self, key):
        return self.gd.text(key)

    def tid(self, i, default=''):
        return (self.gd.text_id(i) or default).rstrip('\n')

    def skill_index(self, p):
        p = str(p or '').strip()
        if not p:
            return -1
        if re.match(r'^-?\d+$', p):
            return int(p)
        return self.skills.find(p, 'skill')

    def skill_name(self, sk):
        if not 0 <= sk < len(self.skills):
            return 'skill #%d' % sk
        k = self.skills.get(sk, 'skilldesc').strip()
        r = self.sd.find(k) if k else -1
        t = self.text(self.sd.get(r, 'str name')) if r >= 0 else ''
        return t or self.skills.get(sk, 'skill')

    def skill_class(self, sk):
        c = self.skills.get(sk, 'charclass').strip().lower()
        if not c:
            return -1
        pc = self.gd.table('playerclass')
        codes = [pc.get(i, 'code').strip().lower() for i in range(len(pc))
                 if pc.get(i, 'code').strip().lower() not in ('', 'expansion')]
        return codes.index(c) if c in codes else -1

    def charstat(self, cls, col):
        if not 0 <= cls < len(self.cs_rows):
            return ''
        return self.text(self.cs.get(self.cs_rows[cls], col))


# ------------------------------------------------------------------------------- properties -> stats

class Stats:
    def __init__(self):
        self.vals = {}      # (stat, layer) -> V
        self.order = []
        self.raw = []       # (text, reason)

    def add(self, sid, layer, v):
        if sid is None or sid < 0:
            return
        k = (sid, layer)
        if k in self.vals:
            o = self.vals[k]
            self.vals[k] = V(o.lo + v.lo, o.hi + v.hi)
        else:
            self.vals[k] = v
            self.order.append(k)

    def get(self, sid, layer=0):
        return self.vals.get((sid, layer), V(0))


def apply_property(it, st, code, par, mn, mx, level, ilvl=0):
    code = str(code or '').strip()
    if not code:
        return
    pr = it.props.find(code, 'code')
    if pr < 0:
        st.raw.append(('%s %s %s-%s' % (code, par, mn, mx), 'unknown property %s' % code))
        return
    lo, hi = to_int(mn), to_int(mx)
    if hi < lo and str(mx).strip() == '':
        hi = lo
    rng = V(lo, hi)
    prev = None
    for i in range(1, 8):
        fn = to_int(it.props.get(pr, 'func%d' % i))
        if not fn:
            continue
        sname = it.props.get(pr, 'stat%d' % i).strip().lower()
        sid = it.stat_id.get(sname, -1) if sname else -1
        val = to_int(it.props.get(pr, 'val%d' % i))
        layer = 0
        v = rng
        if fn in (1, 2, 8, 9, 24):
            layer = to_int(par) if str(par).strip() and fn != 2 else 0
        elif fn == 3:
            if prev is None:
                continue
            layer, v = prev
        elif fn == 5:
            for s in (21, 23, 159):
                st.add(s, 0, v)
            prev = (0, v)
            continue
        elif fn == 6:
            for s in (22, 24, 160):
                st.add(s, 0, v)
            prev = (0, v)
            continue
        elif fn == 7:
            st.add(17, 0, v)
            st.add(18, 0, v)
            prev = (0, v)
            continue
        elif fn == 10:
            layer = skill_tab_layer(to_int(par))
        elif fn == 11:
            sk = it.skill_index(par)
            lvl = hi
            if ilvl > 0 and hi <= 0 and 0 <= sk < len(it.skills):
                lvl = proc_level(ilvl, to_int(it.skills.get(sk, 'reqlevel')),
                                 to_int(it.skills.get(sk, 'maxlvl')), hi)
            layer = skill_layer(max(sk, 0), lvl)
            v = V(lo if lo > 0 else 5)
        elif fn in (13, 14):
            v = rng
        elif fn == 15:
            v = V(lo)
            if code == 'dmg-norm':
                for damage in (23, 159):
                    st.add(damage, 0, v)
        elif fn == 16:
            v = V(hi)
            if code == 'dmg-norm':
                for damage in (24, 160):
                    st.add(damage, 0, v)
        elif fn == 17:
            v = V(to_int(par)) if str(par).strip() else rng
        elif fn == 19:
            sk = it.skill_index(par)
            layer = skill_layer(max(sk, 0), hi)
            v = V(lo | (lo << 8))
        elif fn == 21:
            layer = val
        elif fn == 22:
            layer = max(it.skill_index(par), 0)
        elif fn in (20, 23):
            v = V(1)
        else:
            st.raw.append(('%s %s %s' % (code, par, rng.num()), 'property func %d' % fn))
            continue
        st.add(sid, layer, v)
        prev = (layer, v)


# ------------------------------------------------------------------------------- stat lines

def display(it, sid, v, level):
    op = it.n(sid, 'op')
    if 2 <= op <= 5:
        base = it.s(sid, 'op base').strip().lower()
        if base in ('level', ''):
            bv = level
        else:
            bv = 0
        ps = it.n(sid, 'op param')
        v = v.map(lambda x: (bv * x) >> ps)
    # ValShift: the game stores value << ValShift and prints it >> ValShift; we keep the unshifted value
    return v


def _place(descval, num, text):
    if descval == 1:
        return '%s %s' % (num, text)
    if descval == 2:
        return '%s %s' % (text, num)
    return text


def stat_text(it, sid, layer, v, level, grp=False):
    """One stat line (str) or None when the game shows nothing; raises KeyError for an unknown descfunc."""
    pre = 'dgrp' if grp else 'desc'
    fn = it.n(sid, 'dgrpfunc' if grp else 'descfunc')
    dv = it.n(sid, 'dgrpval' if grp else 'descval')
    d = v
    neg = d.hi < 0
    text = it.text(it.s(sid, pre + ('strneg' if neg else 'strpos'))) or it.text(it.s(sid, pre + 'strpos'))
    str2 = it.text(it.s(sid, 'dgrpstr2' if grp else 'descstr2'))
    pct = it.tid(PERCENT, '%')
    plus = it.tid(PLUS, '+')
    if fn in (1, 6, 12):
        if fn == 12 and d.lo == d.hi == 1:
            num = ''
        else:
            num = (plus + d.num()) if d.pos() else d.num()
        out = _place(dv, num, text).strip() if dv else text
    elif fn in (4, 8):
        out = _place(dv, ((plus if d.lo >= 0 else '') + d.num() + pct), text)
    elif fn in (20, 21):
        d = d.map(lambda x: -x)
        out = _place(dv, ((plus if d.lo >= 0 else '') + d.num() + (pct if fn == 20 else '')), text)
    elif fn in (2, 7):
        out = _place(dv, d.num() + pct, text)
    elif fn in (3, 9):
        out = _place(dv, d.num(), text)
    elif fn in (5, 10):
        out = _place(dv, d.map(lambda x: x * 100 // 128).num() + pct, text)
    elif fn == 11:
        if d.lo > 0:
            rate = 2500 // d.lo
            out = cformat(it.tid(21241, 'Repairs %d durability per second'), [1]) if rate <= 30 else \
                cformat(it.tid(21242, 'Repairs %d durability in %d seconds'), [1, (rate + 12) // 25])
        else:
            out = cformat(it.tid(21241, 'Repairs %d durability per second'), [25])
    elif fn == 13:
        allsk = it.charstat(layer, 'StrAllSkills')
        if not allsk:
            return None
        out = _place(dv or 1, (plus + d.num()) if d.pos() else d.num(), allsk)
    elif fn == 14:
        tab, cls = layer & 7, layer >> 3
        if not 0 <= tab <= 2:
            return None
        out = cformat(it.charstat(cls, 'StrSkillTab%d' % (tab + 1)), [d]) + ' ' + it.charstat(cls, 'StrClassOnly')
    elif fn == 15:
        sk, lv = layer >> 6, layer & 0x3f
        out = cformat(it.text(it.s(sid, 'descstrpos')), [d, lv, it.skill_name(sk)])
    elif fn == 16:
        out = cformat(text, [d, it.skill_name(layer)])
    elif fn in (17, 18):
        out = _place(dv, plus + d.num() + (pct if fn == 18 else ''), text)
    elif fn == 19:
        out = cformat(text, [d])
    elif fn == 22:
        out = _place(dv, ((plus if d.lo >= 0 else '') + d.num() + pct), text)
        mt = it.gd.table('montype')
        if 0 <= layer < len(mt):
            out += ' ' + it.text(mt.get(layer, 'strplur'))
    elif fn == 23:
        out = _place(dv, d.num() + pct, text)
        ms = it.gd.table('monstats')
        if 0 <= layer < len(ms):
            out += ' ' + it.text(ms.get(layer, 'NameStr'))
    elif fn == 24:
        sk, lv = layer >> 6, layer & 0x3f
        out = '%s %d %s %s' % (it.tid(21249, 'Level'), lv, it.skill_name(sk),
                               cformat(text, [d.map(lambda x: x & 0xff), d.map(lambda x: x >> 8)]))
    elif fn in (25, 26):
        d = d.map(lambda x: -x)
        out = _place(dv, (plus + d.num()) if d.pos() else d.num(), text)
    elif fn == 27:
        cls = it.skill_class(layer)
        out = '%s %s %s' % ((plus + d.num()) if d.pos() else d.num(), it.tid(TO, 'to'), it.skill_name(layer))
        if cls >= 0:
            out += ' ' + it.charstat(cls, 'StrClassOnly')
    elif fn == 28:
        out = '%s %s %s' % ((plus + d.num()) if d.pos() else d.num(), it.tid(TO, 'to'), it.skill_name(layer))
    # Median XL's own descfuncs (D2Sigma ITEMDESC_DescFunc31..38, names DB)
    elif fn in (31, 34):
        out = it.tid(layer) if layer else ''
    elif fn == 32:
        d = d.map(lambda x: x // 10 if x // 10 else (1 if x > 0 else (-1 if x < 0 else 0)))
        out = _place(dv or 1, (plus + d.num()) if d.pos() else d.num(), text)
    elif fn == 36:
        out = text if d.lo == d.hi == 2 else ''
    elif fn == 37:
        out = cformat(text, [it.skill_name(layer)])
    elif fn == 38 and not layer:
        out = _place(dv, ((plus if d.lo >= 0 else '') + d.num() + pct), text)
    else:
        raise KeyError(fn)
    if 6 <= fn <= 10 or fn == 21:
        out += ' ' + (str2 if str2 else '')
    return out.rstrip()


def stat_lines(it, st, level, colour='3', kind='prop'):
    """The property block: [(segments, kind)] in the game's order."""
    vals = {}
    for (sid, layer), v in st.vals.items():
        vals[(sid, layer)] = display(it, sid, v, level)

    def g(sid):
        return vals.get((sid, 0), V(0))

    rows = []
    done = set()
    # combined damage pairs
    combined = {}
    for mn, (one, two) in COMBINED.items():
        lo, hi = g(mn), g(COMBINED_MAX[mn])
        if lo.lo > 0 and hi.lo > 0:
            combined[mn] = cformat(it.tid(one), [hi]) if lo.lo >= hi.hi else cformat(it.tid(two), [lo, hi])
            done.add(COMBINED_MAX[mn])
    pmn, pmx, plen = g(POISON[0]), g(POISON[1]), g(POISON[2])
    if pmn.lo > 0 and pmx.lo > 0:
        ln = plen.lo or 1
        a = pmn.map(lambda x: (x * ln + 128) >> 8)
        b = pmx.map(lambda x: (x * ln + 128) >> 8)
        combined[POISON[0]] = cformat(it.tid(POISON[3]), [b, ln // 25]) if a.lo >= b.hi else \
            cformat(it.tid(POISON[4]), [a, b, ln // 25])
        done.update((POISON[1], POISON[2]))
    dmn, dmx = g(21) or g(23), g(22) or g(24)
    if dmn.lo > 0 and dmx.lo > 0 and dmn.hi < dmx.lo:
        combined[min(s for s in (21, 22, 23) if (s, 0) in vals)] = cformat(it.tid(DMG_RANGE), [dmn, dmx])
        done.update((21, 22, 23, 24))
    if g(17).lo > 0 and g(18).lo > 0:
        combined[18] = '%s%s%s %s' % (it.tid(PLUS, '+'), g(18).num(), it.tid(PERCENT, '%'), it.tid(ED_TEXT))
        done.add(17)
    if (21, 0) in vals:
        done.add(23)
    if (22, 0) in vals:
        done.add(24)

    keys = sorted(vals, key=lambda k: (-it.n(k[0], 'descpriority'), k[0], k[1]))
    for sid, layer in keys:
        v = vals[(sid, layer)]
        if not v and sid not in combined:
            continue
        if sid in combined:
            rows.append((it.n(sid, 'descpriority'), combined.pop(sid), False))
            done.add(sid)
            continue
        if sid in done:
            continue
        fn = it.n(sid, 'descfunc')
        if not fn:
            continue
        # a dgrp whose stats all show the same value: one line, at the group's lowest stat id
        grp = it.n(sid, 'dgrp')
        if grp:
            members = [s for s in it.row_of if it.n(s, 'dgrp') == grp]
            if members and all(vals.get((m, 0), V(0)) == v for m in members):
                if sid != min(members):
                    continue
                try:
                    txt = stat_text(it, sid, layer, v, level, grp=True)
                except KeyError as e:
                    rows.append((it.n(sid, 'descpriority'), _raw(it, sid, layer, v, e), True))
                    continue
                if txt:
                    rows.append((it.n(sid, 'descpriority'), txt, False))
                continue
        try:
            txt = stat_text(it, sid, layer, v, level)
        except KeyError as e:
            rows.append((it.n(sid, 'descpriority'), _raw(it, sid, layer, v, e), True))
            continue
        if txt:
            rows.append((it.n(sid, 'descpriority'), txt, False))
    out = []
    for _p, txt, raw in rows:
        if raw:
            out.append(([(txt, '5')], 'raw'))
            continue
        for ln in reversed(txt.strip('\n').split('\n')):
            segs, _c = split_colours(ln, None)
            out.append(([(s, c or colour) for s, c in segs], kind))
    for txt, why in st.raw:
        out.append(([('%s (%s)' % (txt, why), '5')], 'raw'))
    return out


def _raw(it, sid, layer, v, e):
    name = it.s(sid, 'Stat') or 'stat %d' % sid
    t = it.text(it.s(sid, 'descstrpos'))
    return '[descfunc %s] %s %s%s' % (e.args[0] if e.args else '?', t or name, v.num(),
                                      (' (param %d)' % layer) if layer else '')


# ------------------------------------------------------------------------------- the item

def _base_row(gd, code):
    for t in ('weapons', 'armor', 'misc'):
        tb = gd.table(t)
        r = tb.find(code, 'code') if code else -1
        if r >= 0:
            return t, tb, r
    return None, None, -1


def _socket_slot(gd, itype):
    """'weapon' | 'helm' | 'shield': which gems.txt mods a socketed rune gives in an item of this type."""
    tb = gd.table('itemtypes')
    seen, todo = set(), [itype.lower()]
    while todo:
        c = todo.pop()
        if not c or c in seen:
            continue
        seen.add(c)
        r = tb.find(c, 'Code')
        if r >= 0:
            todo += [tb.get(r, 'Equiv1').strip().lower(), tb.get(r, 'Equiv2').strip().lower()]
    if 'shld' in seen:
        return 'shield'
    if 'weap' in seen:
        return 'weapon'
    return 'helm'


def detect_kind(row):
    low = {k.lower() for k in row}
    if 'rune name' in low or 't1code1' in low:
        return 'runeword'
    if 'aprop1a' in low or 'set' in low:
        return 'set'
    return 'unique'


def _get(row, col):
    if col in row:
        return row[col] or ''
    cl = col.lower()
    for k, v in row.items():
        if k.lower() == cl:
            return v or ''
    return ''


class Lines(list):
    raw = 0
    reasons = ()
    name = ''


def item_tooltip(tables, strings, item_row, level=99, kind=None, ilvl=0):
    """Lines of the tooltip of a uniqueitems / setitems / runes row ({column: value}, the live edited row).

    tables: explain.Ctx / txt folder / GameData; strings: tbl.StringSet or None (the .tbl beside the txt);
    level: the character level for per-level stats (op 2-5); kind: 'unique' | 'set' | 'runeword' (guessed
    from the columns when None). Returns a list of (segments [(text, colour code)], kind) with .raw / .reasons."""
    gd = GameData(tables, strings)
    it = ItemTables(gd)
    kind = kind or detect_kind(item_row)
    ilvl = ilvl or to_int(_get(item_row, 'lvl'))
    col = QUALITY_COLOUR.get(kind, '0')
    out = Lines()
    st = Stats()
    if kind == 'runeword':
        name = gd.text(_get(item_row, 'Rune Name')) or _get(item_row, 'Rune Name') or _get(item_row, 'Name')
        out.append(([(name, col)], 'name'))
        letters = []
        for i in range(1, 7):
            rc = _get(item_row, 'Rune%d' % i).strip()
            if rc:
                t = gd.text(rc + 'L')
                if not t:
                    _t, tb, r = _base_row(gd, rc)
                    t = gd.text(tb.get(r, 'namestr')) if tb else rc
                    t = re.sub(r'\s*Rune$', '', t)
                letters.append(t)
        if letters:
            out.append(([("'%s'" % ''.join(letters), col)], 'base'))
        # the runes' own socket bonuses (gems.txt) for the runeword's first item type
        slot = _socket_slot(gd, _get(item_row, 'itype1').strip())
        gems = gd.table('gems')
        for i in range(1, 7):
            rc = _get(item_row, 'Rune%d' % i).strip()
            r = gems.find(rc, 'code') if rc else -1
            if r < 0:
                continue
            for m in range(1, 4):
                c = gems.get(r, '%sMod%dCode' % (slot, m))
                if c.strip():
                    apply_property(it, st, c, gems.get(r, '%sMod%dParam' % (slot, m)),
                                   gems.get(r, '%sMod%dMin' % (slot, m)), gems.get(r, '%sMod%dMax' % (slot, m)), level, ilvl)
        for i in range(1, 14):
            c = _get(item_row, 'T1Code%d' % i)
            if c.strip():
                apply_property(it, st, c, _get(item_row, 'T1Param%d' % i), _get(item_row, 'T1Min%d' % i),
                               _get(item_row, 'T1Max%d' % i), level, ilvl)
        out.extend(stat_lines(it, st, level))
    else:
        name = gd.text(_get(item_row, 'index')) or _get(item_row, 'index')
        out.append(([(name, col)], 'name'))
        code = _get(item_row, 'item' if kind == 'set' else 'code').strip()
        t, tb, r = _base_row(gd, code)
        n = 12 if kind == 'unique' else 9
        for i in range(1, n + 1):
            c = _get(item_row, 'prop%d' % i)
            if c.strip():
                apply_property(it, st, c, _get(item_row, 'par%d' % i), _get(item_row, 'min%d' % i),
                               _get(item_row, 'max%d' % i), level, ilvl)
        mxl = gd.version == 'mxl'
        to = gd.text('ItemStast1k') or 'to'

        def pct(v):     # Median: the enhanced % in brackets after the base line
            return ' (%s%s%%)' % ('+' if v.lo >= 0 else '', v.num()) if mxl and v else ''
        if tb is not None:
            out.append(([(gd.text(tb.get(r, 'namestr')) or tb.get(r, 'name'), col)], 'base'))
            if t == 'armor':
                ed = st.get(16)
                lo = to_int(tb.get(r, 'minac')) * (100 + ed.lo) // 100
                hi = to_int(tb.get(r, 'maxac')) * (100 + ed.hi) // 100
                out.append(([('%s %s%s' % (gd.text('ItemStats1h') or 'Defense:', V(lo, hi).num(), pct(ed)),
                              '3' if ed else '0')], 'info'))
                if mxl:
                    st.vals.pop((16, 0), None)
            elif t == 'weapons':
                emn, emx = st.get(18), st.get(17)
                for key, dflt, c1, c2 in (('ItemStats1l', 'One-Hand Damage:', 'mindam', 'maxdam'),
                                          ('ItemStats1m', 'Two-Hand Damage:', '2handmindam', '2handmaxdam')):
                    a0, b0 = to_int(tb.get(r, c1)), to_int(tb.get(r, c2))
                    if a0 or b0:
                        lo = V(a0 * (100 + emn.lo) // 100, a0 * (100 + emn.hi) // 100)
                        hi = V(b0 * (100 + emx.lo) // 100, b0 * (100 + emx.hi) // 100)
                        e = emx if (emx.hi, emx.lo) >= (emn.hi, emn.lo) else emn
                        out.append(([('%s %s %s %s%s' % (gd.text(key) or dflt, lo.num(), to, hi.num(), pct(e)),
                                      '3' if e else '0')], 'info'))
                if mxl:
                    st.vals.pop((17, 0), None)
                    st.vals.pop((18, 0), None)
            for key, c2, dflt in (('ItemStats1f', 'reqdex', 'Required Dexterity:'),
                                  ('ItemStats1e', 'reqstr', 'Required Strength:')):
                v = to_int(tb.get(r, c2))
                if v:
                    out.append(([('%s %d' % (gd.text(key) or dflt, v), '0')], 'req'))
        lr = to_int(_get(item_row, 'lvl req'))
        if lr:
            out.append(([('%s %d' % (gd.text('ItemStats1p') or 'Required Level:', lr), '0')], 'req'))
        out.extend(stat_lines(it, st, level))
        if kind == 'set':
            st2 = Stats()
            for i in range(1, 6):
                for ab in 'ab':
                    c = _get(item_row, 'aprop%d%s' % (i, ab))
                    if c.strip():
                        apply_property(it, st2, c, _get(item_row, 'apar%d%s' % (i, ab)),
                                       _get(item_row, 'amin%d%s' % (i, ab)), _get(item_row, 'amax%d%s' % (i, ab)),
                                       level, ilvl)
            extra = stat_lines(it, st2, level, colour='2', kind='set')
            if extra:
                out.extend(extra)
    out.raw = sum(1 for _s, k in out if k == 'raw')
    out.reasons = [''.join(t for t, _c in s) for s, k in out if k == 'raw']
    out.name = name
    return out
