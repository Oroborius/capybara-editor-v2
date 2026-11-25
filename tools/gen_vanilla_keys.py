"""Writes src/mxl_vanilla_keys.json: the vanilla (1.13c) row names of the tables whose names Median XL does not
store in its compiled .bin files (states, skills, missiles, overlay, monstats), with the fingerprint columns that
tell whether a row is still the vanilla one, resolved to (offset, type) of the Median layout.

Source: D2-Development-Kit (MIT), d2bt/data/vanilla_keys.json + d2bt/binfmt/layouts/mxl/<table>.json.

    python3 tools/gen_vanilla_keys.py /path/to/D2-Development-Kit
"""
import json
import os
import sys

TABLES = ('states', 'skills', 'missiles', 'overlay', 'monstats')
TYPES = {'u8': 'B', 'i8': 'b', 'u16': 'H', 'i16': 'h', 'u32': 'I', 'i32': 'i'}


def main(kit):
    van = json.load(open(os.path.join(kit, 'd2bt', 'data', 'vanilla_keys.json')))['tables']
    out = {'source': 'D2-Development-Kit, MIT (d2bt/data/vanilla_keys.json, layouts/mxl)'}
    for t in TABLES:
        v = van[t]
        lay = json.load(open(os.path.join(kit, 'd2bt', 'binfmt', 'layouts', 'mxl', t + '.json')))
        fields = {f['name'].lower(): f for f in lay['fields']}
        fp = []
        for col, vals in v['fingerprint'].items():
            f = fields.get(col.lower())
            if f and f['type'] in TYPES:
                fp.append([f['offset'], TYPES[f['type']], vals])
        out[t] = {'record_size': lay.get('record_size'), 'names': v['names'], 'fingerprint': fp}
    dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'mxl_vanilla_keys.json')
    with open(dst, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))
    print(dst, os.path.getsize(dst), {t: len(out[t]['fingerprint']) for t in TABLES})


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/home/ps5/Downloads/D2-Development-Kit')
