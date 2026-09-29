#!/usr/bin/env python3
"""Transfer tables for rdnxfer (docs/G2_LUT_PLAN.md 3), packed RRGGBBAA.
  ident  -- the identity, k -> k
  ws22   -- what the window server sent this boot: floor(255 * (k/255)^(1/2.2)),
            the ONE formula whose packed sum is the logged 4a4a9a00 (python search,
            2026-09-26): the exact table, so sending it back is an exact restore.
Writes build/g2/<name>.txt and prints each table's packed sum."""
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'build', 'g2')
WS_SUM = 0x4a4a9a00

def packed(v):
    return (v << 24) | (v << 16) | (v << 8) | 0xff

tables = {
    'ident': [k for k in range(256)],
    'ws22': [min(255, math.floor(255 * (k / 255) ** (1 / 2.2))) for k in range(256)],
}
for name, t in tables.items():
    words = [packed(v) for v in t]
    s = sum(words) & 0xffffffff
    with open(os.path.join(OUT, name + '.txt'), 'w') as f:
        f.write('# %s: packed RRGGBBAA, 256 lines, sum %08x\n' % (name, s))
        for w in words:
            f.write('%08x\n' % w)
    print('%-6s sum %08x first %08x last %08x%s' % (name, s, words[0], words[-1],
          '  == logged xferdata sum' if s == WS_SUM else ''))
if (sum(packed(v) for v in tables['ws22']) & 0xffffffff) != WS_SUM:
    print('ws22 does not reproduce the logged sum'); sys.exit(1)
