"""Status bar "XBone: Necromancer level 100, Strength 972, Dexterity 208": the same Strength / Dexterity as the
Stats page.

The collector's `App.show_status` prints `char['strength']` / `char['dexterity']` of its own `load_character`:
the stored value plus the flat +Strength / +Dexterity of every equipped item of BOTH weapon sets - no charms, set
bonuses, per-level stats or "+x %" (docs/review/gui.md finding 10, game-data.md row 16). Those numbers stay as
they are in `app.char` (the collector's red "Required ..." lines read them); only the text is replaced, with the
stat screen's totals (`mxl_statscreen.attribute_total`: active weapon set, charms, set bonuses, per-level, %) of
the character file as it is on disk (pending edits of the Character tab show after SAVE, like every other number
of the status bar). The totals are cached per file (path, size, mtime): reading the save and summing its items
takes 5-7 ms (about 50 ms on the very first call), and show_status runs on every stash redraw. When the file
cannot be read, the collector's own text stays.
"""
import os

_cache = {}


def _sig(path):
    try:
        st = os.stat(path)
        return (path, st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def totals(path, data):
    """(strength, dexterity) of the character file as the stat screen totals them, or None."""
    sig = _sig(path)
    if sig is None:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        import mxl_char
        import mxl_statscreen as SS
        ch = mxl_char.Character(path, data)
        tot = SS.char_totals(ch, data)
        val = None if tot.get('error') else (SS.attribute_total(ch, data, tot, 0), SS.attribute_total(ch, data, tot, 2))
    except Exception:
        val = None
    _cache.clear()                         # one character at a time
    _cache[path] = (sig, val)
    return val


def status_text(app):
    """The status bar text with the stat screen's Strength / Dexterity, or None (keep the collector's)."""
    import mxl_gui
    ch = getattr(app, 'char', None)
    if not ch or not ch.get('path'):
        return None
    t = totals(ch['path'], app.data)
    if t is None:
        return None
    return mxl_gui.tr('status.char', name=ch['name'], cls=mxl_gui.CLASSES[ch['cls']], level=ch['level'],
                      str=t[0], dex=t[1])


def install(App):
    if getattr(App.show_status, '_capy_attr', False):
        return
    orig = App.show_status

    def show_status(self, *a, **k):
        r = orig(self, *a, **k)
        try:
            if getattr(self, 'path', None):
                txt = status_text(self)
                if txt:
                    self.char_label.configure(text=txt)
        except Exception:
            pass
        return r
    show_status._capy_attr = True
    App.show_status = show_status
