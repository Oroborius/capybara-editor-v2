"""Classic D2 excel .txt -> .bin compiler (the inverse of bin2txt), driven by the same layouts.

    proj = Project(txt_dir, version='114d', strings=tbl_dir)
    data = proj.compile('weapons')          # bytes of weapons.bin
    pool = proj.code_pool('skillscode')     # bytes of skillscode.bin
    compile_dir(txt_dir, out_dir, version='auto', strings=None) -> {table: bytes}

It is a port of the game's own compiler, Fog #10207 (Fog 1.13c 0x6FF62A60, Excel.cpp) driven by
the D2Common descriptor arrays, plus the D2Common callbacks (D2MOO DataTbls/*.cpp):

- Rows: every CRLF line after the header; a row whose first cell is "Expansion" (case-sensitive) is
  dropped, whatever the other cells hold (Fog #10208).  Blank lines are rows.  LF-only files and an
  unterminated last line are accepted here (the game would choke / drop it).
- Columns are matched to descriptors by name, case-insensitively, first txt column wins; other txt
  columns (comments, '*' columns) are ignored.  Pass 1 handles key types (10/12/14 codes, 16 key
  string, 17/18 names) for all rows; pass 2 runs every other column row by row in TXT COLUMN ORDER
  (this decides overlapping writes, the NUL spill of full-length strings and the order calc
  expressions are appended to the *code.bin pool).  Descriptors with no txt column run after the
  txt columns: callbacks get no source (calc -> -1, composit -> 0xFF fill ...), code/name links
  get -1 (Fog reads past the row end and the lookup fails), other fields are left zero.
- Numbers: optional '-', then v = v*10 + (c - '0') for every char (no validation), int32 wrap,
  truncated to the field width.  Type 5 is only written when the cell is non-empty; BIT (26)
  sets/clears bit `bit` at offset + bit/8.
- Strings (1/7): up to `size` chars are copied and a NUL is written after them, i.e. one byte past
  the buffer when the text fills it (later columns may overwrite that byte again).
- 4cc codes are space padded; an empty RAW (9) cell is "    ".  Code links (11/13/15) and name
  links (19-21) store the linked row index, -1 (0xFF.. at the field width) when not found.  Name
  linkers fold case and cut names to 31 chars; "" is a valid name (TC index 0 is "").
  Duplicate codes/names: the first row wins.
- KEYTOWORD (22) = the .tbl index of a string key (patchstring > expansionstring > string);
  not found or empty -> 5382.
- CALC (25 'calc:<pool>'): expressions compiled with a line-for-line port of Fog Calc.cpp
  (#10254) and appended to the pool without dedup; the field stores the byte offset (-1 empty).
  25 'param' = item/cube mod param (atoi, else skill/montype/state name or stat name).
- 1.07-1.09d (old Fog enum, layouts already renumbered): name -> word lookups store a dword,
  the type-16 key string is copied like ASCII.  Best effort.
- Callbacks (23): cubemain inputs/outputs, monstats Sk*mode, monstats2 composit, monpreset Place.
  For 'mxl' the cube outputs go through D2Sigma's parser instead (FUN_10081d10: portal= /
  skillpts= / statpts= / mon= / boss= / goldcost= / [un]set_flag_player|game= / items, the
  modifiers, and its strtok quirk: nothing after the first 'key=value' token counts).
- 'mxl' calc cells compile leniently: an operator / function that finds too few operands is
  emitted anyway (Median's pools hold such bytecode; Fog itself would fail the cell).
- Linkers are global: the items linker spans weapons+armor+misc; the TC linker holds "" at 0,
  then 32 auto classes (<itemtype code><3..96>) per itemtype with TreasureClass set, then the
  treasureclassex rows (up to the first empty name).

Extensions for txt written by bin2txt (none of these exist in the game):
- Placeholders: a link cell 'pr116' (bin2txt's prefix + row) that is not a real key resolves to
  row 116 of the linked table ('it12' = item 12, 'tc5' = treasureclassex row 5).
- Calc: 'fnN(...)' calls Sigma function N; 'pN' is skill/missile calc parameter N.  For 'mxl'
  missiles formulas also know stat()/sklvl() (D2Sigma; misscode.bin uses them).
- A calc cell '@N' stores pool offset N without compiling anything (bin2txt writes it when the
  pool .bin was not beside the table, e.g. a patch that ships skilldesc.bin alone).
- '-1' in a link cell is a name no linker holds: the field gets -1 (bin2txt NOT_FOUND).
- A calc cell '?{0840010105 00}' (hex, no spaces) is appended to the pool as is: bin2txt's
  lossless mode writes it for bytecode it cannot render as an expression that compiles back.
- A code pool that no table feeds (Sigma's skills2code) is rebuilt from its bin2txt listing.
- '*patch' column (written by `bin2txt.convert_dir(..., lossless=True)`): byte patches
  'off:compiled>original;...' applied to the compiled record only where it still holds the
  compiled bytes, so they never undo an edit.  '*pool' lines in a <pool>.txt listing do the same
  for code pools.  They carry what the txt cannot express (garbage after a string's NUL, tbl
  indices whose key resolves elsewhere, unparsable formulas ...).
- Raw dumps (bin2txt type@offset columns for tables without a layout) are compiled back too.
"""
import os
import re
import struct

from . import layouts
from .tbl import Tbl, StringSet

NONE_STR = 5382          # string index for an empty / unknown string key
TC_AUTO_TOP = {'107': 132, '108': 90, '109d': 90}
OLD_VERSIONS = ('107', '108', '109d')
ITEM_TABLES = ('weapons', 'armor', 'misc')

# bin2txt placeholder prefixes (kept in sync with bin2txt.PREFIX)
from .bin2txt import PREFIX, CODE_TABLES, MODE_CODES   # noqa: E402

# Pass-2 handler class per field type (Fog 1.13c class map at 0x6FF6341B)
CLASS = {1: 'str', 7: 'str', 2: 'num', 3: 'num', 4: 'num', 5: 'num', 6: 'num', 8: 'num',
         26: 'num', 9: 'raw', 10: 'key', 12: 'key', 14: 'key', 16: 'key', 17: 'key', 18: 'key',
         11: 'code', 13: 'code', 15: 'code', 19: 'name', 20: 'name', 21: 'name', 22: 'tbl',
         23: 'cb', 24: 'cb', 25: 'cb'}
WIDTH = {2: 4, 3: 2, 4: 1, 5: 1, 6: 1, 8: 4, 10: 4, 11: 4, 12: 1, 13: 1, 14: 2, 15: 2, 17: 2,
         18: 4, 19: 4, 20: 2, 21: 1, 22: 2, 25: 4}

# D2Common load order (DataTbls.cpp DATATBLS_LoadAllTxts, MonsterTbls.cpp); decides code pool order
LOAD_ORDER = (
    'compcode playerclass bodylocs storepage elemtypes hitclass colors hiredesc monmode plrmode '
    'monai monplace skillcalc misscalc events itemtypes montype sounds pettype overlay '
    'itemstatcost properties missiles states skills skilldesc charstats arena chartemplate '
    'weapons armor misc magicsuffix magicprefix automagic raresuffix rareprefix uniqueitems sets '
    'setitems gems books qualityitems lowqualityitems runes itemratio gamble plrtype objtype '
    'objmode composit armtype experience uniquetitle uniqueprefix uniquesuffix '
    'uniqueappellation monlvl treasureclassex monstats2 monprop monsounds monseq monstats '
    'monumod superuniques monpreset hireling npc monequip levels leveldefs lvltypes lvlprest '
    'lvlwarp lvlmaze lvlsub automap objects objgroup shrines inventory belts monitempercent '
    'cubemain difficultylevels').split()


def _i32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def fog_atoi(s):
    """Fog's number parse: no validation, every char counts as a digit."""
    neg = s[:1] == b'-'
    v = 0
    for c in (s[1:] if neg else s):
        if c >= 0x80:
            c -= 0x100            # signed char
        v = _i32(c - 0x30 + v * 10)
    return _i32(-v) if neg else v


def c_atoi(s):
    """C atoi: spaces, sign, digits."""
    m = re.match(rb'\s*([-+]?\d+)', s)
    return _i32(int(m.group(1))) if m else 0


