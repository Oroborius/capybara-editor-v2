"""Pre-1.10 saves (header version 92, Diablo II 1.09) in the vanilla 1.14d profile (mxl_v109): the five mock
clones made for 1.09 open, their u32 stats and 1.09 item records read (widths from the game folder's
itemstatcost "1.09-Save Bits / Add" columns, every item parsed without the opaque fallback), a save without edits
is byte-identical, stats are written back in the 1.09 layout, item edits are refused, and the collector's reader
gets the same values. Median XL never takes the 1.09 path."""
import glob
import os
import shutil
import sys

import capytest as T

MODE = 'engine'
NEEDS = ()
GAME = os.environ.get('MXL_TEST_VANILLA_GAME') or os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')
OLD = ('clone-59', 'clone-91', 'clone-44', 'clone-97', 'clone-61')
_E = None


def engine():
    global _E
    if _E is not None:
        return _E
    src = os.path.join(T.REPO, '.cache', 'samples', 'mock')
    if not os.path.isfile(os.path.join(GAME, 'd2data.mpq')) or not os.path.isdir(src):
        T.skip(f'no vanilla 1.14d install ({GAME}) or no mock samples')
    user = T.guard(os.path.join(T.tmp(), 'v94user'), 'user folder')
    saves = T.guard(os.path.join(T.tmp(), 'v94saves'), 'save folder')
    os.makedirs(user, exist_ok=True)
    os.makedirs(saves, exist_ok=True)
    files = {}
    for f in glob.glob(os.path.join(src, '**', '*.d2s'), recursive=True):
        n = os.path.basename(f)[:-4]
        if n in OLD and n not in files:
            files[n] = os.path.join(saves, n + '.d2s')
            shutil.copy(f, files[n])
    T.check(sorted(files) == sorted(OLD), f'the five 1.09 samples: {sorted(files)}')
    os.environ.update(MXL_USER_DIR=user, MXL_SAVE_DIR=saves, MXL_GAME='vanilla', MXL_GAME_DIR=GAME)
    os.environ.setdefault('LOCALAPPDATA', T.tmp())
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import paths
    T.guard(paths.USER_DIR, 'paths.USER_DIR')
    out = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        import mxl_free
        import mxl_format_fix
        mxl_free.install()
        mxl_format_fix.install()
        import mxl_profile
        mxl_profile.install()
    finally:
        sys.stdout = out
    import mxl_data
    import mxl_char
    _E = T.NS(data=mxl_data.Data(paths.DATA_DIR), MC=mxl_char, files=files)
    return _E


@T.test
def old_saves_open_and_rebuild_identical():
    E = engine()
    import mxl_save
    for n, path in sorted(E.files.items()):
        raw = T.read(path)
        T.eq(raw[4], 92, f'{n}: header version 92')
        ch = E.MC.Character(path, E.data)
        T.check(ch.old, f'{n}: read as a 1.09 save')
        T.check(ch.stat(12) > 0 and all(0 <= s < 16 for s, _p, _v in ch.stats), f'{n}: stats 0..15, level set')
        T.check(len(ch.items) > 0, f'{n}: items read')
        for e in list(ch.items) + list(ch.merc_items or []):
            T.check(getattr(e.it, 'v109', False) and not getattr(e.it, 'opaque', False),
                    f'{n}: {e.it["code"]} parsed as a 1.09 record')
            T.check(e.blob[:2] == b'JM', f'{n}: item bytes start with JM')
        T.check(bytes(ch.build()) == raw, f'{n}: rebuilt bytes identical')
        c = mxl_save.load_character(path, E.data)        # the main window's reader
        T.eq(len(c['items']), len(ch.items), f'{n}: collector reader item count')
        T.eq(c['strength'], ch.stat(0), f'{n}: collector reader strength')
        ch.save(backup=False)
        T.check(T.read(path) == raw, f'{n}: SAVE without edits leaves the file as it was')


