"""Save safety: property tests over every item and character of the samples, through the editor's real code paths
(mxl_char, mxl_creator, mxl_stash_order, mxl_undo, mxl_savecheck, the collector's safe writer) with the independent
parser mxlsave as the judge. Findings and their history: docs/review/save-safety.md."""
import glob
import os
import struct

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')


def sample_dirs():
    out = [T.fresh_saves(1)]
    if T.saves_ok(T.SRC_SAVES2):
        out.append(T.fresh_saves(2))
    return out


def files(folder, *patterns):
    return sorted(p for pat in patterns for p in glob.glob(os.path.join(folder, pat)))


_tables = []
_stack = []


def eng():
    """The engine with the application's write stack: the stash order writer and the independent save check
    (strict) around the collector's commit_file, as mxl_creator_gui.run() installs them."""
    E = T.engine()
    if not _stack:
        import mxl_stash_order
        import mxl_savecheck
        mxl_stash_order.install()
        mxl_savecheck.install()
        _stack.append(mxl_savecheck.mode())
    return E


def tables():
    if not _tables:
        E = eng()
        import mxl_savecheck
        mxl_savecheck.lib()
        import mxlsave
        _tables.append(mxlsave.Tables(E.data.folder))
    return _tables[0]


def independent(path_or_bytes, kind=None):
    """[problems] of a file (or bytes) for the independent parser mxlsave."""
    from mxlsave.check import check_bytes
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
    else:
        data = T.read(path_or_bytes)
        kind = kind or ('d2s' if path_or_bytes.endswith('.d2s') else 'stash')
    _obj, problems = check_bytes(data, kind, tables())
    return problems


def all_item_blobs(folder):
    """[(file, where, blob)] of every top-level item of every character / stash file of a folder (with its
    socketed items behind it)."""
    E = eng()
    out = []
    for p in files(folder, '*.d2s'):
        ch = E.MC.Character(p, E.data)
        for merc in (False, True):
            for e in ch.entries(merc):
                out.append((os.path.basename(p), 'merc' if merc else 'char', bytes(e.blob)))
    for p in files(folder, '*.stash', '*.shared'):
        buf = E.save.read_file(p)
        for it in E.save.parse_stash(p, E.data):
            out.append((os.path.basename(p), 'stash', bytes(E.save.item_blob(buf, it))))
    return out


# ------------------------------------------------------------------------------------------ items
@T.test
def every_item_decodes_and_encodes_to_its_own_bytes():
    """mxl_creator.decode_item -> encode_item of every item (and every socketed item) of every sample file gives
    the same bytes: every right-click action and every edit goes through this pair."""
    E = eng()
    n = 0
    for folder in sample_dirs():
        for fn, where, blob in all_item_blobs(folder):
            pos = 0
            while pos < len(blob):
                rec, size = E.C.decode_item(blob[pos:], E.data)
                again = E.C.encode_item(rec, E.data)
                T.check(again == blob[pos:pos + size], f'{fn} {where} {rec.get("code")}: decode/encode changes '
                        f'the bytes ({size} -> {len(again)})')
                pos += size
                n += 1
    T.check(n > 100, f'only {n} items')


# ------------------------------------------------------------------------------------------ character values
def chars():
    E = eng()
    for folder in sample_dirs():
        for p in files(folder, '*.d2s'):
            yield E, p


def save_reload(E, ch, what):
    """Character.save, then a fresh read by both parsers; returns the new Character."""
    ch.save(backup=False)
    probs = independent(ch.path)
    T.check(not probs, f'{what}: the independent parser refuses the file: {probs}')
    for problem in T.d2s_header_ok(T.read(ch.path)):
        T.check(False, f'{what}: {problem}')
    return E.MC.Character(ch.path, E.data)


@T.test
def every_field_at_its_limits_round_trips_and_reverts():
    """Every stat-screen field set to its lowest and highest storable value: saved, read back the same by
    both parsers; set back to the original value: the file is byte-identical to the original."""
    for E, p in chars():
        raw = T.read(p)
        ch = E.MC.Character(p, E.data)
        for fd in ch.stat_fields():
            orig = fd.raw
            for v in (fd.min, fd.max, fd.min + 1, fd.max - 1):
                ch = E.MC.Character(p, E.data)
                ch.set_field(fd.key, v)
                ch2 = save_reload(E, ch, f'{fd.key}={v}')
                T.eq(ch2.field(fd.key), v, f'{fd.key}: read back')
                # the stored integer (life / mana / stamina keep 1/256 points: set_field with whole points
                # after a change drops that fraction - cosmetic, see docs/review/save-safety.md)
                ch2.set_field_raw(fd.key, orig)
                ch2.save(backup=False)
                if T.read(p) != raw:
                    T.check(False, f'{os.path.basename(p)}: {fd.key} raw {orig} -> {v} -> raw {orig} leaves other bytes')
                    with open(p, 'wb') as f:
                        f.write(raw)


