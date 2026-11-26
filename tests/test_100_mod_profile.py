"""Use synthetic mod layers over read-only local game fixtures."""
import os
from pathlib import Path
import struct
import sys

import capytest as T

MODE = 'engine'
NEEDS = ()


def _base():
    game = os.environ.get('MXL_TEST_VANILLA_GAME')
    if not game or not (Path(game) / 'd2data.mpq').is_file():
        T.skip('no cached vanilla game')
    return Path(game)


def _single_file_mpq(target, name, payload):
    """Make a one-member, uncompressed MPQ with the host reader's hash function."""
    from mpq import CT, hs

    def encrypt(raw, key):
        mask = 0xffffffff
        seed = 0xeeeeeeee
        result = bytearray()
        for (word,) in struct.iter_unpack('<I', raw):
            seed = (seed + CT[0x400 + (key & 255)]) & mask
            result += struct.pack('<I', word ^ ((key + seed) & mask))
            key = (((~key << 21) + 0x11111111) | (key >> 11)) & mask
            seed = (word + seed + (seed << 5) + 3) & mask
        return result

    hash_offset, block_offset = 32, 48
    payload_offset = 64
    header = struct.pack('<4sIIHHIIII', b'MPQ\x1a', 32, payload_offset + len(payload),
                         0, 3, hash_offset, block_offset, 1, 1)
    hashes = struct.pack('<IIII', hs(name, 1), hs(name, 2), 0, 0)
    blocks = struct.pack('<IIII', payload_offset, len(payload), len(payload), 0x81000000)
    target.write_bytes(header + encrypt(hashes, hs('(hash table)', 3)) +
                       encrypt(blocks, hs('(block table)', 3)) + payload)


def _stat_width(width):
    return (f'Stat\tID\tSave Bits\tSave Add\tSave Param Bits\nstrength\t0\t{width}\t32\t0\n'
            'example_stat\t401\t19\t100\t6\n').encode()


@T.test
def d2se_patch_and_loose_override_follow_game_order():
    import mxl_data
    import mxl_profile as P
    from mxl_profile_tables import EXCEL_PATH

    base = Path(T.tmp()) / 'game'
    base.mkdir()
    for file in P.base_archives(str(_base())):
        (base / Path(file).name).symlink_to(Path(file).resolve())
    mod = base / 'MODS' / 'Example'
    mod.mkdir(parents=True)
    (mod / 'D2SE_SETUP.ini').write_text('[Protected]\nD2Core=1.10f\nModName=Example\n')
    patch = mod / 'Patch_D2.mpq'
    _single_file_mpq(patch, EXCEL_PATH + 'itemstatcost.txt', _stat_width(13))
    info = P.detect(str(mod))
    T.eq(P._detection_label(info), 'Example (1.10f mod, D2SE) - supported', 'profile label')
    T.eq(info['save_version'], 96, '1.10 save version')
    T.eq(Path(P.archive_order(str(mod))[0]), patch, 'mod patch archive first')
    out = str(Path(T.tmp()) / 'extracted')
    P.extract(str(mod), out, icons=False)
    T.eq(mxl_data.Data(out).isc[0]['bits'], 13, 'patch text beats the base binary')
    binary = bytearray((Path(out) / 'itemstatcost.bin').read_bytes())
    binary[4 + 25] = 15
    _single_file_mpq(patch, EXCEL_PATH + 'itemstatcost.bin', binary)
    T.check(not P.data_ok(str(mod), out), 'replacing the patch invalidates the extraction')
    P.extract(str(mod), out, icons=False)
    T.eq(mxl_data.Data(out).isc[0]['bits'], 15, 'compiled 1.10 patch beats base data')
    loose = mod / 'Data' / 'Global' / 'Excel'
    loose.mkdir(parents=True)
    (loose / 'ITEMSTATCOST.TXT').write_bytes(_stat_width(17))
    T.check(not P.data_ok(str(mod), out), 'loose file invalidates cache')
    P.extract(str(mod), out, icons=False)
    data = mxl_data.Data(out)
    T.eq(data.isc[0]['bits'], 17, 'loose text beats the mod patch')
    from mxl_creator import BitWriter, _BR, _read_stats, _write_stats
    stat = {'id': 401, 'param': 37, 'value': 70000}
    writer = BitWriter()
    _write_stats(writer, [stat], data)
    T.eq(writer.pos, 9 + 6 + 19 + 9, 'mod-defined value and parameter widths')
    decoded = _read_stats(_BR(writer.bytes()), data)[0]
    T.eq({k: decoded[k] for k in stat}, stat, 'custom stat round trip')


