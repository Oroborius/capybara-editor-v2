#!/usr/bin/env python3
"""Self-check of mxlsave on sample files, and cross-check against the editor's own parser.

    python tools/mxlsave/tests/selfcheck.py <folder or file>... [--data DIR] [--expect-fail SUBSTRING]...

1. verify      every sample: parse -> rebuild -> byte-identical (with tables, and .d2s / stash without tables)
2. checksum    every .d2s: the computed checksum equals the stored one, the size field equals the file size
3. edit        every .d2s: change header + stat fields through mxlsave, rebuild, parse again, values kept
4. cross-check when the editor's modules can be imported (run with the application's Python and
               PYTHONPATH=<AppDir>/opt/capybara, MXL_USER_DIR=<copy>): every value both parsers decode is
               compared - character stats, skills, each item's header fields and every stat of every list,
               the stash pages. The edited files of step 3 must also open in the editor's reader.

Files whose name contains an --expect-fail substring (default: "corrupt") must be REFUSED by both parsers.
Never point this at real saves you care about: it only reads, but use copies anyway. Exit status 0 = all good.
"""
import argparse
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from mxlsave import Tables, D2S, Stash, FormatError, checksum          # noqa: E402
from mxlsave.cli import kind_of, load_bytes, verify                    # noqa: E402
from mxlsave.items import QUALITY                                      # noqa: E402

QUALITY_EDITOR = dict(QUALITY)
QUALITY_EDITOR[9] = 'tempered'          # the editor's internal name of quality 9


class Report:
    def __init__(self):
        self.counts = {}
        self.failures = []

    def ok(self, step):
        self.counts.setdefault(step, [0, 0])[0] += 1

    def fail(self, step, what):
        self.counts.setdefault(step, [0, 0])[1] += 1
        self.failures.append(f'{step}: {what}')


def collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                out += [os.path.join(root, f) for f in sorted(files)]
        else:
            out.append(p)
    keep = []
    for f in out:
        try:
            with open(f, 'rb') as fh:
                kind_of(f, fh.read(4))
            keep.append(f)
        except (FormatError, OSError):
            pass
    return keep


# ---------------------------------------------------------------------- editor side

def editor_modules():
    try:
        import mxl_format_fix
        mxl_format_fix.install()
        import mxl_data
        import mxl_char
        import mxl_save
        import mxl_format
    except Exception as e:                  # not run inside the application's environment
        return None, f'{type(e).__name__}: {e}'
    user = os.environ.get('MXL_USER_DIR')
    if not user:
        return None, 'MXL_USER_DIR is not set'
    return dict(data=mxl_data.Data(os.path.join(user, 'data')), char=mxl_char, save=mxl_save,
                fmt=mxl_format), ''


def compare_item(mine, theirs, where, diffs):
    """mine: mxlsave Item, theirs: the editor's item record."""
    def chk(name, a, b):
        if a != b:
            diffs.append(f'{where} {mine.code!r} {name}: mxlsave {a!r} / editor {b!r}')
    chk('code', mine.code, theirs['code'])
    for k in ('location', 'equipped', 'x', 'y', 'panel', 'version', 'socketed_count'):
        chk(k, getattr(mine, k), theirs[k])
    chk('size', mine.size, theirs['_size'])
    chk('identified', mine.flag(4), theirs['identified'])
    chk('has_sockets', mine.flag(11), theirs['has_sockets'])
    chk('ethereal', mine.flag(22), theirs['ethereal'])
    if not mine.simple:
        chk('id', mine.id, theirs['id'])
        chk('ilvl', mine.ilvl, theirs['ilvl'])
        chk('quality', QUALITY_EDITOR.get(mine.quality), theirs['quality'])
        for k, e in (('image', 'image'), ('auto_affix', 'auto_affix'), ('subquality', 'subquality'),
                     ('prefix', 'prefix'), ('suffix', 'suffix'), ('set_unique_id', 'set_unique_id'),
                     ('rare_names', 'rare_names'), ('rare_affixes', 'rare_affixes'),
                     ('personalized_name', 'personalized_name'), ('quantity', 'quantity'), ('sockets', 'sockets'),
                     ('max_durability', 'max_durability'), ('durability', 'durability')):
            chk(k, getattr(mine, k), theirs.get(e))
        if mine.runeword_id is not None:
            chk('runeword (low 12 bits)', mine.runeword_id & 0xFFF, theirs.get('runeword'))
        lists = [('stats', mine.stats, theirs['stats'])]
        for bit in range(5):
            lists.append((f'set_stats_{bit}', mine.set_stats.get(bit, []), theirs.get(f'set_stats_{bit}', [])))
        lists.append(('stats_runeword', mine.runeword_stats or [], theirs.get('stats_runeword', [])))
        for name, a, b in lists:
            chk(name, [(s.id, s.param, s.value) for s in a], [(s['id'], s['param'], s['value']) for s in b])
    chk('socketed items', len(mine.socketed), len(theirs.get('socketed', [])))
    for a, b in zip(mine.socketed, theirs.get('socketed', [])):
        compare_item(a, b, where + ' socketed', diffs)


