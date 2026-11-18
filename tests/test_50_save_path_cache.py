"""The save path on a big stash (docs/review/performance.md R1, docs/review/save-safety.md): the parsed-stash cache of
mxl_stash_order and the content-keyed cache of mxl_savecheck's old side, and that neither weakens a check:
- the cache answers exactly what the collector's parser answers, for the bytes on the disk NOW (an outside rewrite is
  seen at once), and every caller gets its own copy;
- every write still parses its temp file with the collector's parser (the writers' verification) and still checks
  the NEW bytes with the independent mxlsave, with both caches warm;
- corrupted writes are still refused (savecheck, and the writer's own verification), the file untouched;
- Copy / Duplicate / Export / Item stats read an item through mxl_stash_order.item_now: refused from an out-of-date
  view (the offset now holds a neighbour of the same size).
Timing of one Duplicate on a full stash (1340 items) is printed, not asserted."""
import glob
import os
import shutil
import time

import capytest as T

MODE = 'engine'
NEEDS = ('user', 'saves')

_ready = []


def eng():
    E = T.engine()
    if not _ready:
        import mxl_speed
        import mxl_stash_order
        import mxl_savecheck
        mxl_speed.install()
        mxl_stash_order.install()
        mxl_savecheck.install()
        _ready.append(1)
    return E


def stash_copy(name='S.stash'):
    src = sorted(glob.glob(os.path.join(T.fresh_saves(1), '*.stash')))
    if not src:
        T.skip('no .stash in the sample')
    return src[0]


def full_stash(E, path, n=1340):
    """Fills the stash at `path` with copies of its own items up to n items (or until it is full)."""
    from mxl_format import write_bits
    save, data = E.save, E.data
    raw = save.read_file(path)
    items = save.parse_stash(path, data)
    blobs = [bytes(save.item_blob(raw, i)) for i in items]
    pages = save.stash_blobs(raw, items)
    placed = list(items)
    k = misses = 0
    while len(placed) < n and misses < len(blobs):
        b = blobs[k % len(blobs)]
        k += 1
        probe = save.blob_item(b, data)
        spot = save.free_spot(placed, probe, data)
        if spot is None:
            misses += 1
            continue
        misses = 0
        bb = bytearray(b)
        write_bits(bb, 16 + probe['_pos_bit'], 4, spot[1])
        write_bits(bb, 16 + probe['_pos_bit'] + 4, 4, spot[2])
        probe['page'], probe['x'], probe['y'] = spot
        placed.append(probe)
        pages.setdefault(spot[0], []).append(bytes(bb))
    with open(path, 'wb') as f:
        f.write(save.build_stash(raw[:8], pages))
    return len(placed)


def plain(items):
    """Comparable form of a parsed item list (types kept)."""
    def conv(o):
        if isinstance(o, dict):
            return (type(o).__name__, sorted((k, conv(v)) for k, v in dict.items(o)))
        if isinstance(o, (list, tuple)):
            return (type(o).__name__, [conv(v) for v in o])
        return o
    return conv(items)


class Counting:
    """Counts the collector-parser calls of the cache (per path suffix) and mxlsave's check_bytes calls."""

    def __init__(self):
        import mxl_stash_order as SO
        import mxlsave.check as MC
        self.SO, self.MC = SO, MC
        self.parsed, self.checked = [], []
        self._pb, self._cb = SO._parse_bytes, MC.check_bytes

    def __enter__(self):
        def pb(orig, path, buf, data):
            self.parsed.append((str(path), bytes(buf)))
            return self._pb(orig, path, buf, data)

        def cb(data, kind, tables):
            self.checked.append(bytes(data))
            return self._cb(data, kind, tables)
        self.SO._parse_bytes, self.MC.check_bytes = pb, cb
        return self

    def __exit__(self, *a):
        self.SO._parse_bytes, self.MC.check_bytes = self._pb, self._cb


@T.test
def cache_gives_the_parsers_answer_and_a_copy_each_time():
    E = eng()
    import mxl_stash_order as SO
    import mxl_save
    orig = SO._cache['orig']
    T.check(orig is not None and getattr(mxl_save.parse_stash, '_capy_cached', False), 'the cache is not installed')
    folder = T.fresh_saves(1)
    for path in sorted(glob.glob(os.path.join(folder, '*.stash')) + glob.glob(os.path.join(folder, '*.shared'))):
        want = plain(orig(path, E.data))
        a = mxl_save.parse_stash(path, E.data)
        b = mxl_save.parse_stash(path, E.data)
        T.check(plain(a) == want and plain(b) == want, f'{os.path.basename(path)}: cached parse differs')
        if not a:
            continue
        T.check(a is not b and a[0] is not b[0] and a[0]['stats'] is not b[0]['stats'], 'callers share objects')
        a[0]['x'] = 99
        a[0]['stats'].append({'id': -1})
        a.pop()
        T.check(plain(mxl_save.parse_stash(path, E.data)) == want, 'a caller\'s change reached the cache')


