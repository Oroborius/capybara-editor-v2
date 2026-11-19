"""Item inspector: right-click an item -> "Inspect..." shows, read only, exactly what the item stores.

Every header field (flags by name, version, location / position, code, item level, quality and the fields of
that quality, sockets, runeword id + name, personalization, set / unique id + name), each stat in save order
(id, name, param decoded where it has a name, stored raw value, value, the tooltip's line), the socketed items
nested, and the bit layout: every field with its bit offset, width, value and bits, plus a hex dump.

The fields are read by mxlsave (tools/mxlsave, the independent save reader that also checks every write): a
BitReader that logs each read (offset, width, value) runs mxlsave's own item parser, and the log is labelled by
walking it in the parser's order with the decoded item choosing the branches. Nothing here writes anything.
"""
import tkinter as tk

from mxl_lang import T

STAT_END = 0x1FF


def tr(key, default, **fields):
    return T('insp.' + key, default, **fields)


def _lib():
    import mxl_savecheck
    return mxl_savecheck.lib(), mxl_savecheck.tables()


class _Log:
    """Wraps a BitReader: every read is noted as (bit position, width, value)."""

    def __init__(self, br):
        self.br = br
        self.reads = []

    def read(self, n):
        pos = self.br.pos
        v = self.br.read(n)
        self.reads.append((pos, n, v))
        return v

    def read_padding(self):
        n = -self.br.pos % 8                    # noted also when 0 bits: one entry per field of the layout
        return self.read(n) if n else (self.reads.append((self.br.pos, 0, 0)) or 0)

    def bytes_used(self):
        return self.br.bytes_used()

    @property
    def pos(self):
        return self.br.pos


def parse_traced(blob, pos=0, tables=None):
    """(Item, [(bit offset from 'JM'+2, width, value)]) of the item at byte `pos` of blob, read by mxlsave."""
    ms, tb = _lib()
    tables = tables or tb
    from mxlsave import items as MI
    from mxlsave.bits import BitReader, FormatError
    if blob[pos:pos + 2] != b'JM':
        raise FormatError(f"'JM' expected at byte {pos}")
    log = _Log(BitReader(blob, pos + 2))
    it = MI.Item(offset=pos)
    MI._parse_body(it, log, tables)
    it.size = 2 + log.bytes_used()
    return it, log.reads


def _labels(it, tables):
    """The field names of the reads of `it`, in mxlsave's read order (one label per read)."""
    from mxlsave import items as MI
    from mxlsave.tables import STAT_GROUPS
    out = ['flags', 'version', 'location', 'equipped', 'x', 'y', 'panel', 'code[0]', 'code[1]', 'code[2]', 'code[3]']
    if it.simple:
        return out + ['socketed count', 'padding']
    out += ['socketed count', 'item id', 'item level', 'quality', 'has picture']
    if it.image is not None:
        out.append('picture')
    out.append('has auto affix')
    if it.auto_affix is not None:
        out.append('auto affix')
    q = MI.QUALITY.get(it.quality)
    if q in ('low', 'superior'):
        out.append('subquality')
    elif q == 'magic':
        out += ['prefix', 'suffix']
    elif q in ('set', 'unique'):
        out.append(q + ' id')
    elif q in ('rare', 'crafted', 'honorific'):
        out += ['rare name 1', 'rare name 2']
        if q != 'honorific':
            for k, a in enumerate(it.rare_affixes):
                out.append(f'affix {k + 1} present')
                if a is not None:
                    out.append(f'affix {k + 1}')
    if it.flag(MI.FLAG_RUNEWORD):
        out.append('runeword id')
    if it.flag(MI.FLAG_PERSONALIZED):
        out += [f'name[{k}]' for k in range(len(it.personalized_name))] + ['name end']
    if it.code in MI.TOME_CODES:
        out.append('tome bits')
    out.append('realm bit')
    if it.defense_raw is not None:
        out.append('defense')
    if it.max_durability is not None:
        out.append('max durability')
    if it.durability is not None:
        out.append('durability')
    if it.quantity is not None:
        out.append('quantity')
    if it.sockets is not None:
        out.append('sockets')
    if q == 'set':
        out.append('set lists')

    def stats(lst, title):
        i = 0
        while i < len(lst):
            sid = lst[i].id
            out.append(f'{title} stat id')
            for x in (sid,) + STAT_GROUPS.get(sid, ()):
                if tables.stats[x].save_param:
                    out.append(f'{title} {x} param')
                out.append(f'{title} {x} value')
                i += 1
        out.append(f'{title} end (0x1FF)')
    stats(it.stats, 'stats')
    if q == 'set':
        for bit in range(5):
            if it.set_mask >> bit & 1:
                stats(it.set_stats[bit], f'set list {bit}')
    if it.flag(MI.FLAG_RUNEWORD):
        stats(it.runeword_stats, 'runeword')
    return out + ['padding']


