#!/usr/bin/env python3
"""Extract Hero Editor 1.04 artwork from a user-supplied installation."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from mxl_vanilla_he_assets import load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='folder containing Hero Editor.exe')
    parser.add_argument('output', type=Path, help='directory for the extracted PNGs')
    args = parser.parse_args()
    pictures = load(args.folder)
    if not pictures:
        parser.error('no supported Hero Editor 1.04 pictures found')
    args.output.mkdir(parents=True, exist_ok=True)
    for name, picture in pictures.items():
        picture.save(args.output / f'{name}.png')


if __name__ == '__main__':
    main()