def to_code(s):
    """4-char space padded code (DATATBLS_StringToCode / Fog), as a little-endian u32."""
    b = bytes(s[:4]).split(b'\0')[0]
    return struct.unpack('<I', (b + b'    ')[:4])[0]


def _lower(b):
    return bytes(b).lower()


# ------------------------------------------------------------------ linkers

class CodeLinker:
    """Fog code linker (#10215 add, #10213 lookup): sorted u32 codes; a duplicate is stored as
    code+1 (so the first row wins on lookup)."""

    def __init__(self):
        self.map = {}
        self.by_index = {}
        self.count = 0

    def add(self, code):
        while code in self.map:
            code = (code + 1) & 0xFFFFFFFF
        idx = self.count
        self.map[code] = idx
        self.by_index[idx] = code
        self.count += 1
        return idx

    def get(self, code):
        return self.map.get(code, -1)

    def code_text(self, idx):
        """#10214: the code of index idx, spaces -> NUL (so 'ab c' -> 'ab')."""
        c = self.by_index.get(idx)
        if c is None:
            return None
        b = struct.pack('<I', c)
        return b.replace(b' ', b'\0').split(b'\0')[0]


class NameLinker:
    """Fog name linker: case-folded names cut to 31 chars, first wins."""

    def __init__(self):
        self.map = {}
        self.count = 0

    @staticmethod
    def norm(name):
        return _lower(bytes(name)[:31])

    def add_record(self, name):
        """#10216: always takes the next index (a duplicate is dropped from the tree)."""
        k = self.norm(name)
        if k not in self.map:
            self.map[k] = self.count
        self.count += 1

    def add_key(self, name):
        """types 17/18: index of an existing name, else a new one."""
        k = self.norm(name)
        if k not in self.map:
            self.map[k] = self.count
            self.count += 1
        return self.map[k]

    def get(self, name):
        return self.map.get(self.norm(name), -1)


# --------------------------------------------------------------------- txt

def read_txt(path):
    """-> (header cells, rows) as bytes; 'Expansion' rows dropped like Fog does."""
    with open(path, 'rb') as fh:
        data = fh.read()
    return parse_txt(data)


def parse_txt(data):
    lines = data.split(b'\n')
    if lines and lines[-1] in (b'', b'\r'):
        lines.pop()
    lines = [ln[:-1] if ln.endswith(b'\r') else ln for ln in lines]
    if not lines:
        return [], []
    header = lines[0].split(b'\t')
    rows = []
    for ln in lines[1:]:
        cells = ln.split(b'\t')
        if cells[0] == b'Expansion':       # Storm #508 SStrCmp, case-sensitive
            continue
        rows.append(cells)
    return header, rows


def _cell(row, i):
    if i is None or i >= len(row):
        return b''
    return row[i]


# ---------------------------------------------------------------- calc

AST = dict(none=0, cb=1, paren=2, sep=3, p8=4, p16=5, p32=6, r8=7, r16=8, r32=9, lt=10, gt=11,
           le=12, ge=13, eq=14, ne=15, add=16, sub=17, mul=18, div=19, pow=20, neg=21, tern=22,
           colon=23)
PREC = [23, 1, 2, 3, 9, 9, 9, 9, 9, 9, 15, 15, 15, 15, 15, 15, 17, 17, 19, 19, 20, 21, 22, 0]
BINOP = {b'<': 10, b'>': 11, b'<=': 12, b'>=': 13, b'==': 14, b'!=': 15, b'+': 16, b'-': 17,
         b'*': 18, b'/': 19, b'^': 20}

KEYWORDS = {
    'skills': [b'min', b'max', b'rand', b'skill', b'miss', b'stat', b'sklvl'],
    'missiles': [b'min', b'max', b'rand', b'skill', b'miss'],
    'items': [b'min', b'max', b'rand', b'stat'],
}
POOL_KIND = {'skillscode': 'skills', 'skilldesccode': 'skills', 'skills2code': 'skills',
             'misscode': 'missiles', 'itemscode': 'items'}


RAW_CALC = re.compile(rb'^\?\{([0-9a-fA-F]*)\}$')     # '?{hex}': bytecode bin2txt cannot render
POOL_OFF = re.compile(rb'^@(\d+)$')       # '@N': a pool offset (bin2txt had no pool .bin)


class CalcError(Exception):
    pass


def _isalnum(c):
    return c < 0x80 and (chr(c).isalnum())


def _isspace(c):
    return c in b' \t\n\r\x0b\x0c'


def calc_eval(buf):
    """Fog #10253 without callbacks (used for constant folding)."""
    st = []

    def pop():
        return st.pop() if st else 0

    def push(v):
        if len(st) < 64:
            st.append(_i32(v))
    i = 0
    n = len(buf)
    while i < n:
        op = buf[i]
        i += 1
        if op in (7, 8, 9):
            sz = {7: 1, 8: 2, 9: 4}[op]
            if i >= n:
                return 0
            push(int.from_bytes(buf[i:i + sz], 'little', signed=True))
            i += sz
        elif op in (4, 5, 6):
            return 0
        elif op == 1:
            i += 1
            push(0)
        elif 10 <= op <= 20:
            b = pop()
            a = pop()
            if op == 10:
                push(a < b)
            elif op == 11:
                push(a > b)
            elif op == 12:
                push(a <= b)
            elif op == 13:
                push(a >= b)
            elif op == 14:
                push(a == b)
            elif op == 15:
                push(a != b)
            elif op == 16:
                push(a + b)
            elif op == 17:
                push(a - b)
            elif op == 18:
                push(a * b)
            elif op == 19:
                push(0 if b == 0 else int(a / b))
            else:
                if b <= 0:
                    push(1)
                else:
                    p = a
                    for _ in range(b - 1):
                        p = _i32(p * a)
                    push(p)
        elif op == 21:
            push(-pop())
        elif op == 22:
            c = pop()
            b = pop()
            a = pop()
            push(b if a else c)
            return pop()          # falls through into 'default: return pop' in Fog
        else:
            return pop()
    return 0


def _push_const(out, v, param):
    if -128 <= v <= 127:
        out += bytes([4 if param else 7]) + struct.pack('<b', v)
    elif -32768 <= v <= 32767:
        out += bytes([5 if param else 8]) + struct.pack('<h', v)
    else:
        out += bytes([6 if param else 9]) + struct.pack('<i', _i32(v))


