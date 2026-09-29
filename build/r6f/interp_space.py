# depth interpolation analysis families (pre-conversion value per covered pixel), then a conversion
import sys, math, numpy as np
sys.path.insert(0, '../../tools/r6')
import gouraud_oracle as go, tri_oracle as to
from fractions import Fraction as Fr
F32 = np.float32
def rq(v, k, m):
    s = v * (1 << k); f = math.floor(s)
    if m == 'up': f = math.floor(s + Fr(1, 2))
    elif m == 'even': f = round(s)
    return Fr(f, 1 << k)
def verts(pts, p):
    return [(go.pos(x, p), go.pos(y, p)) for x, y in pts]
def lefti(P): return min(range(3), key=lambda i: (P[i][0], P[i][1]))
def topi(P): return min(range(3), key=lambda i: (P[i][1], P[i][0]))
def fam_exact(pts, zs, pix, p='t16'):
    (x0, y0), (x1, y1), (x2, y2) = P = verts(pts, p)
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    z = [Fr(v) for v in zs]; out = []
    for x, y in pix:
        sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
        w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
        w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
        out.append((1 - w1 - w2) * z[0] + w1 * z[1] + w2 * z[2])
    return out
def fam_wq(pts, zs, pix, k, m):
    (x0, y0), (x1, y1), (x2, y2) = P = verts(pts, 't16'); L = lefti(P)
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    z = [Fr(v) for v in zs]; out = []
    for x, y in pix:
        sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
        w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
        w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
        w = [1 - w1 - w2, w1, w2]
        for i in range(3):
            if i != L: w[i] = rq(w[i], k, m)
        w[L] = 1 - sum(w[i] for i in range(3) if i != L)
        out.append(sum(a * b for a, b in zip(w, z)))
    return out
def fam_f32(pts, zs, pix, ref):
    P = [(F32(float(a)), F32(float(b))) for a, b in verts(pts, 't16')]
    z = [F32(v) for v in zs]
    (x0, y0), (x1, y1), (x2, y2) = P
    ax, ay, bx, by = x1 - x0, y1 - y0, x2 - x0, y2 - y0
    dz1, dz2 = z[1] - z[0], z[2] - z[0]
    A = ax * by - bx * ay
    dzdx = (dz1 * by - dz2 * ay) / A
    dzdy = (dz2 * ax - dz1 * bx) / A
    r = {'v0': 0, 'left': lefti(P), 'top': topi(P)}[ref]
    xr, yr, zr = P[r][0], P[r][1], z[r]
    out = []
    for x, y in pix:
        sx, sy = F32(x + 0.5), F32(y + 0.5)
        out.append(Fr(float(zr + dzdx * (sx - xr) + dzdy * (sy - yr))))
    return out
def fam_fx(pts, zs, pix, f, m, ref):
    P = verts(pts, 't16'); z = [Fr(v) for v in zs]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    dzdx = rq(((z[1] - z[0]) * (y2 - y0) - (z[2] - z[0]) * (y1 - y0)) / A, f, m)
    dzdy = rq(((z[2] - z[0]) * (x1 - x0) - (z[1] - z[0]) * (x2 - x0)) / A, f, m)
    r = {'v0': 0, 'left': lefti(P)}[ref]
    return [z[r] + dzdx * (Fr(2 * x + 1, 2) - P[r][0]) + dzdy * (Fr(2 * y + 1, 2) - P[r][1]) for x, y in pix]
def families():
    F = {('exact', 't16'): lambda p, z, x: fam_exact(p, z, x, 't16'),
         ('exact', 'exact'): lambda p, z, x: fam_exact(p, z, x, 'exact')}
    for k in (8, 10, 12, 14, 16, 20, 24):
        for m in ('up', 'even'):
            F[('wq', k, m)] = lambda p, z, x, k=k, m=m: fam_wq(p, z, x, k, m)
    for ref in ('v0', 'left', 'top'):
        F[('f32', ref)] = lambda p, z, x, ref=ref: fam_f32(p, z, x, ref)
    for f in (16, 20, 24, 28, 32):
        for m in ('floor', 'up'):
            for ref in ('v0', 'left'):
                F[('fx', f, m, ref)] = lambda p, z, x, f=f, m=m, ref=ref: fam_fx(p, z, x, f, m, ref)
    return F
def conv(v, bits, c):
    top = (1 << bits) - 1
    s = v * (top if c[0] == 'm1' else (1 << bits))
    k = math.floor(s) if c[1] == 'floor' else math.floor(s + Fr(1, 2))
    return max(0, min(top, k))
CONVS = [('m1', 'floor'), ('m1', 'up'), ('p2', 'floor'), ('p2', 'up')]
