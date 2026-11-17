#!/usr/bin/env python3
"""Cross-check of everything the editor derives from the game's tables. Read-only: it loads the extracted tables
of a user folder, builds every catalogue item in memory and writes one report (stdout, or --out FILE).

Run it with the Python and the module folder of a built app (Linux AppDir shown):

    APP=dist/linux/AppDir
    $APP/opt/python/bin/python3.10 tools/audit_game_data.py --app $APP/opt/capybara \\
        --user-dir <copy of the editor's user folder> [--game-dir <Median XL folder>] \\
        [--save-dir <copy of a save folder>] [--txt-dir <folder of vanilla *.txt tables>] [--out report.txt]

Environment instead of arguments: MXL_APP_DIR, MXL_USER_DIR, MXL_GAME_DIR, MXL_SAVE_DIR, MXL_TXT_DIR.
The user folder must be a COPY (the host's `paths` module may create missing sub-folders in it); the game and
save folders are only read.

What is checked, per category (uniques, relics, set items, runewords, mystic orbs, gems / runes, base items):
- every mod resolves to a property, the property to stats with save bits and a label, every skill / class /
  state / monster param to a name;
- the creator builds the item at minimum and maximum rolls, the bytes read back (mxl_format.parse_item) to the
  stats that were written, the record re-encodes byte-identically and the edit path (spec_from_item -> build)
  gives the same record again;
- the rendered tooltip has no placeholder left ('skill #', 'stat #', '%d', '%s', 'None', buffalo text, empty line);
- names: empty names, labels the creator list cannot tell apart, placeholder rows.
Lines starting with '!' are problems (something the editor gets wrong or cannot handle); lines starting with 'i'
are properties of the game's own tables that the editor shows as they are (each with the reason in its text).
Extra sections: honorific (quality 9) items built from the cube recipe's output; the extracted tables against the
game's own MPQ (--game-dir); every item of the save files of --save-dir (re-encode byte-identical, no-op character
rebuild byte-identical, tooltip, edit path; with --noop-edit also: an unchanged edit gives the item's own bytes);
the binary readers against vanilla text tables (--txt-dir).
"""
import argparse
import collections
import glob
import os
import re
import struct
import sys
import traceback

PLACEHOLDER_LABEL = re.compile(r'%\+?[ds]|POLAR BUFFALO')
PLACEHOLDER = re.compile(r'skill #|stat #|class #|%\+?[ds]|\bNone\b|POLAR BUFFALO|#\d')
SKILL_FUNCS = {15: 'cast', 16: 'aura', 24: 'charges', 27: 'skill', 28: 'skill'}
CLASS_FUNCS = {13}
MONSTER_FUNCS = {23}
STATE_STAT = 98
MAX_EXAMPLES = 6
HOW = re.compile(r' \((min|max)\)')


class Report:
    def __init__(self):
        self.sections = []
        self.cur = None

    def section(self, title):
        self.cur = dict(title=title, totals=collections.OrderedDict(), problems=collections.OrderedDict(),
                        infos=collections.OrderedDict())
        self.sections.append(self.cur)

    def total(self, key, n=1):
        self.cur['totals'][key] = self.cur['totals'].get(key, 0) + n

    def note(self, key, text):
        self.cur['totals'][key] = text

    def info(self, cls, example):
        """A property of the game's own data the editor shows as it is: listed ('   i ...'), not a problem."""
        self.problem(cls, example, 'infos')

    def problem(self, cls, example, kind='problems'):
        """Counted once per distinct example (the ' (min)' / ' (max)' build of one item is one example)."""
        example = HOW.sub('', str(example))
        p = self.cur[kind].setdefault(cls, [0, [], set()])
        if example in p[2]:
            return
        p[2].add(example)
        p[0] += 1
        if len(p[1]) < MAX_EXAMPLES:
            p[1].append(example)

    def text(self):
        out = []
        for s in self.sections:
            out.append('== ' + s['title'])
            for k, v in s['totals'].items():
                out.append(f'   {k}: {v}')
            if not s['problems']:
                out.append('   no problems')
            for cls, (n, ex, _seen) in sorted(s['problems'].items(), key=lambda kv: -kv[1][0]):
                out.append(f'   ! {cls}: {n}')
                for e in ex:
                    out.append(f'       {e}')
            for cls, (n, ex, _seen) in sorted(s['infos'].items(), key=lambda kv: -kv[1][0]):
                out.append(f'   i {cls}: {n}')
                for e in ex:
                    out.append(f'       {e}')
            out.append('')
        return '\n'.join(out)