def cross_d2s(path, obj, ed, diffs):
    c = ed['char'].Character(path, ed['data'])
    if [(s.id, s.param, s.value) for s in obj.stats] != [tuple(s) for s in c.stats]:
        diffs.append('character stats differ')
    if b'if' + obj.skills != bytes(c.skills):
        diffs.append('skills section differs')
    h = obj.header
    for name, a, b in (('name', h.name_str, c.name), ('class', h.cls, c.cls), ('level', h.level, c.level),
                       ('progression', h.progression, c.progression), ('merc id', h.merc_id, c.merc_id),
                       ('status', h.status, c.status)):
        if a != b:
            diffs.append(f'header {name}: mxlsave {a!r} / editor {b!r}')
    for d in range(3):
        for wd in range(48):
            if obj.quests.words[d][wd] != c.quest_word(d, wd):
                diffs.append(f'quest word {d}/{wd}')
        act = set(obj.waypoints.active(d))
        for n in range(96):
            if (n in act) != c.waypoint(d, n):
                diffs.append(f'waypoint {d}/{n}')
    for name, mine, theirs in (('items', obj.items, c.items), ('mercenary items', obj.merc_items, c.merc_items)):
        if (mine is None) != (theirs is None):
            diffs.append(f'{name}: present in one parser only')
            continue
        if mine is None:
            continue
        if len(mine) != len(theirs):
            diffs.append(f'{name}: {len(mine)} / {len(theirs)}')
        for a, b in zip(mine, theirs):
            compare_item(a, b.it, name, diffs)
            if a.to_bytes_with_socketed(ed['tables']) != bytes(b.blob):
                diffs.append(f'{name} {a.code!r}: rebuilt bytes differ from the editor blob')
    if c.build() != obj.to_bytes(ed['tables']):
        diffs.append('rebuilt files differ between the two implementations')
    return len(obj.items) + sum(len(i.socketed) for i in obj.items) + len(obj.merc_items or [])


def cross_stash(path, obj, ed, diffs):
    theirs = ed['save'].parse_stash(path, ed['data'])
    mine = [(p.number, it) for p in obj.pages for it in p.items]
    if len(mine) != len(theirs):
        diffs.append(f'stash items: {len(mine)} / {len(theirs)}')
    for (page, a), b in zip(mine, theirs):
        if page != b['page']:
            diffs.append(f'page of {a.code!r}: {page} / {b["page"]}')
        if a.offset != b['_offset']:
            diffs.append(f'offset of {a.code!r}: {a.offset} / {b["_offset"]}')
        compare_item(a, b, f'page {page}', diffs)
    try:
        lp = ed['save'].last_page(path)
        if lp != obj.last_page:
            diffs.append(f'last page: {obj.last_page} / {lp}')
    except Exception as e:
        diffs.append(f'editor last_page failed: {e}')
    return len(mine)


# ---------------------------------------------------------------------- steps