@T.test
def old_save_item_stats_use_current_ids():
    """The packed old forms come out as the 1.10 ids: no 1.09-only id (84-87, 92, 94, 108, 181-193, 196, ...)
    in any list, and every stat id has a row in the game's itemstatcost."""
    E = engine()
    bad = set(range(84, 88)) | {92, 94, 95, 97, 98, 100, 101, 103, 104, 106, 108, 109} | set(range(179, 188)) | \
        set(range(189, 194)) | {196, 197, 199, 200, 202, 203} | set(range(205, 214))
    seen = 0
    for n, path in sorted(E.files.items()):
        ch = E.MC.Character(path, E.data)
        for e in ch.items:
            for st in e.it['stats']:
                seen += 1
                T.check(st['id'] not in bad and st['id'] in E.data.isc, f'{n}: {e.it["code"]} stat {st["id"]}')
    T.check(seen > 100, f'{seen} item stats read')


@T.test
def old_set_item_index_is_a_sets_row():
    """A 1.09 set item's 12-bit index is a sets row: it reads as the setitems row of that set with the item's base
    code (no sample has one: a record synthesized from a 1.14d set amulet / ring, empty stat lists, which lay out
    the same in both versions). The same bytes read as 1.14d keep the index; a set without that base keeps it."""
    E = engine()
    import mxl_creator as C
    import mxl_save
    import mxl_tooltip
    import mxl_v109
    d = E.data
    row = next((i for i, r in enumerate(d.set_items) if r['code'] in ('amu ', 'rin ') and i != r['set_id']
                and [x['code'] for x in d.set_items if x['set_id'] == r['set_id']].count(r['code']) == 1), None)
    if row is None:
        T.skip('no set amulet / ring off its sets row')
    want = d.set_items[row]
    cr = C.Creator(d)
    rec = C.decode_item(bytes(cr.build(cr.new_spec('set', None, row))[0]), d)[0]
    blob = C.encode_item(dict(rec, stats=[], set_unique_id=want['set_id'], set_mask=0), d)
    it = mxl_save.blob_item(blob, mxl_v109.Data109(d))
    T.eq(it['set_unique_id'], row, f"1.09 sets row {want['set_id']} -> setitems row")
    T.eq(mxl_tooltip.special_name(it, d), want['name'], 'tooltip name')
    T.eq(mxl_save.blob_item(blob, d)['set_unique_id'], want['set_id'], '1.14d read unchanged')
    other = next(s for s in range(len(d._rows('sets'))) if not any(
        x['set_id'] == s and x['code'] == want['code'] for x in d.set_items))
    blob2 = C.encode_item(dict(rec, stats=[], set_unique_id=other, set_mask=0), d)
    T.eq(mxl_save.blob_item(blob2, mxl_v109.Data109(d))['set_unique_id'], other, 'no member with that base: kept')


@T.test
def old_save_stats_written_items_refused():
    E = engine()
    path = E.files['clone-44']
    raw = T.read(path)
    ch = E.MC.Character(path, E.data)
    T.eq(ch.stat_field('strength').bits, 32, '1.09 stats hold 32 bits')
    ch.set_field('strength', 50)
    ch.save(backup=False)
    again = E.MC.Character(path, E.data)
    T.eq(again.stat(0), 50, 'strength written in the 1.09 layout')
    T.eq(T.read(path)[4], 92, 'still a version 92 file')
    T.eq(len(again.items), len(ch.items), 'items kept')
    try:
        again.items[0].moved(E.data, x=0)
        T.check(False, 'moving a 1.09 item refused')
    except E.MC.CharError as e:
        T.check('1.09' in str(e), f'clear note: {e}')
    again.items.pop()
    try:
        again.build()
        T.check(False, 'changed 1.09 items refused')
    except E.MC.CharError:
        pass
    with open(path, 'wb') as f:
        f.write(raw)


@T.test
def median_never_reads_old_saves():
    E = engine()
    from mxl_format import FormatError
    real = E.MC._median
    E.MC._median = lambda: True
    try:
        E.MC.Character(E.files['clone-59'], E.data)
        T.check(False, 'Median XL refuses version 92')
    except FormatError as e:
        T.check('(92)' in str(e), str(e))
    finally:
        E.MC._median = real


T.main(globals())
