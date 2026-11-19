"""Is a character IN A GAME right now (not merely the game open at its menu / character select)?

Rule: a character is in game when a running Game.exe holds one of that character's own files open:
`<name>.d2s`, `.key`, `.map`, `.ma0`-`.ma3`, `.stash` in the save folder. `_sharedstash.shared` belongs to no
character and does not count. At the menu / character select the game reads every character's .d2s to draw the
list and closes it again; in a game it keeps the playing character's files open. (This menu / in-game difference
is how Diablo II handles its save files as far as we know - it was not observed here, the game cannot run on the
test machine. Check it with `python3 mxl_ingame.py <save folder>` once at the menu and once in a game: it prints
the files every Game.exe / wineserver process holds.) When unsure the answer is "not in game" and nothing changes.

- Linux / Wine: /proc/<pid>/fd of every process whose argv[0] (Unix or Windows path) ends in Game.exe, and of the
  wineserver processes while a Game.exe runs: Wine's server owns the unix fd of every open file handle, the client
  process only caches the fds it has used.
- Windows: a running Game.exe and the character's file cannot be opened with sharing mode 0 (ERROR_SHARING_VIOLATION).
  The probe opens and closes at once, the companions (.key / .map / .stash) before the .d2s; first hit wins.

in_game(save_dir) -> set of character names. Never raises (an error = empty set), cached about 1 s.
"""
import os
import sys
import time

GAME_EXES = ('game.exe',)
SERVERS = ('wineserver', 'wineserver64')
OWN_EXT = ('.key', '.map', '.ma0', '.ma1', '.ma2', '.ma3', '.stash', '.d2s')   # probe order on Windows
TTL = 1.0
PROC_TTL = 3.0                     # the process list (a /proc walk) is cached a little longer

_cache = {}                        # realpath(save_dir) -> (time, frozenset)
_procs = [0.0, [], []]             # time, [game pids], [wineserver pids]


def clear():
    _cache.clear()
    _procs[0] = 0.0


def _arg0(pid):
    with open(f'/proc/{pid}/cmdline', 'rb') as f:
        return f.read().split(b'\0')[0].decode('utf-8', 'replace')


def _base(arg0):
    return arg0.replace('\\', '/').rsplit('/', 1)[-1].lower()


def _processes():
    now = time.monotonic()
    if now - _procs[0] < PROC_TTL:
        return _procs[1], _procs[2]
    games, servers = [], []
    own = os.getpid()
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == own:
            continue
        try:
            b = _base(_arg0(pid))
        except OSError:
            continue
        if b in GAME_EXES:
            games.append(int(pid))
        elif b in SERVERS:
            servers.append(int(pid))
    _procs[:] = [now, games, servers]
    return games, servers


def char_of(fname):
    """Character name of one of its own files, else None."""
    stem, ext = os.path.splitext(fname)
    if ext.lower() in OWN_EXT and stem and not stem.startswith('_'):
        return stem
    return None


def held_files(save_dir):
    """{pid: [file names in save_dir that pid holds open]} of the Game.exe (and wineserver) processes (Linux)."""
    real = os.path.normcase(os.path.realpath(save_dir))
    games, servers = _processes()
    out = {}
    for pid in games + (servers if games else []):
        try:
            fds = os.listdir(f'/proc/{pid}/fd')
        except OSError:
            continue
        for fd in fds:
            try:
                link = os.readlink(f'/proc/{pid}/fd/{fd}')
            except OSError:
                continue
            if not link.startswith('/') or link.endswith(' (deleted)'):
                continue
            d, name = os.path.split(link)
            if os.path.normcase(os.path.realpath(d)) == real:
                out.setdefault(pid, []).append(name)
    return out


def _linux(save_dir):
    names = set()
    for files in held_files(save_dir).values():
        for f in files:
            n = char_of(f)
            if n:
                names.add(n)
    return names


_win_game = [0.0, False]


def _win_game_running():
    """A Game.exe in the process list (Toolhelp snapshot, no subprocess), cached PROC_TTL."""
    now = time.monotonic()
    if now - _win_game[0] < PROC_TTL:
        return _win_game[1]
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD),
                    ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                    ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD),
                    ('szExeFile', ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)                    # TH32CS_SNAPPROCESS
    found = False
    try:
        pe = PE()
        pe.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            if pe.szExeFile.lower() in GAME_EXES:
                found = True
                break
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    _win_game[:] = [now, found]
    return found


def _windows(save_dir, only=None):
    """Characters whose files cannot be opened with sharing mode 0 while a Game.exe runs (only: that one name)."""
    import ctypes
    from ctypes import wintypes
    if not _win_game_running():         # the probe is not free for the game: only while it runs
        return set()
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE)
    invalid = wintypes.HANDLE(-1).value
    files = {}
    for f in os.listdir(save_dir):
        n = char_of(f)
        if n and (only is None or n.lower() == only.lower()):
            files.setdefault(n, []).append(f)
    names = set()
    for n, fs in files.items():
        fs.sort(key=lambda f: OWN_EXT.index(os.path.splitext(f)[1].lower()))
        for f in fs:
            h = k32.CreateFileW(os.path.join(save_dir, f), 0x80000000, 0, None, 3, 0x80, None)   # GENERIC_READ, OPEN_EXISTING
            if h == invalid or h is None:
                if ctypes.get_last_error() == 32:                   # ERROR_SHARING_VIOLATION: someone holds it
                    names.add(n)
                    break
                continue
            k32.CloseHandle(h)
    return names


