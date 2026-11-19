"""A second opinion before every write, and "Compare with backup...".

Every character (.d2s), stash (.stash) and shared stash (.shared) file the editor writes goes through ONE
function of the collector: mxl_save.commit_file(path, content, verify, backup) - edit_stash, apply_edits,
move_item, transfer_item, mxl_stash_order, Character.save / rename, the import and the roll-backs of the
character windows all end there. install() wraps it (also where a module bound it by name): before the collector
writes anything, the NEW bytes are read in memory by `mxlsave`, the independent implementation of the save
formats (tools/mxlsave, shipped in the app as the package `mxlsave`):

- the structure parses, a character's size field and checksum are right, the parsed fields rebuild the same
  bytes, the item counts are plausible;
- when the file exists, a structural diff old -> new is computed, and its one-line summary is written to
  capybara.log after the write ("savecheck: XBone.d2s: stats strength 817->900; items +1 (Ring at inv 3,4); ...").

What happens when the new bytes fail the check depends on the setting "savecheck" of settings.json (or the
environment variable MXL_SAVECHECK):
  strict (default)  the write is refused (EditError: the caller shows it like any other refusal), nothing changes
  warn              the file is written; a warning is shown and logged, and the previous file is kept as an
                    extra backup <file>.bak-savecheck-<date> (not one of the collector's rotating backups)
  off               no check, no diff line
The collector's own verification runs as before in every mode. Two cases are never refused, only warned about:
bytes that were on the disk earlier in this session (a roll-back, "Restore this backup"), and a file whose
CURRENT content already fails the independent check (then this second reader cannot judge that file). An error
inside the check itself never stops a write either: it is logged and the write goes on.

mxl_char.copy_character writes its new file directly: it is checked right after (a refused copy is removed).

"Compare with backup..." (the "More" menu of the top bar) shows the same diff between a file and one of the
backups next to it (*.bak-*), and can put the backup back ("Restore this backup": the current file is first
kept as a new backup; the confirmation is asked in the window itself).

Backups (F10 of docs/review/save-safety.md): install() also replaces the collector's mxl_save.make_backup, which
kept ONE <file>.bak-<date>-<time> per file (each new backup deleted the older ones). The replacement makes the
same backup (same name, -2, -3... when the name exists) and keeps the newest N of that file (setting
"backups_keep" of settings.json, default 5, at least 1); only that file's dated backups are counted and removed
(<file>.bak-savecheck-*, .bak-before-restore-* and other files' backups are never touched).
"""
import functools
import glob
import hashlib
import os
import re
import shutil
import sys
import time

SETTING = 'savecheck'
KEEP_SETTING = 'backups_keep'
KEEP_DEFAULT = 5
MODES = ('strict', 'warn', 'off')
EXTRA_TAG = 'savecheck'
TEST_HOOK = None            # tests: function(path, content) -> content, applied before the check AND the write

_state = {'installed': False, 'tables': None, 'tables_key': None, 'parsed': {}, 'seen': {}, 'last': None}

try:
    from mxl_lang import T
except Exception:                                      # bare src/ (tests of the pure parts)
    def T(key, default, **fields):
        _ = key
        return default.format(**fields) if fields else default


def _log():
    try:
        import mxl_log
        return mxl_log.log
    except Exception:
        import logging
        return logging.getLogger('capybara')


def lib():
    """The mxlsave package: shipped next to the modules (AppImage) / in the exe's archive; from a source
    checkout it is tools/mxlsave."""
    try:
        import mxlsave
    except ImportError:
        tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')
        if not os.path.isdir(os.path.join(tools, 'mxlsave')):
            raise
        sys.path.append(tools)
        import mxlsave
    return mxlsave


def mode():
    v = os.environ.get('MXL_SAVECHECK')
    if not v:
        try:
            import settings
            v = settings.get(SETTING)
        except Exception:
            v = None
    v = str(v or '').strip().lower()
    return v if v in MODES else 'strict'


