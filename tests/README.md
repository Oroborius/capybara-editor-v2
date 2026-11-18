# Regression suite

Headless tests of the editor's data paths and main GUI flows. They run the modules of `src/` inside a built
application folder, on **copies** of sample saves, on an X server of their own (`xvfb-run`).

```
tools/run_tests.sh                 # everything (about 13 minutes)
tools/run_tests.sh --quick         # data + engine tests only: no window, no X server (about 40 s)
tools/run_tests.sh -k creator      # only tests whose id contains the text (repeatable: -k a -k b)
tools/run_tests.sh --list          # the test ids
tools/run_tests.sh --keep          # keep the session folder (copies, output of every process)
```

Output: one line per test, then the lists of failures / expected failures / skips, then

```
N passed, M failed, K skipped, X expected failures[, U unexpected passes]  (seconds)
RESULT: PASS | FAIL
```

Exit code 0 when nothing failed unexpectedly, 1 otherwise, 2 when the setup is broken.

| mark | meaning |
|---|---|
| `PASS` / `FAIL` | as usual |
| `SKIP` | a fixture is missing, or the thing cannot be tested headlessly (the reason is printed) |
| `XFAIL` | expected failure: the test shows a **known, real bug** (described in a comment above the test) |
| `XPASS` | an expected failure passes now: the bug is fixed, remove the `xfail=` marker |

A failing test is a finding. Do not weaken an assertion to make it pass: fix the code, or - when the bug is real
and stays open - mark the test `@T.test(xfail='what is wrong')` with a comment describing the bug.

## What is needed

1. **The application folder** `dist/linux/AppDir`. `tools/run_tests.sh` builds it when it is missing
   (`packaging/build_appimage.sh --appdir-only`; in a git worktree without `.cache/` pass `BASE_DIR=<folder with
   the base exe>` and `PYTHON_DIR=<unpacked standalone Python 3.10>`), and before **every** run copies `src/mxl_*.py`,
   `src/*.json`, `lang/*.json` and the Linux launcher into `opt/capybara/`: what is tested is the working tree.
   The tests run with the folder's own Python 3.10; nothing else is installed (no pytest).
2. **Fixtures** - the user's own game data, never committed:

   | variable | default | must contain |
   |---|---|---|
   | `MXL_TEST_USER_DIR` | `/tmp/opencode/fakehome` | an editor user folder: `data/` with the extracted game tables (`itemstatcost.bin` and the other `*.bin`, `string.tbl`, `expansionstring.tbl`, `patchstring.tbl`, `data/items/*.png`), optionally `settings.json` (its `game_dir` is used for the game-art panels) and `ui_art/`. It is what the editor creates in `~/.local/share/MXL Capybara Editor` after its first start with the game folder set. |
   | `MXL_TEST_SAVE_DIR` | `/tmp/opencode/fakesaves` | a **copy** of a Median XL save folder: at least one `<Name>.d2s` with its `<Name>.stash` (and the companion files `.key .ma0 .map ...`), `_sharedstash.shared`. The richer the better: tests pick their items by property (an item with a roll below its maximum, a stackable item, an item with socketed items, a hired mercenary ...) and skip with a message when the sample has none. |
   | `MXL_TEST_SAVE_DIR2` | `/tmp/claude-1000/honorific-sample` | optional: a save folder whose character holds an honorific (quality 9) item. Without it `12_honorific` is skipped. |
   | `MXL_TEST_TMP` | system temp folder | where the session folder is made (falls back to `.cache/test-tmp` when the temp filesystem has less than 400 MB free) |
   | `BASE_DIR` | first folder of `.cache/base/` | the base exe + `_internal/` for the packaging tests (skipped without it) |

   A missing fixture is not an error: the tests that need it are reported as `SKIP` with the reason.

## Safety

- The fixture folders are only read. Every test process gets fresh copies inside the session folder and
  `MXL_USER_DIR` / `MXL_SAVE_DIR` pointing at them; destructive engine tests take a new copy each, GUI tests put
  the pristine files back before every test (`RESET = True`). At the end of a run the runner compares the save
  fixtures with their digest from the start and fails when a file changed.
