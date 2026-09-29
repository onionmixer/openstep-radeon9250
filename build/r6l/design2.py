#!/usr/bin/env python3
"""R6l design 2: the ring padding, exhaustively -- cpR6Submit's arithmetic for every start.

The C is three lines (osrdn_cp.m cpR6Submit); the point of doing it here is that the hardware boot
can only ever show ONE alignment, so the formula itself is checked for all 4096 of them:
  - no word of the ring is written twice inside one submission
  - the payload never crosses the ring end (the fake CP in world5.c fails such a packet)
  - the new wptr is where the CP will stop, and the whole submission is contiguous from it backwards
"""
RING, MASK = 4096, 0xfff
SIZES = [65, 186, 188, 650, 1250, 1400]          # F, BC, BD, BA, BB, and CP_R6_WORDS


def submit(p, n):
    length = (n + 15) & ~15
    pad = RING - p if length > RING - p else 0
    words = [(p + k) & MASK for k in range(pad)] + [(p + pad + k) & MASK for k in range(length)]
    payload = [(p + pad + k) & MASK for k in range(n)]
    return pad, length, words, payload, (p + pad + length) & MASK


bad = 0
for n in SIZES:
    for p in range(RING):
        pad, length, words, payload, target = submit(p, n)
        if len(set(words)) != len(words):
            print('FAIL n=%d p=%d: a word is written twice' % (n, p))
            bad += 1
        if len(words) > RING:
            print('FAIL n=%d p=%d: the submission is longer than the ring' % (n, p))
            bad += 1
        # the payload must be contiguous and must not cross the end
        if any((payload[k] + 1) & MASK != payload[k + 1] for k in range(len(payload) - 1)):
            print('FAIL n=%d p=%d: the payload is not contiguous' % (n, p))
            bad += 1
        if payload and payload[0] > payload[-1]:
            print('FAIL n=%d p=%d: the payload crosses the ring end' % (n, p))
            bad += 1
        if target != (payload[0] + length) % RING:
            print('FAIL n=%d p=%d: target %d is not payload start + length' % (n, p, target))
            bad += 1
print('the pad arithmetic over %d starts x %d sizes: %s' %
      (RING, len(SIZES), 'PASS' if not bad else 'FAIL (%d)' % bad))
# and the one thing the formula cannot survive: a submission longer than the ring
n = RING + 1
pad, length, words, payload, target = submit(0, n)
print('a submission of %d words would write %d ring words -- CP_R6_WORDS must stay <= %d (checked in '
      'check_r5_src)' % (n, len(words), RING - 16))
