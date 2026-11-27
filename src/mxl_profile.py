"""Game profiles: Median XL (the default, unchanged) or any other Diablo II game folder (vanilla LoD 1.14d first).

Median XL keeps every path of the editor as it was: install() returns at once and patches nothing.

Folder profiles resolve a base Diablo II installation and an optional D2SE core. The selected mod's MPQs
override the core and shared archives. Loose Excel files have the highest priority. Extracted tables, strings
and artwork live under the selected folder's own user profile.

Settings: 'game_profile' ('median' | 'folder'), 'profile_game_dir', 'profile_base_dir' and 'vanilla_ui_theme'.
The saved Median 'game_dir' stays separate. MXL_GAME=vanilla (+ MXL_GAME_DIR) selects a folder for tests.

Diablo II 1.10–1.14d saves use version 96. Older LoD saves use versions 87, 89 and 92.
"""
import hashlib
import json
import os
import struct
from pathlib import Path

DEFAULT_VANILLA = os.path.expanduser(
    '~/Games/diablo-ii-lord-of-destruction/drive_c/Program Files (x86)/Diablo II')
EXCEL = ('armor arena armtype automagic automap belts bodylocs books charstats chartemplate colors compcode composit '
         'cubemain cubemod cubetype difficultylevels elemtypes events experience gamble gems hiredesc hireling '
         'hitclass inventory itemratio itemstatcost itemtypes leveldefs levels lowqualityitems lvlmaze lvlprest '
         'lvlsub lvltypes lvlwarp magicprefix magicsuffix misc misscalc missiles monai monequip monitempercent '
         'monlvl monmode monname monplace monpreset monprop monseq monsounds monstats monstats2 montype monumod '
         'npc objects objgroup objmode objtype overlay pettype playerclass plrmode plrtype properties qualityitems '
         'rareprefix raresuffix runes setitems sets shrines skillcalc skilldesc skills soundenviron sounds states '
         'storepage superuniques treasureclassex uniqueappellation uniqueitems uniqueprefix uniquesuffix uniquetitle '
         'weapons itemscode skillscode skilldesccode missilescode monstatscode').split()
STRINGS = ('string', 'expansionstring', 'patchstring')
EXTRACT_VERSION = 5
BASE_ARCHIVE_NAMES = frozenset(n + '.mpq' for n in (
    'd2data', 'd2sfx', 'd2speech', 'd2delta', 'd2kfixup', 'd2exp', 'patch_d2', 'd2char', 'd2music',
    'd2xmusic', 'd2xtalk', 'd2xvideo', 'd2video',
))

_state = None                 # the active profile (dict) once install() ran


# ---------------------------------------------------------------------------------------------------- detection
def _filesystem_path(path):
    """Use the Windows extended namespace for paths near MAX_PATH."""
    if os.name != 'nt' or not path:
        return path
    path = os.path.abspath(path)
    if len(path.encode('utf-16-le', 'surrogatepass')) < 480 or path.startswith(('\\\\?\\', '\\\\.\\')):
        return path
    if path.startswith('\\\\'):
        return '\\\\?\\UNC\\' + path[2:]
    return '\\\\?\\' + path


def _directory_archives(game_dir):
    """Archive search order (highest priority first) the way the game builds it. Adapted from D2-Development-Kit,
    d2bt/mpq.py default_archive_order (MIT): vanilla 1.13c/1.14d open d2data, d2sfx, d2speech, d2delta,
    d2kfixup @1000, patch_d2 @5000, d2exp @3000; Median (D2Sigma) d2exp @3000, patch_d2 @5000, then every
    medianxl-*.mpq @6000; then d2char, d2music @1000, LoD d2xmusic, d2xtalk, d2xvideo @3000, d2video @1000. Among
    equal priorities the archive opened last is searched first. Names match case-insensitively; d2gl.mpq (a
    renderer's) is not game data. Other *.mpq files of a mod folder come first (@6000, the way mod loaders add
    theirs)."""
    game_dir = _filesystem_path(game_dir)
    try:
        files = os.listdir(game_dir)
    except OSError:
        return []
    paths = ((f.lower(), _filesystem_path(os.path.join(game_dir, f))) for f in files)
    low = {name: path for name, path in paths if os.path.isfile(path)}
    median = sorted((f for f in files if f.lower().startswith('medianxl-') and f.lower().endswith('.mpq')),
                    key=str.upper)
    base = ['d2data', 'd2sfx', 'd2speech', 'd2delta', 'd2kfixup']
    if median:
        seq = [(n, 1000) for n in base] + [('d2exp', 3000), ('patch_d2', 5000)]
        seq += [(f[:-4], 6000) for f in median]
    else:
        seq = [(n, 1000) for n in base] + [('patch_d2', 5000), ('d2exp', 3000)]
        seq += [(f[:-4], 6000) for f in sorted(files, key=str.upper)
                if f.lower().endswith('.mpq') and f.lower() not in BASE_ARCHIVE_NAMES | {'d2gl.mpq'}]
    seq += [('d2char', 1000), ('d2music', 1000)]
    if 'd2exp.mpq' in low:
        seq += [('d2xmusic', 3000), ('d2xtalk', 3000), ('d2xvideo', 3000)]
    seq.append(('d2video', 1000))
    opened = [(prio, i, low[(n + '.mpq').lower()]) for i, (n, prio) in enumerate(seq) if (n + '.mpq').lower() in low]
    opened.sort(key=lambda t: (-t[0], -t[1]))
    return [path for _, _, path in opened]


STOCK_TABLE_ARCHIVES = ('patch_d2.mpq', 'd2exp.mpq', 'd2data.mpq')


def legit_stock():
    """Legit Mode reads the game tables the way the server's checker does: only Patch_D2 > d2exp > d2data (no
    extra .mpq, no loose data\\global\\excel files), so the creator offers exactly what the checker knows."""
    return bool(_raw_settings().get('legit_mode'))


def has_non_stock(game_dir):
    """The folder (or its base) has table sources Legit Mode ignores: other .mpq archives or loose Excel files."""
    try:
        extra = [p for p in archive_order(game_dir, stock=False)
                 if os.path.basename(p).lower() not in BASE_ARCHIVE_NAMES]
        return bool(extra or _loose_excel(game_dir, stock=False))
    except Exception:
        return False


def archive_order(game_dir, info=None, stock=None):
    """Highest priority first, with the mod above its core and base install."""
    info = info or detect(game_dir)
    folders = (game_dir, info.get('core_dir'), info.get('base_dir'))
    if info.get('core_dir') and os.path.abspath(game_dir) == os.path.abspath(info['base_dir']):
        folders = (info['core_dir'], game_dir)
    paths = {}
    for folder in folders:
        if folder:
            for path in _directory_archives(folder):
                paths.setdefault(os.path.normcase(os.path.abspath(path)), path)
    out = list(paths.values())
    if legit_stock() if stock is None else stock:
        out = [p for p in out if os.path.basename(p).lower() in BASE_ARCHIVE_NAMES]   # no mod / extra archives
    return out


def base_archives(game_dir):
    """Base UI files, excluding the selected mod's override archives."""
    info = detect(game_dir)
    return list(dict.fromkeys(p for folder in (info.get('core_dir'), info.get('base_dir') or game_dir)
                              if folder for p in _directory_archives(folder)
                              if os.path.basename(p).lower() in ('patch_d2.mpq', 'd2exp.mpq', 'd2data.mpq')))


def _pe_version(path):
    """FileVersion (a, b, c, d) of a PE file's VS_FIXEDFILEINFO, or None."""
    try:
        with open(path, 'rb') as f:
            b = f.read(32 * 1024 * 1024)
    except OSError:
        return None
    i = b.rfind(b'\xbd\x04\xef\xfe')
    if i < 0 or i + 16 > len(b):
        return None
    ms, ls = struct.unpack_from('<II', b, i + 8)
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


VERSIONS = {(1, 14, 3): '1.14d', (1, 14, 2): '1.14c', (1, 14, 1): '1.14b', (1, 14, 0): '1.14a',
            (1, 0, 13): '1.13', (1, 0, 12): '1.12', (1, 0, 11): '1.11', (1, 0, 10): '1.10', (1, 0, 9): '1.09'}


def _child(folder, name):
    """Resolve a game path case-insensitively on case-sensitive hosts."""
    exact = _filesystem_path(os.path.join(folder, name))
    if os.path.exists(exact):
        return exact
    try:
        with os.scandir(_filesystem_path(folder)) as entries:
            return next((entry.path for entry in entries if entry.name.lower() == name.lower()), None)
    except OSError:
        return None


