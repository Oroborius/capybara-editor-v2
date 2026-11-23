"""Pre-1.10 saves (header version 92, Diablo II 1.09) in the vanilla 1.14d profile (mxl_v109): the five mock
clones made for 1.09 open, their u32 stats and 1.09 item records read (widths from the game folder's
itemstatcost "1.09-Save Bits / Add" columns, every item parsed without the opaque fallback), a save without edits
is byte-identical, stats are written back in the 1.09 layout, every item record re-encodes byte-identically
(mxl_creator codec with a Data109), items can be moved, deleted, pasted and edited (written as 1.09 records),
an edit the 1.09 record cannot hold is refused, and the collector's reader gets the same values. Median XL never
takes the 1.09 path."""
import glob
import json
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
def old_save_stats_written():
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
    _restore(path, raw)


def _restore(path, raw):
    os.chmod(path, 0o644)
    with open(path, 'wb') as f:
        f.write(raw)


def _old_records(ch):
    """(name, 1.09 bytes) of every item record of a character (socketed items and the mercenary's too)."""
    out = []
    for e in list(ch.items) + list(ch.merc_items or []):
        for it in [e.it] + list(e.it.get('socketed') or []):
            out.append((it['code'], ch.raw[it['_offset']:it['_offset'] + it['_size']]))
    return out


@T.test
def old_item_records_encode_identical():
    """Every item record of the five samples: decoded with the 1.09 widths (Data109) and encoded again gives the
    same bytes (stored ids, fast twins, +all skills parts, skipped single skills, end id and padding kept)."""
    E = engine()
    import mxl_creator as C
    import mxl_v109 as V
    d9 = V.Data109(E.data)
    n = 0
    for name, path in sorted(E.files.items()):
        ch = E.MC.Character(path, E.data)
        for code, b in _old_records(ch):
            rec, size = C.decode_item(b, d9)
            T.eq(size, len(b), f'{name}: {code} record size')
            T.check(C.encode_item(rec, d9) == b, f'{name}: {code} re-encodes byte-identically')
            n += 1
    T.check(n > 200, f'{n} records')


@T.test
def old_items_held_in_the_110_layout():
    """A 1.09 character's items are held in the 1.10 layout (what every item menu reads) and written back as the
    same 1.09 bytes; an item the 1.10 layout cannot hold (a clone's maxed stat) stays as read (move / delete)."""
    E = engine()
    import mxl_creator as C
    import mxl_v109 as V
    kept = 0
    for name, path in sorted(E.files.items()):
        ch = E.MC.Character(path, E.data)
        for e in list(ch.items) + list(ch.merc_items or []):
            raw = ch.raw[e.it['_offset']:e.it['_offset'] + ch._full_size(e.it)]
            if isinstance(e.blob, V.Raw109):
                kept += 1
                T.eq(bytes(e.blob), raw, f'{name}: {e.it["code"]} kept as read')
                try:
                    V.to_110(raw, E.data)
                    T.check(False, f'{name}: {e.it["code"]} kept although the 1.10 layout holds it')
                except C.StoreError:
                    pass
                try:
                    C.decode_item(e.blob, E.data)
                    T.check(False, 'item code refuses a kept 1.09 record')
                except C.CreateError as ex:
                    T.check('1.09' in str(ex), str(ex))
                continue
            rec = C.decode_item(e.blob, E.data)[0]
            T.eq(rec['code'], e.it['code'], f'{name}: 1.10 record readable')
            T.check(V.to_109(e.blob, E.data, ch._v109_hints) == raw,
                    f'{name}: {e.it["code"]} written back identically')
    T.check(kept <= 10, f'{kept} items kept as read')


def _reread(E, path, ch):
    ch.save(backup=False)
    T.eq(T.read(path)[4], 92, 'still a version 92 file')
    return E.MC.Character(path, E.data)


