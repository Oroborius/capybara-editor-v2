"""Small on-disk caches of values the editor derives from the game tables (<user dir>/cache/<name>.json).

A cache file holds a key and a value. The key is built from everything the value depends on: size and mtime of
every file in the input folders (the extracted game tables), size and mtime of the editor's own code (every
code file of the editor's folder and the modules named by the caller: a new editor build has new files), and extra
values the caller adds (the language...). load() returns None unless the stored key is exactly the current one,
so a changed table, a new editor version or another language simply rebuilds the value. Never fatal: an
unreadable or unwritable cache is no cache."""
import hashlib
import json
import os
import sys
import threading

VERSION = 1


def _stat(path):
    try:
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return None


def _code_stamp(m):
    """Size / mtime of a module's file; for a module without a readable file (frozen into the Windows exe) a
    digest of its functions' bytecode, so a new build still changes the key."""
    if m is None:
        return None
    f = getattr(m, '__file__', None)
    st = _stat(f) if f else None
    if st is not None:
        return st
    h = hashlib.sha1()

    def feed(code):
        h.update(code.co_code)
        for c in code.co_consts:
            if hasattr(c, 'co_code'):
                feed(c)
            elif isinstance(c, (str, int, float, bytes, tuple, frozenset, type(None))):
                h.update(repr(c).encode('utf-8', 'replace'))
    for name in sorted(vars(m)):
        obj = vars(m)[name]
        if getattr(obj, '__module__', None) != m.__name__:
            continue
        funcs = [obj] if hasattr(obj, '__code__') else [v for v in vars(obj).values() if hasattr(v, '__code__')] \
            if isinstance(obj, type) else []
        for fn in funcs:
            h.update(name.encode())
            feed(fn.__code__)
    return h.hexdigest()


def key(folders=(), modules=(), extra=()):
    """A digest of the inputs: files directly in each folder (name, size, mtime), every code file of the editor's
    folder, the modules named in `modules` (their file, or their bytecode when frozen), and `extra` (JSON-able
    values). Independent of what happens to be imported when it is asked."""
    parts = [VERSION, sys.version_info[:2]]
    for folder in folders:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            names = None
        parts.append([folder, [[n, _stat(os.path.join(folder, n))] for n in names] if names is not None else None])
    parts.append(_stat(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))       # the editor's code folder (every module's file there)
    try:
        code = sorted(n for n in os.listdir(here) if n.endswith(('.py', '.pyc')))
    except OSError:
        code = []
    parts.append([[n, _stat(os.path.join(here, n))] for n in code])
    for n in sorted(set(modules) | {'mxl_creator', 'mxl_statnames', 'mxl_lang'}):   # (frozen: their bytecode)
        if n not in sys.modules:
            try:
                __import__(n)
            except Exception:
                pass
        parts.append([n, _code_stamp(sys.modules.get(n))])
    parts.append(list(extra))
    return hashlib.sha1(json.dumps(parts, default=str).encode('utf-8')).hexdigest()


def path(name):
    try:
        import paths
        root = paths.USER_DIR
    except Exception:
        return None
    return os.path.join(root, 'cache', name + '.json')


def load(name, k):
    """The stored value when its key is `k`, else None."""
    p = path(name)
    if not p:
        return None
    try:
        with open(p, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get('key') != k:
        return None
    return doc.get('value')


def save(name, k, value):
    p = path(name)
    if not p:
        return False
    tmp = f'{p}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'key': k, 'value': value}, f, separators=(',', ':'))
        os.replace(tmp, p)              # (Windows: refused while another editor reads the file - no cache this time)
        return True
    except (OSError, TypeError, ValueError):
        try:                            # a half-written or unplaced temporary file never stays in the folder
            os.remove(tmp)
        except OSError:
            pass
        return False
