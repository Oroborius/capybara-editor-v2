"""Status bar "XBone: Necromancer level 100, Strength …, Dexterity …" shows the Stats page's totals
(docs/review/gui.md finding 10: it showed the collector's stored + flat items of both weapon sets, 972 / 208,
against 3341 / 336 on the stat screen). src/mxl_status_attr.py; the collector's own numbers in app.char stay
(its red "Required …" lines read them)."""
import gc
import re

import capytest as T

MODE = 'gui'
RESET = True
G = T.G


def label():
    return str(G.app.char_label.cget('text'))


def numbers(text):
    return [int(x) for x in re.findall(r'\d+', text)]


def stat_screen():
    import mxl_char_gui
    import mxl_statscreen
    if T.chartab() is None:
        mxl_char_gui.CharacterWindow(G.app, 'stats')
    T.pump(20)
    return next((o for o in gc.get_objects() if isinstance(o, mxl_statscreen.StatScreen)), None)


@T.test
def status_bar_matches_the_stats_page():
    G.app.show_status()
    T.pump(4)
    txt = label()
    ch = G.app.char
    T.check(ch and ch.get('path'), 'no character loaded')
    ss = stat_screen()
    T.check(ss is not None, 'no Stats page')
    want = (ss.attr_total(0), ss.attr_total(2))
    T.check(want[0] in numbers(txt), f'strength {want[0]} not in {txt!r}')
    T.check(want[1] in numbers(txt), f'dexterity {want[1]} not in {txt!r}')
    T.check(ch['strength'] != want[0] or ch['dexterity'] != want[1], 'sample cannot tell the two apart')
    T.check(ch['strength'] not in numbers(txt), f'collector strength {ch["strength"]} still shown: {txt!r}')
    T.check(ch['name'] in txt and str(ch['level']) in txt, f'name / level missing: {txt!r}')


@T.test
def status_bar_follows_the_file():
    """A changed character file (here: the second sample's save over the first) gives new totals."""
    import os
    import shutil
    import mxl_status_attr
    path = G.app.char['path']
    G.app.show_status()
    before = label()
    src2 = os.path.join(T.SRC_SAVES2, os.path.basename(path))
    if not os.path.isfile(src2):
        T.skip('no second sample of the same character')
    shutil.copyfile(src2, path)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    G.app.show_status()
    T.pump(4)
    after = label()
    t = mxl_status_attr.totals(path, G.app.data)
    T.check(t is not None and t[0] in numbers(after) and t[1] in numbers(after), f'{t} not in {after!r}')
    T.check(after != before, f'unchanged: {after!r}')


T.main(globals())