def _parse_bytes(E, raw):
    ch = E.MC.Character.__new__(E.MC.Character)
    ch.data, ch.path = E.data, None
    ch.raw = raw
    ch.parse(raw)
    return ch


SKILL_PATTERNS = ('all 255', 'all 0', '74 77 alternating', '74 77 first two')


def _skill_pattern(name, ids):
    return {'all 255': {s: 255 for s in ids}, 'all 0': {s: 0 for s in ids},
            '74 77 alternating': {ids[i]: (74 if i % 2 == 0 else 77) for i in range(len(ids))},
            '74 77 first two': {ids[0]: 74, ids[1]: 77}}[name]


@T.test
def skills_at_limits_parse_back():
    """Skill levels 0 / 255, and neighbours 74, 77 (the bytes of the item list's marker 'JM'): the editor's own
    reader (mxl_char) and the independent one read the built file back the same. (mxl_char looked for the first
    'JM' after the skills marker and cut the skills section there: F3.)"""
    for E, p in chars():
        ch = E.MC.Character(p, E.data)
        ids = list(ch.skill_levels())
        for name in SKILL_PATTERNS:
            pattern = _skill_pattern(name, ids)
            ch = E.MC.Character(p, E.data)
            ch.set_skill_levels(pattern)
            out = ch.build()
            T.check(not independent(out, 'd2s'), f'skills {name}: independent parser: {independent(out, "d2s")}')
            try:
                back = _parse_bytes(E, out)
            except Exception as e:
                T.check(False, f'skills {name}: mxl_char cannot read it: {type(e).__name__}: {e}')
                continue
            T.eq({k: v for k, v in back.skill_levels().items() if k in pattern}, pattern, f'skills {name} read back')
            T.eq(len(back.items), len(ch.items), f'skills {name}: items')
            T.check(back.build() == out, f'skills {name}: rebuild differs')


# The collector's own reader (host mxl_save.load_character) looks for the first 'JM' after the first 'if' of the
# file; Character.save runs it as part of its verification, so a save with skill levels 74 and 77 side by side was
# refused (file left as it was). mxl_char.install_reader_fix hands it masked bytes: F4.
@T.test
def skills_74_77_can_be_saved():
    for E, p in chars():
        raw = T.read(p)
        ch = E.MC.Character(p, E.data)
        ids = list(ch.skill_levels())
        ch.set_skill_levels(_skill_pattern('74 77 first two', ids))
        try:
            save_reload(E, ch, 'skills 74 77')
        except Exception as e:
            T.eq(T.read(p), raw, 'a refused save leaves the file as it was')
            T.check(False, f'skills 74, 77: {type(e).__name__}: {e}')


@T.test
def quest_rewards_near_the_stat_limits():
    """Marking every quest done (with rewards) on a character whose life / points are at the storable maximum
    must not make the save fail or wrap."""
    for E, p in chars():
        ch = E.MC.Character(p, E.data)
        for k in ('life_cur', 'life_max', 'stat_points', 'skill_points'):
            ch.set_field(k, ch.stat_field(k).max)
        for diff in range(3):
            words = {w for _a, _i, qs, _t in E.MC.ACTS for w, _ in qs}
            ch.set_quests(diff, words)
        try:
            save_reload(E, ch, 'all quests at max stats')
        except Exception as e:
            T.check(False, f'{os.path.basename(p)}: quests done at max life/points: {type(e).__name__}: {e}')


@T.test
def level_up_to_the_top_saves():
    """set_level from the current level to the table's top (the game's own gains) saves and reads back."""
    for E, p in chars():
        ch = E.MC.Character(p, E.data)
        top = E.MC.max_level(E.data, ch.cls)
        try:
            ch.set_level(top)
            ch2 = save_reload(E, ch, f'level {top}')
            T.eq(ch2.level, top, 'level read back')
        except Exception as e:
            T.check(False, f'{os.path.basename(p)}: level up to {top}: {type(e).__name__}: {e}')
        for lvl in (1, top):
            ch = E.MC.Character(p, E.data)
            ch.set_level_raw(lvl)
            ch2 = save_reload(E, ch, f'raw level {lvl}')
            T.check(ch2.level == lvl and ch2.level_consistent(), f'raw level {lvl}')


