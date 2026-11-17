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

**Editing**
- **Unrestricted editing**: any stat (id, parameter, value) can be added to, changed on or removed from any item;
  the save format is the only limit. The game may stay open while you edit.
- **Item stats tab** in the style of Hero Editor's Magic Attributes list: compact numbered slots with the value,
  level and skill editable in place (skills and classes by name), and a stat picker with categories, a Recent list
  and a Find box that searches every category as you type. Fully usable from the keyboard.
- **Right-click menus on every item** (stash, equipment, mercenary, inventory): Edit, Item stats, Duplicate,
  Copy / Cut / Paste, Move to page, Delete, Change quality, Quantity, Export / Import item, and Hero Editor's
  "Specific editing functions" (defense, durability, ethereal, sockets, personalize, clear magic attributes,
  fill / remove socketed items, magic-attributes buffer).
- **Make perfect**: one click raises every roll of an item to the top of its range. Mystic orb additions are
  recognised and kept. It replaces the value sliders of the main window.
- **Edit items where they are**: equipped, mercenary and inventory items can be edited from the Stash tab, without
  moving them to the stash first.
- **Undo** (Ctrl+Z, 50 steps) for delete, create and replace; Delete key removes the item under the cursor.
- Item details follow the mouse: hovering an item shows its stats.

**Item Creator**
- Unique relics are listed by the skill they grant ("Relic - Bladestorm").
- The search also matches the bonuses an item comes with ("stormlord" finds Arrogance).
- Pickers accept typing (Enter takes the exact, prefix or substring match).
- Barrels, crates, clusters and containers start at Quantity 1000.
- Stats deleted from an item no longer come back at 0 when it is edited again.

**Character**
- **Skills tab** laid out like the in-game trees: real skill icons, tree web and connector arrows from the game
  files, tree names as the game shows them, tooltips on hover.
- The Character dropdown loads the chosen character at once.

**Interface**
- **Tabs instead of windows** (Stash, Character, Creator, Item stats): made for tiling window managers.
- **Dark Diablo theme** by default, built from Median XL's own UI art (stone, bronze, gold, the game's menu
  buttons); the Hero Editor light look is one checkbox away ("Dark D2 theme", applied at the next start).
- Game art is cached, so the editor starts without the long freeze.

**Platforms**
- **Native Linux AppImage** (no Wine): finds the Median XL save folder inside Wine, Lutris, Bottles and Steam
  prefixes, opens at a size that fits the screen, and does not double-scale on HiDPI Wayland
  (`MXL_UI_SCALE=<factor>` to choose a scale).
- Windows build from the same source tree, also buildable on Linux.

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
