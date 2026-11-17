"""Character file <name>.d2s (file version 96, Median XL Sigma 2.14.x) - docs/SAVE_FORMAT.md, sections 1 to 5.

    offset  size  section
    0x000   335   header (fixed fields)
    0x14F   298   quests       'Woo!'  3 difficulties x 48 words
    0x279    80   waypoints    'WS'    3 difficulties x 24 bytes
    0x2C9    52   NPC          01 'w'  3 + 3 x 8 bytes
    0x2FD   var.  stats        'gf'    bit stream of [9-bit id][param][value], ended by 0x1FF
            var.  skills       'if'    one byte per class skill (95 in 2.14.x)
            var.  items        'JM' count, items
            var.  corpses      'JM' count, per corpse: 12 bytes + 'JM' count, items
            var.  mercenary    'jf' [+ 'JM' count, items when a mercenary is hired]
            3+    golem        'kf' has_item [+ item]

Without game tables (tables=None) the stats section can still be read for the stats whose widths are built in
(DEFAULT_CSV), and everything from the first 'JM' on is kept as raw bytes (`items_raw`).
"""
import struct
from dataclasses import dataclass, field
from typing import Optional

from .bits import BitReader, BitWriter, FormatError
from .items import parse_item, parse_item_list, build_item_list

MAGIC = 0xAA55AA55
HEADER_SIZE = 0x14F
QUEST_OFF, WAYPOINT_OFF, NPC_OFF, STATS_OFF = 0x14F, 0x279, 0x2C9, 0x2FD
QUEST_WORDS = 48
DIFFICULTIES = ('Normal', 'Nightmare', 'Hell')
CLASSES = ('Amazon', 'Sorceress', 'Necromancer', 'Paladin', 'Barbarian', 'Druid', 'Assassin')

# header status byte (0x24)
STATUS_HARDCORE, STATUS_DIED, STATUS_EXPANSION, STATUS_LADDER = 0x04, 0x08, 0x20, 0x40

# character stats section: {stat id: (param bits, value bits)} as itemstatcost.bin has them in 2.14.x
# (CSvParam / CSvBits). Used only when no tables are given.
DEFAULT_CSV = {0: (0, 11), 1: (0, 11), 2: (0, 11), 3: (0, 11), 4: (0, 11), 5: (0, 9), 6: (0, 21), 7: (0, 21),
               8: (0, 21), 9: (0, 21), 10: (0, 21), 11: (0, 21), 12: (0, 8), 13: (0, 32), 14: (0, 25),
               15: (0, 25), 88: (16, 32), 185: (0, 12), 186: (0, 8)}
STAT_NAMES = {0: 'strength', 1: 'energy', 2: 'dexterity', 3: 'vitality', 4: 'stat points', 5: 'skill points',
              6: 'life', 7: 'max life', 8: 'mana', 9: 'max mana', 10: 'stamina', 11: 'max stamina', 12: 'level',
              13: 'experience', 14: 'gold', 15: 'stash gold', 88: 'achievement counter',
              185: 'signets of learning used', 186: 'signets of skill used'}
FIXED_POINT_STATS = (6, 7, 8, 9, 10, 11)       # value / 256
ACHIEVEMENT_STAT = 88                          # param < 0x2000: monstats id (kill count); >= 0x2000: counters

# quest words: (act, intro word, first quest word, quest count, "act finished" word)
QUEST_LAYOUT = (('Act I', 0, 1, 6, 7), ('Act II', 8, 9, 6, 15), ('Act III', 16, 17, 6, 23),
                ('Act IV', 24, 25, 3, 28), ('Act V', 32, 35, 6, None))