@T.test
def flags_and_waypoints_toggled_and_back_are_identical():
    """(Quests are not part of this: unmarking and marking again across two saves is not a no-op by design -
    rewards, act introduction words; see docs/review/save-safety.md, F9.)"""
    for E, p in chars():
        raw = T.read(p)
        ch = E.MC.Character(p, E.data)
        fl = ch.flags()
        for k in fl:
            ch.set_flag(k, not fl[k])
            ch.set_flag(k, fl[k])
        for diff in range(3):
            act = [n for n in E.MC.ALL_WAYPOINTS if ch.waypoint(diff, n)]
            ch.set_waypoints(diff, set(E.MC.ALL_WAYPOINTS))
            ch.set_waypoints(diff, set(act))
        T.check(ch.build() == raw, f'{os.path.basename(p)}: flags / waypoints toggled and back differ')


@T.test
def names_with_marker_letters():
    """Names holding the letters of a section marker ('gf' = stats, 'if' = skills, 'JM' = items): the
    character can be renamed, saved and read by every reader."""
    E = eng()
    for new in ('Bigfoot', 'Clifford', 'JMax', 'Ajmo'):
        folder = T.fresh_saves()
        p = os.path.join(folder, 'XBone.d2s')
        ch = E.MC.Character(p, E.data)
        try:
            dst, _bak = ch.rename(new, backup=False)
        except Exception as e:
            T.check(False, f'rename to {new}: {type(e).__name__}: {e}')
            continue
        try:
            E.save.load_character(dst, E.data)
        except Exception as e:
            T.check(False, f'{new}: the collector cannot read the file: {type(e).__name__}: {e}')
        ch = E.MC.Character(dst, E.data)
        ch.set_field('gold', 1234)
        try:
            ch.save(backup=False)
        except Exception as e:
            T.check(False, f'{new}: save: {type(e).__name__}: {e}')


@T.test
def marker_bytes_in_fixed_sections_differential():
    """The bytes of a section marker ('gf', 'if', 'JM', 'jf', 'kf') written into the name, the NPC bits, the
    quest and waypoint bytes: mxl_char reads the same stats, skills and item counts as the independent parser
    (mxl_char searched 'gf' from the NPC section on: F2), and so does the collector's reader through
    mxl_char.install_reader_fix (F5)."""
    E = eng()
    from mxlsave.d2s import D2S
    for _E, p in chars():
        raw = T.read(p)
        ref_c = E.save.load_character(p, E.data)          # the collector's totals for the untouched file
        for marker in (b'gf', b'if', b'JM', b'jf', b'kf'):
            for off in (0x14 + 1, 0x2C9 + 4, 0x2C9 + 40, 0x2FB, 0x159 + 60, 0x281 + 10):
                b = bytearray(raw)
                b[off:off + 2] = marker
                b[0x14:0x24] = bytes(b[0x14:0x24]).split(b'\0')[0][:15].ljust(16, b'\0')
                struct.pack_into('<I', b, 12, E.MC.checksum(b))
                b = bytes(b)
                ref = D2S.parse(b, tables())
                try:
                    ch = _parse_bytes(E, b)
                except Exception as e:
                    T.check(False, f'{marker} at {off:#x}: mxl_char: {type(e).__name__}: {e}')
                    continue
                T.eq([(st[0], st[1] or 0, st[2]) for st in ch.stats],
                     [(st.id, st.param or 0, st.value) for st in ref.stats], f'{marker} at {off:#x}: stats')
                T.eq(bytes(ch.skills[2:]), bytes(ref.skills), f'{marker} at {off:#x}: skills')
                T.eq(len(ch.items), len(ref.items), f'{marker} at {off:#x}: items')
                T.check(ch.build() == b, f'{marker} at {off:#x}: rebuild differs')
                tmpf = os.path.join(T.tmp(), 'marker.d2s')
                with open(tmpf, 'wb') as f:
                    f.write(b)
                try:
                    c = E.save.load_character(tmpf, E.data)
                    T.eq([c[k] for k in ('strength', 'energy', 'dexterity', 'vitality')],
                         [ref_c[k] for k in ('strength', 'energy', 'dexterity', 'vitality')],
                         f'{marker} at {off:#x}: collector reader stats')
                    T.eq(c['name'], ch.name, f'{marker} at {off:#x}: collector reader name')
                except Exception as e:
                    T.check(False, f'{marker} at {off:#x}: collector reader: {type(e).__name__}: {e}')


