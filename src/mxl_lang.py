"""Translations of the Capybara Editor's own windows (Item Creator, Character window, inventory panel, import...).

T('key', 'English text {field}', field=...) looks the key up in the language file chosen in the editor
(lang/<code>.json, same files and same Language setting as the collector's texts) and falls back to the English
text written at the call. Missing keys therefore never break a window: they just stay in English.

Game text (item, stat, skill, quest and waypoint names, tooltip lines) comes from Median XL's own tables and stays
as the game shows it."""
try:
    import i18n
except Exception:                     # tests without the collector
    i18n = None


SEEN = {}            # key -> English text of every T() call without fields so far (retranslate() maps them)


def T(key, default, **fields):
    if not fields and key not in SEEN:
        SEEN[key] = default
    txt = None
    if i18n is not None:
        try:
            txt = (getattr(i18n, '_texts', None) or {}).get(key)
        except Exception:
            txt = None
    if not txt:
        txt = default
    if fields:
        try:
            return txt.format(**fields)
        except (KeyError, IndexError, ValueError):
            try:
                return default.format(**fields)
            except (KeyError, IndexError, ValueError):
                return default
    return txt


# ------------------------------------------------------------------ live language switch
SUFFIXES = (' \u00bb', '...', '\u2026', ':')      # "More »", "Add...": a T() text with a fixed ending


def _text_map(old_texts):
    """{text in the old language: text in the new one} of every T() text seen so far; a text that two keys
    share and that would become two different texts is left out (not guessed)."""
    out, bad = {}, set()
    for key, default in list(SEEN.items()):
        old = (old_texts or {}).get(key) or default
        new = T(key, default)
        if old == new or old in bad:
            continue
        if out.get(old, new) != new:
            bad.add(old)
            out.pop(old, None)
            continue
        out[old] = new
    return out


def _swap(text, tmap):
    if text in tmap:
        return tmap[text]
    for suf in SUFFIXES:
        if text.endswith(suf) and text[:-len(suf)] in tmap:
            return tmap[text[:-len(suf)]] + suf
    return None


def retranslate(root, old_texts):
    """Puts the texts of the editor's own widgets into the language just chosen: every widget text, notebook
    tab and menu entry that is exactly a T() text of the old language (optionally with a fixed ending such as
    " \u00bb" or "...") gets the same key's text of the new one. Texts with fields in them (a character's name,
    a number) and pictures with text (game-art buttons) are not changed: they follow on their next refresh.
    Returns the number of texts changed."""
    import tkinter as tk
    tmap = _text_map(old_texts)
    if not tmap:
        return 0
    n = 0

    def walk(w):
        nonlocal n
        try:
            cls = w.winfo_class()
        except tk.TclError:
            return
        try:
            if cls == 'Menu':
                last = w.index('end')
                for i in range(0 if last is None else last + 1):
                    if w.type(i) in ('command', 'cascade', 'checkbutton', 'radiobutton'):
                        new = _swap(str(w.entrycget(i, 'label')), tmap)
                        if new is not None:
                            w.entryconfigure(i, label=new)
                            n += 1
            elif cls == 'TNotebook':
                for t in w.tabs():
                    new = _swap(str(w.tab(t, 'text')), tmap)
                    if new is not None:
                        w.tab(t, text=new)
                        n += 1
            else:
                try:
                    tv = str(w.cget('textvariable'))
                except tk.TclError:
                    tv = ''
                if not tv:
                    new = _swap(str(w.cget('text')), tmap)
                    if new is not None:
                        w.configure(text=new)
                        n += 1
        except tk.TclError:
            pass
        try:
            kids = w.winfo_children()
        except tk.TclError:
            kids = []
        for c in kids:
            walk(c)
    walk(root)
    return n


def install(App):
    """More » Language: the collector re-labels its own widgets; this does the same for the editor's (toolbar
    buttons, Character pages, Creator, footer...), then lays the top bar out again (other text widths)."""
    original = getattr(App, 'change_language', None)
    if original is None:
        return

    def change_language(self, *a, **k):
        old = dict(getattr(i18n, '_texts', None) or {}) if i18n is not None else {}
        result = original(self, *a, **k)
        try:
            n = retranslate(self.root, old)
            bar = getattr(self, 'toolbar', None)
            if bar is not None and n:
                self.root.after_idle(bar.layout)
        except Exception as e:                 # never in the way of the switch itself
            print('mxl_lang: retranslate failed:', type(e).__name__, e)
        return result

    App.change_language = change_language