def plain(tt):
    return [''.join(t for _c, t in line) for line in tt]


class Audit:
    def __init__(self, args):
        self.args = args
        self.rep = Report()
        import paths
        import mxl_data
        import mxl_format
        import mxl_format_fix
        mxl_format_fix.install()
        import mxl_creator
        import mxl_rules
        import mxl_tooltip
        import mxl_statnames
        import mxl_statnames_ext
        self.fmt, self.cm, self.rules, self.tip = mxl_format, mxl_creator, mxl_rules, mxl_tooltip
        self.sn, self.snx = mxl_statnames, mxl_statnames_ext
        self.d = mxl_data.Data(paths.DATA_DIR)
        self.cr = mxl_creator.Creator(self.d)
        self.unresolved_skills = set()
        self.skill_refs = set()

    # ------------------------------------------------------------------ names of params
    def skill_name(self, sk):
        f = getattr(self.sn, 'skill_name', None)
        n = f(self.d, sk) if f else self.d.skill_names.get(sk)
        if n and not n.startswith('skill #') and 'POLAR BUFFALO' not in n.upper():
            return n
        return None

    def stat_label(self, sid):
        ic = self.d.isc.get(sid) if isinstance(self.d.isc, dict) else None
        if ic is None:
            return None
        return self.sn.stat_text(self.d, sid, None, 1, ic.get('desc')) or self.snx.fallback_label(sid)

    def check_stat(self, where, s):
        """One stat {id, param, value} an item would carry."""
        d, rep = self.d, self.rep
        sid, param = s['id'], s.get('param')
        ic = d.isc.get(sid)
        if ic is None:
            rep.problem('stat id not in itemstatcost', f'{where}: stat {sid}')
            return
        if not ic.get('bits'):
            return                                   # not saved on items: the creator drops it too
        if not self.stat_label(sid):
            rep.problem('stat without a label', f'{where}: stat {sid}')
        pb = ic.get('param') or 0
        if param and pb and not 0 <= param < (1 << pb):
            rep.problem('param does not fit the stat\'s param bits', f'{where}: stat {sid} param {param} ({pb} bits)')
        raw = s['value'] + (ic.get('add') or 0)
        if not 0 <= raw < (1 << ic['bits']):
            # the table asks for more than the stat's save bits hold. Not an editor defect: Creator.roll narrows
            # the mod's range to what can be stored (the item is built with the nearest storable value; the
            # encoder itself refuses an unstorable value with StoreError). Whether the game keeps the table's
            # value in memory until the item is saved can only be seen in the game.
            lo, hi = -(ic.get('add') or 0), (1 << ic['bits']) - 1 - (ic.get('add') or 0)
            rep.info('game data: mod value outside the stat\'s save range (the creator stores the nearest value)',
                     f'{where}: stat {sid} value {s["value"]} (storable {lo}..{hi})')
        func = ic.get('func')
        if func in SKILL_FUNCS and param is not None:
            sk = param >> 6 if SKILL_FUNCS[func] in ('cast', 'charges') else param
            self.skill_refs.add(sk)
            if self.skill_name(sk) is None:
                self.unresolved_skills.add(sk)
                rep.problem('skill param without a name', f'{where}: stat {sid} -> skill {sk}')
        elif func in CLASS_FUNCS and param is not None:
            if not 0 <= param < len(self.rules.CLASSES):
                rep.problem('class param without a name', f'{where}: stat {sid} -> class {param}')
        elif func in MONSTER_FUNCS and param is not None:
            if not (0 <= param < len(d.monster_names) and d.monster_names[param]):
                rep.problem('monster param without a name', f'{where}: stat {sid} -> monster {param}')
        if sid == STATE_STAT and param is not None:
            if not 0 <= param < self.n_states:
                rep.problem('state param is not a row of the states table', f'{where}: state {param}')
            elif not self.sn.state_name(d, param):
                # states.bin holds no name strings; a state gets its name from the skills that set it or from
                # its buff icon (stateicons). These states have neither (no table of the game names them:
                # visual / marker states of event awards and a few uniques): the editor shows '#N'.
                rep.info('game data: state without a name in any table (no skill sets it, no buff icon)',
                         f'{where}: state {param}')

    @property
    def n_states(self):
        n = getattr(self, '_n_states', None)
        if n is None:
            try:
                n = len(self.d._rows('states'))
            except Exception:
                n = 1 << 16
            self._n_states = n
        return n

    def check_mods(self, where, mods):
        d, rep = self.d, self.rep
        for m in mods:
            prop, param, lo, hi = (m['prop'], m['param'], m['min'], m['max']) if isinstance(m, dict) else m
            if not 0 <= prop < len(d.props):
                rep.problem('property id not in properties', f'{where}: property {prop}')
                continue
            for how, v in (('min', min(lo, hi)), ('max', max(lo, hi))):
                try:
                    stats = self.rules.mods_stats([(prop, param, v, v)], d, 'min')
                except Exception as e:
                    rep.problem('property cannot be turned into stats', f'{where}: property {prop}: {e!r}')
                    break
                for s in stats:
                    self.check_stat(f'{where} ({how})', s)

    # ------------------------------------------------------------------ build / read back
    def norm(self, stats):
        acc = {}
        for s in stats or ():
            k = (s['id'], s.get('param') or None)
            acc[k] = acc.get(k, 0) + s['value']
        # a zero value is a group follower the format writes with its lead (cold length with cold damage...)
        return sorted(((k, v) for k, v in acc.items() if v), key=lambda kv: (kv[0][0], kv[0][1] or 0))

    def check_tooltip(self, where, it):
        try:
            lines = plain(self.tip.item_tooltip(it, self.d))
        except Exception as e:
            self.rep.problem('tooltip raised', f'{where}: {e!r}')
            return
        blank = [not ln.strip() for ln in lines]
        if lines and (blank[0] or blank[-1] or any(a and b for a, b in zip(blank, blank[1:]))):
            raw = ''
            try:
                raw = str(self.d.base(it['code']).name_raw or '').replace('\\n', '\n')
            except Exception:
                pass
            if raw.startswith('\n') and blank[-1] and not blank[0] and len(lines) > 1 and not blank[-2] \
                    and not any(a and b for a, b in zip(blank, blank[1:])):
                # the item's name string itself begins with a line break (the game draws a name's lines bottom
                # up, so that empty line closes the name block): shown as the game's string has it
                self.rep.info('game data: name string starts with a line break (one empty line ends the tooltip)',
                              where)
            else:
                self.rep.problem('tooltip: empty line (first, last or doubled; single ones separate sections)',
                                 where)
        for ln in lines:
            m = PLACEHOLDER.search(ln)
            if m:
                self.rep.problem(f'tooltip: placeholder "{m.group(0) if not m.group(0)[1:].isdigit() else "#N"}"',
                                 f'{where}: {ln.strip()[:90]}')

    def roundtrip(self, where, spec, tooltip=True):
        """Build -> parse -> compare -> re-encode -> edit path. True when the item could be built."""
        cr, d, rep, cm = self.cr, self.d, self.rep, self.cm
        built = False
        if spec.get('code') in d.bases and not spec.get('auto'):
            auto = cr.auto_choices(spec['code'], spec['ilvl'])        # bases with an innate affix need one chosen
            if auto:
                spec['auto'] = auto[0][0]
                self.check_mods(where + ' innate affix', auto[0][2]['mods'])
        for how in ('min', 'max'):
            sp = dict(spec, rolls={})
            try:
                cr.roll(sp, how)
                blob, rec = cr.build(sp)
            except cm.CreateError as e:
                rep.problem('creator refuses to build', f'{where} ({how}): {str(e)[:110]}')
                continue
            except Exception as e:
                rep.problem('build raised', f'{where} ({how}): {e!r}'[:200])
                continue
            built = True
            try:
                it = self.fmt.read_item_list(blob, 0, 1, d)[0][0]
            except Exception as e:
                rep.problem('built bytes do not parse', f'{where} ({how}): {e!r}')
                continue
            if rec is not None:
                for key in ('stats', 'stats_runeword'):
                    if self.norm(rec.get(key)) != self.norm(it.get(key)):
                        rep.problem('stats read back differently', f'{where} ({how}) {key}')
            try:
                r1, n = cm.decode_item(blob, d)
                if cm.encode_item(r1, d) != blob[:n]:
                    rep.problem('record does not re-encode identically', f'{where} ({how})')
            except Exception as e:
                rep.problem('decode / re-encode raised', f'{where} ({how}): {e!r}')
                continue
            try:
                sp2 = cr.spec_from_item(it)
                sp2.pop('_orig', None)            # the spec model alone (the editor also carries the original item)
                blob2, _rec2 = cr.build(sp2)
                r2, _n2 = cm.decode_item(blob2, d)
                diff = sorted(k for k in set(r1) | set(r2) if k not in ('id', 'image') and r1.get(k) != r2.get(k))
                if 'stats' in diff and self.norm(r1.get('stats')) == self.norm(r2.get('stats')):
                    diff.remove('stats')
                if diff:
                    rep.problem(f'edit path changes the item ({", ".join(diff)})', f'{where} ({how})')
            except cm.CreateError as e:
                rep.problem('edit path refuses the item', f'{where} ({how}): {str(e)[:110]}')
            except Exception as e:
                rep.problem('edit path raised', f'{where} ({how}): {e!r}'[:200])
            if tooltip and how == 'max':
                self.check_tooltip(where, it)
        if built:
            rep.total('built')
        return built

    def dupes(self, labels, what):
        seen = collections.Counter(l.casefold() for l, _k in labels)
        groups = collections.defaultdict(list)
        for l, k in labels:
            if not l.strip():
                self.rep.problem(f'{what}: empty name', str(k))
            elif seen[l.casefold()] > 1:
                groups[l].append(k)
        for l, ks in groups.items():
            self.rep.problem(f'{what}: label shared by several rows', f'{l!r} x{len(ks)}: rows {ks[:8]}')

    # ------------------------------------------------------------------ categories
    def uniques(self):
        cr, d, rep = self.cr, self.d, self.rep
        rows = cr.uniques()
        listed = {i for i, _n, _u in rows}
        shown = cr.catalog_labels('unique')              # the labels of the creator list (mxl_creator_gui.fill_list)
        for relic in (False, True):
            rep.section('Relics (uniques on base cotw)' if relic else 'Unique items')
            labels = []
            for i, name, u in rows:
                if (u['code'] == 'cotw') != relic:
                    continue
                rep.total('listed by the creator')
                where = f'unique {i} {name!r}'
                label = shown[i]
                labels.append((label, i))
                if not u['mods']:
                    if cr.unique_enabled(i):
                        # an enabled row: the game's own item, its text is the base item's description
                        rep.info('game data: enabled row without any mod (quest / reagent items)', where)
                    else:
                        rep.problem('listed row without any mod that is not enabled (leftover row)', where)
                self.check_mods(where, u['mods'])
                self.roundtrip(where, cr.new_spec('unique', None, i))
            self.dupes(labels, 'creator list')
            if relic:
                hidden = [i for i, u in enumerate(d.uniques) if u['code'] == 'cotw' and i not in listed]
                rep.total('placeholder rows hidden from the creator (no mods)', len(hidden))
            else:
                hidden = [i for i, u in enumerate(d.uniques) if u['code'] != 'cotw' and i not in listed]
                rep.total('table rows not listed (no base / no name string / empty and not enabled)', len(hidden))

    def sets(self):
        cr, d, rep = self.cr, self.d, self.rep
        rep.section('Set items')
        labels = []
        shown = cr.catalog_labels('set')
        for i, name, u in cr.set_items():
            rep.total('listed by the creator')
            where = f'set item {i} {name!r}'
            labels.append((shown[i], i))
            self.check_mods(where, u['mods'])
            self.roundtrip(where, cr.new_spec('set', None, i))
        self.dupes(labels, 'creator list')
        rep.total('table rows not listed', len(d.set_items) - len(labels))

    def runewords(self):
        cr, d, rep = self.cr, self.d, self.rep
        rep.section('Runewords')
        labels = []
        for i, name, runes in cr.runewords():
            rep.total('listed by the creator')
            where = f'runeword {i} {name!r}'
            labels.append((f"{name} - {' '.join(str(d.base(r).name) for r in runes)}", i))
            self.check_mods(where, d.runeword_mods[i])
            bases = cr.runeword_bases(i)
            if not bases:
                rep.problem('no base can hold it (the creator list hides it)', where)
                continue
            spec = cr.new_spec('runeword', bases[0].code, i)
            spec['sockets'] = len(runes)
            spec['ilvl'] = 99
            self.roundtrip(where, spec)
        self.dupes(labels, 'creator list')

    def bases(self):
        cr, d, rep = self.cr, self.d, self.rep
        orbs = cr._orb_table()
        fillers = {c for c, _n in cr.sockets_fillers()}
        allb = cr.bases()
        for title, pick in (('Mystic orbs', lambda b: b.code in orbs),
                            ('Gems and runes (socket fillers)', lambda b: b.code in fillers and b.code not in orbs),
                            ('Other base items', lambda b: b.code not in orbs and b.code not in fillers)):
            rep.section(title)
            labels = []
            for b in allb:
                if not pick(b) or b.code == 'gld ':
                    continue
                rep.total('listed by the creator')
                try:
                    label = cr.display_name(b.code)
                except Exception as e:
                    rep.problem('display name raised', f'{b.code!r}: {e!r}')
                    label = b.name or ''
                where = f'base {b.code!r} {label[:40]!r}'
                if b.code in orbs:
                    self.check_mods(where, orbs[b.code]['mods'])
                    eff = cr.orb_effects(b.code)
                    if not eff or not eff[0]:
                        rep.problem('mystic orb without effect text', where)
                    else:
                        label += ': ' + '; '.join(eff[0])
                        for t in eff[0]:
                            if PLACEHOLDER.search(t):
                                rep.problem('orb effect text has a placeholder', f'{where}: {t[:80]}')
                if b.code in d.gems:
                    for k, mods in enumerate(d.gems[b.code]):
                        self.check_mods(f'{where} (socketed in {("weapon", "armor", "shield")[k]})', mods)
                labels.append((label, b.code))
                self.roundtrip(where, cr.new_spec('normal', b.code))
            # the labels of the creator list itself (same names told apart by description / picture / item code)
            try:
                final = cr.base_list_rows([d.base(c) for _l, c in labels])
            except Exception as e:
                rep.problem('creator list labels raised', repr(e))
                final = labels
            for l, c in final:
                if PLACEHOLDER_LABEL.search(l):
                    rep.problem('creator list: label with a placeholder', f'{c!r}: {l[:90]}')
            self.dupes(final, 'creator list')
        for c in sorted(set(orbs) - {b.code for b in allb}):
            rep.problem('mysticorbs row whose item the creator does not list', repr(c))

    def honorific(self):
        """Quality 9 ('tempered' internally, 'Honorific' in the game's own loot filter strings): built from the
        output of the cube recipes that make them, read back, edited, re-encoded."""
        cr, d, rep, cm = self.cr, self.d, self.rep, self.cm
        rep.section('Honorific items (quality 9, cube output)')
        recipes = []
        for i, r in enumerate(cm._rows(d, 'cubemain')):
            if len(r) < 0x4C + 0x54 or not r[0] or r[0x4C + 6] != 9:
                continue
            fl, item, _iid, q, _qty = struct.unpack_from('<HHHBB', r, 0x14)
            recipes.append((i, fl, item, q, cr._cube_mods(r[:0x4C] + r[0x4C:])))
        rep.total('cube recipes with a quality 9 output', len(recipes))
        if not recipes:
            rep.problem('no honorific recipe found in cubemain', '-')
            return
        done = set()
        for row, fl, item, q, mods in recipes:
            self.check_mods(f'cube row {row}', mods)
            tag = d.itypes[item][0] if fl & 2 and 0 <= item < len(d.itypes) else None
            if tag in done or tag not in ('weap', 'armo'):
                continue
            done.add(tag)
            kind = 'weapons' if tag == 'weap' else 'armor'
            n = 0
            for b in cr.bases():
                if b.kind != kind or not cr.rare_name_choices(b.code)['rareprefix'] \
                        or not cr.rare_name_choices(b.code)['raresuffix']:
                    continue
                n += 1
                if n % 25 != 1:                    # every 25th base: all item types are met
                    continue
                rep.total('built')
                where = f'honorific {b.code!r} {b.name!r}'
                names = cr.rare_name_choices(b.code)
                spec = cr.new_spec('tempered', b.code)
                spec['ilvl'] = max(spec['ilvl'] or 1, 99)
                spec['rare_names'] = (names['rareprefix'][0][0], names['raresuffix'][0][0])
                spec['sockets'] = cr.max_sockets(b.code, spec['ilvl'])
                spec['extra'] = cr.honorific_stats(b.code)
                if not any(s['id'] == cm.HONORIFIC_STAT for s in spec['extra']):
                    rep.problem('honorific recipe output lacks the "orb effects doubled" stat', where)
                try:
                    blob, rec = cr.build(spec)
                    it = self.fmt.read_item_list(blob, 0, 1, d)[0][0]
                    if it.get('quality') != 'tempered' or self.norm(it['stats']) != self.norm(rec['stats']):
                        rep.problem('honorific reads back differently', where)
                    r1, k = cm.decode_item(blob, d)
                    if cm.encode_item(r1, d) != blob[:k]:
                        rep.problem('honorific does not re-encode identically', where)
                    sp2 = cr.spec_from_item(it)
                    sp2.pop('_orig', None)
                    r2 = cm.decode_item(cr.build(sp2)[0], d)[0]
                    diff = [x for x in set(r1) | set(r2) if x != 'id' and r1.get(x) != r2.get(x)]
                    if diff:
                        rep.problem(f'edit path changes the honorific item ({", ".join(sorted(diff))})', where)
                    self.check_tooltip(where, it)
                    if not self.rules.rare_name(it, d):
                        rep.problem('honorific item without a name', where)
                except Exception as e:
                    rep.problem('honorific path raised', f'{where}: {e!r}'[:200])

    def skills_table(self):
        d, rep = self.d, self.rep
        rep.section('Skills table')
        rows = d._rows('skills')
        rep.total('skills.bin rows', len(rows))
        rep.total('with a skilldesc name', len(d.skill_names))
        n = sum(1 for i in range(len(rows)) if self.skill_name(i) is None)
        rep.total('rows the editor has no name for', n)
        rep.total('distinct skill ids used by item stats', len(self.skill_refs))
        rep.total('of these without a name', len(self.unresolved_skills))
        if self.unresolved_skills:
            rep.problem('skill ids used by items that have no name', str(sorted(self.unresolved_skills))[:300])
        names = collections.Counter(self.skill_name(i) for i in range(len(rows)))
        names.pop(None, None)
        dup = {k: v for k, v in names.items() if v > 1}
        if dup and not hasattr(self.sn, 'skill_label'):
            rep.problem('skill names shared by several ids (a name picks the first id)',
                        ', '.join(f'{k} x{v}' for k, v in sorted(dup.items(), key=lambda kv: -kv[1])[:8]))
        rep.total('skill names shared by several ids (later ids are listed as "Name (#id)")', len(dup))

    # ------------------------------------------------------------------ outside sources
    def game_dir(self):
        g = self.args.game_dir
        if not g:
            return
        rep, d = self.rep, self.d
        rep.section('Extracted tables against the game folder')
        try:
            from mpq import MPQ
            mpqs = []
            for n in sorted(glob.glob(os.path.join(g, 'medianxl-*.mpq'))):
                try:
                    mpqs.append(MPQ(n))
                except Exception:
                    pass
        except Exception as e:
            rep.problem('game MPQs not readable', repr(e))
            return
        rep.total('MPQ archives opened', len(mpqs))
        for f in sorted(os.listdir(d.folder)):
            if not f.endswith(('.bin', '.tbl')):
                continue
            with open(os.path.join(d.folder, f), 'rb') as fh:
                mine = fh.read()
            theirs = None
            for path in ('data\\global\\excel\\' + f, 'data\\local\\lng\\eng\\' + f):
                for m in mpqs:
                    try:
                        theirs = m.read(path)
                    except Exception:
                        theirs = None
                    if theirs:
                        break
                if theirs:
                    break
            if theirs is None:
                rep.total('files not found in the MPQs')
            elif bytes(theirs) != mine:
                rep.problem('extracted table differs from the game\'s (stale extraction?)', f)
            else:
                rep.total('files identical to the game\'s')

    def saves(self):
        sd = self.args.save_dir
        if not sd:
            return
        import mxl_char
        import mxl_save
        cr, d, rep, cm = self.cr, self.d, self.rep, self.cm
        rep.section('Items of the save files')

        def item(where, it, blob, full=None):
            rep.total('items')
            if it.get('quality') == 'tempered':
                rep.total('honorific (quality 9) items')
            try:
                r, n = cm.decode_item(blob, d)
                if cm.encode_item(r, d) != blob[:n]:
                    rep.problem('item does not re-encode identically', where)
            except Exception as e:
                rep.problem('decode / re-encode raised', f'{where}: {e!r}'[:200])
            self.check_tooltip(where, it)
            for s in it.get('stats') or ():
                self.check_stat(where, s)
            if it.get('quality') in ('unique', 'set'):
                table = d.uniques if it['quality'] == 'unique' else d.set_items
                row = it.get('set_unique_id')
                if not isinstance(row, int) or not 0 <= row < len(table):
                    rep.problem('unique / set item that names no table row', f'{where}: id {row}')
                elif table[row]['code'] != it['code']:
                    rep.problem('unique / set row belongs to another base', f'{where}: row {row} is {table[row]["code"]!r}')
            try:
                sp = cr.spec_from_item(it)
            except cm.CreateError:
                rep.total('items the creator does not edit (simple / unknown rows)')
                return
            except Exception as e:
                rep.problem('edit path raised', f'{where}: {e!r}'[:200])
                return
            if self.args.noop_edit:
                noop(where, sp, full if full is not None else blob)

        PLACE = ('location', 'equipped', 'x', 'y', 'panel')

        def noop(where, sp, blob):
            """Edit item -> Replace with nothing changed: the bytes the creator would write against the item's
            own (socketed items included). Twice: as the editor does it (the original item carried through,
            Creator._carry) and from the spec model alone, which shows what the model itself cannot hold."""
            rep.total('no-op edit: items tried')
            try:
                new, _rec = cr.build(dict(sp))
                if bytes(new) == bytes(blob):
                    rep.total('no-op edit: byte-identical')
                else:
                    rep.total('no-op edit: NOT byte-identical')
                    rep.problem('no-op edit is not byte-identical', where)
            except Exception as e:
                rep.total('no-op edit: NOT byte-identical')
                rep.problem('no-op edit raised', f'{where}: {e!r}'[:200])
            try:
                sp2 = {k: v for k, v in sp.items() if k != '_orig'}
                new, _rec = cr.build(sp2)
                r1, k1 = cm.decode_blob(bytes(blob), d)
                r2, k2 = cm.decode_blob(bytes(new), d)
                diff = sorted(k for k in set(r1) | set(r2) if k not in PLACE and r1.get(k) != r2.get(k))
                for k in [k for k in diff if 'stats' in k]:
                    if self.norm(r1.get(k)) == self.norm(r2.get(k)):
                        diff.remove(k)
                strip = [[{k: v for k, v in c.items() if k not in PLACE} for c in ks] for ks in (k1, k2)]
                if strip[0] != strip[1]:
                    diff.append('socketed items')
                if not diff:
                    rep.total('no-op edit, spec model alone: same item (place aside)')
                for k in diff:
                    rep.total(f'no-op edit, spec model alone: differs in {k}')
            except Exception as e:
                rep.problem('no-op edit (spec model alone) raised', f'{where}: {e!r}'[:200])
        for p in sorted(glob.glob(os.path.join(sd, '*'))):
            n = os.path.basename(p)
            try:
                if n.endswith('.d2s'):
                    with open(p, 'rb') as f:
                        raw = f.read()
                    ch = mxl_char.Character(p, d)
                    rep.total('character files')
                    if ch.build() != raw:
                        rep.problem('no-op character rebuild is not byte-identical', n)
                    for e in ch.items + (ch.merc_items or []):
                        item(f'{n} {e.it["code"]!r} {str(e.it.get("name"))[:30]!r}', e.it, e.blob)
                elif n.endswith(('.stash', '.shared')):
                    with open(p, 'rb') as f:
                        raw = f.read()
                    items = mxl_save.parse_stash(p, d)
                    rep.total('stash files')
                    for it in items:
                        if '_offset' in it and '_size' in it:
                            item(f'{n} {it["code"]!r} {str(it.get("name"))[:30]!r}', it,
                                 raw[it['_offset']:it['_offset'] + it['_size']], mxl_save.item_blob(raw, it))
            except Exception as e:
                rep.problem('file could not be read', f'{n}: {e!r}'[:200])

    def txt(self):
        """The binary readers against vanilla text tables: the mod changed most values, so a column that agrees on
        most rows shows the offset is read right; the differing rows are the mod's own changes."""
        td = self.args.txt_dir
        if not td:
            return
        rep, d = self.rep, self.d
        rep.section('Binary table readers against vanilla text tables (agreement shows the offsets are right)')

        def table(name):
            p = os.path.join(td, name)
            if not os.path.exists(p):
                return None
            with open(p, encoding='latin1') as f:
                lines = [ln.rstrip('\r\n').split('\t') for ln in f]
            return [dict(zip(lines[0], ln)) for ln in lines[1:] if ln and ln[0] and ln[0] != 'Expansion']

        def num(v):
            try:
                return int(v or 0)
            except ValueError:
                return None

        def compare(label, pairs):
            same = sum(1 for a, b in pairs if a == b)
            rep.note(f'{label}: rows agreeing', f'{same} / {len(pairs)}')
            if pairs and same * 2 < len(pairs):
                rep.problem('column agrees on less than half of the rows (offset wrong, or reworked by the mod)', label)
        isc = table('itemstatcost.txt')
        if isc:
            rows = [(num(r.get('ID')), r) for r in isc]
            rows = [(i, r) for i, r in rows if i is not None and i in d.isc]
            for col, key in (('Save Bits', 'bits'), ('Save Add', 'add'), ('Save Param Bits', 'param'),
                             ('descfunc', 'func'), ('descpriority', 'prio'), ('descval', 'val')):
                compare(f'itemstatcost {col}', [(num(r.get(col)), d.isc[i].get(key) or 0) for i, r in rows])
        sk = table('skills.txt')
        if sk:
            classes = {'': 255, 'ama': 0, 'sor': 1, 'nec': 2, 'pal': 3, 'bar': 4, 'dru': 5, 'ass': 6}
            rows = [(num(r.get('Id')), r) for r in sk]
            rows = [(i, r) for i, r in rows if i is not None and i in d.skill_class]
            compare('skills charclass', [(classes.get(r.get('charclass', ''), 255), d.skill_class[i]) for i, r in rows])
            compare('skills reqlevel', [(num(r.get('reqlevel')), d.skill_req[i]) for i, r in rows])
            compare('skills has skilldesc', [(bool(r.get('skilldesc')), i in d.skill_names) for i, r in rows])
        un = table('uniqueitems.txt')
        if un:
            names = {u['name'] for u in d.uniques}
            compare('uniqueitems name key still in the table', [(r['name'] in names, True) for r in un])
            byname = {u['name']: u for u in d.uniques}
            both = [r for r in un if r['name'] in byname]
            compare('uniqueitems base code (rows of the same name)',
                    [((r.get('code') or '').ljust(4), byname[r['name']]['code']) for r in both])

    def run(self):
        steps = (self.uniques, self.sets, self.runewords, self.bases, self.honorific, self.skills_table,
                 self.game_dir, self.saves, self.txt)
        for step in steps:
            try:
                step()
            except Exception:
                if self.rep.cur is None:
                    self.rep.section(step.__name__)
                self.rep.problem('audit step crashed', traceback.format_exc(limit=-3).strip().replace('\n', ' | ')[-400:])
        return self.rep.text()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--app', default=os.environ.get('MXL_APP_DIR'), help='folder of the app modules (host .pyc + mxl_*.py)')
    ap.add_argument('--user-dir', default=os.environ.get('MXL_USER_DIR'), help='COPY of the editor\'s user folder')
    ap.add_argument('--game-dir', default=os.environ.get('MXL_GAME_DIR'), help='Median XL folder (read only)')
    ap.add_argument('--save-dir', default=os.environ.get('MXL_SAVE_DIR'), help='COPY of a save folder (read only)')
    ap.add_argument('--txt-dir', default=os.environ.get('MXL_TXT_DIR'), help='folder with vanilla *.txt tables')
    ap.add_argument('--noop-edit', action='store_true',
                    help='with --save-dir: Edit item -> Replace with nothing changed, for every item of the save files; '
                         'counts the items whose bytes are not identical afterwards')
    ap.add_argument('--out', help='report file (default: stdout)')
    args = ap.parse_args()
    if not args.app or not args.user_dir:
        ap.error('--app and --user-dir (or MXL_APP_DIR / MXL_USER_DIR) are required')
    os.environ['MXL_USER_DIR'] = args.user_dir
    if args.save_dir:
        os.environ['MXL_SAVE_DIR'] = args.save_dir
    sys.dont_write_bytecode = True
    sys.path.insert(0, args.app)
    text = Audit(args).run()
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(text)
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
