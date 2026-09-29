# independent recount of the R6f anchors: own log parser, own conversion, own address maths
import re, sys, math, struct
from fractions import Fraction as Fr
sys.path.insert(0, 'tools/r6'); import depth_oracle as do
log = open('build/r6/boot-e4d44687.full.log', errors='replace').read().splitlines()
planes, cur = {}, None
for ln in log:
    m = re.search(r'RDN-R6 plh boot=(\w+) zc=(\d+) case=(\d+) lane=(\d+) chunk=(\d+) src=(\d+)', ln)
    if m:
        assert m.group(1) == 'e4d44687'; cur = (int(m.group(3)), int(m.group(4)), int(m.group(6))); continue
    m = re.search(r'RDN-R6 pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur:
        assert int(m.group(1)) == cur[1]
        planes.setdefault(cur, {})[int(m.group(2))] = [int(w, 16) for w in m.group(3).split()]
def bit(v, b): return (v >> b) & 1
def z16(x, y):          # written again from Mesa r200_span.c, not imported
    b = (y >> 4) * (64 >> 6) + (x >> 6)
    return (bit(x,0)<<1)|(bit(y,0)<<2)|(bit(x,1)<<3)|(bit(y,1)<<4)|(bit(x,2)<<5)|(bit(x,4)<<6)|(bit(x,5)<<7)|(bit(x,3)<<8)|(bit(y,2)<<9)|(bit(y,3)<<10)|((b&1)<<11)|((b>>1)<<12)
def z32(x, y):
    b = (y >> 4) * (64 >> 5) + (x >> 5)
    return (bit(x,0)<<2)|(bit(y,0)<<3)|(bit(x,1)<<4)|(bit(y,1)<<5)|(bit(x,3)<<6)|(bit(x,4)<<7)|(bit(x,2)<<8)|(bit(y,2)<<9)|(bit(y,3)<<10)|((b&1)<<11)|((b>>1)<<12)
def val(case, bits, x, y):
    lanes = 3 if bits == 16 else 3           # lanes 0,1 (+2 for 24)
    n = 2 if bits == 16 else 3
    i = y * 32 + x
    v = 0
    for l in range(n):
        ws = planes[(case, l, 2 if bits == 16 else 1)]
        w = [x_ for k in range(32) for x_ in ws[k]][i // 4]
        v |= ((w >> (8 * (i % 4))) & 0xff) << (8 * l)
    return v
def conv(z, bits, mode):
    top = (1 << bits) - 1
    s = Fr(z) * ((1 << bits) if mode[0] == 'p2' else top)
    k = math.floor(s) if mode[1] == 'floor' else math.floor(s + Fr(1, 2))
    return max(0, min(top, k))
bad = 0
for bits, first in ((16, 60), (24, 64)):
    obs = []
    for g in range(4):
        case = first + g
        for k, (x0, y0) in enumerate(do.CELLS):
            vs = {val(case, bits, x0, y0), val(case, bits, x0 + 1, y0), val(case, bits, x0, y0 + 1)}
            assert len(vs) == 1, (case, k, vs)
            obs.append(vs.pop())
    for mode in (('p2', 'floor'), ('m1', 'floor'), ('m1', 'up'), ('p2', 'up')):
        d = sum(1 for z, v in zip(do.ANCHORS, obs) if conv(z, bits, mode) != v)
        print(bits, mode, 'mismatches', d)
        if mode == ('p2', 'floor') and d: bad += 1
    print(bits, 'first 4 anchors', obs[:4], 'want', [conv(z, bits, ('p2','floor')) for z in do.ANCHORS[:4]])
# 16 = 24 >> 8 on the anchors too
same = sum(1 for g in range(4) for k, (x0, y0) in enumerate(do.CELLS)
           if val(60 + g, 16, x0, y0) == val(64 + g, 24, x0, y0) >> 8)
print('anchors: v16 == v24 >> 8 on', same, 'of 64')
print('independent check:', 'PASS' if bad == 0 else 'FAIL')