@T.test
def old_items_move_edit_delete_paste():
    E = engine()
    import mxl_creator as C
    import mxl_v109 as V
    d = E.data
    path = E.files['clone-44']
    raw = T.read(path)
    try:
        ch = E.MC.Character(path, d)
        e = ch.items[0]
        stats = {s['id']: s['value'] for s in C.decode_item(e.blob, d)[0]['stats']}
        # move: inventory -> stash (0, 0); the record keeps its 1.09 form, only the header bits change
        ch.items[0] = E.MC.Entry(None, e.moved(d, location=0, equipped=0, x=0, y=0, panel=5))
        again = _reread(E, path, ch)
        it = again.items[0].it
        T.eq((it['panel'], it['x'], it['y']), (5, 0, 0), 'moved item re-read at its new place')
        old_b = raw[e.it['_offset']:e.it['_offset'] + e.it['_size']]
        new_b = again.raw[it['_offset']:it['_offset'] + it['_size']]
        T.eq(new_b, bytes(V.moved_raw(old_b, dict(location=0, equipped=0, x=0, y=0, panel=5))),
             'moved record: same bytes but the place')
        T.eq({s['id']: s['value'] for s in it['stats']}, stats, 'stats unchanged by the move')
        # edit one stat value
        sid = next(s for s in stats if s != 99)
        rec, n = C.decode_item(again.items[0].blob, d)
        for s in rec['stats']:
            if s['id'] == sid:
                s['value'] -= 7
        again.items[0].blob = C.encode_item(rec, d) + again.items[0].blob[n:]
        ed = _reread(E, path, again)
        got = {s['id']: s['value'] for s in ed.items[0].it['stats']}
        want = dict(stats)
        want[sid] -= 7
        T.eq(got, want, f'stat {sid} edited, the others kept')
        # an edit the 1.09 record cannot hold: refused with a clear note, the rest stays editable
        rec, n = C.decode_item(ed.items[0].blob, d)
        bad = next(x for x in (85, 97) if x in d.isc)
        prm = 1 if d.isc[bad].get('param') else None
        good = ed.items[0].blob
        ed.items[0].blob = C.encode_item(dict(rec, stats=rec['stats'] + [dict(id=bad, param=prm, value=1)]), d)
        try:
            ed.build()
            T.check(False, f'stat {bad} on a 1.09 item refused')
        except E.MC.CharError as ex:
            T.check('1.09' in str(ex) and str(bad) in str(ex), f'clear note: {ex}')
        ed.items[0].blob = good
        # paste: Creator items (1.10 layout) into the stash; the first one 1.09 holds is written as a 1.09 record
        cr = C.Creator(d)
        pasted = refused = None
        for row in range(len(d.uniques)):
            try:
                spec = cr.new_spec('unique', None, row)
                blob = bytes(cr.build(spec)[0])
            except Exception:
                continue
            rec = C.decode_item(blob, d)[0]
            if rec['flags'] & C.FLAG_SOCKETED:
                continue
            blob = C.encode_item(dict(rec, location=0, equipped=0, x=4, y=0, panel=5), d)
            try:
                V.to_109(blob, d)
            except C.CreateError as ex:
                refused = refused or str(ex)
                continue
            pasted = rec
            ed.items.append(E.MC.Entry(None, blob))
            break
        T.check(pasted is not None, 'a Creator unique 1.09 can hold')
        if refused:
            T.check('1.09' in refused, f'refused paste says why: {refused}')
        n_before = len(ed.items)
        p2 = _reread(E, path, ed)
        T.eq(len(p2.items), n_before, 'pasted item saved')
        last = p2.items[-1].it
        T.eq((last['code'], last['panel'], last['x']), (pasted['code'], 5, 4), 'pasted item re-read')
        T.check(not isinstance(p2.items[-1].blob, V.Raw109), 'pasted item editable again')
        # delete
        p2.items.pop()
        p3 = _reread(E, path, p2)
        T.eq(len(p3.items), n_before - 1, 'deleted')
    finally:
        _restore(path, raw)


@T.test
def old_item_delete_keeps_the_rest():
    E = engine()
    path = E.files['clone-59']
    raw = T.read(path)
    try:
        ch = E.MC.Character(path, E.data)
        codes = [e.it['code'] for e in ch.items]
        k = len(codes) // 2
        blobs = [e.blob for e in ch.items]
        del ch.items[k]
        again = _reread(E, path, ch)
        T.eq([e.it['code'] for e in again.items], codes[:k] + codes[k + 1:], 'one item gone, the rest kept')
        T.check([e.blob for e in again.items] == blobs[:k] + blobs[k + 1:], 'the other items unchanged')
    finally:
        _restore(path, raw)


