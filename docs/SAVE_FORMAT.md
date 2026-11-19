# Median XL Sigma 2.14.x save files — format reference

Byte- and bit-level description of every file the game writes per character and per account, as far as the
evidence goes. The same structure exists as code in `tools/mxlsave/` (pure standard library, independent of the
editor): `python -m mxlsave dump <file>` prints any of these files, `python -m mxlsave verify <file>` rebuilds it
and compares the bytes.

## 0. How to read this document

**Status of every statement**

| Mark | Meaning |
|---|---|
| **C** | confirmed: a reader/writer (editor, host application or `mxlsave`) and the samples agree |
| **K** | from code only: the editor / host reads it that way, no sample exercises it |
| **S** | observed in samples only: no code interprets it; the meaning is inferred from values and differences |
| **V** | vanilla Diablo II 1.13 knowledge, compatible with the samples but not proven for Median XL |
| **U** | unknown |

**Editor column** (what MXL Capybara Editor V2 does today): **E** edits it, **R** reads / shows it, **K** keeps the
bytes as they are (never interpreted), **W** rewrites it automatically (size, checksum).

**Samples** (copies; one character at four moments, plus stashes):

| Id | File | State |
|---|---|---|
| A | `fakesaves/XBone.d2s` | Necromancer level 100, Nightmare act V, 3029 bytes |
| Q | `test_qchar.d2s` | a test copy of the same character, saved 314 s before A (one item less), 3012 bytes |
| B | `honorific-sample/XBone.d2s.bak-…` | level 117, Hell, 4086 bytes |
| C | `honorific-sample/XBone.d2s` | level 117, Hell, later, 4107 bytes |
| — | 2 × `XBone.stash`, 1 backup, 2 × `_sharedstash.shared`, 6 other stashes | 2 656 stash items in total |
| — | 3 × `Mr_Owlie.stash.bak-corrupt-*` | negative samples: both parsers refuse them |
| — | `.key`, `.map`, `.ma0`–`.ma3` of A and C; the game's `default.key` | companions |

All four character files are the same character, so every "S" statement about the header rests on differences
between states of ONE Necromancer. Things no sample contains (corpse, iron golem, ear, personalized item, tome,
hardcore, ladder, a second weapon set in use) are marked K or V.

**Verification**: `tools/mxlsave/tests/selfcheck.py` on all 29 sample files: 26 of 26 valid files rebuild
byte-identically from parsed fields (the 3 corrupt ones are refused), 15 of 15 `.d2s` / stash files also round-trip
without game tables, and every value both implementations decode is equal to the editor's own parser for all 2 947
items (header fields, every stat of every list, sizes, offsets) and all character stats / skills / quest words /
waypoints.

Conventions: integers are little-endian; `u8/u16/u32/u64` unsigned. Bit fields are read least significant bit
first (bit 0 of byte 0 first). Offsets are hexadecimal file offsets unless a section says otherwise.

---

## 1. `<name>.d2s` — overview

| Offset | Size | Section | Marker |
|---|---|---|---|
| 0x000 | 335 | header | `55 AA 55 AA` |
| 0x14F | 298 | quests | `Woo!` |
| 0x279 | 80 | waypoints | `WS` |
| 0x2C9 | 52 | NPC introductions | `01 77` (`\x01w`) |
| 0x2FD | variable | character stats | `gf` |
| after stats | 2 + 95 | skills | `if` |
| after skills | variable | items | `JM` + count |
| | variable | corpses | `JM` + count |
| | variable | mercenary | `jf` |
| | 3 + item | iron golem | `kf` |

