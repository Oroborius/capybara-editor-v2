"""The one path for writing into a game install, keeping a pristine copy of every file it changes. No Tk in here.

    <D2BT_HOME or ~/D2DevKit>/originals/<install-id>/      install-id = bin_codebase.install_id(<install root>)
        originals.json   {"format": 1, "install_path",
                          "files": {<rel lower, '/'>: {"path": <rel as on disk>, "kind": "original" | "added",
                                                       "stored": <path in this folder>, "sha1", "size", "mtime",
                                                       "captured_at", ["link": <symlink target>]}}}
        changes.jsonl    one line per write / remove / restore
        <rel_path>       the untouched original of every file the app changed

ensure_original(root, rel)        the first time a game file is about to change: copy it here (an absent file is
                                  recorded as "added"). A stored original is never replaced, so a file patched
                                  twice still restores to the version before the first patch.
write_game_file(root, rel, data=None, src_path=None)
                                  ensure_original, then temp file in the same folder + os.replace (a symlink is
                                  replaced itself, never written through); logged.
remove_game_file(root, rel)       ensure_original, then delete (used when a deploy backup is undone).
restore(root, rel_paths=None)     originals back (all or the selected ones); files the app added are deleted.
status(root)                      per tracked file: original / modified / missing / added / removed.
find_install(path, roots=())      the install root a path lies in (given roots, else a folder holding the game's
                                  data archives), or None. Nothing under D2BT_HOME counts: the store itself holds
                                  copies of medianxl-*.mpq.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time

FORMAT = 1
MANIFEST = 'originals.json'
LOG = 'changes.jsonl'
# A game folder is recognised by its data archives (never by Game.exe / D2Sigma.dll alone: patched copies of those
# live in the app's own output folders).
GAME_MARKERS = ('d2data.mpq', 'd2exp.mpq', 'patch_d2.mpq', 'd2char.mpq')

_LOCK = threading.RLock()


class GameFileError(ValueError):
    pass


def home_dir():
    return os.environ.get('D2BT_HOME') or os.path.join(os.path.expanduser('~'), 'D2DevKit')


def install_id(root):
    from .gui.bin_codebase import install_id as _iid      # the codebase's id: one id per install everywhere
    return _iid(root)


def store_dir(root):
    return os.path.join(home_dir(), 'originals', install_id(os.path.realpath(root)))


def _key(rel):
    return rel.replace('\\', '/').strip('/').lower()


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def is_game_folder(d):
    try:
        names = {n.lower() for n in os.listdir(d)}
    except OSError:
        return False
    return bool(names & set(GAME_MARKERS)) or any(n.startswith('medianxl-') and n.endswith('.mpq') for n in names)


def _under(path, folder):
    p, f = os.path.realpath(path), os.path.realpath(folder)
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def find_install(path, roots=()):
    """-> the realpath of the install `path` lies in, or None."""
    if not path:
        return None
    if _under(path, home_dir()):
        return None
    for r in roots:
        if r and _under(path, r):
            return os.path.realpath(r)
    d = os.path.realpath(path)
    if not os.path.isdir(d):
        d = os.path.dirname(d)
    while True:
        if is_game_folder(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def rel_in(root, path):
    """`path` (absolute) relative to the install root, '/'-separated; raises when it is outside."""
    r = os.path.realpath(root)
    p = os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(path))), os.path.basename(path))
    rel = os.path.relpath(p, r)
    if rel == '.' or rel.startswith('..') or os.path.isabs(rel):
        raise GameFileError(f'{path} is not inside the game folder {root}')
    return rel.replace(os.sep, '/')


def _target(root, rel):
    """-> (absolute path, rel with the on-disk spelling). Existing folders / files are matched case-insensitively;
    a parent folder that resolves outside the install (symlink) is refused."""
    r = os.path.realpath(root)
    parts = [p for p in rel.replace('\\', '/').split('/') if p not in ('', '.')]
    if not parts or '..' in parts:
        raise GameFileError(f'bad game file path: {rel!r}')
    cur, spelled = r, []
    for i, part in enumerate(parts):
        hit = part
        try:
            if not os.path.lexists(os.path.join(cur, part)):
                low = part.lower()
                hit = next((n for n in os.listdir(cur) if n.lower() == low), part)
        except OSError:
            pass
        spelled.append(hit)
        cur = os.path.join(cur, hit)
    if not _under(os.path.dirname(cur), r):
        raise GameFileError(f'{rel}: its folder leads outside the game folder (symlink)')
    return cur, '/'.join(spelled)


# ------------------------------------------------------------------------------------------- manifest
def _read_manifest(sd):
    try:
        with open(os.path.join(sd, MANIFEST), encoding='utf-8') as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and isinstance(doc.get('files'), dict):
            return doc
    except (OSError, ValueError):
        pass
    return None


def manifest(root):
    root = os.path.realpath(root)
    return _read_manifest(store_dir(root)) or {'format': FORMAT, 'install_path': root, 'files': {}}


def _save_manifest(root, doc):
    sd = store_dir(root)
    os.makedirs(sd, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.originals-', dir=sd)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
        fh.write('\n')
    os.replace(tmp, os.path.join(sd, MANIFEST))


def _log(root, **rec):
    sd = store_dir(root)
    os.makedirs(sd, exist_ok=True)
    rec = {'time': _now(), **rec}
    with open(os.path.join(sd, LOG), 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec) + '\n')


def change_log(root):
    out = []
    try:
        with open(os.path.join(store_dir(root), LOG), encoding='utf-8') as fh:
            for ln in fh:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def _stored_name(rel):
    if _key(rel) in (MANIFEST, LOG):
        return '_game_root_/' + rel
    return rel


def stored_original(install_root, rel_path):
    """Read-only: (path, sha1) of the pristine copy of rel_path kept in the originals store, or None (nothing
    stored, or the stored file no longer hashes to its recorded sha1). Never captures anything."""
    sd = store_dir(install_root)
    ent = (_read_manifest(sd) or {}).get('files', {}).get(_key(rel_path))
    if not ent or ent.get('kind') != 'original' or not ent.get('stored'):
        return None
    p = os.path.join(sd, ent['stored'])
    if not os.path.isfile(p):
        return None
    s = sha1_file(p)
    return (p, s) if not ent.get('sha1') or s == ent['sha1'] else None


# ------------------------------------------------------------------------------------------- capture / write
def ensure_original(install_root, rel_path, pristine=None):
    """Keep the untouched original of install_root/rel_path before its first change. -> the manifest entry.
    An entry already in the store is never replaced (the file may be patched since: that is expected).
    `pristine`: a known-untouched copy of an existing file (e.g. the binary codebase's original.dll) to store
    instead of the file on disk, which may already be modified by an earlier tool or app version."""
    root = os.path.realpath(install_root)
    with _LOCK:
        doc = manifest(root)
        k = _key(rel_path)
        ent = doc['files'].get(k)
        if ent is not None:
            return ent
        dst, rel = _target(root, rel_path)
        sd = store_dir(root)
        if not os.path.lexists(dst):
            ent = {'path': rel, 'kind': 'added', 'captured_at': _now()}
        elif os.path.isdir(dst):
            raise GameFileError(f'{rel} is a folder')
        else:
            stored = _stored_name(rel)
            sp = os.path.join(sd, *stored.split('/'))
            os.makedirs(os.path.dirname(sp), exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix='.capture-', dir=os.path.dirname(sp))
            os.close(fd)
            src = pristine if pristine and os.path.isfile(pristine) else dst
            try:
                shutil.copy2(src, tmp)              # follows a symlink: its content is what the game reads
                want = sha1_file(src)
                if sha1_file(tmp) != want:
                    raise GameFileError(f'{rel}: the copy in the originals store does not match the file')
                os.replace(tmp, sp)
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
            st = os.stat(src)
            ent = {'path': rel, 'kind': 'original', 'stored': stored, 'sha1': want, 'size': st.st_size,
                   'mtime': st.st_mtime, 'captured_at': _now()}
            if src != dst:
                ent['from'] = src
            elif os.path.islink(dst):
                ent['link'] = os.readlink(dst)
        doc['files'][k] = ent                       # the manifest entry is the commit point
        _save_manifest(root, doc)
        _log(root, action='capture', rel=rel, kind=ent['kind'], sha1=ent.get('sha1'))
        return ent


def _atomic_put(dst, data=None, src_path=None):
    """temp file in dst's folder + os.replace: a symlink at dst is replaced, never written through."""
    d = os.path.dirname(dst)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.d2bt-', suffix='.part', dir=d)
    try:
        with os.fdopen(fd, 'wb') as fh:
            if src_path is not None:
                with open(src_path, 'rb') as sf:
                    shutil.copyfileobj(sf, fh, 1 << 20)
            else:
                fh.write(data)
        if src_path is not None:
            shutil.copystat(src_path, tmp)
        elif os.path.isfile(dst) and not os.path.islink(dst):
            shutil.copymode(dst, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def write_game_file(install_root, rel_path, data=None, src_path=None, note=''):
    """Write bytes (`data`) or a copy of `src_path` to install_root/rel_path, keeping the original first.
    -> absolute path written."""
    if (data is None) == (src_path is None):
        raise ValueError('write_game_file needs exactly one of data / src_path')
    root = os.path.realpath(install_root)
    with _LOCK:
        ensure_original(root, rel_path)
        dst, rel = _target(root, rel_path)
        if src_path is not None and os.path.lexists(dst) and os.path.realpath(src_path) == os.path.realpath(dst):
            raise GameFileError(f'{rel}: source and target are the same file')
        _atomic_put(dst, data, src_path)
        _log(root, action='write', rel=rel, sha1=sha1_file(dst), note=note)
        return dst


def remove_game_file(install_root, rel_path, note=''):
    """Delete install_root/rel_path (its original is kept first). -> True when something was removed."""
    root = os.path.realpath(install_root)
    with _LOCK:
        dst, rel = _target(root, rel_path)
        if not os.path.lexists(dst):
            return False
        ensure_original(root, rel_path)
        os.remove(dst)
        _log(root, action='remove', rel=rel, note=note)
        return True


# ------------------------------------------------------------------------------------------- status / restore
def _state(root, ent):
    p, _ = _target(root, ent['path'])
    if ent['kind'] == 'added':
        return 'added' if os.path.lexists(p) else 'removed'
    if not os.path.lexists(p):
        return 'missing'
    if ent.get('link') is not None:
        if os.path.islink(p) and os.readlink(p) == ent['link']:
            return 'original'
        return 'modified'
    if os.path.islink(p) or not os.path.isfile(p):
        return 'modified'
    if os.path.getsize(p) != ent['size']:
        return 'modified'
    return 'original' if sha1_file(p) == ent['sha1'] else 'modified'


def status(install_root):
    """-> [{rel, kind ('original' | 'added'), state, captured_at, sha1}] sorted by path. States:
    original (byte-identical to the stored original), modified, missing (original deleted), added (a file the app
    created, still there), removed (an added file that is gone again)."""
    root = os.path.realpath(install_root)
    out = []
    for k, ent in sorted(manifest(root)['files'].items()):
        try:
            st = _state(root, ent)
        except (OSError, GameFileError):
            st = 'missing'
        out.append({'rel': ent['path'], 'key': k, 'kind': ent['kind'], 'state': st,
                    'captured_at': ent.get('captured_at', ''), 'sha1': ent.get('sha1')})
    return out


def changed(install_root):
    """status() rows that differ from the install as it was: modified / missing / added."""
    return [r for r in status(install_root) if r['state'] in ('modified', 'missing', 'added')]


def restore(install_root, rel_paths=None):
    """Put the originals back (every tracked file, or the given rel paths) and delete the files the app added.
    -> {'restored': [rel], 'removed': [rel], 'unchanged': [rel], 'unknown': [rel]}"""
    root = os.path.realpath(install_root)
    res = {'restored': [], 'removed': [], 'unchanged': [], 'unknown': []}
    with _LOCK:
        files = manifest(root)['files']
        keys = sorted(files) if rel_paths is None else [_key(r) for r in rel_paths]
        sd = store_dir(root)
        for k in keys:
            ent = files.get(k)
            if ent is None:
                res['unknown'].append(k)
                continue
            st = _state(root, ent)
            dst, rel = _target(root, ent['path'])
            if ent['kind'] == 'added':
                if os.path.lexists(dst):
                    os.remove(dst)
                    res['removed'].append(rel)
                    _log(root, action='restore-remove', rel=rel)
                else:
                    res['unchanged'].append(rel)
                continue
            if st == 'original':
                res['unchanged'].append(rel)
                continue
            sp = os.path.join(sd, *ent['stored'].split('/'))
            if not os.path.isfile(sp) or sha1_file(sp) != ent['sha1']:
                raise GameFileError(f'{rel}: the stored original is missing or damaged ({sp})')
            if ent.get('link') is not None:
                if os.path.lexists(dst):
                    os.remove(dst)
                os.symlink(ent['link'], dst)
            else:
                _atomic_put(dst, src_path=sp)
            res['restored'].append(rel)
            _log(root, action='restore', rel=rel, sha1=ent['sha1'])
    return res


def confirm_text(install_root, rel_paths, intro='', limit=10):
    """The text of the one confirm dialog before a write into an install."""
    root = os.path.realpath(install_root)
    known = manifest(root)['files']
    lines = []
    for rel in rel_paths[:limit]:
        try:
            p, _ = _target(root, rel)
            new = rel and not os.path.lexists(p)
        except GameFileError:
            new = False
        tag = '  (new)' if new else ('  (original already kept)' if _key(rel) in known else '')
        lines.append('  ' + rel.replace('/', os.sep) + tag)
    if len(rel_paths) > limit:
        lines.append(f'  ... and {len(rel_paths) - limit} more')
    return ((intro + '\n\n' if intro else '') + f'Write into the game folder\n    {root}\n\n' + '\n'.join(lines)
            + f'\n\nOriginals are kept in\n    {store_dir(root)}\nRestore any time with "Restore originals..." '
              '(Extras > Folders & tools, or Compile / Mod > Deploy).\n\nContinue?')


def publish_dir(install_root, staged_dir, target_dir, note=''):
    """Copy every file under staged_dir to the same relative place under target_dir (inside the install) through
    write_game_file. -> [rel paths written]"""
    root = os.path.realpath(install_root)
    base = '' if os.path.realpath(target_dir) == root else rel_in(root, os.path.join(target_dir, 'x'))[:-1]
    out = []
    for dp, dns, fns in os.walk(staged_dir):
        dns.sort()
        for fn in sorted(fns):
            src = os.path.join(dp, fn)
            rel = base + os.path.relpath(src, staged_dir).replace(os.sep, '/')
            write_game_file(root, rel, src_path=src, note=note)
            out.append(rel)
    return out


def staged_rels(install_root, staged_dir, target_dir):
    """The rel paths publish_dir would write (for the confirm dialog)."""
    root = os.path.realpath(install_root)
    base = '' if os.path.realpath(target_dir) == root else rel_in(root, os.path.join(target_dir, 'x'))[:-1]
    return [base + os.path.relpath(os.path.join(dp, fn), staged_dir).replace(os.sep, '/')
            for dp, _d, fns in sorted(os.walk(staged_dir)) for fn in sorted(fns)]


def known_installs():
    """Install folders that have an originals store. -> [install path]"""
    base = os.path.join(home_dir(), 'originals')
    out = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for n in names:
        doc = _read_manifest(os.path.join(base, n))
        if doc and doc.get('install_path') and doc['files']:
            out.append(doc['install_path'])
    return out
