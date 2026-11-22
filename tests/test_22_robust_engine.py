"""Robustness of the write paths outside the happy path (docs/review/robustness.md): a file the system refuses to
replace (Windows: read-only, held open by another program), a copy under a name the game refuses or that is taken
by left-over files, the undo stack when recording fails, two threads writing the same art cache file, a cache file
that cannot be written, and the Linux launcher's save-folder search."""
import os
import threading

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')


class _ReplaceRefused:
    """os.replace refuses targets ending in `suffix` (as Windows does for a file another program holds open)."""

    def __init__(self, suffix):
        self.suffix, self.calls = suffix, 0

    def __enter__(self):
        self.real = os.replace

        def replace(src, dst, *a, **k):
            if str(dst).lower().endswith(self.suffix):
                self.calls += 1
                raise PermissionError(13, 'Access is denied (test)', str(dst))
            return self.real(src, dst, *a, **k)
        os.replace = replace
        return self

    def __exit__(self, *exc):
        os.replace = self.real


@T.test
def character_save_refused_by_the_system_is_a_char_error():
    """Character.save (mxl_free's version, the one installed) turns an OSError of the safe writer into CharError,
    which every window shows in a box (an OSError only reached the log: nothing visible in the windowed exe), and
    removes the writer's left-over <file>.d2s.tmp. The file stays as it was."""
    E = T.engine()
    folder = T.fresh_saves()
    path = next(os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith('.d2s'))
    raw = T.read(path)
    c = E.MC.Character(path, E.data)
    c.set_field('gold', (c.field('gold') or 0) // 2 + 1)
    with _ReplaceRefused('.d2s') as r:
        try:
            c.save(backup=False)
            T.check(False, 'the save went through although the rename was refused')
        except E.MC.CharError as e:
            T.check('Access is denied' in str(e), f'the message names the system error: {e}')
        except OSError as e:
            T.check(False, f'an OSError escaped Character.save: {e!r}')
    T.check(r.calls >= 1, 'the refused rename was never attempted')
    T.eq(T.read(path), raw, 'the character file after a refused write')
    T.check(not os.path.exists(path + '.tmp'), 'the writer left its temporary file behind')


@T.test
def copy_character_name_rule_and_taken_names():
    """copy_character applies the game's name rule (A-Z, one - or _) and refuses a name any file of the copy would
    take, without regard to case: a non-Latin name raised UnicodeEncodeError (no box), 'Jöhn' made a save the game
    refuses, and a left-over <name>.stash was silently overwritten."""
    E = T.engine()
    folder = T.fresh_saves()
    path = next(os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith('.d2s'))
    before = {f: T.read(os.path.join(folder, f)) for f in os.listdir(folder)
              if os.path.isfile(os.path.join(folder, f))}
    for bad in ('Жора', 'Jöhn', 'A--b', '-Abc', 'x'):
        try:
            E.MC.copy_character(path, bad, E.data)
            T.check(False, f'copy as {bad!r} was accepted')
        except E.MC.CharError:
            pass
        except Exception as e:
            T.check(False, f'copy as {bad!r}: {type(e).__name__} instead of CharError: {e}')
    orphan = os.path.join(folder, 'leftover.stash')
    with open(orphan, 'wb') as f:
        f.write(b'not a stash of the copy')
    try:
        E.MC.copy_character(path, 'Leftover', E.data)
        T.check(False, 'copy over a left-over leftover.stash was accepted')
    except E.MC.CharError:
        pass
    T.eq(T.read(orphan), b'not a stash of the copy', 'the left-over stash file')
    now = {f: T.read(os.path.join(folder, f)) for f in os.listdir(folder)
           if f != "leftover.stash" and os.path.isfile(os.path.join(folder, f))}
    T.eq(now, before, 'the save folder after the refused copies')
    dst = E.MC.copy_character(path, 'Capy_Copy', E.data)
    T.check(os.path.isfile(dst), 'a valid copy was not made')
    c = E.MC.Character(dst, E.data)
    T.eq(c.name, 'Capy_Copy', 'name in the copied header')


@T.test
def undo_record_failure_keeps_the_previous_action():
    """A delete whose undo record cannot be made (the stash cannot be read) must not throw away the PREVIOUS
    action's undo entry (record() popped the stack on its own failure)."""
    T.engine()
    import types
    import mxl_undo
    prev = dict(kind='create', spots=[(0, 0, 0)])
    app = types.SimpleNamespace(_undo=[prev], path=os.path.join(T.tmp(), 'no-such.stash'))
    ok = mxl_undo.record(app, 'delete', item={'_offset': 0, 'page': 0}, page=0, x=0, y=0, name='x')
    T.eq(ok, False, 'record() result for an action it could not record')
    T.eq(app._undo, [prev], 'undo stack after a failed record')


@T.test
def undo_of_an_unreadable_stash_says_so():
    """undo() on a stash the reader refuses reported "Nothing to undo" (every exception was swallowed into None)."""
    E = T.engine()
    import types
    import mxl_undo
    bad = os.path.join(T.tmp(), 'broken.stash')
    with open(bad, 'wb') as f:
        f.write(b'\x00garbage, not a stash' * 3)
    op = dict(kind='delete', page=0, x=0, y=0, blob=b'', name='thing')
    app = types.SimpleNamespace(_undo=[op], path=bad, data=E.data, needs_backup=lambda p: False,
                                backup_made=lambda p, b: None)
    msg = mxl_undo.undo(app)
    T.check(msg is not None and 'fail' in msg.lower(), f'undo message for an unreadable stash: {msg!r}')


@T.test
def art_cache_same_picture_from_two_threads():
    """The art warm-up thread and the main thread can build the same cached picture at once: they shared one
    temporary file name (<file>.<pid>.tmp), wrote into each other's file and one rename failed."""
    T.engine()
    import mxl_d2look_art as A
    root = os.path.join(T.tmp(), 'artcache-threads')
    nogame = os.path.join(T.tmp(), 'nogame')
    os.makedirs(nogame, exist_ok=True)
    art = A.Art(nogame, A.THEMES[0], root)
    w = h = 64
    rgba = bytes([200, 100, 50, 255]) * (w * h)
    start = threading.Barrier(8)
    errors = []

    def build():
        return w, h, bytearray(rgba)

    def run(n):
        try:
            start.wait()
            for i in range(6):
                p = art._cached(f'same-{i}', build)
                # the next round starts from no file again (both threads build it anew)
                start.wait()
                if n == 0:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                start.wait()
        except Exception as e:
            errors.append(f'{type(e).__name__}: {e}')
            try:
                start.abort()
            except Exception:
                pass
    ths = [threading.Thread(target=run, args=(n,)) for n in range(8)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(60)
    T.eq(errors[:3], [], 'errors of threads building the same picture')
    p = art._cached('same-final', build)
    from PIL import Image
    with Image.open(p) as im:
        T.eq(im.size, (w, h), 'size of the cached picture')
    left = [f for f in os.listdir(art.cache) if f.endswith('.tmp')]
    T.eq(left, [], 'temporary files left in the art cache')


@T.test
def disk_cache_unwritable_value_leaves_no_temporary_file():
    """mxl_diskcache.save of a value JSON cannot hold fails quietly (False) and leaves no <name>.json.<pid>.tmp."""
    T.engine()
    import mxl_diskcache
    import paths
    folder = os.path.join(paths.USER_DIR, 'cache')
    T.eq(mxl_diskcache.save('robust-test', 'k', {'x': object()}), False, 'save of an unwritable value')
    left = [f for f in os.listdir(folder) if f.startswith('robust-test')] if os.path.isdir(folder) else []
    T.eq(left, [], 'files left by the failed cache write')
    T.eq(mxl_diskcache.save('robust-test', 'k', [1, 2]), True, 'save of a plain value')
    T.eq(mxl_diskcache.load('robust-test', 'k'), [1, 2], 'value read back')


@T.test
def launcher_save_dir_search():
    """find_save_dir: a home folder with [ ] in its name (a glob pattern otherwise), the Flatpak Steam prefix; a
    prefix found by the older patterns (~/.wine) still wins over the added ones."""
    T.engine()
    import importlib
    home = os.path.join(T.tmp(), 'home [x] y')
    rel = os.path.join('drive_c', 'users', 'steamuser', 'AppData', 'Roaming', 'MedianXL', 'save')
    flat = os.path.join(home, '.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata/1/pfx', rel)
    os.makedirs(flat)
    old = {k: os.environ.get(k) for k in ('HOME', 'WINEPREFIX')}
    os.environ['HOME'] = home
    os.environ.pop('WINEPREFIX', None)
    try:
        import capybara_editor as L
        importlib.reload(L)
        T.eq(L.find_save_dir(), flat, 'save folder in a Flatpak Steam prefix, [ ] in the home path')
        wine = os.path.join(home, '.wine', rel)
        os.makedirs(wine)
        T.eq(L.find_save_dir(), wine, '~/.wine still first')
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@T.test
def median_header_bytes_restored_on_save():
    """A character Median XL refused ("bad data") comes back from the game with header 0x29 / 0x2A zeroed (every
    Median save has 0x10 0x5F there): building it in the Median profile puts them back; a normal save keeps its bytes."""
    E = T.engine()
    import glob
    path = sorted(glob.glob(os.path.join(T.fresh_saves(1), '*.d2s')))[0]
    raw = T.read(path)
    T.eq((raw[0x29], raw[0x2A]), (0x10, 0x5F), 'fixture header bytes')
    c = E.MC.Character(path, E.data)
    T.eq(bytes(c.build()), raw, 'a normal save rebuilds byte for byte')
    c.head[0x29] = c.head[0x2A] = 0
    out = bytes(c.build())
    T.eq((out[0x29], out[0x2A]), (0x10, 0x5F), 'zeroed bytes restored')
    T.eq(out[0x2B:], raw[0x2B:], 'the rest unchanged')


T.main(globals())
