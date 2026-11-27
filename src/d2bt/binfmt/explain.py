"""Formula explainer for the Excel editor's Simple mode (docs/SIMPLE_MODE.md).

Three layers, each usable on its own:

1. Lossless text <-> AST.  parse(text) -> Formula.  Every character of the cell is kept in a token
   (its leading blanks and '"', which Fog skips, ride along as the token's `ws`), so
   Formula.text() == text for any input, also for cells Fog would refuse, '?{hex}' / '@N' cells and
   bin2txt's render_faithful forms ('stat(320)', '0 0', '(((50+...').  The tree is built by a port
   of Fog's own shunting-yard (txt2bin.compile_expr, Fog #10254): the same precedence quirks
   ('a+b?c:d' is a+(b?c:d), ':' pops nothing, '-' is a negation unless a value came just before),
   the same function arities, and the lenient Median mode (an operator that finds too few operands
   gets None children).  So the tree is what the game computes, and Formula.postfix() replays it
   as bytecode; the gate (main --gate) checks that against compile_expr for every formula cell.
   Edits go through the tokens (Formula.set_token), so everything else stays byte-identical.

2. explain(expr, table, row, ctx) -> {'text': readable expression, 'vars': [...], 'notes': [...]}.
   Each variable: {token, name, meaning, value, editable, columns, kind}.  par1..par8 point at
   that row's Param1..8 (labels from the column docs when there are any), ln12/dm34 are spelled
   out, stat('x'.accr) / skill('X'.blvl) are named, min/max/rand and D2Sigma's functions become
   words.

3. evaluate(expr, ctx, levels) -> per-level values.  The text is compiled with txt2bin (the
   project's linkers, lenient for Median) and run by a port of Fog's evaluator
   (DATATBLS_CalcEvaluateExpression: int32 wrap, C division with x/0 = 0, '^' by repeated
   multiplication with exponent <= 0 -> 1, and evaluation ending right after a ternary).  The
   skillcalc / misscalc codes follow D2MOO's SKILLS_GetSpecialParamValue /
   MISSILE_GetSpecialParamValue (ln = Pa + (lvl-1)*Pb, dm = D2Common_11033
   p + (max-p)*(110*L/(L+6))/100 capped at max, ...).  The Median codes past D2MOO's list follow
   the V2 editor's tooltip rules (bl/bd = ln/dm over the base level, wdm = SrcDam*100/128, skcd =
   the delay formula); what only the running game knows (character stats, synergy items, auras,
   D2Sigma's state()/class()/... functions) becomes a sample input with a default, reported in
   the result as `assumed`.  rand(a,b) is evaluated at both ends and shown as a range.
"""
import os
import re
import struct

from . import calc

# --------------------------------------------------------------------------------------- tokens


class Tok:
    __slots__ = ('kind', 'text', 'ws', 'name')

    def __init__(self, kind, text, ws='', name=None):
        self.kind = kind        # num quoted ident fn dot op junk
        self.text = text        # exact source text (fn: 'skill (' incl. the '(')
        self.ws = ws            # blanks / '"' before it (Fog skips them)
        self.name = name        # fn: the function name; quoted: the name inside; dot: the sub name

    def __repr__(self):
        return 'Tok(%s,%r)' % (self.kind, self.ws + self.text)


def _alnum(c):
    return c < '\x80' and c.isalnum()


def tokenize(s, fn_names=None):
    """Lossless tokens of a calc cell, split the way Fog's tokenizer reads it.  fn_names: the
    names that are functions when '(' follows (default: every skill/item function name)."""
    fns = fn_names if fn_names is not None else _ALL_FN
    out = []
    i, n = 0, len(s)
    while i < n:
        j = i
        while j < n and (s[j] in ' \t\n\r\x0b\x0c"'):
            j += 1
        ws = s[i:j]
        if j >= n:
            out.append(Tok('end', '', ws))
            break
        c = s[j]
        if '0' <= c <= '9':
            k = j
            while k < n and '0' <= s[k] <= '9':
                k += 1
            out.append(Tok('num', s[j:k], ws))
        elif c == "'":
            k = s.find("'", j + 1)
            k = n if k < 0 else k + 1
            nm = s[j + 1:k - 1] if k <= n and s[k - 1:k] == "'" and k - 1 > j else s[j + 1:k]
            out.append(Tok('quoted', s[j:k], ws, nm))
        elif c < '\x80' and c.isalpha():
            k = j
            while k < n and _alnum(s[k]):
                k += 1
            nm = s[j:k]
            m = k
            while m < n and s[m] in ' \t\n\r\x0b\x0c':
                m += 1
            if m < n and s[m] == '(' and _is_fn(nm, fns):
                out.append(Tok('fn', s[j:m + 1], ws, nm.lower()))
                k = m + 1
            else:
                out.append(Tok('ident', nm, ws, nm))
        elif c == '.':
            k = j + 1
            while k < n and _alnum(s[k]):
                k += 1
            out.append(Tok('dot', s[j:k], ws, s[j + 1:k]))
        elif s[j:j + 2] in ('<=', '>=', '==', '!='):
            k = j + 2
            out.append(Tok('op', s[j:k], ws))
        elif c in '()*+,-/:<>?^':
            k = j + 1
            out.append(Tok('op', c, ws))
        else:                       # Fog stops reading here: the rest is kept, never compiled
            out.append(Tok('junk', s[j:], ws))
            k = n
        i = k
    return out


_ALL_FN = {n for n, _a in calc.SKILL_FUNCS} | {n for n, _a in calc.ITEM_FUNCS}


def _is_fn(name, fns):
    ln = name.lower()
    return ln in fns or re.match(r'^fn\d+$', ln) is not None


# --------------------------------------------------------------------------------------- tree

BIN_AST = {'<': 10, '>': 11, '<=': 12, '>=': 13, '==': 14, '!=': 15, '+': 16, '-': 17, '*': 18,
           '/': 19, '^': 20}
AST_BIN = {v: k for k, v in BIN_AST.items()}
PREC = [23, 1, 2, 3, 9, 9, 9, 9, 9, 9, 15, 15, 15, 15, 15, 15, 17, 17, 19, 19, 20, 21, 22, 0]


class Node:
    """kind: num | name (param code / unknown name) | quoted ('X') | dot (.sub) | bin | neg | tern |
    fn | seq (values left side by side).  tok: index of the token (leaves, fn, operators).
    kids may hold None (an operand the lenient compiler never had)."""
    __slots__ = ('kind', 'val', 'kids', 'tok', 'pre')

    def __init__(self, kind, val=None, kids=(), tok=None):
        self.kind = kind
        self.val = val
        self.kids = list(kids)
        self.tok = tok
        self.pre = 0            # '(' flushed (02 bytes) right before this operator, end of cell only

    def walk(self):
        yield self
        for k in self.kids:
            if k is not None:
                yield from k.walk()

    def __repr__(self):
        if not self.kids:
            return '%s(%r)' % (self.kind, self.val)
        return '%s(%r, %s)' % (self.kind, self.val, ', '.join(map(repr, self.kids)))


