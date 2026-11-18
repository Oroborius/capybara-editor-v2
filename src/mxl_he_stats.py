"""Hero Editor v1.04-style "Magic Attributes" list for one item (the "Item stats" tab).

Left: the item's attribute slots, one compact numbered row per stored stat (the game's own stat text, the
value, and - where the stat carries one - the cast level and the skill / class by NAME), followed by
"(empty)" slots (the save format ends a stat list with a marker and has no fixed slot count: the used slots
plus empty ones are shown, at least SLOTS_MIN). Right: the attribute picker of mxl_attr_picker (categories |
stats, one filter over all categories); it turns into a skill / class name list while a row's skill is chosen.

Keys in the slot list: Up / Down / PgUp / PgDn / Home / End move; Enter or a double-click opens the picker
for the slot (pick = replace the slot's stat, or fill an empty slot); Delete clears the slot; typing a number
(or F2) edits the value in place; Right / Left walk the row's editable cells; typing letters starts the
picker's filter; Ctrl+S saves. In a value box: Enter writes, Tab goes to the row's next cell, Up / Down keep
the typed value and move, Escape gives up.

The engine is the one of the former flat table:
- "Save changes" (or Enter in a value box) writes changed values of a stash item in place through
  mxl_save.apply_edits - one file write, verification, .bak backup; linked stats (the groups the game keeps
  together, like enhanced damage base + average) are written with the collector's own set_stat logic;
  the value of a stat with a parameter (and of the innate-damage stats that logic refuses, e.g. 415) is
  written like a changed parameter instead: see needs_reencode;
- an added, replaced or cleared slot (and a changed skill / level / param) rewrites the item's bytes through
  a lossless decode -> encode round trip via mxl_save.edit_stash, at the item's own place - its socketed
  items follow; the main window is reloaded then, as offsets shift;
- a character's item (equipment, mercenary, inventory) is re-encoded in the character's entry and saved
  through the character window;
- values: anything the save format stores (ItemStatCost save bits / add); the game's affix ranges are ignored
  on purpose (unrestricted build). A value the format cannot store is capped to what it can, never written
  wrong; a stat stored by an auto-affix tier can only take one of its tier values (the status bar says so).

Everything goes through the collector's own safe writers (verification, backups), never direct file writes.
"""
import os

import tkinter as tk
import tkinter.ttk as ttk

import mxl_save
from mxl_save import edit_stash, apply_edits, EditError
from mxl_format import FormatError
from mxl_rules import stat_hidden, is_innate_damage
from mxl_lang import T
from mxl_creator import decode_blob, build_blob
from mxl_statnames import (stat_text, param_kind, decode_param, encode_skill_param, skill_names_sorted,
                           param_bits, param_choices, param_title, param_spec, param_name)
import mxl_attr_picker as AP

from mxl_attr_slots import (AttrSlots, SLOTS_MIN, SLOTS_SPARE, he, value_range, info_bits, slot_row,
                            section_rows, stat_info as _stat_info, row_label as _row_label,
                            row_info_text as _row_info_text)

TAB_KEY = 'Item stats'


def needs_reencode(data, sid):
    """True for a stat whose VALUE the collector's in-place editor (mxl_save.set_stat) must not be asked to
    write on a stash item: a stat with parameter bits (that editor finds a stat's linked partners by id alone and
    knows no param layouts) and the innate-damage stats it refuses outright (description function 35, e.g. 415
    whose param packs element | attribute << 8). Their value goes through the lossless decode -> encode path."""
    try:
        if param_bits(data, sid):
            return True
        return bool(is_innate_damage(sid, data))
    except Exception:
        return True


