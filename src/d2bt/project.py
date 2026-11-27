"""Mod projects: every edit saved from any tab, collected per project, plus the Build & Play chain. No Tk in here.

    <D2BT_HOME or ~/D2DevKit>/projects/<name>/
        project.json   {"format": 1, "name", "install" (target game folder), "version" (layout: auto / mxl / 113c...),
                        "packing" ('' = per install: median for Median XL, patch_d2 for vanilla; or loose / txt /
                        patch_d2 / median / font), "txt_dir" (the txt folder edits came from), "strings_dir",
                        "items": {<key>: item}, "deployed": {<install-id>: [rel paths the last build wrote]}}
        files/<archive path>          the current content of every recorded file ('/'-separated)
        originals/<archive path>      its content before the project's first edit (absent = a new file)
        files/binaries/<File.dll>/    snapshot of the codebase patch sets (bin_codebase) after the last save
        originals/binaries/<File.dll>/  the patch sets before the first save in this project
        build/                        staging of the last Build (txt, bin, files, stage)

Item: {"key", "kind" (txt / tbl / sprite / cof / animdata / map / file / binary), "arc" (archive path, '\\'),
       "path" (where the tab saved it), "game" (install root when saved into one), "source" (tab), "first", "last",
       "has_original", "txt_dir"}; a binary item has "file", "install" (codebase install) instead of arc.

Hooks (one or two lines in each tab's save path): `before(kind, path, game, arc)` before the write returns the bytes
the project should keep as the original (only on the first save of that file), `record(...)` after it.
Binaries are recorded through bin_codebase.SAVE_HOOKS (every patch-set save goes there).

Build & Play: `build(project, game, ...)` compiles the txt folder (project txts overlaid) and stages the changed
tables' bins + the code pools they feed + every other recorded file in archive layout, packs and deploys them with
build_tab.deploy_plan / deploy_apply (originals kept by d2bt.gamefiles), then `launch_spec` gives argv / env / cwd.
Launch: Direct Wine or Lutris (`lutris lutris:rungame/<slug>`, else xdg-open); `lutris_game` matches the install to a
Lutris game (prefix + exe folder; read-only yml / pga.db; D2BT_LUTRIS_DIR / D2BT_STEAM_DIRS override the folders) and
gives the defaults: runner wine binary, args, env, prefix. `launch_warnings` says what Lutris / a non-runner wine miss.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time

from . import gamefiles as GF

KINDS = {'.txt': 'txt', '.tbl': 'tbl', '.dc6': 'sprite', '.dcc': 'sprite', '.cof': 'cof', '.d2': 'animdata',
         '.ds1': 'map', '.dt1': 'tiles'}
SAVE_SUBSCRIBERS = []          # fn(project) after every change (the GUI refreshes its panel)
_ACTIVE = {'name': None, 'obj': None}


def home():
    return os.environ.get('D2BT_HOME') or os.path.join(os.path.expanduser('~'), 'D2DevKit')


def projects_root():
    return os.path.join(home(), 'projects')


def safe_name(name):
    n = re.sub(r'[^A-Za-z0-9._ -]+', '_', (name or '').strip()).strip(' .')
    return n or 'default'


def list_projects():
    try:
        return sorted(d for d in os.listdir(projects_root())
                      if os.path.isfile(os.path.join(projects_root(), d, 'project.json')))
    except OSError:
        return []


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _read_json(p):
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_json(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
        fh.write('\n')
    os.replace(p + '.tmp', p)


def _put(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.tmp', 'wb') as fh:
        fh.write(data)
    os.replace(p + '.tmp', p)


def _get(p):
    try:
        with open(p, 'rb') as fh:
            return fh.read()
    except OSError:
        return None


def norm_arc(arc):
    return '\\'.join(x for x in arc.replace('/', '\\').split('\\') if x not in ('', '.', '..'))


def kind_of(arc):
    return KINDS.get(os.path.splitext(arc)[1].lower(), 'file')


# ================================================================================================ project
class Project:
    def __init__(self, name):
        self.name = safe_name(name)
        self.dir = os.path.join(projects_root(), self.name)
        self.path = os.path.join(self.dir, 'project.json')
        self.doc = _read_json(self.path) or {'format': 1, 'name': self.name, 'created': _now(), 'install': '',
                                             'version': 'auto', 'packing': '', 'txt_dir': '', 'strings_dir': '',
                                             'items': {}, 'deployed': {}}
        self.doc.setdefault('items', {})
        self.doc.setdefault('deployed', {})

    def save(self):
        _write_json(self.path, self.doc)

    @property
    def items(self):
        return self.doc['items']

    def get(self, key, default=None):
        return self.doc.get(key, default)

    def set(self, **kw):
        self.doc.update(kw)
        self.save()

    def fpath(self, arc, which='files'):
        return os.path.join(self.dir, which, *norm_arc(arc).split('\\'))

    def current(self, key):
        it = self.items[key]
        return _get(self.fpath(it['arc'])) if it['kind'] != 'binary' else None

    def original(self, key):
        it = self.items[key]
        return _get(self.fpath(it['arc'], 'originals')) if it['kind'] != 'binary' else None

    def set_original(self, key, data):
        """Fill in an original found later (from the install's archives); never replaces one already kept."""
        it = self.items[key]
        p = self.fpath(it['arc'], 'originals')
        if data is None or os.path.exists(p):
            return
        _put(p, data)
        it['has_original'] = True
        it['orig_from'] = 'install archives'
        if _get(self.fpath(it['arc'])) == data:
            self.drop(key)
            return
        self.save()

    # ---- files
    def has(self, arc):
        return norm_arc(arc).lower() in self.items

    def record(self, kind, arc, data, before=None, path='', game=None, source='', **extra):
        """Keep `data` as the project's version of `arc`; on the first save of it `before` is kept as the original.
        Saving the original bytes again drops the item. -> item or None"""
        arc = norm_arc(arc)
        key = arc.lower()
        it = self.items.get(key)
        if it is None:
            if before is not None and before == data:
                return None                     # saved without a change: nothing to record
            it = {'key': key, 'kind': kind or kind_of(arc), 'arc': arc, 'first': _now(),
                  'has_original': before is not None}
            if before is not None:
                _put(self.fpath(arc, 'originals'), before)
            self.items[key] = it
        elif it['has_original'] and _get(self.fpath(arc, 'originals')) == data:
            self.drop(key)                       # edited back to the original
            return None
        _put(self.fpath(arc), data)
        it.update(last=_now(), path=os.path.abspath(path) if path else '', game=game or '', source=source,
                  sha1=hashlib.sha1(data).hexdigest(), size=len(data), **extra)
        if kind == 'txt' and extra.get('txt_dir') and not self.doc.get('txt_dir'):
            self.doc['txt_dir'] = extra['txt_dir']
        self.save()
        _notify(self)
        return it

    def drop(self, key):
        it = self.items.pop(key, None)
        if it is None:
            return
        if it['kind'] == 'binary':
            shutil.rmtree(os.path.join(self.dir, 'files', 'binaries', it['file']), ignore_errors=True)
            shutil.rmtree(os.path.join(self.dir, 'originals', 'binaries', it['file']), ignore_errors=True)
        else:
            for w in ('files', 'originals'):
                try:
                    os.remove(self.fpath(it['arc'], w))
                except OSError:
                    pass
        self.save()
        _notify(self)

    # ---- binaries (codebase patch sets)
    def binary_dir(self, file, which='files'):
        return os.path.join(self.dir, which, 'binaries', file)

    def record_binary(self, cb, file, phase):
        key = 'bin:' + file.lower()
        src = cb.bdir(file, 'patches')
        if phase == 'before':
            if key not in self.items:
                dst = self.binary_dir(file, 'originals')
                shutil.rmtree(dst, ignore_errors=True)
                os.makedirs(dst, exist_ok=True)
                for p in cb.patch_files(file):
                    shutil.copyfile(p, os.path.join(dst, os.path.basename(p)))
            return
        dst = self.binary_dir(file)
        shutil.rmtree(dst, ignore_errors=True)
        os.makedirs(dst, exist_ok=True)
        n = 0
        for p in cb.patch_files(file):
            shutil.copyfile(p, os.path.join(dst, os.path.basename(p)))
            n += len((_read_json(p) or {}).get('patches') or ())
        orig = self.binary_dir(file, 'originals')
        if key not in self.items and _same_dir(orig, dst):
            shutil.rmtree(orig, ignore_errors=True)
            shutil.rmtree(dst, ignore_errors=True)
            return
        it = self.items.setdefault(key, {'key': key, 'kind': 'binary', 'arc': file, 'file': file, 'first': _now(),
                                         'has_original': True})
        it.update(last=_now(), install=cb.install_path, codebase=cb.dir, entries=n, source='Binaries')
        self.save()
        _notify(self)

    def binary_entries(self, key, which='files'):
        it = self.items[key]
        d = self.binary_dir(it['file'], which)
        out = []
        try:
            names = sorted(os.listdir(d))
        except OSError:
            names = []
        for f in names:
            doc = _read_json(os.path.join(d, f)) or {}
            for e in doc.get('patches') or ():
                out.append(dict(e, _set=f.split('.d2patch')[0], _set_off=doc.get('enabled') is False))
        return out

    # ---- revert
    def revert(self, key):
        """Undo one change: the file where the tab saved it gets its original back (through d2bt.gamefiles inside
        a game folder; only when it still holds the project's version), a binary's codebase patch sets go back to
        the snapshot from before the first save. The item leaves the project. -> message"""
        it = self.items[key]
        if it['kind'] == 'binary':
            pdir = os.path.join(it['codebase'], 'binaries', it['file'], 'patches')
            shutil.rmtree(pdir, ignore_errors=True)
            os.makedirs(pdir, exist_ok=True)
            od = self.binary_dir(it['file'], 'originals')
            for f in os.listdir(od) if os.path.isdir(od) else ():
                shutil.copyfile(os.path.join(od, f), os.path.join(pdir, f))
            self.drop(key)
            return f'{it["file"]}: patch sets restored in the codebase (reopen the binary in the Binaries tab)'
        cur, orig = self.current(key), self.original(key)
        path, game = it.get('path'), it.get('game')
        msg = f'{it["arc"]}: removed from the project'
        if path and _get(path) == cur:
            if game:
                rel = GF.rel_in(game, path)
                if orig is None:
                    GF.remove_game_file(game, rel, note='project revert')
                else:
                    GF.write_game_file(game, rel, data=orig, note='project revert')
                msg = f'{it["arc"]}: original put back in the game folder ({rel})'
            elif orig is None:
                os.remove(path)
                msg = f'{it["arc"]}: removed {path} (new file)'
            else:
                _put(path, orig)
                msg = f'{it["arc"]}: original written back to {path}'
        elif path:
            msg += f' ({path} changed since; left as it is)'
        self.drop(key)
        return msg


def _same_dir(a, b):
    def snap(d):
        try:
            return {f: _get(os.path.join(d, f)) for f in os.listdir(d)}
        except OSError:
            return {}
    return snap(a) == snap(b)


def _notify(p):
    for fn in list(SAVE_SUBSCRIBERS):
        try:
            fn(p)
        except Exception:       # noqa: BLE001 - a GUI refresh never breaks a save
            pass


# ================================================================================================ active project
def activate(name):
    _ACTIVE['name'] = safe_name(name) if name else None
    _ACTIVE['obj'] = None
    return active()


def active():
    """The active Project (created on first use), or None when projects are switched off."""
    if not _ACTIVE['name']:
        return None
    if _ACTIVE['obj'] is None or _ACTIVE['obj'].name != _ACTIVE['name']:
        _ACTIVE['obj'] = Project(_ACTIVE['name'])
    return _ACTIVE['obj']


def arc_for(kind, path, game=None, arc=None):
    if arc:
        return norm_arc(arc)
    if game:
        try:
            return norm_arc(GF.rel_in(game, path))
        except GF.GameFileError:
            pass
    mod = os.path.join(home(), 'work', 'mod_files')
    ap = os.path.abspath(path)
    if ap.startswith(os.path.abspath(mod) + os.sep):
        return norm_arc(os.path.relpath(ap, mod))
    base = os.path.basename(path)
    if kind == 'txt':
        return 'data\\global\\excel\\' + base
    if kind == 'tbl':
        return 'data\\local\\lng\\eng\\' + base
    return None


def before(kind, path, game=None, arc=None):
    """Hook BEFORE a tab writes `path`: the bytes to keep as the original (first save in the project only)."""
    p = active()
    try:
        a = arc_for(kind, path, game, arc)
        if p is None or not a or p.has(a):
            return None
        if game:
            hit = GF.stored_original(game, GF.rel_in(game, path))
            if hit:
                return _get(hit[0])
        return _get(path)
    except Exception:       # noqa: BLE001 - recording never breaks a save
        return None


def record(kind, path, data, orig=None, game=None, arc=None, source='', **extra):
    """Hook AFTER a tab wrote `data` to `path`. -> item or None"""
    p = active()
    if p is None:
        return None
    try:
        a = arc_for(kind, path, game, arc)
        if not a:
            return None
        if kind == 'txt':
            extra.setdefault('txt_dir', os.path.dirname(os.path.abspath(path)))
        return p.record(kind, a, data, orig, path=path, game=game, source=source, **extra)
    except Exception:       # noqa: BLE001
        import traceback
        traceback.print_exc()
        return None


def _codebase_hook(cb, file, phase):
    p = active()
    if p is not None:
        try:
            p.record_binary(cb, file, phase)
        except Exception:       # noqa: BLE001
            import traceback
            traceback.print_exc()


def install_hooks():
    from .gui import bin_codebase as CB
    if _codebase_hook not in CB.SAVE_HOOKS:
        CB.SAVE_HOOKS.append(_codebase_hook)


# ================================================================================================ diffs
def _rows(data):
    return [ln.split(b'\t') for ln in data.replace(b'\r\n', b'\n').split(b'\n') if ln != b''] if data else []


def txt_diff(old, new, limit=400):
    """Cell diff of two tab-separated tables, rows matched by their first column (then by position).
    -> [(row label, column, old, new)] with column '' for an added / removed row."""
    a, b = _rows(old), _rows(new)
    hdr = [h.decode('latin-1') for h in (b[0] if b else a[0] if a else [])]
    out = []
    if a and b and a[0] != b[0]:
        out.append(('header', '', '\t'.join(h.decode('latin-1') for h in a[0])[:80],
                    '\t'.join(hdr)[:80]))

    def keyed(rows):
        seen, res = {}, []
        for r in rows[1:]:
            k = r[0] if r else b''
            n = seen[k] = seen.get(k, 0) + 1
            res.append(((k, n), r))
        return res
    ka, kb = keyed(a), keyed(b)
    ma = dict(ka)
    mb = dict(kb)
    for k, r in kb:
        lab = k[0].decode('latin-1') + (f' #{k[1]}' if k[1] > 1 else '')
        o = ma.get(k)
        if o is None:
            out.append((lab, '', '', '(row added)'))
            continue
        for j in range(max(len(o), len(r))):
            x = o[j] if j < len(o) else b''
            y = r[j] if j < len(r) else b''
            if x != y:
                col = hdr[j] if j < len(hdr) else f'#{j + 1}'
                out.append((lab, col, x.decode('latin-1'), y.decode('latin-1')))
        if len(out) >= limit:
            return out
    for k, r in ka:
        if k not in mb:
            out.append((k[0].decode('latin-1'), '', '(row removed)', ''))
    return out[:limit]


def tbl_diff(old, new, limit=400):
    """-> [(index, key, old text, new text)] of entries that differ (index = position in the table)."""
    from .binfmt.tbl import Tbl, pretty
    a = Tbl.parse(old).entries if old else []
    b = Tbl.parse(new).entries
    out = []
    for i in range(max(len(a), len(b))):
        x = tuple(a[i]) if i < len(a) else None
        y = tuple(b[i]) if i < len(b) else None
        if x != y:
            k = (y or x)[0]
            out.append((i, pretty(k), pretty(x[1]) if x else '(new)', pretty(y[1]) if y else '(removed)'))
            if len(out) >= limit:
                break
    return out


def byte_summary(old, new):
    """-> text: sizes, differing bytes and ranges of two byte strings."""
    if old is None:
        return f'new file, {len(new):,} bytes'
    n = min(len(old), len(new))
    diff, ranges, start = 0, [], None
    for i in range(n):
        if old[i] != new[i]:
            diff += 1
            if start is None:
                start = i
        elif start is not None:
            ranges.append((start, i))
            start = None
    if start is not None:
        ranges.append((start, n))
    s = f'{len(old):,} -> {len(new):,} bytes; {diff:,} byte(s) differ in {len(ranges)} range(s)'
    if len(old) != len(new):
        s += f'; size {len(new) - len(old):+,}'
    if ranges:
        s += '\n' + '\n'.join(f'  0x{a:06X}..0x{b - 1:06X} ({b - a} bytes): {old[a:min(b, a + 8)].hex(" ")} -> '
                              f'{new[a:min(b, a + 8)].hex(" ")}' for a, b in ranges[:12])
        if len(ranges) > 12:
            s += f'\n  ... {len(ranges) - 12} more'
    return s


def binary_summary(p, key):
    """Patch entries now vs before, plus the byte diff of the last build when there is one."""
    it = p.items[key]
    now = p.binary_entries(key)
    was = p.binary_entries(key, 'originals')
    on = [e for e in now if e.get('enabled', True) and not e.get('_set_off')]
    lines = [f'{it["file"]}: {len(now)} patch entr{"y" if len(now) == 1 else "ies"} ({len(on)} enabled), '
             f'{len(was)} before this project']
    nb = 0
    for e in on[:40]:
        b = e.get('bytes') or e.get('new') or e.get('patch') or ''
        n = len(bytes.fromhex(b.replace(' ', ''))) if isinstance(b, str) and re.fullmatch(r'[0-9A-Fa-f ]*', b) \
            else 0
        nb += n
        what = e.get('note') or e.get('value_id') or e.get('asm') or e.get('kind') or ''
        lines.append(f'  [{e["_set"]}] {e.get("va") or e.get("rva") or e.get("offset") or ""}  '
                     f'{str(what)[:60]}' + (f'  ({n} bytes)' if n else ''))
    if nb:
        lines.insert(1, f'  {nb} byte(s) written by the enabled entries')
    built = it.get('built')
    if built and os.path.isfile(built.get('path', '')) and os.path.isfile(built.get('original', '')):
        lines.append('last build vs original: ' + byte_summary(_get(built['original']), _get(built['path'])))
    return '\n'.join(lines)


# ================================================================================================ build
def packing_for(project, kind):
    pk = project.get('packing') or ''
    if pk:
        return pk
    return 'median' if kind == 'Median XL' else 'patch_d2' if kind in ('LoD', 'Classic', 'MPQ mod') else 'loose'


def build(project, game, strings=None, log=print, split_cap=None, method=None):
    """prepare + apply without a confirm in between (scripts). -> apply()'s dict"""
    return apply(prepare(project, game, strings, log, split_cap, method), log)


def _strings_folder(project, inst, bdir, strings, log):
    """The tbl folder the compile resolves string keys with: the given / project strings folder, else the
    install's own eng tables (read from its archives), with the project's edited tbls on top."""
    sdir = os.path.join(bdir, 'strings')
    os.makedirs(sdir, exist_ok=True)
    base = strings or project.get('strings_dir') or ''
    if base and os.path.isdir(base):
        for f in os.listdir(base):
            if f.lower().endswith('.tbl'):
                shutil.copyfile(os.path.join(base, f), os.path.join(sdir, f))
    else:
        from .gui.install import Source
        src = Source(inst)
        try:
            src.open()
            for n in ('string', 'expansionstring', 'patchstring'):
                hit = src.find(f'data\\local\\lng\\eng\\{n}.tbl')
                if hit is not None:
                    _put(os.path.join(sdir, n + '.tbl'), src.read(hit))
        except Exception as e:      # noqa: BLE001
            log(f'strings: could not read the install\'s tables ({e})')
        finally:
            try:
                src.close()
            except Exception:       # noqa: BLE001
                pass
    for it in project.items.values():
        if it['kind'] == 'tbl':
            shutil.copyfile(project.fpath(it['arc']), os.path.join(sdir, it['arc'].split('\\')[-1]))
    n = len([f for f in os.listdir(sdir) if f.lower().endswith('.tbl')])
    log(f'strings: {n} table(s) for the compile' + (f' from {base}' if base else ' from the install'))
    return sdir if n else None


def prepare(project, game, strings=None, log=print, split_cap=None, method=None):
    """Compile + stage (no game writes) and predict the files a deploy would write. -> context dict with
    'targets' (rel paths in the game, for the one confirm), consumed by apply()."""
    from .gui import build_tab as BT
    from .gui.install import detect
    game = os.path.realpath(game)
    inst = detect(game)
    method = method or packing_for(project, inst.kind)
    bdir = os.path.join(project.dir, 'build')
    shutil.rmtree(bdir, ignore_errors=True)
    files = os.path.join(bdir, 'files')
    os.makedirs(files)
    steps = {}
    items = list(project.items.values())
    txts = [it for it in items if it['kind'] == 'txt']
    txt_stage = None
    # 1. compile
    if txts:
        txt_stage = os.path.join(bdir, 'txt')
        os.makedirs(txt_stage)
        base = project.get('txt_dir') or ''
        if base and os.path.isdir(base):
            for f in os.listdir(base):
                if f.lower().endswith('.txt'):
                    shutil.copyfile(os.path.join(base, f), os.path.join(txt_stage, f))
        for it in txts:
            shutil.copyfile(project.fpath(it['arc']), os.path.join(txt_stage, it['arc'].split('\\')[-1]))
        log(f'compile: {len(txts)} edited txt over {base or "(no txt folder)"}')
        if method == 'txt':
            steps['compile'] = 'skipped (-txt: the game reads the txt)'
        else:
            ver = project.get('version') or 'auto'
            if ver == 'auto' and inst.layout:
                ver = inst.layout
            binout = os.path.join(bdir, 'bin')
            sdir = _strings_folder(project, inst, bdir, strings, log)
            ver, res = BT.compile_tables(txt_stage, binout, ver, sdir)
            want = {os.path.splitext(it['arc'].split('\\')[-1])[0].lower() for it in txts}
            ext_base, ext_of = BT._ext_maps()
            for t in list(want):
                want.update(ext_of.get(t, ()))
            bad = [r for r in res if r['status'] == 'error' and r['table'] in want]
            if bad:
                raise ValueError('compile failed: ' + '; '.join(f'{r["table"]}: {r["msg"]}' for r in bad[:4]))
            from .binfmt import txt2bin
            tp = txt2bin.Project(txt_stage, version=ver)
            pools = {pool for pool in txt2bin.POOL_KIND if want & set(tp._pool_tables(pool))}
            got = []
            for r in res:
                if r['out'] and (r['table'] in want or r['table'] in pools):
                    dst = os.path.join(files, 'data', 'global', 'excel', r['table'] + '.bin')
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copyfile(r['out'], dst)
                    got.append(r['table'])
            n_ok = sum(1 for r in res if r['status'] in ('OK', 'warning'))
            steps['compile'] = f'{n_ok}/{len(res)} tables compiled ({ver}); staged {", ".join(sorted(got))}'
            log('compile: ' + steps['compile'])
    else:
        steps['compile'] = 'nothing to compile'
    # 2. other files at their archive paths
    n = 0
    for it in items:
        if it['kind'] in ('txt', 'binary'):
            continue
        dst = os.path.join(files, *it['arc'].split('\\'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(project.fpath(it['arc']), dst)
        n += 1
    log(f'stage: {n} file(s) staged in {files}')
    iid = GF.install_id(game)
    prev = project.doc['deployed'].get(iid) or []
    targets = set(prev)
    from . import mpq_write
    staged = [n_ for _p, n_ in mpq_write.folder_entries(files)] if os.listdir(files) else []
    if method in ('loose', 'txt'):
        targets |= {GF.rel_in(game, BT._ci_path(game, a)) for a in staged}
        if method == 'txt' and txt_stage:
            targets |= {GF.rel_in(game, BT._ci_path(game, 'data\\global\\excel\\' + f))
                        for f in os.listdir(txt_stage)}
    elif staged and method == 'median':
        from . import mpq_median
        plan = mpq_median.make_plan(game, mpq_median.files_from_folder(files), split_cap=split_cap)
        targets |= {c.archive for c in plan.changes}
    elif staged:
        targets.add({'patch_d2': 'patch_d2.mpq', 'font': 'font.mpq'}.get(method, method))
    targets |= {it['file'] for it in items if it['kind'] == 'binary'}
    return {'project': project, 'game': game, 'inst': inst, 'method': method, 'bdir': bdir, 'files': files,
            'txt_stage': txt_stage, 'steps': steps, 'items': items, 'split_cap': split_cap,
            'targets': sorted(targets)}


def apply(ctx, log=print):
    """Put back what the previous build wrote, pack, deploy (d2bt.gamefiles keeps the originals), binaries.
    -> dict(method, pairs, backup, steps, kind)"""
    from .gui import build_tab as BT
    project, game, method, bdir, files = ctx['project'], ctx['game'], ctx['method'], ctx['bdir'], ctx['files']
    txt_stage, steps, items, split_cap, inst = ctx['txt_stage'], ctx['steps'], ctx['items'], ctx['split_cap'], \
        ctx['inst']
    # 3. put back what the previous build wrote, so reverted items leave the game too
    iid = GF.install_id(game)
    prev = project.doc['deployed'].get(iid) or []
    if prev:
        r = GF.restore(game, prev)
        log(f'previous build: {len(r["restored"])} restored, {len(r["removed"])} removed')
    # 4. pack + deploy
    pairs = []
    if method == 'txt':
        if txt_stage:
            pairs += BT.deploy_plan(game, 'txt', None, txt_folder=txt_stage)
        method_files = 'loose'
    else:
        method_files = method
    if os.listdir(files):
        pairs += BT.deploy_plan(game, method_files, files, staging=os.path.join(bdir, 'stage'), split_cap=split_cap)
    steps['pack'] = f'{BT.METHODS.get(method, method)}: {len(pairs)} target file(s)'
    log('pack: ' + steps['pack'])
    # 5. binaries: build from the codebase original + enabled patch sets
    for it in items:
        if it['kind'] != 'binary':
            continue
        try:
            out = build_binary(project, it, os.path.join(bdir, 'binaries'))
        except Exception as e:      # noqa: BLE001
            log(f'binary {it["file"]}: not built ({e}); build it in the Binaries tab')
            continue
        tgt = BT._ci_file(game, it['file'])
        if not tgt:
            log(f'binary {it["file"]}: not in {game}; skipped')
            continue
        pairs.append((out, tgt))
        log(f'binary {it["file"]}: built {os.path.basename(out)}')
    backup = None
    if pairs:
        backup, replaced, added = BT.deploy_apply(game, pairs, os.path.join(home(), 'backups'))
        steps['deploy'] = f'{len(replaced)} replaced, {len(added)} added (backup {backup})'
    else:
        steps['deploy'] = 'nothing to deploy'
    log('deploy: ' + steps['deploy'])
    project.doc['deployed'][iid] = sorted({GF.rel_in(game, d) for _s, d in pairs})
    project.doc['last_build'] = {'at': _now(), 'game': game, 'method': method, 'steps': steps}
    project.save()
    return {'method': method, 'pairs': pairs, 'backup': backup, 'steps': steps, 'kind': inst.kind}


def build_binary(project, it, out_dir):
    """Patched copy of the codebase's pristine original with every enabled patch set. -> built path"""
    from .gui import bin_codebase as CB
    from .gui import bin_patch as BP
    from .pe.symbols import Resolver
    cb = CB.Codebase(it['install'])
    file = it['file']
    if not cb.has_original(file):
        raise ValueError('no pristine original in the codebase')
    base = (cb.doc['binaries'].get(file) or {}).get('base_sha1') or CB.sha1_file(cb.original_path(file))
    ps = cb.load_patches(file, base)
    res = BP.build(cb.original_path(file), ps, out_dir, lambda img: Resolver(img), (), (), None, out_name=file)
    it['built'] = {'path': res['path'], 'sha1': res['sha1'], 'original': cb.original_path(file)}
    return res['path']


# ================================================================================================ launch
LAUNCH_DEFAULTS = {'exe': '', 'wine': '', 'prefix': '', 'workdir': '', 'windowed': False, 'direct': 'auto',
                   'txt': 'auto', 'args': '', 'env': '', 'launcher': '', 'lutris': ''}
# launcher: '' / 'wine' = Direct Wine (argv built here), 'lutris' = `lutris lutris:rungame/<lutris slug>` (Lutris runs
# its own runner / args / env / prefix). Unsaved installs get their defaults from the matching Lutris game (lutris_game).


# ------------------------------------------------------------------ Lutris (read-only: games/*.yml, runners/wine.yml)
def _yscalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    if ' #' in v:
        v = v.split(' #', 1)[0].rstrip()
    return {'{}': {}, '[]': [], 'true': True, 'false': False, '~': None, 'null': None}.get(v, v)


_YKEY = re.compile(r"""^('[^']*'|"[^"]*"|[^'"\s#][^:]*?)\s*:(?:\s+(.*))?$""")


def yaml_load(text):
    """PyYAML's safe_load when available, else a tolerant block-YAML subset (mappings, lists, folded plain /
    quoted scalars) that is enough for Lutris configs."""
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        pass
    except Exception:       # noqa: BLE001
        pass
    return _mini_yaml(text)


def _mini_yaml(text):
    lines = []          # [indent, text, key column or -1 when the line opens no scalar]
    for raw in text.splitlines():
        t = raw.rstrip()
        if not t.strip() or t.lstrip().startswith('#') or t.strip() in ('---', '...'):
            continue
        ind = len(t) - len(t.lstrip(' '))
        body = t.strip()
        if lines and lines[-1][2] >= 0 and ind > lines[-1][2]:
            lines[-1][1] += ' ' + body          # folded continuation of the previous scalar
            continue
        col, rest = ind, body
        while rest.startswith('- ') or rest == '-':
            r2 = rest[1:].lstrip()
            col += len(rest) - len(r2)
            rest = r2
        m = _YKEY.match(rest)
        opens = (bool(m and (m.group(2) or '').strip() not in ('', '|', '>', '|-', '>-')) or
                 (not m and rest != body and bool(rest)))
        lines.append([ind, body, col if opens else -1])
    pos = [0]

    def item_line(t):
        return t.startswith('- ') or t == '-'

    def parse(ind):
        if pos[0] < len(lines) and item_line(lines[pos[0]][1]):
            out = []
            while pos[0] < len(lines) and lines[pos[0]][0] == ind and item_line(lines[pos[0]][1]):
                t = lines[pos[0]][1]
                rest = t[1:].lstrip()
                if not rest:
                    pos[0] += 1
                    out.append(parse(lines[pos[0]][0]) if pos[0] < len(lines) and lines[pos[0]][0] > ind else None)
                elif _YKEY.match(rest) or item_line(rest):
                    lines[pos[0]] = [ind + len(t) - len(rest), rest, lines[pos[0]][2]]
                    out.append(parse(lines[pos[0]][0]))
                else:
                    pos[0] += 1
                    out.append(_yscalar(rest))
            return out
        out = {}
        while pos[0] < len(lines):
            li, t, _c = lines[pos[0]]
            if li < ind or (li == ind and item_line(t)):
                break
            pos[0] += 1
            m = _YKEY.match(t) if li == ind else None
            if not m:
                continue                         # tolerate what this subset does not understand
            k, v = _yscalar(m.group(1)), (m.group(2) or '').strip()
            if v in ('', '|', '>', '|-', '>-'):
                nxt = lines[pos[0]] if pos[0] < len(lines) else None
                out[k] = parse(nxt[0]) if nxt and (nxt[0] > ind or (nxt[0] == ind and item_line(nxt[1]))) else None
            else:
                out[k] = _yscalar(v)
        return out
    return parse(lines[0][0]) if lines else None


def lutris_root():
    return os.environ.get('D2BT_LUTRIS_DIR') or os.path.join(os.path.expanduser('~'), '.local', 'share', 'lutris')


def _lutris_yml(*parts):
    """Lutris >= 0.5.13 keeps configs in the data folder; older ones in ~/.config/lutris."""
    roots = [lutris_root()]
    if not os.environ.get('D2BT_LUTRIS_DIR'):
        roots.append(os.path.join(os.path.expanduser('~'), '.config', 'lutris'))
    for r in roots:
        p = os.path.join(r, *parts)
        if os.path.isfile(p):
            try:
                with open(p, encoding='utf-8', errors='replace') as f:
                    d = yaml_load(f.read())
                return d if isinstance(d, dict) else {}
            except OSError:
                pass
    return {}


def _lutris_slugs():
    """config file stem -> (slug, name) from pga.db (opened read-only); {} when unavailable."""
    p = os.path.join(lutris_root(), 'pga.db')
    if not os.path.isfile(p):
        return {}
    try:
        import sqlite3
        from urllib.parse import quote
        con = sqlite3.connect(f'file:{quote(p)}?mode=ro', uri=True)
        try:
            return {c: (s, n) for s, n, c in con.execute('select slug, name, configpath from games') if c}
        finally:
            con.close()
    except Exception:       # noqa: BLE001
        return {}


def _natkey(s):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)', s)]


def _steam_dirs():
    env = os.environ.get('D2BT_STEAM_DIRS')
    if env is not None:
        return [d for d in env.split(os.pathsep) if d]
    h = os.path.expanduser('~')
    return [os.path.join(h, '.local', 'share', 'Steam'), os.path.join(h, '.steam', 'steam')]


def lutris_wine(version):
    """Lutris wine-runner version name -> its wine binary ('' when not found). Wine builds live in
    runners/wine/<v>/bin, Proton builds (Steam common/, compatibilitytools.d/) in <v>/files/bin;
    'ge-proton' (umu) is the newest GE-Proton*."""
    cands = []
    rw = os.path.join(lutris_root(), 'runners', 'wine')
    sd = [os.path.join(s, sub) for s in _steam_dirs() for sub in ('compatibilitytools.d', 'steamapps/common')]
    v = (version or '').strip()
    if v.lower() in ('ge-proton', 'ge-proton-latest', 'umu-default', ''):
        pat = 'ge-proton' if v else ''
        for d in [rw] + sd:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            cands += [(n, os.path.join(d, n)) for n in names if n.lower().startswith(pat) or
                      (pat and n.lower().startswith('lutris-ge-proton'))]
        cands = [p for _n, p in sorted(cands, key=lambda c: _natkey(c[0].replace('lutris-', '')), reverse=True)]
    else:
        cands = [os.path.join(d, v) for d in [rw] + sd]
    for d in cands:
        for b in (('bin', 'wine'), ('files', 'bin', 'wine'), ('dist', 'bin', 'wine')):
            p = os.path.join(d, *b)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return ''


def _same_path(a, b):
    if not a or not b:
        return False
    a, b = os.path.realpath(a), os.path.realpath(b)
    return a == b or a.lower() == b.lower()


def lutris_game(game):
    """The Lutris game whose prefix and exe folder are this install -> {'slug', 'name', 'file', 'exe' (full path),
    'workdir', 'prefix', 'args', 'env' {..}, 'wine_version', 'wine' (binary or ''), 'prelaunch'}, or None.
    Only reads the yml files and pga.db."""
    if not game:
        return None
    gdir = os.path.join(lutris_root(), 'games')
    try:
        files = sorted(f for f in os.listdir(gdir) if f.endswith(('.yml', '.yaml')))
    except OSError:
        return None
    slugs = _lutris_slugs()
    pre = wine_prefix(game)
    sysenv = (_lutris_yml('system.yml').get('system') or {}).get('env') or {}
    runner = _lutris_yml('runners', 'wine.yml').get('wine') or {}
    for fn in files:
        try:
            with open(os.path.join(gdir, fn), encoding='utf-8', errors='replace') as f:
                doc = yaml_load(f.read())
        except OSError:
            continue
        if not isinstance(doc, dict):
            continue
        g = doc.get('game') or {}
        exe, prefix = str(g.get('exe') or ''), str(g.get('prefix') or '')
        if not exe or not prefix:
            continue
        if not os.path.isabs(exe):
            exe = os.path.join(prefix, exe)
        if not (_same_path(prefix, pre) and _same_path(os.path.dirname(exe), game)):
            continue
        stem = fn.rsplit('.', 1)[0]
        slug, name = slugs.get(stem) or (re.sub(r'-\d+$', '', stem), str(doc.get('name') or stem))
        system = doc.get('system') or {}
        env = {str(k): str(v) for k, v in dict(sysenv, **(system.get('env') or {})).items() if v is not None}
        wine = doc.get('wine') or {}
        ovr = dict(runner.get('overrides') or {}, **(wine.get('overrides') or {}))
        if ovr and 'WINEDLLOVERRIDES' not in env:
            env['WINEDLLOVERRIDES'] = ';'.join(f'{k}={"" if v in ("disabled", "") else v}' for k, v in ovr.items())
        ver = str(wine.get('version') or runner.get('version') or '')
        return {'slug': slug, 'name': name, 'file': os.path.join(gdir, fn), 'exe': exe,
                'workdir': str(g.get('working_dir') or os.path.dirname(exe)), 'prefix': prefix,
                'args': str(g.get('args') or ''), 'env': env, 'wine_version': ver or '(Lutris default)',
                'wine': lutris_wine(ver), 'prelaunch': system.get('prelaunch_command') or ''}
    return None


def lutris_defaults(game, lg=None):
    """Launch settings taken from the matching Lutris game ({} when there is none)."""
    lg = lg or lutris_game(game)
    if not lg:
        return {}
    return {'launcher': 'lutris', 'lutris': lg['slug'], 'exe': os.path.basename(lg['exe']), 'wine': lg['wine'],
            'prefix': lg['prefix'], 'workdir': '' if _same_path(lg['workdir'], game) else lg['workdir'],
            'args': lg['args'], 'env': '\n'.join(f'{k}={v}' for k, v in lg['env'].items())}


def lutris_argv(slug):
    cli = shutil.which('lutris')
    return [cli, f'lutris:rungame/{slug}'] if cli else ['xdg-open', f'lutris:rungame/{slug}']


def launch_flags(method, cfg):
    """-> (direct, txt) for a build packed with `method`."""
    direct = method in ('loose', 'txt') if cfg['direct'] == 'auto' else bool(cfg['direct'] in (True, 'on'))
    txt = method == 'txt' if cfg['txt'] == 'auto' else bool(cfg['txt'] in (True, 'on'))
    return direct, txt


def launch_warnings(game, method, cfg=None, windows=None, lg=None):
    """Plain-language warnings for the Launch page / log."""
    cfg = dict(LAUNCH_DEFAULTS, **(cfg or {}))
    if (os.name == 'nt' if windows is None else windows):
        return []
    out = []
    direct, txt = launch_flags(method, cfg)
    need = [f for f, on in (('-direct', direct), ('-txt', txt)) if on]
    if cfg['launcher'] == 'lutris':
        if need:
            out.append(f'Lutris will not pass {" / ".join(need)} (the {method} packing needs it): use Median split '
                       'or MPQ (patch_d2) packing, or the Direct Wine method.')
        if cfg['windowed']:
            out.append('Lutris uses its own arguments: -w here is ignored (set it in the Lutris game options).')
        return out
    lg = lg if lg is not None else lutris_game(game)
    if lg:
        chosen = cfg['wine'] or find_wine()
        if not lg['wine']:
            out.append(f'Lutris runner "{lg["wine_version"]}" not found on disk; using {chosen}.')
        elif not _same_path(shutil.which(chosen) or chosen, lg['wine']):
            out.append(f'{chosen} is not the Lutris runner of this prefix ({lg["wine"]}): it may upgrade the prefix.')
        if lg['prelaunch']:
            out.append('Direct Wine skips the Lutris pre-launch / post-exit commands of this game.')
    return out


def wine_prefix(path):
    p = os.path.abspath(path)
    while True:
        parent = os.path.dirname(p)
        if os.path.basename(p).lower() == 'drive_c':
            return parent
        if parent == p:
            return None
        p = parent


def find_wine():
    w = shutil.which('wine')
    if w:
        return w
    d = os.path.join(os.path.expanduser('~'), '.local', 'share', 'lutris', 'runners', 'wine')
    try:
        for r in sorted(os.listdir(d), reverse=True):
            p = os.path.join(d, r, 'bin', 'wine')
            if os.access(p, os.X_OK):
                return p
    except OSError:
        pass
    return 'wine'


def parse_env(text):
    env = {}
    for ln in (text or '').replace(';', '\n').splitlines():
        if '=' in ln and ln.split('=', 1)[0].strip():
            k, v = ln.split('=', 1)
            env[k.strip()] = v.strip()
    return env


def launch_spec(game, method, cfg=None, windows=None):
    """-> (argv, env additions, cwd, shown command line) for starting the game after a build with `method`."""
    import shlex
    cfg = dict(LAUNCH_DEFAULTS, **(cfg or {}))
    windows = os.name == 'nt' if windows is None else windows
    from .gui.build_tab import _ci_file
    exe = cfg['exe'] or os.path.basename(_ci_file(game, 'Game.exe') or 'Game.exe')
    if cfg['launcher'] == 'lutris' and cfg['lutris'] and not windows:
        argv = lutris_argv(cfg['lutris'])
        return argv, {}, game, ' '.join(shlex.quote(a) for a in argv)
    flags = []
    direct, txt = launch_flags(method, cfg)
    if direct:
        flags.append('-direct')
    if txt:
        flags.append('-txt')
    if cfg['windowed']:
        flags.append('-w')
    flags += shlex.split(cfg['args'] or '')
    cwd = cfg['workdir'] or game
    env = parse_env(cfg['env'])
    if windows:
        argv = [os.path.join(game, exe)] + flags
    else:
        pre = cfg['prefix'] or wine_prefix(game)
        if pre:
            env.setdefault('WINEPREFIX', pre)
        argv = [cfg['wine'] or find_wine(), exe] + flags
    shown = ' '.join(f'{k}={shlex.quote(v)}' for k, v in env.items())
    shown = (f'cd {shlex.quote(cwd)} && ' + (shown + ' ' if shown else '') + ' '.join(shlex.quote(a) for a in argv))
    return argv, env, cwd, shown


def launch_config_path():
    return os.path.join(os.environ.get('D2BT_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.config',
                                                                          'd2devkit'), 'launch.json')


def load_launch(game):
    """Saved settings of this install, else the defaults from its Lutris game (when one matches)."""
    doc = _read_json(launch_config_path()) or {}
    if not game:
        return dict(LAUNCH_DEFAULTS)
    saved = doc.get(GF.install_id(os.path.realpath(game)))
    return dict(LAUNCH_DEFAULTS, **(saved if saved is not None else lutris_defaults(game)))


def save_launch(game, cfg):
    doc = _read_json(launch_config_path()) or {}
    doc[GF.install_id(os.path.realpath(game))] = dict(cfg, install_path=os.path.realpath(game))
    _write_json(launch_config_path(), doc)


def start(argv, env, cwd):
    """Popen the game; stdout + stderr merged, own process group (Stop kills the whole tree)."""
    import subprocess
    full = dict(os.environ, **env)
    kw = {'start_new_session': True} if os.name != 'nt' else \
        {'creationflags': getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)}
    return subprocess.Popen(argv, cwd=cwd, env=full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, **kw)


def stop(proc, timeout=5, *, entire_group=False):
    if entire_group and os.name != 'nt' and proc is not None:
        _stop_group(proc, timeout)
        return
    import signal
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name != 'nt':
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout)
    except Exception:       # noqa: BLE001
        try:
            if os.name != 'nt':
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except Exception:   # noqa: BLE001
            pass


def _stop_group(proc, timeout):
    """The session leader's pid remains the group ID while any descendant is in it."""
    import signal
    import time

    def send(sig):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return False
        return True

    deadline = time.monotonic() + timeout
    alive = send(signal.SIGTERM)
    while alive and time.monotonic() < deadline:
        proc.poll()
        time.sleep(0.05)
        alive = send(0)
    if alive:
        send(signal.SIGKILL)
    proc.wait()


if __name__ == '__main__':     # tiny CLI: python -m d2bt.project <name>  (lists the recorded changes)
    pr = Project(sys.argv[1] if len(sys.argv) > 1 else 'default')
    for k, v in pr.items.items():
        print(v['kind'], v['arc'], v.get('path', ''))
