"""Command-line export of stock creation candidates."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('out', type=Path)
    source = export.add_mutually_exclusive_group()
    source.add_argument('--game', help='LoD 1.14d install directory (or set D2BT_LEGIT_GAME)')
    source.add_argument('--tables', type=Path, help='directory of extracted stock tables')
    export.add_argument('--non-ladder', action='store_true', help='exclude ladder-only unique drops')
    vocab = commands.add_parser('vocab', help='export the stat and parameter vocabulary')
    vocab.add_argument('out', type=Path)
    vsource = vocab.add_mutually_exclusive_group()
    vsource.add_argument('--game', help='LoD 1.14d install directory (or set D2BT_LEGIT_GAME)')
    vsource.add_argument('--tables', type=Path, help='directory of extracted stock tables')
    args = parser.parse_args()
    if args.command == 'vocab':
        from . import vocab as build_vocab
        try:
            result = build_vocab(args.game, tables=args.tables)
            with args.out.open('w', encoding='utf-8') as output:
                json.dump(result, output, ensure_ascii=False, separators=(',', ':'))
                output.write('\n')
        except (OSError, ValueError) as exc:
            parser.exit(1, f'{exc}\n')
        return

    from ..legit import Validator, stock_validator
    from .export import build_export

    game = args.game or os.environ.get('D2BT_LEGIT_GAME')
    if not game and args.tables is None:
        installed = (Path.home() / 'Games/diablo-ii-lord-of-destruction/drive_c'
                     / 'Program Files (x86)/Diablo II')
        if installed.is_dir():
            game = installed
    try:
        data = Validator(args.tables) if args.tables is not None else stock_validator(game)
        result = build_export(data, ladder=not args.non_ladder)
        with args.out.open('w', encoding='utf-8') as output:
            json.dump(result, output, separators=(',', ':'))
            output.write('\n')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
