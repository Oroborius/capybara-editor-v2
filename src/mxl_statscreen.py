"""The Character tab's Stats page drawn like the game's own character screen (Median XL Sigma stat-screen panel),
with the stored values editable in place.

Three parts:
- StatEditMixin: the editing controller of CharacterWindow. Every edit of a stat-screen value is an operation
  replayed on a scratch copy of the character (what the page shows) and, on SAVE, on the character itself
  through mxl_char's field engine. Used by the art page and by the grey Hero-Editor page alike.
- GameText: text in the game's own fonts (in memory, baseline kept), totals of the equipped items' stats.
- StatScreen: a canvas showing one 512 x 704 panel composed from the game art and scaled to the space of the
  tab. Pages: the game's page 1 (coordinates measured on game screenshots), "Total attributes" (sums of the
  equipped items' stats, read-only) and "Saved values" (the editor's own page: what the save stores and the game
  screen does not show). The arrow buttons walk the page list.
"""
import copy
import os
import struct
import tkinter as tk

import mxl_char as MC
from mxl_char import CharError
from mxl_lang import T

PANEL_W, PANEL_H = 512, 704
GOLD = (199, 179, 119)
WHITE = (230, 230, 230)
DIM = (128, 120, 104)            # values the game computes / the editor only sums
SUM = (150, 170, 200)            # the editor's own sums of item stats (not the game's final number)
RED = (255, 77, 77)
BLUE = (105, 105, 255)
YELLOW = (255, 255, 100)
GREEN = (0, 255, 0)
ORANGE = (240, 196, 23)
D2_COLORS = {0: WHITE, 1: RED, 2: GREEN, 3: BLUE, 4: GOLD, 5: (105, 105, 105), 6: (0, 0, 0), 7: (208, 194, 125),
             8: (255, 168, 0), 9: YELLOW, 10: (0, 128, 0), 11: (174, 0, 255), 12: (0, 200, 0)}
MIN_K = 0.8                      # below this the game fonts are unreadable: the page scrolls instead
MAX_K = 2.0
ATTRS = ('strength', 'dexterity', 'vitality', 'energy')
# stats that describe one item, not the character: left out of the totals
ITEM_LOCAL = frozenset({16, 17, 18, 72, 73, 75, 91, 92, 152, 194, 204, 252, 253, 372, 410, 411, 443, 497})
RES_IDS = {'fire_res': 39, 'light_res': 41, 'cold_res': 43, 'poison_res': 45, 'phys_res': 36, 'magic_res': 37}
ATTR_IDS = {'strength': 0, 'energy': 1, 'dexterity': 2, 'vitality': 3}
TEXT_KEYS = ('name', 'copy_as')


# ====================================================================================== controller
class StatEditMixin:
    """Stat-screen editing of CharacterWindow: operations on a scratch copy, applied to the character on SAVE."""

    # ------------------------------------------------------------------ state
    def st_reset(self):
        self.st_ops = []
        self.st_name = None
        self.st_rebuild()

    def st_rebuild(self):
        """The scratch character = the character as loaded + the pending operations."""
        ch = self.ch
        sim = copy.copy(ch)
        sim.head = bytearray(ch.head)
        sim.stats = [list(s) for s in ch.stats]
        kept = []
        for op in getattr(self, 'st_ops', []):
            try:
                self._st_apply(sim, op)
                kept.append(op)
            except CharError:
                pass                      # no longer possible on the reloaded character: dropped
        self.st_ops = kept
        self.st_sim = sim
        self._st_totals = None

    @staticmethod
    def _st_apply(target, op):
        kind = op[0]
        if kind == 'field':
            target.set_field(op[1], op[2])
        elif kind == 'levelup':
            target.set_level(op[1])
        elif kind == 'flag':
            target.set_flag(op[1], op[2])
        elif kind == 'done':
            target.set_difficulties_done(op[1])
        elif kind == 'prog':
            target.set_progression(op[1])
        elif kind == 'matchexp':
            target.match_exp_to_level()
        else:
            raise CharError(str(kind))

    def st_do(self, *op):
        """Applies one operation to the scratch character; False (and the reason in the status line) when the
        engine refuses it."""
        try:
            self._st_apply(self.st_sim, op)
        except CharError as e:
            self.set_bar(str(e), error=True)
            return False
        self.st_ops.append(op)
        self.st_changed()
        return True

    def st_commit(self, ch):
        """Replays the pending operations on the real character (raises CharError)."""
        for op in self.st_ops:
            self._st_apply(ch, op)

    def st_dirty(self):
        sim = getattr(self, 'st_sim', None)
        if sim is None:
            return False
        return bool(self.st_name) or bytes(sim.head) != bytes(self.ch.head) or sim.stats != self.ch.stats

    def st_changed(self):
        scr = getattr(self, 'statscreen', None)
        if scr is not None:
            scr.redraw()
        fn = getattr(self, '_refresh_stats_grey', None)
        if fn is not None and getattr(self, 'sv', None):
            fn()
        self.update_dirty()

    # ------------------------------------------------------------------ values
    def st_cls(self):
        p = getattr(self, 'pending_cls', None)
        return self.ch.cls if p is None else p

    def st_value(self, key):
        sim = self.st_sim
        if key == 'name':
            return self.st_name or self.ch.name
        if key == 'copy_as':
            return self.copy_name.get()
        if key == 'progression':
            return sim.progression
        if key == 'levelup':
            return sim.level
        return sim.field(key)

    def st_range(self, key):
        if key == 'progression':
            return 0, 255
        if key == 'levelup':
            return self.st_sim.level, MC.max_level(self.data, self.st_sim.cls)
        fd = self.st_sim.stat_field(key)
        return fd.min, fd.max

    def st_parse(self, key, text):
        """The typed text as a storable value: (value, None) or (None, message)."""
        text = str(text).strip()
        if key in TEXT_KEYS:
            if key == 'copy_as' and not text:
                return '', None
            try:
                MC.check_name(text)
            except CharError as e:
                return None, str(e)
            return text, None
        label = self.st_label(key)
        try:
            v = int(text.replace(',', '').replace(' ', '').replace(' ', ''))
        except ValueError:
            return None, T('ss.err.number', '{label}: a whole number is expected', label=label)
        lo, hi = self.st_range(key)
        if not lo <= v <= hi:
            return None, T('ss.err.range', '{label}: {lo} to {hi}', label=label, lo=lo, hi=hi)
        return v, None

    def st_label(self, key):
        if key == 'name':
            return T('he.name', 'Name')
        if key == 'copy_as':
            return T('he.copy_as', 'Copy as')
        if key == 'progression':
            return T('ss.progression', 'Progression')
        if key == 'levelup':
            return T('ss.levelup', 'Level up like the game')
        return self.st_sim.stat_field(key).label

    def st_set(self, key, text):
        """Commits a typed value. True when stored (or unchanged), False when refused (status line says why)."""
        v, err = self.st_parse(key, text)
        if err:
            self.set_bar(err, error=True)
            return False
        if key == 'name':
            if v == self.ch.name:
                self.st_name = None
            else:
                folder = os.path.dirname(self.ch.path)
                old = os.path.splitext(os.path.basename(self.ch.path))[0]
                if v.lower() != old.lower() and os.path.exists(os.path.join(folder, v + '.d2s')):
                    self.set_bar(T('ch.err.exists', '{name} already exists', name=v), error=True)
                    return False
                self.st_name = v
            self.st_changed()
            return True
        if key == 'copy_as':
            self.copy_name.set(v)
            self.st_changed()
            return True
        if v == self.st_value(key):
            return True
        if key == 'progression':
            return self.st_do('prog', v)
        if key == 'levelup':
            return self.st_do('levelup', v)
        return self.st_do('field', key, v)

    def st_plus(self, key, n=1, take=False, free=False, everything=False):
        """The + button of an attribute. Like the game: +n to the attribute, -n stat points (everything: all
        the points). free: the stat points are left alone. take: the reverse (a point back)."""
        sim = self.st_sim
        cur, pts = sim.field(key), sim.field('stat_points')
        lo, hi = self.st_range(key)
        plo, phi = self.st_range('stat_points')
        if take:
            n = min(n, cur - lo) if not everything else cur - lo
            if not free:
                n = min(n, phi - pts)
            if n <= 0:
                return False
            ok = self.st_do('field', key, cur - n)
            if ok and not free:
                self.st_do('field', 'stat_points', pts + n)
            return ok
        if not free:
            if pts <= 0:
                self.set_bar(T('ss.no_points', 'No stat points left: Alt+click adds a point anyway, or type the value.'))
                return False
            n = pts if everything else min(n, pts)
        n = min(n, hi - cur)
        if n <= 0:
            return False
        ok = self.st_do('field', key, cur + n)
        if ok and not free:
            self.st_do('field', 'stat_points', pts - n)
        return ok

    def st_flag(self, key, on=None):
        cur = self.st_sim.flags()[key]
        return self.st_do('flag', key, (not cur) if on is None else bool(on))

    def st_done(self, n):
        return self.st_do('done', int(n))

    def st_match_exp(self):
        lo, hi = self.st_sim.exp_range()
        if lo <= self.st_sim.field('experience') <= hi:
            self.set_bar(T('ss.exp_ok', 'The experience already matches level {level}.', level=self.st_sim.level))
            return True
        return self.st_do('matchexp')

    def st_totals(self):
        if getattr(self, '_st_totals', None) is None or self._st_totals[0] is not self.ch.items:
            self._st_totals = (self.ch.items, gear_totals(self.ch, self.data))
        return self._st_totals[1]


