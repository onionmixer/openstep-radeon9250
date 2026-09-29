"""R6i: is the gap between the exact fraction and the observed weight a PLANE in (x, y)?
(i.e. the setup's gradient rounding, as R6f left open for depth)"""
import pickle, sys, math
import numpy as np
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i/observed_ff78c18a.pkl','rb'))
for case in ('LD','LF','LA','LC'):
    w,h,_,pat=pe.tex_of(case); st,tt=pe.st_of(case)
    s=pe.coord(case,st,'A',Fr(0)); t=pe.coord(case,tt,'A',Fr(0))
    X=[];Y=[];D=[];DV=[]
    for p,v in obs[case].items():
        u=s[p]*w-Fr(1,2); vv=t[p]*h-Fr(1,2)
        i,j=math.floor(u),math.floor(vv); fu,fv=float(u-i),float(vv-j)
        R=(v>>16)&0xff; G=(v>>8)&0xff
        if pat==2:
            wu = R/255.0; wv = G/255.0
            fu_obs = wu if i%2==0 else 1-wu
            fv_obs = wv if j%2==0 else 1-wv
        else:                                   # pat 1: R = w10+w11 = fu, G = w01+w11 = fv
            fu_obs = R/255.0 if i%2==0 else 1-R/255.0
            fv_obs = G/255.0 if j%2==0 else 1-G/255.0
        X.append(p[0]); Y.append(p[1]); D.append(fu_obs-fu); DV.append(fv_obs-fv)
    A=np.stack([np.ones(len(X)), np.array(X,float), np.array(Y,float)],1)
    for lab,d in (('u',np.array(D)), ('v',np.array(DV))):
        c,res,_,_=np.linalg.lstsq(A,d,rcond=None)
        r=d-A.dot(c)
        print('%s %s: plane fit  const %+.5f  dx %+.6f  dy %+.6f   residual max %.4f rms %.4f  (texels)' %
              (case, lab, c[0], c[1], c[2], abs(r).max(), r.std()))
