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


def _windows(save_dir):
    import ctypes
    from ctypes import wintypes
    import subprocess
    try:                                    # only while a Game.exe runs: the probe is not free for the game
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Game.exe', '/NH'], capture_output=True, text=True,
                             timeout=2, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except Exception:
        return set()
    if 'game.exe' not in out.lower():
        return set()
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE)
    invalid = wintypes.HANDLE(-1).value
    files = {}
    for f in os.listdir(save_dir):
        n = char_of(f)
        if n:
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


def in_game(save_dir):
    """Names of the characters of save_dir that are in a game now (see the module text). Never raises."""
    try:
        if not save_dir or not os.path.isdir(save_dir):
            return set()
        key = os.path.realpath(save_dir)
        now = time.monotonic()
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < TTL:
            return set(hit[1])
        if sys.platform == 'win32':
            names = _windows(save_dir)
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
    return bool(n) and n.lower() in {x.lower() for x in in_game(d)}


if __name__ == '__main__':                  # evidence: what the game holds open, at the menu and in a game
    folder = sys.argv[1] if len(sys.argv) > 1 else '.'
    g, s = _processes()
    print('Game.exe pids:', g, ' wineserver pids:', s)
    for pid, fs in held_files(folder).items():
        print(pid, sorted(fs))
    print('in game:', sorted(in_game(folder)))
