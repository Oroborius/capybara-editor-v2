"""Game artwork for the "D2 look" (Median XL Sigma's own panels, buttons and fonts), read from the player's
installed game files (MPQ archives) - nothing of the game is shipped in the editor.

- Panels / gear frames / buttons: data\\global\\themes\\<theme>\\game\\... (Median XL Sigma themes: tartarus, classic_sigma)
- Fonts: data\\local\\font\\latin\\<font>.dc6 + .tbl (fontexocet10, font16, font30...)
- Palette: data\\global\\palette\\ACT1\\pal.dat
Images are decoded once (DC6, mxl_d2ui_dc6) and kept as PNG in <user dir>/ui_art/<theme>/; a brightness curve
(gamma) brings them to what the game shows on screen."""
import glob
import os
import struct

import mxl_d2ui_dc6 as DC6

THEMES = ('tartarus', 'classic_sigma')
GAMMA = 0.6                 # in-game brightness (measured on a screenshot: raw palette colours ^0.6)
GOLD = (199, 179, 119)      # D2 gold text
WHITE = (230, 230, 230)
_ART = {}


def get_art(game_dir, theme, cache_root):
    key = (game_dir, theme, cache_root)
    if key not in _ART:
        _ART[key] = Art(game_dir, theme, cache_root)
    return _ART[key]


def skill_web(self, code, tab, size):
        """The tree's connector web (the arrows between the skill nodes): the class's
        layout-<code>.dc6 holds 4 art frames per tree tab, in tab order; they tile into the
        tree-sized web, which the editor stretches over the stone panel under the nodes."""
        from PIL import Image

        def build():
            fr = DC6.dc6_frames(self._theme_file(f'skills\\layout-{code}.dc6'))
            base = max(0, tab) * 4
            im = Image.new('RGBA', (512, 704))
            for ty in range(0, 704, 256):
                for tx in range(0, 512, 256):
                    for i in (base, base + 1, base + 2, base + 3):
                        if i >= len(fr):
                            continue
                        w, h, _ox, _oy, px, mask = fr[i]
                        if not any(mask[:w * h]):
                            continue
                        rw, rh, rgba = DC6.to_rgba(fr[i], self.pal())
                        t = Image.frombytes('RGBA', (rw, rh), bytes(rgba))
                        im.paste(t, (tx, ty), t)
            return im.width, im.height, im.tobytes()

        w, h = size
        return self._cached(f'web-{code}-{tab}-{w}x{h}', build)


def warm(game_dir, cache_root):
    """Pre-read the art the editor shows, in the background: opening every MPQ costs ~0.8s and
    some strips are stored implode-compressed, which the pure-python decompressor needs ~0.6s
    per file - the first picture would otherwise freeze the UI for that. Everything lands in the
    ui_art cache, so the main thread only reads small files afterwards."""
    try:
        art = get_art(game_dir, THEMES[0], cache_root)
        art.pal()
        for rel in ('skills\\icons-ama', 'skills\\icons-sor', 'skills\\icons-nec',
                    'skills\\icons-pal', 'skills\\icons-bar', 'skills\\icons-dru',
                    'skills\\icons-ass', 'skills\\icons-shared'):
            try:
                art._theme_file(rel + '.dc6')
            except Exception:
                pass
        art.char_panel_d2()                          # the character screen's paperdoll panel
        for p in ('stash', 'character-inventory'):
            try:
                art.panel(p)
            except Exception:
                pass
        for f in ('font16', 'font30'):
            try:
                art.font(f)
            except Exception:
                pass
    except Exception:
        pass


class ArtError(Exception):
    pass


