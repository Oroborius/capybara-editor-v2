"""Character save (.d2s, version 96 / Median XL) reader and writer: level, quests, waypoints, equipment,
inventory and mercenary items.

Layout (1.13c): header with quests ('Woo!' @0x14F), waypoints ('WS' @0x279), NPC intros ('w4' @0x2C9), then the
stats ('gf', 9-bit ids, CSvParam/CSvBits widths of itemstatcost; Median adds stat 88 with a 16-bit param), the
skills ('if', kept as is), the character's items ('JM' + count), the corpse ('JM' + count), the mercenary ('jf' +
items when hired) and the golem ('kf'). File size @0x08 and checksum @0x0C are recomputed on writing.
"""
import json
import os
import random
import shutil
import struct

from mxl_format import read_item_list, FormatError
from mxl_creator import decode_item, encode_item, CreateError
from mxl_lang import T

MAGIC = 0xAA55AA55
QUEST_OFF, WP_OFF, NPC_OFF = 0x14F, 0x279, 0x2C9
QUEST_DATA = QUEST_OFF + 10           # 'Woo!' + version u32 + size u16
WP_DATA = WP_OFF + 8                   # 'WS' + 6 bytes
DIFFICULTIES = ('Normal', 'Nightmare', 'Hell')

# Quest words per difficulty (48 u16 words; file offset = QUEST_DATA + 96 * difficulty + 2 * word). Layout = vanilla
# 1.13, checked against the game's own saves (one character at level 100 = "A" and twice at level 117 = "B", "C";
# hex values are what the GAME wrote there):
#    0       act I introduction             1 in every difficulty entered (A/B/C: Normal, Nightmare; B/C: Hell)
#    1- 6    act I quests                   1001 9001 101D 9011 804A 1019 101D 1015
#    7       travelled to act II            1 wherever Sisters to the Slaughter (6) is done - also with word 3 at
#                                           804A (no bit 0): it follows the act's last quest, not "all six"
#    8       act II introduction            1
#    9-14    act II quests                  1001 1849 1801 1005 1181 1E65 1A25 1065
#   15       travelled to act III           1
#   16       act III introduction           1 in Normal and Hell, 0 in Nightmare although the act was played
#                                           through: an NPC's speech heard, not a requirement
#   17-22    act III quests                 1001 105D 100D 1005 13F5 1009 1061 1071
#   23       travelled to act IV            1
#   24       act IV introduction            1
#   25-27    act IV quests                  1001 1301 1001  (26 = Terror's End, the act's last quest)
#   28       travelled to act V             1
#   29-31    unused (vanilla: act IV's three empty quest slots)   0
#   32       act V introduction             1 in every difficulty that reached act V
#   33, 34   unused                         0 (this editor wrote 1 to word 34 as "act V intro" before: wrong word)
#   35-40    act V quests                   2002 8002 8022 2032 1001 210A 0709 8709 9709 801E 0009 10C9 000D 040D
#                                           0405 000C  (in progress / reward pending states are common here)
#   41       NOT "act V finished": 8002 in every difficulty entered, also in A's Nightmare where act V had only
#            just been reached; 0 in a difficulty never entered. Vanilla: the stat / skill reset (Akara) state.
#            When the game writes it (entering the difficulty or Den of Evil) the samples cannot tell: the editor
#            leaves it alone (it wrote 1 = "completed" there before, a value the game never holds).
#   42-47    unused                         0
# A difficulty is finished when Eve of Destruction (40) has bit 0 (A/B/C Normal: 000D / 040D with header
# progression >= 5); there is no word of its own for it.
# (act, intro word, [(word, string key)], "travelled to the next act" word or None)
ACTS = [
    ('Act I', 0, [(1, 'qstsa1q1'), (2, 'qstsa1q2'), (3, 'qstsa1q3'), (4, 'qstsa1q4'), (5, 'qstsa1q5'), (6, 'qstsa1q6')], 7),
    ('Act II', 8, [(9, 'qstsa2q1'), (10, 'qstsa2q2'), (11, 'qstsa2q3'), (12, 'qstsa2q4'), (13, 'qstsa2q5'), (14, 'qstsa2q6')], 15),
    ('Act III', 16, [(17, 'qstsa3q1'), (18, 'qstsa3q2'), (19, 'qstsa3q3'), (20, 'qstsa3q4'), (21, 'qstsa3q5'), (22, 'qstsa3q6')], 23),
    ('Act IV', 24, [(25, 'qstsa4q1'), (26, 'qstsa4q2'), (27, 'qstsa4q3')], 28),
    ('Act V', 32, [(35, 'qstsa5q1'), (36, 'qstsa5q2'), (37, 'qstsa5q3'), (38, 'qstsa5q4'), (39, 'qstsa5q5'), (40, 'qstsa5q6')], None),
]
# the quest whose completion opens the way to the next act: travel word -> quest word
ACT_LAST_QUEST = {7: 6, 15: 14, 23: 22, 28: 26}
RESPEC_WORD = 41                      # see above: never written by set_quests
# quest rewards given when a quest is marked done here (per difficulty: 4 skill points, 5 stat points, +20 life)
QUEST_REWARDS = {1: ('skill', 1),      # Den of Evil
                 9: ('skill', 1),      # Radament's Lair
                 25: ('skill', 2),     # The Fallen Angel (Izual)
                 17: ('stats', 5),     # Lam Esen's Tome
                 20: ('life', 20)}     # The Golden Bird
QUEST_DONE = 0x1001                   # completed (bit 0) + closed in the quest log (bit 12): what the game holds for
                                      # a plainly finished quest (words 1, 9, 17, 20, 25, 27, 36 of the samples)
LAST_QUEST_WORD = 40                  # Eve of Destruction: difficulty finished

