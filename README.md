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

## Install
1. Download the latest `MXL-Capybara-Editor-v*.zip` from the [Releases](../../releases) page.
2. Unzip it anywhere and run `MXL Capybara Editor.exe`.
3. Edit freely: the **Unrestricted** switch frees the values (the save format is the only limit) and adds a
   raw stats list where any stat (id, param, value) can be added, edited or deleted on any item. You do not
   need to close the game; changes show after its next save & exit / restart.

## Reporting a problem
The editor keeps a log at `%LOCALAPPDATA%\MXL Capybara Editor\capybara.log`, which records saves, backups, imports and errors.
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
