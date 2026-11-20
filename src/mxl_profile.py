"""Game profiles: Median XL (the default, unchanged) or any other Diablo II game folder (vanilla LoD 1.14d first).

Median XL keeps every path of the editor as it was: install() returns at once and patches nothing.

Any other folder is driven only by its own files ("game folder -> profile"):
- detect(): medianxl-*.mpq / D2Sigma.dll = Median; otherwise the game version from Game.exe's (1.14x) or a D2 DLL's
  (1.13c and older) version resource, plus the mod archives found next to the base ones;
- the MPQ stack is opened in the game's own priority order (archive_order, from D2-Development-Kit, MIT);
- its tables (.bin), strings (.tbl), animdata.d2 and item icons are extracted into a data folder of the profile's own
  (<user dir>/profiles/<id>/data, id = kind + version + folder hash), which the collector then loads as its data/;
- the editor's art (panels, fonts, palettes) is read from the same stack; "Use vanilla UI theme" (default off) takes
  the theme files from the base archives (d2data / d2exp / patch_d2) only, falling back to the folder's own art.

Settings: 'game_profile' ('median' | 'folder'), 'profile_game_dir' (the other game's folder), 'vanilla_ui_theme'.
'game_dir' stays the Median folder: in a folder profile settings.get('game_dir') answers the profile's folder and
settings.put('game_dir', x) stores 'profile_game_dir'. MXL_GAME=vanilla (+ MXL_GAME_DIR) selects the folder profile
for tests without touching settings.json.

Supported in phase 1: 1.10-1.14d item format (d2s version 96). The collector's table reader works on 1.13c/1.14d bins
as they are (record sizes come from the file); only the set / unique id width differs from Sigma (12 bits, not 15)."""
import hashlib
import json
import os
import struct

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
EXTRACT_VERSION = 1

_state = None                 # the active profile (dict) once install() ran


# ---------------------------------------------------------------------------------------------------- detection
def archive_order(game_dir):
    """Archive search order (highest priority first) the way the game builds it. Adapted from D2-Development-Kit,
    d2bt/mpq.py default_archive_order (MIT): vanilla 1.13c/1.14d open d2data, d2sfx, d2speech, d2delta,
    d2kfixup @1000, patch_d2 @5000, d2exp @3000; Median (D2Sigma) d2exp @3000, patch_d2 @5000, then every
    medianxl-*.mpq @6000; then d2char, d2music @1000, LoD d2xmusic, d2xtalk, d2xvideo @3000, d2video @1000. Among
    equal priorities the archive opened last is searched first. Names match case-insensitively; d2gl.mpq (a
    renderer's) is not game data. Other *.mpq files of a mod folder come first (@6000, the way mod loaders add
    theirs)."""
    try:
        files = os.listdir(game_dir)
    except OSError:
        return []
    low = {f.lower(): f for f in files}
    known = {'d2data', 'd2sfx', 'd2speech', 'd2delta', 'd2kfixup', 'd2exp', 'patch_d2', 'd2char', 'd2music',
             'd2xmusic', 'd2xtalk', 'd2xvideo', 'd2video', 'd2gl'}
    median = sorted((f for f in files if f.lower().startswith('medianxl-') and f.lower().endswith('.mpq')),
                    key=str.upper)
    base = ['d2data', 'd2sfx', 'd2speech', 'd2delta', 'd2kfixup']
    if median:
        seq = [(n, 1000) for n in base] + [('d2exp', 3000), ('patch_d2', 5000)]
        seq += [(f[:-4], 6000) for f in median]
    else:
        seq = [(n, 1000) for n in base] + [('patch_d2', 5000), ('d2exp', 3000)]
        seq += [(f[:-4], 6000) for f in sorted(files, key=str.upper)
                if f.lower().endswith('.mpq') and f.lower()[:-4] not in known]
    seq += [('d2char', 1000), ('d2music', 1000)]
    if 'd2exp.mpq' in low:
        seq += [('d2xmusic', 3000), ('d2xtalk', 3000), ('d2xvideo', 3000)]
    seq.append(('d2video', 1000))
    opened = [(prio, i, low[(n + '.mpq').lower()]) for i, (n, prio) in enumerate(seq) if (n + '.mpq').lower() in low]
    opened.sort(key=lambda t: (-t[0], -t[1]))
    return [os.path.join(game_dir, f) for _, _, f in opened]


