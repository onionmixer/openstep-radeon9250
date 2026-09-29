#!/usr/bin/env python3
"""R7 design 3: how big the client's batch may be.

  python3 build/r7/design3.py

Rewritten for G4-3 K4 (docs/G4_3_KERNEL_PLAN.md 5).  The first version modelled a submission as
"pad to the ring's end, then the words" and a 22-word prefix inside the same submission; both were
wrong about the driver as it is now (codex found it, the source confirmed it):

  1. cpR6Submit writes roundup16(n) words from the write pointer THROUGH cpPut, which masks the
     index -- a submission wraps in place, nothing is padded to the end (osrdn_cp.m, M3f).  Its new
     write pointer is (p + len) & mask, so the one thing that must hold is  len < CP_RING_WORDS:
     at equality the target IS the start and the CP would see an empty ring.
  2. What the driver wraps round a client's words is one WAIT_UNTIL pair in front (2) and the purge,
     wait, RB3D_CNTL and scratch pairs behind (10) -- TAIL_WORDS 12, in the SAME submission.  The
     32-word state prefix (G4-7: 26 + the TRI_PERF pair; G4-9: + TAM_DEBUG3) is a separate cpR6Submit that completes first, so it never shares the
     ring space of the client's submission.
  3. The driver's own word array (CP_R6_WORDS) must hold B + 12.

So B is the largest multiple of four with roundup16(B + 12) < CP_RING_WORDS, and CP_R6_WORDS is
roundup16(B + 12).  The mapped one-page window is NOT the limit any more: the copyin path carries
a full batch, and the window path is bounded by its page (OSRDN_R7B_WINDOW_WORDS).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
H = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_cp.h')
R7B = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj', 'osrdn_r7b.h')
VO = os.path.join(PROJ, 'tools', 'r7', 'verify_oracle.py')
DO = os.path.join(PROJ, 'tools', 'r6', 'depth_oracle.py')


def define(path, name):
    m = re.search(r'^%s\s*=\s*(\d+)' % name if path.endswith('.py') else r'#define\s+%s\s+\(?(\d+)' % name,
                  open(path).read(), re.M)
    return int(m.group(1)) if m else None


RING_WORDS = define(H, 'CP_RING_WORDS')
TAIL_WORDS = 2 + 10                             # the driver's WAIT_UNTIL, and its tail (osrdn_cp.m 3080-3088, 3224-3228)
STATE_PREFIX_WORDS = 32                         # its own submission (osrdn_cp.m 2967-2972); not in the inequality
MEASURED_MAX = 1250                             # R6l: the biggest packet the ladder ran


def roundup16(n):
    return (n + 15) & ~15


def submit_len(b):
    return roundup16(b + TAIL_WORDS)


def main():
    bad = 0
    best = 0
    for b in range(4, RING_WORDS, 4):
        if submit_len(b) < RING_WORDS:
            best = b
    print('the ring is %d words; a client submission of B costs roundup16(B + %d) and must be BELOW it'
          % (RING_WORDS, TAIL_WORDS))
    print('the biggest client batch: B = %d  (roundup16(%d + %d) = %d < %d)'
          % (best, best, TAIL_WORDS, submit_len(best), RING_WORDS))
    if submit_len(best + 4) < RING_WORDS:
        print('  FAIL: not tight')
        bad += 1
    else:
        print('  one 4-word step more would cost %d -- not below the ring, so the limit is tight' % submit_len(best + 4))
    if best < MEASURED_MAX:
        print('  FAIL: smaller than the %d words R6l ran' % MEASURED_MAX)
        bad += 1
    words = roundup16(best + TAIL_WORDS)
    print("the driver's command list must hold %d words: CP_R6_WORDS = %d" % (best + TAIL_WORDS, words))
    print('the state prefix (%d words, its own submission) costs %d and completes first'
          % (STATE_PREFIX_WORDS, roundup16(STATE_PREFIX_WORDS)))

    # the constants the driver, the oracle and the header carry must be these
    for path, name, want in ((H, 'CP_R7_BATCH_MAX', best), (H, 'CP_R6_WORDS', words),
                             (R7B, 'OSRDN_R7B_MAX_WORDS', best), (VO, 'BATCH_MAX_WORDS', best),
                             (DO, 'WORDS_MAX', words)):
        got = define(path, name)
        ok = got == want
        print('  %-4s %s %s = %s (want %d)' % ('ok' if ok else 'FAIL', os.path.basename(path), name, got, want))
        bad += 0 if ok else 1
    win = define(R7B, 'OSRDN_R7B_WINDOW_BYTES')
    print('the mapped window is %d bytes = %d words: the window path is bounded by it, the copyin path by B'
          % (win, win // 4))
    if win // 4 > best:
        print('  FAIL: the window holds more than the limit')
        bad += 1
    print('design3: %s' % ('PASS' if not bad else 'FAIL (%d)' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
