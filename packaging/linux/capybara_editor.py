"""Linux entry point of MXL Capybara Editor V2 (AppImage, or run from a staged app folder).

Same start sequence as the launcher repack.py puts in the Windows exe, after mapping the Windows-only defaults:
- settings / data folder: $XDG_DATA_HOME/MXL Capybara Editor (LOCALAPPDATA is what the collector and the editor read);
- save folder: MXL_SAVE_DIR, else the first <Wine prefix>/drive_c/users/*/AppData/Roaming/MedianXL/save found
  ($WINEPREFIX, ~/.wine, Lutris / Bottles / Steam prefixes);
- "is the game open?": the collector only reads the Windows process list; here /proc is read for a Wine Game.exe;
- UI scale: MXL_UI_SCALE=<factor> (1 = 100 %), or "auto" for Tk's own detection. Default under Wayland: 1, because
  the compositor already scales XWayland windows and Tk 9 would scale a second time from Xft.dpi;
- first window size: never larger than the screen (a floating window on a tiling WM takes the requested size)."""
import atexit, glob, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def find_save_dir():
    home = os.path.expanduser('~')
    prefixes = [os.environ.get('WINEPREFIX'), os.path.join(home, '.wine')]
    for pat in ('Games/*', '.local/share/bottles/bottles/*', '.var/app/com.usebottles.bottles/data/bottles/bottles/*',
                '.local/share/lutris/runners/wine/prefixes/*', '.steam/steam/steamapps/compatdata/*/pfx',
                '.local/share/Steam/steamapps/compatdata/*/pfx'):
        prefixes += sorted(glob.glob(os.path.join(home, pat)))
    for p in prefixes:
        if not p:
            continue
        found = sorted(glob.glob(os.path.join(p, 'drive_c', 'users', '*', 'AppData', 'Roaming', 'MedianXL', 'save')))
        found = [f for f in found if os.path.isdir(f)]
        if found:
            return found[0]
    return None


def _arg0(pid):
    with open(f'/proc/{pid}/cmdline', 'rb') as f:
        return f.read().split(b'\0')[0].decode('utf-8', 'replace')


def linux_processes():
    """[(exe name, pid)] of the running processes: a Wine process is listed under its Windows exe name (Game.exe)."""
    out = []
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            arg0 = _arg0(pid)
        except OSError:
            continue
        if arg0:
            out.append((arg0.replace('\\', '/').rsplit('/', 1)[-1], int(pid)))
    return out


def linux_process_path(pid):
    """Unix path of a process's exe, or None when it cannot be told (the collector then blocks the write: caution).
    A Wine process started with a Windows path (C:\\...\\Game.exe) is looked up in its working folder."""
    try:
        arg0 = _arg0(pid)
        if arg0.startswith('/'):
            return os.path.realpath(arg0)
        cwd = os.path.realpath(f'/proc/{pid}/cwd')
        base = arg0.replace('\\', '/').rsplit('/', 1)[-1].lower()
        for name in os.listdir(cwd):
            if name.lower() == base:
                return os.path.join(cwd, name)
    except OSError:
        pass
    return None


def patch_game_check():
    """mxl_game.running_game(game_dir) refuses writes while the game is open; give it Linux process readers."""
    import mxl_game
    mxl_game.running_processes = linux_processes
    mxl_game.process_path = linux_process_path


def setup_env():
    data = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    os.environ.setdefault('LOCALAPPDATA', data)
    if not os.environ.get('MXL_SAVE_DIR'):
        save = find_save_dir()
        if save:
            os.environ['MXL_SAVE_DIR'] = save


def setup_scaling():
    """Tk 9 sizes fonts and widgets from `xrdb -query | grep Xft.dpi` when it starts (tk9.0/scaling.tcl). The only
    way to choose another scale before any widget exists is to answer that query: a one-line xrdb in front of PATH."""
    want = os.environ.get('MXL_UI_SCALE', '').strip().lower()
    if want == 'auto' or (not want and not os.environ.get('WAYLAND_DISPLAY')):
        return
    try:
        scale = min(4.0, max(0.5, float(want))) if want else 1.0
    except ValueError:
        scale = 1.0
    shim = tempfile.mkdtemp(prefix='capybara-scale-')
    atexit.register(shutil.rmtree, shim, True)
    with open(os.path.join(shim, 'xrdb'), 'w') as f:
        f.write('#!/bin/sh\nprintf \'Xft.dpi:\\t%s\\n\' {}\n'.format(round(96 * scale)))
    os.chmod(os.path.join(shim, 'xrdb'), 0o755)
    os.environ['PATH'] = shim + os.pathsep + os.environ.get('PATH', '')


def fit_to_screen():
    """The main window asks for the size of its content, which can exceed the screen. Just before the event loop
    starts, a window larger than the screen is cut down to it and centred (once: later resizes are the user's)."""
    import tkinter
    loop = tkinter.Misc.mainloop
    done = []

    def mainloop(self, n=0):
        if not done:
            done.append(1)
            try:
                root = self.winfo_toplevel()
                root.update_idletasks()
                sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
                w, h = root.winfo_reqwidth(), root.winfo_reqheight()
                mw, mh = int(sw * 0.86), int(sh * 0.86)
                if w > mw or h > mh:
                    w, h = min(w, mw), min(h, mh)
                    root.geometry(f'{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}')
            except Exception as e:                      # never keeps the editor from starting
                print('fit_to_screen:', e)
        return loop(self, n)
    tkinter.Misc.mainloop = mainloop


def main():
    setup_env()
    setup_scaling()
    import mxl_userdir
    mxl_userdir.setup()
    import mxl_splash
    if mxl_splash.FLAG_ARG in sys.argv:
        mxl_splash.main()
        return
    mxl_splash.start()
    patch_game_check()
    fit_to_screen()
    import mxl_creator_gui
    mxl_creator_gui.run()


if __name__ == '__main__':
    main()
