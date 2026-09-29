"""R6j host analysis 2: the product map, clamp-aware, and the candidate arithmetics."""
import pickle
import sys

sys.path.insert(0, 'tools/r6')
N = 'e5d4204a'
import persp_oracle as pe
obs = pickle.load(open('build/r6j/observed_%s.pkl' % N, 'rb'))
dst = pe.blend_dst()
SL = (pe.BLEND_SRC[2], pe.BLEND_SRC[1], pe.BLEND_SRC[0], pe.BLEND_SRC[3])
DL = dict((p, (d[2], d[1], d[0], d[3])) for p, d in dst.items())
L = dict((n, dict((p, [(w >> (8 * l)) & 0xff for l in range(4)]) for p, w in obs[n].items()))
         for n in ('J1', 'J3', 'J4', 'J5', 'J6', 'J2'))

# ---- J2 sanity: destination preserved
print('J2 == rule B destination: %s' % all(L['J2'][p][l] == DL[p][l] for p in DL for l in range(4)))
# ---- P(s,0x37) from the unclamped J6 pixels
psa = {}
for l in range(4):
    v = set(L['J6'][p][l] - DL[p][l] for p in DL if L['J6'][p][l] != 255)
    psa[l] = v
    print('P(%3d, 0x37) = %s   (a*b/255 = %.3f)' % (SL[l], sorted(v), SL[l] * 55 / 255.0))
assert all(len(v) == 1 for v in psa.values())
psa = dict((l, next(iter(v))) for l, v in psa.items())
# ---- P(d,0xc8) from J4
pm = {}
bad = 0
for p in DL:
    for l in range(4):
        d = DL[p][l]
        q = L['J4'][p][l] - psa[l]
        if L['J4'][p][l] == 255:
            continue
        pm.setdefault(d, set()).add(q)
print('P(d, 0xc8): %d distinct d, ambiguous %d' % (len(pm), sum(1 for v in pm.values() if len(v) > 1)))
rows = sorted((d, sorted(v)) for d, v in pm.items())
for d, v in rows[:8] + rows[-4:]:
    print('  d=%3d -> %-8s exact %.3f floor %d round %d' % (d, v, d * 200 / 255.0,
          int(d * 200 // 255), int(d * 200 / 255.0 + 0.5)))
# ---- candidate closed forms for P(a,b)
def cands(a, b):
    x = a * b
    return {
        'floor255': x // 255, 'round255': (x * 2 + 255) // 510, 'ceil255': -((-x) // 255),
        'sh8_r0': x >> 8, 'sh8_r128': (x + 128) >> 8, 'sh8_r137': (x + 137) >> 8,
        'div255_mul': (x + 128 + ((x + 128) >> 8)) >> 8, 'sat256': (a * (256 if b == 255 else b)) >> 8,
        'sat256_r128': (a * (256 if b == 255 else b) + 128) >> 8,
        'expand9': (a * (b + (b >> 7))) >> 8, 'expand9_r128': (a * (b + (b >> 7)) + 128) >> 8,
        'expand9_r255': (a * (b + (b >> 7)) + 255) >> 8,
    }
names = sorted(cands(1, 1))
score = dict((n, 0) for n in names)
tot = 0
for d, v in pm.items():
    if len(v) != 1:
        continue
    got = next(iter(v))
    tot += 1
    c = cands(d, 200)
    for n in names:
        score[n] += (c[n] != got)
for l in range(4):
    c = cands(SL[l], 55)
    tot += 1
    for n in names:
        score[n] += (c[n] != psa[l])
print('P fit over %d points:' % tot)
for n in sorted(names, key=lambda n: score[n]):
    print('   %-14s %d wrong' % (n, score[n]))

# ---- where does expand9 miss, and what variants fix it?
print('--- expand9 misses')
pts = [(d, 200, next(iter(v))) for d, v in sorted(pm.items()) if len(v) == 1]
pts += [(SL[l], 55, psa[l]) for l in range(4)]
for a, b, got in pts:
    if (a * (b + (b >> 7))) >> 8 != got:
        print('   a=%3d b=%3d got %3d  expand9 %3d  exact %.4f' %
              (a, b, got, (a * (b + (b >> 7))) >> 8, a * b / 255.0))
VAR = {
    'Eb': lambda a, b: (a * (b + (b >> 7))) >> 8,
    'Ea': lambda a, b: ((a + (a >> 7)) * b) >> 8,
    'EaEb': lambda a, b: ((a + (a >> 7)) * (b + (b >> 7))) >> 8,
    'EaEb_9': lambda a, b: ((a + (a >> 7)) * (b + (b >> 7))) >> 9,
    'Eb_r1': lambda a, b: (a * (b + (b >> 7)) + 1) >> 8,
    'Eb_r128': lambda a, b: (a * (b + (b >> 7)) + 128) >> 8,
    'Ea_r128': lambda a, b: ((a + (a >> 7)) * b + 128) >> 8,
    'sym': lambda a, b: (a * b + a + b) >> 8,
    'sym1': lambda a, b: (a * b + a + b + 1) >> 8,
    'symh': lambda a, b: (a * b + ((a + b) >> 1)) >> 8,
    'x_xs8': lambda a, b: (a * b + ((a * b) >> 8)) >> 8,
    'x_xs8_1': lambda a, b: (a * b + ((a * b) >> 8) + 1) >> 8,
}
print('--- variants over %d points' % len(pts))
for n, f in sorted(VAR.items(), key=lambda t: sum(t[1](a, b) != g for a, b, g in pts)):
    print('   %-10s %d wrong' % (n, sum(f(a, b) != g for a, b, g in pts)))
