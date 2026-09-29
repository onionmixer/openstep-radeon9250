#!/usr/bin/env python3
"""R7 design 1: the verifier's register allow-list, DERIVED from what the harness measured.

  python3 build/r7/design1.py

The list a verifier lets through must not be typed by hand: a register typed in but never measured
is a guess, and a register the harness writes but the list omits makes the driver refuse its own
stream.  So it is read out of osrdn_cp.m -- every `C_P0(<name>)` plus the PACKET0 headers inside
cpR6State[] -- and printed as the C table the driver will carry.  A host check later compares the
driver's table against this, so the two cannot drift.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
CP = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.m')


def measured(src):
    """{register offset: the name the source uses} -- the registers the R6 harness actually writes"""
    out = {}
    for name in set(re.findall(r'C_P0\((C_[A-Z0-9_]+)', src)):
        m = re.search(r'#define\s+%s\s+(0x[0-9a-fA-F]+)' % name, src)
        if m:
            out[int(m.group(1), 0)] = name
    # the precedent's state block is a table of ready-made PACKET0 words: header, value, ...
    i = src.index('static const unsigned long cpR6State[')
    words = [int(x, 0) for x in re.findall(r'0x[0-9a-fA-F]+', src[i:src.index('};', i)])]
    for w in words[0::2]:
        if (w >> 30) == 0:                          # PACKET0: type 0, one register
            out.setdefault((w & 0x3fff) * 4, 'cpR6State')
    return out


def bases_with_offsets(src):
    """registers the harness reaches as `C_P0(BASE + k)` -- the list must hold BASE + k too"""
    out = {}
    for name, off in re.findall(r'C_P0\((C_[A-Z0-9_]+) \+ (\d+)\)', src):
        out.setdefault(name, set()).add(int(off))
    return out


def main():
    src = open(CP).read()
    regs = measured(src)
    extra = bases_with_offsets(src)
    named = sum(1 for v in regs.values() if v != 'cpR6State')
    print('registers written by name       : %d' % named)
    print('registers only in cpR6State[]   : %d' % (len(regs) - named))
    print('the measured allow-list         : %d registers' % len(regs))
    for a in sorted(regs):
        print('    0x%04x  %s' % (a, regs[a]))
    if extra:
        print('reached as BASE + k (the list must hold those too):')
        for n, offs in sorted(extra.items()):
            print('    %s + %s' % (n, sorted(offs)))
    # the four the verifier must NOT take from a client: they are the harness's own bookkeeping
    ours = {0x15e0: 'SCRATCH_REG0 (the markers)', 0x1720: 'WAIT_UNTIL (the state block and the tail)',
            0x3254: 'RB3D_ZCACHE_CTLSTAT (the purge)', 0x325c: 'RB3D_DSTCACHE_CTLSTAT (the purge)'}
    print('of those, reserved to the driver (a client may not write them):')
    for a, why in sorted(ours.items()):
        print('    0x%04x  %s%s' % (a, why, '' if a in regs else '   -- NOT in the list?'))
    print('a client may write %d of the %d' % (len(regs) - len(ours), len(regs)))
    bad = [a for a in ours if a not in regs]
    print('design1: %s' % ('PASS' if not bad else 'FAIL (reserved register not measured: %s)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
