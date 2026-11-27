"""Property -> stat bounds (from the dev kit tooltip/item.py, trimmed)."""
# Adapted from the D2-Development-Kit (MIT License, see LICENSE in this folder).
import re

def to_int(s, default=0):
    if isinstance(s, int):
        return s
    m = re.match(r'^\s*-?\d+', str(s or ''))
    return int(m.group(0)) if m else default


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


def apply_property(it, st, code, par, mn, mx, level):
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
            layer = to_int(par)
        elif fn == 11:
            sk = it.skill_index(par)
            layer = (max(sk, 0) << 6) | (hi & 0x3f)
            v = V(lo)
        elif fn == 14:
            v = rng
        elif fn == 15:
            v = V(lo)
        elif fn == 16:
            v = V(hi)
        elif fn == 17:
            v = V(to_int(par))
        elif fn == 19:
            sk = it.skill_index(par)
            layer = (max(sk, 0) << 6) | (hi & 0x3f)
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

