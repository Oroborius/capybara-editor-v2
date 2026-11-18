"""Skill tooltips as the game builds them, from the extracted game tables.

The game composes a skill's tooltip from its skilldesc row: the name, the description, up to four
"dsc2" lines (general facts), the per-level block ("First Level" / "Current Skill Level: N" and
"Next Level") made of up to six "desc" lines plus the mana cost, and up to seven "dsc3" lines
(synergies). Every line is a small function number (how to print) with two texts and two
formulas; the formulas are stored compiled (skilldesccode.bin / skillscode.bin, byte offsets in
the rows). This module holds
- the reader of the compiled formulas: `to_text()` (back to the text form of skills.txt) and the
  evaluator `Calc` (the Diablo II formula mini-language: numbers, + - * /, comparisons, ?:,
  min/max/rand, skill('x'.code), stat('x'.accr) and the skillcalc codes ln12, par1, lvl, edmn...),
- `tooltip()`: the lines of a skill's tooltip for a level, as (segments, kind) rows.

Whatever is not understood (a print function or a formula code the editor does not know) is never
guessed: that line comes out as its raw definition, marked 'raw', and is counted.

The numbers are those of the character's own skill levels and saved stats, at rest in town: what
items give (stats, + to skills, the hidden per-skill modifiers 'syn1-6'), masteries and running
buffs are left out (Tip.assumed / Tip.used_stats say what a tooltip depends on). The rules were
checked against 470 in-game tooltips of level 1 characters (tests/test_16_skilldesc.py).

No Tk in here; mxl_skilltree draws the result."""
import os
import struct

# ---- compiled formulas ------------------------------------------------------------------
OPS = {0x0a: '<', 0x0b: '>', 0x0c: '<=', 0x0d: '>=', 0x0e: '==', 0x0f: '!=',
       0x10: '+', 0x11: '-', 0x12: '*', 0x13: '/', 0x14: '^'}
FUNCS = {0: ('min', 2), 1: ('max', 2), 2: ('rand', 2), 3: ('skill', 2), 4: ('miss', 2), 5: ('stat', 2),
         7: ('f7', 1), 10: ('f10', 1), 11: ('f11', 3), 13: ('f13', 2)}      # 7+ : the mod's own, unknown
MISS_FIELD = {'dpa1': 0x78, 'dpa2': 0x7c}             # missiles.bin: the damage parameters (as in the base game)
MASTERY_STATS = (329, 330, 331, 332, 357)           # "+x% to Fire ... Physical/Magic Spell Damage"
ARG = {1: 1, 4: 1, 5: 2, 6: 4, 7: 1, 8: 2, 9: 4}
SIGNED = (7, 8, 9)                                   # the number ops (a byte holds -128..127)
PREC = {'?': 1, '<': 2, '>': 2, '<=': 2, '>=': 2, '==': 2, '!=': 2, '+': 3, '-': 3, '*': 4, '/': 4, '^': 5}


class Unsupported(Exception):
    """A formula or print function the editor cannot reproduce."""


def tokens(code, off):
    """[(op, argument)] of the compiled formula at off (op 0 ends it)."""
    out = []
    p = off
    while 0 <= p < len(code):
        op = code[p]
        if op == 0:
            return out
        n = ARG.get(op)
        if n is None:
            if not 0x0a <= op <= 0x16:
                raise Unsupported(f'formula op {op:#x}')
            out.append((op, None))
            p += 1
        else:
            out.append((op, int.from_bytes(code[p + 1:p + 1 + n], 'little', signed=op in SIGNED)))
            p += 1 + n
    raise Unsupported('formula runs past the table')


def _c_div(a, b):
    if not b:
        return 0
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _i32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


