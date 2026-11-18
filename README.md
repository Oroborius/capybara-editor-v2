# MXL Capybara Editor V2

An offline item creator and character editor for **Median XL**, built on top of MXL Item Collector.

![Main window](docs/main_screen_preview.png)

## Features
- **Item Creator**: make unique, set, runeword, Angelic, rare, magic, superior or normal items, including mystic orbs and other special misc items.
- **Edit / Delete item**: edit any stash item in the creator and write it back in place. A backup is made before every change.
- **Equipment and inventory next to the stash**: drag items between the stash, the inventory, the equipment slots and the mercenary.
- **Character window** (in the style of the old Hero Editor): stats and level-up, inventory, waypoints and quests for Normal, Nightmare and Hell.
- Safe writes: the game may stay open — this build removes the editor's game-closed checks, every file is verified, and backups are kept.
- Languages: English, French, Vietnamese (`lang/`).

## New in V2
V2 is a fork of [capybara-heroeditor](https://github.com/Nugwa628/capybara-heroeditor) 1.2. Everything below is
unique to it.

**Not yet tried in the game.** The newer additions (game-art panels, compact layout, the stat screen, the skill
tree, the Mercenary / Quests+ / Counters / Hotkeys pages, the save check, Fill sockets) pass the editor's automated
test suite, which works on copies of sample saves in a virtual display; it checks that they work and write the
right bytes, not how they look. They have not yet been checked in the running game, and the Windows build has only been run under Wine, not on real Windows. Keep your backups, and
please report what you find.

**Editing**
- **Unrestricted editing**: any stat (id, parameter, value) can be added to, changed on or removed from any item;
  the save format is the only limit. The game may stay open while you edit.
- **Item stats tab** in the style of Hero Editor's Magic Attributes list: compact numbered slots with the value,
  level and skill editable in place (skills and classes by name), and a stat picker with categories, a Recent list
  and a Find box that searches every category as you type. Fully usable from the keyboard. The x in the first
  column deletes a stat.
- **Stat parameters by name**: for stats that carry a parameter, the editor shows what it means and lets you pick
  it by name: the skill and level of "chance to cast" stats, the class, the element and attribute of innate
  elemental damage, the mystic orb, the state. Typing `#N` sets a raw number.
- **Right-click menus on every item** (stash, equipment, mercenary, inventory): Edit, Item stats, Duplicate,
  Copy / Cut / Paste, Move to page, Delete, Change quality, Quantity, Export / Import item, and Hero Editor's
  "Specific editing functions" (defense, durability, ethereal, sockets, personalize, clear magic attributes,
  fill / remove socketed items, magic-attributes buffer).
- **Fill sockets with ...**: copy a gem, rune or jewel, then fill an item's free sockets with copies of it. An item
  with too few sockets gets more first, up to what its base allows (with "Unrestricted", any weapon or armor up
  to 6). Not offered where it cannot work, such as runewords.
- **Make perfect**: one click raises every roll of an item to the top of its range. Mystic orb additions are
  recognised and kept. It replaces the value sliders of the main window.
- **Edit items where they are**: equipped, mercenary and inventory items can be edited from the Stash tab, without
  moving them to the stash first.
- **Undo** (Ctrl+Z, 50 steps) for delete, create and replace; Delete key removes the item under the cursor. An
  undone delete puts the item back at its old place in the file, so the file ends up exactly as before.
- **Edits that change nothing leave the item as it was**, byte for byte: "Edit item" followed by Replace without
  changes no longer gives the item a new id, resets durability, drops socketed items or changes quantities.
- **Honorific items** (quality 9) are read, shown and kept intact (the original editor crashed on characters
  holding one), and can be made in the Item Creator.
- Item details follow the mouse: hovering an item shows its stats.

**Item Creator**
- Rolls are typed number fields (Up / Down, PgUp / PgDn step them) with Min / Random / Max buttons, instead of
  sliders.
- Stats are added through the same slot list and categorised picker as the Item stats tab; the picker completes
  what you type.
- Honorific is one of the qualities.
- Unique relics are listed by the skill they grant ("Relic - Bladestorm"); entries with the same name are told
  apart (by their bonus line, "[not dropped]" or their table row), and empty placeholder rows are hidden.
- The search also matches the bonuses an item comes with ("stormlord" finds Arrogance).
- Pickers accept typing (Enter takes the exact, prefix or substring match).
- Barrels, crates, clusters and containers start at Quantity 1000.
- Stats deleted from an item no longer come back at 0 when it is edited again.

**Character**
- **Stats page drawn like the game's character screen** (dark look): name, level, attributes and stat points are
  edited in place; the + buttons spend a stat point. Further pages: the game's two stat list pages (damage,
  pierce, speed, defenses and more), "All Item Attributes" and "Saved Values" (experience, skill points,
  life / mana / stamina, gold, hardcore and other flags, difficulty). Two pages are shown side by side when the
  window is wide enough. The totals are the editor's own sum of equipped items (with their socketed items),
  inventory charms and set bonuses, so they can differ from what the game shows. The light look has a plain page
  with the same fields.
