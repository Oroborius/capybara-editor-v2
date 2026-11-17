"""A frame whose content scrolls when the window is too small for it - and only then.

The editor's pages were laid out for one large window; in a small one pack / grid simply cut off what did not
fit (buttons at the bottom included). Scrolled gives a page an `inner` frame to build into: while the room is
enough, inner fills it exactly as a plain frame would (so expanding content keeps expanding); when inner asks for
more than there is, it keeps the size it asks for and scrollbars appear on the side that is short."""
import tkinter as tk
from tkinter import ttk

NO_WHEEL = ('Listbox', 'Text', 'Treeview', 'TCombobox', 'Spinbox', 'TSpinbox', 'TScale', 'Scale')


class Scrolled(tk.Frame):
    def __init__(self, parent, bg=None, horizontal=True, **kw):
        super().__init__(parent, **kw)
        if bg is None:
            bg = self.cget('bg')
        self.configure(bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, width=10, height=10,
                                yscrollincrement=16, xscrollincrement=16)
        self.vbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self._horizontal = horizontal
        self._job = None
        self._shown = (False, False)
        self.canvas.bind('<Configure>', self._later)
        self.inner.bind('<Configure>', self._later)
        self._wheel_id = None
        # the wheel: a binding tag of its own given to every widget inside (bind_all is taken, and dropped
        # again, by other scroll areas of the editor)
        self._tag = 'MxlScrolled%d' % id(self)
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.bind_class(self._tag, seq, self._wheel)
        self._tag_all(self)

    def set_bg(self, bg):
        for w in (self, self.canvas, self.inner):
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ layout
    def refresh(self):
        """To call when the content asks for another size (a page was swapped): Tk reports nothing by itself
        while inner is held at the size given to it."""
        self._later()

    def _later(self, _e=None):
        if self._job is None:
            try:
                self._job = self.after_idle(self._fit)
            except tk.TclError:
                pass

    def _fit(self):
        self._job = None
        try:
            if not self.winfo_exists():
                return
            W, H = self.winfo_width(), self.winfo_height()
            if W < 4 or H < 4:
                return
            rw, rh = self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()
            bw = self.vbar.winfo_reqwidth()
            bh = self.hbar.winfo_reqheight()
            need_h = self._horizontal and rw > W
            need_v = rh > H - (bh if need_h else 0)
            if need_v and self._horizontal and rw > W - bw:
                need_h = True
            if (need_v, need_h) != self._shown:
                self._shown = (need_v, need_h)
                if need_v:
                    self.vbar.grid(row=0, column=1, sticky='ns')
                else:
                    self.vbar.grid_remove()
                if need_h:
                    self.hbar.grid(row=1, column=0, sticky='ew')
                else:
                    self.hbar.grid_remove()
            cw = W - (bw if need_v else 0)
            ch = H - (bh if need_h else 0)
            w = max(cw, rw) if self._horizontal else cw
            h = max(ch, rh)
            self.canvas.itemconfigure(self._win, width=w, height=h)
            self.canvas.configure(scrollregion=(0, 0, w, h))
            if not need_v:
                self.canvas.yview_moveto(0)
            if not need_h:
                self.canvas.xview_moveto(0)
            self._tag_all(self)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ mouse wheel
    def _tag_all(self, w):
        try:
            if w.winfo_class() not in NO_WHEEL:      # those scroll themselves
                tags = w.bindtags()
                if self._tag not in tags:
                    w.bindtags((self._tag,) + tuple(tags))
            for c in w.winfo_children():
                self._tag_all(c)
        except tk.TclError:
            pass

    def _wheel(self, ev):
        try:
            if not self._shown[0]:
                return
            if getattr(ev, 'num', 0) == 4:
                d = -1
            elif getattr(ev, 'num', 0) == 5:
                d = 1
            else:
                d = -1 if ev.delta > 0 else 1
            self.canvas.yview_scroll(d * 3, 'units')
        except (tk.TclError, AttributeError):
            pass