class Formula:
    """A parsed calc cell.  text() is always the input text; root is None when the cell is empty,
    raw ('?{hex}', '@N') or Fog would not read it at all."""

    def __init__(self, text, kind='skills', link=None, keywords=None, lenient=True):
        self.source = text
        self.kind = kind
        self.raw = bool(re.match(r'^\?\{[0-9a-fA-F]*\}$|^@\d+$', text))
        self.tokens = [] if self.raw else tokenize(text, _fn_names(kind))
        self.root = None
        self.error = None
        self.trailing_open = 0      # unclosed '(' flushed by Fog as 02 bytes
        self.stopped = False        # Fog stopped reading at a 'junk' token (or a '.sub' it cannot link)
        self._ctx = {}              # token index -> (prev ast, value) when Fog read it
        if not self.raw and text.strip(' \t"'):
            try:
                self._build(link, keywords, lenient)
            except _ParseError as e:
                self.error = str(e) or 'unreadable'
                self.root = None

    # -- lossless text
    def text(self):
        if self.raw:
            return self.source
        return ''.join(t.ws + t.text for t in self.tokens)

    def set_token(self, i, text):
        """Replace token i's text (e.g. a number); the rest of the cell stays as it was."""
        t = self.tokens[i]
        t.text = text
        if t.kind == 'num' and not text.isdigit():
            t.kind = 'ident'
        return self.text()

    # -- Fog's shunting-yard, building nodes
    def _build(self, link=None, keywords=None, lenient=True):
        kw = keywords
        toks = self.tokens
        flush = [0]                 # '(' popped by the final flush, not yet placed
        vals = []                   # node stack (what Fog's bytecode would push)
        ops = []                    # [ast, val, tok index]
        pending = [0]
        state = {'pv': False, 'has_fn': False}

        def arity(ast, val):
            if ast == 1:
                return _arity(self.kind, val)
            if 10 <= ast <= 20:
                return 2
            if ast == 21:
                return 1
            if ast == 22:
                return 3
            return 0

        def emit(ast, val, ti):
            np_ = arity(ast, val)
            if pending[0] < np_ and not lenient:
                raise _ParseError('stack')
            have = min(len(vals), np_)
            kids = [None] * (np_ - have) + (vals[len(vals) - have:] if have else [])
            if have:
                del vals[len(vals) - have:]
            pending[0] = max(pending[0], np_) + 1 - np_
            pre, flush[0] = flush[0], 0
            if ast == 1:
                vals.append(Node('fn', _fn_name(self.kind, val), kids, ti))
            elif ast == 21:
                vals.append(Node('neg', None, kids, ti))
            elif ast == 22:
                vals.append(Node('tern', None, kids, ti))
            else:
                vals.append(Node('bin', AST_BIN[ast], kids, ti))
            vals[-1].pre = pre

        def check_prec(prev, new):
            if prev == 1 or new == 1 or prev >= 23:
                return False
            return PREC[prev] >= new

        def new_op(new, ti):
            while ops:
                prev = ops[-1][0]
                if not check_prec(prev, new):
                    break
                a, v, t = ops.pop()
                emit(a, v, t)
            if new in (23, 3, 0):
                return
            ops.append([new, 0, ti])

        for ti, t in enumerate(toks):
            k = t.kind
            if k == 'end':
                break
            if k == 'junk':
                self.stopped = True
                break
            self._ctx[ti] = (ops[-1][0], ops[-1][1]) if ops else (0, 0)
            if k == 'dot' and link is not None:
                a3, a4 = self._ctx[ti]
                if link(t.name.encode('latin-1', 'replace')[:255], a3, a4)[0] < 0:
                    self.stopped = True     # Fog's tokenizer returns nothing: reading ends here
                    break
            if k == 'op':
                o = t.text
                if o == '(':
                    ops.append([2, 0, ti])
                elif o == ')':
                    if not ops:
                        raise _ParseError("')' without '('")
                    while True:
                        prev, pv, pt = ops[-1]
                        if prev == 2:
                            break
                        if prev == 1:
                            emit(1, pv, pt)
                            break
                        ops.pop()
                        emit(prev, pv, pt)
                        if not ops:
                            raise _ParseError("')' without '('")
                    ops.pop()
                elif o == ',':
                    new_op(3, ti)
                elif o == '-':
                    new_op(17 if state['pv'] else 21, ti)
                    state['pv'] = False
                elif o == '?':
                    new_op(22, ti)
                elif o == ':':
                    new_op(23, ti)
                else:
                    new_op(BIN_AST[o], ti)
                    state['pv'] = False
            elif k == 'fn':
                ops.append([1, _fn_id(self.kind, t.name, kw), ti])
                state['pv'] = True
                state['has_fn'] = True
            else:
                if k == 'num':
                    nd = Node('num', int(t.text) & 0xFFFFFFFF, (), ti)
                    if nd.val >= 0x80000000:
                        nd.val -= 0x100000000
                elif k == 'quoted':
                    nd = Node('quoted', t.name, (), ti)
                elif k == 'dot':
                    nd = Node('dot', t.name, (), ti)
                else:
                    nd = Node('name', t.name, (), ti)
                vals.append(nd)
                pending[0] += 1
                state['pv'] = True
        # end: flush everything (Fog's new_op(0)); it stops at an unclosed function
        while ops:
            if ops[-1][0] == 1:
                break
            a, v, t = ops.pop()
            if a == 2:
                flush[0] += 1
                continue
            emit(a, v, t)
        self.trailing_open = flush[0]
        if not vals:
            raise _ParseError('empty')
        self.root = vals[0] if len(vals) == 1 else Node('seq', None, vals)
        self.has_fn = state['has_fn']

    # -- the tree as bytecode (for the gate)
    def postfix(self, link, keywords=None):
        """Bytecode replayed from the tree, resolving leaves with txt2bin's link(name, a3, kw)."""
        from .txt2bin import _push_const, calc_eval
        out = bytearray()
        any_fn = [getattr(self, 'has_fn', False)]     # Fog: a function name read, emitted or not

        def leaf_ctx(n):
            # Fog resolves a name with the op on top of its stack (prev_ast) as context
            return self._ctx.get(n.tok, (0, 0))

        def walk(n):
            if n is None:
                return
            if n.kind in ('num',):
                _push_const(out, n.val, False)
            elif n.kind in ('name', 'quoted', 'dot'):
                a3, a4 = leaf_ctx(n)
                nm = n.val.encode('latin-1', 'replace')[:255]
                idx, raw = link(nm, a3, a4)
                if n.kind == 'dot':
                    if idx < 0:
                        raise _ParseError('sub-name %r' % n.val)
                    _push_const(out, idx, False)
                elif idx >= 0:
                    _push_const(out, idx, not raw)
                    if not raw:
                        any_fn[0] = True
                else:
                    _push_const(out, 0, False)
            elif n.kind == 'seq':
                for k in n.kids:
                    walk(k)
            else:
                for k in n.kids:
                    walk(k)
                out.extend(b'\x02' * n.pre)
                if n.kind == 'fn':
                    out.append(1)
                    out.append(_fn_id(self.kind, n.val, keywords) & 0xFF)
                    any_fn[0] = True
                elif n.kind == 'neg':
                    out.append(21)
                elif n.kind == 'tern':
                    out.append(22)
                else:
                    out.append(BIN_AST[n.val])
        walk(self.root)
        out += b'\x02' * self.trailing_open
        out.append(0)
        if not any_fn[0]:
            v = calc_eval(bytes(out))
            out = bytearray()
            _push_const(out, v, False)
            out.append(0)
        return bytes(out)


class _ParseError(Exception):
    pass


def _fn_list(kind):
    return calc.ITEM_FUNCS if kind == 'items' else calc.SKILL_FUNCS


def _fn_names(kind):
    return {n for n, _a in _fn_list(kind)}


def _fn_id(kind, name, keywords=None):
    m = re.match(r'^fn(\d+)$', name)
    if m:
        return int(m.group(1))
    names = [n for n, _a in _fn_list(kind)]
    return names.index(name) if name in names else -1


def _fn_name(kind, fid):
    lst = _fn_list(kind)
    return lst[fid][0] if 0 <= fid < len(lst) else 'fn%d' % fid


def _arity(kind, fid):
    lst = _fn_list(kind)
    return lst[fid][1] if 0 <= fid < len(lst) else 1


def parse(text, kind='skills', link=None, keywords=None, lenient=True):
    """-> Formula (lossless: .text() == text).  kind: skills | missiles | items (pool kind).
    link / keywords (txt2bin Project._calc_link(kind) / calc_keywords(kind)): resolve '.sub' names
    as Fog does, which ends reading at one it cannot link.  lenient=False: fail like Fog (not
    Median) when an operator finds too few operands."""
    return Formula(text if isinstance(text, str) else text.decode('latin-1'), kind, link, keywords,
                   lenient)