QUEST_NAMES = {1: 'Den of Evil', 2: "Sisters' Burial Grounds", 3: 'Tools of the Trade', 4: 'The Search for Cain',
               5: 'The Forgotten Tower', 6: 'Sisters to the Slaughter', 9: "Radament's Lair",
               10: 'The Horadric Staff', 11: 'Tainted Sun', 12: 'Arcane Sanctuary', 13: 'The Summoner',
               14: 'The Seven Tombs', 17: "Lam Esen's Tome", 18: "Khalim's Will", 19: 'Blade of the Old Religion',
               20: 'The Golden Bird', 21: 'The Blackened Temple', 22: 'The Guardian', 25: 'The Fallen Angel',
               26: "Terror's End", 27: "Hell's Forge", 35: 'Siege on Harrogath', 36: 'Rescue on Mount Arreat',
               37: 'Prison of Ice', 38: 'Betrayal of Harrogath', 39: 'Rite of Passage', 40: 'Eve of Destruction'}
QUEST_BITS = {0: 'completed', 1: 'requirements met', 2: 'given', 3: 'left town', 4: 'entered area',
              12: 'closed in log', 13: 'done this game'}       # vanilla meaning of the bits; others custom


def checksum(data):
    """The file checksum (stored at 0x0C): over every byte with the checksum field taken as zero,
    sum = rotate_left_32(sum, 1) + byte."""
    s = 0
    for i, x in enumerate(data):
        if 12 <= i < 16:
            x = 0
        s = ((s << 1) | (s >> 31)) & 0xFFFFFFFF
        s = (s + x) & 0xFFFFFFFF
    return s


@dataclass
class Header:
    """The 335 fixed bytes before the quests. Offsets in the comments."""
    magic: int = MAGIC                 # 0x00 u32  0xAA55AA55
    version: int = 96                  # 0x04 u32  96 (0x60), the 1.10+ file version
    file_size: int = 0                 # 0x08 u32  recomputed by to_bytes()
    checksum: int = 0                  # 0x0C u32  recomputed by to_bytes()
    active_weapon: int = 0             # 0x10 u32  weapon set in use (0 / 1)
    name: bytes = b''                  # 0x14 16 bytes, zero padded
    status: int = 0                    # 0x24 u8   0x04 hardcore, 0x08 died, 0x20 expansion, 0x40 ladder
    progression: int = 0               # 0x25 u8   acts finished: +1 Andariel, Duriel, Mephisto, +2 Baal (5/difficulty)
    unknown_26: int = 0                # 0x26 u16  0 in every sample
    cls: int = 0                       # 0x28 u8   0 Amazon .. 6 Assassin
    unknown_29: int = 0x10             # 0x29 u8   0x10 in every sample (vanilla: 0x10)
    unknown_2a: int = 0x5F             # 0x2A u8   0x5F in every sample (vanilla: 0x1E)
    level: int = 1                     # 0x2B u8   copy of stat 12
    created: int = 0                   # 0x2C u32  0 in every sample
    last_played: int = 0               # 0x30 u32  Unix time of the last save
    unknown_34: int = 0xFFFFFFFF       # 0x34 u32  0xFFFFFFFF in every sample
    hotkeys: list = field(default_factory=lambda: [0xFFFF] * 16)   # 0x38 16 x u32: skill id (| 0x8000 left hand), 0xFFFF none
    left_skill: int = 0                # 0x78 u32
    right_skill: int = 0               # 0x7C u32
    left_skill_swap: int = 0           # 0x80 u32  weapon set II
    right_skill_swap: int = 0          # 0x84 u32
    appearance: bytes = b''            # 0x88 32 bytes: 16 component pictures + 16 component tints (0xFF none)
    difficulty: bytes = b'\0\0\0'      # 0xA8 3 bytes, one per difficulty: 0x80 = last played, low 3 bits = act - 1
    map_seed: int = 0                  # 0xAB u32  seed of the last game (also the newest entry of <name>.map)
    unknown_af: int = 0                # 0xAF u16  0 in every sample
    merc_dead: int = 0                 # 0xB1 u16  not 0 = the mercenary is dead
    merc_id: int = 0                   # 0xB3 u32  0 = no mercenary; else its unit id / seed
    merc_name: int = 0                 # 0xB7 u16  index into the hireling's name list
    merc_type: int = 0                 # 0xB9 u16  row of hireling.bin
    merc_exp: int = 0                  # 0xBB u32  experience
    reserved: bytes = b''              # 0xBF 144 bytes, all zero in every sample

    _FMT = '<IIIII16sBBHBBBBIII16IIIII32s3sIHHIHHI144s'

    @classmethod
    def parse(cls, b):
        v = struct.unpack_from(cls._FMT, b, 0)
        assert struct.calcsize(cls._FMT) == HEADER_SIZE
        h = cls(*v[:16], list(v[16:32]), *v[32:])
        if h.magic != MAGIC:
            raise FormatError('not a character file (magic)')
        return h

    def to_bytes(self):
        return struct.pack(self._FMT, self.magic, self.version, self.file_size, self.checksum, self.active_weapon,
                           self.name, self.status, self.progression, self.unknown_26, self.cls, self.unknown_29,
                           self.unknown_2a, self.level, self.created, self.last_played, self.unknown_34,
                           *self.hotkeys, self.left_skill, self.right_skill, self.left_skill_swap,
                           self.right_skill_swap, self.appearance, self.difficulty, self.map_seed, self.unknown_af,
                           self.merc_dead, self.merc_id, self.merc_name, self.merc_type, self.merc_exp,
                           self.reserved)

    @property
    def name_str(self):
        return self.name.split(b'\0')[0].decode('latin1')

    def last_difficulty(self):
        """(difficulty index, act 1..5) the character was last in, or None."""
        for i, x in enumerate(self.difficulty):
            if x & 0x80:
                return i, (x & 7) + 1
        return None


