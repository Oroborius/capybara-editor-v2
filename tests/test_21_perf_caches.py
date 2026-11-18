"""The start-up speed-ups give the same results as the code they replace, and their caches follow their inputs.

- mxl_explode: the faster PKWARE "explode" returns the same bytes as the collector's own mpq.explode for real
  implode-compressed members of the game archives (needs the game folder of the fixture's settings.json; skipped
  without it), and the same exception type for cut-off streams.
- mxl_d2ui_dc6.to_rgba and Art._bright (C-speed versions) against the per-pixel loops they replaced.
- mxl_diskcache: the key changes when a table file changes (size or mtime), when a file is added, with the
  language; a stored value comes back only under its own key.
- the art cache's "not in any archive" markers: a second lookup of a missing member opens no archive; a new
  game version (another stamp) removes them with the rest of the raw cache."""
import json
import os
import random
import shutil
import time

import capytest as T

MODE = 'engine'
NEEDS = ('user',)

MEMBERS = (                                      # implode-compressed members of Median XL Sigma's archives
    'data\\global\\themes\\tartarus\\game\\buttons\\stat-screen.dc6',
    'data\\global\\themes\\tartarus\\game\\skills\\socket.dc6',
    'data\\local\\font\\latin\\font6.dc6',
    'data\\global\\themes\\tartarus\\game\\panels\\character-inventory.dc6',
)


def game_dir():
    try:
        with open(os.path.join(T.SRC_USER, 'settings.json'), encoding='utf-8') as f:
            gd = json.load(f).get('game_dir')
    except (OSError, ValueError):
        gd = None
    if not gd or not os.path.isfile(os.path.join(gd, 'medianxl-version.mpq')):
        T.skip('no game folder in the fixture settings.json (game_dir): the archives are needed')
    return gd


def ref_to_rgba(frame, pal):
    w, h, _ox, _oy, px, mask = frame
    out = bytearray(w * h * 4)
    for i in range(w * h):
        if mask[i]:
            r, g, b = pal[px[i]]
            out[i * 4:i * 4 + 4] = bytes((r, g, b, 255))
    return w, h, out


def ref_bright(lut, rgba):
    out = bytearray(rgba)
    for i in range(0, len(out), 4):
        if out[i + 3]:
            out[i] = lut[out[i]]
            out[i + 1] = lut[out[i + 1]]
            out[i + 2] = lut[out[i + 2]]
    return out


@T.test
def explode_matches_the_collectors_own():
    gd = game_dir()
    T.engine()
    import mpq
    import mxl_d2look_art as A
    import mxl_explode
    host = mxl_explode.host_explode()
    T.check(getattr(mpq.explode, '_capy_fast', False), 'mxl_d2look_art did not install the fast explode')
    streams = []

    def rec(src):
        out = host(src)
        streams.append((bytes(src), out))
        return out
    mpq.explode = rec
    try:
        archives = [m for m in map(A._archive, sorted(__import__('glob').glob(os.path.join(gd, 'medianxl-*.mpq'))))
                    if m is not None]
        for name in MEMBERS:
            for m in archives:
                if m.find(name) is not None:
                    m.read(name)
                    break
    finally:
        mpq.explode = mxl_explode.explode
    T.check(len(streams) >= 4, f'only {len(streams)} implode streams read from {MEMBERS}')
    t_fast = 0.0
    for src, out in streams:
        t = time.perf_counter()
        got = mxl_explode.explode(src)
        t_fast += time.perf_counter() - t
        T.check(got == out, f'explode differs on a stream of {len(src)} bytes')
    rnd = random.Random(7)
    for src, _out in rnd.sample(streams, min(40, len(streams))):
        cut = src[:rnd.randint(2, len(src) - 1)]
        res = []
        for f in (host, mxl_explode.explode):
            try:
                res.append(('ok', f(cut)))
            except Exception as e:
                res.append((type(e).__name__,))
        T.eq(res[1], res[0], f'cut-off stream ({len(cut)} of {len(src)} bytes)')
    print(f'  {len(streams)} streams, {sum(len(o) for _s, o in streams)} bytes in {t_fast:.2f} s')


