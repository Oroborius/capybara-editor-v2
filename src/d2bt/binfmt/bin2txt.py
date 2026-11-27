"""Classic D2 excel .bin -> .txt, driven by layouts/<version>/<table>.json.

    headers, rows = convert(data, 'weapons', version='auto', ctx=Context(bin_dir))
    write_txt(path, headers, rows)

A .bin is u32 record count followed by fixed-size records.  Each layout field
describes where one txt column was compiled to.  Links (columns that were
compiled to a row index of another table) are resolved back to that table's
key when the key is stored in its .bin; otherwise a placeholder is written:
prefix + row number (pr116 = properties row 116, sk198 = skills row 198, ...).

Bins with no matching layout fall back to a raw dump with columns named
type@offset (str / i32 / u16 / u8).

Whole directories: convert_dir(bin_dir, out_dir, lossless=False, structure=True).  The default
(structure=True) output already compiles back (txt2bin) to the same bytes for Median, 1.10,
1.13c/d and 1.14d, because it also recovers the source txt's structure from the bins:
  - drops columns the source txt evidently lacked (every record holds what Fog leaves for a
    missing column: 0 RAW codes / string keys, -1 links), so the compiler leaves them alone too;
  - permutes the calc columns into the order recovered from the pool offsets (the game appends
    formulas row by row in txt column order).
lossless=True adds what is left after that (nothing for Median, 1.10, 1.13c/d, 1.14d; the
1.11b/1.12a itemscode pool holds misc's formulas three times; 1.07-1.09d skills keep name bytes
past the 16-char key field and missiles a dword at +168):
  - '?{hex}' for formula bytecode whose text does not compile back;
  - a hidden '*patch' column for records that still differ ('off:compiled>original;...',
    applied by txt2bin only where the compiled bytes are unchanged, so edits win) and a
    '*pool' line in a code listing whose pool differs.
Formulas that are not one well-formed expression (Median: functions with a missing argument,
cells cut at 255 chars) are written by calc.render_faithful so that they compile back (txt2bin
lenient for 'mxl').  Median's cube outputs use D2Sigma's own grammar (SIGMA_CUBE_OUT).
The game ignores '*' columns.  Value conventions shared with txt2bin: '' = 0 / none / the
5382 'dummy' string; placeholders like pr116 = row 116 of the linked table.

Names and their inverse (every text written here must compile back to the same index):
  - A link cell is always the key text that the *target* table's own key column shows for that
    row, so txt2bin's linker (built from that column) maps it back.  Key columns whose text is
    not in the .bin (Fog types 17/18, e.g. skills.skill, itemstatcost.stat) and the links to
    them both go through Context.row_name(): a txt beside the bins, else the base table's
    column for a D2Sigma *names table (infographicsnames <- infographics.name), else, by
    Context(names=):
      'ingame' (default for Median): the name the player sees (NAME_SOURCES 'shown': skills via
        skilldesc 'str name', monsters NameStr, levels, superuniques, sets, states via
        stateicons ...), else the vanilla key, else a derived name (NAME_SOURCES 'derived': a
        missile's CelFile, the monster that uses a skill / sequence / sound ...);
      'vanilla' (default elsewhere, where only vanilla keys are used): the vanilla key first;
    the vanilla key = data/vanilla_keys.json when the row's fingerprint columns still match
    vanilla and the name is unique, else the placeholder.  Synthesized names are cleaned
    (clean_name), unique on the linker's 31 case-folded chars ('Iron Golem (sk132)' when
    several rows share one) and do not repeat a name of a table looked up before them
    (NAME_GROUPS).  Formula text uses the same names: stat('dexterity'.accr),
    skill('Iron Golem'.blvl); a name with an apostrophe is written by row number there.
  - '-1' (NOT_FOUND) in a link into sounds/montype/monsounds/treasureclassex: the txt named
    no row (-1); there '' is row 0, whose key is empty.
  - '@N' in a calc cell: pool offset N, written when the pool .bin is not in the dir.
  - Placeholders (PREFIX + index) are always accepted by txt2bin for links into that table;
    '#N' = string index N when no string table is loaded; 'itN' = item N (weapons+armor+misc).
  - Context(raw_links=True) / cli --raw-links writes every name key (Fog 17/18, the keys that
    are not in the .bin) and every link to one as its placeholder (the raw row index with the
    table prefix), still compilable; codes stored in the bins (item codes, itemtypes ...) stay.
  - D2Sigma callbacks (D2Linkers.cpp): Classifications = comma list of itemclasses keys;
    requirements / npcactions param1..10 are typed by the record's 'type' (REQUIREMENT_PARAMS /
    NPCACTION_PARAMS, shared with txt2bin): a key of the looked-up table, a 4-char code, a
    string key, or a number; '' = the value the game stores for an empty cell.
  - merge_ext / cli --merge-ext writes the D2Sigma extension tables as extra columns of their
    base txt (EXT_BASE, the hook FUN_100b9fa0 that Median's own -txt build uses); txt2bin reads an
    extension table from its base txt when its own txt is missing.
"""
import os
import re
import struct

from . import calc, layouts
from .tbl import StringSet, Tbl, pretty

# Bumped when the names written for rows whose key is not stored change (caches of converted
# txt, e.g. semantics.InstallData and bin_semantics.TxtStore, key on it).
NAMES_VERSION = 3

# Placeholder prefixes for rows whose key is not stored in the .bin.
PREFIX = {
    'arena': 'ae', 'belts': 'bl', 'books': 'bk', 'chartemplate': 'ct', 'cubemain': 'cm',
    'difficultylevels': 'dl', 'events': 'ev', 'inventory': 'iv', 'itemratio': 'ir',
    'itemstatcost': 'is', 'levels': 'lv', 'lvlmaze': 'lm', 'lvlprest': 'lp', 'lvlsub': 'ls',
    'lvltypes': 'lt', 'lvlwarp': 'lw', 'misc': 'mi', 'missiles': 'ml', 'monai': 'ma',
    'monlvl': 'mv', 'monplace': 'me', 'monprop': 'mp', 'monseq': 'mq', 'monstats': 'ms',
    'monstats2': 'ms', 'objgroup': 'og', 'overlay': 'ol', 'pettype': 'pt', 'properties': 'pr',
    'sets': 'se', 'shrines': 'sr', 'skilldesc': 'sd', 'skills': 'sk', 'states': 'st',
    'superuniques': 'su', 'uniquetitle': 'ut', 'monsounds': 'mo', 'montype': 'mt',
    'treasureclassex': 'tc', 'sounds': 'so', 'monumod': 'mu', 'hireling': 'hi',
    # Median XL (D2Sigma) tables whose key names are not stored in the .bin
    'cellfiles': 'cf', 'difficultylevelnames': 'dn', 'hireclassnames': 'hn',
    'infographicsnames': 'gn', 'itemclasses': 'ic', 'lvltypenames': 'ln',
    'npcactionnames': 'an', 'npcactiontypes': 'at', 'requirementnames': 'rn',
    'requirementtypes': 'rt',
}

STR_TYPES = (1, 7, 16)
CODE_TYPES = (9, 10)
LINK_TYPES = (11, 13, 15, 19, 20, 21)
NAMEKEY_TYPES = (17, 18)
# signedness of plain numeric columns by ftype
INT_FMT = {2: '<i', 8: '<i', 3: '<h', 4: '<B', 5: '<B', 6: '<b', 12: '<B', 14: '<H',
           11: '<I', 13: '<B', 15: '<H', 19: '<I', 20: '<H', 21: '<B', 22: '<H', 25: '<I',
           17: '<H', 18: '<I'}
NONE_VAL = {1: 0xFF, 2: 0xFFFF, 4: 0xFFFFFFFF}

# Mode codes are fixed by the engine; their 'code' key column is not in the .bin.
MODE_CODES = {
    'plrmode': 'DT NU WL RN GH TN TW A1 A2 BL SC TH KK S1 S2 S3 S4 DD SQ KB'.split(),
    'monmode': 'DT NU WL GH A1 A2 BL SC S1 S2 S3 S4 DD KB xx RN'.split(),
}

# layouts using the 1.07-1.09d formats
OLD_VERSIONS = ('107', '108', '109d')
TC_AUTO_TOP = {'107': 132, '108': 90, '109d': 90}

# D2Sigma extension table -> the base txt it is compiled from under -txt (FUN_100b9fa0 swaps
# data\global\excel\<ext>.txt for <base>.txt): Median's own source keeps these columns
# inside the base txt.  bin2txt merge_ext writes them there; txt2bin reads them back from it.
EXT_BASE = {
    'armor2': 'armor', 'weapons2': 'weapons', 'misc2': 'misc', 'charstatsexp': 'charstats',
    'cubemainext': 'cubemain', 'difficultylevelnames': 'difficultylevels',
    'hireclassnames': 'hireclasses', 'hiredescext': 'hiredesc',
    'infographicsnames': 'infographics', 'itemtypesext': 'itemtypes',
    'lvltypenames': 'lvltypes', 'missiles2': 'missiles', 'monumodexp': 'monumod',
    'npcactionnames': 'npcactions', 'npcext': 'npc', 'objects2': 'objects',
    'requirementnames': 'requirements', 'skills2': 'skills', 'pettypeext': 'pettype',
    'propertiesext': 'properties', 'uniqueitems2': 'uniqueitems',
}

# tables whose row 0 is a 'none' entry (a link value of 0 means empty)
NONE_ROW0 = ('sounds', 'montype', 'monsounds')
# link cell for -1 (no row) into a NONE_ROW0 table, where '' means row 0
NOT_FOUND = '-1'

# tables whose items are numbered together in cube recipes etc.
ITEM_TABLES = ('weapons', 'armor', 'misc')
# code tables used by calc columns -> param-name table
CODE_TABLES = ('skillscode', 'skilldesccode', 'misscode', 'itemscode', 'skills2code')