# (index in the 'WS' bitfield, in-game name), from levels.txt "Waypoint" and the string tables
WAYPOINTS = [
    ('Act I', [(0, 'Rogue Encampment'), (1, 'Cold Plains'), (2, 'Stony Field'), (3, 'Dark Wood'), (4, 'Black Marsh'),
               (5, 'Outer Cloister'), (6, 'Jail Level 1'), (7, 'Inner Cloister'), (8, 'Catacombs Level 2'),
               (50, 'Duncraig')]),
    ('Act II', [(9, 'Lut Gholein'), (10, 'Sewers Level 2'), (11, 'Dry Hills'), (12, 'Halls of the Dead Level 2'),
                (13, 'Far Oasis'), (14, 'Lost City'), (15, 'Palace Cellar Level 1'), (16, 'Arcane Sanctuary'),
                (17, 'Canyon of the Magi'), (60, 'Tran Athulua'), (61, 'Island of Skartara')]),
    ('Act III', [(18, 'Kurast Docks'), (19, 'Spider Forest'), (20, 'Great Marsh'), (21, 'Flayer Jungle'),
                 (22, 'Lower Kurast'), (23, 'Kurast Bazaar'), (24, 'Upper Kurast'), (25, 'Travincal'),
                 (26, 'Durance of Hate Level 2'), (70, 'Caldeum'), (71, 'Torajan Jungles'), (72, 'Vizjun')]),
    ('Act IV', [(27, 'The Pandemonium Fortress'), (28, 'City of the Damned'), (29, 'River of Flame'),
                (80, 'Silver City')]),
    ('Act V', [(30, 'Harrogath'), (31, 'Frigid Highlands'), (32, 'Arreat Plateau'), (33, 'Crystalline Passage'),
               (34, 'Glacial Trail'), (35, 'Halls of Pain'), (36, 'Frozen Tundra'), (37, "The Ancients' Way"),
               (38, 'Worldstone Keep Level 2'), (90, 'Túr Dúlra')]),
]
# Median XL areas that only exist in Hell (levels.txt: monster level set for Hell only)
HELL_ONLY_WAYPOINTS = frozenset({50, 60, 61, 70, 71, 72, 80, 90})
ALL_WAYPOINTS = [n for _, wps in WAYPOINTS for n, _ in wps]
N_WAYPOINTS = len(ALL_WAYPOINTS)                   # 47


def waypoint_ids(diff):
    """Waypoint indexes that exist in this difficulty (0 Normal, 1 Nightmare, 2 Hell)."""
    return [n for n in ALL_WAYPOINTS if diff == 2 or n not in HELL_ONLY_WAYPOINTS]


# equipment slots (value of the 'equipped' field) and the body location they accept
SLOTS = {1: 'head', 2: 'neck', 3: 'tors', 4: 'rarm', 5: 'larm', 6: 'rrin', 7: 'lrin', 8: 'belt', 9: 'feet',
         10: 'glov', 11: 'rarm', 12: 'larm'}
SLOT_NAMES = {1: 'Helm', 2: 'Amulet', 3: 'Armor', 4: 'Right hand (I)', 5: 'Left hand (I)', 6: 'Right ring',
              7: 'Left ring', 8: 'Belt', 9: 'Boots', 10: 'Gloves', 11: 'Right hand (II)', 12: 'Left hand (II)'}


def slot_name(n, default=''):
    """Name of an equipment slot in the chosen language."""
    return T(f'ch.slot.{n}', SLOT_NAMES[n]) if n in SLOT_NAMES else default


def difficulty_name(k):
    return T(f'ch.diff.{k}', DIFFICULTIES[k])


BODYLOC_CODES = ['', 'head', 'neck', 'tors', 'rarm', 'larm', 'rrin', 'lrin', 'belt', 'feet', 'glov']
# Slots a Median XL Sigma mercenary has: the game's inventory table (inventory.bin, the two "Hireling" rows)
# defines boxes for both arms, torso, head, neck, belt, feet and gloves and none for the two rings; the samples
# hold mercenary items in 1, 2, 3, 4, 8, 9, 10. No weapon set II (11, 12).
MERC_SLOTS = (1, 2, 3, 4, 5, 8, 9, 10)
INV_W, INV_H = 15, 10
LOC_STORED, LOC_EQUIPPED, LOC_BELT = 0, 1, 2
PANEL_INVENTORY, PANEL_CUBE = 1, 4


class CharError(Exception):
    """Character change refused (message for the user); the file is not modified."""


def checksum(buf):
    b = bytearray(buf)
    b[12:16] = b'\0\0\0\0'
    s = 0
    for x in b:
        s = ((s << 1) | (s >> 31)) & 0xFFFFFFFF
        s = (s + x) & 0xFFFFFFFF
    return s


class _Bits:
    def __init__(self, b):
        self.v = int.from_bytes(b, 'little')
        self.pos = 0

    def read(self, n):
        r = (self.v >> self.pos) & ((1 << n) - 1)
        self.pos += n
        return r


class _W:
    def __init__(self):
        self.v = 0
        self.pos = 0

    def write(self, n, x):
        if x < 0 or x >= (1 << n):
            raise CharError(f'value {x} does not fit in {n} bits')
        self.v |= x << self.pos
        self.pos += n

    def bytes(self):
        return self.v.to_bytes((self.pos + 7) // 8, 'little')


def _csv(data):
    """{stat: (param bits, value bits)} of the character stats (itemstatcost CSvParam / CSvBits)."""
    if not hasattr(data, '_csv_widths'):
        out = {}
        for r in data._rows('itemstatcost'):
            sid = struct.unpack_from('<H', r, 0)[0]
            if r[10]:
                out[sid] = (r[11], r[10])
        data._csv_widths = out
    return data._csv_widths


def _exp_table(data):
    if not hasattr(data, '_exp_rows'):
        path = os.path.join(data.folder, 'experience_sp.bin')
        if not os.path.exists(path):
            path = os.path.join(data.folder, 'experience.bin')
        with open(path, 'rb') as f:
            e = f.read()
        n = struct.unpack_from('<I', e)[0]
        data._exp_rows = [struct.unpack_from('<8I', e, 4 + 32 * i) for i in range(n)]
    return data._exp_rows


def _charstats(data):
    if not hasattr(data, '_charstats'):
        rows = []
        for r in data._rows('charstats'):
            rows.append(dict(life=r[0x43], stamina=r[0x44], mana=r[0x45], stats=r[0x50] or 5))
        data._charstats = rows
    return data._charstats


def class_names(data):
    """The seven class display names, from the extracted charstats.bin (rows 0..6, name at 0x20)."""
    try:
        names = [r[0x20:0x30].split(b'\0')[0].decode('latin1') for r in data._rows('charstats')[:7]]
        if len(names) == 7 and all(names):
            return names
    except Exception:
        pass
    from mxl_rules import CLASSES
    return list(CLASSES)


def class_skills(data, cls):
    """The class's skill ids in the save-file order: skills.bin row order (u32 at 12 is the class).
    The skills section of the .d2s ('if') holds one byte per one of these skills, in this order."""
    return [i for i, r in enumerate(data._rows('skills'))
            if struct.unpack_from('<I', r, 12)[0] == cls]


def class_skill_count(data, cls):
    return len(class_skills(data, cls))


def _skill_tab_names():
    """{class: {local tab: short name}} - the in-game tree tab bar labels, mined from the game
    (MedianDB 2.14's tabName per tab). Loaded once, empty only when the file is gone."""
    if not hasattr(_skill_tab_names, '_cache'):
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'skilltabnames.json'), encoding='utf-8') as f:
                _skill_tab_names._cache = json.load(f)
        except Exception:
            _skill_tab_names._cache = {}
    return _skill_tab_names._cache