def edit_check(path, data, tables, ed, rep, tmp):
    obj = D2S.parse(data, tables)
    obj.header.merc_exp = (obj.header.merc_exp + 12345) & 0xFFFFFFFF
    obj.header.hotkeys[9] = 0x8000 | 5
    obj.header.last_played += 60
    for s in obj.stats:
        if s.id == 14:
            s.value = 4242
    obj.quests.words[0][1] |= 0x1001
    out = obj.to_bytes(tables)
    back = D2S.parse(out, tables)
    good = (back.header.merc_exp == obj.header.merc_exp and back.header.hotkeys[9] == 0x8005
            and back.stat(14) in (4242, 0) and back.header.file_size == len(out)
            and back.header.checksum == checksum(out) and back.to_bytes(tables) == out)
    if not good:
        rep.fail('edit', f'{path}: edited values not kept')
        return
    if ed:
        p = os.path.join(tmp, os.path.basename(path).split('.')[0] + '.d2s')
        with open(p, 'wb') as f:
            f.write(out)
        try:
            c = ed['char'].Character(p, ed['data'])
            if c.build() != out or struct.unpack_from('<I', c.head, 0xBB)[0] != obj.header.merc_exp:
                rep.fail('edit', f'{path}: the editor reads the edited file differently')
                return
        except Exception as e:
            rep.fail('edit', f'{path}: the editor refuses the edited file: {e}')
            return
    rep.ok('edit')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--data')
    ap.add_argument('--expect-fail', action='append', default=None)
    a = ap.parse_args(argv)
    bad_marks = a.expect_fail or ['corrupt']
    tables = Tables.find(a.data)
    if tables is None:
        print('game tables not found (--data DIR): nothing can be checked on items')
        return 2
    ed, why = editor_modules()
    if ed:
        ed['tables'] = tables
    rep = Report()
    files = collect(a.paths)
    n_items = 0
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            with open(f, 'rb') as fh:
                data = fh.read()
            kind = kind_of(f, data)
            expect_bad = any(m in os.path.basename(f) for m in bad_marks)
            ok, msg = verify(f, tables)
            if expect_bad:
                if ok:
                    rep.fail('negative', f'{f}: a file marked as bad was accepted')
                else:
                    rep.ok('negative')
                if ed and kind == 'stash':
                    try:
                        ed['save'].parse_stash(f, ed['data'])
                        rep.fail('negative-editor', f'{f}: refused by mxlsave ({msg}) but read by the editor')
                    except Exception:
                        rep.ok('negative-editor')
                continue
            if not ok:
                rep.fail('verify', f'{f}: {msg}')
                continue
            rep.ok('verify')
            if kind in ('d2s', 'stash'):
                ok2, msg2 = verify(f, None)
                rep.ok('verify-no-tables') if ok2 else rep.fail('verify-no-tables', f'{f}: {msg2}')
            obj = load_bytes(data, kind, tables)
            if kind == 'd2s':
                if obj.header.checksum == checksum(data) and obj.header.file_size == len(data):
                    rep.ok('checksum')
                else:
                    rep.fail('checksum', f'{f}: stored {obj.header.checksum:08x} computed {checksum(data):08x}')
                edit_check(f, data, tables, ed, rep, tmp)
            if ed and kind in ('d2s', 'stash'):
                diffs = []
                try:
                    n_items += (cross_d2s if kind == 'd2s' else cross_stash)(f, obj, ed, diffs)
                except Exception as e:
                    diffs.append(f'editor parser failed: {type(e).__name__}: {e}')
                if diffs:
                    rep.fail('cross-check', f'{f}: {len(diffs)} differences, first: {diffs[0]}')
                else:
                    rep.ok('cross-check')
    print(f'{len(files)} sample files')
    for step, (good, bad) in rep.counts.items():
        print(f'  {step:18} {good} ok, {bad} failed')
    if ed:
        print(f'  cross-checked items (with socketed): {n_items}')
    else:
        print(f'  cross-check skipped: editor modules not importable ({why})')
    for line in rep.failures:
        print('FAIL', line)
    return 1 if rep.failures else 0


if __name__ == '__main__':
    sys.exit(main())
