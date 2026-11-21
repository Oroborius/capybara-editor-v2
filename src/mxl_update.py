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

API = 'https://git.wyrd.games/api/v1/repos/oroborius/capybara-editor-v2/releases/latest'
PAGE = 'https://git.wyrd.games/oroborius/capybara-editor-v2/releases'
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


def latest_release(timeout=15):
    """{'tag', 'url', 'assets': {name: download url}, 'notes'} of the newest release."""
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(API, headers=UA), timeout=timeout) as r:
        d = json.loads(r.read().decode('utf-8'))
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
    """Unpacks the release next to the current folder; returns the new exe's path."""
    import zipfile
    here = os.path.dirname(os.path.abspath(sys.executable))
    parent = os.path.dirname(here)
    dest = os.path.join(parent, f"MXL Capybara Editor V2 {rel['tag']}")
    tmp = os.path.join(parent, f".capybara-update-{rel['tag']}.zip")
    _download(rel['assets'][WIN_ASSET], tmp, progress)
    try:
        with zipfile.ZipFile(tmp) as z:
            z.extractall(dest)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    exe = next((os.path.join(r, f) for r, _d, fs in os.walk(dest) for f in fs
                if f.lower().endswith('.exe') and 'capybara' in f.lower()), None)
    if not exe:
        raise OSError(f'no exe in the downloaded release ({dest})')
    return exe


def install_appimage(rel, progress=None):
    """Swaps the running AppImage file for the new one (Linux keeps the running copy open); returns its path."""
    target = os.environ['APPIMAGE']
    tmp = target + '.new'
    _download(rel['assets'][LINUX_ASSET], tmp, progress)
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)
    return target


def run(app):
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
        what = {'windows': T('upd.how_win', 'It will be unpacked next to this folder and started; this window closes. '
                                           'Your settings and saves are kept.'),
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
                path = (install_windows if how == 'windows' else install_appimage)(rel, prog)
                ui(done, path, None)
            except Exception as e:
                ui(done, None, e)
        threading.Thread(target=work, daemon=True).start()

    def done(path, err):
        if err:
            msg.configure(text=T('upd.failed', 'The update failed:\n{error}\n\nYou can download it by hand from:\n{url}',
                                 error=err, url=state['rel']['url']))
            ttk.Button(btns, text=T('upd.close', 'Close'), command=w.destroy).pack(side='right')
            return
        try:
            import mxl_log
            mxl_log.log.info('update installed: %s -> %s', state['rel']['tag'], path)
        except Exception:
            pass
        import subprocess
        try:
            subprocess.Popen([path], cwd=os.path.dirname(path))
        except OSError as e:
            messagebox.showinfo(title, T('upd.start_by_hand', 'Installed. Start it from:\n{path}\n({error})',
                                         path=path, error=e), parent=w)
        try:
            root.destroy()
        except tk.TclError:
            pass

    def check():
        try:
            ui(checked, latest_release(), None)
        except Exception as e:
            ui(checked, None, e)
    threading.Thread(target=check, daemon=True).start()
    return w


def install():
    try:
        import mxl_toolbar
        mxl_toolbar.add_entry(lambda: T('upd.menu', 'Check for updates...'), run)
    except Exception:
        pass