@dataclass
class Quests:
    """'Woo!' + u32 version (6) + u16 size (298) + 3 x 48 little-endian words."""
    version: int = 6
    size: int = 298
    words: list = field(default_factory=lambda: [[0] * QUEST_WORDS for _ in range(3)])

    @classmethod
    def parse(cls, b, off=QUEST_OFF):
        if b[off:off + 4] != b'Woo!':
            raise FormatError("quests: 'Woo!' expected")
        version, size = struct.unpack_from('<IH', b, off + 4)
        words = [list(struct.unpack_from(f'<{QUEST_WORDS}H', b, off + 10 + 96 * d)) for d in range(3)]
        return cls(version, size, words)

    def to_bytes(self):
        return b'Woo!' + struct.pack('<IH', self.version, self.size) + b''.join(
            struct.pack(f'<{QUEST_WORDS}H', *w) for w in self.words)


@dataclass
class Waypoints:
    """'WS' + u32 version (1) + u16 size (80) + 3 x 24 bytes: u16 0x0102, then a bit field of 176 bits
    (bit n = waypoint n: 0..38 the vanilla ones, 50 / 60 / 61 / 70 / 71 / 72 / 80 / 90 Median XL's)."""
    version: int = 1
    size: int = 80
    lead: list = field(default_factory=lambda: [0x0102] * 3)
    bits: list = field(default_factory=lambda: [bytes(22)] * 3)

    @classmethod
    def parse(cls, b, off=WAYPOINT_OFF):
        if b[off:off + 2] != b'WS':
            raise FormatError("waypoints: 'WS' expected")
        version, size = struct.unpack_from('<IH', b, off + 2)
        lead = [struct.unpack_from('<H', b, off + 8 + 24 * d)[0] for d in range(3)]
        bits = [bytes(b[off + 10 + 24 * d:off + 32 + 24 * d]) for d in range(3)]
        return cls(version, size, lead, bits)

    def to_bytes(self):
        return b'WS' + struct.pack('<IH', self.version, self.size) + b''.join(
            struct.pack('<H', self.lead[d]) + self.bits[d] for d in range(3))

    def active(self, diff):
        v = int.from_bytes(self.bits[diff], 'little')
        return [n for n in range(176) if v >> n & 1]