# The collector's reader (host mxl_save.load_character, used for the main window's character: stats shown,
# requirement colours) searched b'gf' from the start of the file: a name holding "gf" (Bigfoot) gave made-up
# strength / dexterity / ... in the main window. Display only; fixed by mxl_char.install_reader_fix: F5.
@T.test
def collector_reads_the_stats_of_a_name_with_gf():
    E = eng()
    folder = T.fresh_saves()
    c0 = E.save.load_character(os.path.join(folder, 'XBone.d2s'), E.data)
    ch = E.MC.Character(os.path.join(folder, 'XBone.d2s'), E.data)
    dst, _bak = ch.rename('Bigfoot', backup=False)
    ch = E.MC.Character(dst, E.data)
    c = E.save.load_character(dst, E.data)
    for key in ('strength', 'dexterity', 'vitality', 'energy'):      # (the collector adds the items' bonuses)
        T.eq(c[key], c0[key], f'collector reader: {key} (as read under the old name)')
    T.eq((c['name'], c['level'], len(c['items'])), ('Bigfoot', c0['level'], len(c0['items'])), 'collector reader: name, level, items')


# ------------------------------------------------------------------------------------------ stash + undo
class FakeApp:
    """What mxl_undo and mxl_stash_order need of the main window."""

    def __init__(self, path, data):
        self.path, self.data, self._undo = path, data, []
        self.items = None
        self.reloaded = 0

    def needs_backup(self, _path):
        return False

    def backup_made(self, *_a):
        pass

    def full_name(self, it):
        return it['code']

    def load(self, *_a, **_k):
        self.items = eng().save.parse_stash(self.path, self.data)

    def reload(self, *_a, **_k):
        self.reloaded += 1
        self.load()


def stash_setup():
    E = eng()
    import mxl_stash_order
    mxl_stash_order.install()
    import mxl_undo
    return E, mxl_stash_order, mxl_undo


@T.test
def undo_brings_back_the_last_item_of_a_page():
    """Delete the only item of a stash page, Ctrl+Z: the item is back and the file is byte-identical. (The page's
    section disappears with its last item; the indexed insert of the undo refused a page without a section and
    the undo step was dropped with the error: the item was gone for good - F1.)"""
    E, SO, U = stash_setup()
    p = os.path.join(T.fresh_saves(), 'XBone.stash')
    items = E.save.parse_stash(p, E.data)
    used = {i['page'] for i in items}
    empty = next(pg for pg in range(E.save.STASH_PAGES) if pg not in used)
    it = items[-1]
    blob = bytes(E.save.item_blob(T.read(p), it))
    E.save.edit_stash(p, E.data, remove=[it['_offset']], insert=[(empty, 0, 0, blob)], backup=False)
    raw = T.read(p)
    app = FakeApp(p, E.data)
    app.load()
    lone = next(i for i in app.items if i['page'] == empty)
    U.delete_item(app, lone)
    T.check(not any(i['page'] == empty for i in E.save.parse_stash(p, E.data)), 'deleted')
    msg = U.undo(app)
    T.check(T.read(p) == raw, f'undo of the last item of a page: file differs ({msg})')
    T.check(not independent(p), 'independent parser')


@T.test
def failed_undo_keeps_its_step():
    """An undo that cannot be done now (no room, a refused write) stays on the undo list."""
    E, SO, U = stash_setup()
    p = os.path.join(T.fresh_saves(), 'XBone.stash')
    app = FakeApp(p, E.data)
    app.load()
    it = app.items[0]
    U.delete_item(app, it)
    import mxl_save
    real = mxl_save.commit_file
    def refuse(*_a, **_k):
        raise mxl_save.EditError('refused for the test')
    try:
        for mod in (mxl_save,):
            mod.commit_file = refuse
        msg = U.undo(app)
    finally:
        mxl_save.commit_file = real
    T.eq(len(app._undo), 1, f'the undo step is kept after "{msg}"')
    U.undo(app)
    T.check(any((i['page'], i['x'], i['y']) == (it['page'], it['x'], it['y']) for i in E.save.parse_stash(p, E.data)),
            'the second undo puts the item back')


