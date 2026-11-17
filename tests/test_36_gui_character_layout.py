"""The Character tab's pages in both looks, at 1280x720 and 800x600, and at UI scales 1.25 / 1.5: every page opens
without an exception (the harness checks stderr / capybara.log after each test), the application becomes idle
after it was opened - no layout loop (W24: two widgets resizing each other kept the event loop at 100 % CPU;
measured the same way here, by counting Tk callbacks and <Configure> events over one second) - and the SAVE /
RELOAD / CLOSE image buttons follow the UI scale and stay inside the window.

Also here: the status bar's item counters after stash writes (they showed the numbers of before the write).

Set CAPY_SHOTS=<folder> to get a screenshot of every page (ImageMagick `import`; nothing is compared)."""
import os
import subprocess

import capytest as T

MODE = 'gui'
RESET = True
VARIANTS = {
    'd2-1280x720': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0'},
    'he-1280x720': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '1280x720+0+0'},
    'd2-800x600': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '800x600+0+0'},
    'he-800x600': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '800x600+0+0'},
    'd2-scale1.25': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0', 'MXL_UI_SCALE': '1.25'},
    'd2-scale1.5': {'MXL_THEME': 'd2', 'CAPY_GEOMETRY': '1280x720+0+0', 'MXL_UI_SCALE': '1.5'},
    'he-scale1.5': {'MXL_THEME': 'he', 'CAPY_GEOMETRY': '1280x720+0+0', 'MXL_UI_SCALE': '1.5'},
}
G = T.G
SCALE = float(os.environ.get('MXL_UI_SCALE') or 1)
# callbacks / <Configure> events of one second in an idle window. Idle, the application runs a handful of timers
# (file watcher, hover); the W24 layout loop made thousands of both.
MAX_CALLS, MAX_CONFIGURES = 120, 12


def activity(secs=1.0):
    """(Tk callbacks, <Configure> events) during `secs` of running the event loop."""
    import tkinter
    n = [0, 0]
    orig = tkinter.CallWrapper.__call__

    def call(self, *a):
        n[0] += 1
        return orig(self, *a)

    def conf(_e):
        n[1] += 1
    tkinter.CallWrapper.__call__ = call
    fid = G.root.bind_all('<Configure>', conf, add='+')
    try:
        T.settle(secs)
    finally:
        tkinter.CallWrapper.__call__ = orig
        try:
            G.root.unbind_all('<Configure>')            # only this test binds it application-wide ...
        except Exception:
            pass
        _ = fid
    return n[0], n[1] - 0


def shot(name):
    folder = os.environ.get('CAPY_SHOTS')
    if not folder:
        return
    os.makedirs(folder, exist_ok=True)
    G.root.update()
    try:
        subprocess.run(['import', '-window', 'root', os.path.join(folder, f'{T.VARIANT}-{name}.png')], timeout=30,
                       capture_output=True)
    except Exception:
        pass


def window():
    import mxl_char_gui
    cw = T.chartab()
    if cw is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
        cw = T.chartab()
    T.select_tab('Character')
    T.settle(0.3)
    return cw


def buttons(cw):
    import mxl_char_gui
    return [w for w in cw.bar_status.master.winfo_children() if isinstance(w, mxl_char_gui.StoneButton)]


@T.test
def all_binds_survive_the_measurement():
    """activity() removes its own application-wide <Configure> binding: make sure there was none before (it
    would be removed with it, and this file would test a crippled application)."""
    T.eq(G.root.bind_all('<Configure>') or '', '', 'application-wide <Configure> binding')