# Where a name-key row (Fog 17/18: the name is not in the .bin) gets a readable name when no
# txt is beside the bins.  'shown': the name the player sees (the row's own .tbl string, or the
# row it is displayed through); 'derived': built from what the row carries (a file name, the
# row that uses it) for rows the player never sees named.  Sources:
#   ('tbl', col)               text of the row's string-table column
#   ('str', col)               a stored string (file names: base name, no extension)
#   ('via', col, table)        the row's link column -> that row's name
#   ('ref', table, cols)       the first row of table whose link column points here -> its name
#                              ('*skmode' = the monstats Sk*mode sequences)
#   ('row', table, col, kind)  the same row of another table (kind 'tbl' / 'str')
_MON_SKILLS = tuple('Skill%d' % i for i in range(1, 9))
NAME_SOURCES = {
    'skills': {'shown': [('via', 'skilldesc', 'skilldesc')],
               'derived': [('ref', 'monstats', _MON_SKILLS),
                           ('via', 'srvmissile', 'missiles'), ('via', 'cltmissile', 'missiles'),
                           ('ref', 'missiles', ('Skill',)), ('ref', 'states', ('skill',))]},
    'skilldesc': {'shown': [('tbl', 'str name')],
                  'derived': [('ref', 'skills', ('skilldesc',))]},
    'monstats': {'shown': [('tbl', 'NameStr')],
                 'derived': [('via', 'BaseId', 'monstats'), ('ref', 'monstats', ('minion1',
                                                                                   'minion2'))]},
    'monstats2': {'shown': [('ref', 'monstats', ('MonStatsEx',))]},
    'monprop': {'shown': [('ref', 'monstats', ('MonProp',))]},
    'monsounds': {'derived': [('ref', 'monstats', ('MonSound', 'UMonSound'))]},
    'monseq': {'derived': [('ref', 'monstats', ('*skmode',))]},
    'missiles': {'derived': [('str', 'CelFile'),
                             ('ref', 'skills', ('srvmissile', 'srvmissilea', 'srvmissileb',
                                                'srvmissilec', 'cltmissile', 'cltmissilea',
                                                'cltmissileb', 'cltmissilec', 'cltmissiled')),
                             ('via', 'Skill', 'skills'),
                             ('ref', 'missiles', ('SubMissile1', 'SubMissile2', 'SubMissile3',
                                                  'HitSubMissile1', 'HitSubMissile2',
                                                  'HitSubMissile3', 'HitSubMissile4',
                                                  'CltSubMissile1', 'CltSubMissile2',
                                                  'CltSubMissile3', 'CltHitSubMissile1',
                                                  'CltHitSubMissile2', 'CltHitSubMissile3',
                                                  'CltHitSubMissile4', 'ExplosionMissile')),
                             ('ref', 'monstats', ('MissA1', 'MissA2', 'MissS1', 'MissS2',
                                                  'MissS3', 'MissS4', 'MissC', 'MissSQ')),
                             # a controller missile (CelFile 'null'): what it spawns
                             ('via', 'SubMissile1', 'missiles'),
                             ('via', 'CltSubMissile1', 'missiles'),
                             ('via', 'HitSubMissile1', 'missiles'),
                             ('via', 'CltHitSubMissile1', 'missiles'),
                             ('via', 'ExplosionMissile', 'missiles')]},
    'states': {'shown': [('ref', 'stateicons', ('State',))],
               'derived': [('ref', 'skills', ('aurastate', 'auratargetstate', 'passivestate')),
                           ('via', 'skill', 'skills'), ('via', 'overlay1', 'overlay'),
                           ('via', 'castoverlay', 'overlay'), ('via', 'missile', 'missiles')]},
    'stateicons': {'shown': [('tbl', 'NameStr')]},
    'itemstatcost': {'derived': [('ref', 'statscreen', ('stat',)), ('tbl', 'descstrpos'),
                                 ('tbl', 'descstr2'), ('tbl', 'descstrneg')]},
    'statscreen': {'shown': [('tbl', 'text'), ('tbl', 'hoverText')]},
    'properties': {'derived': [('via', 'stat1', 'itemstatcost')]},
    'levels': {'shown': [('tbl', 'StrLevelName'), ('str', 'LevelName')]},
    'superuniques': {'shown': [('tbl', 'Name')]},
    'sets': {'shown': [('tbl', 'name')]},
    # Sigma splits Classifications on spaces too (FUN_100822e0): no spaces in these names
    'itemclasses': {'shown': [('tbl', 'Description')], 'nospace': True},
    'pettype': {'shown': [('tbl', 'name')]},
    'montype': {'shown': [('tbl', 'strsing')]},
    'overlay': {'derived': [('str', 'Filename')]},
    'cellfiles': {'derived': [('str', 'Filename')]},
    'lvltypenames': {'derived': [('row', 'lvltypes', 'File 1', 'str')]},
    'requirementtypes': {'derived': [('fixed', 'REQUIREMENT_TYPE_NAMES')]},
    'npcactiontypes': {'derived': [('fixed', 'NPCACTION_TYPE_NAMES')]},
}


# Cells that look a name up in several tables, first hit wins (monpreset Place: superuniques,
# monstats, monplace; property / cube mod params: skills, montype, states): a synthesized name
# must not also be the name of a row in an earlier table of its group.
NAME_GROUPS = (('superuniques', 'monstats', 'monplace'), ('skills', 'montype', 'states'))


class _Used(str):
    """A name made from the rows that use this one ('Thundergod: aura'); always written with the
    row's placeholder, 'Thundergod: aura (sk1234)', so it stays unique and says it is derived."""
    __slots__ = ()


# Last resort for rows with no shown, vanilla or derived name: the rows that USE them, as
# '<user>: <role>' (Context.used_name).  Sources, first hit wins:
#   ('ref', table, cols, role)  a row of table links here through one of cols (first col first)
#   ('calc', )                  a formula names this row: skill('x'.blvl), stat('x'.accr) ...
#   ('via', col, table, role)   this row's own link column -> that row's name
#   ('uses', )                  this row's own formulas name another row
#   ('str', col, word)          a stored code: 'monster fa'
#   ('sigma_req', ) / ('sigma_act', )  the D2Sigma requirements / npcactions record as text
_SUMSK = tuple('sumskill%d' % i for i in range(1, 6))
_SUBMIS = ('SubMissile1', 'SubMissile2', 'SubMissile3', 'HitSubMissile1', 'HitSubMissile2',
           'HitSubMissile3', 'HitSubMissile4', 'ExplosionMissile', 'CltSubMissile1',
           'CltSubMissile2', 'CltSubMissile3', 'CltHitSubMissile1', 'CltHitSubMissile2',
           'CltHitSubMissile3', 'CltHitSubMissile4')
_SKMIS = ('srvmissile', 'srvmissilea', 'srvmissileb', 'srvmissilec', 'cltmissile', 'cltmissilea',
          'cltmissileb', 'cltmissilec', 'cltmissiled')
_MONMIS = ('MissA1', 'MissA2', 'MissS1', 'MissS2', 'MissS3', 'MissS4', 'MissC', 'MissSQ')
_ITEMST = ('state', 'cstate1', 'cstate2')
USED_SOURCES = {
    'skills': [('ref', 'skills', _SUMSK, 'summon'), ('ref', 'states', ('skill',), 'state'),
               ('ref', 'charstats', ('StartSkill',) + tuple('Skill %d' % i for i in range(1, 11)),
                'class skill'),
               ('ref', 'hireling', tuple('skill%d' % i for i in range(1, 7)), 'hireling'),
               ('ref', 'monstats', _MON_SKILLS + ('SkillDamage',), 'monster skill'),
               ('ref', 'monstats2', ('ResurrectSkill',), 'resurrect'),
               ('ref', 'missiles', ('Skill',), 'missile'),
               ('ref', 'books', ('scrollskill', 'bookskill'), 'book'),
               ('calc',), ('uses',),
               ('ref', 'skills', ('reqskill1', 'reqskill2', 'reqskill3'), 'prereq of'),
               ('via', 'summon', 'monstats', 'summon'),
               ('via', 'aurastate', 'states', 'aura'), ('via', 'passivestate', 'states', 'passive'),
               ('via', 'aurastat1', 'itemstatcost', 'aura'),
               ('via', 'passivestat1', 'itemstatcost', 'passive'),
               ('via', 'srvmissilea', 'missiles', 'missile'),
               ('via', 'srvmissile', 'missiles', 'missile'),
               ('via', 'cltmissile', 'missiles', 'missile'),
               ('via', 'auratargetstate', 'states', 'aura')],
    'states': [('ref', 'skills', ('aurastate',), 'aura'),
               ('ref', 'skills', ('passivestate',), 'passive'),
               ('ref', 'skills', ('auratargetstate',), 'aura target'),
               ('ref', 'skills', ('state1', 'state2', 'state3'), 'state'),
               ('ref', 'weapons', _ITEMST, 'item'), ('ref', 'armor', _ITEMST, 'item'),
               ('ref', 'misc', _ITEMST, 'item'), ('calc',),
               ('via', 'skill', 'skills', 'state'), ('via', 'stat', 'itemstatcost', 'state'),
               ('via', 'missile', 'missiles', 'state')],
    'missiles': [('ref', 'skills', _SKMIS, 'missile'), ('ref', 'missiles', _SUBMIS, 'sub'),
                 ('ref', 'monstats', _MONMIS, 'missile'),
                 ('ref', 'skilldesc', ('descmissile1', 'descmissile2', 'descmissile3'), 'tooltip'),
                 ('ref', 'states', ('missile',), 'state'),
                 ('ref', 'monstats3', ('BossEventMissile1', 'BossEventMissile2'), 'boss event'),
                 ('calc',), ('via', 'Skill', 'skills', 'missile')],
    'itemstatcost': [('ref', 'skills', tuple('aurastat%d' % i for i in range(1, 7)), 'aura'),
                     ('ref', 'skills', tuple('passivestat%d' % i for i in range(1, 6)), 'passive'),
                     ('ref', 'states', ('stat',), 'state'),
                     ('ref', 'properties', tuple('stat%d' % i for i in range(1, 8)), 'property'),
                     ('ref', 'itemstatcost', ('op stat1', 'op stat2', 'op stat3', 'maxstat'),
                      'op'),
                     ('calc',)],
    'properties': [('via', 'stat1', 'itemstatcost', 'property')],
    'monstats': [('ref', 'skills', ('summon',), 'summon'),
                 ('ref', 'monstats', ('minion1', 'minion2'), 'minion'),
                 ('ref', 'monstats', ('BaseId',), 'base'), ('str', 'Code', 'monster')],
    'monstats2': [('ref', 'monstats', ('MonStatsEx',), 'gfx')],
    'monprop': [('ref', 'monstats', ('MonProp',), 'props')],
    'requirementnames': [('sigma_req',)],
    'npcactionnames': [('sigma_act',)],
}
# formulas scanned for USED_SOURCES 'calc' / 'uses'
CALC_USERS = ('skills', 'skills2', 'skilldesc', 'missiles', 'weapons', 'armor', 'misc')
# D2Sigma requirement types (FUN_100a10f0 'D2Requirements.cpp' switch + its handler tables)
REQUIREMENT_TYPE_NAMES = {
    0: 'Empty', 1: 'Any of', 2: 'All of', 3: 'None of', 4: 'Stat equals', 5: 'Stat above',
    6: 'Stat at least', 7: 'Stat below', 8: 'Stat at most', 9: 'Quest flag set',
    10: 'Quest flag unset', 11: 'Skill lvl equals', 12: 'Skill lvl above',
    13: 'Skill lvl at least', 14: 'Skill lvl below', 15: 'Skill lvl at most',
    16: 'Base skill equals', 17: 'Base skill above', 18: 'Base skill at least',
    19: 'Base skill below', 20: 'Base skill at most', 21: 'Lacks skill', 22: 'Act is',
    23: 'Act is not', 24: 'Difficulty is', 25: 'Difficulty is not', 26: 'Not hardcore',
    27: 'Is hardcore', 28: 'In town', 29: 'Not in town', 30: 'Class is', 31: 'Class is not',
    32: 'Has state', 33: 'Not in state', 34: 'Item count at least', 35: 'Lacks item',
    36: 'Always false', 37: 'Always true'}
# D2Sigma npc action types (the D2NpcActions.cpp handlers by type)
NPCACTION_TYPE_NAMES = {
    0: 'Empty', 1: 'Compound', 3: 'Show text page', 4: 'Set quest bits', 5: 'Clear quest bits', 6: 'Add stat',
    7: 'Remove stat', 8: 'Travel to town', 9: 'Toggle UI state', 10: 'Set UI tab',
    15: 'Activate town waypoint', 16: 'Continue', 17: 'Create item', 20: 'System message',
    21: 'Exchange'}


def _calc_role(table, col):
    """Role of a formula column in a used name."""
    c = col.lower()
    if table == 'skilldesc':
        return 'tooltip'
    if table == 'missiles':
        return 'missile calc'
    if table in ITEM_TABLES:
        return 'item calc'
    for pre, role in (('aura', 'aura calc'), ('passive', 'passive calc'), ('sum', 'summon calc'),
                      ('pet', 'summon calc'), ('edmg', 'damage calc'), ('dmg', 'damage calc')):
        if c.startswith(pre):
            return role
    return 'calc'


def _row_role(table, row, col):
    """What a row is, for '<the row its formulas name>: <role>'."""
    if table == 'skills':
        if _get(row, 'aura'):
            return 'aura'
        none = (None,) + tuple(NONE_VAL.values())
        if _get(row, 'passive') or _get(row, 'passivestate') not in none:
            return 'passive'
        if any(_get(row, c) not in none for c in _SKMIS):
            return 'missile'
        return 'proc'
    return 'helper'