# ====================================================================================== item sums
def gear_totals(ch, data):
    """Sums of the equipped items' stats (item + runeword + socketed, the active weapon set only).
    {'stats': {(id, param): stat dict with the summed value}, 'defense': int, 'items': n}."""
    out = {'stats': {}, 'defense': 0, 'items': 0, 'error': None}
    try:
        import mxl_tooltip
        active2 = struct.unpack_from('<I', ch.head, 0x10)[0] == 1
        skip = (4, 5) if active2 else (11, 12)
        for slot, e in sorted(ch.equipped().items()):
            if slot in skip:
                continue
            it = e.it
            out['items'] += 1
            ed = flat = 0
            for s in mxl_tooltip.all_stats(it, data):
                sid, val = s.get('id'), s.get('value')
                if not isinstance(val, int):
                    continue
                if sid == 16:
                    ed += val
                elif sid == 31:
                    flat += val
                if sid in ITEM_LOCAL:
                    continue
                k = (sid, s.get('param'))
                if k in out['stats']:
                    out['stats'][k]['value'] += val
                else:
                    out['stats'][k] = dict(s)
            base = it.get('defense') if 'defense' in it else None
            if isinstance(base, int):
                out['defense'] += base * (100 + ed) // 100
            out['defense'] += flat
    except Exception as e:                       # an item the host cannot describe: no sums rather than wrong ones
        out['error'] = str(e)
    return out


def total_of(tot, sid):
    return sum(s['value'] for (i, _p), s in tot['stats'].items() if i == sid)


def total_lines(tot, data, char=None):
    """[(colour, text)] of the summed stats, in the game's own wording and order (the tooltip code of the host)."""
    try:
        import mxl_tooltip
        stats = sorted(tot['stats'].values(), key=lambda s: (s['id'], s.get('param') or 0))
        return [(ln[0], mxl_tooltip.strip_colors(ln[1]) if '\xff' in str(ln[1]) else str(ln[1]))
                for ln in mxl_tooltip.stat_lines(stats, data, char)]
    except Exception as e:
        return [(1, str(e))]


