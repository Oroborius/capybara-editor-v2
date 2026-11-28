"""More » "Make a support zip for help...": one click packs what a helper needs into ONE zip, written somewhere obvious
(next to the editor's exe; Linux: next to the AppImage), then opens that folder and says where the file is.

In the zip: capybara.log (+ the older .1 .. .3), settings.json, and from the save folder every character / stash
file plus the two newest backups of each (to compare before / after an edit). Nothing is changed or deleted."""
import glob
import os
import sys
import time
import zipfile

from mxl_lang import T

SAVE_EXT = ('.d2s', '.d2x', '.sss', '.shared', '.stash', '.d2i')
MAX_BYTES = 200 * 1024 * 1024                  # a safety cap on what is packed (saves are tiny; huge = something odd)


def _user_dir():
    try:
        import paths
        return paths.USER_DIR
    except Exception:
        return None


def _save_dir(app=None):
    d = getattr(app, 'save_dir', None) if app is not None else None
    if not d:
        g = sys.modules.get('mxl_gui')
        d = getattr(g, 'SAVE_DIR', None) if g is not None else None
    return d or os.environ.get('MXL_SAVE_DIR')


def out_folders():
    """Where the zip goes, most obvious first: next to the exe (Windows) / the AppImage (Linux), the Desktop, home."""
    cands = []
    if os.environ.get('APPIMAGE'):
        cands.append(os.path.dirname(os.path.abspath(os.environ['APPIMAGE'])))
    if getattr(sys, 'frozen', False):
        cands.append(os.path.dirname(os.path.abspath(sys.executable)))
    home = os.path.expanduser('~')
    cands += [os.path.join(home, 'Desktop'), home]
    return [c for c in cands if c and os.path.isdir(c)]


def files_to_pack(app=None):
    """[(path on disk, name in the zip)]."""
    out = []
    ud = _user_dir()
    if ud:
        for p in sorted(glob.glob(os.path.join(glob.escape(ud), 'capybara.log*'))):
            out.append((p, os.path.join('log', os.path.basename(p))))
        s = os.path.join(ud, 'settings.json')
        if os.path.isfile(s):
            out.append((s, 'settings.json'))
    sd = _save_dir(app)
    if sd and os.path.isdir(sd):
        names = sorted(os.listdir(sd))
        for n in names:
            p = os.path.join(sd, n)
            if os.path.isfile(p) and n.lower().endswith(SAVE_EXT):
                out.append((p, os.path.join('saves', n)))
                baks = sorted((b for b in names if b.startswith(n + '.bak')), reverse=True)[:2]
                out += [(os.path.join(sd, b), os.path.join('saves', 'backups', b)) for b in baks]
    return out


def make_zip(app=None, folder=None):
    """Writes the zip; returns its path. Tries each folder of out_folders() until one is writable."""
    files = files_to_pack(app)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    name = f'Capybara-support-{stamp}.zip'
    last = None
    for d in ([folder] if folder else out_folders()):
        path = os.path.join(d, name)
        try:
            total = 0
            with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED) as z:
                info = [f'MXL Capybara Editor support zip, {stamp}', f'python {sys.version.split()[0]} on {sys.platform}',
                        f'save folder: {_save_dir(app)}', '']
                for p, arc in files:
                    try:
                        total += os.path.getsize(p)
                        if total > MAX_BYTES:
                            info.append(f'skipped (size cap): {arc}')
                            continue
                        z.write(p, arc)
                    except OSError as e:
                        info.append(f'could not read {arc}: {e}')
                z.writestr('README.txt', '\n'.join(info) + '\n')
            return path
        except OSError as e:
            last = e
            try:
                if os.path.isfile(path) and os.path.getsize(path) == 0:
                    os.remove(path)
            except OSError:
                pass
    raise OSError(f'no folder to write the zip into ({last})')


def _show_in_folder(path):
    try:
        if sys.platform.startswith('win'):
            import subprocess
            subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', '-R', path])
        else:
            import subprocess
            subprocess.Popen(['xdg-open', os.path.dirname(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def run(app):
    from tkinter import messagebox
    root = getattr(app, 'root', None)
    try:
        path = make_zip(app)
    except Exception as e:
        messagebox.showerror(T('sup.title', 'Support zip'), T('sup.fail', 'The zip could not be made:\n{error}',
                                                             error=e), parent=root)
        return None
    try:
        import mxl_log
        mxl_log.log.info('support zip: %s', path)
    except Exception:
        pass
    _show_in_folder(path)
    messagebox.showinfo(T('sup.title', 'Support zip'),
                        T('sup.done2', 'Done! Send this one file to whoever is helping you:\n\n{path}\n\n'
                                       'On the D2O Discord: DM it to LadderBot, never post it in public.\n'
                                       '(It holds the editor log, its settings and your character / stash files.)',
                          path=path), parent=root)
    return path


def install():
    try:
        import mxl_toolbar
        mxl_toolbar.add_entry(lambda: T('sup.menu', 'Make a support zip for help...'), run)
    except Exception:
        pass
