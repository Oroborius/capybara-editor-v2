"""Decode D2 formula bytecode (skillscode / misscode / itemscode / skilldesccode .bin).

The txt compiler turns each calc column into postfix bytecode (Fog Calc.cpp in D2MOO):
    00            end of expression
    01 nn         call function nn of the table's function list (pops its args)
    04 b / 05 w / 06 d   parameter by id (name from skillcalc / misscalc 'code')
    07 b / 08 w / 09 d   signed constant
    0a < 0b > 0c <= 0d >= 0e == 0f != 10 + 11 - 12 * 13 / 14 ^
    15            negate
    16            ternary (cond ? a : b)
    02            an unclosed '(' (flushed before 00); rendered as a leading '('
A calc column in a table holds the byte offset of its expression in the code blob.

Function ids and arities come from the engine's {fn, nargs} tables:
  skills/skilldesc/missiles: D2Common 0x6fde9e24 (7 entries; names from the compile resolver
    FUN_6fdadcd0: min max rand skill miss stat sklvl).  D2Sigma replaces it with its 14-entry
    table 0x101df3a8 (ids 0-6 copied from D2Common at startup by FUN_10027130, 7-13 its own;
    names from its resolver FUN_100a75f0) and patches D2Common's evaluators to use it.
  items: D2Common 0x6fded354 (4 entries: min max rand stat, resolver FUN_6fdc1b40); D2Sigma's
    table 0x101d94b4 adds istat (4) and skill (5), resolver FUN_10070370.
Vanilla bytecode never uses the Sigma ids, so one list serves every version.  An id beyond the
list (unknown mods) is written fnN(...) with a guessed arity.

decode() renders one well-formed expression with precedence-aware parentheses; anything else
(Median: a function or ?: missing an operand, values left side by side, a cell cut at 255 chars
whose final flush emitted '(' markers) goes through render_faithful(), which writes text that
the Fog compiler port (txt2bin.compile_expr, lenient for 'mxl') turns into the same bytes.  A
second argument with no name is written as a plain argument list: stat(220,5).
"""
import struct

BINOPS = {0x0a: '<', 0x0b: '>', 0x0c: '<=', 0x0d: '>=', 0x0e: '==', 0x0f: '!=',
          0x10: '+', 0x11: '-', 0x12: '*', 0x13: '/', 0x14: '^'}
CMP = {'<', '>', '<=', '>=', '==', '!='}

# function lists per code table: (name, arity)
SKILL_FUNCS = [('min', 2), ('max', 2), ('rand', 2), ('skill', 2), ('miss', 2), ('stat', 2),
               ('sklvl', 3),
               # D2Sigma 0x101df3a8 ids 7-13 (fn 0x100a6b20, 0x100a68d0, 0x100a6a80,
               # 0x100a6af0, 0x100a69f0, 0x100a6b70, 0x100a6940)
               ('state', 1), ('class', 1), ('prob', 1), ('sktree', 1), ('lstat', 3),
               ('sumcount', 1), ('istat', 2)]
VANILLA_SKILL_FUNCS = 7
# D2Sigma item table 0x101d94b4: istat (0x100700c0) and skill (0x10070150, D2ItemCalc.cpp)
ITEM_FUNCS = [('min', 2), ('max', 2), ('rand', 2), ('stat', 2), ('istat', 2), ('skill', 2)]
VANILLA_ITEM_FUNCS = 4
MISS_FUNCS = SKILL_FUNCS
FUNCS = {'skillscode': SKILL_FUNCS, 'skilldesccode': SKILL_FUNCS, 'skills2code': SKILL_FUNCS,
         'misscode': MISS_FUNCS, 'itemscode': ITEM_FUNCS}
# which table names the 04/05/06 parameters
PARAM_TABLE = {'skillscode': 'skillcalc', 'skilldesccode': 'skillcalc', 'skills2code': 'skillcalc',
               'misscode': 'misscalc', 'itemscode': None}
STAT_SUB = {0: 'accr', 1: 'base', 2: 'mod'}


