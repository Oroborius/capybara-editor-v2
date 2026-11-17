"""False-positive hunt: every item the creator can build must be accepted by mxlsave (as a one-item stash)."""
import os, struct, sys, time, collections
sys.path.insert(0, os.path.dirname(__file__))
import harness


def test(app, ctx):
    import mxl_save, mxl_savecheck, mxl_creator, mxlsave
    from mxlsave.check import check_bytes
    print('installed:', getattr(mxl_save.commit_file, '_capy_savecheck', False), 'mode', mxl_savecheck.mode())
    import mxl_inv_gui, mxl_char_gui
    print('bound by name:', mxl_inv_gui.commit_file is mxl_save.commit_file, mxl_char_gui.commit_file is mxl_save.commit_file)
    data = app.data
    tb = mxl_savecheck.tables()
    cr = mxl_creator.Creator(data)
    stats = collections.Counter()
    bad = collections.defaultdict(list)
    why = collections.Counter()

    import types, mxl_creator_gui
    Win = next(c for c in vars(mxl_creator_gui).values() if isinstance(c, type) and 'prepare_defaults' in vars(c))
    fake = types.SimpleNamespace(cr=cr, data=data)

    def one(label, spec, how):
        try:
            if 'eth' not in label:
                spec['ilvl'] = max(spec['ilvl'], 99)
            spec['max_sockets'] = spec['quality'] in ('unique', 'set', 'crafted')
            if spec['quality'] == 'runeword':
                spec['sockets'] = len(data.runewords[spec['row']][1])
            Win.prepare_defaults(fake, spec)
            if spec['quality'] == 'crafted':
                cr.reroll_crafted(spec)
            else:
                cr.roll(spec, how)
            blob, rec = cr.build(spec)
        except Exception as e:
            stats['not built'] += 1
            why[str(e)[:60]] += 1
            return
        stash = struct.pack('<II', 1, 0) + b'STASH' + struct.pack('<I', 0) + b'JM' + struct.pack('<H', 1) + blob
        try:
            mxl_save_ok = True
            from mxl_format_fix import parse_item
            parse_item(blob, data)
        except Exception:
            mxl_save_ok = False
        obj, problems = check_bytes(stash, 'stash', tb)
        stats['built'] += 1
        if problems:
            bad[problems[0].split(':')[-1].strip()[:70]].append(label)
    t = time.time()
    bases = cr.bases()
    for b in bases:
        for q in ('normal', 'superior', 'magic', 'rare', 'crafted'):
            try:
                if not cr.can_have_quality(b.code, q):
                    continue
                spec = cr.new_spec(q, b.code)
            except Exception:
                stats['no spec'] += 1
                continue
            one(f'{q} {b.code!r} {b.name}', spec, 'max')
            if q in ('normal', 'magic'):
                spec = cr.new_spec(q, b.code)
                spec['ethereal'] = b.kind in ('weapons', 'armor')
                try:
                    spec['sockets'] = cr.max_sockets(b.code, 99)
                except Exception:
                    pass
                one(f'{q}+eth+sockets {b.code!r} {b.name}', spec, 'min')
    print('bases', len(bases), dict(stats), 'bad', {k: len(v) for k, v in bad.items()}, '%.0fs' % (time.time() - t))
    for i in range(len(data.uniques)):
        try:
            spec = cr.new_spec('unique', row=i)
        except Exception:
            stats['no spec'] += 1
            continue
        one(f'unique {i}', spec, 'random')
    for i in range(len(data.set_items)):
        try:
            spec = cr.new_spec('set', row=i)
        except Exception:
            stats['no spec'] += 1
            continue
        one(f'set {i}', spec, 'max')
    for rw in cr.rw_list:
        try:
            bs = cr.runeword_bases(rw)
            spec = cr.new_spec('runeword', bs[0].code, rw)
        except Exception:
            stats['no spec'] += 1
            continue
        one(f'runeword {rw}', spec, 'max')
    print('all', dict(stats), '%.0fs' % (time.time() - t))
    print(why.most_common(8))
    for k, v in bad.items():
        print('BAD', len(v), k, v[:6])


harness.run(test, 'mass')
