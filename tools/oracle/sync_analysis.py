#!/usr/bin/env python3
"""Keep the generated register table in ANALYSIS.md identical to regtable.py.

  sync_analysis.py          rewrite the block between the markers
  sync_analysis.py --check  exit 1 if the block differs (or markers missing)

The table is generated from the three reference headers; the prose around it
is written by hand.  Only the block between the markers is machine-owned.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
DOC = os.path.join(ROOT, 'ANALYSIS.md')
BEGIN = '<!-- BEGIN regtable.py --markdown (generated; do not edit) -->'
END = '<!-- END regtable.py -->'


def generated():
    out = subprocess.run([sys.executable, os.path.join(HERE, 'regtable.py'), '--markdown'],
                         check=True, capture_output=True, text=True).stdout
    return out.rstrip('\n') + '\n'


def main():
    text = open(DOC).read()
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        print('sync_analysis: markers missing or duplicated in ANALYSIS.md')
        return 1
    head, rest = text.split(BEGIN)
    old, tail = rest.split(END)
    new = '\n' + generated()
    if '--check' in sys.argv:
        if old != new:
            print('sync_analysis: ANALYSIS.md table is stale; run sync_analysis.py')
            return 1
        rows = sum(1 for line in new.splitlines() if line.startswith('| ') and '`' in line)
        print('sync_analysis: table current (%d register rows)' % rows)
        return 0
    open(DOC, 'w').write(head + BEGIN + new + END + tail)
    print('sync_analysis: table written')
    return 0


if __name__ == '__main__':
    sys.exit(main())