class Tables:
    """The skill tables of one data folder (host Data object): rows, compiled formulas, names."""
    SK_CALC = {'prgcalc1': 0x38, 'prgcalc2': 0x3c, 'prgcalc3': 0x40, 'len': 0x60, 'rng': 0x64,
               'ast1': 0x68, 'ast2': 0x6c, 'ast3': 0x70, 'ast4': 0x74, 'ast5': 0x78, 'ast6': 0x7c,
               'pst1': 0xa4, 'pst2': 0xa8, 'pst3': 0xac, 'pst4': 0xb0, 'pst5': 0xb4, 'pets': 0xc0,
               'clc1': 0x138, 'clc2': 0x13c, 'clc3': 0x140, 'clc4': 0x144, 'tohitcalc': 0x1a0,
               'dmgsym': 0x1d8, 'edmgsym': 0x210, 'elensym': 0x224}

    def __init__(self, data):
        self.data = data
        self.sk = data._rows('skills')
        self.sd = data._rows('skilldesc')
        self.strings = data.strings
        self.code = self._blob('skillscode.bin')
        self.dcode = self._blob('skilldesccode.bin')
        self.calc_names = [r[:4].decode('latin1').strip('\0 ') for r in self._rows('skillcalc')]
        self.s2 = self._rows('skills2')
        self.s2code = self._blob('skills2code.bin')
        self.elem = self._elem_names()
        self.miss = self._rows('missiles')
        self.miss_calc = [r[:4].decode('latin1').strip('\0 ') for r in self._rows('misscalc')]
        self._stat_names = None

    def _blob(self, name):
        try:
            with open(os.path.join(self.data.folder, name), 'rb') as f:
                return f.read()
        except OSError:
            return b''

    def _rows(self, table):
        b = self._blob(table + '.bin')
        if len(b) < 4:
            return []
        n = struct.unpack_from('<I', b)[0]
        if not n or (len(b) - 4) % n:
            return []
        rs = (len(b) - 4) // n
        return [b[4 + i * rs:4 + (i + 1) * rs] for i in range(n)]

    def _elem_names(self):
        return [r[:4].decode('latin1').strip('\0 ') for r in self._rows('elemtypes')]

    def spell_scaled(self, sid):
        """skills2.bin byte 45: the skill's elemental damage gets the standard spell scaling."""
        return sid < len(self.s2) and len(self.s2[sid]) > 45 and self.s2[sid][45] == 1

    def text(self, idx):
        e = self.strings.get(idx)
        t = e[1] if e else ''
        return '' if (e and e[0] == 'dummy') else t

    def name(self, sid):
        if not 0 <= sid < len(self.sk):
            return f'skill #{sid}'
        di = self.desc_index(sid)
        if di is not None:
            t = self.text(struct.unpack_from('<H', self.sd[di], 8)[0])
            if t:
                return t
        return self.data.skill_names.get(sid) or self._hidden_name(sid) or f'skill #{sid}'

    def _hidden_name(self, sid):
        """The derived '... (hidden #id)' name of a skill without a name string (mxl_statnames), None if none."""
        try:
            import mxl_statnames
            return mxl_statnames.hidden_skill_name(self.data, sid)
        except Exception:
            return None

    def desc_index(self, sid):
        di = struct.unpack_from('<H', self.sk[sid], 0x194)[0]
        return di if di < len(self.sd) else None

    def field(self, sid, off, fmt='<i'):
        return struct.unpack_from(fmt, self.sk[sid], off)[0]

    def stat_name(self, i):
        if self._stat_names is None:
            try:
                import mxl_statnames
                self._stat_names = mxl_statnames
            except Exception:
                self._stat_names = False
        return f'stat{i}'

    # ---- formula text
    def to_text(self, code, off):
        """The formula at off in the text form of the game's tables ('' for none)."""
        if off is None or off < 0:
            return ''
        try:
            toks = tokens(code, off)
        except Unsupported as e:
            return f'<{e}>'
        st = []                                             # (text, precedence)

        def wrap(e, p, right=False):
            return f'({e[0]})' if e[1] < p or (right and e[1] == p) else e[0]
        try:
            for op, arg in toks:
                if op == 7 or op == 8 or op == 9:
                    st.append((str(arg), 9))
                elif op in (4, 5, 6):
                    st.append((self.calc_names[arg] if arg < len(self.calc_names) else f'code{arg}', 9))
                elif op == 1:
                    nm, n = FUNCS.get(arg, (f'f{arg}', 1))
                    args = [st.pop() for _ in range(n)][::-1]
                    if nm in ('skill', 'miss', 'stat'):
                        a, b = args
                        what = a[0]
                        if nm == 'skill' and a[0].isdigit():
                            what = self.name(int(a[0]))
                        if nm == 'stat':
                            acc = {'0': 'accr', '1': 'base', '2': 'mod'}.get(b[0], b[0])
                            st.append((f"stat('{what}'.{acc})", 9))
                        else:
                            c = int(b[0]) if b[0].isdigit() else -1
                            names = self.miss_calc if nm == 'miss' else self.calc_names
                            cn = names[c] if 0 <= c < len(names) else b[0]
                            st.append((f"{nm}('{what}'.{cn})", 9))
                    else:
                        st.append((f'{nm}({",".join(a[0] for a in args)})', 9))
                elif op == 0x15:
                    a = st.pop()
                    st.append(('-' + wrap(a, 5), 5))
                elif op == 0x16:
                    c, b, a = st.pop(), st.pop(), st.pop()
                    st.append((f'{wrap(a, 2)} ? {wrap(b, 2)} : {wrap(c, 2)}', 1))
                else:
                    sym = OPS[op]
                    b, a = st.pop(), st.pop()
                    p = PREC[sym]
                    st.append((f'{wrap(a, p)}{sym}{wrap(b, p, True)}', p))
            return st[-1][0] if st else ''
        except (IndexError, KeyError):
            return '<bad formula>'