def clean_name(t):
    """A .tbl text / file name -> a key that every reader of the txt can take back: the last
    line, colour codes and printf codes removed, ASCII, no tab/'"'/comma/'=' (they split cube
    cells), not a placeholder, '-1' or a number.  An apostrophe stays (formulas then name that
    row by number, see calc.render)."""
    if not t:
        return None
    import unicodedata
    t = pretty(t).replace('\\n', '\n').split('\n')[-1]
    t = re.sub('\u00ffc.', '', t)
    t = re.sub(r'%[+\-]?\d*[dsiu%]', ' ', t)
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    t = re.sub(r'[\t\r\n",=]', '', t)
    t = re.sub(r'\s+', ' ', t).strip(' +-:.;')
    if not t or re.match(r'^[a-z]{2}\d+$', t) or re.match(r'^-?\d+$', t) or t == NOT_FOUND:
        return None
    return t


def placeholder(table, row):
    return '%s%d' % (PREFIX.get(table, table[:2]), row)


def records(data):
    """(count, record_size) of a .bin, or (count, None) if it does not divide."""
    if len(data) < 4:
        return 0, None
    n = struct.unpack_from('<I', data, 0)[0]
    if n == 0:
        return 0, None
    if (len(data) - 4) % n:
        return n, None
    return n, (len(data) - 4) // n


def detect(data, table, prefer=None):
    """Pick a layout version for this .bin (None if nothing fits)."""
    _n, rs = records(data)
    if rs is None:
        return None
    cands = layouts.candidates(table, rs)
    if prefer and prefer in cands:
        return prefer
    return cands[0] if cands else None


# ------------------------------------------------------------------- context