POOL_KIND = {'skillscode': 'skills', 'skilldesccode': 'skills', 'skills2code': 'skills',
             'misscode': 'missiles', 'itemscode': 'items'}


def calc_columns(table, version):
    """{column name lower: pool} of the layout's calc fields (ftype 25 'calc:<pool>')."""
    from . import layouts
    lay = layouts.load(version, table) or {}
    out = {}
    for f in lay.get('fields', ()):
        ln = str(f.get('link') or '')
        if f.get('ftype') == 25 and ln.startswith('calc:'):
            out[f['name'].lower()] = ln[5:]
    return out


# --------------------------------------------------------------------------------------- codes
# skillcalc codes (D2MOO SKILLS_GetSpecialParamValue ids 0-72, the rest D2Sigma / V2 tooltips)

def _ln(x, y):
    return 'Param%d + Param%d × (level − 1)' % (x, y)


def _dm(x, y):
    return 'from Param%d toward Param%d, rising more slowly each level' % (x, y)


SKILL_CODE_INFO = {
    'lvl': ('skill level', 'The skill level including +skills from items.'),
    'blvl': ('base level', 'Hard points: the skill level without +skills from items.'),
    'ulvl': ('character level', 'The level of the character using the skill.'),
    'edmn': ('elemental damage min', 'EMin + EMinLev per level band (whole points).'),
    'edmx': ('elemental damage max', 'EMax + EMaxLev per level band (whole points).'),
    'edns': ('elemental damage min (1/256)', 'Elemental minimum in 256ths of a point.'),
    'edxs': ('elemental damage max (1/256)', 'Elemental maximum in 256ths of a point.'),
    'edln': ('elemental duration', 'ELen + ELevLen per level band, in frames (25 = 1 s).'),
    'toht': ('attack rating bonus', 'ToHit + LevToHit per level, or the ToHitCalc formula.'),
    'mana': ('mana cost', 'mana + lvlmana per level, shifted by manashift.'),
    'usmc': ('mana cost (1/256)', 'Mana cost in 256ths.'),
    'mps': ('mana per second', 'Mana drain per second of a channelled skill.'),
    'math': ('mastery attack rating', 'Attack rating % from a weapon mastery.'),
    'madm': ('mastery damage', 'Damage % from a weapon mastery.'),
    'macr': ('mastery crit', 'Critical strike % from a weapon mastery.'),
    'len': ('aura length', 'The auralencalc formula.'),
    'rng': ('aura range', 'The aurarangecalc formula.'),
    'pets': ('pet maximum', 'The petmax formula.'),
    'skpt': ('skill point cost', 'The skpoints formula.'),
    'wdm': ('weapon damage %', 'SrcDam × 100 / 128.'),
    'skcd': ('cooldown', 'The delay formula (frames).'),
    'mlvl': ('maximum skill level', 'Median: the skill level cap (runtime).'),
    'aura': ('buff active', 'Median: 1 while the skill\'s aura/buff is on (runtime).'),
    'area': ('in town', 'Median: where the character stands (runtime).'),
    'mode': ('character mode', 'Median: what the character is doing (runtime).'),
    'pass': ('passive unlocked', 'Median: the hidden passive has a level (runtime).'),
    'maxe': ('at maximum level', 'Median: the skill is at its maximum level (runtime).'),
    'mnhp': ('summon life', 'Median: the summon\'s life (runtime).'),
    'mnar': ('summon attack rating', 'Median: the summon\'s attack rating (runtime).'),
    'pdmn': ('physical damage min (1/256)', 'Median: physical minimum in 256ths.'),
    'pdmx': ('physical damage max (1/256)', 'Median: physical maximum in 256ths.'),
    'enma': ('elemental min incl. mastery', 'Elemental minimum including spell mastery.'),
    'exma': ('elemental max incl. mastery', 'Elemental maximum including spell mastery.'),
    'edma': ('elemental duration incl. mastery', 'Elemental length including mastery.'),
    'enms': ('elemental min incl. mastery (1/256)', ''),
    'exms': ('elemental max incl. mastery (1/256)', ''),
    'skcp': ('skill cap bonus', 'Median: meaning not confirmed (runtime).'),
    'skcn': ('skill cap bonus 2', 'Median: meaning not confirmed (runtime).'),
    'bmax': ('bmax', 'Median: meaning not confirmed (runtime).'),
}
for _i in range(1, 9):
    SKILL_CODE_INFO['par%d' % _i] = ('Param%d' % _i, 'Column Param%d of this skill.' % _i)
for _x in (1, 3, 5, 7):
    _k = '%d%d' % (_x, _x + 1)
    SKILL_CODE_INFO['ln' + _k] = (_ln(_x, _x + 1), 'Linear: Param%d at level 1, +Param%d per level.' % (_x, _x + 1))
    SKILL_CODE_INFO['dm' + _k] = (_dm(_x, _x + 1), 'Diminishing returns: Param%d + (Param%d − Param%d) × '
                                  '(110·lvl/(lvl+6))/100, never above Param%d.' % (_x, _x + 1, _x, _x + 1))
    SKILL_CODE_INFO['bl' + _k] = ('Param%d + Param%d × (base level − 1)' % (_x, _x + 1),
                                  'Median: linear over the base level (hard points).')
    SKILL_CODE_INFO['bd' + _k] = ('Param%d toward Param%d over base level' % (_x, _x + 1),
                                  'Median: diminishing over the base level.')
    SKILL_CODE_INFO['blz%d' % _x] = ('Param%d over base level from 0' % _x, 'Median: linear from base level 0.')
    SKILL_CODE_INFO['bdz%d' % _x] = ('Param%d diminishing from base level 0' % _x, 'Median (runtime).')
for _i in range(1, 5):
    SKILL_CODE_INFO['clc%d' % _i] = ('calc%d' % _i, 'The value of this skill\'s calc%d formula.' % _i)
for _i in range(1, 7):
    SKILL_CODE_INFO['ast%d' % _i] = ('aura stat value %d' % _i, 'The aurastatcalc%d formula.' % _i)
    SKILL_CODE_INFO['syn%d' % _i] = ('item bonus %d' % _i, 'Median: per-skill modifier stat %d from items '
                                     '(0 without such items).' % _i)
for _i in range(1, 6):
    SKILL_CODE_INFO['pst%d' % _i] = ('passive stat value %d' % _i, 'The passivecalc%d formula.' % _i)
for _m in (1, 2, 3):
    SKILL_CODE_INFO['m%den' % _m] = ('missile %d elemental min' % _m, 'Of skilldesc descmissile%d.' % _m)
    SKILL_CODE_INFO['m%dex' % _m] = ('missile %d elemental max' % _m, 'Of skilldesc descmissile%d.' % _m)
    SKILL_CODE_INFO['m%del' % _m] = ('missile %d elemental length' % _m, 'Of skilldesc descmissile%d.' % _m)
    SKILL_CODE_INFO['m%drn' % _m] = ('missile %d range' % _m, 'Of skilldesc descmissile%d.' % _m)

MISS_CODE_INFO = {
    'lvl': ('missile level', 'The level of the skill that fired it.'),
    'blvl': ('base level', 'Hard points of the skill that fired it.'),
    'edmn': ('elemental damage min', ''), 'edmx': ('elemental damage max', ''),
    'edln': ('elemental duration', ''), 'edns': ('elemental min (1/256)', ''),
    'edxs': ('elemental max (1/256)', ''), 'damn': ('damage min', ''), 'damx': ('damage max', ''),
    'dmns': ('damage min (1/256)', ''), 'dmxs': ('damage max (1/256)', ''),
    'rang': ('range', 'Range + LevRange × level.'), 'msyn': ('synergy', 'Median (runtime).'),
}
_MISS_COLS = {'par': 'Param', 'cpa': 'CltParam', 'hpa': 'sHitPar', 'chp': 'cHitPar', 'dpa': 'dParam'}
for _p, _c in _MISS_COLS.items():
    for _i in range(1, 6):
        MISS_CODE_INFO['%s%d' % (_p, _i)] = ('%s%d' % (_c, _i), 'Column %s%d of this missile.' % (_c, _i))