@T.test
def an_outside_rewrite_is_seen_at_once():
    """Same size, same modification time: only the bytes differ. The next parse is of the new bytes."""
    E = eng()
    import mxl_save
    path = stash_copy()
    raw = T.read(path)
    items = mxl_save.parse_stash(path, E.data)
    st = os.stat(path)
    blobs = mxl_save.stash_blobs(raw, items)
    page = max(blobs, key=lambda p: len(blobs[p]))
    if len(blobs[page]) < 2:
        T.skip('no page with two items')
    blobs[page] = blobs[page][1:] + blobs[page][:1]             # same items, another order: same size
    new = mxl_save.build_stash(raw[:8], blobs)
    T.eq(len(new), len(raw), 'size')
    with open(path, 'wb') as f:
        f.write(new)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    after = mxl_save.parse_stash(path, E.data)
    T.check([i['_offset'] for i in after] != [i['_offset'] for i in items] or
            [(i['page'], i['x'], i['y']) for i in after] != [(i['page'], i['x'], i['y']) for i in items],
            'the parse after the outside rewrite is the old one')
    import mxl_stash_order as SO
    T.check(plain(after) == plain(SO._cache['orig'](path, E.data)), 'not the parser\'s answer for the new bytes')


def one_duplicate(E, path, it=None):
    save = E.save
    items = save.parse_stash(path, E.data)
    it = it or items[0]
    buf = save.read_file(path)
    blob = bytes(save.item_blob(buf, it))
    spot = save.free_spot(items, save.blob_item(blob, E.data), E.data)
    if spot is None:
        T.skip('the stash is full')
    save.edit_stash(path, E.data, insert=[(spot[0], spot[1], spot[2], blob)], backup=False)
    return spot


@T.test
def every_write_is_still_verified_and_checked():
    """With both caches warm (a write before): the temp file is parsed by the collector's parser, and mxlsave
    checks the new bytes, once per write each."""
    E = eng()
    path = stash_copy()
    one_duplicate(E, path)                                      # warm
    for k in range(3):
        before = T.read(path)
        with Counting() as c:
            one_duplicate(E, path)
        now = T.read(path)
        T.check(now != before, 'nothing written')
        tmp = [p for p, b in c.parsed if p.endswith('.tmp')]
        T.eq(len(tmp), 1, f'write {k + 1}: parses of the temp file by the collector\'s parser')
        T.check(any(b == now for p, b in c.parsed if p.endswith('.tmp')), 'the temp file parsed is not the new file')
        T.eq(sum(1 for b in c.checked if b == now), 1, f'write {k + 1}: mxlsave checks of the new bytes')
        T.eq(sum(1 for b in c.checked if b == before), 0, f'write {k + 1}: the old bytes checked again (cache cold?)')


@T.test
def corrupted_writes_are_refused_with_warm_caches():
    E = eng()
    import mxl_save
    import mxl_savecheck as SC
    path = stash_copy()
    one_duplicate(E, path)
    one_duplicate(E, path)
    raw = T.read(path)

    def broken(path_, content):                                 # the first page marker: mxlsave refuses
        if str(path_).endswith('.stash'):
            b = bytearray(content)
            b[8:13] = b'XXXXX'
            return bytes(b)
        return content
    SC.TEST_HOOK = broken
    try:
        try:
            one_duplicate(E, path)
            T.check(False, 'a broken stash was written')
        except mxl_save.EditError:
            pass
    finally:
        SC.TEST_HOOK = None
    T.check(T.read(path) == raw, 'the file changed (savecheck)')
    T.check(not os.path.exists(path + '.tmp'), 'temp file left')

    def dropped(path_, content):                               # a valid stash with one item less: only the
        if not str(path_).endswith('.stash'):                   # writer's own verification (count) can see it
            return content
        items = mxl_save.parse_stash(path_, E.data)
        blobs = mxl_save.stash_blobs(content, SC_items(content))
        p = max(blobs, key=lambda q: len(blobs[q]))
        blobs[p] = blobs[p][:-2]
        _ = items
        return mxl_save.build_stash(content[:8], blobs)

    def SC_items(content):
        tmp = os.path.join(T.tmp(), 'probe.stash')
        with open(tmp, 'wb') as f:
            f.write(content)
        return mxl_save.parse_stash(tmp, E.data)
    SC.TEST_HOOK = dropped
    try:
        try:
            one_duplicate(E, path)
            T.check(False, 'a stash with items missing was written')
        except mxl_save.EditError:
            pass
    finally:
        SC.TEST_HOOK = None
    T.check(T.read(path) == raw, 'the file changed (verification)')