# ====================================================================================== game fonts
class GameText:
    """Lines of text in the game's fonts as PIL images; the glyph cells keep the font's baseline, so captions
    and values sit on the same line whatever letters they hold."""

    def __init__(self, art):
        self.art = art
        self._fonts = {}
        self._lines = {}

    def _font(self, name):
        f = self._fonts.get(name)
        if f is None:
            glyphs, _lh = self.art.font(name)
            top = max([g[2][1] - g[2][3] for g in glyphs.values()] + [1])
            bottom = max([g[2][3] for g in glyphs.values()] + [0])
            f = self._fonts[name] = {'glyphs': glyphs, 'top': top, 'h': top + bottom, 'cells': {}, 'cap': None}
            ref = self._cell(f, ord('0')) or self._cell(f, ord('H'))
            box = ref[1].getbbox() if ref else None
            f['cap'] = (box[1] + box[3]) / 2 + ref[3] if box else f['h'] / 2
        return f

    def _cell(self, f, code):
        """(advance, 'L' image of the glyph's brightness, x offset, y offset in the line)."""
        if code in f['cells']:
            return f['cells'][code]
        from PIL import Image
        g = f['glyphs'].get(code) or f['glyphs'].get(ord('?'))
        cell = None
        if g:
            adv, _h, fr = g
            fw, fh, ox, oy, px, mask = fr
            pal = self.art.pal()
            buf = bytes((max(1, max(pal[px[i]])) if mask[i] else 0) for i in range(fw * fh))
            cell = (adv, Image.frombytes('L', (fw, fh), buf), ox, f['top'] - (fh - oy))
        f['cells'][code] = cell
        return cell

    def has(self, text, font):
        g = self._font(font)['glyphs']
        return all(ord(c) in g for c in text)

    def line(self, text, font='font16', color=WHITE):
        """(RGBA image trimmed to the ink sideways, y of the middle of a capital letter in it)."""
        key = (text, font, color)
        hit = self._lines.get(key)
        if hit is not None:
            return hit
        from PIL import Image
        f = self._font(font)
        cells = [c for c in (self._cell(f, ord(ch)) for ch in text) if c]
        W = max(1, sum(c[0] for c in cells) + 16)
        lum = Image.new('L', (W, f['h'] + 4), 0)
        x = 0
        for adv, im, ox, y0 in cells:
            lum.paste(im, (x + ox, y0), im.point(lambda v: 255 if v else 0))
            x += adv
        box = lum.getbbox()
        if box:
            lum = lum.crop((box[0], 0, box[2], lum.height))
        else:
            lum = lum.crop((0, 0, 1, lum.height))
        lut = self.art._lut
        chans = [lum.point([lut[min(255, color[i] * v // 255)] for v in range(256)]) for i in range(3)]
        img = Image.merge('RGBA', chans + [lum.point(lambda v: 255 if v else 0)])
        if len(self._lines) > 4000:
            self._lines.clear()
        self._lines[key] = (img, f['cap'])
        return self._lines[key]

    def draw(self, dst, text, cx, cy, font='font16', color=WHITE, align='center'):
        """Pastes the text with its capital-letter middle at cy; cx is the centre (or the left / right end)."""
        img, cap = self.line(text, font, color)
        x = cx - img.width / 2 if align == 'center' else (cx if align == 'left' else cx - img.width)
        dst.alpha_composite(img, (int(round(x)), int(round(cy - cap))))
        return img.width

    def width(self, text, font='font16'):
        return self.line(text, font, WHITE)[0].width


# ====================================================================================== page 1 (measured)
# Coordinates of the game's page 1 in the 512 x 704 panel art (docs/statscreen-ref/layout.json).
P1_BOX = {'name': (108, 58, 240, 26), 'level': (378, 67, 45, 16),
          'strength': (74, 161, 90, 18), 'dexterity': (74, 222, 90, 18),
          'vitality': (350, 161, 90, 18), 'energy': (350, 222, 90, 18), 'stat_points': (240, 154, 36, 22)}
P1_PLUS = {'strength': (29, 147), 'dexterity': (29, 208), 'vitality': (439, 147), 'energy': (439, 208)}
PLUS_SIZE = (44, 44)
ARROWS = {'prev': (379, 654, 6), 'next': (425, 654, 8)}
ARROW_SIZE = (41, 36)
CLOSE = (484, 8, 22, 22)
PORTRAIT = (35, 49)                   # where the game draws the 71 x 74 class portrait, over the art
P1_CAPTIONS = (                       # text key, default, centre x, centre y, font, colour
    ('ss.level', 'Level', 400.5, 61.5, 'font6', GOLD),
    ('ss.strength', 'Strength', 119, 153.5, 'font16', GOLD),
    ('ss.dexterity', 'Dexterity', 119, 214.5, 'font16', GOLD),
    ('ss.vitality', 'Vitality', 395, 153.5, 'font16', GOLD),
    ('ss.energy', 'Energy', 395, 214.5, 'font16', GOLD),
    ('ss.stat_points', 'Stat Points', 256.5, 209.5, 'font16', GOLD),
    ('ss.damage', 'Damage', 256, 364, 'font6', GOLD),
    ('ss.attack_rating', 'Attack Rating', 256.5, 389.5, 'font6', GOLD),
    ('ss.defense', 'Defense', 257, 547, 'font6', GOLD),
)
P1_TWO_LINES = (                      # text key, default, centre x, centre y of the box, colour
    ('ss.fire_res', 'Fire\nResistance', 154, 482.5, RED),
    ('ss.cold_res', 'Cold\nResistance', 154, 509.5, BLUE),
    ('ss.light_res', 'Lightning\nResistance', 154, 536.5, YELLOW),
    ('ss.poison_res', 'Poison\nResistance', 154, 563.5, GREEN),
    ('ss.phys_res', 'Physical\nResistance', 360, 482.5, GOLD),
    ('ss.magic_res', 'Magic\nResistance', 360, 509.5, ORANGE),
    ('ss.block', 'Block Chance', 360, 536.5, WHITE),
    ('ss.grit', 'Grit', 360, 563.5, WHITE),
)
P1_DERIVED = {                        # key -> value box
    'damage_1': (92, 352, 96, 20), 'damage_2': (323, 352, 96, 20),
    'attack_rating_1': (92, 379, 96, 20), 'attack_rating_2': (323, 379, 96, 20),
    'fire_res': (65, 472, 43, 21), 'cold_res': (65, 499, 43, 21), 'light_res': (65, 526, 43, 21),
    'poison_res': (65, 553, 43, 21), 'phys_res': (405, 472, 43, 21), 'magic_res': (405, 499, 43, 21),
    'block': (405, 526, 43, 21), 'grit': (405, 553, 43, 21), 'defense': (207, 552, 98, 22)}
SKILL_ICONS = {'left': (115, 289), 'right': (351, 289)}
P1_ORDER = ('name', 'level', 'strength', 'dexterity', 'vitality', 'energy', 'stat_points')

# ---- the editor's own pages: boxes cut from the same art, on the panel's stone
BLANK = (14, 136, 498, 612)           # the part of the panel replaced with plain stone
STONE_SRC = (206, 292, 306, 344)      # clean stone of the art (between the two skill frames)
BOX_SRC = (109, 471, 199, 494)        # an engraved box of the art (a resistance caption box), 9-sliced
ROW_H = 21
ROW_PITCH = 26
SV_Y0 = 186
SV_L = (34, 104, 140, 104)            # left column: caption box x, w; value box x, w
SV_R = (268, 80, 350, 62, 414, 62)    # right column: caption x, w; current x, w; maximum x, w
SV_LEFT = ('experience', None, 'skill_points', 'gold', 'gold_stash', 'class', 'levelup', 'copy_as')
SV_RIGHT = (None, 'life', 'mana', 'stamina')
SV_FLAGS = ('expansion', 'ladder', 'hardcore', 'died')
SV_FLAGS_Y0 = 432
SV_ORDER = ('name', 'level', 'experience', 'skill_points', 'gold', 'gold_stash', 'levelup', 'copy_as',
            'life_cur', 'life_max', 'mana_cur', 'mana_max', 'stamina_cur', 'stamina_max', 'progression')
LIST_BOX = (34, 186, 444, 418)        # the totals list: x, y, w, h
LIST_PITCH = 16


class StatScreen:
    """The canvas of the art page. win: the CharacterWindow (StatEditMixin); art: mxl_d2look_art.Art."""

    def __init__(self, parent, win, art):
        self.win = win
        self.art = art
        self.text = GameText(art)
        self.k = 1.0
        self.pages = ['main', 'totals', 'saved']
        self.page = 'main'
        self.pressed = None
        self.edit = None                  # (key, entry widget, canvas item)
        self.scroll_at = 0
        self._bg = {}
        self._pil = {}
        self._photo = None
        self._regions = []
        self._lines = None
        self._tip = None
        self._closing = False
        self.frame = tk.Frame(parent, bg='#000000')
        self.cv = tk.Canvas(self.frame, bg='#000000', highlightthickness=0, bd=0, width=PANEL_W, height=PANEL_H,
                            takefocus=1)
        self.cv.pack(expand=True)
        self._item = self.cv.create_image(0, 0, anchor='nw')
        cv = self.cv
        cv.bind('<ButtonPress-1>', self.on_press)
        cv.bind('<ButtonRelease-1>', self.on_release)
        cv.bind('<ButtonPress-3>', self.on_right)
        cv.bind('<Motion>', self.on_motion)
        cv.bind('<Leave>', lambda e: self._show_tip(None))
        cv.bind('<MouseWheel>', self.on_wheel)
        cv.bind('<Button-4>', self.on_wheel)
        cv.bind('<Button-5>', self.on_wheel)
        cv.bind('<Prior>', lambda e: self.turn(-1))
        cv.bind('<Next>', lambda e: self.turn(1))

    # ------------------------------------------------------------------ art pieces
    def _open(self, path):
        im = self._pil.get(path)
        if im is None:
            from PIL import Image
            im = self._pil[path] = Image.open(path).convert('RGBA')
        return im

    def _frame(self, rel, i):
        return self._open(self.art.frame(rel, i))

    def _panel(self):
        return self._open(self.art.panel('stat-screen'))

    def _box(self, w, h):
        """An engraved box of any size: the art's own box, corners kept, edges and middle stretched."""
        key = ('box', w, h)
        im = self._pil.get(key)
        if im is None:
            from PIL import Image
            src = self._panel().crop(BOX_SRC)
            m = 4
            sw, sh = src.size
            im = Image.new('RGBA', (w, h))
            xs = ((0, m, 0, m), (m, sw - m, m, w - m), (sw - m, sw, w - m, w))
            ys = ((0, m, 0, m), (m, sh - m, m, h - m), (sh - m, sh, h - m, h))
            flat = src.crop((m, m, sw - m, sh - m)).resize((1, 1), Image.BOX).getpixel((0, 0)) if h > 2 * sh else None
            for sx0, sx1, dx0, dx1 in xs:
                for sy0, sy1, dy0, dy1 in ys:
                    if flat and sx0 == m and sy0 == m:
                        im.paste(flat, (dx0, dy0, dx1, dy1))
                    elif dx1 > dx0 and dy1 > dy0:
                        im.paste(src.crop((sx0, sy0, sx1, sy1)).resize((dx1 - dx0, dy1 - dy0), Image.BILINEAR), (dx0, dy0))
            self._pil[key] = im
        return im

    def _button(self, w, h, down=False):
        """A text button in the stone of the art: the engraved box, lighter, with a bronze rim."""
        key = ('btn', w, h, down)
        im = self._pil.get(key)
        if im is None:
            from PIL import ImageDraw, ImageEnhance
            im = ImageEnhance.Brightness(self._box(w, h)).enhance(0.9 if down else 1.9)
            d = ImageDraw.Draw(im)
            d.rectangle((0, 0, w - 1, h - 1), outline=(111, 90, 58, 255))
            d.rectangle((1, 1, w - 2, h - 2), outline=(40, 32, 20, 255) if not down else (154, 127, 82, 255))
            self._pil[key] = im
        return im

    def _checkbox(self, on):
        """A toggle in the panel's own style: a small engraved box, a gold X when set."""
        key = ('cb', bool(on))
        im = self._pil.get(key)
        if im is None:
            from PIL import ImageDraw
            im = self._box(15, 15).copy()
            ImageDraw.Draw(im).rectangle((0, 0, 14, 14), outline=(111, 90, 58, 255))
            if on:
                self.text.draw(im, 'X', 7.5, 7.5, 'font6', (242, 220, 156))
            self._pil[key] = im
        return im

    def _portrait(self, cls):
        key = ('portrait', cls)
        if key not in self._pil:
            try:
                self._pil[key] = self._frame('panel-elements\\stat-screen-portrait', cls)
            except Exception:
                self._pil[key] = None              # no portrait art: the window stays empty
        return self._pil[key]

    def _skill_icon(self, cls, sid):
        """The 48 x 48 icon of one of the class's skills (None for any other skill: nothing is drawn)."""
        key = ('skills', cls)
        icons = self._pil.get(key)
        if icons is None:
            icons = self._pil[key] = {}
            try:
                import mxl_d2ui_dc6 as DC6
                from PIL import Image
                data = self.win.data
                code = data._rows('playerclass')[cls][:4].decode('latin1').strip()
                base = 'data\\global\\themes\\classic_sigma\\game\\skills\\icons-'
                cels = DC6.dc6_frames(self.art.read(base + code + '.dc6'))
                pal = self.art.pal()
                for _tab, _name, cells in (MC.skill_trees(data).get(cls) or []):
                    for _row, _col, s, cel in cells:
                        if cel < len(cels):
                            w, h, rgba = DC6.to_rgba(cels[cel], pal)
                            icons[s] = Image.frombytes('RGBA', (w, h), bytes(self.art._bright(rgba)))
            except Exception as e:
                print('stat screen: no skill icons:', e)
        return icons.get(sid)

    def _background(self, kind):
        """'game': the panel art as it is. 'blank': the same frame and header, the middle replaced with the
        art's own stone (for the editor's pages)."""
        bg = self._bg.get(kind)
        if bg is not None:
            return bg
        from PIL import Image
        panel = self._panel()
        if kind == 'game':
            bg = panel
        else:
            x0, y0, x1, y1 = BLANK
            tile = panel.crop(STONE_SRC)
            tw, th = tile.size
            stone = Image.new('RGBA', (x1 - x0, y1 - y0))
            for j, ty in enumerate(range(0, stone.height, th)):
                for i, tx in enumerate(range(0, stone.width, tw)):
                    t = tile
                    if i % 2:
                        t = t.transpose(Image.FLIP_LEFT_RIGHT)
                    if j % 2:
                        t = t.transpose(Image.FLIP_TOP_BOTTOM)
                    stone.paste(t, (tx, ty))
            mask = Image.new('L', stone.size, 255)             # soft upper / lower edge: no seam with the art
            f = 10
            for i in range(f):
                v = round(255 * (i + 1) / (f + 1))
                mask.paste(v, (0, i, stone.width, i + 1))
                mask.paste(v, (0, stone.height - 1 - i, stone.width, stone.height - i))
            bg = panel.copy()
            bg.paste(stone, (x0, y0), mask)
        self._bg[kind] = bg
        return bg

    # ------------------------------------------------------------------ size
    def fit(self, W, H):
        """Scale factor from the space of the tab: the whole panel when it stays readable, else the width."""
        k = min(W / PANEL_W, max(H / PANEL_H, MIN_K), MAX_K)
        k = max(0.5, round(k * 64) / 64)
        if abs(k - self.k) > 1e-6 or self._photo is None:
            self.k = k
            self.cancel_edit()
            self.cv.configure(width=round(PANEL_W * k), height=round(PANEL_H * k))
            self.redraw()

    # ------------------------------------------------------------------ drawing
    def redraw(self):
        from PIL import Image, ImageTk
        try:
            img = self.compose()
        except Exception as e:                    # never a dead tab: the reason on the status line
            import traceback
            traceback.print_exc()
            self.win.set_bar(str(e), error=True)
            return
        size = (round(PANEL_W * self.k), round(PANEL_H * self.k))
        if size != img.size:
            img = img.resize(size, Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img, master=self.cv)
        self.cv.itemconfigure(self._item, image=self._photo)

    def compose(self):
        from PIL import Image
        win = self.win
        page = self.page
        out = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 255))
        out.alpha_composite(self._background('game' if page == 'main' else 'blank'))
        cls = win.st_cls()
        por = self._portrait(cls) if cls < 7 else None
        if por is not None:                       # the class portrait, drawn by the game over the art's window
            out.alpha_composite(por, PORTRAIT)
        self._regions = reg = []
        tx = self.text
        # header: name plate and level (every page)
        name = str(win.st_value('name'))
        tx.draw(out, name if tx.has(name, 'font16') else name.encode('ascii', 'replace').decode(), 124, 73, 'font16', GOLD, 'left')
        tx.draw(out, T('ss.level', 'Level'), 400.5, 61.5, 'font6', GOLD)
        tx.draw(out, str(win.st_value('level')), 400.5, 75, 'font16', WHITE)
        reg.append(('edit', 'name', P1_BOX['name']))
        reg.append(('edit', 'level', P1_BOX['level']))
        try:
            cl = self._frame('buttons\\close', 1 if self.pressed == ('close', None) else 0)
            out.alpha_composite(cl, (CLOSE[0], CLOSE[1]))
        except Exception:
            pass
        reg.append(('close', None, CLOSE))
        for which, (x, y, fr) in ARROWS.items():
            out.alpha_composite(self._frame('buttons\\stat-screen', fr + (1 if self.pressed == ('page', which) else 0)), (x, y))
            reg.append(('page', which, (x, y) + ARROW_SIZE))
        tx.draw(out, f'{self.pages.index(page) + 1} / {len(self.pages)}', 370, 672, 'font6', GOLD, 'right')
        getattr(self, '_page_' + page)(out, reg)
        return out

    def _dash(self, out, cx, cy):
        """The dimmed dash of a value only the game can compute."""
        from PIL import ImageDraw
        ImageDraw.Draw(out).rectangle((round(cx) - 6, round(cy) - 1, round(cx) + 6, round(cy)), fill=DIM + (255,))

    def _page_main(self, out, reg):
        win, tx = self.win, self.text
        sim = win.st_sim
        for key, default, cx, cy, font, color in P1_CAPTIONS[1:]:
            tx.draw(out, T(key, default), cx, cy, font, color)
        for key, default, cx, cy, color in P1_TWO_LINES:
            parts = T(key, default).split('\n')
            for i, part in enumerate(parts):              # measured: lines 11 px apart, a single line 1.5 px low
                tx.draw(out, part, cx, cy + (i * 11 - 5 if len(parts) > 1 else 1.5), 'font6', color)
        for key in ATTRS + ('stat_points',):
            x, y, w, h = P1_BOX[key]
            tx.draw(out, str(win.st_value(key)), x + w / 2 + (0.5 if key == 'stat_points' else 0), y + h / 2 + (0 if key == 'stat_points' else 0), 'font16', WHITE)
            reg.append(('edit', key, P1_BOX[key]))
        pts = sim.field('stat_points')
        for key, (x, y) in P1_PLUS.items():
            if self.pressed == ('plus', key):
                fr = 3 if pts > 0 else 1
            else:
                fr = 2 if pts > 0 else 0
            out.alpha_composite(self._frame('buttons\\stat-screen', fr), (x, y))
            reg.append(('plus', key, (x, y) + PLUS_SIZE))
        # the two attack blocks: the skills on the mouse buttons as the save names them
        cls = sim.cls
        for side, off in (('left', 0x78), ('right', 0x7C)):
            sid = struct.unpack_from('<I', sim.head, off)[0]
            ic = self._skill_icon(cls, sid) if cls < 7 else None
            x, y = SKILL_ICONS[side]
            if ic is not None:
                out.alpha_composite(ic, (x + (48 - ic.width) // 2, y + (48 - ic.height) // 2))
            reg.append(('info', 'skill_' + side, (x, y, 48, 48)))
        tot = win.st_totals()
        for key, (x, y, w, h) in P1_DERIVED.items():
            cx, cy = x + w / 2 + (1.5 if w == 43 else 0), y + h / 2
            val = None
            if not tot['error']:
                if key in RES_IDS:
                    val = f'{total_of(tot, RES_IDS[key])}%'
                elif key == 'defense':
                    val = str(tot['defense'])
            if val is None:
                self._dash(out, cx, cy)
            else:
                tx.draw(out, val, cx, cy, 'font16', SUM)
            reg.append(('info', key, (x, y, w, h)))

    def _title(self, out, title, note):
        tx = self.text
        tx.draw(out, title, 256, 152, 'font16', GOLD)
        for i, part in enumerate(note.split('\n')):
            tx.draw(out, part, 256, 167 + 10 * i, 'font6', DIM)

    def _lines_of(self):
        """The totals list, wrapped to the list box: [(colour, text)]."""
        win = self.win
        tot = win.st_totals()
        key = (tot, self.win.st_sim.level)
        if self._lines is None or self._lines[0][0] is not tot or self._lines[0][1] != key[1]:
            maxw = LIST_BOX[2] - 30
            rows = []
            if tot['error']:
                rows.append((RED, tot['error'][:60]))
            base = [(GOLD, T('ss.tot.items', 'Equipped items: {n}', n=tot['items'])),
                    (WHITE, T('ss.tot.defense', 'Defense of the items: {n}', n=tot['defense']))]
            for col, text in base + [(D2_COLORS.get(int(c), WHITE) if str(c).isdigit() else WHITE, t)
                                     for c, t in total_lines(tot, win.data, getattr(win.app, 'char', None))]:
                text = ''.join(ch if self.text.has(ch, 'font16') else '?' for ch in text)
                words, cur = text.split(' '), ''
                for wd in words:
                    trial = (cur + ' ' + wd) if cur else wd
                    if cur and self.text.width(trial, 'font16') > maxw:
                        rows.append((col, cur))
                        cur = '  ' + wd
                    else:
                        cur = trial
                rows.append((col, cur))
            self._lines = (key, rows)
        return self._lines[1]

    def _page_totals(self, out, reg):
        from PIL import ImageDraw
        tx = self.text
        self._title(out, T('ss.totals', 'Total Attributes (from equipped items)'),
                    T('ss.totals_note', 'Plain sums of the stats of the equipped items (active weapon set, with sockets).\n'
                      'Set bonuses, charms, skills and per-level effects the game applies may be missing.'))
        x, y, w, h = LIST_BOX
        out.alpha_composite(self._box(w, h), (x, y))
        rows = self._lines_of()
        shown = (h - 10) // LIST_PITCH
        top = max(0, len(rows) - shown)
        self.scroll_at = max(0, min(self.scroll_at, top))
        for i, (col, text) in enumerate(rows[self.scroll_at:self.scroll_at + shown]):
            tx.draw(out, text, x + 10, y + 5 + LIST_PITCH * i + LIST_PITCH / 2, 'font16', col, 'left')
        if top:                                    # the place in the list: a thumb on the right edge
            d = ImageDraw.Draw(out)
            th = max(16, (h - 8) * shown // len(rows))
            ty = y + 4 + (h - 8 - th) * self.scroll_at // top
            d.rectangle((x + w - 9, y + 4, x + w - 5, y + h - 5), fill=(20, 18, 16, 255))
            d.rectangle((x + w - 9, ty, x + w - 5, ty + th), fill=(111, 90, 58, 255))
        reg.append(('list', None, LIST_BOX))

    def _value_box(self, out, reg, key, x, y, w, text=None, kind='edit', color=WHITE):
        out.alpha_composite(self._box(w, ROW_H), (x, y))
        if text is None:
            text = str(self.win.st_value(key))
        if text:
            font = 'font16' if self.text.width(text, 'font16') <= w - 6 else 'font6'
            self.text.draw(out, text, x + w / 2, y + ROW_H / 2, font, color)
        reg.append((kind, key, (x, y, w, ROW_H)))

    def _caption_box(self, out, x, y, w, text, color=GOLD):
        out.alpha_composite(self._box(w, ROW_H), (x, y))
        parts = text.split('\n')
        for i, part in enumerate(parts):
            self.text.draw(out, part, x + w / 2, y + ROW_H / 2 + (i - (len(parts) - 1) / 2) * 10, 'font6', color)

    def _text_button(self, out, reg, key, x, y, w, text):
        down = self.pressed == ('button', key)
        out.alpha_composite(self._button(w, ROW_H, down), (x, y))
        self.text.draw(out, text, x + w / 2, y + ROW_H / 2 + (1 if down else 0), 'font6', GOLD)
        reg.append(('button', key, (x, y, w, ROW_H)))

    def _page_saved(self, out, reg):
        win, tx = self.win, self.text
        sim = win.st_sim
        self._title(out, T('ss.saved', 'Saved Values'),
                    T('ss.saved_note', "The editor's own page:\nwhat the save stores and the game's screen does not show."))
        lx, lw, vx, vw = SV_L
        names = {'experience': T('ss.experience', 'Experience'), 'skill_points': T('ss.skill_points', 'Skill Points'),
                 'gold': T('ss.gold', 'Gold'), 'gold_stash': T('ss.gold_stash', 'Gold in Stash'),
                 'class': T('ss.class', 'Class'), 'levelup': T('ss.levelup2', 'Level up\nlike the game'),
                 'copy_as': T('ss.copy_as', 'Copy as')}
        for r, key in enumerate(SV_LEFT):
            y = SV_Y0 + ROW_PITCH * r
            if key is None:                         # under the experience: its range in the game table + the fix
                lo, hi = sim.exp_range() if sim.cls < 7 else (0, MC.EXP_MAX)
                ok = lo <= sim.field('experience') <= hi
                tx.draw(out, T('ss.exp_range', 'level {level}: {lo}', level=sim.level, lo=lo), lx + lw + 2, y + 5.5, 'font6',
                        DIM if ok else RED, 'right')
                tx.draw(out, T('ss.exp_to', 'to {hi}', hi=hi), lx + lw + 2, y + 15.5, 'font6', DIM if ok else RED, 'right')
                self._text_button(out, reg, 'match_exp', vx, y, vw, T('ss.match', 'Match to level'))
                continue
            self._caption_box(out, lx, y, lw, names[key])
            if key == 'class':
                cls = win.st_cls()
                nm = win.class_names[cls] if cls < len(win.class_names) else str(cls)
                self._value_box(out, reg, 'class', vx, y, vw, nm, kind='class',
                                color=WHITE if getattr(win, 'pending_cls', None) is None else YELLOW)
            elif key == 'levelup':
                self._value_box(out, reg, key, vx, y, vw, T('ss.levelup_to', 'to level ...'), color=DIM)
            elif key == 'copy_as':
                self._value_box(out, reg, key, vx, y, vw, win.copy_name.get() or T('ss.new_name', 'new name ...'),
                                color=WHITE if win.copy_name.get() else DIM)
            else:
                self._value_box(out, reg, key, vx, y, vw)
        cx, cw, ax, aw, bx, bw = SV_R
        tx.draw(out, T('ss.current', 'Current'), ax + aw / 2, SV_Y0 + ROW_H / 2, 'font6', GOLD)
        tx.draw(out, T('ss.maximum', 'Maximum'), bx + bw / 2, SV_Y0 + ROW_H / 2, 'font6', GOLD)
        for r, key in enumerate(SV_RIGHT):
            if key is None:
                continue
            y = SV_Y0 + ROW_PITCH * r
            self._caption_box(out, cx, y, cw, {'life': T('ss.life', 'Life'), 'mana': T('ss.mana', 'Mana'),
                                               'stamina': T('ss.stamina', 'Stamina')}[key],
                              {'life': RED, 'mana': BLUE, 'stamina': YELLOW}[key])
            self._value_box(out, reg, key + '_cur', ax, y, aw)
            self._value_box(out, reg, key + '_max', bx, y, bw)
        y = SV_Y0 + ROW_PITCH * 5
        self._caption_box(out, cx, y, cw + 2 + aw, T('ss.progression', 'Progression'))
        self._value_box(out, reg, 'progression', bx, y, bw)
        self._text_button(out, reg, 'copy', vx + vw + 6, SV_Y0 + ROW_PITCH * 7, 56, T('he.copy', 'Copy'))
        # toggles: character type (left), difficulties finished (right)
        y0 = SV_FLAGS_Y0
        tx.draw(out, T('ss.char_type', 'Character Type'), lx + (vx + vw - lx) / 2, y0 - 16, 'font16', GOLD)
        tx.draw(out, T('ss.difficulty', 'Difficulty'), cx + (bx + bw - cx) / 2, y0 - 16, 'font16', GOLD)
        flags = sim.flags()
        fl_names = {'expansion': T('he.expansion', 'Expansion'), 'ladder': T('he.ladder', 'Ladder'),
                    'hardcore': T('he.hardcore', 'Hardcore'), 'died': T('he.dead', 'You were Dead')}
        for r, key in enumerate(SV_FLAGS):
            y = y0 + ROW_PITCH * r
            w = vx + vw - lx
            out.alpha_composite(self._box(w, ROW_H), (lx, y))
            out.alpha_composite(self._checkbox(flags[key]), (lx + 6, y + 3))
            tx.draw(out, fl_names[key], lx + 30, y + ROW_H / 2, 'font6', WHITE if flags[key] else GOLD, 'left')
            reg.append(('flag', key, (lx, y, w, ROW_H)))
        done = sim.difficulties_done
        d_names = [MC.difficulty_name(i) for i in range(3)] + [T('ss.hell_done', 'Hell finished')]
        for n in range(4):
            y = y0 + ROW_PITCH * n
            w = bx + bw - cx
            out.alpha_composite(self._box(w, ROW_H), (cx, y))
            out.alpha_composite(self._checkbox(done == n), (cx + 6, y + 3))
            text = d_names[n] if n == 3 else T('ss.diff_open', '{mode} is the highest open', mode=d_names[n])
            tx.draw(out, text, cx + 30, y + ROW_H / 2, 'font6', WHITE if done == n else GOLD, 'left')
            reg.append(('done', n, (cx, y, w, ROW_H)))
        # file
        ch = win.ch
        y = y0 + ROW_PITCH * 4 + 14
        info = (T('ss.file', 'File: {name}', name=os.path.basename(ch.path)),
                T('ss.file_size', 'Size: {size} bytes    Version: {version}', size=f'{len(ch.raw):,}',
                  version=struct.unpack_from('<I', ch.raw, 4)[0]))
        for i, text in enumerate(info):
            text = ''.join(c if tx.has(c, 'font6') else '?' for c in text)
            tx.draw(out, text, 256, y + 12 * i, 'font6', DIM)

    # ------------------------------------------------------------------ pointer
    def _at(self, ev):
        x, y = ev.x / self.k, ev.y / self.k
        for kind, key, (bx, by, bw, bh) in reversed(self._regions):
            if bx <= x < bx + bw and by <= y < by + bh:
                return kind, key, (bx, by, bw, bh)
        return None, None, None

    def tip_of(self, kind, key):
        win = self.win
        if kind == 'edit':
            if key in ATTRS:
                tot = win.st_totals()
                gear = total_of(tot, ATTR_IDS[key])
                return T('ss.tip.attr', '{label}: base value stored in the save.\nEquipped items add +{gear} '
                         '(the game shows the total).', label=win.st_label(key), gear=gear)
            if key == 'level':
                return T('ss.tip.level', 'Level: written as typed, nothing else changes.\n'
                         'The game-like level-up is on the "Saved values" page.')
            if key == 'levelup':
                return T('he.level_note', 'Raising the level works like the game: experience, 5 stat points\n'
                         'and 1 skill point per level, life / mana / stamina per level.')
            if key == 'name':
                return T('ss.tip.name', 'Name: SAVE renames the character and its files.')
            if key == 'copy_as':
                return T('ss.tip.copy', 'Name of the copy: type it, then click Copy.')
            try:
                lo, hi = win.st_range(key)
                return f'{win.st_label(key)}: {lo} - {hi}'
            except CharError:
                return None
        if kind == 'plus':
            return T('ss.tip.plus', 'Click: +1 (Shift +10, Ctrl all the stat points).\nRight click: one point back.\n'
                     'Alt: without touching the stat points.')
        if kind == 'class':
            return T('he.class_note', 'Changing the class resets the skill levels\n(the save keeps one skill list per class).')
        if kind == 'info':
            if key in RES_IDS or key == 'defense':
                return T('ss.tip.sum', 'Sum of the equipped items only.\nThe final value is computed by the game '
                         '(skills, charms, per-level bonuses, difficulty, caps).')
            if key.startswith('skill_'):
                sim = win.st_sim
                sid = struct.unpack_from('<I', sim.head, 0x78 if key == 'skill_left' else 0x7C)[0]
                return win._sk_name(sid)
            return T('ss.tip.game', 'computed by the game')
        if kind == 'page':
            return T('ss.tip.page', 'Other pages: total attributes, saved values')
        return None

    def _show_tip(self, text):
        if text != self._tip:
            self._tip = text
        try:
            self.win._sk_tip(text or '')
        except Exception:
            pass

    def on_motion(self, ev):
        kind, key, _box = self._at(ev)
        cur = {'edit': 'xterm', 'plus': 'hand2', 'page': 'hand2', 'close': 'hand2', 'button': 'hand2',
               'flag': 'hand2', 'done': 'hand2', 'class': 'hand2'}.get(kind, '')
        if self.cv.cget('cursor') != cur:
            self.cv.configure(cursor=cur)
        self._show_tip(self.tip_of(kind, key) if kind else None)

    def on_press(self, ev):
        self.cv.focus_set()
        if self.edit is not None and not self.commit_edit():
            return
        kind, key, box = self._at(ev)
        if kind in ('plus', 'page', 'close', 'button'):
            self.pressed = (kind, key)
            self.redraw()
        elif kind == 'edit':
            self.start_edit(key)
        elif kind == 'flag':
            self.win.st_flag(key)
        elif kind == 'done':
            self.win.st_done(key)
        elif kind == 'class':
            self.class_menu(ev)
        elif kind == 'list':
            x, y, w, h = box
            self.scroll((1 if ev.y / self.k > y + h / 2 else -1) * ((h - 10) // LIST_PITCH - 1))

    def on_release(self, ev):
        if self.pressed is None:
            return
        pressed, self.pressed = self.pressed, None
        kind, key, _box = self._at(ev)
        if (kind, key) != pressed:
            self.redraw()
            return
        self.activate(kind, key, ev.state)

    def activate(self, kind, key, state=0):
        """What a click on a button does (state: the event's modifier bits)."""
        win = self.win
        shift, ctrl, alt = bool(state & 0x1), bool(state & 0x4), bool(state & 0x8)
        if kind == 'plus':
            win.st_plus(key, 10 if shift else 1, free=alt, everything=ctrl and not alt)
        elif kind == 'page':
            self.turn(-1 if key == 'prev' else 1)
            return
        elif kind == 'close':
            self.redraw()
            win.close()
            return
        elif kind == 'button':
            if key == 'match_exp':
                win.st_match_exp()
            elif key == 'copy':
                win.copy_char()
        self.redraw()

    def on_right(self, ev):
        kind, key, _box = self._at(ev)
        if kind == 'plus':
            if self.edit is not None and not self.commit_edit():
                return
            self.win.st_plus(key, 10 if ev.state & 0x1 else 1, take=True, free=bool(ev.state & 0x8))

    def on_wheel(self, ev):
        if self.page != 'totals':
            return None
        d = -1 if (getattr(ev, 'num', 0) == 4 or getattr(ev, 'delta', 0) > 0) else 1
        self.scroll(d * 3)
        return 'break'

    def scroll(self, n):
        self.scroll_at = max(0, self.scroll_at + n)
        self.redraw()

    def turn(self, step):
        if self.edit is not None and not self.commit_edit():
            return
        i = (self.pages.index(self.page) + step) % len(self.pages)
        self.show_page(self.pages[i])

    def show_page(self, page):
        if page in self.pages:
            self.cancel_edit()
            self.page = page
            self.redraw()

    def class_menu(self, ev):
        win = self.win
        m = tk.Menu(self.cv, tearoff=0)
        for name in win.class_names:
            m.add_command(label=name, command=lambda n=name: (win.new_class.set(n), win.on_class_change(), self.redraw()))
        try:
            m.tk_popup(ev.x_root, ev.y_root)
        finally:
            m.grab_release()

    # ------------------------------------------------------------------ editing in place
    def order(self):
        return P1_ORDER if self.page == 'main' else (SV_ORDER if self.page == 'saved' else ('name', 'level'))

    def box_of(self, key):
        return next((box for kind, k, box in self._regions if kind == 'edit' and k == key), None)

    def start_edit(self, key):
        """An entry exactly over the value box, in the box's colours."""
        self.cancel_edit()
        box = self.box_of(key)
        if box is None:
            return None
        x, y, w, h = box
        k = self.k
        if key == 'name':
            x, w = x + 12, w - 16
        px = max(9, round((11 if h < 20 else 12) * k * 1.25))
        e = tk.Entry(self.cv, font=('Times New Roman', -px, 'bold'), bd=0, relief='flat', bg='#0d0c0b',
                     fg='#c7b377' if key == 'name' else '#e6e6e6', insertbackground='#e6e6e6',
                     selectbackground='#4a1712', selectforeground='#ffffff',
                     highlightthickness=1, highlightbackground='#6f5a3a', highlightcolor='#c7b377',
                     justify='left' if key == 'name' else 'center')
        text = '' if key == 'copy_as' and not self.win.copy_name.get() else str(self.win.st_value(key))
        e.insert(0, text)
        e.select_range(0, 'end')
        item = self.cv.create_window(round(x * k), round(y * k), anchor='nw', window=e,
                                     width=max(20, round(w * k)), height=max(14, round(h * k)))
        self.edit = (key, e, item)
        e.bind('<Return>', lambda _e: (self.commit_edit(), 'break')[1])
        e.bind('<KP_Enter>', lambda _e: (self.commit_edit(), 'break')[1])
        e.bind('<Escape>', lambda _e: (self.cancel_edit(), self.win.update_dirty(), 'break')[2])
        e.bind('<FocusOut>', lambda _e: self.commit_edit(leaving=True))
        e.bind('<Tab>', lambda _e: (self.next_edit(1), 'break')[1])
        e.bind('<ISO_Left_Tab>', lambda _e: (self.next_edit(-1), 'break')[1])
        e.bind('<Shift-Tab>', lambda _e: (self.next_edit(-1), 'break')[1])
        if key not in TEXT_KEYS:
            e.bind('<Up>', lambda ev: (self.step_edit(10 if ev.state & 1 else 1), 'break')[1])
            e.bind('<Down>', lambda ev: (self.step_edit(-10 if ev.state & 1 else -1), 'break')[1])
        e.focus_set()
        return e

    def step_edit(self, n):
        if self.edit is None:
            return
        key, e, _item = self.edit
        try:
            v = int(e.get().replace(',', '').replace(' ', ''))
        except ValueError:
            v = self.win.st_value(key)
        lo, hi = self.win.st_range(key)
        e.delete(0, 'end')
        e.insert(0, str(max(lo, min(hi, v + n))))
        e.select_range(0, 'end')

    def commit_edit(self, leaving=False):
        """Stores the typed value. Refused input: the entry stays (Enter / Tab) or is dropped (focus left)."""
        if self.edit is None or self._closing:
            return True
        key, e, _item = self.edit
        ok = self.win.st_set(key, e.get())
        if ok or leaving:
            self.cancel_edit()
            if ok and key == 'copy_as':
                pass
            return ok
        try:
            e.select_range(0, 'end')
            e.focus_set()
        except tk.TclError:
            pass
        return False

    def cancel_edit(self):
        if self.edit is None:
            return
        _key, e, item = self.edit
        self.edit = None
        self._closing = True
        try:
            self.cv.delete(item)
            e.destroy()
        except tk.TclError:
            pass
        self._closing = False

    def next_edit(self, step):
        if self.edit is None:
            return
        key = self.edit[0]
        if not self.commit_edit():
            return
        order = self.order()
        i = order.index(key) if key in order else -1
        self.start_edit(order[(i + step) % len(order)])
