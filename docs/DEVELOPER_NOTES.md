## "Make perfect" replaces the value sliders (`mxl_perfect.py`)
- The "Value editing" switch and the collector's in-place sliders are gone from the main window
  (`app.editing` is forced to False in `mxl_creator_gui.install`). The Item Creator keeps its own sliders
  and Min / Random / Max buttons for an item being created or edited.
- Right-click an item -> Specific editing functions -> **Make perfect (n of m rolls below the maximum)**,
  in the stash and in the character window. Only shown for an item with rolls; greyed out when every roll
  is already at its maximum. One write raises every roll to the top of its range: affix / unique / set
  rolls, Superior bonus, base defense, runeword rolls and the rolls of socketed jewels (the ranges are the
  collector's own, `mxl_edit.edit_groups`; linked stats follow through `mxl_save.set_stat`).
- Mystic orbs are not recorded on an item, so they are told from the value: a stat above its range is
  split into roll + orb part with the orb amounts of the `mysticorbs` table (fixed-amount orbs, at most the
  allowed count of each). The roll goes to its maximum, the orb part stays on top. When several orb totals
  fit, the smallest is taken, so the result never lowers the stat and never invents orb value. A value no
  orb combination explains (hand-edited) or below its range is left untouched and counted in the status line.
- A character item is rewritten in place (same size, same slot): the entry's bytes are swapped and the
  character saved, without the remove -> place step whose slot rules refuse some worn mercenary items.

# Median XL Capybara Editor (personal unrestricted build)

## Hero-Editor item menu on every right click (`mxl_rc_menu.py`, round 5): quality, specific editing, export
- Both windows' item menus now carry the original editor's context menu set: **Edit item / Item stats… /
  Duplicate / Copy / Cut / Paste (replaces it) / Move to page… / Quantity… / Change item quality… /
  Specific editing functions / Delete / Export item…**; an empty cell additionally offers **Paste here /
  Import item… / Create here…**. On the character window the same entries appear (writes through the
  character editor's remove -> place -> save flow), plus To stash; Import on an empty inventory cell.
- **Change item quality (now X)** — one entry per quality the base can carry (the creator's own rules:
  `can_have_quality`, superior bonus choices, craft recipes, set/unique rows filtered to the same base
  code). A switch asks for what the quality needs (which unique row, rare-name first and second part,
  superior bonus) with a small listbox dialog and then only replaces the quality fields — **the rolled
  stats stay exactly as they are**, like Hero Editor's menu. Switching to a set item drops the ethereal
  flag (the game never gives ethereal set items) and mentions it. Runeword items stay runewords.
- **Specific editing functions** — Hero Editor's submenu, written decode -> adjust -> re-encode in place:
  Set defense... (armor, clamped to the save format), Set durability..., Make indestructible (max
  durability = the indestructible encoding, the durability field disappears), Make / Remove ethereal (the
  game's own consequences: stored defense x3/2 or back, max durability /2 + 1 or back, refused when the
  result would not fit), Make socketed... (only on items without socketed children, up to the base's real
  socket cap at the item's level), Personalize... / Remove personalization (2-15 ASCII letters, the
  7-bit-chars field the game shows as "<name>'s ..."), and Delete all magic attributes (the stat list is
  emptied; set-item and runeword stat lists are kept).
- **Export item... / Import item...** — the raw item bytes (item + socketed items, exactly the stash's
  own entry format) to/from a `.d2i` file; Import validates by decoding before anything is written and
  places at the right-clicked cell.
- **Fill sockets** (Hero Editor's Paste Fill): with a gem or rune copied (the creator's own socketable
  filler list), the item's menu offers *Fill sockets with ... (now k of m)* — it appends copies of the
  clipboard item up to the base's real socket cap and rewrites every child's location to "socketed, slot
  i" (lossless re-encode; items with stale child locations get fixed on the way). Refused politely when
  the item is full or the clipboard holds something that is not a filler.
- **Magic-attributes buffer** (Hero Editor's mnuAddAllMagicAttributesToBuffer & friends; the original's
  paste handler is commented out in the VB6 source, here it works): *Add all magic attributes to buffer*
  copies an item's whole stat list (its runeword list kept apart) into a shared buffer, *Paste magic
  attributes from buffer* replaces another item's list with the buffered one (the record is re-spliced at
  its new size through the same safe writers), and *Delete magic attribute buffer* clears it. The menu
  entries appear only when they can do something.
- **Remove socketed items (n)** (Hero Editor's mnuRemoveSocketed) in the Specific editing submenu:
  deletes an item's socketed children (runes, gems, jewels) and clears the socket fields — the children's
  bytes live behind the record, so the entry shrinks to the bare record through the same splice writers.
  On a runeword the status note says its stats stay but the runes are gone.
- Compact-record items (gold, simple stackables) have no quality/stats in the save: the new functions
  refuse them with a status-line note instead of silently doing nothing.
- Every write still goes through the safe writers (edit_stash / Character.save) with backups; anything
  that would not fit its spot or the save format is refused and nothing is written.
- Verified headlessly (`/tmp` round-5 suite, DISPLAY=:0): decode -> encode byte-identical on all 50 real
  stash items; quality switches (normal/superior/magic/rare/unique) keep the stats; ethereal round-trip
  adjusts defense/durability by the game's rules and back; durability, indestructible, personalize,
  clear-mods and socket fields round-trip; one real edit_stash write re-parsed with the new quality; the
  character writer path saves and re-loads with the flag; menu wiring built on a hidden Tk root for a
  gem (quality entries per the base rules) and for a created legit armor (defense / durability /
  indestructible / ethereal / sockets / personalize / clear attributes all offered); a menu-dispatched
  quality write landed in the stash through the real writer.

## Right-click menus on items (`mxl_rc_menu.py`): the Hero-Editor way
- Main window (stash grid): right-click an item for **Edit item / Item stats… / Duplicate / Copy / Cut /
  Paste (replaces it) / Move to page… / Quantity… / Change item quality… / Specific editing functions /
  Delete / Export item…**; right-click an empty cell for **Paste here / Import item… / the Item Creator**.
- Character window (equipment, mercenary, inventory): the same set (written through the character editor's
  own remove -> place -> save flow) plus **To stash**; an empty inventory cell for **Paste here /
  Import item… / Create here…**.
- **Change item quality** replaces only the quality fields (the rolled stats stay); it asks for what the
  quality needs (unique/set row of the same base, rare-name parts, superior bonus) and never offers a
  quality the base cannot carry. **Specific editing functions**: defense, durability / indestructible,
  ethereal (with the game's own defense and durability consequences), sockets (childless items only),
  personalize, delete-all-magic-attributes. **Export/Import** moves items as raw `.d2i` bytes.
  **Fill sockets** copies a clipboard gem/rune into the item's free sockets, up to the base's cap.
- Every write goes through the collector's own safe writers (edit_stash, Character.save / apply_edits; backups).

## Item stats tab (`mxl_he_stats.py` + `mxl_attr_picker.py`): Hero-Editor "Magic Attributes" list (current)
- "Item stats" (toolbar, stash and character right-click menus) opens the `Item stats` tab again (it had been
  routed to the Item Creator's edit mode): left a compact numbered slot list drawn on one canvas (row = font
  linespace + 4 px; used slots + "(empty)" ones, at least 30 - the save format has no slot limit, a stat list
  just ends with the 0x1FF marker), right the attribute picker (categories | stats, one filter over all
  categories); the right pane turns into a skill / class name list while a row's skill is chosen.
- Keys: Up/Down/PgUp/PgDn/Home/End, Enter or double-click = picker for the slot (pick replaces / fills),
  Delete = clear slot, digits or F2 = edit value in place (Enter writes, Tab = next cell of the row, Up/Down
  keep the typed value as pending `*`), letters = start the filter, Ctrl+S = save, Escape = back to the list.
- Engine unchanged (see the section below): value edits through `apply_edits`, add / replace / clear / param
  changes through the lossless decode -> encode path; pending values are written first before a rewrite.
  New: values are capped to the real stored range `-add .. 2^bits-1-add` (negative values work).
- `mxl_attr_picker`: `palette()` (colours from mxl_d2_theme / mxl_he_theme), `metrics()` (font-relative
  sizes), `build_index()`, `categorize()` (rules on stat id / display func / label words; Hero Editor's own
  forms hold no category names - its tree was filled at run time), `AttrPicker`, `ChoiceList`, `popup()` for
  the Item Creator later. Settings: `attr_picker_cat` (last category), `attr_picker_recent` (12 stat ids).

## Former Item stats window: Hero-Editor-style flat stat table (replaced by the tab above; engine notes still apply)
- "Item stats" button in the main bar (next to "Edit item"): opens a plain Hero-Editor-style table of the
  selected item (a stash item, or one of the character's equipment / inventory items opened from the
  character window's right-click menu) — one row per stored stat, the game's own label (plus a `[stat #id, bits]` reference for
  the internal stats), the value in a number box, a × per row to delete it, and a "Stat to add" picker that
  acts like Hero Editor's stat list (a filter box + the list of every stat the save format can hold, param
  box, "Add this stat", "Replace selected row"). Light / dark mode like the character window (`he_stats_dark`).
- **Attribute list like Hero Editor**: click a row (label or number box) to select it — it is highlighted;
  the picked stat in the picker then has **Replace selected row** (takes the selected row's place, the value
  typed in the row's box is kept), next to **Add this stat**; × deletes the selected row's stat.
- Value edits of kept rows are written in place through `mxl_save.apply_edits(..., force=True)` (one write,
  verification, `.bak` backup, linked stats kept by the collector's own set_stat logic). Adding or deleting a
  row re-encodes the item losslessly (`mxl_creator.decode_blob` → `build_blob`, round trip verified
  byte-identical on all items of a real stash) and replaces it at its own place through `mxl_save.edit_stash`;
  the main window is reloaded afterwards because offsets shift.
- Values the save format cannot hold are refused (and shown in the window's status bar) — never written.
  Stash items only for now (equipment / inventory items go through the character file writer).

## Stat names, skill params and the full stat list of the Edit item window (2026-11-09)

- `mxl_statnames.py` (new, shared): readable labels and skill params for every editor.
  - `stat_text`: the stat's own game text, plain; `''` for hidden stats and for the 256 stats whose
    desc / pos / neg / str2 strings are literally 'FLYING POLAR BUFFALO ERROR' in Median XL's own
    itemstatcost (only #377 ever surfaces on real saves) — the editors show a neutral '(stat #N)' for
    those instead of the placeholder (`mxl_creator.stat_choices`, `mxl_he_stats._row_label`; the
    creator's `mod_label` already filtered those strings).
  - Params that carry a skill are known from the game data: the chance-to-cast stats (sids 195 - 203,
    param = `(skill << 6) | level` shown), the single-skill stats (97 / 107, param = skill id) and the
    class skill stat (83, param = class index); `decode_param` / `encode_param` / `skill_names_sorted`
    build the dropdowns.
- **Clamping instead of the range error**: every value box now caps a typed value at what the save
  format holds and reports it, instead of refusing with a "does not fit" dialog or an error:
  `mxl_he_stats.save()` (stash and character items, notes `stat #N capped to M`), `mxl_creator_gui`
  `route_target` / `Replace selected` (`_edit_clamp`), and the character window's stats tab
  (`mxl_char_gui.save_progress`, `he.capped` / `he.capped_to` keys; the box itself shows the capped
  value). The write itself still refuses what the game's own stat logic will not allow (StoreError).
- `mxl_he_stats.py`: chance-to-cast / single-skill / class rows get a skill (or class) dropdown beside
  the value box (chance-to-cast rows get the cast level too); changing it rewrites the item's param at
  once (`_row_param_commit`). The add / replace picker shows the same dropdowns for the picked stat
  (`_build_param_zone`), so e.g. a chance-to-cast stat is added as 'Arrow' + level + chance, not as a
  naked param number.
- **Edit item window** (`mxl_creator_gui.py`, edit mode only): the raw 'extra' section is replaced by
  `render_edit_stats` — the item's own stat list as the game shows it, one row per (stat, param) with
  its final value (the mods' totals plus the hidden delta). Editing routes through the single variable
  mod that owns the stat alone (`spec['rolls']`) when there is one and no delta row yet, else through
  the raw delta rows (`spec['extra']`), so edits survive re-opening the window. Each row: click to
  select (● marker), the value box, the skill dropdown + cast level for skill stats, × to delete (the
  delta cancels what the mods still produce; a zero row the item itself had is kept like the spec
  builder keeps originals). The pick row below takes any stat + its skill / param + a value:
  '+ Add stat' or 'Replace selected' (carries the selected row's value over, capped at the new stat's
  save bounds, and cancels the old key). Runeword items keep the raw runeword section; the creator
  (new item) keeps the plain raw stat section, with the param box upgraded to the skill / level or
  class dropdown.
- `repack.py`: `mxl_statnames` added to the module list.

## What is changed in this fork
- **Works while the game is open** (`mxl_free.py`, new module): the collector's "the game must be closed" check
  (`mxl_save.check_game_closed`, by function identity also everywhere a module bound it by name, and wherever
  a writer of the collector calls it) is replaced by a no-op at start, and `mxl_char.Character.save` no longer
  refuses a file that changed on disk since it was read: it is written through anyway, with a warning in
  capybara.log. Verification after writing and the `.bak` backups stay. The game reads the saves when it
  starts, so changes show after its next save & exit / restart.
- **Unrestricted stat editing / raw stats on any item** (`mxl_creator.py`, `mxl_creator_gui.py`): an
  "Unrestricted" switch in the Item Creator / Editor window (remembered, on by default):
  - value sliders reach the item's full storable range (ItemStatCost save bits / add) instead of the game's
    own affix ranges; a value the save format cannot hold is never written — the encoder refuses it and the
    status line warns, so a broken item cannot corrupt the file;
  - a **raw stats** list at the bottom of the value sliders: **+ Add stat** puts a row with any stat id the
    save can hold (the game's 9-bit stat ids, 0-510, exactly what ItemStatCost has storage for), its param
    (a number; a skill or monster id for the stats that take one) and any value; every row can be edited or
    deleted ('✕'), also on runeword items (a second list, next to the runeword's own one). Same (stat, param)
    rows add up when the item is written, like the game's own stat lists;
  - simple items (runes, gems, keys...) open for editing too: an item without its own stat list carries raw
    stats as a full item record, and stays byte-identical when no raw stat was added;
  - out-of-range values of kept stats (hacked / upgraded items) stay as they are upstream, and in this build
    the free sliders and raw rows can put any storable value on a new item as well.
- The game tables the editor relies on were cross-checked against the extracted Median XL data
  (itemstatcost: max storable stat id 510) (9-bit stat
  id, 5-bit param pieces, 0x200 stride): the editor's item saving is exactly the game's.
- Language keys of the changed windows: `cr.unrestricted`, `cr.unrestricted_note`, `cr.raw.*` and
  `cr.warn.unrestricted` (English text is in the code, `lang/*.json` carry the three languages).

## Upstream features (unchanged)

`MXL Capybara Editor.exe` is the MXL Item Collector with an offline item creator/editor and a character editor added,
named Median XL Capybara Editor (window titles, capybara icon). It sits next to the original `MXL Item Collector.exe`
and uses the same `_internal` folder and the same settings / data folder; the original exe is untouched.

## What's new in the main window
- **No library**: the collector's library (collection of found uniques and sets) is removed. This build has no Library
  button, no "transfer to the library" button, and no library.json file.
- **Item Creator**: create a unique, set item, runeword, rare, magic, superior or normal item.
- **Edit item**: opens the selected stash item in the creator. "Replace item" writes the new version in its place.
- **Delete item**: removes the selected item and anything socketed in it. A backup is made first.
- **Value editing**: switches on the collector's own built-in sliders in the detail panel.

## Equipment and inventory next to the stash (main window)
- Between the stash grid and the detail panel: the selected character's equipment (paperdoll, Character / Mercenary,
  weapon set I / II) with the 15×10 inventory below it.
- Drag items between the stash, the inventory and the equipment slots, in any direction, and inside the character
  (inventory ↔ slots, slot ↔ slot, character ↔ mercenary). The page shown in the stash is where items land;
  while dragging from the character, hovering a page tab or the Shared / Character button switches to it.
- Slot rules: the item's body location, a two-handed weapon needs the other hand empty, mercenaries use helm,
  armor and weapons. Equipping an item whose requirements aren't met asks first.
- Click an item to see its tooltip. Red cells = requirements not met, as in the stash.
- Each move writes the files through the safe writers (game closed, verification, backup). If the second write
  fails, the first file is put back as it was. A character file changed on disk since it was read (game, Character
  window) is never overwritten: it is reloaded and the move has to be done again.

## Character window (Character button)
Laid out like the old Hero Editor (Mastadex, ZonFire99): classic grey frames, Times New Roman, and the tab row at the
bottom of the window (Stats, Inventory, Waypoints, Quests; Alt + first letter switches tab), with the Hero Editor's own
SAVE, RELOAD and CLOSE buttons (normal / hover / pressed images and the window icon, taken from Hero Editor.exe 1.04;
mxl_he_art.py) and the line "Glory to the real Heroes ZonFire99 and Mastadex". A "Dark mode" box right of the tabs switches the
Stats, Waypoints and Quests tabs and the tab row to dark colours (remembered in settings as hero_dark_mode); the Inventory
tab uses the collector's own dark theme in both modes. SAVE applies the
changes of every tab at once; CLOSE asks to save unsaved changes.
- **Stats**: Name (with "Copy as"), Class, Level, Experience, Characteristics (Strength, Dexterity, Vitality, Energy,
  stat and skill points left), Constitution (life, mana, stamina current / max), Gold (person, stash), Character Type,
  Character Difficulty, file info. Every stat number box is editable: type a value and SAVE writes it through
  `set_stat` (gold / person + stash, experience, strength / dexterity / vitality / energy, stat & skill points, and
  life / mana / stamina current + max — those are stored in 256ths, the boxes show the game's own numbers and
  `\u2192 << 8` on write). A value that does not fit the save file's width for its stat (checked against
  itemstatcost CSvBits) is refused with a clear message before anything is written; raising the level still works
  like the game (experience, 5 stat points and 1 skill point per level); lowering it is refused.
- **Inventory**: paperdoll of the character or the mercenary (weapon sets I / II) and the 15×10 inventory. Drag items
  between slots and inventory; To stash / From stash, Edit…, Create here…, Delete.
- **Waypoints**: Normal, Nightmare and Hell side by side, each a tree "<Mode> Mode Waypoints" > Act > waypoint with
  check boxes; a mode or act box ticks everything under it. Hell also lists Median XL's Hell-only waypoints
  (Duncraig, Tran Athulua, Island of Skartara, Caldeum, Torajan Jungles, Vizjun, Silver City, Túr Dúlra).
- **Quests**: the same three trees. Ticking a quest gives its reward in that difficulty: Den of Evil and Radament
  +1 skill point each, Izual +2 skill points, Lam Esen's Tome +5 stat points, The Golden Bird +20 life (unticking a
  quest ticked here takes it back). Quests completed in game are locked (grey box) and never changed. Act
  introductions / travel flags follow, and finishing Eve of Destruction unlocks the next difficulty.
- Saves are rebuilt section by section (byte-identical when nothing changes), with the file size and checksum
  recomputed, then checked and written through the collector's safe writer (game closed, verification, backup).

## Angelic items
- "Angelic" in the quality list (above Rare) lists the 17 Angelic-tier bases of Median XL Sigma (Full Helm (Angelic),
  War Sword (Angelic), ...). They are not in the normal drop pool, so they are made as rares on those bases, with the
  rare affixes that can spawn on them, including the Angelic-only ones; item level 98+ (their base level).

## Mystic orbs and other special misc items
- Normal quality now lists every spawnable misc item under the name the game shows, including items with
  multi-line names that were missing before: unique mystic orbs ("Kara's Trinket — Mystic Orb"), Explorer's Caches,
  cube reagents, quest scrolls and the like. Items that would still share a name get their item code added.
- Mystic orbs show their effect, read from Median XL's mysticorbs table: in the list ("Mystic Orb: +5 to Strength")
  and under the preview, with the most orbs of that kind one item can take. The filter box has a "Mystic Orb" entry.
  The orb itself is stored like the game's (a simple item); its effect is applied when it is cubed into an item.
- Mystic Dyes are listed by colour ("Mystic Dye: Color: Light Blue", "Mystic Dye: Color: Rainbow"), with a
  "Mystic Dye" entry in the filter box. Other items that share a name (cycles, Scrolls of Enchantment, crafting
  scrolls, Explorer's Caches, riftstones, ...) are told apart the same way, by their in-game description, and the
  preview shows that description under the tooltip.

## Import a character from median-xl.com (Import character… button)
1. Open the character page (median-xl.com/char/<name>) in your browser while logged in and save it with
   "Save as… → Web page, HTML only" (or complete).
2. Click **Import character…**, pick the saved .html, and give the new character a name.

The new character is built from the character you have selected, or any other save in the folder, so it has the same game version.
- Class, level, base attributes (strength/dexterity/vitality/energy from the export), skill points per skill.
- Quests: every quest and waypoint of the difficulties where the export has quests done, along with their rewards.
- All items on the page, equipped, inventory, belt and stash, copied **exactly as shown** (the user's choice; this
  is the one place where the legit-only rule does not apply). Each item keeps its base, quality, unique/set/runeword,
  magic affixes, picture, ethereal flag, base defense and sockets with their socketed items, and its stats are read back from the tooltip lines
  (mxl_statparse). Socketed items' stats are taken off the parent's, so nothing counts twice. Container and shrine
  vessel counts are stored too.
- Stash items go to page 1 of the new character's stash. .key/.map/.ma files are copied from the template.

A report window lists everything that could not be copied exactly:
- quests the quest log doesn't have (Sigma's Inquisitor / Justicar);
- skill or attribute points beyond what the level and quests give (they are set as exported);
- descriptive lines that are not stats.

Not copied: mystic-orb bookkeeping (the orbs' stats are in the item), rare items' real names (the page shows only
the base name), the mercenary (not on the page).

## Legit-only rules
Every value comes from the game tables and stays inside the ranges the game rolls:
- affixes, innate (automagic) affixes, rare names and Superior bonuses are limited to what can spawn on that base at that item level;
- set and unique items have no innate affix and get the game's durability multipliers;
- runewords only go in bases with the right item type and number of sockets; their runes are socketed automatically;
- ethereal follows the game's rules: defense ×1.5 stored, durability halved, never on set items.

Every created item is read back with the collector's own reader and checked against its range rules
before it is written. Writes go through the collector's safe writer: the game must be closed, the file is checked
after writing, and a `.bak` backup is made once per session.

## Editing items outside the rules
Items are opened with Edit item exactly as they are, even when they break the game's rules (hacked or
out-of-range values, Sigma upgrades the editor does not model): every stat the item's mods don't give, or give
outside their range, is kept as it is and listed above the sliders, and the status line warns instead of blocking
"Replace item". Moving a slider changes only that value. Tempered (quality 9) items open too (name only).

## Crafted items
- "Crafted" in the quality list. The list shows every base a crafting recipe takes (Angelic bases included):
  shrine-crafted weapons and armor, amulets (alchemy oils).
- Pick the base, then the shrine (or oil) recipe ("Abandoned Shrine (10) + Oil of Intensity: +72-120% Bonus to
  Attack Rating; ..."). The item is rolled once like the cube does: a name and 4 rare affixes (1-3 prefixes,
  1-3 suffixes, weighted by the game's frequencies, one per group) and every value.
- Then everything can be changed within the game's values: the name, each affix (only affixes that can spawn on
  that base at that item level), the recipe, and every value with its slider (the recipe's ranges and the
  affixes' ranges). "Reroll item" rolls a new name, affixes and values on the same base and recipe; Max / Random /
  Min set only the values.
- Edit item works on crafted items. The recipe and the affixes are found from the item's stats (from its affix ids
  when it has them; for an imported copy they are worked out from its stats and its Prefixes / Suffixes
  counters). Whatever they don't explain (shrine blessing, corruption, other upgrades) is kept on the item as it
  is and listed above the sliders; the status line says how many stats were kept.
- The shrine / recipe list works for every recipe (before, picking any recipe other than the first one was ignored:
  the combobox callbacks shared one Python variable that later rows overwrote; every callback now keeps its own list).
- Not modeled: shrine blessing ("Shrine Blessed") and other upgrades of a crafted item, crafted jewels.

## Uniques with special text (The Collector, Azurewrath, Void-Infused..., 2026-10-03)
- The orange / grey text of a unique (The Collector's "Gematria ... +25% Bonus to Defense ... (Bonus for each
  Socketed Great/Elemental Rune)", Azurewrath's rules, Void-Infused's "Erupting Strike grants ...") is ONE text stat
  (375 / 377 / 378 / 385, param = string index) — the bonuses come from the item's hidden skill (+1 to The Collector,
  oskill 1913) and hidden stats. The import read those text lines as real stats (flat +25% defense, +10 life after
  kill, +8% spell damage) and missed the hidden skill and "Orb Effects Applied to this Item are Doubled".
- Import now: the item's unique row (picked from a first reading among same-name rows, e.g. Relics) and the cube
  upgrades the page shows give the text stats; a text whose whole text is on the page is taken as that stat (cube
  upgrades first: they replace the row's text, e.g. Relic states 385) and its lines are not read as stats; row
  stats whose lines are on the page but were not read are added (oskills, orb doubling), a skill read with another
  skill of the same name takes the row's skill; the base's innate affix is set (auto affix id, hidden innate
  element 395/242, "Innate X Damage" 415 read from its page line).
- Uniques and set items get their base's innate (automagic) affix in the Item Creator too (Innate affix list), as
  the game's do (real copies: auto affix on every Sacred / Angelic unique and set item): a created Azurewrath now
  has exactly the stats of the game's (Innate Cold Damage, Adds 160-250 Cold Damage, hidden 151 / 395 / 415...).
- Test (t2/imp_rt.py): the 1838 real uniques of the test stashes, their tooltip lines as a page, imported and
  compared: The Collector / Azurewrath identical; items with differences 1141 → 1008 (the rest: older game
  versions, charges, upgrade states the page cannot tell apart).

## D2 look (homage to Udie's Ultimate Median XL Item Editor, 2026-10-03)
- Main window: the stash and the character's equipment / inventory are drawn on Median XL Sigma's own in-game
  panels (Tartarus theme, as in game; settings key d2_theme = "classic_sigma" for the red Classic theme): stash
  panel with "Storage Page: n / 10" and the character's stash gold in the game's font, inventory panel with the gear
  frames (slot silhouettes when empty), the "I II" weapon-set tabs (clickable), the character's gold, the close
  buttons. Both panels use the same cell size, chosen so they fit the screen side by side with the detail panel.
  Items: no cell boxes, red background when the character cannot use them (like the game), outline when selected.
- Item Creator / Editor: a header on the game's stone with the title in the game's font (font30), the item in a
  gear frame and its name in its quality colour; stone-and-gold buttons.
- The art is read from the player's own game files (MPQ: data\global\themes\<theme>\game\..., fonts
  data\local\font\latin\*.dc6/.tbl, palette ACT1), decoded (mxl_d2ui_dc6.py: DC6 → PNG, pure Python) once and kept
  in <user dir>\ui_art\<theme>\ (re-extracted when the Median XL version changes); a brightness curve (gamma 0.6,
  measured against an in-game screenshot) matches the game's on-screen colours. Nothing of the game is in the exe.
- "D2 look" checkbox in the top bar (applied at the next start). Without the game folder / art, the plain layout.
- Layout values (panel pixels, 512×704, 29 px cells): mxl_d2look.py (stash grid at 53,150; inventory grid at 37,329;
  gear frames measured by template matching on a screenshot). Text with characters the game font lacks (Vietnamese)
  falls back to a normal font in the same gold.

## Item Creator window, affixes, sockets and corruption (user feedback, 2026-10-03)
- Window: sized from the screen (up to 1750×1080, never larger than the screen), three resizable columns
  (catalog | options | preview: drag the separators). All options and the variable values are in one scroll area;
  the status line and the Close / Create / Replace buttons are always visible at the bottom, however many stats the
  item has. The mouse wheel scrolls the options anywhere over them and never changes a combobox by accident.
- Affix lists show the game's own tooltip text with the ranges: "+(31 to 40) to all Attributes   [L80, #41]",
  "+(180 to 200)% Enhanced Damage" (before, only the first stat's name was shown: all-attribute affixes looked like
  "to Strength" and Enhanced Damage affixes showed no text). Same for innate affixes and crafting recipes.
- Affix groups: the game never puts two affixes of one group on an item (e.g. the 200% Enhanced Damage prefix and a
  spell damage prefix are both group 110). An affix that conflicts with another chosen one is marked "⚠ same group as
  Prefix 1" in the list; choosing it asks to replace the other one. A crafted item already holding its 4 affixes says
  so instead of breaking. When the options cannot make an item, the preview says why (it no longer just goes blank).
- Sockets: "Max sockets (n)" for every item that can have sockets (set items included: Sigma's Sacred sets carry
  sockets, 175 of 177 in the test saves have the max). New uniques, set items and crafted items start with the max,
  as the game gives them; the box stays ticked when the item level or the base changes.
- Corruption (Sacred / Angelic gear and jewelry, types under 'ssgl'): "Corruption" list with every outcome and its
  chance, from cubemain: Corrupted Crystal step (25% +100 Required Level, 28.5% no effect, 46.5% not revealed yet;
  unique rings: +50 / -10 Required Level or corrupted), then the Oil of Craft reveal table (hidden roll 1-10000,
  stat 498; 73 outcomes such as +1 to All Skills 0.45%, +20% Cast Speed 2.3%...). "Roll like the cube" draws one
  with the game's chances. Stats: 497 = Corrupted, 496 = "(Cube with Oil of Craft to Reveal)", 498 = hidden roll.
  Editing a corrupted item finds the outcome that explains its stats (the rest is kept as before); 4194 items still
  rebuild identically.

## Loading screen (mxl_splash.py, 2026-10-03)
Homage to Udie's editor: while the editor loads, Diablo II's "door opening" loading animation plays
(`data\global\ui\loading\loadingscreen.dc6`, 10 frames, palette `loading`, read from the player's game files).
- The robed figure is painted out (smooth fill of the surrounding light, feathered edges) and the program icon's
  capybara stands on the platform facing the door, darkened / rim-lit / washed by the door's glare per frame,
  with a contact shadow. "LOADING..." is replaced by "Median XL Capybara Editor" in the game's Exocet font.
- Runs as a separate process (the exe started again with `--capy-splash <pid>`), so the editor's blocking table
  load does not freeze it. Closes (fade) when the main window is built, before any question / file dialog /
  data-rebuild progress window of the start, if the editor dies, or after 90 s. Flag file in %TEMP%.
- Frames are built once (~5-8 s) into `<user dir>\ui_art\splash\door-v7-*.png`; bump `VERSION` to rebuild.
- Only when the D2 look is on and the game folder is known; otherwise no splash (plain fallback inside the
  splash process if the art can't be read).

## Values the item can store, sockets audit (2026-10-03)
- Every stat is saved in a fixed number of bits (ItemStatCost save bits / add): a mod range that asks more is narrowed
  to what can be stored (`Creator._fit_storage`, mods adding to one stat share the room). Alnair / Thelema
  "to Summon Attack Rating" 100-200 / 130-180 -> up to 155, Spire of Kehjan 250 Damage Reflected -> 155 (a real
  Sacred War Staff in a shared stash has exactly 155), Halberd skill suffix 21-33 -> 21-30 (real Halberds: 30),
  Ring of Woe's corruption roll 1-10000 -> 1-9999 (+1 from its other mod).
- Rare names: a rare prefix is saved as index + 183 in 8 bits, so Sigma's last 4 rare prefixes are not offered.
- Lists: misc items no affix can spawn on are left out of Magic / Rare, gold out of Normal, runewords without a base
  (Secret Jewelwords) out of Runeword.
- Sockets: innate "sock" (stat 194) becomes header sockets capped at the max, never a stat (Angelic +6,
  Mastercrafted +6/+3/+4/+3, qblt belts +2).

## Median XL Sigma item layouts (mxl_format_fix.py)
The collector's item reader is replaced at start-up by the same reader plus two Sigma cases it did not know, which
stopped stashes from opening ("FormatError: 'JM' expected at byte ..."):
- quality 9 items ("tempered", e.g. the "Orb Effects Applied to this Item are Doubled" / Shrine Blessed gear): only
  the two name bytes follow the header, no affix slots;
- weapons / armor whose item type is not under 'weap' / 'armo' (the Staff of Herding): no defense or durability in
  the save, as the game reads them only for those types.
The creator's encoder / decoder and the import follow the same rules.

## Languages (English, Français, Tiếng Việt)

The Language setting of the main window now covers every window of the editor: the collector's own texts and the
added windows (Item Creator / Editor, Character window, equipment panel, import). Texts are in `lang/<code>.json`
next to the exe: `en.json` (reference, all keys), `fr.json`, `vi.json`. The added windows' keys start with `cr.`,
`ch.`, `he.`, `inv.`, `im.`; `mxl_lang.T(key, english)` reads them and falls back to the English text written in the
code, so a missing key never breaks a window. Fields in braces (`{name}`, `{level}`...) must stay unchanged.
Game text (item, stat, skill, quest and waypoint names, tooltips) comes from Median XL's tables and stays in English.
To add a language: copy en.json to lang/<code>.json, set `_language` and translate the values.

## Program icon
The exe file, the taskbar and every window use the capybara icon (capybara.ico in the exe's resources; mxl_app_icon.py
for the windows). The Character window keeps the old Hero Editor's own icon.

## The plain Hero-Editor grids, D2 panels off (2026-11-10, third round)
The game-art panels came out - everywhere plain Hero-Editor grey (the user's verdict: the dark
collector / D2 mix is not what Hero Editor looked like):
- `mxl_d2look.disable()` in `run()` keeps the game-art look off for good: no treasure of panels, no
  resized cell for art, no 'D2 look' checkbox (mxl_d2look still ships: `D2.button` falls back to the
  plain ttk buttons the theme styles, the creator header falls back to its title label).
- New `mxl_he_grid.py`: the collector draws its grids with its near-black theme (mxl_theme constants
  copied by value into each window module at import). `install()` wraps
  `App.__init__` (the root exists by then, `_build` yet to run) and replaces the colour copies in
  mxl_theme, mxl_gui, mxl_gui_detail, mxl_char_gui, mxl_inv_gui, mxl_creator_gui, mxl_import (and
  mxl_tooltip / mxl_library_gui where present): light-grey panel (#f0f0f0), pale cells (#e2dfd3) with
  grey outlines, gold selection, blue / red drop tints, and the item text panel + tooltips light with
  black text. The game icon colours (GAME_COLORS) get dark-on-light shades so plain white text stays
  readable on grey. `FONT` becomes a family the runtime really has and the grid's own app.cell_font is
  rebuilt from it inside the wrap.
- The item icons, grid layout, drag & drop and the detail drawing code are untouched - only colours.

## Hero-Editor look everywhere, ASCII-safe fonts and labels (2026-11-09, second round)
Everything now wears the Hero-Editor look, not only the self-styled windows:
- `mxl_he_theme.py` is the outermost look wrapper (`run()` installs it after the splash): 'clam' ttk
  style in the HE palette (grey windows #f0f0f0, white entries, black text, stone-grey buttons #e1e1e1),
  plus a walker that repaints every plain tk widget in the app when windows open - and re-checks every
  2.5 s so late-built widgets (the creator rebuilds its lists constantly) are picked up too.
- It never repaints what is already dark: the black/gold chrome and status bars of the Hero-Editor
  windows, the stone D2 buttons, the item preview and the dark item lists stay as they are. Canvases
  never get recoloured - the stash grid and the D2 panels keep their art.
- Missing font families are repaired (no more glyph boxes on Linux): Palatino Linotype / Times New
  Roman / Segoe UI fall back to DejaVu / Liberation (see `safe_family` / `safe_font`, also for text
  items inside drawing canvases). `_parse_font` reads family / size / styles from the raw spec because
  building a `tkfont.Font` normalizes a missing family away.
- Clean labels: the stat rows and the creators' pickers no longer show `[42, 7 b]` / 'stat #N' ids,
  param numbers or bit counts. The technical line (stat id, param, save bits, value, save range) goes
  to the status bar instead when a row is clicked or a stat is picked (`_row_info_text`,
  `cr.raw.statinfo`, both in mxl_he_stats and the two creators' pickers).
- ASCII sweep through every UI string: em dash -> '-', ellipsis -> '...', the ex / cross marks -> 'x',
  the bullet / arrow / warning glyphs -> '* ' / '->' / '!'. Kept: the Diablo colour-code prefix in
  game text ('-c-...' is data, not decoration) and the accented names in the data ('Tur Dulra' etc.).
  The ' - ' name separator changed everywhere, so producers and parsers stay in sync.
- note for tests: the duplicate game texts (e.g. stat 192 and 196 share '[percent] Chance to cast ... on
  Kill') collapse into identical labels now; the pickers resolve them by index, so tests must too.

## One editor, fixed deletes, type-ahead, quantities, base-D2 character screen (2026-11-10, fourth round)
Six user-reported issues, all verified headless (`test_round4.py`, plus the round-3 suites re-run):

1. **The OHMAN skill played another skill.** The game reads a chance-to-cast param as 16 bits
   effectively, but the isc table gives 17 (skill id 6 bits + level 11). OHMAN (skill id 1697)
   encoded as `(1697 << 6) | lvl` = over 65535 and rolled in-game. `mxl_statnames` now caps the
   param at `min(isc bits, 16)`: `skill_fits` refuses skills whose id does not fit,
   `encode_skill_param` returns `(None, reason)` (reason 'unknown' / 'rolled' / 'level') and the
   creators show why in the status bar; the skill dropdowns are filtered (`skill_names_sorted(data,
   sid)`), so a skill that cannot be stored is never offered. The class stat (83) encodes through
   `mxl_rules.CLASSES` indices, not skill names. Duplicate labels in the stat pickers are suffixed
   ' (2)' / ' (3)' (the identical-text twins are 192 / 196; 195-203 differ by event text and stay
   distinct).
2. **Type-ahead in every dropdown** (`bind_typeahead` in mxl_creator_gui): typing a letter jumps to
   the first value starting with it, wraps around, and stays put when nothing matches. Wired into
   the raw rows, the edit-table rows and both skill pickers. The handler is returned for headless
   tests (synthetic key events do not reach widgets under a withdrawn root).
3. **Removing an attribute in Edit item mode failed.** The save format writes stat GROUPS with
   their lead (17+18, 48+49, 50+51, 52+53, 54+55+56, 57+58+59), so deleting one member put it back
   as a 0; the "left out due to the model" error was the 'kept as they were' warning counting
   bookkeeping delta rows. Now: `_edit_delete` drops the whole group (lead + followers +
   co-followers), marks the keys in `spec['_drop']`, `build` filters dropped keys before the
   keep-zero pass, `render_mods` hides them, re-adding the stat clears the drop (also via
   `route_target` and the raw commits), and the warning counts the item's own kept stats only
   (`spec['_extra_kept']`, `_take_over` on user edits, `_kept_count` - one per stat id, visible
   stats with a non-zero final value).
4. **One item editor.** "Item stats..." (stash and character menus) now opens the same CreatorWindow
   edit mode as "Edit item..." (`mxl_he_stats.open_item_stats` -> `edit_selected(app)`,
   `open_char_item_stats` -> the character window's own `edit()`); the old flat ItemStatsWindow is
   dead code. `clamp_window` keeps every window fully on screen (creator, character window, stats
   window, import report): never bigger than the screen, centred when not placed yet, drag bars
   always reachable.
5. **Standard Diablo II character screen** (`mxl_d2look_art.char_panel_d2`, independent of the
   switched-off Sigma panels): built from the base-game MPQs only (patch_d2 / d2exp / d2data -
   `base_mpqs`, `read_base`, `base_frame`), invchar6 frames 4..7 scaled x1.6 (320x432 -> paperdoll
   512x400), below it the stone filled with mirror-tiled copies of the clean patch (200,374)-(314,428)
   so nothing of the game's own grid repeats visibly. The equipment boxes sit at `GEAR_D2`
   (native game positions x 1.6), the I / II tabs at `WSET_TABS_D2`, the gold button from
   goldbtn.dc6, and the 15x10 inventory grid is drawn D2-style (dark cells `CHAR_CELL_BG`, grey
   borders) over the stone at `CHAR_GRID` (37,400). Fallback on any error: the plain doll layout
   (`self.d2 = False`).
6. **Quantity submenu** (`mxl_rc_menu._quantity_cascade`): right-click a stackable item (clusters,
   quivers, throwing weapons - `base.stack_max is not None`, not a compact record) in the stash for
   Max / Min / Add... / Remove...; Add and Remove ask for a number. `_set_quantity` decodes the
   item, rewrites `quantity` (9 bits), re-encodes with the socketed children behind it and writes
   the stash through the collector's safe single-write editor.

Round-4 test suite: `/tmp/opencode/test_round4.py` (43 checks, all pass headless; the fix-3 repro
item is built in the test itself with the group stats, since the user's Stinger Crossbow is no
longer in the stash).

## Files
- `mxl_creator.py`: bit-level item encoder/decoder (lossless), the legit generators and crafting recipes (cubemain).
- `mxl_creator_gui.py`: the creator window and the main-window buttons.
- `mxl_char.py`: character save reader/writer (stats, quests, waypoints, items, mercenary).
- `mxl_char_gui.py`: the character window.
- `mxl_app_icon.py`: the capybara window / taskbar icon. `rsrc.py`: puts an .ico into the exe's resources
  (`repack.py ... --icon=capybara.ico`).
- `mxl_he_stats.py`, `mxl_he_theme.py`: the flat stat table and the look of the Hero-Editor windows
  (mxl_he_theme is the outermost look wrapper: ttk palette + walker + font repair for every window).
- `mxl_he_art.py`: button images and window icon from Hero Editor.exe 1.04 (ZonFire99, Mastadex).
- `mxl_statnames.py`: shared stat labels (the buffalo-safe game text) and skill-param dropdowns for the
  editors (see 'Stat names, skill params and the full stat list of the Edit item window').
- `mxl_inv_gui.py`: the equipment and inventory panel of the main window (drag & drop with the stash).
- `mxl_statparse.py`: reads tooltip lines back into item stats (uses the collector's tooltip text as the reference).
- `mxl_format_fix.py`: the reader fix above.
- `mxl_import.py`: the character page import (page reader, item rebuilder, new character, Import button).
- `mxl_d2look.py`, `mxl_d2look_art.py`, `mxl_d2ui_dc6.py`: the game-art look (switched off since 2026-11-10,
  see 'The plain Hero-Editor grids, D2 panels off').
- `mxl_he_grid.py`: the light grid constants (replaces the collector's dark theme copies everywhere).
- `mxl_splash.py`: loading screen (door animation with the capybara).
- `mxl_log.py`: the log file `capybara.log` in the settings folder (saves, backups, imports, errors).
- `mxl_lang.py`: translation helper of the added windows (see Languages).
- `repack.py`, `carch.py`: rebuild the PyInstaller exe with these modules (Python 3.10:
  `python repack.py "MXL Item Collector.exe" "MXL Item Collector (Creator).exe"`, plugin folder path set inside).
