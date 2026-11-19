"""The animated character (mxl_char_render) on the Character tab's Stats page, dark look only. In the split layout
(StatScreen.split: the two pages at the left and right edges) it is a SCENE filling the space between the pages: a
background (set_background(scene): a mxl_scene town map, else plain dark ground) with its own animated sprites, the
character in front of it. Otherwise it sits in the free margin left of the centred stat screen, hidden when the
margin is too narrow (800x600 keeps the stat screen as it was). The animation runs only while the canvas is viewable: a hidden tab costs no CPU (the loop stops, a <Map>
of the window restarts it). Decoding runs in a thread; Tk images are made on the main thread."""
import threading
import time
import tkinter as tk

PAD = 6
GROUND = '#0d0b08'          # the scene without a background
TURN = (4, 0, 5, 1, 6, 2, 7, 3)  # the game's directions clockwise from the front (S, SW, W, NW, N, NE, E, SE)


class CharView:
    def __init__(self, win, art):
        self.win = win
        self.art = art
        scr = win.statscreen
        self.host = scr.frame
        self.cv = tk.Canvas(self.host, bg='#000000', highlightthickness=0, bd=0, width=1, height=1)
        self._bg = self.cv.create_image(0, 0, anchor='nw')
        self._img = self.cv.create_image(0, 0, anchor='nw')
        self.direction = 0          # index in TURN: left click on the character turns it left, right click right
        self.cv.tag_bind(self._img, '<Button-1>', lambda e: self.turn(1))
        self.cv.tag_bind(self._img, '<Button-3>', lambda e: self.turn(-1))
        self.scene = None           # the background: object with .base (PIL), .sprites [{pos, frames, fps}], .anchor
        self._scene_auto = True     # True: made here by mxl_scene (when importable) for the size of the room
        self._scene_mod = None      # mxl_scene, False when it cannot be imported (tried once)
        self._scene_key = None
        self._scene_busy = False
        self._bg_photo = None
        self._sprites = []          # [(canvas item, [Tk images], fps)]
        self.box = None             # split layout: (x, y, w, h) of the scene in the host frame
        self.anim = None            # mxl_char_render.Anim
        self.photos = []            # Tk images of the frames at the current scale
        self.scale = 0
        self.index = 0
        self._job = None
        self._busy = False
        self._key = None
        self.shown = False
        self._place_job = None
        self.host.bind('<Configure>', lambda e: self.place_later(), add='+')
        self.host.bind('<Map>', lambda e: self.place_later(), add='+')
        scr.cv.bind('<Configure>', lambda e: self.place_later(), add='+')
        self.host.bind('<<ScenePlaced>>', lambda e: self.place_later(), add='+')
        self.cv.winfo_toplevel().bind('<Map>', lambda e: self.wake(), add='+')
        self.load()

    # ---- data
    def _wanted(self):
        import mxl_char_render as R
        ch = self.win.ch
        return ch.cls, tuple(sorted(R.gear_of(ch).items())), TURN[self.direction % len(TURN)]

    def turn(self, step):
        """Turns the character by one of the 8 directions and renders it again."""
        self.direction = (self.direction + step) % len(TURN)
        self.load()

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
                out['anim'] = R.render(art, folder, key[0], dict(key[1]), direction=key[2])
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

    # ---- background (hook for the town map)
    def set_background(self, scene):
        """The scene behind the character: an object with .base (PIL image, the room's size or scaled to it),
        .sprites ([{'pos': (x, y), 'frames': [PIL images], 'fps': n}], positions in .base pixels) and .anchor
        ((x, y) in .base pixels: where the character's feet stand; None: centred). None: plain dark ground.
        Setting one by hand stops the automatic mxl_scene background."""
        self._scene_auto = False
        self._set_scene(scene)

    def _set_scene(self, scene):
        self.scene = scene
        self._bg_photo = None
        for item, _ph, _fps in self._sprites:
            self.cv.delete(item)
        self._sprites = []
        self.place()

    def _act(self):
        """The act of the town behind the character (the save's current act when the window knows it)."""
        for name in ('scene_act', 'act'):
            v = getattr(self.win, name, None)
            if isinstance(v, int) and 1 <= v <= 5:
                return v
        return save_act(getattr(self.win, 'ch', None))

    def _auto_scene(self, size):
        """mxl_scene.scene(art, data_folder, act, size) in a thread when the module exists; else dark ground."""
        if not self._scene_auto or self._scene_busy:
            return
        key = (self._act(), size)
        if key == self._scene_key:
            return
        if self._scene_mod is None:
            try:
                import mxl_scene
                self._scene_mod = mxl_scene
            except Exception:
                self._scene_mod = False
        mxl_scene = self._scene_mod
        if not mxl_scene:
            return                                   # no town map (yet): plain dark ground
        self._scene_key = key
        self._scene_busy = True
        out = {}
        art, folder = self.art, self.win.data.folder

        def work():
            try:
                sc = mxl_scene.scene(art, folder, key[0], size)
                if sc is not None:
                    try:                             # the town's NPCs (Akara, Kashya...) as extra sprites
                        import mxl_npcs
                        sc = _WithNpcs(sc, mxl_npcs.add_npcs(sc, art, folder, key[0]))
                    except Exception as e:
                        print('town NPCs left out:', e)
                out['scene'] = sc
            except Exception as e:
                print('scene disabled:', e)
                out['scene'] = None
            out['done'] = True
        threading.Thread(target=work, daemon=True).start()

        def poll():
            if not out.get('done'):
                try:
                    self.cv.after(50, poll)
                except tk.TclError:
                    pass
                return
            self._scene_busy = False
            if self._scene_auto:
                self.scene = out['scene']
                self._bg_photo = None
                for item, _ph, _fps in self._sprites:
                    self.cv.delete(item)
                self._sprites = []
                self.place()
        try:
            self.cv.after(50, poll)
        except tk.TclError:
            self._scene_busy = False

    def _draw_scene(self, w, h):
        """The background and its sprites for a room of w x h: the base scaled to cover it, centred."""
        sc = self.scene
        base = getattr(sc, 'base', None)
        if base is None:
            self.cv.itemconfigure(self._bg, image='', state='hidden')
            return 1.0, 0, 0
        from PIL import Image, ImageTk
        f = max(w / base.width, h / base.height)
        bw, bh = max(1, round(base.width * f)), max(1, round(base.height * f))
        ox, oy = (w - bw) // 2, (h - bh) // 2
        if self._bg_photo is None or self._bg_photo[0] != (w, h):
            img = base if (bw, bh) == base.size else base.resize((bw, bh), Image.NEAREST if f >= 1 else Image.LANCZOS)
            self._bg_photo = ((w, h), ImageTk.PhotoImage(img, master=self.cv))
            for item, _ph, _fps in self._sprites:
                self.cv.delete(item)
            self._sprites = []
            for sp in getattr(sc, 'sprites', None) or ():
                frames = sp.get('frames') or []
                if not frames:
                    continue
                phs = [ImageTk.PhotoImage(fr.resize((max(1, round(fr.width * f)), max(1, round(fr.height * f))),
                                                    Image.NEAREST), master=self.cv) for fr in frames]
                x, y = sp.get('pos', (0, 0))
                item = self.cv.create_image(ox + x * f, oy + y * f, anchor='nw', image=phs[0])
                self._sprites.append((item, phs, float(sp.get('fps') or 10)))
            self.cv.tag_raise(self._img)
        self.cv.coords(self._bg, ox, oy)
        self.cv.itemconfigure(self._bg, image=self._bg_photo[1], state='normal')
        return f, ox, oy

    def _step_sprites(self):
        t = time.monotonic()
        for item, phs, fps in self._sprites:
            self.cv.itemconfigure(item, image=phs[int(t * fps) % len(phs)])

    # ---- layout
    def _scale_for(self, room_w, room_h):
        a = self.anim
        if a is None:
            return 0
        w, h = a.size
        for s in (3, 2, 1):
            if room_w >= w * s + 2 * PAD and room_h >= h * s + 2 * PAD:
                return s
        return 0

    def _photos_at(self, scale):
        if scale != self.scale:
            from PIL import Image, ImageTk
            self.photos = [ImageTk.PhotoImage(f.resize((f.width * scale, f.height * scale), Image.NEAREST))
                           for f in self.anim.frames]
            self.scale = scale

    def place_later(self):
        """place() once the pending geometry changes are done (sizes read at a <Configure> can be stale ones)."""
        if self._place_job is None:
            try:
                self._place_job = self.cv.after_idle(self._place_now)
            except tk.TclError:
                pass

    def _place_now(self):
        self._place_job = None
        self.place()

    def place(self):
        try:
            scr = self.win.statscreen
            box = scr.scene_box() if getattr(scr, 'split', False) else None
            if box is not None:
                return self._place_scene(scr, box)
            self.box = None
            self.cv.itemconfigure(self._bg, state='hidden')
            for item, _ph, _fps in self._sprites:
                self.cv.itemconfigure(item, state='hidden')
            a = self.anim
            W, H = self.host.winfo_width(), self.host.winfo_height()
            cw = int(scr.cv.cget('width'))          # (asked for: winfo_width may still be the old one)
            margin = (W - cw) // 2                  # the stat screen is centred
            scale = self._scale_for(margin, H) if W > 1 else 0
            if not scale:
                self.cv.place_forget()
                self.shown = False
                self.load()                          # no animation loop runs now: still follow a character change
                return
            self._photos_at(scale)
            w, h = a.size[0] * scale, a.size[1] * scale
            self.cv.configure(width=w, height=h, bg='#000000')
            self.cv.coords(self._img, 0, 0)
            # image first (in the same call): the item's old image may be gone with the old photos
            self.cv.itemconfigure(self._img, image=self.photos[self.index % len(self.photos)], anchor='nw')
            self.cv.place(x=max(PAD, (margin - w) // 2), y=max(PAD, (H - h) // 2))
            self.shown = True
            self.wake()
        except tk.TclError:
            pass

    def _place_scene(self, scr, box):
        """The split layout: the canvas fills the room between the pages; the character stands in front of the
        background, centred (or on the scene's anchor)."""
        x, y, w, h = box
        x += scr.cv.winfo_x()
        y += scr.cv.winfo_y()
        if w < 2 or h < 2:
            self.cv.place_forget()
            self.shown = False
            return
        self.box = (x, y, w, h)
        self.cv.configure(width=w, height=h, bg=GROUND)
        self.cv.place(x=x, y=y)
        try:
            room = (int(scr.cv.cget('width')) - 2 * round(512 * scr.k), h)   # both pages at their edges
        except (tk.TclError, ValueError):
            room = (w, h)
        zoom = 2 if room[1] >= 560 else 1           # the town and the character share one pixel scale
        self._auto_scene((max(1, room[0] // zoom), max(1, room[1] // zoom)))
        f, ox, oy = self._draw_scene(w, h)
        for item, _ph, _fps in self._sprites:
            self.cv.itemconfigure(item, state='normal')
        self.shown = True
        if getattr(self.scene, 'base', None) is not None and self.anim is not None:
            scale = max(1, int(round(f)))           # the same scale as the town behind it
        else:
            scale = self._scale_for(w, h)
        if not scale:
            self.cv.itemconfigure(self._img, image='')
            self.photos, self.scale = [], 0
            self.load()
            self.wake()
            return
        self._photos_at(scale)
        anchor = getattr(self.scene, 'anchor', None) if getattr(self.scene, 'base', None) is not None else None
        if anchor:
            cx, cy, where = ox + anchor[0] * f, oy + anchor[1] * f, 's'
        else:
            cx, cy, where = w // 2, h // 2, 'center'
        self.cv.coords(self._img, round(cx), round(cy))
        self.cv.itemconfigure(self._img, image=self.photos[self.index % len(self.photos)], anchor=where)
        self.wake()

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
            if not self.shown or not (self.photos or self._sprites) or not self.cv.winfo_viewable():
                return                               # hidden: stop; <Map> restarts
            if self._sprites:
                self._step_sprites()
            fps = 12.0
            if self.photos and self.scale:
                self.index = (self.index + 1) % len(self.photos)
                self.cv.itemconfigure(self._img, image=self.photos[self.index])
                if self.index == 0:
                    self.load()                      # gear changed on the Inventory page: render again
                fps = self.anim.fps
            if self._sprites:
                fps = max([fps] + [s[2] for s in self._sprites])
            self._job = self.cv.after(max(20, int(1000 / fps)), self._tick)
        except tk.TclError:
            self._job = None


class _WithNpcs:
    """A scene with the NPCs added to its sprites (the cached Scene itself stays as it is)."""
    def __init__(self, scene, sprites):
        self._scene, self.sprites = scene, sprites

    def __getattr__(self, name):
        return getattr(self._scene, name)


def save_act(ch):
    """The act the character was last in (1-5): header 0xA8-0xAA, one byte per difficulty, bit 7 = the difficulty
    last played, low 3 bits = its act (0-4). 1 when unknown."""
    try:
        for b in ch.head[0xA8:0xAB]:
            if b & 0x80:
                return min((b & 7) + 1, 5)
    except Exception:
        pass
    return 1


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
