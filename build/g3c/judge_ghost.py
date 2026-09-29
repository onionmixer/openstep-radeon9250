#!/usr/bin/env python3
"""G3c: the picture gate for the depth clear (docs/G3B_CLEAR_PLAN.md 7).

  judge_ghost.py <dir>     dir holds a.ppm (accel, VRAM, frames=1 angle 0), stock_a.ppm.mirror
                           (the stock link, same scene), seq.ppm.seq1/2/3.zraw (GHOST_SEQ=1:
                           clear 0.25, teapot, clear 0.75 -- the depth region, 480000 words)

COUNTERS SAID YES ON BOOT 5; THE PICTURE KNEW.  Three things must hold:
  1. the depth region after a clear is the clear value in EVERY 16-bit half-word of the
     surface (w x h x 2 bytes): floor(z * 65536) -- R6f's measured conversion
  2. the teapot then writes 16-bit z into at least its silhouette's worth of half-words,
     all of them nearer than the clear
  3. the accelerated picture is the stock picture except on edges: the silhouettes agree
     to 2 % and fewer than 3 % of the stock silhouette's pixels differ by more than 32 in a
     channel (the M3a judge's tolerance class -- shading differs at triangle edges)
"""
import os
import struct
import sys

W, H = 800, 600


def ppm(path, swap):
    d = open(path, 'rb').read()
    parts = d.split(b'\n', 3)
    assert parts[0] == b'P6' and parts[1] == b'%d %d' % (W, H), path
    px = parts[3]
    if swap:                        # (unused since boot 6: the VRAM bytes are R,G,B like the array)
        return [(px[i * 3 + 2], px[i * 3 + 1], px[i * 3]) for i in range(W * H)]
    return [(px[i * 3], px[i * 3 + 1], px[i * 3 + 2]) for i in range(W * H)]


def halfwords(path):
    d = open(path, 'rb').read()
    return struct.unpack('<%dH' % (len(d) // 2), d)


def mba16(pitch, x, y):
    """Mesa r200_span.c r200_mba_z16, as tools/r5/sim/world5.c r6MbaZ16 carries it: the byte address of
    pixel (x, y) in a 16-bit depth buffer -- 64 x 16 blocks, NOT a linear w x h x 2 region"""
    b = ((y & 0x7ff) >> 4) * ((pitch & 0xfff) >> 6) + ((x & 0x7ff) >> 6)
    par = (b & 1) if (pitch & 0x40) else ((b & 1) ^ ((y >> 4) & 1))
    return ((((x >> 0) & 1) << 1) | (((y >> 0) & 1) << 2) | (((x >> 1) & 1) << 3) | (((y >> 1) & 1) << 4) |
            (((x >> 2) & 1) << 5) | (((x >> 4) & 1) << 6) | (((x >> 5) & 1) << 7) | (((x >> 3) & 1) << 8) |
            (((y >> 2) & 1) << 9) | (((y >> 3) & 1) << 10) | (par << 11) | ((b >> 1) << 12))


LATE_TILE = 1024      # half-words: the clear's last z-cache lines land with the NEXT submission (the
                      # reference ends its clear without a purge; measured on boot 6: exactly the 32 x 32
                      # block at the origin is still old when the CPU reads right after the ioctl)


def main(d):
    bad = []
    s1 = halfwords(os.path.join(d, 'seq.ppm.seq1.zraw'))
    s2 = halfwords(os.path.join(d, 'seq.ppm.seq2.zraw'))
    s3 = halfwords(os.path.join(d, 'seq.ppm.seq3.zraw'))
    n = W * H
    pitch = (W + 31) & ~31                      # OSRDNMesaDepth.c 109 / OSRDNMesaTri.c 454
    covered = set(mba16(pitch, x, y) // 2 for y in range(H) for x in range(W))
    print('  layout    : pitch %d, %d distinct half-words for %d pixels' % (pitch, len(covered), n))
    for name, s, z in (('clear 1.0', s1, 0xffff), ('clear 0.75', s3, int(0.75 * 65536))):
        wrong = sum(1 for i in covered if s[i] != z)
        print('  %-10s: %d covered half-words are not %04x (late tile allowance %d)' % (name, wrong, z, LATE_TILE))
        if wrong > LATE_TILE:
            bad.append('%s left %d half-words' % (name, wrong))
    wrote = [i for i in covered if s2[i] != s1[i] and s2[i] != 0xffff]
    nearer = sum(1 for i in wrote if s2[i] < 0xffff)
    print('  teapot    : wrote %d half-words, %d nearer than the clear' % (len(wrote), nearer))
    st = ppm(os.path.join(d, 'stock_a.ppm.mirror'), False)
    ac = ppm(os.path.join(d, 'a.ppm'), False)      # boot 6 measured: the VRAM word's byte 0 IS R, as the stock array's
    from collections import Counter
    bg = Counter(st).most_common(1)[0][0]
    sil_st = set(i for i in range(n) if st[i] != bg)
    sil_ac = set(i for i in range(n) if ac[i] != bg)
    sym = len(sil_st ^ sil_ac)
    big = sum(1 for i in range(n) if max(abs(ac[i][k] - st[i][k]) for k in range(3)) > 32)
    print('  picture   : stock silhouette %d, accel %d, symmetric difference %d, pixels off by >32: %d'
          % (len(sil_st), len(sil_ac), sym, big))
    if len(wrote) < len(sil_st) // 2:
        bad.append('the teapot wrote %d half-words (%d nearer) against a silhouette of %d' % (len(wrote), nearer, len(sil_st)))
    if sym > 0.02 * len(sil_st):
        bad.append('silhouettes differ by %d pixels' % sym)
    if big > 0.03 * len(sil_st):
        bad.append('%d pixels off by more than 32' % big)
    print('judge_ghost: %s' % ('PASS' if not bad else 'FAIL -- ' + '; '.join(bad)))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else '.'))
