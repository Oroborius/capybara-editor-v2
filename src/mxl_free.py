"""Lets this Capybara Editor build work while the game is open (personal edit: "no complaining" mode).

The collector's safe writer (mxl_save) refuses to write while the game is running (check_game_closed
raises before edit_stash / commit_file do anything) and the character editor refuses to write a character
whose file changed on disk since it was read (mxl_char.Character.save). This build lifts both:

- mxl_save.check_game_closed and every function of mxl_save whose name is about the game running are
  replaced by a no-op (also in every module that bound them by name, like mxl_log.wrap_saves does for the
  writers), so the Item Collector's own code passes the check too;
- Character.save keeps only the write + verify + backup part: a file that changed on disk is simply
  overwritten (the game cannot hold the file open, writes happen on save & exit; a game that saved in the
  meantime is logged as a warning in capybara.log instead of an error box).

What stays on purpose: the files are still verified after writing, backups are still made, and values that
the save format cannot hold are still refused (a broken item would corrupt the file).

install() is called from mxl_creator_gui.run(), right after mxl_log.install(). Every step is wrapped so a
collector build that does not have the expected names cannot be broken by this module."""
import sys

GAME_CHECK_NAMES = ('check_game_closed', 'game_closed', 'is_game_running', 'game_is_running')


def _noop(*_a, **_k):
    """The game-closed / game-running check that always passes."""


def _free_check(name, original):
    def free(*a, **k):
        return None
    free.__name__ = name
    free._capy_freed = True
    free.original = original
    return free


def _rebind_everywhere(original, replacement):
    """Same idea as mxl_log.wrap_saves: modules that did `from mxl_save import <name>` keep their own
    binding, so every module that still holds the original function gets the freed one."""
    for name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        try:
            for attr, value in list(vars(mod).items()):
                if value is original:
                    setattr(mod, attr, replacement)
        except Exception:
            pass


def _free_game_checks():
    """Every check of mxl_save that refuses work while the game runs becomes a no-op."""
    try:
        import mxl_save
    except Exception:
        return
    replaced = []
    for name in list(vars(mxl_save)):
        original = getattr(mxl_save, name, None)
        known = name in GAME_CHECK_NAMES or (name.startswith('check_') and 'game' in name and 'collision' not in name)
        if not known or not callable(original) or isinstance(original, type):
            continue
        if getattr(original, '_capy_freed', False):
            continue
        free = _free_check(name, original)
        setattr(mxl_save, name, free)
        _rebind_everywhere(original, free)     # mxl_save's own namespace included (its functions call <name> bare)
        replaced.append(name)
    if replaced:
        print('mxl_free: game-closed checks removed:', ', '.join(replaced))


def _free_character_save():
    """mxl_char.Character.save without the "file changed on disk since it was read" refusal: overwrite
    (with backup and verify, as always) and log the overwritten change as a warning."""
    try:
        import mxl_char
    except Exception:
        return
    try:
        from mxl_lang import T
    except Exception:
        def T(key, text, **k):
            _ = key
            return text.format(**k) if k else text
    log = None
    try:
        import mxl_log
        log = mxl_log.log
    except Exception:
        pass

    def save(self, backup=True):
        from mxl_save import commit_file, load_character, EditError
        content = self.build()
        import mxl_legit                      # Legit mode: nothing impossible is written (raises CharError)
        self.legit_warnings = mxl_legit.guard_character(content)
        n_items = len(self.items)
        n_merc = None if self.merc_items is None else len(self.merc_items)

        def verify(tmp):
            try:
                c = mxl_char.Character(tmp, self.data)
                load_character(tmp, self.data)
            except Exception as e:
                raise EditError(T('ch.err.verify', 'check after writing failed: {error}', error=e))
            if len(c.items) != n_items or (None if c.merc_items is None else len(c.merc_items)) != n_merc:
                raise EditError(T('ch.err.verify_count', 'check after writing failed: item count'))
        try:
            with open(self.path, 'rb') as f:
                on_disk = f.read()
        except OSError:
            on_disk = None
        if on_disk is not None and on_disk != self.raw:
            # the file changed on disk (the game saved & exited, another editor...): overwrite anyway,
            # the backup keeps what was there
            _log(log, 'character file changed on disk since it was read - written anyway (mxl_free): %s',
                 self.path)
        ro = mxl_char.is_read_only(self.path)      # a read-only mock clone: written, then read-only again
        if ro:
            mxl_char.set_read_only(self.path, False)
        try:
            bak = commit_file(self.path, content, verify, backup)
        except OSError as e:          # held open / disk full: a CharError the windows show in a box
            raise mxl_char.write_error(self.path, e)
        finally:
            if ro:
                mxl_char.set_read_only(self.path, True)
        self.raw = content
        self.parse(content)
        return bak

    mxl_char.Character.save = save
    print('mxl_free: mxl_char.Character.save no longer refuses a file that changed on disk')


def _log(log, msg, *a):
    """mxl_log.log (the windowed exe has no console: its print() lines are logged) or print()."""
    try:
        if log is not None:
            log.log(30, msg, *a)          # WARNING level
        else:
            print(msg % a)
    except Exception:
        print(msg % a)


def install():
    try:
        import mxl_log
        log = mxl_log.log
        _r = log.info
    except Exception:
        _r = print
    try:
        _free_game_checks()
        _free_character_save()
        _r('mxl_free installed: the editor can run while the game is open')
    except Exception as err:
        try:
            print('mxl_free could not be installed: %r' % err)
        except Exception:
            pass
    try:
        import mxl_follow
        mxl_follow.install()
    except Exception as err:
        print('mxl_follow could not be installed: %r' % err)
