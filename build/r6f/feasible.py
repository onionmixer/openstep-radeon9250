# the feasible affine plane (c, gx, gy) for every interpolation case, from the observed planes alone
import pickle, sys, json
import numpy as np
from fractions import Fraction as Fr
from scipy.optimize import linprog
sys.path.insert(0,'tools/r6'); import depth_oracle as do
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl','rb')); go=do.go
out = {}
for name in [n + b for n in do.IORDER for b in ('_24','_16')]:
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); S=1<<do.fmt_bits(name)
    Z=[Fr(v)*S for v in zs]
    gx=((Z[1]-Z[0])*(y2-y0)-(Z[2]-Z[0])*(y1-y0))/A
    gy=((Z[2]-Z[0])*(x1-x0)-(Z[1]-Z[0])*(x2-x0))/A
    c=Z[0]-gx*x0-gy*y0
    pix=sorted(go.covered(pts)); Au=[]; bu=[]
    for x,y in pix:
        sx,sy=x+0.5,y+0.5; v=obs[name][(x,y)]
        Au.append([-1.0,-sx,-sy]); bu.append(-float(v))
        Au.append([1.0,sx,sy]);    bu.append(float(v)+1-1e-9)
    bnds=[(float(c)-100,float(c)+100),(float(gx)-10,float(gx)+10),(float(gy)-10,float(gy)+10)]
    r={}
    for k,lab in ((0,'c'),(1,'gx'),(2,'gy')):
        for s,t in ((1,'min'),(-1,'max')):
            cv=[0.0,0.0,0.0]; cv[k]=s
            z=linprog(cv,A_ub=np.array(Au),b_ub=np.array(bu),bounds=bnds,method='highs')
            r['%s_%s'%(lab,t)]=z.x[k] if z.success else None
    r['exact']={'c':float(c),'gx':float(gx),'gy':float(gy)}
    r['exact_in'] = bool(r['gx_min'] is not None and r['gx_min']-1e-6 <= float(gx) <= r['gx_max']+1e-6
                     and r['gy_min']-1e-6 <= float(gy) <= r['gy_max']+1e-6)
    r['pixels']=len(pix)
    out[name]=r
    print('%-7s pixels %4d  gx exact %14.5f feasible [%14.5f, %14.5f] %s' % (
        name, len(pix), float(gx), r['gx_min'], r['gx_max'], 'exact inside' if r['exact_in'] else 'exact OUTSIDE'))
json.dump(out, open('build/r6f/feasible.json','w'), indent=1)