for _code, _c in (('sl12', 'Param1/2'), ('sl34', 'Param3/4'), ('cl12', 'CltParam1/2'), ('cl34', 'CltParam3/4'),
                  ('shl1', 'sHitPar1/2'), ('chl1', 'cHitPar1/2'), ('dl12', 'dParam1/2')):
    MISS_CODE_INFO[_code] = ('linear ' + _c, 'First + second × (level − 1).')
    MISS_CODE_INFO[_code.replace('l', 'd', 1) if _code[1] == 'l' else _code] = ('diminishing ' + _c, '')
MISS_CODE_INFO.update({'sd12': ('diminishing Param1/2', ''), 'sd34': ('diminishing Param3/4', ''),
                       'cd12': ('diminishing CltParam1/2', ''), 'cd34': ('diminishing CltParam3/4', ''),
                       'shd1': ('diminishing sHitPar1/2', ''), 'chd1': ('diminishing cHitPar1/2', ''),
                       'dd12': ('diminishing dParam1/2', '')})

# how a code reads inside the expression (bracketed when it is a small formula itself)
EXPR_NAME = {}
for _x in (1, 3, 5, 7):
    EXPR_NAME['ln%d%d' % (_x, _x + 1)] = '[Param%d + Param%d per level]' % (_x, _x + 1)
    EXPR_NAME['dm%d%d' % (_x, _x + 1)] = '[Param%d → Param%d, diminishing]' % (_x, _x + 1)
    EXPR_NAME['bl%d%d' % (_x, _x + 1)] = '[Param%d + Param%d per base level]' % (_x, _x + 1)
    EXPR_NAME['bd%d%d' % (_x, _x + 1)] = '[Param%d → Param%d by base level, diminishing]' % (_x, _x + 1)

STAT_SUB_WORD = {'accr': '', 'base': 'base ', 'mod': 'bonus '}
FN_WORDS = {
    'min': 'the smaller of', 'max': 'the larger of', 'rand': 'a random number between',
    'state': 'has state', 'class': 'character class is', 'prob': 'chance', 'sktree': 'points in skill tree',
    'lstat': 'stat (layer)', 'sumcount': 'number of summons', 'istat': 'item stat',
}
SIGMA_FNS = {'state', 'class', 'prob', 'sktree', 'lstat', 'sumcount', 'istat'}

# sample values for what only the running game knows
STAT_DEFAULTS = {'strength': 100, 'dexterity': 100, 'vitality': 100, 'energy': 100, 'level': 50}


def code_default(code, row):
    """Sample value for a runtime-only code: mlvl = the row's maxlvl, else 0."""
    if code == 'mlvl':
        return _int(_rowget(row or {}, '*skills2.maxlevel')) or _int(_rowget(row or {}, 'maxlvl')) or 20
    return 0


def param_columns(code, table):
    """Columns a calc code reads directly from the row (editable in place)."""
    if table == 'missiles':
        m = re.match(r'^(par|cpa|hpa|chp|dpa)(\d)$', code)
        if m:
            return ['%s%s' % (_MISS_COLS[m.group(1)], m.group(2))]
        pairs = {'sl12': ('Param', 1), 'sd12': ('Param', 1), 'sl34': ('Param', 3), 'sd34': ('Param', 3),
                 'cl12': ('CltParam', 1), 'cd12': ('CltParam', 1), 'cl34': ('CltParam', 3),
                 'cd34': ('CltParam', 3), 'shl1': ('sHitPar', 1), 'shd1': ('sHitPar', 1),
                 'chl1': ('cHitPar', 1), 'chd1': ('cHitPar', 1), 'dl12': ('dParam', 1),
                 'dd12': ('dParam', 1)}
        if code in pairs:
            c, i = pairs[code]
            return ['%s%d' % (c, i), '%s%d' % (c, i + 1)]
        if code == 'rang':
            return ['Range', 'LevRange']
        return []
    m = re.match(r'^par(\d)$', code)
    if m:
        return ['Param' + m.group(1)]
    m = re.match(r'^(ln|dm|bl|bd)(\d)(\d)$', code)
    if m:
        return ['Param' + m.group(2), 'Param' + m.group(3)]
    m = re.match(r'^b[ld]z(\d)$', code)
    if m:
        return ['Param' + m.group(1)]
    if code == 'toht':
        return ['ToHit', 'LevToHit']
    if code in ('mana', 'usmc'):
        return ['mana', 'lvlmana', 'manashift']
    if code == 'wdm':
        return ['SrcDam']
    if code in ('edmn', 'edns'):
        return ['EMin'] + ['EMinLev%d' % i for i in range(1, 6)]
    if code in ('edmx', 'edxs'):
        return ['EMax'] + ['EMaxLev%d' % i for i in range(1, 6)]
    if code == 'edln':
        return ['ELen', 'ELevLen1', 'ELevLen2', 'ELevLen3']
    return []


# --------------------------------------------------------------------------------------- context

class Ctx:
    """What explain()/evaluate() know about the row and its project.

    txt_dir: the folder of the open txt (links, other rows, skillcalc names); table: e.g. 'skills';
    row: {column: text} of the edited row (the live values); docs: column docs dict or None;
    samples: {key: int} user-set values for runtime-only inputs; bonus: +skills (lvl - blvl)."""

    def __init__(self, txt_dir=None, table='skills', row=None, docs=None, samples=None, bonus=0,
                 version=None, row_provider=None):
        self.txt_dir = txt_dir
        self.table = (table or '').lower()
        self.row = row or {}
        self.docs = docs
        self.samples = samples if samples is not None else {}
        self.bonus = bonus
        self._version = version
        self._proj = None
        self._rows = {}
        self.row_provider = row_provider        # (table) -> (header, rows) live data, or None

    # -- project
    @property
    def project(self):
        if self._proj is None:
            from .txt2bin import Project
            self._proj = Project(self.txt_dir or '', version=self._version or 'auto')
        return self._proj

    @property
    def version(self):
        if self._version is None:
            try:
                self._version = self.project.version
            except Exception:
                self._version = 'mxl'
        return self._version

    def rows(self, table):
        """-> (header list, rows list) as str, live data first, else the txt beside the file."""
        table = table.lower()
        if self.row_provider:
            got = self.row_provider(table)
            if got:
                return got
        if table not in self._rows:
            res = None
            try:
                t = self.project.txt(table)
                if t:
                    hdr = [h.decode('latin-1') for h in t[0]]
                    res = (hdr, [[c.decode('latin-1') for c in r] for r in t[1]])
            except Exception:
                res = None
            self._rows[table] = res
        return self._rows[table]

    def find_row(self, table, key, col=None):
        got = self.rows(table)
        if not got:
            return None
        hdr, rows = got
        ci = 0
        if col:
            low = [h.lower() for h in hdr]
            if col.lower() in low:
                ci = low.index(col.lower())
        kl = key.lower()
        for r in rows:
            if ci < len(r) and r[ci].lower() == kl:
                return dict(zip(hdr, r))
        m = re.match(r'^[a-z]{2}(\d+)$', key)   # bin2txt placeholder: sk359 = row 359
        if m and int(m.group(1)) < len(rows):
            return dict(zip(hdr, rows[int(m.group(1))]))
        m = re.search(r'\(([a-z]{2})(\d+)\)$', key)  # 'Egg Trap (sk359)'
        if m and int(m.group(2)) < len(rows):
            return dict(zip(hdr, rows[int(m.group(2))]))
        return None

    def calc_codes(self, kind):
        """param id -> code name, from skillcalc / misscalc beside the file (first row wins)."""
        t = 'misscalc' if kind == 'missiles' else 'skillcalc'
        got = self.rows(t)
        if not got:
            return []
        return [r[0] if r else '' for r in got[1]]

    def col_label(self, col):
        d = (self.docs or {}).get('columns', {}) if self.docs else {}
        for k, v in d.items():
            if k.lower() == col.lower() and v.get('label'):
                return v['label']
        for p in (self.docs or {}).get('patterns', []) if self.docs else []:
            m = re.match(p.get('match', '$^'), col)
            if m and p.get('label'):
                try:
                    return p['label'].format(*([None] + list(m.groups())))
                except (IndexError, KeyError):
                    return p['label']
        return None


