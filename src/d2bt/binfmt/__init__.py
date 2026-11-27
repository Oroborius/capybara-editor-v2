"""Classic D2 excel .bin / .tbl decoding (layouts as data), plus D2R bins and calc code."""
from .bin2txt import Context, convert, convert_file, write_txt, raw_dump  # noqa: F401
from .tbl import Tbl, StringSet  # noqa: F401
