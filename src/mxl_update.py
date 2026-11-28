"""More » "Check for updates...": compares this build with the newest release on the project's Forgejo page and, on
request, installs it.

- Windows (the exe): downloads the release zip, unpacks it next to the current folder as
  "MXL Capybara Editor V2 <tag>", starts the new exe and closes this one. The old folder stays (nothing is deleted);
  settings, the log and the item library live in the user folder, so the new build finds them.
- Linux AppImage: downloads the new AppImage, swaps it in place of the running file and restarts.
- Anything else (run from source): opens the release page in the browser.

The build's own tag comes from build_info.json, written by the release script next to the modules; without it the
build counts as older than any release. Network: one public HTTPS request to the release API, no account, no data
about the user."""
import json
import os
import re
import sys
import threading

from mxl_lang import T

# GitHub is the primary release host, with certificates every system trusts; the Forgejo copy is the fallback (its
# Let's Encrypt "YE1" chain was not trusted by some Windows certificate stores: "SSL certificate" update errors)
APIS = ('https://api.github.com/repos/Oroborius/capybara-editor-v2/releases/latest',
        'https://git.wyrd.games/api/v1/repos/oroborius/capybara-editor-v2/releases/latest')
API = APIS[0]
PAGE = 'https://github.com/Oroborius/capybara-editor-v2/releases'
UA = {'User-Agent': 'Capybara-Editor-updater'}
WIN_ASSET = 'MXL-Capybara-Editor-V2-windows.zip'
LINUX_ASSET = 'MXL_Capybara_Editor_V2-x86_64.AppImage'


