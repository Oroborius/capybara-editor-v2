"""Skill tooltips as the game composes them from a skilldesc row (txt tables, no Tk).

The rules are the ones of the MXL Capybara Editor V2 skill tooltips (checked there against 470 in-game
tooltips of level 1 Median XL characters), moved from .bin offsets to txt columns:
- the name, the long description, "Required Level", up to four dsc2 lines (general facts), the per-level block
  ("First Level" without points, else "Current Skill Level: N" and "Next Level") of up to six desc lines plus the
  mana cost, and up to seven dsc3 lines (synergies);
- every line is a print function (descline/dsc2line/dsc3line) with two texts and two formulas;
- the formulas are compiled with the project's own linkers (txt2bin.compile_expr, the game's compiler) and
  run by Calc, which knows the skillcalc codes (ln12, dm34, par1, edmn, toht, ...) and Median's own ones
  (spell scaling of skills2.BaseSynergy, enma/exma, syn1-6, area, mode, pdmn, mnar, pass ...).
Whatever is not understood (an unknown print function or formula code) is never guessed: that line comes out
grey as its raw definition (kind 'raw') and is counted in Tip.raw / Tip.reasons.

Character state: levels {skill id: base level}, character level ulvl, stats {stat id: value} in the units the
save stores (life / mana in 256ths); items, masteries and buffs are taken as none."""
import re

from .data import GameData, to_int

OPS = {0x0a: '<', 0x0b: '>', 0x0c: '<=', 0x0d: '>=', 0x0e: '==', 0x0f: '!=',
       0x10: '+', 0x11: '-', 0x12: '*', 0x13: '/', 0x14: '^'}
FUNCS = {0: ('min', 2), 1: ('max', 2), 2: ('rand', 2), 3: ('skill', 2), 4: ('miss', 2), 5: ('stat', 2),
         7: ('f7', 1), 10: ('f10', 1), 11: ('f11', 3), 13: ('f13', 2)}
ARG = {1: 1, 4: 1, 5: 2, 6: 4, 7: 1, 8: 2, 9: 4}
SIGNED = (7, 8, 9)
MISS_FIELD = {'dpa1': 'dParam1', 'dpa2': 'dParam2'}
MASTERY_STATS = (329, 330, 331, 332, 357)
ELEM_TEXT = {0: 4256, 1: 4257, 2: 4259, 3: 4291, 4: 4258, 5: 4260}     # etype -> 'Fire Damage: ' ...
# skills.txt calc columns the skillcalc codes of the same name read
SK_CALC = {'prgcalc1': 'prgcalc1', 'prgcalc2': 'prgcalc2', 'prgcalc3': 'prgcalc3', 'len': 'auralencalc',
           'rng': 'aurarangecalc', 'pets': 'petmax', 'tohitcalc': 'ToHitCalc', 'dmgsym': 'DmgSymPerCalc',
           'edmgsym': 'EDmgSymPerCalc', 'elensym': 'ELenSymPerCalc'}
SK_CALC.update({'ast%d' % i: 'aurastatcalc%d' % i for i in range(1, 7)})
SK_CALC.update({'pst%d' % i: 'passivecalc%d' % i for i in range(1, 6)})
SK_CALC.update({'clc%d' % i: 'calc%d' % i for i in range(1, 5)})
SECTIONS = {'desc': ('descline', 'desctexta', 'desctextb', 'desccalca', 'desccalcb', 6),
            'dsc2': ('dsc2line', 'dsc2texta', 'dsc2textb', 'dsc2calca', 'dsc2calcb', 4),
            'dsc3': ('dsc3line', 'dsc3texta', 'dsc3textb', 'dsc3calca', 'dsc3calcb', 7)}


class Unsupported(Exception):
    """A formula or print function the tooltip cannot reproduce."""


def tokens(code):
    out = []
    p = 0
    while p < len(code):
        op = code[p]
        if op == 0:
            return out
        n = ARG.get(op)
        if n is None:
            if not 0x0a <= op <= 0x16:
                raise Unsupported('formula op %#x' % op)
            out.append((op, None))
            p += 1
        else:
            out.append((op, int.from_bytes(code[p + 1:p + 1 + n], 'little', signed=op in SIGNED)))
            p += 1 + n
    return out


def _c_div(a, b):
    if not b:
        return 0
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


