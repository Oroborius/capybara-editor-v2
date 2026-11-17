"""Packaging: every source compiles, the exe repacker reproduces the base exe bit for bit, the host modules come
out of the exe as expected, the application folder under test holds the current sources, the Linux launcher's
environment handling."""
import glob
import importlib.util
import json
import os
import py_compile
import subprocess
import sys

import capytest as T

MODE = 'engine'
NEEDS = ()
ENGINE = False

# the collector's own modules inside the exe's PYZ (WORKLOG W4: 25 host modules)
HOST_MODULES = sorted('''i18n mpq mxl_catalog_tooltip mxl_data mxl_edit mxl_format mxl_game mxl_gfx mxl_gui
mxl_gui_detail mxl_gui_install mxl_install mxl_library mxl_library_gui mxl_library_view mxl_rules mxl_save
mxl_stat_text mxl_theme mxl_tooltip mxl_tooltip_view paths settings stat_ids tbl'''.split())


def base_exe():
    base = os.environ.get('CAPY_BASE_DIR', '')
    exes = sorted(glob.glob(os.path.join(base, '*.exe'))) if base else []
    if not exes:
        T.skip(f'no base exe: BASE_DIR={base!r} has no *.exe (set BASE_DIR, or run packaging/fetch_base.sh)')
    return exes[0]


