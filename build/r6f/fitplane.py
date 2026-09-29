# from the observed plane alone: the feasible (c, gx, gy) with obs <= c + gx*sx + gy*sy < obs+1
import pickle, sys, math
from fractions import Fraction as Fr
import numpy as np
from scipy.optimize import linprog
sys.path.insert(0,'tools/r6'); import depth_oracle as do
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl','rb')); go=do.go
def exact_grad(name):
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); S=1<<do.fmt_bits(name)
    Z=[Fr(v)*S for v in zs]
    gx=((Z[1]-Z[0])*(y2-y0)-(Z[2]-Z[0])*(y1-y0))/A
    gy=((Z[2]-Z[0])*(x1-x0)-(Z[1]-Z[0])*(x2-x0))/A
    c = Z[0] - gx*x0 - gy*y0
    return float(c), float(gx), float(gy), P, sorted(go.covered(pts))
for name in ['I1_24','I3_24','I4_24','I6_24','I7_24']:
    c0, gx0, gy0, P, pix = exact_grad(name)
    A_ub, b_ub = [], []
    for x, y in pix:
        sx, sy = x + 0.5, y + 0.5
        v = obs[name][(x, y)]
        A_ub.append([-1.0, -sx, -sy]); b_ub.append(-v)            # c + gx sx + gy sy >= v
        A_ub.append([1.0, sx, sy]);    b_ub.append(v + 1 - 1e-9)  # < v+1
    bounds = [(c0 - 50, c0 + 50), (gx0 - 5, gx0 + 5), (gy0 - 5, gy0 + 5)]
    out = {}
    for k, name_k in ((1, 'gx'), (2, 'gy')):
        for sign, lab in ((1, 'min'), (-1, 'max')):
            cvec = [0.0, 0.0, 0.0]; cvec[k] = sign
            r = linprog(cvec, A_ub=np.array(A_ub), b_ub=np.array(b_ub), bounds=bounds, method='highs')
            out[(name_k, lab)] = r.x[k] if r.success else None
    print('%-7s exact gx %.5f  feasible [%.5f, %.5f]' % (name, gx0, out[('gx','min')], out[('gx','max')]))
    print('        exact gy %.5f  feasible [%.5f, %.5f]' % (gy0, out[('gy','min')], out[('gy','max')]))
