"""The Creator's preview (the collector's detail panel) shows the corrected damage lines of mxl_dmg_text: Anak
"One-Hand Damage: 145 to 146" and "+70 to Minimum Damage" / "+45 to Maximum Damage", not "145 to 132" /
"Adds 70-45" (docs/review/gui.md finding 9; the data side is test_55_tooltip_damage)."""
import os
import subprocess
import tkinter as tk

import capytest as T

MODE = 'gui'
G = T.G


def all_text(w):
    out = []

    def walk(x):
        if isinstance(x, tk.Text):
            out.append(x.get('1.0', 'end'))
        for c in x.winfo_children():
            walk(c)
    walk(w)
    return '\n'.join(out)


@T.test
def creator_preview_of_anak():
    import mxl_creator_gui as CG
    import mxl_tabs
    CG.CreatorWindow(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    T.check(w is not None, 'no Creator window')
    w.search.set('')
    w.quality.set(dict((k, lab) for lab, k in CG.qualities())['runeword'])
    w.on_quality()
    T.pump()
    i = next((i for i, e in enumerate(w.entries) if str(e[0]).startswith('Anak')), None)
    T.check(i is not None, 'no Anak in the runeword list')
    w.listbox.selection_clear(0, 'end')
    w.listbox.selection_set(i)
    w.on_pick()
    T.pump(12)
    T.select_tab('Creator')
    T.pump(6)
    txt = all_text(mxl_tabs._state['pages']['Creator'])
    T.check('145 to 146' in txt, f'no "145 to 146" in the preview: {txt[:400]!r}')
    T.check('+70 to Minimum Damage' in txt and '+45 to Maximum Damage' in txt, 'split +min / +max lines missing')
    T.check('145 to 132' not in txt and 'Adds 70-45' not in txt, 'old min > max text still shown')
    shot = os.environ.get('CAPY_SHOT')
    if shot:
        subprocess.run(['import', '-window', 'root', shot], check=False)


T.main(globals())
