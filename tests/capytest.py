"""Shared helper of the regression suite: fixture copies, the safety guard, a tiny test registry, the headless
engine loader and the in-process GUI harness. Imported by every tests/test_*.py; see tests/README.md.

A test file is a script:

    import capytest as T
    MODE = 'engine'                # or 'gui' (read by tests/run.py with ast, never imported there)

    @T.test
    def some_name(): ...

    T.main(globals())

The runner (tests/run.py) starts one process per file (per test when ISOLATE = True) and passes, in the
environment: CAPY_APPDIR, CAPY_REPO, CAPY_SRC_USER, CAPY_SRC_SAVES, CAPY_SRC_SAVES2, CAPY_SRC_SAVES3, CAPY_TMP, CAPY_RESULTS,
CAPY_ONLY (names, comma separated; empty = all), CAPY_VARIANT.
"""
import glob
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import traceback

sys.dont_write_bytecode = True


# ------------------------------------------------------------------------------------------- safety guard
def _real_save_dir():
    """What the Linux launcher would pick without MXL_SAVE_DIR (packaging/linux/capybara_editor.py)."""
    home = os.path.expanduser('~')
    prefixes = [os.environ.get('WINEPREFIX'), os.path.join(home, '.wine')]
    for pat in ('Games/*', '.local/share/bottles/bottles/*', '.var/app/com.usebottles.bottles/data/bottles/bottles/*',
                '.local/share/lutris/runners/wine/prefixes/*', '.steam/steam/steamapps/compatdata/*/pfx',
                '.local/share/Steam/steamapps/compatdata/*/pfx'):
        prefixes += sorted(glob.glob(os.path.join(home, pat)))
    for p in prefixes:
        if not p:
            continue
        found = sorted(glob.glob(os.path.join(p, 'drive_c', 'users', '*', 'AppData', 'Roaming', 'MedianXL', 'save')))
        found = [f for f in found if os.path.isdir(f)]
        if found:
            return found[0]
    return None


def guard(path, what='path'):
    """Aborts the process when `path` could be a real save / settings folder. Called for every folder a test
    process works in, before anything is imported from the application."""
    if not path:
        _abort(f'{what} is empty')
    real = os.path.realpath(path)
    parts = real.split(os.sep)
    if len(parts) > 3 and parts[1] == 'home' and parts[3] == 'Games':
        _abort(f'{what} {real!r} is inside /home/*/Games')
    for p in (path, real):
        if 'drive_c/users' in p.replace('\\', '/'):
            _abort(f'{what} {p!r} contains drive_c/users')
    auto = _real_save_dir()
    if auto and (real == os.path.realpath(auto) or real.startswith(os.path.realpath(auto) + os.sep)):
        _abort(f'{what} {real!r} is the real save folder the launcher would find')
    return path


def _abort(msg):
    sys.stderr.write('SAFETY GUARD: ' + msg + ' - refusing to run.\n')
    sys.stderr.flush()
    os._exit(97)


# ------------------------------------------------------------------------------------------- environment
APPDIR = os.environ.get('CAPY_APPDIR', '')
APP = os.path.join(APPDIR, 'opt', 'capybara')
REPO = os.environ.get('CAPY_REPO') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_USER = os.environ.get('CAPY_SRC_USER', '')
SRC_SAVES = os.environ.get('CAPY_SRC_SAVES', '')
SRC_SAVES2 = os.environ.get('CAPY_SRC_SAVES2', '')
SRC_SAVES3 = os.environ.get('CAPY_SRC_SAVES3', '')            # test-druid (in-game screenshots)
VARIANT = os.environ.get('CAPY_VARIANT', '')
_TMP = None


def tmp():
    """The folder of this test process (inside the session folder), removed by the runner afterwards."""
    global _TMP
    if _TMP is None:
        base = os.environ.get('CAPY_TMP') or tempfile.gettempdir()
        _TMP = guard(tempfile.mkdtemp(prefix='p-', dir=base), 'work folder')
    return _TMP


