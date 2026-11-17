"""The compare window through the "More" menu: screenshots, restore with the in-window confirmation."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
import harness

TAG = sys.argv[1] if len(sys.argv) > 1 else 'd2'


def shot(ctx, name):
    ctx.pump(30)
    p = os.path.join(harness.WORK, f'shot_{TAG}_{name}.png')
    subprocess.run(['import', '-window', 'root', p], check=False)
    print('shot', p)


def test(app, ctx):
    import mxl_savecheck as SC, mxl_char
    rd = lambda p: open(p, 'rb').read()
    ctx.pump(60)
    tb = app.toolbar
    tb.post()
    m = tb.menu
    labels = [m.entrycget(i, 'label') for i in range(m.index('end') + 1) if m.type(i) == 'command']
    print('More menu:', labels, '| More button shown:', bool(tb.more.winfo_ismapped()))
    idx = next(i for i in range(m.index('end') + 1) if m.type(i) == 'command' and 'Compare' in m.entrycget(i, 'label'))
    # make a real edit first so that the character has two backups to choose from
    d2s = os.path.join(ctx.saves, 'XBone.d2s')
    ch = mxl_char.Character(d2s, app.data)
    ch.set_stat(0, 900)
    ch.set_stat(14, 5000)
    ch.remove(ch.inventory()[3])
    SC.extra_backup(d2s, 'manual')
    ch.save(False)
    m.invoke(idx)
    ctx.pump(40)
    w = app._savecheck_win
    print('window', w.win.winfo_width(), 'x', w.win.winfo_height(), 'files', [os.path.basename(f) for f in w.files])
    print('backups', w.bak_box.cget('values'))
    print(w.text.get('1.0', '12.0'))
    shot(ctx, 'compare_new')
    # the older backup of the sample (level 117, two days earlier)
    j = next(i for i, b in enumerate(w.baks) if '20261115' in b)
    w.bak_box.current(j)
    w.show()
    shot(ctx, 'compare_old')
    w.text.yview_moveto(0.55)
    shot(ctx, 'compare_old_items')
    # restore: confirmation in the window
    before = rd(d2s)
    bak = w.current()[1]
    w.btn_restore.invoke()
    ctx.pump(10)
    print('confirm row:', w.status.cget('text'), '| yes mapped', bool(w.btn_yes.winfo_ismapped()), '| file untouched', rd(d2s) == before)
    shot(ctx, 'confirm')
    w.btn_no.invoke()
    ctx.pump(5)
    print('cancel: file untouched', rd(d2s) == before, '| restore button back', bool(w.btn_restore.winfo_ismapped()))
    w.btn_restore.invoke()
    w.btn_yes.invoke()
    ctx.pump(10)
    print('restored == backup bytes:', rd(d2s) == rd(bak), '|', w.status.cget('text'))
    kept = [b for b in SC.backups(d2s) if 'before-restore' in b]
    print('kept backup holds the replaced bytes:', len(kept) == 1 and rd(kept[0]) == before)
    shot(ctx, 'restored')
    # a file without backup, and the stash
    i = next(i for i, f in enumerate(w.files) if f.endswith('.stash'))
    w.file_box.current(i)
    w.pick_file()
    shot(ctx, 'stash')
    print(w.text.get('1.0', 'end')[:600])
    print('boxes', ctx.boxes)


env = {'MXL_THEME': TAG}
harness.run(test, 'win_' + TAG, 'saves117', env=env)
