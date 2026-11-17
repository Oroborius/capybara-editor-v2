# Building MXL Capybara Editor V2

The editor is a set of modules (`src/`) added to **MXL Item Collector**. Both builds start from a *base*: a folder
holding a PyInstaller exe with the collector's modules and its `_internal/` folder. The base is either

- the original `MXL Item Collector` folder, or
- an unzipped `MXL Capybara Editor` release (default: v1.2 is downloaded into `.cache/base/` and checksum-verified).

Set `BASE_DIR=<folder>` (`-BaseDir` in PowerShell) to use your own base. Nothing is installed on the system: all
downloads and outputs stay in `.cache/` and `dist/` inside the repository.

| Target  | Command                         | Output                                                     |
|---------|---------------------------------|------------------------------------------------------------|
| Windows | `packaging/build_windows.sh` (Linux) or `packaging\build_windows.ps1` (Windows) | `dist/windows/MXL Capybara Editor V2/` + zip |
| Linux   | `packaging/build_appimage.sh`   | `dist/linux/MXL_Capybara_Editor_V2-x86_64.AppImage`        |

## Windows build

`src/repack.py` rewrites the base exe's PyInstaller archive with the editor's modules. It must run with
**Python 3.10** (the exe's own version: the modules are stored as 3.10 bytecode), but it is pure standard library,
so the Windows exe can be built on Linux as well. No Wine or Windows SDK is needed to build.

On Windows (PowerShell, Python 3.10 from python.org so that `py -3.10` works):

```powershell
packaging\build_windows.ps1                       # downloads the v1.2 base
packaging\build_windows.ps1 -BaseDir "C:\Games\MXL Item Collector"
```

On Linux (needs `curl`, `unzip`, optionally `zip`, and a Python 3.10):

```sh
uv python install 3.10          # user-level, once; or set PYTHON310=/path/to/python3.10
packaging/build_windows.sh
```

Result: `dist/windows/MXL Capybara Editor V2/` with `MXL Capybara Editor V2.exe`, `_internal/` and `lang/`.
Ship the whole folder (the zip next to it).

## Linux build (AppImage)

The Linux build is native, not Wine: the collector's modules are plain Python bytecode, so they are taken out of the
base exe (`packaging/extract_host.py`) and run by a bundled CPython 3.10.

```sh
packaging/build_appimage.sh
chmod +x dist/linux/MXL_Capybara_Editor_V2-x86_64.AppImage
./dist/linux/MXL_Capybara_Editor_V2-x86_64.AppImage
```

Needs only `curl`, `tar` and `unzip`. The script downloads (once, into `.cache/`):

- a standalone CPython 3.10 ([python-build-standalone](https://github.com/astral-sh/python-build-standalone);
  Tcl/Tk and X11 built in, glibc 2.17 or later, so the AppImage runs on any current x86_64 distribution);
- `appimagetool` (skipped when `appimagetool` is on `PATH` or `APPIMAGETOOL=` is set).

Options:

- `packaging/build_appimage.sh --appdir-only` stops after `dist/linux/AppDir/`; run it with `dist/linux/AppDir/AppRun`.
- `PYTHON_DIR=<unpacked standalone python>` bundles that interpreter instead of downloading one, for example
  `PYTHON_DIR=~/.local/share/uv/python/cpython-3.10-linux-x86_64-gnu` after `uv python install 3.10`.
- The build log is `dist/linux/build.log`.

What is in the AppImage: `opt/python/` (CPython 3.10, Pillow 10.4.0, ttkbootstrap 2.2.7) and `opt/capybara/`
(collector modules as `.pyc`, editor modules, `lang/`, `capybara_editor.py`).

### How the Linux version differs from Windows

`packaging/linux/capybara_editor.py` maps the Windows-only defaults before starting the editor:

- **Settings / data folder**: `$XDG_DATA_HOME/MXL Capybara Editor` (`~/.local/share/...`), log in `capybara.log`
  there. `MXL_USER_DIR=<folder>` overrides it.
- **Save folder**: the first `drive_c/users/*/AppData/Roaming/MedianXL/save` found in `$WINEPREFIX`, `~/.wine`,
  `~/Games/*`, Bottles, Lutris or Steam prefixes. `MXL_SAVE_DIR=<folder>` overrides it.
- **Game folder**: asked on first start; pick the Median XL folder inside the Wine prefix.
- **"Game must be closed" check**: the collector reads the Windows process list; on Linux `/proc` is read for a
  Wine `Game.exe` running from the game folder, with the same rule (unknown path: the write is refused).
- **Fonts**: the standalone Python's Tk has no Xft, so text uses X core fonts (not antialiased).
- The AppImage needs FUSE to mount; without it run `./MXL_Capybara_Editor_V2-x86_64.AppImage --appimage-extract-and-run`.

### Testing without touching real saves

```sh
MXL_USER_DIR=/tmp/capy-user MXL_SAVE_DIR=/path/to/copy/of/saves dist/linux/AppDir/AppRun
```

`MXL_EXIT_AFTER=<ms>` closes the main window after that delay (smoke tests).
