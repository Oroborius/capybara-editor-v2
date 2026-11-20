"""Median XL profile (the default): no "Mock Mode" toggle in the top bar and no Mock tab, even with the setting
left on from a folder profile (Mock Mode exists in folder profiles only; test 80)."""
import capytest as T

MODE = 'gui'
G = T.G


@T.test
def no_mock_mode_in_median():
    import mxl_mock_gui as MG
    import mxl_profile
    import mxl_tabs
    T.check(mxl_profile.is_median(), 'Median XL profile')
    T.check(MG._state['button'] is None, 'no toggle built')
    bar = G.app.char_combo.master
    texts = []
    for w in bar.winfo_children():
        try:
            texts.append(str(w.cget('text')))
        except Exception:
            pass
    T.check(not any('Mock' in t for t in texts), f'no Mock widget in the top bar: {texts}')
    nb = mxl_tabs._state['nb']
    T.check(all(nb.tab(t, 'text') != 'Mock' for t in nb.tabs()), 'no Mock tab')
    MG.set_mode(True)                        # even when asked (no app bound): nothing appears
    T.pump(4)
    T.check(all(nb.tab(t, 'text') != 'Mock' for t in nb.tabs()), 'still no Mock tab')


T.main(globals())