def user_ok():
    return os.path.isfile(os.path.join(SRC_USER, 'data', 'itemstatcost.bin'))


def saves_ok(folder=None):
    folder = SRC_SAVES if folder is None else folder
    return bool(folder) and bool(glob.glob(os.path.join(folder, '*.d2s'))) and \
        bool(glob.glob(os.path.join(folder, '*.stash')))


def missing(needs):
    """Reason text when a fixture this file needs is not there, else None."""
    if 'user' in needs and not user_ok():
        return f'no game tables: MXL_TEST_USER_DIR={SRC_USER!r} has no data/itemstatcost.bin (see tests/README.md)'
    if 'saves' in needs and not saves_ok():
        return f'no sample saves: MXL_TEST_SAVE_DIR={SRC_SAVES!r} has no *.d2s + *.stash (see tests/README.md)'
    if 'saves2' in needs and not saves_ok(SRC_SAVES2):
        return f'no second sample: MXL_TEST_SAVE_DIR2={SRC_SAVES2!r} has no *.d2s + *.stash (see tests/README.md)'
    if 'saves3' in needs and not saves_ok(SRC_SAVES3):
        return f'no third sample: MXL_TEST_SAVE_DIR3={SRC_SAVES3!r} has no *.d2s + *.stash (see tests/README.md)'
    return None


_n = [0]


def fresh_saves(which=1):
    """A new private copy of a sample save folder (1 = MXL_TEST_SAVE_DIR, 2 = MXL_TEST_SAVE_DIR2,
    3 = MXL_TEST_SAVE_DIR3)."""
    src = {1: SRC_SAVES, 2: SRC_SAVES2, 3: SRC_SAVES3}[which]
    if not saves_ok(src):
        raise Skip(missing(({1: 'saves', 2: 'saves2', 3: 'saves3'}[which],)))
    _n[0] += 1
    dst = os.path.join(tmp(), f'saves{which}-{_n[0]}')
    shutil.copytree(src, dst)
    return guard(dst, 'save folder copy')


def fresh_user():
    """A new private copy of the user folder (settings + extracted tables). settings.json is pointed away from
    the fixture: the stored 'last_stash' is an absolute path the application would open and write."""
    if not user_ok():
        raise Skip(missing(('user',)))
    _n[0] += 1
    dst = os.path.join(tmp(), f'user-{_n[0]}')
    shutil.copytree(SRC_USER, dst, ignore=shutil.ignore_patterns('capybara.log*', '*.bak', '*.lock'))
    guard(dst, 'user folder copy')
    p = os.path.join(dst, 'settings.json')
    try:
        with open(p, encoding='utf-8') as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    for k in ('last_stash', 'last_character', 'last_view', 'window_geometry', 'geometry'):
        st.pop(k, None)
    st['language'] = 'en'                             # the tests look menu entries up by their English text
    st['capy_unrestricted'] = False                   # the creator's legit ranges (a test may switch it on)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=1)
    return dst


# ------------------------------------------------------------------------------------------- registry
class Skip(Exception):
    pass


class Failed(AssertionError):
    pass


_tests = []
_soft = []


def test(fn=None, *, xfail=None, needs=()):
    """Registers a test. xfail='<bug description>': the test is known to fail because of a real bug; it is
    still run, a failure counts as 'expected failure', a pass is reported as 'unexpected pass'."""
    def deco(f):
        _tests.append((f.__name__, f, xfail, tuple(needs)))
        return f
    return deco(fn) if fn is not None else deco


def skip(reason):
    raise Skip(reason)


def check(cond, msg):
    """Soft assertion: the test goes on and fails at its end with every message collected."""
    if not cond:
        _soft.append(str(msg))
    return bool(cond)


def eq(a, b, msg):
    if a != b:
        ra, rb = repr(a), repr(b)
        _soft.append(f'{msg}: {ra[:300]} != {rb[:300]}')
    return a == b


