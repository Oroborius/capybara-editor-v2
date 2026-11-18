"""The Skills page of the Character window, drawn like the game's skill tree.

Dark look with the game folder known: the page IS the game's skill-tree panel (Tartarus panel art,
512 x 704, scaled to the tab like the stat screen): the class's connector web, every skill in the
game's socket frame (square = active skill, round = passive) with its icon and its level box, the
tree tabs on the right, "Remaining Skill Points" above them and the tree's caption at the bottom,
all at the places measured on game screenshots (docs: WORKLOG). Light Hero-Editor look, or no game
files: the same nodes, tabs and tooltips drawn plainly with Tk shapes and fonts.

Editing: click the level box to type (Enter / Escape / Tab / Up / Down, Shift = 10), left-click the
icon +1, right-click -1 (Shift: 5). Nothing is refused (the editor is unrestricted); a skill
whose required level or prerequisite skills the character does not have shows its level in red,
as the game does. Levels live in win.sk_vars (StringVars) as before; SAVE writes them.

Hovering a skill shows the game's tooltip (mxl_skilldesc): the tables' own texts and formulas for
the level in the box."""
import os
import struct
import tkinter as tk
import tkinter.font as tkfont

import mxl_char as MC
import mxl_skilldesc as SD
from mxl_lang import T

PANEL_W, PANEL_H = 512, 704
NODE_X, NODE_Y, NODE_DX, NODE_DY = 68, 50, 100, 100    # socket frame (60 x 80) of row 1 / column 1; pitch
NODE_W, NODE_H = 60, 80
ICON_OFF, ICON = 6, 48
LVL_BOX = (5, 61, 50, 17)                              # the level box inside the socket frame
TAB_X, TAB_Y, TAB_W, TAB_SPAN = 377, 142, 132, 480     # the tab column: n tabs share 480 px
TAB_FRAMES = {2: 3, 3: 6, 4: 9, 5: 12, 6: 15, 7: 18, 8: 21, 9: 24, 10: 27}   # tabs -> tree-tabs frame (+1 = selected)
TAB_PITCH = {2: 240, 3: 160, 4: 120, 5: 96, 6: 80, 7: 68, 8: 60, 9: 53, 10: 48}  # = the height of that frame
POINTS_AT = (443, 49)                                  # the remaining-points number (in the orb)
POINTS_CAPTION = ((443, 87), (443, 102))               # "Remaining" / "Skill Points"
NOTE_AT = (200, 655)                                   # bottom line of the tree's caption; lines stack upwards
NOTE_DY = 17
CLOSE_AT = (9, 8)
GOLD = (199, 179, 119)
WHITE = (230, 230, 230)
RED = (255, 77, 77)
DIM = (150, 140, 112)
MIN_K, MAX_K = 0.55, 2.0
TIP_DELAY = 350                                        # ms, like the game's short wait
TIP_WRAP = 560                                         # px: longer lines are folded


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(rgb)


def _rgb(hexcol):
    return tuple(int(hexcol[i:i + 2], 16) for i in (1, 3, 5))


