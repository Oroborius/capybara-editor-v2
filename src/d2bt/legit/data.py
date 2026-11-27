"""Materialize the running game's Excel tables for the save and item readers."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import threading

from ..binfmt import bin2txt
from ..binfmt.tbl import TBL_BASE, Tbl
from ..mpq import MPQStack

TABLES = (
    'armor', 'weapons', 'misc', 'itemtypes', 'itemstatcost', 'skills', 'playerclass',
    'charstats', 'skilldesc', 'experience', 'magicprefix', 'magicsuffix', 'automagic',
    'rareprefix', 'raresuffix', 'uniqueitems', 'setitems', 'sets', 'runes',
    'properties', 'cubemain', 'qualityitems', 'lowqualityitems', 'gems',
)
# String IDs for the enabled recipes in the stock 1.14d MPQs.
_STOCK_RUNEWORD_STRINGS = {
    'Runeword1': 20507,
    'Runeword4': 20510,
    'Runeword6': 20512,
    'Runeword8': 20514,
    'Runeword9': 20515,
    'Runeword10': 20516,
    'Runeword11': 20517,
    'Runeword13': 20519,
    'Runeword14': 20520,
    'Runeword16': 20522,
    'Runeword17': 20523,
    'Runeword20': 20526,
    'Runeword22': 10910,
    'Runeword25': 20531,
    'Runeword26': 20532,
    'Runeword27': 20533,
    'Runeword29': 20535,
    'Runeword30': 20536,
    'Runeword31': 20537,
    'Runeword33': 20539,
    'Runeword34': 20540,
    'Runeword36': 20542,
    'Runeword37': 20543,
    'Runeword38': 20544,
    'Runeword39': 20545,
    'Runeword41': 20547,
    'Runeword44': 20550,
    'Runeword45': 20551,
    'Runeword47': 20553,
    'Runeword48': 20554,
    'Runeword49': 20555,
    'Runeword51': 20557,
    'Runeword54': 20560,
    'Runeword55': 20561,
    'Runeword59': 20565,
    'Runeword60': 20566,
    'Runeword62': 20568,
    'Runeword65': 20571,
    'Runeword66': 20572,
    'Runeword69': 20575,
    'Runeword71': 20577,
    'Runeword72': 20578,
    'Runeword74': 20580,
    'Runeword75': 20581,
    'Runeword81': 20586,
    'Runeword82': 20587,
    'Runeword83': 20588,
    'Runeword87': 20592,
    'Runeword88': 20593,
    'Runeword91': 20596,
    'Runeword92': 20597,
    'Runeword95': 20600,
    'Runeword98': 20603,
    'Runeword99': 20604,
    'Runeword103': 20608,
    'Runeword109': 20614,
    'Runeword110': 20615,
    'Runeword112': 20617,
    'Runeword116': 20621,
    'Runeword117': 20622,
    'Runeword120': 20625,
    'Runeword121': 20626,
    'Runeword122': 20627,
    'Runeword126': 20631,
    'Runeword128': 20633,
    'Runeword130': 20635,
    'Runeword131': 20636,
    'Runeword133': 20638,
    'Runeword134': 20639,
    'Runeword137': 20642,
    'Runeword139': 20644,
    'Runeword148': 20653,
    'Runeword154': 20659,
    'Runeword160': 20665,
    'Runeword162': 20667,
    'Runeword163': 20668,
    'Runeword168': 20673,
    'Runeword170': 20675,
}
_LOCK = threading.Lock()


def runeword_strings(directory):
    strings = {}
    for name in ('string', 'expansionstring', 'patchstring'):
        path = directory / f'{name}.tbl'
        if path.is_file():
            # Reverse traversal preserves the first ID for duplicate keys.
            for index, (key, _) in reversed(list(enumerate(Tbl.load(path).entries))):
                if key:
                    strings[key] = TBL_BASE[name] + index
    return strings or _STOCK_RUNEWORD_STRINGS


def cache_root():
    source = Path(__file__).resolve().parents[2]
    if (source / '.git').exists():
        return source / '.cache'
    from ..project import home
    return Path(home()) / '.cache'


def _children(path):
    return {p.name.lower(): p for p in path.iterdir()} if path.is_dir() else {}


def game_tables(game):
    game = Path(game).resolve()
    files = _children(game)
    archives = [files[n] for n in ('patch_d2.mpq', 'd2exp.mpq', 'd2data.mpq') if n in files]
    loose = game
    for part in ('data', 'global', 'excel'):
        loose = _children(loose).get(part, loose / part)
    local = _children(loose)
    names = {f'{name}.{ext}' for name in TABLES for ext in ('bin', 'txt')}
    if not archives and not (names & local.keys()):
        raise FileNotFoundError(f'no LoD game tables found in {game}')
    sources = archives + [local[n] for n in sorted(names & local.keys())]
    stamp = []
    for path in sources:
        st = path.stat()
        stamp.append((str(path), st.st_size, st.st_mtime_ns))
    digest = hashlib.sha256(repr((TABLES, TBL_BASE, stamp)).encode()).hexdigest()
    root = cache_root() / 'legit-tables'
    dest = root / digest
    with _LOCK:
        if dest.is_dir():
            return dest
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=root))
        try:
            _extract(archives, local, staging)
            try:
                os.rename(staging, dest)
            except OSError:
                if not dest.is_dir():
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return dest


def _extract(archives, local, staging):
    stack = MPQStack(archives)
    try:
        for table in TABLES:
            filenames = [f'{table}.{suffix}' for suffix in ('txt', 'bin')]
            paths = [f'data\\global\\excel\\{name}' for name in filenames]
            # Choose both representations from the same priority tier. The text
            # retains original names and fields the compiler does not serialize.
            for name in filenames:
                if name in local:
                    shutil.copyfile(local[name], staging / name)
            hits = [stack.find(path) for path in paths]
            if any(hits):
                if any(name in local for name in filenames):
                    # Keep the compiled references available to the converter.
                    wanted = [False, filenames[1] not in local]
                else:
                    first = next(a for a in stack.archives if any(hit and hit[0] is a for hit in hits))
                    wanted = [hit is not None and hit[0] is first for hit in hits]
                for name, path, hit, read in zip(filenames, paths, hits, wanted):
                    if read and hit:
                        (staging / name).write_bytes(stack.read(path))
        for name in TBL_BASE:
            filename = f'{name}.tbl'
            path = fr'data\local\lng\eng\{filename}'
            if stack.find(path):
                (staging / filename).write_bytes(stack.read(path))
        context = bin2txt.Context(bin_dir=str(staging), version='114d')
        for table in TABLES:
            dst = staging / f'{table}.txt'
            if not dst.exists():
                src = staging / f'{table}.bin'
                if not src.exists():
                    raise FileNotFoundError(f'game data is missing {table}.txt/.bin')
                bin2txt.convert_file(src, dst, '114d', context)
    finally:
        stack.close()