def run(*cmd, **env):
    p = subprocess.run([sys.executable, '-B', *cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
                       cwd=T.tmp(), env=dict(os.environ, **env))
    return p.returncode, p.stdout.decode(errors='replace')


@T.test
def every_source_compiles():
    files = []
    for pat in ('src/*.py', 'packaging/*.py', 'packaging/linux/*.py', 'tools/*.py', 'tests/*.py'):
        files += sorted(glob.glob(os.path.join(T.REPO, pat)))
    T.check(len(files) > 40, f'only {len(files)} python files found under {T.REPO}')
    out = os.path.join(T.tmp(), 'compiled.pyc')
    for f in files:
        try:
            py_compile.compile(f, cfile=out, doraise=True)
        except py_compile.PyCompileError as e:
            T.check(False, f'{os.path.relpath(f, T.REPO)}: {str(e.msg).strip().splitlines()[-1]}')
    T.eq(sys.version_info[:2], (3, 10), 'Python version of the test run (the exe needs 3.10 bytecode)')


@T.test
def shell_scripts_parse():
    for f in sorted(glob.glob(os.path.join(T.REPO, 'packaging', '*.sh')) + glob.glob(os.path.join(T.REPO, 'tools', '*.sh'))):
        p = subprocess.run(['bash', '-n', f], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        T.check(p.returncode == 0, f'{os.path.basename(f)}: {p.stdout.decode(errors="replace")[:200]}')


@T.test
def language_files_are_json():
    files = sorted(glob.glob(os.path.join(T.REPO, 'lang', '*.json')))
    T.check(files, 'no lang/*.json')
    for f in files:
        try:
            with open(f, encoding='utf-8') as fh:
                d = json.load(fh)
            T.check(isinstance(d, dict) and d, f'{os.path.basename(f)}: not a filled object')
        except ValueError as e:
            T.check(False, f'{os.path.basename(f)}: {e}')


@T.test
def repack_identity():
    """src/repack.py --identity: reading the exe's archive and writing it again gives the same file."""
    exe = base_exe()
    code, out = run(os.path.join(T.REPO, 'src', 'repack.py'), exe, os.path.join(T.tmp(), 'unused.exe'), '--identity')
    T.eq(code, 0, f'exit code ({out[-300:]})')
    T.check(out.strip().startswith('identical: True'), f'output: {out.strip()[-200:]!r}')
    T.check(not os.path.exists(os.path.join(T.tmp(), 'unused.exe')), '--identity wrote a file')


@T.test
def repack_builds_an_exe_with_the_editor_modules():
    """A full repack into the test folder: the new exe's archive holds every src/mxl_*.py and still the host's."""
    exe = base_exe()
    dst = os.path.join(T.tmp(), 'repacked.exe')
    code, out = run(os.path.join(T.REPO, 'src', 'repack.py'), exe, dst)
    T.eq(code, 0, f'exit code ({out[-300:]})')
    if not os.path.exists(dst):
        raise T.Failed('no exe written: ' + out[-300:])
    code, out = run('-c', 'import sys, struct, marshal; sys.path.insert(0, sys.argv[1]); import carch\n'
                    'd, start, ents, info = carch.read(sys.argv[2])\n'
                    'z = [e for e in ents if e["typ"] == "z"][0]["data"]\n'
                    'print(" ".join(sorted(n for n, _ in marshal.loads(z[struct.unpack("!i", z[8:12])[0]:]) if "." not in n)))',
                    os.path.join(T.REPO, 'src'), dst)
    names = set(out.split())
    ours = sorted(os.path.basename(f)[:-3] for f in glob.glob(os.path.join(T.REPO, 'src', 'mxl_*.py')))
    T.eq(sorted(set(ours) - names), [], 'editor modules missing from the repacked exe')
    T.eq(sorted(set(HOST_MODULES) - names), [], 'host modules missing from the repacked exe')
    os.remove(dst)


@T.test
def extract_host_module_list():
    exe = base_exe()
    dst = os.path.join(T.tmp(), 'host')
    code, out = run(os.path.join(T.REPO, 'packaging', 'extract_host.py'), exe, dst)
    T.eq(code, 0, f'exit code ({out[-300:]})')
    got = sorted(f[:-4] for f in os.listdir(dst) if f.endswith('.pyc'))
    T.eq(got, HOST_MODULES, 'host modules written')
    T.eq(sorted(os.listdir(dst)), [m + '.pyc' for m in HOST_MODULES], 'files written')
    for m in got:
        raw = T.read(os.path.join(dst, m + '.pyc'))
        T.check(raw[:4] == importlib.util.MAGIC_NUMBER, f'{m}.pyc: not Python 3.10 bytecode')
        T.check(len(raw) > 16 + 50, f'{m}.pyc: {len(raw)} bytes')
        built = os.path.join(T.APP, m + '.pyc')
        T.check(os.path.exists(built) and T.read(built) == raw, f'{m}.pyc differs from the one in the application folder')
    code, out = run('-c', 'import sys; sys.path.insert(0, sys.argv[1]); import mxl_format, mxl_save, mxl_rules, stat_ids, tbl; print("ok")', dst,
                    MXL_USER_DIR=T.guard(os.path.join(T.tmp(), 'empty-user')), MXL_SAVE_DIR=T.guard(os.path.join(T.tmp(), 'empty-saves')))
    T.check(out.strip().endswith('ok'), f'the extracted modules do not import: {out[-300:]}')


@T.test
def application_folder_matches_sources():
    """tools/run_tests.sh copies src/ into the application folder first: what is tested is what is in the tree."""
    n = 0
    for f in sorted(glob.glob(os.path.join(T.REPO, 'src', 'mxl_*.py')) + glob.glob(os.path.join(T.REPO, 'src', '*.json'))
                    + [os.path.join(T.REPO, 'packaging', 'linux', 'capybara_editor.py')]):
        built = os.path.join(T.APP, os.path.basename(f))
        T.check(os.path.exists(built) and T.read(built) == T.read(f), f'{os.path.basename(f)} in the application folder is not the source')
        n += 1
    T.check(n > 30, f'only {n} files compared')
    for m in HOST_MODULES:
        T.check(os.path.exists(os.path.join(T.APP, m + '.pyc')), f'host module {m}.pyc missing from the application folder')
    for f in sorted(glob.glob(os.path.join(T.REPO, 'lang', '*.json'))):
        built = os.path.join(T.APP, 'lang', os.path.basename(f))
        T.check(os.path.exists(built) and T.read(built) == T.read(f), f'lang/{os.path.basename(f)} in the application folder is not the source')


LAUNCHER = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import capybara_editor as L
print('FOUND', L.find_save_dir())
os.environ.pop('MXL_SAVE_DIR', None)
L.setup_env()
print('AUTO', os.environ.get('MXL_SAVE_DIR'))
print('LOCALAPPDATA', os.environ.get('LOCALAPPDATA'))
os.environ['MXL_SAVE_DIR'] = '/given'
L.setup_env()
print('GIVEN', os.environ.get('MXL_SAVE_DIR'))
'''


@T.test
def launcher_environment_handling():
    """In a made-up home folder: the save folder of a Wine prefix is found, MXL_SAVE_DIR given by the caller is
    kept, the data folder follows XDG_DATA_HOME."""
    home = os.path.join(T.tmp(), 'fakehome')
    save = os.path.join(home, '.wine', 'drive_c', 'users', 'someone', 'AppData', 'Roaming', 'MedianXL', 'save')
    os.makedirs(save)
    env = {k: v for k, v in os.environ.items() if k not in ('WINEPREFIX', 'MXL_SAVE_DIR', 'LOCALAPPDATA', 'MXL_USER_DIR')}
    env.update(HOME=home, XDG_DATA_HOME=os.path.join(home, 'xdg'))
    p = subprocess.run([sys.executable, '-B', '-c', LAUNCHER, T.APP], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=60, env=env, cwd=T.tmp())
    out = dict(line.split(' ', 1) for line in p.stdout.decode(errors='replace').splitlines() if ' ' in line)
    T.eq(out.get('FOUND'), save, 'find_save_dir() in the made-up home')
    T.eq(out.get('AUTO'), save, 'MXL_SAVE_DIR chosen by setup_env()')
    T.eq(out.get('LOCALAPPDATA'), os.path.join(home, 'xdg'), 'LOCALAPPDATA from XDG_DATA_HOME')
    T.eq(out.get('GIVEN'), '/given', 'MXL_SAVE_DIR given by the caller')
    env2 = dict(env, HOME=os.path.join(T.tmp(), 'emptyhome'))
    os.makedirs(env2['HOME'])
    p = subprocess.run([sys.executable, '-B', '-c', LAUNCHER, T.APP], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=60, env=env2, cwd=T.tmp())
    T.check('FOUND None' in p.stdout.decode(errors='replace'), 'a home without a Wine prefix: a save folder was found')


@T.test
def safety_guard_refuses_real_folders():
    """The suite's own guard (capytest.guard): each forbidden kind of path ends the process with code 97."""
    code = ('import sys; sys.path.insert(0, sys.argv[1]); import capytest\n'
            'capytest.guard(sys.argv[2], "test path"); print("ACCEPTED")')
    here = os.path.dirname(os.path.abspath(__file__))
    bad = ['/home/someone/Games/diablo/save', os.path.join(T.tmp(), 'x', 'drive_c', 'users', 'u', 'save'), '']
    real = T._real_save_dir()
    if real:
        bad.append(real)
    for path in bad:
        p = subprocess.run([sys.executable, '-B', '-c', code, here, path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        T.check(p.returncode == 97 and b'ACCEPTED' not in p.stdout, f'guard accepted {path!r} (exit code {p.returncode})')
    p = subprocess.run([sys.executable, '-B', '-c', code, here, T.tmp()], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    T.check(p.returncode == 0 and b'ACCEPTED' in p.stdout, 'guard refused the test folder itself')


T.main(globals())
