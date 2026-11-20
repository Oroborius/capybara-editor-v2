"""Character in a game (mxl_ingame): a Game.exe holding one of the character's files open = in game; the game at its
menu (holding no file of the character, or only the shared stash) or another program holding the files = not.
The game is simulated by a holder process: bash opens the files and execs `sleep` under the argv[0] a Wine
Game.exe has (C:\\...\\Game.exe), so the real /proc reader is tested. In game: a write of the character file is read
again on the next poll with a status note, the status bar warns, To stash asks first (No = nothing written).
Not in game: none of it (today's behaviour)."""
import os
import shutil
import subprocess
import time

import capytest as T

MODE = 'gui'
RESET = True
ALLOW_ERRORS = True
# the stand-in "Game.exe" holds the files; the real game's memory (if one runs on this machine) is not read here
VARIANTS = {'d2': {'MXL_THEME': 'd2', 'MXL_INGAME_MEMORY': '0'}, 'he': {'MXL_THEME': 'he', 'MXL_INGAME_MEMORY': '0'}}
G = T.G


def hold(*names, exe='C:\\games\\median-xl\\Game.exe'):
    """A process named exe holding the save folder's files names open (read-only, as fds 3, 4, ...)."""
    opens = ' '.join(f'{3 + i}<"${i + 1}"' for i in range(len(names)))
    p = subprocess.Popen(['bash', '-c', f'exec {opens}; exec -a "{exe}" sleep 600', '_']
                         + [os.path.join(G.save_dir, n) for n in names])
    time.sleep(0.3)
    import mxl_ingame
    mxl_ingame.clear()
    return p


def stop(p):
    p.kill()
    p.wait()
    import mxl_ingame
    mxl_ingame.clear()


def game_save():
    """What the game's save looks like: the character file rewritten IN PLACE (same inode) with other valid bytes
    (one inventory item less). Returns the new bytes."""
    import mxl_char
    import mxl_ingame
    path = G.app.character_file()
    work = os.path.join(T.tmp(), 'gamesave')
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    copy = os.path.join(work, os.path.basename(path))
    shutil.copyfile(path, copy)
    ch = mxl_char.Character(copy, G.app.data)
    e = next(x for x in ch.entries(False) if x.it['location'] != 1)
    ch.remove(e, False)
    ch.save(backup=False)
    mxl_ingame._own.pop(os.path.abspath(copy), None)
    new = T.read(copy)
    T.check(new != T.read(path), 'the simulated save changes nothing')
    time.sleep(0.02)
    with open(path, 'r+b') as f:
        f.write(new)
        f.truncate()
    return new


def warning():
    lbl = getattr(G.app, '_ig_label', None)
    return str(lbl.cget('text')) if lbl is not None and lbl.winfo_manager() else ''


@T.test
def in_game_only_when_game_exe_holds_the_characters_files():
    import mxl_ingame as M
    M.clear()
    T.eq(M.in_game(G.save_dir), set(), 'nothing running')
    p = hold('_sharedstash.shared')                     # the menu: the game holds no file of the character
    try:
        T.eq(M.in_game(G.save_dir), set(), 'Game.exe holding the shared stash only')
    finally:
        stop(p)
    p = hold('XBone.d2s', exe='/usr/bin/someeditor')    # another program
    try:
        T.eq(M.in_game(G.save_dir), set(), 'another program holding the .d2s')
    finally:
        stop(p)
    for name in ('XBone.d2s', 'XBone.key', 'XBone.ma0'):
        p = hold(name)
        try:
            t = time.perf_counter()
            got = M.in_game(G.save_dir)                 # cold: walks /proc for the processes (cached PROC_TTL)
            ms = (time.perf_counter() - t) * 1000
            T.eq(got, {'XBone'}, f'Game.exe holding {name}')
            T.check(ms < 100, f'in_game (cold) took {ms:.1f} ms')
            polls = []
            for _ in range(5):                          # a poll: the fds again, the process list cached
                M._cache.clear()                        # (best of 5: a garbage collection of the big
                t = time.perf_counter()                 # application process may fall into one of them)
                M.in_game(G.save_dir)
                polls.append((time.perf_counter() - t) * 1000)
            ms = min(polls)
            T.check(ms < 20, f'in_game (poll) took {ms:.1f} ms')
            t = time.perf_counter()
            M.in_game(G.save_dir)
            T.check((time.perf_counter() - t) * 1000 < 2, 'cached call not cheap')
        finally:
            stop(p)
    T.eq(M.in_game(os.path.join(G.save_dir, 'missing')), set(), 'missing folder')