- `capytest.guard()` ends the process (exit code 97) when a folder it is asked to work in is inside
  `/home/*/Games`, contains `drive_c/users`, or is the save folder the Linux launcher would find by itself.
  The copied `settings.json` loses `last_stash` / `last_character` (absolute paths the application would reopen).
- The GUI runs under `env WAYLAND_DISPLAY=fake xvfb-run -a -s "-screen 0 1280x720x24"`, never on the real display.

## Layout

| file | mode | covers |
|---|---|---|
| `run.py` | | the runner: one process per test file and variant, result lines, summary |
| `capytest.py` | | helper: guard, fixture copies, `@T.test`, soft assertions (`T.check`, `T.eq`), engine loader `T.engine()`, GUI harness, menu / event helpers, independent `.d2s` checksum |
| `test_10_data.py` | engine | every table loads; `tools/audit_game_data.py` round trip of every catalogue item |
| `test_11_saves.py` | engine | no-op load / save of every sample `.d2s` and stash is byte-identical; checksum |
| `test_12_honorific.py` | engine | the honorific sample parses, shows a tooltip, rebuilds identically |
| `test_13_character.py` | engine | `Character.set_field` for every key, flags, progression, rename; reload and compare |
| `test_14_statparams.py` | engine | `mxl_statparams` against the stat table; enumerations (415, 83), packed params |
| `test_15_creator_engine.py` | engine | creator build at min / max into a stash, edit path, honorific, relic labels, bonus search |
| `test_16_packaging.py` | engine | `py_compile`, `repack.py --identity`, `extract_host.py`, launcher environment, the guard itself |
| `test_16_skilldesc.py` | engine | skill tooltips (`mxl_skilldesc`) against lines read off in-game screenshots; every skill and level renders |
| `test_17_statparse.py` | engine | tooltip-line parser round trip |
| `test_18_stash_order.py` | engine | `mxl_stash_order`: replaced and re-inserted items keep their index; remove + insert-at-index gives the same file |
| `test_19_not_covered.py` | engine | the known gaps, as skipped tests with their reason |
| `test_21_perf_caches.py` | engine | the start-up speed-ups give the old results: `mxl_explode` = the collector's explode on real archive streams (and cut-off ones), DC6 `to_rgba` / brightness = the per-pixel loops; `mxl_diskcache` keys change with a table file (mtime, size, new file) and the language; missing-art markers spare the archives and go with a new game version |
| `test_30_gui_smoke.py` | gui | start in `MXL_THEME=d2` / `he` at 1280x720 and 800x600, every tab and page, status bar, toolbar overflow |
| `test_31_gui_stash_menu.py` | gui | right-click actions on stash items, undo (delete, create, replace, fill sockets) |
| `test_32_gui_creator.py` | gui | Creator tab: lists, search, create, Item Editor, honorific, create on the character |
| `test_33_gui_char_menu.py` | gui | right-click actions on character items: Stash-tab panel and Character tab |
| `test_34_gui_item_stats.py` | gui | Item stats tab on a stash item and on character items |
| `test_35_gui_character_pages.py` | gui | editing on every Character tab page in both looks: Stats, Skills, Waypoints, Quests, Quests+, Counters, Hotkeys, Mercenary; SAVE / RELOAD, pending edits |
| `test_35_launch.py` | launch | `AppRun` started as a user does, closes itself (`MXL_EXIT_AFTER`) |
| `test_36_gui_character_layout.py` | gui | Character tab pages in both looks at 1280x720, 800x600 and UI scales 1.25 / 1.5: open, go idle (no layout loop), image buttons follow the scale; status-bar count |
| `test_36_gui_fill_sockets_char.py` | gui | "Fill sockets with ..." on character and mercenary items, from the Stash-tab panel and the Character tab |
| `test_37_gui_merc_view.py` | gui | light look: the base-game character screen shows no ring frames on the mercenary view |
| `test_37_gui_socket_fillers.py` | gui | Edit item: remove one socket filler (gem, rune, jewel), "Empty sockets", jewels on runewords; no-op Replace byte-identical; stash and character files |
| `test_38_gui_picker_place.py` | gui | stat picker popup placement at 800x600 / 1280x720 / 2560x1440: on screen, never over the slot list; typeahead + Enter picks the closest stat |
| `test_38_gui_fill_sockets_undo_char.py` | gui | Ctrl+Z after "Fill sockets with ..." on character and mercenary items (panel and Character tab): the file byte-identical again, pending page edits kept, the undo refused after a newer write |
| `test_39_gui_merc_weapon_set.py` | gui | no weapon-set switch on the mercenary view (one weapon set: slots 4 / 5) in every look - base-game panel (tabs painted out), Sigma panel, plain panel, Character tab - and the character keeps his set; base-game panel: the I / II tab rectangles, gold marker and clicks match the tabs measured in the art |
| `test_40_gui_creator_layout.py` | gui | Creator and Item Editor at 800x600 (both looks, UI scale 1.25) and 1280x720: every control of every item type inside its column, no horizontal scrollbar; long combobox lists open wide; goes idle (CAPY_BIG=1 on a 2560x1440 X screen: every variant at that size) |
| `test_41_gui_perf.py` | gui | generous time budgets: the start (to built Character / Creator tabs), a rebuild of both windows on a warm art cache (and no game archive opened), stash pages, hover, Character pages, Creator / Item Editor, resize; idle afterwards; the Creator's bonus-text index on disk equals a fresh computation |