def _report(name, status, detail='', secs=0.0):
    rec = dict(name=name, status=status, detail=detail, secs=round(secs, 2), variant=VARIANT)
    path = os.environ.get('CAPY_RESULTS')
    if path:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec) + '\n')
    else:
        print(f'{status.upper():6} {name}  {detail}')


def _selected():
    only = [x for x in os.environ.get('CAPY_ONLY', '').split(',') if x]
    return [t for t in _tests if not only or t[0] in only]


def _run_one(name, fn, xfail, needs, before=None, after=None):
    t0 = time.time()
    del _soft[:]
    status, detail = 'pass', ''
    try:
        why = missing(needs)
        if why:
            raise Skip(why)
        if before:
            before()
        fn()
        if after:
            after()
        if _soft:
            raise Failed('; '.join(_soft[:8]) + (f' (+{len(_soft) - 8} more)' if len(_soft) > 8 else ''))
    except Skip as e:
        status, detail = 'skip', str(e)
    except Failed as e:
        status, detail = 'fail', str(e)
        if _soft and not detail.startswith(_soft[0]):       # raised in the middle: what was collected before
            detail += ' ;; earlier: ' + '; '.join(_soft[:6])
    except Exception:
        tb = traceback.format_exc(limit=-4).strip().splitlines()
        status, detail = 'fail', (tb[-1] + ' | ' + ' | '.join(x.strip() for x in tb[1:-1]))[:700]
        if _soft:
            detail += ' ;; earlier: ' + '; '.join(_soft[:6])
    if xfail:
        if status == 'fail':
            status, detail = 'xfail', f'known bug: {xfail} | {detail}'[:900]
        elif status == 'pass':
            status, detail = 'xpass', f'passes now - remove the xfail marker ({xfail})'
    _report(name, status, detail, time.time() - t0)


def main(g):
    """Runs the tests of the calling file (engine or GUI, from its MODE)."""
    needs = tuple(g.get('NEEDS', ('user', 'saves')))
    why = missing(needs)
    if why:
        for name, _f, _x, _n2 in _selected():
            _report(name, 'skip', why)
        return
    if g.get('MODE') == 'gui':
        _gui_main(g)
        return
    if g.get('ENGINE', True) and 'user' in needs:
        engine()
    for name, fn, xfail, tneeds in _selected():
        _run_one(name, fn, xfail, tneeds)
    sys.stdout.flush()