def base_archives(game_dir):
    """The base game's archives that hold UI / table data: patch_d2, d2exp, d2data (priority order)."""
    return [p for p in archive_order(game_dir)
            if os.path.basename(p).lower() in ('patch_d2.mpq', 'd2exp.mpq', 'd2data.mpq')]


def _pe_version(path):
    """FileVersion (a, b, c, d) of a PE file's VS_FIXEDFILEINFO, or None."""
    try:
        with open(path, 'rb') as f:
            b = f.read()
    except OSError:
        return None
    i = b.rfind(b'\xbd\x04\xef\xfe')
    if i < 0:
        return None
    ms, ls = struct.unpack_from('<II', b, i + 8)
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


VERSIONS = {(1, 14, 3): '1.14d', (1, 14, 2): '1.14c', (1, 14, 1): '1.14b', (1, 14, 0): '1.14a',
            (1, 0, 13): '1.13', (1, 0, 12): '1.12', (1, 0, 11): '1.11', (1, 0, 10): '1.10', (1, 0, 9): '1.09'}


def detect(game_dir):
    """{'kind': 'median'|'d2'|None, 'version': '1.14d'|..., 'mods': [mod archive names], 'supported': bool}."""
    if not game_dir or not os.path.isdir(game_dir):
        return {'kind': None, 'version': None, 'mods': [], 'supported': False}
    files = {f.lower(): f for f in os.listdir(game_dir)}
    if any(f.startswith('medianxl-') and f.endswith('.mpq') for f in files) or 'd2sigma.dll' in files:
        return {'kind': 'median', 'version': None, 'mods': [], 'supported': True}
    ver = None
    for name in ('game.exe', 'd2game.dll', 'd2client.dll', 'storm.dll'):
        v = _pe_version(os.path.join(game_dir, files[name])) if name in files else None
        if v:
            ver = VERSIONS.get(v[:3]) or VERSIONS.get(v[:2] + (v[2],)) or '.'.join(map(str, v))
            break
    if 'd2data.mpq' not in files:
        return {'kind': None, 'version': ver, 'mods': [], 'supported': False}
    mods = [os.path.basename(p) for p in archive_order(game_dir)
            if os.path.basename(p).lower()[:-4] not in ('d2data', 'd2sfx', 'd2speech', 'd2delta', 'd2kfixup',
                                                        'd2exp', 'patch_d2', 'd2char', 'd2music', 'd2xmusic', 'd2xtalk',
                                                        'd2xvideo', 'd2video')]
    # 1.10-1.14d share the item format the editor reads (d2s 96); 1.09 and older (d2s 0x5C) are phase 2
    sup = ver is not None and (ver.startswith('1.14') or ver in ('1.13', '1.12', '1.11', '1.10'))
    return {'kind': 'd2', 'version': ver, 'mods': mods, 'supported': sup}


def profile_id(game_dir, info):
    h = hashlib.sha1(os.path.normcase(os.path.abspath(game_dir)).encode('utf-8', 'replace')).hexdigest()[:8]
    return f"{info['kind']}-{info['version'] or 'unknown'}-{h}"


# ---------------------------------------------------------------------------------------------------- selection
def _raw_settings():
    import settings
    try:
        return settings._read(settings.PATH) or {}
    except Exception:
        return {}