@T.test
def stale_view_never_removes_another_item():
    """The window shows the stash as read before another writer (the game saving, with the game-running check
    removed) appended an item to an earlier page: every later item moved by that item's size, so the offset the
    window holds for an item can be the start of its neighbour. Deleting from the old view must not delete the
    neighbour (it did: edit_stash knows an item only by its offset - F6)."""
    E, SO, U = stash_setup()
    p = os.path.join(T.fresh_saves(), 'XBone.stash')
    app = FakeApp(p, E.data)
    app.load()
    SO.watch_view(app)
    raw = T.read(p)
    pages = sorted({i['page'] for i in app.items})
    later = [i for i in app.items if i['page'] == pages[-1]]
    k = next(k for k in range(1, len(later)) if later[k - 1]['_size'] == later[k]['_size']
             and not later[k - 1].get('socketed') and not later[k].get('socketed'))
    prev, victim = later[k - 1], later[k]
    blob_prev = bytes(E.save.item_blob(raw, prev))
    spot = E.save.free_spot(app.items, E.save.blob_item(blob_prev, E.data), E.data, [pages[0]])
    # the other writer: the view is not told
    E.save.commit_file(p, _insert_raw(E, p, spot, blob_prev), lambda tmp: None, False)
    try:
        U.delete_item(app, victim)
    except Exception as e:
        T.check(False, f'delete raised {type(e).__name__}: {e}')
    now = {(i['page'], i['x'], i['y']) for i in E.save.parse_stash(p, E.data)}
    T.check((prev['page'], prev['x'], prev['y']) in now, 'the neighbour of the deleted item is still there')
    T.check((victim['page'], victim['x'], victim['y']) in now, 'nothing was deleted from the out-of-date view')
    T.check(app.reloaded >= 0, 'view reload requested')
    # read again: now the delete works on the right item
    app.load()
    victim2 = next(i for i in app.items if (i['page'], i['x'], i['y']) == (victim['page'], victim['x'], victim['y']))
    U.delete_item(app, victim2)
    now = {(i['page'], i['x'], i['y']) for i in E.save.parse_stash(p, E.data)}
    T.check((victim['page'], victim['x'], victim['y']) not in now and (prev['page'], prev['x'], prev['y']) in now,
            'after reading again the right item is deleted')


def _insert_raw(E, p, spot, blob):
    """The bytes of the stash with blob appended to page spot[0] at (x, y), built without the editor's writer."""
    from mxl_format import write_bits
    buf = E.save.read_file(p)
    items = E.save.parse_stash(p, E.data)
    pages = E.save.stash_blobs(buf, items)
    b = bytearray(blob)
    new = E.save.blob_item(blob, E.data)
    write_bits(b, 16 + new['_pos_bit'], 4, spot[1])
    write_bits(b, 16 + new['_pos_bit'] + 4, 4, spot[2])
    pages.setdefault(spot[0], []).append(bytes(b))
    return E.save.build_stash(buf[:8], pages)


