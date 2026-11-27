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


def max_sockets(rec, have=0):
    """Most sockets the server accepts on the item record rec (d2bt.legit validate_item's rule): the base's gemsockets
    capped by its item type's MaxSock at the item level; magic / rare / set / unique / crafted items only up to the
    quest allowance (2 magic, 1 others) or the sockets they already have (innate). None when it cannot be told."""
    try:
        from d2bt.legit import to_int
    except ImportError:
        from d2bt.tooltip.data import to_int
    try:
        v = _validator()
        base = v.bases[rec['code'].strip()][1]
        ilvl = rec.get('ilvl') or 1
        col = 'maxsock1' if ilvl <= 25 else 'maxsock25' if ilvl <= 40 else 'maxsock40'
        top = min(to_int(base.get('gemsockets')), to_int(v.item_types.get(base.get('type'), {}).get(col)))
        q = rec.get('quality')
        if q in ('magic', 'rare', 'set', 'unique', 'crafted'):
            top = min(top, max(2 if q == 'magic' else 1, have))
        return top
    except Exception:
        return None


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


_BLOB_VERDICT = {}


def item_is_illegit(blob):
    """Legit Mode on and the item blob has impossible findings (cached by its bytes; the pages draw a red border).
    False when the mode is off or the tables cannot be read."""
    if not blob or not enabled():
        return False
    key = bytes(blob)
    if key not in _BLOB_VERDICT:
        try:
            _BLOB_VERDICT[key] = bool(impossible(check_item(key)))
        except Exception:
            return False
        if len(_BLOB_VERDICT) > 4000:
            _BLOB_VERDICT.clear()
    return _BLOB_VERDICT[key]


ILLEGIT_BORDER = '#ff3030'