def _base_install(folder):
    return (isinstance(folder, (str, os.PathLike)) and folder and os.path.isfile(_child(folder, 'd2data.mpq') or '')
            and not _child(folder, 'd2sigma.dll')
            and not any(os.path.basename(p).lower().startswith('medianxl-') for p in _directory_archives(folder)))


def _mod_config(folder):
    path = _child(folder, 'D2SE_SETUP.ini')
    if path is None:
        return {}
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return {}
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    try:
        config = raw.decode(encoding)
    except UnicodeError:
        config = raw.decode('mbcs' if os.name == 'nt' else 'latin1', errors='replace')
    return {key.strip().lower(): value.strip().strip('"')
            for line in config.splitlines() if not line.lstrip().startswith(('#', ';'))
            for key, sep, value in [line.partition('=')] if sep}


def _game_version(folder):
    if folder:
        for name in ('game.exe', 'd2game.dll', 'd2client.dll', 'storm.dll'):
            v = _pe_version(_child(folder, name) or '')
            if v and v[0] == 1 and (v[1] == 14 or v[1] == 0 and 7 <= v[2] <= 13):
                return VERSIONS.get(v[:3], f'1.{v[2]:02d}')
    return None


def _loose_excel(folder, stock=None):
    if legit_stock() if stock is None else stock:
        return {}                                   # Legit Mode: the stock archives only
    for part in ('data', 'global', 'excel'):
        folder = _child(folder, part)
        if folder is None:
            return {}
    try:
        paths = ((f.lower(), _filesystem_path(os.path.join(folder, f))) for f in os.listdir(folder)
                 if f.lower().endswith(('.bin', '.txt')))
        return {name: path for name, path in paths if os.path.isfile(path)}
    except OSError:
        return {}


def detect(game_dir, base_dir=None):
    """Resolve a game, its D2SE core if present, and the base supplying shared archives."""
    empty = {'kind': None, 'version': None, 'mods': [], 'supported': False}
    if not isinstance(game_dir, (str, os.PathLike)) or not game_dir or not os.path.isdir(_filesystem_path(game_dir)):
        return empty
    archives = _directory_archives(game_dir)
    names = [os.path.basename(p) for p in archives]
    if any(n.lower().startswith('medianxl-') for n in names) or _child(game_dir, 'd2sigma.dll'):
        return dict(empty, kind='median', supported=True)
    config = _mod_config(game_dir)
    here = os.path.abspath(game_dir)
    parents = list(Path(here).parents)
    d2se = bool(config or (parents and parents[0].name.lower() == 'mods'))
    local_base = _base_install(game_dir)
    mods = [n for n in names if n.lower() not in BASE_ARCHIVE_NAMES or
            (not local_base and n.lower() == 'patch_d2.mpq')]
    mod = bool(mods or d2se or _loose_excel(game_dir))
    if not local_base and not mod:
        return empty

    configured_base = next((os.path.normpath(os.path.join(here, os.path.expandvars(config[k]).replace('\\', os.sep)))
                            for k in ('basegamefolder', 'gamepath') if config.get(k)), None)
    if base_dir is None and not local_base:
        active_dir = (_state or {}).get('game_dir')
        if active_dir and os.path.normcase(os.path.abspath(active_dir)) == os.path.normcase(here):
            base_dir = _state.get('base_dir')
        else:
            base_dir = _raw_settings().get('profile_base_dir')
    candidates = (game_dir, configured_base, *(str(p) for p in parents), base_dir)
    base = next((p for p in candidates if _base_install(p)), None)
    version = config.get('d2core') or _game_version(game_dir)
    core = None
    if base and (d2se or (version is None and not _game_version(base))):
        d2se_dir = _child(base, 'D2SE')
        cores = _child(d2se_dir, 'CORES') if d2se_dir else None
        if cores and os.path.isdir(cores):
            core = _child(cores, version) if _save_version(version) else None
            if core and not os.path.isdir(core):
                core = None
            if version is None:
                try:
                    choices = [entry.name for entry in Path(cores).iterdir()
                               if _save_version(entry.name) and entry.is_dir()]
                except OSError:
                    choices = []
                if len(choices) == 1:
                    version = choices[0]
                    core = _child(cores, version)
    version = version or _game_version(base)
    save_version = _save_version(version)
    return dict(empty, kind='d2', version=version, mods=mods, base_dir=base, core_dir=core,
                mod=mod, d2se=bool(d2se), save_version=save_version,
                name=config.get('modname') or os.path.basename(here),
                supported=bool(base and save_version))


def _save_version(version):
    import re
    if not version or not re.fullmatch(r'1\.(0[789]|1[0-4])[a-z]?', version, re.I):
        return None
    return {'1.07': 87, '1.08': 89, '1.09': 92}.get(version[:4], 96)


def _detection_label(info):
    if info['kind'] != 'd2':
        return 'Median XL' if info['kind'] == 'median' else 'No Diablo II game files found'
    version = info['version'] or 'unknown version'
    if info['mod']:
        loader = ', D2SE' if info['d2se'] else ''
        label = f"{info['name']} ({version} mod{loader})"
    else:
        label = f'Diablo II {version}'
    status = ('supported' if info['supported'] else
              'base Diablo II folder required' if not info['base_dir'] else 'unsupported game version')
    return f'{label} - {status}'


def _windows_saved_games():
    from ctypes import byref, c_long, c_void_p, create_string_buffer, windll, wstring_at

    # FOLDERID_SavedGames in the GUID structure's byte order.
    folder_id = create_string_buffer(bytes.fromhex('ff325c4c9dbbb043b5b42d72e54eaaa4'), 16)
    path = c_void_p()
    ole = windll.ole32
    initialize = ole.CoInitializeEx
    initialize.restype = c_long
    initialized = initialize(None, 2) >= 0
    try:
        if windll.shell32.SHGetKnownFolderPath(byref(folder_id), 0x4000, None, byref(path)) == 0 and path.value:
            return wstring_at(path)
    finally:
        if path.value:
            ole.CoTaskMemFree(path)
        if initialized:
            ole.CoUninitialize()


def save_dir(game_dir, home=None):
    """Where the game in game_dir keeps its characters (only detected - nothing is read here): a Wine prefix's
    drive_c/users/<user>/Saved Games/Diablo II (1.14x; 'Public' last), the Windows user's Saved Games\\Diablo II,
    else the game folder's own Save folder (1.13d and older). None when none exists."""
    import glob
    if not game_dir:
        return None
    parts = os.path.abspath(game_dir).split(os.sep)
    low = [p.lower() for p in parts]
    if 'drive_c' in low:
        root = os.sep.join(parts[:low.index('drive_c') + 1]) or os.sep
        found = [f for f in sorted(glob.glob(os.path.join(glob.escape(root), 'users', '*', 'Saved Games',
                                                          'Diablo II'))) if os.path.isdir(f)]
        found.sort(key=lambda f: os.path.basename(os.path.dirname(os.path.dirname(f))).lower() == 'public')
        if found:
            return found[0]
    if os.name == 'nt':
        saved_games = (None if home is not None else _windows_saved_games())
        saved_games = saved_games or os.path.join(
            home or os.environ.get('USERPROFILE') or os.path.expanduser('~'), 'Saved Games')
        p = _filesystem_path(os.path.join(saved_games, 'Diablo II'))
        if os.path.isdir(p):
            return p
    local = _child(game_dir, 'Save')
    return local if local and os.path.isdir(local) else None


def _use_save_dir(game_dir, root=None, info=None):
    """MXL_SAVE_DIR set by the user wins; the Linux launcher's own guess (the Median XL save folder,
    MXL_SAVE_DIR_AUTO=1) or none is replaced by the profile game's save folder. When that game has none, an empty
    folder of the profile (root/saves) - never the Median XL saves (the collector's own default)."""
    if os.environ.get('MXL_SAVE_DIR') and not os.environ.get('MXL_SAVE_DIR_AUTO'):
        return None
    info = info or detect(game_dir)
    version = info.get('version') or ''
    if version.startswith('1.14') or not version and not info.get('mod'):
        d = save_dir(game_dir)        # 1.14 (mods too) saves in the user's Saved Games\Diablo II
    else:
        local = _child(game_dir, 'Save')
        d = local if local and os.path.isdir(local) else None
    if not d and root:
        d = os.path.join(root, 'saves')
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    if d:
        os.environ['MXL_SAVE_DIR'] = d
        os.environ['MXL_SAVE_DIR_AUTO'] = '1'
        # mxl_gui reads MXL_SAVE_DIR once at import (SAVE_DIR); when it is already imported (the launcher's
        # Median guess was read), point it at this game's folder too, or the Median saves/stashes get opened
        import sys
        g = sys.modules.get('mxl_gui')
        if g is not None and hasattr(g, 'SAVE_DIR'):
            g.SAVE_DIR = d
    return d