def in_game(save_dir, only=None):
    """Names of the characters of save_dir that are in a game now (see the module text). Never raises.
    only: the one character that matters (Windows then probes that character's files alone)."""
    try:
        if not save_dir or not os.path.isdir(save_dir):
            return set()
        key = (os.path.realpath(save_dir), only.lower() if only and sys.platform == 'win32' else None)
        now = time.monotonic()
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < TTL:
            return set(hit[1])
        if sys.platform == 'win32':
            names = _windows(save_dir, only)
        elif os.path.isdir('/proc'):
            names = _linux(save_dir)
        else:
            names = set()
        _cache[key] = (now, frozenset(names))
        return set(names)
    except Exception:
        return set()


def is_in_game(path):
    """True when the character of this .d2s (or companion) path is in a game."""
    if not path:
        return False
    d, f = os.path.split(path)
    n = char_of(f)
    return bool(n) and n.lower() in {x.lower() for x in in_game(d, n)}


# ------------------------------------------------------------------------------------------- the editor's side
# Live refresh: while the selected character is in a game (and a few polls after it left: the save & exit write
# lands as the game closes its files), its .d2s, its .stash, the shared stash and the stash shown are watched;
# a change the editor did not make itself is read again (the Stash tab, the inventory panel, the Character tab
# with its pending edits kept: CharacterWindow.sync_file) and the status bar says so. Not in game: nothing.
# Warning: a red line beside the status bar while the selected character is in a game; moves between stash and
# character and the Character tab's SAVE ask first.
POLL_MS = 1500
GRACE = 3                          # polls still watched after the character left the game
_own = {}                          # path -> sig of the file as the editor itself last wrote it