def compile_expr(text, kind, link, arity=None, bufsize=1024, keywords=None, lenient=False):
    """Fog #10254 port.  text: bytes.  link(name, a3, kw) -> (index, raw_constant) with index -1
    when unknown.  -> bytecode bytes, or b'' when the game's compiler fails (field gets -1).
    lenient: an operator / function that finds fewer operands than it pops is emitted anyway
    instead of failing the cell (Median's bins hold such bytecode, e.g. stat(320) with one
    argument, which Fog itself refuses); where Fog succeeds the result is the same."""
    kw_list = keywords or KEYWORDS.get(kind, KEYWORDS['skills'])

    def keyword(name):
        ln = name.lower()
        if ln in kw_list:
            return kw_list.index(ln)
        m = re.match(rb'^fn(\d+)$', ln)
        if m:
            return int(m.group(1))
        # D2Sigma function names (calc.SKILL_FUNCS / ITEM_FUNCS ids past the vanilla list)
        from . import calc
        names = [n.encode() for n, _a in (calc.ITEM_FUNCS if kind == 'items'
                                           else calc.SKILL_FUNCS)]
        if ln in names and names.index(ln) >= len(kw_list):
            return names.index(ln)
        return -1

    def param_count(ast, val):
        if ast == 1:
            if kind == 'skills' or len(kw_list) > 6:
                return 3 if val == 6 else 2
            return 2
        if 10 <= ast <= 20:
            return 2
        if ast == 21:
            return 1
        if ast == 22:
            return 3
        return 0

    out = bytearray()
    ops = []                  # [ast, linkidx]
    st = {'pending': 0}
    s = bytes(text)
    pos = 0
    n = len(s)

    def prev_ast():
        return (ops[-1][0], ops[-1][1]) if ops else (0, 0)

    def check_prec(prev, new):
        if prev == 1 or new == 1 or prev >= 23:
            return False
        return PREC[prev] >= new

    def new_op(new, val=0):
        while ops:
            prev = ops[-1][0]
            if not check_prec(prev, new):
                break
            np_ = param_count(prev, 0)
            if lenient and st['pending'] < np_:
                st['pending'] = np_
            if st['pending'] < np_ or len(out) >= bufsize:
                raise CalcError('stack')
            out.append(prev)
            st['pending'] += 1 - np_
            ops.pop()
        if new in (23, 3):
            return
        if new == 0:
            if not out:
                raise CalcError('empty')
            out.append(0)
            return
        if len(ops) >= 64:
            raise CalcError('ops')
        ops.append([new, val])

    def resolve(name):
        a3, a4 = prev_ast()
        idx, raw = link(name, a3, a4)
        if idx >= 0:
            return ('raw' if raw else 'param'), idx
        return 'raw', 0

    def token(pos):
        """-> (newpos, kind, value) or None at the end / on an unknown char."""
        while pos < n and (_isspace(s[pos]) or s[pos] == 0x22):
            pos += 1
        if pos >= n:
            return None
        c = s[pos]
        if 0x30 <= c <= 0x39:
            v = 0
            while pos < n and 0x30 <= s[pos] <= 0x39:
                v = _i32(v * 10 + s[pos] - 0x30)
                pos += 1
            return pos, 'raw', v
        if c == 0x27:                                      # 'link'
            pos += 1
            st_ = pos
            while pos < n and s[pos] != 0x27:
                pos += 1
            name = s[st_:pos][:255]
            if pos < n:
                pos += 1
            k, v = resolve(name)
            return pos, k, v
        if c < 0x80 and chr(c).isalpha():
            st_ = pos
            while pos < n and _isalnum(s[pos]):
                pos += 1
            name = s[st_:pos][:255]
            while pos < n and _isspace(s[pos]):
                pos += 1
            if pos < n and s[pos] == 0x28:
                fid = keyword(name)
                if fid >= 0:
                    return pos + 1, 'fn', fid
            k, v = resolve(name)
            return pos, k, v
        if c == 0x2E:                                      # .sublink
            pos += 1
            st_ = pos
            while pos < n and _isalnum(s[pos]):
                pos += 1
            a3, a4 = prev_ast()
            idx, _raw = link(s[st_:pos][:255], a3, a4)
            if idx >= 0:
                return pos, 'raw', idx
            return None
        two = s[pos:pos + 2]
        if two in (b'<=', b'>=', b'==', b'!='):
            return pos + 2, 'op', two
        if c in b'=!':
            return None
        if c in b'()*+,-/:<>?^':
            return pos + 1, 'op', bytes([c])
        return None

    try:
        pending_value = False
        has_fn = False
        while True:
            t = token(pos)
            if t is None:
                break
            pos, k, v = t
            if k == 'op':
                if v == b'(':
                    if len(ops) >= 64:
                        return b''
                    ops.append([2, 0])
                elif v == b')':
                    if not ops:
                        return b''
                    while True:
                        prev, pv = ops[-1]
                        if prev == 2:
                            break
                        np_ = param_count(prev, pv)
                        if prev == 1 and arity is not None and pv >= len(kw_list):
                            np_ = 0           # Sigma function: arity unknown, never fail
                        if lenient and st['pending'] < np_:
                            st['pending'] = np_
                        if st['pending'] < np_ or len(out) >= bufsize:
                            return b''
                        out.append(prev)
                        st['pending'] += 1 - np_
                        if prev == 1:
                            out.append(pv & 0xFF)
                            break
                        ops.pop()
                        if not ops:
                            return b''
                    if ops[-1][0] not in (1, 2):
                        return b''
                    ops.pop()
                elif v == b',':
                    new_op(3)
                elif v == b'-':
                    new_op(17 if pending_value else 21)
                    pending_value = False
                elif v == b'?':
                    new_op(22)
                elif v == b':':
                    new_op(23)
                elif v == b'^':
                    new_op(20)
                else:
                    new_op(BINOP[v])
                    pending_value = False
            elif k == 'raw':
                _push_const(out, v, False)
                st['pending'] += 1
                pending_value = True
            elif k == 'param':
                _push_const(out, v, True)
                st['pending'] += 1
                pending_value = True
                has_fn = True
            elif k == 'fn':
                if len(ops) < 64:
                    ops.append([1, v])
                else:
                    return b''
                pending_value = True
                has_fn = True
        new_op(0)
    except CalcError:
        return b''
    if not has_fn:
        val = calc_eval(bytes(out))
        out = bytearray()
        _push_const(out, val, False)
        out.append(0)
    if len(out) > bufsize:
        return b''
    return bytes(out)


# ---------------------------------------------------------------- project