def profile_id(game_dir, info):
    h = hashlib.sha1(os.path.normcase(os.path.abspath(game_dir)).encode('utf-8', 'replace')).hexdigest()[:8]
    return f"{info['kind']}-{info['version'] or 'unknown'}-{h}" + ('-stock' if legit_stock() else '')


# ---------------------------------------------------------------------------------------------------- selection
def _raw_settings():
    try:
        import settings
    except ImportError:
        return {}
    for path in (settings.PATH, settings.PATH + '.bak'):
        try:
            return settings._read(path)
        except (OSError, ValueError):
            pass
    return {}


def choose():
    """The profile asked for: env MXL_GAME (median / vanilla / folder), else settings 'game_profile'.
    Returns (kind, game_dir) with kind 'median' or 'folder'."""
    env = (os.environ.get('MXL_GAME') or '').strip().lower()
    s = _raw_settings()
    if env in ('median', 'mxl'):
        return 'median', None
    saved = s.get('profile_game_dir')
    folder = saved if isinstance(saved, str) and saved else None
    if env in ('vanilla', 'folder', 'd2'):
        return 'folder', os.environ.get('MXL_GAME_DIR') or folder or DEFAULT_VANILLA
    selected = s.get('game_profile')
    if selected == 'folder' and folder:
        return 'folder', folder
    if selected == 'folder' or (not selected and not s.get('profile_chosen')):
        legacy = s.get('game_dir')
        info = detect(legacy)
        if info['kind'] == 'd2':
            return 'folder', legacy
    return ('folder', DEFAULT_VANILLA) if selected == 'folder' else ('median', None)


def active():
    """The active folder profile (dict) or None in Median mode."""
    return _state


def is_median():
    return _state is None


def vanilla_ui_theme():
    return bool((_state if _state is not None else _raw_settings()).get('vanilla_ui_theme', False))


# ---------------------------------------------------------------------------------------------------- extraction
def _fingerprint(game_dir, info=None):
    fp = {}
    info = info or detect(game_dir)
    archives = archive_order(game_dir, info)
    loose = _loose_excel(game_dir)
    for p in [*archives, *sorted(loose.values())]:
        try:
            st = os.stat(p)
            fp[p] = [st.st_size, st.st_mtime_ns]
        except OSError:
            pass
    return {'extract_version': EXTRACT_VERSION, 'inputs': fp, 'archive_order': archives,
            'version': info['version']}


def _open(paths, *, extracting=False):
    from time import perf_counter

    from mxl_boot import phase
    from mxl_profile_mpq import ProfileMPQ

    out = []
    for p in paths:
        started = perf_counter()
        _log(f'opening archive {p}')
        try:
            archive = ProfileMPQ(p)
            archive.profile_path = p
            out.append(archive)
            phase(f'open archive {p}', started)
        except Exception as err:
            if extracting and getattr(err, 'winerror', None) in (32, 33):
                from mxl_boot import ProfileArchiveLocked
                raise ProfileArchiveLocked(p) from err
            _log(f'could not open archive {p}: {err}')
    return out


def _read(archives, name):
    for m in archives:
        try:
            data = m.read(name)
            if data:
                return data
        except Exception as err:
            _log(f'could not read {name} from {getattr(m, "profile_path", "archive")}: {err}')
    return None


def data_ok(game_dir, out, info=None):
    try:
        with open(os.path.join(out, 'install.json'), encoding='utf-8') as f:
            man = json.load(f)
    except (OSError, ValueError):
        return False
    return (isinstance(man, dict) and man.get('fingerprint') == _fingerprint(game_dir, info)
            and os.path.isfile(os.path.join(out, 'itemstatcost.bin')))


def extract(game_dir, out, progress=None, icons=True):
    """Tables, strings, animdata.d2 and item icons of the folder's MPQ stack -> out/ (written to out.new, then
    swapped in: an interrupted extraction never leaves a half folder)."""
    import shutil
    from time import perf_counter

    from mxl_boot import phase

    started = perf_counter()
    tmp = out + '.new'
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    from mxl_profile_tables import EXCEL_PATH, TEXT_LAYOUTS, apply, project_legacy, text_layouts
    info = detect(game_dir)
    fingerprint = _fingerprint(game_dir, info)
    phase('detect extraction profile', started)
    started = perf_counter()
    local = _directory_archives(game_dir) if info.get('mod') else []
    if legit_stock():
        local = [p for p in local if os.path.basename(p).lower() in BASE_ARCHIVE_NAMES]
    mod_stack = _open([p for p in local if not os.path.basename(p).lower().startswith(_NO_DATA)], extracting=True)
    base_stack = _open([p for p in fingerprint['archive_order']
                        if p not in local and not os.path.basename(p).lower().startswith(_NO_DATA)], extracting=True)
    stack = mod_stack + base_stack
    phase('open archive stack', started)
    started = perf_counter()
    loose = _loose_excel(game_dir)
    names = set(EXCEL) | {n.rsplit('.', 1)[0] for n in loose}
    for m in stack:
        _log(f'reading (listfile) from {m.profile_path}')
        lf = _read((m,), '(listfile)')
        for line in (lf or b'').decode('latin1').splitlines():
            low = line.strip().lower().replace('/', '\\')
            if low.startswith(EXCEL_PATH) and low.endswith(('.bin', '.txt')):
                name = low[len(EXCEL_PATH):].rsplit('.', 1)[0]
                if name and '\\' not in name and ':' not in name:
                    names.add(name)

    files = {}
    preferred = {}
    sizes = dict(TEXT_LAYOUTS)
    if info.get('save_version') == 96:
        sizes.update({name: size for name, (size, fields) in text_layouts().items()})

    def read_text(name):
        path = loose.get(name + '.txt')
        return _read_loose(path) if path else _read(stack, EXCEL_PATH + name + '.txt')

    for k, name in enumerate(sorted(names)):
        _log(f'reading Excel table {name}')
        bin_name, txt_name = name + '.bin', name + '.txt'
        bin_path, txt_path = loose.get(bin_name), loose.get(txt_name)

        def sources():
            if bin_path or txt_path:
                yield (_read_loose(bin_path) if bin_path else None,
                       _read_loose(txt_path) if txt_path else None, True)
            for archive in mod_stack:
                yield (_read((archive,), EXCEL_PATH + bin_name),
                       _read((archive,), EXCEL_PATH + txt_name) if name in sizes else None, True)
            # Stock archives can ship text without the generated companion records in the same MPQ.
            # Resolve the effective compiled table over the whole base stack before falling back to text.
            yield (_read(base_stack, EXCEL_PATH + bin_name),
                   _read(base_stack, EXCEL_PATH + txt_name) if name in sizes else None, False)

        for binary, txt, is_override in sources():
            compatible = (name in sizes and binary and len(binary) > 4
                          and len(binary) - 4 == struct.unpack_from('<I', binary)[0] * sizes[name])
            if txt and name in sizes and (is_override or not compatible):
                files[txt_name] = preferred[name] = txt
                # The same or lower compiled table supplies fields absent from the TXT.
                binary = binary or _read(stack, EXCEL_PATH + bin_name)
            elif txt and name == 'itemstatcost':
                files[txt_name] = txt
            if binary:
                files[bin_name] = binary
            if binary or name in preferred:
                break
        if progress:
            progress('tables', k + 1, len(names))
    for n in STRINGS:
        _log(f'reading string table {n}')
        d = _read(stack, f'data\\local\\lng\\eng\\{n}.tbl')
        if d:
            files[n + '.tbl'] = d
    _log('reading animdata.d2')
    d = _read(stack, 'data\\global\\animdata.d2')
    if d:
        files['animdata.d2'] = d
    if 'itemstatcost.bin' not in files and 'itemstatcost' not in preferred:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f'no game tables in {game_dir}')
    for n, d in files.items():
        with open(os.path.join(tmp, n), 'wb') as f:
            f.write(d)
    phase('read game tables and strings', started)
    started = perf_counter()
    if info.get('save_version') in (87, 89, 92):
        project_legacy(Path(tmp))
    apply(Path(tmp), preferred, info.get('save_version'), read_text)
    if not os.path.isfile(os.path.join(tmp, 'itemstatcost.bin')):
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f'no usable item stat table in {game_dir}')
    phase('project game table layouts', started)
    if icons:
        started = perf_counter()
        import mxl_data
        import mxl_gfx
        items = os.path.join(tmp, 'items')
        os.makedirs(items, exist_ok=True)
        o_open, o_read, o_decode = mxl_gfx.open_archives, mxl_gfx.read_file, mxl_gfx.decode_dc6
        mxl_gfx.open_archives = lambda _: stack

        def read_icon(archives, name):
            _log(f'reading artwork {name}')
            return _read(archives, name)

        def decode_icon(raw, palette):
            offset = struct.unpack_from('<I', raw, 24)[0]
            width, height = struct.unpack_from('<II', raw, offset + 4)
            if not 0 < width <= 2048 or not 0 < height <= 2048:
                raise ValueError(f'invalid item icon dimensions {width}x{height}')
            return o_decode(raw, palette)

        mxl_gfx.read_file = read_icon
        mxl_gfx.decode_dc6 = decode_icon

        def icon_progress(done, total):
            if done == 1 or done == total or done % 50 == 0:
                _log(f'decoding item icons: {done}/{total}')
            if progress:
                progress('icons', done, total)
        try:
            mxl_gfx.extract_icons(game_dir, mxl_data.Data(tmp), items, progress=icon_progress)
            try:
                mxl_gfx.extract_ui(game_dir, items)
            except Exception as err:
                _log(f'could not extract socket artwork: {err}')
        finally:
            mxl_gfx.open_archives, mxl_gfx.read_file, mxl_gfx.decode_dc6 = o_open, o_read, o_decode
        phase('decode item and socket icons', started)
    if _fingerprint(game_dir) != fingerprint:
        raise RuntimeError(f'Game files changed during extraction for {game_dir}. Try opening the editor again.')
    with open(os.path.join(tmp, 'install.json'), 'w', encoding='utf-8') as f:
        json.dump({'game_dir': game_dir, 'fingerprint': fingerprint,
                   'files': sorted(files)}, f, indent=1)
    _publish_data(tmp, out)
    return out


