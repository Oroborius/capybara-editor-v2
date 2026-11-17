"""Every write the existing features perform, in strict mode: any savecheck REFUSED / WARNING is a false positive."""
import os, re, sys, time, collections, json, shutil, random
sys.path.insert(0, os.path.dirname(__file__))
import harness

SAVES = sys.argv[1] if len(sys.argv) > 1 else 'saves117'
random.seed(7)


def test(app, ctx):
    import mxl_save, mxl_savecheck, mxl_creator, mxl_char, mxl_rc_menu as RC, mxl_perfect, mxl_undo, mxl_char_gui
    import mxl_creator_gui, types
    from mxl_save import EditError
    data = app.data
    tally = collections.Counter()
    errors = collections.Counter()

    def act(name, fn, *a, **k):
        try:
            r = fn(*a, **k)
            tally[name] += 1
            return r
        except Exception as e:
            errors[f'{name}: {type(e).__name__}: {str(e)[:70]}'] += 1
        finally:
            try:
                app.reload(True)
            except Exception as e:
                errors[f'reload: {e}'] += 1

    def items():
        return list(app.items)

    stash = os.path.join(ctx.saves, 'XBone.stash')
    shared = os.path.join(ctx.saves, '_sharedstash.shared')
    app.load(stash, False, None, True)
    ctx.pump(5)
    print('stash items', len(items()), 'path', os.path.basename(app.path))
    n0 = len(items())
    # ---- host writers
    for k in range(6):
        its = items()
        it = its[(k * 37) % len(its)]
        st = [s for s in it.get('stats', []) if isinstance(s.get('value'), int)]
        if st:
            s = st[0]
            for delta in (0, -1):
                act('apply_edits', mxl_save.apply_edits, app.path, [dict(offset=it['_offset'], code=it['code'], kind='stat',
                    stat=s['id'], value=s['value'] + delta, param=s.get('param'))], data, True, True)
                it = next((i for i in items() if i['_offset'] == it['_offset']), it)
    for k in range(6):
        its = items()
        it = its[(k * 53 + 5) % len(its)]
        spot = mxl_save.free_spot(its, it, data, [2, 1, 0])
        if spot:
            act('move_item', mxl_save.move_item, app.path, it, spot[1], spot[2], data, spot[0], True)
    for k in range(4):
        its = items()
        it = its[(k * 71 + 9) % len(its)]
        other = mxl_save.parse_stash(shared, data)
        spot = mxl_save.free_spot(other, it, data, [0, 1])
        if spot:
            act('transfer_item', mxl_save.transfer_item, app.path, shared, it, spot[0], spot[1], spot[2], data, True, True)
    # ---- right-click actions on the stash
    for k in range(8):
        it = items()[(k * 29 + 3) % len(items())]
        act('rc duplicate', RC._duplicate, app, it)
    for k in range(4):
        it = items()[(k * 31 + 1) % len(items())]
        act('rc move page', RC._move_page, app, it, (it['page'] + 1) % 3)
    stack = [i for i in items() if i.get('quantity') is not None]
    for it in stack[:5]:
        act('rc quantity', RC._set_quantity, app, it, max(1, (it['quantity'] or 1) - 1))
    for q in ('magic', 'rare', 'normal', 'superior', 'unique'):
        for k in range(3):
            its = [i for i in items() if i.get('quality')]
            it = its[(k * 41 + 11) % len(its)]
            act(f'rc quality {q}', RC._apply_quality_picked, app, it, None, q)
    for k in range(6):
        its = [i for i in items() if i.get('sockets')]
        if its:
            it = its[(k * 17) % len(its)]
            act('rc remove socketed', RC._remove_socketed, app, it)
            it = next((i for i in items() if (i['page'], i['x'], i['y']) == (it['page'], it['x'], it['y'])), None)
            if it:
                act('rc fill sockets', RC._fill_sockets, app, it)
    for k in range(10):
        its = [i for i in items() if i.get('quality')]
        it = its[(k * 13 + 2) % len(its)]
        act('make perfect', mxl_perfect.make_perfect, app, it=it)
    for k in range(6):
        it = items()[(k * 19 + 4) % len(items())]
        act('delete', mxl_undo.delete_item, app, it)
    for k in range(4):
        act('undo', mxl_undo.undo, app)
    it = items()[0]
    act('rc cut', RC._cut, app, it)
    # ---- creator: create into the stash, replace
    cr = mxl_creator.Creator(data)
    Win = next(c for c in vars(mxl_creator_gui).values() if isinstance(c, type) and 'prepare_defaults' in vars(c))
    fake = types.SimpleNamespace(cr=cr, data=data)
    blobs = []
    bases = cr.bases()
    for k in range(40):
        try:
            if k % 4 == 0:
                spec = cr.new_spec('unique', row=random.randrange(len(data.uniques)))
            elif k % 4 == 1:
                spec = cr.new_spec('set', row=random.randrange(len(data.set_items)))
            elif k % 4 == 2:
                rw = random.choice(cr.rw_list)
                spec = cr.new_spec('runeword', cr.runeword_bases(rw)[0].code, rw)
                spec['sockets'] = len(data.runewords[rw][1])
            else:
                b = random.choice(bases)
                spec = cr.new_spec(random.choice(['normal', 'magic', 'rare']), b.code)
            spec['ilvl'] = max(spec['ilvl'], 99)
            Win.prepare_defaults(fake, spec)
            cr.roll(spec, 'random')
            blob, rec = cr.build(spec)
            blobs.append(blob)
        except Exception as e:
            errors['creator build: ' + str(e)[:50]] += 1
    print('creator blobs', len(blobs))
    for blob in blobs:
        its = mxl_save.parse_stash(app.path, data)
        spot = mxl_save.free_spot(its, mxl_save.blob_item(blob, data), data, [0, 1, 2, 3, 4])
        if spot:
            act('creator create', mxl_save.edit_stash, app.path, data, insert=[(spot[0], spot[1], spot[2], blob)], backup=True)
    for k in range(8):                                   # creator "replace": same cell, re-encoded item
        it = items()[(k * 23 + 6) % len(items())]
        blob = mxl_save.item_blob(mxl_save.read_file(app.path), it)
        act('creator replace', mxl_save.edit_stash, app.path, data, remove=[it['_offset']],
            insert=[(it['page'], it['x'], it['y'], blob)], backup=True)
    print('stash items now', len(items()), 'from', n0)

    # ---- character
    d2s = os.path.join(ctx.saves, 'XBone.d2s')
    ch = mxl_char.Character(d2s, data)
    act('char save unchanged', ch.save, True)
    same = open(d2s, 'rb').read() == open(os.path.join(harness.ORIG, SAVES, 'XBone.d2s'), 'rb').read()
    print('unedited character save byte-identical:', same)

    def edit(name, fn):
        c = mxl_char.Character(d2s, data)
        try:
            fn(c)
        except Exception as e:
            errors[f'{name} (edit): {type(e).__name__}: {str(e)[:60]}'] += 1
            return
        act(name, c.save, True)
    edit('char stat strength', lambda c: c.set_stat(0, c.stat(0) + 83))
    edit('char gold', lambda c: c.set_stat(14, 123456))
    edit('char level 120', lambda c: c.set_level(120))
    edit('char level 5', lambda c: c.set_level(5))
    edit('char level 117', lambda c: c.set_level(117))
    edit('char skills', lambda c: c.set_skill_levels({k: 7 for k in list(c.skill_levels())[:10]}))
    for dff in range(3):
        edit(f'char waypoints {dff}', lambda c, dff=dff: c.set_waypoints(dff, mxl_char.waypoint_ids(dff)))
        edit(f'char quests {dff}', lambda c, dff=dff: c.set_quests(dff, [1, 2, 3, 4, 5, 6, 9, 10, 35, 36, 40]))
    edit('char waypoints none', lambda c: c.set_waypoints(2, []))
    edit('char flags', lambda c: c.set_flags(hardcore=True))
    edit('char flags back', lambda c: c.set_flags(hardcore=False))
    edit('char progression', lambda c: c.set_difficulties_done(3))
    edit('char class', lambda c: c.set_class((c.cls + 1) % 7))
    edit('char class back', lambda c: c.set_class(2))
    for fld in ('strength', 'vitality', 'life', 'mana', 'stat_points', 'skill_points', 'experience', 'stash_gold'):
        def setf(c, fld=fld):
            f = c.stat_field(fld)
            c.set_field(fld, getattr(f, 'value', 1) + 1 if isinstance(getattr(f, 'value', 1), int) else 5)
        edit(f'char field {fld}', setf)
    # items on the character: remove, move, place, duplicate, mercenary items
    def rm(c):
        c.remove(c.entries()[len(c.entries()) // 2])
    edit('char item remove', rm)

    def dup(c):
        e = c.inventory()[0]
        blob = c.stash_blob(e)
        spot = c.free_inventory_spot(mxl_char.blob_item(blob, data))
        c.place(blob, ('inv',) + spot)
    for k in range(3):
        edit('char item duplicate', dup)

    def place_created(c, blob):
        spot = c.free_inventory_spot(mxl_char.blob_item(blob, data))
        if spot is None:
            raise RuntimeError('no room')
        c.place(blob, ('inv',) + spot)
    for blob in blobs[:12]:
        edit('char item create', lambda c, blob=blob: place_created(c, blob))

    def unequip(c):
        eq = c.equipped()
        e = list(eq.values())[0] if isinstance(eq, dict) else eq[0]
        spot = c.free_inventory_spot(e.it)
        c.move(e, ('inv',) + spot)
    edit('char item unequip', unequip)

    keep = {}

    def merc_rm(c):
        e = next(x for x in c.entries(True) if x.it['equipped'] in (1, 3))
        keep['blob'], keep['slot'] = c.stash_blob(e), e.it['equipped']
        c.remove(e, True)
    def merc_put(c):
        more = []
        for b in [x for x in bases if x.kind in ('armor', 'weapons')][::25]:
            try:
                spec = cr.new_spec('normal', b.code)
                Win.prepare_defaults(fake, spec)
                cr.roll(spec, 'max')
                more.append(cr.build(spec)[0])
            except Exception:
                pass
        print('merc candidates', len(more), sorted(c.equipped(True)))
        if keep.get('blob'):
            c.place(keep.pop('blob'), ('slot', keep['slot']), True)
            print('merc item put back in slot', keep['slot'])
            return
        for blob in more:
            it = mxl_char.blob_item(blob, data)
            for slot in range(1, 13):
                if not c.slot_error(it, slot, True):
                    c.place(blob, ('slot', slot), True)
                    print('merc item placed in slot', slot, it['name'])
                    return
        raise RuntimeError('nothing fits the mercenary')
    edit('merc item remove', merc_rm)
    for k in range(3):
        edit('merc item add', merc_put)

    def merc_move(c):
        e = c.entries(True)[0]
        for slot in range(1, 13):
            if slot != e.it['equipped'] and not c.slot_error(e.it, slot, True, ignore=e):
                c.move(e, ('slot', slot), True)
                return
        raise RuntimeError('no other slot')
    edit('merc item move', merc_move)
    # the character window's own save path + right-click actions there
    try:
        win = mxl_char_gui.CharacterWindow(app, 'stats')
        ctx.pump(10)
        for k in range(3):
            ents = win.ch.entries()
            e = ents[(k * 5 + 1) % len(ents)]
            win.selected = e
            act('rc char duplicate', RC._char_duplicate, win, e)
            ents = [x for x in win.ch.entries() if x.it.get('quality')]
            e = ents[(k * 7 + 2) % len(ents)]
            win.selected = e
            act('char make perfect', mxl_perfect.make_perfect, win, win=win, e=e)
            ents = [x for x in win.ch.entries() if x.it.get('quantity') is not None]
            if ents:
                act('rc char quantity', RC._char_set_quantity, win, ents[0], max(1, ents[0].it['quantity'] - 1))
            ents = [x for x in win.ch.entries() if x.it.get('quality')]
            e = ents[(k * 3) % len(ents)]
            win.selected = e
            act('rc char quality magic', RC._apply_quality_picked, win, e.it, win, 'magic')
        act('char window save', win.save, 'saved')
    except Exception as e:
        errors[f'character window: {type(e).__name__}: {e}'] += 1
    # rename, copy
    c = mxl_char.Character(d2s, data)
    newp = act('char rename', lambda: c.rename('Renamed', True)[0])
    cp = act('char copy', mxl_char.copy_character, newp or d2s, 'CopyOfX', data)
    print('rename ->', newp and os.path.basename(newp), ' copy ->', cp and os.path.basename(cp))
    # import a character (no saved page in the fixtures: an items .json with nothing, every class)
    import mxl_import
    page = os.path.join(ctx.dir, 'page.json')
    with open(page, 'w') as f:
        json.dump([], f)
    tmpl = newp or d2s
    for i, cls in enumerate(mxl_import.CLASS_INDEX):
        act('import character', mxl_import.import_character, page, tmpl, ctx.saves, f'Imp{cls[:8]}', data, cls,
            level=1 + i * 20, quests=[0, 1])
    print('TALLY', json.dumps(dict(tally)))
    print('ERRORS', json.dumps(dict(errors), indent=1))
    lines = harness.log_lines(ctx)
    ok = [l for l in lines if ' savecheck: ' in l]
    bad = [l for l in lines if 'REFUSED' in l or 'savecheck WARNING' in l or 'check itself failed' in l]
    saved = harness.log_lines(ctx, ' saved: ')
    ms = sorted(float(m.group(1)) for l in ok for m in [re.search(r'\[(\d+) ms\]', l)] if m)
    print(f'savecheck lines {len(ok)}  mxl_log "saved" lines {len(saved)}  FALSE POSITIVES {len(bad)}')
    if ms:
        print(f'check time ms: median {ms[len(ms) // 2]:.0f}  p95 {ms[int(len(ms) * .95)]:.0f}  max {ms[-1]:.0f}')
    for l in bad[:15]:
        print('BAD', l[:400])
    kinds = collections.Counter(re.sub(r'\d+', 'N', l.split('savecheck: ')[1].split(':')[0]) for l in ok)
    print('files:', dict(kinds))
    for l in ok[:3] + ok[60:66] + ok[-12:]:
        print('  ', l[20:260])
    # every sample file the editor left must still pass the standalone verify
    import mxlsave
    from mxlsave import cli
    tb = mxl_savecheck.tables()
    res = collections.Counter()
    for fn in sorted(os.listdir(ctx.saves)):
        if mxl_savecheck.kind_of(fn):
            res[cli.verify(os.path.join(ctx.saves, fn), tb)[0]] += 1
    print('standalone verify of every file in the save folder:', dict(res))


harness.run(test, 'paths_' + SAVES, SAVES, env={'MXL_SAVECHECK': 'strict'})