class ItemStatsWindow:
    """The Magic Attributes list + attribute picker of one item: a tab of the main window (a Toplevel when the
    tabs are not installed). it: an item of the stash grid; chwin + entry: an item of the character window."""

    def __init__(self, app, it=None, chwin=None, entry=None):
        self.app = app
        self.chwin, self.entry = chwin, entry
        self.it = dict(it if it is not None else entry.it)
        self.cr = None
        self._bak = None
        self.pal = pal = AP.palette()
        self.m = m = AP.metrics(app.root)
        self.lists = []                       # [(stat_list, [stored entries])]
        self.pending = {}                     # {(stat_list, index): typed value not written yet}
        self._pick_mode = None                # (row index) while the right pane lists skill / class names

        try:
            import mxl_tabs
            top = mxl_tabs.host_window(app, TAB_KEY, owner=self, replace=True)
        except Exception:
            top = None
        if top is None:
            top = tk.Toplevel(app.root)
            ch, row = m['ch'], m['row']
            sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
            w, h = min(ch * 124, sw - 24), min(row * 36, sh - 64)
            top.geometry(f'{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}')
        self.top = top
        top.title(he('title', 'Item stats'))
        ch = m['ch']

        root = self.frame = tk.Frame(top, bg=pal['bg'])
        AP.exempt(root)
        root.pack(fill='both', expand=True, padx=3, pady=2)
        root.columnconfigure(0, weight=1, uniform='half')
        root.columnconfigure(1, weight=1, uniform='half')
        root.rowconfigure(1, weight=1)

        head = tk.Frame(root, bg=pal['bg'])
        head.grid(row=0, column=0, columnspan=2, sticky='we', pady=(0, 2))
        tk.Label(head, text=he('magic', 'Magic Attributes'), font=m['bold'], bg=pal['bg'], fg=pal['fg_hi']
                 ).pack(side='left')
        self.name_lab = tk.Label(head, text=self._name(), font=m['font'], bg=pal['bg'], fg=pal['fg'], anchor='w')
        self.name_lab.pack(side='left', padx=(ch, 0))
        for txt, cmd in ((he('close', 'Close'), self.close),
                         (he('clear', 'Clear slot'), self.delete_selected),
                         (he('pick', 'Pick...'), self.open_picker),
                         (he('save', 'Save changes'), self.save)):
            AP.button(head, txt, cmd, pal, m).pack(side='right', padx=(2, 0))

        # ---- the slot list (mxl_attr_slots: the widget the Item Creator uses too)
        left = tk.Frame(root, bg=pal['bg'])
        left.grid(row=1, column=0, sticky='nsew', padx=(0, 3))
        self.slots = AttrSlots(left, app.data, self)
        self.hdr, self.cv, self.ed, self.ed_var = self.slots.hdr, self.slots.cv, self.slots.ed, self.slots.ed_var
        cv = self.cv

        # ---- the right pane: attribute picker / name list, stacked
        right = self.right = tk.Frame(root, bg=pal['bg'])
        right.grid(row=1, column=1, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.picker = AP.AttrPicker(right, app.data, on_pick=self.picked, on_cancel=self.focus_list,
                                    choices=self._creator().stat_choices())
        self.picker.grid(row=0, column=0, sticky='nsew')
        self.names = AP.ChoiceList(right, on_pick=self._name_picked, on_cancel=self._name_cancel)
        self.names.grid(row=0, column=0, sticky='nsew')
        self.picker.tkraise()

        self.bar = tk.Label(root, text='', font=m['font'], bg=pal['bar'], fg=pal['bar_fg'], anchor='w', padx=4)
        self.bar.grid(row=2, column=0, columnspan=2, sticky='we', pady=(2, 0))

        self.load_rows()
        self.select(self._first_slot())
        self._say(he('hint', 'Enter: pick attribute   Del: clear slot   0-9: edit value   letters: find'))
        top.protocol('WM_DELETE_WINDOW', self.close)
        try:
            cv.focus_set()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.top.destroy()
        except tk.TclError:
            pass

    def _name(self):
        try:
            return self.app.full_name(self.it)
        except Exception:
            return self.it.get('name') or self.it.get('code') or 'item'

    def _creator(self):
        if self.cr is None:
            import mxl_creator as m
            self.cr = m.Creator(self.app.data)
        return self.cr

    # ------------------------------------------------------------ rows
    def load_rows(self):
        """Reads the item's stats: from the stash file itself (exactly what is on disk) for a stash item, from
        the character's entry for one of its items. Typed values not written yet are dropped."""
        self._close_editor()
        if self.entry is not None:
            blob = self.entry.blob
        else:
            buf = open(self.app.path, 'rb').read()
            blob = mxl_save.item_blob(buf, self.it)
        self.rec, self.kids = decode_blob(blob, self.app.data)
        self.pending = {}
        self._build_rows()

    def _build_rows(self):
        """The display rows from self.rec: [runeword header + slots +] the item's slots + empty slots."""
        data = self.app.data
        rows, lists = [], []
        sections = []
        if self.rec.get('stats_runeword'):
            sections.append(('stats_runeword', he('rw_stats', "The runeword's stats")))
            sections.append(('stats', he('own_stats', "The item's stats")))
        else:
            sections.append(('stats', None))
        for stat_list, title in sections:
            entries = list(self.rec.get(stat_list) or [])
            lists.append((stat_list, entries))
            rows += section_rows(data, stat_list, entries, title, None if stat_list == 'stats' else 2)
        self.lists = lists
        try:
            self.name_lab.configure(text=self._name())
        except tk.TclError:
            pass
        self.slots.set_rows(rows)

    # ------------------------------------------------------------ the slot list (see mxl_attr_slots)
    rows = property(lambda self: self.slots.rows)
    sel = property(lambda self: self.slots.sel, lambda self, n: setattr(self.slots, 'sel', n))
    _ed = property(lambda self: self.slots._ed)

    def _slot_row(self, data, stat_list, i, s):
        return slot_row(data, stat_list, i, s)

    def _first_slot(self):
        return self.slots.first_slot()

    def _find_slot(self, stat_list, i):
        return self.slots.find_slot(stat_list, i)

    def _row(self, n=None):
        return self.slots.row(n)

    def _fields(self, r):
        return self.slots.fields(r)

    def draw(self):
        self.slots.draw()

    def select(self, n, see=True):
        self.slots.select(n, see)

    def move(self, d):
        return self.slots.move(d)

    def focus_list(self):
        self.slots.focus_list()

    def edit_cell(self, field, start=None):
        return self.slots.edit_cell(field, start)

    def _close_editor(self):
        self.slots._close_editor()

    def _ed_done(self, how):
        return self.slots._ed_done(how)

    def slot_selected(self, n):
        r = self.rows[n]
        if r['s'] is not None:
            self._say(_row_info_text(self.app.data, r['s']))
        else:
            self._say(he('empty_hint', 'empty slot: Enter (or a double-click on a stat) puts an attribute here'))
        if self._pick_mode is not None and self._pick_mode != n:
            self._name_cancel(focus=False)

    def slot_pick(self, n, text=None):
        self.open_picker(text=text)

    def slot_names(self, n):
        self.open_names()

    def slot_pending(self, r):
        return self.pending.get((r['list'], r['i']))

    def slot_value(self, n, v, how):
        """A number typed into a value cell: kept as a pending value; Enter writes."""
        r = self._row(n)
        key = (r['list'], r['i'])
        if v != r['s']['value']:
            self.pending[key] = v
        else:
            self.pending.pop(key, None)
        self.draw()
        if how == 'save':
            self.save()

    def slot_param(self, n, level=None, raw=None):
        return self._set_param(n, level=level, raw=raw)

    def slot_delete(self, n):
        r = self._row(n)
        if r is not None and r['s'] is not None:
            self.delete_row(r['list'], r['i'])

    def slot_save(self):
        self.save()
        return 'break'

    def slot_say(self, text, error=False):
        self._say(text, error=error)

    # ------------------------------------------------------------ the right pane
    def open_picker(self, text=None):
        """The attribute picker for the selected slot: a used slot shows its own stat in its category, an
        empty one the category used last. A pick replaces the slot's stat / fills the empty slot."""
        r = self._row()
        if r is None or r['kind'] != 'slot':
            return 'break'
        self._ed_done('keep')
        self._name_cancel(focus=False)
        if r['s'] is not None:
            title = he('pick_replace', 'Slot {n}: replace attribute', n=r['n'])
            if text is None:
                self.picker.select_stat(r['s']['id'])
        else:
            title = he('pick_add', 'Slot {n}: add attribute', n=r['n'])
        self.picker.title.configure(text=title)
        self.picker.tkraise()
        self.picker.focus_filter(text)
        return 'break'

    def picked(self, sid):
        """A stat was picked: it replaces the selected slot's stat (the value is kept when the new stat can
        store it) or fills the selected empty slot; then the skill list / the value box opens for it."""
        r = self._row()
        if r is None or r['kind'] != 'slot':
            self._say(he('err.row', 'Select a slot first: the picked attribute goes there.'), error=True)
            return
        data = self.app.data
        info = _stat_info(data, sid)
        if info is None or not info['bits']:
            self._say(he('err.no_bits', 'stat #{sid}: the save format has no storage for it', sid=sid), error=True)
            return
        if r['s'] is not None and r['s']['id'] == sid:
            self.focus_list()
            return
        if not self._flush_pending():
            return
        r = self._row()
        stat_list = r['list']
        entries = list(self.rec.get(stat_list) or [])
        kind = param_kind(sid)
        param = None
        if kind in ('skill', 'skill_only'):
            names = skill_names_sorted(data, sid)
            if names:
                param, _why = encode_skill_param(data, sid, names[0][0], 1)
        elif kind in ('class', 'named'):
            param = 0
        lo, hi = value_range(data, sid)
        if r['s'] is not None:
            i = r['i']
            val = max(lo, min(hi, int(r['s']['value'])))
            entries[i] = dict(id=sid, param=param, value=val)
            msg = he('replaced', 'slot {n}: now {label}', n=i + 1, label=self.picker.label(sid))
        else:
            i = len(entries)
            entries.append(dict(id=sid, param=param, value=max(lo, min(hi, 0))))
            msg = he('added', '{label} added', label=self.picker.label(sid))
        self.rec[stat_list] = entries
        ok = self._write()
        if ok:
            self.refresh_after_write()
        self.load_rows()
        self.focus_list()
        if not ok:
            return
        n = self._find_slot(stat_list, i)
        at = self._row(n) if n is not None else None
        if at is None or at['s'] is None or at['s']['id'] != sid:
            # the encoder keeps a stat list in the game's own order (by stat id): find the stat again
            hits = [k for k, x in enumerate(self.rows) if x['kind'] == 'slot' and x['list'] == stat_list
                    and x['s'] is not None and x['s']['id'] == sid]
            n = next((k for k in hits if (self.rows[k]['s'].get('param') or None) == (param or None)),
                     hits[0] if hits else n)
        self.select(n)
        self._say(msg)
        row = self._row()
        if row is not None and row['s'] is not None and row['s']['id'] == sid:
            if kind:
                self.open_names()
            else:
                self.edit_cell('value')

    def open_names(self):
        """The right pane lists the skills (classes) the selected row's stat can carry; a pick rewrites it."""
        r = self._row()
        if r is None or 'name' not in self._fields(r):
            return 'break'
        self._ed_done('keep')
        sid = r['s']['id']
        if r['pk'] == 'class':
            from mxl_rules import CLASSES
            names = list(CLASSES)
            title = he('pick_class', 'Slot {n}: class', n=r['n'])
        elif r['pk'] == 'named':                # state, monster, orb, element / attribute...: by name
            names = [nm for nm, _v in param_choices(self.app.data, sid)]
            title = he('pick_named', 'Slot {n}: {what}', n=r['n'], what=param_title(sid).lower())
        else:
            names = [nm for nm, _k in param_choices(self.app.data, sid)]
            title = he('pick_skill', 'Slot {n}: skill', n=r['n'])
        self.names.numbers = True               # a typed number is taken as the raw value ('#505')
        self._pick_mode = self.sel
        self.names.set(names, current=r['name'], title=title)
        self.names.tkraise()
        self.names.focus_filter()
        return 'break'

    def _name_cancel(self, focus=True):
        was = self._pick_mode is not None
        self._pick_mode = None
        try:
            self.picker.tkraise()
        except tk.TclError:
            return
        if focus and was:
            self.focus_list()

    def _name_picked(self, name):
        n = self._pick_mode
        self._name_cancel(focus=False)
        self.focus_list()
        if n is None:
            return
        if self._set_param(n, name=name):
            r = self._row(n)
            if r is not None and r['s'] is not None:
                self.sel = n
                self.edit_cell('value')

    def _set_param(self, n, name=None, level=None, raw=None):
        """Changes the param of row n (skill / class name, cast level, or the raw number) and rewrites the
        item at once. False: refused (the status bar says why), nothing written."""
        r = self._row(n)
        if r is None or r['s'] is None:
            return False
        data = self.app.data
        s = r['s']
        sid = s['id']
        if raw is not None:
            bits = min(param_bits(data, sid), 32)
            if not 0 <= raw < (1 << bits):
                self._say(he('err.param_range', 'param out of range (0..{m})', m=(1 << bits) - 1), error=True)
                return False
            newp = raw or None
        else:
            nm = name if name is not None else r['name']
            lv = level if level is not None else (int(r['level']) if r['level'] != '' else 1)
            newp, why = encode_skill_param(data, sid, nm, lv)
            if newp is None:
                txt = {'rolled': he('err.rolled', '{name}: its id does not fit this stat (the game would '
                                                  'show another skill)', name=nm),
                       'level': he('err.level', 'cast level must be 0..63')}.get(why)
                self._say(txt or he('err.param', 'unknown {what}: {name}', name=nm,
                                    what=param_title(sid).lower()), error=True)
                return False
        if (newp or None) == (s.get('param') or None):
            return True
        if not self._flush_pending():
            return False
        r = self._row(n)
        entries = list(self.rec.get(r['list']) or [])
        entries[r['i']] = dict(entries[r['i']], param=newp)
        self.rec[r['list']] = entries
        ok = self._write()
        if ok:
            self.refresh_after_write()
        self.load_rows()
        if ok:
            self.select(n)
            self._say(self._row(n)['label'] if self._row(n) and self._row(n)['s'] else '')
        return ok

    def delete_selected(self, *_e):
        r = self._row()
        if r is None or r['kind'] != 'slot' or r['s'] is None:
            return 'break'
        self.delete_row(r['list'], r['i'])
        return 'break'

    def delete_row(self, stat_list, row):
        if not self._flush_pending():
            return
        entries = list(self.rec.get(stat_list) or [])
        try:
            gone = entries[row]
        except IndexError:
            return
        label = _row_label(self.app.data, gone)
        del entries[row]
        self.rec[stat_list] = entries
        keep = self.sel
        if self._write():
            self.refresh_after_write()
            self.load_rows()
            self.select(keep if keep is not None and keep < len(self.rows) else self._first_slot())
            self._say(he('deleted', 'slot cleared: {label} (stat #{sid})', sid=gone['id'], label=label))
        else:
            self.load_rows()
        self.focus_list()

    def _flush_pending(self):
        """Typed values not written yet are written first (their own in-place path), so a following rewrite of
        the item cannot lose them. False: the write was refused - the caller stops."""
        if not self.pending:
            return True
        return self.save() is not False

    # ------------------------------------------------------------ writes
    def save(self, *args):
        """Changed values of kept rows. A stash item: in place through apply_edits (one write). A character
        item: one re-encode of the item's bytes + the character's own save. Added / cleared slots were written
        already at their own change. A value the save format cannot hold is capped to the nearest it can
        (shown in the status bar); the write itself still refuses what the game's own stat logic will not
        allow. Returns False when a write was refused."""
        took = self.slots.take_open_value()   # take the open box's number along
        if took is not None:
            r = self._row(took[0])
            if r is not None and r['s'] is not None and took[1] != r['s']['value']:
                self.pending[(r['list'], r['i'])] = took[1]
        cap_note = ''
        keep = self.sel
        typed = []                            # [(stat_list, index, row dict) per changed row]
        for stat_list, entries in self.lists:
            for i, s in enumerate(entries):
                if (stat_list, i) not in self.pending:
                    continue
                v = self.pending[(stat_list, i)]
                if v == s['value']:
                    continue
                rng = value_range(self.app.data, s['id'])
                if rng is None:
                    continue                  # the save format has no storage for this stat's value
                lo, hi = rng
                if not lo <= v <= hi:
                    v = max(lo, min(hi, v))
                    cap_note = he('capped', 'a value outside what the save format stores was capped '
                                            '(stat #{n} to {m})', n=s['id'], m=v)
                    self.pending[(stat_list, i)] = v
                typed.append((stat_list, i, dict(id=s['id'], param=s.get('param'), value=v)))
        if not typed:
            self.pending = {}
            self.draw()
            self._say(cap_note or he('nothing', 'nothing to write'))
            return None
        if self.entry is None:
            # stash item: plain values in place (the collector's set_stat keeps linked stats together); a stat
            # with a parameter, or one that in-place editor refuses, through the lossless re-encode of the item
            data = self.app.data
            lossless = [t for t in typed if needs_reencode(data, t[2]['id'])]
            edits = [dict(offset=self.it['_offset'], code=self.it['code'], kind='stat', stat_list=stat_list,
                          stat=row['id'], param=row.get('param'), value=row['value'])
                     for stat_list, _i, row in typed if not needs_reencode(data, row['id'])]
            bak = None
            if edits:
                try:
                    bak = apply_edits(self.app.path, edits, data,
                                      backup=self.app.needs_backup(self.app.path), force=True)
                except Exception as e:        # EditError / FormatError / StoreError / OSError
                    self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
                    return False
            if lossless:
                if edits:                     # the record as it stands on disk now (linked stats moved along)
                    self.refresh_after_write()
                    self.load_rows()
                for stat_list, i, row in lossless:
                    entries = list(self.rec.get(stat_list) or [])
                    entries[i] = dict(entries[i], value=row['value'])
                    self.rec[stat_list] = entries
                self._bak = None
                if not self._write():
                    self.load_rows()
                    return False
                bak = bak or self._bak
            self.refresh_after_write()
            self.load_rows()
            self.select(keep)
            self._say(he('saved', 'written{bak}', bak=(f' - backup {os.path.basename(bak)}' if bak else ''))
                      + ((' - ' + cap_note) if cap_note else ''))
            return True
        # character item: write the typed values into the record, then re-encode the item's bytes once
        for stat_list, i, row in typed:
            entries = list(self.rec.get(stat_list) or [])
            entries[i] = dict(entries[i], value=row['value'])
            self.rec[stat_list] = entries
        if self._write_char():
            self.refresh_after_write()
            self.load_rows()
            self.select(keep)
            self._say(he('saved', 'written{bak}', bak='') + ((' - ' + cap_note) if cap_note else ''))
            return True
        self.load_rows()
        return False

    def _write(self):
        """Stash item: re-encodes its bytes (a slot was added, replaced or cleared) and replaces it at its own
        place through edit_stash (verification, backup; socketed items follow). False: refused, nothing
        written."""
        if self.entry is not None:
            return self._write_char()
        page, x, y = self.it.get('page', 0), self.it.get('x', 0), self.it.get('y', 0)
        try:
            blb = build_blob(self.rec, self.kids, self.app.data)
            bak = edit_stash(self.app.path, self.app.data, remove=[self.it['_offset']],
                             insert=[(page, x, y, blb)], backup=self.app.needs_backup(self.app.path))
            self._bak = bak
        except (EditError, FormatError, OSError) as e:
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        except Exception as e:                # e.g. StoreError: the value does not fit the save bits
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        return True

    def _write_char(self):
        """Character item: re-encodes the item's bytes in the character's entry and saves the character
        through the character window (its own verification, backup and status line).

        The Character tab reads its file again when someone else wrote it (sync_file, pending page edits kept):
        the edit then goes onto the item as it is in that file (current_entry: same place, same bytes), or is
        refused when the item is no longer there - never onto an entry of an older read, whose change the save
        would silently leave out."""
        sync, find = getattr(self.chwin, 'sync_file', None), getattr(self.chwin, 'current_entry', None)
        if sync is not None and find is not None:
            sync()
            cur = find(self.entry, False) or find(self.entry, True)
            if cur is None:
                self._say(he('err.save', 'not written: {err}', err=T('inv.err.item_gone', 'the item is no longer '
                                                                     'where it was: select it again')), error=True)
                return False
            self.entry = cur
        try:
            self.entry.blob = build_blob(self.rec, self.kids, self.app.data)
            import mxl_char as MC
            self.entry.it = MC.blob_item(self.entry.blob, self.app.data)
        except (FormatError, OSError, ValueError) as e:
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        except Exception as e:                # e.g. StoreError: the value does not fit the save bits
            self._say(he('err.save', 'not written: {err}', err=str(e)), error=True)
            return False
        if self.chwin.save(T('ch.replaced', '{item} replaced', item=self._name())) is False:
            self._say(he('err.save', 'not written: {err}', err=he('err.char', 'the character window shows the '
                                                                             'error')), error=True)
            return False
        return True

    def refresh_after_write(self):
        """Stash item: offsets shift as soon as an item changed size - reload from disk and point self.it at
        the item again (sender for the next edit), refresh the main window's grid. Character item: take the
        fresh entry (a save rebuilds the character's item list) and keep it selected."""
        if self.entry is not None:
            self.entry = self._refind_entry() or self.entry
            self.chwin.selected = self.entry
            try:
                self.chwin.redraw()
            except Exception:
                pass
            return
        try:
            self.app.load(self.app.path, keep_selection=False)
            page, x, y = self.it.get('page', 0), self.it.get('x', 0), self.it.get('y', 0)
            new = next((i for i in self.app.items or []
                        if (i.get('page'), i.get('x'), i.get('y')) == (page, x, y)), None)
            if new is not None:
                self.it = dict(new)
                self.app.selected = new
                try:
                    self.app.draw_grid()
                    self.app.set_detail(new)
                except Exception:
                    pass
        except Exception:
            pass

    def _refind_entry(self):
        """The character window's entry standing where the edited one stood (a save rebuilt the entries)."""
        ch = self.chwin.ch
        try:
            same = (self.it.get('location'), self.it.get('x'), self.it.get('y'), self.it.get('equipped'),
                    self.it.get('code'))
            for e in list(ch.items) + ([] if ch.merc_items is None else list(ch.merc_items)):
                t = e.it
                if (t.get('location'), t.get('x'), t.get('y'), t.get('equipped'), t.get('code')) == same:
                    self.it = dict(t)
                    return e
        except Exception:
            pass
        return None

    def _say(self, txt, error=False):
        try:
            self.bar.configure(text=txt, fg=self.pal['error'] if error else self.pal['bar_fg'])
        except tk.TclError:
            pass


def open_item_stats(app):
    """The Magic Attributes tab for the item selected in the stash grid of the main window."""
    it = app.selected
    if it is None or not app.path:
        from tkinter import messagebox
        messagebox.showinfo(he('title', 'Item stats'), T('cr.select_first', 'Select an item of the stash first.'))
        return None
    return ItemStatsWindow(app, it=it)


def open_char_item_stats(chwin, entry):
    """The Magic Attributes tab for an item of the character window (equipment, mercenary or inventory)."""
    if entry is None:
        return None
    chwin.selected = entry
    return ItemStatsWindow(chwin.app, chwin=chwin, entry=entry)