def layout(blob, pos=0):
    """[(bit offset in the blob, width, label, value)] of the item at byte pos (its socketed items excluded); the
    offsets count from the first byte of the blob, 'JM' included. ValueError when the labels and reads differ."""
    _ms, tb = _lib()
    it, reads = parse_traced(blob, pos, tb)
    labels = _labels(it, tb)
    if len(labels) != len(reads):
        raise ValueError(f'inspector: {len(labels)} labels for {len(reads)} reads')
    base = (pos + 2) * 8
    head = [(pos * 8, 16, 'JM', 0x4D4A)]
    return it, head + [(base + p, n, lab, v) for (p, n, v), lab in zip(reads, labels)]


# ------------------------------------------------------------------ names
def _name_of_row(data, rows, i):
    try:
        return data.key(rows[i]['name']).replace('\n', ' ')
    except Exception:
        return ''


def _stat_name(data, tb, sid):
    n = ''
    try:
        n = tb.stat_name(sid) or ''
    except Exception:
        pass
    if not n:
        try:
            import mxl_statnames
            n = mxl_statnames.generic_label(sid) or ''
        except Exception:
            n = ''
    return n.replace('\n', ' ').strip() or f'stat {sid}'


def _param_text(data, sid, param):
    if param is None:
        return ''
    try:
        import mxl_statnames
        if mxl_statnames.param_spec(sid):
            n = mxl_statnames.param_name(data, sid, param)
            if n and n != f'#{param}':
                return f'{param} ({n})'
    except Exception:
        pass
    return str(param)


def _shown(data, sid, param, value):
    try:
        import mxl_statnames
        return mxl_statnames.rendered_line(data, sid, param, value) or ''
    except Exception:
        return ''


# ------------------------------------------------------------------ the text dump
def dump(blob, data, title=None):
    """The inspector's text for an item blob (the item + its socketed items, as stash / .d2i bytes)."""
    from mxlsave import items as MI
    _ms, tb = _lib()
    blob = bytes(blob)
    lines = []
    if title:
        lines.append(title)
    pos, k = 0, 0
    while pos < len(blob):
        it, fields = layout(blob, pos)
        if k == 0:
            _item_text(lines, it, fields, blob, pos, data, tb, '')
            n = it.socketed_count if it.flag(MI.FLAG_SOCKETED) else 0
            if n:
                lines.append('')
                lines.append(tr('socketed', 'Socketed items ({n})', n=n))
        else:
            lines.append('')
            lines.append(f'  --- {tr("child", "socketed item")} {k} ---')
            _item_text(lines, it, fields, blob, pos, data, tb, '    ')
        pos += it.size
        k += 1
    return '\n'.join(lines) + '\n'


