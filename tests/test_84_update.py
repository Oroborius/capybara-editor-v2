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


T.main(globals())