class Context:
    """Everything a conversion may need from outside the .bin itself.

    bin_dir    directory holding the other .bin files (for link resolution, calc code)
    bins       optional dict table -> bytes (overrides bin_dir)
    strings    StringSet (or a dir with string/patchstring/expansionstring .tbl)
    version    preferred layout version ('auto' = detect per table)
    txt_dir    optional dir with .txt files used for keys not stored in bins (sounds.txt)
    """

    def __init__(self, bin_dir=None, bins=None, strings=None, version='auto', txt_dir=None,
                 zero_blank=True, ingame_names=False, raw_links=False, vanilla_names=True,
                 names='auto'):
        self.zero_blank = zero_blank      # write numeric 0 as an empty cell (txt style)
        # names: how rows whose key is not stored are named (see NAME_SOURCES, row_name):
        #   'ingame'  the name the player sees, else the vanilla key, else a derived name
        #   'vanilla' the vanilla key, else the name the player sees, else a derived name
        #   'auto'    'ingame' for Median (mxl layouts); vanilla keys only for other versions
        # ingame_names=True is names='ingame'.
        self.names = 'ingame' if ingame_names else names
        self._firstrow = {}
        self._refcache = {}
        self.bin_dir = bin_dir
        self.bins = dict(bins or {})
        self.version = version
        self.txt_dir = txt_dir or bin_dir
        if isinstance(strings, str):
            strings = load_strings(strings)
        self.strings = strings
        self._raw = {}
        self._txtcols = {}
        self._items = None
        self._tcauto = None
        self._dirver = None
        # raw_links: write every link / name key as its placeholder (prefix + row index, e.g.
        # pr116) instead of a resolved name.  vanilla_names: name keys that are not stored in the
        # bin (Fog types 17/18) borrow the vanilla name of the same row when the row's
        # fingerprint columns still match vanilla (data/vanilla_keys.json).
        self.raw_links = raw_links
        self.vanilla_names = vanilla_names and not raw_links
        self._rownames = {}
        self.code_names = None        # None: d2bt/data/row_names_code.json; {} disables those names

    # -- raw access
    def bin(self, table):
        table = table.lower()
        if table in self.bins:
            return self.bins[table]
        if self.bin_dir:
            p = os.path.join(self.bin_dir, table + '.bin')
            if os.path.exists(p):
                with open(p, 'rb') as fh:
                    self.bins[table] = fh.read()
                return self.bins[table]
        return None

    def dir_version(self):
        """Best layout version for the whole bin_dir (most tables whose size fits)."""
        if self._dirver is None:
            self._dirver = ''
            if self.bin_dir and os.path.isdir(self.bin_dir):
                sizes = {}
                for fn in os.listdir(self.bin_dir):
                    if fn.lower().endswith('.bin'):
                        with open(os.path.join(self.bin_dir, fn), 'rb') as fh:
                            sizes[fn[:-4].lower()] = records(fh.read())[1]
                best = (0, '')
                for v in layouts.versions():
                    n = sum(1 for t, rs in sizes.items()
                            if rs and (layouts.load(v, t) or {}).get('record_size') == rs)
                    if n > best[0]:
                        best = (n, v)
                self._dirver = best[1]
        return self._dirver or None

    def layout_for(self, table, data):
        v = None if self.version in (None, 'auto') else self.version
        if v is None:
            v = self.dir_version()
        if v:
            lay = layouts.load(v, table)
            n, rs = records(data)
            if lay and lay.get('record_size') == rs:
                return lay
        v = detect(data, table, prefer=v)
        return layouts.load(v, table) if v else None

    def raw_rows(self, table):
        """Decoded rows with raw (unresolved) values, or None."""
        table = table.lower()
        if table in self._raw:
            return self._raw[table]
        self._raw[table] = None
        data = self.bin(table)
        if data is not None:
            lay = self.layout_for(table, data)
            if lay:
                self._raw[table] = _decode_raw(data, lay)
        return self._raw[table]

    def txt_column(self, table, col):
        key = (table, col)
        if key in self._txtcols:
            return self._txtcols[key]
        self._txtcols[key] = None
        if self.txt_dir:
            p = os.path.join(self.txt_dir, table + '.txt')
            if os.path.exists(p):
                with open(p, encoding='latin-1') as fh:
                    lines = fh.read().split('\n')
                if lines and lines[-1].strip('\r') == '':
                    lines.pop()
                hdr = [h.lower() for h in lines[0].rstrip('\r').split('\t')]
                if col.lower() in hdr:
                    i = hdr.index(col.lower())
                    vals = []
                    for ln in lines[1:]:
                        c = ln.rstrip('\r').split('\t')
                        if c[0] == 'Expansion':
                            continue       # Fog drops these rows (case-sensitive first cell)
                        vals.append(c[i] if i < len(c) else '')
                    self._txtcols[key] = vals
        return self._txtcols[key]

    # -- resolution
    def key(self, table, col, row):
        """Key text of `row` in `table` (column col), or a placeholder."""
        if row is None:
            return ''
        table = table.lower()
        if row == 0 and table in NONE_ROW0:
            return ''
        if table in ITEM_TABLES:
            return self.item_code(row)
        if table == 'treasureclassex':
            return self.tc_name(row)
        lay = self.raw_layout(table)
        kf = next((f for f in (lay or {}).get('fields', []) if f['name'].lower() == col.lower()),
                  None)
        if self.raw_links and kf is not None and kf['ftype'] in NAMEKEY_TYPES:
            return placeholder(table, row)
        if kf is not None and kf['ftype'] in NAMEKEY_TYPES:
            # name keys store the linker index; repeated names share one (monseq)
            names = self.name_list(table, col)
            if names is not None and 0 <= row < len(names):
                return names[row]
            if names is None:
                return self.row_name(table, kf, row)
        rows = self.raw_rows(table)
        if rows is not None and 0 <= row < len(rows):
            v = _get(rows[row], col)
            if v is None and table in MODE_CODES and row < len(MODE_CODES[table]):
                return MODE_CODES[table][row]
            if v is None:
                v = _first_key(rows[row], self.raw_layout(table))
            if isinstance(v, str):
                return v
        vals = self.txt_column(table, col)
        if vals is not None and 0 <= row < len(vals):
            return vals[row]
        return placeholder(table, row)

    def row_name(self, table, kf, idx):
        """Key text of linker index idx of a name-key column whose names are not in the bin
        (and no txt is beside it): the vanilla name when the row still matches vanilla and the
        name is unique in the table, else the placeholder.  The key column itself is written with
        the same function, so every name stays resolvable back to its index."""
        lst = self._rownames.get(table)
        if lst is None:
            lst = self._rownames[table] = self._build_row_names(table, kf)
        if 0 <= idx < len(lst) and lst[idx]:
            return lst[idx]
        return placeholder(table, idx)

    def _build_row_names(self, table, kf):
        rows = self.raw_rows(table) or []
        first = {}
        for r, row in enumerate(rows):
            v = row.get(kf['name']) if kf['ftype'] in NAMEKEY_TYPES else r
            if isinstance(v, int) and v not in first:
                first[v] = r
        out = [None] * (max(first) + 1 if first else 0)
        if self.raw_links:
            return out
        # a D2Sigma *names table is compiled from its base txt's name column: use it when the
        # base .bin stores that column (infographics.name)
        base = EXT_BASE.get(table)
        brows = self.raw_rows(base) if base else None
        if brows and len(brows) == len(rows):
            vals = [_get(r, kf['name']) for r in brows]
            if all(isinstance(v, str) for v in vals) and \
                    len({v[:31].lower() for v in vals}) == len(vals):
                return [vals[r] or None for r in range(len(vals))]
        vanilla = self._vanilla_row_names(table, rows, first)
        style = self.name_style(table)
        shown = derived = {}
        if style == 'ingame' or self.names != 'auto':
            shown = {i: self.shown_name(table, i) for i in first}
            derived = {i: self.derived_name(table, i) for i in first}
        # pick: ingame  = the name the player sees > vanilla key > derived > placeholder
        #       vanilla = vanilla key > the name the player sees > derived > placeholder
        pick = {}
        self.__dict__.setdefault('_vancache', {})[table] = vanilla
        for i in first:
            order = ((shown, vanilla, derived) if style == 'ingame'
                     else (vanilla, shown, derived))
            for src in order:
                nm = src.get(i)
                if nm:
                    pick[i] = (nm, src is vanilla)
                    break
        if style == 'ingame' or self.names != 'auto':
            # last resort: the rows that use this one ('Thundergod: aura (sk1234)')
            for i in first:
                if i not in pick:
                    nm = self.used_name(table, i)
                    if nm:
                        pick[i] = (nm, False)
            # after that: what the game's code does with the row id ('Suck Blood (sk229)'), only for the .bin the
            # names were mined from
            cn = self.code_names if self.code_names is not None else _code_names()
            want = (cn.get('bins') or {}).get(table)
            if want and (cn.get('names') or {}).get(table):
                import hashlib
                ok = hashlib.sha1(self.bin(table) or b'').hexdigest() == want
            else:
                ok = False
            if ok:
                for i, e in (cn.get('names') or {}).get(table, {}).items():
                    nm = clean_name(e.get('name') or '') if int(i) in first else None
                    if nm and int(i) not in pick:
                        pick[int(i)] = (_Used(nm), False)
        if table in NONE_ROW0:
            pick.pop(0, None)     # row 0 is the 'none' row, written ''
        # unique on what the game's name linker compares (31 chars, case-folded): the vanilla
        # keys are unique already; a synthesized name shared by several rows (or equal to a
        # vanilla key) gets the row's placeholder appended, 'Iron Golem (sk132)'
        fold = lambda n: n.encode('latin-1', 'replace')[:31].lower()
        nospace = NAME_SOURCES.get(table, {}).get('nospace')
        if nospace:
            pick = {i: (nm.replace(' ', '') if not van else nm, van)
                    for i, (nm, van) in pick.items()}
        taken = set()            # names of the tables looked up before this one
        for grp in NAME_GROUPS:
            if table in grp:
                for t in grp[:grp.index(table)]:
                    taken |= {fold(n) for n in self._all_names(t)}
        cnt = {}
        for nm, van in pick.values():
            cnt[fold(nm)] = cnt.get(fold(nm), 0) + 1
        used = set()
        for i in sorted(pick):
            nm, van = pick[i]
            if isinstance(nm, _Used):
                suf = ('(%s)' if nospace else ' (%s)') % placeholder(table, i)
                head, sep, role = nm.rpartition(': ')
                if not sep:
                    head, role = role, ''
                tail = (sep + role) + suf
                if len(tail) > 24:            # keep the user readable; cut a long role
                    tail = suf
                    head = nm
                nm = head[:31 - len(tail)].rstrip(' :') + tail
            elif not van and (cnt[fold(nm)] > 1 or fold(nm) in taken):
                suf = ('(%s)' if nospace else ' (%s)') % placeholder(table, i)
                full = nm + suf
                # the linker compares 31 chars: keep the suffix inside them only when needed
                nm = full if fold(full) not in used and fold(full) not in taken and \
                    fold(full) not in cnt else nm[:31 - len(suf)].rstrip() + suf
            if fold(nm) in used:
                continue          # cannot happen; never give two rows one name
            used.add(fold(nm))
            out[i] = nm
        return out

    def _all_names(self, table):
        """Every key text of a name-key table (as written), for NAME_GROUPS."""
        lay = self.raw_layout(table) or {}
        kf = next((f for f in lay.get('fields', []) if f['ftype'] in NAMEKEY_TYPES), None)
        if kf is None:
            rows = self.raw_rows(table) or []
            return [v for v in (_first_key(r, lay) for r in rows) if isinstance(v, str) and v]
        lst = self.name_list(table, kf['name'])
        if lst is not None:
            return lst
        n = len(self._rownames.get(table) or []) or len(self.raw_rows(table) or [])
        return [self.row_name(table, kf, i) for i in range(n)]

    def _vanilla_row_names(self, table, rows, first):
        """{linker index: vanilla key} for rows whose fingerprint columns still match vanilla
        and whose vanilla name is unique in the table."""
        van = _vanilla_keys().get(table) if self.vanilla_names else None
        if not van:
            return {}
        if van.get('rows_from', table) != table:
            rows = self.raw_rows(van['rows_from']) or []
        vfirst = {}
        vnames = []
        for r, nm in enumerate(van['names']):
            k = nm[:31].lower()
            if k not in vfirst:
                vfirst[k] = r
                vnames.append((nm, r))
        res = {}
        used = set()
        fp = van.get('fingerprint') or {}
        for idx, r in sorted(first.items()):
            if idx >= len(vnames) or r >= len(rows):
                continue
            nm, vr = vnames[idx]
            if not nm or re.match(r'^[a-z]{2}\d+$', nm) or nm[:31].lower() in used:
                continue
            tot = eq = 0
            for col, vals in fp.items():
                mv = _get(rows[r], col)
                if isinstance(mv, int) and vr < len(vals):
                    tot += 1
                    eq += (mv == vals[vr])
            if tot and eq * 4 < tot * 3:
                continue
            res[idx] = nm
            used.add(nm[:31].lower())
        return res

    def name_style(self, table):
        """'ingame' or 'vanilla' (see Context names=)."""
        if self.names in ('ingame', 'vanilla'):
            return self.names
        lay = self.raw_layout(table) or {}
        return 'ingame' if lay.get('version') == 'mxl' else 'vanilla'

    # -- synthesized names (no name stored anywhere): see NAME_SOURCES
    def _row_of(self, table, idx):
        """First row of a name-key linker index."""
        m = self._firstrow.get(table)
        if m is None:
            m = self._firstrow[table] = {}
            lay = self.raw_layout(table) or {}
            kf = next((f for f in lay.get('fields', []) if f['ftype'] in NAMEKEY_TYPES), None)
            for r, row in enumerate(self.raw_rows(table) or []):
                v = row.get(kf['name']) if kf else r
                if isinstance(v, int) and v not in m:
                    m[v] = r
        return m.get(idx)

    def _refs(self, table, cols):
        """{target index: first referencing row} for link columns cols of table."""
        key = (table, tuple(cols))
        if key not in self._refcache:
            res = {}
            if cols == ('*skmode',):
                data = self.bin('monstats') or b''
                n, rs = records(data)
                for r in range(n or 0):
                    rec = data[4 + r * rs: 4 + (r + 1) * rs]
                    for k in range(8):
                        if len(rec) < 0x198:
                            break
                        if struct.unpack_from('<h', rec, 0x170 + 2 * k)[0] < 0:
                            continue
                        seq = struct.unpack_from('<h', rec, 0x188 + 2 * k)[0]
                        if seq >= 0:
                            res.setdefault(seq, r)
            else:
                for r, row in enumerate(self.raw_rows(table) or []):
                    for c in cols:
                        v = _get(row, c)
                        if isinstance(v, int) and v not in NONE_VAL.values():
                            res.setdefault(v, r)
            self._refcache[key] = res
        return self._refcache[key]

    def _source_name(self, table, idx, src, depth):
        r = self._row_of(table, idx)
        rows = self.raw_rows(table) or []
        if r is None or r >= len(rows):
            return None
        kind = src[0]
        if kind == 'fixed':        # engine ids with a fixed meaning (D2Sigma type switches)
            return globals()[src[1]].get(idx)
        if kind == 'tbl':
            sid = _get(rows[r], src[1])
            if isinstance(sid, int) and sid not in (0, 0xFFFF, 5382) and self.strings:
                return clean_name(self.strings.text(sid))
            return None
        if kind == 'str':
            v = _get(rows[r], src[1])
            if isinstance(v, str) and v.strip() and v.strip().lower() not in ('null', 'none'):
                return clean_name(re.split(r'[\\/]', v.strip())[-1].rsplit('.', 1)[0])
            return None
        if kind == 'via':          # own link column -> that row's shown name
            v = _get(rows[r], src[1])
            if isinstance(v, int) and v not in NONE_VAL.values():
                return (self.shown_name(src[2], v, depth + 1) or
                        self.derived_name(src[2], v, depth + 1))
            return None
        if kind == 'row':
            orow = (self.raw_rows(src[1]) or [])
            v = _get(orow[r], src[2]) if r < len(orow) else None
            if src[3] == 'tbl':
                return clean_name(self.strings.text(v)) if isinstance(v, int) and \
                    self.strings and v not in (0, 0xFFFF, 5382) else None
            if isinstance(v, str) and v.strip():
                return clean_name(re.split(r'[\\/]', v.strip())[-1].rsplit('.', 1)[0])
            return None
        if kind == 'ref':          # a row of another table that links here -> its name
            hit = self._refs(src[1], src[2]).get(idx)
            if hit is None:
                return None
            other = self.raw_layout(src[1]) or {}
            okf = next((f for f in other.get('fields', []) if f['ftype'] in NAMEKEY_TYPES),
                       None)
            oidx = _get((self.raw_rows(src[1]) or [])[hit], okf['name']) if okf else hit
            if not isinstance(oidx, int):
                return None
            return (self.shown_name(src[1], oidx, depth + 1) or
                    (self.derived_name(src[1], oidx, depth + 1) if src[1] != table else None))
        return None

    # -- names from how a row is used (USED_SOURCES): 'Thundergod: aura (sk1234)'
    def _calc_refs(self):
        """{(target table, index): [(table, row, column)]} of every formula that names a row
        (skill('x'.blvl), stat('x'.accr), miss('x'.range) ...) and the same per formula row:
        {(table, row): [(target table, index, column)]}."""
        if getattr(self, '_crefs', None) is not None:
            return self._crefs
        by_target, by_row = {}, {}
        fn_table = {'skill': 'skills', 'sklvl': 'skills', 'stat': 'itemstatcost',
                    'miss': 'missiles', 'state': 'states'}
        for t in CALC_USERS:
            lay = self.raw_layout(t) or {}
            cols = [(f['name'], f['link'][5:]) for f in lay.get('fields', [])
                    if f['ftype'] == 25 and str(f.get('link') or '').startswith('calc:')]
            for r, row in enumerate(self.raw_rows(t) or [] if cols else []):
                for col, ct in cols:
                    off = row.get(col)
                    blob = self.bin(ct)
                    if not isinstance(off, int) or off == 0xFFFFFFFF or not blob or \
                            off >= len(blob):
                        continue
                    try:
                        node, _end = calc.parse(blob, off, ct)
                    except Exception:     # noqa: BLE001  (a malformed formula names nothing)
                        continue
                    stack = [node] if node is not None else []
                    while stack:
                        n = stack.pop()
                        stack.extend(n.kids)
                        tt = fn_table.get(n.val) if n.kind == 'fn' else None
                        if tt and n.kids and n.kids[0].kind == 'const':
                            k = n.kids[0].val
                            bt = EXT_BASE.get(t, t)       # skills2 row r = skills row r
                            by_target.setdefault((tt, k), []).append((bt, r, col))
                            by_row.setdefault((bt, r), []).append((tt, k, col))
        self._crefs = (by_target, by_row)
        return self._crefs

    def _user_name(self, table, r, depth):
        """Readable name of raw row r of table (a row that uses another), or None."""
        lay = self.raw_layout(table) or {}
        rows = self.raw_rows(table) or []
        if r >= len(rows):
            return None
        kf = next((f for f in lay.get('fields', []) if f['ftype'] in NAMEKEY_TYPES), None)
        if kf is None:
            v = _first_key(rows[r], lay)
            return clean_name(v) if isinstance(v, str) else None
        idx = _get(rows[r], kf['name'])
        if not isinstance(idx, int):
            return None
        return self.any_name(table, idx, depth + 1)

    def any_name(self, table, idx, depth=0):
        """shown > vanilla key > derived > used name of a name-key row, head part only
        ('Thundergod' of 'Thundergod: aura'), or None."""
        nm = self.shown_name(table, idx, min(depth, 3))
        if not nm:
            van = getattr(self, '_vancache', {}).get(table)
            nm = van.get(idx) if van else None
        nm = nm or self.derived_name(table, idx, min(depth, 3)) or self.used_name(table, idx,
                                                                                   depth)
        if nm and isinstance(nm, _Used):
            nm = nm.split(': ')[0]
        return nm or None

    def used_name(self, table, idx, depth=0):
        """'<user>: <role>' from the rows that use this one (USED_SOURCES), or None."""
        key = (table, idx)
        memo = self.__dict__.setdefault('_usedmemo', {})
        if key in memo:
            return memo[key]
        busy = self.__dict__.setdefault('_usedbusy', set())
        if depth > 5 or key in busy or self.raw_links:
            return None
        busy.add(key)
        try:
            nm = None
            for src in USED_SOURCES.get(table, ()):
                nm = self._used_source(table, idx, src, depth)
                if nm:
                    nm = clean_name(nm)
                if nm:
                    break
        finally:
            busy.discard(key)
        res = _Used(nm) if nm else None
        if depth == 0 or res:
            memo[key] = res
        return res

    def _used_source(self, table, idx, src, depth):
        kind = src[0]
        r = self._row_of(table, idx)
        rows = self.raw_rows(table) or []
        if kind == 'ref':            # ('ref', table, cols, role): a row of table links here
            for c in src[2]:
                hit = self._refs(src[1], (c,)).get(idx)
                if hit is not None and not (src[1] == table and hit == r):
                    nm = self._user_name(src[1], hit, depth)
                    if nm:
                        return '%s: %s' % (nm, src[3])
            return None
        if kind == 'calc':           # ('calc', role by column prefix): a formula names this row
            for t, rr, col in self._calc_refs()[0].get((table, idx), ()):
                if t == table and rr == r:
                    continue
                nm = self._user_name(t, rr, depth)
                if nm:
                    return '%s: %s' % (nm, _calc_role(t, col))
            return None
        if r is None or r >= len(rows):
            return None
        if kind == 'via':            # ('via', col, table, role): this row's own link
            v = _get(rows[r], src[1])
            if isinstance(v, int) and v not in NONE_VAL.values() and \
                    not (src[2] == table and v == idx):
                nm = self.any_name(src[2], v, depth + 1)
                if nm:
                    return '%s: %s' % (nm, src[3])
            return None
        if kind == 'uses':           # ('uses',): this row's own formulas name another row
            for tt, k, col in self._calc_refs()[1].get((table, r), ()):
                if tt == table and k == idx:
                    continue
                nm = self.any_name(tt, k, depth + 1)
                if nm:
                    return '%s: %s' % (nm, _row_role(table, rows[r], col))
            return None
        if kind == 'str':            # ('str', col, role): a stored code of the row
            v = _get(rows[r], src[1])
            if isinstance(v, str) and v.strip():
                return '%s %s' % (src[2], v.strip())
            return None
        if kind in ('sigma_req', 'sigma_act'):
            return self._sigma_row_name(kind, r)
        return None

    def _sigma_row_name(self, kind, r):
        """requirementnames / npcactionnames row r: its requirements / npcactions record as
        text ('Class is ama', 'Create item rvs')."""
        req = kind == 'sigma_req'
        data = self.bin('requirements' if req else 'npcactions') or b''
        n, rs = records(data)
        if rs is None or r >= n:
            return None
        rec = data[4 + r * rs: 4 + (r + 1) * rs]
        typ = struct.unpack_from('<i', rec, 0)[0]
        names = REQUIREMENT_TYPE_NAMES if req else NPCACTION_TYPE_NAMES
        tn = names.get(typ)
        if tn is None:
            return None
        spec = REQUIREMENT_PARAMS if req else NPCACTION_PARAMS
        first = 4 if req else 0xc
        parts = []
        for off in range(first, rs, 4):
            kd = sigma_param_kind(spec, typ, off)
            if isinstance(kd, tuple) and kd[0] == 'link' and kd[1].endswith('names'):
                parts = ['%d' % sum(1 for o in range(first, rs, 4)
                                    if struct.unpack_from('<i', rec, o)[0] not in (0, -1))]
                break
            try:
                v = _sigma_param(spec, rec, off, self)
            except Exception:     # noqa: BLE001
                v = ''
            if v:
                parts.append(v)
            if len(parts) >= 2:
                break
        return ' '.join([tn] + parts)

    def shown_name(self, table, idx, depth=0):
        """The name the player sees for this row (its own .tbl string, or the string of the row
        it is displayed through), cleaned; None if there is none."""
        if depth > 3:
            return None
        for src in NAME_SOURCES.get(table, {}).get('shown', ()):
            nm = self._source_name(table, idx, src, depth)
            if nm:
                return nm
        return None

    def derived_name(self, table, idx, depth=0):
        """A readable name built from what the row does carry (a file name, the row that uses
        it), for rows the player never sees named."""
        if depth > 3:
            return None
        for src in NAME_SOURCES.get(table, {}).get('derived', ()):
            nm = self._source_name(table, idx, src, depth)
            if nm:
                return nm
        return None

    def name_list(self, table, col):
        """Distinct names of a name-key column in linker order (case-folded, first wins)."""
        vals = self.txt_column(table, col)
        if vals is None:
            return None
        seen = set()
        out = []
        for v in vals:
            k = v[:31].lower()
            if k not in seen:
                seen.add(k)
                out.append(v)
        return out

    def raw_layout(self, table):
        data = self.bin(table)
        return self.layout_for(table, data) if data is not None else None

    def tc_name(self, idx):
        """Treasure class index -> name.  Index 0 is 'none', then 32 auto classes
        (code3..code96) per item type flagged TreasureClass, then treasureclassex rows."""
        if idx == 0:
            return ''
        if self._tcauto is None:
            self._tcauto = []
            # highest auto class level: 96 from 1.10 on (D2MOO, Median data); 90 in 1.09d and
            # 132 in 1.07; 1.08 like 1.09d (all measured on the vanilla bins+txt)
            lay = self.raw_layout('treasureclassex') or {}
            top = TC_AUTO_TOP.get(lay.get('version'), 96)
            for r in self.raw_rows('itemtypes') or []:
                if _get(r, 'TreasureClass'):
                    code = _get(r, 'Code') or ''
                    self._tcauto += ['%s%d' % (code, lv) for lv in range(3, top + 1, 3)]
        i = idx - 1
        if i < len(self._tcauto):
            return self._tcauto[i]
        i -= len(self._tcauto)
        rows = self.raw_rows('treasureclassex')
        if rows is not None and 0 <= i < len(rows):
            v = _get(rows[i], 'Treasure Class')
            if isinstance(v, str):
                return v
        return placeholder('treasureclassex', i)

    def tbl_key(self, sid):
        if sid == 5382:
            return ''      # an empty (or unknown) string key compiles to index 5382 ('dummy')
        if self.strings:
            k = self.strings.key(sid)
            if k is not None:
                return pretty(k)
        return "#%d" % sid      # no string table: txt2bin reads #N back as the index

    def item_code(self, idx):
        if self._items is None:
            self._items = []
            for t in ITEM_TABLES:
                rows = self.raw_rows(t) or []
                self._items += [_get(r, 'code') or '' for r in rows]
        if 0 <= idx < len(self._items):
            return self._items[idx]
        return 'it%d' % idx

    def calc_names(self, code_table):
        pt = calc.PARAM_TABLE.get(code_table)

        def codes(t):
            rows = self.raw_rows(t) if t else None
            return [r.get('code', '') for r in rows] if rows else []
        pc = codes(pt)
        sc = codes('skillcalc')
        mc = codes('misscalc')
        get = lambda lst, i: lst[i] if lst and 0 <= i < len(lst) and lst[i] else None
        return calc.Names(param=lambda i: get(pc, i),
                          skill=lambda i: self.key('skills', 'skill', i),
                          stat=lambda i: self.key('itemstatcost', 'Stat', i),
                          missile=lambda i: self.key('missiles', 'Missile', i),
                          misscalc=lambda i: get(mc, i),
                          skillcalc=lambda i: get(sc, i))


