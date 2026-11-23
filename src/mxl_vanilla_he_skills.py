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
        self.cv.pack_configure(anchor='nw', expand=False)
        footer = tk.Frame(self.frame, width=640, height=99)
        footer.pack(fill='x', pady=(4, 0))
        footer.pack_propagate(False)
        control = tk.Frame(footer, relief='groove', bd=1)
        control.place(x=2, y=0, width=494, height=98)
        self.selected_icon = tk.Label(control, bd=0)
        self.selected_icon.place(x=7, y=8, width=50, height=50)
        self.selected_level = tk.Label(control, bg=WHITE, bd=1, relief='sunken')
        self.selected_level._vanilla_he_role = 'art'
        self.selected_level.configure(font=font())
        self.selected_level.place(x=7, y=63, width=50, height=18)
        self.selected_name = tk.Label(control)
        self.selected_name.place(x=70, y=5, width=413, height=20)
        self.slider_value = tk.IntVar()
        self.level_scale = tk.Scale(control, from_=0, to=20, orient='horizontal', showvalue=False, tickinterval=1,
                                    sliderlength=12, highlightthickness=0, variable=self.slider_value,
                                    command=self._set_current)
        self.level_scale.place(x=70, y=59, width=411)
        batch = tk.Frame(footer, relief='groove', bd=1)
        batch.place(x=504, y=0, width=136, height=98)
        self.batch_level = tk.Spinbox(batch, from_=0, to=255, width=4, justify='center')
        self.batch_level.place(x=6, y=8, width=34)
        tk.Button(batch, text='Set Skills', pady=0, command=self.set_all).place(x=46, y=8, width=82)
        self.points = tk.Label(batch)
        self.points.place(x=6, y=39, width=120, height=48)

    def set_all(self):
        try:
            level = int(self.batch_level.get())
        except ValueError:
            return
        for sid in self.win.sk_vars:
            self.set_level(sid, level)

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
        width = 216
        rows = max((len(cells) + 1) // 2 for _tab, _title, cells in trees) if trees else 0
        height = rows * 66 + 2
        canvas.configure(width=max(1, len(trees)) * width - 4, height=height, bg=FORM)
        for panel, (tab, title, cells) in enumerate(trees):
            if self.lod_titles and 0 <= self.cls < len(LOD_TREES) and 1 <= tab <= 3:
                title = LOD_TREES[self.cls][tab - 1]
            left = panel * width + 2
            canvas.create_rectangle(left, 4, left + width - 8, height - 2, outline=EDGE, tags='tiles')
            canvas.create_text(left + 4, 5, anchor='w', text=title, font=font(LEGEND_FONT),
                               fill=BLACK, tags='tiles')
            column_rows = (len(cells) + 1) // 2
            for i, (_row, _column, sid, icon_index) in enumerate(sorted(cells, key=lambda cell: cell[2])):
                column, row = divmod(i, column_rows)
                x, y = left + 8 + column * 96, 12 + row * 65
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
                canvas.create_rectangle(x + 50, y + 17, x + 95, y + 34, fill=WHITE, outline=INSET, tags='tiles')
                canvas.create_text(x + 73, y + 25, text=str(self.level(sid)), font=font(),
                                   fill=DESCRIPTION if hidden else BLACK, tags='tiles')
                self._regions.extend((('icon', sid, (x, y, 50, 50)), ('lvl', sid, (x + 50, y + 17, 46, 18))))
        if self.current in self.win.sk_vars:
            level = self.level(self.current)
            self.level_scale.configure(to=max(20, level))
            self.slider_value.set(level)
            self.selected_level.configure(text=str(level))
            self.selected_icon.configure(image=self.photos.get(self.current, ''))
        self.points.configure(text=f'Skill Points\n{self.points_left()}')

    def on_press(self, event):
        kind, sid = self._at(event)
        if kind in ('icon', 'lvl'):
            self.select_skill(sid)
            self.redraw_later()
        return super().on_press(event)
