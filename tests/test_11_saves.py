"""Save files: a no-op load / save of every sample character and stash gives the same bytes; the character
checksum is verified with an implementation written in the test helper (capytest.d2_checksum)."""
import glob
import os
import struct

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')


def sample_dirs():
    """Fresh copies of every sample folder there is."""
    out = [T.fresh_saves(1)]
    if T.saves_ok(T.SRC_SAVES2):
        out.append(T.fresh_saves(2))
    return out


def files(folder, *patterns):
    return sorted(p for pat in patterns for p in glob.glob(os.path.join(folder, pat)))


@T.test
def character_noop_build_identical():
    E = T.engine()
    n = 0
    for folder in sample_dirs():
        for p in files(folder, '*.d2s', '*.d2s.bak-*'):
            raw = T.read(p)
            ch = E.MC.Character(p, E.data)
            T.check(ch.build() == raw, f'no-op build differs: {os.path.basename(p)}')
            T.check(ch.level_consistent(), f'level in the header and in the stats differ: {os.path.basename(p)}')
            n += 1
    T.check(n >= 1, 'no character file found')


@T.test
def character_noop_save_identical():
    """Character.save() of an untouched character, and of one whose every field was set to its own value."""
    E = T.engine()
    MC = E.MC
    for folder in sample_dirs():
        for p in files(folder, '*.d2s'):
            raw = T.read(p)
            ch = MC.Character(p, E.data)
            ch.stat_fields()
            ch.flags()
            ch.save(backup=False)
            T.check(T.read(p) == raw, f'no-op save changed {os.path.basename(p)}')
            ch = MC.Character(p, E.data)
            for k in MC.FIELD_KEYS:
                ch.set_field(k, ch.field(k))
            ch.set_flags(**ch.flags())
            ch.set_progression(ch.progression)
            ch.set_difficulties_done(ch.difficulties_done)
            ch.save(backup=False)
            T.check(T.read(p) == raw, f'setting every field to its own value changed {os.path.basename(p)}')


@T.test
def character_checksum_and_size_independent():
    n = 0
    for folder in sample_dirs():
        for p in files(folder, '*.d2s', '*.d2s.bak-*'):
            for problem in T.d2s_header_ok(T.read(p)):
                T.check(False, f'{os.path.basename(p)}: {problem}')
            n += 1
    T.check(n >= 1, 'no character file found')


@T.test
def checksum_matches_application():
    """The application's own checksum function agrees with the independent one, also on changed bytes."""
    E = T.engine()
    folder = sample_dirs()[0]
    raw = bytearray(T.read(files(folder, '*.d2s')[0]))
    for i in (0, 1, 2):
        raw[0x30 + i * 7] ^= 0x5A
        mine = T.d2_checksum(bytes(raw))
        theirs = E.MC.checksum(bytes(raw))
        if isinstance(theirs, (bytes, bytearray)):
            theirs = struct.unpack('<I', bytes(theirs)[:4])[0]
        T.eq(theirs, mine, f'checksum after change {i}')


@T.test
def character_items_reencode_identical():
    E = T.engine()
    n = 0
    for folder in sample_dirs():
        for p in files(folder, '*.d2s'):
            ch = E.MC.Character(p, E.data)
            for e in ch.items + (ch.merc_items or []):
                rec, size = E.C.decode_item(bytes(e.blob), E.data)
                T.check(E.C.encode_item(rec, E.data) == bytes(e.blob)[:size],
                        f'{os.path.basename(p)} {e.it["code"]!r}: decode -> encode differs')
                n += 1
    T.check(n > 20, f'only {n} character items checked')


@T.test
def stash_noop_rebuild_identical():
    """parse -> the item bytes per page -> build_stash gives the file again."""
    E = T.engine()
    n = 0
    for folder in sample_dirs():
        for p in files(folder, '*.stash', '*.stash.bak-*', '*.shared'):
            raw = T.read(p)
            items = E.save.parse_stash(p, E.data)
            again = E.save.build_stash(raw[:8], E.save.stash_blobs(raw, items))
            T.check(bytes(again) == raw, f'no-op stash rebuild differs: {os.path.basename(p)} ({len(items)} items, '
                    f'{len(again)} vs {len(raw)} bytes)')
            n += 1
    T.check(n >= 2, f'only {n} stash files found')


@T.test
def stash_noop_write_identical():
    """The application's stash writer with nothing to remove and nothing to insert."""
    E = T.engine()
    for folder in sample_dirs():
        for p in files(folder, '*.stash', '*.shared'):
            raw = T.read(p)
            E.save.edit_stash(p, E.data, remove=[], insert=[], backup=False)
            T.check(T.read(p) == raw, f'empty edit_stash changed {os.path.basename(p)}')


@T.test
def stash_items_reencode_identical():
    E = T.engine()
    n = 0
    for folder in sample_dirs():
        for p in files(folder, '*.stash', '*.shared'):
            raw = T.read(p)
            for it in E.save.parse_stash(p, E.data):
                blob = bytes(E.save.item_blob(raw, it))
                rec, size = E.C.decode_item(blob, E.data)
                T.check(E.C.encode_item(rec, E.data) == blob[:size],
                        f'{os.path.basename(p)} {it["code"]!r} at {it["page"], it["x"], it["y"]}: decode -> encode differs')
                again = E.save.blob_item(blob, E.data)
                T.eq(T.stats_of(again), T.stats_of(it), f'{it["code"]!r}: stats of the lone item bytes')
                n += 1
    T.check(n > 100, f'only {n} stash items checked')


@T.test
def stash_remove_and_reinsert_identical():
    """Taking an item out and putting the same bytes back at the same place restores the file."""
    E = T.engine()
    folder = sample_dirs()[0]
    p = files(folder, '*.stash')[0]
    raw = T.read(p)
    items = E.save.parse_stash(p, E.data)
    before = T.stash_snap(p, E.data)
    for it in (items[0], items[len(items) // 2], items[-1]):
        cur = next(i for i in E.save.parse_stash(p, E.data) if (i['page'], i['x'], i['y']) == (it['page'], it['x'], it['y']))
        blob = bytes(E.save.item_blob(E.save.read_file(p), cur))
        E.save.edit_stash(p, E.data, remove=[cur['_offset']], backup=False)
        gone = T.stash_snap(p, E.data)
        T.only_changed(before, gone, gone=[(it['page'], it['x'], it['y'])], what='after the removal')
        E.save.edit_stash(p, E.data, insert=[(it['page'], it['x'], it['y'], blob)], backup=False)
        T.eq(T.stash_snap(p, E.data), before, 'items after putting it back')
    T.eq(len(T.read(p)), len(raw), 'file size after the round trip')


T.main(globals())
