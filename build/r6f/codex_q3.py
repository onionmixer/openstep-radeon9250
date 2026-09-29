import struct, math, random
from fractions import Fraction as Fr
from conv_space import hyps, f32
exec(open('design2.py').read().split("random.seed(1)")[0])   # Z (48 anchors)
def fz(h): return Fr(struct.unpack('<f', bytes.fromhex(h)[::-1])[0])
def rne(x): return round(x)                       # Fraction round = half even
def sat(n, x): return max(0, min((1 << n) - 1, x))
def fl2(z):
    return math.floor(math.log2(z)) if z > 0 else 0
def e_of(z):
    e = fl2(z)
    while Fr(2) ** e > z: e -= 1
    while Fr(2) ** (e + 1) <= z: e += 1
    return e
def H(z, mb):  # float with mb fraction bits, RNE
    e = e_of(z); s = Fr(2) ** (mb - e); return Fr(rne(z * s)) / s
NEW = {
 'bin16': lambda z, n: sat(n, rne(H(z, 10) * ((1 << n) - 1))),
 'fp24': lambda z, n: sat(n, rne(H(z, 16) * ((1 << n) - 1))),
 'fx12': lambda z, n: sat(n, rne(Fr(rne(z * 4096), 4096) * ((1 << n) - 1))),
 'u16to24': lambda z, n: sat(n, rne(Fr(rne(z * 65535)) * ((1 << n) - 1) / 65535)) if n == 24 else None,
 'res1': lambda z, n: sat(n, rne(z * ((1 << n) - 2))),
}
W = {'bin16': ('3e99999a', 16, 19664), 'fp24': ('3f612345', 24, 14754687), 'fx12': ('3e99999a', 16, 19664),
     'u16to24': ('3dcccccd', 24, 1677850), 'res1': ('3f400000', 16, 49150)}
for k, (h, n, want) in W.items():
    z = fz(h); got = NEW[k](z, n); H0 = hyps(n)
    vals = sorted(set(f(float(z)) for f in H0.values()))
    print(k, 'witness', h, 'z=%.9g' % float(z), 'mine', got, 'codex', want, 'space range', vals[0], '..', vals[-1], 'in space?', got in vals)
random.seed(1); probe = [f32(random.random()) for _ in range(3000)]
for n in (16, 24):
    H0 = hyps(n)
    sigs = {tuple(f(z) for z in Z): k for k, f in H0.items()}
    for k, f in NEW.items():
        if f(Fr(0.5), n) is None: continue
        s = tuple(f(Fr(z), n) for z in Z)
        eqp = [kk for kk, g in H0.items() if all(g(z) == f(Fr(z), n) for z in probe[:600])]
        print(n, k, 'anchor signature equals a space member:', s in sigs, '| equal to a member on 600 random z:', eqp[:3])