# ------------------------------------------------------------------------------------------ writes, files
@T.test
def interrupted_character_write_keeps_the_old_file():
    """A failure in the middle of a save (the verification refuses, the final rename fails, the disk is full while
    writing the temp file): the character file is the old one, no temp file is left behind."""
    E = eng()
    import mxl_save
    folder = T.fresh_saves()
    p = os.path.join(folder, 'XBone.d2s')
    raw = T.read(p)
    real_replace, real_open = os.replace, open

    def boom_replace(a, b):
        raise OSError(28, 'No space left on device (test)')

    for how in ('replace', 'verify', 'write'):
        ch = E.MC.Character(p, E.data)
        ch.set_field('gold', 4321)
        try:
            if how == 'replace':
                os.replace = boom_replace
                ch.save(backup=False)
            elif how == 'verify':
                real_init = E.MC.Character.__init__
                def bad_init(self, path, data, _real=real_init):
                    if str(path).endswith('.tmp'):
                        raise E.MC.FormatError('simulated')
                    _real(self, path, data)
                E.MC.Character.__init__ = bad_init
                try:
                    ch.save(backup=False)
                finally:
                    E.MC.Character.__init__ = real_init
            else:
                import builtins
                def bad_open(f, mode='r', *a, **k):
                    if str(f).endswith('.tmp') and 'w' in mode:
                        fh = real_open(f, mode, *a, **k)
                        class Half:
                            def __enter__(s):
                                return s
                            def __exit__(s, *e):
                                fh.close()
                            def write(s, data):
                                fh.write(data[:len(data) // 2])
                                raise OSError(28, 'No space left on device (test)')
                            def __getattr__(s, n):
                                return getattr(fh, n)
                        return Half()
                    return real_open(f, mode, *a, **k)
                builtins.open = bad_open
                try:
                    ch.save(backup=False)
                finally:
                    builtins.open = real_open
            T.check(False, f'{how}: the save did not fail')
        except Exception as e:
            _ = e
        finally:
            os.replace = real_replace
        T.check(T.read(p) == raw, f'{how}: the character file changed')
        left = [f for f in os.listdir(folder) if f.endswith('.tmp')]
        T.check(not left, f'{how}: temp files left: {left}')


@T.test
def backup_is_the_file_before_the_write():
    E = eng()
    folder = T.fresh_saves()
    p = os.path.join(folder, 'XBone.d2s')
    raw = T.read(p)
    ch = E.MC.Character(p, E.data)
    ch.set_field('gold', 4321)
    bak = ch.save(backup=True)
    T.check(bak and T.read(bak) == raw, 'the backup holds the previous bytes')


@T.test
def rename_moves_every_companion_and_keeps_the_items():
    E = eng()
    folder = T.fresh_saves()
    p = os.path.join(folder, 'XBone.d2s')
    before = {f: T.read(os.path.join(folder, f)) for f in os.listdir(folder) if f.startswith('XBone.')}
    stash = T.read(os.path.join(folder, 'XBone.stash'))
    ch = E.MC.Character(p, E.data)
    n = len(ch.items)
    dst, bak = ch.rename('Renamed', backup=True)
    after = sorted(os.listdir(folder))
    for f in before:
        ext = f[len('XBone'):]
        if ext == '.d2s' or '.bak-' in ext:
            continue
        T.check('Renamed' + ext in after, f'companion {f} renamed')
        T.check(f not in after, f'old companion {f} gone')
    T.eq(T.read(os.path.join(folder, 'Renamed.stash')), stash, 'stash bytes kept')
    T.check(not os.path.exists(p), 'old .d2s removed')
    T.check(bak and os.path.exists(bak) and T.read(bak) == before['XBone.d2s'], 'backup of the old file kept')
    c2 = E.MC.Character(dst, E.data)
    T.eq((c2.name, len(c2.items)), ('Renamed', n), 'renamed file')
    T.check(not independent(dst), 'independent parser')


@T.test
def rename_failing_half_way_loses_nothing():
    """A companion that cannot be moved (locked by another program on Windows): the character must stay
    loadable under one name with its stash."""
    E = eng()
    folder = T.fresh_saves()
    p = os.path.join(folder, 'XBone.d2s')
    raw = T.read(p)
    stash = T.read(os.path.join(folder, 'XBone.stash'))
    ch = E.MC.Character(p, E.data)
    real = os.replace

    def flaky(a, b):
        if str(a).endswith('.stash'):
            raise PermissionError(13, 'locked (test)')
        return real(a, b)
    os.replace = flaky
    try:
        ch.rename('Renamed', backup=False)
        err = None
    except Exception as e:
        err = e
    finally:
        os.replace = real
    names = sorted(os.listdir(folder))
    have_old = 'XBone.d2s' in names and T.read(p) == raw and 'XBone.stash' in names
    have_new = 'Renamed.d2s' in names and 'Renamed.stash' in names
    old_set = sorted(n for n in names if n.startswith('XBone.') and '.bak-' not in n)
    new_set = sorted(n for n in names if n.startswith('Renamed.'))
    T.check((have_old and not new_set) or (have_new and old_set == []),
            f'after a failed rename ({err!r}) the files are split between two names: {old_set} / {new_set}')
    if err is not None:
        T.eq(ch.name, 'XBone', 'a refused rename leaves the name in memory as it was')
        T.check(isinstance(err, E.MC.CharError), f'refusal as CharError: {err!r}')
    T.check(stash in [T.read(os.path.join(folder, n)) for n in names if n.endswith('.stash')], 'stash bytes kept')


@T.test
def copy_never_overwrites_other_files():
    """Copy a character to a name whose companion file already exists (the stash of a deleted character)."""
    E = eng()
    folder = T.fresh_saves()
    p = os.path.join(folder, 'XBone.d2s')
    orphan = os.path.join(folder, 'Other.stash')
    with open(orphan, 'wb') as f:
        f.write(b'orphan stash')
    try:
        E.MC.copy_character(p, 'Other', E.data)
    except Exception as e:
        _ = e
    T.eq(T.read(orphan), b'orphan stash', 'an existing Other.stash is not overwritten')


@T.test
def copy_refuses_names_the_game_refuses():
    E = eng()
    folder = T.fresh_saves()
    p = os.path.join(folder, 'XBone.d2s')
    for bad in ('Zoé', '_Lead', 'Two--', 'a-b_c'):
        try:
            E.MC.copy_character(p, bad, E.data)
            T.check(False, f'copy to {bad!r} accepted')
        except E.MC.CharError:
            pass
        except Exception as e:
            T.check(False, f'copy to {bad!r}: {type(e).__name__}: {e}')


# ------------------------------------------------------------------------------------------ web-page import
def _import_empty(name, folder):
    E = eng()
    import mxl_import
    page = os.path.join(T.tmp(), 'empty-page.json')
    with open(page, 'w') as f:
        f.write('[]')
    cls = next(iter(mxl_import.CLASS_INDEX))
    return mxl_import.import_character(page, os.path.join(folder, 'XBone.d2s'), folder, name, E.data, cls_name=cls,
                                       level=1, quests=[])


@T.test
def import_never_overwrites_other_files():
    """An import whose name has a file left in the folder (the stash of a deleted character)."""
    folder = T.fresh_saves()
    orphan = os.path.join(folder, 'Newbie.stash')
    with open(orphan, 'wb') as f:
        f.write(b'orphan stash')
    try:
        _import_empty('Newbie', folder)
    except Exception as e:
        _ = e
    T.eq(T.read(orphan), b'orphan stash', 'an existing Newbie.stash is not overwritten')


@T.test
def imported_character_starts_empty():
    """A character imported from a page with no items holds no item of the character it was made from: no
    mercenary items, no stash items, no achievement counters / signets (stats 88, 185, 186), no waypoints."""
    E = eng()
    folder = T.fresh_saves()
    dst, _report = _import_empty('Newbie', folder)
    T.check(not independent(dst), f'independent parser: {independent(dst)}')
    ch = E.MC.Character(dst, E.data)
    T.check(not ch.merc_hired, 'a mercenary of the template')
    T.eq(len(ch.items), 0, 'items')
    T.eq(len(ch.merc_items or ()), 0, 'mercenary items copied from the template')
    st = os.path.join(folder, 'Newbie.stash')
    n = len(E.save.parse_stash(st, E.data)) if os.path.exists(st) else 0
    T.eq(n, 0, 'stash items copied from the template')
    T.eq(sorted({s for s, _p, _v in ch.stats if s in (88, 185, 186)}), [], 'counters / signets of the template')
    T.eq([n for n in E.MC.ALL_WAYPOINTS if n and any(ch.waypoint(d, n) for d in range(3))], [], 'waypoints')


@T.test
def a_short_lock_is_tried_again():
    """The final rename refused once with PermissionError (Windows: a virus scanner or sync client holding the
    file for a moment): the save goes through on the next try; refused every time: the old file stays, no
    temp file is left."""
    E = eng()
    folder = T.fresh_saves()
    p = os.path.join(folder, 'XBone.d2s')
    raw = T.read(p)
    real = os.replace
    calls = []

    def locked(a, b, n):
        calls.append(a)
        if len(calls) <= n:
            raise PermissionError(13, 'locked (test)')
        return real(a, b)
    for n, ok in ((1, True), (99, False)):
        calls.clear()
        ch = E.MC.Character(p, E.data)
        ch.set_field('gold', 1000 + n)
        os.replace = lambda a, b, n=n: locked(a, b, n)
        try:
            ch.save(backup=False)
            saved = True
        except Exception:
            saved = False
        finally:
            os.replace = real
        T.eq(saved, ok, f'locked {n} time(s): saved')
        if ok:
            T.eq(E.MC.Character(p, E.data).field('gold'), 1000 + n, 'gold written')
            raw = T.read(p)
        else:
            T.check(T.read(p) == raw, 'a refused save left the file as it was')
        T.check(not [f for f in os.listdir(folder) if f.endswith('.tmp')], 'temp file left')


T.main(globals())
