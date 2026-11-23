"""Read the original artwork from a local Hero Editor 1.04 executable."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
import struct

from PIL import Image

EXE_NAME = 'Hero Editor.exe'

# VB6 StdPicture payload sizes in Hero Editor 1.04. Button pictures all
# have the same size and are stored as five defaults followed by pairs.
PICTURES = {
    829682: ('splash', (638, 433)),
    152655: ('about', (638, 433)),
    120469: ('person', (320, 432)),
    131807: ('stash', (320, 432)),
    140329: ('cube', (320, 432)),
    147321: ('merc', (320, 432)),
    37280: ('pickup', (87, 141)),
    63228: ('portrait_0', (205, 405)),
    38447: ('portrait_1', (205, 405)),
    41363: ('portrait_2', (205, 405)),
    39293: ('portrait_3', (205, 405)),
    39637: ('portrait_4', (205, 405)),
    41700: ('portrait_5', (205, 405)),
    37589: ('portrait_6', (205, 405)),
}
BUTTONS = [(name, 0) for name in ('EXTRAS', 'CLOSE', 'RELOAD', 'SAVE', 'OPEN')]
BUTTONS += [(name, shade) for name in ('OPEN', 'SAVE', 'RELOAD', 'CLOSE', 'EXTRAS') for shade in (12, -5)]


def extract(data):
    """Decode length-prefixed pictures directly from the executable bytes."""
    if not data.startswith(b'MZ'):
        return {}
    pictures = {}
    button = 0
    for record in re.finditer(rb'lt\x00\x00', data):
        offset = record.end()
        if offset + 4 > len(data):
            continue
        size, = struct.unpack_from('<I', data, offset)
        start = offset + 4
        if start + size > len(data):
            continue
        if size == 9144 and button < len(BUTTONS):
            name, shade = BUTTONS[button]
            key, dimensions = f'button_{name}_{shade}', (94, 32)
        elif size in PICTURES:
            key, dimensions = PICTURES[size]
        else:
            continue
        if key in pictures:
            continue
        try:
            with Image.open(BytesIO(data[start:start + size]), formats=('BMP', 'GIF', 'JPEG')) as image:
                if image.size != dimensions:
                    continue
                pictures[key] = image.convert('RGB')
        except (OSError, ValueError):
            continue
        if size == 9144:
            button += 1
    return pictures


@lru_cache(maxsize=2)
def _load(executable, mtime, size):
    return extract(executable.read_bytes())


def load(folder):
    if not folder:
        return {}
    try:
        executable = Path(folder) / EXE_NAME
        stat = executable.stat()
        return _load(executable, stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError):
        return {}


def panel_source(artwork, top):
    """Expose an in-memory image file to the existing container compositor."""
    source = getattr(artwork, '_he_panel_source', None)
    if source is None:
        source = BytesIO()
        artwork.crop((0, top, artwork.width, artwork.height)).save(source, format='PNG')
        artwork._he_panel_source = source
    return source
