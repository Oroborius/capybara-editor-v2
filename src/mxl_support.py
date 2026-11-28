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
    if offer_send() and _ask_send(app, path):
        return path
    _show_in_folder(path)
    messagebox.showinfo(T('sup.title', 'Support zip'),
                        T('sup.done2', 'Done! Send this one file to whoever is helping you:\n\n{path}\n\n'
                                       'On the D2O Discord: DM it to LadderBot, never post it in public.\n'
                                       '(It holds the editor log, its settings and your character / stash files.)',
                          path=path), parent=root)
    return path


# ------------------------------------------------------------------ send it to LadderBot (the D2O Discord bot)
SEND_URL = 'https://www.shadowdiablo.com/__upload'   # the upload address (setting 'support_send_url' wins)
ASK_SETTING = 'support_send_ask'                 # False after "Never": the zip is only written, as before
NAME_SETTING = 'support_discord_name'
SEND_MAX = 24 * 1024 * 1024


def _settings():
    import settings
    return settings


def send_url():
    try:
        return (_settings().get('support_send_url') or SEND_URL or '').strip()
    except Exception:
        return SEND_URL


def offer_send():
    """Ask to send the new zip: an upload address is known and the user did not pick "Never"."""
    try:
        return bool(send_url()) and _settings().get(ASK_SETTING) is not False
    except Exception:
        return False


def set_offer(on):
    _settings().put(ASK_SETTING, bool(on))


def upload(path, discord='', note='', url=None, timeout=60):
    """POSTs the zip (multipart: file, discord, version, note). -> the ticket id; raises on failure."""
    import json
    import urllib.request

    url = url or send_url()
    if not url:
        raise OSError('no upload address')
    if os.path.getsize(path) > SEND_MAX:
        raise OSError(T('sup.too_big', 'the zip is too big to send ({mb} MB)', mb=os.path.getsize(path) >> 20))
    try:
        import mxl_update
        version = mxl_update.current_tag() or ''
    except Exception:
        version = ''
    boundary = os.urandom(16).hex()
    parts = []
    for name, value in (('discord', discord[:64]), ('version', version), ('note', note[:500])):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode('utf-8'))
    with open(path, 'rb') as f:
        data = f.read()
    import mxl_support_check
    ok, why = mxl_support_check.validate(data, os.path.basename(path), version)
    if not ok:                                   # the receiving side runs the same check: fail here, plainly
        raise OSError(T('sup.invalid', 'this is not a support zip the editor made ({why})', why=why))
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"\r\n'
                 f'Content-Type: application/zip\r\n\r\n'.encode('utf-8') + data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode('utf-8'))
    req = urllib.request.Request(url, data=b''.join(parts), method='POST', headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}', 'User-Agent': 'Capybara-Editor-support'})
    import urllib.error
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            reply = json.loads(r.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as e:               # 400 / 413 / 429 ...: the reason the server gives
        try:
            reply = json.loads(e.read().decode('utf-8') or '{}')
        except Exception:
            reply = {}
        if not reply.get('error'):
            raise OSError(f'HTTP {e.code}') from e
    if not reply.get('ok'):
        raise OSError(reply.get('error') or 'refused')
    return str(reply.get('id') or '')


def _ask_send(app, path, intro=None, note_text=''):
    """The send dialog: Send to LadderBot / No / Never. True when the zip was sent (or is being sent): the old
    "send this file" message is not needed then. path: the zip, or a function that makes it (after an error: the
    zip is only made when Send is clicked)."""
    import threading
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = getattr(app, 'root', None) or tk._default_root
    title = T('sup.title', 'Support zip')
    w = tk.Toplevel(root)
    w.title(title)
    w.transient(root)
    w.resizable(False, False)
    f = ttk.Frame(w, padding=12)
    f.pack(fill='both', expand=True)
    ttk.Label(f, text=intro or T('sup.ask', 'Send this support zip to LadderBot on the D2O Discord now?\n'
                                            'It holds the editor log, its settings and your character / stash files.'),
              justify='left', wraplength=420).grid(row=0, column=0, columnspan=2, sticky='w')
    name = tk.StringVar(value=_settings().get(NAME_SETTING) or '')
    note = tk.StringVar(value=note_text)
    ttk.Label(f, text=T('sup.discord', 'Your Discord name:')).grid(row=1, column=0, sticky='w', pady=(8, 2))
    ttk.Entry(f, textvariable=name, width=32).grid(row=1, column=1, sticky='we', pady=(8, 2))
    ttk.Label(f, text=T('sup.note', 'What happened (optional):')).grid(row=2, column=0, sticky='w', pady=2)
    ttk.Entry(f, textvariable=note, width=32).grid(row=2, column=1, sticky='we', pady=2)
    status = ttk.Label(f, text='', wraplength=420, justify='left')
    status.grid(row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))
    bar = ttk.Frame(f)
    bar.grid(row=4, column=0, columnspan=2, sticky='e', pady=(10, 0))
    result = {'sent': None}

    def send():
        for b in bar.winfo_children():
            b.state(['disabled'])
        _settings().put(NAME_SETTING, name.get().strip())
        status.configure(text=T('sup.sending', 'Sending...'))
        box = {}

        def work():
            try:
                box['path'] = path() if callable(path) else path
                box['id'] = upload(box['path'], name.get().strip(), note.get().strip())
            except Exception as e:
                box['err'] = e

        def wait():
            if t.is_alive():
                w.after(150, wait)
                return
            if 'err' in box:
                try:
                    import mxl_log
                    mxl_log.log.warning('support zip send failed: %r', box['err'])
                except Exception:
                    pass
                result['sent'] = False
                w.destroy()
                where = box.get('path')
                if where:
                    messagebox.showerror(title, T('sup.send_fail', 'It could not be sent ({error}).\n\nPlease DM the '
                                                                   'file to LadderBot on Discord instead:\n{path}',
                                                  error=box['err'], path=where), parent=root)
                    _show_in_folder(where)
                else:
                    messagebox.showerror(title, T('sup.fail', 'The zip could not be made:\n{error}',
                                                  error=box['err']), parent=root)
                return
            result['sent'] = True
            w.destroy()
            messagebox.showinfo(title, T('sup.sent', 'Sent to LadderBot. Thank you!{ticket}',
                                         ticket=f' (ticket {box["id"]})' if box.get('id') else ''), parent=root)
        t = threading.Thread(target=work, daemon=True)
        t.start()
        w.after(150, wait)

    def no():
        result['sent'] = False
        w.destroy()

    def never():
        set_offer(False)
        result['sent'] = False
        w.destroy()
        messagebox.showinfo(title, T('sup.never', 'OK, support zips are only saved from now on.\nYou can switch this '
                                                   'back on in More > "Offer to send support zips".'), parent=root)
    ttk.Button(bar, text=T('sup.never_btn', 'Never'), command=never).pack(side='right', padx=(4, 0))
    ttk.Button(bar, text=T('sup.no', 'No'), command=no).pack(side='right', padx=(4, 0))
    ttk.Button(bar, text=T('sup.send', 'Send to LadderBot'), command=send).pack(side='right')
    w.protocol('WM_DELETE_WINDOW', no)
    try:
        w.grab_set()
    except tk.TclError:
        pass
    w.wait_window()
    return bool(result['sent'])


