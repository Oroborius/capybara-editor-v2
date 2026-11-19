"""Item inspector (mxl_inspect) and personal item library (mxl_itemlib), driven through the stash's right-click menu.

Inspector (now the Bit editor tab's text dump): the dump of every item of the second sample names the fields and stats the host decoder reads; the bit layout covers every
bit of the item without a gap; the bytes mxlsave re-encodes are the item's own bytes. Library: Add to library...
stores the exact bytes, the list finds it, Place a copy writes one copy (verified by a fresh read + mxlsave),
Ctrl+Z (mxl_undo) removes it, rename / delete edit the index."""
import capytest as T

MODE = 'gui'
RESET = True
SAMPLE = 2          # the honorific sample: a socketed runeword, uniques, rares, crafted, honorific items
G = T.G


def _items(pred=lambda it, blob: True):
    import mxl_save
    raw = T.read(G.app.path)
    out = []
    for it in sorted(G.app.items, key=lambda i: (i['page'], i['y'], i['x'])):
        blob = bytes(mxl_save.item_blob(raw, it))
        if pred(it, blob):
            out.append((it, blob))
    return out


def _check_dump(blob, what):
    import mxl_inspect
    import mxl_format_fix
    import mxl_savecheck
    tb = mxl_savecheck.tables()
    data = G.app.data
    text = mxl_inspect.dump(blob, data, what)
    pos = 0
    host, _br = mxl_format_fix.parse_item(blob, data)
    while pos < len(blob):
        it, fields = mxl_inspect.layout(blob, pos)
        # every bit of the item, in order, no gap, no overlap; ends on the item's last byte
        at = pos * 8
        for off, n, lab, _v in fields:
            T.eq(off, at, f'{what}: field {lab!r} starts at bit {off}, expected {at}')
            at = off + n
        T.eq(at, (pos + it.size) * 8, f'{what}: layout end vs item size')
        T.eq(it.to_bytes(tb), blob[pos:pos + it.size], f'{what}: mxlsave re-encodes the item to its bytes')
        if pos == 0:                            # the host decoder reads the same top item
            T.eq(it.code, host['code'], f'{what}: code')
            if not it.simple:
                T.eq(it.ilvl, host['ilvl'], f'{what}: ilvl')
                T.eq(it.quality_name if it.quality_name != 'honorific' else host['quality'], host['quality'],
                     f'{what}: quality')
                T.eq([(s.id, s.value) for s in it.stats], [(s['id'], s['value']) for s in host['stats']],
                     f'{what}: stats in save order (id, value)')
                T.check(f'item level   {it.ilvl}' in text, f'{what}: item level missing in the dump')
                for s in it.stats:
                    T.check(f'{s.id:>4}  ' in text, f'{what}: stat {s.id} missing in the dump')
                if it.runeword_id is not None:
                    T.check(f'runeword id  {it.runeword_id}' in text, f'{what}: runeword id missing')
        pos += it.size
    T.check(f'{blob[0]:02X} {blob[1]:02X}' in text, f'{what}: hex dump missing')
    return text


@T.test
def inspect_dump_matches_the_decoder():
    import mxl_inspect
    n = 0
    for it, blob in _items():
        _check_dump(blob, f"{it['code']} page {it['page'] + 1} ({it['x']}, {it['y']})")
        n += 1
    T.check(n > 10, f'only {n} items checked')
    socketed = _items(lambda it, b: it.get('socketed'))
    T.check(socketed, 'the sample has no socketed item')
    if socketed:
        txt = mxl_inspect.dump(socketed[0][1], G.app.data)
        T.check('Socketed items (' in txt and 'socketed item 1' in txt, 'socketed items are not listed')


@T.test
def inspect_from_the_menu():
    it, blob = next((x for x in _items(lambda it, b: it.get('stats'))), (None, None))
    if it is None:
        T.skip('no item with stats')
    raw = T.read(G.app.path)
    lab = T.invoke(T.stash_menu(it['page'], it['x'], it['y']), 'Open in Bit editor')
    T.check(lab, 'no Open in Bit editor entry')
    T.pump()
    import mxl_tabs
    import mxl_bitedit
    w = mxl_tabs.built_owner('Bit editor')
    T.check(isinstance(w, mxl_bitedit.BitEditor), 'the Bit editor tab did not open')
    w.toggle_view()
    T.pump()
    T.check(w.text.get('1.0', 'end').strip() == w.dump_text().strip(), 'the text view does not show the dump')
    T.check(str(w.text.cget('state')) == 'disabled', 'the dump text is editable')
    w.copy_dump()
    T.eq(G.root.clipboard_get(), w.dump_text(), 'clipboard after Copy text dump')
    w.top.destroy()
    T.check(T.read(G.app.path) == raw, 'inspecting wrote the stash file')