class Node:
    __slots__ = ('kind', 'val', 'kids')

    def __init__(self, kind, val=None, kids=()):
        self.kind = kind      # 'const', 'param', 'bin', 'neg', 'tern', 'fn'
        self.val = val
        self.kids = list(kids)


class Names:
    """Name provider.  Each callable gets an int and returns a str or None."""

    def __init__(self, param=None, skill=None, stat=None, missile=None, misscalc=None,
                 skillcalc=None):
        self.param = param or (lambda i: None)
        self.skill = skill or (lambda i: None)
        self.stat = stat or (lambda i: None)
        self.missile = missile or (lambda i: None)
        self.misscalc = misscalc or (lambda i: None)
        self.skillcalc = skillcalc or (lambda i: None)


def _tokens(buf, pos):
    """Yield (op, arg, start) until the 00 terminator.  Raises on truncation."""
    n = len(buf)
    while pos < n:
        op = buf[pos]
        start = pos
        pos += 1
        if op == 0:
            yield (0, None, start)
            return
        if op == 1:
            yield (1, buf[pos], start)
            pos += 1
        elif op in (4, 7):
            v = buf[pos]
            if op == 7 and v > 127:
                v -= 256
            yield (op, v, start)
            pos += 1
        elif op in (5, 8):
            v = struct.unpack_from('<H' if op == 5 else '<h', buf, pos)[0]
            yield (op, v, start)
            pos += 2
        elif op in (6, 9):
            v = struct.unpack_from('<I' if op == 6 else '<i', buf, pos)[0]
            yield (op, v, start)
            pos += 4
        else:
            yield (op, None, start)
    raise ValueError('calc: expression runs past end of buffer')


def expr_end(buf, pos):
    """Offset just past the 00 terminator of the expression at pos."""
    for op, _a, st in _tokens(buf, pos):
        if op == 0:
            return st + 1
    return len(buf)


def _build(toks, funcs, arity_guess):
    stack = []
    ui = 0
    for op, arg, _st in toks:
        if op == 0:
            break
        if op in (4, 5, 6):
            stack.append(Node('param', arg))
        elif op in (7, 8, 9):
            stack.append(Node('const', arg))
        elif op in BINOPS:
            if len(stack) < 2:
                return None
            b = stack.pop()
            a = stack.pop()
            stack.append(Node('bin', BINOPS[op], (a, b)))
        elif op == 0x02:
            continue          # an unclosed '(' (Fog emits it at the end); see decode()
        elif op == 0x15:
            if not stack:
                return None
            stack.append(Node('neg', None, (stack.pop(),)))
        elif op == 0x16:
            if len(stack) < 3:
                return None
            c = stack.pop()
            b = stack.pop()
            a = stack.pop()
            stack.append(Node('tern', None, (a, b, c)))
        elif op == 1:
            if arg < len(funcs):
                name, ar = funcs[arg]
            else:
                name = 'fn%d' % arg
                ar = arity_guess[ui] if ui < len(arity_guess) else 1
                ui += 1
            if len(stack) < ar:
                return None
            kids = stack[len(stack) - ar:] if ar else []
            del stack[len(stack) - ar:]
            stack.append(Node('fn', name, kids))
        else:
            return None
    if len(stack) != 1:
        return None
    return stack[0]


def parse(buf, pos=0, table='skillscode'):
    """Parse the expression at pos -> (Node or None, end offset)."""
    funcs = FUNCS.get(table, SKILL_FUNCS)
    toks = list(_tokens(buf, pos))
    end = toks[-1][2] + 1
    unknown = sum(1 for op, a, _ in toks if op == 1 and a >= len(funcs))
    if not unknown:
        return _build(toks, funcs, []), end
    # guess arities of unknown functions (prefer 1, then 2, 0, 3)
    order = (1, 2, 0, 3)

    def search(prefix):
        if len(prefix) == unknown:
            return _build(toks, funcs, prefix)
        for a in order:
            r = search(prefix + [a])
            if r is not None:
                return r
        return None
    if unknown > 6:
        return _build(toks, funcs, [1] * unknown), end
    return search([]), end