_VANILLA_KEYS = None


_CODE_NAMES = None


def _code_names():
    """d2bt/data/row_names_code.json (tools/naming/row_names_code.py): names for rows that have no other name,
    taken from what the game's code does with the row id. {'bins': {table: sha1 of its .bin}, 'names': {table:
    {idx: {name, rule, evidence}}}}; a table's names apply only to that exact .bin (the Median build they were
    mined from)."""
    global _CODE_NAMES
    if _CODE_NAMES is None:
        import json
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data',
                         'row_names_code.json')
        try:
            with open(p) as fh:
                _CODE_NAMES = json.load(fh)
        except (OSError, ValueError):
            _CODE_NAMES = {}
    return _CODE_NAMES


def _vanilla_keys():
    global _VANILLA_KEYS
    if _VANILLA_KEYS is None:
        import json
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data',
                         'vanilla_keys.json')
        try:
            with open(p) as fh:
                _VANILLA_KEYS = json.load(fh).get('tables', {})
        except (OSError, ValueError):
            _VANILLA_KEYS = {}
    return _VANILLA_KEYS


def load_strings(path):
    """StringSet from a dir containing the classic .tbl files (any of them)."""
    ss = StringSet()
    if path and os.path.isdir(path):
        for name in ('string', 'patchstring', 'expansionstring'):
            for fn in os.listdir(path):
                if fn.lower() == name + '.tbl':
                    ss.add(name, Tbl.load(os.path.join(path, fn)))
    return ss


# ------------------------------------------------------------------ decoding

def _get(row, col):
    """Case-insensitive column lookup in a raw row dict."""
    if col in row:
        return row[col]
    cl = col.lower()
    for k, v in row.items():
        if k.lower() == cl:
            return v
    return None


def _first_key(row, lay):
    """Fallback key of a row: its first code column, else first text column."""
    if not lay:
        return None
    for want in (CODE_TYPES, STR_TYPES):
        for f in lay['fields']:
            if f['ftype'] in want:
                v = row.get(f['name'])
                if isinstance(v, str):
                    return v
    return None


def _cstr(b):
    i = b.find(b'\0')
    if i >= 0:
        b = b[:i]
    return pretty(b.decode('latin-1'))


def _code(b):
    if b == b'\0\0\0\0':
        return ''
    return _cstr(b).rstrip(' ')


def _field_raw(rec, f):
    """Raw value of one field: str for text/codes, int for numbers, None if n/a."""
    ft = f['ftype']
    off = f['offset']
    if off is None or ft is None:
        return None
    if ft == 26:
        bit = f['bit'] or 0
        o = off + (bit >> 3)
        if o >= len(rec):
            return None
        return (rec[o] >> (bit & 7)) & 1
    if ft in STR_TYPES:
        return _cstr(rec[off:off + (f['size'] or 1)])
    if ft in CODE_TYPES:
        return _code(rec[off:off + 4])
    fmt = INT_FMT.get(ft)
    if fmt is None:
        return None
    sg = f.get('signed')
    if sg is not None and ft not in LINK_TYPES:
        fmt = fmt.lower() if sg else fmt.upper()
    sz = struct.calcsize(fmt)
    if off + sz > len(rec):
        return None
    return struct.unpack_from(fmt, rec, off)[0]


def _decode_raw(data, lay):
    n, rs = records(data)
    out = []
    for i in range(n):
        rec = data[4 + i * rs: 4 + (i + 1) * rs]
        out.append({f['name']: _field_raw(rec, f) for f in lay['fields']})
    return out


def _link_text(ctx, link, val, size):
    if val is None:
        return ''
    if val == NONE_VAL.get(size) or (size == 4 and val >= 0x80000000):
        # -1 = the txt named no row.  Where row 0 of the target has an empty key ('none' rows
        # of sounds/montype/monsounds), '' would compile to 0, so -1 is written as NOT_FOUND:
        # a name no linker holds, which Fog and txt2bin both turn into -1 again.
        if link and '.' in link and not link.startswith('static:'):
            t = link.split('.', 1)[0].lower()
            if (t in NONE_ROW0 or t == 'treasureclassex') and ctx.raw_rows(t) is not None:
                return NOT_FOUND            # TC index 0 is '' as well
        return ''
    if link and link.startswith('static:'):
        lst = link[7:].split(',')
        return lst[val] if 0 <= val < len(lst) else str(val)
    if not link or '.' not in link:
        return str(val)
    t, c = link.split('.', 1)
    return ctx.key(t, c, val)


# ------------------------------------------------------------ custom columns

CUBE_IN_OFF, CUBE_OUT_OFF, CUBE_OUT_LEN = 0x14, 0x4C, 0x54
QUALITY = {1: 'low', 2: 'nor', 3: 'hiq', 4: 'mag', 5: 'set', 6: 'rar', 7: 'uni', 8: 'crf',
           9: 'tmp'}


