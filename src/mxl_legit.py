"""Legit mode (folder profiles such as vanilla 1.14d; Median XL has no such mode).

While it is on, a character may only be written, and an item only be built, when the server's legit rules
(the dev kit's validator, vendored unchanged as package d2bt, MIT) find nothing impossible in it. The rules are run on
the bytes the editor would write, against the stock 1.14d tables of the selected Diablo II folder. 'impossible'
findings refuse the write; 'suspicious' ones only warn. No Tk in here."""
from mxl_char import CharError

SETTING = 'legit_mode'
LABEL = "Legit mode: checked against the server's rules"
IMPOSSIBLE, SUSPICIOUS = 'impossible', 'suspicious'


def _profile():
    try:
        import mxl_profile
        return mxl_profile.active() or {}
    except Exception:
        return {}


def supported():
    return bool(_profile().get('supported'))


def enabled():
    """Legit mode is on (setting 'legit_mode') for a loaded folder profile."""
    try:
        import settings
        on = bool(settings.get(SETTING))
    except Exception:
        on = False
    return on and supported()


def set_enabled(on):
    import settings
    settings.put(SETTING, bool(on))


def game_dir():
    p = _profile()
    return p.get('base_dir') or p.get('game_dir') or ''


class LegitError(CharError):
    def __init__(self, message, findings=()):
        super().__init__(message)
        self.findings = list(findings)


class Unavailable(Exception):
    pass


def _windows_pread():
    """Windows has no os.pread, which the vendored MPQ reader (d2bt/mpq.py, kept unchanged) uses: a seek + read
    stand-in that leaves the descriptor's position where it was (tester: "module 'os' has no attribute 'pread'")."""
    import os
    import threading
    if hasattr(os, 'pread'):
        return
    lock = threading.Lock()

    def pread(fd, n, offset):
        with lock:
            here = os.lseek(fd, 0, os.SEEK_CUR)
            try:
                os.lseek(fd, offset, os.SEEK_SET)
                parts, left = [], n
                while left > 0:
                    chunk = os.read(fd, left)
                    if not chunk:
                        break
                    parts.append(chunk)
                    left -= len(chunk)
                return b''.join(parts)
            finally:
                os.lseek(fd, here, os.SEEK_SET)
    os.pread = pread


def _validator():
    """The dev kit's own validator (vendored unchanged: package d2bt, commit in d2bt/VENDORED.txt), so the editor
    and the server give the same verdict. Its table cache lives in the editor's user folder."""
    import os
    try:
        import paths
        os.environ.setdefault('D2BT_HOME', os.path.join(paths.USER_DIR, 'legit'))
    except Exception:
        pass
    import sys
    _windows_pread()
    here = os.path.dirname(os.path.abspath(__file__))     # Windows build: d2bt is a folder in _internal
    if here not in sys.path:
        sys.path.append(here)
    try:
        from d2bt.legit import stock_validator
        return stock_validator(game_dir())
    except Exception as e:
        raise Unavailable(f"the stock Diablo II tables could not be read ({e}); Legit mode cannot check anything")


def prepare():
    """Loads the stock tables (a few seconds the first time); never raises."""
    try:
        _validator()
        return True
    except Exception:
        return False


def _finding(item, rule, detail, severity=IMPOSSIBLE):
    from d2bt.legit import Finding
    return Finding(item, rule, detail, severity)


def check_character(data):
    """Findings of the bytes of a .d2s (an unreadable save counts as hacked, like the server)."""
    import os
    import tempfile
    from d2bt.lint.savescan import SaveError, UnknownStatError
    v = _validator()
    fd, path = tempfile.mkstemp(suffix='.d2s')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(bytes(data))
        try:
            char = v.parse(path)
        except UnknownStatError as e:
            return [_finding('character', 'stat', f'{e} (hacked)')]
        except (SaveError, IndexError, KeyError, ValueError) as e:
            return [_finding('character', 'unreadable', str(e))]
        return v.validate(char)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def check_item(blob):
    """Findings of an item blob (the item plus its socketed items), read by the dev kit's own item reader."""
    from d2bt.lint.savescan import SaveError, UnknownStatError, Usage, _item
    v = _validator()
    buf, items, u, pos = bytes(blob), [], Usage(''), 0
    try:
        while pos < len(buf):
            pos, flags, nsock = _item(buf, pos, v.save_tables, u, items)
            for _ in range(nsock if flags >> 11 & 1 else 0):
                pos, _f, _n = _item(buf, pos, v.save_tables, u, items[-1].children)
    except UnknownStatError as e:
        return [_finding('item', 'stat', f'{e} (hacked)')]
    except (SaveError, IndexError, KeyError, ValueError) as e:
        return [_finding('item', 'unreadable', str(e))]
    out = []
    for it in items:
        out.extend(v.validate_item(it))
    return out


def impossible(findings):
    return [f for f in findings if f.severity == IMPOSSIBLE]


def summary(findings, limit=6):
    """Short text: one line per finding (item: rule - detail), the rest counted."""
    lines = [f'{f.item}: {f.rule} - {f.detail}' for f in findings[:limit]]
    if len(findings) > limit:
        lines.append(f'... and {len(findings) - limit} more')
    return '\n'.join(lines)


def refusal(findings):
    return (f'{LABEL}.\nNothing was written: {len(findings)} impossible '
            f'{"thing" if len(findings) == 1 else "things"} found.\n' + summary(findings))


def guard_character(content):
    """Called with the bytes about to be written. -> suspicious findings (warn); raises LegitError (impossible)."""
    if not enabled():
        return []
    try:
        findings = check_character(content)
    except Unavailable as e:
        raise LegitError(f'{LABEL}.\nNothing was written: {e}')
    bad = impossible(findings)
    if bad:
        raise LegitError(refusal(bad), bad)
    return [f for f in findings if f.severity == SUSPICIOUS]


def guard_item(blob):
    """-> suspicious findings; raises LegitItemError on impossible ones."""
    if not enabled():
        return []
    try:
        findings = check_item(blob)
    except Unavailable as e:
        raise LegitItemError(f'{LABEL}.\nNot created: {e}')
    bad = impossible(findings)
    if bad:
        raise LegitItemError(refusal(bad).replace('Nothing was written', 'Not created'), bad)
    return [f for f in findings if f.severity == SUSPICIOUS]


class LegitItemError(Exception):
    def __init__(self, message, findings=()):
        super().__init__(message)
        self.findings = list(findings)