def _rowget(row, col, default=''):
    if col in row:
        return row[col]
    cl = col.lower()
    for k, v in row.items():
        if k.lower() == cl:
            return v
    return default


def _int(s):
    s = (s or '').strip()
    m = re.match(r'^-?\d+', s)
    return int(m.group(0)) if m else 0


# --------------------------------------------------------------------------------------- explain

def explain(expr, table, row, ctx=None):
    """Readable rendering + variables of one calc cell.  table: the row's table (skills,
    skilldesc, missiles, weapons ...).  -> dict(text, vars, notes, ok, formula)."""
    ctx = ctx or Ctx(table=table, row=row)
    kind = _table_kind(table)
    f = parse(expr or '', kind)
    out = {'formula': f, 'vars': [], 'notes': [], 'ok': f.root is not None, 'text': ''}
    if f.raw:
        out['text'] = 'raw bytecode (not shown as a formula)'
        return out
    if f.root is None:
        out['text'] = '' if not (expr or '').strip() else '(could not be read: %s)' % (f.error or '?')
        return out
    seen = {}
    vars_ = out['vars']
    notes = out['notes']
    is_skill = kind == 'skills'
    info = MISS_CODE_INFO if kind == 'missiles' else SKILL_CODE_INFO
    vrow = row if kind != 'skills' or table.lower() != 'skilldesc' else (_skill_of_desc(ctx, row) or {})

    def var(key, **kw):
        if key in seen:
            return seen[key]
        v = dict(token=key, **kw)
        seen[key] = v
        vars_.append(v)
        return v

    def code_var(code):
        lc = code.lower()
        if lc not in info and not re.match(r'^p\d+$', lc):
            return None
        name, desc = info.get(lc, ('calc parameter ' + code, 'A placeholder for calc parameter %s.' % code))
        cols = param_columns(lc, 'missiles' if kind == 'missiles' else 'skills')
        vals = []
        for c in cols:
            lab = ctx.col_label(c)
            vals.append((c, _rowget(vrow, c, ''), lab))
        short = EXPR_NAME.get(lc, name)
        if re.match(r'^par\d$', lc) or re.match(r'^(par|cpa|hpa|chp|dpa)\d$', lc):
            lab = vals[0][2] if vals and vals[0][2] else None
            short = '%s%s' % (cols[0], ' (%s)' % lab if lab else '')
        runtime = lc not in _EVALUABLE_SKILL and kind == 'skills' or (kind == 'missiles' and lc == 'msyn')
        v = var(lc, name=short, meaning=desc, columns=[c for c, _v, _l in vals],
                value=', '.join('%s = %s' % (c, val or '0') for c, val, _l in vals) or None,
                editable=bool(cols), kind='runtime' if runtime and not cols else 'code')
        if runtime and not cols:
            v['sample'] = 'code:' + lc
            v['default'] = code_default(lc, vrow)
        return v

    def r(n, minp=0):
        t, p = render(n)
        return '(%s)' % t if p < minp else t

    def render(n):
        if n is None:
            return '…', 9
        k = n.kind
        if k == 'num':
            return str(n.val), 9
        if k == 'name':
            v = code_var(n.val)
            if v is None:
                notes.append('"%s" is not a known calc code: the game reads 0.' % n.val)
                return n.val, 9
            return v['name'], 9
        if k == 'quoted':
            return n.val, 9
        if k == 'dot':
            return '.' + n.val, 9
        if k == 'neg':
            return '−' + r(n.kids[0], 9), 8
        if k == 'bin':
            sym = {'*': '×', '/': '÷', '-': '−', '<=': '≤', '>=': '≥', '==': '=', '!=': '≠'}.get(n.val, n.val)
            p = {'^': 7, '*': 6, '/': 6, '+': 5, '-': 5}.get(n.val, 4)
            if n.val == '/':
                if '÷ drops the fraction (whole numbers only).' not in notes:
                    notes.append('÷ drops the fraction (whole numbers only).')
            a = r(n.kids[0], p)
            b = r(n.kids[1], p + 1)
            if n.val == '^':
                return '%s to the power %s' % (a, b), p
            return '%s %s %s' % (a, sym, b), p
        if k == 'tern':
            c, a, b = n.kids
            return 'if %s then %s, otherwise %s' % (r(c, 4), r(a, 4), r(b, 4)), 1
        if k == 'seq':
            notes.append('Several values side by side: the game uses the last one.')
            return ' ; '.join(r(x) for x in n.kids), 0
        if k == 'fn':
            return fn(n), 9
        return '?', 9

    def fn(n):
        nm, ks = n.val, n.kids
        if nm in ('skill', 'miss', 'stat', 'sklvl', 'istat') and ks and ks[0] is not None \
                and ks[0].kind in ('quoted', 'num', 'name'):
            target = ks[0].val if ks[0].kind != 'num' else '#%d' % ks[0].val
            subs = [x.val for x in ks[1:] if x is not None and x.kind in ('dot', 'name', 'num')]
            sub = str(subs[0]) if subs else ''
            if nm == 'stat':
                word = STAT_SUB_WORD.get(sub, '')
                if sub not in STAT_SUB_WORD:
                    word = '(part %s) ' % sub
                key = 'stat:%s' % target
                v = var(key, name='%s%s' % (word, target), kind='stat', editable=False, columns=[],
                        meaning='The character\'s %s%s (only known in game: set a sample value).' % (word, target),
                        value=None, sample=key, default=STAT_DEFAULTS.get(str(target).lower(), 0))
                return v['name']
            if nm == 'skill':
                cname = SKILL_CODE_INFO.get(sub.lower(), (sub,))[0]
                if _skill_code_needs_level(sub.lower()):
                    key = 'skill:%s' % target
                    var(key, name='%s level' % _tidy(target), kind='skill', editable=False, columns=[],
                        meaning='The character\'s level in %s (only known in game: set a sample value).'
                                % target, value=None, sample=key, default=0)
                else:
                    key = 'skill:%s.%s' % (target, sub.lower())
                    var(key, name='%s\'s %s' % (_tidy(target), cname), kind='runtime', editable=False,
                        columns=[], meaning='%s of skill %s. %s Only known in game: set a sample value.'
                                            % (cname, _tidy(target), SKILL_CODE_INFO.get(sub.lower(), ('', ''))[1]),
                        value=None, sample=key, default=0)
                return '%s\'s %s' % (_tidy(target), cname)
            if nm == 'miss':
                cname = MISS_CODE_INFO.get(sub.lower(), (sub,))[0]
                var('miss:%s' % target, name='missile %s' % target, kind='missile', editable=False, columns=[],
                    meaning='Read from missile %s at this skill\'s level.' % target, value=None)
                return 'missile %s\'s %s' % (_tidy(target), cname)
            if nm == 'sklvl':
                a = SKILL_CODE_INFO.get(sub.lower(), (sub,))[0]
                b = SKILL_CODE_INFO.get(str(subs[1]).lower(), (subs[1] if len(subs) > 1 else '?',))[0] \
                    if len(subs) > 1 else '?'
                var('skill:%s' % target, name='%s level' % target, kind='skill', editable=False, columns=[],
                    meaning='Skill %s, read at a level taken from this skill.' % target, value=None)
                return '%s\'s %s at level = this skill\'s %s' % (_tidy(target), b, a)
        args = [r(x) for x in ks]
        if nm in ('min', 'max') and len(args) == 2:
            return '%s %s and %s' % (FN_WORDS[nm], args[0], args[1])
        if nm == 'rand' and len(args) == 2:
            return 'a random number from %s to %s' % (args[0], args[1])
        if nm in SIGMA_FNS or nm.startswith('fn'):
            key = 'fn:%s(%s)' % (nm, ','.join(args))
            var(key, name='%s(%s)' % (nm, ', '.join(args)), kind='runtime', editable=False, columns=[],
                meaning='Median (D2Sigma) %s: depends on the game at runtime; uses the sample value.'
                        % FN_WORDS.get(nm, 'function'), value=None, sample=key, default=0)
            return '%s %s' % (FN_WORDS.get(nm, nm), ', '.join(args))
        return '%s(%s)' % (nm, ', '.join(args))

    try:
        out['text'] = r(f.root)
    except RecursionError:
        out['text'] = expr
    if f.trailing_open:
        notes.append('%d unclosed "(" at the end (kept as written).' % f.trailing_open)
    if f.stopped:
        notes.append('The game stops reading at an unknown character; the rest is ignored.')
    if f.root is not None and f.root.kind != 'tern' and any(x.kind == 'tern' for x in f.root.walk()):
        notes.append('The game stops at the first "if … then … otherwise" and returns its value.')
    if is_skill or kind == 'missiles':
        for lv in ('lvl', 'blvl'):
            if lv in seen:
                seen[lv]['kind'] = 'level'
    return out