def choose():
    """The profile asked for: env MXL_GAME (median / vanilla / folder), else settings 'game_profile'.
    Returns (kind, game_dir) with kind 'median' or 'folder'."""
    env = (os.environ.get('MXL_GAME') or '').strip().lower()
    s = _raw_settings()
    if env in ('median', 'mxl'):
        return 'median', None
    if env in ('vanilla', 'folder', 'd2'):
        return 'folder', os.environ.get('MXL_GAME_DIR') or s.get('profile_game_dir') or DEFAULT_VANILLA
    if s.get('game_profile') == 'folder':
        return 'folder', s.get('profile_game_dir') or DEFAULT_VANILLA
    return 'median', None


def active():
    """The active folder profile (dict) or None in Median mode."""
    return _state


def is_median():
    return _state is None


def vanilla_ui_theme():
    return bool(_raw_settings().get('vanilla_ui_theme', False))


# ---------------------------------------------------------------------------------------------------- extraction
def _fingerprint(game_dir):
    fp = {}
    for p in archive_order(game_dir):
        try:
            st = os.stat(p)
            fp[os.path.basename(p)] = [st.st_size, int(st.st_mtime)]
        except OSError:
            pass
    return {'extract_version': EXTRACT_VERSION, 'archives': fp}


def _open(paths):
    import mpq
    out = []
    for p in paths:
        try:
            out.append(mpq.MPQ(p))
        except Exception:
            pass
    return out


def _read(archives, name):
    for m in archives:
        try:
            if m.find(name) is not None:
                data = m.read(name)
                if data:
                    return data
        except Exception:
            continue
    return None


def data_ok(game_dir, out):
    try:
        with open(os.path.join(out, 'install.json'), encoding='utf-8') as f:
            man = json.load(f)
    except (OSError, ValueError):
        return False
    return man.get('fingerprint') == _fingerprint(game_dir) and os.path.exists(os.path.join(out, 'itemstatcost.bin'))


def extract(game_dir, out, progress=None, icons=True):
    """Tables, strings, animdata.d2 and item icons of the folder's MPQ stack -> out/ (written to out.new, then
    swapped in: an interrupted extraction never leaves a half folder)."""
    import shutil
    tmp = out + '.new'
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    stack = _open([p for p in archive_order(game_dir) if not os.path.basename(p).lower().startswith(
        ('d2music', 'd2xmusic', 'd2video', 'd2xvideo', 'd2speech', 'd2xtalk', 'd2sfx'))])
    names = set(EXCEL)
    for m in stack:                                     # a mod's own tables, when its archive lists them
        try:
            lf = m.read('(listfile)')
        except Exception:
            lf = None
        for line in (lf or b'').decode('latin1').split():
            low = line.lower().replace('/', '\\')
            if low.startswith('data\\global\\excel\\') and low.endswith('.bin'):
                names.add(low.rsplit('\\', 1)[1][:-4])
    files = {}
    for k, n in enumerate(sorted(names)):
        d = _read(stack, f'data\\global\\excel\\{n}.bin')
        if d:
            files[n + '.bin'] = d
        if progress:
            progress('tables', k + 1, len(names))
    for n in STRINGS:
        d = _read(stack, f'data\\local\\lng\\eng\\{n}.tbl')
        if d:
            files[n + '.tbl'] = d
    d = _read(stack, 'data\\global\\animdata.d2')
    if d:
        files['animdata.d2'] = d
    if 'itemstatcost.bin' not in files:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f'no game tables in {game_dir}')
    for n, d in files.items():
        with open(os.path.join(tmp, n), 'wb') as f:
            f.write(d)
    if icons:
        import mxl_data
        import mxl_gfx
        items = os.path.join(tmp, 'items')
        os.makedirs(items, exist_ok=True)
        mxl_gfx.extract_icons(game_dir, mxl_data.Data(tmp), items, progress=progress)
        try:
            mxl_gfx.extract_ui(game_dir, items)
        except Exception:
            pass
    with open(os.path.join(tmp, 'install.json'), 'w', encoding='utf-8') as f:
        json.dump({'game_dir': game_dir, 'fingerprint': _fingerprint(game_dir),
                   'files': sorted(files)}, f, indent=1)
    old = out + '.old'
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(out):
        os.replace(out, old)
    os.replace(tmp, out)
    shutil.rmtree(old, ignore_errors=True)
    return out


