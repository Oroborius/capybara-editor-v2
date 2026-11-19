"""Damage lines of the collector's item tooltip when an item's minimum damage is above its maximum.

Several Sigma mods add to the minimum only: "+N to Minimum Damage" (property dmg-min: stats 21 / 23 / 159), the
"+min damage" craft prefixes, a runeword's "dmg-mag" / "dmg-fire" giving only the minimum (Aether, Black Cat,
Atlacamani). The item's stats are what the game makes (the creator writes them as the tables say); only the
collector's text was wrong:

- weapon line (host `mxl_tooltip.section_damage`): "One-Hand Damage: 145 to 132". The game raises the maximum to
  minimum + 1 when the minimum is above it (base-game rule; the stat screen does the same, see
  `mxl_statscreen.weapon_damage`). Shown here as "145 to 146". Lines with min <= max are left exactly as the host
  writes them.
- "Adds X-Y" lines (host `mxl_stat_text._grouped_lines`): grouped on the presence of both stats, so a minimum
  without its maximum read "Adds 120-0 Magic Damage" (the save format writes the companion stat of 48 / 50 / 52 /
  54 as 0) and a minimum above the maximum "Adds 70-45 Damage". Such a pair is shown as the two stats' own lines
  ("+120 to Minimum Magic Damage"; "+70 to Minimum Damage" and "+45 to Maximum Damage"), the companion with
  value 0 not at all: only the game's own strings and the true values. Pairs with 0 < min <= max are untouched.
- ethereal weapons: Median XL gives them +25 % base damage (`mxl_statscreen.ETH_PCT`), applied to the base before
  enhanced damage (in game: ethereal Dirk 18-20, +220 % ED, +12 max -> "One-Hand Damage: 70 to 92"). The host's
  section_damage has no ethereal rule ("57 to 76"); it is run on the base scaled to 125 % (all three lines).

install() is called by mxl_format_fix.install(); it is idempotent.
"""

_ORIG = {}


def _own_line(st, sid, value, data):
    """The host's own tooltip text of one stat alone (e.g. '+70 to Minimum Damage')."""
    try:
        for ln in st.stat_lines([{'id': sid, 'value': value, 'param': 0}], data, None):
            txt = ln[1]
            if isinstance(txt, (list, tuple)):
                txt = ''.join(x[1] if isinstance(x, tuple) else str(x) for x in txt)
            txt = str(txt).strip()
            if txt:
                return txt
    except Exception:
        pass
    return None


def bad_pairs(ids, pairs):
    """Range pairs (min stat, max stat) of `ids` the host would show wrongly: both present and the minimum
    above the maximum, or one of them 0."""
    out = set()
    for a, b in pairs:
        if a in ids and b in ids:
            lo, hi = ids[a], ids[b]
            if lo > hi or (lo == 0) != (hi == 0):
                out.add((a, b))
    return out


def _make_grouped(st, orig):
    def _grouped_lines(ids, data, add, *rest, **kw):
        try:
            bad = bad_pairs(ids, list(getattr(st, 'RANGE_TEXT', {}) or {}))
        except Exception:
            bad = set()
        if not bad:
            return orig(ids, data, add, *rest, **kw)

        def add2(sid, text, sids=None, *a, **k):
            pair = tuple(sids) if sids else None
            if pair in bad:
                for s in pair:
                    v = ids.get(s, 0)
                    t = _own_line(st, s, v, data) if v else None
                    if t:
                        add(s, t, [s], *a, **k)
                return None
            return add(sid, text, sids, *a, **k)
        return orig(ids, data, add2, *rest, **kw)
    _grouped_lines._capy_dmg = True
    return _grouped_lines