def _skill_code_needs_level(code):
    """skill('X'.code): True when the code is computed from X's row at the character's level in X
    (so the sample is that level); False for runtime-only codes (aura, syn1 ...: sampled directly)."""
    return code in _EVALUABLE_SKILL and code != 'ulvl'


def _tidy(name):
    """'Egg Trap (sk359)' -> 'Egg Trap' for display (bin2txt's uniqueness suffix)."""
    return re.sub(r' \([a-z]{2}\d+\)$', '', str(name))


def _table_kind(table):
    t = (table or '').lower()
    if t in ('missiles',):
        return 'missiles'
    if t in ('weapons', 'armor', 'misc', 'items'):
        return 'items'
    return 'skills'


def _skill_of_desc(ctx, desc_row):
    """The skills row whose skilldesc is this skilldesc row's key."""
    key = _rowget(desc_row, 'skilldesc', '')
    if not key:
        return None
    return ctx.find_row('skills', key, 'skilldesc')


# --------------------------------------------------------------------------------------- evaluate

class Unknown(Exception):
    pass


def _i32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def _cdiv(a, b):
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    return _i32(q if (a >= 0) == (b >= 0) else -q)


def _dimin(lvl, p, mx):
    """D2Common_11033."""
    v = p + _cdiv((mx - p) * _cdiv(110 * lvl, lvl + 6), 100)
    return mx if v > mx else v


_EVALUABLE_SKILL = set(
    ['lvl', 'blvl', 'ulvl', 'edmn', 'edmx', 'edns', 'edxs', 'edln', 'toht', 'mana', 'usmc', 'mps', 'len', 'rng',
     'pets', 'skpt', 'wdm', 'skcd', 'enma', 'exma', 'edma', 'enms', 'exms']
    + ['par%d' % i for i in range(1, 9)] + ['clc%d' % i for i in range(1, 5)]
    + ['ast%d' % i for i in range(1, 7)] + ['pst%d' % i for i in range(1, 6)]
    + ['%s%d%d' % (p, x, x + 1) for p in ('ln', 'dm', 'bl', 'bd') for x in (1, 3, 5, 7)])
_CALC_COL = {'len': 'auralencalc', 'rng': 'aurarangecalc', 'pets': 'petmax', 'skpt': 'skpoints',
             'skcd': 'delay'}
_CALC_COL.update({'clc%d' % i: 'calc%d' % i for i in range(1, 5)})
_CALC_COL.update({'ast%d' % i: 'aurastatcalc%d' % i for i in range(1, 7)})
_CALC_COL.update({'pst%d' % i: 'passivecalc%d' % i for i in range(1, 6)})


