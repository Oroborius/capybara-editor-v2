"""Shared startup and error reporting for the desktop launchers."""

import os
import sys
from time import perf_counter


def phase(label, started):
    from mxl_log import log
    log.info('startup: %s in %.3f s', label, perf_counter() - started)


def report_error(error):
    from mxl_log import log, path
    log.error('startup failed: %s', error, exc_info=True)
    try:
        from tkinter import messagebox
        details = f'\n\nLog: {path()}' if path() else ''
        messagebox.showerror('Capybara Editor could not start', f'{error}{details}')
    except Exception:
        log.exception('could not open startup error dialog')


_PROFILE_WORKER = '--capy-extract-profile'
PROFILE_TIMEOUT = 12


def _extract_worker(game_dir, output, transcript):
    import faulthandler
    import logging

    from mxl_log import log

    with open(transcript, 'w', encoding='utf-8') as trace:
        handler = logging.StreamHandler(trace)
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        faulthandler.enable(file=trace)
        try:
            from mxl_explode import install
            from mxl_speed import _install_decrypt
            from mxl_profile import extract

            install()
            _install_decrypt()
            extract(game_dir, output)
        except (Exception, SystemExit):
            log.exception('profile extraction failed')
            return 1
        finally:
            faulthandler.disable()
            log.removeHandler(handler)
    return 0


def extract_profile(game_dir, out):
    """Run MPQ decompression in a process the editor can terminate and diagnose."""
    import subprocess
    from tempfile import TemporaryDirectory

    from mxl_log import log
    from mxl_profile import _publish_data

    started = perf_counter()
    parent = os.path.dirname(os.path.abspath(out))
    os.makedirs(parent, exist_ok=True)
    with TemporaryDirectory(prefix='extract-', dir=parent) as work:
        data = os.path.join(work, 'data')
        transcript = os.path.join(work, 'extraction.log')
        args = [game_dir, data, transcript]
        if getattr(sys, 'frozen', False):
            command = [sys.executable, _PROFILE_WORKER, *args]
        else:
            code = ('import sys; sys.path.insert(0, sys.argv.pop(1)); '
                    'from mxl_boot import _extract_worker; sys.exit(_extract_worker(*sys.argv[1:]))')
            command = [sys.executable, '-c', code, os.path.dirname(os.path.abspath(__file__)), *args]
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
        try:
            result = subprocess.run(command, timeout=PROFILE_TIMEOUT, env=env, check=False)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f'Game data extraction exceeded {PROFILE_TIMEOUT} seconds for {game_dir}.') from error
        finally:
            if os.path.isfile(transcript):
                with open(transcript, encoding='utf-8', errors='replace') as trace:
                    for line in trace:
                        log.info('extraction: %s', line.rstrip())
        if result.returncode or not os.path.isfile(os.path.join(data, 'install.json')):
            raise RuntimeError(f'Game data extraction failed for {game_dir} (worker exit {result.returncode}).')
        _publish_data(data, out)
    phase('extract profile data', started)


def launch(prepare=None):
    if sys.argv[1:2] == [_PROFILE_WORKER]:
        raise SystemExit(_extract_worker(*sys.argv[2:]))

    from mxl_log import install
    import mxl_splash
    try:
        if prepare:
            prepare()
        import mxl_userdir
        mxl_userdir.setup()
        if mxl_splash.FLAG_ARG in sys.argv:
            mxl_splash.main()
            return
        install()
        mxl_splash.start()
        import mxl_creator_gui
        mxl_creator_gui.run()
    except (Exception, SystemExit) as error:
        if isinstance(error, SystemExit) and error.code in (None, 0):
            return
        install()
        mxl_splash.close()
        report_error(error)
        raise SystemExit(1) from error
    finally:
        mxl_splash.close()