# --------------------------------------------------------------------- render

def _prec(n):
    if n.kind == 'bin':
        if n.val in CMP:
            return 1
        if n.val in ('+', '-'):
            return 2
        return 3
    if n.kind == 'tern':
        return 0
    return 9


def render(node, names=None, table='skillscode'):
    names = names or Names()

    def r(n):
        k = n.kind
        if k == 'const':
            return str(n.val)
        if k == 'param':
            return names.param(n.val) or 'p%d' % n.val
        if k == 'neg':
            return '-' + wrap(n.kids[0], 9)
        if k == 'tern':
            a, b, c = n.kids
            return '%s?%s:%s' % (wrap(a, 9), wrap(b, 9), wrap(c, 9))
        if k == 'bin':
            a, b = n.kids
            p = _prec(n)
            if p == 3:          # * / ^ : parenthesise any operator child
                return '%s%s%s' % (wrap(a, 9), n.val, wrap(b, 9))
            if p == 2:          # + - : parenthesise + - ?: and comparisons
                return '%s%s%s' % (wrap(a, 3), n.val, wrap(b, 3))
            return '%s%s%s' % (wrap(a, 2), n.val, wrap(b, 2))
        if k == 'fn':
            return fn(n)
        return '?'

    def wrap(n, minprec):
        s = r(n)
        return '(%s)' % s if _prec(n) < minprec else s

    def const_of(n):
        return n.val if n.kind == 'const' else None

    def quotable(nm):
        # Fog reads a quoted name up to the next apostrophe: such a row is written by number
        return nm if nm is not None and "'" not in nm else None

    def fn(n):
        nm, ks = n.val, n.kids
        if nm in ('skill', 'stat', 'miss') and len(ks) == 2:
            a, b = const_of(ks[0]), const_of(ks[1])
            if nm == 'skill':
                an = quotable(names.skill(a)) if a is not None else None
                bn = names.skillcalc(b) if b is not None else None
            elif nm == 'stat':
                an = quotable(names.stat(a)) if a is not None else None
                bn = STAT_SUB.get(b) if b is not None else None
            else:
                an = quotable(names.missile(a)) if a is not None else None
                bn = names.misscalc(b) if b is not None else None
            an = "'%s'" % an if an is not None else r(ks[0])
            if bn is None:
                # no name for the 2nd argument (e.g. a Sigma stat sub-value 5): 'x'.5 does not
                # compile (the '.' token needs a name), the plain argument list does
                return '%s(%s,%s)' % (nm, an, r(ks[1]))
            return '%s(%s.%s)' % (nm, an, bn)
        if nm == 'sklvl' and len(ks) == 3:
            a, b = const_of(ks[0]), const_of(ks[1])
            an = quotable(names.skill(a)) if a is not None else None
            bn = names.skillcalc(b) if b is not None else None
            an = "'%s'" % an if an is not None else r(ks[0])
            c = const_of(ks[2])         # the txt writes the 3rd arg as a calc code too (.edmn)
            cn = names.skillcalc(c) if c is not None else None
            if bn is None or cn is None:
                return '%s(%s,%s,%s)' % (nm, an, r(ks[1]), r(ks[2]))
            return '%s(%s.%s.%s)' % (nm, an, bn, cn)
        return '%s(%s)' % (nm, ','.join(r(k) for k in ks))

    return r(node)


OPCHAR = {0x0a: '<', 0x0b: '>', 0x0c: '<=', 0x0d: '>=', 0x0e: '==', 0x0f: '!=', 0x10: '+',
          0x11: '-', 0x12: '*', 0x13: '/', 0x14: '^'}
# Fog Calc.cpp operator precedence by AST id (txt2bin.PREC): a push pops ops with PREC >= id
_PREC = [23, 1, 2, 3, 9, 9, 9, 9, 9, 9, 15, 15, 15, 15, 15, 15, 17, 17, 19, 19, 20, 21, 22, 0]