@T.test
def savecheck_old_side_comes_from_the_cache_only_for_the_same_bytes():
    """The old side's parse is reused for identical bytes only: a file rewritten from outside between two writes
    is parsed again (its diff is of the real old file)."""
    E = eng()
    import mxl_save
    import mxl_savecheck as SC
    path = stash_copy()
    one_duplicate(E, path)
    raw = T.read(path)
    items = mxl_save.parse_stash(path, E.data)
    blobs = mxl_save.stash_blobs(raw, items)
    p = max(blobs, key=lambda q: len(blobs[q]))
    blobs[p] = blobs[p][:-1]
    outside = mxl_save.build_stash(raw[:8], blobs)
    with open(path, 'wb') as f:
        f.write(outside)
    with Counting() as c:
        one_duplicate(E, path)
    T.eq(sum(1 for b in c.checked if b == outside), 1, 'the outside file (old side) checked by mxlsave')
    T.check('-1' in SC._state['last'].summary or 'items' in SC._state['last'].summary,
            f'diff summary: {SC._state["last"].summary}')


class FakeView:
    def __init__(self, path, items):
        self.path, self.items = path, items
        self.reloads = 0

        class R:
            def after_idle(_s, fn):
                fn()
        self.root = R()

    def reload(self):
        self.reloads += 1


@T.test
def item_now_refuses_a_neighbour_from_an_out_of_date_view():
    """The stash is rewritten with one more item on the first page (another writer); a view of before still shows
    the old offsets. item_now (Copy / Duplicate / Export / Item stats) must not hand out the neighbour's bytes."""
    E = eng()
    import mxl_save
    import mxl_stash_order as SO
    from mxl_format import write_bits
    path = stash_copy()
    raw = T.read(path)
    items = mxl_save.parse_stash(path, E.data)
    pages = sorted({i['page'] for i in items})
    later = [i for i in items if i['page'] == pages[-1]]
    k = next((k for k in range(1, len(later)) if later[k - 1]['_size'] == later[k]['_size']
              and not later[k - 1].get('socketed') and not later[k].get('socketed')), None)
    if k is None or len(pages) < 2:
        T.skip('no two neighbours of the same size on a later page')
    view = FakeView(path, items)
    SO.watch_view(view)
    prev, victim = later[k - 1], later[k]
    T.eq(SO.item_now(path, E.data, victim, view)[3], bytes(mxl_save.item_blob(raw, victim)), 'fresh view: the item')
    blob = bytes(mxl_save.item_blob(raw, prev))
    new = mxl_save.blob_item(blob, E.data)
    spot = mxl_save.free_spot(items, new, E.data, [pages[0]])
    b = bytearray(blob)
    write_bits(b, 16 + new['_pos_bit'], 4, spot[1])
    write_bits(b, 16 + new['_pos_bit'] + 4, 4, spot[2])
    blobs = mxl_save.stash_blobs(raw, items)
    blobs[spot[0]].append(bytes(b))
    with open(path, 'wb') as f:
        f.write(mxl_save.build_stash(raw[:8], blobs))
    try:
        got = SO.item_now(path, E.data, victim, view)
        T.check(False, f'item_now answered from an out-of-date view ({"the neighbour" if got[3] == blob else "?"})')
    except mxl_save.EditError as e:
        T.check('changed on disk' in str(e), f'message: {e}')
    T.check(view.reloads >= 1, 'the view was not asked to read the stash again')
    view.items = mxl_save.parse_stash(path, E.data)               # the view read it again: fine now
    fresh = next(i for i in view.items if (i['page'], i['x'], i['y']) == (victim['page'], victim['x'], victim['y']))
    T.eq(SO.item_now(path, E.data, fresh, view)[3], bytes(mxl_save.item_blob(raw, victim)), 'after the re-read')


@T.test
def duplicate_on_a_full_stash_timing():
    """Prints the time of one Duplicate (engine part: action parse, free place, write with both checks, reload)
    on a stash filled to 1340 items, with the collector's parser and with the cache."""
    E = eng()
    import mxl_save
    import mxl_stash_order as SO
    import mxl_savecheck as SC
    path = stash_copy()
    n = full_stash(E, path)
    keep = os.path.join(T.tmp(), 'full0.stash')
    shutil.copy(path, keep)

    def run(cached):
        shutil.copy(keep, path)
        SC._state['parsed'].clear()
        SO.clear_parse_cache()
        host = mxl_save.parse_stash
        if not cached:
            mxl_save.parse_stash = SO._cache['orig']
        try:
            times = []
            for _k in range(4):
                t0 = time.perf_counter()
                items = mxl_save.parse_stash(path, E.data)
                it = next(i for i in items if E.data.base(i['code']).size == (1, 1))
                one_duplicate(E, path, it)
                mxl_save.parse_stash(path, E.data)              # the window's reload
                times.append(time.perf_counter() - t0)
            return times
        finally:
            mxl_save.parse_stash = host
    plain_t, cached_t = run(False), run(True)
    print(f'  {n} items: one Duplicate (first, then median of the next 3): collector parser '
          f'{1000 * plain_t[0]:.0f} / {1000 * sorted(plain_t[1:])[1]:.0f} ms, cached '
          f'{1000 * cached_t[0]:.0f} / {1000 * sorted(cached_t[1:])[1]:.0f} ms')


T.main(globals())