class SkillTables:
    """skills / skilldesc / skills2 / missiles of a project, with one live row overlaid (the edited one)."""

    def __init__(self, gd, overlay=None):
        self.gd = gd
        self.sk = gd.table('skills')
        self.sd = gd.table('skilldesc')
        self.s2 = gd.table('skills2')
        self.miss = gd.table('missiles')
        self.overlay = overlay or {}          # {(table, row): {col lower: value}}
        try:
            self.calc_names = [c.strip().lower() for c in gd.ctx.calc_codes('skills')]
        except Exception:
            self.calc_names = []
        self.miss_calc = [r[0].strip().lower() if r else '' for r in gd.table('misscalc').rows]
        et = gd.table('elemtypes')
        self.elem_index = {et.get(i, 'code').strip().lower(): i for i in range(len(et))}
        pc = gd.table('playerclass')
        self.class_index = {}
        for i in range(len(pc)):
            c = pc.get(i, 'code').strip().lower()
            if c and c != 'expansion':
                self.class_index.setdefault(c, len(self.class_index))
        self._code = {}

    # ---- cells
    def cell(self, table, r, col):
        ov = self.overlay.get((table, r))
        if ov is not None and col.lower() in ov:
            return ov[col.lower()]
        return {'skills': self.sk, 'skilldesc': self.sd, 'skills2': self.s2, 'missiles': self.miss}[table].get(r, col)

    def num(self, sid, col):
        return to_int(self.cell('skills', sid, col))

    def text(self, key):
        return self.gd.text(key)

    def text_id(self, i):
        return self.gd.text_id(i)

    def charclass(self, sid):
        c = self.cell('skills', sid, 'charclass').strip().lower()
        if not c or c in ('none', 'non'):
            return 7
        if c.isdigit():
            return int(c)
        return self.class_index.get(c, 7)

    def etype(self, sid):
        e = self.cell('skills', sid, 'EType').strip().lower()
        if not e:
            return 0
        if e.isdigit():
            return int(e)
        return self.elem_index.get(e, -1)

    def desc_index(self, sid):
        k = self.cell('skills', sid, 'skilldesc').strip()
        if not k:
            return None
        r = self.sd.find(k)
        if r < 0:
            m = re.search(r'(\d+)\)?$', k)
            if m and k[:2].isalpha() and int(m.group(1)) < len(self.sd):
                r = int(m.group(1))
        return r if r >= 0 else None

    def name(self, sid):
        if not 0 <= sid < len(self.sk):
            return 'skill #%d' % sid
        di = self.desc_index(sid)
        if di is not None:
            t = self.text(self.cell('skilldesc', di, 'str name'))
            if t:
                return t
        return self.cell('skills', sid, 'skill') or 'skill #%d' % sid

    def formula(self, table, r, col):
        """Bytecode of a calc cell, None when empty."""
        text = self.cell(table, r, col)
        if not text or not text.strip():
            return None
        text = text.strip('\r\n')
        m = re.match(r'^\?\{([0-9a-fA-F]*)\}$', text)
        if m:
            return bytes.fromhex(m.group(1))
        if re.match(r'^@\d+$', text):
            raise Unsupported('formula stored as a pool offset (%s)' % text)
        hit = self._code.get(text)
        if hit is None:
            from ..binfmt.txt2bin import compile_expr
            p = self.gd.ctx.project
            try:
                hit = compile_expr(text.encode('latin-1', 'replace')[:256], 'skills', p._calc_link('skills'),
                                   arity=True, keywords=p.calc_keywords('skills'), lenient=self.gd.version == 'mxl')
            except Exception as e:
                raise Unsupported('formula does not compile: %s' % e)
            self._code[text] = hit
        if not hit:
            raise Unsupported('the game\'s compiler refuses %r' % text)
        return hit