class Project:
    """A directory of excel .txt files compiled the way the game does.

    txt_dir   dir with the .txt files (game txt or bin2txt output)
    version   layout version ('auto' = best header match)
    strings   StringSet, or a dir with string/patchstring/expansionstring .tbl (default: bin2txt's
              string.txt/patchstring.txt/expansionstring.txt listings in txt_dir, if any)
    placeholders  accept bin2txt placeholders (pr116 ...) for links that are not real keys
    """

    def __init__(self, txt_dir, version='auto', strings=None, placeholders=True, lenient=None):
        self.txt_dir = txt_dir
        self.placeholders = placeholders
        # Lenient calc compile (operators with too few operands emitted anyway, like Median's own compiler).
        # None = automatic: on for 'mxl', off otherwise.
        self.lenient = lenient
        self._files = {}
        if txt_dir and os.path.isdir(txt_dir):
            for fn in os.listdir(txt_dir):
                if fn.lower().endswith('.txt'):
                    self._files[fn[:-4].lower()] = os.path.join(txt_dir, fn)
        if isinstance(strings, str):
            from .bin2txt import load_strings
            strings = load_strings(strings)
        if not strings:
            strings = self._listing_strings()
        self.strings = strings
        self.version = self.guess_version() if version in (None, 'auto') else version
        self._txt = {}
        self._linkers = {}
        self._pools = {}
        self._out = {}
        self._tblidx = None
        self._fallback = {}
        self._pool_done = set()
        self._pool_prefix = set()
        self._current = None
        self.warnings = []

    def _listing_strings(self):
        """StringSet from bin2txt's .tbl listings (string.txt ... 'key<TAB>text' lines) in the
        txt dir, so a bin2txt output dir compiles without the original .tbl files."""
        ss = StringSet()
        for name in ('string', 'patchstring', 'expansionstring'):
            p = self._files.get(name)
            if not p:
                continue
            with open(p, 'rb') as fh:
                lines = fh.read().decode('utf-8', 'replace').split('\n')
            if lines and lines[-1] == '':
                lines.pop()
            ents = []
            for ln in lines:
                k, _, t = ln.partition('\t')
                ents.append((k.encode('utf-8').decode('latin-1'), t))
            ss.add(name, Tbl(ents))
        return ss

    # -- files
    def tables(self):
        return sorted(self._files)

    def txt(self, table):
        table = table.lower()
        if table not in self._txt:
            p = self._files.get(table)
            if p is None and table == 'leveldefs':
                p = self._files.get('levels')
            if p is None:
                # D2Sigma reads an extension table's columns from its base txt (FUN_100b9fa0;
                # bin2txt merge_ext output): armor2 <- armor.txt, skills2 <- skills.txt, ...
                from .bin2txt import EXT_BASE
                if table in EXT_BASE:
                    p = self._files.get(EXT_BASE[table])
            self._txt[table] = read_txt(p) if p else None
        return self._txt[table]

    def layout(self, table):
        """Layout of table: the project version's, else (a table that version lacks, e.g. the
        1.09 cubemod in a 1.13 dir) the first other version whose fields all have a column."""
        table = table.lower()
        lay = layouts.load(self.version, table)
        if lay is not None:
            return lay
        if table not in self._fallback:
            self._fallback[table] = None
            t = self.txt(table)
            if t:
                hdr = [h.lower() for h in t[0] if h and not h.startswith(b'*')]
                old = self.version in OLD_VERSIONS
                for v in layouts.versions():
                    cand = layouts.load(v, table)
                    if not cand or not cand.get('record_size'):
                        continue
                    names = [f['name'].lower().encode('latin-1') for f in cand['fields']]
                    same = (v in OLD_VERSIONS) == old
                    # same format family: every field has a column; other family (a 1.09 table
                    # left in a 1.13 dir): the header must be exactly bin2txt's for that layout
                    if (same and all(nm in set(hdr) for nm in names)) or names == hdr:
                        self._fallback[table] = cand
                        break
        return self._fallback[table]

    def guess_version(self):
        best = (-1e9, '114d')
        for v in layouts.versions():
            score = 0
            for t in ('weapons', 'skills', 'monstats', 'itemstatcost', 'missiles', 'levels',
                      'runes', 'setitems', 'states'):
                lay = layouts.load(v, t)
                p = self._files.get(t)
                if not lay or not p:
                    continue
                with open(p, 'rb') as fh:
                    hdr = set(h.strip().lower() for h in
                              fh.readline().rstrip(b'\r\n').split(b'\t'))
                names = [f['name'].encode('latin-1').lower() for f in lay['fields']]
                score += sum(1 for nm in names if nm in hdr) - 2 * sum(
                    1 for nm in names if nm not in hdr)
            if score > best[0]:
                best = (score, v)
        return best[1]

    # -- column access
    def column(self, table, col):
        """Cells of a column (bytes list) or None."""
        t = self.txt(table)
        if not t:
            return None
        hdr, rows = t
        cl = col.lower().encode('latin-1')
        for i, h in enumerate(hdr):
            if h.lower() == cl:
                return [_cell(r, i) for r in rows]
        return None

    # -- linkers
    def linker(self, table, col=None):
        """Linker of table (CodeLinker or NameLinker) built like the game does, or None."""
        table = table.lower()
        key = table
        if key in self._linkers:
            return self._linkers[key]
        self._linkers[key] = None
        lk = None
        if table in ITEM_TABLES:
            lk = CodeLinker()
            for t in ITEM_TABLES:
                for c in self.column(t, 'code') or []:
                    lk.add(to_code(c))
            for t in ITEM_TABLES:
                self._linkers[t] = lk
            return lk
        if table == 'treasureclassex':
            lk = self._tc_linker()
        elif table in ('uniqueitems', 'setitems'):
            lk = NameLinker()
            f = self._field(table, 'index')
            size = (f or {}).get('size') or 31
            for c in self.column(table, 'index') or []:
                lk.add_record(c[:size])
        else:
            lay = self.layout(table)
            kf = None
            if lay:
                keys = [f for f in lay['fields'] if f['ftype'] in (10, 12, 14, 16, 17, 18)]
                if col:
                    kf = next((f for f in keys if f['name'].lower() == col.lower()), None)
                kf = kf or (keys[0] if keys else None)
            if kf is not None:
                cells = self.column(table, kf['name']) or []
                if kf['ftype'] in (10, 12, 14):
                    lk = CodeLinker()
                    for c in cells:
                        lk.add(to_code(c))
                elif kf['ftype'] == 16:
                    lk = NameLinker()
                    for c in cells:
                        lk.add_record(c)
                else:
                    lk = NameLinker()
                    for c in cells:
                        lk.add_key(c[:31])
            elif col and table in MODE_CODES:
                lk = CodeLinker()
                for c in MODE_CODES[table]:
                    lk.add(to_code(c.encode()))
        self._linkers[key] = lk
        return lk

    def _tc_linker(self):
        lk = NameLinker()
        lk.add_record(b'')
        top = TC_AUTO_TOP.get(self.version, 96)
        it = self.linker('itemtypes')
        tcs = self.column('itemtypes', 'TreasureClass') or []
        self._tc_auto = 1
        for i, v in enumerate(tcs):
            if fog_atoi(v):
                code = it.code_text(i) if it else None
                for lv in range(3, top + 1, 3):
                    if code is not None:
                        lk.add_record(b'%s%d' % (code, lv))
                    else:
                        lk.count += 1
                    self._tc_auto += 1
        for c in self.column('treasureclassex', 'Treasure Class') or []:
            if not c:
                break
            lk.add_record(c[:31])
        return lk

    def _field(self, table, name):
        lay = self.layout(table)
        if not lay:
            return None
        nl = name.lower()
        return next((f for f in lay['fields'] if f['name'].lower() == nl), None)

    # -- lookups used by fields
    def code_index(self, link, cell):
        t = link.split('.', 1)[0]
        lk = self.linker(t, link.split('.', 1)[1] if '.' in link else None)
        if lk is None:
            return -1
        v = lk.get(to_code(cell)) if isinstance(lk, CodeLinker) else lk.get(cell)
        if v < 0:
            v = self._placeholder(t, cell)
        return v

    def name_index(self, link, cell):
        t = link.split('.', 1)[0]
        lk = self.linker(t, link.split('.', 1)[1] if '.' in link else None)
        if lk is None:
            return self._placeholder(t, cell)
        if isinstance(lk, CodeLinker):
            v = lk.get(to_code(cell))
        else:
            v = lk.get(cell[:31])
        if v < 0:
            v = self._placeholder(t, cell)
        return v

    def _placeholder(self, table, cell):
        if not self.placeholders or not cell:
            return -1
        if table in ITEM_TABLES:
            m = re.match(rb'^it(\d+)$', cell)
            return int(m.group(1)) if m else -1
        pre = PREFIX.get(table, table[:2]).encode()
        m = re.match(rb'^' + re.escape(pre) + rb'(\d+)$', cell)
        if not m:
            return -1
        i = int(m.group(1))
        if table == 'treasureclassex':
            self.linker('treasureclassex')
            return self._tc_auto + i
        return i

    def tbl_index(self, key):
        """D2Lang key -> string index; NONE_STR when missing or empty."""
        if not key:
            return NONE_STR
        if self._tblidx is None:
            self._tblidx = {}
            if self.strings:
                for base in (0, 20000, 10000):        # later wins: patch > expansion > string
                    t = self.strings.tables.get(base)
                    if not t:
                        continue
                    first = {}
                    for i, (k, _txt) in enumerate(t.entries):
                        kb = k.encode('latin-1', 'replace')
                        if kb not in first:
                            first[kb] = base + i
                    self._tblidx.update(first)
        v = self._tblidx.get(bytes(key))
        if v is None:
            try:   # bin2txt writes keys as UTF-8 when the latin-1 bytes were UTF-8
                v = self._tblidx.get(bytes(key).decode('utf-8').encode('latin-1'))
            except UnicodeError:
                v = None
        if v is None and self.placeholders:
            m = re.match(rb'^#(\d+)$', key)
            if m:
                return int(m.group(1)) & 0xFFFF
        return NONE_STR if v is None else v & 0xFFFF

    # -- calc
    def _calc_link(self, kind):
        def code_of(name):
            return to_code(name if name else b'    ')

        def link(name, a3, kw):
            sc = self.linker('skillcalc')
            mc = self.linker('misscalc')
            if kind == 'items':
                if kw == 5:          # D2Sigma item skill('name'.calc) (calc.ITEM_FUNCS id 5)
                    if a3 == 1:
                        r = self._name_row('skills', name)
                        if r >= 0:
                            return r, True
                    return (sc.get(code_of(name)) if sc else -1), False
                if a3 == 1 and kw == 3:
                    r = self._name_row('itemstatcost', name)
                    if r >= 0:
                        return r, True
                    ln = name.lower()
                    if ln == b'base':
                        return 1, False
                    if ln == b'mod':
                        return 2, False
                    return 0, False
                return 0, False
            dflt = mc if kind == 'missiles' else sc
            lk = dflt
            ext = kind == 'skills' or self.version == 'mxl'   # D2Sigma: missiles get stat/sklvl
            if a3 == 1:
                if kw == 3 or (kw == 6 and ext):
                    r = self._name_row('skills', name)
                    if r >= 0:
                        return r, True
                    lk = sc
                elif kw == 4:
                    r = self._name_row('missiles', name)
                    if r >= 0:
                        return r, True
                    lk = mc
                elif kw == 5 and ext:
                    r = self._name_row('itemstatcost', name)
                    if r >= 0:
                        return r, True
                    ln = name.lower()
                    if ln == b'base':
                        return 1, False
                    if ln == b'mod':
                        return 2, False
                    return 0, False
            m = re.match(rb'^p(\d+)$', name)
            r = lk.get(code_of(name)) if lk else -1
            if r < 0 and m and self.placeholders:
                return int(m.group(1)), False
            return r, False
        return link

    def calc_keywords(self, kind):
        if kind == 'missiles' and self.version == 'mxl':
            return KEYWORDS['skills']
        return KEYWORDS[kind]

    def _name_row(self, table, name):
        lk = self.linker(table)
        if lk is None:
            return -1
        r = lk.get(name)
        if r < 0:
            r = self._placeholder(table, name)
        return r

    def code_pool(self, pool):
        """Bytes of a *code.bin (compiles the owning tables first)."""
        pool = pool.lower()
        if pool not in self._pool_done:
            self._pool_done.add(pool)
            self._pools.setdefault(pool, bytearray())
            owners = self._pool_tables(pool)
            for t in owners:
                self.compile(t)
            if not owners:
                self._pools[pool] = bytearray(self._pool_from_listing(pool) or b'')
            self._apply_pool_patch(pool)
        return bytes(self._pools[pool])

    def _pool_tables(self, pool):
        out = []
        names = [t for t in LOAD_ORDER] + sorted(t for t in self._files if t not in LOAD_ORDER)
        for t in names:
            lay = self.layout(t)
            if lay and self.txt(t) and any(f.get('link') == 'calc:' + pool for f in lay['fields']):
                out.append(t)
        return out

    def _pool_from_listing(self, pool):
        """A pool no table owns (e.g. Sigma's skills2code): rebuild it from the hex lines of
        bin2txt's listing ('index<TAB>expr' then '<TAB>hex bytes')."""
        p = self._files.get(pool)
        if not p:
            return None
        out = bytearray()
        with open(p, 'rb') as fh:
            for ln in fh.read().split(b'\n'):
                if ln.startswith(b'\t'):
                    try:
                        out += bytes.fromhex(ln.strip().decode('latin-1'))
                    except ValueError:
                        pass
        return bytes(out)

    def _apply_pool_patch(self, pool):
        t = self.txt(pool)
        if not t:
            return
        hdr, rows = t
        lines = [hdr] + rows
        for cells in lines:
            if cells and cells[0] == b'*pool' and len(cells) > 1:
                _apply_patch(self._pools[pool], cells[1])

    def _calc(self, pool, cell):
        if pool not in self._pool_prefix:
            # earlier owners of the same pool are appended first (weapons, armor, misc)
            self._pool_prefix.add(pool)
            for t in self._pool_tables(pool):
                if t == self._current:
                    break
                self.compile(t)
        if not cell:
            return 0xFFFFFFFF
        m = POOL_OFF.match(bytes(cell))
        if m:
            return int(m.group(1)) & 0xFFFFFFFF
        m = RAW_CALC.match(bytes(cell))
        if m:
            code = bytes.fromhex(m.group(1).decode())
        else:
            kind = POOL_KIND.get(pool, 'skills')
            code = compile_expr(cell[:256], kind, self._calc_link(kind), arity=True,
                                keywords=self.calc_keywords(kind),
                                lenient=(self.version == 'mxl') if self.lenient is None else self.lenient)
        if not code:
            return 0xFFFFFFFF
        buf = self._pools.setdefault(pool, bytearray())
        off = len(buf)
        buf += code
        return off

    # -- compile one table
    def compile(self, table):
        """-> bytes of <table>.bin, or None if there is no txt / layout."""
        table = table.lower()
        if table in self._out:
            return self._out[table]
        self._out[table] = None
        t = self.txt(table)
        if t is None:
            return None
        lay = self.layout(table)
        if lay is None:
            data = compile_raw(t)
            self._out[table] = data
            return data
        prev, self._current = self._current, table
        data = self._compile(table, lay, t)
        self._current = prev
        self._out[table] = data
        return data

    def _compile(self, table, lay, t):
        hdr, rows = t
        rs = lay['record_size']
        fields = [f for f in lay['fields'] if f.get('offset') is not None and f.get('ftype')]
        # header -> descriptor (first txt column wins, case-insensitive)
        byname = {}
        for f in fields:
            byname.setdefault(f['name'].lower().encode('latin-1'), []).append(f)
        colmap = []
        used = set()
        for i, h in enumerate(hdr):
            for f in byname.get(h.lower(), []):
                if id(f) not in used:
                    used.add(id(f))
                    colmap.append((i, f))
                    break
        missing = [f for f in fields if id(f) not in used]
        # one contiguous buffer like the game's: a string written past a record's end lands in
        # the next record (where that row's own columns may overwrite it again)
        SLACK = 512
        buf = bytearray(rs * len(rows) + SLACK)
        mv = memoryview(buf)
        recs = [mv[r * rs: r * rs + rs + SLACK] for r in range(len(rows))]
        patch_col = next((i for i, h in enumerate(hdr) if h.lower() == b'*patch'), None)
        # pass 1: keys, row by row
        own = {}
        keycols = []
        for i, f in colmap:
            ft = f['ftype']
            if CLASS.get(ft) == 'key':
                lk = CodeLinker() if ft in (10, 12, 14) else NameLinker()
                keycols.append((i, f, lk))
        for r, row in enumerate(rows):
            for i, f, lk in keycols:
                self._key(recs[r], f, _cell(row, i), lk)
        # pass 2 (row by row, txt column order), then descriptors with no column
        for r, row in enumerate(rows):
            rec = recs[r]
            for i, f in colmap:
                if CLASS.get(f['ftype']) != 'key':
                    self._field_set(table, rec, f, _cell(row, i), r)
            for f in missing:
                cls = CLASS.get(f['ftype'])
                if cls == 'cb':
                    self._field_set(table, rec, f, None, r)
                elif cls in ('code', 'name'):
                    # Fog reads past the row end here: the lookup fails -> -1
                    w = self._width(f['ftype'])
                    rec[f['offset']:f['offset'] + w] = b'\xff' * w
        out = bytearray(struct.pack('<I', len(rows)))
        for r in range(len(rows)):
            rec = bytearray(buf[r * rs: (r + 1) * rs])
            if patch_col is not None:
                _apply_patch(rec, _cell(rows[r], patch_col))
            out += rec
        return bytes(out)

    def _key(self, rec, f, cell, lk):
        ft, off = f['ftype'], f['offset']
        if ft in (10, 12, 14):
            code = to_code(cell)
            lk.add(code)
            b = struct.pack('<I', code)
            rec[off:off + {10: 4, 12: 1, 14: 2}[ft]] = b[:{10: 4, 12: 1, 14: 2}[ft]]
        elif ft == 16:
            # 1.07-1.09d key string: copied whole (strcpy, no limit); later columns overwrite
            # what ran past the buffer.  The linker gets the full name.
            s = bytes(cell).split(b'\0')[0]
            _write(rec, off, s + b'\0')
            lk.add_record(s)
        else:
            idx = lk.add_key(cell[:31])
            rec[off:off + WIDTH[ft]] = (idx & 0xFFFFFFFF).to_bytes(4, 'little')[:WIDTH[ft]]

    def _field_set(self, table, rec, f, cell, row):
        ft, off = f['ftype'], f['offset']
        cls = CLASS.get(ft)
        link = f.get('link') or ''

        def put(v, w):
            rec[off:off + w] = (v & 0xFFFFFFFF).to_bytes(4, 'little')[:w]
        if cls == 'str':
            size = f['size'] or 1
            s = bytes(cell[:size]).split(b'\0')[0]
            _write(rec, off, s + b'\0')
        elif cls == 'num':
            if ft == 5 and not cell:
                return
            v = fog_atoi(cell)
            if ft == 26:
                bit = f.get('bit') or 0
                o = off + (bit >> 3)
                if v:
                    rec[o] |= 1 << (bit & 7)
                else:
                    rec[o] &= ~(1 << (bit & 7)) & 0xFF
            else:
                put(v, WIDTH[ft])
        elif cls == 'raw':
            rec[off:off + 4] = struct.pack('<I', to_code(cell))
        elif cls == 'code':
            if link.startswith('static:'):
                v = self._static(link, cell)
            elif '.' in link:
                v = self.code_index(link, cell)
            else:
                v = fog_atoi(cell) if cell else -1
            put(v, WIDTH[ft])
        elif cls == 'name':
            if link.startswith('static:'):
                v = self._static(link, cell)
            elif '.' in link:
                v = self.name_index(link, cell)
            else:
                v = fog_atoi(cell) if cell else -1     # Sigma var: links: bin2txt writes the number
            put(v, self._width(ft))
        elif cls == 'tbl':
            put(self.tbl_index(bytes(cell[:255])), 2)
        elif cls == 'cb':
            self._callback(table, rec, f, cell, row)

    def _width(self, ft):
        # 1.07-1.09d Fog (type 17 'name -> word') stores the index as a dword
        return 4 if ft == 20 and self.version in OLD_VERSIONS else WIDTH[ft]

    def _static(self, link, cell):
        lst = [x.encode('latin-1') for x in link[7:].split(',')]
        if cell in lst:
            return lst.index(cell)
        return fog_atoi(cell) if cell else -1

    # -- callbacks
    def _callback(self, table, rec, f, cell, row):
        link = f.get('link') or ''
        off = f['offset']
        if link.startswith('calc:'):
            v = self._calc(link[5:], cell[:256] if cell else cell)
            rec[off:off + 4] = struct.pack('<I', v & 0xFFFFFFFF)
        elif link == 'param':
            rec[off:off + 4] = struct.pack('<I', self._param(table, cell) & 0xFFFFFFFF)
        elif link == 'cube_input':
            if cell:
                self._cube_input(rec, 0x14 + 8 * off, cell)
        elif link == 'cube_output':
            if cell:
                self._cube_output(rec, 0x4C + 0x54 * off, cell)
        elif link == 'monstats_skmode':
            self._skmode(rec, off, cell)
        elif link == 'monstats2_comp':
            self._composit(rec, off, cell)
        elif link == 'monpreset_place':
            self._preset(rec, cell)
        elif link == 'sigma_classifications':
            self._sigma_classifications(rec, off, cell)
        elif link in ('sigma_requirement_param', 'sigma_npcaction_param'):
            self._sigma_param(link, rec, off, cell)
        else:
            # Sigma callback of unknown semantics: bin2txt shows the dword at the offset
            if cell is not None:
                rec[off:off + 4] = struct.pack('<I', fog_atoi(cell) & 0xFFFFFFFF)

    # -- D2Sigma callbacks (inverse of bin2txt._sigma_*; FUN_100822e0 / 10082c10 / 10082620)
    def _sigma_classifications(self, rec, off, cell):
        items = [x for x in re.split(rb'[ "\t,]+', cell or b'') if x][:16]
        vals = []
        for x in items:
            r = self.name_index('itemclasses.Name', x)
            if r > 0:
                vals.append(r)
        for i in range(16):
            v = vals[i] if i < len(vals) else 0
            rec[off + 2 * i: off + 2 * i + 2] = struct.pack('<H', v & 0xFFFF)

    def _sigma_param(self, link, rec, off, cell):
        from .bin2txt import (REQUIREMENT_PARAMS, NPCACTION_PARAMS, sigma_param_kind)
        spec = REQUIREMENT_PARAMS if link == 'sigma_requirement_param' else NPCACTION_PARAMS
        cell = cell or b''
        num = c_atoi(cell) if cell else 0
        kind = sigma_param_kind(spec, struct.unpack_from('<i', rec, 0)[0], off)
        if kind == 'code':
            v = to_code(cell) if cell else 0
        elif kind == 'tbl':
            v = self.tbl_index(cell)
        elif kind in ('stat', 'sound'):
            v = num
            if cell and not re.match(rb'^-?\d+$', cell):
                r = self.name_index('itemstatcost.stat' if kind == 'stat' else 'sounds.Sound', cell)
                v = r if r >= 0 else num
        elif kind[0] == 'num':
            v = num if cell else kind[1]
        else:
            _l, t, c, empty = kind
            if not cell:
                v = empty
            elif t == 'playerclass':
                v = self.code_index('playerclass.%s' % c, cell)
            else:
                v = self.name_index('%s.%s' % (t, c), cell)
            if v < 0:
                v = empty
        rec[off:off + 4] = struct.pack('<I', v & 0xFFFFFFFF)

    def _param(self, table, cell):
        if not cell:
            return 0
        if cell[:1] == b'-' or b'0' <= cell[:1] <= b'9':
            return c_atoi(cell)
        if table == 'cubemain':
            return max(self._name_row('itemstatcost', cell), 0)
        for t in ('skills', 'montype', 'states'):
            r = self._name_row(t, cell)
            if r >= 0:
                return r
        return 0

    def _item_index(self, code_bytes):
        lk = self.linker('weapons')
        return lk.get(to_code(code_bytes)) if lk else -1

    def _special_row(self, table, name):
        r = self._name_row(table, name)
        return r

    def _special_vals(self, table, r):
        if table == 'uniqueitems':
            code = (self.column(table, 'code') or [])[r]
            lvl = (self.column(table, 'lvl') or [])[r]
        else:
            code = (self.column(table, 'item') or [])[r]
            lvl = (self.column(table, 'lvl') or [])[r]
        return code, fog_atoi(lvl)

    def _cube_input(self, rec, o, cell):
        s = bytes(cell)
        if s[:1] == b'"':
            s = s[1:]
        s = s.split(b'"')[0]
        if not s:
            return
        parts = s.split(b',', 1)
        base, rest = parts[0], (parts[1] if len(parts) > 1 else None)
        flags, item, iid, qual, qty = struct.unpack_from('<HHHBB', rec, o)
        if len(base) <= 4 and base.lower() == b'any':
            flags |= 1
            item = 0xFFFF
        else:
            lid = self.linker('itemtypes').get(to_code(base)) if len(base) <= 4 and \
                self.linker('itemtypes') else -1
            bid = self._item_index(base) if len(base) <= 4 else -1
            if lid >= 0:
                flags |= 2
                item = lid
            elif bid >= 0:
                flags |= 1
                item = bid
            else:
                done = False
                for tb, q in (('uniqueitems', 7), ('setitems', 5)):
                    r = self._special_row(tb, base)
                    if r >= 0:
                        code, _lvl = self._special_vals(tb, r)
                        b = self._item_index(code)
                        flags |= 0x41
                        qual = q
                        iid = r + 1
                        item = b if b >= 0 else 0
                        done = True
                        break
                if not done:
                    struct.pack_into('<HHHBB', rec, o, flags, item & 0xFFFF, iid, qual, qty)
                    return
        mods = {b'nos': 4, b'sock': 8, b'noe': 0x20, b'eth': 0x10, b'upg': 0x80, b'bas': 0x100,
                b'exc': 0x200, b'eli': 0x400, b'nru': 0x800}
        quals = {b'low': 1, b'nor': 2, b'hiq': 3, b'mag': 4, b'set': 5, b'rar': 6, b'uni': 7,
                 b'crf': 8, b'tmp': 9}
        nxt = rest
        while nxt is not None:
            m = re.search(rb'[=,]', nxt)
            mod, nxt = (nxt[:m.start()], nxt[m.end():]) if m else (nxt, None)
            if mod == b'qty':
                if nxt is None:
                    break
                m = re.search(rb',', nxt)
                val, nxt = (nxt[:m.start()], nxt[m.end():]) if m else (nxt, None)
                qty = c_atoi(val) & 0xFF
            elif mod in quals:
                qual = quals[mod]
            elif mod in mods:
                flags |= mods[mod]
            else:
                break
        struct.pack_into('<HHHBB', rec, o, flags & 0xFFFF, item & 0xFFFF, iid & 0xFFFF, qual, qty)

    def _nrows(self, table):
        t = self.txt(table)
        return len(t[1]) if t else 0

    def _sigma_cube_output(self, rec, o, cell):
        """D2Sigma FUN_10081d10 (Median's cube output parser, see bin2txt.SIGMA_CUBE_OUT).
        Tokens are strtok(',') pieces; a handler that reads '=value' runs strtok on its own
        token, which ends the outer loop: nothing after the first valued token counts."""
        from .bin2txt import SIGMA_CUBE_KW, SIGMA_CUBE_MODS
        s = bytes(cell)
        if s[:1] == b'"':
            s = s[1:]
        s = s.split(b'"')[0]
        toks = [t for t in s.split(b',') if t]
        if not toks:
            return
        flags, item, iid, qual, qty, typ = struct.unpack_from('<HHHBBB', rec, o)
        val = None
        pre = [struct.unpack_from('<H', rec, o + 12 + 2 * k)[0] for k in range(3)]
        suf = [struct.unpack_from('<H', rec, o + 18 + 2 * k)[0] for k in range(3)]

        def value(tok):
            v = [x for x in tok.split(b'=') if x]
            return v[1] if len(v) > 1 else None

        def row_or_num(tok, table, lo, dflt):
            v = value(tok)
            if v is None:
                return dflt
            n = self._nrows(table)
            r = self._name_row(table, v)
            if lo <= r < n:
                return r
            r = c_atoi(v)
            return r if lo <= r < n else dflt

        def num(tok, dflt, lo=None):
            v = value(tok)
            if v is None:
                return dflt
            r = c_atoi(v)
            return lo if lo is not None and r < lo else r

        first, stop = toks[0], False
        kw = next((k for k in SIGMA_CUBE_KW if first.startswith(k.encode())), None)
        if kw is not None:
            stop = kw not in ('useitem', 'usetype')
            if kw == 'portal':
                val, typ = row_or_num(first, 'levels', 1, 0), 1
            elif kw in ('skillpts', 'statpts'):
                val, typ = num(first, 1, 1), (2 if kw == 'skillpts' else 3)
            elif kw == 'mon':
                val, typ = row_or_num(first, 'monstats', 0, -1), 4
            elif kw == 'boss':
                val, typ = row_or_num(first, 'superuniques', 0, -1), 5
            elif kw == 'goldcost':
                val, typ = num(first, 0), 6
            elif kw == 'useitem':
                typ = 0xFE
            elif kw == 'usetype':
                typ = 0xFF
            else:
                val = num(first, -1)
                typ = {'set_flag_player': 7, 'unset_flag_player': 8, 'set_flag_game': 9,
                       'unset_flag_game': 10}[kw]
        elif len(first) < 5:
            b = self._item_index(first)
            lid = self.linker('itemtypes').get(to_code(first)) if self.linker('itemtypes') \
                else -1
            if b >= 0:
                typ, item = 0xFC, b
            elif lid >= 0:
                typ, item = 0xFD, lid
        else:
            for tb, q in (('uniqueitems', 7), ('setitems', 5)):
                r = self._special_row(tb, first)
                if 0 <= r < self._nrows(tb):
                    code, _lvl = self._special_vals(tb, r)
                    b = self._item_index(code)
                    if b >= 0:
                        flags |= 8
                        item, iid, qual, typ = b, r + 1, q, 0xFC
                        break
        quals = {b'low': 1, b'nor': 2, b'hiq': 3, b'mag': 4, b'set': 5, b'rar': 6, b'uni': 7,
                 b'crf': 8, b'tmp': 9}
        fl = {b'eth': 4, b'mod': 1, b'uns': 0x10, b'rem': 0x20, b'exc': 0x80, b'eli': 0x100,
              b'rep': 0x200, b'rch': 0x400}
        for tok in toks[1:]:
            if stop:
                break
            m = next((k.encode() for k in SIGMA_CUBE_MODS if tok.startswith(k.encode())), None)
            if m is None:
                continue
            if m == b'qty':
                qty, stop = num(tok, 1, 1) & 0xFF, True
            elif m in (b'pre', b'suf'):
                lst = pre if m == b'pre' else suf
                v = num(tok, 0, 0)
                k = next((k for k in range(3) if not lst[k]), None)
                if k is not None:
                    lst[k] = v & 0xFFFF
                stop = True
            elif m in quals:
                qual = quals[m]
            elif m == b'sock':
                flags |= 2
                qty, stop = num(tok, 1, 1) & 0xFF, True
            elif m == b'reg':
                flags |= 0x40
                typ = 0xFF
            else:
                flags |= fl[m]
        struct.pack_into('<HHHBBB', rec, o, flags & 0xFFFF, item & 0xFFFF, iid & 0xFFFF, qual,
                         qty, typ)
        if val is not None:
            struct.pack_into('<H', rec, o + 6, val & 0xFFFF)
        for k in range(3):
            struct.pack_into('<H', rec, o + 12 + 2 * k, pre[k])
            struct.pack_into('<H', rec, o + 18 + 2 * k, suf[k])

    def _cube_output(self, rec, o, cell):
        if self.version == 'mxl':
            return self._sigma_cube_output(rec, o, cell)
        s = bytes(cell)
        if s[:1] == b'"':
            s = s[1:]
        s = s.split(b'"')[0]
        parts = s.split(b',', 1)
        base, rest = parts[0], (parts[1] if len(parts) > 1 else None)
        flags, item, iid, qual, qty, typ = struct.unpack_from('<HHHBBB', rec, o)
        ilvl = rec[o + 11]
        lb = base.lower()
        portals = {b'cow portal': 1, b'pandemonium portal': 2, b'pandemonium finale portal': 3}
        if self.version in ('107', '108', '109d', '110'):
            portals = {b'cow portal': 1}
        if lb in portals:
            typ = portals[lb]
        elif base == b'usetype':
            typ = 0xFF
        elif base == b'useitem':
            typ = 0xFE
        elif len(base) <= 4 and self._item_index(base) >= 0:
            typ = 0xFC
            item = self._item_index(base)
        else:
            lid = self.linker('itemtypes').get(to_code(base)) if len(base) <= 4 and \
                self.linker('itemtypes') else -1
            if lid >= 0:
                typ = 0xFD
                item = lid
            else:
                for tb, q in (('uniqueitems', 7), ('setitems', 5)):
                    r = self._special_row(tb, base)
                    if r >= 0:
                        code, lvl = self._special_vals(tb, r)
                        b = self._item_index(code)
                        flags |= 8
                        typ = 0xFC
                        qual = q
                        iid = r + 1
                        item = b if b >= 0 else 0
                        ilvl = lvl & 0xFF
                        break
                else:
                    return
        pre = [struct.unpack_from('<H', rec, o + 12 + 2 * k)[0] for k in range(3)]
        suf = [struct.unpack_from('<H', rec, o + 18 + 2 * k)[0] for k in range(3)]
        npre = nsuf = 0
        fl = {b'eth': 4, b'mod': 1, b'uns': 0x10, b'rem': 0x20, b'exc': 0x80, b'eli': 0x100,
              b'rep': 0x200, b'rch': 0x400}
        quals = {b'low': 1, b'nor': 2, b'hiq': 3, b'mag': 4, b'set': 5, b'rar': 6, b'uni': 7,
                 b'crf': 8, b'tmp': 9}
        extra = []          # pre/suf beyond 3 write into the following fields (pointer walk)
        nxt = rest
        while nxt is not None:
            m = re.search(rb'[=,]', nxt)
            mod, nxt = (nxt[:m.start()], nxt[m.end():]) if m else (nxt, None)

            def val():
                nonlocal nxt
                if nxt is None:
                    return 0
                m2 = re.search(rb',', nxt)
                v, nxt = (nxt[:m2.start()], nxt[m2.end():]) if m2 else (nxt, None)
                return c_atoi(v)
            if mod == b'qty':
                qty = val() & 0xFF
            elif mod == b'pre':
                v = val() & 0xFFFF
                if npre < 3:
                    pre[npre] = v
                else:
                    extra.append((12 + 2 * npre, v))
                npre += 1
            elif mod == b'suf':
                v = val() & 0xFFFF
                if nsuf < 3:
                    suf[nsuf] = v
                else:
                    extra.append((18 + 2 * nsuf, v))
                nsuf += 1
            elif mod in quals:
                qual = quals[mod]
            elif mod == b'sock':
                flags |= 2
                qty = val() & 0xFF
            elif mod == b'reg':
                flags |= 0x40
                typ = 0xFF
            elif mod in fl:
                flags |= fl[mod]
            else:
                break
        struct.pack_into('<HHHBBB', rec, o, flags & 0xFFFF, item & 0xFFFF, iid & 0xFFFF, qual,
                         qty, typ)
        rec[o + 11] = ilvl
        for k in range(3):
            struct.pack_into('<H', rec, o + 12 + 2 * k, pre[k])
            struct.pack_into('<H', rec, o + 18 + 2 * k, suf[k])
        for eo, v in extra:
            struct.pack_into('<H', rec, o + eo, v)

    def _skmode(self, rec, k, cell):
        if not (0 <= k < 8):
            return
        rec[0x180 + k] = 0
        struct.pack_into('<h', rec, 0x188 + 2 * k, -1)
        skill = struct.unpack_from('<h', rec, 0x170 + 2 * k)[0]
        if skill < 0 or cell is None:
            return
        if len(cell) > 3:
            rec[0x180 + k] = 14
            struct.pack_into('<h', rec, 0x188 + 2 * k, self._seq(cell))
            return
        lk = self.linker('monmode', 'code')
        mode = lk.get(to_code(cell)) if lk else -1
        mode = struct.unpack('<b', struct.pack('<B', mode & 0xFF))[0]
        rec[0x180 + k] = mode & 0xFF
        if mode < 0 or mode == 14:
            rec[0x180 + k] = 14
            struct.pack_into('<h', rec, 0x188 + 2 * k, self._seq(cell))

    def _seq(self, cell):
        r = self._name_row('monseq', cell)
        return max(min(r, 32767), -32768)

    def _composit(self, rec, k, cell):
        if not (0 <= k < 16):
            return
        rec[0x15 + k] = 0
        rec[0x26 + 12 * k: 0x26 + 12 * k + 12] = b'\xff' * 12
        if cell is None:
            return
        s = bytes(cell)
        if s[:1] == b'"':
            s = s[1:]
        s = s.split(b'"')[0]
        lk = self.linker('compcode')
        cnt = 0
        toks = s.split(b',')
        for tk in toks:
            if not tk or len(tk) > 4:
                break
            v = lk.get(to_code(tk)) if lk else -1
            rec[0x26 + 12 * k + cnt] = v & 0xFF
            cnt += 1
            if cnt >= 12:
                break
        rec[0x15 + k] = cnt
        if k == 15:
            tot = sum(c - 1 for c in rec[0x15:0x25] if c > 1)
            rec[0x25] = min(tot, 254)

    def _preset(self, rec, cell):
        rec[1] = 0
        struct.pack_into('<H', rec, 2, 0)
        if not cell:
            return
        r = self._name_row('superuniques', cell)
        if r >= 0:
            rec[1] = 2
            struct.pack_into('<H', rec, 2, r & 0xFFFF)
            return
        r = self._name_row('monstats', cell)
        if r >= 0:
            rec[1] = 1
            struct.pack_into('<H', rec, 2, r & 0xFFFF)
            return
        r = self._name_row('monplace', cell)
        if r >= 0:
            struct.pack_into('<H', rec, 2, r & 0xFFFF)

    # -- everything
    def compile_all(self):
        """{name: bytes} for every txt with a layout (or raw dump) plus the code pools."""
        out = {}
        for t in LOAD_ORDER + sorted(x for x in self._files if x not in LOAD_ORDER):
            if t in CODE_TABLES:
                continue
            if t not in self._files and not (t == 'leveldefs' and 'levels' in self._files):
                continue
            if self.layout(t) is None and not _is_raw_dump(self.txt(t)):
                continue
            d = self.compile(t)
            if d is not None:
                out[t] = d
        for pool in sorted(set(POOL_KIND) | set(self._pools)):
            if self._pool_tables(pool) or pool in self._pools:
                out[pool] = self.code_pool(pool)
        return out


