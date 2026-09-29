import time, random, struct, sys
from interp_space import *
from conv_space import f32
t0 = time.time()
random.seed(62307)
def rz(): return f32(random.uniform(0.05, 0.95))
G = {'T1': [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)],
     'X3': go.GCASES['G3'][0], 'S1': go.GCASES['S1'][0], 'V1': go.GCASES['V1'][0], 'V4': go.GCASES['V4'][0]}
CASES = [('I1', 'T1', (0.25, 0.75, 0.25)), ('I2', 'T1', (0.25, 0.25, 0.75)),
         ('I3', 'X3', (rz(), rz(), rz())), ('I4', 'S1', (rz(), rz(), rz())),
         ('I5', 'V1', (0.5, f32(0.5 + 2 ** -12), f32(0.5 - 3 * 2 ** -13))),   # small gradient
         ('I6', 'V4', (0.03, 0.97, 0.5)),                                     # large gradient
         ('I7', 'V1', (rz(), rz(), rz()))]
F = families()
for name, g, zs in CASES:
    print(name, g, ['%.9g' % z for z in zs], len(go.covered(G[g])))
for bits in (16, 24):
    for c in CONVS:
        sig = {}
        for k, fn in F.items():
            s = tuple(tuple(conv(v, bits, c) for v in fn(G[g], zs, go.covered(G[g]))) for _, g, zs in CASES)
            sig.setdefault(s, []).append(k)
        merged = [v for v in sig.values() if len(v) > 1]
        print(bits, c, 'families', len(F), 'distinct', len(sig), 'merged groups', merged[:6], '%.0fs' % (time.time() - t0))
        sys.stdout.flush()
