"""strict / warn / off with a corrupted output, the known-corrupt stashes as output, restore round trip."""
import glob, os, sys, shutil
sys.path.insert(0, os.path.dirname(__file__))
import harness

CORRUPT = sorted(glob.glob(os.path.join(harness.ORIG, 'corrupt/*corrupt*')))
REPAIRED = os.path.join(harness.ORIG, 'corrupt/Mr_Owlie_repaired.stash')
FAILS = []


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        FAILS.append(what)


def test(app, ctx):
    import mxl_save, mxl_savecheck as SC, mxl_char, settings
    from mxl_save import EditError
    data = app.data
    rd = lambda p: open(p, 'rb').read()
    d2s = os.path.join(ctx.saves, 'XBone.d2s')
    stash = os.path.join(ctx.saves, 'XBone.stash')
    import mxl_log, mxl_inv_gui
    g = mxl_save.commit_file
    mxl_log.wrap_saves(); SC.install()
    check(mxl_save.commit_file is g and mxl_inv_gui.commit_file is g and g._capy_savecheck,
          'install is idempotent and survives another mxl_log.wrap_saves(); modules that bound commit_file use the guard')
    os.environ.pop('MXL_SAVECHECK', None)
    check(SC.mode() == 'strict', 'default mode is strict')
    settings.put('savecheck', 'warn')
    check(SC.mode() == 'warn', 'setting savecheck=warn is read from settings.json')
    settings.put('savecheck', 'strict')

    def flip_checksum(path, content):
        b = bytearray(content)
        b[12] ^= 0xFF
        return bytes(b)

    def flip_item(path, content):                      # bytes inside the item data
        b = bytearray(content)
        for i in range(len(b) - 40, len(b) - 30):
            b[i] ^= 0xFF
        return bytes(b)

    # ---- strict: refused, file untouched
    before = rd(d2s)
    n_bak = len(SC.backups(d2s))
    SC.TEST_HOOK = flip_checksum
    ch = mxl_char.Character(d2s, data)
    ch.set_stat(0, ch.stat(0) + 1)
    try:
        ch.save(True)
        check(False, 'strict: corrupted character output refused')
    except EditError as e:
        check('independent check refused' in str(e), 'strict: corrupted character output refused (EditError: %s)' % str(e).split('\n')[1])
    check(rd(d2s) == before, 'strict: character file unchanged on disk')
    check(len(SC.backups(d2s)) == n_bak and not os.path.exists(d2s + '.tmp'), 'strict: no backup, no temp file left')
    SC.TEST_HOOK = flip_item
    before_s = rd(stash)
    it = mxl_save.parse_stash(stash, data)[3]
    try:
        mxl_save.edit_stash(stash, data, remove=[it['_offset']], backup=True)
        check(False, 'strict: corrupted stash output refused')
    except EditError as e:
        check('independent check refused' in str(e), 'strict: corrupted stash output refused (%s)' % str(e).split('\n')[1][:90])
    check(rd(stash) == before_s, 'strict: stash file unchanged on disk')
    # ---- warn: written, warning, extra backup
    os.environ['MXL_SAVECHECK'] = 'warn'
    SC.TEST_HOOK = flip_checksum
    ctx.boxes.clear()
    ch = mxl_char.Character(d2s, data)
    ch.set_stat(0, ch.stat(0) + 1)
    expect = flip_checksum(d2s, ch.build())
    try:
        ch.save(True)
        check(rd(d2s) == expect, 'warn: the corrupted character output was written as it was')
    except Exception as e:
        check(False, f'warn: written ({type(e).__name__}: {e})')
    extra = [b for b in SC.backups(d2s) if '.bak-savecheck-' in b]
    check(len(extra) == 1 and rd(extra[0]) == before, 'warn: extra backup .bak-savecheck-* holds the previous bytes')
    for _ in range(30):
        app.root.update()
        app.root.after(5)
    check(any(b[0] == 'showwarning' and 'independent check' in str(b[2]) for b in ctx.boxes), 'warn: warning box shown')
    # the next write (no hook) repairs the file: old side fails the check -> not refused even in strict
    os.environ['MXL_SAVECHECK'] = 'strict'
    SC.TEST_HOOK = None
    ch = mxl_char.Character(d2s, data)
    ch.set_stat(0, ch.stat(0) - 1)
    ch.save(True)
    check(SC.examine(d2s, rd(d2s)).ok, 'a normal save afterwards gives a file the check accepts')
    # ---- off: nothing checked
    os.environ['MXL_SAVECHECK'] = 'off'
    n = len(harness.log_lines(ctx))
    SC.TEST_HOOK = flip_checksum
    ch = mxl_char.Character(d2s, data)
    ch.save(True)
    check(len(harness.log_lines(ctx)) == n, 'off: no savecheck line, hook not applied')
    SC.TEST_HOOK = None
    os.environ['MXL_SAVECHECK'] = 'strict'
    # ---- the three known-corrupt stashes as OUTPUT
    for k, bad in enumerate(CORRUPT):
        content = rd(bad)
        for label, prepare in (('over the repaired stash', lambda p: shutil.copy2(REPAIRED, p)), ('as a new file', lambda p: None)):
            dst = os.path.join(ctx.saves, f'Owlie{k}{label[:2]}.stash')
            prepare(dst)
            was = rd(dst) if os.path.exists(dst) else None
            try:
                mxl_save.commit_file(dst, content, lambda tmp: None, False)
                check(False, f'corrupt sample {k + 1} {label}: refused')
            except EditError as e:
                now = rd(dst) if os.path.exists(dst) else None
                check(now == was, f'corrupt sample {k + 1} {label}: refused, disk unchanged ({str(e).splitlines()[1][:80]})')
    # reading one stays the host's business: nothing of savecheck runs, the host refuses it itself
    n = len(harness.log_lines(ctx))
    try:
        mxl_save.parse_stash(CORRUPT[0], data)
        r = 'read by the host'
    except Exception as e:
        r = f'host: {type(e).__name__}'
    check(len(harness.log_lines(ctx)) == n, f'reading a corrupt stash does not involve savecheck ({r})')
    # ---- restore round trip
    path = os.path.join(ctx.saves, 'XBone.stash')
    bak = SC.backups(path)[-1]                      # the sample's own backup
    cur, old = rd(path), rd(bak)
    kept = SC.restore_backup(path, bak)
    check(rd(path) == old, 'restore: the file now holds the exact bytes of the backup')
    check(kept and rd(kept) == cur and os.path.exists(bak), 'restore: the replaced file is kept as a new backup, the backup itself stays')
    kept2 = SC.restore_backup(path, kept)
    check(rd(path) == cur, 'restore of that new backup returns the exact previous bytes (round trip)')
    # a corrupt backup can be restored on request (warned, not refused)
    cb = path + '.bak-20200101-000000'
    shutil.copy2(CORRUPT[0], cb)
    try:
        SC.restore_backup(path, cb)
        check(rd(path) == rd(CORRUPT[0]), 'restore of a backup the check does not accept: done, with a warning in the log')
    except Exception as e:
        check(False, f'restore of a bad backup: {e}')
    SC.restore_backup(path, kept)
    check(rd(path) == cur, 'and back')
    print('--- log')
    for l in harness.log_lines(ctx):
        if 'REFUSED' in l or 'WARNING' in l or 'restore' in l:
            print('  ', l[20:330])
    print('FAILS', FAILS)


harness.run(test, 'guard', 'saves117')