def weapon_lines(ctx, S):
    """[(label key, min, max)] of the weapon damage lines the host's section_damage computes (same formula)."""
    out = []
    base = ctx.base()
    bd = getattr(base, 'damage', None)
    if not bd:
        return out
    ids = ctx.ids
    ed = ids.get(S.ENH_DAMAGE_MAX, 0)
    for key, (a, b), fmin, fmax in (('ItemStats1n', bd['throw'], S.THROW_MIN_DAMAGE, S.THROW_MAX_DAMAGE),
                                    ('ItemStats1l', bd['one_hand'], S.MIN_DAMAGE, S.MAX_DAMAGE),
                                    ('ItemStats1m', bd['two_hand'], S.MIN_DAMAGE_2, S.MAX_DAMAGE_2)):
        if not b:
            continue
        out.append((key, a * (100 + ed) // 100 + ids.get(fmin, 0), b * (100 + ed) // 100 + ids.get(fmax, 0)))
    return out


ETH_PCT = 125                       # = mxl_statscreen.ETH_PCT


class _EthBase:
    """An item base whose weapon damage is the ethereal one (x 125 // 100); every other attribute the base's."""

    def __init__(self, base):
        self._b = base
        self.damage = {k: (tuple(x * ETH_PCT // 100 for x in v) if isinstance(v, (tuple, list)) else v)
                       for k, v in base.damage.items()}

    def __getattr__(self, name):
        return getattr(self._b, name)


def _eth_base(ctx):
    """The ethereal-scaled base of ctx's item, or None (not ethereal / no weapon damage)."""
    try:
        if not ctx.it.get('ethereal'):
            return None
        base = ctx.base()
        if not getattr(base, 'damage', None):
            return None
        return _EthBase(base)
    except Exception:
        return None


def _replace_text(lines, old, new):
    n = 0
    for ln in lines:
        if not isinstance(ln, list):
            continue
        for i, seg in enumerate(ln):
            if isinstance(seg, tuple) and len(seg) == 2 and seg[1] == old:
                ln[i] = (seg[0], new)
                n += 1
    return n


def _make_section(orig, S):
    def section_damage(ctx, *rest, **kw):
        eb = _eth_base(ctx)
        if eb is not None:
            ctx.base = lambda: eb           # instance attribute over the method, for this call only
        try:
            out = orig(ctx, *rest, **kw)
            try:
                for key, lo, hi in weapon_lines(ctx, S):
                    if lo > hi:
                        label = ctx.data.key(key)
                        _replace_text(out, f'{label} {lo} to {hi}', f'{label} {lo} to {lo + 1}')
            except Exception:
                pass
        finally:
            if eb is not None:
                try:
                    del ctx.base
                except AttributeError:
                    pass
        return out
    section_damage._capy_dmg = True
    section_damage.__name__ = 'section_damage'
    return section_damage


class host_text:
    """Context manager: the host's own (unpatched) damage texts inside the block (tests compare against them)."""

    def __enter__(self):
        import mxl_stat_text as st
        import mxl_tooltip as MT
        self.saved = (st._grouped_lines, MT.section_damage, MT.ITEM_SECTIONS, MT.item_tooltip.__defaults__)
        if not _ORIG:
            return self
        new, old = MT.section_damage, _ORIG['section']

        def swap(seq):
            return type(seq)(old if f is new else f for f in seq)
        st._grouped_lines = _ORIG['grouped']
        MT.section_damage = old
        MT.ITEM_SECTIONS = swap(MT.ITEM_SECTIONS)
        MT.item_tooltip.__defaults__ = tuple(swap(x) if isinstance(x, (tuple, list)) else x
                                             for x in MT.item_tooltip.__defaults__ or ())
        return self

    def __exit__(self, *exc):
        import mxl_stat_text as st
        import mxl_tooltip as MT
        st._grouped_lines, MT.section_damage, MT.ITEM_SECTIONS, MT.item_tooltip.__defaults__ = self.saved
        return False


def install():
    try:
        import mxl_stat_text as st
        import mxl_tooltip as MT
    except Exception:
        return False
    if getattr(st._grouped_lines, '_capy_dmg', False):
        return True
    _ORIG['grouped'] = st._grouped_lines
    st._grouped_lines = _make_grouped(st, st._grouped_lines)
    old = MT.section_damage
    _ORIG['section'] = old
    new = _make_section(old, MT.S)

    def swap(seq):
        return type(seq)(new if f is old else f for f in seq)
    MT.section_damage = new
    if isinstance(getattr(MT, 'ITEM_SECTIONS', None), (tuple, list)):
        MT.ITEM_SECTIONS = swap(MT.ITEM_SECTIONS)
    d = MT.item_tooltip.__defaults__
    if d:
        MT.item_tooltip.__defaults__ = tuple(swap(x) if isinstance(x, (tuple, list)) else x for x in d)
    return True
