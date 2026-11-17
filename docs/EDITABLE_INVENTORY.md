# What is stored in the save files, and what the editor edits today

Answer to "is there anything editable we don't know about yet". Every row is something the game writes to disk;
offsets and layouts are in `docs/SAVE_FORMAT.md`, the same structure as code is in `tools/mxlsave/`.

- **Edits today**: yes / partly / no (MXL Capybara Editor V2 as of this commit; "API" = a function exists in
  `mxl_char.Character`, no window offers it).
- **Risk**: low = worst case the value is ignored or rewritten by the game; medium = may change gameplay state
  in ways not tested; high = a wrong value can make the character or stash unloadable. Every edit keeps the
  editor's safe writer (game closed, verify, backup), so "high" means "restore the backup", not data loss.
- **Proof**: C confirmed by code + samples, S seen in samples only, V vanilla knowledge not re-checked on Sigma,
  U unknown. Nothing below was tested in the running game during this investigation — the "game reaction"
  column says so where it matters.

## 1. Not exposed by the editor yet

These are the finds. Ordered by how useful they look.

| # | What | Where | Edits today | Risk | Game reaction (as far as known) | Proof |
|---|---|---|---|---|---|---|
| 1 | **Mercenary record**: dead flag, id / seed, name index, type (`hireling.bin` Id), experience | header 0xB1–0xBE | no (only "has a mercenary" is read) | medium; type / name out of range = unknown | vanilla: dead flag non-zero → must be revived; experience decides the level; type picks class / act / difficulty row. Sigma: not tested | fields S (id constant, experience grows A→C, type 1 = rogue with a bow), meaning V |
| 2 | **Mercenary equipment slots**: Sigma mercenaries wear amulet, belt, boots, gloves besides helm / armor / weapon | `jf` item list, `equipped` 1, 2, 3, 4, 8, 9, 10 | partly: the items are shown and editable, but `MERC_SLOTS = (1, 3, 4, 5)` refuses to place anything in 2, 8, 9, 10 (and rings 6, 7 — not seen) | low | the game wrote these slots itself | C (all four character samples) |
| 3 | **Achievement counters** (stat 88): kill count per tracked monster (bosses, challenge monsters) and general counters (7 seen, layers 0x2000–0x200C), one of them the play time in seconds | stats section, id 88, 16-bit "layer" + 32-bit value | no (kept; API `set_stat(88, value, param)`) | medium: unknown which entries gate content | unknown. Boss entries with value 1 look like "killed once" flags that challenges / uberquest rewards may test | layout C, meaning S (monster names match, play time matches the save clock), gating U |
| 4 | **Signets of learning / skill used** (stats 185, 186) | stats section | no (kept; API) | low–medium | lowering 185 should let the character eat signets again (cap believed 400); the attribute points already granted stay unless stat 4 is lowered too. Not tested | S |
| 5 | **Skill hotkeys** (16) and **left / right mouse skills** for both weapon sets | header 0x38–0x87 | no (the web import writes "none" / Attack) | low | a skill the character does not have is normally dropped by the game on load (V) | S (ids are the character's skills), flag 0x8000 V |
| 6 | **Individual quest bits** beyond done / not done: requirements met, given, entered area, closed in log, done this game, bit 15 on act V quests | quest words, 3 × 48 × 16 bits | partly: only `0x1001` (done) or 0, per quest; states such as "in progress" (`0x0009`), "reward not taken" (`0x8002`) cannot be set or even seen | medium | vanilla: bit 0 + bit 12 = finished; clearing bit 0 re-opens the quest and its reward (how the editor's quest rewards work). Sigma act V semantics unknown | bit 0 C, others V / U |
| 7 | **Act introduction / travel words**, incl. the act V intro at word 32 | quest words 0, 7, 8, 15, 16, 23, 24, 28, 32 | partly: set as a side effect, never cleared; **word 34 is written as "act V intro" although the samples use word 32**, and word 41 is written as "act V finished" although the game holds `0x8002` there | low (the game's own words are left alone when non-zero) | unknown: no sample shows what the game does with word 34 set | S |
| 8 | **Quest word 41** (`0x8002` once a difficulty is entered; vanilla: stat/skill reset state) | quest word 41 | no (see 7) | medium | unknown — a candidate for "free respec available" | S value, U meaning |
| 9 | **Last played difficulty and act** | header 0xA8–0xAA | no | low | decides where the character-select screen says the character is; the game rewrites it on every save (V) | S |
| 10 | **Map seed** + the four-entry seed ring | header 0xAB; `<name>.map` | no | low | Sigma rolls a new seed per game; forcing a seed is only possible if the game honours the stored one — unknown | S |
| 11 | **Automap cache** of the last four games | `<name>.ma0`–`.ma3` | no (renamed with the character) | low | deleting them loses the remembered automap only (V) | S, contents mostly undecoded |
| 12 | **NPC introduced / congratulated bits** | `01 77` section, 6 × u64 | no | low | cosmetic: NPCs greet again (V) | S |
| 13 | **Play time** | stat 88 layer 0x200C | no | low | display only, presumably | S (+312 vs +314 s of save clock) |
| 14 | **Last save time**, creation time | header 0x30, 0x2C | no | low | 0x30 is rewritten on every save; 0x2C is 0 | S |
| 15 | **Active weapon set** | header 0x10 | no | low | V | V |
| 16 | **Appearance bytes** (character-select picture) | header 0x88–0xA7 | no | low | rewritten from the equipment on every save (V), so an edit does not last — relevant only for characters made by the editor / import, which show a bare model until first played | S (changes with the gear) |
| 17 | **Corpse** (items left on a dead body) | second `JM` list | no (bytes kept; one corpse can be skipped over) | medium | items of a corpse come back when the character is loaded (V); no sample | K / V |
| 18 | **Iron golem item** | `kf` | no (kept) | medium | V; no sample; Sigma necromancers may not have an iron golem at all | K / V |
| 19 | **Item flags 10, 20, 27**, starter flag 17, "new" flag 13 | item header | partly (13 is set on created honorifics; the rest kept) | low | unknown; 10 / 27 only on potions, 20 on worn uniques | S |
| 20 | **Runeword field high 4 bits** (always 2), **item version** (always 101), realm bit | item | no (written as found / as constants) | high if changed | unknown | S |
| 21 | **Stash: page shown last** | `.stash` / `.shared` header 0x04 | no (read to open on that page) | low | which page the stash opens on | C |
| 22 | **Key bindings** | `<name>.key` | no | low | probably unused by Sigma (its bindings are in `preferences.json`) | S |
| 23 | **Unknown header bytes** 0x26, 0x29, 0x2A (`0x5F`), 0x34, 0xAF, 0xBF–0x14E | header | no (kept) | high if changed blindly | unknown | U |

## 2. Already editable

| What | Where | Edits today | Risk | Game reaction | Proof |
|---|---|---|---|---|---|
| Name (+ rename of all companion files) | header 0x14, file names | yes | low | name rule checked (2–15 letters) | C |
| Class | header 0x28 | yes (skills reset to 0) | medium: items / quests of the old class stay | not tested in game | C |
| Level | header 0x2B + stat 12 | yes (raw, or "level up" with the game's gains) | low | level and experience outside the table: the editor offers to match them | C |
| Experience, strength, dexterity, vitality, energy, stat / skill points, life / mana / stamina, gold, stash gold | stats 0–15 | yes | low; values limited to the stored width | the game clamps gold to its own caps (V) | C |
| Status flags: hardcore, died, expansion, ladder | header 0x24 | yes | medium: ladder / hardcore change which shared stash and rules apply | not tested | C / V |
| Progression (difficulties unlocked) | header 0x25 | yes | low | Nightmare at 5, Hell at 10 | S |
| Quests done / not done, with rewards | quest words | yes (see rows 6–8 for the limits) | low | | C |
| Waypoints, all three difficulties, incl. Median XL's Hell-only ones | `WS` | yes | low | | C |
| Skill levels | `if` | yes | low | 0–255 per skill; the game's own cap per skill is not enforced | C |
| Items: inventory, equipment, belt, cube, mercenary items, stash pages, shared stash — create, edit every field and stat, move, copy, delete | item lists | yes | medium–high for hand-made stat lists (an impossible stat makes the file unreadable; the editor verifies before writing) | | C |
| Character from a median-xl.com page | whole file | yes (import) | medium | | C |

## 3. Looked for and not found in the files

- **Stash page count, page names, shared gold**: do not exist. A page exists while it holds an item; the highest
  page seen is 2. Stash gold is character stat 15.
- **Attribute / skill reset counters, class charm upgrades, trophy or charm progress, cube-recipe counters** as
  separate fields: nothing of the kind outside stat 88 (and 185 / 186). Trophies, charm upgrades and relic
  states are properties of the items themselves (item stats), not of the character. If such counters exist they
  are among the unnamed stat-88 layers 0x2000–0x200B, or they would appear as new layers on a character that has
  done those things (ours has done few).
- **Challenge / uberquest completion flags**: no dedicated section. The only candidates are the stat-88 boss
  entries (value 1) and custom quest bits (bit 15 in act V words).
- **Per-difficulty waypoints**: yes, three independent blocks — already editable.
- **Anything after the golem section**: no trailing bytes in any sample.
- **A second checksum or signature**: none; only the vanilla checksum at 0x0C. Stash files have no checksum.

## 4. What would turn "S" into "C"

One throw-away character and five minutes per item: change one value with the editor (or `mxlsave`), load, save
in game, and dump the file again — `python -m mxlsave dump` shows exactly what the game kept or rewrote. The
order that pays most: mercenary type / experience / dead flag (1), stat 185 (4), a stat-88 boss entry before
talking to the matching challenge NPC (3), quest word 41 (8), skill hotkeys (5).
