#!/usr/bin/env python3
"""G5-2 phase 0: the two streams of run_g52_0.sh (see there).  Rebuilds build/g52/{real-stream,synth-prologue}.bin."""
import os, struct
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N = 4057            # trace-g411.txt seq 9af: the last stream kept in trace-g411-last.bin (the file is not truncated)
w = list(struct.unpack('<%dI' % (os.path.getsize(R + '/build/g410/trace-g411-last.bin') // 4),
                       open(R + '/build/g410/trace-g411-last.bin', 'rb').read()))[:N]

def walk(s):
    i, p3, n0 = 0, [], 0
    while i < len(s):
        h = s[i]; t = h >> 30; c = ((h >> 16) & 0x3fff) + 1
        assert t in (0, 3), (t, i)
        if t == 3: p3.append(i)
        else: n0 += 1
        i += 1 + c
    assert i == len(s)
    return p3, n0

p3, n0 = walk(w)
tris = 0
for hi in p3:
    cnt = ((w[hi] >> 16) & 0x3fff) + 1
    assert (cnt - 1) % 7 == 0                   # x y z w colour s t
    tris += (cnt - 1) // 7 // 3
hi = p3[0]; vw = 7
one = 1 + 3 * vw
hdr = (3 << 30) | ((one - 1) << 16) | (w[hi] & 0xffff)
vf1 = (w[hi + 1] & 0xffff) | (3 << 16)
tri = [hdr, vf1] + w[hi + 2:hi + 2 + 3 * vw]
pro = w[:hi]
pairs, j = [], 0
while j < len(pro):
    c = ((pro[j] >> 16) & 0x3fff) + 1; pairs.append(pro[j:j + 1 + c]); j += 1 + c
synth = []
while len(synth) + len(pro) + len(tri) <= N: synth += pro
k = 0
while len(synth) + 2 + len(tri) <= N: synth += pairs[k % len(pairs)]; k += 1
synth += tri
p3s, n0s = walk(synth)
assert len(synth) == N and len(p3s) == 1
open(R + '/build/g52/real-stream.bin', 'wb').write(struct.pack('<%dI' % N, *w))
open(R + '/build/g52/synth-prologue.bin', 'wb').write(struct.pack('<%dI' % N, *synth))
print('real: %d words, %d register packets, %d draws, %d triangles' % (N, n0, len(p3), tris))
print('synth: %d words, %d register packets, 1 draw of 1 triangle (prologue %d words x%d + %d pairs)'
      % (N, n0s, len(pro), N // len(pro), k))