def _item_text(lines, it, fields, blob, pos, data, tb, ind):
    from mxlsave import items as MI
    end = pos + it.size
    out = lines.append
    try:
        base = tb.base_name(it.code) or ''
    except Exception:
        base = ''
    out(f'{ind}{base} [{it.code.strip()}]  {it.size} {tr("bytes", "bytes")} (byte {pos}..{end - 1})')
    out(f'{ind}' + tr('h.header', 'Header'))
    out(f'{ind}  flags        0x{it.flags:08X}  {", ".join(it.flag_names())}')
    out(f'{ind}  version      {it.version}')
    out(f'{ind}  location     {it.location} ({MI.LOCATION.get(it.location, "?")}), equipped slot {it.equipped}, '
        f'panel {it.panel} ({MI.PANEL.get(it.panel, "?")}), x {it.x}, y {it.y}')
    out(f'{ind}  code         {it.code!r}')
    out(f'{ind}  socketed     {it.socketed_count}')
    if not it.simple:
        out(f'{ind}  item id      0x{it.id:08X}')
        out(f'{ind}  item level   {it.ilvl}')
        out(f'{ind}  quality      {it.quality} ({it.quality_name})')
        if it.image is not None:
            out(f'{ind}  picture      {it.image}')
        if it.auto_affix is not None:
            out(f'{ind}  auto affix   {it.auto_affix}')
        if it.subquality is not None:
            out(f'{ind}  subquality   {it.subquality}')
        if it.prefix is not None:
            out(f'{ind}  prefix       {it.prefix}   suffix {it.suffix}')
        if it.set_unique_id is not None:
            rows = data.uniques if it.quality_name == 'unique' else data.set_items
            out(f'{ind}  {it.quality_name} id    {it.set_unique_id}  {_name_of_row(data, rows, it.set_unique_id)}')
        if it.rare_names is not None:
            out(f'{ind}  rare names   {it.rare_names[0]}, {it.rare_names[1]}')
        if it.rare_affixes is not None:
            out(f'{ind}  affixes      {", ".join("-" if a is None else str(a) for a in it.rare_affixes)}')
        out(f'{ind}  ethereal     {"yes" if it.flag(MI.FLAG_ETHEREAL) else "no"}')
        if it.runeword_id is not None:
            try:
                rw = tb.string(it.runeword_id) or ''
            except Exception:
                rw = ''
            out(f'{ind}  runeword id  {it.runeword_id} (0x{it.runeword_id:04X})  {rw}')
        if it.personalized_name is not None:
            out(f'{ind}  personalized {it.personalized_name!r}')
        if it.tome_bits is not None:
            out(f'{ind}  tome bits    {it.tome_bits}')
        out(f'{ind}  realm bit    {it.realm_bit}')
        if it.defense_raw is not None:
            add = tb.stats[31].save_add
            out(f'{ind}  defense      raw {it.defense_raw} -> {it.defense_raw - add}')
        if it.max_durability is not None:
            out(f'{ind}  durability   (stored) {it.durability if it.durability is not None else "-"} / {it.max_durability}')
        if it.quantity is not None:
            out(f'{ind}  quantity     {it.quantity}')
        if it.sockets is not None:
            out(f'{ind}  sockets      {it.sockets}')
        if it.set_mask is not None:
            out(f'{ind}  set lists    0b{it.set_mask:05b}')
        lists = [(tr('h.stats', 'Stats (save order)'), it.stats)]
        for bit, lst in sorted(it.set_stats.items()):
            lists.append((tr('h.set', 'Set bonus list {n}', n=bit), lst))
        if it.runeword_stats is not None:
            lists.append((tr('h.rw', 'Runeword stats'), it.runeword_stats))
        for head, lst in lists:
            out(f'{ind}{head}: {len(lst)}')
            out(f'{ind}  {"id":>4}  {"name":<34} {"param":<22} {"raw":>8} {"value":>8}  shown')
            for s in lst:
                out(f'{ind}  {s.id:>4}  {_stat_name(data, tb, s.id)[:34]:<34} '
                    f'{_param_text(data, s.id, s.param)[:22]:<22} {s.raw:>8} {s.value:>8}  '
                    f'{_shown(data, s.id, s.param, s.value)}')
    out(f'{ind}  padding      {it.padding}')
    out(f'{ind}' + tr('h.bits', 'Bit layout (offset = byte.bit from the start of the item; stored LSB first, shown high bit first)'))
    for off, n, lab, v in fields:
        o = off - pos * 8
        bits = ''.join('1' if (v >> b) & 1 else '0' for b in range(n - 1, -1, -1)) if n <= 32 else ''
        out(f'{ind}  {o // 8:>4}.{o % 8}  {n:>2}  {lab:<26} {v:>10}  {bits}')
    out(f'{ind}' + tr('h.hex', 'Bytes (hex)'))
    raw = blob[pos:end]
    for i in range(0, len(raw), 16):
        out(f'{ind}  {i:04X}  ' + ' '.join(f'{b:02X}' for b in raw[i:i + 16]))


# ------------------------------------------------------------------ the window
class InspectWindow:
    def __init__(self, master, blob, data, name):
        self.text_value = dump(blob, data, name)
        top = self.top = tk.Toplevel(master)
        top.title(tr('title', 'Inspect: {name}', name=name))
        try:
            import mxl_d2_theme as D
            dark = D.dark()
        except Exception:
            dark = False
        bg, fg = ('#141112', '#c7b377') if dark else ('white', 'black')
        bar = tk.Frame(top)
        bar.pack(side='bottom', fill='x', padx=2, pady=2)
        tk.Button(bar, text=tr('copy', 'Copy to clipboard'), command=self.copy).pack(side='left', padx=2)
        tk.Button(bar, text=tr('close', 'Close'), command=top.destroy).pack(side='right', padx=2)
        self.status = tk.Label(bar, text='')
        self.status.pack(side='left', padx=4)
        body = tk.Frame(top)
        body.pack(fill='both', expand=True)
        sy = tk.Scrollbar(body, orient='vertical')
        sx = tk.Scrollbar(body, orient='horizontal')
        self.text = tk.Text(body, wrap='none', font='TkFixedFont', bg=bg, fg=fg, insertbackground=fg,
                            width=110, height=36, yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.configure(command=self.text.yview)
        sx.configure(command=self.text.xview)
        sy.pack(side='right', fill='y')
        sx.pack(side='bottom', fill='x')
        self.text.pack(fill='both', expand=True)
        self.text.insert('1.0', self.text_value)
        self.text.configure(state='disabled')
        try:
            w, h = top.winfo_screenwidth(), top.winfo_screenheight()
            top.geometry(f'{min(900, w - 40)}x{min(640, h - 80)}')
        except tk.TclError:
            pass

    def copy(self):
        self.top.clipboard_clear()
        self.top.clipboard_append(self.text_value)
        self.status.configure(text=tr('copied', 'copied'))


def open_blob(master, blob, data, name):
    try:
        return InspectWindow(master, blob, data, name)
    except Exception as e:                       # read only: an item mxlsave cannot read is reported, not fatal
        from tkinter import messagebox
        messagebox.showerror(tr('title0', 'Inspect'), str(e), parent=master)
        return None
