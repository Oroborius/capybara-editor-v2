"""In-process GUI harness of the mxl_savecheck tests (the editor's pre-write check that uses mxlsave).

run(test, name, saves='saves117', env=...) boots the application on FRESH COPIES of the fixtures and calls
test(app, ctx). One application per process; never the real display, never real saves:

    env WAYLAND_DISPLAY=fake xvfb-run -a -s "-screen 0 1280x720x24" \\
        dist/linux/AppDir/opt/python/bin/python3.10 tools/mxlsave/tests/app/t_guard.py

Needs the AppDir (packaging/build_appimage.sh --appdir-only) and the fixtures in dist/work/orig/ (or
$MXL_TEST_ORIG): home/ (user dir with data/), saves100/, saves117/ (the sample characters) and corrupt/ (the
Mr_Owlie*corrupt* stashes + Mr_Owlie_repaired.stash). Work copies and screenshots go to dist/work/.

t_mass.py   every item the creator can build is accepted by the check (false-positive hunt)
t_paths.py  every write the features perform, in strict mode: no refusal, timing, standalone verify
            [saves100|saves117]
t_guard.py  corrupted output: refused in strict, written with warning + extra backup in warn; the corrupt
            samples as output; restore-backup round trip
t_win.py    "Compare with backup..." through the More menu, screenshots, restore with the confirmation in the
            window [d2|he]
"""
import gc, os, shutil, sys, traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
APP = os.path.join(ROOT, 'dist/linux/AppDir/opt/capybara')
WORK = os.path.join(ROOT, 'dist/work')
ORIG = os.environ.get('MXL_TEST_ORIG') or os.path.join(WORK, 'orig')


class Ctx:
    pass


def run(test, name, saves='saves117', env=None, extra=None):
    ctx = Ctx()
    ctx.dir = os.path.join(WORK, 'run_' + name)
    os.makedirs(WORK, exist_ok=True)
    shutil.rmtree(ctx.dir, ignore_errors=True)
    ctx.home = os.path.join(ctx.dir, 'home')
    ctx.saves = os.path.join(ctx.dir, 'saves')
    shutil.copytree(os.path.join(ORIG, 'home'), ctx.home)
    shutil.copytree(os.path.join(ORIG, saves), ctx.saves)
    for src, dst in (extra or {}).items():
        shutil.copy2(src, os.path.join(ctx.saves, dst))
    try:
        os.remove(os.path.join(ctx.home, 'capybara.log'))
    except OSError:
        pass
    os.environ['MXL_USER_DIR'] = ctx.home
    os.environ['MXL_SAVE_DIR'] = ctx.saves
    os.environ.update(env or {})
    sys.path.insert(0, APP)
    sys.argv = [os.path.join(APP, 'capybara_editor.py')]
    import tkinter
    from tkinter import messagebox
    ctx.boxes = []
    for fn in ('showerror', 'showwarning', 'showinfo'):
        setattr(messagebox, fn, lambda title=None, message=None, _fn=fn, **kw: ctx.boxes.append((_fn, title, message)))
    for fn in ('askyesno', 'askokcancel', 'askyesnocancel'):
        setattr(messagebox, fn, lambda *a, **k: True)
    tkinter.Menu.tk_popup = lambda self, *a, **k: None
    ctx.rc = 1

    def mainloop(self, n=0):
        try:
            import mxl_gui
            app = next(o for o in gc.get_objects() if isinstance(o, mxl_gui.App))
            ctx.app = app
            ctx.pump = lambda k=40: [app.root.update() for _ in range(k)]
            ctx.pump()
            test(app, ctx)
            ctx.rc = 0
        except Exception:
            traceback.print_exc()
        finally:
            try:
                self.winfo_toplevel().destroy()
            except Exception:
                pass
    tkinter.Misc.mainloop = mainloop
    import capybara_editor
    try:
        capybara_editor.main()
    except SystemExit:
        pass
    return ctx


def log_lines(ctx, word='savecheck'):
    import mxl_log
    for h in mxl_log.log.handlers:
        h.flush()
    p = os.path.join(ctx.home, 'capybara.log')
    if not os.path.exists(p):
        return []
    with open(p, encoding='utf-8') as f:
        return [l.rstrip() for l in f if word in l]
