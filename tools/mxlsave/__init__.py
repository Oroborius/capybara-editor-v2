"""mxlsave - standalone reference implementation of the Median XL Sigma (2.14.x) save files.

Pure standard library. Does not import the editor (src/mxl_*.py) nor the host application: it is an independent
second implementation, meant for reading the format as code and for cross-checking the editor.

    from mxlsave import load, Tables
    tables = Tables.find()                 # extracted game tables (<user dir>/data/*.bin); None when not found
    save = load('XBone.d2s', tables)       # -> D2S / Stash / KeyFile / MapFile / AutomapFile
    assert save.to_bytes() == open('XBone.d2s', 'rb').read()

Modules: bits (bit streams), tables (game table readers), items (item records), d2s (character file),
stash (.stash / .shared), companions (.key / .map / .maN), check (second opinion on a file's bytes),
diff (structural diff of two files), cli (dump / verify / diff).
The format description lives in docs/SAVE_FORMAT.md.
"""
from .bits import BitReader, BitWriter, FormatError
from .tables import Tables
from .items import Item, parse_item, parse_item_list, build_item_list
from .d2s import D2S, checksum
from .stash import Stash
from .companions import KeyFile, MapFile, AutomapFile
from .cli import load
from .check import check_bytes
from .diff import diff_bytes, diff_files, diff_objects, format_text, summary

__all__ = ['BitReader', 'BitWriter', 'FormatError', 'Tables', 'Item', 'parse_item', 'parse_item_list',
           'build_item_list', 'D2S', 'checksum', 'Stash', 'KeyFile', 'MapFile', 'AutomapFile', 'load']