def _write(rec, off, data):
    """rec[off:...] = data, clipped to the record view."""
    data = data[:max(len(rec) - off, 0)]
    rec[off:off + len(data)] = data


def absent_fields(lay, compiled, original):
    """Fields that look like they had no column in the source txt: every record holds what Fog
    leaves for a missing descriptor (0 for RAW / string keys, -1 for links) and compiling the
    decoded cells gives something else.  bin2txt's lossless mode drops these columns."""
    if not lay or len(compiled) != len(original) or len(original) < 4:
        return []
    n = struct.unpack_from('<I', original)[0]
    rs = lay['record_size']
    if not n or 4 + n * rs != len(original):
        return []
    out = []
    for f in lay['fields']:
        cls = CLASS.get(f.get('ftype'))
        off = f.get('offset')
        if off is None or cls not in ('raw', 'tbl', 'code', 'name'):
            continue
        w = 4 if cls == 'raw' else WIDTH[f['ftype']]
        miss = b'\0' * w if cls in ('raw', 'tbl') else b'\xff' * w
        differs = False
        for r in range(n):
            o = 4 + r * rs + off
            if original[o:o + w] != miss:
                break
            differs = differs or compiled[o:o + w] != miss
        else:
            if differs:
                out.append(f['name'])
    return out


