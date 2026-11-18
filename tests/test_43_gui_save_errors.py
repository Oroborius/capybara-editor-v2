"""A character file the system refuses to replace (Windows: read-only, or held open by another program) during
"To stash" from the character, in both places that have it: the Stash tab's panel and the Character tab.

Before: the OSError escaped Character.save; in the windowed exe that is a line in capybara.log and nothing on the
screen, and on the Character tab the stash had already been written: the item was in both files. Now: an error box,
the stash put back as it was, the character file unchanged, no temporary file left. When putting the stash back
fails too, the box says so (the item may be in both files) and the log has the traceback."""
import os

import capytest as T

MODE = 'gui'
RESET = True
ALLOW_ERRORS = True          # the error boxes and the logged failed saves are the point: checked by hand below
VARIANTS = {'panel': {'CAPY_HOLDER': 'panel'}, 'tab': {'CAPY_HOLDER': 'tab'}}
G = T.G
HOLDER = os.environ.get('CAPY_HOLDER', 'panel')
SLOT = 1


def view():
    if HOLDER == 'tab':
        cw = T.chartab()
        if cw is None:
            raise T.Failed('no Character tab')
        T.select_tab('Character')
        if cw.tab.get() != 'inventory':
            cw.tab.set('inventory')
            cw.show_tab()
    T.pump(6)


def small_equipped():
    import mxl_char
    import mxl_creator
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    for e in ch.entries(False):
        it = e.it
        b = G.app.data.base(it['code'])
        try:
            rec = T.rec_of(e.blob)
        except Exception:
            continue
        if it['location'] == SLOT and not rec['flags'] & mxl_creator.FLAG_SIMPLE and b.size[0] * b.size[1] <= 4:
            return ('slot', it['equipped'])
    T.skip('the sample character has no small equipped item')


class Refuse:
    """os.replace refuses the character file always, and the stash file from its `stash_from`-th write on."""

    def __init__(self, stash_from=None):
        self.stash_from, self.stash_writes = stash_from, 0

    def __enter__(self):
        self.real = os.replace

        def replace(src, dst, *a, **k):
            d = str(dst).lower()
            if d.endswith('.d2s'):
                raise PermissionError(13, 'Access is denied (test)', str(dst))
            if d.endswith(('.stash', '.shared')):
                self.stash_writes += 1
                if self.stash_from is not None and self.stash_writes >= self.stash_from:
                    raise PermissionError(13, 'Access is denied (test, stash)', str(dst))
            return self.real(src, dst, *a, **k)
        os.replace = replace
        return self

    def __exit__(self, *exc):
        os.replace = self.real


def run(stash_from):
    where = small_equipped()
    char_path, stash_path = G.app.character_file(), G.app.path
    char0, stash0 = T.read(char_path), T.read(stash_path)
    view()
    m = T.mark()
    menu = T.chartab_menu(where) if HOLDER == 'tab' else T.panel_menu(where)
    with Refuse(stash_from):
        T.invoke(menu, 'To stash')
        T.pump(8)
    T.pump(4)
    errs = T.errors_since(m)
    T.check(not [e for e in errs if e.startswith('stderr')], f'traceback instead of a message: {errs}')
    try:
        with open(os.path.join(G.user_dir, 'capybara.log'), encoding='utf-8', errors='replace') as f:
            f.seek(m[1])
            log = f.read()
    except OSError:
        log = ''
    T.check('error in a window action' not in log, 'the failure only reached the log (uncaught in a window action)')
    boxes = [b for b in G.boxes if b[0] == 'showerror']
    T.check(boxes, 'no error box: the user is not told that nothing was saved')
    T.eq(T.read(char_path), char0, 'character file after the refused write')
    T.check(not os.path.exists(char_path + '.tmp'), 'the writer left <character>.d2s.tmp behind')
    return stash0, boxes, log


@T.test
def to_stash_character_file_refused():
    stash0, _boxes, _log = run(None)
    T.eq(T.read(G.app.path), stash0, 'stash file: put back as it was')


@T.test
def to_stash_roll_back_refused_too():
    _stash0, boxes, log = run(2)            # the stash's first write goes through, putting it back is refused
    text = ' '.join(b[2] for b in boxes)
    T.check('back as it was failed too' in text, f'the box does not say the roll-back failed: {text[:300]!r}')
    T.check('roll-back of' in log, 'the failed roll-back is not in capybara.log')


T.main(globals())