class SkillTree:
    """Canvas + tooltip of the Skills page. win: the CharacterWindow."""

    def __init__(self, parent, win):
        self.win = win
        self.k = 1.0
        self.tab = None                    # the tree shown (int; 0 = the skills outside the trees)
        self.cls = None
        self.trees = []
        self.match = None                  # skill ids the Find box matches (None: no filter)
        self.edit = None
        self._closing = False
        self._regions = []
        self._photo = None
        self._pil = {}
        self._icons = {}
        self._text = None
        self._art = False
        self._tip_win = None
        self._tipper = None                # mxl_floattip.FloatTip, made on the first hover
        self._tip_label = None
        self._tip_for = None
        self._tip_job = None
        self._tip_photo = None
        self._traces = []
        self._redraw_job = None
        self.frame = tk.Frame(parent, bg='#000000')
        self.cv = tk.Canvas(self.frame, bg='#000000', highlightthickness=0, bd=0, width=PANEL_W, height=PANEL_H)
        self.cv.pack(expand=True)
        cv = self.cv
        cv.bind('<ButtonPress-1>', self.on_press)
        cv.bind('<ButtonPress-3>', self.on_right)
        cv.bind('<Motion>', self.on_motion)
        cv.bind('<Leave>', lambda e: self._leave())
        cv.bind('<Destroy>', lambda e: self.hide_tip(), add='+')
        try:                               # the look is switched: the page is drawn the other way
            win.dark.trace_add('write', lambda *_a: self.redraw_later())
        except Exception:
            pass

    # ------------------------------------------------------------------ data
    def art(self):
        """The game's art for the dark look (None: plain drawing)."""
        win = self.win
        try:
            if not win.dark.get():
                return None
            import mxl_d2look
            a = mxl_d2look.art()
            if a is None:
                return None
            a.panel('skill-tree')
            a.frame('skills\\socket', 2)
            a.font('font16')
            return a
        except Exception as e:
            if not getattr(self, '_art_said', False):
                self._art_said = True
                print('game art for the skill tree disabled:', e)
            return None

    def class_code(self):
        rows = self.win.data._rows('playerclass')
        return rows[self.cls][:4].decode('latin1').strip().lower() if self.cls is not None and self.cls < len(rows) else ''

    def rebuild(self):
        """Another character / class: the trees and the level variables."""
        win = self.win
        self.cancel_edit()
        self.hide_tip()
        for var, tid in self._traces:
            try:
                var.trace_remove('write', tid)
            except (tk.TclError, ValueError):
                pass
        self._traces = []
        self.cls = win.ch.cls
        self.trees = MC.skill_trees(win.data).get(self.cls) or []
        levels = win.ch.skill_levels()
        win.sk_vars = {}
        for _tab, _name, cells in self.trees:
            for _row, _col, sid, _cel in cells:
                var = tk.StringVar(value=str(levels.get(sid, 0)))
                self._traces.append((var, var.trace_add('write', lambda *_a: self.redraw_later())))
                win.sk_vars[sid] = var
        tabs = [t for t, _n, _c in self.trees]
        self.tab = next((t for t in tabs if t > 0), tabs[0] if tabs else None)
        self._icons = {}
        self.redraw()

    def cells(self, tab=None):
        """[(sid, row, col)] of a tree, never two skills in one cell; tab 0 is laid out in reading order."""
        tab = self.tab if tab is None else tab
        cells = next((c for t, _n, c in self.trees if t == tab), [])
        out = []
        if tab == 0:
            for i, (_r, _c, sid, _cel) in enumerate(sorted(cells, key=lambda c: c[2])):
                out.append((sid, i // 3 + 1, i % 3 + 1))
            return out
        taken = set()
        for row, col, sid, _cel in cells:
            cell = (max(1, row), max(1, col))
            while cell in taken:
                cell = (cell[0], cell[1] + 1)
            taken.add(cell)
            out.append((sid, cell[0], cell[1]))
        return out

    def level(self, sid):
        var = self.win.sk_vars.get(sid)
        try:
            return max(0, min(255, int(var.get()))) if var is not None else 0
        except (ValueError, tk.TclError):
            return 0

    def levels(self):
        return {sid: self.level(sid) for sid in self.win.sk_vars}

    def set_level(self, sid, v):
        var = self.win.sk_vars.get(sid)
        if var is not None:
            var.set(str(max(0, min(255, int(v)))))
            self.win.update_dirty()

    def tables(self):
        return SD.tables(self.win.data)

    def unmet(self, sid, levels=None):
        """What the character lacks for the skill: [texts] (empty: it could be learned in game)."""
        t = self.tables()
        ch = self.win.ch
        out = []
        req = t.field(sid, 0x174, '<H')
        if req > getattr(ch, 'level', 1):
            out.append(T('sk.need_level', 'Character level {n}', n=req))
        levels = self.levels() if levels is None else levels
        for other in struct.unpack_from('<3h', t.sk[sid], 0x17e):
            if other >= 0 and not levels.get(other, 0) and other in self.win.sk_vars:
                out.append(T('sk.need_skill', 'a point in {s}', s=SD.split_colours(t.name(other))[0][0][0]))
        return out

    def is_passive(self, sid):
        return bool(self.tables().sk[sid][4] & 0x10)

    def points_left(self):
        try:
            return int(self.win.st_value('skill_points'))
        except Exception:
            try:
                return int(self.win.ch.stat(5))
            except Exception:
                return 0

    def tab_note(self):
        note = MC.skill_tab_note(self.win.data, self.cls or 0, int(self.tab)) if self.tab else None
        if self.tab == 0:
            note = T('he.skills_other', 'Other (not in a class tree)')
        return [ln for ln in (note or '').split('\n')]

    # ------------------------------------------------------------------ size
    def fit(self, W, H):
        """The whole panel in the space of the tab (it scales down; under MIN_K the page scrolls)."""
        k = max(MIN_K, min(W / PANEL_W, H / PANEL_H, MAX_K))
        k = round(k * 64) / 64
        if abs(k - self.k) > 1e-6 or self._photo is None and self._art:
            self.k = k
            self.cancel_edit()
            self.redraw()

    def redraw_later(self):
        if self._redraw_job is None:
            def go():
                self._redraw_job = None
                self.redraw()
            try:
                self._redraw_job = self.cv.after_idle(go)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ layout shared by both looks
    def layout(self):
        """Regions in panel coordinates: [(kind, key, (x, y, w, h))] for 'icon', 'lvl' and 'tab'."""
        reg = []
        for sid, row, col in self.cells():
            x, y = NODE_X + (col - 1) * NODE_DX, NODE_Y + (row - 1) * NODE_DY
            reg.append(('icon', sid, (x, y, NODE_W, LVL_BOX[1])))
            reg.append(('lvl', sid, (x + LVL_BOX[0], y + LVL_BOX[1], LVL_BOX[2], LVL_BOX[3])))
        tabs = [(t, n) for t, n, _c in self.trees if t > 0]
        if tabs:
            h = TAB_PITCH.get(len(tabs), TAB_SPAN // len(tabs))
            for i, (t, _n) in enumerate(tabs):
                reg.append(('tab', t, (TAB_X, TAB_Y + i * h, TAB_W, h)))
        return reg

    def redraw(self):
        if self.cls is None:
            return
        art = self.art()
        self._regions = self.layout()
        k = self.k
        cv = self.cv
        try:
            cv.configure(width=round(PANEL_W * k), height=round(PANEL_H * k))
            if art is not None:
                try:
                    self._draw_art(art)
                    self._art = True
                    return
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print('skill tree: game art drawing failed, plain look used:', e)
            self._art = False
            self._photo = None
            self._draw_plain()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ the game's look
    def _open(self, path):
        im = self._pil.get(path)
        if im is None:
            from PIL import Image
            im = self._pil[path] = Image.open(path).convert('RGBA')
        return im

    def icon(self, art_any, sid):
        """The 48 x 48 icon of a class skill as a PIL image (None without the game files)."""
        if not self._icons and art_any is not None:
            try:
                import mxl_d2ui_dc6 as DC6
                from PIL import Image
                base = 'data\\global\\themes\\classic_sigma\\game\\skills\\icons-'
                cels = DC6.dc6_frames(art_any.read(base + self.class_code() + '.dc6'))
                try:
                    shared = DC6.dc6_frames(art_any.read(base + 'shared.dc6'))
                except Exception:
                    shared = []
                pal = art_any.pal()
                for _t, _n, cells in self.trees:
                    for _r, _c, s, cel in cells:
                        fr = cels[cel] if cel < len(cels) else (shared[cel] if cel < len(shared) else None)
                        if fr is not None:
                            w, h, rgba = DC6.to_rgba(fr, pal)
                            self._icons[s] = Image.frombytes('RGBA', (w, h), bytes(art_any._bright(rgba)))
            except Exception as e:
                print('skill icons disabled:', e)
                self._icons = {None: None}
        return self._icons.get(sid)

    def _draw_art(self, art):
        from PIL import Image, ImageTk               # no ImageEnhance: the Windows exe's Pillow has no such module

        def dim(im, k):                              # brightness k < 1, alpha kept (ImageEnhance.Brightness's result)
            r, g, b, a = im.convert('RGBA').split()
            f = lambda v: int(v * k)
            return Image.merge('RGBA', (r.point(f), g.point(f), b.point(f), a))
        if self._text is None or self._text.art is not art:
            from mxl_statscreen import GameText
            self._text = GameText(art)
        tx = self._text
        out = Image.new('RGBA', (PANEL_W, PANEL_H), (0, 0, 0, 255))
        out.alpha_composite(self._open(art.panel('skill-tree')))
        if self.tab:
            try:
                out.alpha_composite(self._open(art.skill_web(self.class_code(), self.tab)))
            except Exception:
                pass                                   # a tree without a web (masteries, rewards)
        levels = self.levels()
        cells = {sid: (row, col) for sid, row, col in self.cells()}
        for sid, (row, col) in cells.items():
            x, y = NODE_X + (col - 1) * NODE_DX, NODE_Y + (row - 1) * NODE_DY
            rnd = self.is_passive(sid)
            lv = levels.get(sid, 0)
            unmet = bool(self.unmet(sid, levels))
            hidden = self.match is not None and sid not in self.match
            node = Image.new('RGBA', (NODE_W, NODE_H))
            node.alpha_composite(self._open(art.frame('skills\\socket', 1 if rnd else 0)), (ICON_OFF, ICON_OFF))
            ic = self.icon(art, sid)
            if ic is not None:
                if unmet and not lv:
                    ic = dim(ic, 0.7)
                node.alpha_composite(ic, (ICON_OFF, ICON_OFF))
            node.alpha_composite(self._open(art.frame('skills\\socket', 3 if rnd else 2)))
            tx.draw(node, f'{lv}/{lv}', NODE_W // 2, LVL_BOX[1] + LVL_BOX[3] // 2, 'font16',
                    WHITE if lv and not unmet else RED)
            if hidden:
                node = dim(node, 0.3)
            out.alpha_composite(node, (x, y))
            if ic is None or self.tab == 0:            # no picture (or the page outside the trees): the name
                nm = self.name(sid)
                nm = nm if len(nm) <= 15 else nm[:14] + '.'
                nm = nm if tx.has(nm, 'font6') else '?'
                tx.draw(out, nm, x + NODE_W // 2, y + (NODE_H + 8 if ic is not None else 30), 'font6', GOLD)
        tabs = [(t, n) for t, n, _c in self.trees if t > 0]
        fr = TAB_FRAMES.get(len(tabs))
        for kind, t, (x, y, w, h) in self._regions:
            if kind != 'tab':
                continue
            sel = t == self.tab
            name = next(n for tt, n in tabs if tt == t)
            if fr is not None:
                plate = self._open(art.frame('skills\\tree-tabs', fr + (1 if sel else 0)))
                out.alpha_composite(plate, (x, y + h - plate.height))     # the selected plate may be taller: bottom-aligned
            tx.draw(out, name if tx.has(name, 'font16') else '?', x + w // 2, y + h // 2, 'font16', GOLD if sel else DIM)
        tx.draw(out, str(self.points_left()), POINTS_AT[0], POINTS_AT[1], 'font16', WHITE)
        cap = T('sk.remaining', 'Remaining|Skill Points').split('|')
        for (x, y), s in zip(POINTS_CAPTION, cap):
            tx.draw(out, s if tx.has(s, 'font16') else '?', x, y, 'font16', GOLD)
        try:                                           # the close button of the game's panel (decoration here)
            out.alpha_composite(self._open(art.frame('buttons\\close', 0)), CLOSE_AT)
        except Exception:
            pass
        y = NOTE_AT[1]
        note = self.tab_note()
        for i, ln in enumerate(note):
            if ln.strip():
                s = ln if tx.has(ln, 'font16') else ln.encode('ascii', 'replace').decode()
                tx.draw(out, s, NOTE_AT[0], y, 'font16', GOLD if s.startswith('(') or len(note) == 1 else WHITE)
            y -= NOTE_DY
        self.last_image = out                          # the panel at the game's own size (tests compare it)
        size = (round(PANEL_W * self.k), round(PANEL_H * self.k))
        if size != out.size:
            out = out.resize(size, Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(out, master=self.cv)
        cv = self.cv
        cv.delete('plain')
        if not cv.find_withtag('art'):
            cv.create_image(0, 0, anchor='nw', tags=('art',))
        cv.itemconfigure('art', image=self._photo)
        cv.tag_lower('art')
        cv.configure(bg='#000000')
        self.frame.configure(bg='#000000')

    # ------------------------------------------------------------------ the plain look
    def name(self, sid):
        segs = SD.split_colours(self.tables().name(sid))[0]
        nm = ''.join(s for s, _c in segs)
        if not nm or 'POLAR BUFFALO' in nm.upper():    # the game's placeholder for an unnamed skill
            nm = T('skill.unknown', 'skill #{id}', id=sid)
        return nm

    def _draw_plain(self):
        from PIL import ImageTk
        cv = self.cv
        k = self.k
        dark = bool(self.win.dark.get())
        bg, fg, box, edge, sel, dim, red, line = (
            ('#14110c', '#d8c27a', '#0b0a08', '#4a3f26', '#2a2212', '#8a7a4a', '#ff4d4d', '#5a4a20') if dark else
            ('#f0f0f0', '#000000', '#ffffff', '#808080', '#d4d0c8', '#606060', '#c00000', '#909090'))
        cv.delete('art')
        cv.delete('plain')
        cv.configure(bg=bg)
        self.frame.configure(bg=bg)
        self._photo_plain = []
        font = ('Times New Roman', -max(9, round(12 * k)))
        small = ('Times New Roman', -max(8, round(10 * k)))
        bold = ('Times New Roman', -max(9, round(12 * k)), 'bold')
        P = lambda v: round(v * k)
        cv.create_rectangle(P(8), P(8), P(TAB_X - 8), P(PANEL_H - 8), outline=edge, fill=bg, tags='plain')
        levels = self.levels()
        cells = {sid: (row, col) for sid, row, col in self.cells()}
        t = self.tables()
        for sid, (row, col) in cells.items():          # prerequisite lines (the game's arrows)
            for other in struct.unpack_from('<3h', t.sk[sid], 0x17e):
                if other in cells:
                    (r0, c0), (r1, c1) = cells[other], (row, col)
                    cv.create_line(P(NODE_X + (c0 - 1) * NODE_DX + 30), P(NODE_Y + (r0 - 1) * NODE_DY + 30),
                                   P(NODE_X + (c1 - 1) * NODE_DX + 30), P(NODE_Y + (r1 - 1) * NODE_DY + 30),
                                   fill=line, width=max(1, P(3)), arrow='last', tags='plain')
        try:
            import mxl_d2look_art
            import settings
            import paths
            gd = settings.get('game_dir')
            any_art = mxl_d2look_art.get_art(gd, 'classic_sigma', os.path.join(paths.USER_DIR, 'ui_art')) \
                if gd and os.path.isdir(gd) else None
        except Exception:
            any_art = None
        for sid, (row, col) in cells.items():
            x, y = NODE_X + (col - 1) * NODE_DX, NODE_Y + (row - 1) * NODE_DY
            lv = levels.get(sid, 0)
            unmet = bool(self.unmet(sid, levels))
            hidden = self.match is not None and sid not in self.match
            x0, y0, x1, y1 = P(x + ICON_OFF), P(y + ICON_OFF), P(x + ICON_OFF + ICON), P(y + ICON_OFF + ICON)
            ic = self.icon(any_art, sid) if any_art is not None else None
            shape = cv.create_oval if self.is_passive(sid) else cv.create_rectangle
            shape(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline=edge, width=2, fill='#000000' if ic is not None else box,
                  tags='plain')
            if ic is not None and not hidden:
                im = ic.resize((max(8, x1 - x0), max(8, y1 - y0)))
                ph = ImageTk.PhotoImage(im, master=cv)
                self._photo_plain.append(ph)
                cv.create_image(x0, y0, anchor='nw', image=ph, tags='plain')
            elif not hidden:
                cv.create_text((x0 + x1) // 2, (y0 + y1) // 2, text=self.name(sid), width=x1 - x0 + P(30), font=small,
                               fill=fg, justify='center', tags='plain')
            bx, by, bw, bh = x + LVL_BOX[0], y + LVL_BOX[1], LVL_BOX[2], LVL_BOX[3]
            cv.create_rectangle(P(bx), P(by), P(bx + bw), P(by + bh), outline=edge, fill=box, tags='plain')
            cv.create_text(P(bx + bw / 2), P(by + bh / 2), text=str(lv), font=bold,
                           fill=dim if hidden else (fg if lv and not unmet else red), tags='plain')
        for kind, tb, (x, y, w, h) in self._regions:
            if kind != 'tab':
                continue
            on = tb == self.tab
            name = next(n for tt, n, _c in self.trees if tt == tb)
            cv.create_rectangle(P(x + 3), P(y + 3), P(x + w - 3), P(y + h - 3), outline=edge, width=2 if on else 1,
                                fill=sel if on else box, tags='plain')
            cv.create_text(P(x + w / 2), P(y + h / 2), text=name, font=bold if on else font, fill=fg if on else dim,
                           tags='plain')
        cv.create_text(P(POINTS_AT[0]), P(POINTS_AT[1]), text=str(self.points_left()), font=bold, fill=fg, tags='plain')
        cv.create_text(P(POINTS_AT[0]), P(POINTS_CAPTION[0][1] + 8), text=T('sk.remaining', 'Remaining|Skill Points').replace('|', '\n'),
                       font=font, fill=dim, justify='center', tags='plain')
        note = [ln for ln in self.tab_note()[::-1] if ln.strip()]
        if note:
            cv.create_text(P(NOTE_AT[0]), P(NOTE_AT[1] + 8), text='\n'.join(note), font=font, fill=dim, anchor='s',
                           justify='center', tags='plain')

    # ------------------------------------------------------------------ mouse
    def _at(self, ev):
        x, y = ev.x / self.k, ev.y / self.k
        for kind, key, (bx, by, bw, bh) in reversed(self._regions):
            if bx <= x < bx + bw and by <= y < by + bh:
                return kind, key
        return None, None

    def on_motion(self, ev):
        kind, key = self._at(ev)
        cur = {'icon': 'hand2', 'lvl': 'xterm', 'tab': 'hand2'}.get(kind, '')
        if self.cv.cget('cursor') != cur:
            self.cv.configure(cursor=cur)
        self.hover((kind, key) if kind in ('icon', 'lvl', 'tab') else None)

    def on_press(self, ev):
        kind, key = self._at(ev)
        if self.edit is not None and not self.commit_edit():
            return
        if kind == 'tab':
            self.show_tab(key)
        elif kind == 'lvl':
            self.start_edit(key)
        elif kind == 'icon':
            self.set_level(key, self.level(key) + (5 if ev.state & 1 else 1))
            self.refresh_tip()

    def on_right(self, ev):
        kind, key = self._at(ev)
        if kind in ('icon', 'lvl'):
            if self.edit is not None and not self.commit_edit():
                return
            self.set_level(key, self.level(key) - (5 if ev.state & 1 else 1))
            self.refresh_tip()

    def toggle_other(self):
        """The class's skills outside the trees (oSkills, procs, hidden skills): a page of their own."""
        if self.tab == 0:
            self.show_tab(next((t for t, _n, _c in self.trees if t > 0), 0))
        else:
            self._back = self.tab
            self.show_tab(0)

    def show_tab(self, tab):
        if tab != self.tab and any(t == tab for t, _n, _c in self.trees):
            self.cancel_edit()
            self.hide_tip()
            self.tab = tab
            self.redraw()

    def tab_of(self, sid):
        return next((t for t, _n, cells in self.trees if any(c[2] == sid for c in cells)), None)

    def set_filter(self, text):
        """Find box: the matching skills stay lit; the first tree with a match is shown."""
        text = (text or '').strip().lower()
        if not text:
            self.match = None
        else:
            self.match = {sid for sid in self.win.sk_vars if text in self.name(sid).lower()}
            here = {sid for sid, _r, _c in self.cells()}
            if self.match and not (self.match & here):
                first = min(self.match, key=lambda s: (self.tab_of(s) or 99, s))
                self.tab = self.tab_of(first)
        self.redraw()

    # ------------------------------------------------------------------ typing a level
    def order(self):
        return [sid for sid, _r, _c in sorted(self.cells(), key=lambda c: (c[1], c[2]))]

    def start_edit(self, sid):
        self.cancel_edit()
        self.hide_tip()
        box = next((b for kind, key, b in self._regions if kind == 'lvl' and key == sid), None)
        if box is None:
            return None
        x, y, w, h = box
        k = self.k
        e = tk.Entry(self.cv, font=('Times New Roman', -max(9, round(13 * k)), 'bold'), bd=0, relief='flat',
                     bg='#0d0c0b', fg='#e6e6e6', insertbackground='#e6e6e6', selectbackground='#4a1712',
                     selectforeground='#ffffff', highlightthickness=1, highlightbackground='#6f5a3a',
                     highlightcolor='#c7b377', justify='center')
        e.insert(0, str(self.level(sid)))
        e.select_range(0, 'end')
        item = self.cv.create_window(round(x * k), round(y * k), anchor='nw', window=e,
                                     width=max(24, round(w * k)), height=max(14, round(h * k)))
        self.edit = (sid, e, item, self.level(sid))
        self._closing = False
        e.bind('<KeyRelease>', lambda _e: self._typed())
        e.bind('<Return>', lambda _e: (self.commit_edit(), 'break')[1])
        e.bind('<KP_Enter>', lambda _e: (self.commit_edit(), 'break')[1])
        e.bind('<Escape>', lambda _e: (self.cancel_edit(restore=True), 'break')[1])
        e.bind('<FocusOut>', lambda _e: self.commit_edit(leaving=True))
        e.bind('<Tab>', lambda _e: (self.next_edit(1), 'break')[1])
        e.bind('<ISO_Left_Tab>', lambda _e: (self.next_edit(-1), 'break')[1])
        e.bind('<Shift-Tab>', lambda _e: (self.next_edit(-1), 'break')[1])
        e.bind('<Up>', lambda ev: (self.step_edit(10 if ev.state & 1 else 1), 'break')[1])
        e.bind('<Down>', lambda ev: (self.step_edit(-10 if ev.state & 1 else -1), 'break')[1])
        e.focus_set()
        return e

    def _typed(self):
        """A valid number is the level at once (SAVE needs no extra Enter); Escape puts the old one back."""
        if self.edit is None:
            return
        sid, e = self.edit[0], self.edit[1]
        try:
            v = int(e.get().strip() or 0)
        except (ValueError, tk.TclError):
            return
        if 0 <= v <= 255 and v != self.level(sid):
            self.set_level(sid, v)

    def step_edit(self, n):
        if self.edit is None:
            return
        sid, e = self.edit[0], self.edit[1]
        try:
            v = int(e.get().strip())
        except ValueError:
            v = self.level(sid)
        e.delete(0, 'end')
        e.insert(0, str(max(0, min(255, v + n))))
        e.select_range(0, 'end')
        self._typed()

    def commit_edit(self, leaving=False):
        """Stores the typed level. Not a number 0-255: the entry stays (Enter / Tab) or is dropped (focus left)."""
        if self.edit is None or self._closing:
            return True
        sid, e = self.edit[0], self.edit[1]
        try:
            text = e.get().strip()
            v = int(text) if text else 0
            ok = 0 <= v <= 255
        except (ValueError, tk.TclError):
            ok = False
        if ok or leaving:
            self.cancel_edit()
            if ok:
                self.set_level(sid, v)
            return ok
        try:
            self.win.set_bar(T('sk.bad_level', 'A skill level is a number from 0 to 255.'), error=True)
            e.select_range(0, 'end')
            e.focus_set()
        except Exception:
            pass
        return False

    def cancel_edit(self, restore=False):
        if self.edit is None:
            return
        sid, e, item, old = self.edit
        self.edit = None
        if restore:
            self.set_level(sid, old)
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
        sid = self.edit[0]
        if not self.commit_edit():
            return
        order = self.order()
        if sid in order:
            self.start_edit(order[(order.index(sid) + step) % len(order)])

    def flush(self):
        """A level still being typed is stored (SAVE); False when it is refused."""
        return self.commit_edit()

    # ------------------------------------------------------------------ tooltip
    def tip_rows(self, what):
        """[[(text, '#colour')]] of the tooltip for ('icon' | 'lvl', sid) or ('tab', tab)."""
        kind, key = what
        if kind == 'tab':
            if key == 0:
                return [[(T('he.skills_other', 'Other (not in a class tree)'), '#c7b377')],
                        [(T('sk.other_tip', 'oSkills, procs and hidden skills of the class'), '#ffffff')]]
            name = next((n for t, n, _c in self.trees if t == key), '')
            rows = [[(T('he.skills_tree_of', '{n} tree', n=name), '#c7b377')]]
            for ln in [ln for ln in (MC.skill_tab_note(self.win.data, self.cls or 0, key) or '').split('\n')[::-1]
                       if ln.strip()]:
                rows.append([(ln, '#ffffff')])
            return rows
        win = self.win
        ch = win.ch
        levels = self.levels()
        stats = {}
        for sid in (0, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15):
            try:
                stats[sid] = int(ch.stat(sid))
            except Exception:
                pass
        t = self.tables()
        calc = SD.Calc(t, levels, getattr(ch, 'level', 1), stats)
        try:
            tip = SD.Composer(t, calc).tooltip(key)
        except Exception as e:                         # a table the editor cannot read: the name still shows
            print('skill tooltip failed:', key, e)
            return [[(self.name(key), '#00ff00')]]
        unmet = self.unmet(key, levels)
        body = '#ff4d4d' if unmet else '#ffffff'
        base = {'name': '#00ff00', 'desc': '#ffffff', 'req': body, 'level': body, 'line': body, 'head': '#c7b377',
                'raw': '#7a7a7a', 'blank': body}
        rows = []
        for segs, kind_ in tip.lines:
            col = base.get(kind_, body)
            if kind_ == 'req' and t.field(key, 0x174, '<H') <= getattr(ch, 'level', 1):
                col = '#ffffff'
            if kind_ == 'raw':
                rows.append([(''.join(s for s, _c in segs), col)])
            else:
                rows.append([(s, SD.COLOURS.get(c, col) if c is not None else col) for s, c in segs])
        notes = []
        if unmet:
            notes.append(T('sk.tip_unmet', 'In game this needs: {what}', what=', '.join(unmet)))
        if tip.raw:
            notes.append(T('sk.tip_raw', 'Grey lines: the raw table entry (not understood by the editor).'))
        # what the numbers leave out, said exactly (the levels of the character's other skills ARE counted)
        if tip.used_stats:
            notes.append(T('sk.tip_stats', 'Uses the saved character stats: bonuses from items and charms are not included.'))
        if 'synergy' in tip.assumed:
            notes.append(T('sk.tip_items', 'Not included: bonuses that items give to this skill.'))
        if 'mastery' in tip.assumed:                   # "+x% to Fire Spell Damage" ...: how the game adds it
            notes.append(T('sk.tip_mastery', 'Not included: spell damage bonuses (masteries) from items and skills.'))
        if tip.assumed & {'aura', 'state', 'place'}:
            notes.append(T('sk.tip_rest', 'For a character at rest in town: no buff, aura or charge active.'))
        if notes:
            rows.append([])
            rows += [[(n, '#7a7a7a')] for n in notes]
        return rows

    def hover(self, what):
        if what == self._tip_for:
            if self._tip_win is not None and self._tipper is not None:
                self._tipper.show(self.cv)          # follows the pointer; a pending delayed hide is cancelled
            return
        self.hide_tip()
        self._tip_for = what
        if what is None or self.edit is not None:
            return
        try:
            self._tip_job = self.cv.after(TIP_DELAY, self._show_tip)
        except tk.TclError:
            pass

    def refresh_tip(self):
        """The level under the pointer changed: the open tooltip shows the new numbers at once."""
        what = self._tip_for
        if what is not None and self._tip_win is not None and self._tipper is not None:
            self._tipper.show(self.cv, key=what, force=True)        # a fresh window at the new size

    def hide_tip(self):
        if self._tip_job is not None:
            try:
                self.cv.after_cancel(self._tip_job)
            except tk.TclError:
                pass
            self._tip_job = None
        self._tip_for = None
        if self._tipper is not None:
            self._tipper.hide()
        self._tip_win = None

    def _leave(self):
        """<Leave> of the tree: the tip goes a moment later, when the pointer really left (mxl_floattip)."""
        if self._tip_job is not None:
            try:
                self.cv.after_cancel(self._tip_job)
            except tk.TclError:
                pass
            self._tip_job = None
        if self._tipper is not None and self._tipper.shown:
            self._tipper.leave(self.cv)
        else:
            self._tip_for = None

    def _tip_gone(self):
        """The delayed hide happened: the next hover shows the tip again."""
        self._tip_for = None
        self._tip_win = None

    def _show_tip(self):
        self._tip_job = None
        what = self._tip_for
        if what is None:
            return
        try:
            import mxl_floattip
            tip = self._tipper
            if tip is None:
                tip = self._tipper = mxl_floattip.FloatTip(self.win.top, build=self._build_tip, gap=(20, 22, 14),
                                                           within=self.win.top, alpha=0.9, bg='#000000',
                                                           edge='#3a3020')
                tip.on_hide = self._tip_gone
            tip.show(self.cv, key=what, force=True)
            if not tip.shown:
                self._tip_win = None
        except tk.TclError:
            self._tip_win = None

    def _build_tip(self, body):
        """The content of a fresh tip window (mxl_floattip calls it for every new window)."""
        self._tip_win = body
        self._tip_label = tk.Label(body, bg='#000000', bd=0, highlightthickness=0)
        self._tip_label.pack()
        self._fill_tip(self._tip_for)

    def _wrap(self, rows, measure, limit):
        """Folds rows wider than limit at spaces (colours kept)."""
        out = []
        for row in rows:
            if sum(measure(s) for s, _c in row) <= limit:
                out.append(row)
                continue
            cur, width = [], 0
            for s, c in row:
                for word in s.replace(' ', ' \0').split('\0'):
                    wd = measure(word)
                    if cur and width + wd > limit:
                        out.append(cur)
                        cur, width = [], 0
                    if cur and cur[-1][1] == c:
                        cur[-1] = (cur[-1][0] + word, c)
                    else:
                        cur.append((word, c))
                    width += wd
            out.append(cur)
        return out

    def _fill_tip(self, what):
        """Draws the rows into one image: the game font with the game's art, else a Tk font."""
        from PIL import Image, ImageTk
        rows = self.tip_rows(what)
        art = self.art()
        pad = 8
        if art is not None and self._text is not None:
            tx = self._text
            fix = lambda s: s if tx.has(s, 'font16') else ''.join(ch if tx.has(ch, 'font16') else '?' for ch in s)
            rows = [[(fix(s), c) for s, c in row] for row in rows]
            rows = self._wrap(rows, lambda s: tx.line(s, 'font16', WHITE)[0].width + 2 if s.strip() else 5 * len(s), TIP_WRAP)
            lh = 16
            parts = []
            for row in rows:
                imgs = [(tx.line(s, 'font16', _rgb(c)), s) for s, c in row if s]
                parts.append(imgs)
            width = max([sum((im.width if s.strip() else 5 * len(s)) + 2 for (im, _cap), s in p) for p in parts] + [40])
            out = Image.new('RGBA', (width + 2 * pad, lh * len(parts) + 2 * pad - 2), (0, 0, 0, 255))
            y = pad + lh // 2
            for p in parts:
                x = (out.width - sum((im.width if s.strip() else 5 * len(s)) + 2 for (im, _cap), s in p)) // 2
                for (im, cap), s in p:
                    if s.strip():
                        lead = (len(s) - len(s.lstrip())) * 5
                        out.alpha_composite(im, (x + lead, int(round(y - cap))))
                        x += im.width + 2 + lead + (len(s) - len(s.rstrip())) * 5
                    else:
                        x += 5 * len(s) + 2
                y += lh
            self._tip_photo = ImageTk.PhotoImage(out.convert('RGB'), master=self._tip_win)
        else:
            font = tkfont.Font(family='Times New Roman', size=-13)
            rows = self._wrap(rows, font.measure, TIP_WRAP)
            lh = font.metrics('linespace') + 1
            width = max([sum(font.measure(s) for s, _c in row) for row in rows] + [40])
            from PIL import ImageDraw
            # Tk text cannot be drawn into an image: a canvas takes its place
            w = self._tip_win
            for c in w.winfo_children():
                c.destroy()
            cv = tk.Canvas(w, bg='#000000', highlightthickness=0, bd=0,
                           width=width + 2 * pad, height=lh * len(rows) + 2 * pad)
            cv.pack()
            self._tip_label = cv
            y = pad
            for row in rows:
                x = pad + (width - sum(font.measure(s) for s, _c in row)) // 2
                for s, c in row:
                    cv.create_text(x, y, text=s, fill=c, font=font, anchor='nw')
                    x += font.measure(s)
                y += lh
            return
        self._tip_label.configure(image=self._tip_photo)

    def _place_tip(self):
        """Beside the pointer, inside the Character window (inside the screen when the window is too small),
        never under the pointer (mxl_floattip)."""
        if self._tipper is not None and self._tip_win is not None:
            self._tipper.place()