# ------------------------------------------------------------------------------------------- engine
class NS(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


_engine = None


def engine():
    """The application's data layer without any window: E.data (game tables), E.cr (Creator) and the modules
    E.fmt / E.save / E.MC (mxl_char) / E.C (mxl_creator) / E.rules / E.tip / E.paths. Loaded once per process,
    on a private copy of the user folder; MXL_SAVE_DIR points at a private save copy nothing should use."""
    global _engine
    if _engine is not None:
        return _engine
    os.environ['MXL_USER_DIR'] = fresh_user()
    os.environ['MXL_SAVE_DIR'] = fresh_saves() if saves_ok() else guard(os.path.join(tmp(), 'nosaves'))
    os.environ.setdefault('LOCALAPPDATA', tmp())
    if APP not in sys.path:
        sys.path.insert(0, APP)
    import paths
    guard(paths.USER_DIR, 'paths.USER_DIR')
    import mxl_data
    import mxl_format
    import mxl_format_fix
    out = sys.stdout
    sys.stdout = open(os.devnull, 'w')            # the installers print one line each
    try:
        import mxl_free
        mxl_free.install()
        mxl_format_fix.install()
    finally:
        sys.stdout = out
    import mxl_char
    import mxl_creator
    import mxl_rules
    import mxl_save
    import mxl_tooltip
    data = mxl_data.Data(paths.DATA_DIR)
    _engine = NS(data=data, cr=mxl_creator.Creator(data), fmt=mxl_format, save=mxl_save, MC=mxl_char,
                 C=mxl_creator, rules=mxl_rules, tip=mxl_tooltip, paths=paths)
    return _engine


# ------------------------------------------------------------------------------------------- file checks
def read(path):
    with open(path, 'rb') as f:
        return f.read()


def d2_checksum(raw):
    """The .d2s checksum, written here from the format description (not the application's code): the four bytes
    at 12 count as zero; for every byte the 32-bit sum is rotated left by one bit, then the byte is added."""
    s = 0
    for i, x in enumerate(raw):
        if 12 <= i < 16:
            x = 0
        s = ((s << 1) & 0xFFFFFFFF | (s >> 31)) + x & 0xFFFFFFFF
    return s


def d2s_header_ok(raw):
    """[problems] of a character file's signature, stored size and stored checksum."""
    out = []
    if raw[:4] != b'\x55\xaa\x55\xaa':
        out.append('signature')
    if struct.unpack_from('<I', raw, 8)[0] != len(raw):
        out.append(f'stored size {struct.unpack_from("<I", raw, 8)[0]} != {len(raw)}')
    if struct.unpack_from('<I', raw, 12)[0] != d2_checksum(raw):
        out.append('checksum')
    return out


def stash_snap(path, data=None):
    """{(page, x, y): (code, bytes of the item with its socketed items)} from a fresh parse of the file."""
    E = engine() if data is None else None
    import mxl_save
    data = data if data is not None else E.data
    buf = mxl_save.read_file(path)
    out = {}
    for it in mxl_save.parse_stash(path, data):
        k = (it['page'], it['x'], it['y'])
        assert k not in out, f'two stash items at {k}'
        out[k] = (it['code'], bytes(mxl_save.item_blob(buf, it)))
    return out


def stash_items(path, data):
    """{(page, x, y): parsed item} from a fresh parse."""
    import mxl_save
    return {(it['page'], it['x'], it['y']): it for it in mxl_save.parse_stash(path, data)}


def char_snap(path, data):
    """{(merc, location, equipped, x, y, panel): (code, bytes)} of a character file read from disk."""
    import mxl_char
    ch = mxl_char.Character(path, data)
    out = {}
    for merc in (False, True):
        if merc and ch.merc_items is None:
            continue
        for e in ch.entries(merc):
            it = e.it
            k = (merc, it['location'], it.get('equipped'), it['x'], it['y'], it.get('panel'))
            assert k not in out, f'two character items at {k}'
            out[k] = (it['code'], bytes(e.blob))
    return out


def diff(a, b):
    """(removed, added, changed) keys between two snapshots."""
    gone = sorted(k for k in a if k not in b)
    new = sorted(k for k in b if k not in a)
    chg = sorted(k for k in a if k in b and a[k] != b[k])
    return gone, new, chg


def only_changed(a, b, gone=(), new=(), chg=(), what=''):
    """Soft-asserts that two snapshots differ in exactly these keys (everything else byte-identical)."""
    g, n, c = diff(a, b)
    return eq((g, n, c), (sorted(gone), sorted(new), sorted(chg)), f'{what}: (removed, added, changed) items')


def stats_of(it, key='stats'):
    return sorted((s['id'], s.get('param') or 0, s['value']) for s in it.get(key) or ())


# ------------------------------------------------------------------------------------------- GUI harness
G = NS(app=None, root=None, menu=None, boxes=[], answers={}, stderr_path=None, save_dir=None, user_dir=None, sample=1)


def pump(n=6, wait=0.0):
    for _ in range(n):
        G.root.update()
        if wait:
            time.sleep(wait)
    G.root.update()


def settle(secs=0.4):
    """Runs the event loop for a while (timers, threads handing work back with after())."""
    end = time.time() + secs
    while time.time() < end:
        G.root.update()
        time.sleep(0.02)
    G.root.update()


def wait_for(cond, secs=20.0, what='condition'):
    end = time.time() + secs
    while time.time() < end:
        G.root.update()
        v = cond()
        if v:
            return v
        time.sleep(0.03)
    raise Failed(f'timeout waiting for {what}')


def _stub_dialogs():
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog
    tk.Menu.tk_popup = lambda self, x, y, entry='': G.__setitem__('menu', self)
    tk.Menu.post = lambda self, x, y: G.__setitem__('menu', self)
    tk.Menu.grab_release = lambda self: None
    for name, default in (('showerror', 'ok'), ('showwarning', 'ok'), ('showinfo', 'ok'), ('askyesno', True),
                          ('askokcancel', True), ('askyesnocancel', True), ('askquestion', 'yes'),
                          ('askretrycancel', False)):
        def box(title=None, message=None, _name=name, _default=default, **kw):
            G.boxes.append((_name, str(title), str(message)))
            return G.answers.get(_name, _default)
        setattr(messagebox, name, box)
    simpledialog.askinteger = lambda *a, **k: G.answers.get('int')
    simpledialog.askstring = lambda *a, **k: G.answers.get('str')
    simpledialog.askfloat = lambda *a, **k: G.answers.get('float')
    filedialog.asksaveasfilename = lambda *a, **k: G.answers.get('file', '')
    filedialog.askopenfilename = lambda *a, **k: G.answers.get('file', '')
    filedialog.askdirectory = lambda *a, **k: G.answers.get('dir', '')


def errors_since(mark):
    """Error lines the application produced since mark(): tracebacks on stderr, ERROR lines of capybara.log,
    error boxes it tried to show."""
    out = []
    try:
        sys.stderr.flush()
        with open(G.stderr_path, encoding='utf-8', errors='replace') as f:
            f.seek(mark[0])
            txt = f.read()
        for bad in ('Traceback (most recent call last)', 'Exception in Tkinter callback', 'TclError'):
            if bad in txt:
                tail = [ln for ln in txt.strip().splitlines() if ln.strip()][-3:]
                out.append('stderr: ' + ' / '.join(tail)[:400])
                break
    except OSError:
        pass
    try:
        with open(os.path.join(G.user_dir, 'capybara.log'), encoding='utf-8', errors='replace') as f:
            f.seek(mark[1])
            lines = f.read().splitlines()
        bad = [i for i, ln in enumerate(lines) if ' ERROR ' in ln or 'Traceback' in ln]
        if bad:
            out.append('capybara.log: ' + ' / '.join(lines[bad[0]:bad[0] + 12])[-500:])
    except OSError:
        pass
    for kind, title, msg in G.boxes[mark[2]:]:
        if kind == 'showerror':
            out.append(f'error box {title!r}: {msg[:200]}')
    return out


def mark():
    sys.stderr.flush()
    try:
        a = os.path.getsize(G.stderr_path)
    except OSError:
        a = 0
    try:
        b = os.path.getsize(os.path.join(G.user_dir, 'capybara.log'))
    except OSError:
        b = 0
    return (a, b, len(G.boxes))


def xft_lib(appdir=None):
    """The Xft build of Tk in the application folder (the launcher's lib/xft/), present or not."""
    if appdir:
        return os.path.join(appdir, 'opt', 'python', 'lib', 'xft', 'libtcl9tk9.0.so')
    return os.path.join(sys.base_prefix, 'lib', 'xft', 'libtcl9tk9.0.so')


def use_xft(appdir=None):
    """GUI tests draw with the Xft fonts users get whenever the application folder has the Xft Tk (CAPY_XFT=0:
    X core fonts; CAPY_XFT=1: Xft or the test process stops)."""
    v = os.environ.get('CAPY_XFT', '').strip()
    if v == '0':
        return False
    return bool(v) or os.path.isfile(xft_lib(appdir))


def _gui_main(g):
    """Starts the real application in this process (the Linux launcher's main()); Tk's mainloop is wrapped so
    that the tests of the file run inside it, then the window is destroyed. One application per process.
    stdout / stderr of the application go to files in the work folder (errors_since() reads them)."""
    if g.get('EMPTY_GUI'):
        G.user_dir = os.path.join(tmp(), 'empty-user')
        G.save_dir = os.path.join(tmp(), 'empty-saves')
        home = os.path.join(tmp(), 'empty-home')
        for folder in (G.user_dir, G.save_dir, home):
            os.makedirs(folder)
        os.environ['HOME'] = home
    else:
        G.user_dir = fresh_user()
        G.sample = 2 if g.get('SAMPLE') == 2 else 1
        G.save_dir = fresh_saves(G.sample)
    os.environ['MXL_USER_DIR'] = G.user_dir
    os.environ['MXL_SAVE_DIR'] = G.save_dir
    os.environ['LOCALAPPDATA'] = guard(os.path.join(tmp(), 'localappdata'))
    os.environ['XDG_DATA_HOME'] = os.environ['LOCALAPPDATA']
    os.environ.pop('MXL_EXIT_AFTER', None)
    for k, v in (g.get('ENV') or {}).items():
        os.environ[k] = v
    G.stderr_path = os.path.join(tmp(), 'stderr.txt')
    sys.stderr.flush()
    keep = os.dup(2)
    fd = os.open(G.stderr_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(fd, 2)
    out_path = os.path.join(tmp(), 'stdout.txt')            # the application prints progress lines
    keep_out = os.dup(1)
    fd1 = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    sys.stdout.flush()
    os.dup2(fd1, 1)
    sys.path.insert(0, APP)
    sys.argv = [os.path.join(APP, 'capybara_editor.py')]
    if use_xft():
        # the text the users see: the launcher loads the Xft build of Tk (antialiased fonts, other metrics) before
        # tkinter, but this harness imports tkinter first, so without this every GUI test runs on X core fonts
        import ctypes
        lib = xft_lib()
        if not os.path.isfile(lib):
            sys.stderr.write(f'CAPY_XFT=1 but the application folder has no Xft Tk ({lib}): build it without MXL_NO_XFT\n')
            os._exit(2)
        ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
    import tkinter
    state = {'ran': False}

    real_loop = tkinter.Misc.mainloop

    def loop(self, n=0):
        # the tests run as a timer callback INSIDE the real main loop: worker threads of the application hand
        # their results back with after(), which only works while the main loop is running
        if state['ran']:
            return real_loop(self, n)
        state['ran'] = True
        self.winfo_toplevel().after(30, body)
        return real_loop(self, n)

    def body():
        try:
            import gc
            import mxl_gui
            G.app = next(o for o in gc.get_objects() if isinstance(o, mxl_gui.App))
            G.root = G.app.root
            _stub_dialogs()
            guard(os.path.dirname(G.app.path) if getattr(G.app, 'path', None) else G.save_dir, 'open stash folder')
            if getattr(G.app, 'path', None) and not os.path.realpath(G.app.path).startswith(os.path.realpath(tmp())):
                _abort(f'the application opened {G.app.path!r}, outside the test folder')
            geo = os.environ.get('CAPY_GEOMETRY') or g.get('GEOMETRY') or '1180x680+0+0'
            G.root.geometry(geo)
            pump(20, 0.02)
            if g.get('WAIT_TABS', True):
                import mxl_tabs
                wait_for(lambda: mxl_tabs.built_owner('Creator') is not None, 40, 'the Character / Creator tabs')
                settle(0.3)
            startup = errors_since((0, 0, 0))
            for name, fn, xfail, needs in _selected():
                m = mark()
                del G.boxes[:]
                m = (m[0], m[1], 0)

                def after(m=m, name=name):
                    pump(4)
                    if not g.get('ALLOW_ERRORS'):
                        for e in errors_since(m):
                            check(False, 'application error during the test: ' + e)
                _run_one(name, fn, xfail, needs, before=reset if g.get('RESET') else None, after=after)
            if startup and not g.get('ALLOW_ERRORS'):
                _report('startup_without_errors', 'fail', ' ;; '.join(startup)[:900])
        except Exception:
            _report('gui_harness', 'fail', traceback.format_exc(limit=-5)[-900:])
        finally:
            try:
                G.root.destroy()
            except Exception:
                pass
            _finish(keep, keep_out)

    tkinter.Misc.mainloop = loop
    try:
        import capybara_editor
        capybara_editor.main()
    except SystemExit:
        pass
    except Exception:
        _report('gui_harness', 'fail', 'application start raised: ' + traceback.format_exc(limit=-5)[-900:])
    if not state['ran']:
        _report('gui_harness', 'fail', 'the application never reached its main loop')
    _finish(keep, keep_out)


def _finish(keep, keep_out):
    try:
        sys.stderr.flush()
        sys.stdout.flush()
        os.dup2(keep, 2)
        os.dup2(keep_out, 1)
        with open(G.stderr_path, encoding='utf-8', errors='replace') as f:     # the runner shows the end of it
            tail = f.read()[-3000:]                                               # when the process failed
        if tail.strip():
            sys.stderr.write('---- stderr of the application (end)\n' + tail + '\n')
            sys.stderr.flush()
    except OSError:
        pass
    try:
        import mxl_splash                       # the splash is its own process: make sure it is gone
        p = mxl_splash._proc.get('p')
        if p is not None and p.poll() is None:
            p.kill()
    except Exception:
        pass
    os._exit(0)


# ---- menus
def menu_entries(m, depth=0):
    """[(depth, label, state, menu, index)] of a captured menu, cascades included."""
    out = []
    if m is None:
        return out
    last = m.tk.call(m._w, 'index', 'end')
    if last in ('', 'none', None):
        return out
    for i in range(int(last) + 1):
        t = m.type(i)
        if t in ('separator', 'tearoff'):
            continue
        out.append((depth, m.entrycget(i, 'label'), str(m.entrycget(i, 'state')), m, i))
        if t == 'cascade':
            out += menu_entries(m.nametowidget(m.entrycget(i, 'menu')), depth + 1)
    return out


def menu_labels(m):
    return [lab for _d, lab, _s, _m, _i in menu_entries(m)]


def invoke(m, text, under=None):
    """Invokes the first enabled command whose label starts with `text` (inside the cascade whose label starts
    with `under`, when given). Fails the test when there is none."""
    inside = under is None
    base = None
    for d, lab, st, mm, i in menu_entries(m):
        if under is not None:
            if mm.type(i) == 'cascade' and lab.startswith(under):
                inside, base = True, d
                continue
            if inside and base is not None and d <= base:
                inside = False
        if inside and lab.startswith(text) and mm.type(i) != 'cascade':
            if st == 'disabled':
                raise Failed(f'menu entry {lab!r} is disabled')
            mm.invoke(i)
            pump()
            return lab
    raise Failed(f'no menu entry {text!r}' + (f' under {under!r}' if under else '') + f' in {menu_labels(m)}')


def status_text():
    try:
        return str(G.app.status.cget('text'))
    except Exception:
        return ''


# ---- fresh files inside the running application
def reset():
    """Puts the pristine sample files back into the application's save folder (new copies, backups removed) and
    makes every window read them again: each destructive GUI test starts from the original bytes."""
    app = G.app
    src = SRC_SAVES2 if G.sample == 2 else SRC_SAVES
    for name in os.listdir(G.save_dir):
        p = os.path.join(G.save_dir, name)
        if os.path.isfile(p) and not os.path.exists(os.path.join(src, name)):
            os.remove(p)
    for name in os.listdir(src):
        p = os.path.join(src, name)
        if os.path.isfile(p):
            shutil.copyfile(p, os.path.join(G.save_dir, name))
    app._undo = []
    app.backups_done.clear()                              # as in a new session: the first write makes a backup
    app._capy_clip = None
    app._capy_magicbuf = None
    app.selected = None
    G.menu = None
    del G.boxes[:]
    G.answers.clear()
    import mxl_tabs
    for name in list(mxl_tabs._state['pages']):           # extra tabs of an earlier test (Item stats, Item Editor)
        if name not in ('Stash', 'Character', 'Creator'):
            try:
                mxl_tabs._state['pages'][name].destroy()
            except Exception:
                pass
    app.load(app.path, keep_selection=False)
    try:
        app.notebook.select(0)
    except Exception:
        pass
    inv = getattr(app, 'inventory', None)
    if inv is not None:
        inv.merc.set(False)
        inv.reload()
    cw = mxl_tabs.built_owner('Character')
    if cw is not None:
        cw.merc.set(False) if hasattr(cw.merc, 'set') else None
        cw.reload()
    mxl_tabs._state['nb'].select(mxl_tabs._state['pages']['Stash'])
    pump(8)


# ---- pointer events (the handlers only read widget, x, y, x_root, y_root)
def ev(widget, x, y):
    import types
    return types.SimpleNamespace(widget=widget, x=int(x), y=int(y), x_root=widget.winfo_rootx() + int(x),
                                 y_root=widget.winfo_rooty() + int(y), num=3, state=0)


def stash_ev(page, cx, cy):
    """Event in the middle of stash cell (cx, cy), the stash page selected first."""
    app = G.app
    if app.page() != page:
        app.notebook.select(page)
        pump(4)
    return ev(app.canvas, (cx + .5) * app.cell, (cy + .5) * app.cell)


def stash_menu(page, cx, cy):
    """The right-click menu of the stash at a cell (captured, not shown)."""
    e = stash_ev(page, cx, cy)
    G.menu = None
    G.app._rc_menu(e)
    pump(2)
    return G.menu


def panel_ev(where):
    """Event on the Stash tab's character panel: ('slot', n) or ('inv', x, y)."""
    inv = G.app.inventory
    c = inv.cell
    if where[0] == 'slot':
        box = next(b for b in inv.visible_boxes() if inv.slot_of(b) == where[1])
        bx, by, w, h = inv.boxes[box]
        return ev(inv.doll, (bx + w / 2) * c, (by + h / 2) * c)
    return ev(inv.canvas, (where[1] + .5) * c, (where[2] + .5) * c)


def panel_menu(where):
    G.menu = None
    G.app.inventory.on_menu(panel_ev(where))
    pump(2)
    return G.menu


def chartab():
    import mxl_tabs
    return mxl_tabs.built_owner('Character')


def chartab_ev(where):
    """Event on the Character tab's equipment page: ('slot', n) or ('inv', x, y)."""
    import mxl_char_gui
    cw = chartab()
    c = cw.cell
    if where[0] == 'slot':
        box = next(b for b in cw.visible_boxes() if cw.slot_of(b) == where[1])
        bx, by, w, h = mxl_char_gui.DOLL[box]
        return ev(cw.doll, (bx + w / 2) * c, (by + h / 2) * c)
    return ev(cw.inv, (where[1] + .5) * c, (where[2] + .5) * c)


def chartab_menu(where):
    import mxl_rc_menu
    e = chartab_ev(where)
    G.menu = None
    mxl_rc_menu._char_menu(chartab(), e.widget, e)
    pump(2)
    return G.menu


def select_tab(name):
    import mxl_tabs
    mxl_tabs._state['nb'].select(mxl_tabs._state['pages'][name])
    pump(6)


def tab_names():
    import mxl_tabs
    nb = mxl_tabs._state['nb']
    return [nb.tab(t, 'text') for t in nb.tabs()]


# ---- item comparison
PLACE = ('x', 'y', 'panel', 'location', 'equipped')


def record(blob, data=None):
    """(decoded record without its place, bytes of the socketed items behind it)."""
    import mxl_creator
    data = data if data is not None else G.app.data
    rec, size = mxl_creator.decode_item(bytes(blob), data)
    return {k: v for k, v in rec.items() if k not in PLACE}, bytes(blob)[size:]


def same_item(a, b, data=None):
    """True when two item byte strings are the same item at possibly different places."""
    ra, ka = record(a, data)
    rb, kb = record(b, data)
    return ra == rb and len(ka) == len(kb)


def rec_of(blob, data=None):
    import mxl_creator
    return mxl_creator.decode_item(bytes(blob), data if data is not None else G.app.data)[0]
