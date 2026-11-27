"""Legit mode (folder profiles such as vanilla 1.14d; Median XL has no such mode).

While it is on, a character may only be written, and an item only be built, when the server's legit rules
(the vendored d2legit package, from the D2-Development-Kit, MIT) find nothing impossible in it. The rules are run on
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
    try:
        import d2legit
        from d2legit.tables import MissingTables
        return d2legit.stock_validator(game_dir())
    except (MissingTables, OSError, KeyError, ValueError) as e:
        raise Unavailable(f"the stock Diablo II tables could not be read ({e}); Legit mode cannot check anything")


def prepare():
    """Loads the stock tables (a few seconds the first time); never raises."""
    try:
        _validator()
        return True
    except Exception:
        return False


def _finding(item, rule, detail, severity=IMPOSSIBLE):
    import d2legit
    return d2legit.Finding(item, rule, detail, severity)


def check_character(data):
    """Findings of the bytes of a .d2s."""
    from d2legit.savescan import SaveError, UnknownStatError
    v = _validator()
    try:
        char = v.parse(bytes(data))
    except UnknownStatError as e:
        return [_finding('character', 'stat', f'{e} (hacked)')]
    except (SaveError, IndexError, KeyError) as e:
        return [_finding('character', 'unreadable', str(e))]
    return v.validate(char)


def check_item(blob):
    """Findings of an item blob (the item plus its socketed items)."""
    from d2legit.savescan import SaveError, UnknownStatError, parse_items
    v = _validator()
    try:
        items = parse_items(bytes(blob), v.save_tables)
    except UnknownStatError as e:
        return [_finding('item', 'stat', f'{e} (hacked)')]
    except (SaveError, IndexError, KeyError) as e:
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
