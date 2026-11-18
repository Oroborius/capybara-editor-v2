"""Start-up time and the time of common actions, with generous limits (a regression guard, not a benchmark: the
limits are several times what the editor needs on the development machine, so a busy CI box does not fail them).

Measured on the PS5 (Zen 2) under Xvfb at 2560x1440, UI scale 1.25, d2 look, after the start-up work of
2026-11-17: first start with an empty art cache ~9 s to an idle window (36 s before), later starts ~2.5 s (4 s);
switching stash pages 10-110 ms, item hover < 20 ms, Character pages 50-200 ms, Item Editor ~250 ms, a resize
of the main window that changes the cell size ~300-400 ms.

- start: from the end of the fixture copies to the window with its Character and Creator tabs built (the
  fixture's art cache is partly empty: part of the art is extracted during this start);
- a rebuild of the Character and Creator windows with the art cache warm opens no game archive (later starts
  read everything from <user dir>/ui_art) and stays within its budget;
- the Creator's bonus-text index is written to <user dir>/cache and equals what the Creator computes;
- actions: stash pages, hover, Character tab pages, Creator / Item Editor, a resize; the window goes idle after."""
import os
import time

import capytest as T

MODE = 'gui'
VARIANTS = {'d2-scale1.25': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1180x680+0+0', 'MXL_UI_SCALE': '1.25'}}
G = T.G

START_BUDGET = 60.0          # s: first start, art partly extracted (measured ~10 s)
REBUILD_BUDGET = 8.0         # s: Character + Creator windows built again on a warm cache (measured ~0.8 s)
ACTION_BUDGET = 3.0          # s: one action until the event loop is quiet again (measured 0.01-0.4 s)
MAX_CALLS = 120              # Tk callbacks in one idle second (as test_36: the layout loop of W24 made thousands)

_mark = {}
_fresh = T.fresh_saves


def _fresh_saves(which=1):                      # the harness copies the saves last, just before the start
    try:
        return _fresh(which)
    finally:
        _mark.setdefault('t0', time.time())


T.fresh_saves = _fresh_saves


class Count:
    """Tk callbacks and <Configure> events while active."""

    def __enter__(self):
        import tkinter
        self.n = [0, 0]
        self.orig = tkinter.CallWrapper.__call__
        n, orig = self.n, self.orig

        def call(w, *a):
            n[0] += 1
            return orig(w, *a)
        tkinter.CallWrapper.__call__ = call
        G.root.bind_all('<Configure>', lambda _e: n.__setitem__(1, n[1] + 1), add='+')
        return self

    def __exit__(self, *exc):
        import tkinter
        tkinter.CallWrapper.__call__ = self.orig
        try:
            G.root.unbind_all('<Configure>')
        except Exception:
            pass


def until_quiet(fn, quiet=0.2, cap=ACTION_BUDGET * 3):
    """Seconds from fn() until the event loop ran no callback for `quiet` seconds."""
    with Count() as c:
        t0 = time.time()
        fn()
        busy, last = time.time(), -1
        while time.time() - t0 < cap:
            s = time.time()
            G.root.update()
            if c.n[0] != last or time.time() - s > 0.01:
                busy, last = time.time(), c.n[0]
            elif time.time() - busy > quiet:
                break
            time.sleep(0.003)
    return busy - t0


def idle_calls(secs=1.0):
    with Count() as c:
        T.settle(secs)
    return c.n[0]


def act(what, fn, budget=ACTION_BUDGET):
    t = until_quiet(fn)
    print(f'  {what}: {t * 1000:.0f} ms')
    T.check(t <= budget, f'{what} took {t:.2f} s (budget {budget} s)')
    return t


@T.test
def start_is_within_budget():
    import mxl_tabs
    T.check(mxl_tabs.built_owner('Creator') is not None and mxl_tabs.built_owner('Character') is not None,
            'the Character / Creator tabs were not built at the start')
    t = time.time() - _mark.get('t0', time.time())
    print(f'  start to built tabs (plus the harness settle): {t:.1f} s')
    T.check(t <= START_BUDGET, f'the start took {t:.1f} s (budget {START_BUDGET} s)')


@T.test
def warm_rebuild_opens_no_archive():
    import mxl_char_gui
    import mxl_creator_gui
    import mxl_d2look_art as A
    import mxl_tabs
    T.settle(1.0)                                    # the background art warm-up of the start is over
    opened = []
    orig = A._archive

    def spy(path):
        opened.append(os.path.basename(path))
        return orig(path)
    A._archive = spy
    A._ART.clear()                                   # new Art objects, as a new start has them
    try:
        t = until_quiet(lambda: (mxl_char_gui.CharacterWindow(G.app, 'stats'), mxl_creator_gui.CreatorWindow(G.app)))
    finally:
        A._archive = orig
    print(f'  Character + Creator rebuilt: {t * 1000:.0f} ms')
    T.check(t <= REBUILD_BUDGET, f'rebuilding the Character and Creator windows took {t:.1f} s')
    T.eq(sorted(set(opened)), [], 'game archives opened with a warm art cache')
    T.select_tab('Stash')
    T.check(mxl_tabs.built_owner('Character') is not None, 'no Character window after the rebuild')


@T.test
def bonus_index_is_cached_on_disk():
    import mxl_creator_gui as CG
    import mxl_diskcache
    import mxl_tabs
    cw = mxl_tabs.built_owner('Creator')
    cr = cw.cr
    T.wait_for(lambda: getattr(cr, '_bonus_done', False), 60, 'the Creator bonus-text index')
    k = CG._bonus_disk_key(cr)
    T.check(k is not None, 'no key for the bonus-text index')
    got = CG._bonus_disk_load(k)
    T.check(got is not None and len(got) > 100, f'bonus-text index not on disk ({mxl_diskcache.path(CG.BONUS_CACHE)})')
    if got:
        fresh = cr.__class__(cr.data)                # computed from scratch
        for key in list(got)[::max(1, len(got) // 60)]:
            T.eq(got[key], fresh.bonus_text(*key), f'cached bonus text of {key}')
    T.eq(CG._bonus_disk_load(k + 'x'), None, 'the index under another key')


@T.test
def actions_stay_responsive():
    import mxl_tabs
    app = G.app
    T.select_tab('Stash')
    nb = app.notebook
    for p in list(range(1, len(nb.tabs()))) + [0]:
        act(f'stash page {p}', lambda p=p: nb.select(p))
    items = [i for i in app.items if i['page'] == 0][:8]
    for it in items:
        x, y = int((it['x'] + .5) * app.cell), int((it['y'] + .5) * app.cell)
        act(f'hover {it.get("name") or it.get("code")!r}',
            lambda x=x, y=y: app.canvas.event_generate('<Motion>', x=x, y=y, warp=True), budget=ACTION_BUDGET / 2)
    pages = mxl_tabs._state['pages']
    act('Character tab', lambda: mxl_tabs._state['nb'].select(pages['Character']))
    cw = mxl_tabs.built_owner('Character')
    for key in list(cw.pages):
        def show(key=key):
            cw.tab.set(key)
            cw.show_tab()
        act(f'Character page {key}', show)
    cw.tab.set('stats')
    cw.show_tab()
    act('Creator tab', lambda: mxl_tabs._state['nb'].select(pages['Creator']))
    act('Stash tab', lambda: mxl_tabs._state['nb'].select(pages['Stash']))
    it = next((i for i in app.items if i.get('quality') in ('unique', 'rare', 'set')), None)
    if it is not None:
        import mxl_creator_gui as CG

        def edit():
            nb.select(it['page'])
            app.selected = it
            app.draw_grid()
            app.set_detail(it)
            CG.edit_selected(app)
        act('Item Editor', edit)
        act('back to the Creator', lambda: CG.CreatorWindow(app))
        T.select_tab('Stash')
    for geo in ('1000x600', '1180x680'):
        act(f'resize to {geo}', lambda g=geo: G.root.geometry(g))
    n = idle_calls(1.0)
    T.check(n <= MAX_CALLS, f'not idle after the actions: {n} Tk callbacks in one second')


T.main(globals())