@T.test
def library_add_list_place_undo():
    import os
    import mxl_itemlib
    import mxl_undo
    it, blob = next((x for x in _items(lambda it, b: it.get('stats'))), (None, None))
    if it is None:
        T.skip('no item with stats')
    T.check(os.path.realpath(mxl_itemlib.folder()).startswith(os.path.realpath(G.user_dir)),
            'library folder is not in the (copied) user folder')
    before = len(mxl_itemlib.load())
    G.answers['str'] = 'Tests/My test item'
    T.invoke(T.stash_menu(it['page'], it['x'], it['y']), 'Add to library...')
    entries = mxl_itemlib.load()
    T.eq(len(entries), before + 1, 'library entries after Add')
    e = entries[-1]
    T.eq((e['folder'], e['name'], e['code']), ('Tests', 'My test item', it['code']), 'entry')
    T.eq(mxl_itemlib.blob_of(e), blob, 'stored bytes = the item bytes')
    T.check('added to the item library' in T.status_text(), f'status: {T.status_text()!r}')
    w = mxl_itemlib.LibraryWindow(G.app)
    T.pump()
    w.q.set('test item')
    T.pump()
    T.eq([r['file'] for r in w.rows.values()], [e['file'] for e in mxl_itemlib.search(entries, 'test item')],
         'search result')
    T.check(e['file'] in [r['file'] for r in w.rows.values()], 'the entry is not listed')
    w.q.set('no such thing at all')
    T.pump()
    T.eq(len(w.rows), 0, 'rows for a search without match')
    w.q.set('My test')
    T.pump()
    iid = next(k for k, r in w.rows.items() if r['file'] == e['file'])
    w.tree.selection_set(iid)
    path = G.app.path
    snap = T.stash_snap(path, G.app.data)
    raw0 = T.read(path)
    undo0 = len(getattr(G.app, '_undo', []) or [])
    w.place()
    T.pump()
    now = T.stash_snap(path, G.app.data)
    g, new, chg = T.diff(snap, now)
    T.eq((g, chg, len(new)), ([], [], 1), 'place a copy: (removed, changed, number added)')
    T.check(T.same_item(now[new[0]][1], blob), 'the copy is not the stored item (only its place may differ)')
    T.eq(new[0][0], G.app.page(), 'the copy is on the page shown')
    import mxl_savecheck
    r = mxl_savecheck.examine(path, T.read(path), raw0)
    T.check(r.ok, f'mxlsave check of the written stash: {getattr(r, "summary", r)}')
    T.eq(len(G.app._undo), undo0 + 1, 'undo records after Place a copy')
    msg = mxl_undo.undo(G.app)
    T.pump()
    T.check(msg and 'removed' in msg, f'undo message {msg!r}')
    T.eq(T.read(path), raw0, 'stash bytes after the undo')
    # rename + delete
    G.answers['str'] = 'Other/Renamed'
    w.rename()
    e2 = next(x for x in mxl_itemlib.load() if x['file'] == e['file'])
    T.eq((e2['folder'], e2['name']), ('Other', 'Renamed'), 'renamed entry')
    w.q.set('')
    T.pump()
    iid = next(k for k, r in w.rows.items() if r['file'] == e['file'])
    w.tree.selection_set(iid)
    w.delete()
    T.check(all(x['file'] != e['file'] for x in mxl_itemlib.load()), 'entry still listed after Delete')
    T.check(not os.path.exists(os.path.join(mxl_itemlib.folder(), e['file'])), '.d2i still there after Delete')
    w.top.destroy()


@T.test
def library_reachable_from_more():
    import mxl_toolbar
    labels = [lab() for lab, _c in mxl_toolbar.EXTRA]
    T.check('Item library...' in labels, f'More entries: {labels}')


T.main(globals())
