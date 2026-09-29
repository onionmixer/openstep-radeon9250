# R6f-2 first look: a few candidate depth interpolation rules against the 24-bit planes
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0, 'tools/r6'); import depth_oracle as do
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl', 'rb'))
go = do.go
def verts(pts, p='t16'): return [(do.go.pos(x, p), do.go.pos(y, p)) for x, y in pts]
def bary(pts, pix, p='t16'):
    (x0, y0), (x1, y1), (x2, y2) = P = verts(pts, p)
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    out = []
    for x, y in pix:
        sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
        w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
        w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
        out.append((1 - w1 - w2, w1, w2))
    return out
def rules(bits):
    top = (1 << bits) - 1
    R = {}
    R['exact then floor'] = lambda w, z: [max(0, min(top, math.floor(sum(a * Fr(b) for a, b in zip(ww, z)) * (1 << bits))))
                                          for ww in w]
    R['exact then round'] = lambda w, z: [max(0, min(top, math.floor(sum(a * Fr(b) for a, b in zip(ww, z)) * (1 << bits) + Fr(1, 2))))
                                          for ww in w]
    for vm in ('floor', 'round'):
        for pm in ('floor', 'round'):
            def f(w, z, vm=vm, pm=pm, top=top, bits=bits):
                Z = [max(0, min(top, math.floor(Fr(v) * (1 << bits) + (Fr(1, 2) if vm == 'round' else 0)))) for v in z]
                out = []
                for ww in w:
                    s = sum(a * Fr(b) for a, b in zip(ww, Z))
                    out.append(max(0, min(top, math.floor(s + (Fr(1, 2) if pm == 'round' else 0)))))
                return out
            R['vertex %s, exact, %s' % (vm, pm)] = f
    return R
for name in ['I5_24', 'I1_24', 'I3_24', 'I6_24']:
    pts, zs = do.triangles(name)[0]
    pix = sorted(go.covered(pts))
    seen = [obs[name][q] for q in pix]
    w = bary(pts, pix)
    print(name, len(pix))
    for k, f in rules(24).items():
        got = f(w, zs)
        d = sum(1 for a, b in zip(got, seen) if a != b)
        mx = max((abs(a - b) for a, b in zip(got, seen)), default=0)
        print('   %-28s misses %4d max |diff| %d' % (k, d, mx))