def set_mode(value):
    if value not in MODES:
        raise ValueError(value)
    import settings
    settings.put(SETTING, value)


def tables():
    """The game tables of the editor's data folder for mxlsave (reloaded when the data is installed again);
    None when there are none - the items are then not decoded."""
    try:
        import paths
        folder = paths.DATA_DIR
    except Exception:
        folder = os.path.join(os.environ.get('MXL_USER_DIR', ''), 'data')
    probe = os.path.join(folder, 'itemstatcost.bin')
    try:
        st = os.stat(probe)
        key = (folder, st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    if _state['tables_key'] != key:
        _state['tables'] = lib().Tables(folder)
        _state['tables_key'] = key
        _state['parsed'].clear()
    return _state['tables']


def kind_of(path):
    """'d2s' / 'stash' for the files this module looks at, else None."""
    name = os.path.basename(str(path)).lower()
    for ext, kind in (('.d2s', 'd2s'), ('.stash', 'stash'), ('.shared', 'stash')):
        if name.endswith(ext) or (ext + '.bak-') in name:
            return kind
    return None


def _digest(data):
    return hashlib.sha1(data).digest()


def _remember(path, data):
    """Bytes that were on the disk for this path during this session: writing them back is never refused."""
    s = _state['seen'].setdefault(os.path.abspath(path), [])
    d = _digest(data)
    if d not in s:
        s.append(d)
        del s[:-40]


class Result:
    """What examine() found. problems: why the new bytes are refused ([] = fine). changes: the structural diff
    (None when there is no old file or one side could not be read). summary: the line for the log."""

    def __init__(self):
        self.kind = None
        self.problems = []
        self.changes = None
        self.summary = ''
        self.ms = 0.0
        self.old_exists = False
        self.old_problems = []
        self.known = False          # the new bytes were on the disk before (roll-back / restore)
        self.items = None
        self.obj = None

    @property
    def ok(self):
        return not self.problems


def examine(path, content, old=None):
    """Independent check of `content` (the bytes about to be written to `path`) and diff against the file on
    the disk (or `old` bytes). Raises nothing for a bad file: see Result.problems."""
    import gc
    was = gc.isenabled()
    gc.disable()            # thousands of small objects for a few ms: a full collection in the middle of the
    try:                    # parse (the app holds a lot of live objects) doubled the time of some checks
        return _examine(path, content, old)
    finally:
        if was:
            gc.enable()


def _examine(path, content, old):
    t0 = time.perf_counter()
    m = lib()
    from mxlsave.check import check_bytes, count_items
    from mxlsave.diff import diff_objects, summary
    r = Result()
    r.kind = kind_of(path)
    content = bytes(content)
    tb = tables()
    key = os.path.abspath(path)
    if old is None:
        try:
            with open(path, 'rb') as f:
                old = f.read()
        except OSError:
            old = None
    r.old_exists = old is not None
    r.known = _digest(content) in _state['seen'].get(key, ())
    r.obj, r.problems = check_bytes(content, r.kind, tb)
    if r.obj is not None:
        r.items = count_items(r.obj)
    old_obj = None
    if old is not None:
        _remember(path, old)
        cached = _parsed_get(old, r.kind)
        if cached is not None:                  # the OLD side only: the new bytes are always checked above
            old_obj, r.old_problems = cached
        elif old == content:
            old_obj, r.old_problems = r.obj, list(r.problems)
        else:
            old_obj, r.old_problems = check_bytes(old, r.kind, tb)
            _parsed_put(old, r.kind, old_obj, r.old_problems)
    size = f'{len(content)} bytes' if old is None or len(old) == len(content) else f'{len(old)}->{len(content)} bytes'
    if r.obj is None:
        r.summary = f'not readable by the independent check; {size}'
    elif old is None:
        n = '' if r.items is None else f'{r.items} items, '
        r.summary = f'new file, {n}{size}'
    elif old_obj is None:
        r.summary = f'the previous file is not readable by the independent check; {size}'
    elif old == content:
        r.changes = []
        r.summary = f'identical bytes; {size}'
    else:
        r.changes = diff_objects(old_obj, r.obj, tb, old, content)
        r.summary = summary(r.changes, old_size=len(old), new_size=len(content))
    if tb is None:
        r.summary += ' (game tables not found: items not checked)'
    _ = m
    r.ms = (time.perf_counter() - t0) * 1000
    _state['last'] = r
    return r


PARSED_KEEP = 8


def _parsed_get(data, kind):
    """(obj, problems) of an earlier check of exactly these bytes (keyed by their hash, compared byte for byte),
    or None. Used for the OLD side of a write (the file on the disk, for the diff and the "already fails" rule):
    after a write it is the bytes just checked as new, after an undo / restore bytes checked earlier."""
    e = _state['parsed'].get((_digest(data), kind))
    if e is None or e[0] != data:
        return None
    return e[1], list(e[2])


def _parsed_put(data, kind, obj, problems):
    p = _state['parsed']
    k = (_digest(data), kind)
    p.pop(k, None)
    p[k] = (bytes(data), obj, list(problems))
    while len(p) > PARSED_KEEP:
        p.pop(next(iter(p)))


def _accepted(path, content, r):
    """After a successful write: the parsed new file is the next write's old side."""
    if r.obj is not None:
        _parsed_put(bytes(content), r.kind, r.obj, r.problems)
    _remember(path, bytes(content))


def extra_backup(path, tag=EXTRA_TAG):
    """Copy of the current file as <file>.bak-<tag>-<date>: outside the collector's backup rotation (which
    keeps one <file>.bak-<date>-<time> and deletes the older ones). Returns the copy, None without a file."""
    if not os.path.isfile(path):
        return None
    base = f'{path}.bak-{tag}-' + time.strftime('%Y%m%d-%H%M%S')
    bak, n = base, 1
    while os.path.exists(bak):
        n += 1
        bak = f'{base}-{n}'
    shutil.copy2(path, bak)
    return bak


def _warn_user(text):
    """A warning box once the write is over (never in the middle of it); logged by mxl_log either way."""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter._default_root
        if root is None:
            return
        root.after(50, lambda: messagebox.showwarning(T('sc.title', 'Save check'), text, parent=root))
    except Exception:
        pass


def backups_keep():
    """How many dated backups per file make_backup keeps (settings.json "backups_keep", default 5, at least 1)."""
    try:
        import settings
        v = settings.get(KEEP_SETTING)
    except Exception:
        v = None
    if v is None or v == '':
        return KEEP_DEFAULT
    try:
        return max(1, int(v))
    except (TypeError, ValueError):
        return KEEP_DEFAULT


def _dated(path):
    """The collector-style backups of path, oldest first: [(key, file)], key = (date-time, n)."""
    pat = re.compile(re.escape(os.path.basename(path)) + r'\.bak-(\d{8})-(\d{6})(?:-(\d+))?$')
    out = []
    for f in glob.glob(glob.escape(path) + '.bak-*'):
        m = pat.fullmatch(os.path.basename(f))
        if m and os.path.isfile(f):
            out.append(((m.group(1) + m.group(2), int(m.group(3) or 1)), f))
    out.sort()
    return out


def make_backup(path):
    """The collector's make_backup (same name: <path>.bak-<date>-<time>[-n]; returns it), keeping the newest
    backups_keep() of this file instead of one. The order is the date-time in the name (mtime is the copied
    file's own, copy2 keeps it)."""
    stamp = time.strftime('%Y%m%d-%H%M%S')
    bak = f'{path}.bak-{stamp}'
    n = 1
    while os.path.exists(bak):
        n += 1
        bak = f'{path}.bak-{stamp}-{n}'
    shutil.copy2(path, bak)
    keep = backups_keep()
    old = [f for _k, f in _dated(path) if f != bak]
    for f in old[:max(0, len(old) - (keep - 1))]:
        try:
            os.remove(f)
        except OSError as e:
            _log().warning('backup: old backup %s not removed: %s', os.path.basename(f), e)
    return bak


make_backup._capy_keep = True


def _edit_error():
    try:
        import mxl_save
        return mxl_save.EditError
    except Exception:
        return RuntimeError


RETRY_DELAYS = (0.15, 0.4, 0.8)      # PermissionError (Windows: antivirus / OneDrive / the game holding the file)


def _write(host, path, content, verify, backup):
    """The collector's write. It removes its temp file (<path>.tmp) when the write or the verification fails, but
    not when the backup or the final rename fails (disk full, the file locked by another program on Windows):
    then the old file is still in place and the temp file is removed here.
    A PermissionError (a short lock by a virus scanner or a sync client on Windows) is tried again a few times
    (about 1.4 s in all): every try is the whole safe write again, and the old file is untouched until the
    final rename succeeds."""
    tries = 0
    while True:
        try:
            return host(path, content, verify, backup)
        except PermissionError as e:
            _remove_tmp(path)
            if tries >= len(RETRY_DELAYS):
                raise
            _log().warning('savecheck: %s locked (%s), trying again', os.path.basename(str(path)), e)
            time.sleep(RETRY_DELAYS[tries])
            tries += 1
        except BaseException:
            _remove_tmp(path)
            raise


def _remove_tmp(path):
    tmp = str(path) + '.tmp'
    try:
        if os.path.isfile(tmp):
            os.remove(tmp)
    except OSError:
        pass


def _guard(host):
    @functools.wraps(host)
    def commit_file(path, content, verify, backup=True):
        m = mode()
        if m == 'off' or kind_of(path) is None:
            return _write(host, path, content, verify, backup)
        log = _log()
        name = os.path.basename(str(path))
        if TEST_HOOK is not None:
            content = TEST_HOOK(path, content)
        try:
            r = examine(path, content)
        except Exception as e:                       # a bug here must never cost the user a save
            log.exception('savecheck: the check itself failed for %s (%s) - written without it', name, e)
            return _write(host, path, content, verify, backup)
        if r.problems:
            why = '; '.join(r.problems)
            soft = None
            if r.known:
                soft = 'these bytes were on the disk before (roll-back / restore)'
            elif r.old_exists and r.old_problems:
                soft = 'the current file fails the same check, the independent reader cannot judge this file'
            if m == 'strict' and soft is None:
                log.error('savecheck REFUSED %s: %s | %s', name, why, r.summary)
                raise _edit_error()(T('sc.refused', 'The independent check refused this write, {file} was not '
                                      'changed:\n{why}\n\n(Setting "savecheck" in settings.json: strict / warn / '
                                      'off. Details: capybara.log)', file=name, why=why))
            log.warning('savecheck WARNING %s: %s | %s%s', name, why, r.summary, f' [{soft}]' if soft else '')
            if soft is None:
                try:
                    kept = extra_backup(path)
                except OSError as e:
                    kept = None
                    log.warning('savecheck: extra backup of %s failed: %s', name, e)
                if kept:
                    log.warning('savecheck: previous file kept as %s', kept)
                _warn_user(T('sc.warned', '{file} was written although the independent check does not accept it:\n'
                             '{why}\n\nThe previous file is kept as {backup}.', file=name, why=why,
                             backup=os.path.basename(kept) if kept else '-'))
        bak = _write(host, path, content, verify, backup)
        try:
            _accepted(path, content, r)
            log.info('savecheck: %s: %s [%.0f ms]', name, r.summary, r.ms)
        except Exception:
            pass
        return bak
    commit_file._capy_savecheck = True
    commit_file._capy_logged = True          # mxl_log.wrap_saves: already wraps the logging version, leave it
    return commit_file


def _guard_copy(host):
    """mxl_char.copy_character writes <new name>.d2s itself: checked right after, removed when refused."""
    @functools.wraps(host)
    def copy_character(path, new_name, data):
        dst = host(path, new_name, data)
        m = mode()
        if m == 'off':
            return dst
        log = _log()
        try:
            with open(dst, 'rb') as f:
                content = f.read()
            r = examine(dst, content, old=b'')
            r.summary = f'copy of {os.path.basename(path)}, ' + (f'{r.items} items, ' if r.items is not None else '') \
                        + f'{len(content)} bytes'
        except Exception as e:
            log.exception('savecheck: the check itself failed for %s (%s)', dst, e)
            return dst
        if r.problems:
            why = '; '.join(r.problems)
            if m == 'strict':
                folder, stem = os.path.dirname(dst), os.path.splitext(os.path.basename(dst))[0]
                for fn in os.listdir(folder):
                    if os.path.splitext(fn)[0] == stem:
                        try:
                            os.remove(os.path.join(folder, fn))
                        except OSError:
                            pass
                log.error('savecheck REFUSED %s: %s (the copy was removed)', os.path.basename(dst), why)
                raise _edit_error()(T('sc.refused_copy', 'The independent check refused the copy {file}, it was '
                                      'removed:\n{why}', file=os.path.basename(dst), why=why))
            log.warning('savecheck WARNING %s: %s', os.path.basename(dst), why)
            _warn_user(T('sc.warned_copy', '{file} was written although the independent check does not accept '
                         'it:\n{why}', file=os.path.basename(dst), why=why))
        log.info('savecheck: %s: %s [%.0f ms]', os.path.basename(dst), r.summary, r.ms)
        return dst
    copy_character._capy_savecheck = True
    return copy_character


def _warm():
    try:
        tb = tables()
        if tb is not None:
            tb.stat_name(0)
            tb.base_name('rin ')
            tb.skill_name(0)
            tb.monster_name(0)
    except Exception:
        pass


def _rebind(old, new, name):
    for mod in list(sys.modules.values()):
        try:
            if mod is not None and getattr(mod, name, None) is old:
                setattr(mod, name, new)
        except Exception:
            pass


def install():
    """Called at the end of mxl_creator_gui.run(), after every module that wraps or binds the writers."""
    log = _log()
    try:
        import mxl_save
        if not getattr(mxl_save.make_backup, '_capy_keep', False):
            current = mxl_save.make_backup
            mxl_save.make_backup = make_backup        # host commit_file looks it up at call time (global)
            _rebind(current, make_backup, 'make_backup')
    except Exception as e:
        log.error('backup rotation not installed: %s: %s', type(e).__name__, e)
    try:
        lib()
        import mxl_save
    except Exception as e:
        log.error('savecheck not installed: %s: %s', type(e).__name__, e)
        return
    if not getattr(mxl_save.commit_file, '_capy_savecheck', False):
        current = mxl_save.commit_file
        inner = getattr(current, '__wrapped__', None)        # the collector's own function under mxl_log's
        guard = _guard(current)
        mxl_save.commit_file = guard
        _rebind(current, guard, 'commit_file')
        if inner is not None:
            _rebind(inner, guard, 'commit_file')
    try:
        import mxl_char
        if not getattr(mxl_char.copy_character, '_capy_savecheck', False):
            current = mxl_char.copy_character
            guard = _guard_copy(current)
            mxl_char.copy_character = guard
            _rebind(current, guard, 'copy_character')
    except Exception as e:
        log.warning('savecheck: copy_character not covered: %s', e)
    if not _state['installed']:
        _state['installed'] = True
        try:
            import mxl_toolbar
            mxl_toolbar.add_entry(lambda: T('sc.menu', 'Compare with backup...'), open_compare)
        except Exception as e:
            log.warning('savecheck: no menu entry: %s', e)
        log.info('savecheck installed: mode %s', mode())
        try:                                     # tables and name strings read ahead: the first save is not slower
            import threading
            threading.Thread(target=_warm, name='savecheck-warm', daemon=True).start()
        except Exception:
            pass


# ------------------------------------------------------------------------------------------------ backups
def backups(path):
    """The backups next to a file (<file>.bak-*), newest first."""
    found = [p for p in glob.glob(glob.escape(path) + '.bak-*') if os.path.isfile(p)]
    return sorted(found, key=lambda p: (os.path.getmtime(p), p), reverse=True)


def compare(old_path, new_path):
    """(text of the diff old -> new, [notes]) for the compare window; the files are only read."""
    from mxlsave.check import check_bytes
    from mxlsave.diff import diff_objects, format_text
    tb = tables()
    kind = kind_of(new_path) or kind_of(old_path)
    sides = []
    notes = []
    for p in (old_path, new_path):
        with open(p, 'rb') as f:
            data = f.read()
        obj, problems = check_bytes(data, kind, tb)
        if problems:
            notes.append(T('sc.note_bad', '{file} is not accepted by the independent check: {why}',
                           file=os.path.basename(p), why='; '.join(problems)))
        sides.append((data, obj))
    if tb is None:
        notes.append(T('sc.note_tables', 'game tables not found: the items are not decoded'))
    (a, oa), (b, ob) = sides
    if oa is None or ob is None:
        return T('sc.unreadable', 'The files cannot be compared field by field ({a} / {b} bytes).', a=len(a),
                 b=len(b)), notes
    if a == b:
        return T('sc.same', 'The two files are identical ({n} bytes).', n=len(a)), notes
    return format_text(diff_objects(oa, ob, tb, a, b)), notes


def restore_backup(path, backup):
    """Puts `backup` back as `path`. The current file is first kept as a new backup (returned, None when there
    was no file); the write is the collector's (commit_file: same rules, logged, with the diff line)."""
    import mxl_save
    with open(backup, 'rb') as f:
        data = f.read()
    kept = None
    if os.path.isfile(path):
        with open(path, 'rb') as f:
            _remember(path, f.read())
        kept = extra_backup(path, 'before-restore')
    _remember(path, data)                    # the user asked for exactly these bytes: warned about, not refused
    _log().info('restore backup: %s -> %s (current file kept as %s)', backup, path, kept)
    mxl_save.commit_file(path, data, lambda tmp: None, False)
    return kept


def _files_with_backups(app):
    """Save files to offer: the open character and stash first, then every file of the save folder that has
    a backup."""
    out = []
    for get in (getattr(app, 'character_file', None), getattr(app, 'view_path', None)):
        try:
            p = get() if get else None
        except Exception:
            p = None
        if p and os.path.isfile(p) and p not in out:
            out.append(p)
    p = getattr(app, 'path', None)
    if p and os.path.isfile(p) and p not in out:
        out.append(p)
    folder = getattr(app, 'save_dir', None)
    if folder and os.path.isdir(folder):
        for fn in sorted(os.listdir(folder), key=str.lower):
            full = os.path.join(folder, fn)
            if '.bak-' not in fn and kind_of(fn) and full not in out and backups(full):
                out.append(full)
    return out


def _describe_file(p):
    try:
        st = os.stat(p)
        return f'{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}, {st.st_size} bytes'
    except OSError:
        return '?'


class CompareWindow:
    """File + backup pickers, the diff backup -> current file as text, "Restore this backup" with the
    confirmation in the window."""

    def __init__(self, app):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.app = app
        self.files = _files_with_backups(app)
        self.baks = []
        self.win = win = tk.Toplevel(app.root)
        win.title(T('sc.win_title', 'Compare with backup'))
        win.geometry('900x560')
        try:
            from mxl_creator_gui import clamp_window
            win.after_idle(lambda: clamp_window(win, size=(900, 560)))
        except Exception:
            pass
        dark = True
        try:
            import mxl_d2_theme as D
            dark = D.dark()
            bg, fg, head, dim = (D.FIELD, D.GOLD, D.GOLD_HI, D.DIM) if dark else ('#ffffff', '#000000', '#000000',
                                                                                 '#606060')
        except Exception:
            bg, fg, head, dim = '#141112', '#c7b377', '#f2dc9c', '#6a624f'
        top = ttk.Frame(win)
        top.pack(side='top', fill='x', padx=4, pady=(4, 2))
        ttk.Label(top, text=T('sc.file', 'File:')).pack(side='left')
        self.file_box = ttk.Combobox(top, state='readonly', width=22,
                                     values=[os.path.basename(p) for p in self.files])
        self.file_box.pack(side='left', padx=(3, 8))
        ttk.Label(top, text=T('sc.backup', 'Backup:')).pack(side='left')
        self.bak_box = ttk.Combobox(top, state='readonly', width=30)
        self.bak_box.pack(side='left', padx=(3, 0), fill='x', expand=True)
        self.bottom = ttk.Frame(win)
        self.bottom.pack(side='bottom', fill='x', padx=4, pady=(2, 4))
        self.status = ttk.Label(self.bottom, text='', anchor='w')
        self.btn_close = ttk.Button(self.bottom, text=T('cr.btn.close', 'Close'), command=win.destroy)
        self.btn_restore = ttk.Button(self.bottom, text=T('sc.restore', 'Restore this backup'), command=self.ask)
        self.btn_no = ttk.Button(self.bottom, text=T('sc.cancel', 'Cancel'), command=self.normal_row)
        self.btn_yes = ttk.Button(self.bottom, text=T('sc.yes', 'Yes, restore'), command=self.restore)
        body = ttk.Frame(win)
        body.pack(side='top', fill='both', expand=True, padx=4)
        self.text = tk.Text(body, wrap='none', bg=bg, fg=fg, insertbackground=fg, bd=0, padx=6, pady=4,
                            highlightthickness=0, width=40, height=8)
        sy = ttk.Scrollbar(body, orient='vertical', command=self.text.yview)
        sx = ttk.Scrollbar(body, orient='horizontal', command=self.text.xview)
        self.text.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side='right', fill='y')
        sx.pack(side='bottom', fill='x')
        self.text.pack(side='left', fill='both', expand=True)
        try:
            import mxl_he_theme
            mxl_he_theme.exempt(self.text)          # keeps its own colours in both looks
        except Exception:
            pass
        self.text.tag_configure('head', foreground=head, font=self._bold())
        self.text.tag_configure('note', foreground='#e0a040' if dark else '#a05000')
        self.text.tag_configure('add', foreground='#7fc97f' if dark else '#006000')
        self.text.tag_configure('del', foreground='#e07060' if dark else '#a00000')
        self.text.tag_configure('dim', foreground=dim)
        self.file_box.bind('<<ComboboxSelected>>', lambda _e: self.pick_file())
        self.bak_box.bind('<<ComboboxSelected>>', lambda _e: self.show())
        win.bind('<Escape>', lambda _e: win.destroy())
        self.normal_row()
        if self.files:
            self.file_box.current(0)
            for i, p in enumerate(self.files):          # the first file that has a backup
                if backups(p):
                    self.file_box.current(i)
                    break
        self.pick_file()

    def _bold(self):
        from tkinter import font as tkfont
        try:
            f = tkfont.Font(font=self.text.cget('font'))
            f.configure(weight='bold')
            self._font = f
            return f
        except Exception:
            return None

    # ------------------------------------------------------------------ rows of buttons
    def normal_row(self):
        for w in (self.btn_yes, self.btn_no, self.btn_close, self.btn_restore, self.status):
            w.pack_forget()
        self.btn_close.pack(side='right')
        self.btn_restore.pack(side='right', padx=(0, 4))
        self.status.pack(side='left', fill='x', expand=True)
        self.btn_restore.state(['!disabled'] if self.current()[1] else ['disabled'])

    def ask(self):
        path, bak = self.current()
        if not bak:
            return
        for w in (self.btn_close, self.btn_restore, self.status):
            w.pack_forget()
        self.btn_no.pack(side='right')
        self.btn_yes.pack(side='right', padx=(0, 4))
        self.status.configure(text=T('sc.confirm', 'Replace {file} with this backup? The current file is kept as '
                                     'a new backup.', file=os.path.basename(path)))
        self.status.pack(side='left', fill='x', expand=True)

    # ------------------------------------------------------------------ content
    def current(self):
        def index(box, n):
            try:                                  # Tk 9 answers '' when nothing is selected
                i = int(box.current())
            except (ValueError, TypeError, self.tk.TclError):
                return -1
            return i if 0 <= i < n else -1
        i, j = index(self.file_box, len(self.files)), index(self.bak_box, len(self.baks))
        return (self.files[i] if i >= 0 else None), (self.baks[j] if j >= 0 else None)

    def pick_file(self, keep=None):
        path = self.current()[0]
        self.baks = backups(path) if path else []
        n = len(os.path.basename(path)) + 1 if path else 0
        self.bak_box.configure(values=[f'{os.path.basename(b)[n:]}   ({_describe_file(b)})' for b in self.baks])
        self.bak_box.set('')
        if self.baks:
            self.bak_box.current(self.baks.index(keep) if keep in self.baks else 0)
        self.show()

    def _put(self, text, tag=None):
        self.text.insert('end', text + '\n', tag or ())

    def show(self):
        self.normal_row()
        path, bak = self.current()
        t = self.text
        t.configure(state='normal')
        t.delete('1.0', 'end')
        self.status.configure(text='')
        if not path:
            self._put(T('sc.no_file', 'No character or stash file is open.'), 'dim')
        elif not bak:
            self._put(T('sc.no_backup', '{file} has no backup (*.bak-*) next to it yet. A backup is made the first '
                        'time a file is written in a session.', file=os.path.basename(path)), 'dim')
        else:
            self._put(T('sc.from', 'Backup:   {file}   ({info})', file=os.path.basename(bak),
                        info=_describe_file(bak)), 'dim')
            self._put(T('sc.to', 'Current:  {file}   ({info})', file=os.path.basename(path),
                        info=_describe_file(path)), 'dim')
            self._put(T('sc.direction', 'Changes from the backup to the current file:'), 'dim')
            self._put('')
            try:
                body, notes = compare(bak, path)
            except Exception as e:
                body, notes = f'{type(e).__name__}: {e}', []
                _log().exception('compare with backup failed: %s / %s', bak, path)
            for n in notes:
                self._put(n, 'note')
            for line in body.split('\n'):
                s = line.lstrip()
                tag = 'head' if line and not line.startswith(' ') else (
                    'add' if s.startswith('+') else 'del' if s.startswith('- ') or s.startswith('-stat') else None)
                self._put(line, tag)
        t.configure(state='disabled')
        self.btn_restore.state(['!disabled'] if bak else ['disabled'])

    def restore(self):
        path, bak = self.current()
        if not path or not bak:
            return
        try:
            kept = restore_backup(path, bak)
        except Exception as e:
            self.normal_row()
            self.status.configure(text=T('sc.restore_failed', 'Not restored: {error}', error=str(e).split('\n')[0]))
            _log().error('restore backup FAILED: %s -> %s: %s: %s', bak, path, type(e).__name__, e)
            return
        try:
            if os.path.abspath(getattr(self.app, 'path', '') or '') == os.path.abspath(path):
                self.app.reload(True)                # the open stash; a character window follows the file watch
        except Exception:
            pass
        self.pick_file(keep=bak)
        self.status.configure(text=T('sc.restored', '{file} restored. The file it replaced is kept as {backup}.',
                                     file=os.path.basename(path), backup=os.path.basename(kept) if kept else '-'))


def open_compare(app):
    try:
        w = getattr(app, '_savecheck_win', None)
        if w is not None and w.win.winfo_exists():
            w.win.lift()
            w.files = _files_with_backups(app)
            w.file_box.configure(values=[os.path.basename(p) for p in w.files])
            w.pick_file()
            return w
    except Exception:
        pass
    app._savecheck_win = CompareWindow(app)
    return app._savecheck_win