def _cube_input(rec, i, ctx):
    """Inverse of D2Common DATATBLS_CubeMainInputParser (flags: 1 any/item, 2 itemtype, 4 nos,
    8 sock, 0x10 eth, 0x20 noe, 0x40 unique/set, 0x80 upg, 0x100 bas, 0x200 exc, 0x400 eli,
    0x800 nru)."""
    p = rec[CUBE_IN_OFF + 8 * i: CUBE_IN_OFF + 8 * i + 8]
    if len(p) < 8:
        return ''
    flags, widx, wid, post, qty = struct.unpack('<HHHBB', p)
    special = False
    if flags & 0x40:
        special = post in (5, 7)
        if post == 7:
            base = ctx.key('uniqueitems', 'index', wid - 1)
        elif post == 5:
            base = ctx.key('setitems', 'index', wid - 1)
        else:
            return ''
    elif flags & 1:
        base = 'any' if widx == 0xFFFF else ctx.item_code(widx)
    elif flags & 2:
        base = 'any' if widx == 0xFFFF else ctx.key('itemtypes', 'Code', widx)
    else:
        return ''
    parts = [base]
    if special:
        flags &= ~0x41        # set by the unique/set lookup; modifiers follow as for items
    for bit, nm in ((0x100, 'bas'), (0x200, 'exc'), (0x400, 'eli'), (0x800, 'nru')):
        if flags & bit:
            parts.append(nm)
    if post in QUALITY and not special:
        parts.append(QUALITY[post])
    for bit, nm in ((8, 'sock'), (4, 'nos'), (0x10, 'eth'), (0x20, 'noe'), (0x80, 'upg')):
        if flags & bit:
            parts.append(nm)
    if qty:
        parts.append('qty=%d' % qty)
    return ','.join(parts)


# D2Sigma replaces the output parser (D2Common+0x1c47b call -> FUN_10081d10, D2Linkers.cpp).
# First token: one of these keywords (prefix match, in this order), else an item code / item
# type (<5 chars), else a uniqueitems / setitems name.  type byte (+8) -> keyword; the value
# (u16 at +6, over quality and qty) and its default when the cell gives none:
SIGMA_CUBE_OUT = {1: ('portal', 0), 2: ('skillpts', 1), 3: ('statpts', 1), 4: ('mon', -1),
                  5: ('boss', -1), 6: ('goldcost', 0), 7: ('set_flag_player', -1),
                  8: ('unset_flag_player', -1), 9: ('set_flag_game', -1),
                  10: ('unset_flag_game', -1)}
SIGMA_CUBE_KW = ('portal', 'skillpts', 'statpts', 'mon', 'boss', 'goldcost', 'set_flag_player',
                 'unset_flag_player', 'set_flag_game', 'unset_flag_game', 'useitem', 'usetype')
# modifier keywords in Sigma's match order (prefix match)
SIGMA_CUBE_MODS = ('qty', 'pre', 'suf', 'low', 'nor', 'hiq', 'mag', 'set', 'rar', 'uni', 'crf',
                   'tmp', 'eth', 'sock', 'mod', 'uns', 'rem', 'reg', 'exc', 'eli', 'rep', 'rch')


def _is_mxl(ctx, table):
    lay = ctx.raw_layout(table) if ctx is not None else None
    return bool(lay) and lay.get('version') == 'mxl'


def _sigma_cube_output(rec, o, i, ctx):
    """Inverse of D2Sigma FUN_10081d10.  Every handler that reads a '=value' calls strtok
    (shared state) on its own token, so in the game nothing after the first valued token is
    parsed: such a token is always written last."""
    p = rec[o:o + 0x18]
    flags, widx, wid, post, qty, btype = struct.unpack_from('<HHHBBB', p)
    val = struct.unpack_from('<h', p, 6)[0]
    pre = list(struct.unpack_from('<3H', p, 12))
    suf = list(struct.unpack_from('<3H', p, 18))
    if btype in SIGMA_CUBE_OUT:
        kw, _dflt = SIGMA_CUBE_OUT[btype]
        if kw == 'mon' and val >= 0:
            v = ctx.key('monstats', 'Id', val)
        elif kw == 'boss' and val >= 0:
            v = ctx.key('superuniques', 'Superunique', val)
        else:
            v = str(val)
        if re.match(r'^[a-z]{2}\d+$', v) or ',' in v or '=' in v or not v:
            v = str(val)       # a placeholder is not a name the game knows: write the row
        return '%s=%s' % (kw, v)
    special = False
    if flags & 0x08 and btype == 0xFC and post in (5, 7):
        special = True
        base = ctx.key('uniqueitems' if post == 7 else 'setitems', 'index', wid - 1)
        flags &= ~0x08
    elif btype == 0xFF:
        base = 'usetype'
    elif btype == 0xFE:
        base = 'useitem'
    elif btype == 0xFD:
        base = ctx.key('itemtypes', 'Code', widx)
    elif btype == 0xFC:
        base = ctx.item_code(widx)
    else:
        base = ''
    if not base:
        return 'void' if i == 0 else ''
    parts = [base]
    if flags & 0x40 and btype == 0xFF:
        parts.append('reg')
        flags &= ~0x40
    for bit, nm in ((0x04, 'eth'), (0x01, 'mod'), (0x10, 'uns'), (0x20, 'rem'), (0x80, 'exc'),
                    (0x100, 'eli'), (0x200, 'rep'), (0x400, 'rch')):
        if flags & bit:
            parts.append(nm)
    if post in QUALITY and not special:
        parts.append(QUALITY[post])
    while pre and not pre[-1]:
        pre.pop()
    while suf and not suf[-1]:
        suf.pop()
    vals = ['pre=%d' % v for v in pre] + ['suf=%d' % v for v in suf]
    if flags & 2:
        vals.append('sock=%d' % qty)
    elif qty:
        vals.append('qty=%d' % qty)
    return ','.join(parts + vals)


def _cube_output(rec, i, ctx):
    """Inverse of D2Common DATATBLS_CubeMainOutputParser (D2Sigma's parser for Median)."""
    o = CUBE_OUT_OFF + CUBE_OUT_LEN * i
    if len(rec) >= o + 0x18 and _is_mxl(ctx, 'cubemain'):
        return _sigma_cube_output(rec, o, i, ctx)
    p = rec[o:o + 0x18]
    if len(p) < 0x18:
        return ''
    flags, widx, wid, post, qty, btype = struct.unpack_from('<HHHBBB', p)
    pre = list(struct.unpack_from('<3H', p, 12))
    suf = list(struct.unpack_from('<3H', p, 18))
    special = False
    if flags & 0x08 and btype == 0xFC and post in (5, 7):
        special = True
        base = ctx.key('uniqueitems' if post == 7 else 'setitems', 'index', wid - 1)
    elif btype == 0xFF and flags & 0x40:
        base = 'usetype'           # 'reg' below sets the type again
    else:
        special_names = {0xFF: 'usetype', 0xFE: 'useitem', 1: 'Cow Portal',
                         2: 'Pandemonium Portal', 3: 'Pandemonium Finale Portal'}
        if btype in special_names:
            base = special_names[btype]
        elif btype == 0xFD:
            base = ctx.key('itemtypes', 'Code', widx)
        elif btype == 0xFC:
            base = ctx.item_code(widx)
        else:
            base = ''
    if not base:
        return 'void' if i == 0 else ''
    parts = [base]
    for bit, nm in ((0x04, 'eth'), (0x02, None), (0x01, 'mod'), (0x80, 'exc'), (0x10, 'uns'),
                    (0x20, 'rem'), (0x40, 'reg')):
        if flags & bit:
            parts.append(nm if nm else 'sock=%d' % qty)
    for bit, nm in ((0x100, 'eli'), (0x200, 'rep'), (0x400, 'rch')):
        if flags & bit:
            parts.append(nm)
    if post in QUALITY and not special:
        parts.append(QUALITY[post])
    while pre and not pre[-1]:
        pre.pop()
    while suf and not suf[-1]:
        suf.pop()
    parts += ['pre=%d' % v for v in pre] + ['suf=%d' % v for v in suf]
    if not (flags & 2) and qty:
        parts.append('qty=%d' % qty)
    return ','.join(parts)


def _monstats_skmode(rec, i, ctx):
    if len(rec) < 0x198:
        return ''
    skill = struct.unpack_from('<h', rec, 0x170 + 2 * i)[0]
    if skill < 0:
        return ''
    mode = rec[0x180 + i]
    seq = struct.unpack_from('<h', rec, 0x188 + 2 * i)[0]
    if seq >= 0:            # mode is a monseq sequence (MONMODE_SEQUENCE), else -1
        return ctx.key('monseq', 'sequence', seq)
    return ctx.key('monmode', 'code', mode)


def _monstats2_comp(rec, i, ctx):
    if len(rec) < 0xE6:
        return ''
    cnt = rec[0x15 + i]
    comps = rec[0x26 + 12 * i: 0x26 + 12 * i + min(cnt, 12)]
    # 0xFF = a token that was not in compcode; '?' compiles back to 0xFF
    return ','.join('?' if c == 0xFF else ctx.key('compcode', 'code', c) for c in comps)


def _monpreset_place(rec, i, ctx):
    typ = rec[1]
    row = struct.unpack_from('<H', rec, 2)[0]
    if typ == 2:
        return ctx.key('superuniques', 'Superunique', row)
    if typ == 1:
        return ctx.key('monstats', 'Id', row)
    return ctx.key('monplace', 'code', row)


# --- D2Sigma (Median XL) callbacks, D2Linkers.cpp in the installed D2Sigma.dll

def _sigma_classifications(rec, off, ctx):
    """armor2/weapons2/misc2 Classifications (FUN_100822e0): the text is split on ' ', '"',
    TAB, then ','; each item is looked up in itemClasses (Sigma linker id 0x2c, rows > 0 only)
    and stored as a u16 at +4+2*i, up to 16.  Written as a comma list of itemclasses keys."""
    vals = struct.unpack_from('<16H', rec, off) if off + 32 <= len(rec) else ()
    return ','.join(ctx.key('itemclasses', 'Name', v) for v in vals if v)


# Per record type: {param offset (or None = every param): kind}.  The cell is first read as a
# number (stored at the param's offset), then the record's type picks a lookup that
# overwrites it.  kind: ('link', table, column, value written for '' / not found),
# 'stat'/'sound' (itemstatcost / sounds name, else the number), 'tbl' (string key, '' = 5382),
# 'code' (4-char code, space padded), ('num', value for '').
_DIFF = ('link', 'difficultylevelnames', 'name', -1)
REQUIREMENT_PARAMS = {        # requirements.bin type -> params (FUN_10082c10), param1 at +4
    1: {None: ('link', 'requirementnames', 'name', 0)},
    **{t: {None: ('link', 'requirementnames', 'name', 0)} for t in (2, 3)},
    **{t: {4: 'stat'} for t in (4, 5, 6, 7, 8)},
    9: {0xc: _DIFF}, 10: {0xc: _DIFF},
    **{t: {4: ('link', 'skills', 'skill', -1)} for t in range(0xb, 0x16)},
    0x18: {4: _DIFF}, 0x19: {4: _DIFF},
    0x1e: {4: ('link', 'playerclass', 'Code', -1)}, 0x1f: {4: ('link', 'playerclass', 'Code', -1)},
    0x20: {4: ('link', 'states', 'state', -1)}, 0x21: {4: ('link', 'states', 'state', -1)},
    0x22: {4: 'code', 8: ('num', 1), **{o: ('num', -1) for o in (0xc, 0x10, 0x14, 0x18)}},
    0x23: {4: 'code'},
}
NPCACTION_PARAMS = {          # npcactions.bin type -> params (FUN_10082620), param1 at +0xc
    1: {None: ('link', 'npcactionnames', 'name', 0)},
    3: {0x10: 'tbl'},
    **{t: {o: ('num', -1) for o in range(0x14, 0x34, 4)} for t in (4, 5)},
    6: {0xc: 'stat'}, 7: {0xc: 'stat'},
    **{t: {0xc: ('link', 'levels', 'Name', -1)} for t in (8, 9, 0xf)},
    10: {0xc: 'tbl', 0x10: 'sound'},
    0x11: {0xc: 'code'},
    0x12: {0xc: ('link', 'overlay', 'overlay', -1)}, 0x13: {0xc: ('link', 'overlay', 'overlay', -1)},
    0x14: {0xc: 'sound'},
    0x15: {0xc: 'code', 0x10: ('num', 1), **{o: ('num', -1) for o in (0x14, 0x18, 0x1c, 0x20)}},
}


