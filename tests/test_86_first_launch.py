"""First launch without any saved game: the editor starts (no blocking dialog, no error), shows the "which game"
dialog, remembers the answer. Vanilla (MXL_TEST_VANILLA_GAME) opens the vanilla profile; Median with no install
opens without a game folder; Skip too. A fresh, EMPTY user folder every time (MXL_FIRSTRUN_CHOICE answers the dialog)."""
import json
import os
import subprocess

import capytest as T

MODE = 'launch'
ENGINE = False
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or ''


def _run(choice, folder=''):
    user = T.guard(os.path.join(T.tmp(), f'empty-user-{choice}'))
    os.makedirs(user, exist_ok=True)
    saves = T.guard(os.path.join(T.tmp(), 'saves-' + choice))      # no characters: nothing to open or write
    os.makedirs(saves, exist_ok=True)
    xdg = T.guard(os.path.join(T.tmp(), 'xdg-' + choice))
    home = T.guard(os.path.join(T.tmp(), 'home-' + choice))
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ, MXL_USER_DIR=user, MXL_SAVE_DIR=saves, MXL_EXIT_AFTER='9000', WAYLAND_DISPLAY='fake',
               XDG_DATA_HOME=xdg, HOME=home, MXL_FIRSTRUN_CHOICE=choice, MXL_FIRSTRUN_FOLDER=folder)
    for k in ('LOCALAPPDATA', 'MXL_GAME', 'MXL_GAME_DIR'):
        env.pop(k, None)
    try:
        p = subprocess.run([os.path.join(T.APPDIR, 'AppRun')], env=env, cwd=T.tmp(), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=150)
    except subprocess.TimeoutExpired:
        raise T.Failed('the editor did not close by itself (a blocking dialog?)')
    out = p.stdout.decode(errors='replace')
    T.eq(p.returncode, 0, f'exit code (output: {out[-400:]!r})')
    for bad in ('Traceback', 'Exception in Tkinter callback', 'TclError'):
        T.check(bad not in out, f'{bad!r} in the output: {out[-500:]!r}')
    with open(os.path.join(user, 'capybara.log'), encoding='utf-8', errors='replace') as f:
        log = f.read()
    T.check('first launch dialog shown' in log, 'the first-launch dialog did not appear')
    T.eq([ln for ln in log.splitlines() if ' ERROR ' in ln or 'Traceback' in ln][:3], [], 'errors in capybara.log')
    with open(os.path.join(user, 'settings.json'), encoding='utf-8') as f:
        st = json.load(f)
    T.check(st.get('profile_chosen'), 'the choice was not remembered')
    return log, st


@T.test
def vanilla_choice_opens_vanilla():
    if not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        T.skip('no MXL_TEST_VANILLA_GAME')
    log, st = _run('vanilla', GAME)
    T.eq(st.get('game_profile'), 'folder', 'profile saved')
    T.eq(st.get('profile_game_dir'), GAME, 'vanilla path saved separately')
    T.check('game_dir' not in st, 'vanilla selection must not populate the Median path')
    T.check('game profile vanilla' in log or 'game profile d2-' in log, 'vanilla profile not loaded: ' + log[-400:])


@T.test
def median_without_install_opens_with_hint():
    log, st = _run('median', '')
    T.eq(st.get('game_profile'), 'median', 'profile saved')
    T.check('no game folder saved' in log, 'started without a game folder: ' + log[-300:])


@T.test
def skip_opens_without_game():
    log, st = _run('skip', '')
    T.check('game_profile' not in st, 'skip must not choose a profile')


T.main(globals())