@T.test
def old_save_paste_from_a_114d_save():
    """Items of a 1.14d save pasted into a 1.09 character: those 1.09 can hold are written as 1.09 records and read
    back with the same stats; the others are refused, naming the stat."""
    E = engine()
    import mxl_creator as C
    import mxl_v109 as V
    src = os.path.join(T.REPO, '.cache', 'samples', 'vanilla', 'complex.d2s')
    if not os.path.isfile(src):
        T.skip('no 1.14d sample')
    d = E.data
    donor = E.MC.Character(src, d)
    path = E.files['clone-44']
    raw = T.read(path)
    try:
        ch = E.MC.Character(path, d)
        added, refused = [], []
        for e in donor.items:
            if e.it.get('location') != 0 or len(added) >= 3:
                continue
            blob = bytes(donor.stash_blob(e))
            try:
                V.to_109(blob, d)
            except C.StoreError as ex:
                refused.append(str(ex))
                continue
            rec = C.decode_item(blob, d)[0]
            x = 2 * len(added)
            new = C.encode_item(dict(rec, location=0, equipped=0, x=x, y=4, panel=5), d) + blob[len(
                C.encode_item(rec, d)):]
            ch.items.append(E.MC.Entry(None, new))
            added.append((rec['code'], sorted((s['id'], s.get('param') or 0, s['value']) for s in rec['stats'])))
        T.check(added, 'some 1.14d items 1.09 can hold')
        again = _reread(E, path, ch)
        got = [(e.it['code'], sorted((s['id'], s.get('param') or 0, s['value']) for s in
                                     C.decode_item(e.blob, d)[0]['stats'])) for e in again.items[-len(added):]]
        T.eq(got, added, 'pasted items read back with their stats')
        for msg in refused:
            T.check('1.09' in msg and 'stat' in msg, f'refusal names the stat: {msg}')
    finally:
        _restore(path, raw)


@T.test
def old_item_kept_as_read_moves():
    """An item kept as read (Raw109) moves by its header bits; its stats stay as they were."""
    E = engine()
    import mxl_v109 as V
    path = E.files['clone-91']
    raw = T.read(path)
    try:
        ch = E.MC.Character(path, E.data)
        k, e = next((i, e) for i, e in enumerate(ch.items) if isinstance(e.blob, V.Raw109))
        stats = [(s['id'], s['param'], s['value']) for s in e.it['stats']]
        x = (e.it['x'] + 1) % 10
        ch.items[k] = E.MC.Entry(None, e.moved(E.data, location=0, equipped=0, x=x, y=0, panel=5))
        it = _reread(E, path, ch).items[k].it
        T.eq((it['code'], it['panel'], it['x'], it['y']), (e.it['code'], 5, x, 0), 'moved')
        T.eq([(s['id'], s['param'], s['value']) for s in it['stats']], stats, 'stats kept')
    finally:
        _restore(path, raw)


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