def _skill_tab_name(note):
    """A short tab title from a skilltabs.bin note, or None when the note is no name."""
    if not note:
        return None
    low = note.lower()
    if 'masteries' in low:
        return 'Masteries'
    if 'paragon' in low or 'ultimate' in low:
        return 'Paragon & Ultimate'
    if 'passives' in low:
        return 'Passives'
    lines = [x.strip() for x in note.split('\n') if x.strip()]
    if not lines:
        return None
    last = lines[-1]
    if last.startswith('All Skills require ') and last.endswith(' Form'):
        return last[len('All Skills require '):-len(' Form')]
    for suffix in ('Devotion', 'Form', 'Tree'):
        if last.endswith(suffix):
            return last
    return None


def skill_trees(data):
    """{class: [(tab, name, [(row, col, sid, icon_cel)])]} - the in-game skill tree layout, from
    the extracted game tables: skilldesc.bin holds the position (byte 2 = tree tab, 3 = row,
    4 = column; tab 0 = the skill is not in any tree - an oSkill) and the icon cel (u16 at 22,
    a frame of the class's icons-<code>.dc6 sheet), and skilltabs.bin the tab notes
    (byte 0 = class, byte 1 = tab - 1, u16 at 2 = its string). Tabs are in game order."""
    if hasattr(data, '_skill_trees'):
        return data._skill_trees
    srows = data._rows('skills')
    sd_rows = data._rows('skilldesc')
    trees = {c: {} for c in range(7)}
    for sid, cls in data.skill_class.items():
        if cls == 255 or cls not in trees:
            continue
        sd = struct.unpack_from('<H', srows[sid], 404)[0]
        if not 0 < sd < len(sd_rows):
            continue
        r = sd_rows[sd]
        trees[cls].setdefault(r[2], []).append((r[3], r[4], sid, struct.unpack_from('<H', r, 22)[0]))
    notes = {}
    try:
        with open(os.path.join(data.folder, 'skilltabs.bin'), 'rb') as f:
            b = f.read()
        for i in range(struct.unpack_from('<I', b)[0]):
            r = b[4 + 8 * i:12 + 8 * i]
            try:
                notes[(r[0], r[1])] = data.s(struct.unpack_from('<H', r, 2)[0])
            except Exception:
                pass
    except Exception:
        pass
    out = {}
    cnames = class_names(data)
    short_names = _skill_tab_names()
    for cls in range(7):
        tabs = []
        for tab in sorted(trees[cls]):
            cells = sorted(trees[cls][tab])
            short = short_names.get(cnames[cls]) if cls < len(cnames) else None
            name = short.get(str(tab)) if isinstance(short, dict) else None
            if name is None:
                name = _skill_tab_name(notes.get((cls, tab - 1)))
            if name is None:
                name = T('he.skills_tree', 'Tree {n}', n=tab)
            tabs.append((tab, name, cells))
        out[cls] = tabs
    data._skill_trees = out
    data._skill_tab_notes = notes
    return out


def skill_tab_note(data, cls, tab):
    """The raw skilltabs.bin note of a tree tab: the long caption the game shows under the tree
    ("BOW DEVOTION (LOCKS OTHER DEVOTIONS)"). None when the game has no note for the tab."""
    if getattr(data, '_skill_tab_notes', None) is None:
        skill_trees(data)
    return (data._skill_tab_notes or {}).get((cls, tab - 1))


def max_level(data, cls):
    return _exp_table(data)[0][cls]


def exp_for_level(data, cls, level):
    rows = _exp_table(data)
    return rows[level][cls] if 1 <= level < len(rows) else None


EXP_MAX = 0xFFFFFFFF


def level_exp_range(data, cls, level):
    """(first, last) experience of a level in the game's table: from the experience that gives the level to one
    below the next level's. At the table's top level, or above it, the range is open up to what the save stores."""
    rows = _exp_table(data)
    top = max_level(data, cls)
    if level >= top or level + 1 >= len(rows):
        return rows[min(max(top, 1), len(rows) - 1)][cls], EXP_MAX
    level = max(1, level)
    lo, hi = rows[level][cls], rows[level + 1][cls] - 1
    return lo, max(lo, hi)


def level_for_exp(data, cls, exp):
    """Level the game's table gives for an experience value (1 .. the class's top level)."""
    rows = _exp_table(data)
    top = min(max_level(data, cls), len(rows) - 1)
    level = 1
    while level < top and exp >= rows[level + 1][cls]:
        level += 1
    return level


# ---------------------------------------------------------------------- stat screen fields
# Status byte (header 0x24). The other bits are kept as the file has them.
STATUS_FLAGS = {'hardcore': 0x04, 'died': 0x08, 'expansion': 0x20, 'ladder': 0x40}
STAT_LEVEL, STAT_EXP = 12, 13
FRACTION_BITS = 8                       # life / mana / stamina: fixed point, 8 fractional bits
# key, stat id, fractional bits, label
FIELDS = (
    ('level', 12, 0, 'Level'),
    ('experience', 13, 0, 'Experience'),
    ('strength', 0, 0, 'Strength'),
    ('dexterity', 2, 0, 'Dexterity'),
    ('vitality', 3, 0, 'Vitality'),
    ('energy', 1, 0, 'Energy'),
    ('stat_points', 4, 0, 'Stat points left'),
    ('skill_points', 5, 0, 'Skill points left'),
    ('life_cur', 6, FRACTION_BITS, 'Life'),
    ('life_max', 7, FRACTION_BITS, 'Life (maximum)'),
    ('mana_cur', 8, FRACTION_BITS, 'Mana'),
    ('mana_max', 9, FRACTION_BITS, 'Mana (maximum)'),
    ('stamina_cur', 10, FRACTION_BITS, 'Stamina'),
    ('stamina_max', 11, FRACTION_BITS, 'Stamina (maximum)'),
    ('gold', 14, 0, 'Gold'),
    ('gold_stash', 15, 0, 'Gold in stash'),
)
FIELD_KEYS = tuple(f[0] for f in FIELDS)
_FIELD = {f[0]: f for f in FIELDS}


