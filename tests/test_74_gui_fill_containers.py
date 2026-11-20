"""Creator tab, "All containers": one of every container / cluster / barrel / crate / vessel at Quantity 1000 on the
next empty stash pages through the normal stash writer, undoable; with no empty page nothing is written and a
message says so."""
import capytest as T

MODE = 'gui'
RESET = True
G = T.G


def creator():
    import mxl_creator_gui as CG
    import mxl_tabs
    CG.CreatorWindow(G.app)
    T.pump(10)
    w = mxl_tabs.built_owner('Creator')
    if w is None or w.edit_item is not None:
        raise T.Failed('no Creator window')
    return w


@T.test
def fill_then_undo():
    import mxl_undo
    path, data = G.app.path, G.app.data
    raw0 = T.read(path)
    snap0 = T.stash_snap(path, data)
    w = creator()
    w.fill_containers()
    T.pump(6)
    snap1 = T.stash_snap(path, data)
    new = [k for k in snap1 if k not in snap0]
    import mxl_creator
    n = len(mxl_creator.container_codes(data))
    T.check(len(new) > 90, f'only {len(new)} containers written')
    T.check(not {k[0] for k in new} & {k[0] for k in snap0}, 'a used page was written to')
    T.check('containers added' in w.status.cget('text'), f"status: {w.status.cget('text')!r}")
    T.check(n == len(new), 'one of every container')
    mxl_undo._do_undo(G.app)
    T.pump(6)
    T.eq(sorted(T.stash_snap(path, data)), sorted(snap0), 'items after fill + undo')
    T.check(T.read(path) == raw0, 'stash file bytes after fill + undo')


@T.test
def refused_without_empty_pages():
    import mxl_creator_gui as CG
    import mxl_save
    path, data = G.app.path, G.app.data
    w = creator()
    blob, _ = w.cr.build(w.cr.new_spec('normal', 'gc01'))
    used = {it['page'] for it in mxl_save.parse_stash(path, data)}
    ins = [(p, 0, 0, bytes(blob)) for p in range(mxl_save.STASH_PAGES) if p not in used]
    if ins:
        mxl_save.edit_stash(path, data, insert=ins, backup=False)
    CG._reload_main(G.app)
    T.pump(4)
    raw = T.read(path)
    n_boxes = len(G.boxes)
    w.fill_containers()
    T.pump(4)
    T.check(T.read(path) == raw, 'the stash file changed although no page was empty')
    T.check(any('adjacent empty' in b[2] for b in G.boxes[n_boxes:]), f'no refusal message: {G.boxes[n_boxes:]}')


T.main(globals())
