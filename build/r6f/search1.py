# R6f-2: value = floor(Zref + qx*(x - xr) + qy*(y - yr)), gradients quantised to 2^-f of a depth LSB
import pickle, sys, math, itertools
from fractions import Fraction as Fr
sys.path.insert(0, 'tools/r6'); import depth_oracle as do
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl','rb')); go=do.go
def q(v, f, m):
    s = v * (1 << f)
    k = math.floor(s) if m == 'floor' else math.floor(s + Fr(1,2)) if m == 'up' else int(s) if m == 'tz' else math.ceil(s)
    return Fr(k, 1 << f)
def setup(name):
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); z=[Fr(v) for v in zs]
    bits = do.fmt_bits(name); S = 1 << bits
    Z=[v*S for v in z]
    gx=((Z[1]-Z[0])*(y2-y0)-(Z[2]-Z[0])*(y1-y0))/A
    gy=((Z[2]-Z[0])*(x1-x0)-(Z[1]-Z[0])*(x2-x0))/A
    return P, Z, gx, gy, sorted(go.covered(pts)), (1 << bits) - 1
def predict(name, f, m, ref, rm):
    P, Z, gx, gy, pix, top = setup(name)
    qx, qy = q(gx, f, m), q(gy, f, m)
    r = {'v0': 0, 'left': min(range(3), key=lambda i: (P[i][0], P[i][1])),
         'top': min(range(3), key=lambda i: (P[i][1], P[i][0]))}[ref]
    zr = Z[r] if rm == 'exact' else q(Z[r], f, m)
    xr, yr = P[r]
    out = []
    for x, y in pix:
        v = zr + qx*(Fr(2*x+1,2) - xr) + qy*(Fr(2*y+1,2) - yr)
        out.append(max(0, min(top, math.floor(v))))
    return out, pix
CASES = [n + b for n in do.IORDER for b in ('_24', '_16')]
best = []
for f in range(0, 13):
    for m in ('floor', 'up', 'tz'):
        for ref in ('v0', 'left', 'top'):
            for rm in ('exact', 'q'):
                tot = 0
                for name in CASES:
                    got, pix = predict(name, f, m, ref, rm)
                    tot += sum(1 for a, p in zip(got, pix) if a != obs[name][p])
                best.append((tot, f, m, ref, rm))
best.sort()
for t in best[:8]: print('misses %5d  f=%-2d %-5s ref=%-4s zref=%s' % t)