@T.test
def pre_109_real_saves_round_trip_and_edit():
    E = engine()
    import mxl_creator as C
    import mxl_save
    from mxl_format import FormatError
    root = os.path.join(T.REPO, '.cache', 'samples', 'oldver')
    for folder, version in (('107', 87), ('108', 89), ('100', 71), ('106b', 71)):
        sources = sorted(glob.glob(os.path.join(root, folder, '*.d2s')))
        T.eq(len(sources), 2, f'{folder}: real save fixtures')
        for source in sources:
            path = os.path.join(T.tmp(), f'{folder}-{os.path.basename(source)}')
            shutil.copy(source, path)
            raw = T.read(path)
            ch = E.MC.Character(path, E.data)
            tag = f'{folder}/{ch.name}'
            T.eq(ch.version, version, tag)
            T.eq(ch.name, os.path.basename(source)[:-4], tag)
            T.eq(ch.level, 1, tag)
            T.eq(len(ch.skills), 32, tag)
            T.eq(len(ch.items), 8, tag)
            T.eq([e.it['code'].strip() for e in ch.items[:6]],
                 ['hp1'] * 4 + ['tsc', 'isc'], tag)
            T.check(ch.waypoint(0, 0), tag)
            T.eq(ch.build(), raw, f'{tag}: byte-identical rebuild')
            summary = mxl_save.load_character(path, E.data)
            T.eq(summary['name'], ch.name, tag)
            T.eq(len(summary['items']), 8, tag)
            ch.save(backup=False)
            T.eq(T.read(path), raw, f'{tag}: no-op save')
            strength = ch.stat(0) + 1
            ch.set_field('strength', strength)
            ch.save(backup=False)
            saved = E.MC.Character(path, E.data)
            T.eq(saved.stat(0), strength, tag)
            T.eq(saved.version, version, tag)
            T.eq([e.blob for e in saved.items], [e.blob for e in ch.items], tag)

            sid = next(iter(saved.skill_levels()))
            saved.set_skill_levels({sid: 1})
            saved.set_quests(0, {1})
            saved.set_waypoints(0, {0, 1})
            saved.set_flag('hardcore', True)
            if version == 71:
                T.check(30 not in saved.waypoint_ids(0), tag)
            if version != 71:
                weapon = saved.items[6]
                rec, size = C.decode_item(weapon.blob, E.data)
                T.eq(size, len(weapon.blob), tag)
                durability = rec['durability'] - 1
                weapon.blob = C.encode_item(dict(rec, durability=durability), E.data)
            saved.save(backup=False)
            again = E.MC.Character(path, E.data)
            T.eq(again.skill_levels()[sid], 1, tag)
            T.check(again.quest_done(0, 1) and again.waypoint(0, 1) and again.flags()['hardcore'], tag)
            if version != 71:
                T.eq(again.items[6].it['durability'], durability, tag)
            real = E.MC._median
            E.MC._median = lambda: True
            try:
                for reader in (E.MC.Character, mxl_save.load_character):
                    try:
                        reader(path, E.data)
                    except FormatError:
                        pass
                    else:
                        T.check(False, f'{tag}: Median XL must refuse legacy saves')
            finally:
                E.MC._median = real


@T.test
def classic_item_records_encode_identical():
    E = engine()
    import mxl_early_save as early
    root = os.path.join(T.REPO, '.cache', 'samples', 'oldver')
    for folder in ('100', '106b'):
        paths = sorted(glob.glob(os.path.join(root, folder, '*.d2s')))
        T.eq(len(paths), 2, f'{folder}: Classic fixtures')
        for path in paths:
            ch = E.MC.Character(path, E.data)
            T.eq(ch._classic_original, folder == '100', 'native layout detected')
            for code, raw in _old_records(ch):
                rec, size = early.decode_classic(raw)
                T.eq(size, len(raw), f'{folder}/{code}: native record length')
                T.eq(early.encode_classic(rec), raw, f'{folder}/{code}: native round trip')