@T.test
def every_page_opens_and_the_application_goes_idle():
    cw = window()
    builtin = ['stats', 'inventory', 'skills', 'waypoints', 'quests']
    for key in builtin + sorted(k for k in cw.pages if k not in builtin):
        cw.tab.set(key)
        cw.show_tab()
        T.settle(0.6)                                    # the page lays itself out (fit, scroll area, wrap)
        page = cw.pages[key]
        T.check(page.winfo_ismapped() and page.winfo_width() > 100 and page.winfo_height() > 50,
                f'page {key!r}: {page.winfo_width()}x{page.winfo_height()}, mapped {page.winfo_ismapped()}')
        calls, confs = activity(1.0)
        T.check(calls <= MAX_CALLS and confs <= MAX_CONFIGURES,
                f'page {key!r} does not come to rest: {calls} Tk callbacks and {confs} <Configure> events in one second')
        T.check(not cw.dirty(), f'unsaved changes after only opening {key!r}')
        shot(key)
    if cw.statscreen is not None:                        # the stat screen's own pages
        cw.tab.set('stats')
        cw.show_tab()
        for name in cw.statscreen.pages:
            cw.statscreen.show_page(name, exact=True)
            T.settle(0.3)
            calls, confs = activity(1.0)
            T.check(calls <= MAX_CALLS and confs <= MAX_CONFIGURES,
                    f'stat screen page {name!r} does not come to rest: {calls} callbacks, {confs} <Configure> events')
            shot('stats-' + name)
        cw.statscreen.show_page('main')
    for tab in [t for t, _n, _c in cw.sktree.trees]:     # every skill tree (and the "other skills" page)
        cw.tab.set('skills')
        cw.show_tab()
        cw.sktree.show_tab(tab)
        T.settle(0.3)
        calls, confs = activity(0.5)
        T.check(calls <= MAX_CALLS and confs <= MAX_CONFIGURES,
                f'skill tree {tab} does not come to rest: {calls} callbacks, {confs} <Configure> events')
    cw.tab.set('inventory')
    cw.show_tab()
    cw.merc.set(True)
    cw.on_view()
    T.settle(0.3)
    calls, confs = activity(0.5)
    T.check(calls <= MAX_CALLS and confs <= MAX_CONFIGURES, f'mercenary view: {calls} callbacks, {confs} <Configure> events')
    cw.merc.set(False)
    cw.on_view()
    cw.tab.set('stats')
    cw.show_tab()
    T.pump(4)


@T.test
def image_buttons_follow_the_ui_scale():
    """SAVE / RELOAD / CLOSE are 94x32 pixel images of the old Hero Editor: at 125 % / 150 % they stayed that
    small beside text that had grown. They are drawn at the UI scale now (the original pixels at 100 %)."""
    cw = window()
    bs = buttons(cw)
    T.eq(len(bs), 3, 'image buttons')
    dpi = G.root.winfo_fpixels('1i') / 96.0
    T.check(abs(dpi - SCALE) < 0.06, f'the test window runs at {dpi:.2f}, not at MXL_UI_SCALE {SCALE}')
    for b in bs:
        w, h = b.imgs[0].width(), b.imgs[0].height()
        T.eq((w, h), (round(94 * SCALE), round(32 * SCALE)), f'image size of {b.command.__name__} at scale {SCALE}')
        T.eq({(i.width(), i.height()) for i in b.imgs}, {(w, h)}, 'normal / hover / pressed images have one size')
        T.check(b.winfo_ismapped(), 'button not shown')
        x, y = b.winfo_rootx() - G.root.winfo_rootx(), b.winfo_rooty() - G.root.winfo_rooty()
        T.check(x >= 0 and y >= 0 and x + b.winfo_width() <= G.root.winfo_width() + 1
                and y + b.winfo_height() <= G.root.winfo_height() + 1,
                f'{b.command.__name__}: {b.winfo_width()}x{b.winfo_height()} at ({x}, {y}) is outside the window')
    from tkinter import font as tkfont
    import mxl_char_gui
    line = tkfont.Font(root=G.root, font=mxl_char_gui.HE_FONT).metrics('linespace')
    ratio = bs[0].imgs[0].height() / line
    if SCALE == 1 or line >= 13 * SCALE:                 # (X core fonts - an AppDir built without Xft - do not
        T.check(1.5 <= ratio <= 2.6,                     # grow with the scale: nothing to compare with then)
                f'button height {bs[0].imgs[0].height()} against a text line of {line} px')
    shot('buttons')


@T.test
def status_bar_counts_follow_stash_writes():
    """"Stash: n items" / "Page p: n" at the bottom of the Stash tab after a write that takes the fast reload
    (create, delete, undo, paste): they kept the numbers of before the write until something else reloaded."""
    import mxl_undo
    app = G.app
    T.select_tab('Stash')
    T.pump(6)

    def shown():
        return str(app.count_total.cget('text')), str(app.count_page.cget('text'))

    def numbers():
        import re
        return tuple(int((re.findall(r'\d+', t) or ['-1'])[-1]) for t in shown())
    app.notebook.select(0)
    T.pump(4)
    app.show_status()
    n0 = len(app.items)
    p0 = sum(1 for i in app.items if i['page'] == 0)
    T.eq(numbers(), (n0, p0), f'counters before any write {shown()}')
    it = next(i for i in app.items if i['page'] == 0)
    mxl_undo.delete_item(app, it)
    T.pump(6)
    T.eq(len(T.stash_items(app.path, app.data)), n0 - 1, 'items in the file after the delete')
    T.eq(numbers(), (n0 - 1, p0 - 1), f'counters after a delete {shown()}')
    T.check('deleted' in T.status_text(), f'status line after the delete: {T.status_text()!r}')
    mxl_undo._do_undo(app)
    T.pump(6)
    T.eq(numbers(), (n0, p0), f'counters after the undo {shown()}')


T.main(globals())
