#!/usr/bin/env python3
"""Does one merged cpR6Submit still place its words where the card reads them?

cpR6Submit (osrdn_cp.m:1846-1867):
    len = roundup16(n)
    pad = (len > RING - p) ? RING - p : 0
    write PACKET2 at p .. p+pad-1
    write the stream at p+pad .. p+pad+len-1, INDICES MASKED (& C_RPTR_MASK)
When it pads, p+pad == RING == 0, so the stream lands at 0 .. len-1 while the
padding occupies p .. RING-1.  Those overlap exactly when len > p: a stream
word is written where a PACKET2 belongs, and the card -- which starts reading
at p -- reads that stream word out of order.  There is no len <= RING check.
"""
RING = 4096

def overlap(p, n, ring=RING):
    ln = (n + 15) & ~15
    if ln <= ring - p:
        return 0                     # no padding, contiguous
    if ln >= ring:
        return ring - p              # the stream covers every index
    return max(0, ln - p)            # stream words landing on the padding

def unsafe(n):
    return [p for p in range(RING) if overlap(p, n)]

PREFIX_R7 = 26     # 13 PACKET0 pairs, counted from osrdn_cp.m:2481-2497
PREFIX_R6 = 22     # 11 pairs (no SE_VTX_FMT_0/1)
TAIL      = 12     # our WAIT_UNTIL (2) + the tail (10), osrdn_cp.m:2423
BATCH     = 2016   # CP_R7_BATCH_MAX (osrdn_cp.h:188)
R6WORDS   = 2064   # CP_R6_WORDS (osrdn_cp.h:168)

# brute-force spot check of the closed form, on a small ring
def brute(p, n, ring):
    ln = (n + 15) & ~15
    pad = ring - p if ln > ring - p else 0
    pi = [(p + k) % ring for k in range(pad)]
    si = [(p + pad + k) % ring for k in range(ln)]
    return len(set(pi) & set(si))
bad = 0
for ring in (64, 128):
    for p in range(ring):
        for n in range(1, ring + 33):
            ln = (n + 15) & ~15
            got = overlap(p, n, ring)
            want = brute(p, n, ring)
            if got != want:
                bad += 1
                if bad < 4:
                    print('  MISMATCH ring=%d p=%d n=%d closed=%d brute=%d' % (ring, p, n, got, want))
print('closed form vs brute force on rings 64 and 128: %s' % ('PASS' if not bad else 'FAIL %d' % bad))
print()

print('prefix words, R7 case : %d   (the plan said 13 -- 13 is the PAIR count)' % PREFIX_R7)
print('prefix words, R6 cases: %d' % PREFIX_R6)
print()
for name, n in (('today, the prefix alone', PREFIX_R7),
                ('today, stage 2 alone',    BATCH + TAIL),
                ('MERGED, full batch',      PREFIX_R7 + BATCH + TAIL)):
    u = unsafe(n)
    print('%-25s n=%4d roundup16=%4d  unsafe write pointers: %4d%s'
          % (name, n, (n + 15) & ~15, len(u),
             ('  p in [%d, %d]' % (u[0], u[-1])) if u else ''))
print()
print('safe from every write pointer  <=>  roundup16(n) <= %d' % (RING // 2))
best = max(b for b in range(16, RING) if not unsafe(PREFIX_R7 + b + TAIL))
print('biggest client batch the MERGED path takes from every pointer: %d words' % best)
print('  CP_R7_BATCH_MAX is %d -- the merge must lower it by %d (a caps-visible change)'
      % (BATCH, BATCH - best))
print()
need = PREFIX_R7 + BATCH + TAIL
print("the driver's array: merged worst %d + %d + %d = %d;  CP_R6_WORDS %d;  margin %d"
      % (PREFIX_R7, BATCH, TAIL, need, R6WORDS, R6WORDS - need))
need2 = PREFIX_R7 + best + TAIL
print('  with the batch lowered to %d: need %d, margin %d' % (best, need2, R6WORDS - need2))