Everything up to 0x2FD has a fixed position (**C**: the editor and `mxlsave` use fixed offsets; all four samples
agree). There are **no extra bytes between sections** in 2.14.x: the skills section is exactly `if` + one byte per
class skill and is followed at once by `JM` (**C**, all samples; an older note about "extra bytes after the skills
section" does not apply to this version — vanilla has 30 skill bytes, Median XL has 95).

## 2. Header (0x000–0x14E)

`mxlsave.d2s.Header` parses every field below with one `struct` format and rebuilds the 335 bytes from them.

| Offset | Size | Type | Field | Values seen | Status | Editor |
|---|---|---|---|---|---|---|
| 0x00 | 4 | u32 | magic | `0xAA55AA55` | C | R (refuses other values) |
| 0x04 | 4 | u32 | file version | 96 (0x60) — the vanilla 1.10–1.14 number | C | R |
| 0x08 | 4 | u32 | file size in bytes | = real size in all samples | C | W |
| 0x0C | 4 | u32 | checksum (section 2.1) | matches in all samples | C | W |
| 0x10 | 4 | u32 | active weapon set (0 = I, 1 = II) | 0 | V | K |
| 0x14 | 16 | bytes | character name, zero padded | `XBone` | C | E (name + rename of the companion files) |
| 0x24 | 1 | u8 | status flags: 0x04 hardcore, 0x08 died, 0x20 expansion, 0x40 ladder | 0x28 | C for 0x08 / 0x20, V for 0x04 / 0x40 | E (four check boxes) |
| 0x25 | 1 | u8 | progression (section 2.2) | 8 (A), 13 (B, C) | S | E ("character difficulty") |
| 0x26 | 2 | u16 | unknown | 0 | U | K |
| 0x28 | 1 | u8 | class: 0 Amazon, 1 Sorceress, 2 Necromancer, 3 Paladin, 4 Barbarian, 5 Druid, 6 Assassin | 2 | C | E (class change resets the skills) |
| 0x29 | 1 | u8 | unknown, vanilla constant 0x10 | 0x10 | U | K |
| 0x2A | 1 | u8 | unknown, vanilla constant 0x1E; **Median XL writes 0x5F** | 0x5F | S | K |
| 0x2B | 1 | u8 | level (copy of stat 12; shown in the character list) | 100, 117 | C | E (written together with stat 12) |
| 0x2C | 4 | u32 | creation time in vanilla | 0 | V | K |
| 0x30 | 4 | u32 | time of the last save, Unix seconds | Q→A differ by 314 s; C = 2026-11-17 08:45:13 UTC = the file's mtime | S | K |
| 0x34 | 4 | u32 | unknown | `0xFFFFFFFF` | U | K |
| 0x38 | 64 | 16 × u32 | skill hotkeys: skill id, `0x8000` added when bound to the left button, `0xFFFF` = empty | C: 372L Widowmaker, 1751L Tantrum, 1444, 1638 Town Portal, 1415, 377; slot 15 = 551 | S (ids are valid skills of the character; flag meaning V) | K (import writes "none") |
| 0x78 | 4 | u32 | left mouse skill | B 372 → C 1751 | S | K (import writes 0 = Attack) |
| 0x7C | 4 | u32 | right mouse skill | 1444 Deathly Effigy | S | K |
| 0x80 | 4 | u32 | left mouse skill, weapon set II | 0 Attack | V | K |
| 0x84 | 4 | u32 | right mouse skill, weapon set II | 1134 Blink | S | K |
| 0x88 | 16 | 16 × u8 | appearance: picture of each body component for the character-select screen, `0xFF` = none | changes with the equipment between A and B | V (meaning), S (changes) | K |
| 0x98 | 16 | 16 × u8 | appearance: colour tint of each component | A `4C…`, C `42 FF…` | V | K |
| 0xA8 | 3 | 3 × u8 | one byte per difficulty; `0x80` = the character was last in this difficulty, low 3 bits = act − 1 | A `00 84 00` (Nightmare, act V), C `00 00 80` (Hell, act I) | S | K |
| 0xAB | 4 | u32 | map seed of the last game; equals the newest entry of `<name>.map` (section 8.2) | different in every state | S | K |
| 0xAF | 2 | u16 | unknown | 0 | U | K |
| 0xB1 | 2 | u16 | mercenary dead (non-zero = dead) | 0 | V | K |
| 0xB3 | 4 | u32 | mercenary id / seed; 0 = no mercenary | `0x85BB53FB`, constant A→C | C (non-zero ⇔ a mercenary item list exists) | R (`merc_id`, "has a mercenary") |
| 0xB7 | 2 | u16 | mercenary name: index into the name list of its hireling row | 19 | V | K |
| 0xB9 | 2 | u16 | mercenary type: the `Id` column (u32 at +4) of `hireling.bin` | 1 = act 1 rogue row (class 271); the mercenary wears a long bow | S | K |
| 0xBB | 4 | u32 | mercenary experience | A 1 010 150 → C 1 292 640 | S | K |
| 0xBF | 144 | bytes | reserved | all zero | S | K |

### 2.1 Checksum (**C**)

Over the whole file with bytes 0x0C–0x0F taken as zero: `sum = ((sum << 1) | (sum >> 31)) + byte` (32-bit, i.e.
rotate left by one, then add), starting at 0. `mxlsave.d2s.checksum()` and `mxl_char.checksum()` give the stored
value for all four samples. The size at 0x08 must be written before the checksum is computed.

### 2.2 Progression byte (**S**)

A (Nightmare, Diablo dead, in act V) holds 8; B and C (Hell, Diablo dead) hold 13. That fits the vanilla expansion
rule: +1 for Andariel, Duriel and Mephisto, nothing for Diablo, and Baal brings the value to the next multiple of
5 — so 5 / 10 / 15 = Normal / Nightmare / Hell finished. The editor uses `value // 5` as "difficulties finished"
(unlocks Nightmare at 5, Hell at 10). What the game does with values that contradict the quest words is not known.

## 3. Quests, waypoints, NPC section

### 3.1 Quests (0x14F, 298 bytes)

| Offset | Size | Field | Status | Editor |
|---|---|---|---|---|
| 0x14F | 4 | `Woo!` | C | R (required) |
| 0x153 | 4 | u32 version = 6 | S | K |
| 0x157 | 2 | u16 section size = 298 | S | K |
| 0x159 | 3 × 96 | per difficulty (Normal, Nightmare, Hell): 48 × u16 | C | E (partly) |

Word index within one difficulty (file offset = `0x159 + 96·difficulty + 2·word`):

| Word | Meaning | Values seen | Status | Editor |
|---|---|---|---|---|
| 0 | act I introduction heard | 1 once the difficulty was entered | S | E: set to 1 when a quest of the act is ticked |
| 1–6 | act I quests: Den of Evil, Sisters' Burial Grounds, Tools of the Trade, The Search for Cain, The Forgotten Tower, Sisters to the Slaughter | `1001`, `101D`, `804A`, `1019`, `1015`, `9001`, `9011` | C (bit 0), S (rest) | E: writes `0x1001` to mark done, 0 to unmark its own marks |
| 7 | act I finished / travelled to act II | 1 | S | E: set to 1 when all six are ticked |
| 8, 9–14, 15 | act II: intro, Radament's Lair, The Horadric Staff, Tainted Sun, Arcane Sanctuary, The Summoner, The Seven Tombs, finished | | S | E |
| 16, 17–22, 23 | act III: intro, Lam Esen's Tome, Khalim's Will, Blade of the Old Religion, The Golden Bird, The Blackened Temple, The Guardian, finished | | S | E |
| 24, 25–27, 28 | act IV: intro, The Fallen Angel, Terror's End, Hell's Forge, finished | `1301` for Terror's End | S | E |
| 29–31 | unused | 0 | S | K |
| **32** | **act V introduction** | 1 in every difficulty that reached act V | S | **K — the editor writes word 34 instead** |
| 33, 34 | unused | 0 in all samples | S | E (word 34 is set to 1 by the editor as "act V intro"; no sample has it set) |
| 35–40 | act V quests: Siege on Harrogath, Rescue on Mount Arreat, Prison of Ice, Betrayal of Harrogath, Rite of Passage, Eve of Destruction | `8002`, `8022`, `0709`, `8709`, `9709`, `801E`, `0009`, `10C9`, `040D`, `0405`, `000C`, `1001` | S | E (`0x1001`) |
| 41 | not an "act finished" flag: `0x8002` in every difficulty the character has entered — including A's Nightmare where act V was only just reached — and 0 in a difficulty never entered. In vanilla this byte pair is the "stat/skill reset (Akara)" state | `8002` / 0 | S (value), U (meaning) | E (the editor sets it to 1 when all six act V quests are ticked and it is 0) |
| 42–47 | unused | 0 | S | K |

Bits of a quest word (**V** unless noted): bit 0 = completed / reward given (**C**: this is what the editor tests
and what every finished quest of the samples has), bit 1 = requirements met, bit 2 = quest given, bit 3 = left
town, bit 4 = entered the quest area, bit 12 = quest box closed in the log, bit 13 = completed in the current
game, bits 5–11, 14, 15 = quest specific. Act V words in Median XL often lack bit 0 but carry bit 15 (`8002`,
`8022`, `801E`): the meaning of bit 15 there is unknown (the Sigma act V quests differ from vanilla).

Differences that show what the game changes: between A and B the whole Hell block went from all zero to filled;
Nightmare words 35–40 went from `2002 2032 210A 0 0 0` to `8022 8022 8709 801E 0009 0405` (act V played through).

### 3.2 Waypoints (0x279, 80 bytes)

| Offset | Size | Field | Status | Editor |
|---|---|---|---|---|
| 0x279 | 2 | `WS` | C | R (required) |
| 0x27B | 4 | u32 version = 1 | S | K |
| 0x27F | 2 | u16 section size = 80 | S | K |
| 0x281 | 3 × 24 | per difficulty: u16 `0x0102`, then 22 bytes = 176 waypoint bits | C | E |

Bit `n` (byte `n // 8`, bit `n % 8` of the 22 bytes) = waypoint `n` is active. 0–8 act I, 9–17 act II, 18–26 act
III, 27–29 act IV, 30–38 act V are the vanilla ones (**C**: Normal and Nightmare of B / C have exactly bits 0–38).
Median XL's extra waypoints use higher bits (**C** for 60, 61, 70, 71, 80 — set in C's Hell block; **K** for 50
Duncraig, 72 Vizjun, 90 Túr Dúlra, which come from the editor's table built from `levels.bin`): 50 Duncraig,
60 Tran Athulua, 61 Island of Skartara, 70 Caldeum, 71 Torajan Jungles, 72 Vizjun, 80 Silver City, 90 Túr Dúlra.
The editor writes the two lead bytes `02 01` and only touches the bits it knows.

### 3.3 NPC section (0x2C9, 52 bytes)

| Offset | Size | Field | Status | Editor |
|---|---|---|---|---|
| 0x2C9 | 2 | `01 77` | S | K |
| 0x2CB | 2 | u16 section size = 52 | S | K |
| 0x2CD | 3 × 8 | u64 per difficulty: "introduced" bit per NPC | S (changes when a difficulty is first played), V (meaning) | K |
| 0x2E5 | 3 × 8 | u64 per difficulty: "congratulated" bit per NPC | S, V | K |

C holds `…05C9A42E2E`, `…C9A42E2E`, `…06C9A4222E` (introduced) and `19E7FFF0`, `19E7FFFC`, `19C3FFBC`
(congratulated). Which bit is which NPC is not established (vanilla uses a fixed NPC list; unknown for Sigma).

## 4. Character stats (`gf`, at 0x2FD)

A bit stream directly after `gf`: repeated `[9-bit stat id][parameter][value]`, ended by the id `0x1FF`, padded
with zero bits to a whole byte. The widths come from `itemstatcost.bin` — `CSvBits` (byte 10 of the row) and
`CSvParam` (byte 11) (**C**). A stat worth 0 is left out, stats are sorted by id, then by parameter (**C**: the
editor's writer reproduces the game's level-117 section from the level-100 file).

| Id | Param bits | Value bits | Meaning | Samples | Status | Editor |
|---|---|---|---|---|---|---|
| 0 | – | 11 | strength (base) | 817 → 1025 | C | E |
| 1 | – | 11 | energy | 25 | C | E |
| 2 | – | 11 | dexterity | 118 → 25 (respec) | C | E |
| 3 | – | 11 | vitality | 20 | C | E |
| 4 | – | 11 | unspent stat points | 20; absent in B / C | C | E |
| 5 | – | 9 | unspent skill points | 4; absent in B / C | C | E |
| 6 | – | 21 | life, current, × 256 | 2 097 151 = the 21-bit maximum (the real life exceeds 8191) | C | E |
| 7 | – | 21 | life, maximum (base), × 256 | 910 080 = 3555 | C | E |
| 8, 9 | – | 21 | mana current / maximum, × 256 | | C | E |
| 10, 11 | – | 21 | stamina current / maximum, × 256 | 12 800 = 50 | C | E |
| 12 | – | 8 | level | 100, 117 | C | E |
| 13 | – | 32 | experience | 4 939 122 → 6 722 603 | C | E |
| 14 | – | 25 | gold carried | | C | E |
| 15 | – | 25 | gold in the stash | 2 500 000 | C | E |
| 88 | 16 | 32 | Median XL "achievement data", one entry per parameter ("layer") — section 4.1 | 7 entries (A) → 34 (C) | C (layout), S (meaning) | K (kept; `Character.set_stat(88, v, param)` exists, no GUI) |
| 185 | – | 12 | signets of learning used | 400 in all states | S (name from the project's stat-name table; 400 is believed to be the game's cap) | K (API only) |
| 186 | – | 8 | signets of skill used | absent (A) → 2 (B, C) | S | K (API only) |

Only these 19 stats have a `CSvBits` width in 2.14.x; any other id in the section makes both parsers stop.

### 4.1 Stat 88 — achievement counters (**S**)

Parameter below 0x2000 = a `monstats.bin` row, value = number of kills of that monster. In C: 956 Cow Soldier
5743, 1006 Bone Archer 1158, 1086 Amazon Warrior 2095, 2359 Forest Keeper 1236, 2774 Treasure Goblin 14, and a
value of 1 for bosses such as 961 Infernal Machine, 964 Akarat, 966 Tal Rasha, 971 The Butcher, 973 Bul-Kathos,
1022 Buyard Cholik, 1059 Primus, 1069 Lord Aldric Jitan, 1109 Bartuc (2). Only some monsters are tracked (bosses
and the monsters of "kill N" challenges, it seems).

Parameter 0x2000 + n = general counters:

| n | Q → A → B → C | Reading |
|---|---|---|
| 0 | 13 014 → 13 169 → 33 196 → 33 251 | grows by 55 while experience grows by 746: a kill counter (which kills: unknown) |
| 1 | 2745 → 2745 → 6153 → 6156 | unknown counter |
| 2 | 5250 → 5252 → 8193 → 8214 | unknown counter |
| 4 | 1 → 1 → 1 → 1 | unknown flag |
| 10 | 62 → 64 → 125 → 125 | unknown counter |
| 11 | 402 → 402 → 417 → 417 | unknown counter |
| 12 | 41 902 → 42 214 → 56 529 → 57 991 | **play time in seconds**: Q → A is +312 while the save time (0x30) moved by 314 s; B → C is +1462 over three calendar days |

The game's chat commands call the parameter a "layer" (`Stat %d, Layer %d has a value of %d`). The names of the counters are not in the
extracted tables.

## 5. Skills, item lists, corpse, mercenary, golem

### 5.1 Skills (`if`)

`if` + one byte per skill of the character's class: its base ("hard point") level. The order is the row order of
`skills.bin` filtered on the class column (u32 at +12) (**C**: the editor's skill page, and the non-zero bytes of
the samples are exactly the skills the character uses). Every class has 95 such rows in 2.14.x, so the section
is 97 bytes. Editor: **E** (Skills page; a class change writes 95 zero bytes).

### 5.2 Item lists

`JM` + u16 count + `count` items; each item is followed by the items socketed into it (they are not counted).
Items are described in section 6. Editor: **E**.

Where the character's items are (**C**, all from the item header):

| location | panel | Meaning | x, y |
|---|---|---|---|
| 0 stored | 1 | inventory, 15 × 10 cells | cell of the top-left corner |
| 0 stored | 4 | Horadric cube | cell (K: not in the samples) |
| 0 stored | 5 | stash page (only in `.stash` / `.shared` files), 14 × 14 cells seen | cell |
| 1 equipped | 0 | worn; `equipped` = slot: 1 helm, 2 amulet, 3 armor, 4 right hand, 5 left hand, 6 right ring, 7 left ring, 8 belt, 9 boots, 10 gloves, 11 / 12 right / left hand of weapon set II | x = slot, y = 0 |
| 2 belt | 0 | belt | x = belt slot 0–15, y = 0 |
| 4 cursor | – | on the cursor (V) | |
| 6 socketed | 0 | inside the previous non-socketed item | x = socket index |

### 5.3 Corpses

`JM` + u16 corpse count. Per corpse (**K**/**V**, no sample has one): 12 bytes (vanilla: u32 unknown, u32 x,
u32 y) and then a full item list (`JM` + count + items). All samples hold `4A 4D 00 00`. Editor: **K** (bytes kept;
it can skip one corpse).

### 5.4 Mercenary

`jf`, and — only when the header's mercenary id (0xB3) is not 0 — an item list (`JM` + count + items) (**C**).
All samples: 7 worn items. **The Median XL mercenary wears more than the vanilla one**: slots 1 helm, 2 amulet,
3 armor, 4 weapon, 8 belt, 9 boots, 10 gloves are in use in the samples (**S**). Editor: **E** for the items, but
`mxl_char.MERC_SLOTS = (1, 2, 3, 4, 5, 8, 9, 10)`: every one of these slots can be filled from the editor.

### 5.5 Iron golem

`kf` + u8 (0 / 1) + one item when 1 (**K**/**V**; all samples end with `6B 66 00`). Editor: **K** (kept as the tail).

---

## 6. Items

An item is `JM` followed by a bit stream, padded with zero bits to a whole byte (**C**: padding is 0 on all 2 947
sample items). Its length is not stored: an item can only be delimited by decoding it, which needs the stat
widths of `itemstatcost.bin`. `mxlsave.items.Item` holds every field below; `Item.to_bytes()` rebuilds the bytes.

### 6.1 Common header (bits after `JM`)

| Bit | Width | Field | Values seen | Status | Editor |
|---|---|---|---|---|---|
| 0 | 32 | flags (section 6.2) | | C | E (identified, socketed, ethereal, runeword, personalized, "new"); others K |
| 32 | 10 | item format version | 101 on every item | S | K (the creator writes 101) |
| 42 | 3 | location (section 5.2) | 0, 1, 2, 6 | C | E |
| 45 | 4 | equipped slot | 0–11 | C | E |
| 49 | 4 | x | 0–14 | C | E |
| 53 | 4 | y | 0–13 | C | E |
| 57 | 3 | panel | 0, 1, 5 | C | E |
| 60 | 32 | item code, 4 characters, space padded (`'box '`, `'@01 '`, `'kazm'`) | | C | E (base change) |
| 92 | 1 or 3 | number of socketed items that follow: 1 bit on a simple item, 3 bits otherwise | 0–6 | C | E |

A **simple** item (flag 21) ends here: 93 bits → 12 bytes + `JM` = 14 bytes. Runes, gems, potions, most
consumables are simple (1 171 of the samples' items).

### 6.2 Flags

| Bit | Name | Seen | Status |
|---|---|---|---|
| 4 | identified | on every item | C |
| 10 | unknown (vanilla: unnamed) | 20 healing potions | U |
| 11 | socketed: the 4-bit socket count exists and socketed items may follow | 85 | C |
| 13 | "new": on items made in the cube since the last save (runes, the fresh honorific armor) | 42 | S |
| 16 | ear (vanilla: a different layout follows) | never | V — neither the editor nor `mxlsave` reads ears |
| 17 | starter item | the Horadric Cube only | S |
| 20 | unknown | 10 worn unique items | U |
| 21 | simple | 1 171 | C |
| 22 | ethereal | 42 | C |
| 23 | always set | every item | S |
| 24 | personalized: a name follows | never | K |
| 26 | runeword: a 16-bit id and a second stat list follow | 16 | C |
| 27 | unknown | 39 healing potions | U |

All other bits are 0 in the samples. Parsers keep the 32 bits as they are.

### 6.3 Extended part (everything except simple items), in file order

| Width | Field | Present when | Status | Editor |
|---|---|---|---|---|
| 32 | item id (random) | always | C | E (the creator draws a new one) |
| 7 | item level | always | C | E |
| 4 | quality: 1 low, 2 normal, 3 superior, 4 magic, 5 set, 6 rare, 7 unique, 8 crafted, **9 honorific** | always | C | E |
| 1 + 3 | has-picture bit, then picture number | bit set (652 items, all misc: charms, jewels, rings…) | C | E |
| 1 + 11 | has-automagic bit, then `automagic.bin` row | bit set (144 items) | C | E |
| 3 | low / superior sub-quality | quality 1 or 3 | C | E |
| 11 + 11 | magic prefix, magic suffix | quality 4 | C | E |
| **15** | set / unique row (vanilla: 12 bits) | quality 5 or 7 | C | E |
| 8 + 8 | rare name prefix / suffix | quality 6, 8 **and 9** | C | E |
| 6 × (1 + 11) | six affix slots: present bit + affix number | quality 6 or 8 only (an honorific item has none) | C | E |
| **16** | runeword id: the `string.tbl` index of the runeword's name key (e.g. 0x20BB = 8379 = "Dyaus Pita"), not a `runes.bin` row; the "high 4 bits = 2" seen on the samples is only a side effect of indices around 8 200 | flag 26 | C (checked on every sample runeword) | E |
| 7 × n + 7 | personalized name, 7-bit characters, ended by 0 | flag 24 | K | E |
| 5 | unknown tome field | code `tbk ` or `ibk ` | K | K |
| 1 | "realm data follows" bit of vanilla; 0 on every sample. What follows when 1 is not known | always | S | K (written as 0) |
| 16 | defense + 500 (`itemstatcost` stat 31: 16 bits, add 500) | item type under `armo` | C | E |
| 9 | maximum durability + 90 (stat 73) | item type under `armo` or `weap` | C | E |
| 9 | durability + 150 (stat 72) | the maximum durability field ≠ 90, i.e. real maximum ≠ 0 (10 sample items have no durability field) | C | E |
| 9 | quantity | the base is stackable (byte 306 of its `weapons/armor/misc.bin` row) | C | E |
| 4 | number of sockets | flag 11 | C | E |
| 5 | set bonus mask: one extra stat list per set bit | quality 5 | C (field), K (non-zero mask: none in the samples) | E |
| list | the item's stats (section 6.4) | always | C | E |
| lists | set bonus stat lists, for mask bits 0–4 | quality 5 | K | E |
| list | runeword stats | flag 26 | C | E |

Two Median XL particularities that broke the host's reader and are handled by the editor (`mxl_format_fix.py`)
and by `mxlsave`:

- **Quality 9 (honorific)** — made in the cube from a magic / rare item + Mark of Infusion. After the common
  fields it holds only the two rare-name bytes; all its properties are in the stat list. The one real sample
  (leather armor `'785 '`, flags `0x802810`) has stats 36 = 1 and 289 = 2 (**C**).
- **Defense / durability depend on the item type, not on the table**: a `weapons.bin` row whose type is not under
  `weap` (Staff of Herding `wd02`) has no durability field (**K**, from the editor's fix; the samples hold no
  such item).

### 6.4 Stat lists

Repeated `[9-bit stat id][parameter][value]`, ended by id `0x1FF` (**C**).

- Widths per stat from `itemstatcost.bin`: value width = byte 25 of the row ("save bits"), bias = i32 at +28
  ("save add": stored = real + add), parameter width = i32 at +36 ("save param bits"). 396 of the 511 stats of
  2.14.x can be saved on items, 48 of them have a parameter. The largest id in the samples is 510: the 9-bit id
  space (0–510, 511 = end) is fully used by Median XL.
- **Save groups** (**C**): the stats 17 (+18), 48 (+49), 50 (+51), 52 (+53), 54 (+55, +56), 57 (+58, +59) are
  written under the id of their first member only — one 9-bit id, then parameter and value of each member in
  turn (enhanced damage, the elemental minimum / maximum pairs, cold and poison triples).
- What a parameter means (skill id, class, mystic orb row, `skill << 6 | level`, element | attribute << 8 for
  stat 415, …) is documented per stat in `docs/STAT_PARAMS_REPORT.txt` / `src/mxl_statparams.py`: 32 proven, 13
  inferred, 3 unknown (88, 417, 427).
- Values that do not fit the width cannot be stored; 4 table mods exceed their stat's range
  (`tools/audit_game_data.py`). How the game stores those is unknown.

### 6.5 Not covered

- Ear items (flag 16): vanilla replaces the item code by class (3 bits), level (7 bits) and a 7-bit name. No
  sample; both parsers refuse them. **V**
- The 96 bits vanilla writes when the realm bit is 1. **U**
- Whether item version 101 has variants (other mod versions wrote 100 / 2). **U**

---

## 7. `<name>.stash` and `_sharedstash.shared`

Both files have the same layout (**C**: the host's `parse_stash` / `build_stash`, the editor and `mxlsave`
round-trip all 11 valid samples byte for byte).

| Offset | Size | Field | Values seen | Status | Editor |
|---|---|---|---|---|---|
| 0x00 | 4 | u32 version | 1 | S | K |
| 0x04 | 4 | u32 page shown last in game (0-based) | 0, 1 | C (host `last_page`) | R (opens on this page), K on writing |
| 0x08 | … | one section per **non-empty** page, in ascending page order | | C | E |

Page section: `STASH` (5 bytes) + u32 page number + `JM` + u16 item count + items (socketed items follow their
owner, as in the `.d2s`). Items have location 0, panel 5, and x / y inside a 14 × 14 grid (largest extent seen).

What the file does **not** contain: a page count (the highest page number in the samples is 2; empty pages are
simply absent — the smallest file is the 8-byte header of an empty shared stash), page names, gold (stash gold is
character stat 15; a shared gold field does not exist in these files), a checksum or a size. An unknown stat id,
a wrong count or a missing marker makes the whole file unreadable for the game's reader as well as for ours — the
three `Mr_Owlie…corrupt` samples each contain one item with an impossible stat list.

A separate shared stash for ladder characters (`_sharedstash.ladder`?) probably exists; no sample.

## 8. Companion files

### 8.1 `<name>.key` — key bindings (**S**)

1142 bytes: u16 `0x25`, then 114 records of 10 bytes — `u32 function (0–56)`, `u16 key`, `u32 slot` — two records
per function. `key` is a Windows virtual-key code (`0x41` = A), `0x100`–`0x104` for mouse buttons / wheel,
`0xFFFF` = not bound; `slot` is 1 on one record of each pair and 0 on the other. The first functions follow the
vanilla order (0: A / C character screen, 1: I / B inventory, 2: P party, 3: M message log, 4: Q quests, 5: Enter
chat, 6: H help, 7: Tab automap…).

The game folder's `default.key` (1146 bytes) holds the same 114 records behind a 6-byte header: `WS`, u16 `0x25`,
u16 file size. The character's `.key` was written once (same bytes in A and C, file time = character creation).
Sigma keeps its real key configuration in `preferences.json` (`hotkey_merc`, `hotkey_quests`,
`hotkey_automap`…), so the `.key` file is probably a
vanilla leftover the game no longer reads — not verified. Editor: renamed with the character, otherwise ignored.

### 8.2 `<name>.map` — the last four game seeds (**S**)

24 bytes: u32 `12`, u32 `next slot` (0–3), 4 × u32 seed.

| | u32 @4 | seeds | `.maN` files present | header 0xAB of the `.d2s` |
|---|---|---|---|---|
| A | 3 | `04BA8D2A 240D0F02 6CD8D09B 00000000` | .ma0 .ma1 .ma2 | `6CD8D09B` |
| C | 0 | `1A77AC2D 40852623 21D22F82 0AB39E0B` | .ma0 … .ma3 | `0AB39E0B` (B: `40852623`) |

So it is a ring buffer: slot N belongs to `<name>.maN`, the field at 4 is the slot the next game will overwrite,
and the newest seed is the `.d2s` map seed. The file times agree (C: .ma0 Nov 12, .ma1 Nov 13 = time of state B,
.ma2 Nov 16, .ma3 Nov 17 = time of state C). Consequence: Sigma rolls a new map seed for each game and remembers
the automap of the last four. Editor: renamed with the character, otherwise ignored.

### 8.3 `<name>.ma0` – `.ma3` — automap cache (**S**, partly)

- 0x0000: 1024 × u32 file offsets, indexed by level id (`levels.bin` has 280 rows; entries beyond the game's
  level count hold uninitialised memory such as `0x0071F59C`). 0 = level not visited.
- 0x1000 onwards: one block per visited level, appended in visit order (the table is therefore not sorted). A
  block starts with `u32 ?`, `u32 level id` (equals its table index — used by `mxlsave` to tell real entries from
  garbage), `u32 ?`, `u32 seed-like value` (per level; equal for several blocks in some files), `u32 ?`; the rest (revealed
  automap cells, most likely) is not decoded. Sizes range from 56 bytes to 845 KB per level.

Sizes: 9 KB (one town visit) to 1.8 MB (a long session). Editor: renamed with the character, otherwise ignored.
Deleting them only loses the remembered automap (**V**: not tested in game).

### 8.4 Other files in the save folder

- `preferences.json`, `infographics.json` (Sigma's own files): account-wide settings of Sigma, outside the
  per-character set; not in the samples, not examined.
- `MXL Item Collector/library.json`: the host application's own item library, not a game file.

## 9. Game tables the format depends on

`.bin` = u32 row count + rows of equal size. Offsets within a row (2.14.x; from the host's `mxl_data` reader,
used unchanged by `mxlsave.tables` and checked by the byte-identical round trip):

| Table | Column | Offset | Used for |
|---|---|---|---|
| itemstatcost | stat id u16 | 0 | |
| | CSvBits u8 / CSvParam u8 | 10 / 11 | character stats section |
| | save bits u8 | 25 | item stat value width |
| | save add i32 | 28 | bias |
| | save param bits i32 | 36 | parameter width |
| weapons / armor / misc | code (4 bytes) | 128 | |
| | name string u16 | 244 | |
| | width, height u8 | 271, 272 | |
| | type, type2 i16 | 286, 288 | defense / durability fields |
| | stackable u8 | 306 | quantity field |
| itemtypes | code (4 bytes), parents i16 × 2 | 0, 4 | type ancestry (`armo`, `weap`) |
| skills | class u32 | 12 | order of the skills section |
| | skilldesc row u16 | 404 | names |
| skilldesc | name string u16 | 8 | names |
| monstats | name string u16 | 6 | names of stat-88 parameters |
| hireling | Id u32, class u32, act u32, difficulty u32 | 4, 8, 12, 16 | mercenary type |

String tables: `string.tbl` (index 0…), `patchstring.tbl` (10 000…), `expansionstring.tbl` (20 000…).

## 10. Open questions

Settled only by an in-game experiment on a throw-away character:

1. Stat 88: the names of counters 0x2000–0x200C and the list of tracked monsters; which of them gate content
   (uberquest entry, challenges, trophies) and whether the game recomputes any of them.
2. Quest words: bit 15 on act V quests, the meaning of word 41 (`0x8002`), which bits the Sigma quest log and
   the "labyrinth" / challenge NPCs test; whether word 34 (written by the editor) is read at all.
3. Header 0x2A (`0x5F`), 0x26, 0x34, 0xAF; whether 0x2C (creation time) is ever written.
4. Item flags 10, 20, 27; the layout behind the realm bit; ears.
5. The mercenary: whether 0xB9 is validated against `hireling.bin` rows of the current difficulty, how the name
   index is bounded, what a seed (0xB3) change does to its stats.
6. Whether the game checks 0x30 (last played), 0xAB (map seed) against `.map`, and what it does when `.maN`
   and `.map` disagree.
7. NPC introduction bit ↔ NPC mapping.
8. Stash: the page limit, whether a page section may be out of order or repeated, the role of the version field,
   and the `.ladder` shared stash.
9. `.key`: whether Sigma still reads it; `.maN` block contents.
10. The cap behaviour of stats 6 / 8 / 10 (current life stored at the 21-bit maximum in B / C) and of gold
    (25 bits) — what the game does with values above its own limits (stash gold cap 2 500 000 seen).