class Calc:
    """Evaluates compiled formulas for one character state.

    levels: {skill id: base (hard point) level}; bonus: + to all skills (0 in the editor: items
    are not counted); ulvl: character level; stats: {stat id: value} known for the character."""

    def __init__(self, tables, levels=None, ulvl=1, stats=None, bonus=0):
        self.t = tables
        self.levels = levels or {}
        self.ulvl = ulvl
        self.stats = stats or {}
        self.bonus = bonus
        self.used_stats = set()
        self.assumed = set()       # what was taken as "none": 'synergy' (item modifiers of the skill),
        #                            'mastery', 'aura' / 'state' (buffs, charges), 'place' (in town, standing)
        self._depth = 0

    def blvl(self, sid):
        return int(self.levels.get(sid, 0))

    def lvl(self, sid):
        b = self.blvl(sid)
        return b + self.bonus if b > 0 else 0

    # ---- the numbers of a skills.bin row
    def _par(self, sid, n):
        return self.t.field(sid, 0x148 + 4 * (n - 1))

    def _ln(self, sid, lvl, a):
        return self._par(sid, a) + (lvl - 1) * self._par(sid, a + 1)

    def _dm(self, sid, lvl, a):
        lo, hi = self._par(sid, a), self._par(sid, a + 1)
        return _c_div(110 * lvl * (hi - lo), 100 * (lvl + 6)) + lo

    @staticmethod
    def _per_level(base, steps, lvl, bounds):
        """base + the per-level steps of the game's level brackets (2-8, 9-16, 17-22, 23-28, 29+)."""
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

    def _sym(self, sid, lvl, key):
        off = self.t.field(sid, Tables.SK_CALC[key])
        v = self.eval(self.t.code, off, sid, lvl) if off >= 0 else 0
        if v is None:
            raise Unsupported('damage bonus uses a function of the mod the editor does not know')
        return v

    def phys(self, sid, lvl, hi=False, shift=True):
        """Physical damage of the skill (min or max) in 256ths (shift=False) or points."""
        t = self.t
        base = t.field(sid, 0x1ac if hi else 0x1a8)
        steps = struct.unpack_from('<5i', t.sk[sid], 0x1c4 if hi else 0x1b0)
        v = self._per_level(base, steps, lvl, (8, 16, 22, 28, None)) << t.sk[sid][0x1a4]
        v += _c_div(v * self._sym(sid, lvl, 'dmgsym'), 100)
        return v >> 8 if shift else v

    def elem(self, sid, lvl, hi=False, shift=True):
        t = self.t
        base = t.field(sid, 0x1e4 if hi else 0x1e0)
        steps = struct.unpack_from('<5i', t.sk[sid], 0x1fc if hi else 0x1e8)
        v = self._per_level(base, steps, lvl, (8, 16, 22, 28, None)) << t.sk[sid][0x1a4]
        sym = self._sym(sid, lvl, 'edmgsym')
        if t.spell_scaled(sid):
            # the mod's standard spell scaling (skills2.bin flag): the skills that carry it have no
            # formula of their own; how the two would combine is not known
            if sym:
                raise Unsupported('spell scaling together with a damage formula')
            sym = self.spell_scale()
        v += _c_div(v * sym, 100)
        return v >> 8 if shift else v

    def energy_factor(self):
        """The "Energy: +N% Increased Damage" number (energy, plus Spell Focus / 10 up to 100)."""
        e = int(self.stats.get(1, 0))
        self.used_stats.update((1, 485))
        return _c_div(130 * (e + 20), 500 + e) + min(_c_div(int(self.stats.get(485, 0)), 10), 100)

    def spell_scale(self):
        """% the damage of a spell changes by character level and energy. The formula is the one
        the tables spell out in 'edmgsym' for most spells; the skills flagged in skills2.bin get it
        from the game itself (Devouring Cloud 14-21, Angel of Death 4-6, Rain of Fire 3-5 ... on
        level 1 characters)."""
        return _c_div((50 + 10 * min(self.ulvl, 120)) * (50 + self.energy_factor()), 100) - 75

    def elen(self, sid, lvl):
        t = self.t
        steps = struct.unpack_from('<3i', t.sk[sid], 0x218)
        v = self._per_level(t.field(sid, 0x214), steps, lvl, (8, 16, None))
        return v + _c_div(v * self._sym(sid, lvl, 'elensym'), 100)

    def mana(self, sid, lvl, shift=True):
        t = self.t
        v = (t.field(sid, 0x18a, '<h') + t.field(sid, 0x18c, '<h') * (lvl - 1)) << t.field(sid, 0x188, '<H')
        v = max(v, t.field(sid, 0x186, '<h') << 8)
        return v >> 8 if shift else v

    # ---- skillcalc codes
    TABLE_CODES = ('edmn', 'edmx', 'edns', 'edxs', 'edln', 'toht', 'mana', 'usmc', 'enma', 'exma', 'enms', 'exms',
                   'edma')

    def code(self, name, sid, lvl):
        t = self.t
        if lvl <= 0 and (name in self.TABLE_CODES or (name[:2] in ('ln', 'dm') and name[2:].isdigit())):
            return 0                                       # a skill without a level has no table values
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
            v = t.field(sid, 0x198) + (lvl - 1) * t.field(sid, 0x19c)
            off = t.field(sid, Tables.SK_CALC['tohitcalc'])
            return v + (self.eval(t.code, off, sid, lvl) if off >= 0 else 0)
        if name == 'mana':                                 # the table's own cost, without the minimum
            return ((t.field(sid, 0x18a, '<h') + t.field(sid, 0x18c, '<h') * (lvl - 1)) << t.field(sid, 0x188, '<H')) >> 8
        if name == 'usmc':
            return self.mana(sid, lvl, shift=False)
        if name in Tables.SK_CALC and name not in ('tohitcalc', 'dmgsym', 'edmgsym', 'elensym'):
            off = t.field(sid, Tables.SK_CALC[name])
            return self.eval(t.code, off, sid, lvl) if off >= 0 else 0
        if name == 'wdm':                                  # weapon damage %: srcdam is in 128ths
            return t.sk[sid][0x1a5] * 100 // 128
        return self.mod_code(name, sid, lvl)

    def mod_code(self, name, sid, lvl):
        """The mod's own codes, as far as the in-game tooltips of a bare character confirm them."""
        t = self.t
        if name == 'skcd':                                 # cooldown (frames): the 'delay' formula
            off = t.field(sid, 0x190)
            return self.eval(t.code, off, sid, lvl) if off >= 0 else 0
        if name[:2] in ('bl', 'bd') and name[2:].isdigit() and len(name) == 4:
            b = self.code('blvl', sid, lvl)                # ln12 / dm12 over the base level
            if b <= 0:
                return 0
            a = int(name[2])
            return self._ln(sid, b, a) if name[1] == 'l' else self._dm(sid, b, a)
        # Masteries ("+x% to Fire / Lightning / Cold / Poison / Physical-Magic Spell Damage", stats 329-332,
        # 357) come from items and from passives of other skills (Nightwalker, Way of the Raven, Blight ...).
        # How the game folds them into these codes is not in the tables (the mod's own formulas write it
        # both as x*(100+m)/100 and as x*(100+m)/100+m), and every reference tooltip has mastery 0: taken as 0.
        if name in ('enma', 'exma'):                       # elemental damage + mastery
            self.assumed.add('mastery')
            return self.elem(sid, lvl, name == 'exma')
        if name in ('enms', 'exms'):
            self.assumed.add('mastery')
            return self.elem(sid, lvl, name == 'exms', shift=False)
        if name == 'edma':
            self.assumed.add('mastery')
            return self.elen(sid, lvl)
        if name[:3] == 'syn' and name[3:].isdigit():       # the hidden per-skill modifier stats (382,
            # 383, 393 ...: "[SKILL] +#") that items carry; no class skill hands them out
            self.assumed.add('synergy')
            return 0
        if name == 'aura':                                 # "the buff is switched on"
            self.assumed.add('aura')
            return 0
        if name == 'area':                                 # where the character stands: a town (the
            self.assumed.add('place')                      # reference tooltips were read in town)
            return 1
        if name == 'mode':                                 # what the character does: standing
            self.assumed.add('place')
            return 1
        if name == 'maxe':                                 # "the skill is at its maximum level"
            if self.code('blvl', sid, lvl) <= 0:
                return 0
            raise Unsupported('formula code maxe (the maximum level of a skill is not known)')
        if name[:3] == 'blz' and name[3:].isdigit():       # linear over the base level, from 0: seen
            if self.code('blvl', sid, lvl) <= 0:           # only at base level 0 (Mind Spark)
                return self._par(sid, int(name[3:]))
            raise Unsupported(f'formula code {name} above base level 0')
        if name in ('pdmn', 'pdmx'):                       # physical damage (min / max) in 256ths with the
            # skill's damage formula, like edns / edxs; not 0 without points: Absolution / Sentence read the two
            # Vessels' (no points) and show "Magic Damage: 2 / 3", "Physical Damage: +2 / +3" in game
            return self.phys(sid, max(lvl, 1), name == 'pdmx', shift=False)
        if name == 'mnar':                                 # the summon's attack rating: 0 while the skill has
            if self.code('blvl', sid, lvl) <= 0:           # no point (Night Hawks, Blood Skeleton, the Barbarian
                return 0                                   # spirits ... show just the constant: "Attack Rating: 200")
            raise Unsupported('formula code mnar above base level 0')
        if name == 'pass':                                 # skill('Mark of ...'.pass) of the Paragon skills: 0
            if self.blvl(sid) <= 0:                        # while the hidden skill has no level (the game shows
                return 0                                   # "Unlockable Skill" and the upgrade text)
            raise Unsupported('formula code pass of a skill with a level')
        if name == 'mlvl':                                 # a skill's maximum level: not in the tables
            return None                                    # (unknown; harmless where it divides 0)
        raise Unsupported(f'formula code {name}')

    _self = None
    _blvl = None

    def eval(self, code, off, sid, lvl):
        """The value of the compiled formula at off, for skill sid at level lvl."""
        if off is None or off < 0:
            return 0
        self._depth += 1
        try:
            if self._depth > 12:
                raise Unsupported('formula recursion')
            st = []
            for op, arg in tokens(code, off):
                if op in (7, 8, 9):
                    st.append(arg)
                elif op in (4, 5, 6):
                    if arg >= len(self.t.calc_names):
                        raise Unsupported(f'formula code {arg}')
                    st.append(self.code(self.t.calc_names[arg], sid, lvl))
                elif op == 1:
                    nm, n = FUNCS.get(arg, (None, 0))
                    if nm is None or len(st) < n:
                        raise Unsupported(f'formula function {arg}')
                    args = st[len(st) - n:]
                    del st[len(st) - n:]
                    if None in args:
                        st.append(None)
                    elif nm[0] == 'f' and nm[1:].isdigit():
                        # the mod's own functions (7, 10, 11, 13) ask about the character's
                        # momentary condition (buffs, charges): 0 for a character at rest. With 0
                        # every such line of the reference tooltips comes out as in game.
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
                    if a is None or b is None:             # unknown, unless multiplied by 0 (or 0 / it)
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
            if self.t.field(other, 0xc, '<I') < 7:
                # a class skill the character has no point in: its table values (damage, length,
                # ln12 ...) are 0, its formulas are still worked out, at level 0 (in game: Snake
                # Stance's poison length 0; Witch Blood's spell factor in Glacial Torrent's damage,
                # Mind Spark's "+1 bolt" in Tempest's maximum)
                return self.code(cn, other, max(lv, 0))
            return self.code(cn, other, max(lv, 1))      # the mod's helper skills (no class) always exist
        if nm == 'stat':
            sid_, acc = args
            self.used_stats.add(sid_)
            if sid_ in MASTERY_STATS and sid_ not in self.stats:
                self.assumed.add('mastery')                # given by items and other skills' passives
            return int(self.stats.get(sid_, 0))
        if nm == 'miss':
            # a number of a missile: the code is one of misscalc.bin; the damage parameters are
            # read (in game: "Converts 70% / 100% Physical Damage" of the Necromancer's bolts)
            mid, c = args
            cn = self.t.miss_calc[c] if 0 <= c < len(self.t.miss_calc) else ''
            if cn in MISS_FIELD and 0 <= mid < len(self.t.miss) and len(self.t.miss[mid]) >= 128:
                return struct.unpack_from('<i', self.t.miss[mid], MISS_FIELD[cn])[0]
            raise Unsupported(f'formula function miss() with code {cn or c}')
        raise Unsupported(f'formula function {nm}()')