@T.test
def standalone_mod_uses_remembered_base_and_loads_new_item():
    import mxl_data
    import mxl_profile as P

    base = _base()
    mod = Path(T.tmp()) / 'Standalone'
    excel = mod / 'data' / 'global' / 'excel'
    excel.mkdir(parents=True)
    archives = P._open_stack(str(base))

    def add_row(table, values):
        path = f'data\\global\\excel\\{table}.txt'
        text = P._read(archives, path)
        T.check(text, f'base {table} text available')
        columns = text.splitlines()[0].decode('latin1').lower().split('\t')
        row = '\t'.join(values.get(column, '') for column in columns).encode('latin1')
        (excel / (table + '.txt')).write_bytes(text.rstrip(b'\r\n') + b'\r\n' + row + b'\r\n')

    add_row('misc', {'name': 'Example token', 'code': 'zqt', 'type': 'misc',
                     'invwidth': '1', 'invheight': '1', 'invfile': 'invbox', 'compactsave': '1'})
    add_row('properties', {'code': 'example', 'func1': '1', 'stat1': 'strength'})
    T.check(not P.detect(str(mod), '')['supported'], 'missing base is reported')
    original = P._raw_settings
    try:
        P._raw_settings = lambda: {'profile_base_dir': str(base)}
        info = P.detect(str(mod))
        T.check(info['mod'] and info['supported'], 'remembered base supports the standalone mod')
        out = str(Path(T.tmp()) / 'standalone-data')
        P.extract(str(mod), out, icons=False)
    finally:
        P._raw_settings = original
    data = mxl_data.Data(out)
    T.check('zqt ' in data.item_index, 'new base item loaded')
    T.eq(data.base('zqt ').size, (1, 1), 'new item grid size')
    T.eq(data.props[-1][0], 0, 'text property resolves the strength stat')
    T.eq(data.prop_func[-1], 1, 'text property function')


@T.test
def cached_legacy_installs_resolve_archives_for_mod_profiles():
    import mxl_data
    import mxl_format_fix
    import mxl_newchar
    import mxl_profile as P

    mxl_format_fix.install()
    original = P._state
    fixtures = Path(T.REPO) / '.cache' / 'oldver'
    for name, version in (('107', 87), ('108', 89), ('109d', 92)):
        base = fixtures / name
        if not (base / 'd2data.mpq').is_file():
            T.skip('no cached legacy game')
        legacy = next((base / 'MODS').iterdir())
        legacy_info = P.detect(str(legacy))
        T.eq(legacy_info['save_version'], version, 'legacy D2SE core version')
        out = str(Path(T.tmp()) / f'legacy-data-{name}')
        P.extract(str(legacy), out, icons=False)
        try:
            P._state = legacy_info
            P._patch_format()
            data = mxl_data.Data(out)
            _, character = mxl_newchar.build(data, 'Fixture', 0, 1)
        finally:
            P._state = original
        T.eq(character.version, version, 'the new character uses the native old-save path')
        mod = Path(T.tmp()) / name
        mod.mkdir()
        (mod / 'D2SE_SETUP.ini').write_text('D2Core=1.10f\n')
        info = P.detect(str(mod), str(base))
        T.check(info['supported'], '1.10 mod with shared archives from the older D2SE install')
        T.eq(info['save_version'], 96, 'the mod core determines the save version')


@T.test
def broken_core_paths_and_manifests_are_ignored():
    import mxl_profile as P

    base = Path(T.tmp()) / 'CorePaths'
    cores = base / 'D2SE' / 'CORES'
    cores.parent.mkdir(parents=True)
    (base / 'd2data.mpq').touch()
    cores.touch()
    T.check(not P.detect(str(base))['supported'], 'a file named CORES is not a core directory')
    cores.unlink()
    cores.mkdir()
    (cores / '1.09d').touch()
    T.check(not P.detect(str(base))['supported'], 'a file named like a version is not a core')
    (cores / '1.10f').mkdir()
    T.eq(P.detect(str(base))['version'], '1.10f', 'the only core directory determines the version')

    output = base / 'profile'
    output.mkdir()
    (output / 'install.json').write_text('[]')
    T.check(not P.data_ok(str(base), str(output)), 'a non-object manifest triggers extraction')


@T.test
def optional_mercenary_tables_do_not_break_the_character_editor():
    from mxl_data import Data
    from mxl_merc import hirelings

    folder = Path(T.tmp()) / 'OptionalMercenary'
    folder.mkdir()
    for raw in (None, b'', b'\0' * 4, struct.pack('<I', 1) + b'\0' * 12):
        path = folder / 'hireling.bin'
        if raw is not None:
            path.write_bytes(raw)
        data = Data.__new__(Data)
        data.folder = str(folder)
        T.eq(hirelings(data), {}, 'unavailable definitions leave the mercenary types empty')


sys.path.insert(0, T.APP)
T.main(globals())
