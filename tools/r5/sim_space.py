#!/usr/bin/env python3
"""G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 1-5, 2-2): the driver's ring space against the reference's.

  sim_space.py

cpWaitSpace admits `len` words at wptr when (rptr - wptr - 1) & mask >= len.  FreeBSD's
radeon_wait_ring (radeon_cp.c 1901-1926) says space = head - tail, plus the size when that
is <= 0, and admits n when space > n.  This reads the driver's expression and the ring size
out of the source, evaluates it for EVERY (rptr, wptr) pair and every padded length the
driver can ask for, and compares.  The kick guard (cpLatchDump) uses the same free count and
must refuse exactly when fewer than 16 words are free.  Three mutations of the expression
must each be caught.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.normpath(os.path.join(HERE, '..', '..'))
CPM = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.m')
CPH = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.h')
EXPR = 'room = (cur - c->wptr - 1UL) & C_RPTR_MASK;'


def c_expr(line):
    """the C assignment as a python function of (cur, wptr, mask), 32-bit unsigned"""
    m = re.match(r'room = (.*);$', line.strip())
    if not m:
        return None
    e = m.group(1).replace('c->wptr', 'wptr').replace('C_RPTR_MASK', 'mask').replace('1UL', '1')
    if re.search(r'[^\w\s()&|+\-*]', e):
        return None
    return eval('lambda cur, wptr, mask: ((%s) & 0xffffffff)' % e)


def check(expr_line, size):
    f = c_expr(expr_line)
    if f is None:
        return ['the space expression is not one this checker can read: %r' % expr_line]
    mask = size - 1
    lens = sorted(set(((n + 15) // 16) * 16 for n in range(1, 4081)))
    bad = []
    for r in range(size):
        for w in range(size):
            room = f(r, w, mask)
            space = r - w
            if space <= 0:
                space += size
            if room != space - 1:
                bad.append((r, w, room, space))
                if len(bad) > 3:
                    return ['room != reference space - 1 at (rptr, wptr, room, space) %s' % bad]
            # the kick's guard: 16 NOPs only where the reference would admit 16
            if (room < 16) != (not space > 16):
                return ['the kick guard disagrees with the reference at rptr=%d wptr=%d' % (r, w)]
    # and every length the driver pads to: admitted exactly when the reference admits it
    for n in lens[:3] + lens[-3:]:
        for r in range(0, size, 7):
            w = (r + 5) & mask
            space = r - w
            if space <= 0:
                space += size
            if (f(r, w, mask) >= n) != (space > n):
                return ['length %d disagrees at rptr=%d wptr=%d' % (n, r, w)]
    return bad and ['room != reference space - 1 at %s' % bad] or []


def main():
    src = open(CPM).read()
    hdr = open(CPH).read()
    ms = re.search(r'#define\s+CP_RING_WORDS\s+(\d+)UL', hdr)
    fails = 0
    if not ms:
        print('  FAIL CP_RING_WORDS is not in osrdn_cp.h')
        return 1
    size = int(ms.group(1))
    if src.count(EXPR) != 1:
        print('  FAIL the space expression %r is in osrdn_cp.m %d times' % (EXPR, src.count(EXPR)))
        return 1
    p = check(EXPR, size)
    print('  %s the driver\'s space equals the reference\'s over all %d x %d pointer pairs%s'
          % ('ok  ' if not p else 'FAIL', size, size, '' if not p else ': ' + '; '.join(p)))
    fails += bool(p)
    for label, new in (('no reserved word', 'room = (cur - c->wptr) & C_RPTR_MASK;'),
                       ('the pointers swapped', 'room = (c->wptr - cur - 1UL) & C_RPTR_MASK;'),
                       ('two reserved words', 'room = (cur - c->wptr - 2UL) & C_RPTR_MASK;')):
        caught = bool(check(new.replace('2UL', '2'), size))
        print('  %s mutation %-24s %s' % ('ok  ' if caught else 'FAIL', label, 'caught' if caught else 'NOT caught'))
        fails += 0 if caught else 1
    print('sim_space: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
