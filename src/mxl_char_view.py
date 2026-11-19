"""The animated character (mxl_char_render) on the Character tab's Stats page, dark look only: placed in the free
margin left of the in-game stat screen, hidden when the margin is too narrow (800x600 keeps the stat screen as it
was). The animation runs only while the canvas is viewable: a hidden tab costs no CPU (the loop stops, a <Map>
of the window restarts it). Decoding runs in a thread; Tk images are made on the main thread."""
import threading
import tkinter as tk

PAD = 6


class CharView:
    def __init__(self, win, art):
        self.win = win
        self.art = art
        scr = win.statscreen
        self.host = scr.frame
        self.cv = tk.Canvas(self.host, bg='#000000', highlightthickness=0, bd=0, width=1, height=1)
        self._img = self.cv.create_image(0, 0, anchor='nw')
        self.anim = None            # mxl_char_render.Anim
        self.photos = []            # Tk images of the frames at the current scale
        self.scale = 0
        self.index = 0
        self._job = None
        self._busy = False
        self._key = None
        self.shown = False
        self.host.bind('<Configure>', lambda e: self.place(), add='+')
        scr.cv.bind('<Configure>', lambda e: self.place(), add='+')
        self.cv.winfo_toplevel().bind('<Map>', lambda e: self.wake(), add='+')
        self.load()

    # ---- data
    def _wanted(self):
        import mxl_char_render as R
        ch = self.win.ch
        return ch.cls, tuple(sorted(R.gear_of(ch).items()))

    def load(self):
        """Renders the character again when class or gear changed (in a thread)."""
        try:
            key = self._wanted()
        except Exception:
            return
        if key == self._key or self._busy:
            return
        self._key = key
        self._busy = True
        folder = self.win.data.folder
        art = self.art
        out = {}

        def work():
            try:
                import mxl_char_render as R
                out['anim'] = R.render(art, folder, key[0], dict(key[1]))
            except Exception as e:
                print('character render disabled:', e)
                out['anim'] = None
            out['done'] = True
        threading.Thread(target=work, daemon=True).start()

        def poll():
            if not out.get('done'):
                try:
                    self.cv.after(50, poll)
                except tk.TclError:
                    pass
                return
            self._busy = False
            self.anim = out['anim']
            self.photos = []
            self.scale = 0
            self.index = 0
            self.place()
        try:
            self.cv.after(50, poll)
        except tk.TclError:
            self._busy = False

    # ---- layout
    def place(self):
        try:
            a = self.anim
            W, H = self.host.winfo_width(), self.host.winfo_height()
            cw = self.win.statscreen.cv.winfo_width()
            margin = (W - cw) // 2                  # the stat screen is centred
            scale = 0
            if a is not None and W > 1:
                w, h = a.size
                for s in (3, 2, 1):
                    if margin >= w * s + 2 * PAD and H >= h * s + 2 * PAD:
                        scale = s
                        break
            if not scale:
                self.cv.place_forget()
                self.shown = False
                return
            if scale != self.scale:
                from PIL import Image, ImageTk
                self.photos = [ImageTk.PhotoImage(f.resize((f.width * scale, f.height * scale), Image.NEAREST))
                               for f in a.frames]
                self.scale = scale
            w, h = a.size[0] * scale, a.size[1] * scale
            self.cv.configure(width=w, height=h)
            self.cv.place(x=max(PAD, (margin - w) // 2), y=max(PAD, (H - h) // 2))
            self.shown = True
            self.cv.itemconfigure(self._img, image=self.photos[self.index % len(self.photos)])
            self.wake()
        except tk.TclError:
            pass

    # ---- animation
    def wake(self):
        if self._job is None and self.shown:
            try:
                if self.cv.winfo_viewable():
                    self._tick()
            except tk.TclError:
                pass

    def _tick(self):
        self._job = None
        try:
            if not self.shown or not self.photos or not self.cv.winfo_viewable():
                return                               # hidden: stop; <Map> restarts
            self.index = (self.index + 1) % len(self.photos)
            self.cv.itemconfigure(self._img, image=self.photos[self.index])
            if self.index == 0:
                self.load()                          # gear changed on the Inventory page: render again
            self._job = self.cv.after(max(20, int(1000 / self.anim.fps)), self._tick)
        except tk.TclError:
            self._job = None


def install():
    import os
    import mxl_char_gui
    if os.environ.get('MXL_CHAR_RENDER', '1') == '0':      # off: no animated character (and no animation timer)
        return
    W = mxl_char_gui.CharacterWindow
    if getattr(W, '_capy_char_view', False):
        return
    orig = W._build_progress

    def _build_progress(self, *a, **kw):
        r = orig(self, *a, **kw)
        try:
            scr = getattr(self, 'statscreen', None)
            art = getattr(scr, 'art', None) if scr is not None else None
            if art is not None:                      # dark look with the game's art only
                self.char_view = CharView(self, art)
        except Exception as e:                       # never keeps the window from opening
            print('character view disabled:', e)
        return r
    W._build_progress = _build_progress
    W._capy_char_view = True