def _read_loose(path):
    with open(path, 'rb') as file:
        data = file.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise ValueError(f'oversized Excel file {path}')
    return data


def _publish_data(source, out):
    import shutil

    old = out + '.old'
    if os.path.exists(old) and not os.path.exists(out):
        os.replace(old, out)
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(out):
        os.replace(out, old)
    try:
        os.replace(source, out)
    except OSError:
        if os.path.exists(old):
            os.replace(old, out)
        raise
    shutil.rmtree(old, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------- install
# ---------------------------------------------------------------------------------------------------- first launch
def _patch_no_game():
    """The collector's start() asks for the Median XL folder in a blocking dialog (an info box, then a folder chooser
    that repeats until a Median folder is given) whenever none is saved: people without Median XL could not open the
    editor. No folder now means: open without one; pages that need the tables show a hint, "Game folder..." sets it."""
    try:
        import mxl_gui_install as gi
    except Exception:
        return
    GI = gi.GameInstall
    if getattr(GI.start, '_capy_nogame', False):
        return
    o_start = GI.start

    def start(self):
        if not gi.is_game_dir(self.game_dir):
            self.game_dir = None
            _log('no game folder saved: opening without one (Game folder... sets it)')
            return None
        return o_start(self)
    start._capy_nogame = True
    GI.start = start


def _candidates(kind):
    """Likely install folders of the game, checked with detect() (only the folder's listing is read)."""
    import glob
    home = os.path.expanduser('~')
    pf = [os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), r'C:\Program Files (x86)',
          r'C:\Program Files', r'C:\Games']
    names = ['Median XL', 'MedianXL', 'median-xl'] if kind == 'median' else ['Diablo II', 'Diablo II LoD']
    out = [os.environ.get('MXL_FIRSTRUN_FOLDER') or '']
    if kind == 'folder':
        out.append(DEFAULT_VANILLA)
    for b in pf:
        out += [os.path.join(b, n) for n in names if b]
    for pat in ('Games/*/drive_c/Program Files (x86)/', 'Games/*/drive_c/games/', '.wine/drive_c/Program Files (x86)/',
                '.wine/drive_c/games/'):
        for b in sorted(glob.glob(os.path.join(glob.escape(home), pat))):
            out += [os.path.join(b, n) for n in names]
    want = 'median' if kind == 'median' else 'd2'
    return [d for d in out if d and (info := detect(d))['kind'] == want and info['supported']]


def needs_first_launch():
    """True when nothing says which game to open: no profile chosen, no MXL_GAME, no usable saved game folder."""
    if os.environ.get('MXL_GAME'):
        return False
    s = _raw_settings()
    if s.get('profile_chosen') or s.get('game_profile'):
        return False
    return not (s.get('game_dir') and detect(s.get('game_dir'))['kind'])