def sigma_param_kind(spec, rtype, off):
    """Kind of a requirements/npcactions param (shared with txt2bin)."""
    k = spec.get(rtype, {})
    return k.get(off, k.get(None, ('num', 0)))


def _sigma_param(spec, rec, off, ctx):
    if off + 4 > len(rec):
        return ''
    v = struct.unpack_from('<i', rec, off)[0]
    kind = sigma_param_kind(spec, struct.unpack_from('<i', rec, 0)[0], off)
    if kind == 'code':
        return _code(rec[off:off + 4])
    if kind == 'tbl':
        return '' if v == 5382 else ctx.tbl_key(v)
    if kind in ('stat', 'sound'):
        if v == 0:
            return ''
        return ctx.key('itemstatcost', 'stat', v) if kind == 'stat' else ctx.key('sounds', 'Sound', v)
    if kind[0] == 'num':
        return '' if v == kind[1] else str(v)
    _l, t, c, empty = kind
    if v == empty:
        return ''
    return ctx.key(t, c, v)


def _sigma_requirement_param(rec, off, ctx):
    return _sigma_param(REQUIREMENT_PARAMS, rec, off, ctx)


def _sigma_npcaction_param(rec, off, ctx):
    return _sigma_param(NPCACTION_PARAMS, rec, off, ctx)


CUSTOM = {'cube_input': _cube_input, 'cube_output': _cube_output,
          'monstats_skmode': _monstats_skmode, 'monstats2_comp': _monstats2_comp,
          'monpreset_place': _monpreset_place,
          'sigma_classifications': _sigma_classifications,
          'sigma_requirement_param': _sigma_requirement_param,
          'sigma_npcaction_param': _sigma_npcaction_param}


# ------------------------------------------------------------------ convert

def _cell(rec, f, row, table, ctx, codes):
    ft = f['ftype']
    link = f.get('link')
    if ft in (23, 24):
        fn = CUSTOM.get(link)
        if fn is None:
            # unknown callback (Median's D2Sigma): show the dword it was compiled to
            off = f['offset']
            if off is None or off + 4 > len(rec):
                return ''
            v = struct.unpack_from('<i', rec, off)[0]
            return '' if v == 0 and ctx.zero_blank else str(v)
        try:
            return fn(rec, f['offset'] or 0, ctx)
        except (IndexError, struct.error):
            return ''
    if ft in NAMEKEY_TYPES or (ft == 12 or ft == 14):
        # the name itself is not stored; the field holds its link index (usually the row,
        # but e.g. monseq rows of one sequence share it).  Use a txt beside the bins if any.
        v = _field_raw(rec, f)
        idx = v if isinstance(v, int) and ft in NAMEKEY_TYPES else row
        if idx == 0 and table in NONE_ROW0:
            return ''          # the 'none' row has an empty key (links to it are written '')
        vals = ctx.txt_column(table, f['name'])
        if vals is not None and 0 <= row < len(vals) and not ctx.raw_links:
            return vals[row]
        if ft in NAMEKEY_TYPES and not ctx.raw_links:
            return ctx.row_name(table, f, idx)
        return placeholder(table, idx)
    v = _field_raw(rec, f)
    if v is None:
        return ''
    if ft in LINK_TYPES:
        return _link_text(ctx, link, v, struct.calcsize(INT_FMT[ft]))
    if ft == 22:
        return '' if v == 0xFFFF or (v == 0 and ctx.zero_blank) else ctx.tbl_key(v)
    if ft == 25:
        if link and link.startswith('calc:'):
            ct = link[5:]
            blob = codes.get(ct)
            if blob is None:
                blob = ctx.bin(ct)
                codes[ct] = blob
                codes[ct + '#names'] = ctx.calc_names(ct)
            if v == 0xFFFFFFFF:
                return ''
            if blob is not None and v < len(blob):
                t = calc.decode(blob, v, ct, codes[ct + '#names'])
                if len(t.encode('utf-8')) > 255:
                    # the compiler reads 256 chars: long row names would cut the formula;
                    # write skills / stats / missiles by row number instead
                    nm = codes[ct + '#names']
                    t = calc.decode(blob, v, ct, calc.Names(
                        param=nm.param, misscalc=nm.misscalc, skillcalc=nm.skillcalc))
                return t
            # the pool .bin is not in the dir (a patch ships only the bins it changed): keep
            # the offset itself, '@N', which txt2bin stores as is
            return '@%d' % v
        v = struct.unpack('<i', struct.pack('<I', v))[0]
        return '' if v == 0 and ctx.zero_blank else str(v)
    if isinstance(v, str):
        return v
    if v == 0 and ctx.zero_blank:
        return ''
    return str(v)


def convert(data, table, version='auto', ctx=None):
    """-> (headers, rows) where rows are lists of strings."""
    table = table.lower()
    if ctx is None:
        ctx = Context(version=version)
    lay = None
    if version not in (None, 'auto'):
        lay = layouts.load(version, table)
        n, rs = records(data)
        if lay and lay.get('record_size') not in (None, rs):
            lay = None
    if lay is None:
        lay = ctx.layout_for(table, data)
    if lay is None:
        return raw_dump(data)
    n, rs = records(data)
    fields = lay['fields']
    headers = [f['name'] for f in fields]
    rows = []
    codes = {}
    for i in range(n):
        rec = data[4 + i * rs: 4 + (i + 1) * rs]
        rows.append([_cell(rec, f, i, table, ctx, codes) for f in fields])
    return headers, rows


def layout_used(data, table, version='auto', ctx=None):
    """Version string that convert() would use, or None for raw dump."""
    if version not in (None, 'auto'):
        lay = layouts.load(version, table)
        if lay and lay.get('record_size') == records(data)[1]:
            return version
    prefer = None if version in (None, 'auto') else version
    if prefer is None and ctx is not None:
        prefer = ctx.dir_version()
    return detect(data, table, prefer=prefer)


# ------------------------------------------------------------------ raw dump

def _printable(b):
    return all(32 <= c < 127 for c in b)


def raw_dump(data):
    """Fallback for unknown layouts: columns named type@offset."""
    n, rs = records(data)
    if not rs:
        # not a record table: one row with the bytes
        return ['offset', 'hex'], [[str(i), data[i:i + 16].hex(' ')]
                                   for i in range(0, len(data), 16)]
    recs = [data[4 + i * rs: 4 + (i + 1) * rs] for i in range(n)]
    unit = 4 if rs % 4 == 0 else (2 if rs % 2 == 0 else 1)
    cols = []
    off = 0
    while off < rs:
        L = _string_at(recs, off, rs, unit)
        if L:
            cols.append(('str', off, L))
            off += L
            continue
        u = unit
        while off % u or off + u > rs:
            u //= 2
        cols.append(({4: 'i32', 2: 'u16', 1: 'u8'}[u], off, u))
        off += u
    fmt = {'i32': '<i', 'u16': '<H', 'u8': '<B'}
    headers = ['row'] + ['%s@%d' % (t, o) for t, o, _l in cols]
    rows = []
    for i, r in enumerate(recs):
        row = [str(i)]
        for t, o, L in cols:
            if t == 'str':
                row.append(_cstr(r[o:o + L]))
            else:
                row.append(str(struct.unpack_from(fmt[t], r, o)[0]))
        rows.append(row)
    return headers, rows