class StatField:
    """One writable value of the stat screen. `value`, `min`, `max` are in the unit shown to the user (whole
    points); `raw` / `raw_max` are the stored integers (`value` = raw >> `shift`). `present` tells whether the stat
    is written in the file (a stat worth 0 is left out, except the level). `where`: 'stats' or 'header+stats'."""
    __slots__ = ('key', 'label', 'sid', 'bits', 'shift', 'raw', 'raw_max', 'value', 'min', 'max', 'present',
                 'where', 'stored', 'note')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self):
        return f'StatField({self.key}={self.value}, {self.min}..{self.max})'


def check_name(name):
    """The game's character name rule: 2 to 15 letters (A-Z), with at most one '-' or '_' that is neither the first
    nor the last character. Raises CharError."""
    ok = (isinstance(name, str) and 2 <= len(name) <= 15
          and all(c in '-_' or (c.isascii() and c.isalpha()) for c in name)
          and sum(c in '-_' for c in name) <= 1 and name[0] not in '-_' and name[-1] not in '-_')
    if not ok:
        raise CharError(T('ch.err.name_rule', 'name: 2 to 15 letters (A-Z), at most one - or _, not at the start '
                          'or the end'))
    return name


def companion_files(path):
    """Files of the save folder that belong to the character besides its .d2s (.key, .map, .ma0-.ma3, .stash)."""
    folder = os.path.dirname(path)
    old = os.path.splitext(os.path.basename(path))[0]
    out = []
    for fn in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(fn)
        if stem == old and (ext.lower() in ('.key', '.map', '.stash') or ext.lower().startswith('.ma')):
            out.append(fn)
    return out


def item_bodylocs(data, code):
    """Body locations ('head', 'rarm'...) where an item type can be equipped (item type and its ancestors)."""
    if not hasattr(data, '_bodylocs'):
        out = []
        for r in data._rows('itemtypes'):
            out.append((r[0x0A], r[0x0B]))
        data._bodylocs = out
    b = data.base(code)
    locs = set()
    for t in data.type_ancestors(b.type) | data.type_ancestors(b.type2):
        for x in data._bodylocs[t]:
            if 0 < x < len(BODYLOC_CODES):
                locs.add(BODYLOC_CODES[x])
    return locs


class Entry:
    """A top-level item of the character (with its socketed items): parsed item + raw bytes."""

    def __init__(self, it, blob):
        self.it = it
        self.blob = blob

    def moved(self, data, **fields):
        """Copy with header fields changed (location, equipped, x, y, panel); socketed items unchanged."""
        rec, n = decode_item(self.blob, data)
        rec.update(fields)
        return encode_item(rec, data) + self.blob[n:]


