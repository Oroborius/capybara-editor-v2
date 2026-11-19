"""Switching characters in the main window's dropdown: quick, and the art caches the Character tab now keeps
between its rebuilds (mxl_speed: stat screen text / images, skill tree images, decoded DC6 files) draw exactly
what empty caches draw.

A second character is made from the second sample (the same hero at level 117, other stats and items) under the
name "Zweiter" (mxl_char.copy_character in a private folder, then moved into the application's save folder).

- switching back and forth rebuilds the Character tab with the picked character, within a generous time budget
  (measured on the development machine: ~0.5 s; 0.75-1 s before the caches; the budget is several times that);
- after each switch, every stat screen page composed with the shared caches has the same pixels as the same page
  composed with empty caches (the guard that nothing character-specific is kept in them), and the new tab really
  got the caches of the one before (they are shared, not rebuilt);
- the skill tree page draws the same picture with shared and with empty caches."""
import glob
import os
import shutil
import time

import capytest as T

MODE = 'gui'
NEEDS = ('user', 'saves', 'saves2')
VARIANTS = {'d2': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1180x680+0+0', 'MXL_UI_SCALE': '1.25'}}
G = T.G
SWITCH_BUDGET = 4.0          # s until the event loop is quiet again (measured ~0.5 s)
NAME = 'Zweiter'


def until_quiet(fn, quiet=0.2, cap=SWITCH_BUDGET * 3):
    import tkinter
    n = [0]
    orig = tkinter.CallWrapper.__call__

    def call(w, *a):
        n[0] += 1
        return orig(w, *a)
    tkinter.CallWrapper.__call__ = call
    try:
        t0 = time.time()
        fn()
        busy, last = time.time(), -1
        while time.time() - t0 < cap:
            s = time.time()
            G.root.update()
            if n[0] != last or time.time() - s > 0.01:
                busy, last = time.time(), n[0]
            elif time.time() - busy > quiet:
                break
            time.sleep(0.003)
    finally:
        tkinter.CallWrapper.__call__ = orig
    return busy - t0


def second_character():
    """Zweiter.d2s (+ companions) in the save folder: the second sample's hero under another name."""
    import mxl_char
    if os.path.exists(os.path.join(G.save_dir, NAME + '.d2s')):
        return
    src = T.guard(os.path.join(T.tmp(), 'second-src'), 'second character folder')
    os.makedirs(src, exist_ok=True)
    for p in glob.glob(os.path.join(T.SRC_SAVES2, 'XBone.*')):
        if '.bak' not in os.path.basename(p):
            shutil.copyfile(p, os.path.join(src, os.path.basename(p)))
    dst = mxl_char.copy_character(os.path.join(src, 'XBone.d2s'), NAME, G.app.data)
    for p in glob.glob(os.path.join(os.path.dirname(dst), NAME + '.*')):
        shutil.move(p, os.path.join(G.save_dir, os.path.basename(p)))


def pick(name):
    """What the dropdown does: the name, then open_view (the Character tab follows, mxl_follow)."""
    app = G.app

    def go():
        app.select_character(name, app.view.get())
        app.open_view(keep_page=True)
    prof = os.environ.get('CAPY_PROFILE_DIR')         # (diagnosis: a cProfile of every switch)
    if not prof:
        return until_quiet(go)
    import cProfile
    pr = cProfile.Profile()
    pr.enable()
    try:
        return until_quiet(go)
    finally:
        pr.disable()
        pr.dump_stats(os.path.join(prof, f'switch-{name}-{time.time():.0f}.prof'))


def compose_both(scr):
    """[(page, bytes with the shared caches, bytes with empty caches)] of every page of the stat screen."""
    from mxl_statscreen import GameText
    out = []
    shared = (scr.text, scr._pil, scr._bg)
    for page in list(scr.pages):
        a = scr.compose(page).tobytes()
        scr.text, scr._pil, scr._bg = GameText(scr.art), {}, {}
        try:
            b = scr.compose(page).tobytes()
        finally:
            scr.text, scr._pil, scr._bg = shared
        out.append((page, a, b))
    return out


@T.test
def switching_characters_is_quick_and_draws_the_same():
    import mxl_tabs
    cr = getattr(mxl_tabs.built_owner('Creator'), 'cr', None)      # the start's background work is over (the
    T.wait_for(lambda: cr is None or getattr(cr, '_bonus_done', False), 90, 'the Creator bonus-text index')
    T.settle(0.5)                                                   # harness copies the code: rebuilt each run)
    T.select_tab('Character')
    first = os.path.splitext(os.path.basename(G.app.character_file()))[0]
    second_character()
    T.settle(0.3)
    prev = T.chartab()
    T.check(prev is not None, 'no Character tab')
    times = []
    for name in (NAME, first, NAME, first):
        t = pick(name)
        times.append(t)
        print(f'  switch to {name}: {t * 1000:.0f} ms')
        cw = T.chartab()
        T.check(cw is not None and os.path.splitext(os.path.basename(cw.ch.path))[0] == name,
                f'the Character tab did not follow the dropdown to {name}')
        T.check(t <= SWITCH_BUDGET, f'switching to {name} took {t:.2f} s (budget {SWITCH_BUDGET} s)')
        scr = getattr(cw, 'statscreen', None)
        if scr is None:
            T.skip('no stat screen (no game art in this setup)')
        old = getattr(prev, 'statscreen', None)
        if old is not None and old.art is scr.art:
            T.check(scr._pil is old._pil and scr.text is old.text, 'the new tab did not get the stat screen caches')
        for page, a, b in compose_both(scr):
            T.check(a == b, f'{name}: stat screen page {page!r} differs between shared and empty caches')
        tree = getattr(cw, 'sktree', None)
        if tree is not None and tree.art() is not None:
            from mxl_statscreen import GameText
            tree.redraw()
            a = tree._photo
            sa = (a.width(), a.height()) if a is not None else None
            pa = _photo_bytes(a)
            T.check(pa, f'{name}: no skill tree picture to compare')
            keep = (tree._pil, tree._text, tree._icons)
            tree._pil, tree._text, tree._icons = {}, GameText(tree.art()), {}
            try:
                tree.redraw()
                b = tree._photo
                T.check(sa == ((b.width(), b.height()) if b is not None else None) and pa == _photo_bytes(b),
                        f'{name}: the skill tree differs between shared and empty caches')
            finally:
                tree._pil, tree._text, tree._icons = keep
                tree.redraw()
        prev = cw
    T.check(mxl_tabs.built_owner('Character') is not None, 'no Character tab at the end')


def _photo_bytes(ph):
    """The pixels of a Tk photo (the PIL image behind an ImageTk.PhotoImage is not kept): its PPM data."""
    if ph is None:
        return None
    try:
        return ph._PhotoImage__photo.tk.call(ph._PhotoImage__photo.name, 'data', '-format', 'ppm')
    except Exception:
        try:
            return ph.tk.call(str(ph), 'data', '-format', 'ppm')
        except Exception:
            return None


T.main(globals())