class Calc:
    """Evaluates compiled formulas for one character state (see the module doc)."""

    def __init__(self, tables, levels=None, ulvl=1, stats=None, bonus=0):
        self.t = tables
        self.levels = levels or {}
        self.ulvl = ulvl
        self.stats = stats or {}
        self.bonus = bonus
        self.used_stats = set()
        self.assumed = set()
        self._depth = 0
        self._self = None
        self._blvl = None

    def blvl(self, sid):
        return int(self.levels.get(sid, 0))

    def lvl(self, sid):
        b = self.blvl(sid)
        return b + self.bonus if b > 0 else 0

    def _par(self, sid, n):
        return self.t.num(sid, 'Param%d' % n)

    def _ln(self, sid, lvl, a):
        return self._par(sid, a) + (lvl - 1) * self._par(sid, a + 1)

    def _dm(self, sid, lvl, a):
        lo, hi = self._par(sid, a), self._par(sid, a + 1)
        return _c_div(110 * lvl * (hi - lo), 100 * (lvl + 6)) + lo

    @staticmethod
    def _per_level(base, steps, lvl, bounds):
        v = base
        lo = 1
        for step, hi in zip(steps, bounds):
            n = (lvl if hi is None else min(lvl, hi)) - lo
            if n > 0:
                v += step * n
            if hi is None or lvl <= hi:
                break
            lo = hi
        return v

    def run(self, table, r, col, sid, lvl):
        code = self.t.formula(table, r, col)
        return 0 if code is None else self.eval(code, sid, lvl)

    def _sym(self, sid, lvl, key):
        v = self.run('skills', sid, SK_CALC[key], sid, lvl)
        if v is None:
            raise Unsupported('damage bonus uses a function of the mod the editor does not know')
        return v

    def phys(self, sid, lvl, hi=False, shift=True):
        t = self.t
        base = t.num(sid, 'MaxDam' if hi else 'MinDam')
        pre = 'MaxLevDam' if hi else 'MinLevDam'
        steps = [t.num(sid, '%s%d' % (pre, i)) for i in range(1, 6)]
        v = self._per_level(base, steps, lvl, (8, 16, 22, 28, None)) << t.num(sid, 'HitShift')
        v += _c_div(v * self._sym(sid, lvl, 'dmgsym'), 100)
        return v >> 8 if shift else v

    def elem(self, sid, lvl, hi=False, shift=True):
        t = self.t
        base = t.num(sid, 'EMax' if hi else 'EMin')
        pre = 'EMaxLev' if hi else 'EMinLev'
        steps = [t.num(sid, '%s%d' % (pre, i)) for i in range(1, 6)]
        v = self._per_level(base, steps, lvl, (8, 16, 22, 28, None)) << t.num(sid, 'HitShift')
        sym = self._sym(sid, lvl, 'edmgsym')
        if to_int(t.cell('skills2', sid, 'BaseSynergy')) == 1:
            if sym:
                raise Unsupported('spell scaling together with a damage formula')
            sym = self.spell_scale()
        v += _c_div(v * sym, 100)
        return v >> 8 if shift else v

    def energy_factor(self):
        e = int(self.stats.get(1, 0))
        self.used_stats.update((1, 485))
        return _c_div(130 * (e + 20), 500 + e) + min(_c_div(int(self.stats.get(485, 0)), 10), 100)

    def spell_scale(self):
        return _c_div((50 + 10 * min(self.ulvl, 120)) * (50 + self.energy_factor()), 100) - 75

    def elen(self, sid, lvl):
        t = self.t
        steps = [t.num(sid, 'ELevLen%d' % i) for i in range(1, 4)]
        v = self._per_level(t.num(sid, 'ELen'), steps, lvl, (8, 16, None))
        return v + _c_div(v * self._sym(sid, lvl, 'elensym'), 100)

    def _table_mana(self, sid, lvl):
        t = self.t
        return (t.num(sid, 'mana') + t.num(sid, 'lvlmana') * (lvl - 1)) << t.num(sid, 'manashift')

    def mana(self, sid, lvl, shift=True):
        v = max(self._table_mana(sid, lvl), self.t.num(sid, 'minmana') << 8)
        return v >> 8 if shift else v

    TABLE_CODES = ('edmn', 'edmx', 'edns', 'edxs', 'edln', 'toht', 'mana', 'usmc', 'enma', 'exma', 'enms', 'exms',
                   'edma')

    def code(self, name, sid, lvl):
        t = self.t
        if lvl <= 0 and (name in self.TABLE_CODES or (name[:2] in ('ln', 'dm') and name[2:].isdigit())):
            return 0
        if name[:2] in ('ln', 'dm') and name[2:].isdigit() and len(name) == 4:
            a = int(name[2])
            return self._ln(sid, lvl, a) if name[0] == 'l' else self._dm(sid, lvl, a)
        if name[:3] == 'par' and name[3:].isdigit():
            return self._par(sid, int(name[3:]))
        if name == 'lvl':
            return lvl
        if name == 'blvl':
            return self.blvl(sid) if sid != self._self or self._blvl is None else self._blvl
        if name == 'ulvl':
            return self.ulvl
        if name in ('edmn', 'edmx'):
            return self.elem(sid, lvl, name == 'edmx')
        if name in ('edns', 'edxs'):
            return self.elem(sid, lvl, name == 'edxs', shift=False)
        if name == 'edln':
            return self.elen(sid, lvl)
        if name == 'toht':
            v = t.num(sid, 'ToHit') + (lvl - 1) * t.num(sid, 'LevToHit')
            return v + self.run('skills', sid, 'ToHitCalc', sid, lvl)
        if name == 'mana':
            return self._table_mana(sid, lvl) >> 8
        if name == 'usmc':
            return self.mana(sid, lvl, shift=False)
        if name in SK_CALC and name not in ('tohitcalc', 'dmgsym', 'edmgsym', 'elensym'):
            return self.run('skills', sid, SK_CALC[name], sid, lvl)
        if name == 'wdm':
            return t.num(sid, 'SrcDam') * 100 // 128
        return self.mod_code(name, sid, lvl)

    def mod_code(self, name, sid, lvl):
        """Median's own codes, as far as the in-game tooltips of a bare character confirm them."""
        if name == 'skcd':
            return self.run('skills', sid, 'delay', sid, lvl)
        if name[:2] in ('bl', 'bd') and name[2:].isdigit() and len(name) == 4:
            b = self.code('blvl', sid, lvl)
            if b <= 0:
                return 0
            a = int(name[2])
            return self._ln(sid, b, a) if name[1] == 'l' else self._dm(sid, b, a)
        if name in ('enma', 'exma'):
            self.assumed.add('mastery')
            return self.elem(sid, lvl, name == 'exma')
        if name in ('enms', 'exms'):
            self.assumed.add('mastery')
            return self.elem(sid, lvl, name == 'exms', shift=False)
        if name == 'edma':
            self.assumed.add('mastery')
            return self.elen(sid, lvl)
        if name[:3] == 'syn' and name[3:].isdigit():
            self.assumed.add('synergy')
            return 0
        if name == 'aura':
            self.assumed.add('aura')
            return 0
        if name in ('area', 'mode'):
            self.assumed.add('place')
            return 1
        if name == 'maxe':
            if self.code('blvl', sid, lvl) <= 0:
                return 0
            raise Unsupported('formula code maxe (the maximum level of a skill is not known)')
        if name[:3] == 'blz' and name[3:].isdigit():
            if self.code('blvl', sid, lvl) <= 0:
                return self._par(sid, int(name[3:]))
            raise Unsupported('formula code %s above base level 0' % name)
        if name in ('pdmn', 'pdmx'):
            return self.phys(sid, max(lvl, 1), name == 'pdmx', shift=False)
        if name == 'mnar':
            if self.code('blvl', sid, lvl) <= 0:
                return 0
            raise Unsupported('formula code mnar above base level 0')
        if name == 'pass':
            if self.blvl(sid) <= 0:
                return 0
            raise Unsupported('formula code pass of a skill with a level')
        if name == 'mlvl':
            return None
        raise Unsupported('formula code %s' % name)

    def eval(self, code, sid, lvl):
        self._depth += 1
        try:
            if self._depth > 12:
                raise Unsupported('formula recursion')
            st = []
            for op, arg in tokens(code):
                if op in (7, 8, 9):
                    st.append(arg)
                elif op in (4, 5, 6):
                    if arg >= len(self.t.calc_names):
                        raise Unsupported('formula code %d' % arg)
                    st.append(self.code(self.t.calc_names[arg], sid, lvl))
                elif op == 1:
                    nm, n = FUNCS.get(arg, (None, 0))
                    if nm is None or len(st) < n:
                        raise Unsupported('formula function %d' % arg)
                    args = st[len(st) - n:]
                    del st[len(st) - n:]
                    if None in args:
                        st.append(None)
                    elif nm[0] == 'f' and nm[1:].isdigit():
                        self.assumed.add('state')
                        st.append(0)
                    else:
                        st.append(self.func(nm, args, sid, lvl))
                elif op == 0x15:
                    a = st.pop()
                    st.append(None if a is None else -a)
                elif op == 0x16:
                    c, b, a = st.pop(), st.pop(), st.pop()
                    st.append(None if a is None else (b if a else c))
                else:
                    b, a = st.pop(), st.pop()
                    sym = OPS[op]
                    if a is None or b is None:
                        st.append(0 if (sym == '*' and (a == 0 or b == 0)) or (sym == '/' and a == 0) else None)
                        continue
                    if sym == '+':
                        v = a + b
                    elif sym == '-':
                        v = a - b
                    elif sym == '*':
                        v = a * b
                    elif sym == '/':
                        v = _c_div(a, b)
                    elif sym == '^':
                        v = a ** b if 0 <= b < 64 else 0
                    else:
                        v = int({'<': a < b, '>': a > b, '<=': a <= b, '>=': a >= b,
                                 '==': a == b, '!=': a != b}[sym])
                    st.append(_i32(v))
            if len(st) != 1:
                raise Unsupported('bad formula')
            if st[0] is None:
                if self._depth > 1:
                    return None
                raise Unsupported('formula uses a function of the mod the editor does not know')
            return st[0]
        except IndexError:
            raise Unsupported('bad formula')
        finally:
            self._depth -= 1

    def func(self, nm, args, sid, lvl):
        if nm == 'min':
            return min(args)
        if nm == 'max':
            return max(args)
        if nm == 'skill':
            other, c = args
            if not 0 <= other < len(self.t.sk) or not 0 <= c < len(self.t.calc_names):
                raise Unsupported('skill() reference')
            cn = self.t.calc_names[c]
            if cn == 'blvl':
                return self.blvl(other)
            lv = self.lvl(other)
            if self.t.charclass(other) < 7:
                return self.code(cn, other, max(lv, 0))
            return self.code(cn, other, max(lv, 1))
        if nm == 'stat':
            sid_, _acc = args
            self.used_stats.add(sid_)
            if sid_ in MASTERY_STATS and sid_ not in self.stats:
                self.assumed.add('mastery')
            return int(self.stats.get(sid_, 0))
        if nm == 'miss':
            mid, c = args
            cn = self.t.miss_calc[c] if 0 <= c < len(self.t.miss_calc) else ''
            if cn in MISS_FIELD and 0 <= mid < len(self.t.miss):
                return to_int(self.t.cell('missiles', mid, MISS_FIELD[cn]))
            raise Unsupported('formula function miss() with code %s' % (cn or c))
        raise Unsupported('formula function %s()' % nm)