# ---------------------------------------------------------------------------------------------------- install
def install():
    """Before mxl_gui is imported (it copies paths.DATA_DIR at import). Median: nothing. Never raises for Median."""
    global _state
    kind, game_dir = choose()
    if kind == 'median':
        return None
    import paths
    info = detect(game_dir)
    if info['kind'] == 'median':                      # a Median folder chosen as "other folder": today's path
        return None
    pid = profile_id(game_dir, info)
    root = os.path.join(paths.USER_DIR, 'profiles', pid)
    data_dir = os.path.join(root, 'data')
    _state = dict(info, game_dir=game_dir, id=pid, root=root, data_dir=data_dir)
    if info['kind'] is None or not info['supported']:
        _log(f'game profile: {game_dir} is not a supported game folder ({info})')
    paths.DATA_DIR = data_dir
    paths.ICONS_DIR = os.path.join(data_dir, 'items')
    _patch_settings(game_dir)
    _patch_format()
    _patch_gfx()
    _patch_install()
    _patch_art()
    if not data_ok(game_dir, data_dir):
        _log(f'game profile {pid}: extracting tables and icons from {game_dir}')
        extract(game_dir, data_dir)
    _log(f'game profile {pid}: data {data_dir}')
    return _state


def _log(msg):
    try:
        import mxl_log
        mxl_log.log.info(msg)
    except Exception:
        pass


def _patch_settings(game_dir):
    """'game_dir' reads as the profile's folder; writing it stores 'profile_game_dir' (Median's stays)."""
    import settings
    o_load, o_put = settings.load, settings.put

    def load():
        s = dict(o_load())
        s['game_dir'] = _state['game_dir'] if _state else game_dir
        return s

    def put(key, value):
        if key == 'game_dir':
            key = 'profile_game_dir'
            if _state is not None:
                _state['game_dir'] = value
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


def _patch_gfx():
    """The collector's icon reader opens medianxl-*.mpq + lower-case base names: the folder's stack instead."""
    import mpq
    import mxl_gfx

    def open_archives(game_dir):
        return _open([p for p in archive_order(game_dir)
                      if not os.path.basename(p).lower().startswith(('d2music', 'd2xmusic', 'd2video', 'd2xvideo',
                                                                     'd2speech', 'd2xtalk', 'd2sfx'))])
    mxl_gfx.open_archives = open_archives
    _ = mpq


def _patch_install():
    """The collector's Median install checks (medianxl-version.mpq, its manifest) do not apply: the profile's
    data folder is checked / extracted by install(); a folder change re-extracts."""
    import mxl_gui_install as gi
    o_is = gi.is_game_dir

    def is_game_dir(d, *a, **k):
        info = detect(d)
        return info['kind'] == 'd2' or bool(o_is(d, *a, **k))
    gi.is_game_dir = is_game_dir
    GI = gi.GameInstall

    def check_data(self, startup=False, *a, **k):
        if not data_ok(self.game_dir, self.data_dir):
            extract(self.game_dir, self.data_dir)
            if not startup and self.on_rebuilt:
                self.on_rebuilt()
        return True
    GI.check_data = check_data

    def show_game(self, *a, **k):                      # top bar: "Diablo II 1.14d", not "Median XL ?"
        if getattr(self, 'label', None) is not None and _state:
            mods = [m for m in _state.get('mods', [])]
            self.label.configure(text=f"Diablo II {_state.get('version') or '?'}"
                                 + (f" + {', '.join(mods)}" if mods else ''))
    GI.show_game = show_game