def current_tag():
    """This build's release tag (build_info.json next to this module), or None."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build_info.json'), encoding='utf-8') as f:
            return json.load(f).get('tag')
    except (OSError, ValueError):
        return None


def tag_key(tag):
    """Sortable key of 'v2.0-2026-11-21-4' -> ('2026-11-21', 4); None for anything else."""
    m = re.fullmatch(r'v[\d.]+-(\d{4}-\d{2}-\d{2})(?:-(\d+))?', tag or '')
    return (m.group(1), int(m.group(2) or 1)) if m else None


def newer(latest, current):
    a, b = tag_key(latest), tag_key(current)
    return a is not None and (b is None or a > b)


def _log_error(what, err):
    """Update errors in the log too (support zips showed none: the dialog only)."""
    try:
        import mxl_log
        mxl_log.log.warning('%s failed: %r', what, err)
    except Exception:
        pass


def latest_release(timeout=15):
    """{'tag', 'url', 'assets': {name: download url}, 'notes'} of the newest release."""
    import urllib.request
    error = None
    for api in APIS:
        try:
            with urllib.request.urlopen(urllib.request.Request(api, headers=UA), timeout=timeout) as r:
                d = json.loads(r.read().decode('utf-8'))
            if d.get('tag_name') and d.get('assets'):
                break
        except Exception as e:                      # SSL, network, rate limit: the next host
            error = e
    else:
        raise error or OSError('no release found')
    return dict(tag=d.get('tag_name'), url=d.get('html_url') or PAGE, notes=(d.get('body') or '').split('**Downloads**')[0].strip(),
                assets={a['name']: a['browser_download_url'] for a in d.get('assets', [])})


def mode():
    """'appimage', 'windows' or 'browser': how this build can update itself."""
    if os.environ.get('APPIMAGE') and os.path.isfile(os.environ['APPIMAGE']):
        return 'appimage'
    if getattr(sys, 'frozen', False) and sys.platform.startswith('win'):
        return 'windows'
    return 'browser'


def _download(url, dest, progress=None):
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, open(dest, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        got = 0
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            f.write(b)
            got += len(b)
            if progress:
                progress(got, total)
    return dest


def install_windows(rel, progress=None):
    """Downloads and unpacks the release into a staging folder next to the install; returns (staged folder, helper)
    where the helper (a .cmd in %TEMP%) waits for this process to end, moves the current folder aside as
    "<folder>.previous" (one backup kept), moves the new one into its place (or copies over it when a file is
    locked), and starts the editor again from the same path: shortcuts keep working."""
    import zipfile
    import tempfile
    exe = os.path.abspath(sys.executable)
    here = os.path.dirname(exe)
    parent = os.path.dirname(here)
    stage = os.path.join(parent, f".capybara-update-{rel['tag']}")
    tmp = stage + '.zip'
    _download(rel['assets'][WIN_ASSET], tmp, progress)
    try:
        import shutil
        shutil.rmtree(stage, ignore_errors=True)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(stage)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    new = next((r for r, _d, fs in os.walk(stage) if os.path.basename(exe) in fs), None)
    if not new:
        raise OSError(f'no {os.path.basename(exe)} in the downloaded release')
    helper = os.path.join(tempfile.gettempdir(), f"capybara-update-{rel['tag']}.cmd")
    with open(helper, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(WIN_HELPER.format(pid=os.getpid(), old=here, new=new, stage=stage, exe=os.path.basename(exe)))
    return new, helper


WIN_HELPER = """@echo off
chcp 65001 >NUL
setlocal
set "OLD={old}"
set "NEW={new}"
set "STAGE={stage}"
set "EXE={exe}"
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >NUL
  goto wait
)
ping -n 2 127.0.0.1 >NUL
if exist "%OLD%.previous" rmdir /s /q "%OLD%.previous"
move "%OLD%" "%OLD%.previous" >NUL 2>NUL
if errorlevel 1 goto copy
move "%NEW%" "%OLD%" >NUL 2>NUL
if not errorlevel 1 goto start
move "%OLD%.previous" "%OLD%" >NUL 2>NUL
:copy
robocopy "%NEW%" "%OLD%" /E /R:3 /W:1 /NFL /NDL /NJH /NJS >NUL
:start
start "" /D "%OLD%" "%OLD%\\%EXE%"
rmdir /s /q "%STAGE%" >NUL 2>NUL
(goto) 2>NUL & del "%~f0"
"""


def launch_windows_helper(helper):
    import subprocess
    # CREATE_NO_WINDOW alone (with NEW_PROCESS_GROUP): cmd gets a hidden console that tasklist / find / ping /
    # robocopy share. With DETACHED_PROCESS too (as before) Windows ignores NO_WINDOW, the script has no console,
    # and each of those programs opens a console window of its own - one sometimes stayed on screen
    flags = 0x00000200 | 0x08000000                    # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    si = None
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0                             # SW_HIDE
    except AttributeError:                             # not Windows (tests)
        pass
    subprocess.Popen(['cmd', '/c', helper], creationflags=flags, close_fds=True, startupinfo=si)


def install_appimage(rel, progress=None):
    """Swaps the running AppImage file for the new one (Linux keeps the running copy open); returns its path."""
    target = os.environ['APPIMAGE']
    tmp = target + '.new'
    _download(rel['assets'][LINUX_ASSET], tmp, progress)
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)
    return target


SETTING_SEEN = 'update_seen_tag'


def _seen():
    try:
        import settings
        return settings.get(SETTING_SEEN)
    except Exception:
        return None


def _set_seen(tag):
    try:
        import settings
        settings.put(SETTING_SEEN, tag)
    except Exception:
        pass


def startup_check(app, delay_ms=4000):
    """A few seconds after start, a quiet check in the background: when a newer release is out that this user was
    not shown before, the update window opens for it. Offline / errors: nothing at all."""
    import queue
    q = queue.Queue()

    def work():
        try:
            rel = latest_release(timeout=8)
            if newer(rel['tag'], current_tag()) and rel['tag'] != _seen():
                q.put(rel)
        except Exception:
            pass

    def poll(n=0):
        try:
            rel = q.get_nowait()
        except queue.Empty:
            if n < 150:
                app.root.after(200, poll, n + 1)
            return
        _set_seen(rel['tag'])
        run(app, rel)

    def go():
        threading.Thread(target=work, daemon=True).start()
        app.root.after(200, poll)
    try:
        app.root.after(delay_ms, go)
    except Exception:
        pass


def run(app, rel=None):
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = getattr(app, 'root', None) or tk._default_root
    title = T('upd.title', 'Update')
    w = tk.Toplevel(root)
    w.title(title)
    w.transient(root)
    msg = ttk.Label(w, text=T('upd.checking', 'Checking for a new version...'), wraplength=420, justify='left')
    msg.pack(padx=12, pady=(10, 4), anchor='w')
    bar = ttk.Progressbar(w, mode='indeterminate', length=420)
    bar.pack(padx=12, pady=4)
    bar.start(12)
    btns = ttk.Frame(w)
    btns.pack(padx=12, pady=(4, 10), anchor='e')
    state = {}
    import queue
    q = queue.Queue()                         # worker threads never touch Tk: the window polls this queue

    def ui(fn, *a):
        q.put((fn, a))

    def poll():
        try:
            while True:
                fn, a = q.get_nowait()
                fn(*a)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            if w.winfo_exists():
                w.after(100, poll)
        except tk.TclError:
            pass
    w.after(100, poll)

    def checked(rel, err):
        bar.stop()
        bar.pack_forget()                     # back only while downloading
        if err:
            _log_error('update check', err)
            msg.configure(text=T('upd.offline', 'Could not reach the release page:\n{error}', error=err))
            ttk.Button(btns, text=T('upd.close', 'Close'), command=w.destroy).pack(side='right')
            return
        cur = current_tag()
        state['rel'] = rel
        if not newer(rel['tag'], cur):
            msg.configure(text=T('upd.uptodate', 'You have the newest version ({tag}).', tag=cur or rel['tag']))
            ttk.Button(btns, text=T('upd.close', 'Close'), command=w.destroy).pack(side='right')
            return
        how = mode()
        what = {'windows': T('upd.how_win', 'The editor closes, is replaced in this same folder (the old version is '
                                           'kept as a backup next to it) and starts again. Your settings and saves '
                                           'are kept.'),
                'appimage': T('upd.how_app', 'This AppImage file is replaced and the editor restarts. '
                                             'Your settings and saves are kept.'),
                'browser': T('upd.how_web', 'The download page opens in your browser.')}[how]
        notes = rel['notes'][:600]
        msg.configure(text=T('upd.found', 'A new version is out: {new}\n(you have {cur})\n\n{notes}\n\n{how}',
                             new=rel['tag'], cur=cur or T('upd.unknown', 'an older build'), notes=notes, how=what))
        ttk.Button(btns, text=T('upd.later', 'Later'), command=w.destroy).pack(side='right', padx=(4, 0))
        ttk.Button(btns, text=T('upd.now', 'Update now'), command=lambda: start(how)).pack(side='right')

    def start(how):
        rel = state['rel']
        if how == 'browser':
            import webbrowser
            webbrowser.open(rel['url'])
            w.destroy()
            return
        for c in btns.winfo_children():
            c.destroy()
        bar.configure(mode='determinate', maximum=100, value=0)
        bar.pack(padx=12, pady=4, before=btns)
        msg.configure(text=T('upd.downloading', 'Downloading {tag}...', tag=rel['tag']))

        def prog(got, total):
            if total:
                ui(lambda v: bar.configure(value=v), got * 100 // total)

        def work():
            try:
                path = install_windows(rel, prog) if how == 'windows' else install_appimage(rel, prog)
                ui(done, path, None)
            except Exception as e:
                ui(done, None, e)
        threading.Thread(target=work, daemon=True).start()

    def done(path, err):
        if err:
            _log_error('update download', err)
            msg.configure(text=T('upd.failed', 'The update failed:\n{error}\n\nYou can download it by hand from:\n{url}',
                                 error=err, url=state['rel']['url']))
            ttk.Button(btns, text=T('upd.close', 'Close'), command=w.destroy).pack(side='right')
            return
        try:
            import mxl_log
            mxl_log.log.info('update downloaded: %s -> %s', state['rel']['tag'], path)
        except Exception:
            pass
        try:
            if isinstance(path, tuple):                    # Windows: the helper swaps the folder once we are gone
                launch_windows_helper(path[1])
            else:
                import subprocess
                subprocess.Popen([path], cwd=os.path.dirname(path), start_new_session=True)
        except OSError as e:
            messagebox.showinfo(title, T('upd.start_by_hand', 'Downloaded. Start it from:\n{path}\n({error})',
                                         path=path[0] if isinstance(path, tuple) else path, error=e), parent=w)
            return
        msg.configure(text=T('upd.restarting', 'Restarting with {tag}...', tag=state['rel']['tag']))
        w.after(400, lambda: root.destroy())

    def check():
        try:
            ui(checked, latest_release(), None)
        except Exception as e:
            ui(checked, None, e)
    if rel is not None:                       # the startup check found it already
        ui(checked, rel, None)
    else:
        threading.Thread(target=check, daemon=True).start()
    return w


def install(App=None):
    try:
        import mxl_toolbar
        mxl_toolbar.add_entry(lambda: T('upd.menu', 'Check for updates...'), run)
    except Exception:
        pass
    if App is None or os.environ.get('MXL_NO_UPDATE_CHECK'):
        return
    o_build = App._build

    def _build(self):
        o_build(self)
        startup_check(self)
    App._build = _build
