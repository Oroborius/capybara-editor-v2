"""Second opinion on the bytes of a character / stash file: does this implementation accept them?

    obj, problems = check_bytes(data, 'd2s' | 'stash', tables)

`problems` is empty when: the structure parses, the size and checksum stored in a .d2s are the real ones, the
parsed fields rebuild the same bytes, and the item counts are plausible (nothing left over after the last
section, no list longer than its container can hold). Without tables the items cannot be decoded: only the fixed
sections of a .d2s and the page markers of a stash are checked.
"""
import struct

from .bits import FormatError
from .d2s import D2S, checksum
from .stash import Stash

MAX_STASH_PAGE_ITEMS = 256      # x and y are 4 bits: a page cannot hold more top-level items than cells
MAX_LIST_ITEMS = 1024           # a character's list: inventory + cube + stash panel + belt + equipment
PARSE_ERRORS = (FormatError, ValueError, KeyError, IndexError, OverflowError, struct.error, TypeError,
                AttributeError)


def count_items(obj):
    """Top-level items of a parsed file (socketed items not counted); None when they were not decoded."""
    if isinstance(obj, Stash):
        if any(p.items is None for p in obj.pages):
            return None
        return sum(len(p.items) for p in obj.pages)
    if obj.items is None:
        return None
    return len(obj.items) + len(obj.merc_items or ()) + sum(len(c.items) for c in obj.corpses)


def check_bytes(data, kind, tables=None):
    """(parsed object or None, [problem, ...]) for the bytes of a 'd2s' or 'stash' file."""
    data = bytes(data)
    problems = []
    try:
        obj = D2S.parse(data, tables) if kind == 'd2s' else Stash.parse(data, tables)
    except PARSE_ERRORS as e:
        return None, [f'structure: {e}' if isinstance(e, FormatError) else f'structure: {type(e).__name__}: {e}']
    if kind == 'd2s':
        h = obj.header
        if h.file_size != len(data):
            problems.append(f'size field {h.file_size}, the file has {len(data)} bytes')
        real = checksum(data)
        if h.checksum != real:
            problems.append(f'checksum {h.checksum:08x}, computed {real:08x}')
        if obj.trailing:
            problems.append(f'{len(obj.trailing)} bytes left after the last section (a wrong item count?)')
        if obj.items is not None:
            for title, lst in (('items', obj.items), ('mercenary items', obj.merc_items or ())):
                if len(lst) > MAX_LIST_ITEMS:
                    problems.append(f'{title}: {len(lst)} is not a plausible count')
    else:
        for p in obj.pages:
            if p.count > MAX_STASH_PAGE_ITEMS:
                problems.append(f'page {p.number}: {p.count} items is not a plausible count')
        numbers = [p.number for p in obj.pages]
        if len(set(numbers)) != len(numbers):
            problems.append('a page number occurs twice')
    try:
        out = obj.to_bytes(tables)
    except PARSE_ERRORS as e:
        problems.append(f'rebuild: {type(e).__name__}: {e}')
        return obj, problems
    if out != data and not problems:        # a wrong size / checksum already explains a different rebuild
        n = next((i for i, (a, b) in enumerate(zip(out, data)) if a != b), min(len(out), len(data)))
        problems.append(f'rebuilt file differs at byte {n} (sizes {len(out)} / {len(data)})')
    return obj, problems