@T.test
def to_rgba_and_brightness_match_the_pixel_loops():
    T.engine()
    import mxl_d2look_art as A
    import mxl_d2ui_dc6 as D
    rnd = random.Random(3)
    pal = [(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(256)]
    for w, h in ((0, 0), (1, 1), (7, 3), (64, 40), (256, 256)):
        px = bytearray(rnd.randrange(256) for _ in range(w * h))
        mask = bytearray(1 if rnd.random() < 0.7 else 0 for _ in range(w * h))
        frame = (w, h, 0, 0, px, mask)
        T.eq(D.to_rgba(frame, pal), ref_to_rgba(frame, pal), f'to_rgba of a {w}x{h} frame')
        rgba = ref_to_rgba(frame, pal)[2]
        art = A.Art.__new__(A.Art)
        art._lut = [min(255, round(255 * (v / 255) ** A.GAMMA)) for v in range(256)]
        T.eq(art._bright(rgba), ref_bright(art._lut, rgba), f'brightness curve on a {w}x{h} image')


@T.test
def disk_cache_key_follows_its_inputs():
    E = T.engine()
    import mxl_diskcache as DC
    folder = os.path.join(T.tmp(), 'tables')
    os.makedirs(folder)
    for n in ('a.bin', 'b.tbl'):
        with open(os.path.join(folder, n), 'wb') as f:
            f.write(b'x' * 10)
    k = DC.key([folder], extra=['en'])
    T.eq(DC.key([folder], extra=['en']), k, 'same inputs, same key')
    T.check(DC.key([folder], extra=['de']) != k, 'the language is not part of the key')
    st = os.stat(os.path.join(folder, 'a.bin'))
    os.utime(os.path.join(folder, 'a.bin'), ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    k2 = DC.key([folder], extra=['en'])
    T.check(k2 != k, 'a table file with a new mtime keeps the key')
    with open(os.path.join(folder, 'b.tbl'), 'ab') as f:
        f.write(b'y')
    k3 = DC.key([folder], extra=['en'])
    T.check(k3 != k2, 'a table file with a new size keeps the key')
    with open(os.path.join(folder, 'c.bin'), 'wb') as f:
        f.write(b'z')
    k4 = DC.key([folder], extra=['en'])
    T.check(k4 != k3, 'a new table file keeps the key')
    T.check(DC.save('capytest-probe', k4, {'v': [1, 2]}), 'the cache file could not be written')
    T.check(os.path.dirname(DC.path('capytest-probe')).startswith(os.path.realpath(E.paths.USER_DIR))
            or os.path.dirname(DC.path('capytest-probe')).startswith(E.paths.USER_DIR), 'cache outside the user folder')
    T.eq(DC.load('capytest-probe', k4), {'v': [1, 2]}, 'value under its own key')
    T.eq(DC.load('capytest-probe', k3), None, 'value under an older key')
    with open(DC.path('capytest-probe'), 'w') as f:
        f.write('{broken')
    T.eq(DC.load('capytest-probe', k4), None, 'a broken cache file')


@T.test
def missing_art_is_remembered_until_the_game_changes():
    gd = game_dir()
    T.engine()
    import mxl_d2look_art as A
    root = os.path.join(T.tmp(), 'ui_art')
    name = 'data\\global\\ui\\capytest\\no-such-file.dc6'
    a = A.Art(gd, 'tartarus', root)
    try:
        a.read(name)
        T.check(False, 'a missing member was read')
    except A.ArtError:
        pass
    raw = os.path.join(root, 'tartarus', 'raw')
    T.check(any(n.endswith('.mpqs.none') for n in os.listdir(raw)), 'no marker for the missing member')
    b = A.Art(gd, 'tartarus', root)                      # a new start: no archive may be opened for it
    opened = []
    b.mpqs = lambda: opened.append(1) or []
    b.mpqs.__name__ = 'mpqs'
    try:
        b._read_raw(name, b.mpqs)
    except A.ArtError:
        pass
    T.eq(opened, [], 'archives opened again for a member known to be missing')
    with open(os.path.join(root, 'tartarus', 'stamp.txt'), 'w') as f:
        f.write('another game version')
    A.Art(gd, 'tartarus', root)
    T.check(not os.path.exists(raw) or not any(n.endswith('.none') for n in os.listdir(raw)),
            'the markers survived a new game version')
    shutil.rmtree(root, ignore_errors=True)


T.main(globals())