# ---- text helpers
def split_colours(text, colour=None):
    """'ÿc1red ÿc0white' -> [(text, colour code or None)], and the colour in force at the end."""
    out = []
    parts = text.replace('\xffc', 'ÿc').split('ÿc')
    if parts[0]:
        out.append((parts[0], colour))
    for p in parts[1:]:
        if not p:
            continue
        colour = p[0]
        if p[1:]:
            out.append((p[1:], colour))
    return out, colour


def text_lines(text, reverse=True):
    """A game string as lines [[(text, colour)]]: the game draws the lines of a string bottom-up."""
    lines = []
    colour = None
    for ln in text.split('\n'):
        segs, colour = split_colours(ln, colour)
        lines.append(segs)
    return lines[::-1] if reverse else lines


def _num(v):
    return str(int(v))


def _range(lo, hi):
    return str(int(lo)) if lo == hi else '%d-%d' % (lo, hi)


def _plus(v):
    return '+%d' % v if v >= 0 else str(int(v))


def _frac(n, d, places=1):
    if not d:
        return '0'
    k = 10 ** places
    v = abs(n) * k // abs(d)
    s = ('%d.%0*d' % (v // k, places, v % k)).rstrip('0').rstrip('.')
    return ('-' if (n < 0) != (d < 0) and v else '') + s


class Tip:
    def __init__(self):
        self.lines = []            # (segments [(text, colour code or None)], kind)
        self.raw = 0
        self.reasons = []
        self.used_stats = set()
        self.assumed = set()
        self.name = ''

    def add(self, segs, kind='line'):
        if isinstance(segs, str):
            segs = [(segs, None)]
        self.lines.append((segs, kind))

    def blank(self):
        if self.lines and self.lines[-1][1] != 'blank':
            self.lines.append(([], 'blank'))

    def plain(self):
        return '\n'.join(('?? ' if k == 'raw' else '') + ''.join(t for t, _c in segs) for segs, k in self.lines)


class Composer:
    def __init__(self, tables, calc):
        self.t = tables
        self.c = calc

    def line(self, fn, sid, lvl, A, B, ca, cb):
        """One desc line -> [[(text, colour)]] in display order; raises Unsupported.
        A, B: the two texts; ca, cb: (table, row, column) of the two formulas or None."""
        t = self.t
        one = text_lines
        c = self.c
        if fn == 18:
            return one(A)
        if fn == 65:
            return one('%s: %s' % (A, B))
        if fn == 11 and not A and not B and ca is None and cb is None and c.blvl(sid) <= 0:
            return []
        if fn == 9:
            lo, hi = c.phys(sid, lvl), c.phys(sid, lvl, True)
            if not lo and not hi:
                return []
            if lo != hi:
                return one('%s%d-%d' % (t.text_id(ELEM_TEXT[0]), lo, hi))
            return one('%s+%d' % (t.text_id(ELEM_TEXT[0]), lo + (1 if t.num(sid, 'SrcDam') else 0)))
        if fn in (24, 26, 27):
            lo, hi = c.elem(sid, lvl, shift=False), c.elem(sid, lvl, True, shift=False)
            if not lo and not hi:
                return []
            if fn == 24:
                return one('%s%s' % (A, _range(lo >> 8, hi >> 8)))
            k = 25 if fn == 26 else 75
            if t.etype(sid) != 1:
                raise Unsupported('line function %d for damage type %d' % (fn, t.etype(sid)))
            return one('%s%s%s%s' % (t.text_id(4322), t.text_id(ELEM_TEXT[1]),
                                     _range((lo * k) >> 8, (hi * k) >> 8), t.text_id(4286)))
        if fn in (10, 14):
            et = t.etype(sid)
            if et not in ELEM_TEXT or (fn == 14 and et != 5):
                raise Unsupported('line function %d for damage type %d' % (fn, et))
            if fn == 14:
                n = c.elen(sid, lvl)
                lo = (c.elem(sid, lvl, shift=False) * n) >> 8
                hi = (c.elem(sid, lvl, True, shift=False) * n) >> 8
                if not lo and not hi:
                    return []
                return [[('%s%s' % (t.text_id(ELEM_TEXT[5]), _range(lo, hi)), None)],
                        [('over %s second%s' % (_frac(n, 25), '' if n == 25 else 's'), None)]]
            lo, hi = c.elem(sid, lvl, shift=False), c.elem(sid, lvl, True, shift=False)
            if not lo and not hi:
                return []
            return one('%s%s' % (t.text_id(ELEM_TEXT[et]), _range(lo >> 8, hi >> 8)))
        need = {2: 'a', 3: 'a', 4: 'a', 5: 'a', 6: 'a', 7: 'a', 12: 'a', 19: 'a', 63: 'a', 66: 'a', 67: 'a',
                16: 'ab', 35: 'ab', 38: 'ab', 52: 'ab', 73: 'ab', 40: '', 76: 'a',
                17: 'ab', 20: 'a', 21: 'a', 42: 'ab'}.get(fn)
        if need is None:
            raise Unsupported('line function %d' % fn)
        if (ca is None and 'a' in need) or (cb is None and 'b' in need):
            return []
        a = c.run(*ca, sid, lvl) if ca is not None else 0
        b = c.run(*cb, sid, lvl) if cb is not None else 0
        if fn == 76:
            text = '' if b >= 1 else (A if a > 0 else B)
            return one(text) if text.strip(' ') else []
        if fn == 20:
            return one('%s%s%%%s' % (A, _plus(a), B))
        if a == 0 and fn not in (35, 40, 66) and (fn not in (16, 17, 38, 52) or b == 0):
            return []
        if fn == 17:
            return one('%s%s%s' % (A, _range(a, b), t.text_id(4286)))
        if fn == 21:
            return one('%s%s%%%s' % (A, _num(a), B))
        if fn == 42:
            if not 10 <= b <= 99:
                raise Unsupported('line function 42 with a one-digit fraction')
            return one('%s: %s.%s %s' % (A, _plus(a), _num(b), B))
        if fn == 35:
            return one('%s: %s-%s' % (A, _num(a), _num(b)))
        if fn == 2:
            return one('%s%s%s' % (A, _plus(a), B))
        if fn == 3:
            return one('%s%s%s' % (A, _num(a), B))
        if fn == 4:
            return one('%s%s' % (A, _plus(a)))
        if fn == 5:
            return one('%s%s' % (A, _num(a)))
        if fn == 6:
            return one('%s%s' % (_plus(a), A))
        if fn == 7:
            return one('%s%s' % (_num(a), A))
        if fn == 12:
            return one('%s%s second%s' % (A, _frac(a, 25), '' if a == 25 else 's'))
        if fn == 16:
            return one('%s%s-%s seconds' % (A, _frac(a, 25), _frac(b, 25)))
        if fn == 19:
            return one('%s%s yard%s' % (A, _frac(a * 2, 3), '' if a * 2 == 3 else 's'))
        if fn == 38:
            return one('%s%s%s' % (A, _range(a, b), B))
        if fn == 40:
            col = str(a) if 0 <= a <= 9 else None
            return [[(s, cc or col) for s, cc in ln] for ln in text_lines(A)]
        if fn == 52:
            return one('%s%s-%s%s' % (A, _plus(a), _num(b), B))
        if fn == 63:
            return one('%s: %s%% %s' % (A, _plus(a), B) if A else '%s%% %s' % (_plus(a), B))
        if fn == 66:
            return one(A.replace('%%', '\0').replace('%d', _num(a)).replace('\0', '%'))
        if fn == 67:
            return one(('%s: %s %s' % (A, _plus(a), B)).rstrip())
        if fn == 73:
            return one('%s/%s %s' % (_num(a), _num(b), A))
        raise Unsupported('line function %d' % fn)

    def raw_line(self, fn, A, B, fa, fb):
        bits = ['[%d]' % fn]
        for s in (A, B):
            if s:
                bits.append(''.join(x for x, _c in split_colours(s.replace('\n', ' / '))[0]))
        for f in (fa, fb):
            if f:
                bits.append('{%s}' % f)
        return ' '.join(bits)

    def mana(self, sid, lvl):
        """Mana cost in points: Median keeps the cost formulas in skills2 (ManaCost, LvlManaCalc)."""
        t = self.t
        if not len(t.s2) or not t.s2.has('ManaCost'):
            return self.c.mana(sid, lvl)
        v = self.c.run('skills2', sid, 'ManaCost', sid, lvl)
        v += (lvl - 1) * self.c.run('skills2', sid, 'LvlManaCalc', sid, lvl)
        if v <= 0:
            return 0
        return max((v << t.num(sid, 'manashift')) >> 8, t.num(sid, 'minmana'))

    def block(self, tip, sid, lvl, sec):
        t = self.t
        di = t.desc_index(sid)
        fcol, tacol, tbcol, cacol, cbcol, n = SECTIONS[sec]
        order = range(1, n + 1) if sec == 'dsc3' else range(n, 0, -1)
        out = []
        for i in order:
            fn = to_int(t.cell('skilldesc', di, '%s%d' % (fcol, i)))
            if not fn:
                continue
            A = t.text(t.cell('skilldesc', di, '%s%d' % (tacol, i)))
            B = t.text(t.cell('skilldesc', di, '%s%d' % (tbcol, i)))
            fa = t.cell('skilldesc', di, '%s%d' % (cacol, i)).strip()
            fb = t.cell('skilldesc', di, '%s%d' % (cbcol, i)).strip()
            ca = ('skilldesc', di, '%s%d' % (cacol, i)) if fa else None
            cb = ('skilldesc', di, '%s%d' % (cbcol, i)) if fb else None
            try:
                if fn == 77:
                    m = self.mana(sid, lvl)
                    label = t.text(t.cell('skilldesc', di, 'str mana'))
                    if m > 0 and label:
                        out.append(([('%s%d' % (label, m), None)], 'line'))
                    continue
                for segs in self.line(fn, sid, lvl, A, B, ca, cb):
                    out.append((segs, 'head' if fn == 40 else 'line'))
            except Unsupported as e:
                tip.raw += 1
                tip.reasons.append(str(e))
                out.append(([(self.raw_line(fn, A, B, fa, fb), None)], 'raw'))
        return out

    def tooltip(self, sid):
        t = self.t
        tip = Tip()
        di = t.desc_index(sid)
        segs, _c = split_colours(t.name(sid))
        tip.name = ''.join(s for s, _ in segs)
        tip.add(segs, 'name')
        if di is None:
            return tip
        for segs in text_lines(t.text(t.cell('skilldesc', di, 'str long'))):
            tip.add(segs, 'desc')
        req = t.num(sid, 'reqlevel')
        if req > 0:
            tip.add(t.text('skilldesc3') + str(req), 'req')
        blvl = self.c.blvl(sid)
        lvl = self.c.lvl(sid)
        self.c._self, self.c._blvl = sid, blvl
        d2 = self.block(tip, sid, max(lvl, 1), 'dsc2')
        if d2:
            tip.blank()
            for segs, kind in d2:
                tip.add(segs, kind)
        for shown, title in (((1, 4269),) if lvl <= 0 else ((lvl, 4254), (lvl + 1, 4253))):
            rows = self.block(tip, sid, shown, 'desc')
            if rows or lvl > 0:
                tip.blank()
                tip.add(t.text_id(title) + (str(shown) if title == 4254 else ''), 'level')
                for segs, kind in rows:
                    tip.add(segs, kind)
        d3 = self.block(tip, sid, max(lvl, 1), 'dsc3')
        if d3:
            tip.blank()
            for segs, kind in d3:
                tip.add(segs, kind)
        tip.used_stats = set(self.c.used_stats)
        tip.assumed = set(self.c.assumed)
        return tip


KIND_COLOUR = {'name': '2', 'desc': '0', 'req': '0', 'level': '0', 'line': '0', 'head': '4', 'raw': '5',
               'blank': '0'}


def start_stats(gd, cls):
    """What a new character of class index cls has (charstats.txt), in save units (life / mana * 256)."""
    cs = gd.table('charstats')
    rows = [r for r in range(len(cs)) if cs.get(r, 'class').strip().lower() not in ('', 'expansion')]
    if not 0 <= cls < len(rows):
        return {12: 1}
    r = rows[cls]
    s, e, d, v = (to_int(cs.get(r, c)) for c in ('str', 'int', 'dex', 'vit'))
    st = {0: s, 1: e, 2: d, 3: v, 12: 1}
    st[6] = st[7] = (50 + v) << 8
    st[8] = st[9] = e << 8
    return st


def skill_tip(gd, sid, levels=None, ulvl=1, stats=None, bonus=0, overlay=None):
    """The V2-style Tip of skill row sid (see module doc)."""
    t = SkillTables(gd, overlay)
    return Composer(t, Calc(t, levels, ulvl, stats, bonus)).tooltip(sid)


def skill_tooltip(tables, strings, skill_row, level=0, sample_stats=None, ulvl=None, levels=None, sid=None):
    """Lines of a skill's tooltip: [(segments [(text, colour code)], kind)], top to bottom.

    tables: explain.Ctx / txt folder / GameData; strings: tbl.StringSet or None (the .tbl beside the txt);
    skill_row: the skills.txt row index, or a {column: value} dict of the (live, edited) row - then sid (its
    index) or its 'skill' name finds the row the other tables align with; level: hard points in the skill (0 =
    none: the "First Level" block); sample_stats: {stat id: value} of the character (default: the class's
    starting stats; life / mana in 256ths as the save stores them); ulvl: character level (default max(level, 1));
    levels: {skill id: base level} of other skills (synergies).
    kind: name, desc, req, level, line, head, raw (grey: not understood), blank."""
    gd = GameData(tables, strings)
    overlay = None
    if isinstance(skill_row, dict):
        if sid is None:
            sid = gd.table('skills').find(skill_row.get('skill', ''), 'skill')
        if sid is None or sid < 0:
            sid = len(gd.table('skills'))       # a new row: overlay only
        overlay = {('skills', sid): {k.lower(): v for k, v in skill_row.items()}}
    else:
        sid = int(skill_row)
    t = SkillTables(gd, overlay)
    lv = dict(levels or {})
    if level:
        lv[sid] = level
    if sample_stats is None:
        sample_stats = start_stats(gd, t.charclass(sid))
    tip = Composer(t, Calc(t, lv, ulvl if ulvl is not None else max(level, 1), sample_stats)).tooltip(sid)
    return tip_lines(tip)


class Lines(list):
    """Tooltip lines plus what the builder could not do: raw (grey lines), reasons, name."""
    raw = 0
    reasons = ()
    name = ''


def tip_lines(tip):
    out = Lines()
    out.raw, out.reasons, out.name = tip.raw, list(tip.reasons), tip.name
    for segs, kind in tip.lines:
        base = KIND_COLOUR.get(kind, '0')
        if kind == 'raw':
            out.append(([(''.join(s for s, _c in segs), base)], kind))
        else:
            out.append(([(s, c if c is not None else base) for s, c in segs], kind))
    return out