_ERROR_OFFERED = set()


def offer_after_error(root, exc_type, exc):
    """An unexpected error in a window action: the same Send / No / Never question (once per kind of error in a
    run; never while a dialog of ours is open). The zip is only made when Send is clicked."""
    if not offer_send() or root is None:
        return
    key = (getattr(exc_type, '__name__', str(exc_type)), str(exc)[:80])
    if key in _ERROR_OFFERED or _ERROR_OFFERED and len(_ERROR_OFFERED) > 5:
        return
    _ERROR_OFFERED.add(key)
    import types
    app = types.SimpleNamespace(root=root)
    gui = sys.modules.get('mxl_gui')
    real = getattr(getattr(gui, 'App', None), '_capy_instance', None) if gui else None
    summary = f'{key[0]}: {key[1]}'

    def ask():
        try:
            _ask_send(real or app, lambda: make_zip(real),
                      intro=T('sup.ask_err', 'Something went wrong in the editor ({error}).\n\nSend a support zip to '
                                             'LadderBot on the D2O Discord so it can be fixed? It holds the editor '
                                             'log, its settings and your character / stash files.', error=summary),
                      note_text=summary)
        except Exception:
            pass
    try:
        root.after(300, ask)
    except Exception:
        pass


def _hook_errors():
    import tkinter
    old = tkinter.Tk.report_callback_exception
    if getattr(old, '_capy_offer', False):
        return

    def report_callback_exception(self, t, v, tb):
        old(self, t, v, tb)                         # logged (mxl_log) and shown as before
        offer_after_error(self, t, v)
    report_callback_exception._capy_offer = True
    tkinter.Tk.report_callback_exception = report_callback_exception


def install():
    try:
        _hook_errors()
    except Exception:
        pass
    try:
        import mxl_toolbar
        mxl_toolbar.add_entry(lambda: T('sup.menu', 'Make a support zip for help...'), run)
        mxl_toolbar.add_check(lambda: T('sup.offer', 'Offer to send support zips'),
                              lambda: _settings().get(ASK_SETTING) is not False, set_offer)
    except Exception:
        pass
