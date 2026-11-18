"""What the suite does NOT test, as skipped tests with the reason - so the gaps show in every run instead of being
forgotten. Replace an entry by a real test when the means exist."""
import capytest as T

MODE = 'engine'
NEEDS = ()
ENGINE = False


@T.test
def web_page_import():
    T.skip('mxl_import.import_character needs a saved median-xl.com character page as a fixture (none is among the '
           'sample folders); only its tooltip-line parser is tested (17_statparse)')


@T.test
def windows_exe_starts():
    T.skip('the repacked Windows exe cannot be started here (no Windows, and Wine must not touch the real prefix); '
           'only its archive is checked (16_packaging::repack_builds_an_exe_with_the_editor_modules)')


@T.test
def drag_and_drop_between_stash_and_character():
    T.skip('dragging needs real pointer grabs, which Xvfb without a window manager does not deliver reliably; the '
           'moves are tested through the menu actions (To stash, Paste here, Move to page)')


@T.test
def game_art_panels_and_fonts_look_right():
    T.skip('appearance is not asserted: no reference screenshots are compared (Tk under Xvfb has no Xft fonts, the '
           'art comes from the user\'s game folder); 30_gui_smoke only checks that both looks build without errors')


@T.test
def game_is_open_guard():
    T.skip('needs a running Game.exe; mxl_free removes the game-closed checks anyway (WORKLOG W8)')


T.main(globals())