def _patch_art():
    """Art (panels, fonts, palettes) from the folder's MPQ stack, its cache in the profile's folder; with
    'Use vanilla UI theme' the base archives come first for every UI file."""
    try:
        import mxl_d2look_art as A
    except Exception:
        return
    o_init = A.Art.__init__

    def __init__(self, game_dir, theme, cache_root):
        o_init(self, game_dir, theme, os.path.join(_state['root'], 'ui_art') if _state else cache_root)
    A.Art.__init__ = __init__

    def mpqs(self):
        if self._mpqs is None:
            order = archive_order(self.game_dir)
            if vanilla_ui_theme():
                base = base_archives(self.game_dir)
                order = base + [p for p in order if p not in base]
            self._mpqs = A._Archives(order)
        return self._mpqs
    A.Art.mpqs = mpqs

    def base_mpqs(self):
        if self._base_mpqs is None:
            self._base_mpqs = [m for m in map(A._archive, base_archives(self.game_dir)) if m is not None]
        return self._base_mpqs
    A.Art.base_mpqs = base_mpqs


# ---------------------------------------------------------------------------------------------------- menu
def open_dialog(app):
    """More menu -> "Game profile...": Median XL or another game folder, + "Use vanilla UI theme". Restart needed."""
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import settings
    from mxl_lang import T
    s = _raw_settings()
    root = getattr(app, 'root', None) or tk._default_root
    w = tk.Toplevel(root)
    w.title(T('profile.title', 'Game profile'))
    w.transient(root)
    kind = tk.StringVar(value='folder' if s.get('game_profile') == 'folder' else 'median')
    folder = tk.StringVar(value=s.get('profile_game_dir') or DEFAULT_VANILLA)
    vui = tk.BooleanVar(value=bool(s.get('vanilla_ui_theme', False)))
    f = ttk.Frame(w, padding=6)
    f.pack(fill='both', expand=True)
    ttk.Radiobutton(f, text=T('profile.median', 'Median XL'), value='median', variable=kind).grid(
        row=0, column=0, columnspan=3, sticky='w')
    ttk.Radiobutton(f, text=T('profile.folder', 'Other game folder (Diablo II LoD 1.14d, ...)'), value='folder',
                    variable=kind).grid(row=1, column=0, columnspan=3, sticky='w')
    ttk.Entry(f, textvariable=folder, width=48).grid(row=2, column=0, columnspan=2, sticky='we', padx=(16, 2))

    def browse():
        d = filedialog.askdirectory(parent=w, initialdir=folder.get() or None)
        if d:
            folder.set(d)
    ttk.Button(f, text=T('profile.browse', 'Browse...'), command=browse).grid(row=2, column=2, sticky='e')
    info = ttk.Label(f, text='')
    info.grid(row=3, column=0, columnspan=3, sticky='w', padx=(16, 0))
    ttk.Checkbutton(f, text=T('profile.vanilla_ui', 'Use vanilla UI theme'), variable=vui).grid(
        row=4, column=0, columnspan=3, sticky='w', padx=(16, 0))

    def show(*_):
        d = detect(folder.get())
        info.configure(text=(T('profile.detected', 'Detected: {k} {v}', k=d['kind'] or '?', v=d['version'] or '')
                             + ('' if d['supported'] else ' - ' + T('profile.unsupported', 'not supported yet'))))
    folder.trace_add('write', show)
    show()

    def ok():
        settings.put('game_profile', kind.get())
        if kind.get() == 'folder':
            settings.put('profile_game_dir', folder.get())
        settings.put('vanilla_ui_theme', bool(vui.get()))
        w.destroy()
        messagebox.showinfo(T('profile.title', 'Game profile'),
                            T('profile.restart', 'Restart the editor to load the selected game.'), parent=root)
    b = ttk.Frame(f)
    b.grid(row=5, column=0, columnspan=3, sticky='e', pady=(4, 0))
    ttk.Button(b, text=T('profile.ok', 'OK'), command=ok).pack(side='left', padx=2)
    ttk.Button(b, text=T('profile.cancel', 'Cancel'), command=w.destroy).pack(side='left', padx=2)


def install_menu():
    try:
        import mxl_toolbar
        from mxl_lang import T
        mxl_toolbar.add_entry(lambda: T('profile.menu', 'Game profile...'), open_dialog)
    except Exception:
        pass
