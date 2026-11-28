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


@T.test
def support_zip_upload_sends_the_fields_and_reads_the_ticket():
    """More > Make a support zip > Send to LadderBot: a multipart POST of file / discord / version / note; the reply
    {"ok": true, "id": ...} gives the ticket, {"ok": false, ...} is an error. Not offered without an address."""
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import cgi
    import json
    import tempfile
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import mxl_support as S
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD': 'POST'})
            got.update({k: form[k].value for k in ('discord', 'version', 'note')})
            got['file'] = (form['file'].filename, form['file'].value)
            ok = got['discord'] != 'refuse me'
            body = json.dumps({'ok': True, 'id': 'T42'} if ok else {'ok': False, 'error': 'nope'}).encode()
            self.send_response(200 if ok else 400)              # the live address refuses with 400 + a reason
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{srv.server_port}/__upload'
    path = _support_zip(tempfile.mkdtemp())
    import mxl_update
    o_tag = mxl_update.current_tag
    mxl_update.current_tag = lambda: 'v2.0-2026-11-28-10'
    try:
        T.eq(S.upload(path, 'tester#1', 'mana resets', url=url), 'T42', 'the ticket')
        T.eq((got['discord'], got['note'], got['file'][0]), ('tester#1', 'mana resets', os.path.basename(path)),
             'the fields')
        T.eq(got['file'][1], open(path, 'rb').read(), 'the zip bytes')
        try:
            S.upload(path, 'refuse me', url=url)
            T.check(False, 'a refusal raises')
        except OSError as e:
            T.check('nope' in str(e), f'the error: {e}')
    finally:
        mxl_update.current_tag = o_tag
        srv.shutdown()
        os.remove(path)
    import settings
    old = settings.get('support_send_url')
    try:
        settings.put('support_send_url', '')
        T.check(not S.offer_send() or bool(S.SEND_URL), 'not offered without an upload address')
        settings.put('support_send_url', url)
        settings.put(S.ASK_SETTING, False)
        T.check(not S.offer_send(), 'not offered after Never')
        S.set_offer(True)
        T.check(S.offer_send(), 'offered again after the More check box')
    finally:
        settings.put('support_send_url', old or '')
        settings.put(S.ASK_SETTING, True)



def _support_zip(folder, stamp='20261128-162418', extra=(), d2s=b'\x55\xaa\x55\xaa' + b'\0' * 60, readme=None):
    import zipfile
    path = os.path.join(folder, f'Capybara-support-{stamp}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('log/capybara.log', '2026-11-28 16:21:40 INFO    build v2.0-2026-11-28-9 (commit 83e3dfa)\n')
        z.writestr('settings.json', '{"mock_mode": true}')
        z.writestr('saves/Hero.d2s', d2s)
        z.writestr('saves/backups/Hero.d2s.bak-20261128-014649', d2s)
        for name, data in extra:
            z.writestr(name, data)
        z.writestr('README.txt', readme if readme is not None else f'MXL Capybara Editor support zip, {stamp}\nsave folder: x\n')
    return path


@T.test
def the_upload_accepts_only_genuine_support_zips():
    """The shared check (mxl_support_check.validate, also run by the upload address and LadderBot): a support zip
    the editor makes passes; renamed, traversal, foreign files, a zip bomb, a fake .d2s, a wrong stamp or version
    do not."""
    if T.APP not in sys.path:
        sys.path.insert(0, T.APP)
    import tempfile
    import zipfile
    import mxl_support_check as C
    d = tempfile.mkdtemp()
    v = 'v2.0-2026-11-28-10'

    def check(path, name=None, version=v):
        return C.validate(open(path, 'rb').read(), name or os.path.basename(path), version)
    good = _support_zip(d)
    T.eq(check(good), (True, ''), 'a genuine support zip')
    T.check(not check(good, 'evil.zip')[0], 'another file name')
    T.check(not check(good, version='1.0')[0], 'another version')
    T.check(not check(good, 'Capybara-support-20261128-162419.zip')[0], 'the stamp does not match the README')
    for what, kw in (('traversal', dict(extra=[('../x.txt', 'x')])),
                     ('an exe', dict(extra=[('saves/run.exe', 'MZ')])),
                     ('html', dict(extra=[('index.html', '<script>')])),
                     ('a fake .d2s', dict(d2s=b'MZ' + b'\0' * 60)),
                     ('another README', dict(readme='hello\n'))):
        sub = tempfile.mkdtemp()
        T.check(not check(_support_zip(sub, **kw))[0], f'refused: {what}')
    bomb = os.path.join(tempfile.mkdtemp(), 'Capybara-support-20261128-162418.zip')
    with zipfile.ZipFile(bomb, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('log/capybara.log', 'build v2.0-x\n' + 'A' * (20 * 1024 * 1024))
        z.writestr('README.txt', 'MXL Capybara Editor support zip, 20261128-162418\n')
    T.check(not check(bomb)[0], 'refused: a zip bomb')
    T.check(not C.validate(b'PK' + b'0' * 50, 'Capybara-support-20261128-162418.zip', v)[0], 'refused: not a zip')

T.main(globals())
