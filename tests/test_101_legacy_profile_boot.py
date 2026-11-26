"""Cold boot and extraction failure through the desktop launcher under Xvfb."""

import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from time import perf_counter

import capytest as T
from test_100_mod_profile import _stat_width

MODE = 'launcher'
NEEDS = ()


def _dense_archive(path):
    from mpq import CT, hs

    # A large archive with a completely occupied hash index. Missing names used
    # to probe every slot for every table and icon, even though the file is mapped.
    slots = 131072
    size = 384 * 1024 * 1024
    with path.open('wb') as file:
        file.write(struct.pack('<4sIIHHIIII', b'MPQ\x1a', 32, size, 0, 3, 32, 32 + 16 * slots, slots, 0))
        key, seed = hs('(hash table)', 3), 0xeeeeeeee
        encrypted = bytearray()
        for _ in range(slots):
            for word in (0, 0, 0, 0xfffffffe):
                seed = (seed + CT[0x400 + (key & 255)]) & 0xffffffff
                encrypted += struct.pack('<I', word ^ ((key + seed) & 0xffffffff))
                key = (((~key << 21) + 0x11111111) | (key >> 11)) & 0xffffffff
                seed = (word + seed + (seed << 5) + 3) & 0xffffffff
        file.write(encrypted)
        file.truncate(size)


def _environment(folder, user):
    home = user.parent / 'home'
    home.mkdir(exist_ok=True)
    return dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home), LOCALAPPDATA=str(home),
                MXL_GAME='folder', MXL_GAME_DIR=str(folder), MXL_USER_DIR=str(user),
                MXL_SAVE_DIR='', WINEPREFIX='', MXL_EXIT_AFTER='150', MXL_THEME='he')


@T.test
def cold_boot_dense_109_mods():
    from mxl_data import Data

    game = Path(T.REPO) / '.cache' / 'oldver' / '109d'
    core = game / 'D2SE' / 'CORES' / '1.09d'
    saves = sorted((game / 'MODS').glob('*/save/*.d2s'))
    if not (core / 'D2Game.dll').is_file() or not (game / 'd2data.mpq').is_file() or not saves:
        T.skip('cached 1.09d archives and v92 save required')
    launcher = Path(T.APP) / 'capybara_editor.py'
    root = Path(T.tmp())
    dense = root / 'Dense.mpq'
    _dense_archive(dense)
    for layout in ('d2se', 'standalone'):
        base = root / layout
        base.mkdir()
        for file in game.iterdir():
            if file.name.lower() in ('d2data.mpq', 'd2exp.mpq'):
                (base / file.name).symlink_to(file.resolve())
        if layout == 'd2se':
            (base / 'D2SE').symlink_to((game / 'D2SE').resolve(), target_is_directory=True)
            mod = base / 'MODS' / 'Example'
            mod.mkdir(parents=True)
            (mod / 'D2SE_SETUP.ini').write_text('D2Core=1.09d\nModName=Example\n')
        else:
            mod = base
            (mod / 'D2Game.dll').write_bytes(struct.pack('<IIII', 0xfeef04bd, 0, 1 << 16, 9 << 16))
            patch = next(p for p in core.iterdir() if p.name.lower() == 'patch_d2.mpq')
            (mod / patch.name).symlink_to(patch.resolve())
        (mod / dense.name).symlink_to(dense)
        excel = mod / 'Data' / 'Global' / 'Excel'
        excel.mkdir(parents=True)
        (excel / 'itemstatcost.txt').write_bytes(_stat_width(13))
        (mod / 'Save').mkdir()
        shutil.copyfile(saves[0], mod / 'Save' / 'Fixture.d2s')
        T.eq(struct.unpack_from('<I', (mod / 'Save' / 'Fixture.d2s').read_bytes(), 4)[0], 92, 'v92 fixture')

        user = root / f'{layout}-user'
        start = perf_counter()
        result = subprocess.run([sys.executable, str(launcher)], env=_environment(mod, user),
                                capture_output=True, text=True, timeout=18)
        T.eq(result.returncode, 0, result.stderr)
        log = (user / 'capybara.log').read_text()
        ready = re.search(r'editor ready in ([0-9.]+) s', log)
        T.check(ready and float(ready[1]) < 12, f'{layout} reached the window within 12 seconds')
        T.check(perf_counter() - start < 16, f'{layout} launcher exited within 16 seconds')
        T.check('opening archive' in log and 'decode item and socket icons' in log, 'extraction phases logged')
        T.eq(log.count('startup: extract profile data in'), 1, 'the launcher builds one profile cache')
        T.check('scan character saves (1 found)' in log and 'load editor data' in log, 'save and data phases logged')
        data = next((user / 'profiles').glob('*/data'))
        T.eq(Data(str(data)).isc[0]['bits'], 13, 'loose mod override loaded')