def _sig(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _T(key, default, **kw):
    try:
        from mxl_lang import T
        return T(key, default, **kw)
    except Exception:
        return default.format(**kw)


def _watched(app):
    path = app.character_file()
    if not path:
        return None, []
    d, f = os.path.split(path)
    n = char_of(f)
    files = [path, getattr(app, 'path', None), os.path.join(d, f'{n}.stash'), os.path.join(d, '_sharedstash.shared')]
    out = []
    for x in files:
        if x and os.path.abspath(x) not in out:
            out.append(os.path.abspath(x))
    return path, out


def _baseline(app):
    try:
        _, files = _watched(app)
        app._ig_sigs = {f: _sig(f) for f in files}
    except Exception:
        app._ig_sigs = {}


def _char_tab():
    try:
        import mxl_tabs
        return mxl_tabs.built_owner('Character')
    except Exception:
        return None


def warning_text(name):
    return _T('ig.warn', '{name} is in a game: the game will overwrite edits to this character when it saves',
              name=name)


def _show_warning(app, name):
    lbl = getattr(app, '_ig_label', None)
    if lbl is None:
        if not name:
            return
        from tkinter import ttk
        lbl = ttk.Label(app.status.master, text='', foreground='#e06060', anchor='w')
        app._ig_label = lbl
    text = warning_text(name) if name else ''
    if str(lbl.cget('text')) == text:
        return
    lbl.configure(text=text)
    if name:
        mgr = app.status.winfo_manager()
        if mgr == 'grid':
            gi = app.status.grid_info()
            lbl.grid(row=int(gi.get('row', 0)) + 1, column=gi.get('column', 0), sticky='w')
        else:
            lbl.pack(side='bottom', fill='x', after=app.status)
    else:
        lbl.pack_forget() if lbl.winfo_manager() == 'pack' else lbl.grid_forget()


def _busy(app):
    if getattr(app, 'drag', None):
        return True
    inv = getattr(app, 'inventory', None)
    if inv is not None and getattr(inv, 'drag', None) is not None:
        return True
    w = _char_tab()
    return w is not None and getattr(w, 'drag', None) is not None


def tick(app):
    """One poll (the loop calls it every POLL_MS; tests call it directly). Never raises."""
    try:
        path, files = _watched(app)
        name = char_of(os.path.basename(path)) if path else None
        now_in = bool(path) and is_in_game(path)
        _show_warning(app, name if now_in else None)
        w = _char_tab()
        wch = getattr(w, 'ch', None) if w is not None else None
        if wch is not None:
            same = path and os.path.abspath(wch.path) == os.path.abspath(path)
            warned = getattr(w, '_ig_warned', False)
            if same and now_in and not warned:
                w.set_status(warning_text(name), True)
            elif warned and not (same and now_in) and str(w.status.cget('text')) == warning_text(char_of(os.path.basename(wch.path))):
                w.set_status('')                       # back at the menu: the tab's warning goes
            w._ig_warned = bool(same and now_in)
        grace = GRACE if now_in else max(0, getattr(app, '_ig_grace', 0) - 1)
        app._ig_grace = grace
        old = getattr(app, '_ig_sigs', None)
        if not (now_in or grace) or old is None:
            _baseline(app)
            return False
        if _busy(app):
            return False
        new = {f: _sig(f) for f in files}
        changed = [f for f in files if new[f] != old.get(f) and new[f] != _own.get(f)]
        if not changed:
            app._ig_sigs = new
            return False
        shown = []
        if app.path and os.path.abspath(app.path) in changed:
            app.load(app.path, keep_selection=True)        # draw_grid -> inventory panel -> Character tab
            shown.append(app.path)
        if os.path.abspath(path) in changed:
            inv = getattr(app, 'inventory', None)
            if inv is not None:
                inv.refresh()
            if wch is not None and os.path.abspath(wch.path) == os.path.abspath(path):
                w.sync_file()
            shown.append(path)
        app._ig_sigs = {f: _sig(f) for f in files}
        if shown:
            app.status.configure(text=_T('ig.reloaded', 'Reloaded: the game saved {name}', name=name))
        return bool(shown)
    except Exception as e:
        print('in-game watch:', e)
        return False


def confirm(path, parent=None):
    """True when the write may go ahead: the character of path is not in a game, or the user says so."""
    try:
        if not path or not is_in_game(path):
            return True
        from tkinter import messagebox
        name = char_of(os.path.basename(path))
        return bool(messagebox.askyesno(_T('ig.title', 'Character in a game'), _T(
            'ig.ask', '{name} is in a game: the game will overwrite this change when it saves the character '
            '(and an item moved between stash and character may end up twice or be lost). Write anyway?',
            name=name), parent=parent))
    except Exception as e:
        print('in-game check:', e)
        return True


def _gate(cls, meth, path_of, parent_of):
    orig = getattr(cls, meth)

    def gated(self, *a, **k):
        try:
            path, parent = path_of(self), parent_of(self)
        except Exception:
            path, parent = None, None
        if not confirm(path, parent):
            return None
        return orig(self, *a, **k)
    gated.__wrapped__ = orig
    setattr(cls, meth, gated)


def install(App):
    import mxl_char
    from mxl_char_gui import CharacterWindow
    from mxl_inv_gui import MainInventory
    o_save = mxl_char.Character.save

    def save(self, *a, **k):
        r = o_save(self, *a, **k)
        _own[os.path.abspath(self.path)] = _sig(self.path)
        return r
    mxl_char.Character.save = save

    import logging

    class OwnWrites(logging.Handler):            # mxl_log's "saved: <what>: <file>": the editor's own writes
        def emit(self, rec):
            try:
                if str(rec.msg).startswith('saved:') and rec.args:
                    f = str(rec.args[-1])
                    _own[os.path.abspath(f)] = _sig(f)
            except Exception:
                pass
    logging.getLogger('capybara').addHandler(OwnWrites(logging.INFO))

    o_load = App.load

    def load(self, *a, **k):
        # the collector reloads a stash changed on disk by itself: the game's save is then already shown
        # when the poll comes; the note is given here (after the collector's own status text)
        try:
            path, files = _watched(self)
            old = getattr(self, '_ig_sigs', None)
            foreign = bool(path and old is not None and (is_in_game(path) or getattr(self, '_ig_grace', 0)) and any(
                _sig(f) != old.get(f) and _sig(f) != _own.get(f) for f in files))
        except Exception:
            path, foreign = None, False
        r = o_load(self, *a, **k)
        _baseline(self)
        if foreign:
            name = char_of(os.path.basename(path))
            try:
                self.root.after_idle(lambda: self.status.configure(
                    text=_T('ig.reloaded', 'Reloaded: the game saved {name}', name=name)))
            except Exception:
                pass
        return r
    App.load = load

    for m in ('save_progress', 'to_stash', 'from_stash'):
        _gate(CharacterWindow, m, lambda w: w.ch.path, lambda w: w.top)
    for m in ('to_stash', 'drop_from_stash'):
        _gate(MainInventory, m, lambda i: i.ch.path if i.ch is not None else i.app.character_file(),
              lambda i: i.app.root)

    o_build = App._build

    def _build(self):
        o_build(self)

        def loop():
            tick(self)
            try:
                self.root.after(POLL_MS, loop)
            except Exception:
                pass
        try:
            self.root.after(POLL_MS, loop)
        except Exception as e:
            print('in-game watch not started:', e)
    App._build = _build


if __name__ == '__main__':                  # evidence: what the game holds open, at the menu and in a game
    folder = sys.argv[1] if len(sys.argv) > 1 else '.'
    g, s = _processes()
    print('Game.exe pids:', g, ' wineserver pids:', s)
    for pid, fs in held_files(folder).items():
        print(pid, sorted(fs))
    print('in game:', sorted(in_game(folder)))