def render_faithful(buf, pos=0, table='skillscode', names=None):
    """Text for bytecode that is not one well-formed expression, written so that Fog's compiler
    (txt2bin.compile_expr; lenient=True for operators that find too few operands) emits the very
    same bytes:
      - every operator result is fully parenthesised, so it is emitted where it stands;
      - an operand the bytecode never pushed (a function or operator that pops more than the
        stack holds - Median's compiler let such cells through) is left out: 'stat(320)',
        '(?(x):0)'; a function whose first argument was pushed before it is written after that
        argument: '(-100)stat(0)' (Fog counts operands, not commas);
      - values left side by side on the stack are written side by side ('0 0');
      - operators and '(' emitted by the final flush (a cell cut at 255 chars leaves unclosed
        '(' and pending operators) are written as pending: '(((50+(10*...'.
    Fog reads '-' as a negation only when no value came just before it (the flag survives '(',
    ',' and '?'), which the renderer tracks.  -> text, or None when no such text exists (e.g. a
    negative constant, which only constant folding writes)."""
    try:
        toks = [t for t in _tokens(buf, pos)][:-1]
    except (ValueError, IndexError, struct.error):
        return None
    # the end flush: trailing operators / '(' (no operand among them).  Without a '(' marker
    # in it the run is rendered in place first.
    k = len(toks)
    while k > 0 and (toks[k - 1][0] in BINOPS or toks[k - 1][0] in (0x02, 0x15, 0x16)):
        k -= 1
    for cut in ((len(toks), k) if k < len(toks) else (k,)):
        t = _render_faithful(toks[:cut], toks[cut:], table, names)
        if t is not None:
            return t
    return None


def _render_faithful(body, tail, table, names):
    names = names or Names()
    funcs = FUNCS.get(table, SKILL_FUNCS)
    stack = []          # nodes; None = an operand that was never pushed
    for op, arg, _st in body:
        if op in (4, 5, 6):
            stack.append(Node('param', arg))
        elif op in (7, 8, 9):
            if arg < 0:
                return None
            stack.append(Node('const', arg))
        elif op in BINOPS:
            b = stack.pop() if stack else None
            a = stack.pop() if stack else None
            stack.append(Node('bin', op, (a, b)))
        elif op == 0x15:
            stack.append(Node('neg', None, (stack.pop() if stack else None,)))
        elif op == 0x16:
            c = stack.pop() if stack else None
            b = stack.pop() if stack else None
            a = stack.pop() if stack else None
            stack.append(Node('tern', None, (a, b, c)))
        elif op == 1:
            if arg >= len(funcs):
                return None
            nm, ar = funcs[arg]
            kids = []
            for _ in range(ar):
                kids.insert(0, stack.pop() if stack else None)
            stack.append(Node('fn', nm, kids))
        else:
            return None                 # a '(' marker before the end flush

    class Fail(Exception):
        pass

    def leaf(n):
        if n.kind == 'param':
            return names.param(n.val) or 'p%d' % n.val
        return str(n.val)

    def r(n, pv):
        """-> (text, pv after).  pv: a value was the last thing Fog read."""
        if n is None:
            return '', pv
        k = n.kind
        if k in ('const', 'param'):
            return leaf(n), True
        if k == 'neg':
            if pv or n.kids[0] is None:
                raise Fail
            t, _ = r(n.kids[0], False)
            return '(-%s)' % t, True
        if k == 'bin':
            a, b = n.kids
            if b is None:
                raise Fail
            ta, pv2 = r(a, pv)
            if n.val == 0x11 and not pv2:
                raise Fail          # '-' would read as a negation
            tb, _ = r(b, False)
            return '(%s%s%s)' % (ta, OPCHAR[n.val], tb), True
        if k == 'tern':
            a, b, c = n.kids
            if b is None or c is None:
                raise Fail
            ta, pv2 = r(a, pv)
            tb, pv3 = r(b, pv2)
            tc, _ = r(c, pv3)
            return '(%s?%s:%s)' % (ta, tb, tc), True
        if k == 'fn':
            kids = [x for x in n.kids if x is not None]
            try:
                parts, p2 = [], True
                for x in kids:
                    t, p2 = r(x, p2)
                    parts.append(t)
                return '%s(%s)' % (n.val, ','.join(parts)), True
            except Fail:
                pass
            # Fog's function pops what the stack holds: write the leading arguments before it
            pre, p2 = [], pv
            for x in kids[:-1]:
                t, p2 = r(x, p2)
                pre.append(t)
            t, _ = r(kids[-1], True) if kids else ('', True)
            return ''.join(pre) + '%s(%s)' % (n.val, t), True
        raise Fail

    # the end flush pops the op stack top first: rebuild it bottom -> top
    ops = list(reversed([op for op, _a, _s in tail]))
    for lo, hi in zip(ops, ops[1:]):
        if hi == 0x02 or lo == 0x02:
            continue                    # '(' is pushed as is and never popped by a push
        hid = {0x15: 21, 0x16: 22}.get(hi, hi)
        if _PREC[{0x15: 21, 0x16: 22}.get(lo, lo)] >= hid:
            return None                 # pushing hi would have popped lo at once
    out = []
    vals = list(stack)
    pv = False
    try:
        def put_value():
            nonlocal pv
            t, pv = r(vals.pop(0), pv)
            out.append(t)
        if ops and vals:
            put_value()
        for op in ops:
            if op == 0x02:
                out.append('(')
            elif op == 0x15:
                if pv:
                    return None
                out.append('-')
            elif op == 0x16:
                out.append('?')
            else:
                if op == 0x11 and not pv:
                    if not vals:
                        return None
                    put_value()
                out.append(OPCHAR[op])
                pv = False
        while vals:
            put_value()
    except Fail:
        return None
    text = ''
    for t in out:      # a space only between two values ('0 0')
        if text and (text[-1].isalnum() or text[-1] in "')") and t[:1].isalnum():
            text += ' '
        text += t
    return text or None