class _Eval:
    def __init__(self, ctx, kind, rand_hi=False):
        self.ctx = ctx
        self.kind = kind
        self.rand_hi = rand_hi
        self.assumed = {}           # sample key -> value used
        self.depth = 0
        self._code_cache = {}

    # -- compile with the project's linkers
    def compile(self, text, kind):
        from .txt2bin import compile_expr
        key = (text, kind)
        if key not in self._code_cache:
            p = self.ctx.project
            link = p._calc_link(kind)
            kw = p.calc_keywords(kind)
            self._code_cache[key] = compile_expr(text.encode('latin-1', 'replace')[:256], kind, link,
                                                 arity=True, keywords=kw,
                                                 lenient=self.ctx.version == 'mxl')
        return self._code_cache[key]

    def sample(self, key, default=0):
        v = self.ctx.samples.get(key, default)
        self.assumed[key] = v
        return v

    # -- Fog's evaluator
    def run(self, code, kind, unit):
        """unit: dict(row=skills/missiles row, lvl, blvl, table='skills'|'missiles')."""
        self.depth += 1
        if self.depth > 16:
            raise Unknown('formula recursion')
        try:
            st = []

            def pop():
                return st.pop() if st else 0

            funcs = calc.FUNCS.get('itemscode' if kind == 'items' else 'skillscode')
            pos, n = 0, len(code)
            while pos < n:
                op = code[pos]
                pos += 1
                if op == 0:
                    return pop()
                if op in (4, 5, 6, 7, 8, 9):
                    sz = {4: 1, 7: 1, 5: 2, 8: 2, 6: 4, 9: 4}[op]
                    if op >= 7:
                        v = int.from_bytes(code[pos:pos + sz], 'little', signed=True)
                    else:
                        v = int.from_bytes(code[pos:pos + sz], 'little', signed=False)
                    pos += sz
                    st.append(_i32(self.param(v, unit) if op <= 6 else v))
                elif op == 1:
                    fid = code[pos]
                    pos += 1
                    nm, ar = funcs[fid] if fid < len(funcs) else ('fn%d' % fid, 1)
                    args = [0, 0, 0]
                    for i in range(ar - 1, -1, -1):
                        args[i] = pop()
                    st.append(_i32(self.func(nm, args[:ar], unit)))
                elif 10 <= op <= 20:
                    b, a = pop(), pop()
                    st.append(_i32(_binop(op, a, b)))
                elif op == 21:
                    st.append(_i32(-pop()))
                elif op == 22:
                    c, b, a = pop(), pop(), pop()
                    st.append(b if a else c)
                    return pop()        # Fog: the ternary falls into 'default: return pop'
                else:
                    return pop()
            return 0
        finally:
            self.depth -= 1

    # -- parameters (skillcalc / misscalc codes)
    def param(self, pid, unit):
        codes = self.ctx.calc_codes(unit['table'])
        code = codes[pid].lower() if pid < len(codes) else 'p%d' % pid
        if unit['table'] == 'missiles':
            return self.miss_param(code, unit)
        return self.skill_param(code, unit)

    def skill_param(self, code, u):
        row, lvl, blvl = u['row'], u['lvl'], u['blvl']

        def P(i):
            return _int(_rowget(row, 'Param%d' % i))
        m = re.match(r'^par(\d)$', code)
        if m:
            return P(int(m.group(1)))
        m = re.match(r'^(ln|dm|bl|bd)(\d)(\d)$', code)
        if m:
            L = lvl if m.group(1) in ('ln', 'dm') else blvl
            a, b = P(int(m.group(2))), P(int(m.group(3)))
            if m.group(1) in ('ln', 'bl'):
                return a + (L - 1) * b if L > 0 else 0
            if L <= 0 and not (m.group(1) == 'dm' and code == 'dm78'):
                return 0
            return _dimin(L, a, b)
        if code == 'lvl':
            return lvl
        if code == 'blvl':
            return blvl
        if code == 'ulvl':
            return self.sample('stat:level', STAT_DEFAULTS['level'])
        if code in ('edmn', 'edmx', 'edns', 'edxs', 'enma', 'exma', 'enms', 'exms'):
            if lvl <= 0:
                return 0
            v = self.elem(u, 'x' in code)           # edmx/edxs/exma/exms are the max side
            return v >> 8 if code in ('edmn', 'edmx', 'enma', 'exma') else v
        if code in ('edln', 'edma'):
            return self.elen(u) if lvl > 0 else 0
        if code == 'toht':
            if lvl <= 0:
                return 0
            c = _rowget(row, 'ToHitCalc', '')
            if c.strip():
                return self.run(self.compile(c, 'skills'), 'skills', u)
            return _int(_rowget(row, 'ToHit')) + (lvl - 1) * _int(_rowget(row, 'LevToHit'))
        if code in ('mana', 'usmc'):
            if lvl <= 0:
                return 0
            # D2Common skill calc ids 0x15/0x2a (1.13c 0x6fda1070): no minmana here;
            # minmana only clamps the cost D2Game actually deducts.  The sum may be negative.
            v = (_int(_rowget(row, 'mana')) + _int(_rowget(row, 'lvlmana')) * (lvl - 1)) \
                << max(0, _int(_rowget(row, 'manashift')))
            return v >> 8 if code == 'mana' else v
        if code == 'mps':
            if lvl <= 0:
                return 0
            # the whole cost is multiplied by 25 (D2Common 1.13c 0x6fda1070 case 0x16); D2MOO's
            # 25*mana + (lvl-1)*lvlmana is wrong
            t = _cdiv(25 * (_int(_rowget(row, 'mana')) + (lvl - 1) * _int(_rowget(row, 'lvlmana'))), 2)
            return (t << max(0, _int(_rowget(row, 'manashift')))) >> 8
        if code == 'wdm':
            return _cdiv(_int(_rowget(row, 'SrcDam')) * 100, 128)
        if code in _CALC_COL:
            c = _rowget(row, _CALC_COL[code], '')
            if not c.strip():
                return 0
            return self.run(self.compile(c, 'skills'), 'skills', u)
        m = re.match(r'^blz(\d)$', code)
        if m and blvl <= 0:
            return P(int(m.group(1)))
        return self.sample('code:' + code, code_default(code, row))

    def elem(self, u, is_max):
        """SKILLS_GetMin/MaxElemDamage (256ths): base + per-level bands, << HitShift (from 8),
        then the EDmgSymPerCalc synergy %."""
        row, lvl = u['row'], u['lvl']
        b = 'EMax' if is_max else 'EMin'
        v = _int(_rowget(row, b))
        bands = ((2, 8), (9, 16), (17, 22), (23, 28), (29, 10 ** 9))
        for i, (lo, hi) in enumerate(bands, 1):
            if lvl >= lo:
                v += (min(lvl, hi) - lo + 1) * _int(_rowget(row, '%sLev%d' % (b, i)))
        hs = _int(_rowget(row, 'HitShift'))       # D2MOO: << nToHitShift (blank cell = 0)
        v = v << hs if hs >= 0 else v
        c = _rowget(row, 'EDmgSymPerCalc', '')
        # the min side applies the synergy only when the shifted value is > 256 or EMinLev1 is set
        # (D2Common CalcSkillElemMin 1.13c 0x6fda0460; the max side 0x6fda0360 has no such gate)
        if c.strip() and (is_max or v > 256 or _int(_rowget(row, 'EMinLev1')) != 0):
            pct = self.run(self.compile(c, 'skills'), 'skills', u)
            v = v + _cdiv(v * pct, 100)
        return v

    def elen(self, u):
        row, lvl = u['row'], u['lvl']
        v = _int(_rowget(row, 'ELen'))
        for i, (lo, hi) in enumerate(((2, 8), (9, 16), (17, 10 ** 9)), 1):
            if lvl >= lo:
                v += (min(lvl, hi) - lo + 1) * _int(_rowget(row, 'ELevLen%d' % i))
        c = _rowget(row, 'ELenSymPerCalc', '')
        if c.strip():
            v += _cdiv(v * self.run(self.compile(c, 'skills'), 'skills', u), 100)
        return v

    def miss_param(self, code, u):
        row, lvl = u['row'], u['lvl']
        m = re.match(r'^(par|cpa|hpa|chp|dpa)(\d)$', code)
        if m:
            return _int(_rowget(row, '%s%s' % (_MISS_COLS[m.group(1)], m.group(2))))
        if code == 'lvl':
            return lvl
        if code == 'blvl':
            return u['blvl']
        cols = param_columns(code, 'missiles')
        if len(cols) == 2 and code != 'rang':
            a, b = _int(_rowget(row, cols[0])), _int(_rowget(row, cols[1]))
            if code[1] == 'l' or code[2] == 'l':
                return a + (lvl - 1) * b
            return _dimin(lvl, a, b)
        if code == 'rang':
            return _int(_rowget(row, 'Range')) + lvl * _int(_rowget(row, 'LevRange'))
        return self.sample('code:' + code, 0)

    # -- functions
    def func(self, nm, a, u):
        if nm == 'min':
            return a[1] if a[0] >= a[1] else a[0]
        if nm == 'max':
            return a[1] if a[0] <= a[1] else a[0]
        if nm == 'rand':
            self.assumed['rand'] = 'range'
            if a[0] >= a[1]:
                return a[0]
            return a[1] if self.rand_hi else a[0]
        if nm == 'stat':
            return self.stat(a[0], a[1])
        if nm in ('skill', 'sklvl'):
            sk = self.skill_row(a[0])
            if sk is None:
                return 0
            name, srow = sk
            sub = a[1] if nm == 'skill' else a[2]
            if nm == 'skill' and not _skill_code_needs_level(self._code_name(sub)):
                return self.sample('skill:%s.%s' % (name, self._code_name(sub)), 0)
            lv = self.sample('skill:%s' % name, 0) if nm == 'skill' else \
                self.skill_param(self._code_name(a[1]), u)
            su = dict(row=srow, lvl=lv, blvl=lv, table='skills')
            return self.skill_param(self._code_name(sub), su)
        if nm == 'miss':
            got = self.ctx.rows('missiles')
            if not got or a[0] < 0 or a[0] >= len(got[1]):
                return 0
            mrow = dict(zip(got[0], got[1][a[0]]))
            codes = self.ctx.calc_codes('missiles')
            code = codes[a[1]].lower() if 0 <= a[1] < len(codes) else ''
            return self.miss_param(code, dict(row=mrow, lvl=u['lvl'], blvl=u['blvl'], table='missiles'))
        key = 'fn:%s(%s)' % (nm, ','.join(str(x) for x in a))
        return self.sample(key, 0)

    def _code_name(self, pid):
        codes = self.ctx.calc_codes('skills')
        return codes[pid].lower() if 0 <= pid < len(codes) else 'p%d' % pid

    def skill_row(self, idx):
        got = self.ctx.rows('skills')
        if not got or idx < 0 or idx >= len(got[1]):
            return None
        r = got[1][idx]
        return (r[0] if r else str(idx)), dict(zip(got[0], r))

    def stat(self, sid, sub):
        got = self.ctx.rows('itemstatcost')
        name = str(sid)
        if got and 0 <= sid < len(got[1]) and got[1][sid]:
            name = got[1][sid][0]
        default = STAT_DEFAULTS.get(name.lower(), 0)
        return self.sample('stat:%s' % name, default)