@T.test
def classic_items_move_edit_delete_and_paste():
    E = engine()
    import mxl_creator as C
    import mxl_early_save as early
    from mxl_rc_menu import _char_replace
    d = E.data
    creator = C.Creator(d)
    root = os.path.join(T.REPO, '.cache', 'samples', 'oldver')
    for folder in ('100', '106b'):
        source = os.path.join(root, folder, 'Ashbow.d2s')
        path = os.path.join(T.tmp(), f'edit-{folder}.d2s')
        shutil.copy(source, path)
        ch = E.MC.Character(path, d)
        weapon = ch.items[6]
        raw = ch._old_blob(weapon)
        native, _ = early.decode_classic(raw)
        ch.move(weapon, ('inv', 0, 0))
        ch.save(backup=False)
        again = E.MC.Character(path, d)
        weapon = again.items[6]
        T.eq(E.MC.where_of(weapon), ('inv', 0, 0), f'{folder}: item moved')
        want = dict(native, location=0, equipped=0, x=0, y=0, page=0)
        T.eq(again._old_blob(weapon), early.encode_classic(want), 'only position fields changed')
        rec, _ = C.decode_item(weapon.blob, d)
        spec = creator.spec_from_item(weapon.it)
        quantity = spec['quantity'] = rec['quantity'] - 1
        edited, _ = creator.build(spec)
        edit_rec, _ = C.decode_item(edited, d)
        T.eq(edit_rec['quantity'], quantity, 'Creator edit retains changed stack size')
        edited = C.encode_item(dict(edit_rec, durability=rec['durability'] - 1), d)
        _char_replace(T.NS(ch=again), weapon, edited, ('inv', 0, 0), False)
        shield = again.items[7]
        copy = again.place(again.stash_blob(shield), ('inv', 4, 0))
        shield_rec, _ = early.decode_classic(again._old_blob(shield))
        T.eq(again._old_blob(copy), early.encode_classic(dict(shield_rec, location=0, equipped=0, x=4, y=0, page=0)),
             'same-layout clipboard paste preserves the native armor seed')
        again.remove(copy)
        potion = bytes(creator.build(creator.new_spec('normal', 'hp1 '))[0])
        pasted = again.place(potion, ('inv', 3, 0))
        T.eq(len(again._old_blob(pasted)), 27 if folder == '100' else 15, 'paste uses target layout')

        before = list(again.items)
        bad = (
            (dict(rec, stats=[dict(id=0, param=None, value=1)]), 'stat 0'),
            (dict(rec, flags=rec['flags'] | C.FLAG_ETHEREAL), 'ethereal'),
            (dict(rec, flags=rec['flags'] | C.FLAG_SOCKETED, sockets=1), 'sockets'),
            (dict(rec, flags=rec['flags'] | C.FLAG_RUNEWORD, runeword_id=0), 'runewords'),
            (dict(flags=C.FLAG_SIMPLE | C.FLAG_IDENTIFIED, code='r01 '), 'r01'),
        )
        for invalid, message in bad:
            try:
                again.place(C.encode_item(invalid, d), ('inv', 0, 0), replace=again.items[6])
            except E.MC.CharError as ex:
                T.check('Classic' in str(ex) and message in str(ex), str(ex))
            else:
                T.check(False, f'Classic must refuse {message}')
            T.eq(again.items, before, 'refused replacement leaves the inventory intact')

        again.remove(again.items[0])
        again.save(backup=False)
        saved = E.MC.Character(path, d)
        T.eq(saved.version, 71, 'version kept')
        T.eq(len(saved.items), len(ch.items), 'one paste and one delete')
        actual, _ = early.decode_classic(saved._old_blob(saved.items[5]))
        T.eq(actual, dict(want, durability=native['durability'] - 1, quantity=quantity),
             'durability and quantity persisted, including the original seed and reserved bits')
        T.eq(saved.items[-1].it['code'], 'hp1 ', 'Creator item re-read')
        T.eq(E.MC.where_of(saved.items[-1]), ('inv', 3, 0), 'Creator location re-read')


@T.test
def classic_import_places_supported_items_and_reports_refusals():
    E = engine()
    import mxl_import as importer

    template = os.path.join(T.REPO, '.cache', 'samples', 'oldver', '100', 'Ashbow.d2s')
    page = os.path.join(T.tmp(), 'classic-items.json')
    items = [
        dict(location='Inventory', col=0, row=0, code='hp1', quality='normal', display_name='Potion'),
        dict(location='Stash', col=0, row=0, code='isc', quality='normal', display_name='Scroll'),
        dict(location='Inventory', col=1, row=0, code='r01', quality='normal', display_name='El Rune'),
    ]
    with open(page, 'w', encoding='utf-8') as f:
        json.dump(items, f)
    path, report = importer.import_character(page, template, T.tmp(), 'ClassicImport', E.data, cls_name='Amazon')
    ch = E.MC.Character(path, E.data)
    T.eq(ch.version, 71, 'import keeps Classic version')
    T.eq(ch._classic_original, True, 'import keeps original row-index layout')
    T.eq([(e.it['code'], E.MC.where_of(e)) for e in ch.items],
         [('hp1 ', ('inv', 0, 0)), ('isc ', ('store', 5, 0, 0))], 'supported imports re-read')
    T.check(any('El Rune' in line and 'Classic' in line and 'r01' in line for line in report), repr(report))


T.main(globals())