class Art:
    def __init__(self, game_dir, theme, cache_root):
        self.game_dir = game_dir
        self.theme = theme if theme in THEMES else THEMES[0]
        self.cache = os.path.join(cache_root, self.theme)
        self._mpqs = None
        self._base_mpqs = None
        self._pal = None
        self._lut = [min(255, round(255 * (v / 255) ** GAMMA)) for v in range(256)]
        self._fonts = {}
        self.stamp()

    # ---- game files
    def stamp(self):
        """Cache tied to the game version: a new Median XL version re-extracts everything."""
        try:
            st = os.stat(os.path.join(self.game_dir, 'medianxl-version.mpq'))
            stamp = f'{st.st_size}-{int(st.st_mtime)}-{GAMMA}'
        except OSError:
            stamp = 'none'
        os.makedirs(self.cache, exist_ok=True)
        p = os.path.join(self.cache, 'stamp.txt')
        try:
            old = open(p).read()
        except OSError:
            old = None
        if old != stamp:
            for f in glob.glob(os.path.join(self.cache, '*.png')):
                try:
                    os.remove(f)
                except OSError:
                    pass
            import shutil
            shutil.rmtree(os.path.join(self.cache, 'raw'), ignore_errors=True)
            with open(p, 'w') as fh:
                fh.write(stamp)

    def mpqs(self):
        if self._mpqs is None:
            from mpq import MPQ
            names = sorted(glob.glob(os.path.join(self.game_dir, 'medianxl-*.mpq')))
            names += [os.path.join(self.game_dir, n) for n in ('patch_d2.mpq', 'd2exp.mpq', 'd2data.mpq')]
            self._mpqs = []
            for n in names:
                if os.path.exists(n):
                    try:
                        self._mpqs.append(MPQ(n))
                    except Exception:
                        pass
        return self._mpqs

    def _raw_path(self, name):
        """Cache file for one archive member: the implode strips need ~0.6s each with the
        pure-python decompressor, so they are kept as plain bytes after the first read."""
        import hashlib
        d = os.path.join(self.cache, 'raw')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, hashlib.sha1(name.lower().encode('utf-8', 'replace')).hexdigest() + '.bin')

    def _read_raw(self, name, archives):
        p = self._raw_path(name)
        try:
            return open(p, 'rb').read()
        except OSError:
            pass
        for m in archives():
            try:
                if m.find(name) is None:
                    continue
                data = m.read(name)
            except Exception:
                continue
            if data:
                tmp = f'{p}.{os.getpid()}.tmp'
                try:
                    with open(tmp, 'wb') as fh:
                        fh.write(data)
                    os.replace(tmp, p)
                except OSError:
                    pass
                return data
        raise ArtError(f'{name} not found in the game files ({self.game_dir})')

    def read(self, name):
        return self._read_raw(name, self.mpqs)

    def base_mpqs(self):
        """The base game's own archives only (never the Sigma mod's): patch_d2, d2exp, d2data."""
        if self._base_mpqs is None:
            from mpq import MPQ
            self._base_mpqs = []
            for n in ('patch_d2.mpq', 'd2exp.mpq', 'd2data.mpq'):
                p = os.path.join(self.game_dir, n)
                if os.path.exists(p):
                    try:
                        self._base_mpqs.append(MPQ(p))
                    except Exception:
                        pass
        return self._base_mpqs

    def read_base(self, name):
        """A base-game file, so the standard Diablo II graphics win over anything a theme ships."""
        return self._read_raw(name, self.base_mpqs)

    def pal(self):
        if self._pal is None:
            self._pal = DC6.palette(self.read('data\\global\\palette\\ACT1\\pal.dat'))
        return self._pal

    def _theme_file(self, rel):
        for t in (self.theme,) + tuple(x for x in THEMES if x != self.theme):
            name = f'data\\global\\themes\\{t}\\game\\{rel}'
            try:
                return self.read(name)
            except ArtError:
                continue
        raise ArtError(rel)

    # ---- images (PNG paths in the cache)
    def _cached(self, key, build):
        path = os.path.join(self.cache, key + '.png')
        if not os.path.exists(path):
            w, h, rgba = build()
            rgba = self._bright(rgba)
            tmp = f'{path}.{os.getpid()}.tmp'
            with open(tmp, 'wb') as fh:
                fh.write(DC6.png(w, h, rgba))
            os.replace(tmp, path)
        return path

    def _bright(self, rgba):
        lut = self._lut
        out = bytearray(rgba)
        for i in range(0, len(out), 4):
            if out[i + 3]:
                out[i] = lut[out[i]]
                out[i + 1] = lut[out[i + 1]]
                out[i + 2] = lut[out[i + 2]]
        return out

    def panel(self, name, variant=0):
        """A 512x704 game panel (stash, character-inventory, stat-screen...): 6 tiles of 256 px, 2 per row."""
        def build():
            fr = DC6.dc6_frames(self._theme_file(f'panels\\{name}.dc6'))
            return DC6.compose(fr[variant * 6:variant * 6 + 6], self.pal(), 2)
        return self._cached(f'panel-{name}-{variant}', build)

    def panel_variants(self, name):
        """How many 512x704 pages a panel DC6 holds (the stat screen has one per page)."""
        return len(DC6.dc6_frames(self._theme_file(f'panels\\{name}.dc6'))) // 6

    def base_frame(self, name, index):
        """One frame of a base-game panel DC6 (data\\global\\ui\\PANEL\\...), e.g. the gold button."""
        def build():
            fr = DC6.dc6_frames(self.read_base(f'data\\global\\ui\\PANEL\\{name}'))
            return DC6.to_rgba(fr[index], self.pal())
        return self._cached(f'base-{name}-{index}', build)

    def char_panel_d2(self):
        """The standard Diablo II character screen (base-game art, not the mod's themes): the paperdoll with
        every equipment box and the I / II weapon-set tabs over stone, scaled x1.6 to the editor's 512 x 704
        panel size and extended with plain stone below (the 15 x 10 inventory grid is drawn over that)."""
        def build():
            from PIL import Image
            fr = DC6.dc6_frames(self.read_base('data\\global\\ui\\PANEL\\invchar6.dc6'))
            w, h, rgba = DC6.compose(fr[4:8], self.pal(), 2)      # 320 x 432: the inventory / paperdoll screen
            im = Image.frombytes('RGBA', (w, h), bytes(rgba))
            out = Image.new('RGBA', (512, 704))
            out.paste(im.crop((0, 0, 320, 250)).resize((512, 400), Image.LANCZOS), (0, 0))
            patch = im.crop((200, 374, 314, 428)).resize((182, 86), Image.LANCZOS)   # clean stone (right of
            y = 400                                    # the game's own gold row), mirror-tiled: no seams
            while y < 704:
                h = min(86, 704 - y)
                x = 0
                while x < 512:
                    t = patch
                    if (y - 400) // 86 % 2:
                        t = t.transpose(Image.FLIP_TOP_BOTTOM)
                    if x // 182 % 2:
                        t = t.transpose(Image.FLIP_LEFT_RIGHT)
                    out.paste(t.crop((0, 0, min(182, 512 - x), h)), (x, y))
                    x += 182
                y += 86
            return out.width, out.height, out.tobytes()
        return self._cached('panel-d2-character', build)

    def frame(self, rel, index):
        """One frame of a theme DC6 (rel: e.g. 'panel-elements\\inventory-gear')."""
        def build():
            fr = DC6.dc6_frames(self._theme_file(rel + '.dc6'))
            return DC6.to_rgba(fr[index], self.pal())
        return self._cached(rel.replace('\\', '-') + f'-{index}', build)

    def menu_frame(self, rel, index):
        """Frame of a theme menu DC6 (rel: e.g. 'buttons\\short-btn'): data\\global\\themes\\<t>\\menus\\..."""
        def build():
            data = None
            for t in (self.theme,) + tuple(x for x in THEMES if x != self.theme):
                try:
                    data = self.read(f'data\\global\\themes\\{t}\\menus\\{rel}.dc6')
                    break
                except ArtError:
                    continue
            if data is None:
                raise ArtError(rel)
            return DC6.to_rgba(DC6.dc6_frames(data)[index], self.pal())
        return self._cached('menu-' + rel.replace('\\', '-') + f'-{index}', build)

    # ---- game fonts
    def font(self, name):
        if name not in self._fonts:
            base = f'data\\local\\font\\latin\\{name}'
            tbl = self.read(base + '.tbl')
            frames = DC6.dc6_frames(self.read(base + '.dc6'))
            glyphs = {}
            line_h = tbl[9] if len(tbl) > 9 else 16
            for i in range((len(tbl) - 12) // 14):
                code, _u, w, h, _u2, _u3, fidx = struct.unpack_from('<HBBBBHH', tbl, 12 + i * 14)
                if fidx < len(frames):
                    glyphs[code] = (w, h, frames[fidx])
            self._fonts[name] = (glyphs, line_h)
        return self._fonts[name]

    @staticmethod
    def _solid(img, W, H, color):
        """Every glyph pixel in color, a 1 px dark outline around: (image, W + 2, H + 2)."""
        on0 = [img[i * 4 + 3] > 0 for i in range(W * H)]
        W, H = W + 2, H + 2
        on = [0 < x < W - 1 and 0 < y < H - 1 and on0[(y - 1) * (W - 2) + x - 1] for y in range(H) for x in range(W)]
        out = bytearray(W * H * 4)
        for y in range(H):
            for x in range(W):
                j = (y * W + x) * 4
                if on[y * W + x]:
                    out[j:j + 4] = bytes((*color, 255))
                elif any(0 <= x + dx < W and 0 <= y + dy < H and on[(y + dy) * W + x + dx]
                         for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                    out[j:j + 4] = bytes((12, 8, 4, 230))
        return out, W, H

    def text(self, s, font='fontexocet10', color=GOLD, solid=False):
        """The text drawn with a game font (PNG path); solid: one flat colour with a dark outline (easier to read)."""
        key = ('txt2s-' if solid else 'txt2-') + '%s-%02x%02x%02x-%s' % (font, *color, ''.join(c if c.isalnum() else '_%02x' % ord(c) for c in s)[:80])
        key += '-%08x' % (hash(s) & 0xFFFFFFFF) if len(s) > 40 else ''

        def build():
            glyphs, _lh = self.font(font)
            pal = self.pal()
            chars = [glyphs.get(ord(c)) or glyphs.get(ord('?')) for c in s]
            W = max(1, sum(g[0] for g in chars if g))
            top = max([g[2][1] - g[2][3] for g in chars if g] + [1])
            bottom = max([g[2][3] for g in chars if g] + [0])
            H = max(1, top + bottom)
            img = bytearray(W * H * 4)
            x = 0
            for g in chars:
                if not g:
                    continue
                adv, _h, fr = g
                fw, fh, ox, oy, px, mask = fr
                y0 = top - (fh - oy)
                for yy in range(fh):
                    ty = y0 + yy
                    if not 0 <= ty < H:
                        continue
                    for xx in range(fw):
                        tx = x + ox + xx
                        k = yy * fw + xx
                        if mask[k] and 0 <= tx < W:
                            r, gg, b = pal[px[k]]
                            v = max(r, gg, b)
                            j = (ty * W + tx) * 4
                            img[j:j + 4] = bytes((color[0] * v // 255, color[1] * v // 255, color[2] * v // 255, 255))
                x += adv
            if solid:
                img, W, H = self._solid(img, W, H, color)
            rows = [y for y in range(H) if any(img[(y * W + xx) * 4 + 3] for xx in range(W))]
            if rows:                                      # tight vertical box: centring places the text right
                y0, y1 = rows[0], rows[-1] + 1
                img = img[y0 * W * 4:y1 * W * 4]
                H = y1 - y0
            return W, H, img
        return self._cached(key, build)


Art.skill_web = skill_web        # written above the class (module level) and meant as its method
