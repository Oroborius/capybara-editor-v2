"""More -> "Make a support zip for help..." (src/mxl_support.py): one zip with the log, settings.json, every character
/ stash file of the save folder and the two newest backups of each; written next to the exe / AppImage (else the
Desktop / home); nothing in the save folder changes."""
import os
import shutil
import sys
import zipfile

import capytest as T

MODE = 'engine'
NEEDS = ()


@T.test
def zip_holds_log_settings_saves_and_newest_backups():
    user = T.guard(os.path.join(T.tmp(), 'suser'), 'user folder')
    saves = T.guard(os.path.join(T.tmp(), 'ssaves'), 'save folder')
    out = T.guard(os.path.join(T.tmp(), 'sout'), 'zip folder')
    for d in (user, saves, out):
        os.makedirs(d, exist_ok=True)
    for n, b in (('capybara.log', b'log'), ('capybara.log.1', b'old'), ('settings.json', b'{}')):
        with open(os.path.join(user, n), 'wb') as f:
            f.write(b)
    for n in ('Pal.d2s', '_sharedstash.shared', 'Pal.d2s.bak-20261121-010000', 'Pal.d2s.bak-20261121-020000',
              'Pal.d2s.bak-20261121-030000', 'notes.txt'):
        with open(os.path.join(saves, n), 'wb') as f:
            f.write(n.encode())
    os.environ.update(MXL_USER_DIR=user, MXL_SAVE_DIR=saves)
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import paths
    T.guard(paths.USER_DIR, 'paths.USER_DIR')
    import mxl_support
    before = sorted(os.listdir(saves))
    p = mxl_support.make_zip(None, folder=out)
    T.eq(os.path.dirname(p), out, 'written into the chosen folder')
    names = sorted(zipfile.ZipFile(p).namelist())
    T.eq(names, sorted(['README.txt', 'settings.json', 'log/capybara.log', 'log/capybara.log.1', 'saves/Pal.d2s',
                        'saves/_sharedstash.shared', 'saves/backups/Pal.d2s.bak-20261121-030000',
                        'saves/backups/Pal.d2s.bak-20261121-020000']), 'zip contents')
    T.eq(sorted(os.listdir(saves)), before, 'save folder untouched')
    os.environ['APPIMAGE'] = os.path.join(out, 'Editor.AppImage')
    T.eq(mxl_support.out_folders()[0], out, 'next to the AppImage first')
    del os.environ['APPIMAGE']
    shutil.rmtree(out)



@T.test
def read_only_saves_are_found_and_made_writable():
    """More > Make saves writable...: the read-only save files of the folder (the Mock generator's "Lock save file"
    marks a new clone read-only; the game and the server's .clone could not write it) get their write flag back.
    Other files are left alone."""
    import stat
    import tempfile
    import mxl_support as S
    d = tempfile.mkdtemp()
    for n in ('Clone.d2s', 'Clone.key', 'Other.d2s', 'notes.txt'):
        with open(os.path.join(d, n), 'wb') as f:
            f.write(b'x')
    for n in ('Clone.d2s', 'Clone.key', 'notes.txt'):
        p = os.path.join(d, n)
        os.chmod(p, os.stat(p).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    ro = S.read_only_saves(d)
    T.eq(sorted(os.path.basename(p) for p in ro), ['Clone.d2s', 'Clone.key'], 'the read-only save files only')
    T.eq(S.make_writable(ro), 2, 'both made writable')
    T.eq(S.read_only_saves(d), [], 'none left')
    T.check(not os.stat(os.path.join(d, 'notes.txt')).st_mode & stat.S_IWUSR, 'a non-save file is left as it was')
    os.chmod(os.path.join(d, 'notes.txt'), 0o644)

T.main(globals())