# ---- the tooltip ------------------------------------------------------------------------
# D2 text colours (ÿcN)
COLOURS = {'0': '#ffffff', '1': '#ff4d4d', '2': '#00ff00', '3': '#6969ff', '4': '#c7b377', '5': '#696969',
           '6': '#000000', '7': '#d0c27d', '8': '#ffa800', '9': '#ffff64', ':': '#008000', ';': '#ae00ff'}
ELEM_TEXT = {0: 4256, 1: 4257, 2: 4259, 3: 4291, 4: 4258, 5: 4260}     # etype -> 'Fire Damage: ' ...


def split_colours(text, colour=None):
    """'ÿc1red ÿc0white' -> [(text, colour code or None)], and the colour in force at the end."""
    out = []
    parts = text.split('ÿc')
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
    """A game string as tooltip lines [[(text, colour)]]: the game draws the lines of a string
    bottom-up, a colour code holds until the next one (in string order)."""
    lines = []
    colour = None
    for ln in text.split('\n'):
        segs, colour = split_colours(ln, colour)
        lines.append(segs)
    return lines[::-1] if reverse else lines


def _num(v):
    return str(int(v))


def _range(lo, hi):
    """'3-5'; one number when both ends are the same (as the game prints it)."""
    return str(int(lo)) if lo == hi else f'{int(lo)}-{int(hi)}'