def well_formed(buf, pos=0, table='skillscode'):
    """True when the bytecode is one expression tree (what decode() renders normally)."""
    try:
        node, _end = parse(buf, pos, table)
        toks = [op for op, _a, _s in _tokens(buf, pos)]
    except (ValueError, IndexError, struct.error):
        return False
    if node is None:
        return False
    # '(' markers are only fine as the trailing run before 00 (rendered as leading '(')
    k = len(toks) - 1
    while k > 0 and toks[k - 1] == 0x02:
        k -= 1
    return 0x02 not in toks[:k]


def decode(buf, pos=0, table='skillscode', names=None):
    """Expression text at byte offset pos ('?' parts if it cannot be decoded)."""
    try:
        node, _end = parse(buf, pos, table)
    except (ValueError, IndexError, struct.error):
        return '?'
    if node is None or not well_formed(buf, pos, table):
        return render_faithful(buf, pos, table, names) or '?'
    # unclosed '(' in the source txt: Fog flushes each as a 02 byte before the terminator
    opens = 0
    try:
        toks = [op for op, _a, _s in _tokens(buf, pos)]
        while len(toks) > 1 and toks[-2 - opens] == 0x02:
            opens += 1
    except (ValueError, IndexError, struct.error):
        opens = 0
    return '(' * opens + render(node, names, table)


def iter_expressions(buf):
    """Yield (offset, raw bytes) for every expression in a code blob."""
    pos = 0
    n = len(buf)
    while pos < n:
        try:
            end = expr_end(buf, pos)
        except (ValueError, IndexError, struct.error):
            end = n
        yield pos, buf[pos:end]
        pos = end


def code_table_txt(buf, table='skillscode', names=None):
    """The *code.txt listing: 'index<TAB>expr' then '<TAB>hex bytes' per expression."""
    out = []
    for i, (pos, raw) in enumerate(iter_expressions(buf)):
        out.append('%d\t%s\n\t%s \n' % (i, decode(buf, pos, table, names),
                                        ' '.join('%02x' % b for b in raw)))
    return ''.join(out)