- **Skills page laid out like the in-game tree**: the game's panel, skill icons, tree web and tabs. Click a level
  box to type a level, left-click an icon for +1, right-click for -1. Hovering a skill shows its game tooltip,
  computed from the game's own tables for the character's levels (a few lines still show raw values). Skills whose
  required level or prerequisites are missing show their level in red, as in the game. The remaining skill points
  are shown as stored; changing levels does not spend them.
- **Mercenary page**: name, type, level / experience and whether it is dead. Every slot the mercenary can wear is
  shown in the Stash tab's equipment view.
- **Quests+ page**: every quest word of each difficulty with its bits, plus Re-open and Complete. The plain Quests
  page now writes the quest words the way the game does (the Act V word was wrong before).
- **Counters page**: Signets of Learning and Skill used, kill counters (achievements) and play time.
- **Hotkeys page**: the 16 skill hotkeys and the four mouse-button skills, with skill icons.
- Character tab edits stay pending until SAVE and survive changes made elsewhere in the meantime (for example an
  item moved from the Stash tab); RELOAD discards them.
- The Character dropdown loads the chosen character at once.

**Safe saving**
- **Save check**: before every write, a second, independent save reader checks the new file (structure, size,
  checksum, item counts), and a one-line summary of what changed goes into `capybara.log`. The setting
  `savecheck` in `settings.json` (or the environment variable `MXL_SAVECHECK`) chooses what happens when the
  check fails: `strict` (default) refuses the write, `warn` writes it, shows a warning and keeps an extra backup,
  `off` turns the check off.
- **Compare with backup...** (in the "More »" menu) shows what differs between a save file and one of its backups,
  and can put the backup back.
- The same reader can be used by hand from the `tools/` folder: `python3 -m mxlsave verify <file>`,
  `python3 -m mxlsave dump <file>`, `python3 -m mxlsave diff <old> <new>`.

**Interface**
- **Tabs instead of windows** (Stash, Character, Creator, Item stats): made for tiling window managers.
- **Dark Diablo theme** by default, built from Median XL's own UI art (stone, bronze, gold, the game's menu
  buttons); the Hero Editor light look is one checkbox away ("Dark D2 theme", applied at the next start).
- **Game-art stash and inventory**: in the dark look the stash and the character's equipment / inventory are drawn
  on Median XL's own in-game panels. Without the game files they are plain dark grids.
- **Compact layout, usable at 800x600**: cell sizes follow the window size, pages scroll only when they must, and
  toolbar items that do not fit move into a "More »" menu.
- Game art is cached, so the editor starts without the long freeze.

**Platforms**
- **Native Linux AppImage** (no Wine): finds the Median XL save folder inside Wine, Lutris, Bottles and Steam
  prefixes, opens at a size that fits the screen, and does not double-scale on HiDPI Wayland
  (`MXL_UI_SCALE=<factor>` to choose a scale). Text is antialiased (Tk built with Xft; plain X fonts as a
  fallback).
- Windows build from the same source tree, also buildable on Linux.

**Tests**
- A regression suite (`tools/run_tests.sh`, see [`tests/README.md`](tests/README.md)) runs the editor headless on
  copies of sample saves: no-op saves stay byte-identical, item and character edits change only what was asked,
  and every tab and page opens in both looks at 1280x720 and 800x600.

## Install
**Linux**: build the AppImage (see [Building](#building)), make it executable and run it. Settings and the log are
in `~/.local/share/MXL Capybara Editor/`. Set `MXL_SAVE_DIR=<folder>` to work on a copy of your saves.

**Windows**: build the release folder (see [Building](#building)) and run `MXL Capybara Editor V2.exe` from it.
Settings and the log are in `%LOCALAPPDATA%\MXL Capybara Editor\`.

On first start, choose the Median XL game folder. Backups are made before every change; you do not need to close
the game, changes show after its next save & exit.

## Reporting a problem
The editor keeps a log (`capybara.log` in the settings folder above), which records saves, backups, imports and errors.
Attach it to your bug report, along with the saved character page if the problem is with an import.

## Source
The Python source is in [`src/`](src). The editor is a set of modules added to the MXL Item Collector exe:
`repack.py` rebuilds the PyInstaller exe with these modules included, and `rsrc.py` sets the capybara icon.
See [`docs/DEVELOPER_NOTES.md`](docs/DEVELOPER_NOTES.md) for how each part works.

## License
[MIT](LICENSE). This covers the code in this repository only. MXL Item Collector, the Hero Editor art and the
Median XL game data belong to their respective authors.

## Credits
Hero Editor button art and the window layout come from Hero Editor 1.04 by ZonFire99 and Mastadex. Glory to the real Heroes.

## Building
Windows exe and native Linux AppImage, both from this source tree: see [`docs/BUILDING.md`](docs/BUILDING.md).

```
packaging/build_windows.sh      # dist/windows/MXL Capybara Editor V2/   (packaging\build_windows.ps1 on Windows)
packaging/build_appimage.sh     # dist/linux/MXL_Capybara_Editor_V2-x86_64.AppImage
```