@dataclass
class Npcs:
    """0x01 'w' + u16 size (52) + 3 x u64 "introduced" + 3 x u64 "congratulated" (one bit per NPC)."""
    size: int = 52
    intro: list = field(default_factory=lambda: [0, 0, 0])
    congrats: list = field(default_factory=lambda: [0, 0, 0])

    @classmethod
    def parse(cls, b, off=NPC_OFF):
        if b[off:off + 2] != b'\x01w':
            raise FormatError("NPC section: 01 'w' expected")
        size = struct.unpack_from('<H', b, off + 2)[0]
        v = struct.unpack_from('<6Q', b, off + 4)
        return cls(size, list(v[:3]), list(v[3:]))

    def to_bytes(self):
        return b'\x01w' + struct.pack('<H6Q', self.size, *self.intro, *self.congrats)


@dataclass
class CharStat:
    id: int
    param: Optional[int]
    value: int


@dataclass
class Corpse:
    """One corpse: 12 bytes (vanilla: u32 unknown, u32 x, u32 y) + an item list. No sample has a corpse."""
    head: bytes
    items: list


@dataclass
class D2S:
    header: Header
    quests: Quests
    waypoints: Waypoints
    npcs: Npcs
    stats: list                         # [CharStat], in file order (sorted by id, then param)
    skills: bytes                       # one level byte per class skill
    items: Optional[list] = None        # [Item] - None when parsed without tables
    corpses: Optional[list] = None      # [Corpse]
    has_merc_section: bool = False      # 'jf' present (expansion characters)
    merc_items: Optional[list] = None   # None: no 'JM' list after 'jf' (no mercenary)
    has_golem_section: bool = False     # 'kf' present
    golem_item: Optional[object] = None  # Item of the iron golem, when 'kf' is followed by 1
    trailing: bytes = b''               # bytes after the golem section (none in every sample)
    items_raw: Optional[bytes] = None   # without tables: everything from the first 'JM' to the end of the file

    # ------------------------------------------------------------------ reader
    @classmethod
    def parse(cls, b, tables=None):
        header = Header.parse(b)
        quests, waypoints, npcs = Quests.parse(b), Waypoints.parse(b), Npcs.parse(b)
        if b[STATS_OFF:STATS_OFF + 2] != b'gf':
            raise FormatError("stats: 'gf' expected at 0x2FD")
        widths = ({k: (s.csv_param, s.csv_bits) for k, s in tables.stats.items() if s.csv_bits}
                  if tables else DEFAULT_CSV)
        br = BitReader(b, STATS_OFF + 2)
        stats = []
        while True:
            sid = br.read(9)
            if sid == 0x1FF:
                break
            if sid not in widths:
                raise FormatError(f'character stat {sid}: width unknown')
            pb, vb = widths[sid]
            param = br.read(pb) if pb else None
            stats.append(CharStat(sid, param, br.read(vb)))
        if br.read_padding():
            raise FormatError('stats: non-zero padding bits')
        p = STATS_OFF + 2 + br.bytes_used()
        if b[p:p + 2] != b'if':
            raise FormatError("skills: 'if' expected after the stats")
        if tables:
            n = len(tables.class_skills(header.cls))
        else:
            n = b.find(b'JM', p + 2) - p - 2
        skills = bytes(b[p + 2:p + 2 + n])
        p += 2 + n
        if b[p:p + 2] != b'JM':
            raise FormatError("items: 'JM' expected after the skills")
        self = cls(header, quests, waypoints, npcs, stats, skills)
        if not tables:
            self.items_raw = bytes(b[p:])
            return self
        count = struct.unpack_from('<H', b, p + 2)[0]
        self.items, p = parse_item_list(b, p + 4, count, tables)
        if b[p:p + 2] != b'JM':
            raise FormatError("corpses: 'JM' expected after the items")
        ncorpse = struct.unpack_from('<H', b, p + 2)[0]
        p += 4
        self.corpses = []
        for _ in range(ncorpse):
            head = bytes(b[p:p + 12])
            p += 12
            if b[p:p + 2] != b'JM':
                raise FormatError("corpse: 'JM' expected")
            n = struct.unpack_from('<H', b, p + 2)[0]
            items, p = parse_item_list(b, p + 4, n, tables)
            self.corpses.append(Corpse(head, items))
        if b[p:p + 2] == b'jf':
            self.has_merc_section = True
            p += 2
            if b[p:p + 2] == b'JM':
                n = struct.unpack_from('<H', b, p + 2)[0]
                self.merc_items, p = parse_item_list(b, p + 4, n, tables)
        if b[p:p + 2] == b'kf':
            self.has_golem_section = True
            has = b[p + 2]
            p += 3
            if has:
                self.golem_item = parse_item(b, p, tables)
                p += self.golem_item.size
                for _ in range(self.golem_item.socketed_count if self.golem_item.flag(11) else 0):
                    sub = parse_item(b, p, tables)
                    p += sub.size
                    self.golem_item.socketed.append(sub)
        self.trailing = bytes(b[p:])
        return self

    # ------------------------------------------------------------------ writer
    def stats_bytes(self, tables=None):
        widths = ({k: (s.csv_param, s.csv_bits) for k, s in tables.stats.items() if s.csv_bits}
                  if tables else DEFAULT_CSV)
        w = BitWriter()
        for st in self.stats:
            pb, vb = widths[st.id]
            w.write(9, st.id)
            if pb:
                w.write(pb, st.param or 0)
            w.write(vb, st.value)
        w.write(9, 0x1FF)
        return b'gf' + w.to_bytes()

    def to_bytes(self, tables=None):
        """The whole file, with the size (0x08) and the checksum (0x0C) recomputed."""
        out = bytearray(self.header.to_bytes())
        out += self.quests.to_bytes() + self.waypoints.to_bytes() + self.npcs.to_bytes()
        out += self.stats_bytes(tables)
        out += b'if' + self.skills
        if self.items_raw is not None:
            out += self.items_raw
        else:
            if tables is None:
                raise FormatError('the item sections need the game tables')
            out += build_item_list(self.items, tables)
            out += b'JM' + struct.pack('<H', len(self.corpses))
            for c in self.corpses:
                out += c.head + build_item_list(c.items, tables)
            if self.has_merc_section:
                out += b'jf'
                if self.merc_items is not None:
                    out += build_item_list(self.merc_items, tables)
            if self.has_golem_section:
                out += b'kf' + bytes([self.golem_item is not None])
                if self.golem_item is not None:
                    out += self.golem_item.to_bytes_with_socketed(tables)
            out += self.trailing
        struct.pack_into('<I', out, 8, len(out))
        struct.pack_into('<I', out, 12, 0)
        struct.pack_into('<I', out, 12, checksum(out))
        return bytes(out)

    # ------------------------------------------------------------------ convenience
    def stat(self, sid, param=None):
        return next((s.value for s in self.stats if s.id == sid and (param is None or s.param == param)), 0)

    def skill_levels(self, tables):
        return dict(zip(tables.class_skills(self.header.cls), self.skills))

    def as_dict(self, tables=None):
        h = self.header
        hd = {k: (v.hex() if isinstance(v, bytes) else v) for k, v in h.__dict__.items()}
        hd['name'] = h.name_str
        d = dict(kind='d2s', header=hd,
                 quests=dict(version=self.quests.version, size=self.quests.size, words=self.quests.words),
                 waypoints=dict(version=self.waypoints.version, size=self.waypoints.size, lead=self.waypoints.lead,
                                active=[self.waypoints.active(k) for k in range(3)]),
                 npcs=dict(size=self.npcs.size, intro=self.npcs.intro, congrats=self.npcs.congrats),
                 stats=[s.__dict__ for s in self.stats], skills=list(self.skills))
        if self.items is not None:
            d['items'] = [i.as_dict(tables) for i in self.items]
            d['corpses'] = [dict(head=c.head.hex(), items=[i.as_dict(tables) for i in c.items])
                            for c in self.corpses]
            d['merc_items'] = None if self.merc_items is None else [i.as_dict(tables) for i in self.merc_items]
            d['golem_item'] = None if self.golem_item is None else self.golem_item.as_dict(tables)
            d['trailing'] = self.trailing.hex()
        else:
            d['items_raw_size'] = len(self.items_raw)
        return d
