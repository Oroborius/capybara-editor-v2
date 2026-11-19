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
   | `MXL_TEST_SAVE_DIR3` | `.cache/samples/owlie` (this checkout, else the main checkout's) | optional: a copy of test-druid's save folder (Druid level 81), whose stat screen numbers were read off in-game screenshots. Without it `59_statscreen_ingame` is skipped. |
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
| `test_20_statscreen_totals.py` | engine | stat screen sums: set bonuses of a worn set (sets table, by pieces); weapon damage and attack rating of the active weapon set against the seven level-1 screenshots and the host's item tooltip (quiver / inactive set II ignored) |
| `test_21_perf_caches.py` | engine | the start-up speed-ups give the old results: `mxl_explode` = the collector's explode on real archive streams (and cut-off ones), DC6 `to_rgba` / brightness = the per-pixel loops; `mxl_diskcache` keys change with a table file (mtime, size, new file) and the language; missing-art markers spare the archives and go with a new game version |
| `test_21_wheel_notches.py` | engine | `mxl_scroll` wheel helper: Tk 8.6 deltas of 120 / 240 and Button-4/5, Windows touchpad part-deltas adding up to one notch, Tk 9 side buttons ignored, `<TouchpadScroll>` packed deltas, Shift = sideways, nested handlers share one count |
| `test_22_robust_engine.py` | engine | write paths off the happy path: a character file the system refuses to replace gives CharError (no OSError, no `.tmp` left); copy under a name the game refuses or a taken (left-over, other case) name; a failed undo record keeps the previous entry; undo of an unreadable stash says "Undo failed"; two threads building the same art cache file; a cache value JSON cannot hold leaves no temporary file; the launcher's save-folder search (Flatpak Steam, `[ ]` in the home path, `~/.wine` first) |
| `test_23_save_safety.py` | engine | save safety (docs/review/save-safety.md): every sample item decodes / encodes to its own bytes; every stat-screen field at its limits saved, read back by both parsers and put back byte-identical; skill levels 0 / 255 / 74-77 and section-marker bytes in the fixed sections read the same as `mxlsave`; quest rewards on stats at their maximum; undo of the last item of a page and a failed undo kept; a delete from an out-of-date stash view never removes another item; interrupted writes (temp file, verification, final rename) keep the old file, a short PermissionError lock is tried again; rename / copy / web-page import never split or overwrite files, an import holds nothing of its template; the collector's character reader reads names with "gf" and skills 74 / 77 (with the save check installed, strict) |
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
| `test_41_gui_wheel.py` | gui | stat screen arrows walk one page at a time (book: 1-2, 2-3, 3-4, 4-5, numbered "4-5 / 5"; was 1-2, 3-4, 4-5); one notch moves the totals list once and never the page as well; a burst of 30 real wheel clicks (`xdotool`, skipped without it) drawn without lag; the page scrolls at the list's end; the wheel never changes a dropdown of a page (mercenary type; light-look class) or the Creator's copies spinbox; Creator value box one step per notch (d2 at UI scale 1.25, 800x600, 800x480; he at 1.25) |
| `test_42_gui_tooltips.py` | gui | floating tooltips (Stats page, Skills tree, Hotkeys; one reused `mxl_floattip` window each) with a real pointer (`xdotool`, skipped without it): a stationary hover maps the tip once and it stays, small moves keep it, it is never under the pointer and steps aside when the pointer jumps onto it, crossing the labels of one hotkey cell keeps it, a `<Leave>` with the pointer still on the widget keeps it, leaving hides it; window type `tooltip` on X11 (`CAPY_VPTR_FIFO=<fifo>`: pointer through a Wayland virtual pointer, for a headless sway run) |
| `test_43_gui_save_errors.py` | gui | "To stash" from the character (Stash-tab panel and Character tab) while the character file cannot be replaced (Windows lock simulated): an error box instead of a silent traceback, the stash put back, the character unchanged, no `.tmp`; when putting the stash back fails too, the box and the log say so |
| `test_43_gui_quality_pick.py` | gui | right-click "Change item quality" entries that ask first (rare / crafted / tempered names, which set / unique): the pick window opens over the editor (child of the main window, not of the menu), first entry selected, Escape closes it without a write, Enter twice makes the stash item rare; the same window on the Character tab |
| `test_44_gui_move_page.py` | gui | right-click "Move to page... > Page N": a cell taken on the target page sends the item to that page's first free place (was a raw "overlaps" error + ERROR log line), a free cell keeps the position, the item's own page is greyed out |
| `test_45_gui_hotkey_icons.py` | gui | Hotkeys page in both looks: every cell holding a skill shows an icon, a skill of another class (oskill from an item, e.g. the Assassin's Blink on the sample Necromancer) included; skipped without the game art |
| `test_44_gui_save_safety.py` | gui | two-file moves (To stash, panel and Character tab) with the character or the stash write refused by the save check: neither file changes; Delete on the stash grid after the stash was written behind the window's back deletes nothing and re-reads the stash; Paste over an item / ethereal on stash and character items, then Ctrl+Z: the file bytes are back |
| `test_46_gui_check_tristate.py` | gui | Waypoints / Quests in both looks: a mode / act box with part of its rows ticked shows the "partly ticked" box (filled square, not the tick); clicking it ticks every row under it (pending, nothing written before SAVE) |
| `test_47_gui_quantity_remove.py` | gui | right-click Quantity → Remove...: greyed out at quantity 0 (item without a quantity stat; it raised 0 to 1) and 1; removing more than there is stops at 1; the add / remove rule |
| `test_48_gui_language_switch.py` | gui | More » Language at run time: the editor's own texts (toolbar, Character page tabs, Creator labels) change to French at once and come back to exactly the same texts in English |
| `test_49_gui_creator_title.py` | gui | Creator title: "name - base" only when the base is not already part of the name (no "Belt (Angelic) - Belt (Angelic)"), and at 800x600 a long title wraps inside the middle column instead of being cut |
| `test_55_tooltip_damage.py` | engine | item tooltip damage lines never show min above max: every runeword and crafted base (min and max rolls, seeded) built by the creator; Anak "145 to 146" + "+70 to Minimum Damage" / "+45 to Maximum Damage", Aether "+120 to Minimum Magic Damage"; every other tooltip (both sample stashes, all uniques / sets) identical to the collector's own; the created Anak written to a stash copy reads back and passes mxlsave |
| `test_56_gui_status_attr.py` | gui | status bar "Strength … Dexterity …" equals the Stats page totals (not the collector's stored + flat items), and follows a changed character file |
| `test_57_gui_tab_language.py` | gui | main tabs Stash / Character / Creator in French and Vietnamese after a live language switch and back; a tab emptied while French is chosen gets its French name |
| `test_58_gui_creator_damage_preview.py` | gui | Creator → Runeword → Anak: the preview shows the corrected damage lines |
| `test_59_statscreen_ingame.py` | engine | stat screen of test-druid (third sample) against the in-game screenshots: page 1 attack rating boxes, attributes, resistances, Defense 44958, Block 25 %, Grit 11 %; page 2 life 3657, mana 963 / 16 %, poison 75-125, Attack Rating row 0 / 1173 %; page 3 Bonus to Defense 456 %, mana regeneration 424 %, Poison Length Red. 75 %; page 1 Damage boxes unchanged by the passive skills |
| `test_60_gui_switch_speed.py` | gui | switching character within a 4 s budget; stat screen pages and skill tree draw the same pixels with the shared caches as with empty ones (two characters) |
| `test_61_runeword_slots.py` | engine | runeword mods come from all 13 runes.bin slots (Rebel 12, Thelema 9, every row = its raw slots, host record keys); a created Rebel carries stat 372 (slot 1) and the stats of slots 9-12 |
| `test_64_gui_inspect_library.py` | gui | (second sample) right-click Inspect...: the dump of every item names the host decoder's code / ilvl / quality / stats in save order, the bit layout covers each item without gap, mxlsave re-encodes each item (socketed ones too) to its bytes, Copy to clipboard; Add to library... -> list + search -> Place a copy (same item, mxlsave check of the file) -> Ctrl+Z gives the original bytes; rename / delete; More » Item library... |
| `test_50_save_path_cache.py` | engine | save path on a big stash: the parsed-stash cache answers what the collector's parser answers for the bytes on disk now (an outside rewrite of the same size and time is seen), every caller gets its own copy; every write still parses its temp file with the collector's parser and checks the new bytes with `mxlsave` (both caches warm); corrupted writes refused (savecheck and the writer's own count check), file untouched; `item_now` refuses a neighbour from an out-of-date view; prints the time of a Duplicate on a 1340-item stash |
| `test_51_gui_undo_and_stale.py` | gui | Ctrl+Z after Make perfect and after Item stats edits (value, add + value + clear, chance-to-cast param), on a stash item, a worn / carried item from the Stash-tab panel and from the Character tab: the original bytes; an undo after another writer changed the item (stash) / the file (character) is refused and leaves it as that writer did; a value typed but not saved survives a Delete of another item and its undo; stash: Copy / Duplicate / Export from an out-of-date view take nothing, the Item stats tab refuses to write over an item changed on disk, and an edit of an item that only MOVED in the file (an item added before it) reaches that item, never its neighbour |
| `test_52_char_fraction.py` | engine | F8: life / mana / stamina changed and the old whole number typed back keep their 1/256 fraction (edit + revert saves the same bytes); after a save the saved value is the one kept |

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
- Fonts: GUI tests draw text with the Xft build of Tk, as the launcher does for users, whenever the application
  folder has it (`opt/python/lib/xft/`: an AppDir built without `MXL_NO_XFT`, or the cached
  `.cache/tk-xft-9.0.4/lib*.so*` copied there). `CAPY_XFT=0` runs them on X core fonts (narrower text, what an
  `MXL_NO_XFT=1` build gives); `CAPY_XFT=1` insists on Xft (the test process stops without it). The runner prints
  which fonts it uses. The layout tests (30, 36, 40, 41, 49) were written against the core fonts first; they pass
  with both (docs/review/gui.md, finding 8).
- Menu entries are found by their English text (the copied settings are switched to English).
- One Tk application per process: a GUI file is one process (per variant).

## Not covered

`test_19_not_covered.py` lists the gaps as skipped tests: the web-page import (needs a saved page as a fixture),
the Windows exe actually starting (only its archive is checked), drag and drop with a real pointer, how the art
panels and fonts look (no screenshots are compared), the "game is open" guard with a running game. Editing on the
Character tab's pages is covered by `test_35_gui_character_pages.py`.