class Character:
    def __init__(self, path, data):
        self.path = path
        self.data = data
        with open(path, 'rb') as f:
            self.raw = f.read()
        self.parse(self.raw)

    # ------------------------------------------------------------------ parse / build
    def parse(self, b):
        d = self.data
        if struct.unpack_from('<I', b, 0)[0] != MAGIC:
            raise FormatError(T('ch.err.not_char', 'not a character file'))
        self.version = struct.unpack_from('<I', b, 4)[0]
        if b[QUEST_OFF:QUEST_OFF + 4] != b'Woo!' or b[WP_OFF:WP_OFF + 2] != b'WS':
            raise FormatError(T('ch.err.layout', 'unexpected character file layout'))
        gf = b.find(b'gf', NPC_OFF)
        if gf < 0:
            raise FormatError(T('ch.err.no_stats', "stats ('gf') not found"))
        self.head = bytearray(b[:gf])
        widths = _csv(d)
        br = _Bits(b[gf + 2:gf + 2 + 2048])
        stats = []
        while True:
            sid = br.read(9)
            if sid == 0x1FF:
                break
            if sid not in widths:
                raise FormatError(T('ch.err.unknown_stat', 'unknown character stat {stat}', stat=sid))
            pb, vb = widths[sid]
            p = br.read(pb) if pb else None
            stats.append([sid, p, br.read(vb)])
        self.stats = stats
        p = gf + 2 + (br.pos + 7) // 8
        if b[p:p + 2] != b'if':
            raise FormatError(T('ch.err.no_skills', "skills ('if') not found after the stats"))
        jm = b.find(b'JM', p)
        self.skills = b[p:jm]
        count = struct.unpack_from('<H', b, jm + 2)[0]
        items, q = read_item_list(b, jm + 4, count, d)
        self.items = [Entry(it, b[it['_offset']:it['_offset'] + self._full_size(it)]) for it in items]
        if b[q:q + 2] != b'JM':
            raise FormatError(T('ch.err.no_corpse', 'corpse list not found'))
        cc = struct.unpack_from('<H', b, q + 2)[0]
        r = q + 4
        if cc:
            r += 12
            if b[r:r + 2] != b'JM':
                raise FormatError(T('ch.err.no_corpse_items', 'corpse items not found'))
            n = struct.unpack_from('<H', b, r + 2)[0]
            _, r = read_item_list(b, r + 4, n, d)
        self.corpse = b[q:r]
        self.has_jf = b[r:r + 2] == b'jf'
        self.merc_items = None
        if self.has_jf:
            r += 2
            if b[r:r + 2] == b'JM':
                n = struct.unpack_from('<H', b, r + 2)[0]
                mitems, r2 = read_item_list(b, r + 4, n, d)
                self.merc_items = [Entry(it, b[it['_offset']:it['_offset'] + self._full_size(it)]) for it in mitems]
                r = r2
        self.tail = b[r:]

    @staticmethod
    def _full_size(it):
        end = it['_offset'] + it['_size']
        for s in it.get('socketed', []):
            end = s['_offset'] + s['_size']
        return end - it['_offset']

    def build(self):
        d = self.data
        out = bytearray(self.head)
        w = _W()
        widths = _csv(d)
        for sid, p, v in self.stats:
            pb, vb = widths[sid]
            w.write(9, sid)
            if pb:
                w.write(pb, p or 0)
            w.write(vb, v)
        w.write(9, 0x1FF)
        out += b'gf' + w.bytes() + self.skills
        out += b'JM' + struct.pack('<H', len(self.items)) + b''.join(e.blob for e in self.items)
        out += self.corpse
        if self.has_jf:
            out += b'jf'
            if self.merc_items is not None:
                out += b'JM' + struct.pack('<H', len(self.merc_items)) + b''.join(e.blob for e in self.merc_items)
        out += self.tail
        struct.pack_into('<I', out, 8, len(out))
        struct.pack_into('<I', out, 12, checksum(out))
        return bytes(out)

    def reload_items(self):
        """Re-reads the item lists from the built file (fresh offsets for the GUI)."""
        self.parse(self.build())

    # ------------------------------------------------------------------ header values
    @property
    def name(self):
        return self.head[0x14:0x24].split(b'\0')[0].decode('latin1')

    @property
    def cls(self):
        return self.head[0x28]

    @property
    def level(self):
        return self.head[0x2B]

    @property
    def progression(self):
        return self.head[0x25]

    @property
    def merc_id(self):
        return struct.unpack_from('<I', self.head, 0xB3)[0]

    @property
    def merc_hired(self):
        return self.merc_items is not None or self.merc_id != 0

    def stat(self, sid):
        return next((v for s, p, v in self.stats if s == sid), 0)

    def set_stat(self, sid, value, param=None):
        """Writes a stat of the 'gf' section the way the game stores it: sorted by id (then parameter), a stat worth 0
        left out (the level is always written). `param` selects one entry of a stat with a parameter (88).
        The value is not checked here (build() refuses what does not fit): set_field() is the checked way."""
        if param is None:
            for st in self.stats:
                if st[0] == sid:
                    st[2] = value
                    break
            else:
                pb, vb = _csv(self.data)[sid]
                self.stats.append([sid, 0 if pb else None, value])
            if value == 0 and sid not in (12,):
                self.stats = [st for st in self.stats if not (st[0] == sid and st[2] == 0)]
            self.stats.sort(key=lambda st: st[0])
            return
        pb, vb = _csv(self.data).get(sid, (0, 0))
        if not pb or not 0 <= param < (1 << pb) or not 0 <= value < (1 << vb):
            raise CharError(T('ch.err.stat_param', 'stat {stat}: parameter {param} / value {value} cannot be stored',
                              stat=sid, param=param, value=value))
        self.stats = [st for st in self.stats if not (st[0] == sid and st[1] == param)]
        if value:
            self.stats.append([sid, param, value])
        self.stats.sort(key=lambda st: (st[0], st[1] or 0))

    # ------------------------------------------------------------------ stat screen (unrestricted)
    def _field_raw(self, key):
        f = _FIELD.get(key)
        if f is None:
            raise CharError(T('ch.err.field', 'unknown character value: {field}', field=key))
        return f, self.stat(f[1])

    def stat_field(self, key):
        """Descriptor (StatField) of one stat-screen value: current value, storable range, where it is stored."""
        f, raw = self._field_raw(key)
        key, sid, shift, label = f
        bits = _csv(self.data)[sid][1]
        raw_max = (1 << bits) - 1
        note = ''
        lo = 0
        where = 'stats'
        if key == 'level':
            lo = 1
            where = 'header+stats'
            top = max_level(self.data, self.cls) if self.cls < 7 else None
            note = T('ch.note.level', 'stored twice (header byte 0x2B and stat 12), written together; the game '
                     'table ends at level {top}', top=top)
            if self.head[0x2B] != raw:
                note += ' ' + T('ch.note.level_diff', '- the file disagrees: header {a}, stat {b}', a=self.head[0x2B],
                                b=raw)
        elif key == 'experience' and self.cls < 7:
            a, b = level_exp_range(self.data, self.cls, self.level)
            note = T('ch.note.exp', 'level {level} is {lo} to {hi} in the game table', level=self.level, lo=a, hi=b)
        elif shift:
            note = T('ch.note.fixed', 'base value without items; stored in 1/{n} of a point (raw {raw})',
                     n=1 << shift, raw=raw)
        elif key in ('strength', 'dexterity', 'vitality', 'energy'):
            note = T('ch.note.base', 'base value without items')
        return StatField(key=key, label=T('ch.field.' + key, label), sid=sid, bits=bits, shift=shift, raw=raw,
                         raw_max=raw_max, value=raw >> shift, min=lo, max=raw_max >> shift,
                         present=any(st[0] == sid for st in self.stats), where=where, stored=True, note=note)

    def stat_fields(self):
        """Descriptors of every writable stat-screen value, in screen order (see FIELDS for the keys)."""
        return [self.stat_field(k) for k in FIELD_KEYS]

    def field(self, key):
        """Current value of a stat-screen field, in whole points (life / mana / stamina without their fraction)."""
        f, raw = self._field_raw(key)
        return raw >> f[2]

    def set_field(self, key, value):
        """Writes one stat-screen value as given, nothing else is recalculated ("unrestricted"). Limits are what
        the file can store (stat_field(key).min / .max); anything else raises CharError and changes nothing.
        Life / mana / stamina take whole points (a float sets the fraction too; an unchanged whole number keeps the
        stored fraction). 'level' writes the header byte and the stat together; points, life and experience are
        left alone (use set_level for the game's own level-up)."""
        f, raw = self._field_raw(key)
        key, sid, shift, label = f
        fd = self.stat_field(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) > 1e15:
            raise CharError(T('ch.err.field_number', '{label}: a number is expected', label=fd.label))
        if isinstance(value, float) and not shift:
            if value != int(value):
                raise CharError(T('ch.err.field_int', '{label}: a whole number is expected', label=fd.label))
            value = int(value)
        if isinstance(value, float):
            new = int(round(value * (1 << shift)))
        elif shift and value == raw >> shift:
            new = raw
        else:
            new = value << shift if value >= 0 else -1
        if not fd.min << shift <= new <= fd.raw_max:
            raise CharError(T('ch.err.field_range', '{label}: {value} cannot be stored, the file holds {lo} to {hi}',
                              label=fd.label, value=value, lo=fd.min, hi=fd.max))
        self.set_stat(sid, new)
        if key == 'level':
            self.head[0x2B] = new

    def set_field_raw(self, key, raw):
        """Like set_field with the stored integer (life / mana / stamina in 1/256 of a point)."""
        f, _cur = self._field_raw(key)
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise CharError(T('ch.err.field_number', '{label}: a number is expected', label=f[3]))
        self.set_field(key, raw / (1 << f[2]) if f[2] else raw)

    def set_level_raw(self, level):
        """Sets the level only (header byte and stat 12), down or up, without the game's level-up gains."""
        self.set_field('level', level)

    def exp_range(self, level=None):
        """(first, last) experience of a level (default: the character's) in the game table."""
        return level_exp_range(self.data, self.cls, self.level if level is None else level)

    def match_exp_to_level(self):
        """Moves the experience into the range of the current level when it is outside. Returns the experience."""
        lo, hi = self.exp_range()
        exp = self.stat(STAT_EXP)
        if not lo <= exp <= hi:
            exp = lo
            self.set_field('experience', exp)
        return exp

    def match_level_to_exp(self):
        """Sets the level the game table gives for the current experience (raw: nothing else changes)."""
        level = level_for_exp(self.data, self.cls, self.stat(STAT_EXP))
        self.set_field('level', level)
        return level

    def level_consistent(self):
        """True when the header level byte and the level stat agree."""
        return self.head[0x2B] == self.stat(STAT_LEVEL)

    # ------------------------------------------------------------------ status flags / progression / name
    @property
    def status(self):
        return self.head[0x24]

    def flags(self):
        """{'expansion', 'ladder', 'hardcore', 'died': bool} from the status byte (header 0x24)."""
        return {k: bool(self.head[0x24] & bit) for k, bit in STATUS_FLAGS.items()}

    def set_flag(self, key, on):
        """Sets or clears one status flag; the other bits of the byte are kept."""
        bit = STATUS_FLAGS.get(key)
        if bit is None:
            raise CharError(T('ch.err.flag', 'unknown character flag: {flag}', flag=key))
        self.head[0x24] = (self.head[0x24] | bit) if on else (self.head[0x24] & ~bit & 0xFF)

    def set_flags(self, **flags):
        for k in flags:
            if k not in STATUS_FLAGS:
                raise CharError(T('ch.err.flag', 'unknown character flag: {flag}', flag=k))
        for k, on in flags.items():
            self.set_flag(k, on)

    def set_progression(self, value):
        """Progression / title byte (header 0x25), 0..255: 5 per finished difficulty plus the acts finished in the
        current one (an expansion character: 5 = Normal done, 10 = Nightmare done, 15 = Hell done)."""
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            raise CharError(T('ch.err.progression', 'progression: 0 to 255'))
        self.head[0x25] = value

    @property
    def difficulties_done(self):
        """Number of difficulties finished (0..3): what unlocks Nightmare (1) and Hell (2)."""
        return min(3, self.head[0x25] // 5)

    def set_difficulties_done(self, n):
        """Sets the number of finished difficulties (0..3). The acts part of the byte is kept when the count does
        not change, and restarts at 0 otherwise."""
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 3:
            raise CharError(T('ch.err.difficulties', 'finished difficulties: 0 to 3'))
        if self.difficulties_done != n:
            self.head[0x25] = 5 * n

    def set_name(self, name):
        """Writes the name in the header only (game rule checked). The game needs the file to carry the same name:
        use rename() to save under the new name and move the companion files."""
        check_name(name)
        self.head[0x14:0x24] = name.encode('ascii').ljust(16, b'\0')

    def rename(self, new_name, backup=True):
        """Renames the character on disk: the save is written (with any pending change) as <new_name>.d2s through
        the safe writer, the companion files (.key, .map, .ma0-3, .stash) are renamed, the old .d2s is removed
        (kept as a backup when `backup`). Returns (new path, backup or None). Nothing changes on a refusal."""
        from mxl_save import commit_file, load_character, check_game_closed, make_backup, EditError
        check_game_closed()
        check_name(new_name)
        old_path, old_name = self.path, bytes(self.head[0x14:0x24])
        folder = os.path.dirname(old_path)
        old = os.path.splitext(os.path.basename(old_path))[0]
        if new_name == old:
            raise CharError(T('ch.err.same_name', 'the character already has this name'))
        mates = companion_files(old_path)
        taken = {fn.lower() for fn in os.listdir(folder)}
        same_file = new_name.lower() == old.lower()          # case-only change: same file on Windows
        wanted = [new_name + '.d2s'] + [new_name + os.path.splitext(fn)[1] for fn in mates]
        if not same_file and any(w.lower() in taken for w in wanted):
            raise CharError(T('ch.err.exists', '{name} already exists', name=new_name))
        try:
            with open(old_path, 'rb') as f:
                on_disk = f.read()
        except OSError as e:
            raise CharError(str(e))
        if on_disk != self.raw:
            raise CharError(T('ch.err.changed', 'the character file changed on disk since it was read (game or another '
                              'window): it has been reloaded, try again'))
        dst = os.path.join(folder, new_name + '.d2s')
        self.set_name(new_name)
        content = self.build()

        def verify(tmp):
            try:
                c = Character(tmp, self.data)
                load_character(tmp, self.data)
            except Exception as e:
                raise EditError(T('ch.err.verify', 'check after writing failed: {error}', error=e))
            if c.name != new_name or c.build() != content:
                raise EditError(T('ch.err.verify_name', 'check after writing failed: name'))
        bak = None
        try:
            if backup:
                bak = make_backup(old_path)
            commit_file(dst, content, verify, False)
        except (EditError, OSError) as e:
            self.head[0x14:0x24] = old_name
            raise CharError(str(e))
        for fn in mates:
            os.replace(os.path.join(folder, fn), os.path.join(folder, new_name + os.path.splitext(fn)[1]))
        if os.path.exists(old_path) and not (os.path.exists(dst) and os.path.samefile(old_path, dst)):
            os.remove(old_path)
        self.path = dst
        self.raw = content
        self.parse(content)
        return dst, bak

    # ------------------------------------------------------------------ class / skills
    def skill_levels(self):
        """{skill id: hard-point level} of the character's own skills, from the 'if' section:
        one byte per skill of the class, in skills.bin row order (the save's own order)."""
        ids = class_skills(self.data, self.cls)
        body = self.skills[2:]
        return {sid: (body[i] if i < len(body) else 0) for i, sid in enumerate(ids)}

    def set_skill_levels(self, levels):
        """Rewrites the 'if' section: one byte per class skill (save order); ids missing from
        `levels` become 0. Values are clamped to 0..255 (the save's own width)."""
        body = bytes(max(0, min(255, int(levels.get(sid, 0)))) for sid in class_skills(self.data, self.cls))
        self.skills = b'if' + body

    def set_class(self, cls):
        """Changes the class: the class byte in the header plus a fresh (all-zero) skills section of
        the new class - the old levels belong to the previous class's skills and cannot be kept."""
        self.head[0x28] = cls
        self.set_skill_levels({})

    # ------------------------------------------------------------------ level
    def set_level(self, level):
        """Raises the level like the game does: experience = start of the level; per level gained: stat points,
        1 skill point, life / mana / stamina per level (charstats). Lowering a level is refused (not possible in game)."""
        d = self.data
        cur = self.level
        top = max_level(d, self.cls)
        if not cur <= level <= top:
            raise CharError(T('ch.err.level', 'level must be {lo} to {hi} (a level cannot be lowered)', lo=cur, hi=top))
        gained = level - cur
        if not gained:
            return
        cs = _charstats(d)[self.cls]
        self.head[0x2B] = level
        self.set_stat(12, level)
        exp = exp_for_level(d, self.cls, level)
        if exp is not None and exp > self.stat(13):
            self.set_stat(13, exp)
        self.set_stat(4, self.stat(4) + cs['stats'] * gained)
        self.set_stat(5, self.stat(5) + gained)
        for cur_id, max_id, per in ((6, 7, cs['life']), (8, 9, cs['mana']), (10, 11, cs['stamina'])):
            if per:
                new_max = self.stat(max_id) + (per << 6) * gained
                self.set_stat(max_id, new_max)
                self.set_stat(cur_id, new_max)

    # ------------------------------------------------------------------ quests / waypoints
    def quest_word(self, diff, word):
        return struct.unpack_from('<H', self.head, QUEST_DATA + 96 * diff + 2 * word)[0]

    def set_quest_word(self, diff, word, value):
        struct.pack_into('<H', self.head, QUEST_DATA + 96 * diff + 2 * word, value)

    def quest_done(self, diff, word):
        return bool(self.quest_word(diff, word) & 1)

    def set_quests(self, diff, done_words):
        """done_words: set of quest words to mark completed in this difficulty (others are left as they are when
        already done in game, or cleared when they were only marked). The words the game sets beside a finished
        quest follow, only for an act in which a quest is marked by this call and only while they are still 0 (a
        word the game wrote - or left at 0 in an act played in game, like Nightmare's act III introduction of the
        samples - is never changed): the act's introduction (1), and "travelled to the next act" (1) when the
        act's last quest is the one marked. Word 41 is not touched (see the table above ACTS)."""
        for act, intro, quests, travel in ACTS:
            marked = set()
            for word, _ in quests:
                if word in done_words:
                    if not self.quest_done(diff, word):
                        self.set_quest_word(diff, word, QUEST_DONE)
                        self.quest_reward(word, +1)
                        marked.add(word)
                elif self.quest_word(diff, word) == QUEST_DONE:
                    self.set_quest_word(diff, word, 0)
                    self.quest_reward(word, -1)
            if marked and not self.quest_word(diff, intro):
                self.set_quest_word(diff, intro, 1)
            if travel is not None and ACT_LAST_QUEST[travel] in marked and not self.quest_word(diff, travel):
                self.set_quest_word(diff, travel, 1)
        prog = 0
        for k in range(3):
            if self.quest_done(k, LAST_QUEST_WORD):
                prog = 5 * (k + 1)
        if prog > self.head[0x25]:
            self.head[0x25] = prog

    def quest_reward(self, word, sign):
        """Gives (sign +1) or takes back (sign -1, when a quest marked here is unmarked) the quest's reward."""
        r = QUEST_REWARDS.get(word)
        if r is None:
            return
        kind, n = r
        log = self.__dict__.setdefault('reward_log', {})
        log[kind] = log.get(kind, 0) + sign * n
        if kind == 'skill':
            self.set_stat(5, max(0, self.stat(5) + sign * n))
        elif kind == 'stats':
            self.set_stat(4, max(0, self.stat(4) + sign * n))
        else:                                   # life: stats 6 / 7 are stored as 1/256 points
            for sid in (7, 6):
                self.set_stat(sid, max(1 << 8, self.stat(sid) + sign * (n << 8)))

    def waypoint(self, diff, n):
        return bool(self.head[WP_DATA + 24 * diff + 2 + n // 8] >> (n % 8) & 1)

    def set_waypoints(self, diff, active):
        base = WP_DATA + 24 * diff
        self.head[base] = 2
        self.head[base + 1] = 1
        for n in waypoint_ids(diff):
            i = base + 2 + n // 8
            if n in active or n == 0:
                self.head[i] |= 1 << (n % 8)
            else:
                self.head[i] &= ~(1 << (n % 8)) & 0xFF

    # ------------------------------------------------------------------ items
    def entries(self, merc=False):
        return (self.merc_items if self.merc_items is not None else []) if merc else self.items

    def equipped(self, merc=False):
        return {e.it['equipped']: e for e in self.entries(merc) if e.it['location'] == LOC_EQUIPPED}

    def inventory(self):
        return [e for e in self.items if e.it['location'] == LOC_STORED and e.it['panel'] == PANEL_INVENTORY]

    def slot_error(self, it, slot, merc=False, ignore=None):
        """None if the item can go in this equipment slot, else the reason."""
        d = self.data
        if merc and slot not in MERC_SLOTS:
            return T('ch.err.merc_slots2', 'mercenaries have no ring slots and no second weapon set')
        locs = item_bodylocs(d, it['code'])
        if SLOTS[slot] not in locs:
            return T('ch.err.cannot_equip', '{item} cannot be equipped as {slot}', item=d.base(it['code']).name, slot=slot_name(slot))
        eq = self.equipped(merc)
        cur = eq.get(slot)
        if cur is not None and cur is not ignore:
            return T('ch.err.slot_full', '{slot} is not empty', slot=slot_name(slot))
        pair = {4: 5, 5: 4, 11: 12, 12: 11}.get(slot)
        if pair:
            other = eq.get(pair)
            if other is not None and other is not ignore:
                if d.base(it['code']).two_handed or d.base(other.it['code']).two_handed:
                    return T('ch.err.two_hand', 'a two-handed weapon needs the other hand empty')
        return None

    def inventory_error(self, it, x, y, ignore=None):
        w, h = self.data.base(it['code']).size
        if not (0 <= x and 0 <= y and x + w <= INV_W and y + h <= INV_H):
            return T('ch.err.outside_inv', 'outside the inventory')
        for e in self.inventory():
            if e is ignore:
                continue
            ow, oh = self.data.base(e.it['code']).size
            ex, ey = e.it['x'], e.it['y']
            if x < ex + ow and ex < x + w and y < ey + oh and ey < y + h:
                return T('ch.err.overlaps', 'overlaps {item}', item=e.it['name'])
        return None

    def free_inventory_spot(self, it):
        w, h = self.data.base(it['code']).size
        for x in range(INV_W - w + 1):
            for y in range(INV_H - h + 1):
                if self.inventory_error(it, x, y) is None:
                    return x, y
        return None

    def place(self, blob, where, merc=False):
        """Adds an item (bytes incl. socketed items, from a stash or the creator) at where = ('slot', n) or
        ('inv', x, y). Returns the new Entry."""
        d = self.data
        it = blob_item(blob, d)
        if where[0] == 'slot':
            err = self.slot_error(it, where[1], merc)
            if err:
                raise CharError(err)
            new = Entry(None, Entry(it, blob).moved(d, location=LOC_EQUIPPED, equipped=where[1], x=where[1], y=0, panel=0))
        else:
            if merc:
                raise CharError(T('ch.err.merc_no_inv', 'the mercenary has no inventory'))
            err = self.inventory_error(it, where[1], where[2])
            if err:
                raise CharError(err)
            new = Entry(None, Entry(it, blob).moved(d, location=LOC_STORED, equipped=0, x=where[1], y=where[2],
                                                    panel=PANEL_INVENTORY))
        new.it = blob_item(new.blob, d)
        lst = self.entries(merc)
        if merc and self.merc_items is None:
            raise CharError(T('ch.err.no_merc', 'no mercenary hired'))
        lst.append(new)
        return new

    def remove(self, entry, merc=False):
        lst = self.entries(merc)
        lst.remove(entry)

    def move(self, entry, where, merc=False):
        """Moves an item inside the character (slot <-> inventory)."""
        d = self.data
        it = entry.it
        if where[0] == 'slot':
            err = self.slot_error(it, where[1], merc, ignore=entry)
            if err:
                raise CharError(err)
            entry.blob = entry.moved(d, location=LOC_EQUIPPED, equipped=where[1], x=where[1], y=0, panel=0)
        else:
            err = self.inventory_error(it, where[1], where[2], ignore=entry)
            if err:
                raise CharError(err)
            entry.blob = entry.moved(d, location=LOC_STORED, equipped=0, x=where[1], y=where[2], panel=PANEL_INVENTORY)
        entry.it = blob_item(entry.blob, d)

    def stash_blob(self, entry):
        """Bytes of the item as a stash item (location stored, stash panel); position set by the stash writer."""
        return entry.moved(self.data, location=LOC_STORED, equipped=0, x=0, y=0, panel=5)

    # ------------------------------------------------------------------ saving
    def save(self, backup=True):
        """Writes the character (collector's safe writer: game closed, verification, backup). Returns the backup."""
        from mxl_save import commit_file, load_character, EditError
        content = self.build()
        n_items = len(self.items)
        n_merc = None if self.merc_items is None else len(self.merc_items)

        def verify(tmp):
            try:
                c = Character(tmp, self.data)
                load_character(tmp, self.data)
            except Exception as e:
                raise EditError(T('ch.err.verify', 'check after writing failed: {error}', error=e))
            if len(c.items) != n_items or (None if c.merc_items is None else len(c.merc_items)) != n_merc:
                raise EditError(T('ch.err.verify_count', 'check after writing failed: item count'))
        try:
            with open(self.path, 'rb') as f:
                on_disk = f.read()
        except OSError:
            on_disk = None
        if on_disk is not None and on_disk != self.raw:
            raise CharError(T('ch.err.changed', 'the character file changed on disk since it was read (game or another '
                              'window): it has been reloaded, try again'))
        try:
            bak = commit_file(self.path, content, verify, backup)
        except EditError as e:
            raise CharError(str(e))
        self.raw = content
        self.parse(content)
        return bak

    # ------------------------------------------------------------------ generic header access
    def header_u32(self, off):
        return struct.unpack_from('<I', self.head, off)[0]

    def set_header_u32(self, off, value):
        struct.pack_into('<I', self.head, off, value)


def blob_item(blob, data):
    from mxl_save import blob_item as _bi
    return _bi(blob, data)


def copy_character(path, new_name, data):
    """Copies a character (save, map, key and stash files) under a new name. Returns the new .d2s path."""
    from mxl_save import check_game_closed
    check_game_closed()
    if not (2 <= len(new_name) <= 15) or not all(c.isalpha() or c in '-_' for c in new_name):
        raise CharError(T('ch.err.name', 'name: 2 to 15 letters (- and _ allowed)'))
    folder = os.path.dirname(path)
    dst = os.path.join(folder, new_name + '.d2s')
    if os.path.exists(dst):
        raise CharError(T('ch.err.exists', '{name} already exists', name=new_name))
    c = Character(path, data)
    c.head[0x14:0x24] = new_name.encode('latin1').ljust(16, b'\0')
    content = c.build()
    with open(dst, 'wb') as f:
        f.write(content)
    for fn in companion_files(path):
        shutil.copy2(os.path.join(folder, fn), os.path.join(folder, new_name + os.path.splitext(fn)[1]))
    return dst