def _string_at(recs, off, rs, unit):
    """Length of a text column starting at off (multiple of unit), or 0."""
    best = 0
    nonempty = 0
    for r in recs:
        b = r[off:]
        z = b.find(b'\0')
        s = b if z < 0 else b[:z]
        if not s:
            continue
        if not _printable(s) or not (chr(s[0]).isalnum() or s[0] in b' _'):
            return 0
        if z < 0:
            return 0
        # padding after the text must be zero up to the next unit boundary
        nonempty += 1
        best = max(best, len(s) + 1)
    if nonempty == 0 or best < 3:
        return 0
    if nonempty * 4 < len(recs):
        return 0
    L = -(-best // unit) * unit
    # extend while the following bytes are zero in every row (fixed-size buffers)
    while off + L + unit <= rs and all(r[off + L: off + L + unit] == bytes(unit) for r in recs):
        if L >= 64:
            break
        L += unit
    return min(L, rs - off)


# ------------------------------------------------------------------- output

def write_txt(path, headers, rows):
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write('\t'.join(headers) + '\r\n')
        for r in rows:
            fh.write('\t'.join(c.replace('\t', ' ').replace('\r', '').replace('\n', '\\n')
                               for c in r) + '\r\n')


def convert_file(src, dst=None, version='auto', ctx=None):
    """Convert one .bin (or .tbl) file; returns (dst, version used or 'raw'/'tbl')."""
    base = os.path.basename(src)
    name, ext = os.path.splitext(base)
    if dst is None:
        dst = os.path.splitext(src)[0] + '.txt'
    with open(src, 'rb') as fh:
        data = fh.read()
    if ext.lower() == '.tbl':
        with open(dst, 'w', encoding='utf-8', newline='') as fh:
            fh.write(Tbl.parse(data).to_txt())
        return dst, 'tbl'
    table = name.lower()
    if ctx is None:
        ctx = Context(bin_dir=os.path.dirname(src), version=version)
    if table in CODE_TABLES:
        with open(dst, 'w', encoding='utf-8', newline='') as fh:
            fh.write(calc.code_table_txt(data, table, ctx.calc_names(table)))
        return dst, 'calc'
    used = layout_used(data, table, version, ctx)
    headers, rows = convert(data, table, version, ctx)
    write_txt(dst, headers, rows)
    return dst, used or 'raw'


# ------------------------------------------------------------------ directories

def convert_dir(bin_dir, out_dir, version='auto', strings=None, lossless=False, tables=None,
                ingame_names=False, zero_blank=True, log=None, raw_links=False,
                vanilla_names=True, merge_ext=False, structure=True, names='auto'):
    """Convert every .bin/.tbl in bin_dir into out_dir.  -> {name: version used}.

    structure (default): drop the columns the source txt evidently lacked and order the calc
    columns the way the pool was filled, so txt2bin rebuilds the bins (both are visible txt
    structure, recovered from the bins).  lossless: that plus '?{hex}' / '*patch' / '*pool' for
    anything still different (see the module docstring); nothing is left for it in Median, 1.10,
    1.13c/d and 1.14d."""
    os.makedirs(out_dir, exist_ok=True)
    if strings is None:
        strings = bin_dir
    ctx = Context(bin_dir=bin_dir, strings=strings, version=version, zero_blank=zero_blank,
                  ingame_names=ingame_names, raw_links=raw_links,
                  vanilla_names=vanilla_names, names=names)
    done = {}
    for fn in sorted(os.listdir(bin_dir)):
        name, ext = os.path.splitext(fn)
        if ext.lower() not in ('.bin', '.tbl'):
            continue
        if tables and name.lower() not in tables:
            continue
        dst = os.path.join(out_dir, name.lower() + '.txt')
        try:
            _dst, used = convert_file(os.path.join(bin_dir, fn), dst, version, ctx)
            done[name.lower()] = used
        except Exception as e:       # keep going on bad files
            done[name.lower()] = 'error: %s' % e
        if log:
            log('%-28s -> %s' % (fn, done[name.lower()]))
    ver = ctx.dir_version() if version in (None, 'auto') else version
    if lossless:
        add_patches(bin_dir, out_dir, version=ver, strings=ctx.strings, tables=done)
    elif structure:
        # what the bins say about the source txt itself (no hidden data): drop the columns it
        # did not have and put the calc columns in the order the pool was filled
        _drop_absent(bin_dir, out_dir, ver, ctx.strings, done)
        _order_calc(bin_dir, out_dir, ver, done)
    if merge_ext:
        for ext in merge_ext_tables(out_dir):
            done[ext] = 'merged into %s.txt' % EXT_BASE[ext]
    return done


def merge_ext_tables(txt_dir):
    """Move each D2Sigma extension table's columns into its base txt (EXT_BASE), the layout
    Median's authors use.  Skipped when the row counts differ, a column name exists in both
    with other values, or the ext txt carries lossless '*' data.  -> merged ext names."""
    merged = []
    for ext, base in sorted(EXT_BASE.items()):
        pe, pb = (os.path.join(txt_dir, t + '.txt') for t in (ext, base))
        if not (os.path.exists(pe) and os.path.exists(pb)):
            continue
        with open(pe, 'rb') as fh:
            le = fh.read().split(b'\r\n')
        with open(pb, 'rb') as fh:
            lb = fh.read().split(b'\r\n')
        for L in (le, lb):
            if L and L[-1] == b'':
                L.pop()
        he, hb = le[0].split(b'\t'), lb[0].split(b'\t')
        if len(le) != len(lb) or any(h.startswith(b'*') for h in he + hb) or \
                any(ln.startswith(b'*') for ln in le + lb):
            continue
        hbl = [h.lower() for h in hb]
        rows_e = [ln.split(b'\t') for ln in le]
        rows_b = [ln.split(b'\t') for ln in lb]
        add, ok = [], True
        for i, h in enumerate(he):
            if h.lower() in hbl:
                j = hbl.index(h.lower())
                if any((re[i] if i < len(re) else b'') != (rb[j] if j < len(rb) else b'')
                       for re, rb in zip(rows_e[1:], rows_b[1:])):
                    ok = False
            else:
                add.append(i)
        if not ok:
            continue
        out = []
        for re, rb in zip(rows_e, rows_b):
            rb = rb + [b''] * (len(hb) - len(rb))
            out.append(b'\t'.join(rb + [re[i] if i < len(re) else b'' for i in add]))
        with open(pb, 'wb') as fh:
            fh.write(b'\r\n'.join(out) + b'\r\n')
        os.remove(pe)
        merged.append(ext)
    return merged


def _read_bin(bin_dir, name):
    for fn in os.listdir(bin_dir):
        if fn.lower() == name + '.bin':
            with open(os.path.join(bin_dir, fn), 'rb') as fh:
                return fh.read()
    return None


def _drop_absent(bin_dir, txt_dir, version, strings, tables):
    """Remove columns the source txt evidently did not have (txt2bin.absent_fields), so that the
    compiler leaves those bytes alone like the game did."""
    from . import txt2bin
    proj = txt2bin.Project(txt_dir, version=version or 'auto', strings=strings)
    for name in sorted(tables or []):
        if name in txt2bin.POOL_KIND or name in CODE_TABLES:
            continue
        orig = _read_bin(bin_dir, name)
        lay = proj.layout(name)
        if orig is None or lay is None:
            continue
        try:
            mine = proj.compile(name)
        except Exception:
            continue
        if mine is None or mine == orig:
            continue
        drop = set(f.lower() for f in txt2bin.absent_fields(lay, mine, orig))
        if not drop:
            continue
        tp = os.path.join(txt_dir, name + '.txt')
        with open(tp, 'rb') as fh:
            lines = fh.read().split(b'\r\n')
        if lines and lines[-1] == b'':
            lines.pop()
        hdr = lines[0].split(b'\t')
        keep = [i for i, h in enumerate(hdr) if h.decode('latin-1').lower() not in drop]
        out = []
        for ln in lines:
            c = ln.split(b'\t')
            out.append(b'\t'.join(c[i] if i < len(c) else b'' for i in keep))
        with open(tp, 'wb') as fh:
            fh.write(b'\r\n'.join(out) + b'\r\n')


def _order_calc(bin_dir, txt_dir, version, tables):
    """The game appends calc expressions to the pool row by row in txt column order.  Recover
    that order of the calc columns from the offsets in the .bin and permute the calc columns of
    the txt accordingly (other columns stay where they are)."""
    for name in sorted(tables or []):
        lay = layouts.load(version, name) if version else None
        if lay is None:
            continue
        cf = [f for f in lay['fields'] if (f.get('link') or '').startswith('calc:')]
        if len(cf) < 2:
            continue
        orig = _read_bin(bin_dir, name)
        n, rs = records(orig or b'')
        tp = os.path.join(txt_dir, name + '.txt')
        if rs is None or not os.path.exists(tp):
            continue
        after = {f['name']: set() for f in cf}
        indeg = {f['name']: 0 for f in cf}
        for r in range(n):
            seen = []
            for f in cf:
                v = struct.unpack_from('<I', orig, 4 + r * rs + f['offset'])[0]
                if v != 0xFFFFFFFF:
                    seen.append((v, f['name'], f['link']))
            seen.sort()
            for (_a, x, lx), (_b, y, ly) in zip(seen, seen[1:]):
                if lx == ly and y not in after[x]:
                    after[x].add(y)
                    indeg[y] += 1
        order = []
        pos = {f['name']: i for i, f in enumerate(cf)}
        ready = sorted((k for k, d in indeg.items() if d == 0), key=pos.get)
        while ready:
            k = ready.pop(0)
            order.append(k)
            for y in after[k]:
                indeg[y] -= 1
                if indeg[y] == 0:
                    ready.append(y)
            ready.sort(key=pos.get)
        if len(order) != len(cf) or order == [f['name'] for f in cf]:
            continue           # cycle (inconsistent) or already in layout order
        with open(tp, 'rb') as fh:
            lines = fh.read().split(b'\r\n')
        if lines and lines[-1] == b'':
            lines.pop()
        hdr = [h.decode('latin-1') for h in lines[0].split(b'\t')]
        slots = [i for i, h in enumerate(hdr) if h in pos]
        names = [hdr[i] for i in slots]
        if sorted(names) != sorted(order[:len(names)]) and set(names) != set(order):
            order = [k for k in order if k in names]
        src = {nm: i for i, nm in zip(slots, names)}
        perm = list(range(len(hdr)))
        for slot, nm in zip(slots, [k for k in order if k in src]):
            perm[slot] = src[nm]
        out = []
        for ln in lines:
            c = ln.split(b'\t')
            out.append(b'\t'.join(c[j] if j < len(c) else b'' for j in perm))
        with open(tp, 'wb') as fh:
            fh.write(b'\r\n'.join(out) + b'\r\n')


def _fix_calc(bin_dir, txt_dir, version, strings, tables):
    """Calc cells whose text does not compile back to the same bytecode ('?', Sigma
    sub-keywords ...) are rewritten as '?{hex}' so the code pools come out identical."""
    from . import txt2bin
    proj = txt2bin.Project(txt_dir, version=version or 'auto', strings=strings)
    pools = {}
    for name in sorted(tables or []):
        lay = proj.layout(name)
        if lay is None or name in CODE_TABLES:
            continue
        cf = [f for f in lay['fields'] if (f.get('link') or '').startswith('calc:')]
        orig = _read_bin(bin_dir, name) if cf else None
        if not orig:
            continue
        n, rs = records(orig)
        tp = os.path.join(txt_dir, name + '.txt')
        if rs is None or not os.path.exists(tp):
            continue
        with open(tp, 'rb') as fh:
            lines = fh.read().split(b'\r\n')
        if lines and lines[-1] == b'':
            lines.pop()
        hdr = [h.lower() for h in lines[0].split(b'\t')]
        if len(lines) - 1 != n:
            continue
        changed = False
        for f in cf:
            pool = f['link'][5:]
            if pool not in pools:
                pools[pool] = _read_bin(bin_dir, pool)
            blob = pools[pool]
            if not blob:
                continue         # pool bin not in the dir: leave the cells alone
            kind = txt2bin.POOL_KIND.get(pool, 'skills')
            link = proj._calc_link(kind)
            kw = proj.calc_keywords(kind)
            col = f['name'].lower().encode('latin-1')
            if col not in hdr:
                continue
            ci = hdr.index(col)
            for r in range(n):
                off = struct.unpack_from('<I', orig, 4 + r * rs + f['offset'])[0]
                cells = lines[1 + r].split(b'\t')
                cell = cells[ci] if ci < len(cells) else b''
                if off == 0xFFFFFFFF or off >= len(blob):
                    want = b''
                else:
                    want = blob[off:calc.expr_end(blob, off)]
                got = txt2bin.compile_expr(cell[:256], kind, link, arity=True, keywords=kw,
                                           lenient=proj.version == 'mxl') \
                    if cell else b''
                if got == want or (not want and not cell):
                    continue
                new = b'?{%s}' % want.hex().encode() if want else b''
                while len(cells) <= ci:
                    cells.append(b'')
                cells[ci] = new
                lines[1 + r] = b'\t'.join(cells)
                changed = True
        if changed:
            with open(tp, 'wb') as fh:
                fh.write(b'\r\n'.join(lines) + b'\r\n')


def add_patches(bin_dir, txt_dir, version='auto', strings=None, tables=None):
    """Compile txt_dir with txt2bin and add '*patch' / '*pool' data where it differs from the
    bins in bin_dir.  -> {table: number of patched records}."""
    from . import txt2bin
    _drop_absent(bin_dir, txt_dir, version, strings, tables)
    _order_calc(bin_dir, txt_dir, version, tables)
    _fix_calc(bin_dir, txt_dir, version, strings, tables)
    proj = txt2bin.Project(txt_dir, version=version or 'auto', strings=strings)
    stats = {}
    for name in sorted(tables or []):
        if tables[name] in ('tbl',) or str(tables[name]).startswith('error'):
            continue
        p = os.path.join(bin_dir, name + '.bin')
        if not os.path.exists(p):
            for fn in os.listdir(bin_dir):
                if fn.lower() == name + '.bin':
                    p = os.path.join(bin_dir, fn)
        if not os.path.exists(p):
            continue
        with open(p, 'rb') as fh:
            orig = fh.read()
        if name in txt2bin.POOL_KIND:
            continue
        try:
            mine = proj.compile(name)
        except Exception:
            mine = None
        if mine is None or mine == orig:
            continue
        n, rs = records(orig)
        tp = os.path.join(txt_dir, name + '.txt')
        if rs is None or len(mine) != len(orig):
            continue          # row count / size mismatch: cannot patch per record
        with open(tp, 'rb') as fh:
            lines = fh.read().split(b'\r\n')
        if lines and lines[-1] == b'':
            lines.pop()
        hdr = lines[0].split(b'\t')
        if b'*patch' in hdr:
            continue
        lines[0] += b'\t*patch'
        cnt = 0
        for i in range(n):
            a = mine[4 + i * rs: 4 + (i + 1) * rs]
            b = orig[4 + i * rs: 4 + (i + 1) * rs]
            spec = txt2bin.make_patch(a, b) if a != b else ''
            cnt += bool(spec)
            lines[1 + i] += b'\t' + spec.encode()
        with open(tp, 'wb') as fh:
            fh.write(b'\r\n'.join(lines) + b'\r\n')
        stats[name] = cnt
    # code pools (after the tables: compiling them filled the pools)
    for pool in txt2bin.POOL_KIND:
        p = os.path.join(bin_dir, pool + '.bin')
        tp = os.path.join(txt_dir, pool + '.txt')
        if not os.path.exists(p) or not os.path.exists(tp) or not proj._pool_tables(pool):
            continue
        with open(p, 'rb') as fh:
            orig = fh.read()
        mine = proj.code_pool(pool)
        if mine != orig:
            with open(tp, 'ab') as fh:
                fh.write(b'*pool\t' + txt2bin.make_patch(mine, orig).encode() + b'\r\n')
            stats[pool] = 1
    return stats
