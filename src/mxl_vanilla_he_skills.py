"""Compact vanilla skill tiles backed by the existing skill editing engine."""
import tkinter as tk

import mxl_profile
from mxl_skilltree import SkillTree
from mxl_vanilla_he import (
    BLACK, DESCRIPTION, EDGE, FORM, INSET, SELECT, WHITE, CLASS_ART, LEGEND_FONT,
    font, game_art, native_frames,
)


LOD_TREES = (
    ('Bow and Crossbow', 'Passive and Magic', 'Javelin and Spear'),
    ('Fire Spells', 'Lightning Spells', 'Cold Spells'),
    ('Curses', 'Poison and Bone', 'Summoning'),
    ('Combat Skills', 'Offensive Auras', 'Defensive Auras'),
    ('Combat Skills', 'Combat Masteries', 'Warcries'),
    ('Summoning', 'Shape Shifting', 'Elemental'),
    ('Traps', 'Shadow Disciplines', 'Martial Arts'),
)


class VanillaSkillTree(SkillTree):
    def __init__(self, parent, win):
        super().__init__(parent, win)
        self.current = None
        self.any_art = game_art()
        profile = mxl_profile.active() or {}
        version = profile.get('version') or ''
        self.lod_titles = profile.get('kind') == 'd2' and version.startswith('1.14') and not profile.get('mods')
        self.cv.pack_configure(anchor='n', expand=False)
        control = tk.Frame(self.frame)
        control.pack(fill='x', padx=6, pady=(2, 0))
        self.selected_name = tk.Label(control, width=20, anchor='w')
        self.selected_name.pack(side='left', padx=3)
        self.slider_value = tk.IntVar()
        self.level_scale = tk.Scale(control, from_=0, to=20, orient='horizontal', showvalue=True, tickinterval=5,
                                    length=240, variable=self.slider_value, command=self._set_current)
        self.level_scale.pack(side='left', fill='x', expand=True)
        self.points = tk.Label(control, width=16)
        self.points.pack(side='right')

    def _set_current(self, value):
        if self.current in self.win.sk_vars:
            self.set_level(self.current, int(value))

    def fit(self, W, H):
        pass

    def rebuild(self):
        self.current = None
        self.selected_name.configure(text='')
        self.slider_value.set(0)
        self.photos = {}
        super().rebuild()
        cells = self.cells()
        if cells:
            self.select_skill(cells[0][0])
            self.redraw()

    def select_skill(self, sid):
        self.current = sid
        self.selected_name.configure(text=self.name(sid))

    def native_icon(self, sid, index):
        from PIL import Image
        from mxl_d2ui_dc6 import to_rgba

        if sid not in self._icons and self.any_art is not None and 0 <= self.cls < len(CLASS_ART):
            _folder, code = CLASS_ART[self.cls]
            code = 'Dr' if code == 'DZ' else code.title()
            frames, pal = native_frames(self.any_art, f'SPELLS\\{code}Skillicon.dc6')
            if 0 <= index < len(frames):
                width, height, rgba = to_rgba(frames[index], pal)
                self._icons[sid] = Image.frombytes('RGBA', (width, height), bytes(rgba))
            else:
                self._icons[sid] = None
        return self._icons.get(sid)

    def redraw(self):
        if self.cls is None:
            return
        from PIL import ImageTk

        canvas = self.cv
        canvas.delete('tiles')
        self._regions = []
        trees = [(tab, title, cells) for tab, title, cells in self.trees if (tab == 0) == (self.tab == 0)]
        width = 212
        rows = max((len(cells) + 1) // 2 for _tab, _title, cells in trees) if trees else 0
        height = rows * 60 + 20
        canvas.configure(width=max(1, len(trees)) * width, height=height, bg=FORM)
        for panel, (tab, title, cells) in enumerate(trees):
            if self.lod_titles and 0 <= self.cls < len(LOD_TREES) and 1 <= tab <= 3:
                title = LOD_TREES[self.cls][tab - 1]
            left = panel * width + 3
            canvas.create_rectangle(left, 9, left + width - 7, height - 2, outline=EDGE, tags='tiles')
            canvas.create_text(left + 4, 9, anchor='w', text=title, font=font(LEGEND_FONT),
                               fill=BLACK, tags='tiles')
            for i, (_row, _column, sid, icon_index) in enumerate(sorted(cells, key=lambda cell: cell[:3])):
                x, y = left + 6 + i % 2 * 101, 20 + i // 2 * 60
                hidden = self.match is not None and sid not in self.match
                canvas.create_rectangle(x, y, x + 49, y + 49, fill='#302419',
                                        outline=SELECT if self.current == sid else '#907148', tags='tiles')
                icon = self.native_icon(sid, icon_index) if not hidden else None
                if icon is not None:
                    if sid not in self.photos:
                        self.photos[sid] = ImageTk.PhotoImage(icon.resize((46, 46)), master=canvas)
                    canvas.create_image(x + 2, y + 2, image=self.photos[sid], anchor='nw', tags='tiles')
                elif not hidden:
                    canvas.create_text(x + 25, y + 25, text=self.name(sid), width=46,
                                       fill=WHITE, font=font(), tags='tiles')
                canvas.create_rectangle(x + 52, y + 16, x + 92, y + 34, fill=WHITE, outline=INSET, tags='tiles')
                canvas.create_text(x + 72, y + 25, text=str(self.level(sid)), font=font(),
                                   fill=DESCRIPTION if hidden else BLACK, tags='tiles')
                self._regions.extend((('icon', sid, (x, y, 50, 50)), ('lvl', sid, (x + 52, y + 16, 40, 18))))
        if self.current in self.win.sk_vars:
            level = self.level(self.current)
            self.level_scale.configure(to=max(20, level))
            self.slider_value.set(level)
        self.points.configure(text=f'Skill Points\n{self.points_left()}')

    def on_press(self, event):
        kind, sid = self._at(event)
        if kind in ('icon', 'lvl'):
            self.select_skill(sid)
            self.redraw_later()
        return super().on_press(event)