`--quick` runs the `engine` files only.

## Writing a test

```python
import capytest as T

MODE = 'engine'                 # 'gui': the application runs in this process; 'launch': X server, no app here
NEEDS = ('user', 'saves')       # fixtures; the whole file is skipped when one is missing ('saves2': second sample)

@T.test
def stash_keeps_its_bytes():
    E = T.engine()              # E.data, E.cr (Creator), E.save, E.fmt, E.MC (mxl_char), E.C (mxl_creator)
    path = T.fresh_saves() + '/XBone.stash'       # a private copy: do what you like with it
    before = T.stash_snap(path, E.data)           # {(page, x, y): (code, bytes)} from a fresh parse
    ...
    T.only_changed(before, T.stash_snap(path, E.data), chg=[key], what='my edit')   # everything else identical

T.main(globals())
```

- `T.check(cond, msg)` / `T.eq(a, b, msg)` collect failures and let the test go on; a plain exception fails it too.
- `T.skip(reason)`; `@T.test(xfail='bug')`; `@T.test(needs=('saves2',))`.
- File-level switches read by the runner (plain literals): `MODE`, `VARIANTS = {'name': {ENV: value}}` (the file
  runs once per variant, the test id gets `[name]`), `ISOLATE = True` (one process per test).
- GUI files: `RESET = True` restores the sample files and reloads every window before each test. The harness
  starts the real launcher (`capybara_editor.main()`) and runs the tests as a timer callback inside Tk's main loop
  (worker threads of the application hand work back with `after()`, which needs the loop running). Menus are
  captured instead of shown (`T.stash_menu`, `T.panel_menu`, `T.chartab_menu`, then `T.invoke(menu, 'Label
  prefix', under='Cascade prefix')`); message boxes and the simple dialogs are stubbed (`T.G.boxes`,
  `T.G.answers['int'] = 2`, `['askyesno'] = False`, `['file'] = path`). After every GUI test the harness fails it
  when the application printed a traceback, logged an `ERROR` line in `capybara.log` or tried to show an error box.
- Menu entries are found by their English text (the copied settings are switched to English).
- One Tk application per process: a GUI file is one process (per variant).

## Not covered

`test_19_not_covered.py` lists the gaps as skipped tests: the web-page import (needs a saved page as a fixture),
the Windows exe actually starting (only its archive is checked), drag and drop with a real pointer, how the art
panels and fonts look (no screenshots are compared), the "game is open" guard with a running game. Editing on the
Character tab's pages is covered by `test_35_gui_character_pages.py`.