def _apply_patch(rec, spec):
    """'off:compiledhex>originalhex;...' applied only where rec still holds compiledhex."""
    for part in bytes(spec).split(b';'):
        if not part:
            continue
        try:
            off, rest = part.split(b':', 1)
            a, b = rest.split(b'>', 1)
            off = int(off)
            a = bytes.fromhex(a.decode())
            b = bytes.fromhex(b.decode())
        except ValueError:
            continue
        if rec[off:off + len(a)] == a:
            rec[off:off + len(b)] = b


def make_patch(compiled, original):
    """Inverse of _apply_patch: patch spec turning compiled into original (str, '' if equal)."""
    out = []
    i = 0
    n = max(len(compiled), len(original))
    while i < n:
        if i < len(compiled) and i < len(original) and compiled[i] == original[i]:
            i += 1
            continue
        j = i
        while j < n and not (j < len(compiled) and j < len(original) and
                             compiled[j] == original[j]):
            j += 1
        out.append('%d:%s>%s' % (i, compiled[i:j].hex(), original[i:j].hex()))
        i = j
    return ';'.join(out)


# ---------------------------------------------------------------- raw dumps

RAW_COL = re.compile(rb'^(str|i32|u16|u8)@(\d+)$')


def _is_raw_dump(t):
    return bool(t and t[0] and t[0][0] == b'row' and len(t[0]) > 1 and RAW_COL.match(t[0][1]))


