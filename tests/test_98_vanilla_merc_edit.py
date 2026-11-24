"""Vanilla Hero Editor look, Mercenary page: every stored field of the mercenary record (dead flag, id, name id,
type code, experience, level) is editable through the page's own boxes, SAVE writes it and the file read again
shows it; the Base Stats boxes are worked out from the hireling table (not stored). Stats page: Map ID and Time
Stamp (stored header words) are editable. Copies of the vanilla samples only (see test 77)."""
import glob
import os
import shutil
import struct

import capytest as T

MODE = 'gui'
G = T.G
WAIT_TABS = True
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')


def _saves():
    src = os.path.join(T.REPO, '.cache', 'samples', 'vanilla')
    if not glob.glob(os.path.join(src, '*.d2s')) or not os.path.isfile(os.path.join(GAME, 'd2data.mpq')):
        return None
    dst = T.guard(os.path.join(T.tmp(), 'vsaves'), 'vanilla save copies')
    if not os.path.isdir(dst):
        shutil.copytree(src, dst)
    return dst


_S = _saves()
ENV = {'MXL_GAME': 'vanilla', 'MXL_GAME_DIR': GAME, **({'MXL_SAVE_DIR': _S} if _S else {})}


def _open(name):
    G.app.select_character(name, G.app.view.get())
    G.app.open_view(keep_page=True)
    T.pump(20, 0.02)
    cw = T.chartab()
    T.check(cw is not None, 'Character tab built')
    return cw


def type_into(entry, text):
    entry.configure(state='normal')
    entry.delete(0, 'end')
    entry.insert(0, text)
    entry.focus_force()
    T.pump(3)
    entry.event_generate('<KeyRelease>', keysym='0')
    T.pump(3)


def page_of(cw):
    cw.tab.set('merc')
    cw.show_tab()
    T.pump(4)
    page = cw.extra['merc']
    T.check(page.vanilla_he, 'vanilla Hero Editor look')
    return page


def saved(cw):
    cw.save_progress()
    T.pump(6)
    import mxl_char
    return mxl_char.Character(cw.ch.path, cw.data)


@T.test
def base_stats_follow_the_table():
    if _S is None:
        T.skip('no vanilla install / samples')
    import mxl_merc
    cw = _open('complex')
    page = page_of(cw)
    h = cw.data and mxl_merc.hirelings(cw.data)[11]
    lv = int(page.v_level.get())
    want = mxl_merc.base_stats(h, lv)
    T.check(want and want['life'] > 0, f'stats for the table row: {want}')
    T.eq(page.base_stats['Life'].get(), str(want['life']), 'Life box')
    T.eq(page.base_stats['Defense'].get(), str(want['defense']), 'Defense box')
    first, last = h.brackets[0][0], h.brackets[-1][0]
    T.check(mxl_merc.base_stats(h, last + 8)['life'] > mxl_merc.base_stats(h, last)['life'], 'grows per level')
    T.eq(mxl_merc.base_stats(h, first)['life'], h.brackets[0][1], 'row level: the row value')
    type_into(page.e_level, str(lv + 5))
    T.check(page.base_stats['Life'].get() == str(mxl_merc.base_stats(h, lv + 5)['life']), 'Life follows the level')


@T.test
def every_merc_field_round_trips():
    if _S is None:
        T.skip('no vanilla install / samples')
    import mxl_merc
    cw = _open('complex')
    page = page_of(cw)
    before = mxl_merc.record(cw.ch)
    T.check(before['id'] != 0, 'sample has a mercenary')
    types = mxl_merc.hirelings(cw.data)
    # Code (type), ID, Name ID typed in the facts boxes
    new_type = 7
    type_into(page.facts['Code'], str(new_type))
    type_into(page.facts['ID'], '0A0B0C0D')
    type_into(page.facts['Name ID'], '2')
    # Level typed: experience follows from the hireling row; then the experience typed: level follows
    h = types[new_type]
    type_into(page.e_level, '20')
    T.eq(page.v_exp.get(), str(mxl_merc.exp_for_level(h.exp_per_level, 20)), 'typed level sets the experience')
    type_into(page.e_exp, str(mxl_merc.exp_for_level(h.exp_per_level, 30) + 5))
    T.eq(page.v_level.get(), '30', 'typed experience sets the level')
    page.v_life.set('Dead')
    page._change_life()
    ch = saved(cw)
    rec = mxl_merc.record(ch)
    T.eq((rec['type'], rec['id'], rec['name'], rec['exp']),
         (new_type, 0x0A0B0C0D, 2, mxl_merc.exp_for_level(h.exp_per_level, 30) + 5), 'record after save')
    T.check(rec['dead'] != 0, 'dead flag saved')
    cw.discard()
    T.pump(4)
    page = page_of(cw)
    T.eq(page.facts['Code'].get(), str(new_type), 'Code after reload')
    T.eq(page.facts['ID'].get(), '0A0B0C0D', 'ID after reload')
    T.eq(page.facts['Name ID'].get(), '2', 'Name ID after reload')
    T.eq(page.v_level.get(), '30', 'Level after reload')
    T.eq(page.v_life.get(), 'Dead', 'Dead after reload')
    page.v_life.set('Alive')
    page._change_life()
    T.eq(mxl_merc.record(saved(cw))['dead'], 0, 'resurrected')


@T.test
def stats_page_header_words_editable():
    if _S is None:
        T.skip('no vanilla install / samples')
    cw = _open('complex')
    cw.tab.set('stats')
    cw.show_tab()
    T.pump(4)
    for key, off, text in (('map_id', 171, '00C0FFEE'), ('timestamp', 48, '12345678')):
        T.eq(str(cw.sv[key].cget('state')), 'normal', f'{key} box is editable')
        type_into(cw.sv[key], text)
        T.check(cw.st_set(key, text), f'{key} accepted')
    ch = saved(cw)
    T.eq(struct.unpack_from('<I', ch.raw, 171)[0], 0x00C0FFEE, 'Map ID saved')
    T.eq(struct.unpack_from('<I', ch.raw, 48)[0], 0x12345678, 'Time Stamp saved')
    T.check(not cw.st_set('map_id', 'xyz'), 'garbage refused')


if __name__ == '__main__':
    T.main(globals())
