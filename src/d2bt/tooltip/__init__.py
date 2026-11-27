"""In-game tooltip previews (no Tk; d2bt.gui.tooltip_view draws them).

API (for the Excel Editor's Simple mode and the wizards):

    from d2bt import tooltip
    lines = tooltip.item_tooltip(tables, strings, row, level=99)            # uniqueitems / setitems / runes row
    lines = tooltip.skill_tooltip(tables, strings, row_or_index, level=0, sample_stats=None)
    lines = tooltip.tooltip_for('uniqueitems', row, tables)                  # by table name; None if no preview

tables: an explain.Ctx (live grid rows + the txt beside the file), a txt folder path, or a GameData (reuse it
between calls: it caches the tables; call .invalidate() after edits to other tables). strings: a
tbl.StringSet or None (the .tbl files beside the txt). row: {column: value} - the live, edited values.

A result is a list of (segments, kind): segments [(text, colour code)] with the game's colour-code characters
('0' white, '1' red, '2' green set, '3' blue magic, '4' gold unique, '5' grey ... see theme.GAME_COLORS), top to
bottom; kind 'blank' is an empty line, 'raw' a grey line the builder did not understand (never guessed).
The list also has .raw (count), .reasons and .name."""
from .data import GameData  # noqa: F401
from .item import item_tooltip  # noqa: F401
from .skill import skill_tooltip, start_stats  # noqa: F401

ITEM_TABLES = {'uniqueitems': 'unique', 'setitems': 'set', 'runes': 'runeword'}
TABLES = set(ITEM_TABLES) | {'skills', 'skilldesc'}


def tooltip_for(table, row, tables, strings=None, level=None, row_index=None, sample_stats=None):
    """The preview of one row of `table`, or None when the table has none. level: character level for items
    (default 99), skill level for skills (default 0 = no points, the "First Level" block)."""
    table = (table or '').lower()
    if table in ITEM_TABLES:
        return item_tooltip(tables, strings, row, level=99 if level is None else level, kind=ITEM_TABLES[table])
    if table == 'skills':
        return skill_tooltip(tables, strings, row, level=level or 0, sample_stats=sample_stats, sid=row_index)
    if table == 'skilldesc':
        from . import skill as S
        gd = tables if isinstance(tables, GameData) else GameData(tables, strings)
        di = row_index if row_index is not None else gd.table('skilldesc').find(row.get('skilldesc', ''))
        if di is None or di < 0:
            return None
        t = S.SkillTables(gd, {('skilldesc', di): {k.lower(): v for k, v in row.items()}})
        sid = next((r for r in range(len(t.sk)) if t.desc_index(r) == di), None)
        if sid is None:
            return None
        if sample_stats is None:
            sample_stats = S.start_stats(gd, t.charclass(sid))
        lv = {sid: level} if level else {}
        return S.tip_lines(S.Composer(t, S.Calc(t, lv, max(level or 0, 1), sample_stats)).tooltip(sid))
    return None