@T.test
def in_game_save_is_read_again_with_a_note():
    import mxl_ingame as M
    m0 = T.mark()
    p = hold('XBone.d2s', 'XBone.key')
    try:
        M.tick(G.app)
        T.pump(4)
        T.check('XBone is in a game' in warning(), 'no warning: ' + warning())
        T.check(G.app._ig_label.winfo_ismapped() and G.app._ig_label.winfo_height() > 4, 'warning label not shown')
        new = game_save()
        T.check(M.tick(G.app), 'tick did not reload')
        T.pump(6)
        T.check('Reloaded: the game saved XBone' in T.status_text(), 'status: ' + T.status_text())
        inv = G.app.inventory
        T.check(inv.ch is not None and bytes(inv.ch.raw) == new, 'inventory panel shows the old file')
        cw = T.chartab()
        if cw is not None and getattr(cw, 'ch', None) is not None:
            T.check(bytes(cw.ch.raw) == new, 'Character tab holds the old file')
        T.check(not M.tick(G.app), 'second tick reloaded again')
    finally:
        stop(p)
    for _ in range(M.GRACE + 1):                        # the grace polls, then the warning goes
        M.tick(G.app)
    T.pump(4)
    T.eq(warning(), '', 'warning after the game let go')
    cw = T.chartab()
    if cw is not None:
        T.check('in a game' not in str(cw.status.cget('text')), 'Character tab still warns: ' + str(cw.status.cget('text')))
    for e in T.errors_since(m0):
        T.check('Traceback' not in e, 'traceback: ' + e)


@T.test
def the_poll_runs_by_itself():
    """No tick() from the test: the application's own after() loop reads the game's save again."""
    import mxl_ingame as M
    m0 = T.mark()
    p = hold('XBone.d2s')
    try:
        T.wait_for(lambda: 'in a game' in warning(), secs=6, what='warning from the poll loop')
        if os.environ.get('CAPY_SHOT'):                 # a look at the warning line (both looks)
            T.pump(10)
            subprocess.run(['import', '-window', 'root', os.environ['CAPY_SHOT']], check=False)
        G.app.status.configure(text='')
        new = game_save()
        T.wait_for(lambda: G.app.inventory.ch is not None and bytes(G.app.inventory.ch.raw) == new, secs=6,
                   what='reload by the poll loop')
        T.pump(4)
        T.check('Reloaded: the game saved XBone' in T.status_text(), 'status: ' + T.status_text())
        T.check(bytes(G.app.inventory.ch.raw) == new, 'inventory panel shows the old file')
    finally:
        stop(p)
    for e in T.errors_since(m0):
        T.check('in-game watch' not in e and 'Traceback' not in e, e)


@T.test
def not_in_game_no_reload_no_warning():
    import mxl_ingame as M
    M.clear()
    G.app._ig_grace = 0
    M.tick(G.app)
    p = hold('_sharedstash.shared')                     # the game at its menu
    try:
        G.app.status.configure(text='')
        new = game_save()
        T.check(not M.tick(G.app), 'reloaded although not in game')
        T.pump(4)
        T.check('Reloaded' not in T.status_text(), 'note although not in game')
        T.eq(warning(), '', 'warning although not in game')
    finally:
        stop(p)


def small_equipped():
    import mxl_char
    ch = mxl_char.Character(G.app.character_file(), G.app.data)
    for e in ch.entries(False):
        b = G.app.data.base(e.it['code'])
        if e.it['location'] == 1 and b.size[0] * b.size[1] <= 4:
            return ('slot', e.it['equipped'])
    T.skip('no small equipped item')


def asked():
    return [b for b in G.boxes if b[0] == 'askyesno' and 'in a game' in b[2]]


@T.test
def to_stash_asks_only_in_game():
    where = small_equipped()
    cpath, spath = G.app.character_file(), G.app.path
    c0, s0 = T.read(cpath), T.read(spath)
    p = hold('XBone.d2s')
    try:
        G.answers['askyesno'] = False
        T.invoke(T.panel_menu(where), 'To stash')
        T.pump(6)
        T.eq(len(asked()), 1, 'confirmation in game')
        T.check(T.read(cpath) == c0 and T.read(spath) == s0, 'written although the user said No')
    finally:
        stop(p)
    del G.boxes[:]
    G.answers.pop('askyesno', None)
    T.invoke(T.panel_menu(where), 'To stash')
    T.pump(6)
    T.eq(asked(), [], 'confirmation although not in game')
    T.check(T.read(cpath) != c0, 'To stash did nothing when not in game')


@T.test
def character_save_asks_only_in_game():
    cw = T.chartab()
    if cw is None:
        T.skip('no Character tab')
    p = hold('XBone.map')
    try:
        G.answers['askyesno'] = False
        cw.save_progress()
        T.pump(4)
        T.eq(len(asked()), 1, 'SAVE asks in game')
    finally:
        stop(p)
    del G.boxes[:]
    cw.save_progress()
    T.pump(4)
    T.eq(asked(), [], 'SAVE asks although not in game')


@T.test
def player_name_is_read_from_game_memory():
    """The in-game signal checked on the real game: D2Client + 0x11BBFC is 0 at the menu and the player unit in a
    game; unit + 0x14 = player data, whose first 16 bytes are the name. Fake memory here."""
    import mxl_ingame as IG
    base = IG.D2CLIENT_BASE
    mem = {}

    def put(addr, data):
        for i, b in enumerate(data):
            mem[addr + i] = b

    def read(addr, n):
        return bytes(mem.get(addr + i, 0) for i in range(n))
    T.eq(IG._name_at(read, base), None, 'menu: no player unit')
    put(base + IG.PLAYER_UNIT, (0x132A5B00).to_bytes(4, 'little'))
    put(0x132A5B00 + 0x14, (0x02946400).to_bytes(4, 'little'))
    put(0x02946400, b'test-druid\0garbage')
    T.eq(IG._name_at(read, base), 'test-druid', 'in a game: the name')


T.main(globals())
