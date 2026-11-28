"""More -> "Check for updates..." (src/mxl_update.py): release tags compare by date then number; a build without
build_info.json counts as older than any release; the update mode follows how the editor runs. No network here."""
import os
import sys

import capytest as T

MODE = 'engine'
NEEDS = ()


@T.test
def tags_compare_and_mode():
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import mxl_update as U
    T.check(U.newer('v2.0-2026-11-21-4', 'v2.0-2026-11-21-3'), '-4 is newer than -3')
    T.check(U.newer('v2.0-2026-11-22', 'v2.0-2026-11-21-9'), 'a later day wins')
    T.check(not U.newer('v2.0-2026-11-21', 'v2.0-2026-11-21-2'), 'the plain tag is the first of its day')
    T.check(not U.newer('v2.0-2026-11-21-2', 'v2.0-2026-11-21-2'), 'same tag: up to date')
    T.check(U.newer('v2.0-2026-11-21-2', None), 'no build_info: any release is newer')
    T.check(not U.newer('garbage', 'v2.0-2026-11-21'), 'an unknown tag is never offered')
    os.environ.pop('APPIMAGE', None)
    T.eq(U.mode(), 'browser', 'from source: the browser')



@T.test
def both_hosts_are_tried_and_logged_when_they_time_out():
    """Tester: "Could not reach the release page: timed out". Every host is tried; each failure goes to the log
    (the support zip shows which one failed); the last error is raised for the window (which offers the page)."""
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import socket
    import urllib.error
    import urllib.request
    import mxl_update as U
    tried, logged = [], []

    def fake(req, timeout=None):
        tried.append(req.full_url)
        raise urllib.error.URLError(socket.timeout('timed out'))
    o_open, o_log = urllib.request.urlopen, U._log_error
    urllib.request.urlopen, U._log_error = fake, lambda what, err: logged.append(what)
    try:
        try:
            U.latest_release(timeout=1)
            T.check(False, 'an error is raised')
        except Exception as e:
            T.check('timed out' in str(e), f'the error: {e}')
    finally:
        urllib.request.urlopen, U._log_error = o_open, o_log
    T.eq(tried, list(U.APIS), 'both hosts tried, GitHub first')
    T.eq(len(logged), 2, f'each failure logged: {logged}')

T.main(globals())
