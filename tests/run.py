#!/usr/bin/env python3
"""Runner of the regression suite. Started by tools/run_tests.sh with the AppDir's Python 3.10 (see
tests/README.md); every tests/test_*.py runs in its own process (GUI files: one process per test or variant).

    run.py [--quick] [-k SUBSTRING]... [--list] [--keep] [--timeout SECONDS]

Exit code: 0 when nothing failed unexpectedly, 1 otherwise, 2 for a broken setup.
"""
import argparse
import ast
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import capytest                                              # noqa: E402  (guard, fixture checks)

MARK = dict(pass_='PASS ', fail='FAIL ', skip='SKIP ', xfail='XFAIL', xpass='XPASS')


def describe(path):
    """(mode, isolate, variants, [test names], group order) of a test file, read with ast (nothing is run)."""
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read(), path)
    consts, names = {}, []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                consts[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
        elif isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                f = d.func if isinstance(d, ast.Call) else d
                if isinstance(f, ast.Attribute) and f.attr == 'test' or isinstance(f, ast.Name) and f.id == 'test':
                    names.append(node.name)
    return consts.get('MODE', 'engine'), bool(consts.get('ISOLATE')), consts.get('VARIANTS') or {'': {}}, names


def tree_digest(folder):
    """Digest of every file of a fixture folder: the suite must leave the originals untouched."""
    h = hashlib.sha1()
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for n in sorted(files):
            p = os.path.join(root, n)
            h.update(os.path.relpath(p, folder).encode())
            try:
                with open(p, 'rb') as f:
                    h.update(hashlib.sha1(f.read()).digest())
            except OSError:
                h.update(b'?')
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description='MXL Capybara Editor V2 regression suite')
    ap.add_argument('--quick', action='store_true', help='data + engine tests only (no window is opened)')
    ap.add_argument('-k', action='append', default=[], metavar='SUBSTRING',
                    help='only tests whose id (file::name[variant]) contains this text (repeatable: any of them)')
    ap.add_argument('--list', action='store_true', help='list the test ids and exit')
    ap.add_argument('--keep', action='store_true', help='keep the session folder (copies, stderr of every process)')
    ap.add_argument('--timeout', type=int, default=300, help='seconds one test process may take (default 300)')
    args = ap.parse_args()

    appdir = os.environ.get('CAPY_APPDIR', '')
    if not os.path.isfile(os.path.join(appdir, 'opt', 'capybara', 'capybara_editor.py')):
        print(f'no built application in CAPY_APPDIR={appdir!r}: start this through tools/run_tests.sh')
        return 2

    units = []                                   # (file, mode, variant, env, [names])
    for path in sorted(glob.glob(os.path.join(HERE, 'test_*.py'))):
        mode, isolate, variants, names = describe(path)
        if args.quick and mode != 'engine':
            continue
        short = os.path.basename(path)[5:-3]
        for variant, env in variants.items():
            ids = [(n, f'{short}::{n}' + (f'[{variant}]' if variant else '')) for n in names]
            ids = [(n, i) for n, i in ids if not args.k or any(k in i for k in args.k)]
            if not ids:
                continue
            groups = [[x] for x in ids] if isolate else [ids]
            for grp in groups:
                units.append((path, mode, variant, env, grp))
    if args.list:
        for _p, mode, _v, _e, grp in units:
            for _n, i in grp:
                print(f'{mode:6} {i}')
        return 0
    if not units:
        print('no test selected')
        return 2

    need_x = any(u[1] != 'engine' for u in units)
    if need_x and not os.environ.get('DISPLAY'):
        print('GUI tests need an X display: start this through tools/run_tests.sh (it uses xvfb-run)')
        return 2

    # session folder: system temp, or the repository's .cache when the temp filesystem is nearly full
    base = os.environ.get('MXL_TEST_TMP') or tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)
    if not os.environ.get('MXL_TEST_TMP') and shutil.disk_usage(base).free < 400 * 2 ** 20:
        base = os.path.join(capytest.REPO, '.cache', 'test-tmp')
        os.makedirs(base, exist_ok=True)
    session = capytest.guard(tempfile.mkdtemp(prefix='capytest-', dir=base), 'session folder')
    fixtures = [(k, os.environ.get(k, '')) for k in ('CAPY_SRC_USER', 'CAPY_SRC_SAVES', 'CAPY_SRC_SAVES2',
                                                      'CAPY_SRC_SAVES3')]
    for k, v in fixtures:
        if v and os.path.isdir(v):
            capytest.guard(v, k)                 # the originals are only read, but never from a real save folder
    before = {k: tree_digest(v) for k, v in fixtures[1:] if os.path.isdir(v)}
    print(f'app:     {appdir}')
    print('fonts:   ' + ('Xft (as the users get them; CAPY_XFT=0: X core fonts)' if capytest.use_xft(appdir) else
                         'X core fonts (no Xft Tk in the application folder, or CAPY_XFT=0)'))
    for label, k, ok in (('tables', 'CAPY_SRC_USER', capytest.user_ok()), ('saves', 'CAPY_SRC_SAVES', capytest.saves_ok()),
                         ('saves 2', 'CAPY_SRC_SAVES2', capytest.saves_ok(capytest.SRC_SAVES2)),
                         ('saves 3', 'CAPY_SRC_SAVES3', capytest.saves_ok(capytest.SRC_SAVES3))):
        print(f'{label + ":":8} {os.environ.get(k) or "-"}' + ('' if ok else '   (MISSING: the tests that need it are skipped)'))
    print(f'work:    {session}\n')

    counts = dict(pass_=0, fail=0, skip=0, xfail=0, xpass=0)
    notable = []
    t_start = time.time()
    for n_unit, (path, mode, variant, env, grp) in enumerate(units):
        work = os.path.join(session, f'u{n_unit:03d}')
        os.makedirs(work)
        results = os.path.join(work, 'results.jsonl')
        e = dict(os.environ, CAPY_TMP=work, CAPY_RESULTS=results, CAPY_ONLY=','.join(n for n, _i in grp),
                 CAPY_VARIANT=variant, CAPY_REPO=capytest.REPO, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
        for k in ('MXL_USER_DIR', 'MXL_SAVE_DIR', 'MXL_EXIT_AFTER', 'MXL_THEME', 'MXL_UI_SCALE', 'MXL_GAME', 'MXL_GAME_DIR'):
            e.pop(k, None)
        e.update(env)
        if mode != 'engine':
            e['WAYLAND_DISPLAY'] = 'fake'        # the launcher then fixes the UI scale at 1 (no xrdb guess)
        t0 = time.time()
        with open(os.path.join(work, 'output.txt'), 'wb') as out:
            try:
                p = subprocess.run([sys.executable, '-B', path], env=e, cwd=work, stdout=out, stderr=subprocess.STDOUT,
                                   timeout=args.timeout)
                died = None if p.returncode == 0 else f'process exit code {p.returncode}'
            except subprocess.TimeoutExpired:
                died = f'timeout after {args.timeout} s'
        got = {}
        extra = []
        try:
            with open(results, encoding='utf-8') as f:
                for line in f:
                    r = json.loads(line)
                    if r['name'] in dict(grp):
                        got[r['name']] = r
                    else:
                        extra.append(r)
        except OSError:
            pass
        tail = ''
        if died or extra:
            try:
                with open(os.path.join(work, 'output.txt'), encoding='utf-8', errors='replace') as f:
                    lines = [ln for ln in f.read().splitlines() if ln.strip()]
                tail = ' | '.join(lines[-4:])[-500:]
            except OSError:
                pass
        short = os.path.basename(path)[5:-3]
        rows = []
        for name, tid in grp:
            r = got.get(name)
            if r is None:
                rows.append((tid, 'fail', f'no result ({died or "the process ended before this test"}) {tail}', 0))
            else:
                rows.append((tid, r['status'], r.get('detail', ''), r.get('secs', 0)))
        for r in extra:                          # harness / start-up failures reported under their own name
            rows.append((f'{short}::{r["name"]}' + (f'[{variant}]' if variant else ''), r['status'], r.get('detail', ''), 0))
        if died and all(r[1] != 'fail' for r in rows) and got and len(got) == len(grp):
            rows.append((f'{short}::process' + (f'[{variant}]' if variant else ''), 'fail', f'{died} {tail}', 0))
        for tid, status, detail, secs in rows:
            key = 'pass_' if status == 'pass' else status
            counts[key] += 1
            line = f'{MARK[key]} {tid}  ({secs:.1f}s)'
            if status != 'pass':
                line += f'\n        {detail}'
                notable.append((key, tid, detail))
            print(line, flush=True)
        if not args.keep and not any(r[1] == 'fail' for r in rows):
            shutil.rmtree(work, ignore_errors=True)
        elif not args.keep:                      # failed: keep the small files, drop the big copies
            for d in glob.glob(os.path.join(work, 'p-*', 'user-*')):
                shutil.rmtree(d, ignore_errors=True)

    # the originals must be as they were
    for k, v in fixtures[1:]:
        if k in before and tree_digest(v) != before[k]:
            counts['fail'] += 1
            notable.append(('fail', 'fixtures::untouched', f'{v} was modified during the run'))
            print(f'FAIL  fixtures::untouched\n        {v} was modified during the run')

    print()
    for key, title in (('fail', 'FAILED'), ('xpass', 'UNEXPECTED PASSES (bug fixed? remove the xfail marker)'),
                       ('xfail', 'EXPECTED FAILURES (known bugs)'), ('skip', 'SKIPPED')):
        rows = [(t, d) for k, t, d in notable if k == key]
        if not rows:
            continue
        print(title + ':')
        if key == 'skip':                        # one line per reason
            by = {}
            for t, d in rows:
                by.setdefault(d, []).append(t)
            for d, ts in by.items():
                names = ', '.join(ts[:3]) + (f' and {len(ts) - 3} more' if len(ts) > 3 else '')
                print(f'  {len(ts)} x {d[:200]}\n      {names}')
        else:
            for t, d in rows:
                print(f'  {t}: {d[:230]}')
    summary = (f'{counts["pass_"]} passed, {counts["fail"]} failed, {counts["skip"]} skipped, '
               f'{counts["xfail"]} expected failures')
    if counts['xpass']:
        summary += f', {counts["xpass"]} unexpected passes'
    print(f'\n{summary}  ({time.time() - t_start:.0f} s)')
    print('RESULT: ' + ('FAIL' if counts['fail'] else 'PASS'))
    if args.keep or counts['fail']:
        print(f'session folder kept: {session}')
    else:
        shutil.rmtree(session, ignore_errors=True)
    return 1 if counts['fail'] else 0


if __name__ == '__main__':
    sys.exit(main())