def _plus(v):
    return f'+{int(v)}' if v >= 0 else str(int(v))


def _frac(n, d, places=1):
    """n/d cut (not rounded, like the game) to `places` decimals, trailing zeros dropped."""
    if not d:
        return '0'
    k = 10 ** places
    v = abs(n) * k // abs(d)
    s = f'{v // k}.{v % k:0{places}d}'.rstrip('0').rstrip('.')
    return ('-' if (n < 0) != (d < 0) and v else '') + s


class Tip:
    def __init__(self):
        self.lines = []            # (segments [(text, colour code or None)], kind)
        self.raw = 0               # lines shown as their raw definition
        self.reasons = []          # why (one text per raw line)
        self.used_stats = set()    # character stats the formulas read
        self.assumed = set()       # what the numbers leave out (see Calc.assumed)
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

    # ---- one desc line -> [[(text, colour)]] (display order); raises Unsupported
    def line(self, fn, sid, lvl, ta, tb, ca, cb):
        t = self.t
        A, B = t.text(ta), t.text(tb)
        one = text_lines
        c = self.c
        if fn == 18:
            return one(A)
        if fn == 65:
            return one(f'{A}: {B}')
        if fn == 11 and not A and not B and ca < 0 and cb < 0 and c.blvl(sid) <= 0:
            return []                     # no text, no number: nothing in game without points (Thundergod)
        if fn == 9:                       # physical damage of the skill
            lo, hi = c.phys(sid, lvl), c.phys(sid, lvl, True)
            if not lo and not hi:
                return []
            if lo != hi:
                return one(f'{t.text(ELEM_TEXT[0])}{lo}-{hi}')
            # one number: weapon skills (srcdam) show one point more than the table value in
            # game (seen on Impale and Eviscerate), spells the value itself (Dream Eater)
            return one(f'{t.text(ELEM_TEXT[0])}+{lo + (1 if t.sk[sid][0x1a5] else 0)}')
        if fn in (24, 26, 27):            # elemental damage with a caption / as fire per second
            lo, hi = c.elem(sid, lvl, shift=False), c.elem(sid, lvl, True, shift=False)
            if not lo and not hi:
                return []
            if fn == 24:
                return one(f'{A}{_range(lo >> 8, hi >> 8)}')
            k = 25 if fn == 26 else 75    # 27: three flames at a time (Wildfire 28-35 in game)
            if t.sk[sid][0x1dc] != 1:
                raise Unsupported(f'line function {fn} for damage type {t.sk[sid][0x1dc]}')
            return one(f'{t.text(4322)}{t.text(ELEM_TEXT[1])}{_range((lo * k) >> 8, (hi * k) >> 8)}{t.text(4286)}')
        if fn in (10, 14):                # elemental / poison damage of the skill
            et = t.sk[sid][0x1dc]
            if et not in ELEM_TEXT or (fn == 14 and et != 5):
                raise Unsupported(f'line function {fn} for damage type {et}')
            if fn == 14:
                n = c.elen(sid, lvl)
                lo = (c.elem(sid, lvl, shift=False) * n) >> 8
                hi = (c.elem(sid, lvl, True, shift=False) * n) >> 8
                if not lo and not hi:
                    return []
                return [[(f'{t.text(ELEM_TEXT[5])}{_range(lo, hi)}', None)],
                        [(f'over {_frac(n, 25)} second{"" if n == 25 else "s"}', None)]]
            lo, hi = c.elem(sid, lvl, shift=False), c.elem(sid, lvl, True, shift=False)
            if not lo and not hi:
                return []                 # no damage at all; a fraction of a point shows as 0 (Earthquake)
            return one(f'{t.text(ELEM_TEXT[et])}{_range(lo >> 8, hi >> 8)}')
        need = {2: 'a', 3: 'a', 4: 'a', 5: 'a', 6: 'a', 7: 'a', 12: 'a', 19: 'a', 63: 'a', 66: 'a', 67: 'a',
                16: 'ab', 35: 'ab', 38: 'ab', 52: 'ab', 73: 'ab', 40: '', 76: 'a',
                17: 'ab', 20: 'a', 21: 'a', 42: 'ab'}.get(fn)
        if need is None:
            raise Unsupported(f'line function {fn}')
        if (ca < 0 and 'a' in need) or (cb < 0 and 'b' in need):
            return []                     # the game prints nothing for it (Hyena Strike, Lion Stance, Divine Judgement)
        a = c.eval(t.dcode, ca, sid, lvl) if ca >= 0 else 0
        b = c.eval(t.dcode, cb, sid, lvl) if cb >= 0 else 0
        if fn == 76:
            # a text chosen by two conditions: nothing when the second is met, else the first text
            # when the first is met, else the second text ("Unlockable Skill" until unlocked,
            # "Disables X" / "Disabled by X", the Cognition steps, "Max this Skill" red / green)
            text = '' if b >= 1 else (A if a > 0 else B)
            return one(text) if text.strip(' ') else []
        if fn == 20:
            return one(f'{A}{_plus(a)}%{B}')
        if a == 0 and fn not in (35, 40, 66) and (fn not in (16, 17, 38, 52) or b == 0):
            return []                     # the game leaves out a line whose number is 0 (but shows
                                          # a range, 35, even as 0-0: Charged Talons, Blight Descent)
        if fn == 17:
            return one(f'{A}{_range(a, b)}{t.text(4286)}')
        if fn == 21:
            return one(f'{A}{_num(a)}%{B}')
        if fn == 42:
            if not 10 <= b <= 99:
                raise Unsupported('line function 42 with a one-digit fraction')
            return one(f'{A}: {_plus(a)}.{_num(b)} {B}')
        if fn == 35:
            return one(f'{A}: {_num(a)}-{_num(b)}')
        if fn == 2:
            return one(f'{A}{_plus(a)}{B}')
        if fn == 3:
            return one(f'{A}{_num(a)}{B}')
        if fn == 4:
            return one(f'{A}{_plus(a)}')
        if fn == 5:
            return one(f'{A}{_num(a)}')
        if fn == 6:
            return one(f'{_plus(a)}{A}')
        if fn == 7:
            return one(f'{_num(a)}{A}')
        if fn == 12:
            return one(f'{A}{_frac(a, 25)} second{"" if a == 25 else "s"}')
        if fn == 16:
            return one(f'{A}{_frac(a, 25)}-{_frac(b, 25)} seconds')
        if fn == 18:
            return one(A)
        if fn == 19:
            return one(f'{A}{_frac(a * 2, 3)} yard{"" if a * 2 == 3 else "s"}')
        if fn == 38:
            return one(f'{A}{_range(a, b)}{B}')
        if fn == 40:
            col = str(a) if str(a) in COLOURS else None
            return [[(s, c or col) for s, c in ln] for ln in text_lines(A)]     # the second text is not drawn
        if fn == 52:
            return one(f'{A}{_plus(a)}-{_num(b)}{B}')
        if fn == 63:
            return one(f'{A}: {_plus(a)}% {B}' if A else f'{_plus(a)}% {B}')
        if fn == 66:
            return one(A.replace('%%', '\0').replace('%d', _num(a)).replace('\0', '%'))
        if fn == 67:
            return one(f'{A}: {_plus(a)} {B}'.rstrip())
        if fn == 73:
            return one(f'{_num(a)}/{_num(b)} {A}')
        raise Unsupported(f'line function {fn}')

    def raw_line(self, fn, ta, tb, ca, cb):
        t = self.t
        bits = [f'[{fn}]']
        for s in (t.text(ta), t.text(tb)):
            if s:
                bits.append(''.join(x for x, _c in split_colours(s.replace('\n', ' / '))[0]))
        for o in (ca, cb):
            if o >= 0:
                bits.append('{' + t.to_text(t.dcode, o) + '}')
        return ' '.join(bits)

    def mana(self, sid, lvl):
        """Mana cost in points: the mod keeps the cost formulas in skills2.bin (cost and cost
        per level, in the skill's own fraction: << manashift, 256 = 1 point)."""
        t = self.t
        if sid >= len(t.s2) or len(t.s2[sid]) < 66:
            return self.c.mana(sid, lvl)
        base, per = struct.unpack_from('<2i', t.s2[sid], 54)
        v = (self.c.eval(t.s2code, base, sid, lvl) if base >= 0 else 0)
        v += (lvl - 1) * (self.c.eval(t.s2code, per, sid, lvl) if per >= 0 else 0)
        if v <= 0:
            return 0
        return max((v << t.field(sid, 0x188, '<H')) >> 8, t.field(sid, 0x186, '<h'))

    def block(self, tip, sid, lvl, sec):
        """The lines of one section ('desc' 6 lines, 'dsc2' 4, 'dsc3' 7) in display order."""
        t = self.t
        x = t.sd[t.desc_index(sid)]
        first, n = {'desc': (0, 6), 'dsc2': (6, 4), 'dsc3': (10, 7)}[sec]
        order = range(first, first + n) if sec == 'dsc3' else range(first + n - 1, first - 1, -1)
        out = []
        for i in order:
            fn = x[0x42 + i]
            if not fn:
                continue
            ta = struct.unpack_from('<H', x, 0x54 + 2 * i)[0]
            tb = struct.unpack_from('<H', x, 0x76 + 2 * i)[0]
            ca = struct.unpack_from('<i', x, 0x98 + 4 * i)[0]
            cb = struct.unpack_from('<i', x, 0xdc + 4 * i)[0]
            try:
                if fn == 77:
                    m = self.mana(sid, lvl)
                    label = t.text(struct.unpack_from('<H', x, 0x10)[0])
                    if m > 0 and label:
                        out.append(([(f'{label}{m}', None)], 'line'))
                    continue
                for segs in self.line(fn, sid, lvl, ta, tb, ca, cb):
                    out.append((segs, 'head' if fn == 40 else 'line'))
            except Unsupported as e:
                tip.raw += 1
                tip.reasons.append(str(e))
                out.append(([(self.raw_line(fn, ta, tb, ca, cb), None)], 'raw'))
        return out

    def tooltip(self, sid):
        """The whole tooltip of the skill at the calc's levels."""
        t = self.t
        tip = Tip()
        di = t.desc_index(sid)
        segs, _c = split_colours(t.name(sid))
        tip.name = ''.join(s for s, _ in segs)
        tip.add(segs, 'name')
        if di is None:
            return tip
        x = t.sd[di]
        for segs in text_lines(t.text(struct.unpack_from('<H', x, 0xc)[0])):
            tip.add(segs, 'desc')
        req = t.field(sid, 0x174, '<H')
        if req > 0:
            tip.add(t.text(self._key('skilldesc3')) + str(req), 'req')
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
                tip.add(t.text(title) + (str(shown) if title == 4254 else ''), 'level')
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

    def _key(self, key):
        cache = getattr(self.t, '_keys', None)
        if cache is None:
            cache = self.t._keys = {}
            for i, (k, _s) in self.t.strings.items():
                cache.setdefault(k, i)
        return cache.get(key, -1)


def tables(data):
    """The (cached) skill tables of a host Data object."""
    t = getattr(data, '_capy_skilldesc', None)
    if t is None:
        t = data._capy_skilldesc = Tables(data)
    return t


def tooltip(data, sid, levels=None, ulvl=1, stats=None, bonus=0):
    """The tooltip of skill sid for a character: levels {sid: base level}, character level,
    stats {stat id: value} (what the save stores: items are not counted)."""
    t = tables(data)
    calc = Calc(t, levels, ulvl, stats, bonus)
    return Composer(t, calc).tooltip(sid)