def compile_raw(t):
    """bin2txt raw dump (row, type@offset ...) -> bin; None if not a raw dump."""
    if not _is_raw_dump(t):
        return None
    hdr, rows = t
    cols = []
    for i, h in enumerate(hdr):
        m = RAW_COL.match(h)
        if m:
            cols.append((i, m.group(1), int(m.group(2))))
    rs = None
    patch_col = next((i for i, h in enumerate(hdr) if h.lower() == b'*patch'), None)
    rsc = next((i for i, h in enumerate(hdr) if h.lower() == b'*size'), None)
    if rsc is not None and rows:
        rs = c_atoi(_cell(rows[0], rsc))
    if not rs:
        last = cols[-1]
        rs = last[2] + {b'i32': 4, b'u16': 2, b'u8': 1}.get(last[1], 4)
    out = bytearray(struct.pack('<I', len(rows)))
    for row in rows:
        rec = bytearray(rs)
        for k, (i, typ, off) in enumerate(cols):
            cell = _cell(row, i)
            if typ == b'str':
                end = cols[k + 1][2] if k + 1 < len(cols) else rs
                s = bytes(cell)
                try:
                    s = s.decode('utf-8').encode('latin-1')
                except UnicodeError:
                    pass
                rec[off:end] = (s + bytes(end - off))[:end - off]
            else:
                w = {b'i32': 4, b'u16': 2, b'u8': 1}[typ]
                rec[off:off + w] = (c_atoi(cell) & 0xFFFFFFFF).to_bytes(4, 'little')[:w]
        if patch_col is not None:
            _apply_patch(rec, _cell(row, patch_col))
        out += rec[:rs]
    return bytes(out)


# ------------------------------------------------------------------ top level

def compile_dir(txt_dir, out_dir=None, version='auto', strings=None, tables=None):
    """Compile every txt in txt_dir; writes <table>.bin to out_dir if given. -> {table: bytes}"""
    proj = Project(txt_dir, version=version, strings=strings)
    if tables:
        res = {}
        for t in tables:
            t = t.lower()
            if t in POOL_KIND:
                res[t] = proj.code_pool(t)
            else:
                d = proj.compile(t)
                if d is not None:
                    res[t] = d
    else:
        res = proj.compile_all()
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for t, d in res.items():
            with open(os.path.join(out_dir, t + '.bin'), 'wb') as fh:
                fh.write(d)
    return res