def _binop(op, a, b):
    if op == 10:
        return int(a < b)
    if op == 11:
        return int(a > b)
    if op == 12:
        return int(a <= b)
    if op == 13:
        return int(a >= b)
    if op == 14:
        return int(a == b)
    if op == 15:
        return int(a != b)
    if op == 16:
        return a + b
    if op == 17:
        return a - b
    if op == 18:
        return _i32(a * b)
    if op == 19:
        return _cdiv(a, b)
    if b <= 0:
        return 1
    p = a
    for _ in range(min(b, 64) - 1):
        p = _i32(p * a)
    return p


def preview_levels(maxlvl):
    """1, 5, 10, 15, 20, 30, 40, 50, ... up to maxlvl (maxlvl itself included)."""
    maxlvl = max(1, maxlvl or 20)
    out = [x for x in (1, 5, 10, 15, 20) if x <= maxlvl]
    x = 30
    while x < maxlvl:
        out.append(x)
        x += 10
    if out[-1] != maxlvl:
        out.append(maxlvl)
    return out


def evaluate(expr, ctx, levels=(1, 5, 10, 15, 20, 30, 40, 50)):
    """Values of a calc cell per base level.  -> dict(values=[{level, value, lo, hi}], assumed={key:
    value}, error=None|str).  value is a string ('12', '3–9' for rand) or None when it cannot be
    computed (then error says why)."""
    out = {'values': [], 'assumed': {}, 'error': None}
    expr = (expr or '').strip('\r\n')
    if not expr.strip():
        out['error'] = 'empty'
        return out
    table = ctx.table
    kind = _table_kind(table)
    if re.match(r'^\?\{|^@\d+$', expr):
        out['error'] = 'raw bytecode'
        return out
    try:
        if kind == 'items':
            pool = 'items'
            unit_table = 'skills'
            urow = {}
        elif table == 'missiles':
            pool, unit_table, urow = 'missiles', 'missiles', ctx.row
        elif table == 'skilldesc':
            pool, unit_table = 'skills', 'skills'
            urow = _skill_of_desc(ctx, ctx.row) or {}
        else:
            pool, unit_table, urow = 'skills', 'skills', ctx.row
        lo_ev = _Eval(ctx, pool)
        code = lo_ev.compile(expr, pool)
        if not code:
            out['error'] = 'the game\'s compiler refuses this formula'
            return out
        hi_ev = None
        for L in levels:
            u = dict(row=urow, lvl=L + ctx.bonus, blvl=L, table=unit_table)
            lo = lo_ev.run(code, pool, u)
            v = {'level': L, 'lo': lo, 'hi': lo, 'value': str(lo)}
            if 'rand' in lo_ev.assumed:
                hi_ev = hi_ev or _Eval(ctx, pool, rand_hi=True)
                hi = hi_ev.run(code, pool, u)
                v['hi'] = hi
                if hi != lo:
                    v['value'] = '%d–%d' % (min(lo, hi), max(lo, hi))
            out['values'].append(v)
        out['assumed'] = {k: v for k, v in lo_ev.assumed.items() if k != 'rand'}
        if 'rand' in lo_ev.assumed:
            out['random'] = True
    except Unknown as e:
        out['error'] = 'depends on runtime: %s' % e
    except Exception as e:      # never break the form over a formula
        out['error'] = 'cannot evaluate: %s' % e
    return out


# --------------------------------------------------------------------------------------- gate

def gate(txt_dir, version=None, verbose=False):
    """Round-trip gate over every formula cell of a converted txt dir.
    -> dict(cells, text_same, bytes_same, tree, tree_same, parsed, failures=[...])."""
    from .txt2bin import Project, compile_expr, read_txt
    proj = Project(txt_dir, version=version or 'auto')
    ver = proj.version
    res = dict(version=ver, cells=0, text_same=0, bytes_same=0, tree=0, tree_same=0, refused=0, edit_ok=0,
               edit_tried=0, failures=[])
    tables = sorted({f[:-4].lower() for f in os.listdir(txt_dir) if f.lower().endswith('.txt')})
    for t in tables:
        cols = calc_columns(t, ver)
        if not cols:
            continue
        got = proj.txt(t)
        if not got:
            continue
        hdr, rows = got
        idx = {}
        for i, h in enumerate(hdr):
            hl = h.decode('latin-1').lower()
            if hl in cols and hl not in idx:
                idx[hl] = i
        for col, ci in idx.items():
            pool = cols[col]
            kind = POOL_KIND.get(pool, 'skills')
            link = proj._calc_link(kind)
            kw = proj.calc_keywords(kind)
            lenient = ver == 'mxl'
            for ri, r in enumerate(rows):
                cell = r[ci] if ci < len(r) else b''
                if not cell.strip():
                    continue
                text = cell.decode('latin-1')
                res['cells'] += 1
                f = parse(text, kind, link, kw, lenient)
                back = f.text()
                ok_t = back == text
                res['text_same'] += ok_t
                b0 = _compile(compile_expr, cell, kind, link, kw, lenient)
                b1 = _compile(compile_expr, back.encode('latin-1'), kind, link, kw, lenient)
                res['bytes_same'] += (b0 == b1)
                if f.root is not None:
                    res['tree'] += 1
                    try:
                        pf = f.postfix(link, kw)
                    except Exception as e:
                        pf = repr(e)
                    if pf == b0 or (not b0 and f.error):
                        res['tree_same'] += 1
                    elif len(res['failures']) < 30:
                        res['failures'].append((t, col, ri, text, b0.hex(), pf.hex() if isinstance(pf, bytes)
                                                else pf))
                    # mutation: bump the first number by one, re-render, compile
                    nums = [i for i, tk in enumerate(f.tokens) if tk.kind == 'num']
                    if nums and b0:
                        res['edit_tried'] += 1
                        g = parse(text, kind)
                        tk = g.tokens[nums[0]]
                        new = g.set_token(nums[0], str(int(tk.text) + 1))
                        b2 = _compile(compile_expr, new.encode('latin-1'), kind, link, kw, lenient)
                        res['edit_ok'] += bool(b2) and b2 != b0
                elif not f.raw and not b0:
                    res['refused'] += 1             # Fog refuses the cell too (field -1)
                elif not f.raw and len(res['failures']) < 30:
                    res['failures'].append((t, col, ri, text, 'no tree', f.error))
                if not ok_t and len(res['failures']) < 30:
                    res['failures'].append((t, col, ri, text, 'text', back))
    return res


def _compile(compile_expr, cell, kind, link, kw, lenient):
    from .txt2bin import POOL_OFF, RAW_CALC
    if RAW_CALC.match(cell) or POOL_OFF.match(cell):
        return cell
    return compile_expr(cell[:256], kind, link, arity=True, keywords=kw, lenient=lenient)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='calc formula explainer / round-trip gate')
    ap.add_argument('--gate', nargs='+', metavar='TXT_DIR')
    ap.add_argument('--explain', metavar='FORMULA')
    ap.add_argument('--table', default='skills')
    a = ap.parse_args(argv)
    if a.gate:
        bad = 0
        for d in a.gate:
            r = gate(d)
            print('%s [%s]: %d formula cells; text round trip %d; same bytes %d; tree %d, tree == Fog '
                  'bytecode %d (+%d refused by Fog and by the parser); edited-number compiles %d/%d' % (
                      d, r['version'], r['cells'], r['text_same'], r['bytes_same'], r['tree'],
                      r['tree_same'], r['refused'], r['edit_ok'], r['edit_tried']))
            for fl in r['failures'][:10]:
                print('   ', fl)
            bad += (r['text_same'] != r['cells']) + (r['bytes_same'] != r['cells'])
        return 1 if bad else 0
    if a.explain:
        e = explain(a.explain, a.table, {})
        print(e['text'])
        for v in e['vars']:
            print('  %-14s %s: %s' % (v['token'], v['name'], v['meaning']))
        for n in e['notes']:
            print('  note:', n)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
