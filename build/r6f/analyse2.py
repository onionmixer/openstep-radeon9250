# the observed per-pixel differences against the exact gradient (24-bit units)
import pickle, sys
from fractions import Fraction as Fr
sys.path.insert(0, 'tools/r6'); import depth_oracle as do
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl', 'rb'))
go = do.go
for name in ['I1_24', 'I2_24', 'I3_24', 'I4_24', 'I5_24', 'I6_24', 'I7_24']:
    pts, zs = do.triangles(name)[0]
    P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in pts]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    z = [Fr(v) for v in zs]
    dzdx = ((z[1] - z[0]) * (y2 - y0) - (z[2] - z[0]) * (y1 - y0)) / A
    dzdy = ((z[2] - z[0]) * (x1 - x0) - (z[1] - z[0]) * (x2 - x0)) / A
    v = obs[name]
    cov = set(go.covered(pts))
    dx = [v[(x + 1, y)] - v[(x, y)] for (x, y) in cov if (x + 1, y) in cov]
    dy = [v[(x, y + 1)] - v[(x, y)] for (x, y) in cov if (x, y + 1) in cov]
    ex, ey = dzdx * (1 << 24), dzdy * (1 << 24)
    print('%-7s dzdx*2^24 = %-14s observed steps %s' % (name, '%.4f' % float(ex), sorted(set(dx))[:6]))
    print('        dzdy*2^24 = %-14s observed steps %s' % ('%.4f' % float(ey), sorted(set(dy))[:6]))
