# depth conversion hypotheses: float32 z in [0,1] -> 16/24-bit integer
import struct, math, random, itertools
from fractions import Fraction as Fr
def f32(x): return struct.unpack('<f', struct.pack('<f', x))[0]
def rnd(v, m):
    f = math.floor(v)
    if m == 'floor': return f
    if m == 'up': return math.floor(v + Fr(1, 2))
    if m == 'even': return round(v)
    if m == 'ceil': return math.ceil(v)
def hyps(bits):
    out = {}
    top = (1 << bits) - 1
    for q in (None, 16, 20, 24, 32):            # pre-quantise z to 2^-q
        for qm in ('floor', 'up'):
            if q is None and qm == 'up': continue
            for scale in ('m1', 'p2'):          # (2^n - 1) or 2^n
                for m in ('floor', 'up', 'even', 'ceil'):
                    def h(z, q=q, qm=qm, scale=scale, m=m):
                        zz = Fr(z) if q is None else Fr(rnd(Fr(z) * (1 << q), qm), 1 << q)
                        v = zz * (top if scale == 'm1' else (1 << bits))
                        return max(0, min(top, rnd(v, m)))
                    out[('q%s%s' % (q, qm if q else ''), scale, m)] = h
    if bits == 16:                               # 16 from a 24-bit value
        for k, h24 in hyps(24).items():
            for sm in ('shift', 'up'):
                def h(z, h24=h24, sm=sm):
                    v = h24(z)
                    return v >> 8 if sm == 'shift' else min(0xffff, (v + 128) >> 8)
                out[('from24',) + k + (sm,)] = h
    for m in ('floor', 'up', 'even'):            # float32 product
        def h(z, m=m):
            return max(0, min(top, rnd(Fr(f32(z * top)), m)))
        out[('f32prod', m)] = h
    return out
if __name__ == '__main__':
    random.seed(1)
    probe = [f32(random.random()) for _ in range(4000)] + [0.5, 0.75, 0.25, 1.0, f32(1/3)]
    for bits in (16, 24):
        H = hyps(bits)
        sig = {}
        for k, h in H.items():
            sig.setdefault(tuple(h(z) for z in probe), []).append(k)
        print(bits, 'hyps', len(H), 'distinct on probe', len(sig))
