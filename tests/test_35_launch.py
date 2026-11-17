"""End to end: the built application folder started the way a user starts it (AppRun -> launcher -> splash process
-> main window), on copies, on the test X server; it closes itself after MXL_EXIT_AFTER milliseconds."""
import os
import subprocess

import capytest as T

MODE = 'launch'                       # needs the X server, but no application inside this process
ENGINE = False
VARIANTS = {'d2': {'MXL_THEME': 'd2'}, 'he': {'MXL_THEME': 'he'}}


@T.test
def apprun_starts_and_exits_cleanly():
    user, saves = T.fresh_user(), T.fresh_saves()
    before = {n: T.read(os.path.join(saves, n)) for n in os.listdir(saves) if os.path.isfile(os.path.join(saves, n))}
    xdg = T.guard(os.path.join(T.tmp(), 'xdg'))
    home = T.guard(os.path.join(T.tmp(), 'home'))
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ, MXL_USER_DIR=user, MXL_SAVE_DIR=saves, MXL_EXIT_AFTER='5000', WAYLAND_DISPLAY='fake',
               XDG_DATA_HOME=xdg, HOME=home)
    env.pop('LOCALAPPDATA', None)
    try:
        p = subprocess.run([os.path.join(T.APPDIR, 'AppRun')], env=env, cwd=T.tmp(), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=90)
    except subprocess.TimeoutExpired:
        raise T.Failed('the application did not close by itself within 90 s (MXL_EXIT_AFTER=5000)')
    out = p.stdout.decode(errors='replace')
    T.eq(p.returncode, 0, f'exit code (output: {out[-300:]!r})')
    for bad in ('Traceback', 'Exception in Tkinter callback', 'TclError'):
        at = out.find(bad)
        T.check(at < 0, f'{bad!r} in the output: ...{out[max(0, at - 200):at + 300]!r}')
    log_path = os.path.join(user, 'capybara.log')
    T.check(os.path.exists(log_path), 'no capybara.log in the user folder')
    if os.path.exists(log_path):
        with open(log_path, encoding='utf-8', errors='replace') as f:
            log = f.read()
        T.check('---- start' in log, 'capybara.log has no start line')
        errors = [ln for ln in log.splitlines() if ' ERROR ' in ln or 'Traceback' in ln]
        T.eq(errors[:3], [], 'error lines in capybara.log')
    for n, raw in before.items():
        T.check(T.read(os.path.join(saves, n)) == raw, f'{n} changed during a start without any action')
    T.eq(sorted(n for n in set(os.listdir(saves)) - set(before) if os.path.isfile(os.path.join(saves, n))), [],
         'new files in the save folder')
    written = os.listdir(xdg) if os.path.isdir(xdg) else []
    T.eq(written, [], 'folders made in the default data folder although MXL_USER_DIR was given')


T.main(globals())