def first_launch():
    """The first-launch dialog (before the main window): Vanilla 1.14d or Median XL, a game folder (auto-detected,
    Browse...), or Skip. The answer is remembered in settings ('profile_chosen', 'game_profile', 'game_dir' /
    'profile_game_dir'); More > Game profile... changes it later. MXL_FIRSTRUN_CHOICE=vanilla|median|skip answers
    it without a click (tests); the dialog is still built."""
    if not needs_first_launch():
        return None
    import tkinter as tk
    from tkinter import ttk, filedialog
    import settings
    from mxl_lang import T
    auto = (os.environ.get('MXL_FIRSTRUN_CHOICE') or '').strip().lower()
    root = tk.Tk()
    root.withdraw()
    w = tk.Toplevel(root)
    w.title(T('first.title', 'Choose a game'))
    kind = tk.StringVar(value='folder')
    folder = tk.StringVar()
    result = []
    f = ttk.Frame(w, padding=10)
    f.pack(fill='both', expand=True)
    ttk.Label(f, text=T('first.ask', 'Which game do you want to edit characters for?')).grid(
        row=0, column=0, columnspan=3, sticky='w')
    ttk.Radiobutton(f, text=T('first.vanilla', 'Vanilla 1.14d (Diablo II Lord of Destruction)'), value='folder',
                    variable=kind).grid(row=1, column=0, columnspan=3, sticky='w', pady=(6, 0))
    ttk.Radiobutton(f, text=T('first.median', 'Median XL'), value='median', variable=kind).grid(
        row=2, column=0, columnspan=3, sticky='w')
    ttk.Label(f, text=T('first.folder', 'Game folder (detected automatically when possible):')).grid(
        row=3, column=0, columnspan=3, sticky='w', pady=(8, 0))
    ttk.Entry(f, textvariable=folder, width=52).grid(row=4, column=0, columnspan=2, sticky='we')
    info = ttk.Label(f, text='')
    info.grid(row=5, column=0, columnspan=3, sticky='w')

    def valid():
        d = detect(folder.get().strip())
        if kind.get() == 'median':
            return d['kind'] == 'median'
        return d['kind'] == 'd2' and d['supported']

    ok_btn = ttk.Button(f, text=T('profile.ok', 'OK'))

    def refresh(*_):
        d = folder.get().strip()
        if not d:
            msg = T('first.nofolder', 'No folder chosen yet.')
        elif valid():
            msg = T('profile.detected', 'Detected: {k} {v}', k=detect(d)['kind'], v=detect(d)['version'] or '')
        else:
            msg = T('first.notfound', 'Not a game folder of this kind.')
        info.configure(text=msg)
        # vanilla needs its folder (the tables come from it); Median may be set later with "Game folder..."
        ok_btn.state(['!disabled'] if (valid() or kind.get() == 'median') else ['disabled'])

    def pick(*_):
        found = _candidates(kind.get())
        folder.set(found[0] if found else '')
        refresh()

    def browse():
        d = filedialog.askdirectory(parent=w, initialdir=folder.get() or None)
        if d:
            folder.set(d)
    ttk.Button(f, text=T('profile.browse', 'Browse...'), command=browse).grid(row=4, column=2, padx=(4, 0))
    folder.trace_add('write', refresh)
    kind.trace_add('write', pick)

    def finish(how):
        if how == 'ok' and kind.get() == 'folder' and not valid():
            if not auto:
                refresh()
                return
            how = 'skip'
        if how == 'ok':
            d = folder.get().strip()
            if kind.get() == 'folder':
                settings.put('profile_game_dir', d)
            elif valid():
                settings.put('game_dir', d)
            settings.put('game_profile', kind.get())
        settings.put('profile_chosen', True)
        result.append(how)
        w.destroy()
    ok_btn.configure(command=lambda: finish('ok'))
    ok_btn.grid(row=6, column=1, sticky='e', pady=(8, 0))
    ttk.Button(f, text=T('first.skip', 'Skip'), command=lambda: finish('skip')).grid(row=6, column=2, pady=(8, 0))
    f.columnconfigure(0, weight=1)
    w.protocol('WM_DELETE_WINDOW', lambda: finish('skip'))
    pick()
    _log('first launch dialog shown')
    if auto:
        kind.set('median' if auto == 'median' else 'folder')
        pick()
        w.after(300, lambda: finish('skip' if auto == 'skip' else 'ok'))
    w.update_idletasks()
    w.geometry('+%d+%d' % ((w.winfo_screenwidth() - w.winfo_reqwidth()) // 2,
                           (w.winfo_screenheight() - w.winfo_reqheight()) // 3))
    if not auto:
        w.grab_set()
    w.wait_window()
    root.destroy()
    return result[0] if result else None


class _Empty(dict):
    """An empty table of the tolerant Data below: iterates / indexes like an empty dict or list."""
    def append(self, *_):
        pass


_EMPTY_ATTRS = ('isc csv_bits props prop_func prop_funcs prop_vals low_quality quality_mods affixes rare_prefix '
                'rare_suffix uniques set_items runewords runeword_mods itypes itype_class itype_gfx block_factor '
                'skill_names skill_class skill_req bases item_index gems strings anim').split()


def patch_gui(mxl_gui):
    """Called with the imported mxl_gui. Its App reads the game tables (data/) in the constructor and, when they are
    missing, shows an error box and quits: nobody without Median XL (or with the folder not chosen yet) could open
    the editor. With no tables the editor now opens on empty ones; the top bar says to choose the game folder."""
    from time import perf_counter

    from mxl_boot import phase

    o = getattr(mxl_gui, 'Data', None)
    if o is None or getattr(o, '_capy_tolerant', False):
        return

    class Data(o):
        _capy_tolerant = True

        def __init__(self, folder, *a, **k):
            started = perf_counter()
            try:
                o.__init__(self, folder, *a, **k)
                self.empty = False
            except FileNotFoundError as err:
                if _state and _state['supported']:
                    raise
                _log(f'game tables missing ({err.filename}): opening with empty tables')
                self.folder = folder
                self.empty = True
                for name in _EMPTY_ATTRS:
                    if not hasattr(self, name):
                        setattr(self, name, _Empty())
                if not hasattr(self, 'monster_names'):
                    self.monster_names = []
            finally:
                if _state is not None:
                    phase('load editor data', started)
    mxl_gui.Data = Data
    try:
        import mxl_gui_install as gi
        o_show = gi.GameInstall.show_game

        def show_game(self, *a, **k):
            if getattr(self, 'label', None) is not None and not gi.is_game_dir(self.game_dir):
                from mxl_lang import T
                self.label.configure(text=T('first.hint', 'No game folder chosen: use "Game folder..." to select it'))
                return None
            return o_show(self, *a, **k)
        if not getattr(gi.GameInstall.show_game, '_capy_hint', False):
            show_game._capy_hint = True
            gi.GameInstall.show_game = show_game
    except Exception as err:
        _log(f'game folder hint not installed ({err})')


def install():
    """Before mxl_gui is imported (it copies paths.DATA_DIR at import). Median: nothing. Never raises for Median."""
    global _state
    _patch_no_game()
    try:
        first_launch()
    except Exception as err:                          # never a dead start
        _log(f'first launch dialog failed ({type(err).__name__}: {err})')
    kind, game_dir = choose()
    if kind == 'median':
        return None
    import paths
    from time import perf_counter

    from mxl_boot import phase, extract_profile

    started = perf_counter()
    info = detect(game_dir)
    phase('detect game profile', started)
    available = info['kind'] == 'd2' and info['supported']
    if not available:
        _log(f'game profile unavailable: {game_dir} ({_detection_label(info)})')
        info = dict(info, supported=False, kind=None)
    pid = profile_id(game_dir, info)
    root = _filesystem_path(os.path.join(paths.USER_DIR, 'profiles', pid))
    data_dir = os.path.join(root, 'data')
    if available:
        started = perf_counter()
        cached = data_ok(game_dir, data_dir, info)
        phase('check game data cache', started)
        if not cached:
            _log(f'game profile {pid}: extracting tables and icons from {game_dir}')
            extract_profile(game_dir, data_dir)
    _state = dict(info, game_dir=game_dir, id=pid, root=root, data_dir=data_dir,
                  vanilla_ui_theme=vanilla_ui_theme())
    started = perf_counter()
    _state['save_dir'] = _use_save_dir(game_dir if available else None, root, info if available else None)
    phase('select character save directory', started)
    _set_data_dir(data_dir)
    _patch_settings()
    _patch_format()
    _patch_gfx()
    _patch_install()
    _patch_art()
    _patch_savecheck()
    _patch_pages()
    _patch_text()
    _patch_grids()
    _log(f'game profile {pid}: data {data_dir}')
    return _state


def _log(msg):
    try:
        import mxl_log
        mxl_log.log.info(msg)
    except Exception:
        pass


def _patch_settings():
    """Expose the folder profile's game directory and its own last character and stash selection."""
    import settings
    o_load, o_put = settings.load, settings.put
    selection = ('last_character', 'last_stash', 'last_view', 'last_page')

    def profile_key(key):
        return f"profile_{_state['id']}_{key}"

    def load():
        s = dict(o_load())
        s['game_dir'] = _state['game_dir']
        for key in selection:
            s.pop(key, None)
            scoped_key = profile_key(key)
            if scoped_key in s:
                s[key] = s[scoped_key]
        return s

    def put(key, value):
        if key == 'game_dir':
            key = 'profile_game_dir'
        elif key in selection:
            key = profile_key(key)
        settings.load = o_load                         # the collector's put() reads load(): the file's own values
        try:
            return o_put(key, value)
        finally:
            settings.load = load
    settings.load, settings.put = load, put


def _patch_format():
    """1.10-1.14d items: set / unique ids are 12 bits (Sigma: 15), in every reader / writer that copied the width."""
    import importlib
    for name in ('mxl_format', 'mxl_format_fix', 'mxl_creator', 'mxlsave.items'):
        try:
            importlib.import_module(name).SET_UNIQUE_ID_BITS = 12
        except Exception:
            pass
    for name, attr in (('mxl_format_fix', 'LENIENT'), ('mxl_char', 'STATS_LENIENT')):
        try:                                           # ears, opaque items, junk before 'if' (hacked clone saves)
            setattr(importlib.import_module(name), attr, True)
        except Exception:
            pass


def _patch_gfx():
    """The collector's icon reader opens medianxl-*.mpq + lower-case base names: the folder's stack instead."""
    import mxl_gfx
    mxl_gfx.open_archives = _open_stack


_NO_DATA = ('d2music', 'd2xmusic', 'd2video', 'd2xvideo', 'd2speech', 'd2xtalk', 'd2sfx')


def _open_stack(game_dir):
    """The folder's archives that hold tables / art, highest priority first (sound / video archives left out)."""
    return _open([p for p in archive_order(game_dir) if not os.path.basename(p).lower().startswith(_NO_DATA)])


def _patch_pages():
    """The Mercenary page maps the type through the vanilla expansion hireling rows (mxl_merc.hirelings); as a
    guard the page is also dirty only when its values changed since it was built (a SAVE without edits never
    rewrites the mercenary)."""
    try:
        import mxl_merc
    except Exception:
        return
    P = mxl_merc.MercPage
    o_init, o_dirty = P.__init__, P.dirty

    def __init__(self, *a, **k):
        o_init(self, *a, **k)
        try:
            self._profile_base = self.values()
        except Exception:
            self._profile_base = None

    def dirty(self):
        base = getattr(self, '_profile_base', None)
        try:
            if base is not None and self.values() == base:
                return False
        except Exception:
            pass
        return o_dirty(self)
    P.__init__, P.dirty = __init__, dirty


def skill_tab_text(data, param, value):
    """Stat 188 (+n to a class skill tab) the way the game writes it (descfunc 14): param = class * 8 + tab, the
    tab's string from charstats (StrSkillTab1-3) and the class's StrClassOnly. None when the row is unknown."""
    import struct
    cls, tab = (param or 0) >> 3, (param or 0) & 7
    try:
        row = data._rows('charstats')[cls]
        ids = struct.unpack_from('<4H', row, 84)      # StrSkillTab1, 2, 3, StrClassOnly (D2-Development-Kit layout)
    except Exception:
        return None
    if tab > 2:
        return None

    def text(i):
        t = data.strings.get(i)
        return (t[1] if isinstance(t, tuple) else t) or ''
    fmt = text(ids[tab])
    if not fmt:
        return None
    try:
        line = fmt.replace('%d', str(value), 1) if '%d' in fmt else f'+{value} {fmt}'
    except Exception:
        return None
    only = text(ids[3])
    return f'{line} {only}' if only else line


def _fix_isc(data):
    """Vanilla itemstatcost rows the collector renders without their value: 17 / 18 (descfunc 3, descval 0 -
    the game prints them through its own Enhanced Damage line) become '+N% <text>' (descfunc 4, value first)."""
    if getattr(data, '_profile_isc', False):
        return
    for sid in (17, 18):
        try:
            c = data.isc[sid]
            if c.get('func') == 3 and not c.get('val'):
                c['func'], c['val'] = 4, 1
        except Exception:
            pass
    try:
        data._profile_isc = True
    except Exception:
        pass


def aura_text(data, param, value):
    """Stat 151 (descfunc 16): 'Level %d %s Aura When Equipped' with the level (value) and skill (param) name."""
    try:
        fmt = data.isc[151]['pos']
    except Exception:
        fmt = 'Level %d %s Aura When Equipped'
    nm = vanilla_skill_name(data, param)
    if '%d' in fmt and '%s' in fmt:
        return fmt.replace('%d', str(value), 1).replace('%s', str(nm), 1)
    return f'Level {value} {nm} Aura When Equipped'


def vanilla_skill_name(data, sid):
    from mxl_rownames import skill_derived

    sid = sid or 0
    name = data.skill_names.get(sid)
    if name and not missing_stat_text(name):
        return name
    return (skill_derived(data, sid) if isinstance(sid, int) else None) or f'Skill {sid}'


def missing_stat_text(text):
    return not text or 'an evil force' in str(text).casefold()


def stat_row_name(data, sid):
    """Readable ItemStatCost key from the selected game's text table."""
    if is_median():
        return None
    if '_capy_stat_row_names' not in data.__dict__:
        import csv

        names = {}
        try:
            with open(os.path.join(data.folder, 'itemstatcost.txt'),
                      encoding='latin-1', newline='') as table:
                for row in csv.DictReader(table, delimiter='\t'):
                    key = row.get('Stat', '')
                    index = row.get('ID', '').strip()
                    if key and index.isdecimal():
                        names[int(index)] = key
        except (AttributeError, OSError):
            pass
        data._capy_stat_row_names = names
    key = data._capy_stat_row_names.get(sid)
    if not key:
        return f'Stat {sid}'
    key = key.removeprefix('item_')
    labels = {
        'damagepercent': 'Damage %', 'manarecovery': 'Mana recovery',
        'coldlength': 'Cold duration', 'poisonlength': 'Poison duration',
        'velocitypercent': 'Movement speed %', 'attackrate': 'Attack rate',
        'maxdurability': 'Maximum durability', 'timeduration': 'Duration',
        'doubleherbduration': 'Double potion duration', 'lightcolor': 'Light color',
        'levelreq': 'Required level', 'levelreqpct': 'Required level %',
        'nonclassskill': 'Non-class skill bonus', 'singleskill': 'Class skill bonus',
        'extrablood': 'Extra blood', 'throw_mindamage': 'Minimum throw damage',
        'throw_maxdamage': 'Maximum throw damage', 'numsockets': 'Socket count',
        'absorb_pois_perlevel': 'Poison absorb per level',
        'absorb_pois_bytime': 'Poison absorb by time',
        'passive_mastery_melee_th': 'Melee mastery attack rating',
        'passive_mastery_melee_dmg': 'Melee mastery damage',
        'passive_mastery_melee_crit': 'Melee mastery critical strike',
        'passive_mastery_throw_th': 'Throwing mastery attack rating',
        'passive_mastery_throw_dmg': 'Throwing mastery damage',
        'passive_mastery_throw_crit': 'Throwing mastery critical strike',
        'passive_weaponblock': 'Passive weapon block',
        'questitemdifficulty': 'Quest item difficulty',
        'passive_mag_mastery': 'Passive magic mastery',
        'passive_mag_pierce': 'Passive magic pierce',
    }
    return labels.get(key, key.replace('_', ' ').capitalize())


def fallback_stat_line(data, stat):
    sid = stat['id']
    param = stat.get('param')
    suffix = f' (parameter {param})' if param is not None else ''
    return f"{stat_row_name(data, sid)}: {stat['value']}{suffix}"


def _stat_skill(st):
    """Skill id of a direct skill bonus, aura, chance to cast, or charged skill."""
    sid, p = st['id'], st.get('param') or 0
    if sid in (97, 107, 151):
        return p
    if 195 <= sid <= 213:
        return p >> 6
    return None


def unnamed_skill_text(data, st):
    """Render a skill stat whose skill has no translated display name."""
    sk = _stat_skill(st)
    if sk is None or (sk != 0 and not missing_stat_text(data.skill_names.get(sk))):
        return None
    sid, v, nm = st['id'], int(st.get('value') or 0), vanilla_skill_name(data, sk)
    c = data.isc.get(sid) or {}
    fmt = str(c.get('pos') or '')
    if sid == 151:
        return aura_text(data, st.get('param'), v)
    if sid in (97, 107):                                   # direct skill bonus
        return f'{v:+d} to {nm}'
    lvl = (st.get('param') or 0) & 63
    if c.get('func') == 15 and fmt.count('%d') == 2 and '%s' in fmt:     # '%d%% Chance to cast level %d %s on ...'
        return fmt.replace('%d', str(v), 1).replace('%%', '%').replace('%d', str(lvl), 1).replace('%s', nm, 1)
    return None


def _string(data, key, prefer_newline=False):
    """Text of a string key: the later table's (patch > expansion > classic, the game's order); with
    prefer_newline the item-display variant (it ends with a newline) when the tables hold several."""
    hits = [(i, v[1]) for i, v in data.strings.items() if isinstance(v, tuple) and v[0] == key and v[1]]
    hits.sort(key=lambda h: (prefer_newline and not h[1].endswith('\n'), -h[0]))   # later tables win
    return hits[0][1] if hits else None


def _ed_text(data):
    return (_string(data, 'strModEnhancedDamage', True) or 'Enhanced Damage').strip()


def repair_text(data, value):
    """Descfunc 11 (stat 252): 'Repairs 1 durability in N seconds' (N = 100 / value), or per second from 100 up."""
    v = int(value or 0)
    if v <= 0:
        return None
    if v >= 100:
        fmt = data.isc[252]['pos'] if '%d' in str(data.isc[252]['pos']) else 'Repairs %d durability per second'
        return fmt.replace('%d', str(v // 100), 1)
    fmt = _string(data, 'ModStre9u') or 'Repairs %d durability in %d seconds'
    return fmt.replace('%d', '1', 1).replace('%d', str(max(1, 100 // v)), 1)


def _patch_text():
    """Stat lines with the vanilla game's own strings / descfuncs:
    - 188 (skill tab) through charstats, not the raw '+%d to Javelin and Spear Skills' for every tab;
    - 151 (aura when equipped) with its level and skill name, not 'Level %d %s Aura When Equipped';
    - 17 / 18 with their value; equal ones as the game's single '+N% Enhanced Damage' line;
    - 252 (descfunc 11) as 'Repairs 1 durability in N seconds';
    - no 'damage per Strength / Dexterity' lines under the weapon damage (Median XL's use of the string keys
      charmontohit1X / 2X, which are 'Average chance %s will hit you: %d%%' in the vanilla tables).
    Vanilla tooltips show totals with any combined roll range."""
    try:
        import mxl_stat_text as M
    except Exception:
        return
    try:
        import mxl_tooltip
        mxl_tooltip.DMG_BONUS = ()
    except Exception:
        pass
    o_lines = M.stat_lines
    OWN = (188, 151, 252)

    def own_text(data, st):
        t = unnamed_skill_text(data, st)
        if t:
            return t
        sid, value = st['id'], st['value']
        if sid == 188:
            return skill_tab_text(data, st.get('param'), value)
        if sid == 252:
            return repair_text(data, value)
        if sid == 151:
            return aura_text(data, st.get('param'), value)
        return fallback_stat_line(data, st)

    def combined_ranges(ranges):
        totals = {}
        for key, sources in (ranges or {}).items():
            if not sources:
                continue
            value = low = high = 0
            for amount, limits, _source in sources:
                lo, hi = limits if limits is not None else (amount, amount)
                value += amount
                low += lo
                high += hi
            totals[key] = [(value, (low, high) if low != high else None, 'B')]
        return totals

    def charge_text(data, sid, param, current, maximum):
        skill, level = divmod(param or 0, 64)
        name = vanilla_skill_name(data, skill)
        fmt = str(data.isc[sid].get('pos') or '')
        tail = (fmt.replace('%d', str(current), 1).replace('%d', str(maximum), 1)
                if fmt.count('%d') >= 2 else f'({current}/{maximum} Charges)')
        return f"{data.key('ModStre10b') or 'Level'} {level} {name} {tail}"

    def stat_lines(stats, data, char=None, ranges=None, prio=False, two_handed=True,
                   per_level_rate=False, ranged=()):
        from mxl_format_fix import bytime_parts, bytime_range_text, is_bytime

        _fix_isc(data)
        mine, rest = [], []
        charges, timed = {}, {}
        for st in stats or ():
            sid, param = st['id'], st.get('param') or None
            info = data.isc.get(sid) or {}
            if info.get('func') == 24:
                current, maximum = charges.get((sid, param), (0, 0))
                value = int(st['value'])
                charges[sid, param] = current + (value & 255), maximum + (value >> 8)
                continue
            if is_bytime(info):
                period, low, high = bytime_parts(st['value'])
                previous = timed.get((sid, period), (0, 0))
                timed[sid, period] = previous[0] + low, previous[1] + high
                continue

            normalized = st if 'param' in st and st['param'] == param else dict(st, param=param)
            if sid in OWN or unnamed_skill_text(data, st) is not None:
                mine.append(normalized)
                continue
            if sid in data.isc:
                rest.append(normalized)
            # The host still needs raw fields such as poison duration to format damage.
            if sid not in (97, 107) and missing_stat_text(info.get('desc')):
                mine.append(normalized)

        out = [line for line in o_lines(rest, data, char, combined_ranges(ranges), True,
                                        two_handed, per_level_rate, ranged)
               if not missing_stat_text(line[2])]

        damage = M._merge_stats([st for st in rest if st['id'] in (17, 18)])
        ed = {st['id']: st['value'] for st in damage}
        if len(ed) == 2 and ed[17] == ed[18]:
            value = ed[17]
            labels = {f"+{value}% {data.isc[sid]['pos'].strip()}" for sid in ed}
            hits = [i for i, line in enumerate(out) if str(line[2]) in labels]
            if len(hits) == 2:
                priority, color, _text, inline, below = out[hits[0]]
                out[hits[0]] = (priority, color, f'+{value}% {_ed_text(data)}', inline, below)
                del out[hits[1]]

        def append(sid, text):
            if text:
                priority = (data.isc.get(sid) or {}).get('prio', 0)
                out.append((priority, getattr(M, 'BLUE', '3'), text, [], []))

        for st in M._merge_stats(mine):
            append(st['id'], own_text(data, st))
        for (sid, param), (current, maximum) in charges.items():
            append(sid, charge_text(data, sid, param, current, maximum))
        for (sid, period), (low, high) in timed.items():
            append(sid, bytime_range_text(data.isc[sid], period, low, high, data))

        out.sort(key=lambda line: -line[0])
        return out if prio else [line[1:] for line in out]

    stat_lines.__wrapped__ = o_lines
    M.stat_lines = stat_lines
    for name in ('mxl_tooltip', 'mxl_statparse', 'mxl_catalog_tooltip', 'mxl_gui_detail'):
        mod = __import__('sys').modules.get(name)
        if mod is not None and getattr(mod, 'stat_lines', None) is o_lines:
            mod.stat_lines = stat_lines


def grid_sizes(data_dir):
    """{'inv': (w, h), 'stash': (w, h), 'stash_classic': (w, h), 'cube': (w, h)} from the profile's inventory.bin
    (gridX / gridY at 16 / 17 of each 240-byte row; rows: 0 Amazon ... 8 Bank Page 1, 9 Transmogrify Box,
    12 Big Bank Page 1, 14 Druid, 15 Assassin - the low-resolution rows)."""
    import struct
    out = {'inv': (10, 4), 'stash': (6, 8), 'stash_classic': (6, 4), 'cube': (3, 4)}
    try:
        with open(os.path.join(data_dir, 'inventory.bin'), 'rb') as f:
            b = f.read()
        n = struct.unpack_from('<I', b)[0]
        rs = (len(b) - 4) // n

        def grid(i):
            r = b[4 + i * rs:4 + (i + 1) * rs]
            return (r[16], r[17]) if 0 < r[16] < 32 and 0 < r[17] < 32 else None
        cls = [grid(i) for i in (0, 1, 2, 3, 4, 14, 15) if i < n]
        cls = [g for g in cls if g]
        if cls:
            out['inv'] = (max(g[0] for g in cls), max(g[1] for g in cls))
        for key, i in (('stash_classic', 8), ('cube', 9), ('stash', 12)):
            if i < n and grid(i):
                out[key] = grid(i)
    except (OSError, ValueError, ZeroDivisionError, struct.error, IndexError):
        pass
    return out


def belt_rows(data, code):
    """Rows (of 4) of a belt item: armor.bin 'belt' (offset 304) -> belts.bin numboxes (offset 4) / 4; 4 when
    unknown (D2-Development-Kit layouts)."""
    import struct
    try:
        folder = data.folder
        with open(os.path.join(folder, 'armor.bin'), 'rb') as f:
            a = f.read()
        n = struct.unpack_from('<I', a)[0]
        rs = (len(a) - 4) // n
        for i in range(n):
            r = a[4 + i * rs:4 + (i + 1) * rs]
            if r[128:132].decode('latin1').strip() == code.strip():
                with open(os.path.join(folder, 'belts.bin'), 'rb') as f:
                    bb = f.read()
                m = struct.unpack_from('<I', bb)[0]
                brs = (len(bb) - 4) // m
                k = r[304]
                return max(1, min(4, bb[4 + k * brs + 4] // 4)) if k < m else 4
    except Exception:
        pass
    return 4


def _patch_grids():
    """Inventory grid of the profile's game (vanilla 10 x 4, not Median's 15 x 10), from inventory.bin."""
    import sys
    g = grid_sizes(_state['data_dir'])
    _state['grids'] = g
    for name in ('mxl_char', 'mxl_inv_gui', 'mxl_char_gui'):
        mod = sys.modules.get(name) if name != 'mxl_char' else __import__('mxl_char')
        if mod is not None:
            mod.INV_W, mod.INV_H = g['inv']


def _patch_savecheck():
    """mxl_savecheck re-reads every written file with mxlsave, a Median XL parser (Sigma tables, 95 skill
    bytes): in a folder profile it is not asked (phase 2: a vanilla mode for mxlsave); the collector's own
    write-verify-backup path stays."""
    try:
        import mxl_savecheck
    except Exception:
        return
    mxl_savecheck.mode = lambda *a, **k: 'off'


def _patch_install():
    """The collector's Median install checks (medianxl-version.mpq, its manifest) do not apply: the profile's
    data folder is checked / extracted by install(); a folder change re-extracts."""
    import mxl_gui_install as gi

    def is_game_dir(d, *a, **k):
        info = detect(d)
        return info['kind'] == 'd2' and info['supported']
    gi.is_game_dir = is_game_dir
    GI = gi.GameInstall

    def ask_game_dir(self, first=False):
        # A restart also replaces the character list, art and format readers.
        open_dialog(self)

    GI.ask_game_dir = ask_game_dir

    def check_data(self, startup=False, *a, **k):
        if not is_game_dir(self.game_dir):
            return False
        moved = _rebind(self)
        from mxl_boot import extract_profile

        if not data_ok(self.game_dir, self.data_dir):
            extract_profile(self.game_dir, self.data_dir)
            moved = True
        if moved and not startup and self.on_rebuilt:
            self.on_rebuilt()
        return True
    GI.check_data = check_data

    def show_game(self, *a, **k):
        if getattr(self, 'label', None) is not None and _state:
            self.label.configure(text=_detection_label(_state))
    GI.show_game = show_game


def rebind(game_dir):
    """The active profile follows a new game folder ("Game folder..." button): its id, root and data folder are
    the new folder's (kind + version + folder hash), so the tables are extracted next to - never over - the old
    folder's. Returns the new data folder, or None when the folder is not a supported D2 folder or did not change."""
    import paths
    if _state is None or not game_dir:
        return None
    info = detect(game_dir)
    if info['kind'] != 'd2' or not info['supported']:
        return None
    pid = profile_id(game_dir, info)
    if pid == _state.get('id') and os.path.normcase(game_dir) == os.path.normcase(_state.get('game_dir') or ''):
        return None
    root = _filesystem_path(os.path.join(paths.USER_DIR, 'profiles', pid))
    data_dir = os.path.join(root, 'data')
    _state.update(info, game_dir=game_dir, id=pid, root=root, data_dir=data_dir)
    _set_data_dir(data_dir)
    _log(f'game profile {pid}: game folder {game_dir}, data {data_dir}')
    return data_dir


def _set_data_dir(data_dir):
    import sys
    import paths

    paths.DATA_DIR = data_dir
    paths.ICONS_DIR = os.path.join(data_dir, 'items')
    for name in ('mxl_gui', 'mxl_inv_gui'):
        mod = sys.modules.get(name)
        for attr, val in (('DATA_DIR', data_dir), ('ICONS_DIR', paths.ICONS_DIR)):
            if mod is not None and hasattr(mod, attr):
                setattr(mod, attr, val)


def _rebind(gi):
    d = rebind(getattr(gi, 'game_dir', None))
    if d:
        gi.data_dir = d
    return bool(d)


def _patch_art():
    """Art (panels, fonts, palettes, sprites) from the folder's MPQ stack, cached in the profile's folder (its
    own cache per "Use vanilla UI theme" state, renewed when the folder's archives change). With that setting the
    UI files (data\\global\\ui, fonts, palettes) come from the base archives first (d2data / d2exp / patch_d2),
    the folder's own art when they have none; items, sprites and everything else stay the folder's."""
    try:
        import mxl_d2look_art as A
    except Exception:
        return
    from mxl_profile_mpq import ProfileMPQ

    o_init = A.Art.__init__

    def __init__(self, game_dir, theme, cache_root):
        if _state:
            cache_root = os.path.join(_state['root'], 'ui_art-vanilla' if vanilla_ui_theme() else 'ui_art')
        o_init(self, game_dir, theme, cache_root)
    A.Art.__init__ = __init__
    o_stamp = A.Art.stamp

    def stamp(self):
        if not _state:
            return o_stamp(self)
        import glob
        import shutil
        st = hashlib.sha1(json.dumps(_fingerprint(self.game_dir), sort_keys=True).encode()).hexdigest()
        os.makedirs(self.cache, exist_ok=True)
        p = os.path.join(self.cache, 'stamp.txt')
        try:
            old = open(p).read()
        except OSError:
            old = None
        if old != st:
            for f in glob.glob(os.path.join(self.cache, '*.png')):
                try:
                    os.remove(f)
                except OSError:
                    pass
            shutil.rmtree(os.path.join(self.cache, 'raw'), ignore_errors=True)
            with open(p, 'w') as fh:
                fh.write(st)
    A.Art.stamp = stamp

    def mpqs(self):
        if self._mpqs is None:
            self._mpqs = A._Archives([p for p in archive_order(self.game_dir)
                                      if not os.path.basename(p).lower().startswith(_NO_DATA)], ProfileMPQ)
        return self._mpqs
    A.Art.mpqs = mpqs

    def base_mpqs(self):
        if self._base_mpqs is None:
            self._base_mpqs = [m for p in base_archives(self.game_dir)
                               if (m := A._archive(p, ProfileMPQ)) is not None]
        return self._base_mpqs
    A.Art.base_mpqs = base_mpqs
    o_read = A.Art.read
    ui = ('data\\global\\ui\\', 'data\\local\\font\\', 'data\\global\\palette\\')

    def read(self, name):
        if _state and vanilla_ui_theme() and name.lower().startswith(ui):
            try:
                return self.read_base(name)
            except A.ArtError:
                pass
        return o_read(self, name)
    A.Art.read = read


# ---------------------------------------------------------------------------------------------------- menu
def open_dialog(app):
    """More menu -> "Game profile...": Median XL or another game folder, + "Use vanilla UI theme". Restart needed."""
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import settings
    from mxl_lang import T
    root = getattr(app, 'root', None) or tk._default_root
    existing = root.children.get('capy_game_profile')
    if existing is not None:
        existing.lift()
        return
    s = _raw_settings()
    w = tk.Toplevel(root, name='capy_game_profile')
    w.title(T('profile.title', 'Game profile'))
    w.transient(root)
    selected, current = choose()
    kind = tk.StringVar(value=selected)
    folder = tk.StringVar(value=current or s.get('profile_game_dir') or DEFAULT_VANILLA)
    vui = tk.BooleanVar(value=bool(s.get('vanilla_ui_theme', False)))
    f = ttk.Frame(w, padding=6)
    f.pack(fill='both', expand=True)
    ttk.Radiobutton(f, text=T('profile.median', 'Median XL'), value='median', variable=kind).grid(
        row=0, column=0, columnspan=3, sticky='w')
    ttk.Radiobutton(f, text=T('profile.folder', 'Other game folder (Diablo II LoD 1.14d, ...)'), value='folder',
                    variable=kind).grid(row=1, column=0, columnspan=3, sticky='w')
    entry = ttk.Entry(f, textvariable=folder, width=48)
    entry.grid(row=2, column=0, columnspan=2, sticky='we', padx=(16, 2))

    def browse():
        d = filedialog.askdirectory(parent=w, initialdir=folder.get() or None)
        if d:
            folder.set(d)
    browse_btn = ttk.Button(f, text=T('profile.browse', 'Browse...'), command=browse)
    browse_btn.grid(row=2, column=2, sticky='e')
    info = ttk.Label(f, text='')
    info.grid(row=3, column=0, columnspan=3, sticky='w', padx=(16, 0))
    theme_btn = ttk.Checkbutton(f, text=T('profile.vanilla_ui', 'Use vanilla UI theme'), variable=vui)
    theme_btn.grid(row=4, column=0, columnspan=3, sticky='w', padx=(16, 0))

    def show(*_):
        choosing_folder = kind.get() == 'folder'
        for widget in (entry, browse_btn, base_btn, theme_btn):
            widget.state(['!disabled'] if choosing_folder else ['disabled'])
        if choosing_folder:
            detected = detect(folder.get().strip(), base.get())
            text = _detection_label(detected)
            if detected['kind'] == 'median':
                text = T('first.notfound', 'Not a game folder of this kind.')
        else:
            saved_median = s.get('game_dir')
            text = saved_median if detect(saved_median, '')['kind'] == 'median' else T(
                'first.nofolder', 'No folder chosen yet.')
        info.configure(text=text)

    base = tk.StringVar(value=s.get('profile_base_dir') or '')

    def browse_base():
        d = filedialog.askdirectory(parent=w, initialdir=base.get() or None,
                                    title='Choose the base Diablo II folder')
        if d and _base_install(d):
            base.set(d)
        elif d:
            messagebox.showerror('Game profile', 'Choose a Diablo II folder containing d2data.mpq.', parent=w)

    base_btn = ttk.Button(f, text='Base Diablo II folder…', command=browse_base)
    base_btn.grid(row=5, column=0, columnspan=3, sticky='w', padx=(16, 0))
    kind.trace_add('write', show)
    folder.trace_add('write', show)
    base.trace_add('write', show)
    show()

    def ok():
        if kind.get() == 'folder':
            selected_folder = folder.get().strip()
            d = detect(selected_folder, base.get())
            if d['kind'] == 'd2' and not d['base_dir']:
                browse_base()
                d = detect(selected_folder, base.get())
            if d['kind'] != 'd2' or not d['supported']:
                show()
                return
            if base.get():
                settings.put('profile_base_dir', base.get())
            settings.put('profile_game_dir', selected_folder)
            settings.put('vanilla_ui_theme', bool(vui.get()))
        settings.put('game_profile', kind.get())
        settings.put('profile_chosen', True)
        w.destroy()
        messagebox.showinfo(T('profile.title', 'Game profile'),
                            T('profile.restart', 'Restart the editor to load the selected game.'), parent=root)
    b = ttk.Frame(f)
    b.grid(row=6, column=0, columnspan=3, sticky='e', pady=(4, 0))
    ttk.Button(b, text=T('profile.ok', 'OK'), command=ok).pack(side='left', padx=2)
    ttk.Button(b, text=T('profile.cancel', 'Cancel'), command=w.destroy).pack(side='left', padx=2)
    w.protocol('WM_DELETE_WINDOW', w.destroy)
    w.bind('<Escape>', lambda _: w.destroy())

    def mapped(event):
        if event.widget is w:
            w.grab_set()
            w.focus_set()
    w.bind('<Map>', mapped)


def install_menu():
    try:
        import mxl_toolbar
        from mxl_lang import T
        mxl_toolbar.add_entry(lambda: T('profile.menu', 'Game profile...'), open_dialog)
    except Exception:
        pass