@T.test
def extraction_failure_displays_error_and_preserves_log():
    root = Path(T.tmp())
    game = root / 'Invalid'
    game.mkdir()
    (game / 'd2data.mpq').write_bytes(b'bad archive')
    (game / 'D2SE_SETUP.ini').write_text('D2Core=1.09d\n')
    code = """
import sys
sys.path.insert(0, sys.argv[1])
sys.argv[:] = [sys.argv[1] + '/capybara_editor.py']
from tkinter import Tk, messagebox
import os
import subprocess
failure = os.environ.get('CAPY_TEST_WORKER_FAILURE')
if failure:
    import mxl_boot
    if failure == 'timeout':
        mxl_boot.PROFILE_TIMEOUT = 1
    run = subprocess.run
    def crash_worker(command, **kwargs):
        if command[1] == '-c' and '_extract_worker' in command[2]:
            code = "import os,sys; open(sys.argv[1], 'w').write('last archive opened'); os._exit(86)"
            if failure == 'timeout':
                code = code.replace('os._exit(86)', 'import time; time.sleep(60)')
            command = [sys.executable, '-c', code, command[-1]]
        return run(command, **kwargs)
    subprocess.run = crash_worker
from capybara_editor import main
original = messagebox.showerror
def show(title, message, **kwargs):
    root = Tk()
    root.withdraw()
    def dismiss():
        dialog = '.__tk__messagebox'
        if root.tk.call('winfo', 'exists', dialog):
            print(root.tk.call('wm', 'title', dialog), flush=True)
            root.tk.call(dialog + '.ok', 'invoke')
        else:
            root.after(25, dismiss)
    root.after(25, dismiss)
    try:
        return original(title, message, parent=root)
    finally:
        root.destroy()
messagebox.showerror = show
main()
"""
    expected = {
        '': ('no game tables', 'startup failed'),
        'crash': ('last archive opened', 'worker exit 86'),
        'timeout': ('last archive opened', 'exceeded 1 seconds'),
    }
    for failure, messages in expected.items():
        user = root / f'failed-user-{failure}'
        env = dict(_environment(game, user), CAPY_TEST_WORKER_FAILURE=failure)
        result = subprocess.run([sys.executable, '-c', code, T.APP], env=env,
                                capture_output=True, text=True, timeout=17)
        T.eq(result.returncode, 1, result.stderr)
        T.check('Capybara Editor could not start' in result.stdout, 'real Tk startup error dialog displayed')
        log = (user / 'capybara.log').read_text()
        T.check(all(message in log for message in messages), 'worker and launcher errors logged')
        T.check(not list((user / 'profiles').glob('*/data/install.json')), 'failed extraction did not publish data')


@T.test
def sharing_violation_retries_after_worker_cleanup():
    from tkinter import messagebox
    from unittest.mock import patch

    from mxl_boot import ProfileArchiveLocked, extract_profile
    import mxl_profile

    root = Path(T.tmp())
    archive = root / 'patch_d2.mpq'
    out = root / 'data'
    out.mkdir()
    manifest = out / 'install.json'
    manifest.write_text('previous cache')

    error = PermissionError('sharing violation')
    error.winerror = 32
    with patch('mxl_profile_mpq.ProfileMPQ', side_effect=error):
        try:
            mxl_profile._open([str(archive)], extracting=True)
        except ProfileArchiveLocked as locked:
            T.eq(locked.__cause__, error, 'preserve the Windows sharing error')
        else:
            raise AssertionError('the locked archive was silently skipped')

    calls = []

    def run(command, **kwargs):
        work_data = Path(command[-2])
        work_data.mkdir()
        calls.append(work_data.parent)
        status = 2 if len(calls) == 1 else 0
        (work_data / 'install.json').write_text('partial' if status else 'replacement')
        return subprocess.CompletedProcess(command, status)

    def retry(title, message):
        T.eq(message, 'Close Diablo II and press Retry.', 'actionable retry instructions')
        T.eq(manifest.read_text(), 'previous cache', 'old cache survives failed extraction')
        T.check(not calls[0].exists(), 'failed work directory removed before Retry')
        return True

    with patch('subprocess.run', side_effect=run), patch.object(
            messagebox, 'askretrycancel', side_effect=retry) as dialog:
        extract_profile(str(root), str(out))
    T.eq(dialog.call_count, 1, 'one retry dialog')
    T.eq(manifest.read_text(), 'replacement', 'replacement published after successful retry')
    T.check(all(not work.exists() for work in calls), 'all temporary work directories removed')


sys.path.insert(0, T.APP)
T.main(globals())
